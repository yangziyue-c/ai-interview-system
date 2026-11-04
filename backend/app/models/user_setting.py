"""用户设置表：设置页面的 6 项通用偏好

为什么单独建表而不是往 users 表加列：这些是「界面与面试偏好」，与账号资料
（昵称/头像/学号）的读写路径、校验规则都不同；单独成表后，设置接口按行
upsert，不碰 users 行，也不会因为设置字段的增删影响登录链路的查询。

没有记录 = 全部用默认值（GET 返回默认，PUT 首次写入时建行）。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 受控词表（设置接口校验与前端共用）
REPORT_PREFERENCES = ("detailed", "concise")
THEMES = ("light", "dark", "system")


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # 默认岗位 code：空串 = 未设置（前端回退到注册时选择的目标岗位）
    default_position: Mapped[str] = mapped_column(
        String(32), default="", comment="默认面试岗位 code"
    )
    # 语音作答：关闭后前端只走文字输入
    voice_answer: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="语音作答开关"
    )
    # 面试官自动朗读（TTS）：仅引擎链路可用
    auto_tts: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="面试官自动朗读开关"
    )
    # 摄像头体态分析：关闭后前端不采集关键点
    body_language: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="体态分析开关"
    )
    # 报告展示偏好：detailed=完整明细 / concise=只看结论
    report_preference: Mapped[str] = mapped_column(
        String(16), default="detailed", comment="报告展示偏好"
    )
    # 界面主题：light / dark / system
    theme: Mapped[str] = mapped_column(
        String(16), default="system", comment="界面主题"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="最后更新时间"
    )
