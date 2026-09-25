# -*- coding: utf-8 -*-
r"""
answer.py · 考点讲解 / 优秀回答范例（`POST /model_answer`，赛题任务要求 4a）
================================================================
考生按考点取两样**学习材料**。这是赛题 4a「自动推荐针对性学习资源」里
「**知识点讲解 / 优秀回答范例**」这两项**对考生可见**的唯一出口。

⚠️ 本波唯一一处**放宽**，要知情：这两样内容此前只有 `A11_RAW_DETAIL=1` 的
`raw.blindspots.recommendations[]` 里才有（服务端默认档 `RAW_DETAIL=0` 连 raw 都脱敏），
**对考生完全不可见**。现在默认档也能拿到。为什么敢放宽 —— 下面三道闸都是**结构性**的。

为什么单独一个端点、而不是塞进 `/growth`：`/growth` 是**刻意无状态**的
（收一批摘要、算完就丢、不知道是谁，见 growth.py 开头）。本功能的门要一个**活着的
会话**（`session_id` 必须已 `/finish`）。两者的前提不同，不能合并。

⚠️ 三道闸（都是代码里的分支，不是约定）：
  1. 会话必须存在 —— 接口层 `_get_session` 保证（404）；
  2. 源场次必须**已交卷** —— `sess.result()` 非空，否则 409 `source_not_finished`
     （与 `/practice` 同一手法）。⇒「**面试中提前查答案**」在结构上做不到；
  3. 这个考点必须出现在**那一场的诊断**里 —— 否则 404 `answer_target_not_found`。
     ⇒「枚举 kp_id 把整份资源文件刷下来」也做不到。

⛔ 绝不返回：`拉开差距`（= 进阶得分点原文）、`常见卡点`（= 面试官降级策略）、任何
   `missed_points`、任何 `per_round[]`。取材只有一处（`resources.answer_block`），
   它只出 `考点讲解` / `优秀回答范例` / `from_question_id` / `kind` / `note` 五个键。
   ⚠️ 2026-09-25 从三个键加到五个（`kind` / `note`）—— 见 `resources.answer_block`
      的注释：那是为了「示范作答」必须被明确标注，不是放宽取材来源。
⛔ **不返回代表题的题面**：`_pick_sample` 可能挑中他没做过的那道代表题，连题面一起给
   就等于顺带泄露一份没考过的题。只给题号，前端足以说「针对这道题」。

⚠️ 两条取材路（2026-09-25 加第二条）：
  · `kp_id` 路 —— 考点中介，本来就是这条。`kp_id` 必须出现在**这一场**的诊断里。
  · `question_id` 路 —— **新增**，直接按题号取那道题自己的范文。为什么需要：
    题库里有 **1,110 道题不挂任何考点**，走 `kp_id` 路它们**永远取不到**范文。
    ⚠️ 闸**不变**、也**不能**松：题号必须 ∈ 这一场的 `asked_pids`（他真的答过这道题），
      否则同样是 404 `answer_target_not_found`。所以「枚举题号刷全库」依然做不到 ——
      这条新路加的是**覆盖率**，不是**权限**。
"""
from typing import Optional

from app.core.resources import (SRC_ID, SRC_QUESTION, _consistent, answer_block,
                                load_index)
from app.core.session import SessionError


# ============================================================
# 错误（都带 http_status，接口层经 _http_error 映射，与其它 SessionError 同一条路）
# ============================================================
class AnswerTargetNotFound(SessionError):
    """这个考点不在**这一场**的诊断里 —— 也就是「这场根本没考它」。

    ⚠️ 与 `no_material` 必须分开：那个是「考了，但资源侧没有它的材料」。
    两句对考生的话完全不同（「这场没考这个考点」vs「这个考点暂时没有材料」）。
    """
    code = "answer_target_not_found"
    http_status = 404


class NoMaterial(SessionError):
    """本场诊断里有它，但资源侧查不到可用材料（或领域/子类对不上，按既有取舍弃用）。"""
    code = "no_material"
    http_status = 404


# ============================================================
# 取材
# ============================================================
def diagnosis_kps(raw: dict) -> list[dict]:
    """这一场的考点诊断条目（`raw.blindspots.knowledge_points`）。取不到就是空表。"""
    bs = raw.get("blindspots") if isinstance(raw, dict) else None
    bs = bs if isinstance(bs, dict) else {}
    kps = bs.get("knowledge_points")
    return [k for k in kps if isinstance(k, dict)] if isinstance(kps, list) else []


def find_kp(raw: dict, kp_id: str) -> Optional[dict]:
    """
    在**这一场**的诊断里按 `kp_id` 精确找一个考点。找不到返回 `None`。

    ⚠️ 精确匹配、不做标题兜底：标题匹配是资源侧那层的事（`ResourceIndex.lookup`
    有归一标题兜底）。这里的语义是「**这一场考过它没有**」——按名字猜会把
    「他这场没考过 A」变成「A 和 B 名字像，那就当考过吧」，闸就白设了。

    为什么 `review` 给的合并键也能命中：`review._merge_by_topic` 的 `kp_id` 取的是
    该主题下**非 soft 的那个原始 id**（review.py:190-192），它本来就在 `kp_ids` 里，
    ⇒ 合并后的主键一定是本表里的一个 id。
    """
    want = (kp_id or "").strip()
    if not want:
        return None
    for k in diagnosis_kps(raw):
        if str(k.get("kp_id", "")).strip() == want:
            return k
    return None


