# AI 对话层引擎（A11）· 集成说明

这一层是 P5 交付的独立服务，在本项目里作为**可选面试引擎**使用。启用后，出题、追问、五维评分全部委托给它，主后端只负责把每轮问答与最终报告镜像落回本项目的数据库。

## 来源与版本

| 项 | 值 |
| :--- | :--- |
| 来源 | P5 的四个交接包：`A11-Backend-Handoff-v20260929`、`A11-KB-Data-Handoff-v20260929`、`A11-RAG-Data-Handoff-v20260929`、`A11-Backend-Private-Handoff-20260929` |
| 迁入方式 | `app/`、`quality/`、`web/`、`smoke_test.py` 与交付文档原样拷贝，**引擎代码未改一行** |
| 端口 | 8005（`FRAMEWORK_PORT` 可覆盖） |
| 接口 | 12 个端点：原有的 10 个，本版新增 `/tts`（面试官朗读）与 `/body-language/analyze`（体态分析） |
| 流程口径 | 10 题制，阶段固定 3/5/2；单题最多追问 2 轮、最多答 3 次 |
| 评分 | 1~5 分制由 LLM 评出；reranker 走**在线**（硅基流动），不再常驻本地 2.2GB 模型 |
| 本版新增 | 面试官朗读、体态分析、简历模式、客观题评分、知识库检索（KB）、总结守卫 |

接口契约的权威在交付包的 `API_CONTRACT.md`（同目录），它以「只增不改」为准则：已有字段不删、不改名、不改类型。上一版接入的调用面因此不受影响。

与本项目的原链路（7 轮制：1 开场 + 6 追问）并存，由 `backend/.env` 的 `DIALOGUE_ENGINE` 决定走哪条。

## 目录结构

```
backend/dialogue_layer/
├── app/                     服务本体（含 personas/ 人设与 core/ 各能力模块）
├── quality/                 体态分析的算法本体
│   └── body_language.py     ⚠️ 被 app/api/body_language.py import，**不能与 app/ 分开搬**
├── web/
│   ├── test_chat.html       A11 自带的调试页（只连 8005，不经过主后端）
│   ├── body_camera.html     摄像头体态页
│   ├── resume_setup.html    简历模式页
│   └── vendor/mediapipe/    MediaPipe 运行时（约 29MB，浏览器本地提关键点用）
├── 数据/
│   ├── kg/kg_question_graph.pkl      知识图谱（14.8MB，入库）
│   ├── 学习资源样例.json              4a 学习资源的素材源（4.7MB，入库）
│   ├── rag/                          RAG 三件（约 256MB，不入库）
│   ├── kb_index/                     知识库检索索引（约 150MB，不入库）
│   └── models/sensevoice-small/      语音转写模型（约 239MB，不入库）
├── smoke_test.py            冒烟测试（桩模式，不需要 key，判据「失败 0 项」）
├── requirements-handoff.txt 轻量在线模式所需依赖（本版新增 sherpa-onnx）
├── check_env.py             ⚠️ 上一版的自检工具：检的是旧依赖（faster-whisper 等），
│                               本机跑会报一堆 FAIL，那些 FAIL 不代表环境有问题
├── build_kb_index.py        ⚠️ 上一版的建库脚本：本版索引随数据包提供，不需要重建
├── dump_prompt.py           上一版的 prompt 调试工具，留档
├── requirements.txt         上一版的依赖清单，留档备查
└── run.ps1                  上一版的单机调试入口（本项目正常流程用 backend/start.bat）
```

题库不在此目录，见下一节。交付方另发的 `API_CONTRACT.md`、`DEPLOYMENT.md`、`START_HERE.md`、`RESUME_INTEGRATION.md` 一并放在本目录，作为其原始说明留档。

## 数据来源

**题库**不在本目录，由环境变量 `A11_MAIN_DB` 指向 `backend/rag/数据/`。两处的五个 `*-v5.json` 已按题目内容逐字段核对一致（条数、题目 ID 集合、全部字段取值；字节数差异只来自 JSON 缩进），共用一份可以避免 P5 更新题库后两边漂移。代价是本层不能脱离本仓库独立部署。

