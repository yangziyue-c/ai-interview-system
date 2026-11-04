# 决赛阶段前端对接说明（四项新增功能）

本文覆盖 2026-10-31 新增的四项功能：设置页、示范作答、表达与表现分析、职业锚定测试。
接口字段以 `docs/API.md` 为准（第 3.3、3.6、4.1、6.8、9、10 节），本文只写前端要做的动作与容易出错的边界。

所有接口带 `Authorization: Bearer <token>`，响应统一为 `{code, message, data}`。
Base URL：`http://localhost:8001/api/v1`。

---

## 1. 设置页

### 接口

```
GET /settings    读取（没有存过记录时返回默认值，不需要初始化）
PUT /settings    保存（部分更新，只提交改动字段）
```

6 个字段：

| 字段 | 类型 | 默认值 | 前端用途 |
| :--- | :--- | :--- | :--- |
| `default_position` | string | `""` | 开始面试时默认选中的岗位 code；空串表示未设置 |
| `voice_answer` | bool | `true` | 关闭后隐藏录音入口，只保留文字输入 |
| `auto_tts` | bool | `true` | 关闭后不自动播放面试官朗读 |
| `body_language` | bool | `true` | 关闭后不启动摄像头与关键点采集 |
| `report_preference` | string | `detailed` | `detailed` 或 `concise` |
| `theme` | string | `system` | `light`、`dark`、`system` |

### 前端动作

进入设置页调 GET，用返回结果渲染控件。保存时只提交用户改过的字段，例如：

```json
PUT /settings
{ "theme": "dark", "voice_answer": false }
```

返回完整的 6 字段对象，直接覆盖本地状态。

`default_position` 传空串表示清空；非空时必须是已开放岗位的 code，否则返回 400。
`report_preference` 与 `theme` 越界同样返回 400。字段传 `null` 按不修改处理。

这些开关由前端决定是否采集，后端不会强制执行。例如关闭体态开关后，前端不应再调用体态分析接口。

---

## 2. 示范作答

### 数据来源

两个位置都能拿到逐题判定：

- `GET /interviews/{interview_id}` 的 `qa_records[]`，每条带 `id`、`judge_band`、`needs_improvement`
- `GET /reports/{interview_id}` 的 `qa_review[]`，每项为 `{qa_id, round, question, judge_band, needs_improvement}`

判定口径：

| `needs_improvement` | 含义 | 展示建议 |
| :--- | :--- | :--- |
| `true` | 引擎判定这道题没答上来（最后一轮 `degrade` 或 `swap`） | 标「待提升」，显示按钮 |
| `false` | 引擎判定答到了（`L1`、`L2`、`L3`） | 不标待提升，仍可提供按钮 |
| `null` | 平台不知道（原链路没有单题分，或引擎没判出来） | 不要标「答得好」，可以每道题都挂按钮 |

原链路场次的 `judge_band` 与 `needs_improvement` 恒为 `null`。

### 接口

```
POST /interviews/{interview_id}/qa/{qa_id}/sample-answer
```

```json
{
  "code": 0,
  "message": "示范作答已生成",
  "data": {
    "available": true,
    "cached": false,
    "content": "先说结论：……",
    "question_no": "JAVA_BACKEND-Q0001",
    "model": "deepseek-chat",
    "notice": null
  }
}
```

### 前端动作

点击按钮后进入加载态。首次生成需要数秒，`cached: true` 时为毫秒级。

- `available: true`：弹窗展示 `content`，容器加 `white-space: pre-wrap`，用 `textContent` 渲染。
- `available: false`：这道题不在题库（追问或现场生成题），展示 `notice` 文案，不显示弹窗正文。
- HTTP 503（`code: 50300`）：大模型不可用，提示「稍后再试」。
- HTTP 409：面试尚未结束，不显示按钮即可。

---

## 3. 表达与表现分析

### 报告字段

`GET /reports/{interview_id}`、`GET /share/{code}` 以及结束面试的响应里都有 `expression_analysis`：

```json
{
  "available": true,
  "voice": {
    "available": true,
    "round_count": 3,
    "avg_chars_per_min": 213.3,
    "avg_pause_rate_per_min": 2.0,
    "total_pauses": 3,
    "total_pause_ms": 2000,
    "total_fillers": 1,
    "avg_filler_rate": 0.01,
    "avg_loudness_cv": 0.25,
    "rounds": [
      { "round": 1, "chars_per_min": 220, "pauses": 2, "pause_total_ms": 1200,
        "fillers": 1, "filler_rate": 0.01, "duration_ms": 30000, "loudness_cv": 0.2 }
    ],
    "feedback": ["语速适中（平均约 213 字/分）。"]
  },
  "body": {
    "available": true,
    "round_count": 2,
    "avg_score": 4.0,
    "confidence": "high",
    "feedback": ["保持得不错"],
    "summary": "体态整体稳定，镜头前状态自然。"
  },
  "notice": null
}
```

### 前端动作

