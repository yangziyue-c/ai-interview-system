# ============================================================
# run.ps1 · 启动 A11 AI 面试官框架（2 号 AI 对话层）
# ============================================================
# 双击「一键启动.bat」等同于此脚本。
# 所有环境变量都在这里设好，服务代码本身不依赖外部 shell 配置。
#
# ⚠️ PowerShell 5.1 语法约束：没有 && 链式、没有三元运算符。
#    本文件已按 5.1 写，改的时候别用新语法。

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  A11 AI 面试官框架 · 2 号 AI 对话层" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 1) 模型缓存：走本地缓存 + 离线模式
# ------------------------------------------------------------
# 交接说明第七节：D:\A11-Data\hf_cache 是 8.71GB 的模型缓存，不要动。
# 设了 HF_HOME 才能命中它；离线开关避免每次启动去联网校验（慢且会失败）。
if (-not $env:HF_HOME) { $env:HF_HOME = "D:\A11-Data\hf_cache" }
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
Write-Host "[env] HF_HOME = $env:HF_HOME" -ForegroundColor DarkGray

# ------------------------------------------------------------
# 2) 评分设备
# ------------------------------------------------------------
# 交接说明提到 reranker 上 GPU 可能 OOM，所以默认走 CPU。
# 要用 GPU：把下面这行改成 "cuda"（或 "auto" = 有 CUDA 就用）。
#
# ⚠️ 不要用 CUDA_VISIBLE_DEVICES="" 来禁用 GPU —— PowerShell 里给环境变量
#    赋空串是**删除该变量**，不是设成空值，结果 CUDA 反而可见、照样上 GPU。
#    这里显式设 SCORER_DEVICE，由 scoring.resolve_device() 直接读取，语义明确。
if (-not $env:SCORER_DEVICE) { $env:SCORER_DEVICE = "cpu" }
Write-Host "[env] SCORER_DEVICE = $env:SCORER_DEVICE" -ForegroundColor DarkGray

# ------------------------------------------------------------
# 3) 端口
# ------------------------------------------------------------
# 铁律：8000 被 Godot AI MCP 占用，绝不要用。
# 8001/8002 主后端与评估，8003 RAG，8004 旧 hyphen 版框架 → 本框架用 8005。
if (-not $env:FRAMEWORK_PORT) { $env:FRAMEWORK_PORT = "8005" }
Write-Host "[env] 端口 = $env:FRAMEWORK_PORT" -ForegroundColor DarkGray

# ------------------------------------------------------------
# 4) API key
# ------------------------------------------------------------
# ⚠️ local_env.ps1 只做 dot-source 读取，**绝不修改该文件**。
#    key 的值不打印、不写日志。
if (-not $env:DEEPSEEK_API_KEY) {
    $keyFile = "D:\A11-Data\interview_framework\local_env.ps1"
    if (Test-Path $keyFile) {
        . $keyFile
        Write-Host "[key] 已从 local_env.ps1 载入" -ForegroundColor DarkGray
    }
}
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Host "[key] ⚠️ 未设置 DEEPSEEK_API_KEY —— 服务能起来，但 /chat 与 /finish 会失败。" -ForegroundColor Yellow
    Write-Host "      解决：在启动前执行  `$env:DEEPSEEK_API_KEY='sk-xxxx'" -ForegroundColor Yellow
    Write-Host "      或跑冒烟测试（不需要 key）：`$env:LLM_MOCK='1'; & `$py smoke_test.py" -ForegroundColor Yellow
} else {
    Write-Host "[key] DEEPSEEK_API_KEY 已就绪" -ForegroundColor DarkGray
}

# ------------------------------------------------------------
# 5) Python 解释器
# ------------------------------------------------------------
# 依赖都装在豆包沙箱的 python 里（openai / fastapi / sentence_transformers / torch）。
# 换机器或换解释器：设环境变量 A11_PYTHON 覆盖。
if (-not $env:A11_PYTHON) {
    $env:A11_PYTHON = "C:\Users\litao\AppData\Local\Doubao\User Data\sandbox_runtime\bases\c98c5042338ed152c6f10ecd8591889f\python\python.exe"
}
if (-not (Test-Path $env:A11_PYTHON)) {
    Write-Host "[py] ✗ 找不到解释器：$env:A11_PYTHON" -ForegroundColor Red
    Write-Host "     请设 A11_PYTHON 指向装了 requirements.txt 的 python。" -ForegroundColor Red
    exit 1
}
Write-Host "[py] $env:A11_PYTHON" -ForegroundColor DarkGray
Write-Host ""
Write-Host "测试页 http://127.0.0.1:$env:FRAMEWORK_PORT/ui/test_chat.html" -ForegroundColor Green
Write-Host "接口文档 http://127.0.0.1:$env:FRAMEWORK_PORT/docs" -ForegroundColor Green
Write-Host "按 Ctrl+C 停止" -ForegroundColor DarkGray
Write-Host ""

& $env:A11_PYTHON "app\main.py"
