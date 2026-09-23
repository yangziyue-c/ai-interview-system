# 致 4 号（前端）· 你的接口清单：逐条确认与补充

> **来自**：1 号（后端）
> **针对**：你发来的《致 1 号 · 前端接口需求》
> **依据**：[docs/API.md](../API.md)（接口唯一权威）+ [REPORT_TO_P4.md](REPORT_TO_P4.md)

---

## 一、结论先说

**你清单里要的字段，后端全部都有，可以直接开工，不需要我改任何东西。**

逐条核对见第二节。但有两块功能**你的清单里没有覆盖**——都是客户提出的需求、后端已经实现
（2026-09-23 才加，你手上的文档多半是旧版），见第四节。

---

## 二、逐条核对

按你文档的章节顺序过了一遍，全部满足：

| 你的章节 | 对应接口 | 核对结果 |
| :--- | :--- | :--- |
| 1 登录页 | `POST /auth/login` | ✅ `access_token` + user 六个字段齐全 |
| 2 注册页 | `POST /auth/register` | ✅ 请求体**接受** `student_id`（可选字段） |
| 3 岗位大厅 | `GET /positions` | ✅ `code` / `name` / `description` / `tech_stack` / `focus` |
| 4 岗位详情页 | 无需新接口 | ✅ 你的判断正确，前端缓存里按 `code` 取即可 |
| 5.1 开始面试 | `POST /interviews` | ✅ 会话三字段 + `question` |
| 5.2 提交答案 | `POST /interviews/{id}/answers` | ✅ `finished` + 会话字段 + `next_question` + `report` |
| 5.3 主动结束 | `POST /interviews/{id}/finish` | ✅ `interview.status` + `report` |
| 5.4 恢复会话 | `GET /interviews/{id}` | ✅ `qa_records` 含 `created_at` 时间戳 |
| 5.5 运行参数 | `GET /config` | ✅ `total_rounds` |
| 6.1 报告详情 | `GET /reports/{id}` | ✅ 你列的 11 个字段全有（含报告日期 `created_at`） |
| 6.2 成长曲线 | `GET /reports/growth?position=` | ✅ 每项含 `finished_at` / `total_score` |
| 6.3 分享链接 | `POST /reports/{id}/share` | ✅ `share_url` 由后端按当前 Host 拼好，直接复制 |
| 6.4 免登录分享页 | `GET /share/{code}` | ✅ 返回结构与 6.1 **完全一致**，可复用渲染组件 |
| 6.5 问答历史 | `GET /interviews/{id}` | ✅ 与 5.4 同源，同一份 `qa_records` |
| 7.1 用户信息 | `GET /auth/me` | ✅ |
| 7.2 更新资料 | `PUT /auth/me` | ✅ 三个字段可选；补一个：`avatar_url` 也可传 |
| 7.3 历史列表 | `GET /interviews?position=` | ✅ 列表项**含** `finished_at`（进行中为 `null`）与 `total_score` |
| 7.4 最新建议 | `GET /reports/latest` | ✅ 无数据时 `data: null`（不是 404） |
| 7.5 上传头像 | `POST /uploads/avatar` | ✅ 拿到 `url` 后需再调 `PUT /auth/me` 才生效 |
| 8.1 题库列表 | `GET /questions?...` | ✅ 含 `keywords`（`\n` 分隔）、`exam_priority` 等 |
| 8.2 题目详情 | `GET /questions/{id}` | ✅ 全量字段，结构同 8.1 的 item |
| 9.1 上传录音 | `POST /uploads/audio` | ✅ `data.url` 随答案提交到 `audio_url` |

其中两条我特意去代码里核实过（这两处最容易出岔子）：

- **注册请求确实收 `student_id`**，可以直接放进注册表单；
- **历史列表项确实带 `finished_at`**（继承自 `InterviewOut`），进行中的面试该字段为 `null`。

---

## 三、你开头那张「命名对照」表

逐条都对，可以照用：

| 概念 | 字段名 | 出现位置 |
| :--- | :--- | :--- |
| 岗位代码 | `code` | `GET /positions` |
| 岗位代码 | `position` | 面试、报告、历史、成长曲线、学习计划 |
| 岗位代码 | `target_position` | 用户对象 |
| 面试会话 ID | `id` | 面试相关接口 |
| 面试会话 ID | `interview_id` | 报告、成长曲线、学习计划接口 |
| 知识点 ID | `kp_id` | 学习计划接口（新） |
| 简历 ID | `resume_id` | 简历接口（新） |

