# -*- coding: utf-8 -*-
r"""
practice.py · 专项强化练习（赛题 4b「支持学生针对薄弱项进行专项强化练习」）
============================================================
设计稿 `D:\A11-Data\学习资源推荐设计.md` §6。四步都做满了：

  1. **入口** —— `POST /practice` 从一份**已交卷**的成绩单里挑一个薄弱项
     （指定 kp_id、指定领域、或自动取最薄弱的那个），开一个练习场次；
  2. **取题** —— 按该考点从题库的 `关联知识点` 字段找题，**优先取没考过的**，
     难度由易到难铺开（练习讲究循序渐进），数量 3~5 道；
  3. **出题** —— 复用**同一套**追问、判档、reranker 评分、复读守卫与收尾链路
     （只覆写了 `_pick_question` 一个方法，见下），**不计入**正式场次的
     `total_questions`，也不动源场次的任何一个字段；
  4. **闭环证据** —— 练完 `/finish` 出的 `raw.practice` 里带上「练之前 vs 练之后」
     的对比（同一个考点、同一套口径重算一遍 diagnose）。

⚠️ 四条口径约定（改之前先读）：

  1. **评分一套，不是两套。** 练习场次的五维分、reranker 覆盖率、判档规则、
     追问上限与正式面试**逐字节相同** —— 差别只在「问哪几道题」。所以练习场次的
     分数不能当作正式成绩（没有阶段设计、题量少），报告里如实写着这句话。

  2. **练习**不占**正式场次的任何计数。** 它是另一个 `session_id`、另一份会话对象，
     源场次的 `rounds` / `asked_pids` / `coverage` / `blindspots` 一个字段都不改
     —— 只从它那里**读**一份快照（before）。源场次过期被回收也不影响练习报告。

  3. **换题在练习里关着。** 换题（`_swap_round`）在正式场次的语义是「这道题
     不该问他」；在专项练习里它会把「针对薄弱项的题」换成一道无关的题，
     与练习的目的正相反。关掉的写法与 `A11_SWAP=0` 完全一样（`_can_swap` 返 False）。

  4. **练习报告里的 `after` 可能没有目标考点。** 如果题库里这个考点的题不够、
     退回了「考过的题」，甚至一道都没找到（那时直接 409 不出场次），
     重算出来的诊断里未必有这个 kp —— 这时 `after=None`、`delta=None`，
     如实说明，**不要**拿别的考点的分顶上。
"""
import time
from typing import Optional

from app import config
from app.core import blindspot as bsmod
from app.core import question_bank as qb
from app.core.resources import missed_points
from app.core.session import InterviewSession, SessionError
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 练习场次的阶段名。**只有一个阶段**：不按 STAGE_RULES 走（那是正式面试的
# 开场/核心/压轴设计），也不参与难度自适应。
PRACTICE_STAGE = "专项练习"


# ============================================================
# 错误（都带 http_status，接口层直接映射，与其它 SessionError 同一条路）
# ============================================================
class NoWeakPoint(SessionError):
    """这场没有可练的薄弱项：所有考点都判为答到了，或一个都判不了。"""
    code = "no_weak_point"
    http_status = 409


class PracticeTargetNotFound(SessionError):
    """指定的 kp_id / domain 不在这一场的诊断里。"""
    code = "practice_target_not_found"
    http_status = 404


class NoPracticeQuestions(SessionError):
    """题库里这个考点一道题都没有（或全被排除）。"""
    code = "no_practice_questions"
    http_status = 409


# ============================================================
# 选目标 + 选题
# ============================================================
def kp_stat(kp: Optional[dict]) -> Optional[dict]:
    """
    把一个诊断条目压成「可比的一小组数」。**before 与 after 都用它算** ——
    两边口径不同的话前后对比就成了数字游戏。
    """
    if not kp:
        return None
    base, adv = missed_points(kp)
    return {
        "kp_id": kp.get("kp_id", ""),
        "title": kp.get("title", ""),
        "domain": kp.get("domain", ""),
        "subclass": kp.get("subclass", ""),
        "hit": kp.get("hit"),
        "best_score": kp.get("best_score"),
        "last_score": kp.get("last_score"),
        "rounds": list(kp.get("rounds") or []),
        "appearances": int(kp.get("appearances") or 0),
        "question_ids": list(kp.get("question_ids") or []),
        "missed_base": len(base),
        "missed_adv": len(adv),
        "missed_points": (base + adv)[:config.RECOMMEND_MAX_POINTS],
    }


