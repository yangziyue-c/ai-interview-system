"""面试相关 schema"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.report import ReportOut


class StartInterviewRequest(BaseModel):
    # 岗位由数据库 positions 表动态维护，存在性校验在服务层
    position: str = Field(max_length=32, description="面试岗位 code（见 GET /positions）")
    # 简历模式：传了就走引擎的 resume 档，考官 prompt 与开场白都会用到它。
    # 上限对齐引擎侧 A11_RESUME_MAX_CHARS（6000）；**仅引擎链路生效**——
    # 原链路的出题不看简历，传了会被忽略（不报错，见 interviews.start_interview）。
    resume_text: str | None = Field(
        default=None, max_length=6000,
        description="简历文本（可选，仅 AI 对话层引擎链路生效）",
    )


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10000, description="回答内容（语音转写文本）")
    audio_url: str | None = Field(default=None, max_length=512, description="录音文件地址（可选）")
    # 语音作答的表达读数：由 /uploads/audio/asr 的响应**整条原样**回传（只剥 text/url
    # 这类非读数键）。引擎据此算语速/停顿/填充词，写进报告的语音部分；**别挑字段**——
    # 少带一个键报告里就少一项读数（引擎侧对「调用方挑字段」有实测记录）。
    # 不传 = 文字作答，行为与加这个字段之前逐字节相同。仅引擎链路消费。
    speech: dict | None = Field(
        default=None, description="语音表达读数（可选，来自 /uploads/audio/asr 的响应）"
    )


class QAOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    round: int
    question: str
    answer: str | None
    audio_url: str | None
    # 引擎链路的本题对话明细，每条 {answer, audio_url, reply, action, follow_up, swapped}：
    # 追问原文只在这里（question 恒为题库原题面），engine_turns 是断点续答按序重建
    # 整段对话（含考生每轮回答）的唯一来源——answer 列会被追问覆盖，只剩最后一次。
    # 原链路为 None。
    engine_turns: list[dict] | None = None
    # 出题时间：问答回顾页按时间线展示「何时问、何时答」需要它
    created_at: datetime


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
