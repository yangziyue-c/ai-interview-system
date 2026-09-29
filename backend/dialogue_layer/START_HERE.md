# A11 后端交接包

这是当前 A11 AI 面试官后端的最小可运行交接包。

## 包内内容

- `app/`：FastAPI 服务、会话状态机、评分、RAG/KG 接口、ASR、TTS、摄像头接口。
- `web/`：随服务挂载的参考测试页。
- `data/bank/`：五个岗位题库 JSON。
- `data/kg/`：知识图谱文件。
- `data/models/sensevoice-small/`：本地语音识别模型和 Silero VAD。
- `requirements-handoff.txt`：轻量在线模式所需依赖。
- `requirements-full.txt`：当前本机完整依赖清单，备查。
- `start_a11.ps1`：按相对路径启动服务。
- `setup_a11.ps1`：创建虚拟环境并安装依赖。
- `local_env.template.ps1`：环境变量模板，不含任何真实 Key。

## 不含内容

- 任何 API Key。
- 真实用户隐私数据。
- RAG 全量索引和知识库索引。
- 个人开发机的绝对路径。

## 快速启动

```powershell
cd D:\A11-Backend-Handoff
Copy-Item .\local_env.template.ps1 .\local_env.ps1
notepad .\local_env.ps1
.\setup_a11.ps1
.\start_a11.ps1
```

打开：

```text
http://127.0.0.1:8005/ui/test_chat.html
http://127.0.0.1:8005/docs
http://127.0.0.1:8005/health
```

## 默认能力

这个包默认是轻量模式：

- 本地题库：开启
- 知识图谱：开启
- 在线主观评分：开启
- 在线客观评分：开启
- 在线 Reranker：开启
- 在线 TTS：开启
- 在线大 ASR：考生同意后开启
- 本地 SenseVoice 兜底：按需加载
- 本地 RAG：默认关闭
- 本地 KB 检索：默认关闭

这样可以保持服务常驻内存较低。需要全功能 RAG/KB 时，另行补齐对应索引并关闭轻量模式。

## 必须先配置的环境

把 `local_env.template.ps1` 复制为 `local_env.ps1`，填写自己的 Key：

```text
DEEPSEEK_API_KEY
SILICONFLOW_API_KEY
SILICONFLOW_BASE_URL
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
```

不要把 `local_env.ps1` 提交到 Git，也不要发到公开群。

## 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8005/health
```

重点看：

```text
status=ok
llm_configured=true
scorer_ready=true
objective_ready=true
tts_ready=true
online_asr_ready=true
kg_ready=true
```

`rag_ready=false` 在轻量模式下是正常的。

## 验收

```powershell
$env:LLM_MOCK='1'
$env:RERANKER_MOCK='1'
$env:A11_ASR_MOCK='1'
python smoke_test.py
```

最后必须看到失败数为 `0`。
