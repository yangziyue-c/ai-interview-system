# -*- coding: utf-8 -*-
"""
interview.py · 接口层
============================================================
十个端点，全部同步实现（`def` 而不是 `async def`）—— 这是刻意的：

（第 8 个是 `/practice`，专项强化练习（赛题 4b）。它只负责「开课」——
  练习场次就是一个普通会话，之后的 /next、/chat、/finish 全是既有端点，
  **前端除了一个入口按钮不需要任何改动**。）

（第 9 个是 `/growth`，成长档案（错题本 / 考点地图 / 历史成绩 / 提升路径，赛题 4）。
  它是**唯一一个不碰会话、也没有状态**的端点：入参是一批「成绩单摘要」
  （`/finish` 与 `/result` 响应里那个顶层 `digest` 键），出参是四份聚合。
  零落盘、不查库、不认人 —— 身份与持久化都在 1 号 那边。见 app/core/growth.py。
  它是唯一一个会主动读题库（考点地图的骨架）的**只读**端点。）

（第 10 个是 `/model_answer`，考点讲解 / 优秀回答范例（赛题任务要求 4a）。
  它和 `/practice` 是一对：一个给材料、一个给练。**两道结构性的门** —— 源场次必须
  已 `/finish`、`kp_id` 必须出现在那一场的诊断里 —— 所以「面试途中查答案」做不到。
  见 app/core/answer.py。）

（`/asr` 是本轮新增的第 7 个，语音转写。它同样必须是同步的：转写是纯 CPU 活，
  写成 async 会把事件循环整个堵住，那时连 /health 都不响应。
  为了在同步函数里读上传文件，用的是 `file.file.read()` —— 见 /asr 的注释。）

reranker 评分是 CPU 密集的，要跑好几百毫秒。如果写成 async 端点，这段计算
会**阻塞事件循环**，整个服务在评分期间连 /health 都响应不了。写成同步端点，
FastAPI 会把它丢进线程池，一个会话评分时其它请求照常。

SSE 也一样：同步生成器由 Starlette 在线程池里迭代，不占事件循环。

副作用：会话对象会被多个线程同时访问（一个在 /chat 里算分，另一个在 /health
里读 stats）。所以会话存储和评分器都各自加了锁 —— 见 store.py / scoring.py。
"""
import json
import os
import time
from typing import Generator, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app import __version__, config
from app.core import answer as answermod
from app.core import asr as asrmod
from app.core import growth as growmod
from app.core import kb as kbmod
from app.core import kg as kgmod
from app.core import practice as pracmod
from app.core import question_bank as qb
from app.core import rag as ragmod
from app.core import resources as resmod
from app.core.llm import LLMError, get_llm, llm_configured
from app.core.prompts import PERSONA_STYLE_LABELS
from app.core.scoring import get_scorer
from app.core.session import (
    PHASE_DONE, PHASE_START, InterviewSession, SessionError, UnknownJob,
)
from app.core.store import STORE
from app.logging_conf import get_logger
from app.schemas import (
    AsrResp, ChatReq, FinishResp, GrowthReq, GrowthResp, HealthResp,
    ModelAnswerReq, ModelAnswerResp, NextResp,
    PracticeReq, PracticeResp, SessionReq, StartReq, StartResp,
)

logger = get_logger(__name__)
router = APIRouter()


