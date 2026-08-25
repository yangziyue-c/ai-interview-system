"""用户表"""
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(256), comment="bcrypt 哈希")
    nickname: Mapped[str] = mapped_column(String(64), default="", comment="昵称")
    # 目标岗位：backend=后端开发工程师 / frontend=前端开发工程师
    target_position: Mapped[str] = mapped_column(String(16), default="backend", comment="目标岗位")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="注册时间")
