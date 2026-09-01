"""FastAPI 依赖：鉴权与常用资源获取"""
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError, UnauthorizedError
from app.core.security import decode_access_token
from app.database import get_db
from app.models import Interview, Position, User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """从 Authorization: Bearer <token> 解析当前用户"""
    if credentials is None:
        raise UnauthorizedError("缺少认证信息，请先登录")
    user_id = decode_access_token(credentials.credentials)
    user = await db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("账号不存在或已被删除")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_owned_interview(interview_id: int, user: User, db: AsyncSession) -> Interview:
    """获取面试会话（预加载问答记录），并校验归属（非本人一律 404，避免泄露存在性）"""
    result = await db.execute(
        select(Interview)
        .where(Interview.id == interview_id, Interview.user_id == user.id)
        .options(selectinload(Interview.qa_records))
    )
    interview = result.scalar_one_or_none()
    if interview is None:
        raise NotFoundError("面试会话不存在")
    return interview


async def validate_position(db: AsyncSession, code: str) -> None:
    """校验岗位 code 存在且已开放（岗位由数据库动态维护，替代硬编码枚举）"""
    exists = await db.scalar(
        select(Position.id).where(Position.code == code, Position.enabled.is_(True))
    )
    if exists is None:
        raise BadRequestError(f"岗位不存在或未开放: {code}")
