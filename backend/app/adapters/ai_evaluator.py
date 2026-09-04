"""P3 适配器：AI 评估（多维度评分 + 综合报告）

【给 P3 的接入约定】
在 .env 中配置 AI_EVALUATOR_URL 后，面试结束时后端会向你的服务发起：
    POST {AI_EVALUATOR_URL}/evaluate
    Content-Type: application/json
    {
        "position": "backend" | "frontend" | "test_engineer",  # 岗位 code（数据库动态下发）
        "qa_list": [
            {"round": 1, "question": "...", "answer": "...", "audio_url": null}
        ]
    }
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
本适配器对 P3 返回做 5 维契约归一化：任何分数键缺失或非数值时整体回退 Mock，
业务层拿到的结果字段永远齐全且可 float()。

P3 服务本体在 backend/evaluator/（独立 Flask 进程，端口 8002），由 start.py 自动拉起。
"""
import logging

from app.adapters.base import HTTPAdapterBase
from app.config import settings
from app.core.evaluation_weights import build_fallback_report

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
    """5 维分数键齐全且均为数值（bool 视为非法，防御 LLM 输出畸形值）"""
    for field in _SCORE_FIELDS:
        value = result.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
    return True


class AIEvaluatorAdapter(HTTPAdapterBase):
    """P3：生成多维度评估报告"""

    def __init__(self) -> None:
        super().__init__(settings.AI_EVALUATOR_URL, "P3-AI评估")

    async def evaluate(self, position: str, qa_list: list[dict]) -> dict:
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
