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
| 50300 | 依赖服务不可用（AI 对话层引擎未就绪或连不上；仅在 `DIALOGUE_ENGINE=a11` 时出现） |

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
      "avatar_url": null,          // 头像地址，未设置时为 null（前端用昵称首字母占位）
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

`data` 为 `user` 对象（结构见 1.1）。

### 1.4 更新当前用户资料（个人中心用）

```
PUT   /auth/me
PATCH /auth/me              // 与 PUT 等价，前端用哪个都行
```

字段全部可选，**只更新传入的字段**，未传的保持原值：

```json
{
  "nickname": "张三丰",                              // 昵称，不可为空白
  "student_id": "20260002",                          // 学号
  "target_position": "frontend",                     // 目标岗位 code（见 2.1）
  "avatar_url": "/uploads/avatars/1_ab3f9c2d.png"    // 头像地址，须为 6.2 返回的站内路径
}
```

返回更新后的完整 `user` 对象（结构同 1.1 的 `user`）。

> 「未传」与「显式传 null」含义不同：未传的字段保持原值，显式传 `null` 表示清空
> （适用于 `student_id`、`avatar_url`）。
> `nickname` 与 `target_position` 不允许为空，传 `null` 或纯空白返回 400（`code: 40000`）；
> `target_position` 不存在或未开放同样返回 400。
> 改目标岗位只影响之后新开的面试，历史记录保留当时的岗位。

---

## 2. 岗位

### 2.1 岗位列表（岗位大厅用）

```
GET /positions
```

> 岗位由后端数据库动态维护（当前 5 个岗位全部启用；`enabled=false` 的岗位不下发）。
> 前端不得硬编码岗位列表，注册/开始面试的 position 必须传本接口返回的 `code`。

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
GET /interviews?position=backend     // 可选：只看该岗位的记录
```

| 参数 | 说明 |
| :--- | :--- |
| position | 岗位 code（可选，不传 = 全部岗位）。各岗位评估维度权重不同，混在一起统计没有可比性 |

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

返回 `data.qa_records`：`[{round, question, answer, audio_url, created_at}]`，按 `round` 升序。

> `answer` 为 `null` 表示该题已出、考生尚未作答。「查看问答记录」直接用本接口，
> 无需另开接口；`created_at` 供按时间线展示时使用。

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
    "position": "backend",       // 面试岗位 code（2026-09-14 新增：报告页刷新/深链时显示岗位名）
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
>
> `position` 由接口从所属面试注入（`reports` 表不存该列）。前端应直接用它显示岗位名，
> 不要再靠「从列表页带过来的内存变量」，那样一刷新页面岗位名就没了。
> 结束面试的两个响应（`POST /interviews/{id}/answers` 的 `report`、
> `POST /interviews/{id}/finish` 的 `report`）同样带该字段。

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
GET /reports/growth?position=backend   // 可选：只看该岗位的得分序列
GET /reports/growth?engine=a11         // 可选：只看 AI 对话层引擎评的场次
```

| 参数 | 说明 |
| :--- | :--- |
| position | 岗位 code（可选，不传 = 全部岗位）。个人中心按岗位 Tab 筛选时传它 |
| engine | 面试链路（可选，不传 = 全部）：`standard` = 原链路（题库策略 + P3 评估），`a11` = AI 对话层引擎。两种链路的五维分口径不同，混在一条曲线上会被误读成涨跌 |

返回已结束面试的得分序列（按时间升序）：

```json
{ "code": 0, "message": "ok", "data": [
  { "interview_id": 1, "position": "backend", "engine": "", "finished_at": "...",
    "total_score": 76.0, "tech_score": 76.0, "logic_score": 74.0,
    "expression_score": 78.0, "adaptability_score": 75.0, "match_score": 77.0 },
  { "interview_id": 3, "position": "backend", "engine": "a11", "finished_at": "...",
    "total_score": 84.5, ... }
] }
```

### 4.4 生成报告分享链接

