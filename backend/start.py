# -*- coding: utf-8 -*-
"""Backend launcher: locate conda -> create env -> install deps -> start servers.

All startup logic lives here so the .bat wrapper stays minimal:
Python is immune to the encoding / line-ending pitfalls of cmd batch files.

Started processes:
1. Main FastAPI backend on port 8001 (foreground)
2. P3 AI evaluator (Flask) on port 8002 (child process, auto-stopped on exit)
"""
import json
import os
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
DIALOGUE_PORT = "8005"  # AI 对话层引擎（P5 交付的 A11，backend/dialogue_layer/）
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

# AI 对话层（可选引擎）：整场委托出题 / 追问 / 五维评分。与 RAG 同档 ——
# 依赖外部 API key 与约 2.14GB 的本地 reranker 模型，属「可选增强」，
# 端口被占用只跳过、依赖缺失只提示，主流程不受影响。
DIALOGUE_DIR = BASE_DIR / "dialogue_layer"
DIALOGUE_ENTRY = DIALOGUE_DIR / "app" / "main.py"
DIALOGUE_IMPORT_CHECK = (
    "import importlib.util as u, sys; sys.exit(0 if all("
    "u.find_spec(m) for m in ('openai','sentence_transformers','transformers')) else 1)"
)
# 模型缓存目录（bge-reranker-v2-m3 首次运行需联网下载，见 README-集成说明.md）
DIALOGUE_HF_HOME = BASE_DIR / ".hf_cache"
# 平铺的本地模型目录（魔搭下载的布局；CrossEncoder 可直接加载目录路径）
DIALOGUE_MODEL_DIR = DIALOGUE_HF_HOME / "bge-reranker-v2-m3"
# 语音转写模型（faster-whisper 的 CTranslate2 格式，同样走本地目录）
DIALOGUE_ASR_MODEL = DIALOGUE_HF_HOME / "faster-whisper-small"


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


def wait_until_ready(
    url: str,
    seconds: int,
    proc: subprocess.Popen | None = None,
    predicate=None,
) -> bool:
    """轮询健康检查直到服务就绪（仅用标准库，避免依赖未安装时 import 失败）

    传入 proc 时监控子进程存活：进程启动即崩溃则立即返回 False，
    不白等满 seconds（真实报错已在控制台可见）。
    以单调时钟截止时间为准（而非按次计数），实际等待严格受限于 seconds。

    predicate：可选，接收解析后的 JSON body、返回 bool。用于那些
    「HTTP 200 但依赖还没就绪」的服务——AI 对话层的 /health 恒返回 200，
    就绪与否写在 body 的字段里，只看状态码会把「没加载完」当成「就绪」。
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=max(0.5, deadline - time.monotonic())) as resp:
                if resp.status == 200:
                    if predicate is None:
                        return True
                    try:
                        body = json.loads(resp.read().decode("utf-8"))
                    except Exception:
                        body = None
                    if isinstance(body, dict) and predicate(body):
                        return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def read_env_value(name: str) -> str:
    """从 backend/.env 读一个配置项（没有则返回空串）

    刻意不 import app.config：启动器要能在依赖没装好、应用起不来时照样跑，
    只做最简单的 KEY=VALUE 解析就够，不值得为此引入 dotenv。
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def dialogue_model_cached() -> bool:
    """reranker 权重是否已就位（两种布局都认，只按文件名判断、不校验完整性）

    缺它时对话层**照样起得来**，只是客观分恒走默认值——那种「能跑但结果是错的」
    最容易被当成本系统的 bug，所以这里提前提示一句。
    """
    flat = DIALOGUE_MODEL_DIR
    if any(flat.glob("*.safetensors")):
        return True
    for weights in (DIALOGUE_HF_HOME / "hub").glob(
        "models--BAAI--bge-reranker-v2-m3/snapshots/*/*.safetensors"
    ):
        if weights.stat().st_size > 0:
            return True
    return False


