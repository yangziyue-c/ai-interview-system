"""岗位接口：岗位列表（前端岗位大厅用）

岗位由数据库 positions 表动态维护（启动时自动 seed 5 个岗位位），
岗位清单确定后只需更新数据库记录，无需改代码。
"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Position
from app.schemas.position import PositionOut
from app.utils.response import ok

router = APIRouter()


@router.get("", response_model=dict, summary="岗位列表（仅返回已开放岗位）")
async def list_positions(_: CurrentUser, db: DbSession) -> dict:
    result = await db.scalars(
        select(Position)
        .where(Position.enabled.is_(True))
        .order_by(Position.sort_order.asc(), Position.id.asc())
    )
    return ok([PositionOut.model_validate(p).model_dump() for p in result.all()])
