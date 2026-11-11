"""表达与表现分析：把语音读数与体态结果聚合成报告页的一小块

数据来源只有两处，都是**真实测量**：
- `qa_records.speech`：`/uploads/audio/asr` 的原始读数（语速 / 停顿 / 填充词 /
  音量波动），提交答案时整条落库；
- `qa_records.body_language`：引擎 `/body-language` 的结果（体态分 0~5 /
  置信度 / 面向考生的反馈语）。

刻意**不用** P3 返回的 `_speech_details`：那是按回答字数估出来的模拟值
（`simulated: True`），拿它当「语速/停顿」展示等于编数据。

纯度要求：语音读数缺哪项就返回 null，不补 0；体态没数据就 available=false。
前端据此不画这一块，或者明确写「本场为文字作答」。
"""
from typing import Any

# 中文面试语速的参考区间（字/分钟）。这是**陈述性参考**，不是评分标准：
# 说得快不等于差，只是提示考生注意节奏。区间取得宽，避免把正常波动报成问题。
_SLOW_CPM = 140.0
_FAST_CPM = 280.0
# 长停顿密度（次/分钟）：超过这个值说明组织语言时卡顿明显
_PAUSE_RATE_HIGH = 8.0
# 填充词占比：超过 3% 听感上已经比较明显
_FILLER_RATE_HIGH = 0.03
# 音量变异系数：越大说明忽大忽小
_LOUDNESS_CV_HIGH = 0.35
# 体态稳定性的分档（引擎分制 0~5，5 最好）
_BODY_STABLE = 4.0
_BODY_OK = 3.0


