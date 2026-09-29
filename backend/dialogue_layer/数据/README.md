# 这个目录是什么

⚠️ 本说明原为 P5 交付包中同路径的文件（写给「1 号」的换机器部署清单）。
2026-09-29 按本项目**实际落位方式**改写：题库不再随包、语音模型与索引的来路都变了，
照原文操作会找不到东西。

## 里面是什么

| 目录 / 文件 | 内容 | 来源 | 入库 |
| :--- | :--- | :--- | :--- |
| `kg/kg_question_graph.pkl` | 知识图谱，14.8MB | P5 后端包 | 是 |
| `学习资源样例.json` | 学习资源推荐的素材源，4.5MB | P5 后端包 | 是 |
| `rag/` | RAG 三件，约 256MB / 74011 条 | P5 的 RAG 数据包 | 否 |
| `kb_index/` | 知识库检索索引，约 150MB / 20396 块 | P5 的 KB 数据包 | 否 |
| `models/sensevoice-small/` | 语音转写模型，239MB | P5 后端包 | 否 |

**题库不在这里**：环境变量 `A11_MAIN_DB` 指向 `backend/rag/数据/`，与主项目共用一份
（两处的五个 `*-v5.json` 已按内容逐字段核对一致）。

对应关系：

| 目录 | 环境变量 | 缺了会怎样 |
| :--- | :--- | :--- |
| `kg/` | `A11_KG_PATH` | 静默降级：不避重、无深挖方向 |
| `rag/` | `A11_RAG_RETRIEVER_PY` + `RAG_MEM_DIR` | 静默降级（`/health.rag_error` 留一行）；且只在 `DIALOGUE_FULL=1` 时才加载 |
| `kb_index/` | `A11_KB_DIR` | 静默降级：学习资源少了知识库参考、面试少了知识库证据通道；同样只在全功能档加载 |
| `models/` | `SENSEVOICE_MODEL_DIR` | `/asr` 返 503（面试与文字作答照常）；`/health.asr_error` 会说明原因 |
| （根下）`学习资源样例.json` | `A11_RESOURCES_JSON` | 不影响面试：`recommendations` 只剩得分点级兜底 |

`rag/` 里那三个文件是**一套**：`all_records.pkl` 与 `memory_index.npz` 必须来自同一次构建
（检索器里有硬断言 `EXPECTED_N = 74011`）。**别只拷一个，也别拿别处的来配。**

`学习资源样例.json` 里含**得分点与核心答案**，与题库同一条红线：
**只在后端仓库里，绝不能给前端**。

## 模型权重

三份模型都不入 git，每台机器按下面的路子各备一份：

| 模型 | 位置 | 怎么来 |
| :--- | :--- | :--- |
| SenseVoice（转写） | `models/sensevoice-small/` | 随 P5 的后端包解压即可，**无公开下载路径** |
| reranker | `backend/.hf_cache/bge-reranker-v2-m3/` | ModelScope 下载。⚠️ **默认档下不需要它**——reranker 走在线（硅基流动 API）；只有在没配 `SILICONFLOW_API_KEY` 时才回退到本地这份 |
| 情感模型 | `backend/.hf_cache/wav2vec2-base-superb-er/` | P5 于 2026-09-26 直接给的权重（魔搭上没有）。⚠️ **默认档下也不加载**——情感标签由 SenseVoice 自己给；这份只在把 provider 切回 whisper 档时才用 |

下载命令（仅在需要回退本地档时执行）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
python -c "from modelscope import snapshot_download as d; d('BAAI/bge-reranker-v2-m3', local_dir='backend/.hf_cache/bge-reranker-v2-m3')"
```

## 别做的事

- **别改数据内容。** 题库与索引都是只读源头，改了就没法跟别人对账。
- **别把 `rag/` 或 `kb_index/` 挪进 git。** 它们加起来约 400MB，已 gitignore；
  换机器时从 P5 的数据包解压到位。
- **别把 `bank/` 拷进来。** 题库已经共用主项目那一份，多拷一份就会两边漂移。
