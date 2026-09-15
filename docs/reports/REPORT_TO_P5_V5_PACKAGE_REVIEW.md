# 给 5 号（知识库）· V5 交付包评审与落地改动说明

> 评审对象：`交付包-1号后端_new/`（2026-09-14 版）
> 评审与适配人：1 号（后端主程）
> **结论：数据层质量优秀，路径问题已修复；另有 3 个阻塞项及若干功能缺陷/改进由 1 号在落地时一并修好（见第二节，共 13 处改动）。**
> **本副本已迁入 `backend/rag/`，交付包原目录已删除（见文末）。**

---

## 一、本次修复确认（✅ 做得好的地方）

| 项 | 状态 | 证据 |
|---|---|---|
| **路径自适应** | ✅ 已修复 | 01~05 五个脚本统一加入 `_pick()`：`_PKG_ROOT = dirname(dirname(abspath(__file__)))`，优先交付包内 `数据/`、`向量库/`，开发机路径作回退。解压即用的设计意图达成。 |
| **数据与向量库本体** | ✅ 未被误改 | `java-v5.json` md5 `e3dae9a1…`（2026-09-15 复核值；该文件自 09-14 提交后未再改动）。⚠️ `chroma.sqlite3` **每次打开都会被重写**、md5 必然变化，不适合做指纹校验 |
| **主库数据质量** | ✅ 优秀 | 5012 题 / 18 字段**零空值** / 题目 ID 无重复 / 格式 100% 规整（`{PREFIX}-Q{数字}`） |
| **追问字段格式** | ✅ 优秀 | `[触发] 条件` + `[追问] 文本`，**5012/5012 完全规整**——这是本次算法重做得以大幅简化的前提 |
| **向量库完整性** | ✅ 自洽 | `embeddings` 表 74011 条 = 说明文档口径；元数据 666,099 行（×9 字段）；向量 1024 维 FLOAT32 无空值 |
| **词表收敛** | ✅ 合理 | 题型由 V4 的 6 类收敛为 4 类、阶段由 4 个收敛为 3 个，去掉了低频类别 |

---

## 二、1 号在落地时做的改动（13 处）

**原因**：其中 P0 两项会直接导致服务跑不起来，故 1 号未等待反馈、先行修好并记录于此，
方便 5 号同步回自己的交付包版本。

### P0 阻塞项（不改则服务无法启动）

| # | 文件 | 改动 | 原因 |
|---|---|---|---|
| 1 | `05_rag_api_server.py` | `uvicorn.run(..., port=8000)` → `int(os.environ.get("RAG_PORT", "8003"))` | 8000 被本机 Godot AI MCP 占用（项目铁律）；项目约定 8001 主后端 / 8002 评估 / **8003 RAG** |
| 2 | 四个脚本（`02`/`03`/`04`/`05`） | `os.environ["HF_HUB_OFFLINE"] = "1"` → `os.environ.setdefault("HF_HUB_OFFLINE", "0")` | **交付包不含模型文件**（bge-m3 + reranker 共约 4.5GB），成员机器通常也无 HF 缓存；写死 `1` 会在首次启动时抛 `OSError: We couldn't connect to huggingface.co`。注：`01_generate_rag_data.py` 不加载模型，本就无此行 |

### P1 功能缺陷

| # | 文件 | 改动 | 原因 |
|---|---|---|---|
| 3 | `05` | 补 `CORSMiddleware`（`allow_origins=["*"]`） | 原说明文档第 23 行承诺「CORS 已放开，4 号前端也可直接调用」，但代码中**无中间件**，浏览器跨域会被拦 |
| 4 | 五个脚本 | `_pick()` 全部未命中时 `raise FileNotFoundError(已尝试路径列表)` | 原实现返回 `candidates[0]`（无效路径）→ `chromadb.PersistentClient(path=无效路径)` **静默创建空库**（不抛错）→ 服务正常启动但检索永远无结果，**排查成本极高** |

### P2 改进项