def _weak_of(kps: list, domain: str = "") -> list:
    """
    可练的薄弱考点，最薄的在前。

    ⚠️ 判据与推荐**同一条**：只认 `hit is False`（有客观依据地判他没答到）。
    「没考过」（hit=None）不是薄弱项，是「还没覆盖」—— 拿它当练习目标等于
    凭空猜他不会。排序：覆盖率低的在前，其次漏掉的得分点多者在前。
    """
    out = [e for e in kps
           if e.get("hit") is False
           and (not domain or e.get("domain") == domain)
           and isinstance(e.get("best_score"), (int, float))]
    out.sort(key=lambda e: (e["best_score"], -(len(e.get("per_round") or [])),
                            e.get("kp_id", "")))
    return out


def pick_target(blindspots: dict, kp_id: str = "", domain: str = "") -> tuple[dict, str]:
    """挑练习目标 → (诊断条目, 为什么是它)。挑不到就抛（接口层映射成 409/404）。"""
    kps = list(blindspots.get("knowledge_points") or [])
    by_id = {e.get("kp_id"): e for e in kps}

    if kp_id:
        e = by_id.get(kp_id)
        if e is None:
            raise PracticeTargetNotFound(
                f"这一场里没有考点 {kp_id!r}；"
                f"可选：{[x.get('kp_id') for x in kps][:20]}")
        if e.get("hit") is not False:
            # 指定一个「已掌握」或「判不了」的考点：能做，但要说清楚为什么
            return e, f"你指定了考点「{e.get('title')}」（这一场里它的 hit={e.get('hit')}）"
        return e, f"你指定了考点「{e.get('title')}」"

    if domain:
        cand = _weak_of(kps, domain)
        if not cand:
            doms = sorted({x.get("domain", "") for x in kps})
            raise PracticeTargetNotFound(
                f"领域 {domain!r} 里没有可练的薄弱项；本场领域：{doms[:20]}")
        e = cand[0]
        return e, f"领域「{domain}」里最薄弱的一个考点（覆盖率 {e['best_score']:.0f}%）"

    cand = _weak_of(kps)
    if not cand:
        raise NoWeakPoint(
            "这一场没有可练的薄弱项：所有考点都判为答到了，或一个都判不了。"
            "（「没考过」不算薄弱项 —— 那叫还没覆盖。）")
    e = cand[0]
    return e, (f"全卷最薄弱的一个考点：覆盖率 {e['best_score']:.0f}%，"
               f"漏掉 {len(missed_points(e)[0])} 条基础点")


def _spread(pool: list, count: int) -> list:
    """
    从候选里取 count 道，**按难度由易到难铺开**（练习要循序渐进）。

    桶轮转而不是直接切片：题库里同一个考点的题常常挤在同一个难度上，
    直接切片会抽出一整组 medium。桶空了就跳过 —— 循环步数有上限，不会空转。
    """
    buckets: dict[str, list] = {}
    for q in pool:
        buckets.setdefault(q.get(qb.F_DIFFICULTY, ""), []).append(q)
    order = ["easy", "medium", "hard", ""]
    out: list = []
    step = 0
    limit = count * len(order) + len(order)
    while len(out) < count and step < limit:
        b = buckets.get(order[step % len(order)])
        if b:
            out.append(b.pop(0))
        step += 1
    return out


