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
  ├────────────────┐
  │ N              │ 1
qa_records (问答记录)    reports (评估报告)
  round: 第几轮          四个维度分数 + 评语

positions (岗位表，独立无外键)
  启动时自动 seed 5 个岗位位，enabled 控制上/下线
```

- 1 个用户 → N 场面试
- 1 场面试 → N 条问答记录 + 1 份评估报告（严格一对一）
- 岗位由 positions 表动态维护（替代硬编码枚举），预留 5 个岗位位

模型代码见 [backend/app/models/](backend/app/models/)。

## 三、表结构详解

### 1. users —— 用户表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| username | varchar(64) | unique + index | 登录账号，唯一索引防重复注册 |
| password_hash | varchar(256) | not null | bcrypt 哈希，不存明文 |
| nickname | varchar(64) | 默认空串 | 展示昵称 |
| student_id | varchar(32) | nullable | 学号（可选，个人中心展示用） |
| target_position | varchar(16) | 默认 backend | 目标岗位：backend / frontend |
| created_at | datetime | server_default=now() | 注册时间，由数据库生成 |

### 2. interviews —— 面试会话表（核心）

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

### 3. qa_records —— 问答记录表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| interview_id | int | FK→interviews，index，级联删除 | 所属面试 |
| round | int | not null | 第几轮（1 起），与 interviews.current_round 联动 |
| question | text | not null | AI 面试官提问，出题时写入 |
| answer | text | nullable | 考生回答，作答时回填；null = 已出题未作答 |
| audio_url | varchar(512) | nullable | 录音文件地址，供 P3 语音识别评估 |
| created_at | datetime | server_default=now() | 记录创建时间 |

### 4. reports —— 评估报告表

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| interview_id | int | FK→interviews，unique + index，级联删除 | 一场面试严格一份报告 |
| total_score | float | not null | 综合得分（加权） |
| tech_score | float | not null | 技术能力（0~100） |
| logic_score | float | not null | 逻辑思维（0~100） |
| expression_score | float | not null | 表达沟通（0~100） |
| match_score | float | not null | 岗位匹配度（0~100） |
| summary | text | not null | 综合评语 |
| strengths | JSON | 默认 [] | 优势列表（条数不固定） |
| weaknesses | JSON | 默认 [] | 不足列表 |
| suggestions | JSON | 默认 [] | 改进建议列表 |
| created_at | datetime | server_default=now() | 报告生成时间 |

综合得分加权：`total = tech×0.35 + logic×0.25 + expression×0.20 + match×0.20`（见 [ai_evaluator.py](backend/app/adapters/ai_evaluator.py)）。

### 5. positions —— 岗位表（独立无外键）

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | int | 主键自增 | |
| code | varchar(32) | unique + index | 岗位唯一标识（注册/面试传此值，如 backend） |
| name | varchar(64) | not null | 岗位中文名（前端大厅展示） |
| description | text | 默认空串 | 岗位简介 |
| tech_stack | JSON | 默认 [] | 技术栈列表（前端岗位详情展示） |
| focus | JSON | 默认 [] | 考察重点列表 |
| enabled | bool | 默认 true | 是否开放；占位岗位位置 false，不在岗位列表下发 |
| sort_order | int | 默认 0 | 岗位大厅展示顺序 |
| created_at | datetime | server_default=now() | |

启动时若表为空，自动 seed 5 个岗位位（3 个已开放 + 2 个占位待定，见 [position.py](backend/app/models/position.py) 的 `DEFAULT_POSITIONS`）；岗位清单确定后只需更新数据库记录，无需改代码。

## 四、关键设计决策

1. **岗位表化（替代硬编码枚举）**：岗位数量与清单在开发期会频繁调整，故将岗位从代码枚举下沉到 `positions` 表——注册/开始面试时查库校验（无效岗位 400）、前端岗位大厅读 `GET /positions`、Mock 题库按 code 匹配（缺省回退通用池）。新增/下线岗位只需改数据库记录，代码零改动。启动 seed 幂等（表空才插入，不覆盖已有数据）。
2. **双数据库策略**：`DATABASE_URL` 可配置。SQLite 保证演示/开发零依赖成功率；MySQL 体现正式环境技术能力；同一套 ORM 代码，切换零改动。
3. **状态机与数据库解耦**：`status` 存字符串，状态合法性由代码层状态机保证（[state_machine.py](backend/app/core/state_machine.py)）。转换规则表驱动（`_TRANSITIONS`），非法转换抛 409。新增状态不改表结构，比数据库 ENUM 灵活。
4. **current_round 指针设计**：会话表只存"进行到第几轮"一个指针，问答明细全在 qa_records，无冗余；轮次上限判断只需比较 `current_round >= 1 + MAX_FOLLOW_UP_ROUNDS`。
5. **出题即落库、作答再回填**：qa_records 在出题时 INSERT、作答时 UPDATE，任何时刻不会出现"有答案无问题"的脏数据，也天然支持为 P2 重建完整对话历史。
6. **报告一对一 unique 约束**：数据库层面杜绝一场面试两份报告。
7. **级联删除**（`ondelete=CASCADE` + `delete-orphan`）：删除用户/面试自动清理全部关联数据，无孤儿记录。
8. **索引最小化**：只在真实查询路径建索引——登录按 username、面试列表按 user_id、报告按 interview_id、状态筛选按 status。不建冗余索引。

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
  → reports     INSERT (四个维度分数 + 评语)

GET /reports/growth
  → JOIN interviews × reports，WHERE status=finished，ORDER BY finished_at ASC
```

## 六、相关文件索引

| 内容 | 位置 |
| :--- | :--- |
| ORM 模型 | [backend/app/models/](backend/app/models/) |
| 引擎与会话 | [backend/app/database.py](backend/app/database.py) |
| 缓存抽象（Redis/内存） | [backend/app/redis_client.py](backend/app/redis_client.py) |
| 状态机 | [backend/app/core/state_machine.py](backend/app/core/state_machine.py) |
| 环境变量模板 | [backend/.env.example](backend/.env.example) |
