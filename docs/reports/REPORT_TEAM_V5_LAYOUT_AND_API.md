# 团队通览 · V5 知识库落地：目录归属、接口清单与本次改动

> 发布人：1 号（后端主程 & 集成）｜ 日期：2026-09-14
> 适用：全体成员（2/3/4/5 号）
> **本文回答三件事：① 本次改了什么 ② 每份代码归谁管（避免误改他人文件夹）③ 你需要调什么接口**

---

## 一、本次改动总览（1 号执行）

**触发原因**：5 号交付了 V5 知识库（主库 5012 题 / 5 岗位 + 74011 条向量检索条目），
数据结构与 V4 差异较大，需要换代。

| # | 改动 | 影响面 |
|---|---|---|
| 1 | **交付包迁入项目**：`交付包-1号后端_new/` → `backend/rag/`（`代码/`、`数据/`、`vector_db/`、`说明/`），原目录已删除 | 5 号 |
| 2 | **交付包适配 12 处**：端口 8000→8003、解除 `HF_HUB_OFFLINE` 死锁、补 CORS、`_pick()` 失败保护、环境变量支持等 | 5 号 |
| 3 | **questions 表重构**：18 列（V4）→ **19 列**（V5 字段：基础/进阶得分点、L1/L2/L3、降级策略、校准锚点、知识点、关键词、优先级） | 2/3/4 号 |
| 4 | **导入脚本重写**：源由 `题库/*.xlsx` 改为 `backend/rag/数据/*-v5.json`，新增 `--rebuild`/`--dry-run` | 5 号 |
| 5 | **面试官算法重做**：新建 `backend/interviewer_new/`（旧的 `backend/interviewer/` 冻结留档） | **2 号** |
| 6 | **岗位 3 个 → 5 个**：新增算法工程师、系统设计工程师（原占位位改名，`enabled=True`） | 3/4 号 |
| 7 | **RAG 服务接入**：`backend/rag/` 起 8003，由 `start.py` 拉起；接进面试出题链第 2 级 + 新增透传接口 | 2/4 号 |
| 8 | **评估服务增强**：新建 `backend/evaluator_new/`（按题评分：注入 V5 单题校准锚点）；`start.py` 已切到新版 | **3 号** |
| 9 | 文档与报告更新（含本系列 6 份） | 全员 |

**对成员的影响一句话版**：
- **2 号**：算法目录换到 `interviewer_new/`，详见《REPORT_TO_P2_INTERVIEWER_NEW.md》
- **3 号**：岗位权重增至 5 个（新增两岗为**临时值**，待团队定稿）；评估服务增强版在 `evaluator_new/`，详见《REPORT_TO_P3_EVALUATOR_NEW.md》
- **4 号**：岗位列表变 5 个（走 `GET /positions`，**前端无需改代码**）；题库接口字段有变
- **5 号**：交付包 12 处改动见《REPORT_TO_P5_V5_PACKAGE_REVIEW.md》，后续更新请保留这些改动

---

## 二、代码目录归属（⚠️ 请勿修改他人目录）

| 目录 | 归属 | 可写性 | 说明 |
|---|---|---|---|
| `backend/app/` | **1 号** | 可改 | 集成层：模型 / API / schema / 适配器 / 配置 |
| `backend/scripts/`、`backend/tests/` | **1 号** | 可改 | 导入脚本、仿真脚本、测试 |
| `backend/interviewer_new/` | **2 号** | 可改 | 面试官算法（V5 版）。**⚠️ 1 号写的是「示范代码」——主体是 2 号，可照改**（详见 `REPORT_TO_P2_INTERVIEWER_NEW.md` 开头） |
| `backend/interviewer/` | 2 号（旧版） | **冻结** | V4 数据源版，不再被任何代码引用；确认新版稳定后可删 |
| `backend/evaluator_new/` | **3 号** | 3 号可改，他人只读 | 评估服务**增强版**（Flask，8002，`start.py` 已切到此版）。**⚠️ 同为「示范代码」——评分主体是 3 号**（详见 `REPORT_TO_P3_EVALUATOR_NEW.md` 开头） |
| `backend/evaluator/` | 3 号（原版） | 留档 | 评估服务原版；确认新版稳定后可删，或把 `start.py` 切回 |
| `frontend/` | **4 号** | 4 号可改，他人只读 | 正式前端（Vite）——**前端形态由 4 号决定** |
| `frontend_test/` | **1 号** | 可改 | 零依赖演示前端（5273）。**⚠️ 前端的「演示代码」，不是正式前端**；P4 交付后由 1 号停用/删除（详见 `REPORT_TO_P4.md` 第 7 节） |
| `backend/rag/代码/` | 5 号交付 → **1 号适配** | 谨慎 | RAG 服务代码；5 号更新交付包时**必须保留 1 号的 12 处改动** |
| `backend/rag/数据/`、`vector_db/`、`说明/` | **5 号** | 只读 | 大文件（向量库 674MB）已 git 忽略；⚠️ `vector_db/` **必须保持纯 ASCII 名**（chromadb 打不开含非 ASCII 的绝对路径） |
| ~~`题库/`~~ | — | **已于 2026-09-14 删除** | V4 xlsx 历史；已被 `backend/rag/数据/*-v5.json` 取代，本体删除、需要时从 Git 历史取 |
| `docs/`、`CLAUDE.md`、`README.md` | **1 号** | 关键改动请先在群里说 | 项目文档 |

