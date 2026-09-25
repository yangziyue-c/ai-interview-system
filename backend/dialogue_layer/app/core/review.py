# -*- coding: utf-8 -*-
r"""
review.py · 给考生看的「复盘清单」（`/finish` 与 `/result` 的顶层新键 `review`）
============================================================
同一份成绩单上现在有三样东西，**用途不同，别混**：

    raw      给 3 号（评估报告）—— 完整明细，含得分点原文；**脱敏档不给**
    digest   给 1 号（存档）—— 白名单摘要，跨场次聚合用；无论档位都在
    review   给**考生**—— 说人话：这场哪几个考点没答到、下一步练哪个；无论档位都在

**为什么要有它**：`summary` 那段话（LLM 写的）已经在说人话了，但它是**评价** ——
考生看完知道自己「中上」，不知道自己**差在哪、下一步做什么**。而考点级的诊断
（`hit`）本来就有，却只躺在 `raw.blindspots` 里 ⇒ **脱敏档下考生根本看不到**。
review 就是把这份诊断**搬出来、翻成人话、配一个今天就能做的动作**。

⚠️ 八条口径（改之前先读）

  1. **「没答到」全项目只有一条口径：`hit is False`**（与 `practice._weak_of`、
     `growth._wrong_book` 逐字相同）。`hit is None` = 判不了 / 没考过 = **还没覆盖**，
     **不是**漏点 —— 单列 `uncovered[]`，并在 `caveats` 里**明说它不是漏点**。
     （`blindspot.domains[].kps_weak` 用的是更宽的 `hit is not True`，**不许混用**。）

  2. **绝不出现得分点原文**：只出**考点名** + **条数**。`per_round[]`（里面装着
     `base_miss`/`adv_miss` 原文）与 `recommendations[].missed_points` 一律不读。
     它是 `raw` 之外**又一处无论 `A11_RAW_DETAIL` 都会出门**的字段 ⇒ 冒烟里有一条
     拿得分点字面量当针的金丝雀（与 digest 同款）。

  3. **不给百分比、不给「掌握度」、不给预测分**：一场面试只覆盖十来个考点，
     任何比率都是编出来的精度。只给**计数**，而且计数都用**整数**。

  4. 分数 `None` = 「没有数据」，**不是 0 分**；排序时 `None` 排最后，绝不当 0 顶。

  5. **只承诺今天真能做到的事**。文案**不许**写「去看讲解 / 去看优秀范例」——
     可以写的是「回去把第 4 题重讲一遍」「用专项练习重练这个考点」，这两件都真的能做。
     ⚠️ 理由是**能力**还是**上下文**，改代码前先分清（2026-09 的 G 波把前半句证伪了）：
     `POST /model_answer` 现在**做了**，讲解与范例确实能到考生手里 —— 但**不在这个字段里**。
     `review` 挂在 `POST /finish` 的响应上，而那份响应**没有**「这个考点有没有材料」的信息
     （`material` 四态只在 `/growth` 的 `plan.items[]` 里）。⇒ 在这里写「去看讲解」，
     会把考生指到一个**本场可能根本没有材料**的考点上（`not_found` / 资源没开）。
     「能不能给」是 `/model_answer` 的事，「这里该不该承诺」是上下文的事，两回事。
  6. **绝不评价人**：文案只描述「哪个考点没答到 + 下一步做什么」，不写「你的基础很差」
     这类判断 —— 这是给考生看的复盘，不是判决书。

  7. **全函数、绝不抛**：调用点在 `session.finish()` 的收口上，抛了会把整场面试的
     交卷打挂。全程 `.get()`：缺就是缺，缺了照样出一份结构完整的清单。

  8. `A11_REVIEW=0` 时顶层键是 **`None`**（不是 `{}`）：`None` = 「本次响应不含清单」，
     `{}` = 「有清单但是空的」—— 两者混同会让前端把「没开」画成一张空卡片。

  9. **按「考点名 + 领域 + 子类」合并成主题**。题库里同一件事会挂多个 kp_id ——
     实测（27 场真跑）里 `java-backend-kp-4839` 与 `java_backend-kp-soft-28634`
     两条 `title/domain/subclass` 一字不差、题号与漏点条数也一样。不合并的话
     考生会看到「缓存」出现两次，**像是报告坏了**。合并一律**取保守值**：
     漏点条数取 **max**（**不求和** —— 那两个 id 指同一批得分点，求和就是翻倍虚报）、
     分数取 **min**、`hit` 三态取「有 True 即 True」。合并前后**两个口径都报**
     （`counts.topics_*` 是考生看到的，`counts.kps_raw` 与 `digest.kps` 同源同数）。

 10. **给考生看的字符串里不写 markdown**。文案 QA 里发现「按 **主题** 合并过」这句
     一旦前端按纯文本渲染，考生就会读到四个星号。全项目另有**两处**运行时的字符串
     带 `**`（`practice.disclaimer`、`growth.kp_map.note`）—— 那两处**只记录、不修**
     （会改 4 号 已有页面的文字），记在 `owed.md`。本模块是给考生看的新文案，
     从它起**不带 markdown**（加重语气用「」或把句子重写，别用星号）。
"""
from typing import Optional

