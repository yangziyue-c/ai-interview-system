# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CLAUDE.md — AI 模拟面试系统项目指令

## 项目总览与团队分工

AI 模拟面试训练系统（FastAPI 异步 + SQLAlchemy 2.0，5 人小组项目）：

| 成员 | 职责 | 代码/文档位置 |
| :--- | :--- | :--- |
| P1（本机） | 主后端 + 集成 | `backend/app/` |
| P2 | 面试官出题算法 | `backend/interviewer_new/`（V5 版；旧 `backend/interviewer/` 已冻结留档） |
| P3 | AI 评估服务 | `backend/evaluator_new/`（独立 Flask 进程，端口 8002；旧 `backend/evaluator/` 留档） |
| P4 | 前端 | `frontend/`（构建产物拷 `backend/static/` 同端口挂载） |
| P5 | 知识库 | `backend/rag/数据/*-v5.json`（5012 题）+ 向量库；服务代码 `backend/rag/代码/` |

对接文档在 `docs/reports/REPORT_TO_P2~P5.md`；接口唯一权威 `docs/API.md`。
**P2 修改算法只动 `backend/interviewer_new/`**（其 README 有算法速览与与旧版差异），
P3 只动 `backend/evaluator_new/`，P5 只产 `backend/rag/数据/*-v5.json` 与向量库；
`backend/app/` 是集成层，别把成员代码塞进来。
**目录归属与各成员 API 清单见 `docs/reports/REPORT_TEAM_V5_LAYOUT_AND_API.md`**。
P1 维护的零依赖**演示前端**在 `frontend_test/`（`start.bat` 自动拉起到 5273，P4 正式前端交付前的整体演示入口；与 P4 的 `frontend/` 互不相干、不抢 5173 联调端口）。

## 常用命令（conda 环境 ai_interview）

> `conda run` 有插件 bug，**直接调用环境内 python.exe**。本机实测路径
> `D:/anaconda3/envs/ai_interview/python.exe`，环境真实位置以 `conda env list` 为准。

```bash
# 一键启动：RAG 检索（8003）+ P3 评估（8002）+ 演示前端（5273）+ 主服务（8001），
# 就绪后打印访问指引（本机+局域网地址），Ctrl+C 一并退出
cd backend && 双击 start.bat        # 或 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 测试：必须在 backend/ 目录下跑（pytest.ini 的 asyncio_mode、conftest 的 env 切换都在这里生效）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m pytest        # 66 个用例全绿
D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_question_bank.py -q   # 单文件
D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_api.py::TestAuth::test_login_wrong_password  # 单用例

# 题库导入（backend/rag/数据/ 有新 *-v5.json 后重跑；必须用 -m，直接 python scripts/xxx.py 会因 sys.path 找不到 app 包）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.import_question_bank --dry-run          # 先看统计不落库
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.import_question_bank --rebuild --yes    # 表结构变更时（含自动备份）

# 面试流程仿真（算法/数据改动后的效果度量：收尾题出现率、Mock 兜底次数）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.simulate_interview --rounds 200
```

- 测试库 `test_interview.db`：conftest 在 import 时自动删除重建并注入环境变量
  （DATABASE_URL 指向测试库、清空 LLM_API_KEY 防误调真实大模型）——**不会碰开发库 interview.db**
- 测试造数用共享工厂 `backend/tests/helpers.py` 的 `make_question()`（question_no 自动随机后缀防唯一约束冲突）

## 代码架构（大图）

**目录布局**：`backend/app/`（主应用包）+ `backend/interviewer_new/`、`backend/evaluator_new/`、`backend/rag/`
（成员成果目录，主应用 import/拉起）。

### 面试出题：五级数据源链（app/adapters/ai_interviewer.py）

```
题库策略(interviewer_new/) > RAG语义检索(8003) > AI_INTERVIEWER_URL(外部扩展位) > LLM 直连 > 内置 Mock
```

- **题库策略是最高优先级**：查 questions 表（**5012 题 / 5 岗位**：backend 2146 + frontend 734 +
  test_engineer 667 + algorithm 655 + system_design 810），岗位有题即走题库
- RAG 语义检索为兜底（题库未命中时生效；V5 题库覆盖良好，多数场次不会触发）；
  主动使用入口 = `POST /api/v1/rag/search`（透传，服务不可用时返回 `available:false` 而非 500）
- 每级失败自动落下一级，流程永不中断；超时预算分档：**RAG 级 60 秒**（reranker 精排慢，
  实测单次 20~30 秒），其余 HTTP/LLM 级各 15 秒
- SQLite 已配 **WAL + busy_timeout**（database.py 事件监听），并发写不会锁库；
  适配器题库查询自开只读短会话，**不要复用请求级会话传 db**（会触发 autoflush 提前锁库）
- 核心业务规则（interviewer_new/question_bank.py）：1 开场题 + 6 追问共 7 轮（`MAX_FOLLOW_UP_ROUNDS=6`）；
  开场=开场热身+easy；**round 6/7 强制换新题**（收尾题池按 `category=行为素质题`——V5 无「收尾交流」阶段）；
  追问按锚点+层级 L1→L2→L3→降级，**L1 触发用语义分流**（答不出→降级引导，否则→L1，命中率 100%）

### 评估与报告（P3 + 主后端兜底）

