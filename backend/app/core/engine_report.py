"""把 AI 对话层引擎（A11）的 /finish 结果转成本项目报告口径

纯函数：无 I/O、无状态 —— 分数换算与三栏推导是本次集成最容易出错的一环，
单测直接喂 golden 夹具（tests/fixtures/engine_finish_sample.json）。

两件事必须记住：
- 引擎是 **1~5 分制**，本项目 reports 表是 **0~100**，换算在 _to_100 一处完成；
- 引擎的维度键**恒为「技术水平」**——行为素质题只换 dim1 标签、不换键
  （见 A11 交付说明第七节），所以按标签而非键去映射会丢分。
"""
import logging
from typing import Any

from app.core.evaluation_weights import build_fallback_report, weights_for

logger = logging.getLogger(__name__)

# 引擎中文维度 → (reports 列名, weights_for 的键)
_DIM_TO_FIELD: dict[str, tuple[str, str]] = {
    "技术水平": ("tech_score", "tech"),
    "逻辑思维": ("logic_score", "logic"),
    "沟通表达": ("expression_score", "expression"),
    "应变能力": ("adaptability_score", "adaptability"),
    "岗位匹配度": ("match_score", "match"),
}

_ENGINE_SCORE_MAX = 5.0   # 引擎分制上限（1~5）
_STRENGTH_MIN = 4.0       # ≥4.0 记入优势
_WEAK_MAX = 2.5           # ≤2.5 记入不足
_MAX_ITEMS = 4            # 三栏每栏最多几条（报告页展示篇幅）
_NO_DOMAIN = "未归类"      # 引擎在 KG 不可用时的兜底桶，不能当「薄弱领域」报给考生


def build_engine_report(position: str, qa_list: list[dict], payload: dict) -> dict:
    """引擎 /finish 的 payload → reports 表口径的 dict

    整场没有任何有效维度分时回退 build_fallback_report：报告必须能生成，
    「引擎没评出分」不该变成 500（reports 六列都是 NOT NULL）。
    """
    dims = payload.get("five_dim_avg") or {}
    scores: dict[str, float | None] = {
        field: _to_100(dims.get(dim)) for dim, (field, _) in _DIM_TO_FIELD.items()
    }
    available = [v for v in scores.values() if v is not None]
    if not available:
        logger.warning("对话层引擎未产出任何有效维度分，回退兜底报告")
        return build_fallback_report(
            position, qa_list, summary_prefix="面试引擎未产出有效评分，以下为兜底评估"
        )

    # 单维缺失（引擎的 null 是「没有数据」，不是 0 分）用可用维度均值回填：
    # 留 0 会把雷达图拖塌，而 reports 六列又不允许 NULL。
    fill = round(sum(available) / len(available), 1)
    for field, value in scores.items():
        if value is None:
            scores[field] = fill

    report: dict[str, Any] = {
        "total_score": _total_score(position, scores, payload),
        "summary": _summary_of(payload),
        "strengths": _strengths(payload, dims),
        "weaknesses": _weaknesses(payload, dims),
        "suggestions": _suggestions(payload),
    }
    report.update(scores)
    return report


def build_engine_meta(payload: dict) -> dict:
    """报告明细（只进 reports.engine_meta，不进考生可见文案）

    notes 是引擎的内部口径（如「本场换过 1 题，原因：…」），引擎已把该说的话
    拼进了 summary，这里只做留痕，便于事后核对与 3 号（评估报告）取数。
    """
    raw = payload.get("raw") or {}
    blindspots = raw.get("blindspots") or {}
    return {
        "engine": "a11",
        "session_id": payload.get("session_id"),
        "rounds": payload.get("rounds"),
        "questions_asked": raw.get("questions_asked"),
        "partial": bool(payload.get("partial")),
        "notes": list(payload.get("notes") or []),
        "scoring": raw.get("scoring"),
        "swaps_used": raw.get("swaps_used"),
        "scoring_failed_rounds": list(raw.get("scoring_failed_rounds") or []),
        "blindspots_summary": blindspots.get("summary"),
    }


