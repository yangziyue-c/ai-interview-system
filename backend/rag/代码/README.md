# A11 · RAG 知识库与向量数据库 · 代码包使用说明

本目录包含从「岗位结构化主库 v5」到「RAG 语义知识库 + 内存向量索引」的完整可运行代码。

## ⚠️ 2026-09-19 重大变更：305 问题已修复，运行时改用内存精确余弦索引

原 ChromaDB 的 HNSW 近似索引出现**不同步损坏**：sqlite 元数据有 **74011** 条，但 HNSW 向量文件只有 **73706** 条（缺口 305 条），且 `length.bin` 损坏 → 2 号机器报 `Error loading hnsw index`。

**修复方案**（DeepSeek 建议、已采纳）：放弃 HNSW 近似检索，改用**内存精确余弦索引**：

| 项目 | 旧（ChromaDB） | 新（内存索引） |
|---|---|---|
| 检索后端 | `chromadb.PersistentClient` + HNSW 近似 | `MemoryRetriever`（numpy 精确余弦，暴力 Top-K） |
| 数据文件 | `chroma_db_v2/`（HNSW 三段式二进制） | `memory_index.npz`（向量矩阵 + id）+ `all_records.pkl`（记录本体） |
| 条数 | 74011（sqlite）≠ 73706（HNSW）→ 305 缺失 | 74011 = 74011，**逐条断言一致** |
| 检索质量 | 近似（HNSW 可能漏召） | **精确**（全量余弦，零漏召） |
| 依赖 | chromadb==1.5.9（版本锁死，易崩） | **不需要 chromadb**（03/04/05 运行零 chromadb） |
| 启动耗时 | 秒级（但加载损坏 HNSW 直接崩） | 加载 npz 约 2-5 秒，之后秒级 |

- `memory_retriever.py`：内存检索器，接口兼容旧 `col` 用法（count/get/query/distances、where 过滤），内部**硬断言 74011 条**。
- `memory_index.npz` / `all_records.pkl`：由 `rebuild_index_shard.py` 用 **bge-m3（与构建参数完全一致）** 从 5 个 `*-rag-v2.jsonl` 重新编码生成，全部 74011 条。
- 旧 `向量库/chroma_db_v2/` 保留为**只读归档**，不再参与运行时检索。

## 文件清单

| 文件 | 作用 | 输入 → 输出 |
|---|---|---|
| `01_generate_rag_data.py` | RAG 数据生成 | 主库 `*-v5.json` (5012 题) → `*-rag-v2.jsonl` (7.4 万条) |
| `02_build_vector_db.py` | （构建工具）向量库构建 | `*-rag-v2.jsonl` → `chroma_db_v2/`（**仅重建时用，运行不需要**） |
| `rebuild_index_shard.py` | （构建工具）内存索引重建 | `chroma_db_v2` → `memory_index.npz` + `all_records.pkl` |
| `memory_retriever.py` | 内存检索器（03/04/05 共用） | 加载 npz/pkl，精确余弦 Top-K |
| `03_search_rag.py` | 检索实测 | 任意问题 → Top-N 命中（双模式：出题/深挖） |
| `04_verify_collection.py` | 内存索引完整性验证 | memory_index.npz → 条数/岗位/层级/题型分布统计 |
| `05_rag_api_server.py` | HTTP 检索服务 | POST /rag/search（出题/深挖）+ GET /question/{原题ID} |
| `requirements-rag.txt` | RAG 专属依赖清单 | 国内镜像安装命令 + 模型说明 |

## 路径自适应机制（★ 解压即用，别乱改路径）

所有脚本**不写死机器绝对路径**，基于自身位置自动定位数据：

```
交付包/                    ← 任意解压位置
├── 数据/                  ← 01/05 从这里读主库 json，01 写 jsonl 到这里
├── 向量库/                ← 内存索引（memory_index.npz + all_records.pkl）在这里
└── 代码/                  ← 脚本在这里（__file__ 向上两级 = 交付包根）
```

- 探测顺序：交付包内目录 → 开发机构建目录（回退）。
- 全部未命中 → **抛 FileNotFoundError 明确报错**（不会静默建空库）。
- 05 额外支持环境变量覆盖：`RAG_MEM_DIR`（内存索引目录）/ `RAG_MAIN_DIR` / `RAG_PORT` / `RAG_THREADS`（部署目录结构不同时用）。

## 端口约定

| 服务 | 端口 |
|---|---|
| 主后端 | 8001 |
| P3 评估 | 8002 |
| **RAG 检索（05）** | **8003**（8000 被本机其他进程占用，项目铁律勿用） |

05 可用 `RAG_PORT` 环境变量覆盖默认 8003。

## 模型体积与下载（首次约 4.5GB）

```bash
# 依赖（约 2.5GB，走国内镜像；运行 03/04/05 无需 chromadb）：
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install sentence-transformers fastapi uvicorn pydantic -i https://pypi.tuna.tsinghua.edu.cn/simple

# 首次启动自动下载模型（走 hf-mirror，见 requirements-rag.txt）：
set HF_ENDPOINT=https://hf-mirror.com
python 05_rag_api_server.py    # 启动日志打印 [memory] collection size: 74011
```

- 模型：`BAAI/bge-m3`（向量，**检索时仅用于把查询文本编码成向量**）+ `BAAI/bge-reranker-v2-m3`（重排），下载后缓存到 `~/.cache/huggingface`。
- 之后可设 `HF_HUB_OFFLINE=1` 离线加载；**脚本默认允许联网**（交付包不带模型，写死离线会在首次启动直接崩）。

## 1 号适配说明（2026-09-14，P1 落地时修复 12 处，本包已同步）

