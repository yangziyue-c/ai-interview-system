"""面试相关 schema"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.report import ReportOut


class StartInterviewRequest(BaseModel):
    # 岗位由数据库 positions 表动态维护，存在性校验在服务层
    position: str = Field(max_length=32, description="面试岗位 code（见 GET /positions）")


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10000, description="回答内容（语音转写文本）")
    audio_url: str | None = Field(default=None, max_length=512, description="录音文件地址（可选）")


class QAOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    round: int
    question: str
    answer: str | None
    audio_url: str | None


class InterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: str
    status: str
    current_round: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class InterviewListItemOut(InterviewOut):
    """历史列表项：附带综合得分（未生成报告时为 null）"""

    total_score: float | None = None


class InterviewDetailOut(InterviewOut):
    qa_records: list[QAOut] = []


class StartInterviewOut(BaseModel):
    """开始面试：返回会话 + 第一个问题"""

    interview: InterviewOut
    question: str


class NextQuestionOut(BaseModel):
    """提交答案后的响应：下一题；若已结束则附带报告"""

    finished: bool
    interview: InterviewOut
    next_question: str | None = Field(default=None, description="未结束时为下一题")
    report: ReportOut | None = Field(default=None, description="结束时附带评估报告")


class FinishInterviewOut(BaseModel):
    interview: InterviewOut
    report: ReportOut