```
POST /reports/{interview_id}/share
```

```json
{ "code": 0, "message": "分享链接已生成", "data": {
  "share_code": "8f14e45fceea167a5a36dedd4bea2543",
  "share_url": "http://localhost:8001/#/share/8f14e45fceea167a5a36dedd4bea2543",
  "expires_at": "2026-09-25T21:00:00"
} }
```

> 面试未结束（尚无报告）时返回 409。
> 同一份报告重复调用会**复用尚未过期的分享码**，不会堆出一串等价的有效码。
> 有效期默认 7 天，由 `.env` 的 `SHARE_EXPIRE_DAYS` 控制。
> `share_url` 由后端按当前请求的 Host 拼好（内网穿透演示时即穿透域名），前端直接复制到剪贴板即可。
> 分享内容含个人信息，前端应提示「分享内容包含个人信息，请注意隐私」。

### 4.5 智能推荐学习资源 / 练习计划

```
GET /reports/study-plan                             // 聚合最近 5 场（个人中心用）
GET /reports/study-plan?interview_id=12             // 单场（报告页用）
GET /reports/study-plan?position=backend&recent=3   // 按岗位聚合
```

| 参数 | 说明 |
| :--- | :--- |
| interview_id | 指定单场面试（可选）。**不传 = 按最近 N 场聚合**，两种用法共用一个接口 |
| position | 岗位 code（可选，仅聚合模式）。**与 `interview_id` 互斥**，同传返回 400 |
| recent | 聚合模式下取最近 N 场已结束面试，默认 5，范围 1~20 |
| max_knowledge | 最多返回多少个知识点，默认 10，范围 1~50（按优先级 + 命中次数排序后截断） |

返回「该场 / 最近 N 场面试考察过的知识点」+ 题库自带的学习建议原文 + 同知识点的配套练习题：

```json
{ "code": 0, "message": "ok", "data": {
  "interview_id": 12,                    // 单场模式为该场 ID；聚合模式为 null
  "source_interviews": [                 // 本次计划用到的面试（按结束时间倒序）
    { "interview_id": 12, "position": "backend", "finished_at": "2026-09-23T21:04:00" }
  ],
  "positions": ["backend"],              // 覆盖的岗位 code（跨岗位聚合时为多个）
  "knowledge_points": [
    {
      "kp_id": "java-backend-kp-0523",
      "name": "HTTP 响应报文结构",
      "advice": "建议从「HTTP 响应报文结构」的核心定义与基本用法入手……",   // 题库原文
      "priority": "高频必考题",            // 该知识点来源题目中最高的考点优先级
      "hit_count": 2,                     // 来源面试里有几道锚点原题关联到它
      "sources": [                        // 来源：哪场面试的第几轮问到了它
        { "interview_id": 12, "round": 1,
          "question_no": "JAVA_BACKEND-Q0043",
          "question": "GET和POST有什么区别？" }
      ],
      "practice_minutes": 4,              // 该知识点配套练习时长（分）
      "practice_questions": [             // 全库反查同知识点的题：同岗位优先、高频必考题优先
        { "id": 43, "position_code": "backend", "question_no": "JAVA_BACKEND-Q0043",
          "question": "GET和POST有什么区别？", "category": "技术知识题",
          "difficulty": "easy", "exam_priority": "高频必考题", "suggested_minutes": 2,
          "asked": true },                // true = 本计划的来源面试里已经问到过
        { "id": 62, "position_code": "backend", "question_no": "JAVA_BACKEND-Q0062",
          "question": "什么是幂等？HTTP 幂等语义和业务幂等有什么区别？",
          "category": "技术知识题", "difficulty": "easy",
          "exam_priority": "常规题", "suggested_minutes": 2, "asked": false }
      ]
    }
  ],
  "total_minutes": 44,                    // 推荐练习总时长（同题服务多个知识点时只算一次）
  "pending_minutes": 37,                  // 其中尚未练过的部分
  "notice": null                          // 无可推荐内容时的一句中文说明，正常为 null
} }
```

