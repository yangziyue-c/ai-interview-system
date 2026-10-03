# 前端（P4 负责）

## 环境与接口

- 后端 API 文档（Swagger）：http://localhost:8001/docs
- 接口唯一权威：[../docs/API.md](../docs/API.md)
- **页面需求 + 接口补充说明（合并版）**：[../docs/reports/REPORT_TO_P4.md](../docs/reports/REPORT_TO_P4.md)
- **引擎功能对接注意事项（2026-10-01）**：[../docs/reports/REPORT_TO_P4_ENGINE_P1_HANDOFF.md](../docs/reports/REPORT_TO_P4_ENGINE_P1_HANDOFF.md)
  ——朗读 / 体态 / 语音转写 / 简历模式怎么接、有哪些坑，都在这份
- **TTS / 体态接口代理情况答复（2026-10-03）**：[../docs/reports/REPORT_TO_P4_ENGINE_PROXY_QA.md](../docs/reports/REPORT_TO_P4_ENGINE_PROXY_QA.md)
  ——两种 TTS 模式的取舍、体态响应字段随分支变化的分支表
- 统一响应格式：`{ "code": 0, "message": "ok", "data": ... }`，`code != 0` 即失败
  （40100 = 登录失效，清 token 跳登录页；40900 = 已有进行中的面试）

## 开发方式（二选一）

**联调**：`npm install && npm run dev`，前端跑在 5173，直连 `http://localhost:8001/api/v1`
（后端 CORS 已开放 `*`，无需代理）。
**部署**：`npm run build`，把 `dist/` 下的全部内容拷进 `backend/static/`，访问 `http://localhost:8001`。

连接方式、端口清单、Base URL 怎么配、路由模式要求与常见问题排查，见
[../docs/FRONTEND_CONNECT.md](../docs/FRONTEND_CONNECT.md)。连不上时先看那一份。

## 页面需求（详见 REPORT_TO_P4.md 第 1 节）

1. **登录/注册页**：账号密码 + 昵称/可选学号 + 选择目标岗位（选项来自 `GET /positions`，不得硬编码）
2. **岗位大厅 + 岗位详情**：岗位卡片/详情读 `GET /positions`（code→name 由接口 `name` 字段提供）
3. **面试对话室**：
   - 聊天式界面（AI 气泡靠左、自己靠右），顶部显示「第 N 题」（`interview.current_round`）
   - 文本输入 + 按住说话录音：转写可以前端自己做，也可以用后端
     `POST /api/v1/uploads/audio/asr` 一次拿到文本与 `url`（见
     [../docs/FRONTEND_CONNECT.md](../docs/FRONTEND_CONNECT.md) 第七节），
     随后随答案提交到 `POST /api/v1/interviews/{id}/answers` 的 `audio_url` 字段
   - 「结束面试」按钮（`POST /api/v1/interviews/{id}/finish`）
4. **报告页**：`GET /api/v1/reports/{interview_id}`，
   总分 + 五个维度（技术/逻辑/表达/应变/岗位匹配度）雷达图 + 评语/优缺点/建议；
   另可加「查看问答记录」抽屉（数据取 `GET /interviews/{id}` 的 `qa_records`，无需新接口）
   与「生成分享链接」（`POST /reports/{id}/share`，配套一个免登录的 `/share/:code` 只读页）
5. **历史与成长曲线**：
   - `GET /api/v1/interviews` 历史列表（status=in_progress 可点击继续作答）
   - `GET /api/v1/reports/latest` 最近建议、`GET /api/v1/reports/growth` 成长曲线折线图
     （后两个接口都支持可选 `?position=`，个人中心按岗位 Tab 筛选时传它）
   - 个人中心：资料可编辑（`PUT /api/v1/auth/me`）、头像可上传（`POST /api/v1/uploads/avatar`）；
     未设置头像时用昵称首字母占位

## 关键流程时序

```
登录 → POST /auth/login（拿 token，之后所有请求带 Authorization: Bearer <token>）
     → GET /positions 取岗位 → POST /interviews {position}（返回面试 id + 第一题）
     → 循环 { 录音/转写 → 上传 POST /uploads/audio → POST /interviews/{id}/answers {answer, audio_url} → 显示下一题 }
     → 响应 finished=true 或用户点「结束」→ 展示 report
```

> 回答提交后返回 `finished: true` 时直接跳转报告页；`false` 时展示 `next_question`。
> 提交答案是普通 JSON（无 SSE 流），面试题文本由后端题库策略生成，无需前端拼接。