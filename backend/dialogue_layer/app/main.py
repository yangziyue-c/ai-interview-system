# -*- coding: utf-8 -*-
"""
main.py · 服务入口
============================================================
职责：装配 FastAPI 应用、启动时预热（题库 + reranker）、统一错误体、挂静态页。

启动：python app/main.py    或    .\\run.ps1
"""
import os
import sys
import threading
import time
import uuid

# 允许 `python app/main.py` 直接跑：把项目根目录塞进 sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import __version__, config                      # noqa: E402
from app.logging_conf import get_logger, setup_logging   # noqa: E402

setup_logging()                                          # 尽早，之后的 import 都受它管
logger = get_logger(__name__)

from fastapi import FastAPI, Request                     # noqa: E402
from fastapi.exceptions import RequestValidationError    # noqa: E402
from fastapi.middleware.cors import CORSMiddleware       # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles              # noqa: E402
from starlette.datastructures import MutableHeaders      # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from app.api.interview import router                     # noqa: E402
from app.core import kg as kgmod                         # noqa: E402
from app.core import question_bank as qb                 # noqa: E402
from app.core import rag as ragmod                       # noqa: E402
from app.core.llm import LLMError, get_llm               # noqa: E402
from app.core.scoring import get_scorer                  # noqa: E402


# ============================================================
# 响应类：强制声明 charset=utf-8
# ============================================================
class UTF8JSONResponse(JSONResponse):
    """
    FastAPI 默认发 `application/json`（不带 charset）。按 RFC 8259 这已经
    隐含 UTF-8，浏览器和 requests/httpx 都能正确解码 —— 但 Windows
    PowerShell 5.1 的 Invoke-RestMethod 会退化成 Latin-1，中文全变乱码
    （"系统设计工程师" → "ç³»ç»è®¾è®¡å·¥ç¨å¸"）。

    我们这套东西是给 1/3/4 号在 Windows 上用 PowerShell 手测的，
    乱码会直接被当成后端的编码 bug 来报。加上 charset 就没事了。
    """
    media_type = "application/json; charset=utf-8"


