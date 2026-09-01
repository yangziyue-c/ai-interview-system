# 前端交接文档：接口勘误与后端补充说明

> 致 P4 前端同学：你之前提交的 `docs/frontend-spec.md` 中的**页面设计部分可以保留**，
> 但**接口部分与实际后端已完成的代码存在大量不匹配**，直接照其开发将完全调不通接口。
> 本文档列出全部差异与正确接口，并已针对你的页面需求对后端做了补充。
> 联调以 **[API.md](API.md) 为准**，本文档为勘误说明。

---

## 一、后端本次新增/变更的内容（为满足你的页面需求）

### 1. 用户增加「学号」字段（个人中心展示用）

- 注册接口 `POST /api/v1/auth/register` 请求体新增可选字段：

```json
{
  "username": "zhangsan",
  "password": "123456",
  "nickname": "张三",
  "student_id": "20260001",   // 新增，可选
  "target_position": "backend"
}
```

- 登录响应 / `GET /api/v1/auth/me` 的 `user` 对象新增 `student_id` 字段（未填时为 `null`）。
- **头像**：后端未提供头像字段与上传，建议前端用昵称首字母生成圆形头像占位。

### 2. 历史面试列表附带综合得分

`GET /api/v1/interviews` 每项新增 `total_score` 字段（浮点，如 `84.5`）；
进行中或未出报告的面试该项为 `null`。个人中心历史列表**不再需要逐条请求报告接口拿分数**。

### 3. 新增「最近一次面试建议」接口（个人中心下半部分）

```
GET /api/v1/reports/latest
```

```json
{ "code": 0, "message": "ok", "data": {
  "interview_id": 3,
  "position": "backend",
  "finished_at": "2026-08-30T21:00:00",
  "total_score": 84.5,
  "suggestions": ["继续深挖技术原理……", "多进行限时模拟面试……"]
} }
```

从未完成过面试时 `data` 为 `null`（前端显示"暂无建议"即可）。

---

## 二、frontend-spec.md 错误清单与修正对照

### 🔴 致命错误（不修改无法联调）

| # | spec 中写的 | 后端实际 | 修正方法 |
|---|---|---|---|
| 1 | 提交回答是 **SSE 流式**（`type: "delta"/"end"`） | 普通 JSON 响应，**无 SSE** | 改为普通 POST，按 `finished` 字段判断是否结束（见下方流程） |
| 2 | `POST /api/asr/recognize` 语音转文字接口（3 号） | **该接口不存在** | 语音转写改用浏览器 **Web Speech API**（免费、实时），转写文本填入 `answer`；或与后端另行协商新增 ASR 接口 |
| 3 | 所有路径缺 `/api/v1` 前缀且路由名错误 | 统一前缀 `/api/v1`，见下方对照表 | 全部按右侧修正 |
| 4 | 会话标识 `sessionId`（字符串） | `interview.id`（**整数**，如 1、2） | 全部改用整数 id |

### 🟡 各接口字段对照

**登录** `POST /api/v1/auth/login`

| spec 写的响应字段 | 实际字段 |
|---|---|
| `data.userId` | `data.user.id`（整数） |
| `data.realName` | `data.user.nickname` |
| `data.token` | `data.access_token`（另有 `token_type: "bearer"`） |

> spec 还缺了**注册接口**（`POST /api/v1/auth/register`，见本文档第一部分）与登录/注册页设计。
> 系统没有内置账号，不注册无法登录，必须补充。

**开始面试** `POST /api/v1/interviews`

| spec | 实际 |
|---|---|
| 请求 `{"jobId": "java-backend"}` | 请求 `{"position": "backend"}`，枚举**只有** `backend` / `frontend` |
| 响应 `{sessionId, firstQuestion}` | 响应 `data.question`（第一题）+ `data.interview`（含 `id`、`current_round`、`status`） |

> 注意：同一用户已有进行中面试时返回 409（`code: 40900`），前端需提示"你有进行中的面试"，
> 并可引导用户通过历史列表里 `status: "in_progress"` 的记录继续作答（调详情接口恢复对话）。

**提交回答** `POST /api/v1/interviews/{interview_id}/answers`

| spec | 实际 |
|---|---|
| 请求 `{sessionId, answerType, content}` | 请求 `{"answer": "回答文本（必填）", "audio_url": "/uploads/xx.webm"（可选）}` |
| SSE 流 | 响应：`data.finished === false` → 展示 `data.next_question`；`true` → `data.report` 为报告，跳转报告页 |

语音流程（正确版）：

```
按住说话 → 松开 → ① 浏览器 Web Speech API 转写为文本填入输入框（可手动修改）
                → ② 录音文件上传 POST /api/v1/uploads/audio（multipart，file 字段）
                      返回 data.url 如 "/uploads/12_ab3f9c2d.webm"
                → ③ 提交答案：answer=转写文本，audio_url=data.url
```

