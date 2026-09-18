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
    finished_at: datetime
    total_score: float
    tech_score: float
    logic_score: float
    expression_score: float
    adaptability_score: float
    match_score: float
