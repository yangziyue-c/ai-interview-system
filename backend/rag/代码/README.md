# A11 · RAG 知识库与向量数据库 · 代码包使用说明

本目录包含从「岗位结构化主库 v5」到「RAG 语义知识库 + ChromaDB 向量库」的完整可运行代码。

> **本副本已由 1 号（后端主程）适配**，改动清单见文末「1 号适配说明」。
> 目录结构刻意保持交付包原样（`代码/`、`数据/`、`向量库/`、`说明/` 同级），
> 使脚本内的相对路径定位（`_PKG_ROOT` = 脚本所在目录的父目录）自动生效，无需配置任何路径。

## 文件清单

| 文件 | 作用 | 输入 → 输出 |
|---|---|---|
| `01_generate_rag_data.py` | RAG 数据生成 | 主库 `*-v5.json` (5012 题) → `*-rag-v2.jsonl` (7.4 万条) |
| `02_build_vector_db.py` | 向量库构建 | `*-rag-v2.jsonl` → `chroma_db_v2/` (ChromaDB + bge-m3) |
| `03_search_rag.py` | 检索实测 | 任意问题 → Top-N 命中（双模式：出题/深挖） |
| `04_verify_collection.py` | 向量库完整性验证 | chroma_db_v2 → 岗位/层级/题型分布统计 |
| `05_rag_api_server.py` | **RAG 检索 HTTP 服务** | FastAPI 封装，对外提供 `/rag/search`、`/health`、`/question/{原题ID}` |

> 日常使用只需 `05`（HTTP 服务）；`01`~`04` 是数据生成与运维脚本，重建向量库时才用。

## 运行顺序

```bash
# 第 1 步：生成 RAG 数据（主库 → jsonl，约几分钟）
python 01_generate_rag_data.py

# 第 2 步：构建向量库（jsonl → ChromaDB，CPU 约 3 小时，断点续跑）
python 02_build_vector_db.py

# 可选：只预检数据不向量化
python 02_build_vector_db.py --skip-embed

# 第 3 步：检索实测（双模式）
python 03_search_rag.py "Java 里 == 和 equals 的区别？"
python 03_search_rag.py "Java 里 == 和 equals 的区别？" --expand   # 深挖：取该题全部层级
python 03_search_rag.py "Redis 缓存穿透怎么办" --job "Java 后端开发工程师" --top 5

# 第 4 步：验证向量库完整性
python 04_verify_collection.py

# 第 5 步（日常使用）：启动 RAG 检索 HTTP 服务 → http://localhost:8003
#   首次启动需下载模型（约 4.5GB），之后约 10-30 秒加载
python 05_rag_api_server.py
```

## 技术栈与选型理由

| 组件 | 选型 | 理由 |
|---|---|---|
| 向量模型 | `BAAI/bge-m3` | 中文语义检索标杆，1024 维，512 token，CPU 可跑 |
| 重排模型 | `BAAI/bge-reranker-v2-m3` | 交叉编码器，精排精度高（只对 Top-20 跑，代价可控） |
| 向量库 | `ChromaDB` (PersistentClient) | 轻量、本地持久化、cosine 距离、按需过滤 |
| 相似度 | cosine | 检索前 normalize，点积即余弦 |

## 数据设计要点（为什么要这么做）

1. **主库 1 题 : RAG 3~5 条**：每题生成 7 类片段（原题基准款 / 语义变体 / L1-L3 追问 / 得分点拆分 / 前置知识点 / 场景化 / 答案变体），覆盖考生各种提问方式和碎片化回答。
2. **全部绑定原题ID**：检索命中任意变体都能映射回主库完整素材（18 字段），支撑面试官完整出题。
4. **两段式检索 + 双模式**：bge-m3 快速召回 → reranker 精排 → 按原题ID去重 → Top-N。
   - **出题模式**（默认）：按题去重取 Top-N 道不同题，给面试官选下一题；
   - **深挖模式**（`--expand`）：命中 1 题后按原题ID 取该题**全部层级片段**（原题/L1/L2/L3/得分点/铺垫/变体），支撑追问、逐点评分、降级引导——只取 1 条会丢信息。
4. **不入库内容**：五维评分细则、单题校准锚点、知识点学习建议——这些走主库 ID 查询，不进向量库。

## 踩过的坑（血泪教训，务必注意）

