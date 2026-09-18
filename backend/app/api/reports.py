"""报告接口：查看单场报告 / 能力成长曲线 / 生成分享链接"""
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_owned_interview
from app.config import settings
from app.core.exceptions import ConflictError
from app.core.state_machine import InterviewStatus
from app.models import Interview, Report, ReportShare
from app.schemas.report import GrowthPoint, ShareOut, report_out
from app.utils.response import ok

router = APIRouter()


@router.get("/growth", response_model=dict, summary="能力成长曲线（历史面试得分序列）")
async def get_growth(
    user: CurrentUser,
    db: DbSession,
    position: str | None = Query(default=None, description="按岗位筛选（不传=全部岗位）"),
) -> dict:
    conditions = [
        Interview.user_id == user.id,
        Interview.status == InterviewStatus.FINISHED.value,
    ]
    if position:
        # 岗位是动态集合（positions 表），非法值不报错、返回空序列即可。
        # 各岗位评估维度与权重不同，混在一条曲线里没有可比性——按岗位筛是这条接口
        # 的主要用法，前端个人中心切 Tab 时传该参数。
        conditions.append(Interview.position == position)

    result = await db.execute(
        select(Interview, Report)
        .join(Report, Report.interview_id == Interview.id)
        .where(*conditions)
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
            adaptability_score=report.adaptability_score,
            match_score=report.match_score,
        ).model_dump()
        for interview, report in result.all()
    ]
    return ok(points)


@router.get("/latest", response_model=dict, summary="最近一次面试的改进建议（个人中心用）")
async def get_latest_suggestion(user: CurrentUser, db: DbSession) -> dict:
    """返回最近一场已结束面试的建议摘要；从未完成过面试时 data 为 null"""
    result = await db.execute(
        select(Interview, Report)
        .join(Report, Report.interview_id == Interview.id)
        .where(Interview.user_id == user.id, Interview.status == InterviewStatus.FINISHED.value)
        .order_by(Interview.finished_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return ok(None)
    interview, report = row
    return ok(
        {
            "interview_id": interview.id,
            "position": interview.position,
            "finished_at": interview.finished_at,
            "total_score": report.total_score,
            "suggestions": report.suggestions,
        }
    )


@router.get("/{interview_id}", response_model=dict, summary="获取指定面试的评估报告")
async def get_report(interview_id: int, user: CurrentUser, db: DbSession) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    if interview.status != InterviewStatus.FINISHED.value:
        raise ConflictError("面试尚未结束，暂无报告")

    report = await db.scalar(select(Report).where(Report.interview_id == interview_id))
    if report is None:
        raise ConflictError("报告生成中或生成失败，请稍后重试")
    return ok(report_out(report, interview).model_dump())


@router.post("/{interview_id}/share", response_model=dict, summary="生成报告分享链接")
async def create_share(
    interview_id: int, request: Request, user: CurrentUser, db: DbSession
) -> dict:
    interview = await get_owned_interview(interview_id, user, db)
    if interview.status != InterviewStatus.FINISHED.value:
        raise ConflictError("面试尚未结束，暂无可分享的报告")
    report = await db.scalar(select(Report).where(Report.interview_id == interview_id))
    if report is None:
        raise ConflictError("报告生成中或生成失败，请稍后重试")

    now = datetime.now()
    # 复用尚未过期的分享码：用户连点「生成链接」不该堆出一串等价的有效码。
    # 取过期时间最晚的那个，等价于优先复用有效期最长的一张。
    share = await db.scalar(
        select(ReportShare)
        .where(ReportShare.interview_id == interview_id, ReportShare.expires_at > now)
        .order_by(ReportShare.expires_at.desc())
    )
    if share is None:
        share = ReportShare(
            interview_id=interview_id,
            share_code=uuid.uuid4().hex,
            expires_at=now + timedelta(days=settings.SHARE_EXPIRE_DAYS),
        )
        db.add(share)
        await db.commit()
        await db.refresh(share)

    # base_url 取当前请求的 Host：内网穿透演示时它会是穿透域名，前端拿到即可直接分发
    base_url = str(request.base_url).rstrip("/")
    return ok(
        ShareOut(
            share_code=share.share_code,
            share_url=f"{base_url}/#/share/{share.share_code}",
            expires_at=share.expires_at,
        ).model_dump(),
        "分享链接已生成",
    )
