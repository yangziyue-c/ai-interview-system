# -*- coding: utf-8 -*-
r"""
growth.py · 成长档案（错题本 / 考点地图 / 历史成绩追踪 / 提升路径）
============================================================
赛题 4「成长档案」那一路。**本模块没有状态、不认人、不落盘** —— 四个视图都是
「一批成绩单摘要 → 四份聚合」的**纯函数**，可以被冒烟直接 import 断言。

为什么是这个切法：身份与持久化在 1 号（他有 user_id、有数据库）。对话层本来就
**不记事**（`store.SessionStore` 只在内存、`RESULT_TTL` 6 小时后回收、重启即 404），
跨场次的数据只能由调用方保管。所以 `POST /growth` 收一批 `digest`、当场算完就丢，
零落盘、不查库、不知道是谁。见 config.py 那一段与 README §13.7。

四个视图一句话：
    wrong_book —— 错题本：哪些考点**被判过没答到**（`hit is False`），错过几场
    kp_map     —— 考点地图：该岗位**全量考点**按领域铺开，标出练过 / 答到 / 没答到
    history    —— 历史成绩：只吃正式场次（`mode="exam"`），练习场次单列一节
    plan       —— 提升路径（赛题任务要求 4）：先补哪个 → 为什么 → 材料在哪 → 怎么练

⚠️ 七条口径（改之前先读）：

  1. **「薄弱」全项目只有一条口径：`hit is False`**（与 `practice._weak_of` 逐字
     相同）。`hit is None` = 判不了 / 没考过 = **还没覆盖**，**不是**薄弱 ——
     拿它当错题会凭空判考生不会。`blindspot.domains[].kps_weak` 用的是更宽的
     `hit is not True`，那两个数**不许混用**。
     ⚠️ 落到 `plan` 上要再切一刀，否则组名会名不副实：`_facts` 里的条目**必然被考到过**
     （它们是从场次的诊断里来的），所以 `hit is None` 的条目**全都是**「考到过、那些轮次
     没判出分」；而**真「从没考过」的考点根本不是 fact**，只是 `unpracticed_kp_total`
     一个数（⛔ 不列名字）。⇒ `uncovered` 组的 `label` 写「考到过、判不了的」，
     **不是**「还没覆盖的」；「还没覆盖」是 `config.py:815` 那个更宽的上位词，
     用在这一组上会把「考过」说成「没考过」。

  2. **绝不逐字抄诊断条目**：`blindspot.knowledge_points[].per_round[]` 里装着
     `base_miss`/`adv_miss` 的**原文**（= 一份答案的要点）。digest 与三个视图
     一律**白名单**构造，得分点只可能以**条数**（`len()`）出现，不可能出现文字。
     这是 `raw` 之外**第一个无论 `A11_RAW_DETAIL` 都会出门**的字段，所以冒烟里
     拿得分点字面量当针做金丝雀。

  3. 分数可能为 `None` = 「没有数据」，**不是 0 分**。走势里 `None` 就是断点，
     绝不拿 0 顶（`schemas.py` 的 FinishResp 那段有同一条）。**只有一场时 Δ 也是
     `None`** —— 首尾是同一场，按公式算必然得 0.0，而 0 会被读成「持平」。

  4. 练习场次**不与正式场次比**（`practice.py` 自己声明过）：历史走势必须按
     `mode` 分流。本模块是**全项目第一处**按 `mode` 分支的代码。

  5. 「以最近一次判定为准」与「曾经错过」是**两个问题**，两个都给：地图答前者
     （他现在会不会），错题本答后者（他稳不稳）。**两者不一致是正常的** ——
     一个考点可以「以前错过、最近答到了」，那时它既在错题本里、又在地图上标着
     `hit=true`。地图的每条练过的考点带 `ever_missed`，两处因此可以互相校验。

  6. **一份摘要要么整份可用、要么整份跳过**（进 `skipped[]`）。半信半疑地取一半
     字段，是「静默算错」的温床 —— 而这个功能的输出是给考生看的结论。

  7. **提升路径（`plan`）的两组是两件事，不许合并**：`to_fix`（判过没答到，有客观
     依据）与 `uncovered`（判不了，**不是薄弱**）判据互斥；**从没考过**的只给
     `unpracticed_kp_total` 一个数、**不给考点名**（与 `_kp_map` 同一条：那是题库
     内容最大的一份批量外泄面）。⚠️ 还有一条硬约束：**材料有无绝不影响条目数** ——
     资源文件在/不在，`count` 与 `len(items)` 必须一模一样（「四档开关组合增量必须
     相等」那条纪律）。正文（考点讲解 / 优秀回答范例）**一个字都不从本模块出**，
     只在 `POST /model_answer` 出，那里有三道结构性闸。
"""
import json
from typing import Optional

from app import config
from app.core import question_bank as qb
from app.core.blindspot import _is_soft, _level_of
from app.core.kg import UNCLASSIFIED
from app.core.resources import material_status, missed_points
from app.core.session import SessionError
from app.logging_conf import get_logger

logger = get_logger(__name__)


# 摘要结构版本。**不认识的版本不猜**：跳过并在 skipped[] 里点名（见 _select）。
# 它变了意味着字段语义变了，拿旧口径算出来的结论会静默错。
DIGEST_VERSION = 1

# `mode` 的全部合法取值。全项目只有两处写它：session.py:812（exam）、
# practice.py:240（practice）。这里是第三处，也是唯一的分支点。
MODE_EXAM = "exam"
MODE_PRACTICE = "practice"
_MODES = (MODE_EXAM, MODE_PRACTICE)

