# -*- coding: utf-8 -*-
"""
question_bank.py · 主库题库（5012 题）
============================================================
只读加载 5 个岗位 JSON，提供：
- 按阶段难度选题（sample）
- 按题目ID 取原始记录（by_id，给工具/调试用）
- 按**知识点**找题（find_by_knowledge，专项强化练习用，赛题 4b）
- 主库字段的解析器（得分点拆条、三级追问、关联知识点）
- 考点名归一化（norm_kp_title —— 全项目唯一一份，别在别处再写一遍）

字段名集中在本模块的常量里，不要在别处硬编码中文字段名。

⚠️ 主库文件是唯一真值源，**只读**，任何情况下不要修改。
"""
import json
import os
import random
import re
import threading
import unicodedata
from typing import Optional

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)

# ---------- 主库字段名 ----------
F_ID = "题目ID"
F_JOB = "所属岗位"
F_CATEGORY = "题型分类"
F_DIFFICULTY = "难度等级"      # 真实取值：easy / medium / hard
F_STAGE = "面试阶段"           # 注意：这个字段的分布与 3/5/2 计划不一致，只作参考
F_KEYWORDS = "核心关键词"
F_PRIORITY = "考点优先级"
F_QUESTION = "题目内容"
F_BASE_POINTS = "基础得分点"
F_ADV_POINTS = "进阶得分点"
F_FOLLOW_L1 = "L1基础追问"
F_FOLLOW_L2 = "L2递进追问"
F_FOLLOW_L3 = "L3拓展追问"
F_DEGRADE = "降级策略"          # 纯散文，**没有** [触发]/[追问] 标记，不要用 parse_follow_up 解析
F_EST_MINUTES = "建议用时(分)"
F_ANCHOR = "单题校准锚点"
F_KNOWLEDGE = "关联知识点"       # 每行 id|title|description

_RE_FOLLOWUP_TAG = re.compile(r"^\[追问\]\s*(.*)$")
_RE_TRIGGER_TAG = re.compile(r"^\[触发\]")
_RE_PURE_NUMBERING = re.compile(r"^\d+[\.、]\s*$")

# 题库缓存：job -> [record, ...]
_BANK: dict[str, list[dict]] = {}
# 索引缓存：job -> {题目ID: record}
_INDEX: dict[str, dict[str, dict]] = {}
_BANK_LOCK = threading.RLock()


class BankError(RuntimeError):
    """题库加载失败。"""


def _bank_path(job: str) -> Optional[str]:
    fname = config.JOB_FILE_MAP.get(job)
    if not fname:
        return None
    return os.path.join(config.MAIN_DB_DIR, fname)