| # | 文件 | 改动 | 原因 |
|---|---|---|---|
| 5 | `02`/`03`/`05` | `torch.set_num_threads(8)` → `int(os.environ.get("RAG_THREADS", os.cpu_count() or 8))` | 部署机 28 核，写死 8 浪费算力 |
| 6 | `05` | 启动打印**实际命中**的 `CHROMA_DIR` / `MAIN_DIR` + `collection_size` | 路径问题一眼可见（配合改动 4 的快速失败） |
| 7 | `05` | `/rag/search` 包 try/except，失败返回 `{"results": [], "error": "..."}` | 原实现查询异常直接 500，调用方无法降级 |
| 8 | `05` | `GET /question/{qid}` 未命中返回 **404** | 原为 HTTP 200 + `error` 字段，不符合 REST 语义（无既有调用方，改动无破坏） |
| 9 | `05` | 新增环境变量覆盖位：`RAG_CHROMA_DIR` / `RAG_MAIN_DIR` / `RAG_PORT` / `RAG_THREADS` | 部署时目录结构可能与交付包不同，原实现只能靠目录结构 |
| 10 | `代码/README.md` | 补：路径自适应机制、端口说明、模型体积与下载命令、依赖清单、**1 号适配说明表** | 成员才敢放心搬动目录 |
| 11 | `说明/给1号-后端主程-数据对接说明.md` | 同步：路径改项目内、端口 8003、CORS、依赖与模型下载、`GET /question/{id}` 契约 | 原文仍写 `E:\GitHubRepos\…`、端口 8000、「5 号已封装好直接启动」 |
| 12 | **新增** `backend/rag/requirements-rag.txt` | RAG 专属依赖清单 + 国内镜像安装命令 | 依赖刻意**不写进** `backend/requirements.txt`：主流程（8001/8002）不依赖它们，写进去会让每个新环境都多下载 2.5GB |

### P0 阻塞项（2026-09-14 追加，**5 号务必同步回交付包**）

| # | 文件 | 改动 | 原因 |
|---|---|---|---|
| 13 | `02`/`03`/`04`/`05` | 向量库目录 `向量库/` → **`vector_db/`**（四个脚本均带自动改名升级）+ 打开前非 ASCII 路径守卫 | **chromadb 无法打开「含非 ASCII 字符的绝对路径」**（见第六节，实测 10/10 失败）。**构建侧同样受灾**：本机用 `backend/rag/向量库/chroma_db_v2` 这个中文绝对路径重建向量库，跑满 6 小时、`col.count()` 也报 74011，但产出的库**缺 HNSW 索引文件**（`data_level0.bin` 等全部没有，只剩 `index_metadata.pickle`），事后完全无法打开 |

> **推荐 P5 在交付包里直接把目录改名为 `vector_db/`**（或任何纯 ASCII 名），
> 从源头避免成员机器上重演这个问题。脚本已做自动升级，旧名也不会报错，
> 但**每一次"能跑"都依赖那个自动改名成功**，不如命名时就避开。

**未改动**：检索核心逻辑（`03` 的双模式检索、`05` 的 `/rag/search` 响应结构）保持原样，
1 号侧通过适配器接入（见《REPORT_TEAM_V5_LAYOUT_AND_API.md》）。

---

## 三、数据层已知问题（不影响使用，供 5 号参考）

| 项 | 现状 | 影响与建议 |
|---|---|---|
| **HNSW 索引少于记录数** | `header.bin` 第 20 字节 = **73706**，`index_metadata.pickle` 的 `total_elements_added` = **73706**，而 sqlite `embeddings` 表 = **74011**（差 **305 条，0.41%**）；同时 `embeddings_queue` 残留 **306 条**未消费记录 | 这是构建进程最后一批写入后被中断留下的尾巴。记录、元数据、向量 BLOB 都在 sqlite 里没丢，只是没进 HNSW 图索引。ChromaDB 下次打开时应会通过 WAL 重放自动补齐；即便不补也只影响 0.41% 的召回。**首次启用前建议**跑一次 `PRAGMA wal_checkpoint(TRUNCATE)`，再用 `04_verify_collection.py` 确认 `count()==74011` |
| `build_v2_done.json` 未随包提供 | 重建向量库时的断点标记文件缺失 | 仅影响「重建」场景（`02_build_vector_db.py` 会重新生成），使用现成向量库不需要 |
| 1 组重复题干 | 「什么是优先级队列？」在算法岗与系统设计岗各 1 道 | **属正常**：跨岗位考察同一知识点，ID 不同 |
| 主库无「参考答案」字段 | V5 只有基础/进阶得分点 | 设计合理（面试场景下得分点比标准答案更有用）；RAG 条目的「参考答案」由 `01` 脚本拼装得到 |

