# A11 AI 对话层 · 集成回执（给 P5）

> 对应你 2026-09-23 交付的 `A11-AI对话层-后端-1号`（第二版）。
> 这一份回答你 `清单-给1号.md` 里要的东西，并说明我这边做了哪些适配。
> 接口契约的唯一权威仍是本项目 `docs/API.md`；你包的原始说明留在原包目录，未改动。

## 一、集成结论

包已接入本项目，作为**可选的面试引擎**：

| 项 | 值 |
| :--- | :--- |
| 落位 | `backend/dialogue_layer/`，`app/` 与 `personas/` **一行未改** |
| 形态 | 独立服务，端口 8005，由本项目 `backend/start.py` 拉起（端口被占用则跳过，不阻塞主流程） |
| 启用方式 | 本项目 `.env` 里 `DIALOGUE_ENGINE=a11`；置空则走本项目原链路（题库策略出题 + P3 评估） |
| 主后端对接 | 新增适配器 `app/adapters/ai_dialogue.py`，自己消费 `/chat` 的 SSE，对外仍是本项目既有的 JSON 契约 |
| 落库 | 主后端镜像写入自己的三张表（每题一行、追问不落新行、报告分数换算到 0~100） |

实测状态：真模型（`bge-reranker-v2-m3`）加载正常，`/health` 的 `bank_loaded` / `scorer_ready` / `llm_configured` / `kg_ready` 全为 true；桩模式全流程 10 题跑通并出报告。

## 二、对你清单的逐条回复

### 🔴 1. 接口契约差异

无差异需要你改。本项目前端契约以 `docs/API.md` 为准，正式前端（4 号）尚未开工（`frontend/` 目录下目前只有 README），不存在另一套字段约定。你的 `schemas.py` 不需要动。

### 🔴 2. 五维权重真值源

你按《工作成果描述》写的权重，与本项目根目录《评估维度.csv》**逐格一致**：

| 岗位 | 技术水平 | 逻辑思维 | 沟通表达 | 应变能力 | 岗位匹配度 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Java 后端 | 35 / 35 | 25 / 25 | 10 / 10 | 10 / 10 | 20 / 20 |
| Web 前端 | 30 / 30 | 20 / 20 | 15 / 15 | 15 / 15 | 20 / 20 |
| 测试开发 | 25 / 25 | 25 / 25 | 20 / 20 | 15 / 15 | 15 / 15 |
| 算法 | 35 / 35 | 30 / 30 | 10 / 10 | 10 / 10 | 15 / 15 |
| 系统设计 | 30 / 30 | 30 / 30 | 15 / 15 | 10 / 10 | 15 / 15 |

（格式为「你 config.SCORE_WEIGHTS / 本项目 evaluation_weights.py」的百分数。）

本项目的权重有机器校验（`tests/test_api.py::test_weights_match_csv`），改 CSV 不同步改权重会直接失败。至于主库 Excel 的「五维评分基准」sheet 是否权威，我这边没有该文件，需要 5 号（知识库）确认。

### 🔴 3. `raw` 的暴露面（A 还是 B）

在本项目里这条不成立：A11 的 `raw` **不对外暴露**。主后端只从中取摘要写入 `reports.engine_meta`（会话 ID、参与评分轮次、`partial`、`notes`、盲区摘要），`base_hit` / `adv_miss` 这类得分点原文不进本项目的任何表、也不进任何接口响应。所以「4 号不能拿到得分点」这条规则在本项目侧自然满足。

### 🟠 4~6. 术语扣分倾向 / 难度平移规则 / 换题上限

这三条都是评分与算法语义，属你的地盘，我一处没动（代码零改动）。要不要调整请你与需求方确认。

### 🟠 7. 新机器参数回填

| 项 | 实测值 |
| :--- | :--- |
| `A11_PYTHON` | `C:\Users\26373\.conda\envs\ai_interview\python.exe`（**复用本项目 conda 环境**，未另建；只补装了 `openai`） |
| `HF_HOME` | `backend/.hf_cache`；模型放在其下平铺目录 `bge-reranker-v2-m3/`，用 `RERANKER_MODEL` 指向它 |
| 8005 | 空闲，可用 |
| 整机内存 | 15.2 GB（24 逻辑核） |
| 显卡 | NVIDIA RTX 5060 Laptop + AMD Radeon 610M；仍按你的默认走 CPU |
| 依赖 | 除 `openai` 外全部已在本项目环境中 |

### 🟡 8. RAG 开不开

