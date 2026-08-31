# 前端（P4 负责）

## 环境与接口

- 后端 API 文档（Swagger）：http://localhost:8001/docs
- 完整接口说明：[../docs/API.md](../docs/API.md)
- 统一响应格式：`{ "code": 0, "message": "ok", "data": ... }`，`code != 0` 即失败

## 开发方式（二选一）

### A. 开发模式（Vite/Webpack dev server）

```bash
npm create vite@latest . -- --template vue   # 或 react，按你们选的框架
npm install
npm run dev
```

开发时前端运行在 5173 端口，请求后端用代理或直接写 `http://localhost:8001`（后端 CORS 已开放 `*`，无需代理）。

### B. 联调/演示模式（构建产物由后端挂载，统一端口）

```bash
npm run build
# 把 dist/ 下的全部内容复制到 backend/static/（覆盖占位页 index.html）
```

然后访问 `http://localhost:8001` 即可（与 API 同端口，无跨域问题）。

## 页面需求

1. **登录/注册页**：账号密码 + 选择目标岗位（backend/frontend）
2. **面试页**：
   - 聊天式对话界面，展示 AI 面试官问题与自己的回答
   - 文本输入 + **录音按钮**（录音结束先调 `POST /api/v1/uploads/audio` 上传，
     拿到 `url` 后随答案一起提交到 `POST /api/v1/interviews/{id}/answers` 的 `audio_url` 字段）
   - 「结束面试」按钮（`POST /api/v1/interviews/{id}/finish`）
3. **报告页**：`GET /api/v1/reports/{interview_id}`，
   展示总分 + 四个维度（技术/逻辑/表达/岗位匹配度）雷达图/条形图 + 评语/优缺点/建议
4. **历史与成长曲线**：
   - `GET /api/v1/interviews` 历史列表
   - `GET /api/v1/reports/growth` 得分序列，画折线图

## 关键流程时序

```
登录 → POST /auth/login（拿 token，之后所有请求带 Authorization: Bearer <token>）
     → POST /interviews {position}（返回面试 id + 第一题）
     → 循环 { 录音上传 → POST /interviews/{id}/answers {answer, audio_url} → 显示下一题 }
     → 响应 finished=true 或用户点「结束」→ 展示 report
```

> 注意：回答提交后返回 `finished: true` 时直接跳转报告页；`false` 时展示 `next_question`。
