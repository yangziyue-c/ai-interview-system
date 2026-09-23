"""评估报告 schema

评分维度（2026-09-04 起 5 维，源自团队《评估维度.csv》）：
技术水平 / 逻辑思维 / 沟通表达 / 应变能力 / 岗位匹配度
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    interview_id: int
    # 岗位 code：reports 表本身不存该列，由 report_out() 从所属面试注入。
    # 前端报告页刷新 / 深链进入时需要它来显示岗位名——原先只能靠内存变量传递，
    # 一刷新就丢失（页面只剩「综合得分 ·」）。
    position: str = Field(default="", description="面试岗位 code（由接口从所属面试注入）")
    total_score: float
    tech_score: float
    logic_score: float
    expression_score: float
    adaptability_score: float
    match_score: float
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    created_at: datetime


def report_out(report, interview) -> ReportOut:
    """由「报告 + 其所属面试」构造响应对象（三处报告出口统一走这里）。

    为什么不直接让 `ReportOut.model_validate(report)` 读 position：
    reports 表没有岗位列，而 Report.interview 这个 relationship 在 async 上下文里
    懒加载会抛 MissingGreenlet（`_finish_interview` 里新建的 Report 也没绑定过它）。
    故显式把 interview.position 注入——这样响应里的 position 永远非空。
    """
    return ReportOut.model_validate(report).model_copy(
        update={"position": interview.position}
    )


class ShareOut(BaseModel):
    """报告分享链接的创建结果"""

    share_code: str
    # 后端按当前请求的 Host 拼好的完整链接，前端直接复制到剪贴板即可。
    # 路由形式沿用前端的 hash 路由（#/share/<code>）。
    share_url: str
    expires_at: datetime


class GrowthPoint(BaseModel):
    """能力成长曲线上的一个点（一次已完成的面试）"""

    interview_id: int
    position: str
    # 面试链路：'' = 题库策略 + P3 评估（原链路）；'a11' = AI 对话层引擎。
    # 两种链路的五维分口径不同（P3 按题注入校准锚点，引擎逐轮 LLM 打分），
    # 混在一条曲线上会被误读成涨跌；要分开看时传 ?engine=standard|a11。
    engine: str = ""
    finished_at: datetime
    total_score: float
    tech_score: float
    logic_score: float
    expression_score: float
    adaptability_score: float
    match_score: float


# ---------------- 学习资源 / 练习计划（2026-09-23）----------------
# 口径说明：报告只有整场面试的 5 维聚合分（reports 表无单题得分），P3 评估服务
# 也不返回逐题评分，所以这里推荐的是「**考察过的**知识点」，不是「你答得差的」。
# 排序依据 = 考点优先级 + 被几道题命中，不假装知道哪道题答错。


class KPSource(BaseModel):
    """知识点的来源：本计划里哪场面试的第几轮问到了它"""

    interview_id: int
    round: int
    # 锚点原题在题库中的编号（前端可据此跳题库详情）
    question_no: str
    question: str


class PracticeQuestionOut(BaseModel):
    """配套练习题（题库中关联同一知识点的题）"""

    id: int
    # 岗位 code：知识点 ID 会跨岗位被引用，全库反查会带出别岗的题，前端据此标注
    position_code: str
    question_no: str
    question: str
    category: str
    difficulty: str
    exam_priority: str
    suggested_minutes: int
    # 本题在本计划的来源面试里被问到过（含最后一轮问了未作答的）。
    # 刻意不叫 answered：把「问了没答」也算作答，是过度声称。
    asked: bool


class KnowledgePointOut(BaseModel):
    """一个待巩固的知识点（题库自带学习建议原文 + 同知识点的配套练习）"""

    kp_id: str
    name: str
    # 题库自带的学习建议原文，不重写不总结（站内闭环，不依赖外部服务）
    advice: str
    # 该知识点的来源题目中最高的考点优先级
    priority: str
    # 来源面试里有几道锚点原题关联到它（等于 len(sources)，同时是显式排序键）
    hit_count: int
    sources: list[KPSource]
    # 该知识点配套练习时长（分）
    practice_minutes: int
    practice_questions: list[PracticeQuestionOut]


class SourceInterviewOut(BaseModel):
    """本次计划用到的面试（聚合模式下可能跨岗位，按结束时间倒序）"""

    interview_id: int
    position: str
    finished_at: datetime


class StudyPlanOut(BaseModel):
    """学习资源与练习计划（站内闭环：知识点 + 题库原文建议 + 配套练习）"""

    # 单场模式=该场面试 ID；聚合模式=null
    interview_id: int | None
    source_interviews: list[SourceInterviewOut]
    # 覆盖的岗位 code（跨岗位聚合时为多个）
    positions: list[str]
    knowledge_points: list[KnowledgePointOut]
    # 推荐练习总时长（同一道题服务多个知识点时只算一次）
    total_minutes: int
    # 其中尚未练过的部分（asked 为 false 的题）
    pending_minutes: int
    # 无可推荐内容时的一句中文说明（正常为 null）。前端直接展示即可，不要当错误处理：
    # 有它才能区分「还没面试」与「题库未导入 / 题干没命中」这两种空。
    notice: str | None
