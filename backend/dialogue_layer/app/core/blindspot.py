# -*- coding: utf-8 -*-
"""
blindspot.py · 知识盲区诊断（纯结构化，不加 LLM 调用）
============================================================
把一场面试的逐轮记录摊平成两张表，给 3 号写评估报告用：

    knowledge_points —— 扁平明细：每个考过的知识点考了几次、哪几轮、考成什么样
    domains          —— 领域汇总：哪个领域薄弱
    recommendations  —— 学习资源推荐（赛题 4a）：把薄弱考点接到资源样例文件上

⚠️ 后两张表是加法，第三张（recommendations）**只在 /finish 与 /result 里出现**
   —— diagnose() 只被 session.finish() 调用，所以「交卷前不泄题」是结构上封住的。
   A11_RECOMMEND=0 时该键整个不出现（与加这个功能之前逐字节相同）。
   它的实现全在 resources.py，本文件只负责「挑出薄弱考点、把结果挂上去」。

为什么是**扁平表 + 小汇总**两张，而不是一棵嵌套的树：3 号既要「薄弱领域 top-3」
（要汇总）又要「哪个知识点没覆盖」（要明细）。纯嵌套会逼它自己去遍历；
扁平表 + 汇总表两张都能直接 df 化。

为什么单独一个文件：diagnose() 是纯函数，可以像 smoke_test.py 的 _bare_round()
那样用合成数据单测，不需要起会话/题库/模型。塞进已经 800 行的 session.py
会让那个状态机更难读。

⚠️ 三条口径约定（改之前先读）：

  1. **遍历 raw["rounds"]，包含 attempts == [] 的轮**。finish() 里参与评分的
     是 scorable（只含非空轮），而 raw["rounds"] 含全部轮 —— 这个口径差是
     **既有的正确设计**（评不了分的轮也要留痕）。诊断必须跟 rounds 走，
     否则「出了题没答」这件事在报告里会整个消失。
  2. **绝不用 RoundRecord.last_score**：session.py 在 attempts 为空时返回 0.0，
     直接拿来诊断会把「出了题没答」读成「考了 0 分」。一律用本文件里显式
     返回 None 的取值。
  3. **hit 是 Optional[bool]，绝不用 False 冒充「没答上来」**：
     True  = 有一轮 reranker 客观判他答到了（复用既有阈值 LEVEL_L1_MIN，不自创）
     False = 有客观依据地判他没答到
     None  = 无法判定（该轮没答题，或 reranker 全程不可用）
     与 reranker_5 / tech_gap 的「None = 数据不足，不是 0」约定一致。
"""
from typing import Optional

from app import config
from app.core import kg as kgmod
from app.core.kg import UNCLASSIFIED
from app.core.resources import recommend

# ============================================================
# 软标签：不是知识点，诊断时必须滤掉
# ============================================================
# 这张表与 `06_build_kg.py`（图谱构建脚本）里的 SOFT_TAGS **逐字相同** ——
# 那边用它决定「这些标签不进图」，理由是 100+ 道题共用、没有任何区分度。
#
# ⚠️ 但**光在图谱侧滤是不够的**：本模块取知识点走的是 `kg.kp_map()`，
#    也就是「主库 ∪ 图谱」的并集，而**主库是真值源** —— 软标签会从主库那一侧
#    原样兜回来。实测（2026-09-23，11 场真实会话）「未归类」桶里混进了
#    职业素养 ×9、场景设计 ×7、Java版本特性 ×4，全是这张表里的。
#    后果：3 号 写评估报告时，「未归类」这个榜首领域里躺着「职业素养」
#    —— 那不是知识盲区，是分类噪声。
#
# 为什么**不 import** 而是抄一份：`06_build_kg.py` 在数据目录
# （`D:\A11-Data\kg-enhanced\`）里，是构建工具、不在 app 包内，也不该被运行时的
# app 依赖。所以这里是**镜像**：那张表变了，这张要跟着变。
# 表尾那行注释记了它的出处，便于核对。
SOFT_TAGS = {
    "岗位核心能力", "Java版本特性", "场景设计", "职业素养",
    "测试中有哪些风险", "工程实践", "编码规范", "设计模式概述",
}   # 出处：D:\A11-Data\kg-enhanced\06_build_kg.py:88（同名常量）