def pick(sess, kp_id: str, idx=None) -> dict:
    """
    一场**已交卷**的会话 + 一个考点 ⇒ 给考生的材料。抛 `SessionError` 子类或返 dict。

    调用方（接口层）已经确认过两件事：`sess.result()` 非空、资源开关与资源状态都可用
    （那两件的错误码是 409 `source_not_finished` 与 503，**不是**这里的 404）。
    ⇒ 本函数只关心「**这个考点**有没有材料」。

    `idx` 缺省时自己 `load_index()`（冒烟直调本函数时省事）；接口层传进来是为了
    与 `/health` 用同一份进程内索引，不重复加载。
    """
    res = sess.result() or {}
    raw = res.get("raw") or {}
    kp = find_kp(raw, kp_id)
    if kp is None:
        raise AnswerTargetNotFound(
            f"考点 {kp_id!r} 不在这一场的诊断里 —— 这一场没考到它。"
            "只能取**自己刚考过的那一场**里出现过的考点。")
    if idx is None:
        idx = load_index()
    if idx is None or not idx.available:
        # 正常路径到不了这里（接口层已经用 503 resource_unavailable 先说清楚了）。
        # 留着是为了「直调本函数」时不会静默返一个空壳。
        raise NoMaterial("资源索引不可用。")
    rec, src = idx.lookup(kp.get("kp_id", ""), kp.get("title", ""))
    if rec is None:
        raise NoMaterial(f"资源文件里没有考点「{kp.get('title', '')}」的条目。")
    # ⚠️ `_consistent` 是 resources 的私有名 —— 照 growth.py 引 `blindspot._is_soft`
    #    的先例跨模块取用：一致性校验**只能有一份实现**（它防的是「题 ↔ 考点跨岗位
    #    误挂」），两处各写一份迟早分叉。
    if not _consistent(rec, kp):
        raise NoMaterial(f"考点「{kp.get('title', '')}」的资源条目对不上"
                         "（领域/子类不一致），按既有取舍弃用 —— 宁可不给，也不给错的。")
    # 优先挑**他真答过的那道**代表题的范例（问的同一道题，范例才对得上）
    sample = idx._pick_sample(rec, list(getattr(sess, "asked_pids", None) or []))
    block = answer_block(rec, sample)
    if block is None:
        raise NoMaterial(f"考点「{kp.get('title', '')}」的条目里没有可给的正文。")
    return {
        "kp_id": kp.get("kp_id", ""), "title": kp.get("title", ""),
        "domain": kp.get("domain", ""), "subclass": kp.get("subclass", ""),
        "src": src or SRC_ID,
        **block,
    }


def pick_by_question(sess, question_id: str, idx=None) -> dict:
    """
    一场**已交卷**的会话 + 一个**题号** ⇒ 给考生的材料。

    ⚠️ 闸与 `pick()` **完全同一套**，一个字都不松：题号必须 ∈ `sess.asked_pids`。
       「他真的答过这道题」是这条路的全部合法性来源 —— 去掉它，这个端点就变成
       「拿一个题号换一份范文」的批量下载口（题库题号是有规律的，
       `ALGORITHM-Q0001` 这种）。所以这条闸**不是**「顺手加的校验」，是本端点的门。
    ⚠️ `kp_id` / `title` / `domain` / `subclass` 这四项在**这条路里给空串**：
       题号不保证挂在任何考点上（这正是加这条路的原因），硬凑一个考点名出来
       等于编数据。前端要显示「这是针对哪道题的」有 `from_question_id`，够用。
    """
    res = sess.result() or {}
    qid = (question_id or "").strip()
    asked = {str(x) for x in (getattr(sess, "asked_pids", None) or [])}
    if qid not in asked:
        raise AnswerTargetNotFound(
            f"题目 {qid!r} 不在这一场出过的题里 —— 只能取**自己刚考过的那一场**"
            "里出现过的题。")
    if idx is None:
        idx = load_index()
    if idx is None or not idx.available:
        raise NoMaterial("资源索引不可用。")
    sample = idx.sample_for_question(qid)
    if sample is None:
        raise NoMaterial(f"题目库的范文里没有 {qid!r} 这一条。")
    # ⚠️ `rec` 与 `kp_id` 路不同：这条路上没有考点条目，`考点讲解` 给空串。
    #    `answer_block` 要求 `rec` 是 dict —— 给一个只有空讲解的壳，
    #    正文全部来自 `sample`，出口仍然是同一个函数（安全性只有一处要审）。
    block = answer_block({"考点讲解": ""}, sample)
    if block is None:
        raise NoMaterial(f"题目 {qid!r} 的范文是空的。")
    return {
        "kp_id": "", "title": "", "domain": "", "subclass": "",
        "src": SRC_QUESTION,
        **block,
    }
