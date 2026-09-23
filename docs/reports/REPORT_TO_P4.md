# 致 P4（前端）同学：页面需求与接口权威说明

> **2026-09-23 回你的接口清单**：新增
> [《你的接口清单：逐条确认与补充》](REPORT_TO_P4_API_CHECKLIST.md)——
> 针对《致 1 号 · 前端接口需求》逐条核对，**清单里的字段全部满足**，
> 并补上两块未覆盖的新功能（简历导入、学习资源推荐）。

> **2026-09-23 新增简历导入（见 2.14）**：`POST /resumes` 上传简历（PDF / 图片）→ 自动提取
> 文本 → 返回**建议回填**的昵称/学号/目标岗位，用户确认后再走既有的 `PUT /auth/me` 提交；
> 另有 `GET /resumes/latest` 与鉴权下载 `GET /resumes/{id}/file`。图片当前不识别文字
> （明确提示，不假装成功）。后端已实现并有回归测试覆盖；
> 接口字段以 [docs/API.md](../API.md) 为唯一权威。

> **2026-09-23 新增 1 个接口（见 2.13）**：`GET /reports/study-plan` 智能推荐学习资源与
> 练习计划——按面试考察过的知识点给出题库自带的学习建议原文与同知识点的配套练习题。
> 单场（报告页）与最近 N 场聚合（个人中心）共用一个接口，站内闭环、不依赖外部服务。
> 后端已实现并有回归测试覆盖；接口字段以 [docs/API.md](../API.md) 为唯一权威。

> **2026-09-18 新增 5 组接口（见 2.8~2.12）**：个人资料可编辑、头像可上传、报告可生成
> 限时分享链接（含一个免登录的只读报告页）、历史记录与成长曲线支持按岗位筛选、
> 面试详情补上问答时间戳。后端均已实现并有回归测试覆盖；
> 接口字段以 [docs/API.md](../API.md) 为唯一权威。

> **2026-09-14 起题库换代到 V5**：岗位增至 5 个（新增算法工程师、系统设计工程师）、
> 题库题型/阶段受控词表有变、新增 `POST /api/v1/rag/search` 语义检索接口。
> 岗位列表走 `GET /positions`，不硬编码岗位即可正常适配，故无强制改码；
> 但建议验证 5 张岗位卡片的布局。
>
> **另有 2 处可选增强（同一日新增，见 2.6 / 2.7）**：不改也能跑，
> 但用上可避免两个实际缺陷：报告页刷新后岗位名空白（2.6 `position` 字段）、
> 轮数硬编码改配置后脱节（2.7 `GET /config`）。建议一并采纳。
>
> 变更详情见 [REPORT_TEAM_V5_LAYOUT_AND_API.md](REPORT_TEAM_V5_LAYOUT_AND_API.md) 第 4.4 节；
> 接口字段以 [docs/API.md](../API.md) 为唯一权威。

> 来自 P1（后端）。本文档由 `frontend-spec.md`（页面需求部分）+ `FRONTEND_HANDOFF.md`
> （接口勘误与权威）合并而成（2026-09-06）。原 frontend-spec 的接口部分
> 与后端实际实现大量不符，已作废；开发/联调以本文档第 2 节与 [API.md](../API.md)
> 为唯一权威，页面设计以第 1 节为准。

---

## 1. 页面需求（原 frontend-spec.md 有效部分）

采用底部固定 Tab 栏布局，共 2 个 Tab：模拟面试与个人中心。
技术栈：Vue（网页端开发，后续可打包桌面/移动应用）。

### Tab1：模拟面试

#### ① 岗位大厅
- 展示岗位卡片（数据来自 `GET /positions`，不得硬编码）。
- 点击卡片不直接进对话，弹出岗位详情浮层或跳转岗位详情页。

#### ② 岗位详情页
- 展示：岗位简介 / 技术栈要求 / 面试考察重点。
- 底部提供显眼的「开始面试」按钮。

#### ③ 面试对话室（核心页面）
1. **顶部**：面试状态（如「面试中」「第 N 题」，用 `data.interview.current_round`）。
2. **中间**：聊天区域，AI 气泡靠左、用户回答气泡靠右。
3. **底部输入区**：左侧语音录制按钮（按住说话）、右侧文本输入框 + 发送按钮，
   语音/文本随时切换。

### Tab2：个人中心

1. **上半部分**：头像、昵称、学号、目标岗位，并提供「编辑资料」与「更换头像」入口
   （接口见 2.8 / 2.9）。用户没设置头像时用昵称首字母占位。