> **知识点口径是「考察过的知识点」，不是「你答得差的知识点」**：报告只有整场面试的
> 5 维聚合分（`reports` 表无单题得分），接口不会假装知道你哪道题答错。排序口径 =
> 考点优先级（高频必考题优先）→ 被多道题命中 → 首次出现顺序。
>
> **只认锚点原题**：接口把面试问答的题干反查回题库（`questions.question` 精确匹配 +
> 按该场面试的岗位过滤）。追问轮次里由锚点生成的追问文本不在题库里，因此不参与反查；
> 题干跨岗位会重复（如「什么是优先级队列？」同时在算法与系统设计岗），故必须按各场
> 面试自己的岗位分组反查。
>
> 配套练习题按知识点 ID 的**完整 token**（`ID|`）在全库反查，不依赖「当前 1513 个 ID
> 恰好两两无前缀关系」这一数据巧合——否则 `java-backend-kp-318` 会串到 `java-backend-kp-3180`。
> 全库反查会带出别岗位的题（知识点 ID 会跨岗位被引用），故每项带 `position_code`，
> 同岗位的排在前面。
>
> `asked=true` 表示本题在本计划的来源面试里**被问到过**（含最后一轮问了未作答的），
> 前端应标为「已练过」而不是「重做」。
>
> **前置条件**：需要题库已导入（`python -m scripts.import_question_bank`）且存在已结束的
> 面试。题库为空、或本场题目全部由 RAG / Mock 现场生成时，接口返回 200 且
> `knowledge_points` 为空，`notice` 说明原因——**前端展示「暂无推荐」即可，不要当错误处理**。
>
> 错误码：面试未结束 409；`interview_id` 不存在或非本人 404；`interview_id` 与
> `position` 同传 400；`position` 传未开放岗位不报错，返回空计划（与 4.3 同口径）。

---

### 4.6 成长档案（错题本 / 考点地图 / 历史成绩）

```
GET /reports/archive
GET /reports/archive?position=backend&limit=50
```

| 参数 | 说明 |
| :--- | :--- |
| position | 岗位 code（可选，不传 = 最近一场已结束面试的岗位）。档案按岗位算，一次只聚合同一岗位的场次 |
| limit | 最多取几场（可选，默认 50，上限 100；对话层侧上限 100 份） |

把该用户已存档的**成长档案摘要**（每场结束时的 `digest`）原样回传给 AI 对话层，取回四视图：

```json
{ "code": 0, "message": "ok", "data": {
  "available": true,
  "position": "backend",
  "record_count": 12,
  "wrong_book": { "total": 4, "items": [ ... ] },   // 错题本
  "kp_map": { ... },                                 // 考点地图
  "history": { "exam": { "sessions": 12, "timeline": [ ... ] } },  // 历史成绩
  "plan": { ... },                                   // 能力提升路径
  "skipped": []
} }
```

- 只有**引擎链路**的场次有档案（原链路没有）；一场都没有时 `available=false` 且 `notice` 说明原因，这不是错误。
- 对话层不可用时同样返回 `available=false`（口径与 `5.3 RAG 语义检索` 一致），不返回 5xx。

## 5. 题库

题库数据来自 `questions` 表（由 `backend/scripts/import_question_bank.py` 从
`backend/rag/数据/*-v5.json` 导入。题库 V5（2026-09-14 换代）：5 个岗位共 5012 题，
backend 2146 + frontend 734 + test_engineer 667 + algorithm 655 + system_design 810）。
主要供面试官算法（选题/追问）与评估服务（单题评分素材）使用。

> 18 字段规范、导入命令与排障见 [docs/reports/REPORT_TO_P5.md](reports/REPORT_TO_P5.md)；
> 字段变更对照与目录归属见
> [docs/reports/REPORT_TEAM_V5_LAYOUT_AND_API.md](reports/REPORT_TEAM_V5_LAYOUT_AND_API.md)。

