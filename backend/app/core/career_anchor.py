"""极简职业锚定测试：5 道选择题，推荐最匹配的面试岗位

这是「引导入口」，不是心理测评：题目只问工作偏好的日常表现（先做什么、
哪类成果有成就感），每项给岗位加分，答完直接给出岗位建议并引导进入该岗位
的模拟面试。**不做能力判定**，也不输出性格标签。

岗位 code 与 positions 表一致；本模块只负责题目与计分，岗位是否开放、
展示名如何由接口层查库决定。
"""

# 岗位 code（与 positions 表对齐）
POSITIONS = ("backend", "frontend", "algorithm", "test_engineer", "system_design")

# 5 道题 × 4 选项。scores 只写非零项，未列出的岗位该项得 0 分。
ANCHOR_QUESTIONS: list[dict] = [
    {
        "id": "q1",
        "text": "接到一个新需求，你最想先动手做哪一部分？",
        "options": [
            {
                "key": "A",
                "text": "把服务拆成模块，先定好接口和数据怎么流转",
                "scores": {"backend": 2, "system_design": 1},
            },
            {
                "key": "B",
                "text": "把页面结构和交互流程先画出来",
                "scores": {"frontend": 3},
            },
            {
                "key": "C",
                "text": "想清楚数据处理方式，估算规模与复杂度",
                "scores": {"algorithm": 3},
            },
            {
                "key": "D",
                "text": "先列出哪些边界情况可能出问题",
                "scores": {"test_engineer": 3},
            },
        ],
    },
    {
        "id": "q2",
        "text": "排查一个线上问题时，你最习惯从哪入手？",
        "options": [
            {
                "key": "A",
                "text": "看服务日志和调用链，定位是哪个环节出错",
                "scores": {"backend": 2, "system_design": 2},
            },
            {
                "key": "B",
                "text": "按用户的操作路径复现一遍",
                "scores": {"frontend": 2, "test_engineer": 1},
            },
            {
                "key": "C",
                "text": "分析性能瓶颈和数据规模带来的影响",
                "scores": {"algorithm": 2, "system_design": 1},
            },
            {
                "key": "D",
                "text": "检查各种边界条件和异常分支有没有被覆盖",
                "scores": {"test_engineer": 3},
            },
        ],
    },
    {
        "id": "q3",
        "text": "哪种成果最让你有成就感？",
        "options": [
            {
                "key": "A",
                "text": "接口稳定，系统在流量上来时依然扛得住",
                "scores": {"backend": 2, "system_design": 1},
            },
            {
                "key": "B",
                "text": "用户说这个页面用起来顺手、看着舒服",
                "scores": {"frontend": 3},
            },
            {
                "key": "C",
                "text": "程序跑得更快，结果也更准确",
                "scores": {"algorithm": 3},
            },
            {
                "key": "D",
                "text": "上线后缺陷率明显下降，问题提前被拦住",
                "scores": {"test_engineer": 3},
            },
        ],
    },
    {
        "id": "q4",
        "text": "空闲时你更愿意钻研哪类内容？",
        "options": [
            {
                "key": "A",
                "text": "数据库、缓存与分布式一致性",
                "scores": {"backend": 2, "system_design": 2},
            },
            {
                "key": "B",
                "text": "浏览器渲染机制与前端工程化",
                "scores": {"frontend": 3},
            },
            {
                "key": "C",
                "text": "算法复杂度、模型与性能调优",
                "scores": {"algorithm": 3},
            },
            {
                "key": "D",
                "text": "测试框架、质量度量与自动化",
                "scores": {"test_engineer": 2, "system_design": 1},
            },
        ],
    },
    {
        "id": "q5",
        "text": "在团队里，你更像哪种角色？",
        "options": [
            {
                "key": "A",
                "text": "把各个模块拼起来、保证整条链路能跑通的人",
                "scores": {"backend": 1, "system_design": 2},
            },
            {
                "key": "B",
                "text": "打磨体验细节、让产品更好用的人",
                "scores": {"frontend": 3},
            },
            {
                "key": "C",
                "text": "愿意啃最难那块硬骨头的人",
                "scores": {"algorithm": 3},
            },
            {
                "key": "D",
                "text": "守住最后一道质量关的人",
                "scores": {"test_engineer": 3},
            },
        ],
    },
]

# 题目 ID → 选项 key → 选项（校验与计分共用）
_QUESTION_INDEX = {
    q["id"]: {opt["key"]: opt for opt in q["options"]} for q in ANCHOR_QUESTIONS
}

# 平分时的固定顺序：保证同样答案永远给同样推荐（不依赖 dict 顺序）
_PRIORITY = {code: index for index, code in enumerate(POSITIONS)}


def public_questions() -> list[dict]:
    """下发给前端的题目（剥掉计分权重——权重不该让考生看见）"""
    return [
        {
            "id": q["id"],
            "text": q["text"],
            "options": [{"key": opt["key"], "text": opt["text"]} for opt in q["options"]],
        }
        for q in ANCHOR_QUESTIONS
    ]


def validate_answers(answers: dict[str, str]) -> None:
    """校验 5 题全部作答且选项合法；不合法抛 ValueError（接口层转 400）

    不做「缺一题按默认算」：漏答会让推荐结果悄悄偏向某个岗位，而考生
    不知道自己答漏了。
    """
    expected = {q["id"] for q in ANCHOR_QUESTIONS}
    missing = expected - set(answers)
    if missing:
        raise ValueError(f"还有 {len(missing)} 道题未作答：{', '.join(sorted(missing))}")
    unknown = set(answers) - expected
    if unknown:
        raise ValueError(f"未知题目：{', '.join(sorted(unknown))}")
    for qid, key in answers.items():
        if key not in _QUESTION_INDEX[qid]:
            raise ValueError(f"题目 {qid} 的选项非法：{key}")


def score_answers(answers: dict[str, str]) -> dict[str, int]:
    """按选项权重累计各岗位得分（调用前先 validate_answers）"""
    scores = {code: 0 for code in POSITIONS}
    for qid, key in answers.items():
        for code, points in _QUESTION_INDEX[qid][key]["scores"].items():
            scores[code] += points
    return scores


def rank_positions(scores: dict[str, int], enabled: set[str]) -> list[tuple[str, int]]:
    """只在已开放岗位里排序：零分岗位也要排在后面，而不是被推荐

    排序键 = (分数倒序, 固定优先级)。同分时推荐谁必须稳定——否则同样的
    答案在两次请求里可能得到不同建议。
    """
    candidates = [(code, scores.get(code, 0)) for code in POSITIONS if code in enabled]
    candidates.sort(key=lambda item: (-item[1], _PRIORITY[item[0]]))
    return candidates


def build_reason(position_name: str, score: int, second_score: int) -> str:
    """推荐理由：只陈述选择倾向与得分差距，不夸大成「能力很强」

    用与第二名的分差判断，而不是 score/满分：5 道题里各岗位权重不同，
    拿一个理论满分做分母会把「都答得分散」也说成高匹配。
    """
    if score <= 0:
        return f"你的选择没有特别偏向某个方向，{position_name} 是当前可用岗位中的默认推荐。"
    gap = score - second_score
    if gap >= 3:
        return f"你的选择明显集中在{position_name}相关的任务上（{score} 分，领先第二名 {gap} 分）。"
    if gap >= 1:
        return f"你的选择在多个方向间有交叉，{position_name}的匹配度最高（{score} 分，领先第二名 {gap} 分）。"
    return f"几个方向的得分非常接近，{position_name}按默认顺序排在前面（与第二名同为 {score} 分）。"
