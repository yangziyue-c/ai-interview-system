# Git 运行资源说明

本仓库的主代码、题库和知识图谱已经完整入库。为了让克隆后的项目具备
RAG、知识库检索和浏览器语音输入能力，运行资源采用 **zstd 压缩 + 普通 Git 分片**
保存。

这样处理是因为 Gitee 社区版官方限制为：

- 单仓库最大 500 MB
- 单文件最大 50 MB
- Git LFS 仅对付费企业开放

## 随仓库保存的内容

| 运行时文件 | 原始大小 | 仓库保存方式 |
| :--- | ---: | :--- |
| `backend/dialogue_layer/数据/rag/all_records.pkl` | 82,594,012 B | zstd |
| `backend/dialogue_layer/数据/rag/memory_index.npz` | 250,324,230 B | 6 个普通 Git 分片 |
| `backend/dialogue_layer/数据/kb_index/kb_fts.sqlite` | 46,039,040 B | zstd |
| `backend/dialogue_layer/数据/kb_index/kb_index.npz` | 77,644,915 B | 2 个普通 Git 分片 |
| `backend/dialogue_layer/数据/kb_index/kb_records.pkl` | 27,140,111 B | zstd |
| `frontend/ai-interview-front/public/model.tar.gz` | 43,867,744 B | zstd |

提交包位于 `runtime-assets/`，总大小约 400.5 MB。单个分片最大 45 MiB，满足
Gitee 社区版单文件 50 MB 的限制。

RAG 索引基于 **2026-09-29 主库的最终重建版本**，不是旧的 74,011 条索引。
实际运行时为 76,222 条 x 1024 维；KB 为 20,396 块 x 1024 维。
完整大小和 SHA-256 以仓库根目录 `runtime_assets.manifest.json` 为准。

## 首次恢复

```powershell
powershell -ExecutionPolicy Bypass -File tools/restore-runtime-assets.ps1
```

恢复脚本会执行以下操作：

1. 校验 `runtime-assets/` 中全部分片的 SHA-256。
2. 解压或拼接 RAG、KB 和 Vosk 运行时文件。
3. 再次按原始文件大小和 SHA-256 校验。
4. 把 MediaPipe `vendor` 复制到正式前端和 `backend/static`。
5. 把 Vosk `model.tar.gz` 复制到 `backend/static`。

`frontend/public/vendor/`、`backend/static/vendor/` 和
`backend/static/model.tar.gz` 是运行副本，仍在 `.gitignore` 中，避免重复占用仓库。

## 校验提交包

只校验仓库里的压缩分片，不解压、不复制：

```powershell
powershell -ExecutionPolicy Bypass -File tools/restore-runtime-assets.ps1 -VerifyOnly
```

脚本内置 `tools/bin/zstd.exe` 及其 BSD 许可证，不要求本机预先安装 zstd。

## 不入库的模型与派生物

- SenseVoice：约 239 MB，放部署数据包，无公开下载地址。
- bge-reranker：约 2.14 GB，默认走 SiliconFlow 在线服务，本地回退时单独下载。
- 旧 ChromaDB `vector_db/`：当前使用 MemoryRetriever，不再需要提交。
- `*-rag-v2.jsonl`：可由仓库已跟踪的五个 V5 主题库重新生成。
- `vosk-model-small-cn/`：是 `model.tar.gz` 的解包副本，运行代码不直接读取。
- `.env`、API Key、SQLite 数据库、上传音频、简历：涉及密钥或隐私，永远不入库。