# 错题本里「练过几场才配谈反复」的门槛。为什么是 2 而不是别的：**1 场里不可能
# 观察到「又错了」** —— 只投一份摘要时，每个考点最多只能是 "once"，
# `status="repeat"` 这一档在数学上取不到值。所以这个数不是阈值调参，是
# 「这个字段有没有意义」的分界。
_REPEAT_MIN_SESSIONS = 2

# 视图里数组型字段（场次 id）的截断长度。**真实条数另有专门字段**
# （`miss_sessions` / `seen_sessions`），所以截断不会被读成总数 ——
# 与 raw.rounds 那条「只问了 N/M 题」同一条纪律：数字与明细都要在，且不互相冒充。
_MAX_IDS = 20


# ============================================================
# 错误（都带 http_status，接口层直接映射，与其它 SessionError 同一条路）
# ============================================================
# 为什么三个「入参有问题」的错都归 422 而不是 400：
#   · `UnknownJob`（在本模块里复用）本来就是 422，与 /start 逐字一致；
#   · `/practice` 的 `count` 越界走 FastAPI 校验，返的也是 422 —— 同一个项目里
#     「参数不合法」应当只有一个状态码，否则 4 号 要写两套分支。
# 413 只留给**体积**：那是另一个维度的问题（不是写错了，是给错了东西）。
class BadRecords(SessionError):
    """`records` 不是数组、或整批一份都用不上。"""
    code = "bad_records"
    http_status = 422


class TooManyRecords(SessionError):
    """份数超过 GROWTH_MAX_RECORDS。请分批调用。"""
    code = "too_many_records"
    http_status = 422


class JobMismatch(SessionError):
    """某份摘要的 job 与本次请求的 job 不一致。**报错，不静默丢。**"""
    code = "job_mismatch"
    http_status = 422


class DigestTooLarge(SessionError):
    """单份摘要超过 GROWTH_MAX_DIGEST_BYTES —— 几乎一定是把整份 raw 当成摘要投进来了。"""
    code = "digest_too_large"
    http_status = 413