| # | 级别 | 改动 | 本包状态 |
|---|---|---|---|
| 1 | P0 | 端口 8000 → `RAG_PORT`（默认 8003） | ✅ 已同步 |
| 2 | P0 | `HF_HUB_OFFLINE` 写死 "1" → `setdefault("0")` | ✅ 已同步 |
| 3 | P1 | 补 `CORSMiddleware`（文档承诺 CORS 已放开但代码缺失） | ✅ 已同步 |
| 4 | P1 | `_pick()` 未命中 → `raise FileNotFoundError`（防静默建空库） | ✅ 已同步 |
| 5 | P2 | `torch.set_num_threads(8)` → `RAG_THREADS` 环境变量 | ✅ 已同步 |
| 6 | P2 | 05 启动打印实际命中的内存索引目录 + collection_size | ✅ 已同步（RAG_MEM_DIR） |
| 7 | P2 | `/rag/search` 包 try/except，失败返回 `{"results":[],"error":...}` | ✅ 已同步 |
| 8 | P2 | `GET /question/{qid}` 未命中返回 404 | ✅ 已同步 |
| 9 | P2 | 环境变量覆盖位 `RAG_MEM_DIR` / `RAG_MAIN_DIR` / `RAG_PORT` / `RAG_THREADS` | ✅ 已同步 |
| 10 | P2 | 本 README 补：路径机制/端口/模型下载/依赖/适配表 | ✅ 本文件 |
| 11 | P2 | 说明文档同步（给1号文档） | ✅ 已同步 |
| 12 | P2 | 新增 `requirements-rag.txt`（RAG 专属依赖，不并入主 requirements） | ✅ 已新增 |

> 注意：1 号侧交付包已迁入 `backend/rag/` 并删除原目录；后续更新知识库时**保留 1 号代码改动**（或按上表同步到新版代码），只覆盖 `数据/` 和 `向量库/`。

## 运行顺序

```bash
# 第 1 步：生成 RAG 数据（主库 → jsonl，约几分钟）
python 01_generate_rag_data.py

# 第 2 步：构建内存索引（jsonl/已有 chroma → npz+pkl，CPU 约 2 小时，只需一次）
python rebuild_index_shard.py --out 交付包根目录/向量库
#   （若已有现成的 memory_index.npz + all_records.pkl，可跳过本步直接使用）

# 第 3 步：检索实测（双模式）
python 03_search_rag.py "Java 里 == 和 equals 的区别？"
python 03_search_rag.py "Java 里 == 和 equals 的区别？" --expand   # 深挖：取该题全部层级
python 03_search_rag.py "Redis 缓存穿透怎么办" --job "Java 后端开发工程师" --top 5

# 第 4 步：验证内存索引完整性
python 04_verify_collection.py
```

## 技术栈与选型理由

| 组件 | 选型 | 理由 |
|---|---|---|
| 向量模型 | `BAAI/bge-m3` | 中文语义检索标杆，1024 维，512 token，CPU 可跑 |
| 重排模型 | `BAAI/bge-reranker-v2-m3` | 交叉编码器，精排精度高（只对 Top-20 跑，代价可控） |
| 检索后端 | `MemoryRetriever`（内存精确余弦） | 305 修复后方案：numpy 全量余弦 Top-K，**精确无近似误差、零漏召** |
| 距离 | cosine | 编码前 normalize，点积即余弦 |

## 数据设计要点（为什么要这么做）

1. **主库 1 题 : RAG 3~5 条**：每题生成 7 类片段（原题基准款 / 语义变体 / L1-L3 追问 / 得分点拆分 / 前置知识点 / 场景化 / 答案变体），覆盖考生各种提问方式和碎片化回答。
2. **全部绑定原题ID**：检索命中任意变体都能映射回主库完整素材（18 字段），支撑面试官完整出题。
4. **两段式检索 + 双模式**：bge-m3 快速召回 → reranker 精排 → 按原题ID去重 → Top-N。
   - **出题模式**（默认）：按题去重取 Top-N 道不同题，给面试官选下一题；
   - **深挖模式**（`--expand`）：命中 1 题后按原题ID 取该题**全部层级片段**（原题/L1/L2/L3/得分点/铺垫/变体），支撑追问、逐点评分、降级引导——只取 1 条会丢信息。
4. **不入库内容**：五维评分细则、单题校准锚点、知识点学习建议——这些走主库 ID 查询，不进向量库。

## 踩过的坑（血泪教训，务必注意）

0. **HNSW 索引不同步（305 条丢失）**：ChromaDB 的 sqlite 元数据与 HNSW 二进制文件不一致时，检索直接报 `Error loading hnsw index`，且**任何 chromadb 版本都救不回**（版本无关，是文件损坏）。**当前已整体弃用 HNSW，改用内存精确余弦索引**——不要在交付包内再引入 chromadb 运行时依赖。
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
# 运行 03/04/05（推荐，不含 chromadb）：
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install sentence-transformers fastapi uvicorn pydantic -i https://pypi.tuna.tsinghua.edu.cn/simple
# 首次运行需下载模型（或已离线缓存）：
#   BAAI/bge-m3、BAAI/bge-reranker-v2-m3
# 离线环境设置 HF_HUB_OFFLINE=1 + HF_ENDPOINT=https://hf-mirror.com
# 仅当需要重建内存索引/向量库时，额外安装 chromadb==1.5.9（与构建环境一致）。
```
> **版本自测**：`python 04_verify_collection.py` 应显示 74011 条；若 05 启动日志显示
> `[memory] collection size: 0` → 是路径问题（memory_index.npz 未放对位置），先查 向量库/ 下是否有
> `memory_index.npz` 与 `all_records.pkl`。详见 `requirements-rag.txt`。
