# -*- coding: utf-8 -*-
"""Backend launcher: locate conda -> create env -> install deps -> start servers.

All startup logic lives here so the .bat wrapper stays minimal:
Python is immune to the encoding / line-ending pitfalls of cmd batch files.

Started processes:
1. Main FastAPI backend on port 8001 (foreground)
2. P3 AI evaluator (Flask) on port 8002 (child process, auto-stopped on exit)
"""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_NAME = "ai_interview"
PORT = "8001"
EVALUATOR_PORT = "8002"
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
# 主后端 + P3 评估服务所需的全部第三方库（缺任一则触发 pip install）
IMPORT_CHECK = "import fastapi, uvicorn, sqlalchemy, flask, flask_cors, requests"


def sh(cmd: str) -> subprocess.CompletedProcess:
    """Run a command in BASE_DIR, print it for transparency."""
    print(f"  > {cmd}")
    return subprocess.run(cmd, shell=True, cwd=str(BASE_DIR))


def fail(message: str) -> None:
    print(f"[ERROR] {message}")
    input("Press Enter to exit...")
    sys.exit(1)


def locate_conda_base() -> Path | None:
    """Get conda base dir, keeping only drive-letter lines (conda may print ToS text)."""
    try:
        out = subprocess.run(
            ["conda", "info", "--base"], capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if len(line) >= 2 and line[1] == ":":
            return Path(line)
    return None


def locate_env_python() -> Path | None:
    """Find ai_interview env's python.exe via `conda env list`.

    Must NOT guess from conda base: envs may live in a user dir
    (e.g. C:\\Users\\xxx\\.conda\\envs) when the base dir is not writable.
    """
    try:
        out = subprocess.run(
            ["conda", "env", "list"], capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == ENV_NAME and len(parts) >= 2:
            candidate = Path(" ".join(parts[1:])) / "python.exe"
            if candidate.exists():
                return candidate
    return None


def main() -> None:
    print("=" * 60)
    print("AI 模拟面试系统 - 一键启动器")
    print("=" * 60)
    print("启动完成后，通过以下地址访问：")
    print(f"  系统界面（前端页面）：http://localhost:{PORT}")
    print(f"  接口文档（Swagger）：  http://localhost:{PORT}/docs")
    print(f"  P3 评估服务健康检查： http://localhost:{EVALUATOR_PORT}/health")
    print(f"  局域网演示：           http://<本机IP>:{PORT}（同一 WiFi，详见 docs/DEPLOY.md）")
    print("=" * 60)

    # 1. locate conda base dir
    base = locate_conda_base()
    if base is None:
        fail("conda not found. Please install Anaconda or Miniconda first.")
    print(f"[1/5] conda base: {base}")

    # 2. locate or create the env (real location may differ from base/envs)
    python = locate_env_python()
    if python is None:
        print(f"[2/5] creating conda env {ENV_NAME} (Python 3.12)...")
        sh(f"conda create -n {ENV_NAME} python=3.12 -y")
        python = locate_env_python()
        if python is None:
            print("  Conda reported the following environments:")
            print(sh("conda env list").stdout or "  (none)")
            fail("cannot locate conda env ai_interview after creation.")
    print(f"[2/5] env python: {python}")

    # 3. install deps if missing
    print("[3/5] checking dependencies...")
    if sh(f'"{python}" -c "{IMPORT_CHECK}"').returncode != 0:
        print("[3/5] installing dependencies (1-2 minutes, please wait)...")
        if sh(f'"{python}" -m pip install -r requirements.txt -i {PIP_INDEX}').returncode != 0:
            fail("dependency install failed. Check your network and retry.")

    # 4. init .env
    if not (BASE_DIR / ".env").exists():
        (BASE_DIR / ".env").write_text(
            (BASE_DIR / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
        print("[4/5] created .env from .env.example")

    # 5. port check (main backend 8001 + P3 evaluator 8002)
    print(f"[5/5] checking ports {PORT} / {EVALUATOR_PORT}...")
    for port in (PORT, EVALUATOR_PORT):
        if sh(f'netstat -ano | findstr ":{port}" | findstr "LISTENING"').returncode == 0:
            fail(f"port {port} is already in use. Close the other program first.")

    print("-" * 60)
    print(f"Starting AI evaluator (P3) on port {EVALUATOR_PORT}...")
    evaluator = subprocess.Popen([str(python), "evaluator/app.py"], cwd=str(BASE_DIR))
    print(f"Starting server... visit http://localhost:{PORT}/docs")
    print("-" * 60)
    try:
        exit_code = subprocess.call(
            [str(python), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", PORT],
            cwd=str(BASE_DIR),
        )
    finally:
        # 主后端退出后关闭 P3 评估服务，避免残留孤儿进程占用 8002
        evaluator.terminate()
        try:
            evaluator.wait(timeout=5)
        except subprocess.TimeoutExpired:
            evaluator.kill()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