---

## 三、端口分配（⚠️ 8000 不可用）

| 端口 | 服务 | 归属 | 说明 |
|---|---|---|---|
| **8000** | — | — | **被本机 Godot AI MCP 占用，项目内任何服务都不可使用** |
| 8001 | 主后端（FastAPI） | 1 号 | `backend/start.bat` 拉起 |
| 8002 | 评估服务（Flask） | 3 号 | 由 `start.py` 自动拉起 |
| **8003** | **RAG 检索服务** | 5 号交付 / 1 号适配 | 由 `start.py` 自动拉起；首次启动需下载 4.5GB 模型 |
| 5173 | 前端联调（Vite） | 4 号 | P4 自行启动 |
| 5273 | 演示前端 | 1 号 | 由 `start.py` 自动拉起（避开 5173） |

---

## 四、各成员所需 API 清单

### 4.1 全员通用约定

- **统一响应格式**：`{"code": 0, "message": "ok", "data": {...}}`；错误码
  `40000` 参数错 / `40100` 未登录 / `40300` 无权限 / `40400` 不存在 / `40900` 状态冲突 / `50000` 服务端错
- **鉴权**：除注册登录外，所有接口需 `Authorization: Bearer <token>`
- **全局前缀**：`/api/v1`
- **本地地址**：`http://localhost:8001`（Swagger 文档 `/docs`）

### 4.2 给 2 号（AI 专项）

| 用途 | 接口 / 模块 | 契约 |
|---|---|---|
| 面试官算法 | `backend/interviewer_new/question_bank.py` | `pick_next(db, position, round_no, history, is_follow_up) -> str \| None`（首参为 `AsyncSession`；None = 未命中，adapter 会降级） |
| 语义检索（备选） | `POST /api/v1/rag/search` 或直连 `POST http://localhost:8003/rag/search` | `{query, job?, mode: select\|expand, top?, level?}` → `{results: [{score, 题目, 参考答案, 原题ID, 层级, 岗位, 题型, 难度, 面试阶段, 考点优先级}]}`；`mode=expand` 另返回 `全层级片段` |
| 题目素材 | `GET /api/v1/questions/{id}` | 含 `calibration_anchor`（单题校准锚点）、`basic_score_points` / `advanced_score_points` |

> 算法细节、扩展指南见《REPORT_TO_P2_INTERVIEWER_NEW.md》。

### 4.3 给 3 号（评估）

| 用途 | 接口 / 模块 | 契约 |
|---|---|---|
| 岗位权重 | `app.core.evaluation_weights.POSITION_CONFIG` | **5 个岗位** × 5 维（百分制）；仅标准库依赖，可直接 import |
| **评估服务（增强版）** | `backend/evaluator_new/app.py`：`POST /evaluate` | `{position, qa_list:[{round, question, answer, audio_url?, **materials?**}]}` → 5 维分数 + 文本字段。`materials` 由主后端按题干从题库自动附加（含单题校准锚点/得分点），**不传时行为与 3 号原版逐字一致** |
| 单题评分素材（备用入口） | `GET /api/v1/questions/{id}` | `calibration_anchor` 给出该题「技术水平 / 岗位匹配度」的判分标准 |

> ⚠️ **算法工程师 / 系统设计工程师两岗的权重是临时值**（技术/逻辑/表达/应变/匹配 = 40/25/10/10/15 与 30/30/15/10/15），
> 已同步写入 `评估维度.csv` 与 `POSITION_CONFIG`，两处均有「临时，待团队定稿」注释。
> `tests/test_api.py::test_weights_match_csv` 会校验两处一致——**改权重必须同时改 CSV 与代码**。
> 评估服务目前**不读 questions 表**（只吃对话文本），上表第 2 行是可选增强。

### 4.4 给 4 号（前端）

| 用途 | 接口 | 说明 |
|---|---|---|
| 岗位列表 | `GET /api/v1/positions` | **5 个启用岗位**（backend/frontend/test_engineer/algorithm/system_design），含 code/name/description/tech_stack/focus。**前端无需改代码**，但 UI 建议验证 5 张卡片的布局 |
| 题库浏览 | `GET /api/v1/questions` | 过滤参数：`position` / `category` / `difficulty` / `stage` / **`priority`（新增）** / `q` / `limit` / `offset` |
| 题库详情 | `GET /api/v1/questions/{id}` | 字段变更见 4.5 |
| 语义检索（可选） | `POST /api/v1/rag/search` | 透传知识库服务；服务不可用时返回 `available: false` + 空结果（**不会 500**），前端可优雅降级 |
| 面试流程 | 原有接口不变（**注意：无 `next-question` 接口**） | `POST /interviews`（开始，返回首题 + `interview`）；`POST /interviews/{id}/answers`（提交答案，**下一题在响应的 `data.next_question`**，结束则 `data.finished=true` 并附 `data.report`）；`POST /interviews/{id}/finish`（提前结束并出报告）；`GET /interviews/{id}`（恢复会话，含 `qa_records`） |

