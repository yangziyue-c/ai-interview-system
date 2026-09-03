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
    # 期望返回（分数 0~100）：
    {
        "total_score": 85.5,
        "tech_score": 88.0,        # 技术能力
        "logic_score": 83.0,       # 逻辑思维
        "expression_score": 80.0,  # 表达沟通
        "match_score": 90.0,       # 岗位匹配度
        "summary": "综合评语...",
        "strengths": ["优点1", "优点2"],
        "weaknesses": ["不足1"],
        "suggestions": ["建议1", "建议2"]
    }

约定：评估报告生成较慢，单独给 30 秒预算（其余适配器仍 15 秒）；
超时 / 非 2xx / 未配置 URL 时，后端自动使用内置 Mock 评分兜底，
保证报告必然生成、流程不中断。

P3 服务本体在 backend/evaluator/（独立 Flask 进程，端口 8002），由 start.py 自动拉起。
"""
import logging

from app.adapters.base import HTTPAdapterBase
from app.config import settings

logger = logging.getLogger(__name__)

_WEIGHTS = {"tech": 0.35, "logic": 0.25, "expression": 0.20, "match": 0.20}

# 评估报告生成较慢（长 Prompt + 多轮问答），单独 30 秒预算；
# P3 服务内部自身超时 25 秒，保证主后端在 30 秒内总能收到结果
EVALUATE_TIMEOUT_SECONDS = 30.0


def _mock_evaluate(position: str, qa_list: list[dict]) -> dict:
    """内置 Mock 评分：确定性算法（仅依赖回答长度），演示效果稳定可复现"""
    answered = [qa for qa in qa_list if (qa.get("answer") or "").strip()]
    avg_len = (
        sum(len(qa["answer"].strip()) for qa in answered) / len(answered) if answered else 0
    )

    # 平均回答长度 → 基础分
    if avg_len < 20:
        base, band = 60.0, "low"
    elif avg_len < 60:
        base, band = 68.0, "mid-low"
    elif avg_len < 120:
        base, band = 76.0, "mid"
    elif avg_len < 250:
        base, band = 84.0, "good"
    else:
        base, band = 90.0, "excellent"

    def _clamp(v: float) -> float:
        return round(max(0.0, min(100.0, v)), 1)

    tech = _clamp(base)
    logic = _clamp(base - 2)
    expression = _clamp(base + 2)
    match = _clamp(base + 1)
    total = round(
        tech * _WEIGHTS["tech"] + logic * _WEIGHTS["logic"]
        + expression * _WEIGHTS["expression"] + match * _WEIGHTS["match"],
        1,
    )

    summaries = {
        "low": "本次面试中回答较为简略，核心知识点的理解还有提升空间。建议系统性复习岗位基础知识，多做模拟练习。",
        "mid-low": "能回答出基本概念，但深度和细节不足。建议结合项目实践加深理解，回答时补充具体场景。",
        "mid": "基础掌握尚可，能围绕问题作答。若能在回答中补充项目案例和底层原理，表现会更出色。",
        "good": "整体表现良好，回答有内容、有条理，展现出一定的岗位胜任力。继续保持并打磨表达的精炼度。",
        "excellent": "表现优秀！回答详实、思路清晰，能结合实践深入阐述，具备很强的岗位竞争力。",
    }
    strengths, weaknesses, suggestions = {
        "low": (
            ["态度认真，完整参与了面试流程"],
            ["回答内容过少，知识点展开不足", "缺少项目案例支撑"],
            ["提前准备自我介绍与 2~3 个核心项目案例", "复习岗位核心知识点，练习结构化表达"],
        ),
        "mid-low": (
            ["能准确复述基础概念"],
            ["回答深度不够，缺少细节与原理", "表达偏碎片化，逻辑链不完整"],
            ["回答时采用'结论-原因-案例'三段式结构", "针对薄弱知识点做专题复习"],
        ),
        "mid": (
            ["基础知识掌握较扎实", "能够围绕问题进行作答"],
            ["缺少真实项目经验的佐证", "部分回答停留在概念层面"],
            ["多复盘自己的项目，沉淀可讲述的案例", "训练追问场景下的临场应对能力"],
        ),
        "good": (
            ["回答内容充实，条理清晰", "具备一定的实践视角"],
            ["个别问题可再深入到底层原理", "表达可更精炼，突出重点"],
            ["继续深挖技术原理，形成自己的技术体系", "多进行限时模拟面试，提升表达效率"],
        ),
        "excellent": (
            ["回答详实，理论与实践结合紧密", "逻辑严谨，表达流畅，岗位匹配度高"],
            ["个别回答的语速/篇幅控制可再优化"],
            ["保持技术敏感度，持续跟进新技术", "可尝试挑战更高级别的岗位面试"],
        ),
    }[band]

    return {
        "total_score": total,
        "tech_score": tech,
        "logic_score": logic,
        "expression_score": expression,
        "match_score": match,
        "summary": summaries[band],
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
    }


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
        if not isinstance(result, dict) or "total_score" not in result:
            logger.warning("P3 返回缺少评分字段，使用 Mock 兜底")
            result = await _mock()
        return result


adapter: AIEvaluatorAdapter | None = None


def get_evaluator_adapter() -> AIEvaluatorAdapter:
    global adapter
    if adapter is None:
        adapter = AIEvaluatorAdapter()
    return adapter