# ============================================================
# 纯 ASGI 中间件：request_id + 访问日志
# ============================================================
class RequestContext:
    """
    刻意用手写 ASGI 中间件，而不是 @app.middleware("http")。

    后者底层是 Starlette 的 BaseHTTPMiddleware，它会用内存流接管响应体，
    对流式响应有已知的缓冲/分块问题 —— 用在 SSE 上可能把"逐字吐字"变成
    "攒完一次性吐"，而且这类 bug 只在真流式时出现，测试很难发现。
    这里只旁听 http.response.start、不改动任何 body 消息，SSE 原样透传。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:8]
        scope.setdefault("state", {})["request_id"] = rid
        status = 0
        t0 = time.time()

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", rid)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # 流式请求的耗时包含整段生成时间，所以数字看着大是正常的
            logger.info("req=%s %s %s → %s %dms", rid, scope.get("method"),
                        scope.get("path"), status, int((time.time() - t0) * 1000))


# ============================================================
# lifespan：预热
# ============================================================
def _warmup_kg():
    """
    第一段：知识图谱（便宜，约 0.3s、常驻 30-60MB，放最前面）。
    """
    try:
        t0 = time.time()
        idx = kgmod.get_kg()
        if idx is None:
            # get_kg() **从不抛**，返回 None 表示「关掉了」或「加载失败」。
            # 两者在日志里必须能分开 —— 与 kg_status() 同一条原则。
            st = kgmod.kg_status()
            if st["kg_enabled"]:
                logger.error("知识图谱不可用（%s）；出题不避重、无深挖方向、盲区全归「未归类」",
                             st["kg_error"])
            else:
                logger.info("知识图谱未启用（A11_KG=0）；出题不避重、无深挖方向")
        else:
            logger.info("知识图谱预热完成 %s 耗时 %.1fs", idx.stats(), time.time() - t0)
    except Exception:
        # get_kg() 本应永不抛，这里只是兜底：它挂了不该连带 skip 后面两段。
        logger.exception("知识图谱预热出现意外异常；继续预热评分器")


def _warmup_scorer():
    """第二段：reranker / 评分器。"""
    try:
        t0 = time.time()
        scorer = get_scorer()
        scorer.warmup()
        logger.info("评分器预热完成 ready=%s device=%s 耗时 %.1fs",
                    scorer.ready, scorer.reranker.device, time.time() - t0)
    except Exception:
        logger.exception("评分器预热失败；评分将回退默认分，服务继续可用")


def _warmup_rag():
    """
    第三段：RAG（最重，必须**排在 reranker 之后**）。

    ⚠️ 顺序是这个函数存在的理由：RagIndex.warmup() 第一步是内存预检，
    而 reranker 自己要占约 2.3GB。若 RAG 先跑，预检看到的是「reranker 还没加载」
    的假象，会放行，然后两边一起把内存吃爆 —— 那种 OOM 会**把已经加载好的
    reranker 一起带走**。所以：先让 reranker 落地，再让预检看到真实占用。
    """
    try:
        t0 = time.time()
        r = ragmod.get_rag()
        if r is None:
            logger.info("RAG 参考未启用（A11_RAG=0）；追问轮不带同岗位参考片段")
            return
        r.warmup()
        st = ragmod.rag_status()
        if st["rag_ready"]:
            logger.info("RAG 预热完成 model=%s 耗时 %.1fs", st["rag_model"],
                        time.time() - t0)
        else:
            logger.error("RAG 不可用（%s）；本轮起不带参考片段，面试照常",
                         st["rag_error"])
    except Exception:
        # RagIndex.warmup() 内部已经把一切异常吞掉并记进 rag_error，
        # 这里兜住的是它之外的东西（比如 get_rag() 自身）。
        logger.exception("RAG 预热出现意外异常；继续启动")


def _warmup_async():
    """
    在后台线程里按顺序预热三段（知识图谱 → 评分器 → RAG）。

    为什么不在 lifespan 里同步加载：模型加载要好几秒，同步加载期间服务
    根本没起来，健康检查会直接失败、前端首屏报错。后台加载则服务秒起，
    期间 /health 报 scorer_ready=false，第一题评分走默认分 —— 可接受。

    ⚠️ 为什么是**三个各自 try/except 的函数**而不是原样的一个 try 包住全部：
    原先 KG 与 RAG 若塞进同一个 try，**KG 加载失败会连带 skip 掉 reranker 预热**
    —— 一个 30MB 的旁路功能把主链路的评分器拖下水，服务看起来「起来了」但每一题
    都在走默认分，而且日志里只有一条 KG 的错。三段各自兜底，谁也不连累谁。
    """
    _warmup_kg()
    _warmup_scorer()
    _warmup_rag()


def _build_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("=" * 62)
        logger.info("A11 AI 面试官框架 · 2 号 AI 对话层  v%s", __version__)
        logger.info("端口 %d ｜ 岗位 %d 个 ｜ 每场 %d 题",
                    config.THIS_PORT, len(config.JOBS), config.TOTAL_QUESTIONS)
        logger.info("LLM_MOCK=%s  RERANKER_MOCK=%s  SCORER_DEVICE=%s",
                    config.LLM_MOCK, config.RERANKER_MOCK, config.SCORER_DEVICE)
        # 几个开关的默认值不一样（KG 默认开、RAG **代码默认关**但交付包模板设开、
        # 4a 知识库默认开），且都受内存约束，所以启动时必须打出来 ——
        # 不然「为什么没有参考片段」要靠翻代码猜。
        logger.info("A11_KG=%s  A11_RAG=%s  A11_KB_REC=%s",
                    config.A11_KG, config.A11_RAG, config.A11_KB_REC)
        logger.info("=" * 62)

        # 1) 题库
        if config.PRELOAD_BANK:
            sizes = qb.preload()
            logger.info("题库预加载完成：%s（共 %d 题）",
                        sizes, sum(sizes.values()))
        else:
            logger.info("PRELOAD_BANK=0，题库将在首次请求时加载")

        # 2) LLM
        try:
            get_llm()
            logger.info("LLM 就绪 model=%s", getattr(get_llm(), "model", "?"))
        except LLMError as e:
            # 不阻止启动：/health 会报 llm_configured=false，一眼能看出问题
            logger.error("LLM 未就绪，/chat 与 /finish 会失败：%s", e)

        # 3) 知识图谱 → reranker → RAG（后台，顺序有意义，见 _warmup_rag 的注释）
        threading.Thread(target=_warmup_async, name="warmup", daemon=True).start()

        yield

        logger.info("服务停止。%s", qb.bank_sizes())

    app = FastAPI(
        title="A11 AI 面试官框架",
        description="2 号 AI 对话层：出题 / 追问 / 五维评分。接口契约见 app/schemas.py。",
        version=__version__,
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )

    app.add_middleware(RequestContext)
    # 允许前端从任意来源调（测试页是 file:// 打开的，origin 是 null）
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Request-ID"])

    app.include_router(router, tags=["面试"])

    # ---------------- 统一错误体 ----------------
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        d = exc.detail
        if isinstance(d, dict) and "err" in d:
            body = {"session_id": None, **d}
        else:
            body = {"code": "http_error", "err": str(d), "session_id": None}
        body["request_id"] = getattr(request.state, "request_id", "")
        return UTF8JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val_exc(request: Request, exc: RequestValidationError):
        # 把 pydantic 的错误压成一行，方便前端直接展示
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return UTF8JSONResponse({
            "code": "validation_error",
            "err": f"请求参数不合法：{loc} {first.get('msg', '')}".strip(),
            "detail": exc.errors()[:5],
            "request_id": getattr(request.state, "request_id", ""),
        }, status_code=422)

    @app.exception_handler(Exception)
    async def _any_exc(request: Request, exc: Exception):
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return UTF8JSONResponse({
            "code": "internal_error",
            "err": f"{type(exc).__name__}: {exc}",
            "request_id": getattr(request.state, "request_id", ""),
        }, status_code=500)

    # ---------------- 静态测试页 ----------------
    web_dir = os.path.join(config.BASE_DIR, "web")
    if os.path.isdir(web_dir):
        app.mount("/ui", StaticFiles(directory=web_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def _root():
            return RedirectResponse("/ui/test_chat.html")

        @app.get("/test_chat.html", include_in_schema=False)
        def _legacy_page():
            # 老地址也留着，免得有人书签失效
            return RedirectResponse("/ui/test_chat.html")
    else:
        logger.warning("未找到静态目录 %s，测试页不可用", web_dir)

    return app


app = _build_app()


if __name__ == "__main__":
    import uvicorn

    logger.info("文档 http://127.0.0.1:%d/docs ｜ 测试页 http://127.0.0.1:%d/ui/test_chat.html",
                config.THIS_PORT, config.THIS_PORT)
    uvicorn.run(app, host=config.HOST, port=config.THIS_PORT,
                log_level=config.LOG_LEVEL.lower(), access_log=False)
