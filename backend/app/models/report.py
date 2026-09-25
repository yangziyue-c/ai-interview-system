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

    # 引擎链路的报告明细（会话 ID、参与评分轮次、partial/notes、盲区摘要等）。
    # 只做留痕与事后核对，不进考生可见文案——notes 是引擎的内部口径，
    # 该说的话引擎已经拼进了 summary。
    # ⚠️ `none_as_null=True`：JSON 类型的默认行为把 Python 的 None 存成 **JSON 的
    #    `null` 字面量**（不是 SQL NULL），于是 `IS NOT NULL` 会把「原链路场次」
    #    也算成「有明细」。档案接口据此筛过一场，就是被这一点坑的。
    engine_meta: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True, comment="引擎报告明细"
    )

    # 引擎链路的成长档案摘要（单场 4~6KB）。对话层侧是**白名单构造、绝不含得分点原文**，
    # 存档后原样回传给 `POST /growth` 就能得到错题本 / 考点地图 / 历史成绩。
    # 单独一列而不是塞进 engine_meta：回传要的是**原样**的 digest，不能掺别的东西。
    digest: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True, comment="成长档案摘要（引擎链路）"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    interview = relationship("Interview", back_populates="report")
