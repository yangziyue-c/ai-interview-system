"""认证接口：注册 / 登录 / 当前用户 / 更新资料"""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, validate_position
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.core.upload_rules import remove_avatar_file, validate_avatar_url
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenOut,
    UpdateProfileRequest,
    UserOut,
)
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


@router.put("/me", response_model=dict, summary="更新当前用户资料")
@router.patch(
    "/me",
    response_model=dict,
    summary="更新当前用户资料（与 PUT 等价）",
    include_in_schema=False,
)
async def update_me(req: UpdateProfileRequest, user: CurrentUser, db: DbSession) -> dict:
    """只改传入的字段，未传的保持原值（request schema 已说明两种「空」的区别）。

    PUT 与 PATCH 并存是刻意的：本接口本就是部分更新语义，两者在该场景下没有实际
    差异，前端挑顺手的用即可，省得联调时为方法名来回改。
    """
    # exclude_unset 区分「没传该字段」（保持原值）与「显式传 null」（清空）
    updates = req.model_dump(exclude_unset=True)

    if "nickname" in updates:
        nickname = (updates["nickname"] or "").strip()
        if not nickname:
            raise BadRequestError("昵称不能为空")
        updates["nickname"] = nickname
    if "student_id" in updates:
        # 空串与 null 等价（都表示「没填」），统一存 None，免得库里出现 '' 和 NULL 两种空
        updates["student_id"] = (updates["student_id"] or "").strip() or None
    if "target_position" in updates:
        if updates["target_position"] is None:
            raise BadRequestError("目标岗位不能为空")
        await validate_position(db, updates["target_position"])
    if "avatar_url" in updates:
        validate_avatar_url(updates["avatar_url"])

    old_avatar = user.avatar_url
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)

    # 换掉头像才清理旧文件，且放在 commit 之后：先保证新地址已落库，再删旧图——
    # 顺序反过来的话，删完旧图、写库却失败，用户资料里就留下一个指向空文件的地址
    if "avatar_url" in updates and updates["avatar_url"] != old_avatar:
        remove_avatar_file(old_avatar)

    return ok(UserOut.model_validate(user).model_dump(), "资料已更新")
