# API 接口文档

- Base URL：`http://localhost:8001/api/v1`（内网穿透后为公网地址 + 相同路径）
- 在线调试：启动后访问 `http://localhost:8001/docs`（Swagger UI）
- 统一响应格式：

```json
{ "code": 0, "message": "ok", "data": { } }
```

| code | 含义 |
| :--- | :--- |
| 0 | 成功 |
| 40000 | 参数/业务规则错误 |
| 40100 | 未登录或 token 过期 |
| 40300 | 无权限 |
| 40400 | 资源不存在 |
| 40900 | 状态冲突（如对已结束的面试提交答案） |
| 50000 | 服务器内部错误 |

## 鉴权

除注册/登录外，所有接口需携带请求头：

```
Authorization: Bearer <access_token>
```

---

## 1. 认证

### 1.1 注册

```
POST /auth/register
```

```json
{
  "username": "zhangsan",
  "password": "123456",
  "nickname": "张三",
  "student_id": "20260001",       // 学号，可选
  "target_position": "backend"    // 目标岗位 code（见 2.1 岗位列表）
}
```

返回：

```json
{
  "code": 0, "message": "注册成功",
  "data": {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "user": {
      "id": 1,
      "username": "zhangsan",
      "nickname": "张三",
      "student_id": "20260001",
      "target_position": "backend",
      "created_at": "2026-09-01T10:00:00"
    }
  }
}
```

登录接口返回结构相同（`message` 为“登录成功”）；`GET /auth/me` 的 `data` 即上方的 `user` 对象。

### 1.2 登录

```
POST /auth/login          { "username": "zhangsan", "password": "123456" }
```

### 1.3 当前用户

```
GET /auth/me
```

---

## 2. 岗位

### 2.1 岗位列表（岗位大厅用）

```
GET /positions
```

> 岗位由后端数据库动态维护（预留 5 个岗位位，未开放的占位岗位不下发）。
> 前端**不得硬编码岗位列表**，注册/开始面试的 position 必须传本接口返回的 `code`。

```json
{ "code": 0, "message": "ok", "data": [
  {
    "code": "backend",
    "name": "后端开发工程师",
    "description": "负责服务端架构与业务逻辑开发，考察编程语言、数据库、并发与系统设计能力。",
    "tech_stack": ["Java", "Python", "MySQL", "Redis", "Spring Boot"],
    "focus": ["数据结构与算法", "数据库", "并发编程", "分布式系统"]
  },
  {
    "code": "frontend",
    "name": "前端开发工程师",
    "description": "……",
    "tech_stack": ["HTML/CSS", "JavaScript", "TypeScript", "Vue3", "React"],
    "focus": ["CSS 布局", "JavaScript 核心", "前端框架", "性能优化"]
  }
] }
```

---

## 3. 面试

### 3.1 开始面试

```
POST /interviews           { "position": "backend" }    // 岗位 code（见 2.1 岗位列表）
```

返回：会话信息（`status: "in_progress"`）+ 开场题 `question`。

> 同一用户同时只能有一场进行中的面试，否则返回 409。
> position 不存在或未开放时返回 400（`code: 40000`）。

### 3.2 我的面试列表

```
GET /interviews
```

按时间倒序，每项附带综合得分（`total_score`；未生成报告时为 `null`，如进行中/未结束的面试）：

```json
{ "code": 0, "message": "ok", "data": [
  { "id": 1, "position": "backend", "status": "finished", "current_round": 7,
    "created_at": "2026-08-30T10:00:00", "started_at": "...", "finished_at": "...",
    "total_score": 84.5 },
  { "id": 2, "position": "frontend", "status": "in_progress", "current_round": 2,
    "created_at": "2026-09-01T09:00:00", "started_at": "...", "finished_at": null,
    "total_score": null }
] }
```

### 3.3 面试详情（含全部问答）

```
GET /interviews/{interview_id}
```

返回 `data.qa_records`：`[{round, question, answer, audio_url}]`。

