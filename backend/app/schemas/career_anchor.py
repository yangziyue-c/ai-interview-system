"""职业锚定测试 schema"""
from pydantic import BaseModel, Field


class AnchorSubmitRequest(BaseModel):
    """提交答案：题目 ID → 选项 key（如 {"q1": "A", ...}）"""

    answers: dict[str, str] = Field(
        description="5 道题的作答，键为题号、值为选项 key；必须全部作答"
    )
