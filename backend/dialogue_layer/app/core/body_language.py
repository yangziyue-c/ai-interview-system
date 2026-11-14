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
    """Legacy compatibility entry point; camera data never changes scores."""
    body = normalize_summary(summary) if summary else dict(BODY_EMPTY)
    return {
        "applied": False,
        "mode": "display_only",
        "reason": (
            "body_data_available"
            if body.get("available") and body.get("score") is not None
            else "body_score_unavailable"
        ),
        "communication_delta": 0.0,
        "adaptability_delta": 0.0,
        "body_score": body.get("score"),
        "confidence": body.get("confidence") or "low",
    }


def display_only_adjustment(summary: dict | None) -> dict:
    """Describe camera data without allowing it to change any five-dim score.

    Body-language data is useful as candidate-facing feedback, but it is not a
    valid measure of technical, logical, communication or adaptability ability.
    Keeping the field in the payload preserves observability without turning a
    device-dependent posture signal into score movement.
    """
    return score_adjustment(summary)


def apply_to_five_dim(five_dim: dict | None, summary: dict | None) -> dict:
    """Compatibility no-op: camera posture is feedback, never score movement."""
    return dict(five_dim or {})


def prompt_note(summary: dict | None) -> str:
    """Candidate-facing status only; never attach camera data to score prompts."""
    body = normalize_summary(summary) if summary else dict(BODY_EMPTY)
    if not body.get("used"):
        return ""
    if not body.get("available") or body.get("score") is None:
        return "摄像头姿态数据不足或质量不合格，仅作展示，不参与评分。"
    return "摄像头姿态数据仅作表达反馈，不进入五维评分。"