---

## 四、⚠️ 交付包机制已取消：**以后所有修改都在 `backend/rag/` 路径下**（重要）

**2026-09-14 起，「交付包 / 外发压缩包」这一环节正式取消。**
知识库内容已**完整迁入项目内**，原交付包目录已删除：

```
交付包-1号后端_new/代码/     → backend/rag/代码/
交付包-1号后端_new/数据/     → backend/rag/数据/
交付包-1号后端_new/向量库/   → backend/rag/vector_db/
交付包-1号后端_new/说明/     → backend/rag/说明/
```

迁移前已做校验：文件数逐目录比对（23 个）+ `java-v5.json` / `chroma.sqlite3` md5 比对，全部一致。

### 4.1 你后续怎么改（**唯一正确路径**）

**直接在项目内改，不要再打包外发，也不要把项目文件复制到仓库之外**：

| 你要改什么 | 改哪里 | 改完做什么 |
| :--- | :--- | :--- |
| 题目内容 / 得分点 / 追问 / 校准锚点 | `backend/rag/数据/{岗位}-v5.json`（18 字段） | 跑导入命令（见 [REPORT_TO_P5.md](REPORT_TO_P5.md) 第三节） |
| RAG 检索的数据与向量 | 先跑 `代码/01` 生成 jsonl，再 `代码/02` 重建向量库 | 见 `代码/README.md`（CPU 约 3~7 小时，支持断点续跑） |
| 检索服务逻辑 | `backend/rag/代码/*.py` | ⚠️ 保留 1 号的 13 处适配改动（见第二节），或按本报告把改动同步到新版本 |

### 4.2 两条不可违背的约束

1. **向量库目录名必须保持纯 ASCII**（现名 `backend/rag/vector_db/`，**禁止中文名**）——
   chromadb 打不开含非 ASCII 字符的绝对路径，**构建侧与读取侧都会失效**
   （完整排查记录见第六节）。
2. **数据文件必须留在 `backend/rag/数据/` 下**——导入脚本、RAG 服务、向量库构建脚本
   三者共用这一个源目录，挪走任何一处都会导致链路断裂。

> **为什么取消交付包**：V5 之后知识库与主项目已是同一个仓库、同一份数据源，
> 中间再插一道「打包 → 搬运 → 解压」只会增加出错环节——本轮踩到的模型路径、
> 端口占用、依赖体积几个坑，都是这层包装带来的。

---

## 五、验收清单（5 号修复/更新后可自测）

```bash
cd backend/rag/代码

# 1. 依赖（约 2.5GB，走国内镜像）
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install chromadb sentence-transformers -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 首次启动需下载模型（约 4.5GB，走 hf-mirror）
set HF_ENDPOINT=https://hf-mirror.com
python 05_rag_api_server.py          # 应打印实际命中的向量库/主库路径 + collection size: 74011
curl http://localhost:8003/health    # {"status":"ok","collection_size":74011}

# 3. 检索可用
curl -X POST http://localhost:8003/rag/search -H "Content-Type: application/json" \
     -d '{"query":"Redis 缓存穿透怎么办","mode":"select","top":3}'

# 4. 主库接口
curl http://localhost:8003/question/JAVA_BACKEND-Q0001   # 返回 18 字段完整记录

# 5. 路径失效时应明确报错（而非静默建空库）
mv vector_db vector_db_bak && python 05_rag_api_server.py   # 应抛 FileNotFoundError
mv vector_db_bak vector_db

# 6. 向量库目录名会被强制校验为纯 ASCII（见第六节）
RAG_CHROMA_DIR="D:/测试库/chroma_db_v2" python 05_rag_api_server.py   # 应抛 RuntimeError
```

---

## 六、⚠️ chromadb 路径陷阱（2026-09-14 实测，**建议 5 号收进自己的知识库**）

### 6.1 现象

把向量库放在**含中文字符的路径**下（如 `backend/rag/向量库/chroma_db_v2`），
用**绝对路径**打开它时 100% 失败：

