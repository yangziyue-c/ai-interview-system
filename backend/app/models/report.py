"""评估报告表：一场面试对应一份报告（P3 生成）"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    interview_id: Mapped[int] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), unique=True, index=True
    )

    # 多维度评分（0~100）：技术 / 逻辑 / 表达 / 应变 / 岗位匹配度
    # 维度与权重源自团队《评估维度.csv》：技术水平 / 逻辑思维 / 沟通表达 / 应变能力 / 岗位匹配度
    total_score: Mapped[float] = mapped_column(Float, comment="综合得分")
    tech_score: Mapped[float] = mapped_column(Float, comment="技术水平")
    logic_score: Mapped[float] = mapped_column(Float, comment="逻辑思维")
    expression_score: Mapped[float] = mapped_column(Float, comment="沟通表达")
    adaptability_score: Mapped[float] = mapped_column(Float, comment="应变能力")
    match_score: Mapped[float] = mapped_column(Float, comment="岗位匹配度")

    summary: Mapped[str] = mapped_column(Text, comment="综合评语")
    strengths: Mapped[list] = mapped_column(JSON, default=list, comment="优势列表")
    weaknesses: Mapped[list] = mapped_column(JSON, default=list, comment="不足列表")
    suggestions: Mapped[list] = mapped_column(JSON, default=list, comment="改进建议")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    interview = relationship("Interview", back_populates="report")