1. **评分话术污染**：生成器曾把主库「单题校准锚点/评分基准」字段当答案填充，导致 1870 条 RAG 答案变成评分话术。**根因在主库得分点本身是评分话术**——修 RAG 必须同步修主库源头，否则重建又带出。
2. **万能模板套壳**：如"先明确场景的核心矛盾与目标"式模板答案，检索命中后是废话。必须全量扫除。
3. **修复过程自身引入重复**：LLM 批量重写/写回时可能重复插入同一条目。**每次写回后必须跑四键查重**（原题ID+层级+题目+答案全同）。
4. **断点续跑安全**：`build_v2_done.json` 记录已完成文件，但**严禁同时运行多个构建进程**（col.add 对重复 id 会崩）。
5. **得分点短条目**：<50 字条目是"细粒度碎片"设计（考生提到零散知识点也能命中），**豁免 80 字要求**，已验证 100% 有完整条目兜底，删了反而损失召回。

## 验收清单（每次修改后必跑）

```
1. 行数统计           → 与预期一致（当前 74,011 条）
2. 四键全同查重       → 0 组
3. 评分话术扫描       → 0 条（probe_score_total.py 特征串）
4. 万能模板扫描       → 0 条
5. 占位/套壳/空洞     → 0 条（verify_rag_v2b.py / verify_rag_v2c.py）
6. 主库源头扫描       → 主库得分点评分话术 0 题
7. 检索实测           → 典型问题 Top-3 命中与题目相关
```

## 环境依赖

```bash
# 依赖清单在上一级目录（约 2.5GB；torch 走 CPU 索引而非默认 CUDA 版，省约 2GB）
pip install -r ../requirements-rag.txt

# 首次运行需下载两个模型（约 4.5GB，走国内镜像）
set HF_ENDPOINT=https://hf-mirror.com
python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3'); S('BAAI/bge-reranker-v2-m3')"
```

模型就位后可设 `HF_HUB_OFFLINE=1` 跳过联网检查、加快启动。

> 依赖**刻意不写入** `backend/requirements.txt`：主流程（8001 主后端 / 8002 评估服务）
> 不依赖它们，写进去会让每个新环境都多下载 2.5GB。
> `backend/start.py` 会检测并在缺失时按需安装，安装失败则跳过 RAG 服务、不影响主流程。

## 1 号适配说明（2026-09-14）

本副本相对 P5 原交付包做了以下改动。**P5 后续更新交付包时，请保留这 8 处**，
否则会出现端口冲突、首次启动崩溃、路径静默失效等问题：

| # | 文件 | 改动 | 原因 |
|---|---|---|---|
| 1 | `05` | 端口 `8000` → `8003`（`RAG_PORT` 可覆盖） | 8000 被本机 Godot AI MCP 占用（项目铁律） |
| 2 | 五个脚本 | `HF_HUB_OFFLINE` 由写死 `"1"` 改 `setdefault(..., "0")` | 交付包不含模型文件，无本地缓存的机器首次启动直接抛 OSError |
| 3 | `05` | 补 `CORSMiddleware` | 原说明文档承诺「CORS 已放开」，但代码无中间件 |
| 4 | 五个脚本 | `_pick()` 全部未命中时 `raise FileNotFoundError` | 原实现返回无效路径 → chromadb **静默创建空库**，表现为「检索永远无结果」而非「路径配错」 |
| 5 | `02/03/05` | `torch.set_num_threads(8)` → 默认取 CPU 核心数 | 28 核机器上写死 8 会浪费算力 |
| 6 | `05` | 启动打印**实际命中**的向量库/主库路径 + collection 条数 | 路径问题一眼可见 |
| 7 | `05` | `/rag/search` 包异常处理，失败返回 `{"results": [], "error": ...}` | 原实现查询异常直接 500，调用方无法降级 |
| 8 | `05` | `GET /question/{id}` 未命中返回 **404** | 原为 HTTP 200 + error 字段，不符合 REST 语义 |

### 环境变量（全部可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RAG_PORT` | `8003` | 监听端口 |
| `RAG_CHROMA_DIR` | 按交付包结构自动定位 | 向量库目录 |
| `RAG_MAIN_DIR` | 按交付包结构自动定位 | 主库 json 目录 |
| `RAG_THREADS` | CPU 核心数 | torch 线程数 |
| `HF_HUB_OFFLINE` | `0` | 置 `1` 则离线加载模型 |
