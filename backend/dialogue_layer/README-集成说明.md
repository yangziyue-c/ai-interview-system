# AI 对话层引擎（A11）· 集成说明

这一层是 P5 交付的独立服务，在本项目里作为**可选面试引擎**使用。启用后，出题、追问、五维评分全部委托给它，主后端只负责把每轮问答与最终报告镜像落回本项目的数据库。

## 来源与版本

| 项 | 值 |
| :--- | :--- |
| 来源 | P5 交付包 `A11-AI对话层-后端-1号`（2026-09-23 第二版，`app/__version__ = 1.0.0`） |
| 迁入方式 | `app/`、`personas/`、`smoke_test.py`、`requirements.txt`、`run.ps1` 原样拷贝，未改一行代码 |
| 端口 | 8005（`FRAMEWORK_PORT` 可覆盖） |
| 流程口径 | 10 题制，阶段固定 3/5/2（开场热身 / 核心考察 / 深度压轴）；单题最多追问 2 轮、最多答 3 次 |
| 评分 | reranker 客观覆盖率决定追问动作，五维分由 LLM 评出（1~5 分制） |

与本项目的原链路（7 轮制：1 开场 + 6 追问）并存，由 `backend/.env` 的 `DIALOGUE_ENGINE` 决定走哪条。

## 目录结构

```
backend/dialogue_layer/
├── app/                     服务本体（含 personas/ 五份岗位人设）
├── web/test_chat.html       A11 自带的调试页（只连 8005，不经过主后端）
├── 数据/
│   ├── kg/kg_question_graph.pkl      知识图谱（14.8MB，入库）
│   └── rag/                          RAG 三件（219MB，不入库，见 .gitignore）
├── smoke_test.py            冒烟测试（桩模式，不需要 key，判据「失败 0 项」）
├── requirements.txt         A11 原依赖清单，仅供备查
└── run.ps1                  单机调试入口（本项目正常流程用 backend/start.bat）
```

题库不在此目录，见下一节。原交付包里另有 `样例/`、`面试官完整prompt样例.txt` 与几份说明文档（`交付说明-后端.md` 等）未拷入：前两者含得分点原文，属敏感材料；说明文档留在原包位置可查。

## 数据来源

题库不在本目录，由环境变量 `A11_MAIN_DB` 指向 `backend/rag/数据/`。两处的五个 `*-v5.json` 已按题目内容逐字段核对一致（条数、题目 ID 集合、全部字段取值；字节数差异只来自 JSON 缩进），共用一份可以避免 P5 更新题库后两边漂移。代价是本层不能脱离本仓库独立部署。

知识图谱与 RAG 三件是 A11 独有的数据，已随代码拷入。RAG 默认关闭（`A11_RAG=0`），开启需要约 2.14GB 的 bge-m3 编码器。`数据/rag/` 已加进 `.gitignore`，与本项目的 `rag/vector_db/` 同等对待。

## 启动

正常流程不需要单独操作：`backend/start.bat` 会在主服务就绪后拉起它，与之并列的还有 P3 评估（8002）与 RAG 检索（8003）。端口被占用时跳过拉起，依赖缺失时只打印提示，两者都不阻塞主流程。

单机调试：

```bash
cd backend/dialogue_layer && python app/main.py
```

测试页 `http://localhost:8005/ui/test_chat.html`，接口文档 `http://localhost:8005/docs`。

## 环境变量

`start.py` 的 `build_dialogue_env()` 负责注入，原包 `run.ps1` 里的那份默认值指向交付方本机，不适用本仓库。

| 变量 | 值 | 说明 |
| :--- | :--- | :--- |
| `A11_MAIN_DB` | `backend/rag/数据` | 题库目录 |
| `A11_KG_PATH` | `dialogue_layer/数据/kg/kg_question_graph.pkl` | 知识图谱 |
| `A11_RAG_RETRIEVER_PY`、`RAG_MEM_DIR` | `dialogue_layer/数据/rag` | RAG 三件；`RAG_MEM_DIR` 是裸名，不能加 `A11_` 前缀 |
| `A11_KG` / `A11_RAG` | `1` / `0` | 知识图谱默认开，RAG 默认关 |
| `HF_HOME` | `backend/.hf_cache` | 模型缓存根；与 RAG 服务可共用同一对 bge 模型 |
| `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | `1` | 强制离线，模型需提前下好 |
| `SCORER_DEVICE` | `cpu` | reranker 上显卡可能显存不足，默认走 CPU |
| `DEEPSEEK_API_KEY` | 取 `backend/.env` 的 `LLM_API_KEY` | 密钥只从已 gitignore 的 `.env` 读取，经环境变量传给子进程，不写新文件、不打日志 |

## 依赖与模型

本项目 conda 环境 `ai_interview` 里已有 `torch`、`fastapi`、`sentence-transformers`、`transformers`，只缺 `openai` 一个包，`start.py` 会自动补装。

不采用 A11 声明的版本锁（`sentence-transformers==4.1.0`、`transformers==4.49.0`）：共享环境里的 8003 RAG 服务也用这两个包，按其版本锁降级会连累 RAG。当前环境是 `sentence-transformers 6.0.1` + `transformers 5.17.0`，桩模式冒烟测试 2096 项全过；真模型路径由 `/health` 的 `scorer_ready` 判定。

模型权重不在仓库里（约 2.14GB），首次使用需要下载。国内网络走魔搭：

```bash
cd backend
pip install modelscope
python -c "from modelscope import snapshot_download as d; \
  d('BAAI/bge-reranker-v2-m3', local_dir='.hf_cache/bge-reranker-v2-m3')"
