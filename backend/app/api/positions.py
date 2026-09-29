"""岗位接口：岗位列表（前端岗位大厅用）

岗位由数据库 positions 表动态维护（启动时自动 seed 5 个岗位位），
岗位清单确定后只需更新数据库记录，无需改代码。

⚠️ **本接口不要求登录**（与 /share 并列，是仅有的两个免登录业务接口）：
注册页要先拿到岗位清单才能让用户选目标岗位，而那时用户还没账号——
要登录才能看，等于让「先看岗位再决定注册」这条正常路径走不通。
返回的只有岗位名 / 描述 / 技术栈 / 考察重点，都是给访客看的展示信息，
没有任何需要保护的字段，放开不影响安全。
"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import Position
from app.schemas.position import PositionOut
from app.utils.response import ok

router = APIRouter()


@router.get("", response_model=dict, summary="岗位列表（仅返回已开放岗位，无需登录）")
async def list_positions(db: DbSession) -> dict:
    result = await db.scalars(
        select(Position)
        .where(Position.enabled.is_(True))
        .order_by(Position.sort_order.asc(), Position.id.asc())
    )
    return ok([PositionOut.model_validate(p).model_dump() for p in result.all()])