**知识图谱**与**学习资源样例**是 A11 独有的数据，随代码入库。

**RAG 索引**（`数据/rag/`，74011 条）与**知识库索引**（`数据/kb_index/`，20396 块）来自两个数据包。前者服务引擎的 RAG 旁路，后者服务「学习资源的知识库参考」与「面试时的知识库证据通道」。索引目录**不入库**，换机器时从数据包解压到位。

**SenseVoice 语音模型**（`数据/models/sensevoice-small/`，239MB）随后端包提供，无公开下载路径，同样不入库。

## 启动

正常流程不需要单独操作：`backend/start.bat` 会在主服务就绪后拉起它，与之并列的还有 P3 评估（8002）与 RAG 检索（8003）。端口被占用时跳过拉起，依赖缺失时只打印提示，两者都不阻塞主流程。

单机调试：

```bash
cd backend/dialogue_layer && python app/main.py
```

测试页 `http://localhost:8005/ui/test_chat.html`，接口文档 `http://localhost:8005/docs`。

**轻量 / 全功能**：与 P5 的 `start_a11.ps1` 同一条口径，默认轻量（RAG 与 KB 关，内存友好）。在 `backend/.env` 里设 `DIALOGUE_FULL=1` 开全功能——那会启用 RAG 与 KB，代价是首次 `/finish` 时加载本地 bge-m3 编码器（约 2.2GB 常驻）。

## 环境变量

`start.py` 的 `build_dialogue_env()` 负责注入（原包的 `run.ps1` / `start_a11.ps1` 里的默认值指向交付方本机，不适用本仓库）。除下表外，引擎另有一批能力开关（`A11_GROWTH` / `A11_REVIEW` / `A11_PRACTICE` / `A11_MODEL_ANSWER` / `A11_PERSONA` / `A11_INTRO` / `A11_RECOMMEND` 等）默认就是开，不需要显式设置。

