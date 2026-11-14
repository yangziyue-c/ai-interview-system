# 致 P4：前端对接总览（2026-11-08）

这份文档汇总当前前端需要知道的状态与变更。字段细节以 `docs/API.md` 为准，这里只写「改了什么、去哪里看、怎么验收」。

---

## 一、代码位置与启动方式

| 项目 | 位置 | 说明 |
| :--- | :--- | :--- |
| 正式前端 | `frontend/ai-interview-front/` | Vue 3 + Vite，当前已合入 main |
| 开发调试 | `npm run dev` | 默认 5173，接口指向 8001 |
| 生产构建 | `npm run build` | 产物在 `dist/`，需要拷到 `backend/static/` |
| 演示前端 | `frontend_test/` | P1 维护，`start.bat` 拉起到 5273，不是正式前端 |
| 后端启动 | `backend/start.bat` | 8001 主后端、8002 评估、8003 RAG、5273 演示前端；8005 可选 |

正式前端的构建产物目前已经放在 `backend/static/`，访问 `http://localhost:8001` 看到的是正式前端。前端代码再改后，要重新构建并覆盖 `backend/static/`，否则 8001 仍是旧页面。

---

## 二、最新接口变更

### 2.1 设置接口新增 `career_anchor_result`

`GET /settings` 的返回多了 `career_anchor_result`，用来判断用户是否做过岗位倾向速测。

- 值为 `null`：没测过。
- 值非 `null`：测过，可以直接展示上次推荐，并给出「重新测一次」入口。

结构：

```json
{
  "position": "backend",
  "name": "后端开发工程师",
  "index": 90,
  "consistency_percent": 88,
  "confidence": "高",
  "tested_at": "2026-11-08T15:30:00"
}
```

该字段只读，`PUT /settings` 传了也不会生效。每次重新提交速测会覆盖为最新一次。换设备登录仍能读到；localStorage 可以留作离线兜底，但不要作为唯一来源。

### 2.2 岗位倾向速测改为后端计分

接口：

```
GET  /career-anchor/questions
POST /career-anchor/submit   { "answers": [5, 4, 3, ...] }
```

`answers` 正好 20 项，每项 1~5，顺序与题目接口一致。题目、计分、结果文案都在后端，前端只负责答题与展示。完整请求与返回示例见 `REPORT_TO_P4_CAREER_ANCHOR_API.md`。

### 2.3 四项待接功能

| 功能 | 后端状态 | 前端还差什么 |
| :--- | :--- | :--- |
| 体态数据落库 | `POST /body-language/analyze` 已支持 `interview_id` + `round` | 调用时补上当前面试 ID 与轮次 |
| 设置面板 | `GET /settings`、`PUT /settings` 已可用 | `SettingsCard.vue` 接上 6 项偏好 |
| 报告页表达分析 | 报告接口已返回 `expression_analysis` | `ReportPage.vue` 增加模块 |
| 报告页示范作答 | `POST /interviews/{id}/qa/{qa_id}/sample-answer` 已可用 | 增加按钮与弹窗 |

详细改法、空态处理和验收标准见 `REPORT_TO_P4_PENDING_ITEMS.md`。

---

## 三、离线版对前端的影响

5 号合入了无大模型离线版，由 `.env` 的 `OFFLINE_MODE` 控制，默认 `False`，正常演示不受影响。设为 `1` 时：

| 能力 | 离线版行为 | 前端建议 |
| :--- | :--- | :--- |
| 面试链路 | 走原链路，7 轮制 | 轮数从 `GET /config` 读，不要硬编码 |
| 文字作答 | 正常 | 无需改动 |
| 语音转写 | 返回 503 | 隐藏录音入口或提示「离线版请文字作答」 |
| 面试官朗读 | 返回 503 | 关闭自动朗读 |
| 摄像头体态 | 返回 503 | 隐藏体态开关 |
| 示范作答 | 返回 503 | 提示「离线版不可用」 |
| 成长档案 | `available: false`，带 `notice` | 直接展示 notice，不画空图 |
| 职业速测、设置、五维报告、学习计划 | 正常 | 无需改动 |

前端不需要判断 `OFFLINE_MODE` 本身，按接口返回的 503 和 `available: false` 做降级即可。

---

## 四、文档索引

| 内容 | 文档 |
| :--- | :--- |
| 接口字段权威 | `docs/API.md` |
| 四项待接功能 | `docs/reports/REPORT_TO_P4_PENDING_ITEMS.md` |
| 职业速测请求与返回示例 | `docs/reports/REPORT_TO_P4_CAREER_ANCHOR_API.md` |
| 四项功能的前端动作说明 | `docs/reports/REPORT_TO_P4_FINAL_FEATURES.md` |
| 引擎链路的页面与接口映射 | `docs/reports/REPORT_TO_P4_ENGINE_API_MAPPING.md` |

---

## 五、联调验收清单

- 设置：`GET /settings` 能读到 6 项偏好与 `career_anchor_result`；`PUT` 后刷新仍生效。
- 速测：20 条提交成功，结果页展示推荐岗位、指数、置信度；重新提交会覆盖。
- 体态：调用分析时带 `interview_id` 与 `round`，响应 `stored: true`；报告 `body.available` 为 `true`。
- 报告表达分析：有语音时显示语速与停顿；纯文字时显示 `notice`，不显示 0。
- 示范作答：首次生成有加载态，二次命中缓存；题库外题显示提示，503 提示稍后再试。
- 离线版：临时设 `OFFLINE_MODE=1`，确认语音、朗读、体态、示范作答按上表降级，文字面试与报告正常。