### 5.1 题库列表（过滤 + 分页）

```
GET /questions?position=backend&category=技术知识题&difficulty=easy&stage=开场热身&q=JVM&limit=20&offset=0
```

全部查询参数可选：

| 参数 | 说明 |
| :--- | :--- |
| position | 岗位 code（backend / frontend / test_engineer / algorithm / system_design） |
| category | 题型（受控词表，V5 共 4 类）：技术知识题 / 场景应用题 / 项目经历题 / 行为素质题 |
| difficulty | 难度：easy / medium / hard |
| stage | 面试阶段：开场热身 / 核心考察 / 深度压轴 |
| priority | 考点优先级（V5 新增，不做受控校验）：常规题 / 高频必考题 / 拓展题 |
| q | 题干模糊搜索关键词 |
| limit / offset | 分页（limit 默认 20，最大 100） |

> `category` / `difficulty` / `stage` 走受控词表校验，非法值返回 400（`code=40000`），
> 避免题库改名后静默返回空集。

返回：

```json
{ "code": 0, "message": "ok", "data": {
  "total": 5012,
  "items": [
    {
      "id": 1,
      "position_code": "backend",
      "question_no": "JAVA_BACKEND-Q0001",
      "category": "技术知识题",
      "difficulty": "easy",
      "question": "JVM、JDK、JRE 三者有什么区别和联系？",
      "interview_stage": "开场热身",
      "stage_order": 1,
      "suggested_minutes": 2,
      "keywords": "JVM\nJDK\nJRE",
      "exam_priority": "高频必考题",
      "basic_score_points": "JVM 是运行字节码的虚拟机……",
      "advanced_score_points": "JDK 包含 JRE 和开发工具……",
      "follow_up_l1": "[触发] 答出基础得分点、回答基本正确时触发\n[追问] 你提到了JVM，能具体说说它的定义和核心作用吗？",
      "follow_up_l2": "[触发] 基础得分点全对且逻辑清晰时触发\n[追问] JVM的底层实现原理是什么？",
      "follow_up_l3": "[触发] 本题为easy难度，一般不触达L3；若考生表现优异可酌情触发以下追问。\n[触发] 考生答出进阶得分点时触发\n[追问] 在实际项目中你用过JVM吗？遇到过什么坑？怎么解决的？",
      "fallback_strategy": "如果候选人一时答不上来，先引导聚焦核心概念……",
      "calibration_anchor": "[技术水平] 能准确阐述核心概念与原理边界……\n[岗位匹配度] ……",
      "related_knowledge": "java-backend-kp-3180|JVM入门与体系结构|理解JVM运行时数据区……"
    }
  ]
} }
```

> `question_no` 是 V5 原题 ID，与 RAG 向量库元数据的「原题ID」同键，可双向回查。
> 三级追问字段的原文含 `[触发]` / `[追问]` 标记行，解析由 `backend/interviewer_new/`
> 负责（见 [REPORT_TO_P2_INTERVIEWER_NEW.md](reports/REPORT_TO_P2_INTERVIEWER_NEW.md)）。

### 5.2 题库详情

```
GET /questions/{question_id}
```

返回单题全量字段（结构同 5.1 的 item）。

> 该接口也是评估侧取「单题校准锚点」素材的入口（`calibration_anchor` /
> `basic_score_points` / `advanced_score_points`），见
> [REPORT_TO_P3_EVALUATOR_NEW.md](reports/REPORT_TO_P3_EVALUATOR_NEW.md)。

### 5.3 RAG 语义检索（透传知识库服务）

```
POST /rag/search
```

```json
{ "query": "Redis 缓存穿透怎么办", "job": "Java 后端开发工程师",
  "mode": "select", "top": 3, "level": null }
```

