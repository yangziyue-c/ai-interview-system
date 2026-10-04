# 断点续答与语音读数 · 前端对接说明（给 4 号）

> 2026-10-04。本文讲两处新增能力：断点续答可以还原追问记录，语音表达读数可以随作答回传进报告。
> 两处都是加法，已有字段的形状没有变化，不接也不影响现有功能。接口权威仍是 `docs/API.md`；
> 引擎模式的基础说明见 `REPORT_TO_P4_A11_ENGINE.md`。

## 一、断点续答：追问记录现在能还原

**背景**：引擎链路（`engine=a11`）下，追问原文与考生的每轮回答都不在 `qa_records` 的
`question`/`answer` 里。`question` 恒为题库原题面（学习计划靠它反查题库），`answer` 会被
后续追问覆盖、只留最后一次。此前刷新或重新进入对话室，恢复出来的对话只有题面和最后一次
回答，中间的追问与作答拿不回来。

**现在**：`GET /interviews/{id}` 的 `qa_records` 每题多一个 `engine_turns`（原链路为 `null`）：

```json
{ "round": 1, "question": "线程的状态有哪些？", "answer": "最后一次的回答文本",
  "engine_turns": [
    { "answer": "第一次的回答", "audio_url": "/uploads/…", "reply": "面试官追问一",
      "action": "L1", "follow_up": true, "swapped": false },
    { "answer": "第二次的回答", "audio_url": null, "reply": "面试官收尾语",
      "action": "close", "follow_up": false, "swapped": false }
  ] }
```

**重建规则**：题面 →（每条：考生 `answer` → 面试官 `reply`）。末条 `follow_up=true` 时，
那条 `reply` 就是当前等考生回答的话；末行 `answer=null` 且没有未回的追问时，等待回答的是题面。
题号仍由 `current_round` 决定，追问不推进题号。

```js
// 参考写法（演示前端 js/views.js 的同款逻辑）
(qa_records || []).forEach((qa) => {
  push("ai", qa.question);
  const turns = qa.engine_turns || [];
  if (turns.length) {
    turns.forEach((t) => {
      if (t.answer) push("user", t.answer);
      if (t.reply) push("ai", t.reply);
    });
  } else if (qa.answer) {
    push("user", qa.answer);
  }
});
```

三个注意点：

- 原链路 `engine_turns` 为 `null`，按原来的 `question`/`answer` 渲染即可，现有代码不用动。
- 本次改动前落库的旧场次：条目里没有 `answer` 键，能还原多少算多少（最后一次回答仍在 `answer` 列）。
- 每条里还有 `audio_url`（该轮录音地址），做逐轮回放时用它；它与 `answer` 一样是按轮的。

## 二、语音读数：可以随作答回传了

**背景**：`POST /uploads/audio/asr` 一直返回一组表达读数（净时长、停顿、音量、情感分布），
但此前没有承载它们提交的字段，引擎侧拿不到，报告里的语速 / 停顿 / 填充词就一直是空的。
引擎的设计要求调用方把 `/asr` 的读数**整条**回传；它自己的代码注释里记录了实测：调用方只挑
前几个键，报告里 `loudness`、`emotion*` 全成了 `null`。

**现在**：`POST /interviews/{id}/answers` 支持可选 `speech`：

```json
{ "answer": "语音转写的文本", "audio_url": "/uploads/…",
  "speech": { "duration_ms": 16878, "audio_ms": 17600, "segments": [ "…" ],
              "pauses": 2, "pause_total_ms": 3400, "asr_model": "sensevoice-small-int8",
              "loudness": 0.137, "loudness_cv": 0.264, "tail_ratio": 1.05,
              "pitch_variation": null, "emotion": "neu",
              "emotion_score": null, "emotion_dist": null } }
```

**取法**：把转写响应里除 `text` 与 `url` 外的键整条带上。不要挑字段：少一个键，报告里就少
一项读数。

```js
const { text, url, ...speech } = asrResult;   // asrResult 为 /uploads/audio/asr 的 data
api.submitAnswer(id, answer, url, speech);
```

三条边界：

- 文字作答不传 `speech`，行为与从前逐字节相同（引擎侧两条路径是同一份代码）。
- 只有引擎链路消费该字段；原链路忽略它，不会报错。
- 浏览器端 Vosk 只有文本、产不出这组读数，用它时这项能力用不上。要语速 / 停顿就改用
  `POST /uploads/audio/asr`（一次调用同时给文本、读数与可提交的 `url`）。

## 三、一个容易复刻的坑：语音状态要按轮清掉

演示前端此前有过一处错配（已修）：转写结果与待发录音存在全局对象里，只在「按住话筒」时
清空。若某一轮用了语音、下一轮是纯文字，提交时会把上一轮的 `audio_url` 与读数串到这一轮。
你的实现如果也持有这类跨轮状态，注意两个清理位置：提交成功之后、离开对话室时。

## 四、验证建议

- 断点续答：开始一场引擎链路的面试，答两三轮（含被追问的轮次），退出再进入对话室，
  检查追问与每轮回答是否按序还原。
- 语音读数：用 `POST /uploads/audio/asr` 转写一段录音再提交答案，该场报告里应出现
  语速 / 停顿相关读数（此前这部分为空）。
- 遇到对不上的地方，把请求与响应原文发给 1 号，对着两边日志查。
