"""认证接口：注册 / 登录 / 当前用户"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, validate_position
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.utils.response import ok

router = APIRouter()


@router.post("/register", response_model=dict, summary="注册并自动登录")
async def register(req: RegisterRequest, db: DbSession) -> dict:
    exists = await db.scalar(select(User).where(User.username == req.username))
    if exists is not None:
        raise BadRequestError("该用户名已被注册")
    await validate_position(db, req.target_position)

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.username,
        student_id=req.student_id,
        target_position=req.target_position,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))
    return ok(token.model_dump(), "注册成功")


@router.post("/login", response_model=dict, summary="登录")
async def login(req: LoginRequest, db: DbSession) -> dict:
    user = await db.scalar(select(User).where(User.username == req.username))
    if user is None or not verify_password(req.password, user.password_hash):
        raise UnauthorizedError("用户名或密码错误")

    token = TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))
    return ok(token.model_dump(), "登录成功")


@router.get("/me", response_model=dict, summary="获取当前登录用户信息")
async def me(user: CurrentUser) -> dict:
    return ok(UserOut.model_validate(user).model_dump())
