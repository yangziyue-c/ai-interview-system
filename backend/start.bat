@echo off
REM ============================================================
REM  AI 模拟面试系统 - 后端一键启动脚本（Windows）
REM  双击即可：自动准备 conda 环境、安装依赖、启动服务
REM ============================================================
chcp 65001 >nul
title AI模拟面试-后端服务
cd /d %~dp0

REM ---------- 1. 检查 conda ----------
where conda >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 conda，请先安装 Anaconda 或 Miniconda：
    echo        https://www.anaconda.com/download
    pause
    exit /b 1
)

REM ---------- 2. 检查/创建 conda 环境 ai_interview ----------
conda env list | findstr /c:"ai_interview" >nul
if errorlevel 1 (
    echo [首次运行] 正在创建 conda 环境 ai_interview（Python 3.12）...
    conda create -n ai_interview python=3.12 -y
    if errorlevel 1 (
        echo [错误] conda 环境创建失败
        pause
        exit /b 1
    )
)
call conda activate ai_interview

REM ---------- 3. 安装依赖（已安装则跳过） ----------
python -c "import fastapi, uvicorn, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo [首次运行] 正在安装依赖（约1-2分钟，请耐心等待）...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

REM ---------- 4. 初始化 .env（不存在时从示例复制） ----------
if not exist .env (
    copy .env.example .env >nul
    echo [提示] 已生成 .env 配置文件（默认 SQLite，如需 MySQL/Redis 请编辑 .env）
)

REM ---------- 5. 启动服务 ----------
echo ============================================================
echo   启动中... 浏览器访问: http://localhost:8000
echo   接口文档:      http://localhost:8000/docs
echo   局域网/穿透演示使用 0.0.0.0 绑定，CORS 已开放为 *
echo ============================================================
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
