# 致 4 号（前端）·《前端已实现功能清单》核对结果

> **来自**：1 号（后端）
> **针对**：你发来的《前端已实现功能清单.md》《前端已实现功能与其对应接口对接.md》
> **依据**：[docs/API.md](../API.md)（接口唯一权威）+ [REPORT_TO_P4.md](REPORT_TO_P4.md)

---

## 一、结论先说

你对照表里的 **25 条接口路径与方法全部正确**，包括你自己标了「待确认」的
`POST /interviews/{id}/answers`，那个复数是对的。

对不上的是 **6 处字段名**，集中在学习计划与简历两块。这两处的根源都不在你：
你手上那份 `REPORT_TO_P4.md` 是 2026-09-23 之前的版本，那两节当时还不存在；
另外我上一份回执的命名对照表里把简历 ID 写错了一个，下面一并更正。

动作只有两步：`git pull` 拉一次 `docs/reports/`，然后按第三节改 6 个字段名。
另外你报告页等的 `partial` 字段后端已经补上，见第四节，那一处不用改。
其余部分照现有实现继续即可。

---

## 二、先拉一次文档

`REPORT_TO_P4.md` 的 `2.13 智能推荐学习资源 / 练习计划` 与 `2.14 简历导入` 两节，
加入时间是 **2026-09-23**（提交 `cb60918`）。在那之前的版本里，本文档到 `2.12`
就结束了。你写「2.13 节没找到」，实际情况是那一版里确实没有这两节。

这两节现已写全字段名与示例，`4. 正确接口速查表` 也补上了 `study-plan` 与 `resumes`
两组接口。你清单里那几处「字段名待核对」，答案都在里面。

另有 [REPORT_TO_P4_A11_ENGINE.md](REPORT_TO_P4_A11_ENGINE.md)（2026-09-26 更新），
讲后端接入 P5 对话层后的三处字段加法与两个新接口。你的清单里没有引擎链路的痕迹，
建议一并看，第七节末尾有一条前端的必做项。

### 更正：上一份回执里的一处错误

[REPORT_TO_P4_API_CHECKLIST.md](REPORT_TO_P4_API_CHECKLIST.md) 第三节「命名对照」表里
原文写着「简历 ID → `resume_id`」，**这一条是错的**，已订正为：对象里的字段名是 `id`，
`resume_id` 只是下载接口的路径参数名（`/resumes/{resume_id}/file`）。
你写成 `resume_id` 多半是从这张表抄的，是我写坏的。

---

## 三、字段名需要改的地方

### 3.1 学习计划（`GET /reports/study-plan`）

| 你的写法 | 后端实际 |
| :--- | :--- |
| `knowledge_points[].title` | `knowledge_points[].name` |
| `knowledge_points[].suggestion` | `knowledge_points[].advice` |
| `knowledge_points[].question_count` | `knowledge_points[].hit_count` |

`notice` 与 `total_minutes` 是对的，`knowledge_points` 这个数组名也是对的。

每个知识点下还有几项可以直接渲染：`priority`（考点优先级）、`sources[]`
（这个知识点在哪场面试的第几轮被问到）、`practice_minutes`、`practice_questions[]`
（配套练习，其中 `asked` 为 `true` 表示这道题在本计划的来源面试里已经问到过，
标「已练过」而不是「重做」）。顶层另有 `positions` 与 `pending_minutes`，
个人中心的聚合模式会用到。

### 3.2 简历（`/resumes` 的三个读取接口返回同一结构，一套渲染通吃）

| 你的写法 | 后端实际 |
| :--- | :--- |
| `resume_id` | `id` |
| `file_name` | `original_filename` |
| `uploaded_at` | `created_at` |

`file_size` / `parse_status` / `parse_message` / `suggested.*` 都是对的。

你的清单里没写、但**需要用**的两项：

- **`suggested_notes`**：`suggested` 里每个值的来源说明，形如「据文档首行推测：张三（请核对）」
  「命中「学号」标签：20210001」。后端已经拼好整句，原样展示即可。它是用户判断该不该
  采纳的唯一依据，不要自己编文案。
- **`text_preview`**：提取全文的前 300 字，供折叠态直接渲染，省得前端对长字符串再切一刀。

另外 `parse_status` 是**五种**，不是四种。你列的四项正好对应前四种，还差一个
`failed`（文件损坏 / 加密 / 解析超时 / 缺解析依赖），处理方式与其他非 `parsed` 的值
一样：展示 `parse_message`，引导用户手动填写。五种取值与前端动作的对应表在 2.14 节。

---

## 四、`partial` 已补上，`notes` 不下发

你报告页用 `partial` / `notes` 做「评分不完整提示」。这两个字段原先**不在
`GET /reports/{id}` 的响应里**，读出来恒为 `undefined`，那张卡片不会出现；
API.md 里找不到示例，正是因为它们当时不对外。它们的位置是 `reports.engine_meta`
这一列，存的是引擎链路的内部明细（会话 ID、参与评分轮次、换题次数等）。

**`partial` 已于 2026-09-27 补上**，字段名与你写的完全一致，判断逻辑不用改：

