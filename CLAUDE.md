# CLAUDE.md — AI 模拟面试系统项目指令

This file provides guidance to Claude Code when working in this repository.

## 项目总览与团队分工

AI 模拟面试训练系统（FastAPI 异步 + SQLAlchemy 2.0，5 人小组项目）：

| 成员 | 职责 | 代码/文档位置 |
| :--- | :--- | :--- |
| P1 | 主后端 + 集成 | `backend/app/` |
| P2 | 面试官出题算法 | `backend/interviewer_new/`（V5 版；旧 `backend/interviewer/` 已冻结留档） |
| P3 | AI 评估服务 | `backend/evaluator_new/`（独立 Flask 进程，端口 8002；旧 `backend/evaluator/` 留档） |
| P4 | 前端 | `frontend/`（⚠️ 当前**仅有 README.md**、正式代码未交付；构建产物将拷 `backend/static/` 同端口挂载） |
| P5 | 知识库 + AI 对话层 | `backend/rag/数据/*-v5.json`（5012 题）+ 向量库；服务代码 `backend/rag/代码/`；`backend/dialogue_layer/`（独立服务 8005，见「AI 对话层引擎」节） |

对接文档在 `docs/reports/`：4 份独立对接文档 `REPORT_TO_P2/P3/P4/P5.md`，
另有 `REPORT_TEAM_V5_LAYOUT_AND_API.md`（目录归属与各成员 API 清单）、`REPORT_TO_P5_V5_PACKAGE_REVIEW.md`。
**P2/P3 现行权威为 `REPORT_TO_P2_INTERVIEWER_NEW.md` / `REPORT_TO_P3_EVALUATOR_NEW.md`**；
`REPORT_TO_P2.md` 与 `REPORT_TO_P3.md` 顶部均已挂 V5 指引横幅、正文为 V4 口径，仅留档参考。接口唯一权威 `docs/API.md`。
**P2 修改算法只动 `backend/interviewer_new/`**（其 README 有算法速览与与旧版差异），
P3 只动 `backend/evaluator_new/`，P5 只动 `backend/rag/` 与 `backend/dialogue_layer/`；
`backend/app/` 是集成层，别把成员代码塞进来。
**目录归属与各成员 API 清单见 `docs/reports/REPORT_TEAM_V5_LAYOUT_AND_API.md`**。
**竞赛提交材料**（项目概要介绍 / 项目简介 PPT / 项目详细方案）按模块分册存放于 `docs/submission/`，
命名 `0N-材料名-P<成员>部分.md`（现已有 P1 三份）；每册开头含「拼接说明」与术语替换提示，
合并为完整提交包时按提示把 P1~P5 编号统一改为岗位角色名（如「后端开发 A」）。
P1 维护的零依赖**演示前端**在 `frontend_test/`（由 `backend/start.bat` 自动拉起到 5273，P4 正式前端交付前的整体演示入口；与 P4 的 `frontend/` 互不相干、不抢 5173 联调端口）。

## 常用命令（conda 环境 ai_interview）

> `conda run` 有插件 bug，**直接调用环境内 python.exe**。本机实测路径
> `D:/anaconda3/envs/ai_interview/python.exe`（**P1 本机路径；其他成员请替换为自己 conda 环境内的解释器**），
> 环境真实位置以 `conda env list` 为准。
> 测试隔离机制、SQLite 并发配置、超时分档、`start.bat` 编码校验等**机制性说明见 `docs/DEVELOPMENT.md`**。
>
> ⚠️ **首次手动启动前需 `cp backend/.env.example backend/.env`**（`start.bat` 会自动生成，手动
> `uvicorn` 那条路不会）。关键默认值坑：`AI_EVALUATOR_URL` 默认为**空串**，而适配器规则是
> "未配置 URL → 直接返回内置 Mock"——**没有 .env 时，即使 8002 评估服务在跑，所有报告也都静默
> 走 Mock 兜底**；`RAG_API_URL` 默认指向本机 8003。若 `.env` 已存在则看不出差异，换环境才会暴露。

```bash
# 一键启动：RAG 检索（8003）+ P3 评估（8002）+ 演示前端（5273）+ 主服务（8001），
# 就绪后打印访问指引（本机+局域网地址），Ctrl+C 一并退出
cd backend && 双击 start.bat        # 或 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 测试：必须在 backend/ 目录下跑（pytest.ini 的 asyncio_mode、conftest 的 env 切换都在这里生效）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m pytest        # 151 个用例全绿
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_question_bank.py -q   # 单文件
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_api.py::TestAuth::test_login_wrong_password  # 单用例

# 题库导入（backend/rag/数据/ 有新 *-v5.json 后重跑；必须用 -m，直接 python scripts/xxx.py 会因 sys.path 找不到 app 包）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.import_question_bank --dry-run          # 先看统计不落库
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.import_question_bank --rebuild --yes    # 表结构变更时（含自动备份）

# 面试流程仿真（算法/数据改动后的效果度量：收尾题出现率、Mock 兜底次数）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.simulate_interview --rounds 200
```

