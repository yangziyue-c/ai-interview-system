# TTS / 体态接口的代理情况答复（给 4 号）

> 2026-10-03。回答你提的两个问题，其中体态响应有一处字段纠正；文末附链路切换的提醒。
> 接口权威仍是 `docs/API.md`，逐条细则在 `REPORT_TO_P4_A11_ENGINE.md`。

## 一、TTS：代理了，但只支持一种模式

**前端调这个**：

```
POST /api/v1/uploads/audio/tts
{ "text": "要朗读的文本（≤800 字）", "voice": "" }
```

返回**本站**地址，直接 `<audio src>` 播放：

```json
{ "code": 0, "message": "朗读音频已生成", "data": {
  "url": "/uploads/tts/12_ab3f9c2d.wav",
  "content_type": "audio/wav", "bytes": 84320, "chars": 18 } }
```

三种引擎模式，本项目只代理第一种：

| 引擎模式 | 本项目 | 说明 |
| :--- | :--- | :--- |
| 默认档（二进制） | ✅ **代理** | 后端取音频 → 落盘本站 → 回本站 URL |
| `?stream=1`（SSE 流式） | ❌ 没有 | 目前没有 SSE 透传；要「边合成边播」需新加一条转发，提需求即可 |
| `?direct=1`（回引擎自己的 URL） | ❌ **刻意不用** | 那会把 8005 的地址交到前端手里，违反「前端只认 8001、地址一律由后端发」的项目口径 |

失败形态：引擎不可用时返 **503（50300）**，**不会给空音频**——遇到就静默降级（不播报），别去播放空文件。`text` 超 800 字会在这层直接 400 拒掉；`voice` 留空用引擎默认音色。

## 二、体态：请求逐字段一致，响应原样透传（含一处纠正）

**前端调这个**：

```
POST /api/v1/body-language/analyze
{ "frames": [ { "timestamp_ms": 0, "landmarks": [ { "x": 0.51, "y": 0.32 } ] } ] }
```

- 帧数 **1~600**；`landmarks` 里 `x / y` 必填，`z / visibility / presence` 可选（默认 0 / 1 / 0）
- 请求格式与 5 号**逐字段一致**（本端 schema 与引擎 `BodyLanguageReq` 对齐，字段名与取值都没另立一套）
- **只收数字关键点**，不收图片 / 视频 / 音频——这条边界后端不会放宽

响应是统一壳 + **引擎原样的 data**（逐字段透传，不做任何加工）：

```json
{ "code": 0, "message": "分析完成", "data": { …与引擎返回逐字段相同… } }
```

⚠️ **一处要纠正**：`data` 的字段**随分支变化**，你和 5 号列的那套只覆盖了「有分」的情况——

| 分支 | `data` 的字段 |
| :--- | :--- |
| 有分（`quality_status="ready"`） | 共同六字段 + `feedback` + `notes` |
| 证据不足（`available=true`、`score=null`） | 共同六字段 + `notes`，**没有 `feedback`** |
| 完全没姿态（`available=false`） | 只有共同六字段 |

共同六字段：`available / score / confidence / quality_status / score_breakdown / metrics`。

**前端处理建议**：按 `available` 与 `score` 分支，**别假设 `feedback` 一定存在**；`score=null` 不是失败，是「证据不够、不给分」——UI 上按「暂时测不到」提示，**不要补 0**（那等于把「镜头坏了」判成「考生体态差」）。

## 三、附：引擎链路已切到本机，前端只需跟着变一件事

主后端的引擎链路已开启（引擎跑在 1 号本机 `127.0.0.1:8005`）。对前端的影响只有一个：

- **`total_rounds` 从 7 变成 10**（引擎链路固定 10 题制）——继续从 `GET /api/v1/config` 拿即可，别写死；同接口的 `engine` 字段会返回 `"a11"`。

其余契约不变：追问不推进题号（`current_round` 保持不动是**正确**的）、提交答案仍是普通 JSON（不是 SSE）。`50300` 的处理方式见 `REPORT_TO_P4_A11_ENGINE.md` §2.3。