2. **中间部分**：岗位筛选 Tab（「全部」+ 各岗位，选项来自 `GET /positions`）+ 历史面试列表
   （按时间倒序；岗位名称 + 综合得分 + 日期，点击进完整报告）。统计卡片（总次数/平均分/最高分）
   与成长曲线都要跟着 Tab 一起筛选（见 2.11）。
3. **下半部分**：最近一次 AI 改进建议（`GET /reports/latest`；无数据时显示"暂无建议"）。

---

## 2. 后端接口补充说明（为满足上述页面需求而新增/变更）

### 2.1 用户增加「学号」字段

- 注册 `POST /auth/register` 请求体新增可选字段 `student_id`；
- 登录响应 / `GET /auth/me` 的 `user` 对象含 `student_id`（未填为 `null`）。

### 2.2 历史列表附带综合得分

`GET /interviews` 每项含 `total_score`（浮点；进行中/未出报告为 `null`），
个人中心历史列表无需逐条请求报告接口拿分数。

### 2.3 最近一次面试建议

```
GET /reports/latest
```

返回最近一场已结束面试的得分与建议摘要；从未完成面试时 `data` 为 `null`。

### 2.4 岗位列表（岗位大厅用，取代 jobs.json 方案）

```
GET /positions
```

岗位由后端数据库动态维护（2026-09-14 起已开放 5 个：backend / frontend /
test_engineer / algorithm / system_design，全部 `enabled=True`；清单可能调整）。
**前端不得硬编码岗位列表**：岗位大厅展示本接口返回数据；注册的 `target_position`
与开始面试的 `position` 必须传返回的 `code`；岗位中文名由 `name` 字段天然提供。

### 2.5 报告评分 5 维（2026-09-04 起，源自《评估维度.csv》）

| 维度字段 | 中文名 |
| :--- | :--- |
| `tech_score` | 技术水平 |
| `logic_score` | 逻辑思维 |
| `expression_score` | 沟通表达 |
| `adaptability_score` | 应变能力 |
| `match_score` | 岗位匹配度 |

报告详情与成长曲线均返回 5 维分数，雷达图按 5 轴渲染。前端无需计算总分，
直接展示 `total_score`。

### 2.6 报告带岗位 code（2026-09-14 新增，报告页务必用它）

报告响应（`GET /reports/{id}`、`POST /interviews/{id}/answers` 结束时的 `report`、
`POST /interviews/{id}/finish` 的 `report`）统一新增 `position` 字段（岗位 code）。

```json
{ "code": 0, "data": { "interview_id": 1, "position": "algorithm", "total_score": 84.5, ... } }
```

> **为什么要加**：报告页要显示岗位名，而此前响应里没有岗位字段，前端只能靠
> 「从列表页带过来的内存变量」，一旦用户刷新页面或直接深链进报告页，
> 那个变量就没了，页面上岗位名变成空白。
>
> **正确做法**：报告页渲染时直接用 `report.position`（配合 `GET /positions` 把 code
> 转中文名）；不要再用内存变量传岗位 code 这类补丁。若 `GET /positions` 因故失败，
> 顶多把 code 原样显示出来，不影响报告其余内容。

### 2.7 前端运行参数（2026-09-14 新增，不要硬编码轮数）

```
GET /config     { "code": 0, "data": { "total_rounds": 7, "max_follow_up_rounds": 6 } }
```

> 「一场面试共几轮」由后端 `.env` 的 `MAX_FOLLOW_UP_ROUNDS` 决定（当前 = 1 开场题 + 6 追问 = 7）。
> **前端不要把 7 写死**：`total_rounds` 一改，写死的前端就会显示成「第 N / 7 题」而与实际轮数脱节。
> 建议启动/登录后调一次本接口缓存起来（需登录）。`current_round` 仍从面试响应里取。

### 2.8 更新个人资料（个人中心「编辑资料」用，2026-09-18 新增）

```
PUT   /auth/me          （PATCH /auth/me 等价，用哪个都行）
```

请求体字段全部可选，**只改传入的那些**：

```json
{ "nickname": "张三丰", "student_id": "20260002", "target_position": "frontend" }
```

返回更新后的完整 `user` 对象，用它刷新 localStorage 里的 `userInfo` 与页面顶部/侧边栏显示。

