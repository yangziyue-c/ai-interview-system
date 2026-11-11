"""示范作答缓存表：每道问答记录最多一份生成结果

为什么落库而不是每次现生成：
- LLM 生成一份 300~500 字示范作答约数秒，报告页反复打开不该反复付费；
- 演示现场断网/额度用尽时，已生成过的题仍能展示，不会整片空白。

缓存键是 qa_record_id（一对一）：同一道题在不同场次里被问到，各自的考生答案
不同，示范作答却只取决于题干与得分点——但按 qa_record 缓存实现最简单，
也能保证「同一场次内反复点开只生成一次」。跨场次复用是后续可做的优化。

题库外的题（引擎追问、RAG/现场生成题）不写入本表：没有得分点素材，
生成出来的内容没有依据，接口会明确返回 available=false。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SampleAnswer(Base):
    __tablename__ = "sample_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    qa_record_id: Mapped[int] = mapped_column(
        ForeignKey("qa_records.id", ondelete="CASCADE"), unique=True, index=True
    )
    # 题库编号：反查命中时才有值；一并存下便于事后核对是哪个版本的题库素材
    question_no: Mapped[str] = mapped_column(String(32), default="", comment="V5 原题ID")
    content: Mapped[str] = mapped_column(Text, comment="LLM 生成的示范作答")
    # 生成模型名（如 deepseek-chat），用于区分不同模型产出的缓存
    model: Mapped[str] = mapped_column(String(64), default="", comment="生成模型")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
