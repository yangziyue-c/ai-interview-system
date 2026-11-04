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
    # 语音表达读数：提交答案时把 /uploads/audio/asr 的响应**整条**存下来。
    # 原先只转发给引擎、不落库，原链路的读数直接丢弃——报告里的「表达与表现分析」
    # 需要它。`none_as_null=True` 的理由同 reports.digest：JSON 的 null 字面量会
    # 让「文字作答」被 `IS NOT NULL` 误判成「有语音数据」。
    speech: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True, comment="语音表达读数（ASR 原始响应）"
    )
    # 本轮体态分析结果（引擎 /body-language 的返回，最近一次覆盖）。
    # 只有前端调用分析时带了 interview_id + round 才写入；不带参数时该列为 NULL。
    body_language: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True, comment="本轮体态分析结果"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    interview = relationship("Interview", back_populates="qa_records")

    @property
    def judge_band(self) -> str | None:
        """本题的最终判档（引擎链路）；原链路与「没判出来」都是 None

        引擎每轮作答都会给一个档：L1/L2/L3 = 答到了，degrade = 答不出、
        swap = 换题。一题可能被追问多次，取**最后一条** turn——中间答浅
        触发追问、最后答上来的情况不该记为「待提升」。
        """
        turns = self.engine_turns or []
        if not turns:
            return None
        band = turns[-1].get("judge_band")
        return str(band) if band else None

    @property
    def needs_improvement(self) -> bool | None:
        """是否建议看示范作答：只在引擎链路给出判定，原链路恒为 None

        None = 不知道（原链路没有单题分 / 引擎没判出来），不是「答得好」。
        前端据此决定是否标「待提升」，而不是把未知画成正确答案。
        """
        band = self.judge_band
        if band is None:
            return None
        return band in ("degrade", "swap")
