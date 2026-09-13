"""P3 适配器：AI 评估（多维度评分 + 综合报告）

【给 P3 的接入约定】
在 .env 中配置 AI_EVALUATOR_URL 后，面试结束时后端会向你的服务发起：
    POST {AI_EVALUATOR_URL}/evaluate
    Content-Type: application/json
    {
        "position": "backend" | "frontend" | "test_engineer" | "algorithm" | "system_design",
        "qa_list": [
            {"round": 1, "question": "...", "answer": "...", "audio_url": null,
             "materials": {                    # 可选：本题评分素材（V5 知识库，2026-09-14 新增）
                 "basic_score_points": "...",  # 基础得分点
                 "advanced_score_points": "...",  # 进阶得分点
                 "calibration_anchor": "..."   # 单题校准锚点（[技术水平]/[岗位匹配度] 判分标准）
             }}
        ]
    }
    # materials 由本适配器按题干从 questions 表查得后附加；旧版评估服务会忽略该字段。
    # 消费方：backend/evaluator_new/（增强版评估服务，按题评分）。
    # 期望返回（分数 0~100，5 维）：
    {
        "total_score": 85.5,
        "tech_score": 88.0,          # 技术水平
        "logic_score": 83.0,         # 逻辑思维
        "expression_score": 80.0,    # 沟通表达
        "adaptability_score": 82.0,  # 应变能力
        "match_score": 90.0,         # 岗位匹配度
        "summary": "综合评语...",
        "strengths": ["优点1", "优点2"],
        "weaknesses": ["不足1"],
        "suggestions": ["建议1", "建议2"]
    }

约定：评估报告生成较慢，单独给 30 秒预算（其余适配器仍 15 秒）；
超时 / 非 2xx / 未配置 URL 时，后端自动使用内置 Mock 评分兜底，
保证报告必然生成、流程不中断。
本适配器对 P3 返回做 5 维契约归一化：任何分数键缺失、非数值或越出 0~100 时整体回退 Mock，
业务层拿到的结果字段永远齐全、落在 0~100 区间且可 float()。

P3 服务本体在 backend/evaluator/（独立 Flask 进程，端口 8002），由 start.py 自动拉起。
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.adapters.base import HTTPAdapterBase
from app.config import settings
from app.core.evaluation_weights import build_fallback_report
from app.database import async_session
from app.models import Question

logger = logging.getLogger(__name__)

# 评估报告生成较慢（长 Prompt + 多轮问答），单独 30 秒预算；
# P3 服务内部自身超时 25 秒，保证主后端在 30 秒内总能收到结果
EVALUATE_TIMEOUT_SECONDS = 30.0

# 5 维分数键（与契约 JSON 字段一致），用于契约归一化校验
_SCORE_FIELDS = ("total_score", "tech_score", "logic_score", "expression_score", "adaptability_score", "match_score")


def _mock_evaluate(position: str, qa_list: list[dict]) -> dict:
    """内置 Mock 评分：确定性兜底报告（分档口径与评估服务降级报告共用）"""
    return build_fallback_report(position, qa_list)


def _is_valid_score_report(result: dict) -> bool:
    """5 维分数键齐全且均为 0~100 数值

    bool 视为非法；Infinity/NaN 经比较运算天然不满足 0 <= v <= 100 一并拦截。
    """
    for field in _SCORE_FIELDS:
        value = result.get(field)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not (0 <= value <= 100)
        ):
            return False
    return True


async def _attach_materials(position: str, qa_list: list[dict]) -> list[dict]:
    """按题干从题库取评分素材（V5 单题校准锚点 / 得分点），附到每个 qa 项

    **必须按 position 过滤**：题干在跨岗位间会重复（实测「什么是优先级队列？」
    同时存在于 backend 与 system_design 两岗），只按题干匹配会取到**另一个岗位**的
    得分点与判分锚点喂给评估模型——分数看起来正常但口径是错的，比取不到更危险。

    题干与 `questions.question` 精确匹配；匹配不上（题库换代、Mock/LLM 现场
    生成的题）时该项不带素材，评估服务退化为按对话泛泛评分——**软增强**，
    取不到不影响评估流程。

    只读短会话 + load_only：与出题侧同一取舍（长文本列不投影，
    且不复用请求级会话以免 autoflush 抢写锁）。
    """
    stems = {(qa.get("question") or "").strip() for qa in qa_list}
    stems.discard("")
    if not stems:
        return qa_list
    try:
        async with async_session() as session:
            rows = (await session.scalars(
                select(Question)
                .options(load_only(
                    Question.question, Question.basic_score_points,
                    Question.advanced_score_points, Question.calibration_anchor,
                ))
                .where(Question.position_code == position, Question.question.in_(stems))
            )).all()
    except Exception as exc:  # noqa: BLE001 - 素材是增强项，失败不应影响评估
        logger.warning("取题目评分素材失败(%s)，本次评估按对话文本评分", exc)
        return qa_list

    index = {r.question.strip(): r for r in rows}
    enriched: list[dict] = []
    for qa in qa_list:
        item = dict(qa)  # 不改调用方对象
        row = index.get((qa.get("question") or "").strip())
        if row is not None:
            item["materials"] = {
                "basic_score_points": row.basic_score_points,
                "advanced_score_points": row.advanced_score_points,
                "calibration_anchor": row.calibration_anchor,
            }
        enriched.append(item)
    return enriched


class AIEvaluatorAdapter(HTTPAdapterBase):
    """P3：生成多维度评估报告"""

    def __init__(self) -> None:
        super().__init__(settings.AI_EVALUATOR_URL, "P3-AI评估")

    async def evaluate(self, position: str, qa_list: list[dict]) -> dict:
        # 附加题目评分素材（V5 单题校准锚点/得分点）→ evaluator_new 按题评分；
        # 旧版评估服务会忽略 materials 字段，行为不变
        qa_list = await _attach_materials(position, qa_list)
        payload = {"position": position, "qa_list": qa_list}

        async def _mock() -> dict:
            return _mock_evaluate(position, qa_list)

        result = await self.call_or_fallback(
            "/evaluate", payload, _mock, timeout=EVALUATE_TIMEOUT_SECONDS
        )
        # 契约归一化：P3 返回的 5 维分数缺失/非数值（旧版服务、LLM 输出 null 等）时
        # 整体回退 Mock，业务层不做任何防御，直接下标 + float()
        if not isinstance(result, dict) or not _is_valid_score_report(result):
            logger.warning("P3 返回评分字段残缺或非数值，使用 Mock 兜底")
            result = await _mock()
        return result


adapter: AIEvaluatorAdapter | None = None


def get_evaluator_adapter() -> AIEvaluatorAdapter:
    global adapter
    if adapter is None:
        adapter = AIEvaluatorAdapter()
    return adapter
