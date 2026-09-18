# 数据库设计文档

## 一、技术选型

| 维度 | 方案 | 理由 |
| :--- | :--- | :--- |
| ORM | SQLAlchemy 2.0（异步） | 与 FastAPI 异步栈统一；类型注解风格（`Mapped`/`mapped_column`） |
| 开发/演示环境 | SQLite（aiosqlite） | 零配置，双击 start.bat 即跑，比赛现场不依赖外部服务 |
| 正式环境 | MySQL（aiomysql） | 修改 `.env` 中 `DATABASE_URL` 一行切换，同一套代码零改动 |
| 缓存 | Redis（可选） | `REDIS_URL` 未配置时自动降级为进程内缓存，功能等价 |

切换 MySQL 的步骤：

```sql
-- 先在 MySQL 中建库
CREATE DATABASE interview_db DEFAULT CHARACTER SET utf8mb4;
```

```ini
# backend/.env
DATABASE_URL=mysql+aiomysql://root:你的密码@127.0.0.1:3306/interview_db
```

启动时自动建表（`create_all`，只创建不存在的表，不影响已有数据）。

## 二、ER 关系总览

```
users (用户)
  │ 1
  ├────────────────┐
  │ 1              │
interviews (面试会话)      status: idle → in_progress → finished
  │ 1                    current_round: 已提问到第几轮
  ├────────────────┬─────────────────┐
  │ N              │ 1               │ N
qa_records (问答记录)    reports (评估报告)      report_shares (报告分享)
  round: 第几轮          五个维度分数 + 评语    分享码 + 有效期 + 访问计数

positions (岗位表，独立无外键)
  启动时自动 seed 5 个岗位位，enabled 控制上/下线

questions (题库表，独立无外键，按 position_code 关联岗位)
  由 scripts/import_question_bank.py 从 backend/rag/数据/*-v5.json 导入，供面试官算法抽题
```

- 1 个用户 → N 场面试
- 1 场面试 → N 条问答记录 + 1 份评估报告（严格一对一）
- 1 场面试 → N 个分享码（有效期内的至多 1 个，重复生成会复用）
- 岗位由 positions 表动态维护（替代硬编码枚举），预留 5 个岗位位
- 题库由 questions 表承载（V5 换代，5 岗位共 5012 题：backend 2146 + frontend 734 + test_engineer 667 + algorithm 655 + system_design 810），算法按岗位/阶段/难度抽题

模型代码见 [backend/app/models/](../backend/app/models/)。

## 三、表结构详解

### 1. users：用户表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| username | varchar(64) | unique + index | 登录账号，唯一索引防重复注册 |
| password_hash | varchar(256) | not null | bcrypt 哈希，不存明文 |
| nickname | varchar(64) | 默认空串 | 展示昵称 |
| student_id | varchar(32) | nullable | 学号（可选，个人中心展示用） |
| target_position | varchar(16) | 默认 backend | 目标岗位 code（动态，见 positions 表） |
| avatar_url | varchar(512) | nullable | 头像地址，形如 `/uploads/avatars/1_ab3f9c2d.png`；为空时前端用昵称首字母占位。老库由 `database.py::_ensure_column` 补列 |
| created_at | datetime | server_default=now() | 注册时间，由数据库生成 |

### 2. interviews：面试会话表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| user_id | int | FK→users，index，级联删除 | 归属用户 |
| position | varchar(16) | not null | 本场面试岗位 |
| status | varchar(16) | index，默认 idle | 状态机字段：idle → in_progress → finished |
| current_round | int | 默认 0 | 已提问轮数（1=开场题，2~7=追问），也是下一轮问答写入 round=几 的指针 |
| created_at | datetime | server_default=now() | 会话创建时间 |
| started_at | datetime | nullable | 面试开始时间（状态转入 in_progress 时写入） |
| finished_at | datetime | nullable | 面试结束时间（转入 finished 时写入，支撑成长曲线排序） |

