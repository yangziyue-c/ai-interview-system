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
  "target_position": "backend"    // backend | frontend
}
```

返回：

```json
{
  "code": 0, "message": "注册成功",
  "data": { "access_token": "eyJ...", "token_type": "bearer", "user": { "id": 1, ... } }
}
```

### 1.2 登录

```
POST /auth/login          { "username": "zhangsan", "password": "123456" }
```

### 1.3 当前用户

```
GET /auth/me
```

---

## 2. 面试

### 2.1 开始面试

```
POST /interviews           { "position": "backend" }    // backend | frontend
```

返回：会话信息（`status: "in_progress"`）+ 开场题 `question`。

> 同一用户同时只能有一场进行中的面试，否则返回 409。

### 2.2 我的面试列表

```
GET /interviews
```

### 2.3 面试详情（含全部问答）

```
GET /interviews/{interview_id}
```

返回 `data.qa_records`：`[{round, question, answer, audio_url}]`。

### 2.4 提交答案并获取下一题

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

### 2.5 主动结束面试

```
POST /interviews/{interview_id}/finish
```

返回：`interview`（status=finished）+ `report`（评估报告）。

---

## 3. 报告

### 3.1 获取面试报告

```
GET /reports/{interview_id}
```

```json
{
  "code": 0, "message": "ok",
  "data": {
    "interview_id": 1,
    "total_score": 84.5,
    "tech_score": 88.0,       // 技术能力
    "logic_score": 83.0,      // 逻辑思维
    "expression_score": 80.0, // 表达沟通
    "match_score": 87.0,      // 岗位匹配度
    "summary": "整体表现良好……",
    "strengths": ["回答内容充实……"],
    "weaknesses": ["个别问题可再深入……"],
    "suggestions": ["继续深挖技术原理……"],
    "created_at": "2026-08-25T21:00:00"
  }
}
```

### 3.2 能力成长曲线

```
GET /reports/growth
```

返回已结束面试的得分序列（按时间升序）：

```json
{ "code": 0, "message": "ok", "data": [
  { "interview_id": 1, "position": "backend", "finished_at": "...",
    "total_score": 76.0, "tech_score": 76.0, "logic_score": 74.0,
    "expression_score": 78.0, "match_score": 77.0 },
  { "interview_id": 3, "position": "backend", "finished_at": "...",
    "total_score": 84.5, ... }
] }
```

---

## 4. 上传

### 4.1 上传面试录音

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

## 5. 系统

### 5.1 健康检查

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
  "position": "backend",        // backend | frontend
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

期望返回：

```json
{
  "total_score": 85.5,
  "tech_score": 88.0,
  "logic_score": 83.0,
  "expression_score": 80.0,
  "match_score": 90.0,
  "summary": "综合评语……",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1"],
  "suggestions": ["建议1", "建议2"]
}
```