def build(job: str, source_sid: str, blindspots: dict, exclude_ids,
          kp_id: str = "", domain: str = "",
          count: Optional[int] = None, llm=None, scorer=None) -> "PracticeSession":
    """
    组一个练习场次。**只读** blindspots 与题库，不碰源场次的任何状态。

    题目不够时的退路：先只用「没考过的题」；不够 count 时再退回「考过的题」
    （`reused_asked` 记下用了几道）—— 这比「题不够就少练两道」更贴近
    「专门练这个考点」的目的，而且报告里说得清。
    """
    n = int(count or config.PRACTICE_QUESTIONS)
    n = max(1, min(n, config.PRACTICE_MAX))
    target, why = pick_target(blindspots, kp_id, domain)

    fresh, used, hit_key = qb.find_by_knowledge(
        job, kp_id=target.get("kp_id", ""), title=target.get("title", ""),
        exclude_ids=exclude_ids)
    pool = list(fresh)
    reused = 0
    if len(pool) < n and used:
        need = min(n - len(pool), len(used))
        pool.extend(used[:need])
        reused = need
    if not pool:
        raise NoPracticeQuestions(
            f"题库里找不到考点「{target.get('title')}」的题"
            f"（按 kp_id/考点名都试过）—— 换个薄弱项或换个领域再试。")

    picked = _spread(pool, n)
    why_full = (f"{why}；按「{'kp_id' if hit_key == 'kp_id' else '考点名'}」命中 "
                f"{len(fresh) + len(used)} 道题，其中没考过的 {len(fresh)} 道")
    before = kp_stat(target)
    sess = PracticeSession(
        job=job, source_sid=source_sid, target=before, pool=picked,
        count=len(picked), why=why_full, reused_asked=reused,
        hit_key=hit_key, llm=llm, scorer=scorer)
    logger.info("sid=%s 开专项练习：源=%s 考点=%s 题=%d 道（复用考过的 %d 道）",
                sess.session_id, source_sid, target.get("kp_id"),
                len(picked), reused)
    return sess


