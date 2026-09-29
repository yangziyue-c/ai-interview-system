# -*- coding: utf-8 -*-
"""Independent objective scorer (Qwen/OpenAI-compatible)."""
from __future__ import annotations

import json
from typing import Optional

import httpx

from app import config
from app.core.llm import _extract_json
from app.logging_conf import get_logger

logger = get_logger(__name__)

SYSTEM = """你是技术面试的客观核验器。
只判断考生回答中的事实正确性、明确误区、未覆盖得分点和证据充分度。
先抽取考生的技术主张，再逐条判断“支持 / 矛盾 / 证据不足”；不要因为出现关键词就算支持。
如果提供了知识库证据，只把它用于核验事实；证据不足时判 insufficient，不能凭相似度加分。
得分点必须拆成原子断言：一个断言只表达一个事实关系，不要把多个事实粘在一起。
不评价逻辑风格、表达流畅度、性格或岗位匹配。拿不准就降低 confidence。
correctness_score 使用以下硬锚点：
- 0 到 1.5：明确不知道、没有有效技术内容，或核心结论错误。
- 1.5 到 3.5：部分正确，但同时存在关键遗漏、含糊或局部错误。
- 3.5 到 4.5：基础事实正确、主要得分点有覆盖，即使回答简短。
- 4.5 到 5：基础正确且进阶覆盖完整，边界和工程理解充分。
表达流畅不能提高 correctness_score；信息不足时降低 confidence，不要强行给高分。
只输出严格 JSON。"""

PROMPT = """【题目】{question}

【基础得分点】
{base_points}

【进阶得分点】
{adv_points}

【本轮问答】
{qa_block}

【知识库证据】
{kb_evidence}

请输出：
{{
  "correctness_score": <0-5>,
  "evidence": ["最多3条，引用考生原话或得分点"],
  "missing_points": ["最多3条"],
  "misconceptions": ["最多3条，必须是考生明确讲错的"],
  "claims": [
    {{"claim": "<考生的一条技术主张>",
      "verdict": "supported|contradicted|insufficient",
      "severity": "none|minor|major",
      "evidence": "<为什么这样判；引用考生原话或得分点>"}}
  ],
  "target_results": [
    {{"target": "<基础或进阶得分点>", "covered": <true|false>,
      "correct": <true|false|null>, "evidence": "<依据>"}}
  ],
  "point_atoms": [
    {{"point": "<原始得分点>",
      "atom": "<该得分点拆出的一个原子断言>",
      "verdict": "supported|contradicted|insufficient",
      "severity": "none|minor|major",
      "evidence": "<考生原话；如果是知识库核验，引用知识库证据>"}}
  ],
  "confidence": "high|medium|low"
}}"""


_CLAIM_VERDICTS = {"supported", "contradicted", "insufficient"}
_CLAIM_SEVERITY = {"none", "minor", "major"}