| 参数 | 说明 |
| :--- | :--- |
| query | 检索文本：面试问题或考生表述 |
| job | 岗位全名过滤（可选），如 `Java 后端开发工程师`（注意与 `position` code 不同） |
| mode | `select`=出题（Top-N 道不同题）/ `expand`=深挖（命中题的全部层级片段） |
| top | select 模式返回几道题（1~20，默认 3） |
| level | 层级过滤（可选）：原题 / L1 / L2 / L3 / 语义变体… |

返回 `data`：`{available, mode, results: [{score, 题目, 参考答案, 原题ID, 题目ID, 层级, 岗位, 题型, 难度, 面试阶段, 考点优先级}]}`；
`mode=expand` 时响应结构不同：不含 `results`，而是 `{mode, 原题ID, 命中题目, 全层级片段, 片段数}`（`命中题目` 为单元素数组）。

> 服务不可用时返回 `available: false` + 空结果，而非 500，调用方可据此降级。
> RAG 服务本体是独立进程（8003，`backend/rag/`，由 `start.py` 拉起），首次启动需
> 下载约 4.5GB 模型；出题链的自动兜底见 `ai_interviewer.py::_generate_via_rag`。

---

## 6. 上传与简历导入

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

### 6.2 语音转写（音频进，文字 + 表达指标 + 地址出）

```
POST /uploads/audio/asr    Content-Type: multipart/form-data
                           file: 录音文件（与 6.1 同一套格式与大小限制）
```

把录音交给 AI 对话层做**本地**语音转写，并把音频存下来（一次调用同时给文本与地址，同一个文件不用传两次）：

```json
{ "code": 0, "message": "转写完成", "data": {
  "text": "线程的状态包括新建、就绪、运行、阻塞和终止……",
  "url": "/uploads/12_ab3f9c2d.webm",
  "duration_ms": 16878, "audio_ms": 16878,
  "segments": [ { "start": 0.0, "end": 6.0, "text": "…" } ],
  "pauses": 0, "pause_total_ms": 0,
  "asr_model": "faster-whisper-…(int8)", "elapsed_ms": 3804,
  "loudness": 0.0622, "loudness_cv": 0.331, "tail_ratio": 1.05,
  "emotion": "hap", "emotion_score": 0.545,
  "emotion_dist": { "neu": 0.445, "hap": 0.545, "ang": 0.010, "sad": 0.00001 }
} }
```

- `url` 可直接填入提交答案的 `audio_url`，用法与 6.1 的返回值相同。
- 转写有错字是正常形态：前端把文本填进输入框、**由考生自行修改**后再发送。
- `emotion*` 三项来自本地情感模型。⚠️ 该模型是**英语表演情绪**数据训的，**中文上标签不可信**（实测中文 3/3 判 `hap`）：只用它看分布起伏，别把标签当结论展示。
- `loudness*` 与 `tail_ratio` 是音量三指标，与情感无关，中文上一样有效。
- 对话层未就绪时返回 **503（50300）**，不返回空文本——空文本会被当成「考生没说话」。

### 6.3 上传头像

```
POST /uploads/avatar       Content-Type: multipart/form-data
                           file: 图片文件（jpg/jpeg/png/webp，≤2MB）
```

返回：

```json
{ "code": 0, "message": "头像上传成功", "data": { "url": "/uploads/avatars/1_ab3f9c2d.png" } }
```

拿到 `url` 后还需调用 `PUT /auth/me` 提交，头像才会生效——先传图拿地址，再改资料。

> 本接口只落盘并返回地址，不动用户资料；旧头像文件的清理发生在 `PUT /auth/me`
> 换掉 `avatar_url` 的那一步。这样「传了图但没提交」只会留下一个无引用文件，
> 不会让用户资料指向一张已删的图。
> 服务端会校验**文件头**：把 `.html` 改名成 `.png` 会被拒（否则静态服务会照
> `image/png` 托管任意内容）。`avatar_url` 也只接受 `/uploads/avatars/` 下的站内路径。

### 6.4 上传并解析简历