| 变量 | 值 | 说明 |
| :--- | :--- | :--- |
| `A11_MAIN_DB` | `backend/rag/数据` | 题库目录 |
| `A11_KG_PATH` | `dialogue_layer/数据/kg/kg_question_graph.pkl` | 知识图谱 |
| `A11_RAG_RETRIEVER_PY`、`RAG_MEM_DIR` | `dialogue_layer/数据/rag` | RAG 三件；`RAG_MEM_DIR` 是裸名，不能加 `A11_` 前缀 |
| `A11_KB_DIR` | `dialogue_layer/数据/kb_index` | 知识库索引目录 |
| `SENSEVOICE_MODEL_DIR` | `dialogue_layer/数据/models/sensevoice-small` | 语音转写模型 |
| `A11_RESOURCES_JSON` | `dialogue_layer/数据/学习资源样例.json` | 学习资源素材源 |
| `A11_KG` / `A11_RAG` / `A11_KB_REC` / `A11_RAG_KB` | `1` / `0` / `0` / `0` | 轻量档默认值；`DIALOGUE_FULL=1` 时后三项转 `1` |
| `A11_RERANKER_PROVIDER` | 有硅基流动 key 时用引擎默认的 `siliconflow`，否则 `local` | 在线省 2.2GB 常驻内存，但依赖网络 |
| `SCORER_DEVICE` | `cpu` | 本地 reranker 走 CPU（上显卡可能显存不足） |
| `A11_ASR_MIN_FREE_MB` | `800` | 转写的内存门槛（引擎默认 1200；本机 15.2GB 偏紧，按实测占用下调） |
| `HF_HOME` | `backend/.hf_cache` | 模型缓存根 |
| `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | `1` | 强制离线，模型需提前下好 |
| `DEEPSEEK_API_KEY`、`SILICONFLOW_API_KEY`、`DASHSCOPE_API_KEY` | 取 `backend/.env` | 见下节 |

`A11_RAW_DETAIL` 保持引擎默认的 `0`（脱敏档）：`/finish` 与 `/result` 的 `raw` 只剩占位键，得分点原文不出门。

### 三家密钥

| 密钥 | 用途 |
| :--- | :--- |
| DeepSeek（`LLM_API_KEY`） | 主观评分与追问判档；同时供主后端的 LLM 直连兜底 |
| 硅基流动（`SILICONFLOW_API_KEY`） | 在线 reranker 与 embedding（KB 检索用） |
| DashScope（`DASHSCOPE_API_KEY`） | 客观题评分、面试官朗读（TTS）、在线语音转写 |

三家都由 P5 的 **Private 交接包**提供（那份 README 明确要求不许上传 GitHub、云盘或公开群）。本项目把密钥落在 **`backend/.env`**（已 gitignore），`start.py` 从那里读、只经环境变量传给子进程，不写新文件、不打日志。`.env` 里的键名与引擎侧一致，便于对照。

引擎侧多数派生项自带 fallback（`A11_RERANK_API_KEY` ← `SILICONFLOW_API_KEY`、`A11_OBJECTIVE_API_KEY` / `A11_TTS_API_KEY` / `A11_ASR_ONLINE_API_KEY` ← `DASHSCOPE_API_KEY`），**但 `A11_EMBEDDING_API_KEY` 没有**——`start.py` 会显式补上，漏了它 KB 检索恒不可用。

## 依赖与模型

本项目 conda 环境 `ai_interview` 里已有 `torch`、`fastapi`、`sentence-transformers`、`transformers`、`python-multipart`、`onnxruntime`，本版另外补装了语音转写需要的 **`sherpa-onnx`**（1.13.8）。上一版用的 `faster-whisper` / `ctranslate2` 在本版已不需要（转写模型换成了 SenseVoice，走 sherpa-onnx）。

不采用 A11 声明的版本锁（`sentence-transformers==4.1.0`、`transformers==4.49.0`）：共享环境里的 8003 RAG 服务也用这两个包，按其版本锁降级会连累 RAG。

模型权重不在仓库里：

| 模型 | 位置 | 来源 |
| :--- | :--- | :--- |
| SenseVoice（转写） | `dialogue_layer/数据/models/sensevoice-small/` | P5 后端包自带，解压即用 |
| reranker（本地回退用） | `backend/.hf_cache/bge-reranker-v2-m3/` | ModelScope 下载（2.27GB），**只有在没有硅基流动 key 时才需要** |
| 情感模型（wav2vec2） | `backend/.hf_cache/wav2vec2-base-superb-er/` | P5 于 2026-09-26 直接给的权重（361MB） |

情感模型**只在 provider 不是 sensevoice 时才会加载**：默认档下情感标签由 SenseVoice 自己给（`/health` 的 `emotion_model` 会显示 `sensevoice-small-int8`），wav2vec2 那份是留给切回 whisper 档的回退。两个 `.hf_cache` 模型都不入 git，每台机器各自准备。

若某天要直连 Hugging Face：`HF_ENDPOINT=https://hf-mirror.com` 配合 `HF_HUB_DISABLE_XET=1`（新版客户端默认走 Xet 后端，镜像站不支持会返 401）。

## 启用与回滚

`backend/.env` 里设 `DIALOGUE_ENGINE=a11` 启用，置空回到原链路。开关是部署级的，改完需要重启主后端。

引擎启用但未就绪时（`/health` 的 `bank_loaded`、`scorer_ready`、`llm_configured` 任一为假），面试接口返回 503 与具体原因，**不回落原链路**。这是刻意的：一场面试的分数如果中途换了口径，事后无法分辨，排查成本远高于一次明确的失败。原链路的 Mock 兜底行为不受影响。

**正式服务的归属**（2026-09-29 定）：8005 暂时由 P5 运行，本项目的 `DIALOGUE_ENGINE_URL` 指向对方地址；等引擎定稿后再切回本项目自运行。同一时间只认一套为正式环境，禁止混用会话与报告。

## 落库映射

引擎模式下的数据形状与原链路一致，下游（历史列表、成长曲线、学习计划、报告分享）不需要区分来源。

