# 这个目录是什么（给 1 号）

> 由 `gen_数据.py` 生成。**这里是数据，不是文档** —— 完整说明看上一级目录的
> **`交付说明-后端.md` §5.5「换机器部署清单」**（权威），这里只放这一层需要知道的。

## 里面是什么

| 目录 | 文件 | 字节 | 体量 |
|---|---|---|---|
| `bank\` | `java-v5.json` | 6,672,994 | 6.4 MB |
| `bank\` | `web-v5.json` | 2,396,610 | 2.3 MB |
| `bank\` | `test-v5.json` | 1,877,992 | 1.8 MB |
| `bank\` | `algorithm-v5.json` | 2,455,586 | 2.3 MB |
| `bank\` | `system-design-v5.json` | 2,571,825 | 2.5 MB |
| `kg\` | `kg_question_graph.pkl` | 14,804,469 | 14.1 MB |
| `rag\` | `memory_retriever.py` | 7,738 | 7.6 KB |
| `rag\` | `all_records.pkl` | 71,412,669 | 68.1 MB |
| `rag\` | `memory_index.npz` | 158,639,920 | 151.3 MB |
| （`数据\` 根下） | `学习资源样例.json` | 4,708,295 | 4.5 MB |
| | **合计** | **265,548,098** | **253.2 MB** |

对应关系（`环境变量.模板.ps1` 已经替你设好了，都是相对本包根的）：

| 目录 | 环境变量 | 缺了会怎样 |
|---|---|---|
| `bank\` | `A11_MAIN_DB` | **服务照起，第一次 `/next` 才 500** |
| `kg\` | `A11_KG_PATH` | 静默降级：不避重、无深挖方向 |
| `rag\` | `A11_RAG_RETRIEVER_PY` + `RAG_MEM_DIR` | 静默降级（`/health.rag_error` 留一行） |
| （根下）`学习资源样例.json` | `A11_RESOURCES_JSON`（**不用设**） | 不影响面试：`recommendations` 只剩得分点级兜底，`/health.resource_error` 会说明原因 |

`rag\` 里那三个文件是**一套**：`all_records.pkl` 与 `memory_index.npz` 必须来自同一次构建
（检索器里有硬断言 `EXPECTED_N = 74011`）。**别只拷一个，也别拿别处的来配。**

`学习资源样例.json`（4.5 MB，2026-09-25 从 174 KB 涨上来的 —— 别拿旧尺寸认它）是
**学习资源推荐（4a）**用的配置数据，一半按考点、一半按题号：
- `岗位[]` 那棵树：**5 岗位 / 25 考点 / 50 道代表题**，每条给出
  「考点讲解 / 优秀回答范例 / 拉开差距 / 常见卡点」；
- 顶层 `题目范文` 那张**平索引**：**题号 → {范文, kind}，5,012 道题全覆盖**。
  为什么要有第二份：树那份挂在考点上，**1,110 道题一个考点都不挂**，只靠树取不到；
  平索引是按题号挂的，`/model_answer` 传 `question_id` 就走它。
  ⚠️ `kind` 有两档：`范文` 4,021 条 / **`示范作答` 991 条**。后者那些题在主库里
  **只有 STAR 骨架、没有判分内容**，那条「范例」是模型照结构编的通用示例，
  **不是**真题的优秀答案 —— 前端**必须把同一条返回里的 `note` 显示出来**。

它在 `数据\` 根下，代码默认就找这里
（`config.RESOURCE_JSON_CANDIDATES` 第一条 = `<包根>\数据\学习资源样例.json`），
所以**不用设任何环境变量**。

> ⚠️ 这个文件里有**得分点与核心答案**（它的「来源题」还带题目原文），
> 所以它和题库是同一条红线：**只在本包（1 号）里，绝不能给 4 号 或任何前端**。

## 两件要紧的事

1. **先核一遍没坏**（只读、不联网）。在**本目录**里跑：

   ```powershell
   & $env:A11_PYTHON 校验数据.py
   ```

   期望最后一行 `[OK] 10/10 全部一致 —— 数据没坏。` 且退出码 0。
   它核的是每个文件的**字节数 + SHA256**，所以能查出「解压到一半断了」这类问题。
   ⚠️ 它**不是** `check_env.py`：那个查的是运行时环境（路径 / 依赖 / 内存）。两个都要跑。

2. **模型权重不在这个包里**（两个 6.4 GB + 语音 464 MB + 情感 361 MB，全是公开权重，联网下更快）。
   命令在 `交付说明-后端.md` §5.5，一句话版：

   ```powershell
   $env:HF_ENDPOINT = "https://hf-mirror.com"
   & $env:A11_PYTHON -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-reranker-v2-m3'); d('BAAI/bge-m3'); d('Systran/faster-whisper-small'); d('superb/wav2vec2-base-superb-er')"
   ```

   `bge-reranker-v2-m3`（约 2.14 GB）**必须有** —— 缺了不报错，但分数是错的；
   `bge-m3`（约 4.25 GB）只有开 RAG 才要；
   `faster-whisper-small`（约 464 MB）只有要用语音输入才要 —— 缺了只是 `/asr` 用不了
   （面试与文字作答照常），/health 的 `asr_error` 会写明原因；
   `wav2vec2-base-superb-er`（约 361 MB，**2026-09-25 新增**）是**赛题 3b 情感分析**
   那一层要的 —— 缺了也只是 `/asr` 里情感/自信度那几个键为 `null`（其余一字不变），
   `/health` 的 `emotion_error` 会写明原因。**不是必装件**，但演示 3b 就缺不了它。
   ⚠️ 这四份都装在 `HF_HOME` 下，但**目录形状不一样**：两个 BGE **和情感模型**在
   `HF_HOME\hub\` 里（`models--superb--wav2vec2-base-superb-er`），whisper 在
   `HF_HOME\` 根下（`models--Systran--faster-whisper-small`）—— 因为 `asr.py` 给
   `WhisperModel` 显式传了 `download_root`。**拷缓存时别只拷 `hub\`，也别只拷根下。**

## 别做的事

- **别改文件名。** `bank\` 里那 5 个 `*-v5.json` 的名字是代码里写死的
  （`config.JOB_FILE_MAP` 按名字拼路径）。目录名可以随便改，文件名不行。
- **别改数据内容。** 题库是只读源头，改了就没法跟别人对账了。
- **别把 `bank\` 换成一整个 `v5\` 目录。** 那个原始目录 634 MB，95% 是脚本、
  `.bak` 备份和 `*-rag-v2.jsonl` 片段 —— 真正要的只有这 5 个 JSON（15.2 MB）。