> 「未传」与「显式传 null」含义不同：未传的保持原值，传 `null` 表示清空
> （`student_id`、`avatar_url` 适用）。`nickname` 与 `target_position` 不允许为空，
> 传 null 或纯空白返回 400。
> `target_position` 的选项从 `GET /positions` 取，不要硬编码。
> 改昵称后记得同步头像占位字母——没设头像时显示的就是昵称首字母。
> 改目标岗位只影响之后新开的面试，历史记录保留当时的岗位。

### 2.9 上传头像（个人中心「更换头像」用，2026-09-18 新增）

```
POST /uploads/avatar      multipart/form-data，file 字段（jpg/jpeg/png/webp，≤2MB）
                          → { "code": 0, "data": { "url": "/uploads/avatars/1_ab3f9c2d.png" } }
```

**分两步**：先上传拿到 `url`，再调 `PUT /auth/me` 提交 `avatar_url`，头像才真正生效。

> 本地预览用 `FileReader` 即可，不必等上传成功；提交成功后再刷新所有显示头像的位置。
> `avatar_url` 为 `null` 时仍用昵称首字母占位。
> 服务端会校验文件头：把 `.html` 改名成 `.png` 会被 400 拒掉。
> `avatar_url` 只接受 `/uploads/avatars/` 下的站内路径，传外部 URL 也是 400。
> 移动端注意 `<input type="file" accept="image/*">` 的选图体验。

### 2.10 报告分享链接（报告页「生成分享链接」用，2026-09-18 新增）

```
POST /reports/{interview_id}/share
  → { "share_code": "8f14e45f…", "share_url": "http://host/#/share/8f14e45f…", "expires_at": "…" }
```

取到 `share_url` 后直接复制到剪贴板即可。同时需要新增一个**只读报告页** `/share/:code`：

```
GET /share/{code}        // 免登录
```

返回结构与 `GET /reports/{interview_id}` **完全一致**，报告渲染组件可以直接复用。

> 分享码不存在或已过期都返回 404 且提示相同，前端统一提示「链接不存在或已过期」。
> 重复点「生成链接」返回的是同一个未过期的码，不会每次都给新的。
> 这是全站唯一无需登录的接口：分享页不要跳登录，也别去读 localStorage 里的 token。
> 分享内容含个人信息，页面上加一句「分享内容包含个人信息，请注意隐私」。

### 2.11 历史记录与成长曲线按岗位筛选（2026-09-18 新增）

```
GET /interviews?position=backend          // 不传 = 全部岗位
GET /reports/growth?position=backend      // 不传 = 全部岗位
```

个人中心历史列表上方加岗位 Tab（「全部」+ 各岗位），切换时把 code 传给上面两个接口。

> 切换 Tab 要同时驱动三处：历史列表、统计卡片、成长曲线。只筛列表不筛统计，
> 页面上就会出现「列表 5 条、总次数 12 次」这种自相矛盾的显示。
> 各岗位评估维度权重不同，混在一条成长曲线上没有可比性——这正是加这个筛选的原因。
> 别用 localStorage 里的 `position` 做本地筛选来顶替：本地筛选只能筛到当前页那几条，
> 统计口径还是全量的，数据一多就露馅。

### 2.12 报告页「查看问答记录」（2026-09-18 补字段，无需新接口）

`GET /interviews/{interview_id}` 的 `data.qa_records` 就是完整问答记录：

```json
[{ "id": 1, "round": 1, "question": "…", "answer": "…", "audio_url": null, "created_at": "…" }]
```

按 `round` 升序；`answer` 为 `null` 表示该题已出、考生尚未作答。

> 数据早就在库里，报告页加个「查看问答记录」入口即可，不需要新接口。
> `created_at` 是本轮新补的字段，用于按时间线展示。
> 建议做成从右侧滑出的抽屉（不跳走，用户不必离开报告页），聊天气泡样式
> （AI 左、用户右）与对话室保持一致，再加一个「复制全文」按钮。

### 2.13 智能推荐学习资源 / 练习计划（2026-09-23 新增）

```
GET /reports/study-plan                          // 聚合最近 5 场 → 个人中心用
GET /reports/study-plan?interview_id=12          // 单场 → 报告页用
GET /reports/study-plan?position=backend&recent=3
```

| 参数 | 说明 |
| :--- | :--- |
| interview_id | 指定单场面试（可选）。**不传 = 按最近 N 场聚合**，一个接口两种用法 |
| position | 岗位 code（可选，仅聚合模式）。与 `interview_id` **互斥**，同传返回 400 |
| recent | 聚合模式下取最近 N 场已结束面试，默认 5（范围 1~20） |
| max_knowledge | 最多返回几个知识点，默认 10（范围 1~50） |