| 项 | 映射方式 |
| :--- | :--- |
| `interviews.engine` | `'a11'`；原链路为空串。开场时写入，整场只读 |
| `interviews.engine_session_id` | 引擎侧会话 ID（8 位十六进制）。引擎会话在内存里、2 小时后过期，这份留档用于对账 |
| `qa_records` | **每道题一行**，`round` 取引擎的 `q_index`（1 至 10）。追问不落新行，只记进 `engine_turns` |
| `qa_records.question` | 题库原题面，逐字不变。学习计划按题干反查题库，依赖这条不变量 |
| `qa_records.engine_turns` | 本题每次作答的明细：面试官追问原文、判档结果、复读与换题标记 |
| `reports` 六个分数 | 引擎的 1~5 分乘 20 转成 0~100。某一维为 `null` 时用其余维度均值回填 |
| `reports.summary` | 引擎的 `summary` 原文 |
| `reports.engine_meta` | 会话 ID、参与评分轮次、`partial`、`notes`、盲区摘要等。**只存摘要**：引擎 `raw` 里的得分点原文不进本表 |
| `reports.digest` | 每场的成长档案摘要（4~7KB，白名单构造、不含得分点原文），供 `GET /reports/archive` 原样回传给引擎的 `/growth` |
| `reports.review` | 复盘清单（考点、漏掉的得分点、下一步动作），随报告接口返回 |

`strengths` / `weaknesses` / `suggestions` 三栏由主后端从引擎明细推导（`app/core/engine_report.py`）：高分维度与最优轮次的面评转优势，低分维度与盲区弱领域转不足，未覆盖知识点转建议。引擎本身只给一段 `summary`。

换题（引擎侧整轮作废）时，镜像落库同步作废该行，新题复用同一题号。判据是 `done.swapped`，不是 `action == "swap"`：本场名额用尽时引擎仍会给出 `swap` 档，但那一轮照常评分。

## 本项目侧新增的接口

| 接口 | 作用 |
| :--- | :--- |
| `POST /api/v1/uploads/audio/asr` | 语音转写：音频交给引擎的 `/asr`，一次调用同时返回文本与 `audio_url`（前端不必为同一个文件传两次）。引擎不可用时返 503，不返空文本 |
| `POST /api/v1/uploads/audio/tts` | 面试官朗读：文本交给引擎的 `/tts`，音频落盘到 `uploads/tts/` 后返回站内地址。**不透传引擎自己的地址**——前端只认 8001 |
| `POST /api/v1/body-language/analyze` | 体态分析：只转发数字姿态关键点（引擎侧同样不接受图片、视频、音频），结果原样透传 |
| `GET /api/v1/reports/archive` | 成长档案：把已存的 `digest` 原样回传给引擎的 `/growth`，取回错题本 / 考点地图 / 历史成绩 / 提升路径。没有档案或引擎不可用时返回 `available=false` |

**简历模式**：建面试时给 `POST /api/v1/interviews` 带上 `resume_text`（上限 6000 字），引擎会切到 resume 档，考官 prompt 与开场白都会用到它。该字段**只有引擎链路生效**，原链路传了会被忽略（那一条的出题只看岗位与轮次）。

引擎的 `/practice`（专项练习）与 `/model_answer`（参考答案）**尚未接到本项目接口**：它们是给考生的出口，等前端做对应界面时一并接。

TTS 与体态分析的接口已就位，但**演示前端还没有对应页面**——接页面时不用再动后端。体态数据目前也**未接入评分链路**（引擎的 `/chat` 有个 `body_language` 字段可以用它，接不接、怎么接需要和 P5 确认取分口径后再定）。

## 已知差异与边界

