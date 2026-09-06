# 致 P4（前端）同学：页面需求与接口权威说明

> 来自 P1（后端）。本文档由 `frontend-spec.md`（页面需求部分）+ `FRONTEND_HANDOFF.md`
> （接口勘误与权威）**合并而成（2026-09-06）**——原 frontend-spec 的接口部分
> 与后端实际实现大量不符，已作废；开发/联调以本文档第 2 节与 [API.md](../API.md)
> 为唯一权威，页面设计以第 1 节为准。

---

## 1. 页面需求（原 frontend-spec.md 有效部分）

采用 **底部固定 Tab 栏** 布局，共 2 个 Tab：**模拟面试** 与 **个人中心**。
技术栈：Vue（网页端开发，后续可打包桌面/移动应用）。

### Tab1：模拟面试

#### ① 岗位大厅
- 展示岗位卡片（数据来自 `GET /positions`，不得硬编码）。
- 点击卡片不直接进对话，弹出**岗位详情浮层**或跳转**岗位详情页**。

#### ② 岗位详情页
- 展示：岗位简介 / 技术栈要求 / 面试考察重点。
- 底部提供显眼的「开始面试」按钮。

#### ③ 面试对话室（核心页面）
1. **顶部**：面试状态（如「面试中」「第 N 题」，用 `data.interview.current_round`）。
2. **中间**：聊天区域——AI 气泡靠左、用户回答气泡靠右。
3. **底部输入区**：左侧语音录制按钮（按住说话）、右侧文本输入框 + 发送按钮，
   语音/文本随时切换。

### Tab2：个人中心

1. **上半部分**：头像（后端无头像字段，用昵称首字母占位）、昵称、学号。
2. **中间部分**：历史面试列表（按时间倒序；岗位名称 + 综合得分 + 日期，点击进完整报告）。
3. **下半部分**：最近一次 AI 改进建议（`GET /reports/latest`；无数据时显示"暂无建议"）。

---

## 2. 后端接口补充说明（为满足上述页面需求而新增/变更）

### 2.1 用户增加「学号」字段

- 注册 `POST /auth/register` 请求体新增可选字段 `student_id`；
- 登录响应 / `GET /auth/me` 的 `user` 对象含 `student_id`（未填为 `null`）。

### 2.2 历史列表附带综合得分

`GET /interviews` 每项含 `total_score`（浮点；进行中/未出报告为 `null`），
个人中心历史列表**无需逐条请求报告接口拿分数**。

### 2.3 最近一次面试建议

```
GET /reports/latest
```

返回最近一场已结束面试的得分与建议摘要；从未完成面试时 `data` 为 `null`。

### 2.4 岗位列表（岗位大厅用，取代 jobs.json 方案）

```
GET /positions
```

岗位由后端数据库动态维护（当前已开放 backend / frontend / test_engineer 三个，
预留 5 个岗位位，清单可能调整）。**前端不得硬编码岗位列表**：岗位大厅展示本接口
返回数据；注册的 `target_position` 与开始面试的 `position` 必须传返回的 `code`；
岗位中文名由 `name` 字段天然提供。

### 2.5 报告评分 5 维（2026-09-04 起，源自《评估维度.csv》）

| 维度字段 | 中文名 |
| :--- | :--- |
| `tech_score` | 技术水平 |
| `logic_score` | 逻辑思维 |
| `expression_score` | 沟通表达 |
| `adaptability_score` | 应变能力 |
| `match_score` | 岗位匹配度 |

报告详情与成长曲线均返回 5 维分数，雷达图按 **5 轴**渲染。前端无需计算总分，
直接展示 `total_score`。

---

## 3. 前端常见错误对照（原 frontend-spec 接口部分已作废，此表防再犯）

### 🔴 致命错误

| # | 旧 spec 写法 | 后端实际 | 修正 |
|---|---|---|---|
| 1 | 提交回答是 **SSE 流式** | 普通 JSON 响应，**无 SSE** | 按 `finished` 字段判断是否结束 |
| 2 | `POST /api/asr/recognize` 语音转文字接口 | **不存在** | 浏览器 **Web Speech API** 转写，文本填入 `answer` |
| 3 | 路径缺 `/api/v1` 前缀、路由名错误 | 统一前缀 `/api/v1` | 全部按右侧修正 |
| 4 | 会话标识 `sessionId`（字符串） | `interview.id`（**整数**） | 全部改用整数 id |

### 🟡 字段对照

**登录** `POST /api/v1/auth/login`：旧 `data.userId`→`data.user.id`（整数）、
`realName`→`user.nickname`、`token`→`data.access_token`。系统无内置账号，
**必须补充注册接口**（`POST /auth/register`）与注册/登录页。

**开始面试** `POST /api/v1/interviews`：旧 `{"jobId":"java-backend"}`→
`{"position":"backend"}`（岗位接口返回的 code）；旧 `{sessionId, firstQuestion}`→
`data.question` + `data.interview`（含 `id`/`current_round`/`status`）。
> 已有进行中面试时返回 409（code 40900），前端提示「你有进行中的面试」，
> 可引导从历史列表 `status:"in_progress"` 记录继续作答（详情接口恢复对话）。

**提交回答** `POST /api/v1/interviews/{interview_id}/answers`：旧 SSE 流 →
普通 JSON；请求 `{"answer": "文本（必填）", "audio_url": "/uploads/xx.webm"（可选）}`。
正确语音流程：

```
按住说话 → 松开 → ① Web Speech API 转写文本填入输入框（可手动改）
                  → ② 录音上传 POST /api/v1/uploads/audio（multipart, file 字段）拿 data.url
                  → ③ 提交答案：answer=转写文本, audio_url=data.url
```