### 3. qa_records：问答记录表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| interview_id | int | FK→interviews，index，级联删除 | 所属面试 |
| round | int | not null | 第几轮（1 起），与 interviews.current_round 联动 |
| question | text | not null | AI 面试官提问，出题时写入 |
| answer | text | nullable | 考生回答，作答时回填；null = 已出题未作答 |
| audio_url | varchar(512) | nullable | 录音文件地址，供 P3 语音识别评估 |
| created_at | datetime | server_default=now() | 记录创建时间 |

### 4. reports：评估报告表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| interview_id | int | FK→interviews，unique + index，级联删除 | 一场面试严格一份报告 |
| total_score | float | not null | 综合得分（按岗位 5 维加权） |
| tech_score | float | not null | 技术水平（0~100） |
| logic_score | float | not null | 逻辑思维（0~100） |
| expression_score | float | not null | 沟通表达（0~100） |
| adaptability_score | float | not null | 应变能力（0~100，2026-09-04 新增）。模型定义无默认值；老库经 `ALTER TABLE` 补列时带 `DEFAULT 0.0`，启动时把仍为 0 的历史报告用表达分自愈回填 |
| match_score | float | not null | 岗位匹配度（0~100） |
| summary | text | not null | 综合评语 |
| strengths | JSON | 默认 [] | 优势列表（条数不固定） |
| weaknesses | JSON | 默认 [] | 不足列表 |
| suggestions | JSON | 默认 [] | 改进建议列表 |
| created_at | datetime | server_default=now() | 报告生成时间 |

综合得分按岗位 5 维加权（源自《评估维度.csv》），
权重单一事实源为 [evaluation_weights.py](../backend/app/core/evaluation_weights.py) 的 `POSITION_CONFIG`
（主后端 Mock 兜底与评估服务均经 `weights_for()` 派生），
`tests/test_api.py` 的 `test_weights_match_csv` 机器校验 CSV ↔ 代码一致性：

| 岗位 code | 技术 | 逻辑 | 表达 | 应变 | 匹配 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| backend | 35% | 25% | 10% | 10% | 20% |
| frontend | 30% | 20% | 15% | 15% | 20% |
| test_engineer | 25% | 25% | 20% | 15% | 15% |
| algorithm | 35% | 30% | 10% | 10% | 15% |
| system_design | 30% | 30% | 15% | 10% | 15% |

### 5. report_shares：报告分享表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| interview_id | int | FK→interviews，index，级联删除 | 被分享报告所属的面试（报告与面试严格一对一，故直连 interviews） |
| share_code | varchar(32) | unique + index | 分享码，`uuid4().hex`（128 位随机），即分享链接里的那一串 |
| created_at | datetime | server_default=now() | 生成时间 |
| expires_at | datetime | not null | 过期时间 = 生成时刻 + `SHARE_EXPIRE_DAYS`（默认 7 天） |
| view_count | int | 默认 0 | 被访问次数，每次成功读取 +1 |

> 字段名是 `interview_id` 而不是需求文档里写的 `report_id`——需求文档自己也注明
> 「报告 ID（即 interview_id）」，直接叫 interview_id，免得后人误以为要 join `reports.id`。
> 同一份报告重复生成会复用尚未过期的分享码，因此一个 interview_id 可能对应多行
> （历史过期码 + 当前有效码），查询一律带 `expires_at` 条件。

### 6. positions：岗位表（独立无外键）

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| code | varchar(32) | unique + index | 岗位唯一标识（注册/面试传此值，如 backend） |
| name | varchar(64) | not null | 岗位中文名（前端大厅展示） |
| description | text | 默认空串 | 岗位简介 |
| tech_stack | JSON | 默认 [] | 技术栈列表（前端岗位详情展示） |
| focus | JSON | 默认 [] | 考察重点列表 |
| enabled | bool | 默认 true | 是否开放；为 false 的岗位不在 `/positions` 列表下发 |
| sort_order | int | 默认 0 | 岗位大厅展示顺序 |
| created_at | datetime | server_default=now() | |

启动时若表为空，自动 seed 5 个岗位（V5 换代后全部启用：backend / frontend / test_engineer / algorithm / system_design，见 [position.py](../backend/app/models/position.py) 的 `DEFAULT_POSITIONS`）；老库由 `database.py::_align_positions` 幂等对齐（占位岗位位改名 + 缺失岗位补插），岗位清单调整只需更新数据库记录，无需改代码。