- 引擎场是 10 题，原链路是 7 轮。`GET /api/v1/config` 会按当前开关返回对应的总题数。
- 追问不推进题号，前端「第 N 题」在追问期间保持不变。
- 引擎链路**不做 Mock 兜底**，失败即报错（503，错误码 50300）。
- **语音转写有内存门槛**：引擎侧要求空闲内存不低于 `A11_ASR_MIN_FREE_MB`（本部署 800MB），不满足时 `/asr` 返 503 并说明原因，不会硬加载到 OOM。
- **情感标签的来源换了，口径没变**：默认档下 `emotion` 来自 SenseVoice（闭集 `neu`/`hap`/`ang`/`sad`），`emotion_score` 与 `emotion_dist` 可能为 `null`（那个模型只给标签、不给概率）。引擎侧对它的定位仍是「韵律信号」而非「考生表达了什么情绪」——演示口径照旧：「有情感分布，中文看波动」，**不要说「情感识别很准」**。
- 转写质量受模型规模限制（int8 量化），有错字是正常形态，设计上就是让考生确认后再发送。
- 引擎的 `L3` 追问素材、单题校准锚点等字段本框架未使用，属 A11 的既有边界。
- `web/` 下的三个页面都是 A11 自带的调试页，只连 8005，不经过主后端。
- 引擎日志里的「2 号 AI 对话层」是交付方代码里的文案，与项目的成员编号无关，材料里别照抄。
- ⚠️ **引擎的会话存在内存里，它一重启就全丢**。2026-09-29 实测撞上过：引擎 `/health` 的累计会话数
  从 3 掉回 1（累计计数只会往上涨，变小只能是进程重启），而考生 19:16:31 建的会话到 19:19:14
  再答题时已被引擎判为「不存在」，中间只隔 2 分 43 秒。
  会话一丢，那一场在本项目侧会**同时撞上两堵墙**：继续答题是 404、主动结束也是 404（两条路都要
  先找到会话），而「同一用户同时只能有一场进行中」又挡着新开一场——考生就被困住了。
  本项目已为此做了收尾：适配器把这类 404 单独抛成 `EngineSessionLostError`，两处出口（答题 /
  主动结束 / 答满自动结束）都会把本场置为 `finished` 并返回 409 加一句明确提示，考生可直接重开。
  **但报告是生成不出来的**（评分得由引擎做，会话没了就做不了；本项目不会拿 P3 的结果去顶，
  那等于半场换口径）。**所以演示期间千万别重启引擎**——一重启，进行中的面试全部当场作废。

## 排障

| 现象 | 检查 |
| :--- | :--- |
| 面试接口返回 503 | 打开 `http://localhost:8005/health`，看 `bank_loaded`、`scorer_ready`、`llm_configured` 哪个为假 |
| `scorer_ready` 长期为 false | 在线档看 `SILICONFLOW_API_KEY` 是否配好；本地档看模型是否下好（`backend/.hf_cache/bge-reranker-v2-m3`），首次启动要等数十秒预热 |
| 分数恒为 50 左右 | reranker 未就绪，答案与得分点的客观比对没有生效 |
| `/asr` 返回「空闲内存不足」 | 腾出内存后重试，或调低 `A11_ASR_MIN_FREE_MB`；这是引擎的保护性拒绝，不是故障 |
| `/asr` 返回「还在加载」 | 转写模型懒加载中，隔几秒重试即可。首次加载实测约 3 秒（CPU、int8） |
| `/tts` 返 503 | 看 `/health` 的 `tts_ready` 与 `tts_error`；DashScope 密钥缺失或额度用尽都会走到这里 |
| 体态分析没返回 `score` | 正常形态：证据不足（帧太少、镜头里看不到肩线）时引擎**不给分**，而不是给低分。别在前端补 0 |
| `/start` 报 `llm_unavailable` | `backend/.env` 的 `LLM_API_KEY` 未配置 |
| 改完引擎代码想回归 | 见下节的冒烟测试命令，判据是「失败 0 项」 |

## 冒烟测试

桩模式（不需要 key、不加载模型，秒级跑完）：

```bash
cd backend/dialogue_layer
A11_MAIN_DB=<项目根>/backend/rag/数据 \
A11_KG_PATH=<项目根>/backend/dialogue_layer/数据/kg/kg_question_graph.pkl \
A11_RESOURCES_JSON=<项目根>/backend/dialogue_layer/数据/学习资源样例.json \
python smoke_test.py
```

⚠️ **三个路径必须显式给**：冒烟测试直接 import 应用、不走 `start.py` 的注入，而引擎的默认值指向交付方本机（`C:\Users\litao\...`），不给就会在出题那一步报「题库文件不存在」。

本机实测（2026-09-29，桩模式）：**2824 项通过、0 项失败**。项数随 KG / RAG / ASR 开关浮动，不必对齐某个数，判据只是「失败 0 项」。
