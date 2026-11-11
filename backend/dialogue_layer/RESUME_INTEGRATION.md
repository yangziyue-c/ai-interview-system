# Resume Integration Contract

This document defines the first-version resume-based interview flow.

## Responsibility

- Frontend: resume list, editor, upload/import entry, interview setup.
- P1 backend: store resume files, parse PDF/DOCX/TXT, provide structured or raw
  resume text to the AI service.
- AI service on port 8005: parse resume text for skills/projects, use it in the
  interviewer prompt, and prefer matching questions when
  `interview_mode=resume`.

The AI service does not store resume files or resume database records.

## Start Request

```json
{
  "job": "Java 后端开发工程师",
  "interview_mode": "resume",
  "resume_id": "resume-123",
  "resume_text": "技能：Java、Spring Boot、Redis、MySQL\n项目：订单系统，负责支付回调和缓存。",
  "persona_style": "strict"
}
```

Fields:

- `interview_mode`: `general` or `resume`
- `resume_id`: optional P1-side ID for logging/echo
- `resume_text`: required when mode is `resume`
- `persona_style`: `relaxed`, `standard`, or `strict`

## Start Response

```json
{
  "session_id": "abc12345",
  "interview_mode": "resume",
  "resume_read": {
    "enabled": true,
    "mode": "resume",
    "chars": 87,
    "skills": ["Java", "Spring", "Redis", "MySQL"],
    "projects": [
      {
        "name": "项目：订单系统",
        "tech": ["Redis"],
        "evidence": ["负责支付回调和缓存"],
        "responsibilities": ["负责支付回调和缓存"],
        "difficulties": ["Redis 扣减成功但数据库写入失败"],
        "outcomes": ["超卖下降 90%"],
        "probe_points": ["追问该项目中 Redis 的技术选择、难点和结果"]
      }
    ],
    "skills_with_evidence": [
      {"skill": "Redis", "evidence": ["负责支付回调和缓存"], "confidence": "explicit"}
    ],
    "technology_choices": [],
    "difficulties": [],
    "outcomes": [],
    "probe_points": [],
    "uncertainties": []
  }
}
```

## Behavior

- Resume mode is enabled by `A11_RESUME=1`.
- Resume text is capped by `A11_RESUME_MAX_CHARS` (default 6000).
- Resume facts enter the interviewer system prompt only.
- Resume facts do not enter the scoring prompt.
- Question selection combines project technology, skills, responsibilities,
  difficulty fit, and history avoidance. If an embedding encoder is already
  available, it also adds BGE-M3 semantic similarity; otherwise it degrades to
  deterministic keyword/project matching.
- If no matching question exists, the normal question bank fallback remains.
- Resume facts still do not change the five-dimension score.

## Speech and Camera Additions

`POST /chat` accepts two additive optional objects:

- `speech`: the existing `/asr` readings. The service now also derives a
  personal baseline after at least two speech samples and 10 seconds of speech.
- `body_language`: a numeric camera summary. Only `communication` and
  `adaptability` may move, capped at `+/-0.30` and `+/-0.20`; low confidence or
  insufficient coverage abstains.

Camera frames, images, video, audio and raw landmark sequences are never sent
beyond the local browser/server measurement path.

## Persona Mapping

| UI name | API value |
|---|---|
| 温和型 | `relaxed` |
| 严谨型 | `standard` |
| 严肃型 | `strict` |

## P1 Minimum Implementation

1. Store resume records and files.
2. Parse PDF/DOCX/TXT to plain text.
3. Pass the text as `resume_text` on `/start`.
4. Render `resume_read.skills` and `resume_read.projects` for debugging.
5. Keep the original resume file private.

## Out of Scope for Version 1

- OCR from photos
- Resume template rendering
- Resume version history
- Multi-resume ranking
- Billing and remaining-attempt counts