def _clean_claims(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for row in value[:8]:
        if not isinstance(row, dict):
            continue
        claim = str(row.get("claim") or "").strip()[:160]
        verdict = str(row.get("verdict") or "").strip().lower()
        severity = str(row.get("severity") or "").strip().lower()
        if not claim or verdict not in _CLAIM_VERDICTS:
            continue
        if severity not in _CLAIM_SEVERITY:
            severity = "none"
        out.append({
            "claim": claim,
            "verdict": verdict,
            "severity": severity,
            "evidence": str(row.get("evidence") or "").strip()[:160],
        })
    return out


def _clean_target_results(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for row in value[:8]:
        if not isinstance(row, dict):
            continue
        target = str(row.get("target") or "").strip()[:160]
        if not target:
            continue
        covered = row.get("covered")
        correct = row.get("correct")
        out.append({
            "target": target,
            "covered": covered if isinstance(covered, bool) else None,
            "correct": correct if isinstance(correct, bool) else None,
            "evidence": str(row.get("evidence") or "").strip()[:160],
        })
    return out


def _clean_point_atoms(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for row in value[:12]:
        if not isinstance(row, dict):
            continue
        point = str(row.get("point") or "").strip()[:160]
        atom = str(row.get("atom") or "").strip()[:200]
        verdict = str(row.get("verdict") or "").strip().lower()
        severity = str(row.get("severity") or "").strip().lower()
        if not atom or verdict not in _CLAIM_VERDICTS:
            continue
        if severity not in _CLAIM_SEVERITY:
            severity = "none"
        out.append({
            "point": point,
            "atom": atom,
            "verdict": verdict,
            "severity": severity,
            "evidence": str(row.get("evidence") or "").strip()[:200],
        })
    return out


def parse_objective_payload(data: dict) -> tuple[dict, Optional[str]]:
    """Validate the objective model output into the stable additive shape."""
    if not isinstance(data, dict):
        return {}, "客观线未返回可解析 JSON"
    try:
        correctness = float(data.get("correctness_score"))
    except (TypeError, ValueError):
        return {}, "客观线 correctness_score 非法"
    correctness = max(0.0, min(5.0, correctness))
    claims = _clean_claims(data.get("claims"))
    targets = _clean_target_results(data.get("target_results"))
    point_atoms = _clean_point_atoms(data.get("point_atoms"))
    raw_misconceptions = data.get("misconceptions")
    raw_misconceptions = (raw_misconceptions
                          if isinstance(raw_misconceptions, list) else [])
    misconceptions = [
        str(x)[:120] for x in raw_misconceptions[:3] if str(x).strip()
    ]
    for row in claims:
        if row["verdict"] == "contradicted" and row["claim"] not in misconceptions:
            misconceptions.append(row["claim"])
    misconceptions = misconceptions[:5]
    return {
        "correctness_score": round(correctness, 2),
        "evidence": [str(x)[:120] for x in (data.get("evidence") or [])[:3]],
        "missing_points": [
            str(x)[:120] for x in (data.get("missing_points") or [])[:3]
        ],
        "misconceptions": misconceptions,
        "claims": claims,
        "claim_counts": {
            "supported": sum(1 for row in claims if row["verdict"] == "supported"),
            "contradicted": sum(1 for row in claims if row["verdict"] == "contradicted"),
            "insufficient": sum(1 for row in claims if row["verdict"] == "insufficient"),
        },
        "target_results": targets,
        "point_atoms": point_atoms,
        "confidence": str(data.get("confidence") or "").lower(),
    }, None


class ObjectiveScorer:
    def __init__(self):
        self.error = ""
        self.last_raw = ""

    @property
    def ready(self) -> bool:
        return bool(config.OBJECTIVE_BASE_URL and config.OBJECTIVE_API_KEY)

    def score_round(self, ctx: dict) -> tuple[dict, Optional[str]]:
        if not self.ready:
            return {}, "客观线未配置 base_url 或 api_key"
        url = config.OBJECTIVE_BASE_URL.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        user = PROMPT.format(
            question=ctx.get("question", ""),
            base_points=ctx.get("base_points") or "（无）",
            adv_points=ctx.get("adv_points") or "（无）",
            qa_block=ctx.get("qa_block") or "（无有效回答）",
            kb_evidence=ctx.get("kb_evidence") or "（无）",
        )
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {config.OBJECTIVE_API_KEY}"},
                json={
                    "model": config.OBJECTIVE_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                timeout=config.OBJECTIVE_TIMEOUT,
            )
            resp.raise_for_status()
            self.last_raw = (
                (((resp.json().get("choices") or [{}])[0]
                  .get("message") or {}).get("content") or "")
            )
        except Exception as e:
            logger.exception("客观线调用失败")
            return {}, f"{type(e).__name__}: {e}"

        data = _extract_json(self.last_raw)
        return parse_objective_payload(data)


_objective: Optional[ObjectiveScorer] = None


def get_objective_scorer() -> ObjectiveScorer:
    global _objective
    if _objective is None:
        _objective = ObjectiveScorer()
    return _objective


def objective_status() -> dict:
    scorer = get_objective_scorer()
    return {
        "objective_provider": config.OBJECTIVE_PROVIDER,
        "objective_model": config.OBJECTIVE_MODEL,
        "objective_ready": scorer.ready,
        "objective_error": scorer.error,
    }
