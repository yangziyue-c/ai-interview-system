"""简历解析适配器：把上传的字节转成纯文本

**为什么单独一层**：将来接 OCR / 多模态大模型时，替换的就是本模块——那一跳必然是一次
外部服务调用（与 `ai_interviewer.py` 调 P2 服务同构），而 `app/core/resume_fields.py`
的字段抽取规则与文本来源无关，可以原样复用。图片分支现在就留在这个文件里。

**同步阻塞的代价**：pypdf 是同步库，而项目跑的是单进程 uvicorn。在 async 端点里直接调
`extract_text()` 会阻塞整个事件循环——一份畸形 PDF 能让所有请求（含正在进行的面试答题）
一起卡住。故统一走 `asyncio.to_thread` + `wait_for` 超时。

**超时的真相**：`wait_for` 只能让本次请求提前返回，**杀不掉那个线程**，它会继续跑到结束。
之所以安全，是因为该线程只读内存里的字节、不写任何东西；代价只是白烧一点 CPU。
另外 `to_thread` 用的是默认线程池（`min(32, cpu+4)`），并发上传多份大 PDF 会在池里排队。
"""
import asyncio
import io
import logging
from dataclasses import dataclass

from app.config import settings
from app.core.resume_fields import decide_status
from app.models.resume import (
    PARSE_STATUS_FAILED,
    PARSE_STATUS_GARBLED,
    PARSE_STATUS_IMAGE_PENDING,
    PARSE_STATUS_NO_TEXT_LAYER,
    PARSE_STATUS_PARSED,
)

logger = logging.getLogger(__name__)

# 单份 PDF 最多解析的页数：与 10MB 体积上限、15 秒超时一起，三层封住超大 PDF
_MAX_PAGES = 20
# 解析器标识，写进 resumes.parser。将来接 OCR 后可据此筛出「当年用文本层解析」的旧行重解析
PARSER_NAME = "pypdf"


@dataclass
class ParseResult:
    """解析结果：状态 + 文本 + 给用户看的一句话"""

    status: str
    text: str = ""
    message: str = ""
    parser: str = ""


async def parse_resume_file(content: bytes, ext: str) -> ParseResult:
    """解析简历字节 → 文本

    **任何失败都降级为带说明的状态，不抛异常**：文件已经安全落盘，解析不出来不是
    请求失败，用户仍可手动填写资料。与本项目「任一路径失败都不中断流程」一致。
    """
    if ext != ".pdf":
        # 图片：接受上传但本期不解析。不假装成功，给用户明确的下一步。
        return ParseResult(
            status=PARSE_STATUS_IMAGE_PENDING,
            message="图片已保存。当前版本不支持识别图片中的文字，请手动填写资料（后续版本支持）",
        )

    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_extract_pdf_text, content),
            timeout=settings.RESUME_PARSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("简历 PDF 解析超时（上限 %s 秒）", settings.RESUME_PARSE_TIMEOUT_SECONDS)
        return ParseResult(
            status=PARSE_STATUS_FAILED,
            message="PDF 解析超时，请手动填写资料",
            parser=PARSER_NAME,
        )
    except Exception as exc:  # noqa: BLE001 —— 失败种类多（损坏/加密/缺依赖），一律降级
        # 只记异常类型，**绝不记正文**——日志里出现简历内容等于泄露手机号
        logger.warning("简历 PDF 解析失败: %s", type(exc).__name__)
        return ParseResult(
            status=PARSE_STATUS_FAILED, message=_failure_message(exc), parser=PARSER_NAME
        )

    status = decide_status(text)
    return ParseResult(
        status=status, text=text, message=_status_message(status, text), parser=PARSER_NAME
    )


def _extract_pdf_text(content: bytes) -> str:
    """同步提取 PDF 文本（由 to_thread 调起，故内部允许阻塞）

    `import pypdf` 放在函数内部是刻意的：没装依赖的机器上服务照常启动、接口照常返回
    「解析失败 + 请联系管理员」，而不是启动崩溃或 500。
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("未安装 PDF 解析依赖") from exc

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise RuntimeError("PDF 已加密")

    # 不直接用切片：pages 的切片支持随 pypdf 版本而变，按下标取最稳
    page_count = min(len(reader.pages), _MAX_PAGES)
    texts = []
    for index in range(page_count):
        try:
            texts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001 —— 单页坏掉不该让整份解析失败
            logger.warning("简历 PDF 第 %s 页提取失败: %s", index + 1, type(exc).__name__)
    return "\n".join(texts).strip()


def _failure_message(exc: Exception) -> str:
    """把异常翻译成给用户的一句话。只匹配本模块自己抛的固定文案与 pypdf 的加密异常。"""
    text = str(exc)
    if "未安装" in text:
        return "服务端未安装 PDF 解析依赖，请联系管理员（当前可手动填写资料）"
    if "加密" in text:
        return "该 PDF 已加密，无法读取内容，请手动填写资料"
    return "PDF 解析失败，文件可能已损坏，请手动填写资料"


def _status_message(status: str, text: str) -> str:
    if status == PARSE_STATUS_NO_TEXT_LAYER:
        return "PDF 里没有可提取的文字（可能是扫描件或纯图片 PDF），请手动填写资料"
    if status == PARSE_STATUS_GARBLED:
        return "PDF 的文字编码无法识别，请手动填写资料"
    if status == PARSE_STATUS_PARSED:
        return f"已从 PDF 中提取 {len(text)} 字，请核对识别结果后保存"
    return "解析完成"