### 7. questions：面试题库表（独立无外键）

数据由 [import_question_bank.py](../backend/scripts/import_question_bank.py) 从
`backend/rag/数据/*-v5.json`（V5 格式（2026-09-14 换代），5 岗位共 5012 题）导入，
幂等可重跑。V5 相比 V4 的变化：题型由 6 类收敛为 4 类、面试阶段由 4 个收敛为 3 个
（新增「深度压轴」、去掉「收尾交流」）、三级追问由一整段混合文本拆成 L1/L2/L3 三个独立字段、
新增单题校准锚点与关联知识点。字段规范/导入命令/加岗流程见
[docs/reports/REPORT_TO_P5.md](reports/REPORT_TO_P5.md)。

> **注意**：表结构换代涉及删列，无法自动迁移。老库须执行一次
> `python -m scripts.import_question_bank --rebuild --yes`（会自动 `VACUUM INTO` 备份）。
> 忘了跑会由 `database.py::_warn_questions_schema` 在启动时打 ERROR 日志提示。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| position_code | varchar(32) | index | 岗位 code，与 positions 表对齐 |
| question_no | varchar(32) | unique(position_code, question_no) | **V5 原题 ID**（如 `JAVA_BACKEND-Q0001`），与 RAG 向量库元数据「原题ID」同键 |
| category | varchar(32) | not null | 题型：技术知识题 / 场景应用题 / 项目经历题 / 行为素质题 |
| difficulty | varchar(16) | not null | 难度：easy / medium / hard |
| question | text | not null | 题干（可直接读给候选人） |
| interview_stage | varchar(16) | not null | 面试阶段：开场热身(1) / 核心考察(2) / 深度压轴(3) |
| stage_order | int | not null | 阶段顺序 1~3（V5 无该列，导入时按阶段派生） |
| suggested_minutes | int | 默认 0 | 建议用时(分钟) |
| keywords | text | 默认空串 | 核心关键词（换行分隔） |
| exam_priority | varchar(16) | 默认空串 | 考点优先级：常规题 / 高频必考题 / 拓展题 |
| basic_score_points | text | 默认空串 | 基础得分点 |
| advanced_score_points | text | 默认空串 | 进阶得分点 |
| follow_up_l1 | text | 默认空串 | L1 基础追问（原文含 `[触发]` / `[追问]` 标记行） |
| follow_up_l2 | text | 默认空串 | L2 递进追问 |
| follow_up_l3 | text | 默认空串 | L3 拓展追问（31% 的题为 3 行，首行是难度元信息） |
| fallback_strategy | text | 默认空串 | 降级策略（考生答不出时的引导话术） |
| calibration_anchor | text | 默认空串 | **单题校准锚点**（[技术水平]/[岗位匹配度] 判分标准，评估素材） |
| related_knowledge | text | 默认空串 | 关联知识点（`{ID}\|{名称}\|{学习建议}` 多行） |

查询接口：`GET /api/v1/questions`（按岗位/题型/难度/阶段/优先级过滤 + 分页，见 [API.md](API.md)）。

## 四、关键设计决策