# ============================================================
# 练习场次
# ============================================================
class PracticeSession(InterviewSession):
    """
    `InterviewSession` 的**最小覆写**版本。覆写清单（就这五个）：

        total_questions   题数由本次练习决定，不是 10
        _current_stage    只有一个「专项练习」阶段，不参与难度自适应
        _pick_question    从预选题里取，而不是按难度随机抽
        _can_swap         关掉换题（换了就练不到目标考点了，见文件头 §3）
        finish            出「专项练习报告」：自己的诊断 + 与源场次的前后对比

    其余全部继承：`submit_answer`（含 reranker 评分、LLM 判档、复读守卫、
    追问上限、降级引导）、`_settle_round`、`round_status`、RAG 参考片段、
    KG 深挖方向、覆盖度统计、`to_raw`。
    """

    def __init__(self, job: str, source_sid: str, target: dict, pool: list,
                 count: int, why: str, reused_asked: int = 0, hit_key: str = "",
                 llm=None, scorer=None):
        super().__init__(job=job, intro="", llm=llm, scorer=scorer)
        self.mode = "practice"
        self.source_sid = source_sid
        self.target = dict(target or {})      # before 快照（源场次里的状态）
        self.target_why = why
        self.pool = list(pool)                # 预选题（还没出的）
        self.plan = int(count)
        self.reused_asked = int(reused_asked)
        self.hit_key = hit_key
        self.picked_ids: list = []            # 实际出过的题（按顺序）

    # ---------- 开场的这几处覆写 ----------
    @property
    def total_questions(self) -> int:
        return self.plan

    def opening_message(self) -> str:
        t = self.target or {}
        return (f"【专项强化练习】这次我们只练一个考点：{t.get('title', '')}"
                f"（{t.get('domain', '')}）。一共 {self.plan} 道题，"
                f"追问与评分和正式面试完全一样 —— 答完给你一份前后对比。")

    def _current_stage(self):
        """
        练习只有一个阶段。返回的难度集合是**预选题里实际出现的难度**，
        只用于报告与日志（真正的选题在 `_pick_question` 里）。
        """
        diffs = {q.get(qb.F_DIFFICULTY, "") for q in self.pool} or {
            "easy", "medium", "hard"}
        return (PRACTICE_STAGE, self.plan, diffs,
                "专项练习：按目标考点的预选题出题，不参与阶段规则与难度自适应")

    def _can_swap(self) -> bool:
        """练习里不给换题。理由见文件头 §3：换了就练不到目标考点了。"""
        return False

    def _pick_question(self, difficulties: set, trace: dict) -> Optional[dict]:
        """
        从预选题里按顺序取一道。**不做避重过滤**：练习就是要反复练同一个考点，
        避重在这里正好是反的。
        """
        while self.pool:
            q = self.pool.pop(0)
            qid = q.get(qb.F_ID)
            if qid in self.asked_pids:        # 理论上不会发生，兜底防重复
                continue
            trace["level"] = "practice"
            self.picked_ids.append(qid)
            return q
        return None                            # 抽空 → 走既有的 bank_exhausted 收尾

    # ---------- 练习报告 ----------
    def finish(self) -> dict:
        """先走**完全一样**的评分与汇总，再把练习那一块挂上去（加法）。"""
        env = super().finish()
        # 幂等：第二次 /finish 命中缓存，同一个 raw 对象，不要重算（重算会白跑 diagnose）
        if "practice" not in env.get("raw", {}):
            env["raw"]["practice"] = self._practice_report()
        return env

    def _practice_report(self) -> dict:
        after_kps = bsmod.diagnose(self.rounds, self.kg)["knowledge_points"]
        want = (self.target or {}).get("kp_id", "")
        after_entry = next((e for e in after_kps if e.get("kp_id") == want), None)
        after = kp_stat(after_entry)

        # 前后对比只在**两边都有分**时才算。`after` 存在但 best_score=None
        # 是很常见的一种情况：这一轮还没答（练到一半就 /finish，或最后一轮的
        # 题没答）就收尾了 —— 此时 diagnose 里会留下这条没有评分的记录。
        # 而「漏掉的得分点」是按 `reranker_ok is True` 过滤出来的，没评分就是 0 条，
        # 拿它跟 before 做差会凭空多出一次「进步」。**宁可不比，也不算假进步。**
        b = (self.target or {}).get("best_score")
        a = after.get("best_score") if after else None
        comparable = bool(self.target and after
                          and isinstance(b, (int, float))
                          and isinstance(a, (int, float)))
        delta = None
        if comparable:
            delta = {
                "best_score": round(a - b, 1),
                "hit": [self.target.get("hit"), after.get("hit")],
                "missed_base": after["missed_base"] - self.target["missed_base"],
                "missed_adv": after["missed_adv"] - self.target["missed_adv"],
                # 「有没有进步」只认两个客观信号：覆盖率上升，或 hit 由 false 变 true
                "improved": bool(a - b > 0
                                 or (self.target.get("hit") is False
                                     and after.get("hit") is True)),
            }

        title = (self.target or {}).get("title", "")
        if delta is None:
            why_not = ("这次练习的题没覆盖到该考点"
                       if after is None else
                       "该考点这一轮没评出分（题没答完或评分失败）")
            summary = (f"练的是「{title}」，但{why_not}，"
                       f"所以不做前后对比（不拿别的考点的分顶上）。")
        else:
            bits = [f"「{title}」得分点覆盖率 {b:.0f}% → {a:.0f}%"
                    f"（{delta['best_score']:+.0f}）"]
            if self.target.get("hit") is not after.get("hit"):
                bits.append(f"hit {self.target.get('hit')} → {after.get('hit')}")
            bits.append(f"漏掉的基础点 {self.target['missed_base']} → "
                        f"{after['missed_base']}")
            bits.append("本次练习**看到了提升**" if delta.get("improved")
                        else "本次练习**没看到提升**（覆盖率没涨、也没判成答到）")
            summary = "；".join(bits) + "。"

        return {
            "source_session_id": self.source_sid,
            "target": dict(self.target or {}),
            "why": self.target_why,
            "match": self.hit_key,            # kp_id / title —— 题库是按哪条路找到题的
            "before": self.target,
            "after": after,
            "delta": delta,
            "summary": summary,
            "questions": list(self.picked_ids),
            "reused_asked": self.reused_asked,
            "plan": self.plan,
            # 如实说明边界：练习场次分数**不是**正式成绩
            "disclaimer": ("专项练习复用正式面试的同一套追问与评分，但题量少、"
                           "没有阶段设计，分数只用于看**自己前后**的变化，"
                           "不与正式场次横向比较。"),
            "finished_at": round(time.time(), 3),
        }
