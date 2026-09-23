"""问答记录表：面试中的每一轮提问与回答"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
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
    # 引擎链路的本题明细：每次作答的面试官追问原文、判档结果、复读/换题标记等。
    # 追问**只存这里、不写进 question** —— question 始终保持题库原题面逐字不变，
    # 学习计划（reports.py 按题干反查题库）与评分素材注入都依赖这条不变量。
    engine_turns: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="引擎侧作答明细")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    interview = relationship("Interview", back_populates="qa_records")