- `backend/evaluator_new/`（Flask 8002，V5 增强版：按题注入单题校准锚点评分）由 start.py
  自动拉起；主后端 `app/adapters/ai_evaluator.py` 负责附加素材 + Mock 兜底，调用失败自动降级
  （旧 `backend/evaluator/` 保留留档，`start.py` 已不引用它）
- 报告 **5 维评分**（技术/逻辑/表达/应变/匹配），各岗位权重单一事实源 =
  `app/core/evaluation_weights.py` 的 `POSITION_CONFIG`（源自根目录《评估维度.csv》，
  `tests/test_api.py::test_weights_match_csv` 机器校验两者一致——改 CSV 或权重必须同步跑该测试）
- 老库启动自愈：`adaptability_score` 为 0 时用 expression_score 近似回填（database.py init_db）

### 领域约定（改代码前必读）

- **统一响应** `{code, message, data}`；错误码 0/40000/40100/40300/40400/40900/50000
  （app/core/exceptions.py 的 AppException 子类，HTTP 状态码自动对应）
- **受控词表单一来源**：题库 category（**4 类：技术知识题/场景应用题/项目经历题/行为素质题**）、
  difficulty（easy/medium/hard）、stage（**3 个：开场热身/核心考察/深度压轴**）常量定义在
  `app/models/question.py`；`app/api/questions.py` 校验非法值返回 400
  （题库改名后立刻报错而非静默空集）。改词表只改 question.py，查询接口与导入脚本自动跟随
- **状态机**：面试 status 由 `app/core/state_machine.py` 表驱动（idle→in_progress→finished），
  非法转换抛 409；QA 记录"出题即落库、作答回填"
- **题库流水线**：`backend/rag/数据/*-v5.json`（V5，18 字段：题干/基础进阶得分点/L1-L3 追问/
  降级策略/校准锚点/关联知识点等）→ `backend/scripts/import_question_bank.py`（幂等；`--rebuild --yes` 重建表）
  → questions 表（**19 列**）；字段规范与加岗流程 = `docs/reports/REPORT_TO_P5.md`
- **questions 表换代注意**：表结构由 18 列重构为 19 列（涉及删列），**无法自动迁移**——
  老库需跑一次 `python -m scripts.import_question_bank --rebuild --yes`；
  忘了跑会由 `database.py::_warn_questions_schema` 在启动时打 ERROR 日志提示
- **算法效果回归**：改数据或算法后跑 `scripts/simulate_interview.py`，判据是
  **Mock 兜底 0 次 + 收尾题 100% 出现**（当前基线：5 岗位 × 400 场全达标）

## 环境与部署铁律（踩过血的坑）

- **端口**：8001=主后端、8002=P3 评估、**8003=RAG 检索**、5273=演示前端（start.py 自动拉起）；
  **8000 被本机 Godot AI MCP 占用，勿改回**；5173 是 P4 Vite 联调端口，start.py 不会占用
- **RAG 大文件与依赖**：`backend/rag/vector_db/`（674MB）、`backend/rag/数据/*-rag-v2.jsonl`（85MB）
  已 gitignore；RAG 依赖（torch 等约 2.5GB）单独放 `backend/rag/requirements-rag.txt`，
  **不要写进 `backend/requirements.txt`**（会让每个新环境都被强加 2.5GB）；
  模型文件（约 4.5GB）首次启动时自动下载（默认 huggingface.co；网络受限时设 HF_ENDPOINT=https://hf-mirror.com 走镜像）
- **RAG 向量库目录必须纯 ASCII**（`backend/rag/vector_db/`，**禁止中文名**）：
  chromadb 打不开「含非 ASCII 字符的**绝对路径**」——实测 10/10 失败并报
  `Error loading hnsw index`，极易误判成「向量库损坏 / chromadb 版本不兼容」
  （曾因此白跑一次 6 小时重建）。**构建侧同样受影响**：用中文绝对路径建库会产出
  缺 HNSW 索引文件的坏库。旧目录名「向量库」已废弃，5 个 RAG 脚本会自动改名升级；
  任何移动向量库的操作都要保证新路径全 ASCII
- **RAG 检索是慢接口**：单次 `/rag/search` 含 Top-20 reranker 精排，CPU 上实测
  **20~30 秒**（向量召回本身仅 0.1 秒，瓶颈全在 reranker）。故 `RAG_TIMEOUT_SECONDS=60`，
  **不要按普通接口设成个位数秒**——那会让每次检索都被误判为「RAG 不可用」而白白降级
- **`backend/start.bat` 必须 CRLF 行尾且纯 ASCII**（无中文注释/echo）——cmd 对 LF-only 或中文 REM
  解析错乱；`.gitattributes` 已设 `*.bat -text`。改后校验：
  `python -c "open('backend/start.bat','rb').read().count(b'\r\n')"` 应等于行数；中文提示放 start.py
- **内网穿透**：Sakura Frp Web 隧道 + 自动 HTTPS，访问必须 https://（http 被 501 拦截），
  详见 docs/DEPLOY.md

## 双远程推送规则（每次提交必须执行）

| 远程 | 地址 |
| :--- | :--- |
| `origin` | https://github.com/yangziyue-c/ai-interview-system |
| `gitee` | https://gitee.com/yangziyuegit/ai-interview-system |

**每次 git commit 后必须同时推送到两个远程**（提交前先 `git pull origin main` 同步，内容保持一致）：

```bash
git push origin main && git push gitee main
```
