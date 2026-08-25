"""报告接口：查看单场报告 / 能力成长曲线"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_owned_interview
from app.core.exceptions import ConflictError
from app.core.state_machine import InterviewStatus
from app.models import Interview, Report
from app.schemas.report import GrowthPoint, ReportOut
from app.utils.response import ok

router = APIRouter()


@router.get("/growth", response_model=dict, summary="能力成长曲线（历史面试得分序列）")
async def get_growth(user: CurrentUser, db: DbSession) -> dict:
    result = await db.execute(
        select(Interview, Report)
        .join(Report, Report.interview_id == Interview.id)
        .where(Interview.user_id == user.id, Interview.status == InterviewStatus.FINISHED.value)
        .order_by(Interview.finished_at.asc())
    )
    points = [
        GrowthPoint(
            interview_id=interview.id,
            position=interview.position,
            finished_at=interview.finished_at,
            total_score=report.total_score,
            tech_score=report.tech_score,
            logic_score=report.logic_score,
            expression_score=report.expression_score,
            match_score=report.match_score,
        ).model_dump()
        for interview, report in result.all()
    ]
    return ok(points)


@router.get("/{interview_id}", response_model=dict, summary="获取指定面试的评估报告")
async def get_report(interview_id: int, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    if interview.status != InterviewStatus.FINISHED.value:
        raise ConflictError("面试尚未结束，暂无报告")

    report = await db.scalar(select(Report).where(Report.interview_id == interview_id))
    if report is None:
        raise ConflictError("报告生成中或生成失败，请稍后重试")
    return ok(ReportOut.model_validate(report).model_dump())
