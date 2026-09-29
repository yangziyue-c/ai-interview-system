# 部署与排障

## Python

建议 Python 3.11 或 3.12。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-handoff.txt
```

## 服务启动

`start_a11.ps1` 会自动设置这些相对路径：

```text
A11_MAIN_DB=<包目录>\data\bank
A11_KG_PATH=<包目录>\data\kg\kg_question_graph.pkl
SENSEVOICE_MODEL_DIR=<包目录>\data\models\sensevoice-small
```

默认还设置：

```text
A11_RAG=0
A11_KB_REC=0
A11_RAG_KB=0
```

因此后端不需要个人电脑上的绝对路径。

## 全功能模式

全功能模式需要额外准备：

```text
题库派生 RAG 索引
知识库 KB 索引
```

准备好后：

```powershell
.\start_a11.ps1 -Full
```

并且确认对应索引路径已写入环境变量。

## 端口

默认端口：

```text
8005
```

改端口：

```powershell
$env:FRAMEWORK_PORT='8010'
.\start_a11.ps1
```

## 语音

- 不勾选“允许音频上传在线转写”时：本地 SenseVoice。
- 勾选后：优先在线大 ASR，在线失败时自动回退本地 SenseVoice。
- 本地模型是懒加载，不调用语音时不会占内存。
- 音频只写系统临时文件，转写后立即删除。

## 常见问题

### 服务起不来

先检查：

```powershell
.\.venv\Scripts\python.exe -c "import fastapi,pydantic,httpx,sherpa_onnx,av; print('deps ok')"
```

缺少 `python-multipart` 时 FastAPI 会在注册 `/asr` 时直接启动失败。

### 评分不可用

检查 `/health`：

```text
llm_configured
scorer_ready
objective_ready
```

同时检查 `local_env.ps1` 中的 DeepSeek、Qwen、SiliconFlow 配置。

### 语音不可用

检查：

```text
online_asr_ready
asr_error
SENSEVOICE_MODEL_DIR
```

在线 ASR 和本地 ASR 是两条独立链路，在线失败会回退本地。

### 报告缺少 RAG/KB

轻量模式下这是预期行为。补齐索引并关闭轻量模式后才会生效。

## 安全

- 不把 `local_env.ps1` 打进最终公开包。
- 不把音频、视频、用户简历写进日志。
- `raw` 默认脱敏，不要随意改成全量对外暴露。
- `A11_RAW_DETAIL` 只在需要内部评估明细时临时打开。