不开。整机 15.2 GB，低于你文档里「开 RAG 建议整机 ≥16 GB」的门槛，`A11_RAG` 保持 0。RAG 三件已随包拷入本项目（`backend/dialogue_layer/数据/rag/`，已 gitignore），将来内存宽裕时改一个环境变量就能开。

### 🟡 9. 要不要新题

不需要。本项目题库共 5012 题（`backend/rag/数据/*-v5.json` 五个文件，另有导入后的 `questions` 表供原链路使用），A11 直接读这个目录，不经过数据库。

### 🟠 10. 真跑对照的时间窗口

我这边完成的是**真模型**验证（reranker 语义打分对照：得分点原文作答 100 分、无关作答 0 分）。**真 LLM 对照**（你那 3 臂 7 场的同类）需要 API key 与独占 8005 的时间窗口，等本项目这边 key 配好后可以约。

### 🔴 11. 回执

```
smoke_test.py  → 通过 2096 项，失败 0 项（LLM_MOCK=1 / RERANKER_MOCK=1 / A11_KG=1 / A11_RAG=0）
/health        → bank_loaded=true  scorer_ready=true  llm_configured=true  kg_ready=true
                 reranker_mock=false（真模型）  device=cpu  model=BAAI/bge-reranker-v2-m3
check_env.py   → 退出码 0；8 项 FAIL 全部是「原包默认路径未配置」，
                 集成时由 start.py 的环境注入解决（见下一节），不是包的问题
```

`check_env.py` 的 FAIL 明细与处置：

| FAIL 项 | 处置 |
| :--- | :--- |
| 题库目录不存在 | `A11_MAIN_DB` 由 start.py 注入，指向本项目 `backend/rag/数据` |
| 模型缓存缺失（reranker / bge-m3 / 「缓存不全」三项） | reranker 已下载到 `backend/.hf_cache/bge-reranker-v2-m3`；bge-m3 不需要（RAG 关） |
| `DEEPSEEK_API_KEY` 未设置 | 待本项目侧配置，注入时取 `backend/.env` 的 `LLM_API_KEY` |
| 依赖版本不一致（sentence-transformers / transformers / numpy） | 见下一节，刻意不降级 |

### 🟠 12. 转达 3 号的两处口径变更

在本项目里不构成影响：3 号（评估）读的是本项目自己的表，不消费 A11 的 `raw` 明细，`engine_meta` 只存摘要。换题看 `swapped`、盲区软标签这两条我已经记在本项目的团队汇报文档里，将来若要直接对接 A11 明细时会先看那两条。

## 三、我这边做的三处刻意偏离

### 1. 不采用你 `requirements.txt` 的版本锁

`sentence-transformers 4.1.0` / `transformers 4.49.0` 会降级本项目共享环境里的同名包，而 8003 的 RAG 服务（5 号）也用这两个包，降级会连累它。当前环境是 `sentence-transformers 6.0.1` + `transformers 5.17.0` + `numpy 2.5.3`，实测结论：

- 桩模式冒烟 2096 项全过；
- 真模型：`CrossEncoder` 加载 2.27GB 权重耗时 11.8 秒，语义打分正常（得分点原文 100 分 / 无关作答 0 分，`reranker_ok=true`）。

也就是说这三个版本差在这条链路上没有实际影响。若你那边有已知的版本敏感行为，请告诉我，我再单独评估。

### 2. 模型走魔搭下载

本机实测 `hf-mirror.com` 与 `huggingface.co` 都连不上（SSL 握手超时 / 直连超时），改从 ModelScope 下载（2.27GB，83 秒）。另外提醒：新版 `huggingface_hub` 默认走 Xet 后端，镜像站不支持会返 401，需要 `HF_HUB_DISABLE_XET=1`。这条已写进 `backend/dialogue_layer/README-集成说明.md`。

### 3. 题库复用本项目的那一份

你包里的 `数据/bank/*.json` 与本项目 `backend/rag/数据/*-v5.json` 已按题目逐字段核对一致（条数、题目 ID 集合、全部字段取值；字节数差异只来自 JSON 缩进）。所以我没拷第二份，让 A11 直接读本项目目录，避免将来题库更新后两边漂移。代价是这一层不能脱离本项目独立部署。

## 四、未拷入的文件

