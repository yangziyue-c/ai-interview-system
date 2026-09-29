# -*- coding: utf-8 -*-
"""
Local body-language analysis from pose landmarks.

No image, video or audio is required by this module. The browser/worker may
extract MediaPipe Pose landmarks locally and send only numeric coordinates.
"""
from __future__ import annotations

import math
from statistics import mean, median, pstdev
from typing import Optional

NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24


def _visible(point: dict, threshold: float = 0.35) -> bool:
    try:
        return float(point.get("visibility", 1.0)) >= threshold
    except (TypeError, ValueError):
        return False


def _distance(a: dict, b: dict) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]),
                      float(a["y"]) - float(b["y"]))


def _midpoint(a: dict, b: dict) -> dict:
    return {
        "x": (float(a["x"]) + float(b["x"])) / 2.0,
        "y": (float(a["y"]) + float(b["y"])) / 2.0,
    }


def _angle_degrees(a: dict, b: dict, axis: str = "horizontal") -> float:
    dx = float(b["x"]) - float(a["x"])
    dy = float(b["y"]) - float(a["y"])
    if axis == "horizontal":
        return abs(math.degrees(math.atan2(dy, dx)))
    return abs(math.degrees(math.atan2(dx, dy)))


def _safe_std(values: list[float]) -> Optional[float]:
    return round(pstdev(values), 4) if len(values) >= 2 else None


def _median_smooth(values: list[float], window: int = 5) -> list[float]:
    if len(values) < 3:
        return list(values)
    radius = max(1, window // 2)
    result = []
    for index in range(len(values)):
        lo = max(0, index - radius)
        hi = min(len(values), index + radius + 1)
        result.append(median(values[lo:hi]))
    return result


def _per_second(values: list[float], timestamps: list[float]) -> Optional[float]:
    if len(values) < 2 or len(timestamps) < 2:
        return None
    duration = max(1e-6, (timestamps[-1] - timestamps[0]) / 1000.0)
    return sum(abs(values[i] - values[i - 1])
               for i in range(1, len(values))) / duration


def _percentile(values: list[float], ratio: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(
        (len(ordered) - 1) * ratio))))
    return ordered[index]


