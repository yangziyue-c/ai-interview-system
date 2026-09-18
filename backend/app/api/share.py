"""分享接口：凭分享码免登录查看报告

与 /reports 分开挂载是刻意的：本路由是唯一不要求登录的业务接口，单独成文件便于
一眼看清鉴权边界——新增接口时也不会顺手把 CurrentUser 依赖复制进来。
"""
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.models import Interview, Report, ReportShare
from app.schemas.report import report_out
from app.utils.response import ok

router = APIRouter()


@router.get("/{code}", response_model=dict, summary="凭分享码查看报告（无需登录）")
async def get_shared_report(code: str, db: DbSession) -> dict:
    share = await db.scalar(select(ReportShare).where(ReportShare.share_code == code))
    # 「不存在」与「已过期」返回同一提示：避免用枚举试探出哪些分享码真实存在
    if share is None or share.expires_at < datetime.now():
        raise NotFoundError("分享链接不存在或已过期")

    interview = await db.get(Interview, share.interview_id)
    report = await db.scalar(select(Report).where(Report.interview_id == share.interview_id))
    if interview is None or report is None:
        raise NotFoundError("分享的报告已不存在")

    share.view_count += 1
    await db.commit()

    # 结构与 GET /reports/{interview_id} 完全一致，前端可复用同一套渲染
    return ok(report_out(report, interview).model_dump())
