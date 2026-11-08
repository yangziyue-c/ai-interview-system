@echo off
REM Offline launcher: no LLM, RAG, evaluator, or dialogue-engine process.
REM Keep this file pure ASCII - no Chinese comments/echo allowed here.
chcp 65001 >nul
title AI Interview Backend - Offline
cd /d %~dp0

where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] conda not found. Please install Anaconda or Miniconda first.
    pause
    exit /b 1
)

python start.py --offline
if errorlevel 1 (
    echo [ERROR] failed to run start.py. Is Python in PATH?
    echo         If you just installed conda, restart the terminal and try again.
)
pause
