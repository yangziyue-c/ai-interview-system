# 致 P4（前端）同学的工作汇报

> 来自 P1（后端）。本文档汇总与前端对接相关的后端最新变化。
> **重点：岗位相关接口有变化，请务必在开发前阅读。**

## 一、最新变化：岗位大厅改为读后端接口（jobs.json 方案作废）

后端新增岗位接口，**前端不再使用静态 `public/jobs.json`**：

```
GET /api/v1/positions        （需登录，携带 Authorization: Bearer <token>）
```

```json
{ "code": 0, "message": "ok", "data": [
  { "code": "backend", "name": "后端开发工程师", "description": "……",
    "tech_stack": ["Java", "Python", "MySQL", "Redis", "Spring Boot"],
    "focus": ["数据结构与算法", "数据库", "并发编程", "分布式系统"] },
  { "code": "frontend", "name": "前端开发工程师", "description": "……",
    "tech_stack": ["HTML/CSS", "JavaScript", "TypeScript", "Vue3", "React"],
    "focus": ["CSS 布局", "JavaScript 核心", "前端框架", "性能优化"] }
] }
```

**三条硬性约定**：

1. **不得硬编码岗位列表**。岗位大厅展示本接口返回的数据；岗位后续可能新增/调整
   （后端预留 5 个岗位位，当前已开放 backend / frontend / test_engineer 三个）；
2. 注册的 `target_position` 与开始面试的 `position` 必须传本接口返回的 `code`；
3. 岗位中文名→code 映射由 `name` 字段天然提供；历史列表中的 `position` 字段
   也是 code，展示中文名时用岗位接口返回的映射（可进大厅时一次性缓存）。

## 二、此前交接文档已同步更新

[FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md)（接口勘误与补充说明）已同步岗位变化，
**开发时请以 [API.md](API.md) 为唯一权威**。要点回顾：

- 统一前缀 `/api/v1`，响应结构 `{ code, message, data }`，`code === 0` 成功；
- 提交回答是**普通 JSON**（非 SSE），按响应 `data.finished` 判断面试是否结束；
- 面试标识是**整数 `interview.id`**（非字符串 sessionId）；
- 语音：浏览器 Web Speech API 转写 + MediaRecorder 录 webm 上传 `/uploads/audio`；
- 报告雷达图 **4 个维度**（技术/逻辑/表达/岗位匹配度）；成长曲线调 `/reports/growth`；
- `code: 40100` 时清除 token 并跳转登录页；
- 进行中面试（`status: "in_progress"`）可在历史列表点击继续作答
  （`GET /interviews/{id}` 恢复问答记录）。

## 三、当前接口速查（完整 14 个）

| 用途 | 方法 + 路径 | 鉴权 |
|---|---|---|
| 注册（自动登录，含岗位选择） | `POST /auth/register` | 否 |
| 登录 | `POST /auth/login` | 否 |
| 当前用户信息 | `GET /auth/me` | 是 |
| **岗位列表（岗位大厅）** | **`GET /positions`** | 是 |
| 开始面试 | `POST /interviews`，body `{"position": "<岗位 code>"}` | 是 |
| 历史面试列表（附分数） | `GET /interviews` | 是 |
| 面试详情（恢复会话） | `GET /interviews/{interview_id}` | 是 |
| 提交答案获取下一题 | `POST /interviews/{interview_id}/answers` | 是 |
| 主动结束面试 | `POST /interviews/{interview_id}/finish` | 是 |
| 上传录音 | `POST /uploads/audio`（multipart，file 字段） | 是 |
| 评估报告详情 | `GET /reports/{interview_id}` | 是 |
| 最近一次面试建议 | `GET /reports/latest` | 是 |
| 能力成长曲线 | `GET /reports/growth` | 是 |

## 四、联调注意事项

1. 后端 `cd backend && 双击 start.bat`，Swagger：http://localhost:8001/docs ；
2. CORS 已全开，Vite dev server（5173）直连 8001，无需代理；
3. 演示模式：`npm run build` 后把 `dist/` 复制到 `backend/static/`，同端口无跨域；
4. 每次开工前先 `git pull` 并核对 API.md——后端若有调整会同步更新文档。
