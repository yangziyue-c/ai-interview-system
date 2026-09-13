# -*- coding: utf-8 -*-
"""Backend launcher: locate conda -> create env -> install deps -> start servers.

All startup logic lives here so the .bat wrapper stays minimal:
Python is immune to the encoding / line-ending pitfalls of cmd batch files.

Started processes:
1. Main FastAPI backend on port 8001 (foreground)
2. P3 AI evaluator (Flask) on port 8002 (child process, auto-stopped on exit)
"""
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# start.bat 已执行 chcp 65001，控制台为 UTF-8；此处统一 stdout 编码与行缓冲，
# 保证中文/emoji 正常显示且重定向日志时 print 及时落盘
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE_DIR = Path(__file__).resolve().parent
ENV_NAME = "ai_interview"
PORT = "8001"
EVALUATOR_PORT = "8002"
FRONTEND_PORT = "5273"  # 演示前端（frontend_test/）静态服务端口（避开 P4 Vite 联调用的 5173）
RAG_PORT = "8003"       # RAG 语义检索服务（V5 知识库，backend/rag/）
HEALTH_WAIT_SECONDS = 30  # 主后端就绪的最长等待时间
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
# 主后端 + P3 评估服务所需的全部第三方库（缺任一则触发 pip install）
IMPORT_CHECK = "import fastapi, uvicorn, sqlalchemy, flask, flask_cors, requests"

# RAG 服务（可选增强数据源）：依赖与主流程刻意分离，不写进 requirements.txt——
# torch 等约 2.5GB，写进去会让每个新环境都被强加这笔下载。
RAG_DIR = BASE_DIR / "rag"
RAG_ENTRY = RAG_DIR / "代码" / "05_rag_api_server.py"
RAG_REQ = RAG_DIR / "requirements-rag.txt"
# find_spec 只查包元数据、不真正 import：torch 加载要 10s+，会平白拖慢每次启动
RAG_IMPORT_CHECK = (
    "import importlib.util as u, sys; sys.exit(0 if all("
    "u.find_spec(m) for m in ('torch','chromadb','sentence_transformers')) else 1)"
)


def sh(cmd: str) -> subprocess.CompletedProcess:
    """Run a command in BASE_DIR, print it for transparency."""
    print(f"  > {cmd}")
    return subprocess.run(cmd, shell=True, cwd=str(BASE_DIR))


def fail(message: str) -> None:
    print(f"[ERROR] {message}")
    input("Press Enter to exit...")
    sys.exit(1)


def port_in_use(port: str) -> bool:
    """检查端口是否已被占用（TCP 连接探测，比 netstat 快且跨平台）

    同时探测回环与局域网地址：仅测 127.0.0.1 会漏报只绑定在非回环 IP 上的监听
    """
    for host in ("127.0.0.1", get_lan_ip()):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex((host, int(port))) == 0:
                    return True
        except OSError:
            pass
    return False


def get_lan_ip() -> str:
    """获取本机局域网 IP（UDP 探测，不真正发包）；失败回退 127.0.0.1"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def wait_until_ready(url: str, seconds: int, proc: subprocess.Popen | None = None) -> bool:
    """轮询健康检查直到服务就绪（仅用标准库，避免依赖未安装时 import 失败）

    传入 proc 时监控子进程存活：进程启动即崩溃则立即返回 False，
    不白等满 seconds（真实报错已在控制台可见）。
    以单调时钟截止时间为准（而非按次计数），实际等待严格受限于 seconds。
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=max(0.5, deadline - time.monotonic())) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def print_guide(server_ready: bool, frontend_ready: bool, rag_started: bool = False) -> None:
    """启动完成后的访问指引：明确每个网址可以做什么"""
    lan_ip = get_lan_ip()
    print()
    print("=" * 64)
    print("  AI 模拟面试系统 —— 启动完成，访问指引")
    if not server_ready:
        print("  （主后端仍在启动中，可稍等几秒再访问）")
    print("=" * 64)
    print("  🖥️  [前端界面] 注册登录 / 模拟面试 / 评估报告 / 个人中心")
    if frontend_ready:
        print(f"      本机访问:  http://localhost:{FRONTEND_PORT}")
        print(f"      局域网:    http://{lan_ip}:{FRONTEND_PORT}  （同一 WiFi 设备可访问）")
        print("      操作路径:  注册账号 → 岗位大厅选岗位 → 完成一场面试 → 查看 AI 评估报告")
    else:
        print(f"      （前端暂不可用：目录缺失或端口 {FRONTEND_PORT} 被非前端进程占用，请检查后重启）")
    print("  📚  [后端接口] Swagger 在线调试（API 文档）")
    print(f"      本机访问:  http://localhost:{PORT}/docs")
    print(f"      局域网:    http://{lan_ip}:{PORT}/docs")
    print("  🔍  [评估服务] P3 AI 评估健康检查")
    print(f"      本机访问:  http://localhost:{EVALUATOR_PORT}/health")
    print("  🧠  [RAG 语义检索] V5 知识库检索（题库未命中时的语义兜底）")
    if rag_started:
        print(f"      健康检查:  http://localhost:{RAG_PORT}/health")
        print(f"      检索接口:  POST http://localhost:{RAG_PORT}/rag/search")
        print("      注：首次启动需下载 4.5GB 模型，加载完成前该地址不可用；")
        print("          稍后刷新 /health 看到 collection_size 即就绪。主流程不等它。")
    else:
        print("      （未启用：依赖缺失或 backend/rag 不存在，主流程不受影响）")
    print("=" * 64)
    print("  停止全部服务：在本窗口按 Ctrl+C（前端 / P3 / RAG / 主后端一并退出）")
    print("=" * 64)
    print()


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
        # 当前激活的环境行在名称与路径之间多一列 '*'，先剔除再解析
        parts = [p for p in line.split() if p != "*"]
        if parts and parts[0] == ENV_NAME and len(parts) >= 2:
            candidate = Path(" ".join(parts[1:])) / "python.exe"
            if candidate.exists():
                return candidate
    return None