def build_dialogue_env() -> dict:
    """AI 对话层子进程的环境变量

    这些值原本散在 A11 的 run.ps1 里（PowerShell 脚本，默认路径指向交付方本机），
    这里用本项目的位置重新注入。API key 只从 .env 读、只经环境变量传给子进程，
    不写任何新文件、不打印。
    """
    env = dict(os.environ)
    env.update({
        "FRAMEWORK_PORT": DIALOGUE_PORT,
        # 题库复用本项目的一份（内容已逐字段核对一致），避免两份数据将来漂移
        "A11_MAIN_DB": str(BASE_DIR / "rag" / "数据"),
        "A11_KG_PATH": str(DIALOGUE_DIR / "数据" / "kg" / "kg_question_graph.pkl"),
        "A11_RAG_RETRIEVER_PY": str(DIALOGUE_DIR / "数据" / "rag" / "memory_retriever.py"),
        "RAG_MEM_DIR": str(DIALOGUE_DIR / "数据" / "rag"),  # 裸名，不能加 A11_ 前缀
        "A11_KG": "1",
        "A11_RAG": "0",
        "SCORER_DEVICE": os.environ.get("SCORER_DEVICE", "cpu"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    env["HF_HOME"] = os.environ.get("HF_HOME") or str(DIALOGUE_HF_HOME)
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    # 平铺的本地模型目录优先：魔搭下载不写 HF 缓存布局，用路径直接喂给 CrossEncoder
    if any(DIALOGUE_MODEL_DIR.glob("*.safetensors")):
        env["RERANKER_MODEL"] = str(DIALOGUE_MODEL_DIR)
    # 语音转写：同样用本地目录。本机连不上 huggingface.co，用仓库名会卡在下载上，
    # 所以「本地有模型」才开 ASR；没有就关掉——关了只是 /asr 返 503，面试不受影响。
    if DIALOGUE_ASR_MODEL.is_dir() and any(DIALOGUE_ASR_MODEL.glob("*.bin")):
        env["A11_ASR_MODEL"] = str(DIALOGUE_ASR_MODEL)
    else:
        env["A11_ASR"] = "0"
    # 情感模型（superb/wav2vec2-base-superb-er）在魔搭上找不到，暂关。
    # 转写与语速 / 停顿 / 音量三组表达指标不受影响，只是没有情感那几项。
    env["A11_ASR_EMOTION"] = "0"
    # ASR 的内存门槛：引擎默认 1200MB（保守，宁拒不 OOM）。本机整机 15.2GB，
    # 演示时 reranker 常驻 2.3GB、还有主后端与浏览器，1200MB 往往凑不出来。
    # whisper-small（int8）实测加载约 500MB，800 留了余量；外部显式设这个
    # 环境变量可以覆盖本值（要更保守就调回去）。
    env.setdefault("A11_ASR_MIN_FREE_MB", "800")
    # 学习资源样例（4a 的素材源）：指到项目内那一份
    resources = DIALOGUE_DIR / "数据" / "学习资源样例.json"
    if resources.exists():
        env["A11_RESOURCES_JSON"] = str(resources)
    # raw 明细保持脱敏（A11_RAW_DETAIL=0 是引擎的默认档）：得分点原文不出门。
    # 要全量明细（比如给 3 号出评估报告）才在外部设 1，本项目不设。
    # DeepSeek 三项复用本项目 .env 的 LLM_* 配置（LLM 直连与对话层引擎本就用同一套）
    for dialogue_key, project_key in (
        ("DEEPSEEK_API_KEY", "LLM_API_KEY"),
        ("DEEPSEEK_BASE_URL", "LLM_BASE_URL"),
        ("DEEPSEEK_MODEL", "LLM_MODEL"),
    ):
        if not env.get(dialogue_key):
            value = read_env_value(project_key)
            if value:
                env[dialogue_key] = value
    return env


def print_guide(
    server_ready: bool,
    frontend_ready: bool,
    rag_started: bool = False,
    dialogue_started: bool = False,
) -> None:
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
    print("  🤖  [AI 对话层引擎] 整场委托出题 / 追问 / 五维评分（可选引擎模式）")
    if dialogue_started:
        print(f"      健康检查:  http://localhost:{DIALOGUE_PORT}/health")
        print(f"      接口文档:  http://localhost:{DIALOGUE_PORT}/docs")
        print("      注：评分模型在后台预热（约需数十秒），/health 的 scorer_ready 变 true 即就绪。")
        print("      启用方式:  在 backend/.env 里设 DIALOGUE_ENGINE=a11（不设则走原链路）")
    else:
        print("      （未启用：目录缺失或依赖未就绪，主流程不受影响）")
    print("=" * 64)
    print("  停止全部服务：在本窗口按 Ctrl+C（前端 / P3 / RAG / 对话层 / 主后端一并退出）")
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
    dialogue_proc = None
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

        # AI 对话层引擎（可选）：与 RAG 同档——依赖外部 key 与 2.14GB 模型，
        # 任何一步失败只打印、绝不 fail()。拉起后**不等它就绪**：评分模型在
        # 后台线程里预热（数十秒），干等会把「一键启动」变成「一键启动加等待」；
        # 就绪与否由 /health 的 scorer_ready 表达，引擎模式下面试会据此明确报错。
        dialogue_started = False
        if not DIALOGUE_ENTRY.exists():
            print("未找到 AI 对话层（backend/dialogue_layer/），跳过")
        elif port_in_use(DIALOGUE_PORT):
            print(f"AI 对话层端口 {DIALOGUE_PORT} 已被占用，跳过拉起（沿用已在跑的服务）")
            dialogue_started = True
        else:
            dialogue_deps_ok = sh(f'"{python}" -c "{DIALOGUE_IMPORT_CHECK}"').returncode == 0
            if not dialogue_deps_ok:
                # 只补装 openai 这一个纯 Python 包：sentence-transformers / transformers
                # 复用共享环境里已有的版本。照 A11 的版本锁降级会打断 8003 的 RAG 服务。
                print("AI 对话层需补装 openai（约 1MB）...")
                sh(f'"{python}" -m pip install openai -i {PIP_INDEX}')
                dialogue_deps_ok = sh(f'"{python}" -c "{DIALOGUE_IMPORT_CHECK}"').returncode == 0
            if not dialogue_deps_ok:
                print("[警告] AI 对话层依赖未就绪，跳过（主流程不受影响）")
            else:
                if not dialogue_model_cached():
                    print("[提示] 未发现 reranker 模型缓存，对话层要等模型就位才可用；")
                    print("       下载命令见 backend/dialogue_layer/README-集成说明.md")
                print(f"拉起 AI 对话层引擎 → http://localhost:{DIALOGUE_PORT}"
                      "（评分模型后台预热，稍后看 /health 的 scorer_ready）")
                dialogue_proc = subprocess.Popen(
                    [str(python), "app/main.py"],
                    cwd=str(DIALOGUE_DIR),
                    env=build_dialogue_env(),
                )
                dialogue_started = True

        print_guide(
            server_ready,
            frontend_ready,
            rag_started=rag_proc is not None,
            dialogue_started=dialogue_started,
        )
        exit_code = server.wait()
    finally:
        # 主后端退出后关闭 P3 评估服务 / RAG / 对话层 / 前端，
        # 避免残留孤儿进程占用 8002/8003/8005/5273
        for proc in (evaluator, rag_proc, dialogue_proc, frontend_proc, server):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