def _is_soft(title: str) -> bool:
    """标题是不是软标签。空标题按「不是」处理 —— 空标题由 kp_map 兜底成 kp_id，
    那种情况下滤掉它反而会让知识点凭空消失。"""
    return bool(title) and title.strip() in SOFT_TAGS


def _kp_map(kg, qid: str, knowledge_points: Optional[list[dict]]) -> dict[str, dict]:
    """
    取本题的知识点并集。

    ⚠️ 必须与避重走**同一个函数**（`kg.kp_map`）—— 否则同一个 kp 会出现
    「避重说考过、盲区说没考过」这种两种说法，查起来极痛苦。

    kg 不可用时退化成只按主库 kp 归组，**键名完全不变**，3 号的解析逻辑
    不用分两种情况写。这里的退化分支复用 `kg.kp_map_bank()` —— 与
    `KGIndex.kp_map` 的图谱侧用的是同一份主库视图，不手抄第二份。
    """
    if kg is not None:
        return kg.kp_map(qid, knowledge_points)
    return {kid: {"title": title or kid, "weight": 1.0, "src": "bank"}
            for kid, title in kgmod.kp_map_bank(knowledge_points).items()}


def _round_facts(rec) -> dict:
    """
    单轮的客观事实。**不复用 RoundRecord.last_score / last_ok** ——
    那两个属性在 attempts 为空时返回 0.0 / True，是给评分链路用的语义，
    拿来诊断会凭空造出「考了 0 分」和「reranker 正常」两条假信息。
    """
    att = rec.attempts[-1] if rec.attempts else None
    # reranker 失败时 hit_scores 返回的是**兜底 50.0**，那个假分不能进任何统计
    ok_scores = [float(a.reranker_score) for a in rec.attempts if a.reranker_ok]
    return {
        "attempts": len(rec.attempts),
        "reranker_ok": (bool(att.reranker_ok) if att else None),
        "best_score": (max(ok_scores) if ok_scores else None),
        "last_score": (float(att.reranker_score) if (att and att.reranker_ok) else None),
        "five_dim": (dict(rec.five_dim) if rec.five_dim else None),
        "degrade_used": int(rec.degrade_used or 0),
        "follow_ups_used": int(rec.follow_ups_used or 0),
        # 未命中的点取**最后一次回答**的 —— 追问到底之后的那份才反映最终状态
        "base_miss": list(att.base_misses) if att else [],
        "adv_miss": list(att.adv_misses) if att else [],
    }


