# -*- coding: utf-8 -*-
"""
interview.py · 接口层
============================================================
六个端点，全部同步实现（`def` 而不是 `async def`）—— 这是刻意的：

reranker 评分是 CPU 密集的，要跑好几百毫秒。如果写成 async 端点，这段计算
会**阻塞事件循环**，整个服务在评分期间连 /health 都响应不了。写成同步端点，
FastAPI 会把它丢进线程池，一个会话评分时其它请求照常。

SSE 也一样：同步生成器由 Starlette 在线程池里迭代，不占事件循环。

副作用：会话对象会被多个线程同时访问（一个在 /chat 里算分，另一个在 /health
里读 stats）。所以会话存储和评分器都各自加了锁 —— 见 store.py / scoring.py。
"""
import json
import time
from typing import Generator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import __version__, config
from app.core import kg as kgmod
from app.core import question_bank as qb
from app.core import rag as ragmod
from app.core.llm import LLMError, get_llm, llm_configured
from app.core.scoring import get_scorer
from app.core.session import (
    PHASE_DONE, PHASE_START, InterviewSession, SessionError,
)
from app.core.store import STORE
from app.logging_conf import get_logger
from app.schemas import (
    ChatReq, FinishResp, HealthResp, NextResp, SessionReq, StartReq, StartResp,
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
# POST /start
# ============================================================
@router.post("/start", response_model=StartResp, summary="开始一场面试")
def start(req: StartReq):
    if req.job not in config.JOBS:
        raise HTTPException(422, detail={
            "code": "unknown_job",
            "err": f"未知岗位：{req.job!r}；可选：{config.JOBS}",
        })

    try:
        session = InterviewSession(job=req.job, intro=req.intro or "")
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
    )


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
        judge_why      LLM 给的一句话理由（仅排查用，不进面试官 prompt）
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

            for ev in session.submit_answer(req.message):
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
                "judge_why": st["judge_why"],
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
    return FinishResp(**result)


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
    return FinishResp(**r)
