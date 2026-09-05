"""评估契约共享模块：岗位 5 维权重 + 兜底报告生成

被两个进程共用（仅依赖标准库）：
- 主后端 backend/app/adapters/ai_evaluator.py（Mock 兜底评分）
- 独立评估服务 backend/evaluator/（评估 Prompt 权重 + 降级报告）

评分维度与权重源自团队《评估维度.csv》（2026-09-04 定稿）：
技术水平 / 逻辑思维 / 沟通表达 / 应变能力 / 岗位匹配度。
tests/test_api.py 的 test_weights_match_csv 做机器校验，防止与 CSV 漂移。
"""

# ============================================================
# 岗位权重配置（百分制，各维度之和为 100）
# ============================================================

POSITION_CONFIG = {
    # 岗位 code 与主后端数据库 positions 表一一对应，勿单独改动
    "backend": {
        "name": "后端开发工程师",
        "weight_tech": 35,          # 技术水平
        "weight_logic": 25,         # 逻辑思维
        "weight_expression": 10,    # 沟通表达
        "weight_adaptability": 10,  # 应变能力
        "weight_match": 20,         # 岗位匹配度
    },
    "frontend": {
        "name": "前端开发工程师",
        "weight_tech": 30,
        "weight_logic": 20,
        "weight_expression": 15,
        "weight_adaptability": 15,
        "weight_match": 20,
    },
    "test_engineer": {
        "name": "测试开发工程师",
        "weight_tech": 25,
        "weight_logic": 25,
        "weight_expression": 20,
        "weight_adaptability": 15,
        "weight_match": 15,
    },
}

# 通用兜底配置：数据库新增岗位（如预留位启用）但尚无专属权重时使用
GENERIC_POSITION = {
    "weight_tech": 30,
    "weight_logic": 25,
    "weight_expression": 20,
    "weight_adaptability": 10,
    "weight_match": 15,
}


def weights_for(position: str) -> dict[str, float]:
    """按岗位取 5 维小数权重（百分制 / 100），未知岗位用通用权重兜底"""
    config = POSITION_CONFIG.get(position, GENERIC_POSITION)
    return {
        "tech": config["weight_tech"] / 100,
        "logic": config["weight_logic"] / 100,
        "expression": config["weight_expression"] / 100,
        "adaptability": config["weight_adaptability"] / 100,
        "match": config["weight_match"] / 100,
    }


# ============================================================
# 兜底报告生成：评估不可用/超时时按回答篇幅分档
# 主后端 Mock 兜底与评估服务降级报告共用，保证两条降级路径口径一致
# ============================================================