### 3.4 提交答案并获取下一题

```
POST /interviews/{interview_id}/answers
```

```json
{
  "answer": "我认为……（语音转写文本或手输文本）",
  "audio_url": "/uploads/12_ab3f9c2d.mp3"    // 可选，录音上传接口返回
}
```

返回：

```json
{
  "code": 0, "message": "ok",
  "data": {
    "finished": false,              // true 表示面试已结束（达轮次上限自动出报告）
    "interview": { "status": "in_progress", "current_round": 2, ... },
    "next_question": "能结合你做过的一个具体项目……",   // finished=false 时有
    "report": null                  // finished=true 时携带评估报告
  }
}
```

### 3.5 主动结束面试

```
POST /interviews/{interview_id}/finish
```

返回：`interview`（status=finished）+ `report`（评估报告）。

---

## 4. 报告

### 4.1 获取面试报告

```
GET /reports/{interview_id}
```

```json
{
  "code": 0, "message": "ok",
  "data": {
    "interview_id": 1,
    "total_score": 84.5,
    "tech_score": 88.0,          // 技术水平
    "logic_score": 83.0,         // 逻辑思维
    "expression_score": 80.0,    // 沟通表达
    "adaptability_score": 82.0,  // 应变能力
    "match_score": 87.0,         // 岗位匹配度
    "summary": "整体表现良好……",
    "strengths": ["回答内容充实……"],
    "weaknesses": ["个别问题可再深入……"],
    "suggestions": ["继续深挖技术原理……"],
    "created_at": "2026-08-25T21:00:00"
  }
}
```

> 评分维度 5 维（2026-09-04 起，源自团队《评估维度.csv》）：技术水平 / 逻辑思维 /
> 沟通表达 / 应变能力 / 岗位匹配度。`adaptability_score` 为新增字段，前端雷达图按 5 轴渲染。

### 4.2 最近一次面试的改进建议（个人中心用）

```
GET /reports/latest
```

返回最近一场已结束面试的得分与建议摘要；从未完成过面试时 `data` 为 `null`：

```json
{ "code": 0, "message": "ok", "data": {
  "interview_id": 3,
  "position": "backend",
  "finished_at": "2026-08-30T21:00:00",
  "total_score": 84.5,
  "suggestions": ["继续深挖技术原理……", "多进行限时模拟面试……"]
} }
```

### 4.3 能力成长曲线

```
GET /reports/growth
```

返回已结束面试的得分序列（按时间升序）：

```json
{ "code": 0, "message": "ok", "data": [
  { "interview_id": 1, "position": "backend", "finished_at": "...",
    "total_score": 76.0, "tech_score": 76.0, "logic_score": 74.0,
    "expression_score": 78.0, "adaptability_score": 75.0, "match_score": 77.0 },
  { "interview_id": 3, "position": "backend", "finished_at": "...",
    "total_score": 84.5, ... }
] }
```

---

## 5. 题库

题库数据来自 `questions` 表（由 `backend/scripts/import_question_bank.py` 从
`题库/*.xlsx` 导入，当前 3 岗位 × 150 题）。主要供后端开发 B（AI专项1）的
面试官对话逻辑（选题/追问）使用。

### 5.1 题库列表（过滤 + 分页）

```
GET /questions?position=backend&category=技术知识&difficulty=easy&stage=开场热身&q=HashMap&limit=20&offset=0
```

全部查询参数可选：

| 参数 | 说明 |
| :--- | :--- |
| position | 岗位 code（backend / frontend / test_engineer） |
| category | 大类：技术知识 / 场景与设计 / 编码与算法 / 项目深挖 / 行为面试 |
| difficulty | 难度：easy / medium / hard |
| stage | 面试阶段：开场热身 / 核心考察 / 深度考察 / 收尾交流 |
| q | 题干模糊搜索关键词 |
| limit / offset | 分页（limit 默认 20，最大 100） |

返回：

