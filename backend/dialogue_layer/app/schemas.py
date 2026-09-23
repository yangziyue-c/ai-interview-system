# -*- coding: utf-8 -*-
"""
schemas.py · 接口契约（唯一出处）
============================================================
所有请求/响应模型都在这里，`app/api/interview.py` 只负责调用它们。
改接口先改这里，再看前端要不要跟。

兼容性约束（重要，改之前先读）：
现成的 `web/test_chat.html` 是照旧接口写的，它：
- POST /start  只传 {job}                     → intro 必须有默认值
- POST /next   传 {session_id, message: ""}   → message 必须有默认值
- POST /finish 传 {session_id, message: ""}   → 同上
- 读 /start 的  data.session_id / data.message
- 读 /next  的  data.finished / data.stage / data.q_index / data.total / data.question
- 读 /finish 的 data.five_dim_avg / data.total_score / data.weights / data.summary
  （weights 是**字符串**、summary 是**字符串**，不是对象 —— 别改类型）

所以要动的是「加法」：新增字段可以，改已有字段的名字或类型会让前端静默失效
（它读不到就是 undefined，不报错，最难看）。
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app import config


# ============================================================
# 通用
# ============================================================
class Loose(BaseModel):
    """允许透传额外字段的基类：模型当文档用，但不做字段过滤器。"""
    model_config = ConfigDict(extra="allow")


class SessionReq(Loose):
    """/next、/finish 共用的请求体（旧前端会多传一个空 message，必须收下）。"""
    session_id: str = Field(..., min_length=4, description="会话 ID")
    message: str = Field("", description="旧前端固定传空串；本服务不使用该字段")


# ============================================================
# GET /health
# ============================================================
class HealthResp(Loose):
    status: str = "ok"
    version: str = ""
    port: int = 0
    llm_mock: bool = False
    reranker_mock: bool = False
    llm_configured: bool = False
    model: str = ""
    device: str = ""
    bank_loaded: bool = False
    bank_sizes: dict[str, int] = Field(default_factory=dict)
    scorer_ready: bool = False
    jobs: list[str] = Field(default_factory=lambda: list(config.JOBS))
    # 由 SessionStore.stats() 展开
    sessions_active: int = 0
    sessions_finished: int = 0
    sessions_total: int = 0
    session_capacity: int = 0
    # ---- 知识图谱 / RAG（全部带默认值：老响应体仍能通过校验）----
    # ⚠️ enabled 与 ready 是**两个**字段，不能合成一个：enabled=False 是配置
    #    （A11_KG=0），ready=False 且 enabled=True 才是故障。混起来运维分不清
    #    「我没开」和「它坏了」。错误信息同理 —— 关掉时 error 是空串。
    kg_enabled: bool = False
    kg_ready: bool = False
    kg_error: str = ""
    kg_nodes: int = 0
    rag_enabled: bool = False
    rag_ready: bool = False
    rag_error: str = ""
    rag_model: str = ""


# ============================================================
# POST /start
# ============================================================
class StartReq(Loose):
    job: str = Field(config.DEFAULT_JOB, description="岗位名，取值见 /health.jobs")
    intro: Optional[str] = Field("", description="自我介绍（可选，现未使用）")


class StartResp(Loose):
    session_id: str
    job: str
    state: str = Field(description="会话状态，等同 phase")
    phase: str
    message: str = Field(description="开场白（前端直接展示）")
    total_questions: int
    weights: str
    dimensions: list[str] = Field(default_factory=lambda: list(config.DIMENSIONS))


# ============================================================
# POST /next
# ============================================================
class NextResp(Loose):
    """
    出题结果。`finished=true` 时表示没有下一题了（题问完 / 题库抽空），
    前端应停止出题并调 /finish —— 此时只有 message，没有 question。
    """
    type: str = Field("question", description="question | finished")
    finished: bool = False
    session_id: str
    phase: str
    # ---- 题目字段（finished=true 时缺省）----
    stage: Optional[str] = None
    stage_index: Optional[int] = None
    q_index: Optional[int] = None
    total: int = config.TOTAL_QUESTIONS
    difficulty: Optional[str] = None
    question_id: Optional[str] = None
    question: Optional[str] = None
    knowledge_points: list[str] = Field(default_factory=list)
    opening_text: Optional[str] = None
    # ---- finished=true 时 ----
    reason: Optional[str] = None
    message: Optional[str] = None


# ============================================================
# POST /chat（SSE）
# ============================================================
class ChatReq(Loose):
    session_id: str = Field(..., min_length=4)
    message: str = Field(..., min_length=1, description="考生这一句回答")


class ChatResp(Loose):
    """仅为 /docs 展示 SSE 事件形状；实际响应是 text/event-stream。"""
    type: str = Field(description="token | done | error | question")
    text: Optional[str] = Field(None, description="token 事件的文本片段")
    follow_up: Optional[bool] = Field(
        None, description="done 事件：true=面试官在追问，等考生继续答；false=本轮结束，调 /next")
    round_finished: Optional[bool] = None
    q_index: Optional[int] = None
    follow_up_used: Optional[int] = None
    degrade_used: Optional[int] = None
    attempts: Optional[int] = None
    action: Optional[str] = Field(None, description="done 事件：L1 | L2 | degrade | close")
    reranker_score: Optional[float] = Field(
        None, description="done 事件：覆盖率 0-100（0.6*基础命中率 + 0.4*进阶命中率）")
    reranker_ok: Optional[bool] = Field(
        None, description="done 事件：false = reranker 失败，这个分不可信")
    # ↓ 判档：两个判档源各判了什么、最后听了谁。只增不改，4 号可以不看。
    reranker_band: Optional[str] = None
    judge_band: Optional[str] = Field(
        None, description="null = LLM 没判出来（超时/非 JSON），不是「判成降级」")
    judge_ok: Optional[bool] = None
    judge_why: Optional[str] = Field(None, description="LLM 给的一句话理由，仅排查用")
    fuse_rule: Optional[str] = Field(
        None, description="agree | llm_first | disagree_shallow | deepest | reranker_only")
    band_disagree: Optional[bool] = Field(
        None, description="两个判档源是否不一致，供 3 号统计判档质量")
    # ↓ 换题出路：这一轮被作废过一次还是没作废。这三条以前只在
    #   `api/interview.py` 那个手工 dict 里，`/docs` 上看不到 —— 补齐。
    swapped: Optional[bool] = Field(
        None, description="done 事件：这一轮换题了吗（恒存在，没换过是 false）")
    swaps_used: Optional[int] = Field(
        None, description="done 事件：本场已换几次")
    swaps_left: Optional[int] = Field(
        None, description="done 事件：本场还剩几次可换（默认上限 1）")
    phase: Optional[str] = None
    ms: Optional[int] = None
    session_id: Optional[str] = None
    err: Optional[str] = Field(None, description="error 事件：错误信息")
    code: Optional[str] = None


# ============================================================
# POST /finish 与 GET /result/{sid}
# ============================================================
class FinishResp(Loose):
    """
    顶层字段是**旧接口原样**，4 号前端零改动可用；
    新增的 raw 给 3 号评估报告取明细。

    注意 five_dim_avg 的值可能是 null（该维度所有轮次都没评出分），
    total_score 也可能是 null（整场没评出任何分）。
    **null 表示「没有数据」，不表示「0 分」** —— 前端要区分对待。
    """
    session_id: str
    job: str
    five_dim_avg: dict[str, Optional[float]]
    total_score: Optional[float]
    total_score_100: Optional[float] = Field(None, description="折算成百分制，同可能为 null")
    weights: str = Field(description="人类可读权重串，如 '技术30% 逻辑30% …'")
    summary: str = Field(description="面试评价正文")
    rounds: int = Field(description="参与评分的轮次数")
    partial: bool = Field(description="true=有轮次评分失败或整场无分，分数不完整")
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, description="完整明细，结构见 README")
    cached: bool = False


class ErrorResp(Loose):
    """统一错误体。"""
    code: str = Field(description="机器可读错误码，如 session_not_found")
    err: str = Field(description="人可读错误信息")
    session_id: Optional[str] = None