def _clamp_score(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


# 分档按 min_len 降序排列，命中第一个 avg_len >= min_len 的档位
_FALLBACK_BANDS: list[dict] = [
    {
        "min_len": 250, "base": 90.0, "comment": "回答详实",
        "summary": "表现优秀！回答详实、思路清晰，能结合实践深入阐述，具备很强的岗位竞争力。",
        "strengths": ["回答详实，理论与实践结合紧密", "逻辑严谨，表达流畅，岗位匹配度高"],
        "weaknesses": ["个别回答的语速/篇幅控制可再优化"],
        "suggestions": ["保持技术敏感度，持续跟进新技术", "可尝试挑战更高级别的岗位面试"],
    },
    {
        "min_len": 120, "base": 84.0, "comment": "回答较充实",
        "summary": "整体表现良好，回答有内容、有条理，展现出一定的岗位胜任力。继续保持并打磨表达的精炼度。",
        "strengths": ["回答内容充实，条理清晰", "具备一定的实践视角"],
        "weaknesses": ["个别问题可再深入到底层原理", "表达可更精炼，突出重点"],
        "suggestions": ["继续深挖技术原理，形成自己的技术体系", "多进行限时模拟面试，提升表达效率"],
    },
    {
        "min_len": 60, "base": 76.0, "comment": "回答篇幅适中",
        "summary": "基础掌握尚可，能围绕问题作答。若能在回答中补充项目案例和底层原理，表现会更出色。",
        "strengths": ["基础知识掌握较扎实", "能够围绕问题进行作答"],
        "weaknesses": ["缺少真实项目经验的佐证", "部分回答停留在概念层面"],
        "suggestions": ["多复盘自己的项目，沉淀可讲述的案例", "训练追问场景下的临场应对能力"],
    },
    {
        "min_len": 20, "base": 68.0, "comment": "回答篇幅偏短",
        "summary": "能回答出基本概念，但深度和细节不足。建议结合项目实践加深理解，回答时补充具体场景。",
        "strengths": ["能准确复述基础概念"],
        "weaknesses": ["回答深度不够，缺少细节与原理", "表达偏碎片化，逻辑链不完整"],
        "suggestions": ["回答时采用'结论-原因-案例'三段式结构", "针对薄弱知识点做专题复习"],
    },
    {
        "min_len": 0, "base": 60.0, "comment": "回答偏简略",
        "summary": "本次面试中回答较为简略，核心知识点的理解还有提升空间。建议系统性复习岗位基础知识，多做模拟练习。",
        "strengths": ["态度认真，完整参与了面试流程"],
        "weaknesses": ["回答内容过少，知识点展开不足", "缺少项目案例支撑"],
        "suggestions": ["提前准备自我介绍与 2~3 个核心项目案例", "复习岗位核心知识点，练习结构化表达"],
    },
]


def build_fallback_report(position: str, qa_list: list[dict], summary_prefix: str = "") -> dict:
    """按平均回答篇幅生成确定性兜底报告（5 维，总分按岗位权重加权）

    summary_prefix 非空时（如"评估服务暂时不可用"），summary 改为降级说明文案；
    为空时使用正常评语（主后端 Mock 兜底的演示场景）。
    """
    answered = [qa for qa in qa_list if (qa.get("answer") or "").strip()]
    avg_len = (
        sum(len(qa["answer"].strip()) for qa in answered) / len(answered) if answered else 0
    )
    band = next(b for b in _FALLBACK_BANDS if avg_len >= b["min_len"])

    base = band["base"]
    tech = _clamp_score(base)
    logic = _clamp_score(base - 2)
    expression = _clamp_score(base + 2)
    adaptability = _clamp_score(base + 1)
    match = _clamp_score(base + 1)
    weights = weights_for(position)
    total = round(
        tech * weights["tech"] + logic * weights["logic"]
        + expression * weights["expression"] + adaptability * weights["adaptability"]
        + match * weights["match"],
        1,
    )

    summary = (
        f"{summary_prefix}，系统已按回答篇幅生成临时报告（{band['comment']}）。请稍后重试或联系技术支持。"
        if summary_prefix else band["summary"]
    )
    return {
        "total_score": total,
        "tech_score": tech,
        "logic_score": logic,
        "expression_score": expression,
        "adaptability_score": adaptability,
        "match_score": match,
        "summary": summary,
        "strengths": band["strengths"],
        "weaknesses": band["weaknesses"],
        "suggestions": band["suggestions"],
    }


# ============================================================
# 权重完整性校验（加载期执行）
# total_score = Σ(维度分 × 权重) 依赖「权重和为 100」的百分制标度，
# 从注释约定提升为机器断言，防止未来新增岗位时权重和漂移
# ============================================================

_WEIGHT_KEYS = (
    "weight_tech", "weight_logic", "weight_expression",
    "weight_adaptability", "weight_match",
)


def _assert_weights_sum_to_100() -> None:
    for code, cfg in list(POSITION_CONFIG.items()) + [("generic", GENERIC_POSITION)]:
        total = sum(cfg[k] for k in _WEIGHT_KEYS)
        assert total == 100, (
            f"岗位权重和必须为 100（当前 {code} = {total}），"
            f"请与《评估维度.csv》对齐后修改"
        )


_assert_weights_sum_to_100()