**历史列表** `GET /api/v1/interviews`

- spec 写的 `jobName/score/date` 不存在。实际字段：`id / position / status / current_round / created_at / started_at / finished_at / total_score`。
- `position` 是枚举（`"backend"`/`"frontend"`），显示中文"Java 后端开发"需前端自行映射（建议 jobs.json 同时提供映射）。
- 日期为 ISO 8601（如 `2026-08-30T10:00:00`），前端格式化后再显示。

**报告详情** `GET /api/v1/reports/{interview_id}`（RESTful 路径参数，**不是** query `?sessionId=`）

| spec 写的字段 | 实际字段 |
|---|---|
| `score` | `total_score`（浮点，如 84.5） |
| `radarLabels` 5 维 / `radarValues` | **4 个维度**：`tech_score` 技术 / `logic_score` 逻辑 / `expression_score` 表达 / `match_score` 岗位匹配度（删掉"应变能力"） |
| `suggestions` | ✓ 存在（字符串数组） |
| `trend` | **不存在**。成长曲线调独立接口 `GET /api/v1/reports/growth`（按时间升序的得分序列） |
| 未提及 | `summary` 综合评语、`strengths` 优点、`weaknesses` 缺点（都是前端可展示的现成字段） |

**岗位静态数据**（spec 第三部分）

- 后端**没有** `/api/job/list` 接口 → 采用 spec 中「静态 JSON 置于 `public/jobs.json`」的方案。
- `jobId` 值必须改为 `"backend"` / `"frontend"`（要原样传给开始面试接口的 `position`）。

**语音格式**

- spec 写「WAV 16000Hz」不必要且给自己挖坑（浏览器 MediaRecorder 原生输出 webm/opus，录 WAV 需手动转码）。
- 后端上传接口直接支持 `mp3 / wav / webm / m4a / ogg / aac / flac`（≤20MB），**直接传 webm** 即可。

**结束面试**（spec 遗漏，务必补充）

```
POST /api/v1/interviews/{interview_id}/finish
```

响应 `data.report` 即评估报告。对话室内需提供「结束面试」按钮。

### 🟢 已确认无需担心的项

- **CORS**：后端已 `allow_origins: ["*"]`，本地 `http://localhost:5173` 可直接访问，无需代理。
- **响应约定**：`code === 0` 成功 ✓（与 spec 一致）；`message` 为提示文案；错误码见 API.md。
- **鉴权**：`Authorization: Bearer {token}` 存 localStorage ✓（与 spec 一致）。
  - 建议：拦截器收到 `code: 40100`（HTTP 401）时清除 token 并跳转登录页。
- **顶部状态**：`data.interview.current_round` 可直接显示"第 N 题"。

---

## 三、正确接口速查表（完整清单）

Base URL：`http://localhost:8001/api/v1`（联调期）｜统一响应 `{ code, message, data }`

| 用途 | 方法 + 路径 | 鉴权 |
|---|---|---|
| 注册（自动登录） | `POST /auth/register` | 否 |
| 登录 | `POST /auth/login` | 否 |
| 当前用户信息 | `GET /auth/me` | 是 |
| 开始面试 | `POST /interviews`，body `{"position": "backend"}` | 是 |
| 历史面试列表（附分数） | `GET /interviews` | 是 |
| 面试详情（含全部问答，恢复会话用） | `GET /interviews/{interview_id}` | 是 |
| 提交答案并获取下一题 | `POST /interviews/{interview_id}/answers`，body `{"answer", "audio_url"?}` | 是 |
| 主动结束面试 | `POST /interviews/{interview_id}/finish` | 是 |
| 上传录音 | `POST /uploads/audio`（multipart，file 字段） | 是 |
| 评估报告详情 | `GET /reports/{interview_id}` | 是 |
| 最近一次面试建议 | `GET /reports/latest` | 是 |
| 能力成长曲线 | `GET /reports/growth` | 是 |

完整请求/响应示例与错误码定义见 **[API.md](API.md)**，在线调试 http://localhost:8001/docs 。

---

## 四、可直接发给前端 AI 的提示词

### 提示词 A：让 AI 修正 frontend-spec.md

复制以下内容发给你的 AI 编程助手（Claude Code / Cursor / ChatGPT 等），并附带三份文档：
`docs/frontend-spec.md`、`docs/FRONTEND_HANDOFF.md`、`docs/API.md`：

