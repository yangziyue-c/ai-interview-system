# -*- coding: utf-8 -*-
"""Deterministic resume parsing and resume-aware question matching."""
from __future__ import annotations

import re
from typing import Any


SKILLS = (
    "Java", "JVM", "Spring", "Spring Boot", "Spring Cloud", "MyBatis",
    "MySQL", "Redis", "Kafka", "RocketMQ", "RabbitMQ", "Elasticsearch",
    "Docker", "Kubernetes", "Linux", "Nginx", "Netty", "Dubbo",
    "Python", "FastAPI", "Django", "Flask", "Go", "C++", "C#", "PHP",
    "JavaScript", "TypeScript", "Vue", "React", "Node.js", "Webpack",
    "HTML", "CSS", "Sass", "Vite", "小程序",
    "PostgreSQL", "Oracle", "MongoDB", "SQL Server",
    "Git", "Jenkins", "CI/CD", "Prometheus", "Grafana",
    "pytest", "Selenium", "JMeter", "Postman", "Appium",
    "PyTorch", "TensorFlow", "Spark", "Hadoop", "Flink",
    "MQ", "JUC", "AQS", "CAS", "GC", "HTTP", "TCP", "UDP",
)

# Aliases are deliberately small and explicit. They are used only to map a
# resume phrase back to a canonical skill before scoring.
_ALIASES = {
    "SpringBoot": "Spring Boot",
    "SpringCloud": "Spring Cloud",
    "Node": "Node.js",
    "NodeJS": "Node.js",
    "Vue.js": "Vue",
    "React.js": "React",
    "K8s": "Kubernetes",
    "ElasticSearch": "Elasticsearch",
    "Mybatis": "MyBatis",
    "Postgres": "PostgreSQL",
    "CI CD": "CI/CD",
}

_PROJECT_MARKERS = (
    "项目", "系统", "平台", "服务", "中台", "商城", "后台",
    "管理", "订单", "支付", "推荐", "搜索", "数据", "大屏",
)
_PROJECT_HEADING = re.compile(
    r"^(?:项目|项目经历|项目经验|实践项目|项目名称)\s*[:：]?\s*(.*)$")
_SECTION_HEADING = re.compile(
    r"^(?:技能|专业技能|技术栈|项目经历|项目经验|工作经历|实习经历|"
    r"教育经历|个人优势|自我评价|成果|职责)\s*[:：]?\s*$")
_NON_PROJECT_PREFIX = re.compile(
    r"^(?:技能|技术栈|职责|工作内容|难点|挑战|问题|瓶颈|"
    r"结果|成果|收益|优化|教育|证书|自我评价)\s*[:：]")
_ROLE_RE = re.compile(
    r"负责|职责|主导|参与|牵头|开发|设计|实现|维护|优化|搭建|落地|owner|负责人",
    re.IGNORECASE)
_DIFFICULTY_RE = re.compile(
    r"难点|挑战|问题|瓶颈|故障|复杂|高并发|高性能|一致性|"
    r"优化|调优|排障|定位|补偿|容错|限流|降级",
    re.IGNORECASE)
_OUTCOME_RE = re.compile(
    r"提升|降低|减少|增加|达到|成果|收益|节省|稳定|"
    r"\d+(?:\.\d+)?\s*(?:%|％|倍|ms|毫秒|秒|万|亿|qps|tps)",
    re.IGNORECASE)
_CHOICE_RE = re.compile(
    r"选型|采用|使用|基于|引入|架构|技术栈|方案|设计|改造|替换",
    re.IGNORECASE)
