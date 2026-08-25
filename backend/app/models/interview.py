"""面试会话表"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 面试岗位：backend / frontend
    position: Mapped[str] = mapped_column(String(16), comment="面试岗位")
    # 状态机：idle → in_progress → finished
    status: Mapped[str] = mapped_column(String(16), default="idle", index=True)
    # 已提问轮数（1 = 开场题，2~7 = 追问）
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")

    qa_records = relationship(
        "QARecord", back_populates="interview", order_by="QARecord.round", cascade="all, delete-orphan"
    )
    report = relationship("Report", back_populates="interview", uselist=False, cascade="all, delete-orphan")