`data` 的形状（精简版，完整字段见 [API.md 4.5](../API.md)）：

```json
{
  "interview_id": 12,                 // 单场模式=该场 ID；聚合模式=null
  "source_interviews": [{ "interview_id": 12, "position": "backend", "finished_at": "…" }],
  "positions": ["backend"],
  "knowledge_points": [{
    "kp_id": "java-backend-kp-0523", "name": "HTTP 响应报文结构",
    "advice": "建议从「HTTP 响应报文结构」的核心定义与基本用法入手……",   // 题库原文
    "priority": "高频必考题", "hit_count": 2,
    "sources": [{ "interview_id": 12, "round": 1,
                  "question_no": "JAVA_BACKEND-Q0043", "question": "GET和POST有什么区别？" }],
    "practice_minutes": 4,
    "practice_questions": [{ "id": 43, "position_code": "backend",
                             "question_no": "JAVA_BACKEND-Q0043", "question": "GET和POST有什么区别？",
                             "category": "技术知识题", "difficulty": "easy",
                             "exam_priority": "高频必考题", "suggested_minutes": 2,
                             "asked": true }]
  }],
  "total_minutes": 44, "pending_minutes": 37,
  "notice": null                      // 非 null 时是「暂无推荐」的原因说明
}
```

**页面摆放建议**：报告页放一张卡片、传 `interview_id`（跟着这场面试走）；个人中心放一个
入口、不传参（跨场的持续练习计划）。两者共用同一个接口，不用写两套逻辑。

> **`notice` 不是错误**：题库未导入、或这场面试的题目是 RAG / AI 现场生成时，接口返回
> 200、`knowledge_points` 为空、`notice` 里写着原因。**按提示文案展示即可，不要弹错误
> toast**——它不是失败，是「暂时没有可推荐的内容」。
>
> **演示前必须先导题库**：`python -m scripts.import_question_bank`。题库为空的机器上出题
> 会走 Mock 兜底，题干永远反查不到题库，这个接口看起来就像「坏了」。另外至少要有一场
> **已结束**的面试——进行中的面试传 `interview_id` 会返回 409。
>
> **知识点口径是「考察过的」，不是「你答得差的」**：后端拿不到单题得分（报告只有 5 维
> 聚合分），所以界面上别写「你答错了这几道」——按「这场面试考察到、建议巩固」的说法
> 呈现才与数据一致。排序已按「高频必考题 → 被多题命中」给好，前端按顺序渲染即可。
>
> **`asked=true` 的题标「已练过」而不是「重做」**：它表示这道题在本计划的来源面试里
> 已经问到过。
>
> **`total_minutes` 与题目清单自洽**：它统计的就是 `practice_questions` 里那批题（同一道
> 题服务多个知识点时只算一次），可直接显示「共约 44 分钟」。实测单场计划约 40~120 分钟
> （每个知识点最多带 5 道配套题），需要的话前端自行截断展示，后端不再做二次裁剪。

### 2.14 简历导入（2026-09-23 新增，个人中心 / 资料页用）

```
POST /resumes                     // 上传简历（PDF / 图片），multipart，file 字段
GET  /resumes/latest              // 最近一份（含提取的全文与建议字段）
GET  /resumes/{resume_id}         // 按 id 读历史
GET  /resumes/{resume_id}/file    // 下载原件（仅本人）
```

`POST /resumes` 的返回（精简版，完整字段见 [API.md 6.3](../API.md)）：

```json
{ "code": 0, "message": "已从 PDF 中提取 1823 字，请核对识别结果后保存", "data": {
  "id": 7, "original_filename": "张三-后端开发.pdf", "file_ext": ".pdf", "file_size": 248913,
  "parse_status": "parsed",
  "parse_message": "已从 PDF 中提取 1823 字，请核对识别结果后保存",
  "text": "张三\n求职意向：Java 后端开发工程师\n学号：20210001\n……",
  "text_preview": "张三\n求职意向：Java 后端开发工程师……",
  "text_length": 1823, "text_truncated": false,
  "suggested": { "nickname": "张三", "student_id": "20210001", "target_position": "backend" },
  "suggested_notes": {
    "nickname": "据文档首行推测：张三（请核对）",
    "student_id": "命中「学号」标签：20210001",
    "target_position": "据「Java 后端开发工程师」判定为 backend"
  },
  "created_at": "2026-09-23T17:20:11"
} }
```