```
POST /resumes              Content-Type: multipart/form-data
                           file: 简历文件（pdf/jpg/jpeg/png/webp，≤10MB）
```

返回解析结果与**建议回填**的个人资料字段：

```json
{ "code": 0, "message": "已从 PDF 中提取 1823 字，请核对识别结果后保存", "data": {
  "id": 7,
  "original_filename": "张三-后端开发.pdf",
  "file_ext": ".pdf",
  "file_size": 248913,
  "parse_status": "parsed",
  "parse_message": "已从 PDF 中提取 1823 字，请核对识别结果后保存",
  "text": "张三\n求职意向：Java 后端开发工程师\n学号：20210001\n……",   // 全文，上限 10000 字
  "text_preview": "张三\n求职意向：Java 后端开发工程师……",            // 前 300 字，供折叠态渲染
  "text_length": 1823,          // 截断前的字符数
  "text_truncated": false,      // 为 true 说明 text 被截断了
  "suggested": { "nickname": "张三", "student_id": "20210001", "target_position": "backend" },
  "suggested_notes": {
    "nickname": "据文档首行推测：张三（请核对）",
    "student_id": "命中「学号」标签：20210001",
    "target_position": "据「Java 后端开发工程师」判定为 backend"
  },
  "created_at": "2026-09-23T17:20:11"
} }
```

`parse_status` 的五个取值，前端只需判 `== "parsed"`，其余一律展示 `parse_message`：

| 取值 | 含义 | 前端建议 |
| :--- | :--- | :--- |
| `parsed` | 提取成功，`text` 有内容 | 展示识别结果供用户核对 |
| `no_text_layer` | PDF 无文字层（扫描件、纯图 PDF） | 提示改用手动填写 |
| `garbled` | 字体缺 ToUnicode 表，提取成乱码 | 提示改用手动填写 |
| `image_pending` | 图片，当前版本不识别 | 提示手动填写（后续版本支持） |
| `failed` | 损坏 / 加密 / 超时 / 解析依赖缺失 | 提示手动填写 |

> **解析不出来不算请求失败**：文件已安全保存，仍返回 200，原因写在 `parse_message` 里。
> 只有「扩展名不在白名单 / 超过 10MB / 文件头与扩展名不符 / 未登录」才返回 400 或 401。
>
> **`suggested` 是推测而非结论**：三个字段都可能为 `null`——**抽不到就不猜**（抽错会把
> 用户已经填对的信息引导成错的）。`suggested_notes` 给出每个值的来源，可直接展示。
> **前端不要自动提交**：应由用户确认后再调 `PUT /auth/me`（部分更新语义）。
>
> **只回填 users 表已有的三个字段**（昵称/学号/目标岗位），本次不新增资料字段。
> 建议值是每次读取时按当前开放的岗位现算的——岗位若下线，`target_position` 会回到 `null`。
>
> **图片不做 OCR**：照片/扫描件只保存原件并明确返回 `image_pending`，不假装识别成功。
>
> `text` 可供面试出题「结合简历提问」使用（一期未接，约定见 P2 对接文档）。

### 6.5 获取最近一次简历

```
GET /resumes/latest
```

返回与 6.3 完全相同的 `data` 结构；**从未上传过时 `data` 为 `null`**（空态查询而非缺资源，故不返回 404）：

```json
{ "code": 0, "message": "ok", "data": null }
```

> 多次上传保留历史（append-only），`latest` 取最近一份；按 id 读历史用 `GET /resumes/{resume_id}`，
> 返回同一结构。

### 6.6 下载简历原文件

```
GET /resumes/{resume_id}/file
```

返回文件流，**仅本人可下载**：

```
200 OK
Content-Type: application/pdf
Content-Disposition: attachment; filename*=utf-8''%E5%BC%A0%E4%B8%89%E7%9A%84%E7%AE%80%E5%8E%86.pdf
```