1. **岗位表化（替代硬编码枚举）**：岗位数量与清单在开发期会频繁调整，故将岗位从代码枚举下沉到 `positions` 表：注册/开始面试时查库校验（无效岗位 400）、前端岗位大厅读 `GET /positions`、Mock 题库按 code 匹配（缺省回退通用池）。新增/下线岗位只需改数据库记录，代码零改动。启动 seed 幂等（表空才插入，不覆盖已有数据）。
2. **双数据库策略**：`DATABASE_URL` 可配置。SQLite 用于开发与演示，比赛现场不依赖外部服务；MySQL 用于正式环境。同一套 ORM 代码，切换零改动。
3. **状态机与数据库解耦**：`status` 存字符串，状态合法性由代码层状态机保证（[state_machine.py](../backend/app/core/state_machine.py)）。转换规则表驱动（`_TRANSITIONS`），非法转换抛 409。新增状态不改表结构，比数据库 ENUM 灵活。
4. **current_round 指针设计**：会话表只存"进行到第几轮"一个指针，问答明细全在 qa_records，无冗余；轮次上限判断只需比较 `current_round >= 1 + MAX_FOLLOW_UP_ROUNDS`。
5. **出题即落库、作答再回填**：qa_records 在出题时 INSERT、作答时 UPDATE，任何时刻不会出现"有答案无问题"的脏数据，也天然支持为 P2 重建完整对话历史。
6. **报告一对一 unique 约束**：数据库层面约束一场面试只能生成一份报告。
7. **级联删除**（`ondelete=CASCADE` + `delete-orphan`）：删除用户/面试自动清理全部关联数据，无孤儿记录。
8. **索引最小化**：只在真实查询路径建索引：登录按 username、面试列表按 user_id、报告按 interview_id、状态筛选按 status、题库按 position_code。不建冗余索引。
9. **题库表化（V5）**：题库 json（`backend/rag/数据/*-v5.json`）由导入脚本落库（questions 表），面试官算法（`backend/interviewer_new/`）按岗位/阶段/难度从库抽题；题库更新只需重跑导入脚本，代码零改动。V5 的关键改进是把三级追问拆成独立列：V4 时代下游要用 119 行正则从一段混合文本里挖结构化信息，现在直接读字段即可（详见 [REPORT_TO_P2_INTERVIEWER_NEW.md](reports/REPORT_TO_P2_INTERVIEWER_NEW.md)）。
10. **分享码与登录解耦**：分享是外发场景，接收方没有账号，故分享码独立成表，`GET /share/{code}` 是全站唯一免登录的业务接口。安全性靠三点：码为 128 位随机、不可枚举；有有效期；「不存在」与「已过期」返回同一提示，不泄露哪个码真实存在。
11. **用户输入不当作可信 URL**：`users.avatar_url` 只接受 `/uploads/avatars/` 下的站内路径，外部地址、`javascript:`、路径穿越一律 400。前端会把它直接塞进 `<img src>`，放开任意字符串等于允许用户互相注入。头像上传本身也校验文件头，防止改扩展名把非图片内容托管到静态目录。

## 五、数据流示例（一场完整面试的落库过程）

```
POST /interviews
  → interviews  INSERT (status=idle)
  → 状态机校验  idle → in_progress，写入 started_at、current_round=1
  → qa_records  INSERT (round=1, question=开场题)

POST /interviews/{id}/answers（每次提交答案）
  → qa_records  UPDATE (回填 answer / audio_url)
  → 未达上限：interviews.current_round +1 → qa_records INSERT (下一轮问题)
  → 达到上限：转入结束流程（见下）

POST /interviews/{id}/finish（手动结束或达到轮次上限自动触发）
  → 状态机校验  in_progress → finished，写入 finished_at
  → 调用 P3 适配器评估（超时降级 Mock）
  → reports     INSERT (五个维度分数 + 评语)

GET /reports/growth
  → JOIN interviews × reports，WHERE status=finished，ORDER BY finished_at ASC

POST /reports/{id}/share
  → 复用该面试尚未过期的分享码；没有则 INSERT report_shares (share_code=uuid4, expires_at=now+7d)

GET /share/{code}（免登录）
  → SELECT report_shares WHERE share_code=? AND expires_at > now
  → 命中：view_count +1，返回与 GET /reports/{id} 结构一致的报告
  → 未命中或已过期：一律 404（不区分二者）
```

## 六、相关文件索引

| 内容 | 位置 |
| :--- | :--- |
| ORM 模型 | [backend/app/models/](../backend/app/models/) |
| 引擎与会话 | [backend/app/database.py](../backend/app/database.py) |
| 缓存抽象（Redis/内存） | [backend/app/redis_client.py](../backend/app/redis_client.py) |
| 状态机 | [backend/app/core/state_machine.py](../backend/app/core/state_machine.py) |
| 环境变量模板 | [backend/.env.example](../backend/.env.example) |