**`parse_status` 只有五种**，前端只需判 `== "parsed"`，其余一律展示 `parse_message`：

| 取值 | 含义 | 前端怎么做 |
| :--- | :--- | :--- |
| `parsed` | 提取成功 | 展示「识别结果」卡片供用户核对 |
| `no_text_layer` | PDF 没有文字层（扫描件、纯图 PDF） | 提示手动填写 |
| `garbled` | 字体编码不支持，提取成乱码 | 提示手动填写 |
| `image_pending` | 图片，当前版本不识别 | 提示手动填写 |
| `failed` | 损坏 / 加密 / 超时 / 缺解析依赖 | 提示手动填写 |

> **预填 ≠ 自动提交**：`suggested` 是**推测**，三个字段都可能为 `null`——后端的原则是
> **抽不到就不猜**（抽错会把用户已经填对的信息引导成错的，预填了用户又懒得改）。
> 请做成「识别结果」卡片 + 「填入表单」按钮，用户点确认后再调 `PUT /auth/me`。
> **绝不要在拿到响应后静默提交**，那会覆盖用户填好的昵称，而用户完全不知道发生了什么。
>
> **`suggested_notes` 要一并展示**：它解释每个值是怎么来的（「据文档首行推测，请核对」／
> 「命中「学号」标签」），是用户判断该不该采纳的唯一依据。
>
> **`parse_message` 不是错误**：解析不出来时接口仍返回 200（文件已安全保存），
> 按普通提示展示即可，**不要弹错误 toast**。
>
> **上传入口**：`<input type="file" accept=".pdf,image/*" capture="environment">`——
> 加 `capture` 后手机能直接调起相机。但 **iPhone 默认拍出 HEIC**，后端白名单不收
> （收了也解析不了），请在 canvas 里转成 JPEG 再传；顺带把 8~12MB 的原图压到 1MB 以内。
>
> **下载原件必须带 token**：`<iframe src="/api/v1/resumes/7/file">` 和 `window.open()`
> 发的都是**不带 `Authorization` 头的普通 GET，拿不到文件**。要用 fetch/axios 带 token、
> `responseType: 'blob'`，再 `URL.createObjectURL(blob)` 预览或触发下载。
>
> **原件不公开**：简历存在私有目录，只有上面那个鉴权接口能读到——**不要试图拼
> `/uploads/...` 的地址**，那里取不到。这是刻意的：`/uploads` 是公开静态目录，
> 而简历含姓名/学号/联系方式。
>
> **`original_filename` 是用户可控字符串**，渲染时用 `textContent` 而非 `innerHTML`。
>
> **隐私提示**：界面上建议加一句「简历仅用于本次面试训练，不会对外分享」。
>
> 读取用 `GET /resumes/latest`（返回同一结构）；**从未上传过时 `data` 为 `null`
> 而不是 404**，页面加载时判 null 显示引导上传的空态即可。

---

## 3. 前端常见错误对照（原 frontend-spec 接口部分已作废，此表防再犯）

### 致命错误（照旧 spec 实现无法联调通过）

| # | 旧 spec 写法 | 后端实际 | 修正 |
|---|---|---|---|
| 1 | 提交回答是 SSE 流式 | 普通 JSON 响应，无 SSE | 按 `finished` 字段判断是否结束 |
| 2 | `POST /api/asr/recognize` 语音转文字接口 | 不存在 | 浏览器 Web Speech API 转写，文本填入 `answer` |
| 3 | 路径缺 `/api/v1` 前缀、路由名错误 | 统一前缀 `/api/v1` | 全部按右侧修正 |
| 4 | 会话标识 `sessionId`（字符串） | `interview.id`（整数） | 全部改用整数 id |

### 字段对照（字段名与类型有变，需逐项替换）

**登录** `POST /api/v1/auth/login`：旧 `data.userId`→`data.user.id`（整数）、
`realName`→`user.nickname`、`token`→`data.access_token`。系统无内置账号，
必须补充注册接口（`POST /auth/register`）与注册/登录页。

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
后端支持 `mp3/wav/webm/m4a/ogg/aac/flac`（≤20MB），直接传 webm。

**结束面试（旧 spec 遗漏）**：

```
POST /api/v1/interviews/{interview_id}/finish
```

响应 `data.report` 即评估报告；对话室需提供「结束面试」按钮。

