"""认证相关 schema"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="登录账号")
    password: str = Field(min_length=6, max_length=64, description="密码")
    nickname: str = Field(default="", max_length=32, description="昵称")
    student_id: str | None = Field(default=None, max_length=32, description="学号（可选）")
    # 岗位由数据库 positions 表动态维护，此处只做格式校验，存在性校验在服务层
    target_position: str = Field(default="backend", max_length=32, description="目标岗位 code（见 GET /positions）")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


class UpdateProfileRequest(BaseModel):
    """更新个人资料：字段全部可选。

    「未传该字段」与「显式传 null」语义不同——服务层用 `model_dump(exclude_unset=True)`
    取差异集：没传的键不出现在结果里（保持原值），显式传 null 的键会出现且值为 None
    （清空）。这样前端才能把学号、头像改回空。
    """

    nickname: str | None = Field(default=None, max_length=32, description="昵称")
    student_id: str | None = Field(default=None, max_length=32, description="学号（传 null 清空）")
    # 岗位由数据库 positions 表动态维护，此处只做格式校验，存在性校验在服务层
    target_position: str | None = Field(
        default=None, max_length=32, description="目标岗位 code（见 GET /positions）"
    )
    avatar_url: str | None = Field(
        default=None,
        max_length=512,
        description="头像地址（传 null 清空）；须为 POST /uploads/avatar 返回的站内路径",
    )


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    student_id: str | None
    target_position: str
    avatar_url: str | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