```json
{ "code": 0, "message": "ok", "data": {
  "total": 450,
  "items": [
    {
      "id": 1,
      "position_code": "backend",
      "question_no": "tech_001",
      "category": "技术知识",
      "sub_category": "Java基础",
      "difficulty": "easy",
      "question": "Java中==和equals()的区别是什么？",
      "soft_skill_tag": "",
      "score_points": "【basic 0.3】……【core 0.5】……【advanced 0.2】……",
      "follow_up_triggers": "【L1-触发追问】……【L2-深入追问】……【L3-极限追问】……【降级策略】……",
      "reference_answer": "完整参考答案……",
      "note": "高频考点，equals与hashCode契约是必追问点",
      "interview_stage": "开场热身",
      "stage_order": 1,
      "suggested_minutes": 3,
      "alternative_directions": "方向1：……方向2：……",
      "excellent_example": "优秀回答范例……"
    }
  ]
} }
```

> `question` 已剥离「【岗位软技能考察：X】」元信息（独立存于 `soft_skill_tag`），
> 可直接读给候选人。选题约定见 [REPORT_TO_P2.md](REPORT_TO_P2.md)。

### 5.2 题库详情

```
GET /questions/{question_id}
```

返回单题全量字段（结构同 5.1 的 item）。

---

## 6. 上传

### 6.1 上传面试录音

```
POST /uploads/audio        Content-Type: multipart/form-data
                           file: 录音文件（mp3/wav/webm/m4a/ogg/aac/flac，≤20MB）
```

返回：

```json
{ "code": 0, "message": "上传成功", "data": { "url": "/uploads/12_ab3f9c2d.mp3" } }
```

`url` 为相对路径，完整地址 = 当前服务地址 + url（如 `http://localhost:8001/uploads/12_ab3f9c2d.mp3`）。上传后可直接访问该 URL 播放/下载，提交答案时把 `url` 填入 `audio_url` 字段供 P3 语音识别评估。

---

## 7. 系统

### 7.1 健康检查

```
GET /health                { "code": 0, "message": "ok", "data": { "status": "healthy" } }
```

---

## 附录：P2 / P3 外部服务接入约定

在 `backend/.env` 中配置 URL 后自动生效；未配置或调用失败（含 15 秒超时）时后端自动降级为内置 Mock。

### P2：AI 面试官

```
POST {AI_INTERVIEWER_URL}/generate
```

```json
{
  "position": "backend",        // 岗位 code（由 GET /positions 动态下发）
  "round": 2,                   // 当前是第几题（1 开场题，2~7 追问）
  "is_follow_up": true,         // 是否为追问
  "history": [                  // 完整对话历史
    { "role": "interviewer", "content": "请先做个自我介绍……" },
    { "role": "candidate", "content": "我来自……" }
  ]
}
```

期望返回：

```json
{ "question": "你下一题的题目文本" }
```

### P3：AI 评估

面试结束时调用：

```
POST {AI_EVALUATOR_URL}/evaluate
```

```json
{
  "position": "backend",
  "qa_list": [
    { "round": 1, "question": "...", "answer": "...", "audio_url": "/uploads/xxx.mp3" }
  ]
}
```

期望返回（5 维评分）：

```json
{
  "total_score": 85.5,
  "tech_score": 88.0,          // 技术水平
  "logic_score": 83.0,         // 逻辑思维
  "expression_score": 80.0,    // 沟通表达
  "adaptability_score": 82.0,  // 应变能力
  "match_score": 90.0,         // 岗位匹配度
  "summary": "综合评语……",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1"],
  "suggestions": ["建议1", "建议2"]
}
```

各岗位维度权重（源自《评估维度.csv》，代码单一事实源为
`backend/app/core/evaluation_weights.py`，主后端 Mock 兜底与评估服务共用）：

| 岗位 code | 技术 | 逻辑 | 表达 | 应变 | 匹配 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| backend | 35% | 25% | 10% | 10% | 20% |
| frontend | 30% | 20% | 15% | 15% | 20% |
| test_engineer | 25% | 25% | 20% | 15% | 15% |