# ---------------- 分数换算 ----------------
def _to_100(raw: Any) -> float | None:
    """引擎的 1~5 分 → 0~100 分；非数值或越界一律当「没评出分」

    bool 是 int 的子类，True 会被当成 1.0 分（=20 分）落库 —— 先挡掉。
    越界值不当真：脏分数一旦落库，成长曲线与报告页都会跟着错。
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw) * (100.0 / _ENGINE_SCORE_MAX)
    if value < 0.0 or value > 100.0:
        logger.warning("引擎返回越界维度分 %s（应为 1~5），按缺失处理", raw)
        return None
    return round(value, 1)


def _total_score(position: str, scores: dict[str, float], payload: dict) -> float:
    """总分优先采信引擎的百分制值，再用本项目权重表算一遍做漂移检查

    两侧权重表同源（都出自主库《评估维度.csv》，已逐格核对一致），正常差异在
    0.5 分内；超过 1 分说明有一侧被改过，记 WARNING 便于发现（仍以引擎值为准，
    毕竟分数是它评的）。
    """
    weights = weights_for(position)
    recomputed = round(
        sum(scores[field] * weights[key] for field, key in _DIM_TO_FIELD.values()), 1
    )
    engine_total = payload.get("total_score_100")
    if isinstance(engine_total, bool) or not isinstance(engine_total, (int, float)):
        return recomputed
    value = round(float(engine_total), 1)
    if abs(value - recomputed) > 1.0:
        logger.warning(
            "引擎总分 %.1f 与按本项目权重重算的 %.1f 相差超过 1 分，请核对两侧权重表",
            value, recomputed,
        )
    return value


# ---------------- 文案推导 ----------------
def _summary_of(payload: dict) -> str:
    text = str(payload.get("summary") or "").strip()
    return text or "本场面试已完成，详见各维度得分。"


def _strengths(payload: dict, dims: dict) -> list[str]:
    """优势：高分维度 + 表现最好那一轮的面评"""
    items = [
        f"{dim} 表现突出（均分 {dims[dim]}/5）"
        for dim in _dims_by_score(dims, reverse=True)
        if _is_num(dims.get(dim)) and float(dims[dim]) >= _STRENGTH_MIN
    ]
    comment = _best_round_comment(payload)
    if comment:
        items.append(comment)
    return items[:_MAX_ITEMS] or ["本场整体表现平稳，没有明显突出的维度"]


def _weaknesses(payload: dict, dims: dict) -> list[str]:
    """不足：低分维度 + 盲区诊断里的薄弱领域 + 评分缺失说明"""
    items = [
        f"{dim} 有待加强（均分 {dims[dim]}/5）"
        for dim in _dims_by_score(dims)
        if _is_num(dims.get(dim)) and float(dims[dim]) <= _WEAK_MAX
    ]
    for domain in _weak_domains(payload, limit=2):
        weak = "、".join(str(x) for x in (domain.get("weak_kps") or []))
        name = domain.get("domain") or _NO_DOMAIN
        items.append(f"{name} 领域掌握不牢" + (f"：{weak}" if weak else ""))
    failed = (payload.get("raw") or {}).get("scoring_failed_rounds") or []
    if failed:
        items.append(f"有 {len(failed)} 轮评分未能完成，本场分数可能不完整")
    return items[:_MAX_ITEMS] or ["暂未发现明显薄弱项"]


def _suggestions(payload: dict) -> list[str]:
    """建议：优先补没答上来的知识点（盲区表里 hit 为假的那些）"""
    items: list[str] = []
    for kp in _unhit_kps(payload, limit=3):
        title = kp.get("title") or kp.get("kp_id")
        domain = kp.get("domain")
        items.append(
            f"复习「{title}」" + (f"（{domain}）" if domain and domain != _NO_DOMAIN else "")
        )
    if payload.get("partial"):
        items.append("本场有轮次未能完整评分，建议再完整做一场以获得准确报告")
    return items[:_MAX_ITEMS] or [
        "按题库的 L2 递进追问深度准备讲解，把原理讲到实现层面"
    ]


# ---------------- 小工具 ----------------
def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dims_by_score(dims: dict, reverse: bool = False) -> list[str]:
    """按分数排序的维度名；没评出分的维度排最后（它不该影响强弱判断）"""
    scored = [(d, float(dims[d])) for d in _DIM_TO_FIELD if _is_num(dims.get(d))]
    scored.sort(key=lambda item: item[1], reverse=reverse)
    unscored = [d for d in _DIM_TO_FIELD if not _is_num(dims.get(d))]
    return [d for d, _ in scored] + unscored


def _best_round_comment(payload: dict) -> str | None:
    """取综合分最高那一轮的面评（引擎逐轮给了 comment）"""
    best_score, best_comment = -1.0, None
    for rnd in (payload.get("raw") or {}).get("rounds") or []:
        five_dim = rnd.get("five_dim") or {}
        values = [float(v) for v in five_dim.values() if _is_num(v)]
        comment = str(rnd.get("comment") or "").strip()
        if not values or not comment:
            continue
        avg = sum(values) / len(values)
        if avg > best_score:
            best_score, best_comment = avg, comment
    return best_comment


def _weak_domains(payload: dict, limit: int) -> list[dict]:
    """盲区领域按薄弱知识点数降序；「未归类」是 KG 不可用时的兜底桶，不报给考生"""
    domains = [
        d for d in (payload.get("raw") or {}).get("blindspots", {}).get("domains") or []
        if d.get("domain") and d.get("domain") != _NO_DOMAIN and (d.get("kps_weak") or 0) > 0
    ]
    domains.sort(key=lambda d: d.get("kps_weak") or 0, reverse=True)
    return domains[:limit]


def _unhit_kps(payload: dict, limit: int) -> list[dict]:
    """没答上来的知识点：hit 为假（含 None）的，分数低的排前面"""
    kps = [
        kp for kp in (payload.get("raw") or {}).get("blindspots", {}).get("knowledge_points") or []
        if not kp.get("hit")
    ]
    kps.sort(key=lambda kp: float(kp.get("best_score") or 0.0))
    return kps[:limit]