### 无需担心项

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
| 更新个人资料 | `PUT /auth/me`（PATCH 等价），body `{"nickname"?, "student_id"?, "target_position"?, "avatar_url"?}` | 是 |
| 岗位列表（岗位大厅） | `GET /positions` | 是 |
| 前端运行参数（总轮数） | `GET /config` | 是 |
| 开始面试 | `POST /interviews`，body `{"position": "<岗位接口返回的 code>"}` | 是 |
| 历史面试列表（附分数） | `GET /interviews`，可选 `?position=` | 是 |
| 面试详情（恢复会话 / 问答记录） | `GET /interviews/{interview_id}` | 是 |
| 提交答案并获取下一题 | `POST /interviews/{interview_id}/answers`，body `{"answer", "audio_url"?}` | 是 |
| 主动结束面试 | `POST /interviews/{interview_id}/finish` | 是 |
| 上传录音 | `POST /uploads/audio`（multipart，file 字段） | 是 |
| 上传头像 | `POST /uploads/avatar`（multipart，file 字段） | 是 |
| 评估报告详情 | `GET /reports/{interview_id}` | 是 |
| 生成报告分享链接 | `POST /reports/{interview_id}/share` | 是 |
| 凭分享码看报告（只读页） | `GET /share/{code}` | **否** |
| 最近一次面试建议 | `GET /reports/latest` | 是 |
| 能力成长曲线 | `GET /reports/growth`，可选 `?position=` | 是 |
| 学习资源 / 练习计划 | `GET /reports/study-plan`，可选 `?interview_id=` / `?position=` / `?recent=` | 是 |
| 上传简历并解析 | `POST /resumes`（multipart，file 字段） | 是 |
| 最近一次简历 | `GET /resumes/latest`（无记录时 `data` 为 null） | 是 |
| 下载简历原件 | `GET /resumes/{resume_id}/file`（仅本人，需带 token） | 是 |

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
  成长曲线折线图 + 「查看问答记录」抽屉 + 「生成分享链接」按钮）、
  分享只读报告页（/share/:code，免登录）、
  个人中心（用户信息 + 编辑资料/更换头像 + 岗位筛选 Tab + 历史列表带分数 + 统计卡片 + 最近建议）；
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

## 7. 关于 P1 的演示前端 frontend_test/（示范代码，参考随意）

> **先明确定位**：仓库根目录的 `frontend_test/` 是 P1 在你们正式前端交付前搭的
> 零依赖演示前端（纯 HTML/CSS/JS），用来让整体演示能先跑起来。
> 它是示范代码，不是给你的起点约束：前端的形态、技术栈、交互全部由你（4 号）决定，
> 用不用它都行。

### 它的三条边界

- **不取代你的 `frontend/`**：两者互不相干，你按自己的工程化方式做；
- **不抢端口**：`start.bat` 把它拉起到 5273，特意避开你的 5173 联调端口；
- **不用你处理**：你交付正式前端时（`npm run build` → 构建产物放 `backend/static/`），
  `frontend_test/` 与 5273 的拉起会由 P1 停用/删除。

### 教程：从这份示范里能直接抄到什么

它已实测跑通「注册 → 7 轮面试 → 报告 → 成长曲线」。下面这几处接口调用姿势建议对照着看，
能少踩坑：

| 你要做的事 | 看 `frontend_test/` 的哪一处 | 关键点 |
|---|---|---|
| 统一请求层 | `js/api.js` 的 `request()` | 自动附 `Authorization`；`code!==0` 抛错；`40100` 清 token 跳登录页 |
| 开始面试 → 对话室 | `js/views.js` 的 `Views.interview` | 提交答案后按 `data.finished` 分支：显示下一题 / 跳报告 |
| 恢复进行中的面试 | `Views.interview.render()` 开头 | 每次进对话室都调 `GET /interviews/{id}` 同步，不要依赖内存缓存，轮次可能已推进 |
| 报告页 5 维雷达 + 成长曲线 | `js/charts.js` | 5 轴雷达；曲线取 `GET /reports/growth` 的 `finished_at` / `total_score` |
| **刷新后岗位名不丢** | `Views.report.render()` | 直接用响应里的 `report.position`（见 2.6），不要用内存变量传岗位 code |
| **轮数不硬编码** | `js/app.js` 的 `loadConfig()` | 启动时拉一次 `GET /config`（见 2.7），失败再退回兜底值 |

### 一句话

它是 P1 为了「整体演示能跑」搭的临时实现，完成度按演示标准来。正式前端的
组件化、状态管理、类型约束、构建优化完全交给你，别被它的简陋实现限制住想象力。
