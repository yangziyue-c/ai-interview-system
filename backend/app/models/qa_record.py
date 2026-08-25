"""问答记录表：面试中的每一轮提问与回答"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class QARecord(Base):
    __tablename__ = "qa_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, comment="第几轮（1 起）")
    question: Mapped[str] = mapped_column(Text, comment="AI 面试官提问")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True, comment="考生回答（语音转写/文本）")
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="语音文件地址")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    interview = relationship("Interview", back_populates="qa_records")
