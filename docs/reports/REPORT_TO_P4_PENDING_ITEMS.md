# 致 P4：前端待接清单

后端接口已就绪，下面四处页面还没接。按优先级排列：体态传参影响报告数据完整性，报告页两项影响决赛演示。

接口字段以 `docs/API.md` 为准，前端动作的完整说明在 `docs/reports/REPORT_TO_P4_FINAL_FEATURES.md`。本文只列当前缺什么、改哪里、怎么验收。

---

## 1. 体态分析传参（优先）

### 现状

`src/composables/useCameraTracking.js` 的 `uploadFrames()` 调用：

```js
const res = await analyzeBodyLanguage({ frames: snapshot })
```

只传了 `frames`。后端收不到面试 ID 与轮次，结果不会落库，面试结束后的报告里也就没有体态数据。

### 后端接口

```
POST /body-language/analyze
{
  "frames": [ ... ],
  "interview_id": 12,
  "round": 3
}
```

`interview_id` 与 `round` 必须同时提供。只传一个返回 400；都不传时接口只转发分析结果，不落库，响应里 `stored: false`。

### 改法

`useCameraTracking()` 目前不接收参数。可以在 `InterviewRoom.vue` 调用时传入当前面试 ID 与轮次，例如：

```js
const { ... } = useCameraTracking({
  interviewId: () => interview.value?.id,
  round: () => interview.value?.current_round
})
```

在 `uploadFrames()` 里把这两个值一并放进请求体。轮次取当前作答轮，即 `interview.current_round`。

### 验收

- 分析接口响应 `stored: true`。
- 面试结束后，`GET /reports/{interview_id}` 的 `expression_analysis.body.available` 为 `true`，`body.summary` 有评语。
- 未开摄像头或证据不足时，`body.available` 为 `false`，不要补 0。

---

## 2. 设置面板接后端

### 现状

`src/components/SettingsCard.vue` 只有六个分类的导航，点击后统一提示「暂未开放」。后端的 `GET /settings` 与 `PUT /settings` 已经可用，但没有页面调用。

### 后端接口

```
GET /settings    读取，没有记录时返回默认值
PUT /settings    部分更新，只提交要改的字段
```

6 个字段：

| 字段 | 类型 | 默认值 | 建议放在哪个分类 |
| :--- | :--- | :--- | :--- |
| `default_position` | string | `""` | 账户或面试偏好 |
| `voice_answer` | bool | `true` | 语音与音频 |
| `auto_tts` | bool | `true` | 语音与音频 |
| `body_language` | bool | `true` | 数据与隐私 |
| `report_preference` | string | `detailed` | 账户或报告偏好 |
| `theme` | string | `system` | 外观 |

`report_preference` 取值 `detailed` / `concise`；`theme` 取值 `light` / `dark` / `system`。`default_position` 传空串表示清空，非空时必须是已开放岗位的 code。非法值返回 400。

### 改法

进入设置卡片时调 `GET /settings`，用返回值初始化控件。用户改动后调 `PUT /settings`，只提交变化字段：

```json
PUT /settings
{ "theme": "dark", "voice_answer": false }
```

返回完整的 6 字段对象，直接覆盖本地状态。开关类设置可以在前端立即生效，同时写回后端。

### 验收

- 修改后刷新页面或换设备登录，设置仍然生效。
- 非法主题或非法岗位返回 400，前端给出提示，不静默失败。

---

## 3. 报告页「表达与表现分析」

### 现状

`src/views/ReportPage.vue` 当前只有五维雷达、综合评语、优缺点与学习计划，没有表达分析模块。

### 后端返回

`GET /reports/{interview_id}`（分享页 `GET /share/{code}` 同样）已带 `expression_analysis`：

```json
{
  "available": true,
  "voice": {
    "available": true,
    "avg_chars_per_min": 213.3,
    "total_pauses": 3,
    "total_fillers": 1,
    "rounds": [ { "round": 1, "chars_per_min": 220, "...": "…" } ],
    "feedback": ["语速适中（平均约 213 字/分）。"]
  },
  "body": {
    "available": true,
    "avg_score": 4.0,
    "confidence": "high",
    "feedback": ["保持得不错"],
    "summary": "体态整体稳定，镜头前状态自然。"
  },
  "notice": null
}
```

### 前端动作

- `available: false` 时不画模块，把 `notice` 当一句说明展示。
- 数值为 `null` 表示没有数据，不要用 0 占位。
- 语音区展示 `avg_chars_per_min`（语速，字/分）、`total_pauses`（长停顿次数）、`total_fillers`（填充词个数），再列 `voice.feedback`。
- 体态区展示 `body.summary` 与 `body.feedback`；`body.avg_score` 是 0 到 5 分制，可作辅助信息。

### 验收

- 语音作答的场次能看到语速与停顿数字。
- 纯文字作答的场次显示「本场没有语音数据」的说明，不显示 0。

---

## 4. 报告页「查看示范作答」

### 现状

报告页没有逐题的示范作答入口。

### 数据位置

- `GET /reports/{interview_id}` 的 `qa_review[]`：每项 `{qa_id, round, question, judge_band, needs_improvement}`
- `GET /interviews/{interview_id}` 的 `qa_records[]`：每条带 `id`、`judge_band`、`needs_improvement`

`needs_improvement` 三种取值：

| 取值 | 含义 | 展示建议 |
| :--- | :--- | :--- |
| `true` | 引擎判定这道题没答上来 | 标「待提升」，优先显示按钮 |
| `false` | 引擎判定答到了 | 不标待提升，仍可提供按钮 |
| `null` | 平台不知道（原链路没有单题分） | 不要标「答得好」，可以每题都挂按钮 |

### 接口

```
POST /interviews/{interview_id}/qa/{qa_id}/sample-answer
```

```json
{
  "available": true,
  "cached": false,
  "content": "先说结论：……",
  "question_no": "JAVA_BACKEND-Q0001",
  "model": "deepseek-chat",
  "notice": null
}
```

### 前端动作

- 点击后进入加载态。首次生成需要数秒，`cached: true` 时是毫秒级。
- `available: true` 时弹窗展示 `content`，容器加 `white-space: pre-wrap`，用 `textContent` 渲染。
- `available: false` 表示这道题不在题库（追问或现场题），展示 `notice`，不显示正文。
- 503 表示大模型不可用，提示「稍后再试」。
- 面试未结束时接口返回 409，因此按钮只在已结束的面试里显示。

### 验收

- 点开一道题能显示示范作答。
- 第二次打开同一道题不再等待生成。
- 题库外的题显示提示而不是空白弹窗。

---

## 5. 职业速测的变更提醒

职业速测已经改为后端计分，前端 `CareerAnchor.vue` 调用：

```
GET  /career-anchor/questions
POST /career-anchor/submit   { "answers": [5, 4, 3, ...] }
```

`answers` 正好 20 项，每项 1~5，顺序与题目接口返回一致。后端返回倾向指数、兴趣/能力排序、一致性与置信度。

如果继续基于旧的本地计分版本改，合并时会与 main 冲突。请基于当前 main 的最新 `CareerAnchor.vue` 修改。

---

## 6. 参考

| 内容 | 位置 |
| :--- | :--- |
| 接口字段权威 | `docs/API.md` 第 3.3、3.6、4.1、6.8、9 节 |
| 四项功能的前端动作说明 | `docs/reports/REPORT_TO_P4_FINAL_FEATURES.md` |
| 后端自测 | `cd backend && python -m pytest -q`，当前 215 项全绿 |