> **简历原件存在私有目录 `backend/private/resumes/`，不在 `/uploads` 静态挂载内**——
> 那个目录是完全公开的（无鉴权、无子目录白名单），而简历含姓名/学号/联系方式。
> 本接口是下发简历原件的唯一途径。
>
> **非本人一律 404**，不返回 403（403 等于承认这个 id 存在）。
>
> **前端必须带 token 请求**：`<iframe src>` 与 `window.open()` 发出的是不带
> `Authorization` 头的普通 GET，拿不到文件。要用 fetch/axios 带 token 请求，
> `responseType: 'blob'`，再 `URL.createObjectURL(blob)` 预览或触发下载。

---

## 7. 系统

### 7.1 健康检查

```
GET /health                { "code": 0, "message": "ok", "data": { "status": "healthy" } }
```

### 7.2 前端运行参数

```
GET /config                { "code": 0, "message": "ok", "data": {
                              "total_rounds": 7,           // 一场面试总轮数（1 开场题 + N 追问）
                              "max_follow_up_rounds": 6,   // 最大追问轮数
                              "engine": "standard"         // 当前面试链路：standard=原链路；a11=AI 对话层引擎
                            } }
```

> 需登录（与其余业务接口一致）。前端不要硬编码轮数，它由后端 `.env` 的
> `MAX_FOLLOW_UP_ROUNDS` 决定，改配置后本接口自动跟随；硬编码会导致
> 「第 N / 7 题」的显示与实际轮数静默脱节。

---

## 8. 分享

### 8.1 凭分享码查看报告（免登录）

```
GET /share/{code}
```

返回结构与 4.1 完全一致，前端可复用同一套报告渲染。**本接口是全站唯一无需登录的业务接口。**

> 分享码不存在或已过期，一律返回 404（`code: 40400`）且提示同一句话，
> 不区分二者——否则可被用来枚举试探出哪些分享码真实有效。
> 每次成功访问累加一次访问计数（`report_shares.view_count`，当前不对外暴露）。

---

## 附录：P2 / P3 外部服务接入约定

在 `backend/.env` 中配置 URL 后自动生效；未配置或调用失败时后端自动降级为内置 Mock。
**超时预算不同**：P2 面试官 15 秒（`ADAPTER_TIMEOUT_SECONDS`），P3 评估 30 秒
（`ai_evaluator.EVALUATE_TIMEOUT_SECONDS`，评估报告生成较慢故单独放宽；
评估服务自身内部超时为 25 秒，正是为配合这个 30 秒预算，不要按 15 秒改动）。

### P2：AI 面试官

> 2026-09-14 起出题由题库策略原生完成（`backend/interviewer_new/`，最高优先级）：
> 面试官算法已落地主项目，`AI_INTERVIEWER_URL` 仅为扩展位，只在题库策略
> 未命中（如岗位在题库无题）时才会被调用。数据源链为
> `题库策略 > RAG 语义检索 > 外部服务 > LLM 直连 > 内置 Mock`。以下契约供扩展位服务对接：

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
    { "round": 1, "question": "...", "answer": "...", "audio_url": "/uploads/xxx.mp3",
      "materials": {                    // 可选：主后端按题干从题库自动附加（V5 起）
        "basic_score_points": "...",    // 基础得分点
        "advanced_score_points": "...", // 进阶得分点
        "calibration_anchor": "..."     // 单题校准锚点（该题「答到什么程度算好」）
      } }
  ]
}
```

> `materials` 用于让评估服务"按题判分"（同一段答案，easy 概念题与 hard 原理题应得不同分）。
> 它是向后兼容的可选增强：旧版评估服务忽略该字段，不传时评分行为与原版逐字一致。

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
| algorithm | 35% | 30% | 10% | 10% | 15% |
| system_design | 30% | 30% | 15% | 10% | 15% |

> 最后两个岗位（2026-09-14 随 V5 知识库启用）的权重已在《评估维度.csv》与
> `POSITION_CONFIG` 两处同步一致（`test_weights_match_csv` 机器校验）。改权重必须同时改两处。