def _num(value: Any) -> float | None:
    """数值清洗：bool 是 int 的子类，先挡掉；非数值一律当缺失"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _aggregate_voice(qa_records: list) -> dict:
    """语音读数聚合：逐轮明细 + 加权语速 + 停顿/填充词合计 + 评语"""
    rounds: list[dict] = []
    weighted: list[tuple[float, float]] = []  # (chars_per_min, weight)
    pause_rates: list[float] = []
    filler_rates: list[float] = []
    loudness_cvs: list[float] = []
    total_pauses = 0
    total_pause_ms = 0
    total_fillers = 0

    for qa in qa_records:
        speech = qa.speech
        if not isinstance(speech, dict) or not speech:
            continue
        # 防御：模拟值（P3 的 simulated 字段）不混进真实读数
        if speech.get("simulated") is True:
            continue

        cpm = _num(speech.get("chars_per_min"))
        duration = _num(speech.get("duration_ms"))
        pauses = _num(speech.get("pauses"))
        pause_ms = _num(speech.get("pause_total_ms"))
        pause_rate = _num(speech.get("pause_rate_per_min"))
        fillers = _num(speech.get("fillers"))
        filler_rate = _num(speech.get("filler_rate"))
        loudness_cv = _num(speech.get("loudness_cv"))

        item = {
            "round": qa.round,
            "chars_per_min": round(cpm, 1) if cpm is not None else None,
            "pauses": int(pauses) if pauses is not None else None,
            "pause_total_ms": int(pause_ms) if pause_ms is not None else None,
            "fillers": int(fillers) if fillers is not None else None,
            "filler_rate": round(filler_rate, 4) if filler_rate is not None else None,
            "duration_ms": int(duration) if duration is not None else None,
            "loudness_cv": round(loudness_cv, 3) if loudness_cv is not None else None,
        }
        # 只有全是空值的轮次不当作「有语音数据」
        if any(v is not None for k, v in item.items() if k != "round"):
            rounds.append(item)

        if cpm is not None:
            # 净语音时长做权重：说得久的那一轮更能代表整场语速
            weighted.append((cpm, duration if duration and duration > 0 else 1.0))
        if pause_rate is not None:
            pause_rates.append(pause_rate)
        if filler_rate is not None:
            filler_rates.append(filler_rate)
        if loudness_cv is not None:
            loudness_cvs.append(loudness_cv)
        if pauses is not None:
            total_pauses += int(pauses)
        if pause_ms is not None:
            total_pause_ms += int(pause_ms)
        if fillers is not None:
            total_fillers += int(fillers)

    feedback: list[str] = []
    avg_cpm = (
        round(sum(v * w for v, w in weighted) / sum(w for _, w in weighted), 1)
        if weighted else None
    )
    avg_pause_rate = _avg(pause_rates)
    avg_filler_rate = _avg(filler_rates)
    avg_loudness_cv = _avg(loudness_cvs)

    if avg_cpm is not None:
        if avg_cpm < _SLOW_CPM:
            feedback.append(f"语速偏慢（平均约 {avg_cpm:.0f} 字/分），回答时可以更利落一些。")
        elif avg_cpm > _FAST_CPM:
            feedback.append(f"语速偏快（平均约 {avg_cpm:.0f} 字/分），重点处可以适当放慢。")
        else:
            feedback.append(f"语速适中（平均约 {avg_cpm:.0f} 字/分）。")
    if avg_pause_rate is not None and avg_pause_rate > _PAUSE_RATE_HIGH:
        feedback.append(
            f"长停顿偏多（平均每分钟约 {avg_pause_rate:.0f} 次），可以先想清结构再开口。"
        )
    if avg_filler_rate is not None and avg_filler_rate > _FILLER_RATE_HIGH:
        feedback.append("口头填充词占比偏高，注意减少「嗯」「然后」这类停顿词。")
    if avg_loudness_cv is not None and avg_loudness_cv > _LOUDNESS_CV_HIGH:
        feedback.append("音量起伏比较明显，回答时保持稳定的音量会更有底气。")

    return {
        "available": bool(rounds),
        "round_count": len(rounds),
        "avg_chars_per_min": avg_cpm,
        "avg_pause_rate_per_min": avg_pause_rate,
        "total_pauses": total_pauses,
        "total_pause_ms": total_pause_ms,
        "total_fillers": total_fillers,
        "avg_filler_rate": avg_filler_rate,
        "avg_loudness_cv": avg_loudness_cv,
        "rounds": rounds,
        "feedback": feedback,
    }


def _aggregate_body(qa_records: list) -> dict:
    """体态结果聚合：可用轮次求均分，反馈去重，置信度取最保守的一档"""
    scores: list[float] = []
    feedback: list[str] = []
    confidences: list[str] = []
    round_count = 0

    for qa in qa_records:
        data = qa.body_language
        if not isinstance(data, dict) or data.get("available") is not True:
            continue
        round_count += 1
        score = _num(data.get("score"))
        if score is not None:
            scores.append(score)
        confidence = data.get("confidence")
        if confidence in ("high", "medium", "low"):
            confidences.append(confidence)
        for line in data.get("feedback") or []:
            text = str(line).strip()
            if text and text not in feedback:
                feedback.append(text)

    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    # 置信度取最低：多轮里只要有一轮可信度低，整场的结论就不该报「高」
    _order = {"low": 0, "medium": 1, "high": 2}
    confidence = min(confidences, key=_order.get) if confidences else None

    if avg_score is None:
        summary = None
    elif avg_score >= _BODY_STABLE:
        summary = "体态整体稳定，镜头前状态自然。"
    elif avg_score >= _BODY_OK:
        summary = "体态基本稳定，个别时候可以注意上身与镜头位置。"
    else:
        summary = "体态稳定性需要加强，回答时尽量保持上身端正、减少无意识晃动。"

    return {
        "available": round_count > 0,
        "round_count": round_count,
        "avg_score": avg_score,
        "confidence": confidence,
        "feedback": feedback[:4],
        "summary": summary,
    }


def build_expression_analysis(qa_records: list) -> dict:
    """报告页「表达与表现分析」的数据体

    available=false 时前端不画模块；notice 说明为什么没有数据。
    """
    voice = _aggregate_voice(qa_records)
    body = _aggregate_body(qa_records)
    available = voice["available"] or body["available"]

    notice: str | None = None
    if not available:
        notice = "本场没有语音或体态数据（文字作答，或未开启摄像头体态分析）。"
    elif not voice["available"]:
        notice = "本场没有语音数据，表达分析仅包含体态部分。"

    return {
        "available": available,
        "voice": voice,
        "body": body,
        "notice": notice,
    }
