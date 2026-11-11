"""岗位倾向速测 schema"""
from pydantic import BaseModel, Field


class AnchorSubmitRequest(BaseModel):
    """提交 20 条陈述的 1~5 评分，顺序与题目接口返回一致"""

    answers: list[int] = Field(
        description="20 条陈述的评分，按题目顺序，每项为 1~5 的整数"
    )