```

下载到 `.hf_cache/bge-reranker-v2-m3/` 后，`start.py` 会把该目录作为模型路径传给子进程（`CrossEncoder` 接受目录路径），不必再设其它变量。

能直连 Hugging Face 时也可以用官方方式：

```bash
cd backend
export HF_HOME="$(pwd)/.hf_cache"
export HF_ENDPOINT=https://hf-mirror.com    # 镜像站，换网络环境时按需替换
export HF_HUB_DISABLE_XET=1                 # 新版客户端默认走 Xet 后端，镜像站不支持，不加会 401
python -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-reranker-v2-m3')"
```

注意：本机实测 `hf-mirror.com` 连不上（SSL 握手超时），`huggingface.co` 直连超时，魔搭正常。换机器时三个源都试一下，不必照抄。

缺模型时服务照常起，但客观覆盖率恒走默认值，分数不可用，`/health` 的 `scorer_ready` 是判据。若要用 RAG，另需 `BAAI/bge-m3`，并把环境变量 `A11_RAG` 设为 `1`。

## 启用与回滚

`backend/.env` 里设 `DIALOGUE_ENGINE=a11` 启用，置空回到原链路。开关是部署级的，改完需要重启主后端。

引擎启用但未就绪时（`/health` 的 `bank_loaded`、`scorer_ready`、`llm_configured` 任一为假），面试接口返回 503 与具体原因，**不回落原链路**。这是刻意的：一场面试的分数如果中途换了口径，事后无法分辨，排查成本远高于一次明确的失败。原链路的 Mock 兜底行为不受影响。

## 落库映射

引擎模式下的数据形状与原链路一致，下游（历史列表、成长曲线、学习计划、报告分享）不需要区分来源。

| 项 | 映射方式 |
| :--- | :--- |
| `interviews.engine` | `'a11'`；原链路为空串。开场时写入，整场只读 |
| `interviews.engine_session_id` | 引擎侧会话 ID（8 位十六进制）。引擎会话在内存里、2 小时后过期，这份留档用于对账 |
| `qa_records` | **每道题一行**，`round` 取引擎的 `q_index`（1 至 10）。追问不落新行，只记进 `engine_turns` |
| `qa_records.question` | 题库原题面，逐字不变。学习计划按题干反查题库，依赖这条不变量 |
| `qa_records.engine_turns` | 本题每次作答的明细：面试官追问原文、判档结果、复读与换题标记 |
| `qa_records.answer` | 该题的作答文本，多次追问时按空行累积 |
| `reports` 六个分数 | 引擎的 1~5 分乘 20 转成 0~100。某一维为 `null` 时用其余维度均值回填 |
| `reports.summary` | 引擎的 `summary` 原文 |
| `reports.engine_meta` | 会话 ID、参与评分轮次、`partial`、`notes`、盲区摘要等。**只存摘要**：引擎 `raw` 里的得分点原文（`base_hit` / `adv_miss` 等）不进本表 |

`strengths` / `weaknesses` / `suggestions` 三栏由主后端从引擎明细推导（`app/core/engine_report.py`）：高分维度与最优轮次的面评转优势，低分维度与盲区弱领域转不足，未覆盖知识点转建议。引擎本身只给一段 `summary`。

换题（引擎侧整轮作废）时，镜像落库同步作废该行，新题复用同一题号。判据是 `done.swapped`，不是 `action == "swap"`：本场名额用尽时引擎仍会给出 `swap` 档，但那一轮照常评分（真跑实测 15 次 `judge_swap` 中只有 4 次真正换掉）。

## 已知差异与边界

- 引擎场是 10 题，原链路是 7 轮。`GET /api/v1/config` 会按当前开关返回对应的总题数，前端胶囊据此渲染。
- 追问不推进题号，前端「第 N 题」在追问期间保持不变。
- 引擎链路**不做 Mock 兜底**，失败即报错（503，错误码 50300）。
- 引擎的 `L3` 追问素材、单题校准锚点等字段本框架未使用，属 A11 的既有边界。
- `web/test_chat.html` 是 A11 自带的调试页，只连 8005，不经过主后端。

## 排障

| 现象 | 检查 |
| :--- | :--- |
| 面试接口返回 503 | 打开 `http://localhost:8005/health`，看 `bank_loaded`、`scorer_ready`、`llm_configured` 哪个为假 |
| `scorer_ready` 长期为 false | 模型是否下好（`backend/.hf_cache/hub/models--BAAI--bge-reranker-v2-m3`）；首次启动要等数十秒预热 |
| 分数恒为 50 左右 | reranker 未加载，答案与得分点的客观比对没有生效 |
| `/start` 报 `llm_unavailable` | `backend/.env` 的 `LLM_API_KEY` 未配置 |
| 改完引擎代码想回归 | 在 `dialogue_layer/` 跑 `smoke_test.py`，判据是「失败 0 项」，项数随 KG / RAG 开关浮动，不必对齐某个数 |