- conftest 在**导入应用之前**注入隔离环境变量：切到测试库，并清空 6 个外部依赖地址
  （`LLM_API_KEY`、`AI_INTERVIEWER_URL`、`AI_EVALUATOR_URL`、`RAG_API_URL`、`REDIS_URL` 等），**不会碰开发库**；
  造数工厂与用例分布明细见 `docs/DEVELOPMENT.md` §2.2 / §2.3

## 代码架构（大图）

**目录布局**：`backend/app/`（主应用包）+ `backend/interviewer_new/`、`backend/evaluator_new/`、
`backend/dialogue_layer/`、`backend/rag/`（成员成果目录，主应用 import/拉起）。

**缓存抽象（`app/redis_client.py`，约 100 行）**：Redis 与进程内双实现，配置 `REDIS_URL` 时探活并启用、
**任何异常自动降级为进程内实现**（未配置则直接用内存版）。⚠️ 当前**仅 `main.py` lifespan 预热调用，
业务侧尚未接入真实读写**——它是就绪的降级能力与扩展位，对材料/汇报**不要表述为已投产的性能优化**。

### 面试出题：五级数据源链（app/adapters/ai_interviewer.py）

```
题库策略(interviewer_new/) > RAG语义检索(8003) > AI_INTERVIEWER_URL(外部扩展位) > LLM 直连 > 内置 Mock
```

- **题库策略是最高优先级**：查 questions 表（**5012 题 / 5 岗位**：backend 2146 + frontend 734 +
  test_engineer 667 + algorithm 655 + system_design 810），岗位有题即走题库
- RAG 语义检索为兜底（题库未命中时生效；V5 题库覆盖良好，多数场次不会触发）；
  主动使用入口 = `POST /api/v1/rag/search`（透传，服务不可用时返回 `available:false` 而非 500）
- 每级失败自动落下一级，流程永不中断；超时预算分三档：**RAG 级 60 秒**（reranker 精排慢，
  实测单次 20~30 秒）、**P3 评估 30 秒**（`ai_evaluator.py` 的 EVALUATE_TIMEOUT_SECONDS，不占通用档）、
  其余 HTTP/LLM 适配器 15 秒（`config.py` 的 ADAPTER_TIMEOUT_SECONDS）
- **适配器里的题库查询自开只读短会话，不要复用请求级会话传 db**（会触发 autoflush 提前锁库）；
  WAL + busy_timeout 的并发配置见 `docs/DEVELOPMENT.md` §三
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

### AI 对话层引擎（可选链路：P5 的 A11，`backend/dialogue_layer/`）

- 独立 FastAPI 服务（**8005**，源码一行未改），`start.py` 在 RAG 之后拉起；开关 `DIALOGUE_ENGINE=a11`
  （`.env`，默认空 = 关）。开启后出题/追问/五维评分全部委托它，主后端只镜像落库
- **引擎链路 10 题制**（3/5/2 阶段），与原链路 7 轮制并存；链路在 `POST /interviews` 时定死、整场只读
  （`interviews.engine`），中途不切换
- **未就绪即报 503（错误码 50300），不回落原链路**：半场换口径事后无从分辨。就绪判据是 `/health` 的
  `bank_loaded` + `scorer_ready` + `llm_configured`——**该端点恒返回 200，不能只看状态码**
- **落库口径**：`qa_records` 每道题一行（`round` = 引擎的 `q_index`），**追问不落新行、只记进 `engine_turns`**；
  `question` 保持题库原题面逐字不变——学习计划与评分素材按题干反查题库，靠这条不变量
- 报告：引擎 1~5 分制 ×20 换算（`app/core/engine_report.py`），三栏由主后端从引擎明细推导；
  `reports.engine_meta` **只存摘要**，引擎 raw 里的得分点原文不进本表
- **语音转写**：`POST /uploads/audio/asr` 转发给引擎的 `/asr`（faster-whisper 本地模型），
  一次调用同时返回文本与 `audio_url`（前端不必传两次）。情感模型在魔搭上没有、本部署关闭
  （`A11_ASR_EMOTION=0`，`emotion*` 恒为 null）。引擎侧有内存门槛（start.py 注入
  `A11_ASR_MIN_FREE_MB=800`）：内存不足时转写返 503 而不是硬加载到 OOM
