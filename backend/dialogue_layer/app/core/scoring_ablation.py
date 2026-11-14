"""Paired ablation metrics for scoring evidence.

Input is JSONL. Each line must contain:
  {"sample_id": "...", "human_score": 0-5, "scores": {
      "off": 0-5, "kb": 0-5, "kg": 0-5, "both": 0-5}}

The same rows are used for all arms. This is intentionally a pure analysis
module: it never calls a model and never changes production scoring.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable


ARMS = ("off", "kb", "kg", "both")
SEVERE_LOW_THRESHOLD = 2.5


def _pairs(rows: list[dict], arm: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for row in rows:
        truth = row.get("human_score")
        pred = (row.get("scores") or {}).get(arm)
        if (
            isinstance(truth, (int, float))
            and not isinstance(truth, bool)
            and isinstance(pred, (int, float))
            and not isinstance(pred, bool)
            and math.isfinite(float(truth))
            and math.isfinite(float(pred))
        ):
            out.append((float(truth), float(pred)))
    return out


def mean_absolute_error(rows: list[dict], arm: str) -> float | None:
    pairs = _pairs(rows, arm)
    return round(mean(abs(t - p) for t, p in pairs), 4) if pairs else None


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = rank
        i = j
    return ranks


def spearman(rows: list[dict], arm: str) -> float | None:
    pairs = _pairs(rows, arm)
    return _spearman_pairs(pairs)


def _spearman_pairs(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = _ranks([t for t, _ in pairs])
    ys = _ranks([p for _, p in pairs])
    mx, my = mean(xs), mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx <= 0 or dy <= 0:
        return None
    return round(numerator / math.sqrt(dx * dy), 4)


def severe_low_recall(rows: list[dict], arm: str) -> float | None:
    pairs = _pairs(rows, arm)
    severe = [(t, p) for t, p in pairs if t <= SEVERE_LOW_THRESHOLD]
    if not severe:
        return None
    caught = sum(
        1 for _, pred in severe if pred <= SEVERE_LOW_THRESHOLD
    )
    return round(caught / len(severe), 4)


def arm_metrics(rows: list[dict], arm: str) -> dict:
    pairs = _pairs(rows, arm)
    return {
        "n": len(pairs),
        "mae": mean_absolute_error(rows, arm),
        "spearman": spearman(rows, arm),
        "severe_low_recall": severe_low_recall(rows, arm),
        "mean_prediction": (
            round(mean(p for _, p in pairs), 4) if pairs else None
        ),
    }


def _paired_bootstrap_ci(
    rows: list[dict],
    arm_a: str,
    arm_b: str,
    statistic: Callable[[list[tuple[float, float, float]]], float | None],
    *,
    n_boot: int = 2000,
    seed: int = 20261113,
) -> tuple[float | None, float | None]:
    triples = []
    for row in rows:
        truth = row.get("human_score")
        a = (row.get("scores") or {}).get(arm_a)
        b = (row.get("scores") or {}).get(arm_b)
        values = (truth, a, b)
        if all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(float(v))
            for v in values
        ):
            triples.append(tuple(float(v) for v in values))
    if len(triples) < 2:
        return None, None
    rng = random.Random(seed)
    samples = []
    for _ in range(n_boot):
        chosen = [triples[rng.randrange(len(triples))]
                  for _ in range(len(triples))]
        value = statistic(chosen)
        if value is not None and math.isfinite(float(value)):
            samples.append(float(value))
    if not samples:
        return None, None
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    return round(lo, 4), round(hi, 4)


def _mae_improvement(triples: list[tuple[float, float, float]]) -> float:
    return mean(abs(t - a) - abs(t - b) for t, a, b in triples)


def _severe_recall_delta(triples: list[tuple[float, float, float]]) -> float:
    severe = [(t, a, b) for t, a, b in triples
              if t <= SEVERE_LOW_THRESHOLD]
    if not severe:
        return 0.0
    return mean(
        (1.0 if b <= SEVERE_LOW_THRESHOLD else 0.0)
        - (1.0 if a <= SEVERE_LOW_THRESHOLD else 0.0)
        for _, a, b in severe
    )


def _spearman_delta(
    triples: list[tuple[float, float, float]]
) -> float | None:
    base = _spearman_pairs([(t, a) for t, a, _ in triples])
    current = _spearman_pairs([(t, b) for t, _, b in triples])
    if base is None or current is None:
        return None
    return current - base


def compare(rows: list[dict], baseline: str, arm: str) -> dict:
    base = arm_metrics(rows, baseline)
    current = arm_metrics(rows, arm)
    mae_delta = (
        round(base["mae"] - current["mae"], 4)
        if base["mae"] is not None and current["mae"] is not None
        else None
    )
    recall_delta = (
        round(
            (current["severe_low_recall"] or 0.0)
            - (base["severe_low_recall"] or 0.0),
            4,
        )
        if (
            current["severe_low_recall"] is not None
            and base["severe_low_recall"] is not None
        )
        else None
    )
    mae_ci = _paired_bootstrap_ci(
        rows, baseline, arm, _mae_improvement)
    recall_ci = _paired_bootstrap_ci(
        rows, baseline, arm, _severe_recall_delta)
    spearman_ci = _paired_bootstrap_ci(
        rows, baseline, arm, _spearman_delta)
    return {
        "baseline": baseline,
        "arm": arm,
        "mae_improvement": mae_delta,
        "mae_improvement_ci95": list(mae_ci),
        "severe_low_recall_delta": recall_delta,
        "severe_low_recall_delta_ci95": list(recall_ci),
        "spearman_delta_ci95": list(spearman_ci),
        "spearman_delta": (
            round(current["spearman"] - base["spearman"], 4)
            if current["spearman"] is not None and base["spearman"] is not None
            else None
        ),
    }


def load_rows(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"line {line_no}: expected object")
            rows.append(data)
    return rows


def summarize(rows: Iterable[dict]) -> dict:
    materialized = list(rows)
    metrics = {arm: arm_metrics(materialized, arm) for arm in ARMS}
    comparisons = [
        compare(materialized, "off", "kb"),
        compare(materialized, "off", "kg"),
        compare(materialized, "off", "both"),
        compare(materialized, "kb", "both"),
        compare(materialized, "kg", "both"),
    ]
    return {
        "n_rows": len(materialized),
        "arms": metrics,
        "comparisons": comparisons,
        "thresholds": {"severe_low": SEVERE_LOW_THRESHOLD},
    }
