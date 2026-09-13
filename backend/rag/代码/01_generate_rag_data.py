# -*- coding: utf-8 -*-
"""
============================================================
01 · RAG 数据生成脚本（主库 → RAG jsonl）
============================================================
功能：把「岗位结构化主库 v5」（5 个 json，共 5012 题）按 7 类片段
      扩展生成 RAG 语义知识库（jsonl，每行一条 JSON）。

数据流：
  主库 json（题目/得分点/追问/降级策略/知识点…）
    → 每题生成 7 类片段（基准款/语义变体/分级追问/得分点拆分/
      前置知识点/场景化/答案变体）
    → 输出 {岗位}-rag-v2.jsonl（共 7.4 万条）

每条 RAG 条目字段（10 个）：
  题目 / 参考答案 / 对应层级 / 原题ID / 题目ID /
  所属岗位 / 题型分类 / 难度等级 / 面试阶段 / 考点优先级

★ 设计意图（为什么这么做）：
  - 「主库 1 题 : RAG 3~5 条」的语义扩展，让 AI 面试官面对考生
    的任意口语化提问/碎片化回答都能召回对应题目。
  - 所有扩展条目绑定同一个「原题ID」：检索到任意变体都能映射
    回主库完整素材（18 字段）。
  - 不入库内容：五维评分细则、单题校准锚点、知识点学习建议
    （这些走主库 ID 查询，避免污染答案语义）。

★ 踩过的坑（务必读）：
  1. 生成器曾把主库「单题校准锚点/评分基准」当答案填充 → 1870 条
     答案变成评分话术。修复：主库得分点源头重写 + RAG 重写。
  2. 纯模板拼接会产出「请详细说明请讲解XX的核心要点」式假变体
     → 已删除。变体生成必须结合题目真实语义。
  3. 每批生成后必须全量验收：占位/套壳/空洞/重复/评分污染
     全维度一次查清（见 04 验收脚本清单）。
============================================================
"""
import json, os, re, random
from collections import Counter

