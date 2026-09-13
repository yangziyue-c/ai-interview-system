"""题库 schema（供面试官对话逻辑 / RAG 检索使用）

字段与 `app.models.question.Question` 逐一同名（V5 交付包 19 列）。
"""
from pydantic import BaseModel, ConfigDict


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position_code: str
    question_no: str          # V5 原题ID，如 JAVA_BACKEND-Q0001
    category: str             # 技术知识题 / 场景应用题 / 项目经历题 / 行为素质题
    difficulty: str
    question: str
    interview_stage: str      # 开场热身 / 核心考察 / 深度压轴
    stage_order: int
    suggested_minutes: int
    # ---------------- V5 交付包独有素材 ----------------
    keywords: str
    exam_priority: str
    basic_score_points: str
    advanced_score_points: str
    follow_up_l1: str
    follow_up_l2: str
    follow_up_l3: str
    fallback_strategy: str
    calibration_anchor: str
    related_knowledge: str
