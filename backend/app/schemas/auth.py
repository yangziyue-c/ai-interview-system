"""认证相关 schema"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Position = Literal["backend", "frontend"]


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="登录账号")
    password: str = Field(min_length=6, max_length=64, description="密码")
    nickname: str = Field(default="", max_length=32, description="昵称")
    target_position: Position = Field(default="backend", description="目标岗位")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    target_position: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