from app import config
from app.core.kg import UNCLASSIFIED
from app.core.resources import missed_points
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 清单结构版本。**前端可以据此判断字段语义**；变了意味着字段含义变了。
REVIEW_VERSION = 1


def _str(v, default: str = "") -> str:
    return v.strip() if isinstance(v, str) else default


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _rounds(e: dict) -> list[int]:
    """这个考点被问到的题号（升序、去重）。

    ⚠️ 只读 `blindspot` 条目顶层的 `rounds`（那里就是**题号整数**）——
       绝不碰 `per_round[]`，那里面每一轮都挂着 `base_miss`/`adv_miss` 原文。
    """
    out = sorted({r for r in (e.get("rounds") or [])
                  if isinstance(r, int) and not isinstance(r, bool)})
    return out


def _kp(e: dict) -> Optional[dict]:
    """白名单一个考点条目。没有 kp_id 就整条丢掉（宁可少一条，不可半条）。"""
    if not isinstance(e, dict):
        return None
    kid = _str(e.get("kp_id"))
    if not kid:
        return None
    # ⚠️ 只认 True/False/None 三态：别的值（比如被谁改成了 0）宁可当「判不了」，
    #    也不要让它冒充「没答到」上考生的清单。
    hit = e.get("hit")
    if not isinstance(hit, bool):
        hit = None
    # 漏掉的得分点**条数**（不是原文）。口径与 practice.kp_stat / growth 逐字相同：
    # 只看 reranker 正常的那几轮、跨轮按考点去重。
    base, adv = missed_points(e)
    return {
        "kp_id": kid,
        "title": _str(e.get("title")) or kid,
        "domain": _str(e.get("domain")) or UNCLASSIFIED,
        "subclass": _str(e.get("subclass")),
        "hit": hit,
        "rounds": _rounds(e),
        "missed_base": len(base),
        "missed_adv": len(adv),
        "best_score": _num(e.get("best_score")),
        "last_score": _num(e.get("last_score")),
    }


def _rounds_text(rounds: list[int]) -> str:
    """题号列表 → 「第 4、7 题」/「第 4 题」。**只在题号非空时调用**。"""
    if len(rounds) == 1:
        return f"第 {rounds[0]} 题"
    return "第 " + "、".join(str(r) for r in rounds) + " 题"


def _advice(k: dict) -> str:
    """一句给考生的话：哪几题问了这个考点、这次没答到、下一步做什么。

    ⚠️ 只承诺**今天真能做到**的两件事（把那一题重讲一遍 / 用专项练习重练），
       不写「去看考点讲解」—— 那份资源在脱敏档下出不了门（口径 5）。

    ⚠️ **题号可能没记下**（`rounds` 为空）。文案 QA 里抓到的病句：先前把
       「（题库没记下是哪几题）」当主语塞进模板 ⇒ 读出「（题库没记下是哪几题）考的就是
       『索引优化』…先把（题库没记下是哪几题）重新讲一遍」。**没有题号就换一句**，
       不拿括号短语去填主语的坑。
    """
    if not k["rounds"]:
        return (f"「{k['title']}」这个考点这一次没答到。"
                f"建议：把当时那一段重新讲一遍（不看答案，讲给自己听），"
                f"再用专项练习重练这个考点。")
    where = _rounds_text(k["rounds"])
    return (f"{where}考的就是「{k['title']}」，这一次没答到。"
            f"建议：先把{where}重新讲一遍（不看答案，讲给自己听），"
            f"再用专项练习重练这个考点。")