---

## 四、你清单里没有覆盖的两块

### 4.1 简历导入（后端已完成）

> **后端已实现并有回归测试覆盖**，接口与约定如下——你的页面接上即可。

```
POST /resumes                     // 上传简历（PDF / jpg / jpeg / png / webp，≤10MB）
GET  /resumes/latest              // 最近一份；从没传过时 data 为 null
GET  /resumes/{resume_id}         // 按 id 读历史
GET  /resumes/{resume_id}/file    // 下载原件（仅本人）
```

`POST /resumes` 返回解析结果 + **建议回填**的 `nickname` / `student_id` / `target_position`。
四条必须知道的：

1. **预填 ≠ 自动提交**：`suggested` 是**推测**，三个字段都可能为 `null`——后端的原则是
   **抽不到就不猜**（抽错会把用户已经填对的信息引导成错的，预填了用户又懒得改）。
   请做成「识别结果」卡片 + 「填入表单」按钮，用户确认后再调 `PUT /auth/me`。
   **不要拿到响应就静默提交**，那会覆盖用户填好的昵称，而用户完全不知道发生了什么。
2. **`parse_status` 五值**，只需判 `== "parsed"`，其余一律展示 `parse_message`：
   `parsed` / `no_text_layer`（扫描件 PDF）/ `garbled`（字体编码不支持）/
   `image_pending`（图片）/ `failed`。**图片当前不做 OCR 是刻意的**——界面上别写成「识别失败」，
   按「原件已保存、识别能力后续接入」来讲。
3. **下载原件必须带 token**：`<iframe src="...">` 和 `window.open()` 发出的是不带
   `Authorization` 头的普通 GET，**拿不到文件**。要用 fetch/axios + `responseType: 'blob'`，
   再 `URL.createObjectURL(blob)`。
4. **不要试图拼 `/uploads/...` 地址**：简历存在私有目录，只有上面那个鉴权接口能读到——
   这是刻意的，简历含姓名/学号/联系方式。

完整字段表与响应示例见 [REPORT_TO_P4.md 2.14](REPORT_TO_P4.md)。

### 4.2 学习资源 / 练习计划（后端已完成）

```
GET /reports/study-plan                    // 聚合最近 5 场（个人中心 / 独立的练习计划入口）
GET /reports/study-plan?interview_id=12    // 单场（报告页）
GET /reports/study-plan?position=backend&recent=3
```

返回「这场面试**考察过的**知识点」+ 题库自带的学习建议原文 + 同知识点的配套练习题
（含总练习时长）。两条必须知道的：

1. **`notice` 不是错误**：题库未导入、或这场题目由 RAG / AI 现场生成时，接口返回 200、
   `knowledge_points` 为空、`notice` 里写着原因。按提示文案展示即可，**不要弹错误 toast**。
2. **口径是「考察过的」而不是「你答得差的」**：后端拿不到单题得分（报告只有 5 维聚合分），
   界面上别写「你答错了这几道」。排序已按「高频必考题 → 被多题命中」给好，按顺序渲染即可。

你之前提到报告界面有「智能建议 / 面试历史 / 能力成长曲线」三个方格——**「智能建议」那个方格
如果指的是这个，接口就是它**（传当前这场的 `interview_id`）。

完整字段表与响应示例见 [REPORT_TO_P4.md 2.13](REPORT_TO_P4.md)。

---

## 五、开工前请重新拉一次 docs/API.md

你这份清单的「依据」写的是 `docs/API.md` + `REPORT_TO_P4.md`，但上面两块是 **2026-09-23**
才加进去的（API.md 的 4.5 与 6.3~6.5；REPORT_TO_P4 的 2.13 与 2.14）。你手上的多半是旧版。

只需回我一件事：**「智能建议」那个方格是不是接 `study-plan`**——是的话接口现成，
字段按 2.13 接即可；不是的话告诉我那个方格打算怎么做，我们对一下别做重了。

有对不上的地方直接找我，改动量应该都不大。
