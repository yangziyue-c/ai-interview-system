"""题库 schema（供面试官对话逻辑/RAG 检索使用）"""
from pydantic import BaseModel, ConfigDict


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position_code: str
    question_no: str
    category: str
    sub_category: str
    difficulty: str
    question: str
    soft_skill_tag: str
    score_points: str
    follow_up_triggers: str
    reference_answer: str
    note: str
    interview_stage: str
    stage_order: int
    suggested_minutes: int
    alternative_directions: str
    excellent_example: str