def _min_opt(a, b):
    """两个可能为 None 的分数取小（None = 没数据，绝不参与比较，绝不顶 0）。"""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _merge_by_topic(kps: list[dict]) -> list[dict]:
    """把**同一个主题**的多个 kp_id 合并成一条（口径 9）。

    实测（27 场真跑）里就有：`java-backend-kp-4839` 与 `java_backend-kp-soft-28634`
    两条的 `title/domain/subclass` 一字不差、题号与漏点条数也一模一样 —— 同一件事
    在题库里挂了两个 id。清单里原样铺开的话，考生会看到「缓存」出现两次，
    像是这报告坏了。

    合并规则（都是**取保守值**，不放大）：
      · 漏点条数取 **max**（不求和 —— 那两个 id 指的是同一批得分点，求和就是翻倍虚报）
      · 分数取 **min**（两边都是同一轮的分数，取更差的那个更保守）
      · `hit` 三态：有 True 就是 True，否则有 False 就是 False，否则 None
      · `kp_ids` 保留全部 id（4 号 想按 id 开练，哪一个都行）；`kp_id` 取**非 soft**
        的那个当主键（soft 前缀的 id 是通用软标签，练它挑不出题）
    """
    groups: dict[tuple, dict] = {}
    for k in kps:
        key = (k["title"], k["domain"], k["subclass"])
        g = groups.get(key)
        if g is None:
            groups[key] = dict(k, kp_ids=[k["kp_id"]])
            continue
        g["kp_ids"].append(k["kp_id"])
        g["rounds"] = sorted(set(g["rounds"]) | set(k["rounds"]))
        g["missed_base"] = max(g["missed_base"], k["missed_base"])
        g["missed_adv"] = max(g["missed_adv"], k["missed_adv"])
        g["best_score"] = _min_opt(g["best_score"], k["best_score"])
        g["last_score"] = _min_opt(g["last_score"], k["last_score"])
        hits = (g["hit"], k["hit"])
        g["hit"] = True if True in hits else (False if False in hits else None)
    out = []
    for g in groups.values():
        g["kp_ids"] = sorted(g["kp_ids"])
        hard = [i for i in g["kp_ids"] if "-soft-" not in i]
        g["kp_id"] = (hard or g["kp_ids"])[0]
        out.append(g)
    return out