模块标题用「表达与表现分析」。

- `available: false` 时不画模块，把 `notice` 当一句说明展示。
- 数值为 `null` 表示没有数据，不要用 0 占位。
- 语音区展示 `avg_chars_per_min`（语速，字/分）、`total_pauses`（长停顿次数）、`total_fillers`（填充词个数），再列出 `voice.feedback`。
- 体态区展示 `body.summary`（稳定性评语）与 `body.feedback`。`body.avg_score` 是 0 到 5 分制，可作为辅助信息。
- `voice.rounds` 可用于画逐轮趋势。

### 数据采集前提

语音读数：录音后调 `POST /uploads/audio/asr`，把响应中除 `text`、`url` 外的键整条放进提交答案的 `speech` 字段。少一个键，报告里就少一项读数。

```json
POST /interviews/{interview_id}/answers
{
  "answer": "转写后的文本",
  "audio_url": "/uploads/12_ab3f9c2d.mp3",
  "speech": { "duration_ms": 30000, "chars_per_min": 220, "pauses": 2, "fillers": 1, "...": "…" }
}
```

体态结果：调用体态分析时同时带 `interview_id` 和 `round`，后端才会把结果写进该轮问答记录。

```json
POST /body-language/analyze
{
  "frames": [
    { "timestamp_ms": 0, "landmarks": [ { "x": 0.51, "y": 0.32, "z": 0.0, "visibility": 0.99 } ] }
  ],
  "interview_id": 12,
  "round": 3
}
```

只传其中一个返回 400；会话不属于当前用户返回 404。不传这两个字段时接口只转发分析结果，不落库，报告里也不会有体态数据。

摄像头画面不出浏览器：MediaPipe 在本地把画面转成关键点后立即丢弃，上传的只有数字坐标。

---

## 4. 职业锚定测试

### 流程

1. 进入测试页，调 `GET /career-anchor/questions` 拉取 5 道题。
2. 用户逐题选择，必须 5 题全部作答。
3. 调 `POST /career-anchor/submit` 提交答案。
4. 展示推荐卡片，用户点击「开始模拟面试」后调 `POST /interviews`，`position` 用推荐结果里的 code。

### 拉题

```
GET /career-anchor/questions
```

```json
{
  "total": 5,
  "questions": [
    {
      "id": "q1",
      "text": "接到一个新需求，你最想先动手做哪一部分？",
      "options": [
        { "key": "A", "text": "把服务拆成模块，先定好接口和数据怎么流转" },
        { "key": "B", "text": "把页面结构和交互流程先画出来" }
      ]
    }
  ]
}
```

选项只有 `key` 与 `text`，计分权重不下发。

### 提交

```
POST /career-anchor/submit
{ "answers": { "q1": "A", "q2": "C", "q3": "B", "q4": "A", "q5": "D" } }
```

```json
{
  "recommended": {
    "position": "backend",
    "name": "后端开发工程师",
    "score": 9,
    "reason": "你的选择在多个方向间有交叉，后端开发工程师的匹配度最高（9 分，领先第二名 2 分）。"
  },
  "alternatives": [ { "position": "system_design", "name": "系统设计工程师", "score": 7 } ],
  "scores": [ { "position": "backend", "name": "后端开发工程师", "score": 9 } ],
  "guide": "可以先用「后端开发工程师」开始一场模拟面试，系统会按该岗位的题目出题。"
}
```

`recommended.position` 直接传给开始面试接口：

```json
POST /interviews
{ "position": "backend" }
```

缺题或选项非法返回 400，前端给一句「请完成全部 5 道题」。

---

## 5. 联调顺序

1. 设置页：GET 与 PUT 打通，确认 6 个字段能读能写。
2. 职业锚定：拉题、提交、用推荐岗位开一场面试。
3. 语音与体态采集：确认提交答案带 `speech`、体态分析带 `interview_id` 与 `round`。
4. 报告展示：渲染 `expression_analysis` 与 `qa_review`，接通示范作答弹窗。

## 6. 常见错误

| 现象 | 原因 | 改法 |
| :--- | :--- | :--- |
| 报告里没有语音数据 | 提交答案时没带 `speech`，或只挑了部分字段 | ASR 响应除 `text`、`url` 外整条传回 |
| 报告里没有体态数据 | 体态分析没带 `interview_id` 与 `round` | 两个参数同时传 |
| 体态接口返回 400 | 两个参数只传了一个 | 同时提供或都不提供 |
| 把 `needs_improvement: null` 标成「答得好」 | `null` 表示不知道 | 只有 `false` 才表示判定为答到了 |
| 把 `expression_analysis.available: false` 当错误 | 这是「没有数据」，不是失败 | 展示 `notice`，不画图表 |
| 示范作答弹窗没有换行 | 用了普通 div | 容器加 `white-space: pre-wrap` |
| 示范作答按钮点了没反应 | 面试未结束返回 409 | 只在已结束的面试里显示按钮 |
