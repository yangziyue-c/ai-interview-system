"""面试接口：开始 / 列表 / 详情 / 提交答案 / 结束

核心流程（状态机 idle → in_progress → finished）：
1. 开始面试：创建会话 → 生成开场题（第 1 轮）
2. 提交答案：保存答案 → 未达上限则生成追问（下一轮）→ 达上限自动结束并出报告
3. 结束面试：手动结束 → 生成评估报告（终态）
"""
import logging
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.adapters import get_evaluator_adapter, get_interviewer_adapter
from app.api.deps import CurrentUser, DbSession, get_owned_interview
from app.config import settings
from app.core.exceptions import BadRequestError, ConflictError
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
from app.schemas.report import ReportOut
from app.utils.response import ok

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_history(qa_records: list[QARecord]) -> list[dict]:
    """把问答记录转换为 P2 需要的对话历史格式"""
    history: list[dict] = []
    for qa in sorted(qa_records, key=lambda r: r.round):
        history.append({"role": "interviewer", "content": qa.question})
        if qa.answer is not None:
            history.append({"role": "candidate", "content": qa.answer})
    return history


async def _finish_interview(db: DbSession, interview: Interview) -> Report:
    """结束面试：状态转换 + 调用 P3 评估 + 持久化报告"""
    StateMachine.transition(interview, InterviewStatus.FINISHED)
    interview.finished_at = datetime.now()

    # 只把有回答的记录交给 P3
    answered = [qa for qa in interview.qa_records if (qa.answer or "").strip()]
    if not answered:
        raise BadRequestError("没有任何有效回答，无法生成报告")

    qa_list = [
        {"round": qa.round, "question": qa.question, "answer": qa.answer, "audio_url": qa.audio_url}
        for qa in answered
    ]
    data = await get_evaluator_adapter().evaluate(interview.position, qa_list)

    report = Report(
        interview_id=interview.id,
        total_score=float(data["total_score"]),
        tech_score=float(data["tech_score"]),
        logic_score=float(data["logic_score"]),
        expression_score=float(data["expression_score"]),
        match_score=float(data["match_score"]),
        summary=str(data.get("summary") or ""),
        strengths=list(data.get("strengths") or []),
        weaknesses=list(data.get("weaknesses") or []),
        suggestions=list(data.get("suggestions") or []),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.post("", response_model=dict, summary="开始一场模拟面试")
async def start_interview(req: StartInterviewRequest, user: CurrentUser, db: DbSession) -> dict:
    # 同一用户同时只能有一场进行中的面试
    ongoing = await db.scalar(
        select(Interview).where(
            Interview.user_id == user.id,
            Interview.status == InterviewStatus.IN_PROGRESS.value,
        )
    )
    if ongoing is not None:
        raise ConflictError("你有一场进行中的面试，请先完成或结束它")

    interview = Interview(user_id=user.id, position=req.position, status=InterviewStatus.IDLE.value)
    db.add(interview)
    await db.flush()  # 拿到 interview.id 供 Mock 选题使用

    StateMachine.transition(interview, InterviewStatus.IN_PROGRESS)
    interview.started_at = datetime.now()
    interview.current_round = 1

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
async def list_interviews(user: CurrentUser, db: DbSession) -> dict:
    # 左连报告表：已结束的面试附带 total_score，进行中/未出报告的为 null
    result = await db.execute(
        select(Interview, Report.total_score)
        .outerjoin(Report, Report.interview_id == Interview.id)
        .where(Interview.user_id == user.id)
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

    # 已答完最后一轮 → 自动结束并生成报告
    if interview.current_round >= settings.total_rounds:
        report = await _finish_interview(db, interview)
        await db.refresh(interview)
        return ok(
            NextQuestionOut(
                finished=True,
                interview=InterviewOut.model_validate(interview),
                next_question=None,
                report=ReportOut.model_validate(report),
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
            report=ReportOut.model_validate(report),
        ).model_dump(),
        "面试已结束",
    )
