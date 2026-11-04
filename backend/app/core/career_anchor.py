"""岗位倾向速测：20 条陈述，按兴趣与能力双维度推荐岗位

与前端 `CareerAnchor.vue` 的算分口径逐项一致，后端接管计算后，题目与结果
都只有一份事实源。速测是**引导入口**，不是能力测评：题目问的是日常偏好与
当前能否独立完成，结果用于推荐先体验哪个岗位，不做性格或能力判定。

计分口径（与前端 v3 对齐）：
- 每个岗位 4 条陈述：2 条兴趣、2 条能力，每题 1~5 分；
- 岗位原始分 = 同岗位同类别两条之和（2~10），归一化 `(raw - 6) / 4` 到 -1~1；
- 综合分 = 兴趣 60% + 能力 40%，指数 = `(综合分 + 1) * 50`，落在 0~100；
- 排序：综合分降序，再能力分、兴趣分，最后固定岗位顺序；
- 一致性 = 1 - 同岗位同类两条陈述的平均差值 / 4，换算成百分比。
"""

POSITION_CODES = ("backend", "frontend", "test_engineer", "algorithm", "system_design")

POSITION_NAMES = {
    "backend": "后端开发工程师",
    "frontend": "前端开发工程师",
    "test_engineer": "测试开发工程师",
    "algorithm": "算法工程师",
    "system_design": "系统设计工程师",
}

POSITION_REASONS = {
    "backend": "更关注数据、接口与系统稳定性，后端的学习路径和你的选择更接近。",
    "frontend": "更关注交互、体验与工程化，前端的学习路径和你的选择更接近。",
    "test_engineer": "更关注质量、边界与可验证性，测试开发的成长路径和你的选择更接近。",
    "system_design": "更关注架构、容量与高可用，系统设计方向的综合要求与你的回答更接近。",
    "algorithm": "更关注模型效果与指标提升，算法工程方向与你的兴趣和能力自评更接近。",
}

# 1~5 分自评的标签，下发给前端作为选项文案（前端也可本地兜底）
INTEREST_RATINGS = [
    {"value": 1, "label": "完全不符合"},
    {"value": 2, "label": "不太符合"},
    {"value": 3, "label": "一般或不确定"},
    {"value": 4, "label": "比较符合"},
    {"value": 5, "label": "非常符合"},
]
ABILITY_RATINGS = [
    {"value": 1, "label": "目前做不到"},
    {"value": 2, "label": "需要较多帮助"},
    {"value": 3, "label": "基本了解，但不够独立"},
    {"value": 4, "label": "基本可以独立完成"},
    {"value": 5, "label": "能够稳定独立完成"},
]