# ============================================================
# 小工具
# ============================================================
def _num(v) -> Optional[float]:
    """
    只接受**真数**。`bool` 不算 —— Python 里 `True` 是 `int` 的子类，
    不拦的话 `"hit": true` 会被当成 `best_score=1.0` 这种荒谬的读数。
    字符串数字（`"3.4"`）也**不认**：摘要由本模块生成，出现字符串说明中间被人改过，
    宁可当「没有数据」也不要猜。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def _score_key(v: Optional[float]) -> tuple:
    """排序用：`None`（没有覆盖率数据）排在**最后**，而不是当成 0 混在最前面。"""
    return (v is None, v if v is not None else 0.0)


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """后 − 前。**任一端没有数据就是 `None`**（不是 0）—— 「这一场没评出分」
    与「这一场退步了 N 分」必须分得开。"""
    return round(a - b, 2) if (a is not None and b is not None) else None


# ============================================================
# 一、成绩单摘要（digest）—— /finish 与 /result 的顶层新键
# ============================================================
def build_digest(env: dict) -> dict:
    """
    从 `/finish`（或 `/result`）的响应体里取一份**成绩单摘要**。

    **它是全函数，绝不抛** —— 调用点在 `session.finish()` 里，那是整场面试的收口，
    任何异常都会把交卷打挂。所以全程 `.get()`：缺就是缺，缺了照样出一份结构完整的
    摘要（该场在报告里表现为「这场没数据」，而不是「交卷失败」）。

    白名单来源（**不是** `raw` 整份、也**不是** `RoundRecord.to_raw()` —— 那个
    40 键的版本里带着 `priority` / `est_minutes` / `core_keywords` /
    `deepen_directions`，全是本模块不该碰的东西）：
      · 场次级 ← `raw` 的各标量键 + 顶层 `five_dim_avg` / `total_score*` / `partial`
      · `rounds[]` ← `raw["rounds"]` 的**逐轮白名单**（round/题目ID/stage/difficulty/
        答了几次/评没评分）。给 1 号存档用 —— 服务端只用它的计数。
      · `kps[]` ← `raw["blindspots"]["knowledge_points"]` 的**逐项白名单**
        ＋ `resources.missed_points()` 的 `len()`（只取条数，原文在下一行就丢了）

    ⛔ 绝不进这里：`per_round[]`（含 `base_miss`/`adv_miss` 原文）、
       `recommendations[].missed_points`（原文）、`exchanges[]`（问答全文）、
       `base_points`/`adv_points`（得分点原文）、`question`（题面）。
    """
    env = env if isinstance(env, dict) else {}
    raw = env.get("raw") if isinstance(env.get("raw"), dict) else {}

    # ---- 五维（固定键恒在，缺的就是 None）----
    fda = env.get("five_dim_avg") if isinstance(env.get("five_dim_avg"), dict) else {}
    five = {d: _num(fda.get(d)) for d in config.DIMENSIONS}

    # ---- 考点（白名单逐项捡）----
    kps: list[dict] = []
    bs = raw.get("blindspots") if isinstance(raw.get("blindspots"), dict) else {}
    for e in (bs.get("knowledge_points") or []):
        if not isinstance(e, dict):
            continue
        kid = e.get("kp_id")
        kid = kid.strip() if isinstance(kid, str) else ""
        if not kid:
            continue
        hit = e.get("hit")
        # ⚠️ 只认 True/False/None 三态。别的值（比如被谁改成了 0）宁可当「判不了」，
        #    也不要让它冒充「没答到」进错题本。
        base, adv = missed_points(e)     # ← 原文只在这一行存在，下面只用 len()
        kps.append({
            "kp_id": kid,
            "title": (e.get("title") or kid) if isinstance(e.get("title"), str)
                     else kid,
            "domain": (e.get("domain") or UNCLASSIFIED)
                      if isinstance(e.get("domain"), str) else UNCLASSIFIED,
            "subclass": e.get("subclass") if isinstance(e.get("subclass"), str) else "",
            "hit": hit if isinstance(hit, bool) else None,
            "best_score": _num(e.get("best_score")),
            "last_score": _num(e.get("last_score")),
            # 漏掉的得分点**条数**（不是原文）。口径与 practice.kp_stat 逐字相同：
            # 只看 reranker 正常的那几轮、跨轮按考点去重。
            "missed_base": len(base),
            "missed_adv": len(adv),
        })

    # ---- 逐轮（只留给人看的骨架，不带任何得分点/问答原文）----
    rounds: list[dict] = []
    for r in (raw.get("rounds") or []):
        if not isinstance(r, dict):
            continue
        ex = r.get("exchanges")
        rounds.append({
            "round_no": _int(r.get("round")) or 0,
            "question_id": r.get("题目ID") if isinstance(r.get("题目ID"), str) else "",
            "stage": r.get("stage") if isinstance(r.get("stage"), str) else "",
            "difficulty": (r.get("difficulty") if isinstance(r.get("difficulty"), str)
                           else ""),
            "attempts": len(ex) if isinstance(ex, list) else 0,
            "scored": r.get("scored") is True,
        })

    scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    scored_n = _int(scoring.get("rounds_scored"))
    if scored_n is None:
        scored_n = sum(1 for r in rounds if r["scored"])

    return {
        "digest_version": DIGEST_VERSION,
        "session_id": raw.get("session_id") or env.get("session_id") or "",
        "job": raw.get("job") or env.get("job") or "",
        "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else "",
        "started_at": _num(raw.get("started_at")),
        "finished_at": _num(raw.get("finished_at")),
        "duration_sec": _num(raw.get("duration_sec")),
        "questions_asked": _int(raw.get("questions_asked")) or 0,
        "rounds_scored": scored_n,
        "partial": env.get("partial") is True,
        "total_score": _num(env.get("total_score")),
        "total_score_100": _num(env.get("total_score_100")),
        "five_dim": five,
        "rounds": rounds,
        "kps": kps,
    }


# ============================================================
# 二、入参筛选：一份摘要要么整份可用、要么整份跳过
# ============================================================
def _norm_kp(e) -> Optional[dict]:
    """逐项白名单一个考点条目。形状不对返回 None（调用方据此整份跳过）。"""
    if not isinstance(e, dict):
        return None
    kid = e.get("kp_id")
    kid = kid.strip() if isinstance(kid, str) else ""
    if not kid:
        return None
    hit = e.get("hit")
    if hit is not None and not isinstance(hit, bool):
        return None                     # 三态之外的值：这份摘要不敢用
    title = e.get("title")
    domain = e.get("domain")
    subclass = e.get("subclass")
    return {
        "kp_id": kid,
        "title": title.strip() if isinstance(title, str) and title.strip() else kid,
        "domain": (domain.strip() if isinstance(domain, str) and domain.strip()
                   else UNCLASSIFIED),
        "subclass": subclass.strip() if isinstance(subclass, str) else "",
        "hit": hit,
        "best_score": _num(e.get("best_score")),
        "last_score": _num(e.get("last_score")),
        "missed_base": _int(e.get("missed_base")) or 0,
        "missed_adv": _int(e.get("missed_adv")) or 0,
    }


def _select(job: str, records) -> tuple[list[dict], list[dict]]:
    """
    校验 + 归一 + 去重。返回 `(可用的摘要, skipped[])`。

    **每个入参条目必定落在且只落在一个桶里** ⇒ `len(records) == len(used) + len(skipped)`
    （重复投递的那一份算 skipped，但它代表的**那一场**仍算 used —— 见下面的去重）。

    跳过的判据全是「这一份本身坏了」（缺字段、类型不对、mode 不认识）；
    抬成 HTTP 错误的只有两条，都是**契约级**的：
      · `job_mismatch` —— 混着算会让「少算了一场」看不出来；
      · `digest_version` 全不认识且一份都用不上 —— 见函数尾那条。
    """
    if not isinstance(records, list):
        raise BadRecords("records 必须是成绩单摘要的数组（每份就是 /finish 响应里那个 "
                         "顶层 digest 键）。")
    if len(records) > config.GROWTH_MAX_RECORDS:
        raise TooManyRecords(
            f"一次最多聚合 {config.GROWTH_MAX_RECORDS} 份成绩单摘要（收到 "
            f"{len(records)} 份）。请分批调用，把最近的一批放进来。")

    used: list[dict] = []
    skipped: list[dict] = []

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            skipped.append({"session_id": "", "reason": f"第 {i + 1} 份不是对象"})
            continue

        # ⚠️ **体积排在最前**：把整份 raw 当成摘要投进来时（真会发生 —— 两者都是
        #    「一个 dict」），它的字段形状同样不对，若先查字段就会报成「版本不认识」
        #    或者「没有 session_id」，把真正的原因（给错了东西）埋掉。
        #    注意这是**解析之后**才量的：它拦不住「一个 500 MB 的请求体」，
        #    那一层要 ASGI body-size 中间件，本项目没做 —— 如实记在欠账里。
        size = len(json.dumps(rec, ensure_ascii=False))
        if size > config.GROWTH_MAX_DIGEST_BYTES:
            sid = rec.get("session_id") if isinstance(rec.get("session_id"), str) else ""
            raise DigestTooLarge(
                f"第 {i + 1} 份摘要 {size} 字节，超过上限 "
                f"{config.GROWTH_MAX_DIGEST_BYTES} 字节（session_id={sid or '?'}）。"
                "成绩单摘要是 /finish 响应里的 **digest** 键，不是 raw —— "
                "raw 含得分点原文，而且体积大一个量级。")

        sid = rec.get("session_id")
        sid = sid.strip() if isinstance(sid, str) else ""
        if not sid:
            skipped.append({"session_id": "", "reason": f"第 {i + 1} 份没有 session_id"})
            continue

        rjob = rec.get("job")
        rjob = rjob.strip() if isinstance(rjob, str) else ""
        if not rjob:
            skipped.append({"session_id": sid, "reason": "没有 job"})
            continue
        if rjob != job:
            raise JobMismatch(
                f"成绩单 {sid} 的岗位是 {rjob!r}，与本次请求的 {job!r} 不一致。"
                "（不静默丢掉 —— 混着算的话，算错的那几场在结果里看不出来。）")

        v = _int(rec.get("digest_version"))
        if v != DIGEST_VERSION:
            skipped.append({
                "session_id": sid,
                "reason": f"digest_version={rec.get('digest_version')!r} 不认识"
                          f"（本服务只认 {DIGEST_VERSION}）"})
            continue

        mode = rec.get("mode")
        if mode not in _MODES:
            # 不认识的 mode **不往 exam 里塞** —— 那会拿一份不该参与走势的成绩去
            # 影响「进步了还是退步了」。宁可少算一场，也要在 skipped 里说明白。
            skipped.append({"session_id": sid,
                            "reason": f"mode={mode!r} 不是 {list(_MODES)} 之一"})
            continue

        ts = _num(rec.get("finished_at"))
        if ts is None:
            skipped.append({"session_id": sid, "reason": "没有 finished_at"})
            continue

        kps = rec.get("kps")
        if kps is None:
            kps = []                    # 一场没答到任何考点：合法，照样进时间线
        if not isinstance(kps, list):
            skipped.append({"session_id": sid, "reason": "kps 不是数组"})
            continue
        norm, why = [], ""
        for e in kps:
            k = _norm_kp(e)
            if k is None:
                why = "kps 里有条目缺 kp_id，或 hit 不是 true/false/null"
                break
            norm.append(k)
        if why:
            skipped.append({"session_id": sid, "reason": why})
            continue

        fd = rec.get("five_dim")
        fd = fd if isinstance(fd, dict) else {}
        used.append({
            "session_id": sid,
            "job": rjob,
            "mode": mode,
            "finished_at": ts,
            "started_at": _num(rec.get("started_at")),
            "duration_sec": _num(rec.get("duration_sec")),
            "questions_asked": _int(rec.get("questions_asked")) or 0,
            "rounds_scored": _int(rec.get("rounds_scored")) or 0,
            "partial": rec.get("partial") is True,
            "total_score": _num(rec.get("total_score")),
            "total_score_100": _num(rec.get("total_score_100")),
            "five_dim": {d: _num(fd.get(d)) for d in config.DIMENSIONS},
            "kps": norm,
        })

    # ---- 去重：同一场投了多份，**后到的胜出** ----
    # 先按时间升序，这样「后到的」就是 finished_at 更新的那一份 —— 同一场的摘要
    # 本来就不该变，真变了的话更新的那份才是当前口径。排序同时让**入参顺序
    # 不影响结果**（1 号 从数据库里捞出来的顺序他不用操心）。
    by_sid: dict[str, dict] = {}
    for r in sorted(used, key=lambda r: (r["finished_at"], r["session_id"])):
        if r["session_id"] in by_sid:
            skipped.append({"session_id": r["session_id"],
                            "reason": "同一场投了多份，只采用了最新的一份"})
        by_sid[r["session_id"]] = r
    used = list(by_sid.values())

    if records and not used:
        # 「全都用不上」**不能**答 200 —— 那会让「数据全坏了」长得像「还没有历史」。
        # 与 blindspot 那条「『关掉』『坏了』『没有』必须分得开」是同一条纪律。
        head = "；".join(f"{s['session_id'] or '?'}: {s['reason']}" for s in skipped[:3])
        raise BadRecords(
            f"{len(records)} 份成绩单摘要一份都用不上（{head}"
            f"{'…' if len(skipped) > 3 else ''}）。"
            "如果 1 号 那边升级过摘要结构，请核对 digest_version。")

    return used, skipped


# ============================================================
# 三、按考点累计事实（三个视图共用的一张中间表）
# ============================================================
def _facts(used: list[dict]) -> dict[str, dict]:
    """
    把 N 份摘要摊平成 `kp_id → 累计事实`。

    `used` 已按 `finished_at` 升序 ⇒ 循环里「后写的覆盖先写的」= **以最近一次为准**。
    唯一例外是归类：`未归类` **不覆盖**已经归好的领域（两场之间翻过 KG 开关时，
    后一场的 未归类 会把前一场的分类抹掉 —— 那不是新信息，是信息丢失）。
    """
    facts: dict[str, dict] = {}
    for rec in used:
        ts, sid, mode = rec["finished_at"], rec["session_id"], rec["mode"]
        for kp in rec["kps"]:
            kid = kp["kp_id"]
            f = facts.get(kid)
            if f is None:
                f = facts[kid] = {
                    "kp_id": kid, "title": kp["title"],
                    "domain": kp["domain"], "subclass": kp["subclass"],
                    "seen_sessions": 0, "judged_sessions": 0,
                    "miss_sessions": 0, "miss_exam": 0, "miss_practice": 0,
                    "best_score": None, "last_score": None,
                    # 最近一次**判得了的**那一场给出的结论（None = 从没判过）
                    "hit": None, "hit_at": None, "hit_session_id": "",
                    "last_seen_at": None, "last_session_id": "",
                    # 最近一次**判为没答到**的那一场漏掉的条数（从没漏过就是 None）
                    "last_missed_base": None, "last_missed_adv": None,
                    "session_ids": [],
                }
            f["seen_sessions"] += 1
            f["last_seen_at"] = ts
            f["last_session_id"] = sid
            f["last_score"] = kp["last_score"]
            if kp["best_score"] is not None and (
                    f["best_score"] is None or kp["best_score"] > f["best_score"]):
                f["best_score"] = kp["best_score"]
            if kp["domain"] != UNCLASSIFIED or f["domain"] == UNCLASSIFIED:
                f["domain"], f["subclass"] = kp["domain"], kp["subclass"]
            if kp["title"]:
                f["title"] = kp["title"]

            if kp["hit"] is not None:
                f["judged_sessions"] += 1
                f["hit"], f["hit_at"], f["hit_session_id"] = kp["hit"], ts, sid
                if kp["hit"] is False:
                    f["miss_sessions"] += 1
                    if mode == MODE_EXAM:
                        f["miss_exam"] += 1
                    else:
                        f["miss_practice"] += 1
                    f["last_missed_base"] = kp["missed_base"]
                    f["last_missed_adv"] = kp["missed_adv"]
                    f["session_ids"].append(sid)
            # hit is None：**什么都不记** —— 它既不是答到、也不是没答到。
            # 但它**确实出现过**（seen_sessions 已 +1），地图要能用它说
            # 「这个考点练过，只是判不了」。
    return facts


# ============================================================
# 四、错题本
# ============================================================
def _wrong_book(facts: dict[str, dict], used: list[dict]) -> dict:
    """
    「哪些考点被判过没答到」。判据只有 `hit is False`（见文件头口径 ①）。

    ⚠️ **只给计数，不给任何百分比**。「1 场里 1 次没答到」不等于「掌握度 0%」——
    样本量不同的两个百分比没法比，而这个功能的读者是考生，一个凭空算出来的
    掌握度会直接影响他的复习安排。
    """
    items = []
    for f in facts.values():
        if f["miss_sessions"] <= 0:
            continue                    # hit is False 的场次数为 0 ⇒ 不进错题本
        items.append({
            "kp_id": f["kp_id"], "title": f["title"],
            "domain": f["domain"], "subclass": f["subclass"],
            # 反复错 vs 只错过一次。两档，不给度数。
            "status": "repeat" if f["miss_sessions"] >= _REPEAT_MIN_SESSIONS else "once",
            "miss_sessions": f["miss_sessions"],
            "miss_exam": f["miss_exam"], "miss_practice": f["miss_practice"],
            "seen_sessions": f["seen_sessions"],
            "judged_sessions": f["judged_sessions"],
            "best_score": f["best_score"], "last_score": f["last_score"],
            # 最近一次判为没答到时漏掉的**条数**（原文永远不出门）
            "last_missed_base": f["last_missed_base"],
            "last_missed_adv": f["last_missed_adv"],
            "hit_at": f["hit_at"],
            "last_seen_at": f["last_seen_at"],
            # ⚠️ 这里是**判为没答到的**那些场次，不是它出现过的全部场次 ——
            #    「我该回去看哪几场」才是错题本要回答的问题。全量在 seen_sessions。
            "session_ids": f["session_ids"][:_MAX_IDS],
        })
    # 最需要看的排前面：错得多的 → 覆盖率低的 → id（稳定）
    items.sort(key=lambda x: (-x["miss_sessions"], _score_key(x["best_score"]),
                              x["kp_id"]))

    by_mode = {"exam": 0, "practice": 0}
    for r in used:
        by_mode[r["mode"]] += 1
    enough = len(used) >= _REPEAT_MIN_SESSIONS
    return {
        "sessions_used": len(used),
        "by_mode": by_mode,
        "total": len(items),
        "enough_samples": enough,
        # 为什么要有这句话：`status="repeat"` 在只投一份摘要时**取不到值**，
        # 前端拿到的会是一整页 "once" —— 不说清楚就会被读成「他只错过一次」。
        "sample_note": (
            f"样本够（{len(used)} 场）：`status=repeat` 是可信的。" if enough else
            f"只有 {len(used)} 场，每个考点最多只会出现一次「once」—— 那不是"
            "「他只错过一次」，是「还看不出来」。再考一场这个字段才有意义。"),
        "items": items,
    }


# ============================================================
# 五、考点地图
# ============================================================
def _kp_map(job: str, facts: dict[str, dict], kg, kg_error: str) -> dict:
    """
    该岗位**全量考点**按 (领域, 子类) 铺开，并标出练过的那些。

    口径（用户定的）：**领域/子类全量 + 考点名只给练过的**。未练过的格子只给数量、
    不给名字 —— 一份「你没考过的 749 个考点名」对考生没有用，而它是题库内容的
    最大一份批量外泄面。练过的考点名会出门，是因为考生**自己考过它**。

    归类**当场重算**（`_level_of(kg, ...)`），不用摘要里记的那份域 —— 摘要记的是
    那一场当时的归类（KG 可能关着），拿它落格会和骨架重复计数。只有「练过但不在
    主库清单里」（图谱侧多出来的那些）才退回摘要里的归类。
    """
    cells: dict[tuple, dict] = {}

    def cell(domain: str, subclass: str) -> dict:
        key = (domain, subclass)
        c = cells.get(key)
        if c is None:
            c = cells[key] = {
                "domain": domain, "subclass": subclass,
                "kp_total": 0,          # 这一格有多少考点（含图谱侧多出来的）
                "kp_from_graph": 0,     # 其中「主库清单里没有」的个数
                "kp_practiced": 0, "kp_mastered": 0, "kp_missed": 0, "kp_unknown": 0,
                "practiced_ratio": 0.0,
                "practiced_kps": [],
            }
        return c

    # ---- ① 骨架：该岗位全量考点（软标签先滤掉，与 diagnose 同一个过滤）----
    skeleton = [e for e in qb.all_knowledge_points(job) if not _is_soft(e.get("title", ""))]
    skel: dict[str, tuple[str, str]] = {}
    for e in skeleton:
        d, s = _level_of(kg, e["kp_id"], e["title"])
        skel[e["kp_id"]] = (d, s)
        cell(d, s)["kp_total"] += 1

    # ---- ② 练过的：落格 + 三态计数 ----
    from_graph = 0
    for kid, f in facts.items():
        in_skel = kid in skel
        if in_skel:
            d, s = skel[kid]
        else:
            d, s = f["domain"] or UNCLASSIFIED, f["subclass"] or ""
            from_graph += 1
        c = cell(d, s)
        if not in_skel:
            # ⚠️ 骨架里已经数过一次的**不要**再数：kp_total 是「这一格有几个考点」
            #    （去重数），不是「骨架 + 验收」两遍相加。同一格重复计数会让
            #    `Σcells == kp_bank_total + kp_from_graph` 这条不变量失效，
            #    而分母错了的 practiced_ratio 会静默偏小。
            c["kp_total"] += 1
            c["kp_from_graph"] += 1
        c["kp_practiced"] += 1
        if f["hit"] is True:
            c["kp_mastered"] += 1
        elif f["hit"] is False:
            c["kp_missed"] += 1
        else:
            # ⚠️ 第三个桶**必须单列**。不单列的话前端只能用「练过 − 答到 − 没答到」
            #    倒推出一个数，而那个数会被读成「还没覆盖」—— 实际含义是
            #    「练过，但这一场判不了」（没答上来 / reranker 挂了）。
            c["kp_unknown"] += 1
        c["practiced_kps"].append({
            "kp_id": kid, "title": f["title"],
            "domain": f["domain"], "subclass": f["subclass"],
            # 最近一次**判得了的**那一场的结论。None = 从没判过（**不是**「不会」）
            "hit": f["hit"],
            "ever_missed": f["miss_sessions"] > 0,
            "seen_sessions": f["seen_sessions"], "judged_sessions": f["judged_sessions"],
            "miss_sessions": f["miss_sessions"],
            "best_score": f["best_score"], "last_score": f["last_score"],
            "last_seen_at": f["last_seen_at"],
        })

    out = list(cells.values())
    for c in out:
        c["practiced_ratio"] = (round(c["kp_practiced"] / c["kp_total"], 4)
                                if c["kp_total"] else 0.0)
        c["practiced_kps"].sort(key=lambda x: (-x["miss_sessions"], x["kp_id"]))

    # 排序：最需要看的在前（与 blindspot.domains 同一条：薄弱的排前面）。
    # ⚠️ 「未归类」**单列在最后**，不参与这个排序：它的分母是被 KG 漏掉的那些，
    #    `practiced_ratio` 在那格里没有意义；而且它不是一个学习领域，
    #    是数据质量的桶 —— 让它去竞争榜首位置只会把真正的薄弱领域挤下去。
    out.sort(key=lambda c: (1 if c["domain"] == UNCLASSIFIED else 0,
                            -c["kp_missed"], -c["kp_practiced"], -c["kp_total"],
                            c["domain"], c["subclass"]))

    return {
        "kg_available": kg is not None,
        # 「没开」与「坏了」分得开（kg_ready=false 且 kg_error 非空才是坏了）
        "kg_error": kg_error or "",
        "kp_bank_total": len(skeleton),   # 该岗位主库里的全量考点数
        "kp_practiced": len(facts),       # 其中练过的
        "kp_from_graph": from_graph,      # 练过、但主库清单里没有的（图谱侧）
        "cells": out,
        "note": ("领域与子类是**全量**的（含没练过的格子，只给数量、不给考点名）；"
                 "练过的格子才列考点名，并给出 `hit`（最近一次判得了的结论）"
                 "与 `ever_missed`（曾经错过没有）。"
                 "`hit=null` = 练过但判不了（当时没答上来 / 评分器不可用），"
                 "**不是**「不会」；`kp_unknown` 就是这一档。"),
    }


# ============================================================
# 六、历史成绩
# ============================================================
def _entry(r: dict) -> dict:
    return {
        "session_id": r["session_id"],
        "finished_at": r["finished_at"],
        "duration_sec": r["duration_sec"],
        "total_score": r["total_score"],
        "total_score_100": r["total_score_100"],
        "five_dim": r["five_dim"],
        "questions_asked": r["questions_asked"],
        "rounds_scored": r["rounds_scored"],
        "partial": r["partial"],
    }


def _exam_history(recs: list[dict]) -> dict:
    timeline = [_entry(r) for r in recs]
    n = len(timeline)
    empty_delta = {d: None for d in config.DIMENSIONS}
    if n == 0:
        return {
            "sessions": 0, "timeline": [], "first_at": None, "latest_at": None,
            "delta_total": None, "delta_five_dim": empty_delta,
            "trend_note": "还没有正式场次的成绩。",
        }

    first, last = timeline[0], timeline[-1]
    if n < 2:
        # ⚠️ 只有一场时首尾**是同一场**，按公式算必然得 0.0 —— 而 0 会被读成
        #    「持平」，实际含义是「没得比」。这里必须给 None（与「没有数据」同一
        #    条纪律：`None ≠ 0`），下面的 trend_note 已经说清了原因。
        delta_total = None
        delta_five = empty_delta
    else:
        delta_total = _delta(last["total_score_100"], first["total_score_100"])
        delta_five = {d: _delta(last["five_dim"].get(d), first["five_dim"].get(d))
                      for d in config.DIMENSIONS}

    # ⚠️ 只在「够了」的时候才给走势结论；不够就给一句说清楚为什么。
    #    绝不加「进步率」「预测分」这类由 2 个点外推出来的数。
    if n < config.GROWTH_TREND_MIN_SESSIONS:
        note = (f"样本不足（{n} 场，少于 {config.GROWTH_TREND_MIN_SESSIONS} 场），"
                "不构成趋势 —— 下面只是原始时间线。")
    elif delta_total is None:
        note = "首场或最近一场没有总分（整场没评出分），算不出变化。"
    else:
        note = ""
    return {
        "sessions": n,
        "timeline": timeline,
        "first_at": first["finished_at"],
        "latest_at": last["finished_at"],
        "delta_total": delta_total,
        "delta_five_dim": delta_five,
        "trend_note": note,
    }


def _practice_history(recs: list[dict]) -> dict:
    return {
        "sessions": len(recs),
        "timeline": [_entry(r) for r in recs],
        # 与 practice.py 报告里那句 disclaimer 同一个道理，也必须在这里再说一遍：
        # 练习是「针对某一个薄弱考点出的 3~5 道题」，不同练习之间连考点都不同。
        # ⚠️ 所以这一节**刻意没有** delta / trend_note —— 不是漏了。
        "note": ("练习场次针对的考点不同、题量也不同（3~5 道），与正式场次、以及"
                 "彼此之间都不可比：这里只作时间线留档，不给走势与变化。"),
    }


def _history(used: list[dict]) -> dict:
    return {
        "exam": _exam_history([r for r in used if r["mode"] == MODE_EXAM]),
        "practice": _practice_history([r for r in used
                                       if r["mode"] == MODE_PRACTICE]),
    }


# ============================================================
# 七、提升路径（赛题任务要求 4「能力提升路径规划」）
# ============================================================
# 与 review.py 的 actions[].text **逐字相同**（两处都指向 `/practice`）。为什么留两份
# 而不是抽成公共函数：`review` 属于 `/finish`、本模块属于 `/growth`，两边不该为了
# 一句话互相 import（`/growth` 是唯一不碰会话的端点，多一条依赖就多一处能坏）。
# ⇒ 代价是「改一处要改两处」：冒烟里有一条断言拿 review 真产出的文案与本常量比对，
#   谁改单边就红。
_ACTION_TEXT = "专门练「{title}」：出 3 道同类题，练完给前后对比。"

_PLAN_GROUPS = (
    ("to_fix", "要补的",
     "判过、没答到 —— 有客观依据（`hit is false`）。先补这一组。"),
    # ⚠️ `label` 说的是**这一组装的是什么**，不是「你想让它叫什么」。这一组的判据是
    #    `hit is None` ⟺ `judged_sessions == 0`，也就是**考到过、但那些轮次没判出分** ——
    #    不是「还没覆盖」。真「从没考过」只有 `unpracticed_kp_total` 一个数（没有名字）。
    #    早期草稿这里写的是「还没覆盖的」，与组里的内容对不上（口径不一致，已改）。
    ("uncovered", "考到过、判不了的（**不是**薄弱）",
     "考到过，但那些轮次没判出分 —— 这不是你不会，是那几轮没有可用于判分的结论"
     "（没答上来 / 评分器不可用）。**别按错题复习它**。"
     "（真正「从没考过」的考点见 `unpracticed_kp_total`，那是另一回事。）"),
)


def _why(f: dict, group: str) -> list[str]:
    """
    「为什么是它」——**只用计数事实**，每个元素都来自 > 0 的数。

    ⚠️ 两条纪律：
      · **不给百分比、不给掌握度、不给预测分**（`_wrong_book` 那段同样的理由：
        样本量不同的两个百分比没法比，而读者是考生，会照它安排复习）；
      · **0 的那一档不报**（`review.py` 文案 QA 抓到过「0 个答到了、0 个没答到」
        那种句子：报一串 0 既没信息量，又会让状态读起来像结论）。
    """
    if group == "uncovered":
        return [f"考到过 {f['seen_sessions']} 次，但那些轮次都没判出分 —— "
                f"这不是你不会，是那几轮没有可用于判分的结论。"]
    bits = []
    if f["judged_sessions"]:
        bits.append(f"判过 {f['judged_sessions']} 次，其中 {f['miss_sessions']} 次没答到")
    if f["miss_exam"] and f["miss_practice"]:
        bits.append(f"正式场次 {f['miss_exam']} 次、练习场次 {f['miss_practice']} 次")
    rest = f["seen_sessions"] - f["miss_sessions"]
    if rest > 0:
        bits.append(f"另外 {rest} 次考到了")
    miss = []
    if f["last_missed_base"]:
        miss.append(f"{f['last_missed_base']} 条基础得分点")
    if f["last_missed_adv"]:
        miss.append(f"{f['last_missed_adv']} 条进阶得分点")
    if miss:
        bits.append("最近一次漏了 " + "、".join(miss))
    return bits


def _plan_item(f: dict, rank: int, group: str, idx, res_st) -> dict:
    return {
        "rank": rank,
        "kp_id": f["kp_id"], "title": f["title"],
        "domain": f["domain"], "subclass": f["subclass"],
        "why": _why(f, group),
        "evidence": {
            "miss_sessions": f["miss_sessions"],
            "miss_exam": f["miss_exam"], "miss_practice": f["miss_practice"],
            "seen_sessions": f["seen_sessions"],
            "judged_sessions": f["judged_sessions"],
            "best_score": f["best_score"], "last_score": f["last_score"],
            # 最近一次判为没答到时漏掉的**条数**（原文永远不出门，同错题本）
            "last_missed_base": f["last_missed_base"],
            "last_missed_adv": f["last_missed_adv"],
            "last_seen_at": f["last_seen_at"],
        },
        # 只回答「有没有材料、从哪命中」—— 正文只在 /model_answer 出（四态见 resources）
        "material": material_status(idx, res_st, f["kp_id"], f["title"],
                                    f["domain"], f["subclass"]),
        # 指针式的「怎么练」：真正开练还是 POST /practice，这里只给文案与键
        "action": {
            "kind": "practice", "kp_id": f["kp_id"], "title": f["title"],
            "text": _ACTION_TEXT.format(title=f["title"]),
        },
    }


def _plan(facts: dict[str, dict], used: list[dict], kp_map: dict,
          idx=None, res_st=None) -> dict:
    """
    「先补哪个 → 为什么 → 材料在哪 → 怎么练」串成一条路。

    **两组，判据互斥、都不许改**（口径 1 的第三处引用，前两处是 `_wrong_book` 与
    `practice._weak_of`）：
      · `to_fix`    —— `miss_sessions > 0`（= 判过没答到），**有客观依据**；
      · `uncovered` —— `hit is None`（⟺ `judged_sessions == 0`），**单列、
        明确标注不是薄弱** —— 这是用户拍板的那一条，别把它并进 `to_fix`。
    ⛔ `hit is True` 的**两组都不进**（已经答到的不是「要补的」）。

    `unpracticed_kp_total` 是**第三件事**：主库骨架里**从没考过**的考点数。
    它**只给数量、不给名字**（与 `_kp_map` 同一条：一份「你没考过的 700 多个考点名」
    对考生没用，却是题库内容最大的一份批量外泄面）。数怎么来的 —— 吃 `kp_map`
    已经算好的 `kp_bank_total` 与 `kp_from_graph`，**不自己重算骨架**：
    `qb.all_knowledge_points(job)` 带软标签过滤，重算一份迟早与 `_kp_map` 分叉。

    ⚠️ **材料有无绝不影响条目数**：同一个考点，资源文件在/不在，`count` 与
    `len(items)` 必须一模一样，只有 `material.status` 变。这是「四档开关组合增量
    必须相等」那条纪律的硬约束（材料状态不是开关，但它同样不能左右数组长度）。
    """
    res_st = res_st if isinstance(res_st, dict) else {}
    groups: dict[str, list] = {"to_fix": [], "uncovered": []}
    for f in facts.values():
        if f["miss_sessions"] > 0:
            groups["to_fix"].append(f)
        elif f["hit"] is None:
            groups["uncovered"].append(f)

    # 最需要看的排前面。`to_fix` 与错题本用**同一把尺**（两处顺序不一致会被读成
    # 「同一份数据算出两个结论」）：错得多的 → 覆盖率低的（`None` 垫底）→ id 稳定序。
    groups["to_fix"].sort(key=lambda f: (-f["miss_sessions"],
                                         _score_key(f["best_score"]), f["kp_id"]))
    # `uncovered` 没有「错得多」这个维度（从没判过），只能按「被考到的次数」排。
    groups["uncovered"].sort(key=lambda f: (-f["seen_sessions"], f["kp_id"]))

    out = []
    for key, label, why_group in _PLAN_GROUPS:
        items = [_plan_item(f, i + 1, key, idx, res_st)
                 for i, f in enumerate(groups[key])]
        out.append({"key": key, "label": label, "why_this_group": why_group,
                    "count": len(items), "items": items})

    in_skeleton = len(facts) - (kp_map.get("kp_from_graph") or 0)
    unpracticed = (kp_map.get("kp_bank_total") or 0) - in_skeleton
    return {
        "groups": out,
        "unpracticed_kp_total": unpracticed,
        "sessions_used": len(used),
        "note": ("两条路一起看：`to_fix` 是有客观依据的（判过、没答到），"
                 "`uncovered` **不是薄弱** —— 它只是那几轮没判出分，别按错题复习。"
                 f"另外这个岗位还有 {unpracticed} 个考点你**从没考过**"
                 "（就是 `unpracticed_kp_total` 这个数）：那既不是"
                 "「会」也不是「不会」，只是还没覆盖到（只给数量、不给考点名）。"
                 "每条路径的 `material` 只说明**有没有**材料（四态：ready / disabled / "
                 "broken / not_found —— 「没开开关」「文件坏了」「这个考点没材料」"
                 "是三件事）；**正文要单独调 `POST /model_answer` 取**，那里有一道"
                 "「源场次必须已交卷、且这个考点出现在那一场的诊断里」的结构性闸。"),
    }


# ============================================================
# 七、入口（接口层只调这一个）
# ============================================================
def aggregate(job: str, records, kg=None, kg_error: str = "",
              idx=None, res_st=None) -> dict:
    """
    一批成绩单摘要 → 四视图。**纯函数**：不读盘、不写盘、不碰会话、不知道是谁。

    `kg` 由接口层注入（`kg.get_kg()`，取不到就是 `None`，**绝不抛**）；
    `kg_error` 只用于让「没开 KG」与「KG 坏了」在 `kp_map` 里分得开。
    直接传 `kg=None` 也能跑（冒烟的纯函数节就是这么测的），那时全部落「未归类」。

    `idx` / `res_st` 同理由接口层注入（`resources.load_index()` / `resource_status()`），
    只给 `plan` 判断「这个考点有没有材料」用。**两个都不传也能跑**，那时每条材料的
    `status` 是 `disabled` —— 与真的关掉资源开关的表现一致，条目数不受影响。
    """
    used, skipped = _select(job, records)
    facts = _facts(used)
    # ⚠️ `kp_map` 必须先算：`plan` 的「从没考过几个考点」直接吃它的 `kp_bank_total`
    #    与 `kp_from_graph`，不自己重算骨架（见 `_plan` 的说明）。
    kp_map = _kp_map(job, facts, kg, kg_error)
    return {
        "job": job,
        "record_count": len(used),
        "skipped": skipped,
        "wrong_book": _wrong_book(facts, used),
        "kp_map": kp_map,
        "history": _history(used),
        "plan": _plan(facts, used, kp_map, idx=idx, res_st=res_st),
    }
