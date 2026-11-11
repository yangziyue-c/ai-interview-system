"""报告分享表：分享链接的分享码、有效期与访问计数"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportShare(Base):
    __tablename__ = "report_shares"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 指向 interviews 而非 reports：报告与面试一一对应（reports.interview_id 是唯一列），
    # 分享接口入参本就是 interview_id，直连可省一次 join。
    # 注：需求文档里该字段写作 report_id，但文档自己也注明「即 interview_id」——
    # 沿用 interview_id 命名，避免后人误以为要 join reports.id。
    interview_id: Mapped[int] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True
    )
    share_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="分享码（uuid4 十六进制）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, comment="过期时间")
    view_count: Mapped[int] = mapped_column(Integer, default=0, comment="被访问次数")