def load_bank(job: str) -> list[dict]:
    """按岗位加载题库（带缓存）。未知岗位返回空列表，调用方需自行报错。"""
    with _BANK_LOCK:
        if job in _BANK:
            return _BANK[job]

        path = _bank_path(job)
        if not path:
            logger.error("未知岗位 %r，没有对应的题库文件映射", job)
            _BANK[job] = []
            return []

        if not os.path.exists(path):
            raise BankError(f"题库文件不存在：{path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise BankError(f"题库格式异常（应为 JSON 数组）：{path}")

        _BANK[job] = data
        _INDEX[job] = {r.get(F_ID): r for r in data if r.get(F_ID)}
        logger.info("题库已加载 job=%s n=%d file=%s", job, len(data), os.path.basename(path))
        return data


def by_id(job: str, question_id: str) -> Optional[dict]:
    """按题目ID O(1) 取原始记录（工具/调试用；面试主流程不走这里）。"""
    load_bank(job)
    return _INDEX.get(job, {}).get(question_id)


def bank_sizes() -> dict[str, int]:
    """已加载岗位的题量（给 /health 用）。"""
    with _BANK_LOCK:
        return {job: len(_BANK[job]) for job in _BANK}


def preload(jobs: Optional[list[str]] = None) -> dict[str, int]:
    """预加载题库。启动时调用，避免第一个请求承担加载延迟。"""
    result = {}
    for job in (jobs or config.JOBS):
        try:
            result[job] = len(load_bank(job))
        except Exception as e:
            logger.error("题库预加载失败 job=%s err=%s", job, e)
            result[job] = 0
    return result


def sample(job: str, difficulties: set[str], exclude_ids: list[str] | set[str],
           accept=None, accept_relaxed=None,
           trace: Optional[dict] = None) -> Optional[dict]:
    """
    按难度集合随机抽一题，排除已出过的题目ID。
    先按难度筛；筛空了就放宽难度（保证面试能走完），仍为空则返回 None。

    四级兜底阶梯（r0/r1 是新增的两级，插在原有的两级**之前**）：

      r0  难度 ∩ 未出过 ∩ accept()         ← 最严（知识点几乎不重复）
      r1  难度 ∩ 未出过 ∩ accept_relaxed() ← 放宽一档
      r2  难度 ∩ 未出过                    ← 原有行为
      r3  全库 ∩ 未出过                    ← 原有行为（放宽难度，并 warning）
      none → None                         ← 题库抽空，原有行为

    accept / accept_relaxed 是**调用方注入的候选过滤器**（两个接受单题的谓词）。
    为什么用闭包而不是在这里 import 图谱：本模块是**只读数据层**，
    不该知道「知识点覆盖度」这种业务策略 —— 与文件头「字段名集中在本模块常量里」
    是同一条原则。KG 关闭时两个参数都是 None，本函数的行为与以前逐字节相同。

    trace —— 可选的 dict，回填 {"level": "pin"|"r0"|"r1"|"r2"|"r3"|"none"}。
    记下用了哪一级是日后调阈值（KP_OVERLAP_THRESHOLD 等）的唯一依据。
    （`"pin"` 与 practice.py 的 `"practice"` 一样，是**阶梯之外**的一级。）
    """
    bank = load_bank(job)
    if not bank:
        if trace is not None:
            trace["level"] = "none"
        return None
    excluded = set(exclude_ids)

    # ---------- 钉题表（A11_QB_PIN）----------
    # 用途只有一个：**同题两臂真 LLM 对照**要两臂题目序列一致。钉题表提供的是
    # 「确定性本身」，不是"大概同题"。
    #
    # 为什么不用随机种子（`A11_QB_SEED`）：下面 `_pick` 用的是**全局** `random`，
    # "同 seed → 同题"这条链会被**换题**打断 —— 换题要多消耗一次抽签，之后全体错位；
    # 而上一轮三臂对照里三场**都**在第 2 题换了题 ⇒ 撞上的概率并不低。
    #
    # 取表里**第一个「在库且未被排除」**的 qid。刻意**不按难度筛、不过 accept()**：
    # 钉题的全部意义就是确定，任何随机或过滤都会把它变回"近似"。
    # 表空（默认）或都不匹配 → **直接走原阶梯，行为逐字节不变**（冒烟有断言）。
    if config.QB_PIN:
        for qid in config.QB_PIN:
            if qid in excluded:
                continue
            for q in bank:
                if str(q.get(F_ID)) == qid:
                    logger.info("选题避重 level=pin job=%s qid=%s", job, qid)
                    # 这里不调 _done()：它定义在下面（`_pick` 之后），此刻还没绑定。
                    # 就地回填 trace，等价且不依赖定义顺序。
                    if trace is not None:
                        trace["level"] = "pin"
                    return q

    def _pick(candidates: list[dict], acc=None) -> Optional[dict]:
        pool = [q for q in candidates
                if q.get(F_ID) not in excluded and (acc is None or acc(q))]
        return random.choice(pool) if pool else None      # ← random.choice 原样保留

    def _done(rec: Optional[dict], level: str) -> Optional[dict]:
        if trace is not None:
            trace["level"] = level if rec is not None else "none"
        return rec

    by_diff = [q for q in bank if q.get(F_DIFFICULTY) in difficulties]

    for level, acc in (("r0", accept), ("r1", accept_relaxed)):
        if acc is None:
            continue
        hit = _pick(by_diff, acc)
        if hit is not None:
            logger.info("选题避重 level=%s job=%s qid=%s",
                        level, job, hit.get(F_ID))
            return _done(hit, level)

    hit = _pick(by_diff)
    if hit is not None:
        return _done(hit, "r2")

    logger.warning("岗位 %s 在难度 %s 下已无未出过的题，放宽难度限制", job, difficulties)
    hit = _pick(bank)
    return _done(hit, "r3")


# ============================================================
# 按知识点找题（专项强化练习用，赛题 4b）
# ============================================================
def norm_kp_title(s: str) -> str:
    """
    考点名归一键：NFKC（全角→半角）→ 去所有非文字字符 → 转小写。

    为什么放在数据层：按名字匹配知识点是**读数据**的活，与字段解析同源；
    上层（resources.py 的连接规则、practice.py 的专项选题）复用这一份，
    保证「同一个考点名在两条路上归一出同一个键」。

    为什么用 `[\\W_]+` 而不是自己列标点：Python 的 `\\w` 在 unicode 模式下
    **包含 CJK**，所以这个字符类恰好等于「汉字/字母/数字留下，标点与空白去掉」。
    """
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\W_]+", "", s).casefold()


