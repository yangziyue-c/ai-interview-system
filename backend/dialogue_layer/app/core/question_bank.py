# -*- coding: utf-8 -*-
"""
question_bank.py · 主库题库（5012 题）
============================================================
只读加载 5 个岗位 JSON，提供：
- 按阶段难度选题（sample）
- 按题目ID 取原始记录（by_id，给工具/调试用）
- 主库字段的解析器（得分点拆条、三级追问、关联知识点）

字段名集中在本模块的常量里，不要在别处硬编码中文字段名。

⚠️ 主库文件是唯一真值源，**只读**，任何情况下不要修改。
"""
import json
import os
import random
import re
import threading
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

    trace —— 可选的 dict，回填 {"level": "r0"|"r1"|"r2"|"r3"|"none"}。
    记下用了哪一级是日后调阈值（KP_OVERLAP_THRESHOLD 等）的唯一依据。
    """
    bank = load_bank(job)
    if not bank:
        if trace is not None:
            trace["level"] = "none"
        return None
    excluded = set(exclude_ids)

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