def build_review(env: dict) -> dict:
    """
    从 `/finish`（或 `/result`）的响应体里取一份**给考生看的复盘清单**。

    白名单来源：`raw["blindspots"]["knowledge_points"]` 的**逐项白名单**
    （考点名 / 领域 / 题号 / 条数 / 分数 / 三态 hit）＋ `raw` 的几个标量计数。
    ⛔ 绝不进这里：`base_miss`/`adv_miss` 原文、`per_round[]`、题面、问答原文、
       `recommendations[].missed_points`。
    """
    env = env if isinstance(env, dict) else {}
    raw = env.get("raw") if isinstance(env.get("raw"), dict) else {}
    bs = raw.get("blindspots") if isinstance(raw.get("blindspots"), dict) else {}

    kps_raw: list[dict] = []
    for e in (bs.get("knowledge_points") or []):
        k = _kp(e)
        if k is None:
            continue
        kps_raw.append(k)
    # ⚠️ 这里**不额外筛**「软标签 / 噪声名」：`blindspot.diagnose` 建 `kps` 之前
    #    已经滤过一遍（`blindspot.py:158`，`_is_soft`）⇒ 本模块再滤一次不会多滤掉
    #    任何东西，却会让计数**对不上**。合并前后**两个口径都报**（口径 9）：
    #    考生看的是主题数，与 digest 对账看的是原始考点条目数。
    kps = _merge_by_topic(kps_raw)

    gaps = [k for k in kps if k["hit"] is False]
    covered = [k for k in kps if k["hit"] is True]
    uncovered = [k for k in kps if k["hit"] is None]

    # 排序：漏得最多的先看 → 分数低的先看 → kp_id 稳定序。
    #   `best_score` 是 None（没数据）时排最后（口径 4：绝不当 0 顶）。
    gaps.sort(key=lambda k: (-(k["missed_base"] + k["missed_adv"]),
                             k["best_score"] if k["best_score"] is not None else 9e9,
                             k["kp_id"]))
    covered.sort(key=lambda k: (k["best_score"] is None, -(k["best_score"] or 0.0),
                               k["kp_id"]))
    uncovered.sort(key=lambda k: k["kp_id"])

    n_seen = len(kps)
    n_hit, n_gap, n_unc = len(covered), len(gaps), len(uncovered)
    if n_seen == 0:
        headline = "这场没有可用于复盘的考点诊断（可能整场没评出分，或题库没给这几题挂考点）。"
    else:
        # ⚠️ 0 的那一档**不报**（文案 QA 抓到：「0 个答到了、0 个没答到、2 个判不了」）。
        #    报一串 0 既没信息量，又会让「整场没判出分」读起来像「考砸了」。
        bits = [f"这场覆盖了 {n_seen} 个考点"]
        if n_hit:
            bits.append(f"{n_hit} 个答到了")
        if n_gap:
            bits.append(f"{n_gap} 个没答到")
        if n_unc:
            bits.append(f"{n_unc} 个这场判不了")
        headline = "：".join([bits[0], "、".join(bits[1:])]) + "。"
        # 尾句只在**真答到了、且没有漏点**时才加（「没有判为没答到」是句好话，
        # 不能被安在「整场都没判出分」上 —— 那是句误导）。
        if not n_gap and n_hit:
            headline += "没有判为「没答到」的考点。"
        elif not n_gap and n_unc:
            headline += "这一场没有可用于判分的轮次。"
        # 「为什么不算漏点」由 caveats 那张单子说，这里不重复。

    # 下一步：只给**漏点**，最多 config.REVIEW_MAX_ACTIONS 条，指向已有功能
    # （`/practice` 收 kp_id ⇒ 4 号 能一键开练）。动作文案是**给考生看的**，
    # 不带端点名；机器字段（kind/kp_id）才是给 4 号 挂钩子用的。
    actions = []
    for k in gaps[:config.REVIEW_MAX_ACTIONS]:
        actions.append({
            "kind": "practice",
            "kp_id": k["kp_id"],
            "title": k["title"],
            "domain": k["domain"],
            "text": f"专门练「{k['title']}」：出 3 道同类题，练完给前后对比。",
        })

    caveats: list[str] = []
    failed = raw.get("scoring_failed_rounds")
    failed_n = len(failed) if isinstance(failed, list) else 0
    if failed_n:
        caveats.append(f"这场有 {failed_n} 轮没评出分，这几轮不计入 —— "
                       f"所以这份清单可能是不完整的。")
    if uncovered:
        caveats.append(f"「判不了」的 {len(uncovered)} 个考点是指这场没有可用于判分的"
                       f"轮次（没问到，或那几轮评分失败），不算漏点。")
    if env.get("partial") is True and not failed_n:
        caveats.append("这场有轮次没评出分，分数与清单都不完整。")
    if _str(raw.get("mode")) == "practice":
        caveats.append("这是专项练习场次，题量与阶段设计和正式面试不同，"
                       "不与正式成绩横向比较。")
    caveats.append("「没答到」是判分系统对「这一轮回答」的判定（未达及格线），"
                   "不代表你完全不会这个考点；换个问法可能就答上了。")
    caveats.append("这份清单只到考点这一层；具体哪句说得好、哪句该展开，"
                   "看成绩单正文那段评价。")

    sc = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    scored_n = sc.get("rounds_scored") if isinstance(sc.get("rounds_scored"), int) else None

    return {
        "review_version": REVIEW_VERSION,
        "session_id": _str(raw.get("session_id")) or _str(env.get("session_id")),
        "job": _str(raw.get("job")) or _str(env.get("job")),
        "mode": _str(raw.get("mode")),
        "headline": headline,
        "gaps": [dict(k, advice=_advice(k)) for k in gaps],
        "covered": covered,
        "uncovered": uncovered,
        "actions": actions,
        # 计数**全是整数**，没有任何百分比 / 掌握度（口径 3）。
        # `topics_*` = 按主题合并后的（考生看到的那个数）；
        # `kps_raw` = 未合并的内部考点条目数（与 digest.kps 逐字同源，供对账）。
        "counts": {
            "topics_seen": n_seen,
            "topics_hit": len(covered),
            "topics_missed": len(gaps),
            "topics_uncovered": len(uncovered),
            "kps_raw": len(kps_raw),
            "rounds_asked": raw.get("questions_asked")
                            if isinstance(raw.get("questions_asked"), int) else 0,
            "rounds_scored": scored_n,
        },
        "caveats": caveats,
    }
