@echo off
chcp 65001 >nul
REM ============================================================
REM  AI Interview System - one-click start script (Windows)
REM  Double click: prepare conda env, install deps, start server
REM ============================================================
title AI Interview Backend
cd /d %~dp0

REM ---------- 1. 检查 conda ----------
where conda >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 conda，请先安装 Anaconda 或 Miniconda
    pause
    exit /b 1
)

REM ---------- 2. 定位 conda base 目录 ----------
REM conda 首次运行会输出 ToS 确认等额外文本污染 stdout，
REM 因此只取以盘符（如 C:）开头的路径行
set "CONDA_BASE="
for /f "delims=" %%B in ('conda info --base 2^>nul') do (
    echo %%B | findstr /b /r "[A-Za-z]:" >nul && set "CONDA_BASE=%%B"
)
if not defined CONDA_BASE (
    echo [错误] 无法定位 conda 安装目录。请在 cmd 中运行 conda info --base 查看输出并联系 P1
    pause
    exit /b 1
)
set "PYTHON=%CONDA_BASE%\envs\ai_interview\python.exe"

REM ---------- 3. 检查/创建 conda 环境 ----------
if not exist "%PYTHON%" (
    echo [首次运行] 正在创建 conda 环境 ai_interview（Python 3.12）...
    REM conda 可能是 .bat 程序，必须用 call 调用，否则本脚本会提前终止
    call conda create -n ai_interview python=3.12 -y
    if not exist "%PYTHON%" (
        echo [错误] conda 环境创建失败，请检查网络后重试
        pause
        exit /b 1
    )
)

REM ---------- 4. 安装依赖（已安装则跳过） ----------
"%PYTHON%" -c "import fastapi, uvicorn, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo [首次运行] 正在安装依赖（约1-2分钟，请耐心等待）...
    call "%PYTHON%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

REM ---------- 5. 初始化 .env ----------
if not exist .env (
    copy .env.example .env >nul
    echo [提示] 已生成 .env 配置文件
)

REM ---------- 6. 检查端口占用 ----------
netstat -ano | findstr ":8001" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [错误] 端口 8001 已被占用。请先关闭占用该端口的程序（可能是上次未关闭的服务窗口）
    echo        或修改本脚本中的端口号（--port 8001 两处同步修改）
    pause
    exit /b 1
)

REM ---------- 7. 启动服务 ----------
echo ============================================================
echo   启动中... 浏览器访问: http://localhost:8001
echo   接口文档:      http://localhost:8001/docs
echo   停止服务:      关闭本窗口
echo ============================================================
"%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8001
pause
