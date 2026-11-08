"""用户设置 schema：设置页面的 6 项通用偏好

受控词表（report_preference / theme）刻意用普通 str 而非 Literal：取值集合
定义在 `models/user_setting.py`，接口层据此校验并返回 400——与题库接口
「非法值返回 400」的口径一致，也避免同一组取值在模型与 schema 里各写一遍。
"""
from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    """完整设置（没有存过记录的字段取默认值）"""

    default_position: str = Field(description="默认面试岗位 code；空串 = 未设置")
    voice_answer: bool = Field(description="语音作答开关")
    auto_tts: bool = Field(description="面试官自动朗读开关（仅引擎链路）")
    body_language: bool = Field(description="摄像头体态分析开关")
    report_preference: str = Field(description="报告展示偏好：detailed / concise")
    theme: str = Field(description="界面主题：light / dark / system")
    career_anchor_result: dict | None = Field(
        default=None,
        description="最近一次岗位倾向速测结果摘要；未测试过为 null",
    )


class SettingsUpdate(BaseModel):
    """部分更新：只提交要改的字段

    显式传空串可清空 default_position；其余字段不接受 None。
    """

    default_position: str | None = Field(default=None, max_length=32)
    voice_answer: bool | None = None
    auto_tts: bool | None = None
    body_language: bool | None = None
    report_preference: str | None = Field(default=None, max_length=16)
    theme: str | None = Field(default=None, max_length=16)