- **成长档案**：每场 `/finish` 的顶层 `digest` 存进 `reports.digest`。
  ⚠️ 该 JSON 列**必须带 `none_as_null=True`**——默认行为会把 Python 的 None 存成 JSON 的
  `null` 字面量，于是「原链路场次没有档案」会被 `IS NOT NULL` 误判成「有」。
  `GET /reports/archive` 把已存的 digest 原样回传给引擎的 `/growth`，取错题本 / 考点地图 / 历史成绩
- 题库复用 `backend/rag/数据/`（与 A11 自带那份已逐字段核对一致），不拷第二份；
  模型缓存 `backend/.hf_cache`（已 gitignore）：reranker 2.27GB + whisper-small 464MB，
  下载与环境清单见 `dialogue_layer/README-集成说明.md`

### 领域约定（改代码前必读）

- **统一响应** `{code, message, data}`；错误码 0/40000/40100/40300/40400/40900/50000/50300
  （app/core/exceptions.py 的 AppException 子类，HTTP 状态码自动对应；50300 = 依赖服务不可用）
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
- **岗位有三套命名，勿混用**：展示名（`app/models/position.py::DEFAULT_POSITIONS`，如「后端开发工程师」）/
  交付包与 RAG 过滤用的全名（`app/adapters/ai_interviewer.py`，如「Java 后端开发工程师」）/
  CSV 别名简名（如「Java 后端」，由导入脚本 `POSITION_MAP` 归一到 code）。
  **RAG 过滤传错会静默返回空集**——代码注释对此有原始警告
- **算法效果回归**：改数据或算法后跑 `scripts/simulate_interview.py`，判据是
  **Mock 兜底 0 次 + 收尾题 100% 出现**（基线 5 岗位全达标）。
  注意 `--rounds N` 是"每岗位每类考生 N 场"，脚本再乘 2 类考生，故 `--rounds 200` = 每岗位 400 场

## 环境与部署铁律（踩过血的坑）

- **端口**：8001=主后端、8002=P3 评估、**8003=RAG 检索**、**8005=AI 对话层引擎**、5273=演示前端（start.py 自动拉起）；
  **8000 由 P1 本机的 Godot AI MCP 占用，全组统一用 8001，勿改回**；5173 是 P4 Vite 联调端口，start.py 不会占用
- **RAG 大文件与依赖**：`backend/rag/vector_db/`（674MB）、`backend/rag/数据/*-rag-v2.jsonl`（约 70MB）
  已 gitignore；RAG 依赖（torch 等约 2.5GB）单独放 `backend/rag/requirements-rag.txt`，
  **不要写进 `backend/requirements.txt`**（会让每个新环境都被强加 2.5GB）；
  模型文件（约 4.5GB）首次启动时自动下载（默认 huggingface.co；网络受限时设 HF_ENDPOINT=https://hf-mirror.com 走镜像）
- **RAG 向量库目录必须纯 ASCII**（`backend/rag/vector_db/`，**禁止中文名**）：
  chromadb 打不开「含非 ASCII 字符的**绝对路径**」——实测 10/10 失败并报
  `Error loading hnsw index`，极易误判成「向量库损坏 / chromadb 版本不兼容」
  （曾因此白跑一次 6 小时重建）。**构建侧同样受影响**：用中文绝对路径建库会产出
  缺 HNSW 索引文件的坏库。旧目录名「向量库」已废弃，4 个 RAG 脚本（02~05）会自动改名升级；
  任何移动向量库的操作都要保证新路径全 ASCII
- **RAG 检索是慢接口**：单次 `/rag/search` 含 Top-20 reranker 精排，CPU 上实测
  **20~30 秒**（向量召回本身仅 0.1 秒，瓶颈全在 reranker）。故 `RAG_TIMEOUT_SECONDS=60`，
  **不要按普通接口设成个位数秒**——那会让每次检索都被误判为「RAG 不可用」而白白降级
- **`backend/start.bat` 必须 CRLF 行尾且纯 ASCII**（无中文注释/echo）——cmd 对 LF-only 或中文 REM
  解析错乱；`.gitattributes` 已设 `*.bat -text`。**中文提示一律放 start.py**；改后校验脚本见
  `docs/DEVELOPMENT.md` §五
- **内网穿透**：Sakura Frp Web 隧道 + 自动 HTTPS，访问必须 https://（http 被 501 拦截），
  详见 docs/DEPLOY.md

## 双远程推送规则（仅 P1，每次提交必须执行）

> 本节约束同时持有 GitHub（origin）与 Gitee 推送权的 P1；P2~P5 按各自远程推送即可。

**每次 git commit 后必须同时推送到两个远程**（提交前先 `git pull origin main` 同步）：

远程地址见 `git remote -v`：`origin` 走 **SSH**（P1 本机 `~/.ssh/config` 里配了 `ssh.github.com:443` 端口回退，
22 端口不通时靠它，**勿删该配置**）；`gitee` 走 HTTPS。

```bash
git push origin main && git push gitee main
```