def knowledge_index(job: str) -> dict[str, list[dict]]:
    """
    反查表：考点（按 `kp_id` 与「归一后的考点名」两种键）→ 挂着它的题目列表。

    ⚠️ 一次遍历建两份键，**返回的是同一个题目对象**（不是两份拷贝）——
    调用方按 id 命中还是按名字命中，拿到的都是题库里那一条。
    与 `kg.kp_map` 的「主库 ∪ 图谱」并集不同：这里**只看主库自己的
    `关联知识点` 字段**，不引入图谱 —— 专项练习要的是「这道题本身讲的就是这个
    考点」，而图谱的绑定是松的（实测有跨岗位误挂，见资源推荐设计稿 §2）。
    """
    out: dict[str, list[dict]] = {}
    for q in load_bank(job):
        for kp in parse_knowledge_points(q.get(F_KNOWLEDGE, "")):
            kid = (kp.get("id") or "").strip()
            if kid:
                out.setdefault(kid, []).append(q)
            nt = norm_kp_title(kp.get("title") or "")
            if nt:
                out.setdefault(nt, []).append(q)
    return out


def find_by_knowledge(job: str, kp_id: str = "", title: str = "",
                      exclude_ids=()) -> tuple[list[dict], list[dict], str]:
    """
    按一个考点找题。返回 `(没考过的, 考过的, 命中的键)`。

    命中的键是 `"kp_id"` / `"title"` / `""`（都没命中）—— 写进报告，便于事后
    核对「专项练习到底按什么选的题」。**按 id 命中优先**（title 只是兜底）：
    主库的 `关联知识点` 每行是 `id|title|description`，id 才是稳定的那个。

    调用方（practice.py）自己决定取几道、怎么排；本函数只做「查」。
    """
    idx = knowledge_index(job)
    hit_key = ""
    pool: list[dict] = []
    if kp_id and kp_id in idx:
        pool, hit_key = list(idx[kp_id]), "kp_id"
    else:
        nt = norm_kp_title(title)
        if nt and nt in idx:
            pool, hit_key = list(idx[nt]), "title"
    ex = set(exclude_ids or ())
    fresh = [q for q in pool if q.get(F_ID) not in ex]
    used = [q for q in pool if q.get(F_ID) in ex]
    # 排序：高频必考优先 → 题目ID（稳定，不随机 —— 同一场练习重复调用选到同一批）
    key = lambda q: (q.get(F_PRIORITY) != "高频必考题", q.get(F_ID) or "")
    return sorted(fresh, key=key), sorted(used, key=key), hit_key


# 全量考点清单缓存：job -> [{"kp_id","title","question_count"}, ...]（只读、进程内一次）
_KP_LIST: dict[str, list[dict]] = {}