```
chromadb.errors.InternalError: Error executing plan:
  Error sending backfill request to compactor:
    Error constructing hnsw segment reader:
      Error creating hnsw segment reader:
        Error loading hnsw index
```

关键特征——**同一份数据、同一个进程、同一个目录**，只是路径写法不同：

| 传入 `PersistentClient(path=...)` 的写法 | 结果 |
|---|---|
| `chroma_db_v2`（相对路径，cwd 在该目录内） | ✅ 10/10 成功 |
| `d:/.../rag/vector_db/chroma_db_v2`（纯 ASCII 绝对路径） | ✅ 成功 |
| `d:/.../rag/向量库/chroma_db_v2`（**含中文的绝对路径**） | ❌ **0/10 失败** |

### 6.2 为什么这个 bug 极难定位（1 号踩坑记录）

`Error loading hnsw index` 这个报错**指向完全错误的方向**，1 号据此走了三段弯路：

1. **误判为「chromadb 版本不兼容」** —— 因为交付包是 5 号在另一台机器上构建的，
   第一反应是 Rust 版与 Python 版 HNSW 格式不同。
2. **误判为「HNSW 索引未落盘」** —— 用中文绝对路径重建后，`header.bin` 里元素数
   写着 73706、`data_level0.bin` 大小也精确等于 `73706 × 4236` 字节，
   **所有静态检查都自洽**，只看文件根本看不出问题。
3. **最误导的一点**：构建脚本结尾的 `col.count()` 会**如实返回 74011**——
   因为它读的是 SQLite 里的记录数，**而不是 HNSW 图索引**。于是日志上一切正常
   （`[done] build complete`），产出的库却是坏的。

**最终定位手段**：把 `同一份库` 复制到纯 ASCII 路径后**立刻正常**；
再把路径写法做成上表的对照实验，才锁定是「非 ASCII 绝对路径」。

### 6.3 影响范围（不止"打不开"）

| 环节 | 是否受影响 |
|---|---|
| **读取**（`PersistentClient` 打开） | ❌ 100% 失败 |
| **构建**（`02_build_vector_db.py` 写入） | ❌ **同样受灾**：`col.add()` 看着都成功，但 **HNSW 数据文件根本没落盘**，产出目录里只剩一个 `index_metadata.pickle` |
| SQLite 部分（记录数、元数据、WAL） | ✅ 正常，所以 `count()` 会骗人 |
| 纯 Python 文件读写（`数据/*-v5.json` 等） | ✅ 正常（只有 chromadb 受影响） |

> 这也解释了为什么交付包在 5 号机器上一切正常——**5 号的开发路径是纯 ASCII
> （`E:\GitHubRepos\...`）**，问题只有在中文路径下才暴露。

### 6.4 修复

1. **目录改名**：`backend/rag/向量库/` → **`backend/rag/vector_db/`**（纯 ASCII）；
2. **四个脚本**（`02`/`03`/`04`/`05`）都加了：旧目录名自动升级 + 打开前非 ASCII 守卫
   （命中时抛 `RuntimeError` 并直接告诉你怎么改，而不是让你看到「索引加载失败」）；
3. **教训**：给向量库/模型目录命名时**一律用纯 ASCII**，别等出问题再回头查。

### 6.5 附：同批发现的另一个真实缺陷（1 号侧，已在 `backend/app/config.py` 修正）

`RAG_TIMEOUT_SECONDS` 原设 **5 秒**，而一次 `/rag/search`（含 Top-20 reranker 精排）
在 CPU 上**实测 20~30 秒**（向量召回本身仅 0.1 秒，瓶颈全在 reranker）。
后果是**每一次检索都超时**，主后端把 RAG 误判为「不可用」而静默降级——
表面上「有兜底所以不报错」，实际 RAG 这一级**从未真正生效过**。
已改为 **60 秒**。5 号若在其他机器部署，请一并核对这个预算。

---

## 七、致谢

V5 主库的**结构化改造**（把 V4 挤在一段文本里的四层追问拆成独立字段）是本项目本次换代
最有价值的一项工作——它让下游算法直接删掉了 119 行格式兼容正则，追问链触达率从 66% 提升到 100%。
追问字段格式能做到 **5012/5012 完全规整**，也说明数据生产端做了扎实的自检。