| 项 | 原因 |
| :--- | :--- |
| `样例/`、`面试官完整prompt样例.txt` | 含得分点原文，属敏感材料，留在原包 |
| `数据/bank/` | 见上（复用本项目题库） |
| `check_env.py`、`数据/校验数据.py`、`数据/README.md` | 为原包的自包含布局设计（核 `数据/bank/` 的字节数），集成后布局已变，留着会误报 |
| `dump_prompt.py` | 调试工具，非运行所需；需要排障时再补 |
| 说明文档四份 | 留在原包位置可查 |

## 五、需要你确认的事

1. 上述三处偏离（版本不降级、魔搭下载、题库复用）你是否认可；有异议我改。
2. 你文档里「判档真超时的耗时行为」与「9 场对照重跑」两条欠账，要不要在本项目的环境上补测。

## 六、第三版（2026-09-25）追加回执

你这一版把端点从 6 个扩到 10 个（新增 `/asr`、`/practice`、`/growth`、`/model_answer`），`/finish` 多了 `digest` 与 `review`，`core/` 多了 7 个模块。本项目已按新版更新，追加回执如下。

### 已做

| 项 | 结果 |
| :--- | :--- |
| 代码与数据 | `app/`（29 文件）、`smoke_test.py`、`check_env.py`、`dump_prompt.py`、`build_kb_index.py`、`web/`、`数据/学习资源样例.json` 全量替换，**代码零改动** |
| 冒烟测试 | **通过 2854 项，失败 0 项**（LLM_MOCK=1 / RERANKER_MOCK=1 / A11_KG=1 / A11_RAG=0 / A11_ASR=0；项数比文档区间少几项是因为这一轮按你的提示关掉了 ASR） |
| 依赖 | 补装 `faster-whisper==1.2.1`、`ctranslate2==4.8.2`、`av==18.1.0`；`python-multipart` 与 `onnxruntime` 环境里已有（后者是 1.30.0，比 pin 的 1.29.0 高一个小版本，未降级） |
| 模型 | reranker 2.27GB + whisper-small 464MB，均从 ModelScope 下载（本机 hf-mirror 与 huggingface.co 都不通） |
| 语音验证 | 真音频（Windows SAPI 合成中文）实测：模型加载 1.6 秒、17 秒音频转写 4.6 秒、语言识别 zh 置信 1.00。经本项目 `/uploads/audio/asr` 转发的链路同样通了（`duration_ms` / `loudness` / `pause_total_ms` 都有值） |
| 成长档案 | 每场 `/finish` 的顶层 `digest` 已落库（实测一场 7170 字节），`GET /reports/archive` 把它**原样**回传给 `/growth`，取回了 `wrong_book` / `kp_map` / `history` / `plan` 四视图 |
| 学习资源 | `/health` 的 `resource_ready=true`、`resource_kps=25`，素材源就是你包里的 `学习资源样例.json` |

### 四处如实说明

1. **情感模型没装上**：`superb/wav2vec2-base-superb-er` 在 ModelScope 上查不到（`superb/...` 与 `AI-ModelScope/...` 两种命名都试过，都是 404 record not found）。本部署设 `A11_ASR_EMOTION=0`，`emotion*` 恒为 `null`；转写与语速 / 停顿 / 音量三组指标不受影响。你那边若有该模型的可用镜像地址，或认为可以换一个模型（标签是动态读 `id2label` 的，理论上可换），请告知。
2. **ASR 内存门槛按本机下调**：你的默认是 1200MB。本机整机 15.2GB，演示时 reranker 常驻约 2.3GB，1200MB 常常凑不出来（被拒时的原文是「空闲内存 289MB < 门槛 1200MB」）。独立进程实测 whisper-small（int8）加载约 500MB，所以本项目注入 `A11_ASR_MIN_FREE_MB=800`（外部可用环境变量覆盖）。这是本机适配，不是对你的门槛有异议。
3. **`raw` 保持你的脱敏默认档**：不设 `A11_RAW_DETAIL`（用默认 0）。本项目只从 `raw` 取摘要写 `reports.engine_meta`，得分点原文不入库、不出接口。
4. **尚未接入的端点**：`/practice`、`/model_answer` 与 `/finish` 的 `review` 还没接到本项目接口。它们是给考生的出口，等前端做对应界面时一并接；`digest` → `/growth` 这条链已经通了，是它们的基础。

### 待你确认

- 上面第 1、2 条两处偏离是否认可；情感模型若必须上，请给可用的下载源。
- 你清单里给 1 号的三条硬阻塞，前两条（接口契约差异、五维权重真值源）的最新口径是否仍是上一版的答复（无差异、与本项目《评估维度.csv》逐格一致）。