def all_knowledge_points(job: str) -> list[dict]:
    """
    该岗位题库 `关联知识点` 里的**全部考点**（成长档案的「考点地图」拿它当骨架）。

    返回 `[{"kp_id", "title", "question_count"}, ...]`，按 `kp_id` **升序** —— 定序是
    刻意的（与 `find_by_knowledge` 的排序同一条纪律）：同一份数据两次调用给出不同顺序，
    前端与冒烟都没法比对。

    ⚠️ **为什么不在调用方靠「kp_id 的形态」判别**：实测主库里的 id 有四种写法 ——
       `java-backend-kp-0022` / `java-backend-kp-gen-5775` /
       `java_backend-kp-soft-17589`（**用下划线**）/ `kp-soft-50598`；
       而且**同一个 id 会跨岗位出现**（5 个岗位各自去重后相加是 1683，全库去重只剩 1513）。
       从标点推类型是隐式契约，这个项目一直在避免，所以这里老老实实遍历题目、解析字段。

    ⚠️ **去重键是 `kp_id`，不是考点名**：实测「一个考点名对应多个 kp_id」很常见
       （java 37 例，`哈希表` 一个名字对应 8 个 id）—— 按名字去重会**合并掉不同考点**。
       反过来「一个 kp_id 对应多个考点名」在 5 个岗位里**都是 0 例**（实测 2026-09-25），
       所以 kp_id → title 是函数，取首次出现的即可；真出现冲突会在日志里点名。

    ⚠️ **本函数不做任何业务过滤**（软标签、未归类都不管）—— 那是调用方的口径，
       数据层只负责如实列全。成长档案那一侧按 `blindspot.SOFT_TAGS` 滤软标签，
       理由见 app/core/growth.py 里那段注释。
    """
    with _BANK_LOCK:
        cached = _KP_LIST.get(job)
    if cached is not None:
        return cached

    seen: dict[str, dict] = {}
    conflicts: list[str] = []
    for q in load_bank(job):
        qid = q.get(F_ID)
        for kp in parse_knowledge_points(q.get(F_KNOWLEDGE, "")):
            kid = (kp.get("id") or "").strip()
            if not kid:
                # 没有 id 的行（`关联知识点` 里只有标题）：**不进考点清单**。
                # 考点地图按 kp_id 建键（理由见上），没有 id 就没有稳定的键。
                continue
            title = (kp.get("title") or "").strip() or kid
            e = seen.get(kid)
            if e is None:
                seen[kid] = {"kp_id": kid, "title": title, "qids": {qid}}
            else:
                e["qids"].add(qid)
                if e["title"] != title:
                    conflicts.append(f"{kid}:{e['title']!r}/{title!r}")

    out = [{"kp_id": e["kp_id"], "title": e["title"],
            "question_count": len(e["qids"]) - (None in e["qids"])}
           for e in sorted(seen.values(), key=lambda e: e["kp_id"])]
    if conflicts:
        logger.warning("job=%s 有 %d 个 kp_id 对应了多个考点名（实测应为 0 例，"
                       "题库可能变了，考点地图只会用首次出现的那个）：%s",
                       job, len(conflicts), conflicts[:5])
    with _BANK_LOCK:
        _KP_LIST[job] = out
    return out


# ============================================================
# 字段解析器
# ============================================================
def split_points(text: str) -> list[str]:
    """
    把「基础得分点 / 进阶得分点」拆成单条。
    过滤掉太短的行（标题、编号、残句）和明显的标题行。
    """
    if not text:
        return []
    out = []
    for line in text.split("\n"):
        p = line.strip()
        if len(p) < config.MIN_POINT_CHARS:
            continue
        if p.startswith("【") or p.endswith("："):
            continue
        if _RE_PURE_NUMBERING.match(p):
            continue
        out.append(p)
    return out


def parse_follow_up(text: str) -> str:
    """
    从 L1/L2/L3 追问字段里取出 [追问] 的那句话。
    真实格式：可能有 **多个** [触发] 行，加一行 [追问] 行
    （例如 easy 题的 L3 就有两个 [触发]）。

    注意：「降级策略」是纯散文、**没有**这些标记，不要用它调本函数。
    """
    if not text:
        return ""
    for line in text.split("\n"):
        m = _RE_FOLLOWUP_TAG.match(line.strip())
        if m and m.group(1).strip():
            return m.group(1).strip()
    # 没有 [追问] 标记：退回第一行非 [触发] 的正文
    for line in text.split("\n"):
        s = line.strip()
        if s and not _RE_TRIGGER_TAG.match(s):
            return s
    return ""


def parse_knowledge_points(text: str) -> list[dict]:
    """「关联知识点」每行 id|title|description → [{'id','title','description'}]"""
    out = []
    if not text:
        return out
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        parts = s.split("|")
        if len(parts) >= 2:
            out.append({
                "id": parts[0].strip(),
                "title": parts[1].strip(),
                "description": "|".join(parts[2:]).strip(),
            })
        else:
            out.append({"id": "", "title": s, "description": ""})
    return out


def knowledge_titles(text: str, limit: int = 5) -> list[str]:
    """给前端展示用的知识点标题短列表。"""
    return [kp["title"] for kp in parse_knowledge_points(text)[:limit]]


def split_lines(text: str) -> list[str]:
    """把用 \\n 拼接的多行字段拆成列表（核心关键词等）。"""
    return [s.strip() for s in (text or "").split("\n") if s.strip()]


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"
