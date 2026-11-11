# -*- coding: utf-8 -*-
"""Turn retrieved KB passages into hidden evidence and safe probe seeds."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, Optional


_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_CODE_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_+#.]{2,}")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_CODE_LIKE = re.compile(
    r"(^\s*(?:```|~~~|//|/\*|\*|@|public\b|private\b|class\b|def\b|return\b|"
    r"if\b|for\b|while\b|select\b|insert\b|update\b|delete\b))",
    re.IGNORECASE,
)
_ACTIONABLE = (
    "为什么", "原因", "机制", "原理", "区别", "对比", "不同", "条件", "边界",
    "限制", "上限", "下限", "范围", "失败", "异常", "丢失", "死锁", "超时",
    "泄漏", "错误", "实现", "源码", "协议", "流程", "并发", "竞争", "锁",
    "一致性", "可见性", "原子性", "性能", "复杂度", "恢复", "重试",
)


def norm_text(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    return _NON_WORD.sub("", value).casefold()


def _ngrams(text: object, n: int = 2) -> set[str]:
    value = norm_text(text)
    if not value:
        return set()
    if len(value) <= n:
        return {value}
    return {value[i:i + n] for i in range(len(value) - n + 1)}


def jaccard(a: object, b: object, n: int = 2) -> float:
    left, right = _ngrams(a, n), _ngrams(b, n)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def contains_ratio(needle: object, haystack: object) -> float:
    a, b = norm_text(needle), norm_text(haystack)
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    return jaccard(a, b, 2)


def split_segments(document: str) -> list[str]:
    text = str(document or "")
    text = re.sub(r"```.*?```", "\n", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", "\n", text, flags=re.DOTALL)
    rows: list[str] = []
    for raw in text.splitlines():
        line = _HEADING.sub("", raw).strip()
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s*", "", line).replace("`", "")
        line = " ".join(line.split())
        if not line or _CODE_LIKE.search(line):
            continue
        if line.startswith("|") and line.endswith("|"):
            continue
        if line.startswith("![") or re.match(r"^https?://", line):
            continue
        rows.extend(part.strip() for part in re.split(
            r"(?<=[。！？!?；;])", line) if part.strip())
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if len(row) < 16 or len(row) > 260:
            continue
        if not re.search(r"[\u4e00-\u9fff]", row):
            continue
        key = norm_text(row)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _actionability(text: str) -> float:
    value = norm_text(text)
    return min(1.0, sum(1 for word in _ACTIONABLE
                       if norm_text(word) in value) / 3.0)


def _length_quality(text: str) -> float:
    size = len(norm_text(text))
    if size < 40:
        return max(0.0, size / 40.0)
    if size > 140:
        return max(0.0, 1.0 - (size - 140) / 160.0)
    return 1.0


def _probe_type(text: str) -> str:
    value = norm_text(text)
    if any(word in value for word in ("为什么", "原因", "由于", "导致", "因为")):
        return "causal"
    if any(word in value for word in ("区别", "不同", "相比", "对比")):
        return "contrast"
    if any(word in value for word in (
            "条件", "边界", "限制", "上限", "下限", "范围", "前提")):
        return "boundary"
    if any(word in value for word in (
            "失败", "异常", "丢失", "死锁", "超时", "泄漏", "错误")):
        return "failure_mode"
    if any(word in value for word in (
            "实现", "机制", "原理", "源码", "协议", "流程")):
        return "mechanism"
    return "clarify"


def _anchor(text: str, question: str, misses: Iterable[str]) -> str:
    idents = list(dict.fromkeys(_CODE_IDENT.findall(text)))
    if idents:
        return " / ".join(idents)[:70]
    for row in misses:
        for word in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_+#.]{2,16}", row):
            if norm_text(word) in norm_text(text):
                return word[:50]
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_+#.]{3,16}", question)
    return tokens[0][:40] if tokens else "这个点"


def _question_seed(text: str, question: str,
                   misses: Iterable[str]) -> tuple[str, str]:
    probe_type = _probe_type(text)
    anchor = _anchor(text, question, misses)
    templates = {
        "causal": f"请结合你的回答解释：{anchor}背后的原因和触发条件是什么？",
        "contrast": f"请结合你的回答，具体对比一下：{anchor}。",
        "boundary": f"{anchor}在什么条件下成立或失效？请说明边界。",
        "failure_mode": f"如果{anchor}处理不当，会出现什么故障或错误？",
        "mechanism": f"请把{anchor}的实现机制讲得更具体。",
        "clarify": f"请具体说明：{anchor}。",
    }
    return probe_type, templates[probe_type]


def _candidate_id(kb_id: str, text: str) -> str:
    digest = hashlib.sha1(
        (str(kb_id) + "\0" + str(text)).encode("utf-8")).hexdigest()[:12]
    return f"kbprobe:{digest}"


def extract_probe_candidates(refs: Optional[list[dict]],
                             question: str, answer: str,
                             misses: Optional[Iterable[str]] = None,
                             top_n: int = 3) -> list[dict]:
    """Build hidden evidence cards and interviewer-safe probe seeds."""
    miss_rows = [str(row) for row in (misses or []) if str(row).strip()]
    topic = " ".join([question, *miss_rows])
    ranked: list[dict] = []
    seen: set[str] = set()
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        document = str(ref.get("_document") or ref.get("片段") or "")
        kb_id = str(ref.get("kb_id") or "")
        for segment in split_segments(document):
            if norm_text(segment) in seen:
                continue
            seen.add(norm_text(segment))
            topic_rel = jaccard(segment, topic)
            answer_rel = jaccard(segment, answer)
            novelty = 1.0 - max(
                (jaccard(segment, row, 2) for row in miss_rows), default=0.0)
            question_echo = contains_ratio(segment, question)
            actionability = _actionability(segment)
            length_quality = _length_quality(segment)
            score = (
                0.30 * topic_rel
                + 0.22 * answer_rel
                + 0.20 * novelty
                + 0.18 * actionability
                + 0.10 * length_quality
                - 0.60 * question_echo
            )
            if question_echo >= 0.68:
                continue
            probe_type, seed = _question_seed(segment, question, miss_rows)
            ranked.append({
                "gap_id": _candidate_id(kb_id, segment),
                "source": "kb_probe",
                "text": segment,
                "target_concept": segment,
                "question_seed": seed,
                "probe_type": probe_type,
                "hidden_evidence": True,
                "do_not_reveal": list(dict.fromkeys(
                    _CODE_IDENT.findall(segment))),
                "source_kb_id": kb_id,
                "source_repo": str(ref.get("来源仓库") or ""),
                "source_path": str(ref.get("来源路径") or ""),
                "source_heading": str(ref.get("章节标题") or ""),
                "features": {
                    "score": round(score, 6),
                    "topic_relevance": round(topic_rel, 6),
                    "answer_relevance": round(answer_rel, 6),
                    "novelty_vs_score_points": round(novelty, 6),
                    "question_echo": round(question_echo, 6),
                    "actionability": round(actionability, 6),
                    "length_quality": round(length_quality, 6),
                },
            })
    ranked.sort(key=lambda row: (
        -float((row.get("features") or {}).get("score") or 0.0),
        str(row.get("gap_id") or ""),
    ))
    return ranked[:max(0, int(top_n))]


def plan_from_candidate(candidate: dict) -> dict:
    """Convert a safe probe seed into the existing probe-plan contract."""
    probe_type = str(candidate.get("probe_type") or "clarify")
    if probe_type in ("causal", "mechanism", "boundary", "contrast"):
        kind = "deepen_reason"
        instruction = (
            "只追这个具体机制点或边界，不要照念证据句，也不要同时追问多个结论。")
    elif probe_type == "failure_mode":
        kind = "extend_engineering"
        instruction = (
            "只追这个失败场景，问清触发条件、影响和兜底，不要照念证据句。")
    else:
        kind = "clarify_basic"
        instruction = "只补这个基础概念或区别，不要照念证据句。"
    return {
        "target": str(candidate.get("question_seed") or "").strip(),
        "kind": kind,
        "source": "kb_probe",
        "kb_id": str(candidate.get("source_kb_id") or ""),
        "do_not_reveal": list(candidate.get("do_not_reveal") or []),
        "instruction": instruction,
    }