def _avg_five_dim(rounds_facts: list[dict]) -> dict:
    """一组轮次的五维均分。没数据的维度是 None，不是 0。"""
    out = {}
    for d in config.DIMENSIONS:
        vals = [f["five_dim"][d] for f in rounds_facts
                if f["five_dim"] and isinstance(f["five_dim"].get(d), (int, float))]
        out[d] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def diagnose(rounds: list, kg=None, job: Optional[str] = None) -> dict:
    """
    纯函数：list[RoundRecord] + KGIndex|None (+ 岗位名) → 诊断结构。

    kg=None 时**不抛异常**，全部归入「未归类」、domain_known=0.0，键名不变。

    `job` **只透给 4a 的知识库检索做岗位过滤**，不参与本函数的任何统计口径
    （kp_total / domain_known / hit 判定都与它无关）。不传（None）时行为
    与加这个参数之前**逐字节相同** —— 所以冒烟测试里那十处
    `diagnose([...], kg)` 的调用一个都不用改。
    """
    facts: list[tuple[object, dict]] = [(r, _round_facts(r)) for r in rounds]

    # ---------- 逐轮摊平到知识点上 ----------
    kps: dict[str, dict] = {}
    rounds_without_attempts: list[int] = []
    rounds_scored = 0
    q_full_domain = 0            # 本题所有 kp 都归得了类的轮次数

    for rec, f in facts:
        if not rec.attempts:
            rounds_without_attempts.append(rec.round_no)
        if f["five_dim"]:
            rounds_scored += 1

        km = _kp_map(kg, rec.question_id, rec.knowledge_points)
        # 软标签在**汇总处**再筛一次（图谱侧已筛过，见 SOFT_TAGS 那段注释）。
        # ⚠️ 筛在**收集前**、而不是只滤掉 domains[].weak_kps 里的名字：
        #    只滤名字的话，kps_total / kps_weak 还是把它算进去，报告就会出现
        #    「未归类：kps_weak=9，weak_kps=[]」这种自相矛盾的一行，
        #    比不筛更难解释。收集前筛掉，计数与清单天然一致。
        #    代价：kp_total / domain_known 这些**比率**会随之变化 ——
        #    变的方向是对的（分母里少了噪声），但 3 号 跨版本对比时要知道这件事。
        km = {kid: v for kid, v in km.items() if not _is_soft(v["title"])}

        if km and all(_level_of(kg, kid, v["title"])[0] != UNCLASSIFIED
                      for kid, v in km.items()):
            q_full_domain += 1

        for kid, v in km.items():
            domain, subclass = _level_of(kg, kid, v["title"])
            e = kps.get(kid)
            if e is None:
                e = kps[kid] = {
                    "kp_id": kid, "title": v["title"],
                    "domain": domain, "subclass": subclass,
                    "hit": None, "rounds": [], "question_ids": [],
                    "appearances": 0, "src": v["src"],
                    "best_score": None, "last_score": None,
                    "per_round": [],
                }
            e["appearances"] += 1
            if rec.round_no not in e["rounds"]:
                e["rounds"].append(rec.round_no)
            if rec.question_id not in e["question_ids"]:
                e["question_ids"].append(rec.question_id)
            e["src"] = "both" if (e["src"] == "both" or v["src"] == "both") else e["src"]
            e["per_round"].append({
                "round": rec.round_no,
                "question_id": rec.question_id,
                "attempts": f["attempts"],
                "reranker_ok": f["reranker_ok"],
                "best_score": f["best_score"],
                "last_score": f["last_score"],
                "five_dim": f["five_dim"],
                "degrade_used": f["degrade_used"],
                "base_miss": f["base_miss"],
                "adv_miss": f["adv_miss"],
            })
            # 分数取各覆盖轮里的最好/最后 —— 均为 None 表示没有可用数据
            for key in ("best_score", "last_score"):
                if f[key] is not None:
                    e[key] = (f[key] if e[key] is None
                              else (max(e[key], f[key]) if key == "best_score" else f[key]))

    # ---------- hit 判定 + 领域汇总 ----------
    domains: dict[str, dict] = {}
    kp_hit = kp_weak = kp_unknown = 0
    dom_resolved = 0

    for e in kps.values():
        # hit：任一覆盖轮**客观判他答到了**。
        # 复用既有已校准的阈值 LEVEL_L1_MIN，不自创一个。
        # p["reranker_ok"] is True 蕴含 p["last_score"] is not None（见 _round_facts）。
        # 注意这里**不看 best_score** —— 若某轮最后一次回答时 reranker 挂了，
        # 这一轮就是「判不了」，不能拿它早先的分数替它下结论。
        judged = [p for p in e["per_round"] if p["reranker_ok"] is True]
        e["hit"] = (any(p["last_score"] >= config.LEVEL_L1_MIN for p in judged)
                    if judged else None)

        if e["hit"] is True:
            kp_hit += 1
        elif e["hit"] is False:
            kp_weak += 1
        else:
            kp_unknown += 1

        if e["domain"] != UNCLASSIFIED:
            dom_resolved += 1

        d = domains.get(e["domain"])
        if d is None:
            d = domains[e["domain"]] = {
                "domain": e["domain"], "kps_total": 0, "kps_weak": 0,
                "rounds": [], "weak_kps": [], "_facts": {},
            }
        d["kps_total"] += 1
        if e["hit"] is not True:
            d["kps_weak"] += 1
            if e["title"] not in d["weak_kps"]:
                d["weak_kps"].append(e["title"])
        for rn in e["rounds"]:
            if rn not in d["rounds"]:
                d["rounds"].append(rn)
        # 按轮去重：同一个领域里两个 kp 命中同一轮时，那一轮的五维分
        # 只该算一次，否则会被按 kp 个数加权，领域均分失真。
        for p in e["per_round"]:
            if p["five_dim"]:
                d["_facts"].setdefault(p["round"], p)

    dom_list = []
    for d in domains.values():
        dom_list.append({
            "domain": d["domain"],
            "kps_total": d["kps_total"],
            "kps_weak": d["kps_weak"],
            "five_dim_avg": _avg_five_dim(list(d["_facts"].values())),
            "rounds": sorted(d["rounds"]),
            "weak_kps": d["weak_kps"],
        })
    # 薄弱的排前面 —— 3 号要的就是「薄弱领域 top-3」
    dom_list.sort(key=lambda x: (-x["kps_weak"], -x["kps_total"], x["domain"]))

    # ---------- 学习资源推荐（赛题 4a；加法，不影响上面任何字段）----------
    # 只在这一个地方算 —— diagnose() 只被 /finish 调用（session.py:1635），
    # 所以 `recommendations` 天然只出现在 /finish 与 /result 里，不会在
    # /next、/chat 期间漏给考生（设计稿 §5 那条边界）。
    # 关掉开关（A11_RECOMMEND=0）时**键整个不出现**，与加这个功能之前逐字节相同。
    kp_list = sorted(kps.values(),
                     key=lambda e: (e["rounds"][0] if e["rounds"] else 0, e["kp_id"]))
    rec_out = recommend(kp_list, job=job) if config.A11_RECOMMEND else None

    n_kp = len(kps) or 0
    summary = {
        "rounds_total": len(rounds),
        "rounds_scored": rounds_scored,
        "rounds_without_attempts": sorted(rounds_without_attempts),
        "kp_total": n_kp,
        "kp_hit": kp_hit,
        "kp_weak": kp_weak,
        "kp_unknown": kp_unknown,
        # ⚠️ domain_known 的分母是**知识点引用**，不是题目。
        #    两个口径差得很远（实测 java：按 kp 是 78%，按题只有 56%，
        #    因为 44% 的题至少有一个 kp 归不了类）。两个都报，免得好人误解。
        "domain_known": (round(dom_resolved / n_kp, 4) if n_kp else 0.0),
        "questions_domain_known": (round(q_full_domain / len(rounds), 4)
                                   if rounds else 0.0),
        "kg_available": kg is not None,
    }
    if rec_out is not None:
        # 推荐能不能用、为什么空 —— 与 kg_error / rag_error 同一条纪律：
        # 「关掉」和「坏了」必须分得开，否则 3 号 会把「没配好」读成「这场没盲区」。
        summary.update({
            "recommend_enabled": True,
            "recommend_ready": rec_out["ready"],
            "recommend_candidates": rec_out["candidates"],   # 够格的候选数（可能 > 展示数）
            "recommend_error": rec_out["error"],
            # 知识库那一层（4a 的「真知识库」参考）。同样是「关掉 / 没装 /
            # 跑了但没命中」三态可分：kb_refs_total=0 且 kb_error="" 就是「跑通了，
            # 这一场没有够分的片段」，不是故障。
            "kb_enabled": rec_out["kb_enabled"],
            "kb_ready": rec_out["kb_ready"],
            "kb_refs_total": rec_out["kb_refs_total"],
            "kb_error": rec_out["kb_error"],
        })

    out = {
        "summary": summary,
        "domains": dom_list,
        "knowledge_points": kp_list,
    }
    if rec_out is not None:
        out["recommendations"] = rec_out["items"]
    return out


def _level_of(kg, kp_id: str, title: str) -> tuple[str, str]:
    """
    domain / subclass 两级兜底：kp_id 直接查 → 标题唯一时按标题查 → 未归类。

    多义标题（比如「数据库」）宁可归「未归类」也不要错归 ——
    错归会让两个不同的知识点被报成同一个，报告里就是错的。
    """
    if kg is None:
        return (UNCLASSIFIED, "")
    got = kg.level_of(kp_id)
    if got[0] != UNCLASSIFIED:
        return got
    by_name = kg.level_of_name(title)
    if by_name:
        return by_name
    return (UNCLASSIFIED, "")
