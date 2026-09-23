"""面试接口：开始 / 列表 / 详情 / 提交答案 / 结束

核心流程（状态机 idle → in_progress → finished）：
1. 开始面试：创建会话 → 生成开场题（第 1 轮）
2. 提交答案：保存答案 → 未达上限则生成追问（下一轮）→ 达上限自动结束并出报告
3. 结束面试：手动结束 → 生成评估报告（终态）

两条链路，由 `interviews.engine` 标记，**开场时定死、整场只读**：

- 原链路（engine = ''）：题库策略出题 + P3 评估，7 轮制；
- 引擎链路（engine = 'a11'）：出题/追问/评分全部委托 AI 对话层（8005），
  本模块只做镜像落库。题数由引擎决定（10 题），追问不推进题号。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.adapters import get_dialogue_adapter, get_evaluator_adapter, get_interviewer_adapter
from app.adapters.ai_dialogue import EngineError
from app.api.deps import CurrentUser, DbSession, get_owned_interview, validate_position
from app.config import settings
from app.core.engine_report import build_engine_meta, build_engine_report
from app.core.exceptions import BadRequestError, ConflictError, ServiceUnavailableError
from app.core.state_machine import InterviewStatus, StateMachine
from app.models import Interview, QARecord, Report
from app.schemas.interview import (
    AnswerRequest,
    FinishInterviewOut,
    InterviewDetailOut,
    InterviewListItemOut,
    InterviewOut,
    NextQuestionOut,
    QAOut,
    StartInterviewOut,
    StartInterviewRequest,
)
from app.schemas.report import report_out
from app.utils.response import ok

logger = logging.getLogger(__name__)
router = APIRouter()

# 引擎链路标记（interviews.engine 的取值）；空串 = 原链路
ENGINE_A11 = "a11"


def _engine_http_error(exc: EngineError) -> ServiceUnavailableError:
    """引擎异常 → 对外错误。

    引擎模式下失败就明确报错，**不静默回落原链路**：半场之后悄悄换一套口径
    出分，是最难查的一类问题。要回原链路，显式把 DIALOGUE_ENGINE 置空。
    """
    return ServiceUnavailableError(f"AI 对话层不可用：{exc}")


async def _require_engine_ready() -> None:
    """建会话前的就绪门禁：先探测再建，别留下一个跑不动的 in_progress 会话"""
    adapter = get_dialogue_adapter()
    if await adapter.is_ready():
        return
    raise ServiceUnavailableError(
        f"AI 对话层未就绪（{await adapter.unavailable_reason()}）。"
        "请稍后重试，或在 backend/.env 把 DIALOGUE_ENGINE 置空以走原链路。"
    )


async def _start_engine_interview(interview: Interview) -> str:
    """引擎链路开场：建会话 + 取第一题，返回题面。

    失败抛 503：此时考生还没答过任何东西，整场建不起来是干净的。
    """
    adapter = get_dialogue_adapter()
    try:
        session = await adapter.start(interview.position)
        session_id = str(session.get("session_id") or "")
        if not session_id:
            raise EngineError("建会话未返回 session_id")
        first = await adapter.next_question(session_id)
    except EngineError as exc:
        raise _engine_http_error(exc) from exc
    if first.get("finished") or not first.get("question"):
        raise ServiceUnavailableError("AI 对话层的题库没有可用题目")
    interview.engine = ENGINE_A11
    interview.engine_session_id = session_id
    return str(first["question"])


async def _evaluate_via_engine(interview: Interview, qa_list: list[dict]) -> tuple[dict, dict]:
    """引擎链路出报告：调 /finish，再换算成本项目 reports 口径

    返回 (报告数据, 引擎明细)——明细只进 reports.engine_meta，不进考生可见文案。
    """
    try:
        payload = await get_dialogue_adapter().finish(interview.engine_session_id or "")
    except EngineError as exc:
        raise _engine_http_error(exc) from exc
    return build_engine_report(interview.position, qa_list, payload), build_engine_meta(payload)


async def _advance_engine(db: DbSession, interview: Interview, current_qa: QARecord) -> dict:
    """引擎链路：把这次作答交给 /chat，再按它的指令决定下一步。

    引擎的「一次作答」与「一道题」不是一回事：一次作答可能触发追问（题号不推进），
    也可能收尾（去取下一题）。追问原文只记进 engine_turns，qa_records.question
    始终保持题库原题面——学习计划与评分素材注入都靠按题干反查题库。
    """
    adapter = get_dialogue_adapter()
    try:
        result = await adapter.answer(interview.engine_session_id or "", current_qa.answer or "")
    except EngineError as exc:
        raise _engine_http_error(exc) from exc

    current_qa.engine_turns = list(current_qa.engine_turns or []) + [
        {
            "reply": result["reply"],
            "action": result.get("action"),
            "follow_up": result["follow_up"],
            "swapped": result.get("swapped"),
        }
    ]

    if result.get("swapped"):
        # 整轮作废（引擎口径：不占题号、不进评分、不进走势）。镜像落库同步作废
        # 这一行；新题复用同一题号——引擎换题后 q_index 同样复用，行号因此不冲突。
        # 注意判据是 swapped 而不是 action：本场名额用尽时引擎仍会说 swap，
        # 但那一轮照常评分（真跑实测 15 次 judge_swap 里只有 4 次真换掉）。
        await db.delete(current_qa)
        await db.flush()

    if result["follow_up"]:
        # 同一题继续追问：题号不推进，面试官这句话就是前端要展示的下一条
        await db.commit()
        await db.refresh(interview)
        return ok(
            NextQuestionOut(
                finished=False,
                interview=InterviewOut.model_validate(interview),
                next_question=result["reply"],
                report=None,
            ).model_dump()
        )

    try:
        nxt = await adapter.next_question(interview.engine_session_id or "")
    except EngineError as exc:
        raise _engine_http_error(exc) from exc

    if nxt.get("finished"):
        report = await _finish_interview(db, interview)
        await db.refresh(interview)
        return ok(
            NextQuestionOut(
                finished=True,
                interview=InterviewOut.model_validate(interview),
                next_question=None,
                report=report_out(report, interview),
            ).model_dump(),
            "面试已完成",
        )

    question = str(nxt.get("question") or "")
    round_no = int(nxt.get("q_index") or (interview.current_round + 1))
    interview.current_round = round_no
    db.add(QARecord(interview_id=interview.id, round=round_no, question=question))
    await db.commit()
    await db.refresh(interview)
    return ok(
        NextQuestionOut(
            finished=False,
            interview=InterviewOut.model_validate(interview),
            next_question=question,
            report=None,
        ).model_dump()
    )


def _build_history(qa_records: list[QARecord]) -> list[dict]:
    """把问答记录转换为 P2 需要的对话历史格式"""
    history: list[dict] = []
    for qa in sorted(qa_records, key=lambda r: r.round):
        history.append({"role": "interviewer", "content": qa.question})
        if qa.answer is not None:
            history.append({"role": "candidate", "content": qa.answer})
    return history


async def _finish_interview(db: DbSession, interview: Interview) -> Report:
    """结束面试：状态转换 + 生成报告 + 持久化

    两条链路的报告来源不同（原链路走 P3 适配器、引擎链路走对话层 /finish），
    但落库形状相同——成长曲线、报告页、分享都不需要知道分数从哪来。
    """
    StateMachine.transition(interview, InterviewStatus.FINISHED)
    interview.finished_at = datetime.now()

    # 只把有回答的记录交给评估方
    answered = [qa for qa in interview.qa_records if (qa.answer or "").strip()]
    if not answered:
        raise BadRequestError("没有任何有效回答，无法生成报告")

    qa_list = [
        {"round": qa.round, "question": qa.question, "answer": qa.answer, "audio_url": qa.audio_url}
        for qa in answered
    ]
    engine_meta: dict | None = None
    if interview.engine == ENGINE_A11:
        data, engine_meta = await _evaluate_via_engine(interview, qa_list)
    else:
        # 5 维契约由评估适配器归一化（缺失字段在适配器层补齐），这里直接消费
        data = await get_evaluator_adapter().evaluate(interview.position, qa_list)

    report = Report(
        interview_id=interview.id,
        total_score=float(data["total_score"]),
        tech_score=float(data["tech_score"]),
        logic_score=float(data["logic_score"]),
        expression_score=float(data["expression_score"]),
        adaptability_score=float(data["adaptability_score"]),
        match_score=float(data["match_score"]),
        summary=str(data.get("summary") or ""),
        strengths=list(data.get("strengths") or []),
        weaknesses=list(data.get("weaknesses") or []),
        suggestions=list(data.get("suggestions") or []),
        engine_meta=engine_meta,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.post("", response_model=dict, summary="开始一场模拟面试")
async def start_interview(req: StartInterviewRequest, user: CurrentUser, db: DbSession) -> dict:
    await validate_position(db, req.position)

    # 同一用户同时只能有一场进行中的面试
    ongoing = await db.scalar(
        select(Interview).where(
            Interview.user_id == user.id,
            Interview.status == InterviewStatus.IN_PROGRESS.value,
        )
    )
    if ongoing is not None:
        raise ConflictError("你有一场进行中的面试，请先完成或结束它")

    if settings.engine_enabled:
        # 就绪门禁放在建会话之前：否则会留下一个 in_progress 却跑不动的空会话
        await _require_engine_ready()

    interview = Interview(user_id=user.id, position=req.position, status=InterviewStatus.IDLE.value)
    db.add(interview)
    await db.flush()  # 拿到 interview.id 供 Mock 选题使用

    StateMachine.transition(interview, InterviewStatus.IN_PROGRESS)
    interview.started_at = datetime.now()
    interview.current_round = 1

    if settings.engine_enabled:
        # 引擎链路：链路标记与引擎会话 ID 在这里写入，整场不再改变
        question = await _start_engine_interview(interview)
    else:
        question = await get_interviewer_adapter().generate_question(
            position=req.position,
            round_no=1,
            history=[],
            interview_id=interview.id,
            is_follow_up=False,
        )
    db.add(QARecord(interview_id=interview.id, round=1, question=question))
    await db.commit()
    await db.refresh(interview)

    return ok(
        StartInterviewOut(
            interview=InterviewOut.model_validate(interview), question=question
        ).model_dump(),
        "面试已开始",
    )


@router.get("", response_model=dict, summary="我的面试历史列表（按时间倒序，附综合得分）")
async def list_interviews(
    user: CurrentUser,
    db: DbSession,
    position: str | None = Query(default=None, description="按岗位筛选（不传=全部岗位）"),
) -> dict:
    conditions = [Interview.user_id == user.id]
    if position:
        # 岗位是动态集合（positions 表），非法值不报错、返回空列表即可
        conditions.append(Interview.position == position)

    # 左连报告表：已结束的面试附带 total_score，进行中/未出报告的为 null
    result = await db.execute(
        select(Interview, Report.total_score)
        .outerjoin(Report, Report.interview_id == Interview.id)
        .where(*conditions)
        .order_by(Interview.created_at.desc())
    )
    items = []
    for interview, total_score in result.all():
        item = InterviewListItemOut.model_validate(interview)
        item.total_score = total_score
        items.append(item)
    return ok([i.model_dump() for i in items])


@router.get("/{interview_id}", response_model=dict, summary="面试详情（含全部问答）")
async def get_interview(interview_id: int, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    detail = InterviewDetailOut.model_validate(interview)
    return ok(detail.model_dump())


@router.post("/{interview_id}/answers", response_model=dict, summary="提交答案并获取下一题")
async def submit_answer(interview_id: int, req: AnswerRequest, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    StateMachine.require(interview, InterviewStatus.IN_PROGRESS)

    # 定位当前轮次的问答记录并写入答案
    current_qa = next(
        (qa for qa in interview.qa_records if qa.round == interview.current_round), None
    )
    if current_qa is None:
        logger.error("面试 %s 第 %s 轮问答记录缺失", interview.id, interview.current_round)
        raise ConflictError("面试数据异常，请重新开始一场面试")
    current_qa.answer = req.answer
    current_qa.audio_url = req.audio_url

    if interview.engine == ENGINE_A11:
        # 引擎链路：下一步由对话层的 done 决定（追问 / 下一题 / 收尾）
        return await _advance_engine(db, interview, current_qa)

    # ---- 以下为原链路（题库策略 + P3），逻辑未变 ----

    # 已答完最后一轮 → 自动结束并生成报告
    if interview.current_round >= settings.total_rounds:
        report = await _finish_interview(db, interview)
        await db.refresh(interview)
        return ok(
            NextQuestionOut(
                finished=True,
                interview=InterviewOut.model_validate(interview),
                next_question=None,
                report=report_out(report, interview),
            ).model_dump(),
            "面试已完成",
        )

    # 生成下一轮追问
    interview.current_round += 1
    next_question = await get_interviewer_adapter().generate_question(
        position=interview.position,
        round_no=interview.current_round,
        history=_build_history(interview.qa_records),
        interview_id=interview.id,
        is_follow_up=True,
    )
    db.add(QARecord(interview_id=interview.id, round=interview.current_round, question=next_question))
    await db.commit()
    await db.refresh(interview)

    return ok(
        NextQuestionOut(
            finished=False,
            interview=InterviewOut.model_validate(interview),
            next_question=next_question,
            report=None,
        ).model_dump()
    )


@router.post("/{interview_id}/finish", response_model=dict, summary="主动结束面试并生成报告")
async def finish_interview(interview_id: int, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    StateMachine.require(interview, InterviewStatus.IN_PROGRESS)

    report = await _finish_interview(db, interview)
    await db.refresh(interview)
    return ok(
        FinishInterviewOut(
            interview=InterviewOut.model_validate(interview),
            report=report_out(report, interview),
        ).model_dump(),
        "面试已结束",
    )
