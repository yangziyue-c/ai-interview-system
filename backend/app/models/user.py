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
    # 学号（可选，个人中心展示用）
    student_id: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="学号")
    # 目标岗位：backend=后端开发工程师 / frontend=前端开发工程师
    target_position: Mapped[str] = mapped_column(String(16), default="backend", comment="目标岗位")
    # 头像地址（可选，由 POST /uploads/avatar 产出，形如 /uploads/avatars/xxx.png）。
    # 为空时前端用昵称首字母占位，故不设默认值。
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="头像地址")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="注册时间")