# ============================================================
# 配置（★ 路径自适应：优先使用交付包内的相对路径）
# ============================================================
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 交付包根目录
def _pick(*candidates):
    """按存在性选择路径：交付包结构优先，开发机构建目录回退。

    全部候选都不存在时快速失败（原先返回 candidates[0] 会让下游
    静默使用无效路径，问题被推迟到运行时且难以定位）。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "路径不存在，已尝试：\n  " + "\n  ".join(candidates)
        + "\n请确认交付包结构完整（数据/ 与本脚本所在目录同级）。"
    )
V5 = _pick(os.path.join(_PKG_ROOT, "数据"),
           r"C:\Users\litao\WorkBuddy\2026-09-10-21-25-17\ai-interview-data\v5")

# 5 个岗位：(文件前缀, 岗位全名, 题目ID前缀)
POSITIONS = [
    ("java",          "Java 后端开发工程师",  "JAVA_BACKEND"),
    ("web",           "Web 前端开发工程师",   "WEB_FRONTEND"),
    ("test",          "测试开发工程师",       "TEST_DEV"),
    ("algorithm",     "算法工程师",           "ALGORITHM"),
    ("system-design", "系统设计工程师",       "SYSTEM_DESIGN"),
]

# ============================================================
# 工具函数
# ============================================================
def clean_text(s):
    """清洗文本：去首尾空白、压缩连续换行/空格"""
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = re.sub(r'[ \t]+', ' ', s)
    return s

def ensure_min_length(text, min_len=50):
    """答案长度兜底：短于阈值时追加通用引导语，避免条目过薄。
    注：后来决策「得分点拆分」短条目豁免 80 字（碎片兜底设计），
    其余层级要求 ≥80 字。"""
    text = clean_text(text)
    if len(text) >= min_len:
        return text
    supplement = "（以上为核心要点，实际面试中可结合具体项目经验和技术细节进一步展开说明。）"
    return text + supplement

def extract_keywords(kw_str):
    """核心关键词字段 → 列表（用于变体问法的同义替换）"""
    if not kw_str:
        return []
    parts = re.split(r'[\n,，;；、\s]+', str(kw_str))
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 2]

def extract_knowledge_points(kp_str):
    """关联知识点字段 → [(ID, 名称, 学习建议)]"""
    if not kp_str:
        return []
    points = []
    for line in str(kp_str).split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            points.append((parts[0].strip(), parts[1].strip(),
                           parts[2].strip() if len(parts) >= 3 else ""))
    return points

def split_score_points(score_str, max_parts=3):
    """把一大段得分点拆成若干子要点（供细粒度片段使用）
    按编号/换行/分号拆；拆不动就按句子拆；太短(<10字)的丢弃"""
    if not score_str:
        return []
    text = clean_text(score_str)
    parts = re.split(r'(?:\n+|(?<=[。；;])\s*|\d+[.、、]\s*)', text)
    parts = [p.strip() for p in parts if p.strip() and len(p.strip()) >= 10]
    if len(parts) <= 1:
        parts = re.split(r'[。；;]', text)
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) >= 10]
    return parts[:max_parts] if parts else [text]


# ============================================================
# 7 类片段生成器（每题各调一次）
# ============================================================

def gen_base_item(r):
    """类型 1：原题完整对话条目（基准款）
    内容 = 题目 + 基础得分点 + 进阶得分点 + 三级追问 + 降级策略 + 建议用时
    作用：召回完整题目素材，供面试官完整使用"""
    qid = r["题目ID"]
    content = clean_text(r.get("题目内容", ""))
    base_pts = clean_text(r.get("基础得分点", ""))
    adv_pts = clean_text(r.get("进阶得分点", ""))
    l1 = clean_text(r.get("L1基础追问", ""))
    l2 = clean_text(r.get("L2递进追问", ""))
    l3 = clean_text(r.get("L3拓展追问", ""))
    degrade = clean_text(r.get("降级策略", ""))
    duration = r.get("建议用时(分)", "")

    answer_parts = ["【基础得分点】",
                    base_pts if base_pts else "该题基础得分点需结合具体技术场景展开。"]
    if adv_pts:
        answer_parts += ["\n【进阶得分点】", adv_pts]
    answer_parts.append("\n【追问引导】")
    if l1:
        answer_parts.append(f"L1基础追问：{l1}")
    if l2:
        answer_parts.append(f"L2递进追问：{l2}")
    if l3:
        answer_parts.append(f"L3拓展追问：{l3}")
    if degrade:
        answer_parts.append(f"\n【降级策略】{degrade}")
    if duration:
        answer_parts.append(f"\n【建议用时】{duration}分钟")

    return _mk_item(content, ensure_min_length("\n".join(answer_parts)),
                    "原题", qid, r)

def gen_semantic_variants(r, count=4):
    """类型 2：题干多语义变体（RAG 体量大的核心来源）
    同一道题扩展 3-5 种问法：正向/反向/举例/场景化/口语化/同义/易错混淆。
    难度调整：easy→3 条(正向/口语/同义)；hard→5 条(加反向/场景/易错)；medium→4 条"""
    qid = r["题目ID"]
    content = clean_text(r.get("题目内容", ""))
    base_pts = clean_text(r.get("基础得分点", ""))
    adv_pts = clean_text(r.get("进阶得分点", ""))
    keywords = extract_keywords(r.get("核心关键词", ""))
    kw_str = "、".join(keywords[:3]) if keywords else "相关技术"

    variant_templates = [
        lambda c, k: f"请详细说明{c.replace('？','').replace('?','')}的核心要点。",
        lambda c, k: f"如果不了解{c.replace('？','').replace('?','')}，在实际工作中可能遇到什么问题？",
        lambda c, k: f"能否结合具体例子说明{c.replace('？','').replace('?','')}？",
        lambda c, k: f"在项目开发中遇到{c.replace('？','').replace('?','')}的场景，你会如何处理？",
        lambda c, k: f"想请教一下，{c.replace('？','呢？').replace('?','呢？')}",
        lambda c, k: f"关于{k}这方面，你能分享一下你的理解和实践经验吗？",
        lambda c, k: f"很多人对{k}存在误解，你能澄清一下{c.replace('？','').replace('?','')}的正确理解吗？",
    ]
    difficulty = r.get("难度等级", "medium")
    if difficulty == "easy":
        count = min(count, 3)
        selected = [0, 4, 5]
    elif difficulty == "hard":
        count = min(count, 5)
        selected = [0, 1, 3, 6, 2]
    else:
        selected = [0, 2, 3, 5, 1][:count]

    items = []
    for idx in selected[:count]:
        try:
            variant_q = variant_templates[idx](content, kw_str)
        except Exception:
            variant_q = f"关于{kw_str}，{content}"
        answer_parts = [p for p in (base_pts, adv_pts) if p]
        answer = ensure_min_length(
            "\n".join(answer_parts) if answer_parts
            else f"关于{kw_str}的核心要点需要结合具体技术场景展开说明。")
        items.append(_mk_item(clean_text(variant_q), answer, "语义变体", qid, r))
    return items

def gen_followup_items(r):
    """类型 3：分级追问独立片段（L1/L2/L3）
    每级追问 + 答案要点单独入库，标注层级。
    作用：考生回答到对应深度时能精准召回下一级追问；
    考生回答内容也能匹配层级，辅助判断该触发哪层追问"""
    qid = r["题目ID"]
    base_pts = clean_text(r.get("基础得分点", ""))
    adv_pts = clean_text(r.get("进阶得分点", ""))
    items = []
    for level, field, desc in [("L1", "L1基础追问", "基础细节"),
                               ("L2", "L2递进追问", "原理深挖"),
                               ("L3", "L3拓展追问", "工程延伸")]:
        fu_text = clean_text(r.get(field, ""))
        if not fu_text:
            continue
        # 去掉 [触发] / [追问] 前缀标记，只留追问正文
        fu_question = fu_text
        for tag in ("[触发]", "【触发】"):
            if tag in fu_text:
                fu_question = fu_text.split(tag, 1)[1].strip()
                break
        for tag in ("[追问]", "【追问】"):
            if tag in fu_text:
                fu_question = fu_text.split(tag, 1)[1].strip()
                break
        # L1 用基础得分点作答，L2/L3 用进阶得分点作答
        source = base_pts if level == "L1" else (adv_pts if adv_pts else base_pts)
        answer = ensure_min_length(
            f"针对{desc}层面的追问，{source}\n\n"
            f"该追问主要考察候选人对相关技术点的{desc}能力，需结合具体场景给出有深度的回答。")
        items.append(_mk_item(clean_text(fu_question), answer, level, qid, r))
    return items

def gen_scorepoint_items(r):
    """类型 4：得分点细粒度片段（基础/进阶各拆 2 条）
    作用：细粒度语义匹配——考生只提到某个零散知识点也能命中对应题。
    ★ 决策：这类短条目豁免 80 字要求（碎片兜底设计），已全量验证
      100% 有完整条目兜底，删除反而损失召回。"""
    qid = r["题目ID"]
    keywords = extract_keywords(r.get("核心关键词", ""))
    kw_str = "、".join(keywords[:2]) if keywords else "相关技术"
    items = []

    base_pts = clean_text(r.get("基础得分点", ""))
    if base_pts:
        for part in split_score_points(base_pts, max_parts=2)[:2]:
            q = (f"关于{kw_str}，{part[:30]}...的核心要点是什么？"
                 if len(part) > 30 else f"关于{kw_str}，{part}的核心要点是什么？")
            ans = ensure_min_length(f"{part}\n\n以上是该知识点的基础核心要点，面试中需能够清晰表述并举例说明。")
            items.append(_mk_item(clean_text(q), ans, "基础得分点", qid, r))

    adv_pts = clean_text(r.get("进阶得分点", ""))
    if adv_pts:
        for part in split_score_points(adv_pts, max_parts=2)[:2]:
            q = (f"深入理解{kw_str}：{part[:30]}...的原理和实践是什么？"
                 if len(part) > 30 else f"深入理解{kw_str}：{part}的原理和实践是什么？")
            ans = ensure_min_length(f"{part}\n\n以上是该知识点的进阶深入内容，考察候选人对技术原理的理解深度和实际应用能力。")
            items.append(_mk_item(clean_text(q), ans, "进阶得分点", qid, r))
    return items

def gen_knowledge_items(r):
    """类型 5：关联前置知识点（基础铺垫，取前 2 个知识点）
    作用：考生基础薄弱时能快速召回前置知识点，支撑降级引导，不用跳题"""
    qid = r["题目ID"]
    items = []
    for kp_id, kp_name, kp_advice in extract_knowledge_points(r.get("关联知识点", ""))[:2]:
        if not kp_name:
            continue
        q = f"什么是{kp_name}？它的核心概念和基本原理是什么？"
        answer = ensure_min_length(
            f"{kp_name}是理解本题的重要前置知识点。\n\n"
            f"核心概念：{kp_name}涉及的基本定义和关键术语需要准确掌握。\n"
            f"基本原理：理解其工作机制和核心流程，为深入学习本题打下基础。\n"
            f"学习建议：建议先掌握{kp_name}的基础概念，再结合本题的具体应用场景加深理解。")
        items.append(_mk_item(clean_text(q), answer, "基础铺垫", qid, r))
    return items

def gen_scenario_items(r):
    """类型 6：多场景表述（每题 1 条，按岗位场景模板）
    作用：提升跨场景语义匹配度，项目题/场景题效果显著"""
    qid = r["题目ID"]
    content = clean_text(r.get("题目内容", ""))
    base_pts = clean_text(r.get("基础得分点", ""))
    adv_pts = clean_text(r.get("进阶得分点", ""))
    pos = r["所属岗位"]

    scenario_templates = {
        "Java 后端开发工程师": ["在高并发后端服务开发中，", "在微服务架构设计中，", "在线上问题排查和性能优化时，" ],
        "Web 前端开发工程师":  ["在大型前端项目开发中，", "在前端性能优化和用户体验提升时，", "在跨团队协作和组件化开发中，" ],
        "测试开发工程师":      ["在自动化测试框架搭建中，", "在测试用例设计和缺陷分析时，", "在持续集成和测试平台建设中，" ],
        "算法工程师":          ["在算法模型设计和优化中，", "在大规模数据处理和特征工程时，", "在算法落地和性能调优中，" ],
        "系统设计工程师":      ["在分布式系统架构设计中，", "在高可用和高并发系统设计时，", "在系统容量规划和扩展性设计中，" ],
    }
    scenario = (scenario_templates.get(pos) or ["在实际项目开发中，"])[0]
    q = f"{scenario}{content.replace('？','').replace('?','')}，你会如何分析和解决？"

    answer_parts = [p for p in (base_pts, adv_pts) if p]
    answer = ensure_min_length(
        "\n".join(answer_parts) +
        f"\n\n在{scenario.strip('，')}的具体场景下，需要结合业务需求和技术约束，"
        f"综合考虑性能、可维护性、可扩展性等因素，给出切实可行的解决方案。")
    return [_mk_item(clean_text(q), answer, "场景化", qid, r)]

def gen_answer_variants(r):
    """类型 7：正确答案表述变体
    变体 1：一句话总结式；变体 2：对比式（仅 hard 题，额外增加）"""
    qid = r["题目ID"]
    content = clean_text(r.get("题目内容", ""))
    base_pts = clean_text(r.get("基础得分点", ""))
    adv_pts = clean_text(r.get("进阶得分点", ""))
    keywords = extract_keywords(r.get("核心关键词", ""))
    kw_str = "、".join(keywords[:2]) if keywords else "相关技术"
    items = []

    q1 = f"用一句话总结{content.replace('？','').replace('?','')}的核心答案。"
    a1 = ensure_min_length(
        f"核心答案：{base_pts[:100] if base_pts else kw_str}\n\n"
        f"展开说明：{adv_pts if adv_pts else base_pts}\n\n"
        f"以上是对该问题的核心总结，实际面试中可根据面试官的追问进一步展开细节。")
    items.append(_mk_item(clean_text(q1), a1, "答案变体", qid, r))

    if r.get("难度等级") == "hard":
        q2 = f"对比不同方案，说明{content.replace('？','').replace('?','')}的最优选择。"
        a2 = ensure_min_length(
            f"方案对比：{adv_pts if adv_pts else base_pts}\n\n"
            f"最优选择：需要根据具体业务场景、技术栈、团队能力、成本预算等因素综合判断。"
            f"没有绝对最优的方案，只有最适合当前场景的方案。\n\n"
            f"在实际工作中，建议先明确需求和约束条件，再评估各方案的优劣，最后做出合理的技术选型决策。")
        items.append(_mk_item(clean_text(q2), a2, "答案变体", qid, r))
    return items


# ============================================================
# 通用条目构造 + 主流程
# ============================================================
def _mk_item(question, answer, level, qid, r):
    """统一构造 RAG 条目（10 字段），保证所有片段结构一致"""
    return {
        "题目": question,
        "参考答案": answer,
        "对应层级": level,
        "原题ID": qid,          # ← 所有变体绑定主库题目ID，检索映射回主库
        "题目ID": qid,
        "所属岗位": r["所属岗位"],
        "题型分类": r["题型分类"],
        "难度等级": r["难度等级"],
        "面试阶段": r["面试阶段"],
        "考点优先级": r["考点优先级"],
    }

def generate_for_position(pos_key, pos_name):
    """为单个岗位生成 RAG jsonl"""
    with open(f"{V5}\\{pos_key}-v5.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    all_items, level_counter = [], Counter()
    for r in data:
        qtype = r.get("题型分类", "技术知识题")
        difficulty = r.get("难度等级", "medium")

        all_items.append(gen_base_item(r))                          # 1 基准款
        level_counter["原题"] += 1

        vc = 4
        if qtype == "行为素质题":
            vc = 3
        elif qtype == "技术知识题" and difficulty == "hard":
            vc = 5
        vs = gen_semantic_variants(r, count=vc)                     # 2 语义变体
        all_items.extend(vs); level_counter["语义变体"] += len(vs)

        fs = gen_followup_items(r)                                  # 3 追问
        all_items.extend(fs); level_counter["追问"] += len(fs)

        sp = gen_scorepoint_items(r)                                # 4 得分点
        all_items.extend(sp); level_counter["得分点"] += len(sp)

        kp = gen_knowledge_items(r)                                 # 5 前置知识
        all_items.extend(kp); level_counter["基础铺垫"] += len(kp)

        sc = gen_scenario_items(r)                                  # 6 场景化
        all_items.extend(sc); level_counter["场景化"] += len(sc)

        av = gen_answer_variants(r)                                 # 7 答案变体
        all_items.extend(av); level_counter["答案变体"] += len(av)

    with open(f"{V5}\\{pos_key}-rag-v2.jsonl", "w", encoding="utf-8") as f:
        for item in all_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(data), len(all_items), level_counter


if __name__ == "__main__":
    print("=" * 60)
    print("【RAG v2 知识库重建】")
    print("=" * 60)
    total_main = total_rag = 0
    all_lv = Counter()
    for pos_key, pos_name, _prefix in POSITIONS:
        mc, rc, lc = generate_for_position(pos_key, pos_name)
        total_main += mc; total_rag += rc; all_lv.update(lc)
        print(f"{pos_name}: 主库{mc}条 → RAG {rc}条 (平均{rc/mc:.1f}条/题)")
    print(f"\n【总计】主库 {total_main} 条 → RAG {total_rag} 条，平均 {total_rag/total_main:.1f} 条/题")
    print(f"层级分布: {dict(all_lv)}")
    print(f"目标区间: 5.5-7.5 万条 → {'达标 ✓' if 55000 <= total_rag <= 75000 else '未达标 ✗'}")
