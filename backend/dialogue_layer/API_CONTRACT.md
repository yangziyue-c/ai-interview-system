# A11 API Contract

所有接口都按“只增不改”处理。已有字段不能删、不能改名、不能改类型。

## POST /start

请求：

```json
{
  "job": "Java 后端开发工程师",
  "intro": "",
  "resume_text": "",
  "resume_id": "",
  "interview_mode": "general",
  "persona_style": "standard"
}
```

常用响应：

```json
{
  "session_id": "abc12345",
  "job": "Java 后端开发工程师",
  "phase": "awaiting_start",
  "message": "开场白",
  "total_questions": 10,
  "weights": "技术35% 逻辑25% ...",
  "persona_style": "standard",
  "persona_label": "严谨型",
  "interview_mode": "general",
  "resume_read": null
}
```

`interview_mode=resume` 时必须传 `resume_text`。

## POST /next

请求：

```json
{"session_id": "abc12345", "message": ""}
```

题目响应：

```json
{
  "type": "question",
  "finished": false,
  "session_id": "abc12345",
  "phase": "awaiting_answer",
  "stage": "开场热身",
  "stage_index": 0,
  "q_index": 1,
  "total": 10,
  "difficulty": "easy",
  "question_id": "...",
  "question": "题目正文",
  "knowledge_points": ["..."],
  "opening_text": "..."
}
```

`finished=true` 时表示没有下一题，继续调 `/finish`。

## POST /chat

请求：

```json
{
  "session_id": "abc12345",
  "message": "考生回答",
  "speech": {},
  "body_language": {}
}
```

响应类型：`text/event-stream`

事件类型：

- `token`：面试官文本片段。
- `done`：一轮结束或进入追问。
- `error`：请求失败。

`done` 重点字段：

```text
follow_up
round_finished
session_id
q_index
action
effective
reranker_ok
attempts
follow_up_used
degrade_used
assist_used
hint_used
swapped
```

## POST /asr

Multipart 字段：

```text
file
session_id
round_index
allow_online
```

成功响应主要字段：

```text
ok
text
duration_ms
audio_ms
segments
pauses
pause_total_ms
asr_model
elapsed_ms
loudness
loudness_cv
tail_ratio
pitch_variation
emotion
emotion_score
emotion_dist
```

## POST /tts

请求：

```json
{"text": "需要朗读的文本", "voice": "longanlingxi"}
```

响应：`audio/wav`

## POST /body-language/analyze

只接受本地提取的数字姿态关键点，不接受图片、视频或音频。

## POST /finish

请求：

```json
{"session_id": "abc12345", "message": ""}
```

核心成绩字段：

```text
five_dim_avg
total_score
total_score_100
weights
summary
rounds
completion_rate
score_status
partial
dimension_info
difficulty_mix
score_by_difficulty
content_analysis
score_breakdown
objective
subjective
combined
review
pace_note
raw
```

## GET /result/{session_id}

返回同一份成绩单结构。未结束会话返回 `409`。