# 20 条陈述，顺序即前端答题顺序。category=interest/ability，role=岗位 code
SCALE_QUESTIONS: list[dict] = [
    {"id": "q1", "category": "interest", "role": "backend", "text": "我喜欢把业务规则拆成清晰的数据模型和接口边界。"},
    {"id": "q2", "category": "interest", "role": "frontend", "text": "我愿意反复打磨页面交互、视觉细节和操作路径。"},
    {"id": "q3", "category": "interest", "role": "test_engineer", "text": "我喜欢提前设计异常场景和验收标准。"},
    {"id": "q4", "category": "interest", "role": "system_design", "text": "我喜欢权衡模块边界、容量、扩展性和可用性。"},
    {"id": "q5", "category": "interest", "role": "algorithm", "text": "我愿意用数据和实验判断一个方案是否真的有效。"},
    {"id": "q6", "category": "interest", "role": "backend", "text": "看到一套服务稳定支撑高并发请求，我会很有成就感。"},
    {"id": "q7", "category": "interest", "role": "frontend", "text": "我享受把复杂功能整理成清晰、顺手的界面。"},
    {"id": "q8", "category": "interest", "role": "test_engineer", "text": "我愿意追查偶现问题，直到它能够稳定复现。"},
    {"id": "q9", "category": "interest", "role": "system_design", "text": "我对多个服务如何协作、部署和承受流量很感兴趣。"},
    {"id": "q10", "category": "interest", "role": "algorithm", "text": "我喜欢研究模型、特征或指标为什么发生变化。"},
    {"id": "q11", "category": "ability", "role": "backend", "text": "我能独立设计数据表、接口和基本的登录权限。"},
    {"id": "q12", "category": "ability", "role": "frontend", "text": "我能独立完成响应式页面、组件交互和状态联动。"},
    {"id": "q13", "category": "ability", "role": "test_engineer", "text": "我能独立设计测试用例、自动化脚本和回归检查。"},
    {"id": "q14", "category": "ability", "role": "system_design", "text": "我能拆分模块、画架构图并说明部署方案。"},
    {"id": "q15", "category": "ability", "role": "algorithm", "text": "我能完成数据清洗、模型训练和基本效果评估。"},
    {"id": "q16", "category": "ability", "role": "backend", "text": "遇到数据库异常、并发或消息堆积时，我知道从哪里排查。"},
    {"id": "q17", "category": "ability", "role": "frontend", "text": "遇到渲染、兼容性或网络请求问题时，我能定位到具体环节。"},
    {"id": "q18", "category": "ability", "role": "test_engineer", "text": "我能复现环境差异、边界输入和偶现缺陷。"},
    {"id": "q19", "category": "ability", "role": "system_design", "text": "我能分析服务依赖、资源瓶颈和扩展方案。"},
    {"id": "q20", "category": "ability", "role": "algorithm", "text": "遇到指标异常时，我能判断是数据、特征还是训练过程的问题。"},
]

_QUESTION_COUNT = len(SCALE_QUESTIONS)


def public_questions() -> dict:
    """下发给前端的题目与评分标签（不含任何计分权重）"""
    return {
        "total": _QUESTION_COUNT,
        "questions": [
            {"id": q["id"], "category": q["category"], "role": q["role"], "text": q["text"]}
            for q in SCALE_QUESTIONS
        ],
        "interest_ratings": INTEREST_RATINGS,
        "ability_ratings": ABILITY_RATINGS,
    }


def validate_answers(answers: list[int]) -> None:
    """校验 20 条全部作答且每项在 1~5；不合法抛 ValueError（接口层转 400）"""
    if len(answers) != _QUESTION_COUNT:
        raise ValueError(f"需要作答 {_QUESTION_COUNT} 条陈述，当前提交了 {len(answers)} 条")
    for index, value in enumerate(answers, 1):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"第 {index} 条评分必须是 1~5 的整数，当前为 {value!r}")


def _normalize(raw: int) -> float:
    """两条陈述之和（2~10）归一化到 -1~1"""
    return (raw - 6) / 4


def _local_consistency(answers: list[int]) -> int:
    """同岗位同类两条陈述的差值越小，一致性越高（0~100）"""
    total_difference = 0
    pair_count = 0
    for code in POSITION_CODES:
        for category in ("interest", "ability"):
            values = [
                answers[i]
                for i, q in enumerate(SCALE_QUESTIONS)
                if q["role"] == code and q["category"] == category
            ]
            if len(values) == 2:
                total_difference += abs(values[0] - values[1])
                pair_count += 1
    if pair_count == 0:
        return 0
    return round((1 - total_difference / (pair_count * 4)) * 100)