def main() -> None:
    print("=" * 60)
    print("  AI 模拟面试系统 - 一键启动器")
    print("  正在启动服务，完成后将打印访问指引（请保持本窗口打开）")
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
        if port_in_use(port):
            fail(f"port {port} is already in use. Close the other program first.")
    # RAG 端口单独判定：被占用只跳过 RAG，不 fail（增强数据源，主流程不依赖）
    rag_port_busy = port_in_use(RAG_PORT)

    print("-" * 60)

    # 6. 演示前端（frontend_test/，P4 正式前端交付前的一键入口）
    #    端口已被占用时视为用户手动启动过，直接沿用；退出时随主后端一并关闭
    frontend_dir = BASE_DIR.parent / "frontend_test"
    frontend_proc = None
    frontend_ready = False
    print(f"启动 P3 评估服务（端口 {EVALUATOR_PORT}）...")
    print(f"启动主后端服务（端口 {PORT}）...")
    # 所有子进程 spawn 与等待整体包进 try：任何退出路径（含等待窗口内 Ctrl+C）
    # 都走 finally 清理，不残留占用 8001/8002/5273 的孤儿进程
    evaluator = None
    rag_proc = None
    server = None
    try:
        if (frontend_dir / "index.html").exists():
            frontend_ready = True
            frontend_url = f"http://localhost:{FRONTEND_PORT}/"
            if port_in_use(FRONTEND_PORT):
                print(f"前端端口 {FRONTEND_PORT} 已被占用（可能是您手动启动的前端服务），跳过拉起")
                # 探测该端口是否真的在服务前端，避免指引谎报可用
                if not wait_until_ready(frontend_url, 3):
                    print(f"[警告] 端口 {FRONTEND_PORT} 未响应 HTTP，指引中的前端地址可能不可用")
                    frontend_ready = False
            else:
                print(f"拉起演示前端 frontend_test/ → http://localhost:{FRONTEND_PORT}")
                frontend_proc = subprocess.Popen(
                    [str(python), "-m", "http.server", FRONTEND_PORT, "--directory", str(frontend_dir)],
                    cwd=str(BASE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if not wait_until_ready(frontend_url, 5, frontend_proc):
                    print(f"[警告] 前端服务未就绪，指引中的前端地址可能不可用")
                    frontend_ready = False
        else:
            print("未找到 frontend_test/，跳过前端拉起（仅 API 可用）")

        # 评估服务用 evaluator_new（V5 增强版：注入单题校准锚点做按题评分；
        # 未传 materials 时行为与 3 号原版 evaluator/ 逐字一致）
        evaluator = subprocess.Popen([str(python), "evaluator_new/app.py"], cwd=str(BASE_DIR))
        server = subprocess.Popen(
            [str(python), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", PORT],
            cwd=str(BASE_DIR),
        )
        print(f"等待主后端就绪（最长 {HEALTH_WAIT_SECONDS} 秒）...")
        server_ready = wait_until_ready(f"http://localhost:{PORT}/api/v1/health", HEALTH_WAIT_SECONDS, server)

        # RAG 语义检索服务（可选增强数据源）：刻意放在主服务就绪**之后**拉起——
        # 依赖缺失时首次需同步安装约 2.5GB，若排在启动路径前会让主后端干等数分钟，
        # 与「RAG 可选、主流程不依赖它」的设计前提相矛盾。
        # 任何一步失败只打印，绝不 fail()。
        if not RAG_ENTRY.exists():
            print("未找到 RAG 服务代码（backend/rag/），跳过")
        elif rag_port_busy:
            print(f"RAG 端口 {RAG_PORT} 已被占用，跳过拉起")
        else:
            rag_deps_ok = sh(f'"{python}" -c "{RAG_IMPORT_CHECK}"').returncode == 0
            if not rag_deps_ok:
                print("RAG 语义检索需额外依赖（约 2.5GB），正在安装，首次约需数分钟...")
                # 分两步装：torch 必须先走 CPU 索引，否则会命中默认 CUDA 版多下约 2GB
                sh(f'"{python}" -m pip install torch '
                   f'--index-url https://download.pytorch.org/whl/cpu')
                sh(f'"{python}" -m pip install chromadb sentence-transformers -i {PIP_INDEX}')
                rag_deps_ok = sh(f'"{python}" -c "{RAG_IMPORT_CHECK}"').returncode == 0
            if not rag_deps_ok:
                print("[警告] RAG 依赖未就绪，跳过 RAG 服务（主流程不受影响）")
            else:
                print(f"拉起 RAG 语义检索服务 → http://localhost:{RAG_PORT}"
                      "（首次需下载约 4.5GB 模型，稍后访问 /health 确认）")
                rag_proc = subprocess.Popen(
                    [str(python), "05_rag_api_server.py"], cwd=str(RAG_ENTRY.parent))

        print_guide(server_ready, frontend_ready, rag_started=rag_proc is not None)
        exit_code = server.wait()
    finally:
        # 主后端退出后关闭 P3 评估服务 / RAG / 前端，避免残留孤儿进程占用 8002/8003/5273
        for proc in (evaluator, rag_proc, frontend_proc, server):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
