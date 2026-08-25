"""评估报告 schema"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    interview_id: int
    total_score: float
    tech_score: float
    logic_score: float
    expression_score: float
    match_score: float
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    created_at: datetime


class GrowthPoint(BaseModel):
    """能力成长曲线上的一个点（一次已完成的面试）"""

    interview_id: int
    position: str
    finished_at: datetime
    total_score: float
    tech_score: float
    logic_score: float
    expression_score: float
    match_score: float