def score_answers(answers: list[int]) -> dict:
    """按前端 v3 口径算分并生成结果文案（调用前先 validate_answers）"""
    interest = {code: 0 for code in POSITION_CODES}
    ability = {code: 0 for code in POSITION_CODES}
    for value, question in zip(answers, SCALE_QUESTIONS):
        if question["category"] == "interest":
            interest[question["role"]] += value
        else:
            ability[question["role"]] += value

    ranked = []
    for code in POSITION_CODES:
        interest_norm = _normalize(interest[code])
        ability_norm = _normalize(ability[code])
        composite = interest_norm * 0.6 + ability_norm * 0.4
        ranked.append(
            {
                "position": code,
                "name": POSITION_NAMES[code],
                "interest_raw": interest[code],
                "ability_raw": ability[code],
                "interest_norm": round(interest_norm, 4),
                "ability_norm": round(ability_norm, 4),
                "composite": round(composite, 4),
                "index": round((composite + 1) * 50),
            }
        )
    # 与前端排序键一致：综合分、能力分、兴趣分，最后固定岗位顺序
    ranked.sort(
        key=lambda item: (
            -item["composite"],
            -item["ability_norm"],
            -item["interest_norm"],
            POSITION_CODES.index(item["position"]),
        )
    )

    top = ranked[0]
    second = ranked[1]
    margin = top["index"] - second["index"]
    consistency = _local_consistency(answers)
    confidence = (
        "高"
        if consistency >= 75 and margin >= 10
        else "中"
        if consistency >= 50 and margin >= 5
        else "低"
    )

    top_interest = max(
        POSITION_CODES, key=lambda code: (interest[code], -POSITION_CODES.index(code))
    )
    top_ability = max(
        POSITION_CODES, key=lambda code: (ability[code], -POSITION_CODES.index(code))
    )
    interest_name = POSITION_NAMES[top_interest]
    ability_name = POSITION_NAMES[top_ability]

    if margin < 5:
        title = "方向暂不明确"
        narrative = (
            f"当前相对最高的是「{top['name']}」，但与「{second['name']}」的分差只有 {margin} 分，"
            "暂时不能形成明确的主推荐。建议补充项目经历后再测，或先分别体验这两个方向。"
        )
        signal_label = "各方向区分度不足"
        signal_narrative = (
            "各岗位的倾向指数过于接近，当前无法可靠判断兴趣与能力的优势方向。"
            "建议补充真实项目经历后重测，或分别体验排名靠前的岗位。"
        )
    else:
        title = top["name"]
        if top_interest == top_ability:
            narrative = (
                f"兴趣量表与能力自评都更支持「{interest_name}」。"
                f"{POSITION_REASONS[top['position']]}"
            )
            signal_label = "兴趣与能力方向一致"
            signal_narrative = f"两类量表都把「{interest_name}」排在首位，方向较一致。"
        else:
            narrative = (
                f"兴趣量表更偏向「{interest_name}」，能力自评更偏向「{ability_name}」。"
                f"按兴趣 60%、能力 40% 综合后，当前优先推荐「{top['name']}」。"
            )
            signal_label = "兴趣与能力方向存在差异"
            signal_narrative = (
                f"兴趣最高的是「{interest_name}」，能力自评最高的是「{ability_name}」。"
                "建议先用项目或模拟面试验证兴趣方向，同时评估能力方向的提升空间。"
            )
        if confidence == "低":
            signal_narrative += " 当前主次分差较小，或同类陈述的回答不够稳定，结果只适合作为初步线索。"
        elif confidence == "中":
            signal_narrative += " 结果具有一定区分度，但仍建议结合一次真实练习验证。"
        else:
            signal_narrative += " 主次方向区分较清楚，可以作为优先探索方向。"

    return {
        "recommended": {
            "position": top["position"],
            "name": top["name"],
            "index": top["index"],
            "reason": POSITION_REASONS[top["position"]],
        },
        "alternatives": [
            {"position": item["position"], "name": item["name"], "index": item["index"]}
            for item in ranked[1:3]
        ],
        "scores": ranked,
        "consistency_percent": consistency,
        "confidence": confidence,
        "margin": margin,
        "title": title,
        "narrative": narrative,
        "signal_label": signal_label,
        "signal_narrative": signal_narrative,
        "guide": f"可以先用「{top['name']}」开始一场模拟面试，系统会按该岗位的题目出题。",
    }