_UNCERTAIN_RE = re.compile(
    r"了解|熟悉|接触过|参与过|正在学习|入门|有所|大概|可能|"
    r"不确定|未量化|尚未|没有量化",
    re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _lines(text: str) -> list[str]:
    rows = []
    for line in (text or "").splitlines():
        clean = _norm(line.strip(" -·\t"))
        if clean:
            rows.append(clean)
    return rows


def _dedupe(items: list[str], limit: int = 20) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _norm(item).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(_norm(item))
        if len(out) >= limit:
            break
    return out


def _dedupe_json(items: list[dict], limit: int) -> list[dict]:
    out = []
    seen = set()
    for item in items:
        key = tuple(sorted((k, str(v)) for k, v in item.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _contains_skill(text: str, skill: str) -> bool:
    hay = _norm(text).casefold()
    needle = _norm(skill).casefold()
    if not needle:
        return False
    if re.search(r"[a-z]", needle):
        pattern = r"(?<![a-z0-9+#.])" + re.escape(needle) + r"(?![a-z0-9+#.])"
        return bool(re.search(pattern, hay))
    return needle in hay


def _skills_in(text: str) -> list[str]:
    return [skill for skill in SKILLS if _contains_skill(text, skill)]


def _is_project_heading(line: str) -> bool:
    if _SECTION_HEADING.match(line):
        return False
    if _NON_PROJECT_PREFIX.match(line):
        return False
    if _PROJECT_HEADING.match(line):
        return True
    if len(line) > 64:
        return False
    return any(marker in line for marker in _PROJECT_MARKERS)


def _short(value: str, limit: int = 160) -> str:
    value = _norm(value)
    return value if len(value) <= limit else value[:limit] + "…"


def parse_resume(text: str) -> dict[str, Any]:
    """Extract a stable structure without inventing experience."""
    raw = _norm(text)
    lines = _lines(text)

    skill_hits: list[str] = []
    for skill in SKILLS:
        if _contains_skill(raw, skill):
            skill_hits.append(skill)
    for alias, canonical in _ALIASES.items():
        if _contains_skill(raw, alias):
            skill_hits.append(canonical)
    skills = _dedupe(skill_hits, 24)

    skills_with_evidence = []
    for skill in skills:
        evidence = [_short(line) for line in lines
                    if _contains_skill(line, skill)][:3]
        skills_with_evidence.append({
            "skill": skill,
            "evidence": evidence,
            "confidence": "explicit" if evidence else "keyword_only",
        })

    projects: list[dict[str, Any]] = []
    project_starts = [i for i, line in enumerate(lines) if _is_project_heading(line)]
    for pos, start in enumerate(project_starts[:8]):
        end = project_starts[pos + 1] if pos + 1 < len(project_starts) else len(lines)
        block = lines[start + 1:end]
        heading_match = _PROJECT_HEADING.match(lines[start])
        heading_tail = (heading_match.group(1).strip()
                        if heading_match and heading_match.group(1).strip() else "")
        name = heading_tail or lines[start]
        combined = [lines[start], *block]
        tech = _dedupe([skill for line in combined for skill in _skills_in(line)], 12)
        responsibilities = [_short(line) for line in block if _ROLE_RE.search(line)][:6]
        difficult = [_short(line) for line in block if _DIFFICULTY_RE.search(line)][:6]
        outcomes = [_short(line) for line in block if _OUTCOME_RE.search(line)][:6]
        choices = []
        for line in block:
            if not _CHOICE_RE.search(line):
                continue
            for skill in _skills_in(line):
                choices.append({"technology": skill, "evidence": _short(line)})
        choices = _dedupe_json(choices, 8)
        probes = []
        for skill in tech[:3]:
            probes.append(f"追问「{_short(name, 40)}」中 {skill} 的技术选型、难点和结果")
        if not tech and difficult:
            probes.append(f"追问「{_short(name, 40)}」中的难点、取舍和最终结果")
        projects.append({
            "name": _short(name, 80),
            "tech": tech,
            "evidence": [_short(line) for line in combined][:8],
            "responsibilities": responsibilities,
            "technology_choices": choices,
            "difficulties": difficult,
            "outcomes": outcomes,
            "probe_points": _dedupe(probes, 4),
        })

    if not projects:
        inline = [line for line in lines
                  if _PROJECT_HEADING.match(line) and len(line) <= 160]
        for line in inline[:3]:
            match = _PROJECT_HEADING.match(line)
            tail = (match.group(1).strip() if match else line)
            if not tail:
                continue
            tech = _skills_in(tail)
            projects.append({
                "name": _short(tail, 80),
                "tech": tech,
                "evidence": [_short(line)],
                "responsibilities": [],
                "technology_choices": [],
                "difficulties": [],
                "outcomes": [],
                "probe_points": [
                    f"追问「{_short(tail, 40)}」中的个人职责和技术选择"
                ] if tech else [],
            })

    roles = [{"role": _short(line, 100), "evidence": _short(line)}
             for line in lines if _ROLE_RE.search(line)][:8]
    technology_choices = []
    for line in lines:
        if not _CHOICE_RE.search(line):
            continue
        for skill in _skills_in(line):
            technology_choices.append({
                "technology": skill,
                "evidence": _short(line),
            })
    technology_choices = _dedupe_json(technology_choices, 12)
    difficulties = [_short(line) for line in lines if _DIFFICULTY_RE.search(line)][:10]
    outcomes = [_short(line) for line in lines if _OUTCOME_RE.search(line)][:10]
    probe_points = _dedupe(
        [probe for project in projects for probe in project["probe_points"]], 8)
    uncertainties = [
        {"text": _short(line), "reason": "表述较笼统，需要面试中确认边界"}
        for line in lines if line and _UNCERTAIN_RE.search(line)
    ][:8]
    for project in projects:
        if project["tech"] and not project["outcomes"]:
            uncertainties.append({
                "text": f"项目「{project['name']}」没有识别到可量化结果",
                "reason": "缺少结果证据，不能据此推断实际效果",
            })

    return {
        "raw_text": raw,
        "skills": skills,
        "skills_with_evidence": skills_with_evidence,
        "projects": projects,
        "roles": _dedupe_json(roles, 8),
        "technology_choices": technology_choices,
        "difficulties": difficulties,
        "outcomes": outcomes,
        "probe_points": probe_points,
        "uncertainties": _dedupe_json(uncertainties, 12),
        "has_resume": bool(raw),
    }


def format_for_prompt(profile: dict[str, Any], max_chars: int = 1600) -> str:
    skills = "、".join(profile.get("skills") or []) or "未识别"
    projects = profile.get("projects") or []
    project_lines = []
    for project in projects[:5]:
        project_lines.append(
            f"- {project.get('name', '')} 技术："
            f"{'、'.join(project.get('tech') or []) or '未识别'}")
        for label, key in (("职责", "responsibilities"),
                           ("难点", "difficulties"),
                           ("结果", "outcomes")):
            rows = project.get(key) or []
            if rows:
                project_lines.append(f"  {label}：{'；'.join(rows[:2])}")
    project_text = "\n".join(project_lines) or "- 未识别到项目名称"
    extras = []
    if profile.get("probe_points"):
        extras.append("可追问点：\n" + "\n".join(
            f"- {point}" for point in profile["probe_points"][:5]))
    if profile.get("uncertainties"):
        extras.append("不确定信息：\n" + "\n".join(
            f"- {row.get('text', '')}" for row in profile["uncertainties"][:4]))
    raw = str(profile.get("raw_text") or "")
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "…"
    return (
        f"识别技能：{skills}\n"
        f"结构化项目信息：\n{project_text}\n"
        + ("\n".join(extras) + "\n" if extras else "")
        + f"简历摘录：{raw}"
    )


def format_match_query(profile: dict[str, Any]) -> str:
    """A compact text used only as an optional semantic-matching query."""
    parts = list(profile.get("skills") or [])
    for project in (profile.get("projects") or [])[:5]:
        parts.extend(project.get("tech") or [])
        parts.extend(project.get("difficulties") or [])
    parts.extend(profile.get("difficulties") or [])
    return "；".join(_dedupe(parts, 30))


def _question_fields(question: dict) -> str:
    return " ".join(
        str(question.get(k, ""))
        for k in (
            "题目内容", "核心关键词", "关联知识点",
            "基础得分点", "进阶得分点",
        )
    )


def question_match_details(question: dict, profile: dict[str, Any],
                           difficulty: str = "",
                           semantic_score: float | None = None) -> dict:
    """Return an explainable hybrid score; semantic_score is optional."""
    if not profile.get("skills") and not profile.get("projects"):
        return {"score": 0.0, "skill_hits": [], "project_hits": [],
                "difficulty_bonus": 0.0, "semantic_bonus": 0.0}
    fields = _question_fields(question)
    skill_hits = [skill for skill in (profile.get("skills") or [])
                  if _contains_skill(fields, skill)]
    project_tech = []
    for project in profile.get("projects") or []:
        project_tech.extend(project.get("tech") or [])
    project_hits = _dedupe(
        [skill for skill in project_tech if _contains_skill(fields, skill)], 8)
    role_hits = sum(
        1 for row in (profile.get("roles") or [])
        if _contains_skill(fields, row.get("role", "")))
    difficulty_bonus = 0.0
    if difficulty:
        q_difficulty = str(question.get("难度等级") or "").casefold()
        expected = difficulty.casefold()
        if q_difficulty == expected:
            difficulty_bonus = 1.0
        elif {q_difficulty, expected} <= {"easy", "medium"}:
            difficulty_bonus = 0.4
        elif {q_difficulty, expected} <= {"medium", "hard"}:
            difficulty_bonus = 0.4
    semantic_bonus = 0.0
    if semantic_score is not None:
        try:
            semantic_bonus = max(0.0, min(1.0, float(semantic_score))) * 4.0
        except (TypeError, ValueError):
            semantic_bonus = 0.0
    score = (
        len(skill_hits) * 3.0
        + len(project_hits) * 4.0
        + role_hits
        + difficulty_bonus
        + semantic_bonus
    )
    return {
        "score": round(score, 3),
        "skill_hits": skill_hits,
        "project_hits": project_hits,
        "difficulty_bonus": difficulty_bonus,
        "semantic_bonus": round(semantic_bonus, 3),
    }


def question_match_score(question: dict, profile: dict[str, Any]) -> int:
    """Backward-compatible integer score used by existing callers."""
    score = question_match_details(question, profile)["score"]
    return int(round(score))
