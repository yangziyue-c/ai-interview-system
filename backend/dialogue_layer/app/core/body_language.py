# -*- coding: utf-8 -*-
"""Normalization and bounded score impact for camera posture summaries."""
from __future__ import annotations

from typing import Any


BODY_EMPTY = {
    "used": False,
    "available": False,
    "score": None,
    "confidence": "low",
    "quality_status": "not_provided",
    "metrics": {},
    "feedback": [],
}

_CONFIDENCE = {"low", "medium", "high"}


def _number(value: Any):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def normalize_summary(value: Any) -> dict:
    """Return the closed, numeric-only summary accepted from /chat."""
    if not isinstance(value, dict):
        return dict(BODY_EMPTY)
    confidence = str(value.get("confidence") or "low").strip().lower()
    if confidence not in _CONFIDENCE:
        confidence = "low"
    status = str(value.get("quality_status") or "").strip()[:40]
    metrics = value.get("metrics")
    clean_metrics = {}
    if isinstance(metrics, dict):
        for key, raw in metrics.items():
            name = str(key or "").strip()[:60]
            if not name:
                continue
            if isinstance(raw, bool):
                clean_metrics[name] = raw
            elif isinstance(raw, (int, float)):
                number = _number(raw)
                if number is not None:
                    clean_metrics[name] = round(number, 4)
    feedback = value.get("feedback")
    clean_feedback = [
        str(x).strip()[:120] for x in feedback[:3]
    ] if isinstance(feedback, list) else []
    score = _number(value.get("score"))
    if score is not None:
        score = max(0.0, min(5.0, score))
    available = bool(value.get("available")) and score is not None
    if not available:
        score = None
    return {
        "used": True,
        "available": available,
        "score": round(score, 2) if score is not None else None,
        "confidence": confidence,
        "quality_status": status,
        "metrics": clean_metrics,
        "feedback": clean_feedback,
    }


def score_adjustment(summary: dict | None) -> dict:
    """Return bounded score deltas; low-confidence or incomplete data abstains."""
    body = normalize_summary(summary) if summary else dict(BODY_EMPTY)
    result = {
        "applied": False,
        "reason": "no_body_data",
        "communication_delta": 0.0,
        "adaptability_delta": 0.0,
        "body_score": body.get("score"),
        "confidence": body.get("confidence") or "low",
    }
    if not body.get("available") or body.get("score") is None:
        result["reason"] = "body_score_unavailable"
        return result
    if body.get("confidence") == "low":
        result["reason"] = "low_confidence_abstain"
        return result
    quality = body.get("quality_status")
    if quality and quality != "ready":
        result["reason"] = "quality_not_ready"
        return result
    centered = max(-1.5, min(1.5, float(body["score"]) - 3.0))
    factor = 1.0 if body["confidence"] == "high" else 0.5
    communication = max(-0.30, min(0.30, centered * 0.20 * factor))
    adaptability = max(-0.20, min(0.20, centered * 0.133333 * factor))
    result.update({
        "applied": True,
        "reason": "bounded_weak_signal",
        "communication_delta": round(communication, 2),
        "adaptability_delta": round(adaptability, 2),
    })
    return result


def apply_to_five_dim(five_dim: dict | None, summary: dict | None) -> dict:
    """Return a copy of five_dim with only the two permitted dimensions moved."""
    data = dict(five_dim or {})
    adjustment = score_adjustment(summary)
    if not adjustment.get("applied") or not data:
        return data
    for dimension, key in (
        ("沟通表达", "communication_delta"),
        ("应变能力", "adaptability_delta"),
    ):
        current = _number(data.get(dimension))
        if current is None:
            continue
        data[dimension] = round(max(0.0, min(5.0, current + adjustment[key])), 2)
    return data


def prompt_note(summary: dict | None) -> str:
    """A short note for the scoring prompt; empty when no camera data exists."""
    body = normalize_summary(summary) if summary else dict(BODY_EMPTY)
    if not body.get("used"):
        return ""
    if not body.get("available") or body.get("score") is None:
        return (
            "摄像头姿态数据不足或质量不合格，本项弃权；不得据此推测紧张、"
            "自信、诚实、性格或技术能力。"
        )
    adjustment = score_adjustment(body)
    metrics = body.get("metrics") or {}
    fields = []
    for key, label in (
        ("presence_rate", "画面覆盖"),
        ("head_stability", "头部稳定"),
        ("shoulder_tilt_delta_deg", "肩线漂移"),
        ("upper_body_motion", "上身移动"),
        ("gesture_rate_per_min", "手势频率"),
        ("framing_stability", "取景稳定"),
    ):
        value = _number(metrics.get(key))
        if value is not None:
            fields.append(f"{label} {value:g}")
    if adjustment.get("applied"):
        rule = (
            "该信号最多只允许调整「沟通表达」±0.30、"
            "「应变能力」±0.20；不得影响技术水平、逻辑思维、岗位匹配度。"
        )
        if adjustment["body_score"] >= 3:
            rule += "它只能是同向旁证，禁止因为姿态平稳就替答案加分。"
        else:
            rule += "低质量、低可信或画面覆盖不足时必须弃权，不能据此扣分。"
    else:
        rule = "该信号不可用，本项弃权；不得转换成加分或扣分。"
    detail = ("；".join(fields) + "。" if fields else "")
    return (
        f"摄像头姿态摘要：分 {body['score']:.2f}/5，可信度 {body['confidence']}。"
        f"{detail}{rule}"
    )