```json
{ "total_score": 84.5, "...": "其余字段不变", "partial": false, "review": null }
```

- `true` 表示本场有轮次未能完成评分，分数可能不全。只有引擎链路会出现，且是评分
  真的失败过的场次；原链路与评分完整的场次恒为 `false`。
- 三个报告出口都带它：`GET /reports/{id}`、`POST /interviews/{id}/finish` 的 `report`、
  以及免登录的 `GET /share/{code}`。

`notes` 没有下发，也不建议用：它是引擎的内部口径（例如「本场换过 1 题，原因：…」），
引擎已经把该说的话拼进了 `summary`，再发一份给前端只会多一处口径来源。
原先的替代做法（从 `weaknesses` 里匹配「有 N 轮评分未能完成」）现在不需要了。

---

## 五、你标了「待核对」的几处

| 你的疑问 | 答复 |
| :--- | :--- |
| 提交答案用 `/interviews/{id}/answers`（复数） | 对的，就是复数，不用改 |
| `POST /interviews` 返回结构 | `{ interview: {...}, question: "..." }`，开场 `current_round` 恒为 `1` |
| `report` 结构 | 与 `GET /reports/{id}` 的 `data` 完全一致，同一个 `ReportOut` |
| 面试详情 `answer` 为 `null` 的语义 | **该题已出、考生尚未作答**。出题即落库、作答回填，所以最新一轮正在等答的那道就是 `null`，不是答题失败 |
| 面试列表 `status` 枚举 | 三种：`idle` / `in_progress` / `finished`。落库的只有后两个，`idle` 是建会话到开场之间的过渡态，失败会整体回滚，列表里见不到，按两种处理即可 |
| 成长曲线无数据 | `[]`，不是 `null` |

---

## 六、会踩的边界

| 场景 | 后端行为 | 前端要处理的 |
| :--- | :--- | :--- |
| 已有进行中的面试时再开一场 | **409**：你有一场进行中的面试，请先完成或结束它 | 「重新面试」需先结束旧场；你的「断点续答」正好对上这条约束 |
| 一题未答就点「主动结束」 | **400**：没有任何有效回答，无法生成报告 | 按钮前置拦截，或捕获后提示先作答 |
| 面试未结束或报告未生成时看报告 | **409**，不是 404 | 别按 404 分支写 |
| `GET /reports/latest`，从未完成过面试 | `data` 为 `null` | 空态处理 |
| `GET /resumes/latest`，从未上传过 | `data` 为 `null` | 空态处理，不是 404 |
| `GET /auth/me` | `data` **直接就是**用户对象 | 不是 `data.user`，按 `data.nickname` 这样读 |
| 分享链接的地址形式 | 后端按当前请求 Host 拼 `#/share/{code}` | **hash 路由**，前端路由形式要对得上 |
| 题库列表传了非法的 `category` / `difficulty` / `stage` | **400**，不是返回空集 | 筛选值从受控词表取，别让用户自由输入 |

---

## 七、清单里没有覆盖的后端能力

这几项后端已经能跑，你的清单里没有对应条目，按需接：

| 能力 | 接口 | 说明 |
| :--- | :--- | :--- |
| 成长档案 | `GET /reports/archive` | 错题本 / 考点地图 / 历史成绩，按岗位聚合。没有档案或引擎不可用时返回 `available: false` 加 `notice`，不是错误 |
| 考后复盘 | `GET /reports/{id}` 的 `review` 字段 | 漏点、已覆盖、下一步动作、注意事项，文案由后端拼好。`frontend_test/` 的报告页已渲染成卡片，可参考 |
| 语音转写 | `POST /uploads/audio/asr` | 一次调用同时返回文本与 `url`，文件只传一遍 |
| 对话层引擎 | `GET /config` 的 `engine` 字段、`GET /reports/growth` 的 `engine` 字段与 `?engine=` 参数 | 后端可在两种链路间切换（`DIALOGUE_ENGINE=a11`），`total_rounds` 会从 7 变成 10 |

最后一行如果打开，前端有一件必须做的事：**请求超时不能设短**。引擎侧在外部大模型
偶发卡住时不返 5xx，而是把超时预算跑完再收尾，所以提交答案的超时要 ≥540 秒、
结束面试 ≥360 秒。低于这个值，正常场次会被前端自己掐断，而后端日志里看不到任何异常。
原链路模式下不受影响。

---

## 八、顺手可以改的两处

- **语音输入**：你用的是 Vosk 离线识别。中文识别效果如果不理想，可以换
  `POST /uploads/audio/asr`（后端本地跑 faster-whisper）。转写文本填进输入框让考生
  改一遍再发送，返回的 `url` 直接作为 `audio_url` 提交，同一个文件不必传两次。
  要注意它未就绪时返回 503，**别当空文本处理**，那会被当成「考生没说话」。

- **报告页的「重新面试」**：它会撞上第六节第一条那个 409。建议先查一次
  `GET /interviews`，确认没有 `in_progress` 的场次再发起。

---

接口细节以 [docs/API.md](../API.md) 为准；本文档与它不一致时，以 API.md 为准，
并告诉我改本文档。
