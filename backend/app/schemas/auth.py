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


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    student_id: str | None
    target_position: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