**受控词表变更**（`GET /questions` 的过滤值，非法值返回 400）：

| 维度 | 旧值（V4） | **新值（V5）** |
|---|---|---|
| category | 技术知识 / 系统设计题 / 场景题 / 编码与算法 / 项目深挖 / 行为面试 | **技术知识题 / 场景应用题 / 项目经历题 / 行为素质题** |
| stage | 开场热身 / 核心考察 / 深度考察 / 收尾交流 | **开场热身 / 核心考察 / 深度压轴** |
| difficulty | easy / medium / hard | 不变 |
| priority | —（无） | **常规题 / 高频必考题 / 拓展题** |

### 4.5 给 5 号（知识库）

| 用途 | 命令 / 文件 | 说明 |
|---|---|---|
| 导入题库 | `cd backend && python -m scripts.import_question_bank --rebuild --yes` | 读 `backend/rag/数据/*-v5.json`（18 字段），幂等可重跑 |
| 只看统计不落库 | `... --dry-run` | 输出记录数 / 岗位分布 / 阶段分布 / 校验失败明细 |
| RAG 服务自测 | `python backend/rag/代码/04_verify_collection.py` | 应报 collection 总条数 74011 |
| 交付包改动 | 见《REPORT_TO_P5_V5_PACKAGE_REVIEW.md》 | 12 处，更新交付包时请保留 |

### 4.6 题库字段变更对照（V4 → V5，19 列）

| 变更 | 字段 |
|---|---|
| **新增（10）** | `keywords` `exam_priority` `basic_score_points` `advanced_score_points` `follow_up_l1` `follow_up_l2` `follow_up_l3` `fallback_strategy` `calibration_anchor` `related_knowledge` |
| **保留（9）** | `id` `position_code` `question_no`（现存 V5 原题 ID，如 `JAVA_BACKEND-Q0001`）`category` `difficulty` `question` `interview_stage` `stage_order` `suggested_minutes` |
| **删除（9）** | `sub_category` `soft_skill_tag` `score_points` `follow_up_triggers` `reference_answer` `note` `alternative_directions` `excellent_example` `expression_points` |

> 参考答案不再单列：V5 只提供基础/进阶得分点（面试场景下得分点比标准答案更有用）；
> RAG 条目的「参考答案」由数据生产端拼装。

---

## 五、环境与启动

**依赖**（conda 环境 `ai_interview`）：

| 组 | 内容 | 体积 | 谁需要 |
|---|---|---|---|
| 主依赖 | fastapi / uvicorn / sqlalchemy / flask / openpyxl 等 | ~100MB | 全员（`backend/requirements.txt`） |
| **RAG 依赖** | torch(CPU 版) / chromadb / sentence-transformers | **~2.5GB** | 只有要跑 RAG 服务的机器；`backend/rag/requirements-rag.txt` |
| **模型文件** | bge-m3 + bge-reranker-v2-m3 | **~4.5GB** | 同上，首次启动时自动下载（默认 huggingface.co，网络受限可设 HF_ENDPOINT 走镜像） |

> RAG 依赖**刻意不写进** `requirements.txt`：主流程不依赖它，写进去会让每个新环境都被强加 2.5GB。
> `start.py` 会检测并在缺失时按需安装；**安装失败或 RAG 未启用，主流程完全不受影响**。

**一键启动**：

```bash
双击 backend/start.bat
# 依次拉起：RAG(8003) + 评估(8002) + 演示前端(5273) + 主后端(8001)
# 启动完成后打印访问指引（本机 + 局域网地址）
# Ctrl+C 一并退出全部子进程
```

**测试与仿真**（必须在 `backend/` 下跑）：

```bash
cd backend
python -m pytest -q                              # 全量 66 个用例
python -m scripts.simulate_interview --rounds 200  # 面试流程仿真（效果度量）
```

---

## 六、需要团队确认的两件事

1. **算法工程师 / 系统设计工程师的评估权重**：目前是 1 号填的临时值
   （40/25/10/10/15 与 30/30/15/10/15）。请团队在《评估维度.csv》上定稿后，
   同步更新 `app/core/evaluation_weights.py`（两处都有「临时」注释标记）。
2. **旧 `backend/interviewer/` 是否删除**：它已冻结、不再被引用，保留仅作历史留档。
   待 2 号确认新算法稳定后可清理。