def analyze_frames(frames: list[dict]) -> dict:
    """
    Analyze a short sequence of pose-landmark frames.

    Coordinates are normalized [0,1], matching MediaPipe Pose output. The
    result is a communication posture signal, not a personality or emotion
    judgment. A score is emitted only when there is enough reliable temporal
    evidence; camera failures and out-of-frame hands never become low scores.
    """
    frames = [x for x in (frames or []) if isinstance(x, dict)]
    usable = []
    presence = []
    shoulder_tilts = []
    torso_leans = []
    head_x = []
    head_y = []
    shoulder_widths = []
    centers = []
    wrist_frame_offsets = []
    wrist_positions = []
    timestamps = []
    head_visible_count = 0
    torso_visible_count = 0
    hand_visible_count = 0

    for frame in frames:
        lm = frame.get("landmarks") or []
        if len(lm) < 25:
            presence.append(False)
            continue
        ls, rs = lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]
        lh, rh = lm[LEFT_HIP], lm[RIGHT_HIP]
        # Typical laptop webcams show head and shoulders, not hips. Hips are
        # optional; requiring them made valid sessions look like 0% coverage.
        core = _visible(ls) and _visible(rs)
        presence.append(core)
        if not core:
            continue
        usable.append(frame)
        shoulder_mid = _midpoint(ls, rs)
        width = max(1e-6, _distance(ls, rs))
        timestamps.append(float(frame.get("timestamp_ms") or 0))
        shoulder_widths.append(width)
        shoulder_tilts.append(_angle_degrees(ls, rs, "horizontal"))
        hip_visible = _visible(lh) and _visible(rh)
        if hip_visible:
            hip_mid = _midpoint(lh, rh)
            torso_leans.append(_angle_degrees(shoulder_mid, hip_mid, "vertical"))
            centers.append(_midpoint(shoulder_mid, hip_mid))
            torso_visible_count += 1
        else:
            centers.append(dict(shoulder_mid))

        nose = lm[NOSE]
        if _visible(nose):
            head_visible_count += 1
            head_x.append((float(nose["x"]) - shoulder_mid["x"]) / width)
            head_y.append((float(nose["y"]) - shoulder_mid["y"]) / width)
        else:
            head_x.append(0.0)
            head_y.append(0.0)

        current_wrists = []
        frame_wrists = {}
        for wrist_idx, elbow_idx in ((LEFT_WRIST, LEFT_ELBOW),
                                     (RIGHT_WRIST, RIGHT_ELBOW)):
            wrist = lm[wrist_idx]
            elbow = lm[elbow_idx]
            if _visible(wrist) and _visible(elbow):
                value = _distance(wrist, shoulder_mid) / width
                current_wrists.append(value)
                frame_wrists[wrist_idx] = {
                    "x": (float(wrist["x"]) - shoulder_mid["x"]) / width,
                    "y": (float(wrist["y"]) - shoulder_mid["y"]) / width,
                }
        if current_wrists:
            hand_visible_count += 1
            wrist_frame_offsets.append(mean(current_wrists))
        wrist_positions.append(frame_wrists)

    if not usable:
        return {
            "available": False,
            "score": None,
            "confidence": "low",
            "quality_status": "no_pose",
            "score_breakdown": [],
            "metrics": {
                "frame_count": len(frames),
                "presence_rate": 0.0,
                "usable_frame_count": 0,
                "duration_ms": 0,
                "head_visibility_rate": 0.0,
                "torso_visibility_rate": 0.0,
                "hand_visibility_rate": 0.0,
                "head_stability": None,
                "shoulder_tilt_deg": None,
                "shoulder_tilt_delta_deg": None,
                "torso_lean_deg": None,
                "torso_lean_delta_deg": None,
                "upper_body_motion": None,
                "gesture_activity": None,
                "framing_stability": None,
            },
            "notes": ["没有可用的上半身姿态关键点，未生成肢体语言分。"],
        }

    smoothed_centers_x = _median_smooth([x["x"] for x in centers])
    smoothed_centers_y = _median_smooth([x["y"] for x in centers])
    smoothed_head_x = _median_smooth(head_x)
    smoothed_head_y = _median_smooth(head_y)
    smoothed_widths = _median_smooth(shoulder_widths)
    base_width = median(smoothed_widths)
    base_center_x = median(smoothed_centers_x[:max(1, len(centers) // 3)])
    base_center_y = median(smoothed_centers_y[:max(1, len(centers) // 3)])

    motion = []
    for index in range(1, len(smoothed_centers_x)):
        dx = smoothed_centers_x[index] - smoothed_centers_x[index - 1]
        dy = smoothed_centers_y[index] - smoothed_centers_y[index - 1]
        motion.append(math.hypot(dx, dy) / max(1e-6, base_width))

    head_shift = [
        math.hypot(smoothed_head_x[i], smoothed_head_y[i])
        for i in range(len(smoothed_head_x))
    ]
    torso_jitter = _safe_std(_median_smooth(torso_leans)) or 0.0
    shoulder_jitter = _safe_std(_median_smooth(shoulder_tilts)) or 0.0
    head_sway_rate = _per_second(head_shift, timestamps)

    baseline_count = max(1, len(shoulder_tilts) // 3)
    baseline_shoulder_tilt = median(shoulder_tilts[:baseline_count])
    shoulder_tilt_delta = mean(
        abs(value - baseline_shoulder_tilt) for value in shoulder_tilts)
    if torso_leans:
        baseline_torso_count = max(1, len(torso_leans) // 3)
        baseline_torso_lean = median(torso_leans[:baseline_torso_count])
        torso_lean_delta = mean(
            abs(value - baseline_torso_lean) for value in torso_leans)
    else:
        torso_lean_delta = None

    gesture_events = 0
    gesture_direction_changes = 0
    gesture_amplitudes = []
    last_wrist_positions = None
    last_wrist_directions: dict[int, float] = {}
    gesture_active = False
    gesture_quiet_frames = 0
    for index, current in enumerate(wrist_positions):
        previous_time = timestamps[index - 1] if index else None
        current_time = timestamps[index] if index < len(timestamps) else None
        if last_wrist_positions:
            movements = []
            for wrist_idx in (LEFT_WRIST, RIGHT_WRIST):
                a = last_wrist_positions.get(wrist_idx)
                b = current.get(wrist_idx)
                if a and b:
                    dx = b["x"] - a["x"]
                    dy = b["y"] - a["y"]
                    distance = math.hypot(dx, dy)
                    movements.append(distance)
                    angle = math.atan2(dy, dx)
                    previous_angle = last_wrist_directions.get(wrist_idx)
                    if previous_angle is not None and distance >= 0.015:
                        delta = abs(math.atan2(
                            math.sin(angle - previous_angle),
                            math.cos(angle - previous_angle),
                        ))
                        if delta >= 2.2:
                            gesture_direction_changes += 1
                    if distance >= 0.015:
                        last_wrist_directions[wrist_idx] = angle
                    else:
                        last_wrist_directions.pop(wrist_idx, None)
            if movements and previous_time is not None and current_time is not None:
                delta_seconds = max(
                    0.001, (current_time - previous_time) / 1000.0)
                speed = max(movements) / delta_seconds
                if speed >= 0.45 and not gesture_active:
                    gesture_events += 1
                    gesture_active = True
                    gesture_quiet_frames = 0
                if gesture_active:
                    gesture_amplitudes.append(speed)
                    if speed <= 0.12:
                        gesture_quiet_frames += 1
                        if gesture_quiet_frames >= 2:
                            gesture_active = False
                            gesture_quiet_frames = 0
                else:
                    gesture_quiet_frames = 0
        elif gesture_active:
            gesture_active = False
            gesture_quiet_frames = 0
            last_wrist_directions.clear()
        last_wrist_positions = current

    gesture_events = max(
        gesture_events, int(round(gesture_direction_changes / 2.0)))

    duration_ms = (
        int(max(0.0, timestamps[-1] - timestamps[0]))
        if len(timestamps) >= 2 else 0)
    duration_minutes = max(1e-6, duration_ms / 60000.0)
    hand_visibility_rate = hand_visible_count / max(1, len(usable))
    gesture_rate = (
        gesture_events / duration_minutes
        if duration_ms >= 1000 and hand_visibility_rate >= 0.4
        else None)
    posture_shifts = 0
    shifted = False
    for x, y in zip(smoothed_centers_x, smoothed_centers_y):
        offset = math.hypot(x - base_center_x, y - base_center_y) / max(
            1e-6, base_width)
        if offset >= 0.18 and not shifted:
            posture_shifts += 1
            shifted = True
        elif offset < 0.10:
            shifted = False

    head_stability_values = [
        value for value in (_safe_std(smoothed_head_x),
                            _safe_std(smoothed_head_y))
        if value is not None
    ]
    presence_rate = round(
        sum(bool(x) for x in presence) / max(1, len(presence)), 4)
    framing_stability = (
        round(_safe_std(smoothed_widths) / max(1e-6, base_width), 4)
        if _safe_std(smoothed_widths) is not None else None)

    metrics = {
        "frame_count": len(frames),
        "presence_rate": presence_rate,
        "usable_frame_count": len(usable),
        "duration_ms": duration_ms,
        "head_visibility_rate": round(
            head_visible_count / max(1, len(usable)), 4),
        "torso_visibility_rate": round(
            torso_visible_count / max(1, len(usable)), 4),
        "hand_visibility_rate": round(hand_visibility_rate, 4),
        "head_stability": (round(mean(head_stability_values), 4)
                           if head_stability_values else None),
        "head_sway_rate": (round(head_sway_rate, 4)
                           if head_sway_rate is not None else None),
        "shoulder_tilt_deg": round(mean(shoulder_tilts), 2),
        "shoulder_tilt_delta_deg": round(shoulder_tilt_delta, 2),
        "shoulder_jitter_deg": round(shoulder_jitter, 2),
        "torso_lean_deg": (round(mean(torso_leans), 2)
                           if torso_leans else None),
        "torso_lean_delta_deg": (round(torso_lean_delta, 2)
                                 if torso_lean_delta is not None else None),
        "torso_jitter_deg": round(torso_jitter, 2),
        "upper_body_motion": round(mean(motion), 4) if motion else None,
        "gesture_activity": _safe_std(wrist_frame_offsets),
        "gesture_rate_per_min": (round(gesture_rate, 2)
                                 if gesture_rate is not None else None),
        "gesture_direction_changes": gesture_direction_changes,
        "gesture_amplitude": (round(_percentile(gesture_amplitudes, 0.9), 4)
                              if gesture_amplitudes else None),
        "posture_shift_count": posture_shifts,
        "framing_stability": framing_stability,
    }

    # A useful personal baseline needs more than a few frames. Until then,
    # report measurement quality instead of turning camera noise into a low
    # communication score.
    enough_frames = len(usable) >= 16 and duration_ms >= 3000
    visibility_ok = presence_rate >= 0.80
    if not enough_frames or not visibility_ok:
        quality_status = (
            "low_visibility" if not visibility_ok else "warming_up")
        return {
            "available": True,
            "score": None,
            "confidence": "low",
            "quality_status": quality_status,
            "score_breakdown": [],
            "metrics": metrics,
            "notes": [
                "姿态数据还不够稳定，暂不生成肢体语言分。",
                "请保持肩部在画面内，并连续采集至少 3 秒。",
                "摄像头画面和音频不上传云端；只使用本地提取的数字关键点。",
            ],
        }

    score = 3.0
    breakdown = []

    presence_delta = 0.5 if metrics["presence_rate"] >= 0.9 else 0.0
    score += presence_delta
    breakdown.append({
        "factor": "presence",
        "delta": presence_delta,
        "evidence": metrics["presence_rate"],
    })

    if metrics["head_stability"] is not None:
        delta = 0.4 if metrics["head_stability"] <= 0.18 else (
            -0.4 if metrics["head_stability"] > 0.28 else 0.0)
        score += delta
        breakdown.append({
            "factor": "head_stability",
            "delta": delta,
            "evidence": metrics["head_stability"],
        })
    if metrics["head_sway_rate"] is not None:
        delta = 0.2 if metrics["head_sway_rate"] <= 0.12 else (
            -0.2 if metrics["head_sway_rate"] > 0.24 else 0.0)
        score += delta
        breakdown.append({
            "factor": "head_sway",
            "delta": delta,
            "evidence": metrics["head_sway_rate"],
        })

    delta = 0.3 if metrics["shoulder_tilt_delta_deg"] <= 4 else (
        -0.4 if metrics["shoulder_tilt_delta_deg"] > 12 else 0.0)
    score += delta
    breakdown.append({
        "factor": "shoulder_baseline_drift",
        "delta": delta,
        "evidence": metrics["shoulder_tilt_delta_deg"],
    })

    if metrics["torso_lean_delta_deg"] is not None:
        if metrics["torso_lean_delta_deg"] <= 5:
            delta = 0.3
        elif metrics["torso_lean_delta_deg"] > 15:
            delta = -0.4
        elif metrics["torso_lean_delta_deg"] > 8:
            delta = -0.2
        else:
            delta = 0.0
        score += delta
        breakdown.append({
            "factor": "torso_baseline_drift",
            "delta": delta,
            "evidence": metrics["torso_lean_delta_deg"],
        })

    if metrics["upper_body_motion"] is not None:
        delta = 0.2 if 0.015 <= metrics["upper_body_motion"] <= 0.12 else (
            -0.3 if metrics["upper_body_motion"] > 0.25 else 0.0)
        score += delta
        breakdown.append({
            "factor": "upper_body_motion",
            "delta": delta,
            "evidence": metrics["upper_body_motion"],
        })

    if metrics["gesture_rate_per_min"] is not None:
        if 2 <= metrics["gesture_rate_per_min"] <= 18:
            delta = 0.2
        elif metrics["gesture_rate_per_min"] > 60:
            delta = -0.5
        elif metrics["gesture_rate_per_min"] > 35:
            delta = -0.2
        else:
            delta = 0.0
        score += delta
        breakdown.append({
            "factor": "gesture_rate",
            "delta": delta,
            "evidence": metrics["gesture_rate_per_min"],
        })

    if metrics["posture_shift_count"] > 4:
        score -= 0.2
        breakdown.append({
            "factor": "posture_shift_count",
            "delta": -0.2,
            "evidence": metrics["posture_shift_count"],
        })

    if metrics["framing_stability"] is not None:
        delta = 0.2 if metrics["framing_stability"] <= 0.04 else (
            -0.3 if metrics["framing_stability"] > 0.12 else 0.0)
        score += delta
        breakdown.append({
            "factor": "framing_stability",
            "delta": delta,
            "evidence": metrics["framing_stability"],
        })

    score = round(max(0.0, min(5.0, score)) / 0.05) * 0.05

    if (metrics["presence_rate"] >= 0.9 and len(usable) >= 20
            and duration_ms >= 3000):
        confidence = "high"
    elif metrics["presence_rate"] >= 0.75 and len(usable) >= 8:
        confidence = "medium"
    else:
        confidence = "low"

    feedback = []
    if metrics["head_stability"] is not None and metrics["head_stability"] > 0.28:
        feedback.append("头部位置波动较大，回答时可以保持视线和头部更稳定。")
    if metrics["shoulder_tilt_delta_deg"] > 12:
        feedback.append("肩线相对个人基线变化明显，注意保持上身端正。")
    if metrics["upper_body_motion"] is not None and metrics["upper_body_motion"] > 0.25:
        feedback.append("上身移动幅度偏大，建议减少无意识晃动。")
    if metrics["gesture_rate_per_min"] is not None and metrics[
            "gesture_rate_per_min"] > 35:
        feedback.append("手势频率偏高，可以放慢并只在强调重点时使用。")
    if metrics["torso_lean_delta_deg"] is not None and metrics[
            "torso_lean_delta_deg"] > 12:
        feedback.append("躯干相对个人基线偏移明显，注意保持上身稳定。")
    if metrics["framing_stability"] is not None and metrics[
            "framing_stability"] > 0.12:
        feedback.append("肩膀宽度和取景变化较大，注意保持摄像头画面稳定。")

    return {
        "available": True,
        "score": round(score, 2),
        "confidence": confidence,
        "quality_status": "ready",
        "score_breakdown": breakdown,
        "metrics": metrics,
        "feedback": feedback,
        "notes": [
            "仅根据上半身姿态关键点评估，不推断情绪、性格或能力。",
            "摄像头画面和音频不上传云端；只使用本地提取的数字关键点。",
        ],
    }