# ============================================================
# 工具
# ============================================================
def _sse(obj: dict) -> str:
    """SSE 帧。ensure_ascii=False 是必须的 —— 否则中文会变成 \\uXXXX，白白三倍体积。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _get_session(session_id: str) -> InterviewSession:
    s = STORE.get(session_id)
    if s is None:
        raise HTTPException(404, detail={
            "code": "session_not_found",
            "err": f"会话不存在或已过期：{session_id}",
            "session_id": session_id,
        })
    return s


def _http_error(e: SessionError) -> HTTPException:
    return HTTPException(e.http_status, detail={
        "code": e.code, "err": str(e),
    })


# ------------------------------------------------------------
# `raw` 的默认档：脱敏
# ------------------------------------------------------------
# 开关与理由见 config.A11_RAW_DETAIL 那一段（一句话：raw 里就是得分点原文，
# 而拿它的门槛是零）。这里只说实现上的两条约束：
#
# ⚠️ 1) 必须造**浅拷贝**。传进来的 `env` 就是 `session._result` 本身，
#       就地改会把会话里那份也脱掉 —— 而 /practice 正是靠
#       `src.result()["raw"]["blindspots"]` 挑薄弱项、靠 `raw.rounds[]` 取已问题号。
#       脱了会话里那份，/practice 会跟着坏（smoke_test 里「源场次 raw 逐字节不变」
#       那条断言就是守这个的）。
# ⚠️ 2) 运行时读 config，不在 import 时冻结 —— 冒烟测试靠运行期翻这个值验两条路。
#
# 占位键只有 `note` 一个，与 `交付\gen_samples.py` 写 4 号包样例时的 RAW_STUB
# **同形**（`set(raw) == {"note"}`）。两处文案不完全逐字相同是有意的：包内那句
# 说「本包不含」，运行期说「本次响应按默认档换掉了、怎么打开」—— 后者对
# 3 号 更有用。`打包.py` 的闸① 与 `gen_docx_5号.py` 的 zip 自检都只认键集，不受影响。
_RAW_SCRUBBED = {
    "note": ("已脱敏：raw 是给 3 号（评估报告）的内部明细，含得分点与追问素材原文。"
             "本次响应按交付默认档（A11_RAW_DETAIL=0）把它换成了这个占位键；"
             "要全量明细，在服务端设 A11_RAW_DETAIL=1 后重启。"
             "前端不要读、不要显示 raw 的任何字段。")
}


def _with_raw_detail(env: dict) -> dict:
    """按 `A11_RAW_DETAIL` 决定返回全量 raw 还是脱敏占位（见上面两条约束）。"""
    if config.A11_RAW_DETAIL:
        return env
    out = dict(env)
    out["raw"] = dict(_RAW_SCRUBBED)
    return out


# ============================================================
# GET /health
# ============================================================
@router.get("/health", response_model=HealthResp, summary="健康检查")
def health():
    """
    永远返回 200（除非进程挂了）—— 依赖没就绪时用字段表达，不用状态码。
    这样任何监控/前端探活逻辑都不用去区分「服务活着但模型没加载完」。
    """
    try:
        scorer = get_scorer()
        device, ready = scorer.reranker.device, scorer.ready
    except Exception as e:                       # 评分器构造失败也要能探活
        logger.warning("health 读取评分器失败：%s", e)
        device, ready = "unknown", False

    try:
        model = getattr(get_llm(), "model", "")
    except LLMError:
        model = ""

    # KG / RAG 各自 try/except：这两个是纯增量旁路，它们的 status 读取
    # 绝不该让 /health 挂掉 —— 探活端点自己先挂是最糟的一种失败。
    extra: dict = {}
    try:
        extra.update(kgmod.kg_status())
    except Exception as e:
        logger.warning("health 读取知识图谱状态失败：%s", e)
        extra.update({"kg_enabled": config.A11_KG, "kg_ready": False,
                      "kg_error": f"{type(e).__name__}: {e}", "kg_nodes": 0})
    try:
        st = ragmod.rag_status()
        # rag_free_mb 是诊断用的瞬时值，不进契约
        extra.update({k: v for k, v in st.items() if k != "rag_free_mb"})
    except Exception as e:
        logger.warning("health 读取 RAG 状态失败：%s", e)
        extra.update({"rag_enabled": config.A11_RAG, "rag_ready": False,
                      "rag_error": f"{type(e).__name__}: {e}", "rag_model": ""})
    try:
        # ⚠️ 这里**不加载** ASR 模型（懒加载）—— 探活端点自己去加载一个 0.5GB 的
        #    模型，是最糟的一种探活。所以 ready=false 且 error="" 的含义是
        #    「还没人用过它」，不是「它坏了」；坏了的话 error 一定有内容。
        extra.update(asrmod.asr_status())
    except Exception as e:
        logger.warning("health 读取 ASR 状态失败：%s", e)
        extra.update({"asr_enabled": config.A11_ASR, "asr_ready": False,
                      "asr_error": f"{type(e).__name__}: {e}", "asr_model": ""})
    try:
        # 情感模型的四键三态（赛题 3b）。⚠️ 与 ASR 同一条：**不在这里加载权重**
        #    （那是 360 MB）。所以冷启动时 `emotion_ready=false` 而 `emotion_error=""`
        #    的意思是「**还没人用过它**」，**不是**「它坏了」—— 坏了的话 error 非空。
        #    这个区别是 1 号换机器后排查「为什么 `emotion` 一直是 null」的唯一线索。
        extra.update(asrmod.emotion_status())
    except Exception as e:
        logger.warning("health 读取情感模型状态失败：%s", e)
        extra.update({"emotion_enabled": config.A11_ASR_EMOTION,
                      "emotion_ready": False,
                      "emotion_error": f"{type(e).__name__}: {e}",
                      "emotion_model": ""})
    try:
        # 学习资源样例：读一份 JSON（进程内只读一次），探活顺带确认它在不在。
        # ⚠️ 别在这里形容它多大，更别写死字节数 —— 它是**会长**的：2026-09-25 把
        #    「优秀回答范例」从 50 条铺到**每题一条**，同一个文件从 174 KB 涨到 4.5 MB
        #    （顶层多了一张 `题目范文` 平索引）；同一天稍后重跑一次生成器又多了 176 B。
        #    所以「不到 200 KB」这种话写过一次就过期 —— **连精确字节数也一样会过期**。
        #    **权威字节数在包内 `数据\校验数据.py` 里**（那份会咬）。
        extra.update(resmod.resource_status())
    except Exception as e:
        logger.warning("health 读取学习资源状态失败：%s", e)
        extra.update({"resource_enabled": config.A11_RECOMMEND, "resource_ready": False,
                      "resource_error": f"{type(e).__name__}: {e}", "resource_kps": 0})
    try:
        # ⚠️ 与 ASR 同一条：这里**不加载**知识库索引与其编码器（懒加载）——
        #    探活端点去加载一个 2.3 GB 的模型是最糟的一种探活。所以
        #    kb_ready=false 且 kb_error="" 的含义是「还没人交过卷」。
        # kb_dir 是本机路径，与 rag_free_mb 同类：诊断值，不进契约。
        st = kbmod.kb_status()
        extra.update({k: v for k, v in st.items() if k != "kb_dir"})
    except Exception as e:
        logger.warning("health 读取知识库检索状态失败：%s", e)
        extra.update({"kb_enabled": config.A11_KB_REC, "kb_ready": False,
                      "kb_error": f"{type(e).__name__}: {e}", "kb_n": 0})

    # 专项强化练习（4b）：只有一个开关，没有「就绪」一说 —— 它不依赖任何外部
    # 数据（题库在 /start 时就加载了），所以**一键**而不是四键。运维看这里
    # 就能分辨 /practice 返 503 到底是「没开」还是「坏了」：坏了不会有 503。
    extra["practice_enabled"] = config.A11_PRACTICE

    # 复盘清单（给考生看的那一份）：同样只有一个键，同样不依赖外部数据 ——
    # 关掉时 `/finish` 与 `/result` 的 `review` 是 **null**（不是空对象）。
    extra["review_enabled"] = config.A11_REVIEW

    # 面试官风格三档（F）+ 考生自述进 prompt（E），2026-09-25。
    # ⚠️ 这两个必须上 /health，理由与 `A11_RAG` / `A11_REPEAT_GUARD` 那一族
    #    吃过的亏同一条：**不上就只能靠行为反推**，而这两条的「关掉」形态
    #    恰好都是「什么都没发生」（提示词里少一块，响应里看不出来）。
    #    `persona_styles` 是**唯一一个值不是布尔的**（与 rag_kb_query_src 同款破例）：
    #    调用方要照着它渲染选项，写错档名会 422，所以可选集必须能问出来。
    extra["persona_enabled"] = config.A11_PERSONA
    extra["persona_styles"] = sorted(PERSONA_STYLE_LABELS)
    extra["intro_enabled"] = config.A11_INTRO
    extra["intro_max_chars"] = config.INTRO_MAX_CHARS

    # `raw` 的暴露档位（同样只有一个键）。
    # ⚠️ 之所以要把它暴露出来：`A11_RAG` / `A11_REPEAT_GUARD` 这一族当初选了
    #    「不上 /health」,结果两轮 A/B 的臂定义**只能靠行为反推**。同一个坑不踩第二次。
    # 看到 false 就是「/finish、/result 的 raw 里没有得分点原文」这个安全默认还在。
    extra["raw_detail_enabled"] = config.A11_RAW_DETAIL

    # 面试期那条知识库通路（赛题 6.1)b + 6.2)b）—— 同样只有一个键。
    # ⚠️ 与 kb_enabled 是**两个开关**：`kb_enabled` 管 4a（交卷后的学习资源），
    #    这个是「面试期要不要把知识库片段当背景参考喂给面试官」。
    #    上 /health 的理由同上一条：A11_RAG / A11_REPEAT_GUARD 那一族的亏吃过一次
    #    —— 不上 /health 就**只能靠行为反推**，而这条通路的行为在
    #    A11_RAG=0（借不到编码器）时也是「什么都没发生」，两者分不开。
    extra["rag_kb_enabled"] = config.A11_RAG_KB

    # 2026-09-25 的三条「素材怎么被用」开关 —— 各一个**单键**，理由同上两条。
    # ⚠️ 为什么这次尤其必须上：同题两臂对照的 `old` 臂与 `new` 臂的差异**全在这三个键上**，
    #    不上 /health 的话，「这一场到底跑的是哪一档」又只能靠行为反推 ——
    #    而这三条里有两条（契约措辞、位置）**在产出指标上可能完全看不出差别**
    #    （那正是上一轮三臂的结论），反推根本推不出来。
    # ⚠️ 键名与 env 一一对应，别合并成一个「档位」数字：单键才能与
    #    `A11_RAG_TASK` / `A11_RAG_HEAD_ONLY` / `A11_RAG_KB_ASIDE` 逐个核对。
    extra["rag_task_enabled"] = config.RAG_TASK
    extra["rag_head_only_enabled"] = config.RAG_HEAD_ONLY
    extra["rag_kb_aside_enabled"] = config.RAG_KB_ASIDE

    # 面试期那条检索的**检索词从哪来**（2026-09-25 晚，`A11_RAG_KB_QUERY_SRC`）。
    # ⚠️ **这是本文件里唯一一个值不是布尔的键**，破例的理由正是它为什么必须暴露：
    #    默认是 `"answer"`（赛题 6.2)b 字面），只有 `"miss"` 算实验档 ⇒ env 写错
    #    （打错字、写成 `MISS`）会**静默退回默认档**，而布尔键在这种情形下会老老实实
    #    报 false —— 运维看到 false 只会以为「没开」，不会知道**自己以为开了**。
    #    回显**原值字符串**，一眼就能看出写的是 `MISS`；默认档下它顺带证明 env 没覆盖。
    # ⚠️ 为什么这条尤其必须上：两轮**同题两臂对照**唯一差异就是它，
    #    而它的两种取值在**检索到的材料**上可能高度重合（产出指标更看不出来）——
    #    这两条加起来等于「不上 /health 就永远验不出这一场跑的是哪一档」。
    extra["rag_kb_query_src"] = config.RAG_KB_QUERY_SRC

    # 成长档案（赛题 4）：同样只有一个开关 —— 它连题库与外部数据都不依赖
    # （摘要由调用方传进来），所以没有「就绪」一说。
    # ⚠️ 它与 KG/RAG 无关 ⇒ **不会**让冒烟那条「四组合（KG×RAG）增量必须相等」
    #    失效（那条断言正是为「开关间互相影响」设的哨）。
    # ⚠️ 这一位 false 时，`/finish` 与 `/result` 的 `digest` 是 **null**（不是 {}）。
    extra["growth_enabled"] = config.A11_GROWTH

    # 优秀回答范例 / 考点讲解（赛题任务要求 4a）：单键，与上面两条同族。
    # ⚠️ 它**还要**再叠一层上头的 `resource_*` 四键：本键答「这个端点开没开」，
    #    `resource_enabled` / `resource_ready` 答「材料源可用不可用」——
    #    两件事，所以 503 有两个码（`model_answer_disabled` / `resource_unavailable`）。
    #    运维看这里就能分辨 `/model_answer` 返 503 到底是哪一种，不必猜。
    extra["model_answer_enabled"] = config.A11_MODEL_ANSWER

    return HealthResp(
        status="ok",
        version=__version__,
        port=config.THIS_PORT,
        llm_mock=config.LLM_MOCK,
        reranker_mock=config.RERANKER_MOCK,
        llm_configured=llm_configured(),
        model=model,
        device=device,
        bank_loaded=bool(qb.bank_sizes()),
        bank_sizes=qb.bank_sizes(),
        scorer_ready=ready,
        **extra,
        **STORE.stats(),
    )


# ============================================================
# POST /asr（语音转写：音频进、文字出）
# ============================================================
def _asr_err(status: int, error: str, detail: str,
             retry_after: Optional[str] = None) -> JSONResponse:
    """
    错误响应。**形状与成功响应同族**（都有 ok / error / detail），且**永不 null**
    —— 4 号 的假服务与真服务必须同形，否则前端只在一边能跑。

    为什么不用 HTTPException：那样错误体会被包成 {"detail": {...}} 一层，
    而这里要的是设计稿里那个平铺的形状（多模态接入方案.md §四）。
    """
    headers = {"Retry-After": retry_after} if retry_after else None
    return JSONResponse(status_code=status,
                        content={"ok": False, "error": error, "detail": detail},
                        headers=headers)


@router.post("/asr", response_model=AsrResp, summary="语音转写（音频进、文字出）",
             responses={
                 413: {"description": "file_too_large / audio_too_long"},
                 415: {"description": "unsupported_format"},
                 503: {"description": "asr_unavailable / asr_loading（带 Retry-After）"},
             })
def asr_transcribe(file: UploadFile = File(..., description="音频文件，≤10MB / ≤60 秒"),
                   session_id: str = Form("", description="可选，仅用于日志串场"),
                   round_index: str = Form("", description="可选，仅用于日志串场")):
    """
    把一段音频转成文字 + 一组**只有数字**的时间戳。**它不碰会话状态**。

    前端拿到 `text` 之后仍然调**原来的** `POST /chat`（`message` = 这段文字），
    想把语速/停顿带进报告的话，再把这里的 `duration_ms` / `segments` /
    `audio_ms` / `asr_model` / **`pauses` / `pause_total_ms`** 原样放进
    `/chat` 的 `speech` 字段。

    ⚠️ `pauses` / `pause_total_ms` 是**在音频上量出来的**（VAD 人声块之间的
       真实静音），不是从 `segments` 的间隔推的 —— 后者永远数不出停顿（whisper
       的段首尾相接，静音被吞进段里，实测三处 5s/2.5s/6s 静音全数漏掉）。
       旧前端不带这两个键也能跑，那时停顿按段间隔兜底算（多数情况是 0）。

    为什么单独一个端点而不是塞进 `/chat`：塞进去会让「文字输入」这条已经验收过的
    通路跟着变成待验状态；拆开之后评分、追问、判档、换题、复读守卫**零改动复用**。

    隐私与留存（三条，都与 RAG 的「片段绝不进 raw」同一条原则）：
      · 音频只在内存与一个系统临时文件里存在，**转写完立刻删**；
      · 音频与转写原文都**不进 `raw`、不落 `logs/`**；转写文本只作为 `message`
        进会话，与考生手打的那句话没有区别；
      · `raw` 里只会多出一组数字（净时长 / 语速 / 长停顿 / 填充词），由
        `asr.derive_speech()` 从上面的时间戳算出来。

    错误码（都是 ok=false + error + detail，不是裸 500）：
        503 asr_unavailable  没开（A11_ASR=0）或模型加载失败（detail 给原因）
        503 asr_loading      首次调用正在加载模型，带 Retry-After，前端稍后重试
        413 file_too_large   文件 > A11_ASR_MAX_MB
        413 audio_too_long   净时长 > A11_ASR_MAX_SEC（**在转写之前**就判，不白跑）
        415 unsupported_format  扩展名不在白名单里
        400 empty_audio      一个字节都没传
        500 asr_failed       转写过程抛异常（detail 给异常原文）
    """
    engine = asrmod.get_asr()
    if engine is None:
        return _asr_err(503, "asr_unavailable",
                        "本机未启用语音识别（A11_ASR=0），请改用文字输入。")

    try:
        # ⚠️ 用 file.file.read() 而不是 await file.read()：本端点是**同步**的
        #    （理由见文件开头的说明），Starlette 的 UploadFile.read 是 async。
        #    .file 是底层 SpooledTemporaryFile，同步读是它的正当用法。
        data = file.file.read()
    except Exception as e:
        logger.exception("sid=%s /asr 读取上传内容失败", session_id)
        return _asr_err(500, "asr_failed", f"读取上传内容失败：{type(e).__name__}: {e}")

    if not data:
        return _asr_err(400, "empty_audio", "上传内容为空。")
    limit = config.A11_ASR_MAX_MB * 1024 * 1024
    if len(data) > limit:
        return _asr_err(413, "file_too_large",
                        f"文件 {len(data) / 1024 / 1024:.1f}MB > 上限 "
                        f"{config.A11_ASR_MAX_MB}MB。")
    if not asrmod.allowed_format(file.filename or ""):
        return _asr_err(415, "unsupported_format",
                        f"不支持的格式：{file.filename!r}；"
                        f"白名单：{list(config.ASR_FORMATS)}")

    # 懒加载：第一个请求起加载线程并等一会儿，等到了就直接转写（体验最好），
    # 等不到才回 503 + Retry-After（前端重试一次即可）—— 绝不无限期挂着。
    state = engine.ensure_loaded(config.A11_ASR_WAIT_SEC)
    if state == "loading":
        return _asr_err(503, "asr_loading",
                        f"语音模型正在加载（已等 {config.A11_ASR_WAIT_SEC:g} 秒），"
                        "请稍后重试。", retry_after="3")
    if state == "failed":
        return _asr_err(503, "asr_unavailable",
                        f"语音模型不可用：{engine.error}")

    path = None
    try:
        path = asrmod.save_temp(data, file.filename or "")
        r = engine.transcribe(path)
    except asrmod.AudioTooLong as e:
        return _asr_err(413, "audio_too_long", str(e))
    except Exception as e:
        logger.exception("sid=%s /asr 转写失败", session_id)
        return _asr_err(500, "asr_failed", f"{type(e).__name__}: {e}")
    finally:
        # 音频用完即弃 —— 这是全项目唯一一处把考生音频写到磁盘的地方，
        # 而且只存在于这一行的前后。删不掉也只是留下一个临时文件，不影响作答。
        if path:
            try:
                os.unlink(path)
            except OSError as e:
                logger.warning("sid=%s 临时音频删除失败 %s：%s", session_id, path, e)

    logger.info("sid=%s round=%s /asr 转写完成 字符=%d 净时长=%dms 耗时=%dms",
                session_id, round_index or "-", len(r["text"]),
                r["duration_ms"], r["elapsed_ms"])
    return AsrResp(ok=True, text=r["text"], duration_ms=r["duration_ms"],
                   audio_ms=r["audio_ms"], segments=r["segments"],
                   pauses=r.get("pauses"), pause_total_ms=r.get("pause_total_ms"),
                   asr_model=engine.tag, elapsed_ms=r["elapsed_ms"],
                   # 韵律 + 情感：`.get` 而非 `[]` —— 桩与真服务都给了这 6 个键，
                   # 但老版本引擎（热重载中途）可能没有，用 `.get` 让接口不至于 500。
                   loudness=r.get("loudness"), loudness_cv=r.get("loudness_cv"),
                   tail_ratio=r.get("tail_ratio"), emotion=r.get("emotion"),
                   emotion_score=r.get("emotion_score"),
                   emotion_dist=r.get("emotion_dist"))


# ============================================================
# POST /start
# ============================================================
@router.post("/start", response_model=StartResp, summary="开始一场面试")
def start(req: StartReq):
    if req.job not in config.JOBS:
        raise HTTPException(422, detail={
            "code": "unknown_job",
            "err": f"未知岗位：{req.job!r}；可选：{config.JOBS}",
        })

    # 面试官风格三档（F）。**不认识的档名报错，不静默回落** ——
    # 静默会让「我明明选了严厉」「我明明选了 relaxed」在响应里看不出来。
    # （session 内部那道回落是给**直连 session 的代码路径**留的保险，不是给 HTTP 留的。）
    style = req.persona_style
    if style is not None and style not in PERSONA_STYLE_LABELS:
        raise HTTPException(422, detail={
            "code": "bad_persona_style",
            "err": f"未知的面试官风格：{style!r}；可选：{sorted(PERSONA_STYLE_LABELS)}",
        })

    try:
        session = InterviewSession(job=req.job, intro=req.intro or "",
                                   persona_style=style)
    except LLMError as e:
        # 没配 API key：这是部署问题，不是客户端问题，502 更贴切
        logger.error("创建会话失败：%s", e)
        raise HTTPException(502, detail={"code": "llm_unavailable", "err": str(e)})

    STORE.add(session)
    return StartResp(
        session_id=session.session_id,
        job=session.job,
        state=session.phase,
        phase=session.phase,
        message=session.opening_message(),
        total_questions=config.TOTAL_QUESTIONS,
        weights=config.weights_text_for(session.job),
        persona_style=session.persona_style,
        persona_label=PERSONA_STYLE_LABELS.get(session.persona_style, "标准"),
        intro_read=session.intro_read(),
    )


# ============================================================
# POST /practice（专项强化练习：赛题 4b）
# ============================================================
@router.post("/practice", response_model=PracticeResp,
             summary="按薄弱项开一场专项强化练习",
             responses={404: {"description": "practice_target_not_found"},
                        409: {"description": "source_not_finished / no_weak_point / "
                                             "no_practice_questions"},
                        503: {"description": "practice_disabled（A11_PRACTICE=0）"}})
def practice(req: PracticeReq):
    """
    从一份**已交卷**的成绩单里挑一个薄弱项，开一场只练这个考点的练习。

    **这一段之后前端零改动**：练习场次就是一个普通会话 —— 照旧调
    `POST /next` 出题、`POST /chat` 答题（SSE 形状一模一样，追问、判档、
    换题字段都在）、`POST /finish` 收卷。唯一的区别是 `/finish` 的
    `raw.practice` 里多一块「练之前 vs 练之后」的对比。

    三条边界（都写死在实现里，不是约定）：
      · **不计入正式场次**：练习是另一个 session_id，源场次的任何字段都不改；
      · 练习场次的 `/next` 返回的 `total` 是本次练习的题数（3~5），不是 10；
      · 换题在练习里关着（`practice.PracticeSession._can_swap`）——
        换了就练不到目标考点了。

    错误码：404 practice_target_not_found（kp_id/domain 不在这一场的诊断里）
            409 source_not_finished（源场次还没 /finish，没有成绩单可依据）
            409 no_weak_point（这一场没有 hit=false 的考点：都答到了，或都判不了）
            409 no_practice_questions（题库里这个考点一道题都没有）
            503 practice_disabled（A11_PRACTICE=0）
    """
    if not config.A11_PRACTICE:
        raise HTTPException(503, detail={
            "code": "practice_disabled", "err": "本机未启用专项强化练习（A11_PRACTICE=0）。",
        })
    src = _get_session(req.session_id)
    res = src.result()
    if res is None:
        raise HTTPException(409, detail={
            "code": "source_not_finished",
            "err": "这场面试还没结束，没有成绩单可依据；请先 /finish。",
            "session_id": src.session_id,
        })
    raw = res.get("raw") or {}
    blindspots = raw.get("blindspots") or {}

    # 排除「他已经见过的题」：源场次出过的（asked_pids）+ 诊断里出现过的
    # （含被换掉的那些轮 —— 那些题他也看到了题面）。
    excl = set(src.asked_pids)
    for r in list(raw.get("rounds") or []) + list(raw.get("swapped_rounds") or []):
        qid = r.get("题目ID")
        if qid:
            excl.add(qid)

    try:
        sess = pracmod.build(job=src.job, source_sid=src.session_id,
                             blindspots=blindspots, exclude_ids=excl,
                             kp_id=req.kp_id, domain=req.domain,
                             count=req.count or None,
                             llm=src.llm, scorer=src.scorer)
    except SessionError as e:
        raise _http_error(e)

    STORE.add(sess)
    logger.info("sid=%s 专项练习开课 源=%s 考点=%s 题=%d",
                sess.session_id, src.session_id,
                (sess.target or {}).get("kp_id"), len(sess.pool))
    return PracticeResp(
        session_id=sess.session_id,
        job=sess.job,
        mode=sess.mode,
        phase=sess.phase,
        message=sess.opening_message(),
        total_questions=sess.total_questions,
        source_session_id=sess.source_sid,
        target=dict(sess.target or {}),
        why=sess.target_why,
        match=sess.hit_key,
        plan=list(sess.picked_ids) or [q.get(qb.F_ID, "") for q in sess.pool],
        reused_asked=sess.reused_asked,
    )


# ============================================================
# POST /growth（成长档案：错题本 / 考点地图 / 历史成绩，赛题 4）
# ============================================================
@router.post("/growth", response_model=GrowthResp,
             summary="成长档案：错题本 / 考点地图 / 历史成绩",
             responses={413: {"description": "digest_too_large（单份摘要超体积，"
                                             "通常是把 raw 当 digest 传了）"},
                        422: {"description": "bad_records / too_many_records / "
                                             "job_mismatch / unknown_job"},
                        503: {"description": "growth_disabled（A11_GROWTH=0）"}})
def growth(req: GrowthReq):
    """
    一批**成绩单摘要** → 三份聚合（错题本 / 考点地图 / 历史成绩）。

    入参就是 `/finish`（或 `/result`）响应里那个顶层 `digest` 键，**原样回传**即可，
    不用加工。**顺序无所谓**（服务端自己按 finished_at 排序）。

    ⚠️ 这个端点是**无状态**的：它不认人、不查库、不落盘，也不知道这些摘要属于谁。
    每一场面试交卷时，1 号 把 `digest` 存进自己的库；要展示成长档案时，从库里
    把该考生的若干份捞出来调这里。对话层这边**不留任何痕迹** —— 会话本来就只在
    内存里活 2~6 小时，跨场次的数据只能由调用方保管。

    错误码：422 bad_records（records 不是数组 / 整批一份都用不上 / 版本不认识）
            422 too_many_records（超过 A11_GROWTH_MAX_RECORDS 份，请分批）
            422 job_mismatch（某份摘要的岗位与入参 job 不一致，**不静默丢掉**）
            422 unknown_job（job 不在 config.JOBS 里）
            413 digest_too_large（单份摘要超体积）
            503 growth_disabled（A11_GROWTH=0）

    容错：**单份**坏掉（缺字段/字段类型不对）⇒ 进 `skipped[]` 并说明原因，其余照算，
    不返 5xx。但**整批都坏** ⇒ 422 —— 那两种情况必须分得开，否则「数据全坏了」
    会长得像「这个考生还没有历史」。
    """
    if not config.A11_GROWTH:
        raise HTTPException(503, detail={
            "code": "growth_disabled",
            "err": "本机未启用成长档案（A11_GROWTH=0）。",
        })
    if req.job not in config.JOBS:
        # 与 /start 同一条路：UnknownJob（422 unknown_job）
        raise _http_error(UnknownJob(
            f"未知岗位：{req.job!r}；可选：{config.JOBS}"))

    # KG 只用于把「考点地图」的骨架归到领域/子类。取不到就是 None（绝不抛），
    # 那时全部落「未归类」，并在响应里 kg_available=false 如实说明 ——
    # 「没开 KG」与「KG 坏了」靠 kg_error 区分（与 /health 同一套口径）。
    kg_st = kgmod.kg_status()
    # 资源侧同理：只给「提升路径」判断每个考点**有没有**材料用。**正文一个字都
    # 不从 /growth 出去**（它没有那道「会话已交卷」的门），正文只在 /model_answer。
    # 资源没开时**不去读那份文件**（load_index 是毫秒级，但没必要）。
    res_st = resmod.resource_status()
    idx = resmod.load_index() if res_st.get("resource_enabled") else None
    try:
        body = growmod.aggregate(req.job, req.records,
                                 kg=kgmod.get_kg(),
                                 kg_error=str(kg_st.get("kg_error") or ""),
                                 idx=idx, res_st=res_st)
    except SessionError as e:
        raise _http_error(e)

    logger.info("成长档案 job=%s 采用 %d 份，跳过 %d 份，错题 %d 条，路径 %d + %d 条",
                body["job"], body["record_count"], len(body["skipped"]),
                body["wrong_book"]["total"],
                body["plan"]["groups"][0]["count"], body["plan"]["groups"][1]["count"])
    return GrowthResp(ok=True, **body)


# ============================================================
# POST /model_answer（考点讲解 / 优秀回答范例：赛题任务要求 4a）
# ============================================================
@router.post("/model_answer", response_model=ModelAnswerResp,
             summary="取某个考点或某道题给考生的学习材料（考点讲解 / 优秀回答范例）",
             responses={404: {"description": "answer_target_not_found（这一场没考到它 / "
                                             "没出过这道题）/ "
                                             "no_material（考到了，但资源侧没有材料）"},
                        409: {"description": "source_not_finished（源场次还没 /finish）"},
                        422: {"description": "missing_target（kp_id 与 question_id 都没给）"},
                        503: {"description": "model_answer_disabled（A11_MODEL_ANSWER=0）/ "
                                             "resource_unavailable（A11_RECOMMEND=0 或"
                                             "资源文件加载失败）"}})
def model_answer(req: ModelAnswerReq):
    """
    考生按考点取「**考点讲解** + **优秀回答范例**」。这是赛题任务要求 4a
    「知识点讲解 / 优秀回答范例」对考生可见的唯一出口，也是 `/practice` 的搭档
    （一个给材料、一个给练）。

    ⚠️ 这是本波唯一一处**放宽**：这两样内容此前只在 `A11_RAW_DETAIL=1` 的
    `raw.blindspots.recommendations[]` 里，默认档对考生完全不可见。为什么敢放宽 ——
    下面两道门是**结构性**的，不是约定：

      · **源场次必须已 `/finish`**（409 `source_not_finished`）⇒ 面试途中查不到答案；
      · **`kp_id` 必须出现在那一场的诊断里 / `question_id` ∈ 那一场的 `asked_pids`**
        （404 `answer_target_not_found`）⇒ 没法枚举 kp_id / 题号把整份资源刷下来。

    ⚠️ 2026-09-25 加 `question_id` 入参：题库里有 **1,110 道题不挂任何考点**，
       走 kp_id 那条路它们**永远取不到**范文。加的是**覆盖率**，**不是权限** ——
       闸还是「他真的答过这道题」。两个入参都不给 ⇒ 422（不是 404）。

    ⛔ **只出两个内容键**：`talk`（考点讲解）+ `model_answer`（优秀回答范例）。
    `拉开差距`（进阶得分点原文）、`常见卡点`（面试官降级策略）、`missed_points`
    **一个字节都不出**；**也不给代表题的题面**（只给 `from_question_id`）——
    `_pick_sample` 可能挑中他没做过的那道，给题面等于泄露一份没考过的题。
    ⚠️ 另外两个非内容键 `kind` / `note`：`kind=示范作答` 表示「这段是按题库给的
       答题结构编的通用示例，不是真题范例」，`note` 是给考生的提醒。
       **前端必须展示 `note`** —— 不展示就等于把编的经历当范文给考生。

    错误码：404 answer_target_not_found（这一场没考到它 / 没出过这道题）
            404 no_material（考到了，但资源侧查不到可用材料）
            409 source_not_finished（源场次还没 /finish）
            422 missing_target（kp_id 与 question_id 都没给）
            503 model_answer_disabled（A11_MODEL_ANSWER=0）
            503 resource_unavailable（A11_RECOMMEND=0 或资源文件加载失败）

    ⚠️ 检查顺序是**先服务端状态、再这一场**：资源不可用时，任何 kp_id 都拿不到材料，
    先报 503 比先报 404 更接近真相。
    """
    if not config.A11_MODEL_ANSWER:
        raise HTTPException(503, detail={
            "code": "model_answer_disabled",
            "err": "本机未启用学习材料（A11_MODEL_ANSWER=0）。",
        })
    res_st = resmod.resource_status()
    if not res_st.get("resource_enabled") or not res_st.get("resource_ready"):
        # 「没开」与「坏了」在这里合成一个码但**信息不合并**：`resource_error` 空
        # 就是没开、非空就是坏了（与 /health 同一套口径，`resources.resource_status`
        # 那句注释写死了「ready=false 且 error 为空」只可能是没开）。
        raise HTTPException(503, detail={
            "code": "resource_unavailable",
            "err": ("本机未启用学习资源（A11_RECOMMEND=0），拿不到材料。"
                    if not res_st.get("resource_enabled") else
                    f"资源文件加载失败：{res_st.get('resource_error') or ''}"),
            "resource_enabled": bool(res_st.get("resource_enabled")),
            "resource_error": str(res_st.get("resource_error") or ""),
        })

    src = _get_session(req.session_id)
    if src.result() is None:
        raise HTTPException(409, detail={
            "code": "source_not_finished",
            "err": "这场面试还没结束，还没有诊断可依据；请先 /finish。"
                   "（这道门也是「面试途中查不到答案」的原因。）",
            "session_id": src.session_id,
        })

    # ⚠️ 两个入参**至少给一个**。两个都不给 ⇒ 422（不是 404）：这不是「找不到」，
    #    是「调用方没说清要什么」。放在最前面，免得后面两条路各自兜一次。
    kp_id = (req.kp_id or "").strip()
    question_id = (req.question_id or "").strip()
    if not kp_id and not question_id:
        raise HTTPException(422, detail={
            "code": "missing_target",
            "err": "`kp_id` 与 `question_id` 至少要给一个 —— 不说是哪个考点、"
                   "也不说是哪道题，就没法取材。",
        })

    try:
        block = (answermod.pick_by_question(src, question_id, idx=resmod.load_index())
                 if question_id and not kp_id
                 else answermod.pick(src, kp_id, idx=resmod.load_index()))
    except SessionError as e:
        raise _http_error(e)

    # ⚠️ 只打考点/题号与命中方式，**不打材料正文**（那是考生的学习材料，不该进日志）
    logger.info("sid=%s 取学习材料 考点=%s 题号=%s 命中=%s kind=%s",
                src.session_id, block.get("kp_id"), block.get("from_question_id"),
                block.get("src"), block.get("kind"))
    return ModelAnswerResp(ok=True, session_id=src.session_id, **block)


# ============================================================
# POST /next
# ============================================================
@router.post("/next", response_model=NextResp, summary="出下一题")
def next_question(req: SessionReq):
    session = _get_session(req.session_id)
    try:
        return NextResp(**session.ask_next_question())
    except SessionError as e:
        raise _http_error(e)


# ============================================================
# POST /chat（SSE）
# ============================================================
@router.post("/chat", summary="考生回答（SSE 流式）",
             response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "token* → done，异常时 error"}})
def chat(req: ChatReq):
    """
    事件序列：
        {"type":"question","data":{…}}   仅当考生在没出题时先说话了（兜底）
        {"type":"token","text":"…"}      0..n 次，面试官的话
        {"type":"done","follow_up":bool,"round_finished":bool,…}   必定最后一条
        {"type":"error","code":"…","err":"…"}                      出错时

    done 事件里的判档字段（本轮新增，全部是**只增不改**）：
        reranker_band  覆盖率换算出的档（L2/L1/degrade）
        judge_band     LLM 判出的档；**null = 没判出来**，不是"判成降级"
        judge_ok       LLM 是否成功给出了档位
        judge_why      LLM 给的一句话理由（仅排查用，不进面试官 prompt）；
                       脱敏档（A11_RAW_DETAIL=0，默认）下恒为空串 —— 见上面的取值处
        fuse_rule      最后听了谁：agree / llm_first / disagree_shallow /
                       deepest / judge_swap / reranker_only
        band_disagree  两个源是否不一致（供 3 号统计判档质量）

    换题字段（本轮新增，同属只增不改）：
        action        额外的取值 "swap" —— 这一轮**整轮作废**，考生答的那道题
                      不占 10 题名额、不进评分、不进走势。此时 follow_up=false，
                      前端照常调 /next 即可（**前端零改动**）。
        swapped       本次回调把上一轮换掉了吗（与 action=="swap" 同义，
                      恒存在，从没换过时是 false）
        swaps_used    本场已换题次数｜swaps_left 还剩几次（默认上限 1 次）
    """
    session = _get_session(req.session_id)
    sid = session.session_id

    def gen() -> Generator[str, None, None]:
        t0 = time.time()
        n_tok = 0
        try:
            # 兜底：没出题就先说话了 → 先出题，再把这句话当作这道题的回答
            if session.phase == PHASE_START or session.current_round is None:
                payload = session.ask_next_question()
                if payload.get("finished"):
                    yield _sse({"type": "done", "follow_up": False,
                                "round_finished": True, "finished": True,
                                "session_id": sid, "message": payload.get("message", ""),
                                "q_index": session.questions_asked})
                    return
                yield _sse({"type": "question", "data": payload})

            for ev in session.submit_answer(req.message, speech=req.speech):
                if ev.get("type") == "token":
                    n_tok += 1
                yield _sse(ev)

            st = session.round_status()
            yield _sse({
                "type": "done",
                # follow_up=true → 面试官在追问，前端继续等考生输入
                # follow_up=false → 本轮结束，前端调 /next 出下一题
                "follow_up": st["follow_up"],
                "round_finished": not st["follow_up"],
                "session_id": sid,
                "q_index": session.questions_asked,
                "action": st["action"],
                "follow_up_used": st["follow_ups_used"],
                "degrade_used": st["degrade_used"],
                "attempts": st["attempts"],
                "reranker_score": st["reranker_score"],
                # 评分失败时前端/3号要能看出来这轮的分不可信
                "reranker_ok": st["reranker_ok"],
                # 判档：两个判档源各判了什么、最后听了谁。**只是多给字段** ——
                # 上面那些原有字段一个没删、没改名，4 号的既有解析不受影响。
                # 这 6 个字段**必须在这里显式列出**：本函数是手搓 dict，不是把
                # round_status() 整个铺开，session 那边加了字段这里不会自动跟。
                "reranker_band": st["reranker_band"],
                # judge_band 为 null = LLM 没判出来（超时/非 JSON），
                # **不是**"判成了降级"；此时 fuse_rule 必为 reranker_only。
                "judge_band": st["judge_band"],
                "judge_ok": st["judge_ok"],
                # ⚠️ 脱敏档下置空串（键**保留**）。
                #    理由：判档那次 LLM 调用的 prompt 里就有 base_points/adv_points
                #    （scoring.py:304-305）,所以这句自由文本经常把得分点复述出来 ——
                #    它与 raw 是同一个泄漏面的第二条缝。键保留是为了 4 号 的既有解析
                #    不出现「字段整块消失」。
                "judge_why": (st["judge_why"] if config.A11_RAW_DETAIL else ""),
                "fuse_rule": st["fuse_rule"],
                "band_disagree": st["band_disagree"],
                # ---- 换题（加法）----
                # 同上：手搓 dict，session 那边加了键这里不写就传不出去。
                "swapped": st["swapped"],
                "swaps_used": st["swaps_used"],
                "swaps_left": st["swaps_left"],
                "phase": session.phase,
                "ms": int((time.time() - t0) * 1000),
            })
        except SessionError as e:
            logger.warning("sid=%s /chat 业务错误 code=%s：%s", sid, e.code, e)
            yield _sse({"type": "error", "code": e.code, "err": str(e)})
        except LLMError as e:
            logger.error("sid=%s /chat LLM 不可用：%s", sid, e)
            yield _sse({"type": "error", "code": "llm_unavailable",
                        "err": f"模型调用失败：{e}"})
        except Exception as e:
            # 这里必须兜住：SSE 一旦响应头发出去了就改不了状态码，
            # 异常直接抛出去会变成"连接中途断掉"，前端只看到空回复，没有线索。
            logger.exception("sid=%s /chat 未处理异常", sid)
            yield _sse({"type": "error", "code": "internal_error",
                        "err": f"{type(e).__name__}: {e}"})
        finally:
            logger.info("sid=%s /chat 结束 tokens=%d phase=%s 耗时=%.2fs",
                        sid, n_tok, session.phase, time.time() - t0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        # 关掉所有中间层缓冲，否则"流式"会变成"等全部生成完再一次性吐出"
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


# ============================================================
# POST /finish
# ============================================================
@router.post("/finish", response_model=FinishResp, summary="结束面试并出分")
def finish(req: SessionReq):
    """幂等：重复调用返回同一份结果（修 #6：会话不再被 pop 掉）。"""
    session = _get_session(req.session_id)
    if session.phase != PHASE_DONE and not session.rounds:
        raise HTTPException(409, detail={
            "code": "nothing_to_score",
            "err": "这场面试还没有任何问答，无法评分。",
        })
    try:
        result = session.finish()
    except Exception as e:
        logger.exception("sid=%s /finish 失败", session.session_id)
        raise HTTPException(500, detail={
            "code": "finish_failed", "err": f"{type(e).__name__}: {e}",
        })

    # 会话保留，只把 TTL 换长 —— /result/{sid} 因此可复查
    STORE.keep_result(session.session_id)
    # ⚠️ `result` 就是 `session._result` 本身，`_with_raw_detail` 返回**浅拷贝**，
    #    所以会话里那份全量 raw 原封不动（/practice 与 /result 复查都靠它）。
    return FinishResp(**_with_raw_detail(result))


# ============================================================
# GET /result/{session_id}
# ============================================================
@router.get("/result/{session_id}", response_model=FinishResp,
            summary="复查已结束的面试结果")
def result(session_id: str):
    session = _get_session(session_id)
    r = session.result()
    if r is None:
        # 还没结束：给个明确的 409，而不是让人以为"结果就是空的"
        raise HTTPException(409, detail={
            "code": "not_finished",
            "err": "这场面试还没结束，请先调用 /finish。",
            "session_id": session_id,
        })
    return FinishResp(**_with_raw_detail(r))