**历史列表** `GET /api/v1/interviews`：无 `jobName/score/date`。实际字段
`id/position/status/current_round/created_at/started_at/finished_at/total_score`；
`position` 是 code，显示中文名用岗位接口映射；日期 ISO 8601 需前端格式化。

**报告详情** `GET /api/v1/reports/{interview_id}`（RESTful 路径参数）：旧 `score`→
`total_score`；雷达图 5 维（见 2.5）；旧 `trend` 不存在→成长曲线调
`GET /reports/growth`；另有 `summary`/`strengths`/`weaknesses` 可直接展示。

**岗位数据**：放弃 `public/jobs.json` 静态方案，一律 `GET /positions`。

**语音格式**：无需 WAV@16000Hz（浏览器 MediaRecorder 原生 webm/opus）。
后端支持 `mp3/wav/webm/m4a/ogg/aac/flac`（≤20MB），**直接传 webm**。

**结束面试（旧 spec 遗漏）**：

```
POST /api/v1/interviews/{interview_id}/finish
```

响应 `data.report` 即评估报告；对话室需提供「结束面试」按钮。

### 🟢 无需担心项

- **CORS**：后端已 `allow_origins: ["*"]`，`http://localhost:5173` 直连即可，无需代理。
- **响应约定**：`code === 0` 成功，错误码见 API.md；`data.interview.current_round` 显示"第 N 题"。
- **鉴权**：`Authorization: Bearer {token}` 存 localStorage；拦截器收到 40100
  （HTTP 401）清除 token 跳登录页。

---

## 4. 正确接口速查表

Base URL：`http://localhost:8001/api/v1`（联调期）｜统一响应 `{ code, message, data }`

| 用途 | 方法 + 路径 | 鉴权 |
|---|---|---|
| 注册（自动登录） | `POST /auth/register` | 否 |
| 登录 | `POST /auth/login` | 否 |
| 当前用户信息 | `GET /auth/me` | 是 |
| 岗位列表（岗位大厅） | `GET /positions` | 是 |
| 开始面试 | `POST /interviews`，body `{"position": "<岗位接口返回的 code>"}` | 是 |
| 历史面试列表（附分数） | `GET /interviews` | 是 |
| 面试详情（恢复会话） | `GET /interviews/{interview_id}` | 是 |
| 提交答案并获取下一题 | `POST /interviews/{interview_id}/answers`，body `{"answer", "audio_url"?}` | 是 |
| 主动结束面试 | `POST /interviews/{interview_id}/finish` | 是 |
| 上传录音 | `POST /uploads/audio`（multipart，file 字段） | 是 |
| 评估报告详情 | `GET /reports/{interview_id}` | 是 |
| 最近一次面试建议 | `GET /reports/latest` | 是 |
| 能力成长曲线 | `GET /reports/growth` | 是 |

完整请求/响应示例与错误码见 [API.md](../API.md)；在线调试 http://localhost:8001/docs 。

---

## 5. 可直接发给前端 AI 的提示词

> 本文档已含页面需求 + 接口权威，无需再附带旧 spec。

```text
你是资深前端工程师。请根据以下文档开发"AI 模拟面试系统"的前端：

1. docs/reports/REPORT_TO_P4.md —— 页面需求与接口说明（权威）
2. docs/API.md —— 后端接口权威文档（路径/字段以它为准）

技术要求：
- Vue3 + Vite + TypeScript，代码放 frontend/ 目录；
- axios（或 fetch 封装）统一请求层：BaseURL http://localhost:8001/api/v1，
  拦截器自动附加 Authorization: Bearer {token}（存 localStorage），
  响应统一处理 { code, message, data }，code===40100 清 token 跳登录页；
- 页面：登录/注册页（注册含目标岗位选择——选项来自 GET /positions、可选学号）、
  岗位大厅（读 GET /positions）、岗位详情、面试对话室（文本+按住说话语音：
  Web Speech API 转写 + MediaRecorder 录 webm 上传 /api/v1/uploads/audio）、
  报告页（5 维雷达图 技术/逻辑/表达/应变/匹配 + 总分 + 评语/优缺点/建议 +
  成长曲线折线图）、个人中心（用户信息 + 历史列表带分数 + 最近建议）；
- 面试对话室关键流程：开始面试拿 interview.id → 提交答案后按 finished 判断
  显示下一题或跳报告；提供"结束面试"按钮；历史列表 status=in_progress 可继续作答；
- 岗位名称/简介/技术栈/考察重点均从 GET /positions 读取，position 原样传 code；
- UI：移动端优先底部 Tab 栏，面试对话室聊天界面（AI 气泡靠左、用户气泡靠右），
  样式现代简洁，可直接用于课堂演示。

完成后自检：对照 docs/API.md 逐条核对每个请求的方法/路径/请求体字段/响应字段，
并在回复中列出"接口自检清单"。
```

---

## 6. 联调注意事项

1. **启动顺序**：后端 `cd backend && 双击 start.bat`，访问 http://localhost:8001/docs 确认 Swagger。
2. **跨域**：CORS 已全开，Vite dev（5173）直连 8001，无需代理。
3. **演示模式**：`npm run build` 后把 `dist/` 复制到 `backend/static/`，同端口无跨域。
4. **错误处理**：后端任何异常返回 `{ code, message, data }` 统一结构
   （400→40000、401→40100、409→40900 等），前端按 code 提示 message。
5. **变更同步**：后端调整会更新 API.md，每次开工前先 `git pull` 核对。