```text
你是一名前端架构师。我们正在开发"AI 模拟面试系统"的前端（Vue3 技术栈），
项目后端（FastAPI）已完成。现有三份文档，请全部阅读：

1. docs/frontend-spec.md —— 前端需求与接口规格（初稿，接口部分已过时、存在错误）
2. docs/FRONTEND_HANDOFF.md —— 后端团队出具的接口勘误与补充说明（权威依据）
3. docs/API.md —— 后端实际接口文档（唯一权威，所有路径/字段/响应结构以此为准）

任务：修订 frontend-spec.md，输出修订后的完整版本，要求：

1. 页面设计部分（底部 Tab 栏、岗位大厅、面试对话室、个人中心）保留原设计；
2. 接口部分全部按 FRONTEND_HANDOFF.md 与 API.md 重写，硬性约束：
   - 所有接口以 /api/v1 为前缀，路径、方法、字段名与 API.md 完全一致，不得自创；
   - 提交回答接口是普通 JSON 请求，不是 SSE，按响应中 finished 字段判断面试是否结束；
   - 不存在语音转文字后端接口，语音输入方案为：浏览器 Web Speech API 转写文本 + 录音
     上传 /api/v1/uploads/audio 后把返回的 url 填入 audio_url 字段一并提交；
   - 面试会话标识为整数 interview.id，不使用字符串 sessionId；
   - 岗位枚举只有 backend / frontend，静态岗位数据 jobId 必须使用这两个值；
   - 补充原规格缺失的内容：注册接口与注册/登录页、主动结束面试接口、
     40100 错误码自动跳转登录、进行中面试（status=in_progress）的恢复入口；
   - 报告雷达图改为 4 个维度：tech_score / logic_score / expression_score / match_score；
     成长曲线数据来自 GET /reports/growth；
3. 在修订版末尾附一节"相对原规格的修改清单"，逐条列出改了什么、为什么。

只输出修订后的 frontend-spec.md 完整内容，不要输出无关解释。
```

### 提示词 B：让 AI 按修订后规格直接开发前端

（在你完成提示词 A、拿到修订版规格之后使用）

```text
你是资深前端工程师。请根据以下两份文档开发"AI 模拟面试系统"的前端：

1. <修订后的 frontend-spec.md 全文或文件路径> —— 页面需求与接口规格
2. docs/API.md —— 后端接口权威文档

技术要求：
- Vue3 + Vite + TypeScript，组件化开发，代码放 frontend/ 目录；
- 用 axios（或 fetch 封装）统一请求层：BaseURL http://localhost:8001/api/v1，
  请求拦截器自动附加 Authorization: Bearer {token}（token 存 localStorage），
  响应拦截器统一处理 { code, message, data } 结构，code===40100 时清除 token 并跳登录页；
- 页面：登录/注册页（注册含目标岗位选择 backend/frontend、可选学号）、
  岗位大厅（读 public/jobs.json）、岗位详情、面试对话室（文本+按住说话语音、
  语音用 Web Speech API 转写、录音用 MediaRecorder 录 webm 上传 /api/v1/uploads/audio）、
  报告页（4 维雷达图 + 总分 + 评语/优缺点/建议 + 成长曲线折线图）、
  个人中心（用户信息 + 历史列表带分数 + 最近建议）；
- 面试对话室关键流程：开始面试拿 interview.id → 提交答案后按 finished 判断
  显示下一题或跳转报告；提供"结束面试"按钮；历史列表中 status=in_progress 的
  记录可点击继续作答（用 GET /interviews/{id} 恢复问答记录）；
- 岗位中文名、技术栈、考察重点均从 public/jobs.json 读取，jobId 字段值与后端
  position 枚举（backend/frontend）一致；
- UI 要求：移动端优先的底部 Tab 栏布局，面试对话室采用聊天界面（AI 气泡靠左、
  用户气泡靠右），样式现代简洁，可直接用于课堂演示。

完成后请自检：对照 API.md 逐条确认每个请求的方法、路径、请求体字段、响应字段
完全一致，并在回复中列出"接口自检清单"。
```

---

## 五、联调注意事项

1. **启动顺序**：后端 `cd backend && 双击 start.bat`，访问 http://localhost:8001/docs 确认 Swagger 可打开。
2. **跨域**：后端 CORS 已全开，Vite dev server（5173 端口）直连 8001 即可，无需配代理。
3. **演示模式**：`npm run build` 后把 `dist/` 内容复制到 `backend/static/`，同端口访问 http://localhost:8001 ，无跨域。
4. **错误处理**：后端保证任何异常都返回 `{ code, message, data }` 统一结构，HTTP 状态码与 code 对应（400→40000、401→40100、409→40900 等），前端按 code 提示 message 文案即可。
5. **变更同步**：后端若有后续调整会同步更新 API.md，请每次开工前先 `git pull` 并核对 API.md。
