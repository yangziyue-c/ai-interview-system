#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
check_env.py · 换机器部署自检（**只读**）
============================================================
给 1 号 换到另一台电脑时用。**在起服务之前跑**，把「代码里写死的本机绝对路径」
和实际环境对一遍 —— 因为本项目大部分外部依赖**缺了不会启动失败**，
而是静默降级（评分全走默认 50、不避重、RAG 空转…）。那种错最难发现。

用法（在包根，与 smoke_test.py 同级）：
    & $env:A11_PYTHON check_env.py             # 常规检查
    & $env:A11_PYTHON check_env.py --deep      # 额外真加载一次 RAG 索引（多几秒、约 300MB 内存）

退出码：0 = 没有致命项（可以有 ⚠️）；1 = 有 ❌，别急着起服务。

三条设计约束（为什么这么写）：
  1. **只读** —— 只做「存在性 / 字节数 / json 解析 / 版本比对」。不写文件、不建目录、
     不加载模型、**绝不打印 API key 的值**（只报已设置/未设置）。
  2. **不 import 重的模块** —— 只 import `app.config`（它只 import os，见 config.py:10）。
     不 import `app.main`（会加载题库）；也不 import `app.core.rag`（它连带
     `app.logging_conf` 去 os.makedirs(logs)，那就不是只读了）。
     所以下面那段内存探测是**照抄** `app/core/rag.py:49-76`，不是 import 它。
  3. **标记用纯 ASCII** —— 这台脚本要跑在一台**我们没见过的机器**上，控制台代码页未知，
     ✅/❌ 这种字符在 GBK 控制台会变成问号。中文本来就要正常显示才能用，但标记必须稳。

严重程度的口径（这也是给你看结论用的）：
    [FAIL] 服务起不来，或**能起来但结果是错的**（题库缺 → /next 500；模型缓存缺 →
           评分恒为默认 50）。必须在起服务前修掉。
    [WARN] 能跑，只是**降级**（KG 缺失 → 不避重、无深挖方向）。知道就行，可以后面再补。
    [INFO] 只是情况说明，不用动手。
"""
import argparse
import ctypes
import glob
import importlib.metadata as md
import json
import os
import platform
import socket
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

_ap = argparse.ArgumentParser(
    description="A11 对话层换机器部署自检（只读，不改任何东西）")
_ap.add_argument("--deep", action="store_true",
                 help="额外真加载一次 RAG 索引并断言条数（多几秒、约 300MB 内存）")
DEEP = _ap.parse_args().deep

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

OK, INFO, WARN, FAIL = "OK", "INFO", "WARN", "FAIL"
MARK = {OK: "[OK]  ", INFO: "[INFO]", WARN: "[WARN]", FAIL: "[FAIL]"}
RESULTS = []


def add(level, title, detail="", fix=""):
    RESULTS.append((level, title, detail, fix))
    if detail:
        print(f"{MARK[level]} {title}\n         {detail}")
    else:
        print(f"{MARK[level]} {title}")
    if fix:
        print(f"         → 怎么办: {fix}")
    sys.stdout.flush()


def head(text):
    print(f"\n{'=' * 68}\n{text}\n{'=' * 68}")


# ============================================================
# 内存探测 —— 照抄 app/core/rag.py:49-76（那边是同语义的唯一实现）
# ============================================================
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def mem_mb():
    """(总内存 MB, 可用内存 MB)。取不到返回 (None, None) —— 与 rag.py 一致：
    「测不出来」不等于「内存不足」。"""
    try:
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None, None
        return int(st.ullTotalPhys // 1048576), int(st.ullAvailPhys // 1048576)
    except Exception:
        return None, None


# ============================================================
# RAG 检索器的数据目录链 —— **逐字复刻** memory_retriever.py:74-81
# ============================================================
# 为什么要在自检里复刻一遍：那段逻辑决定 RAG 读哪个目录，而它的行为有个坑 ——
# `os.environ.get("RAG_MEM_DIR") or _pick(...)`，只要环境变量**非空就直接用**，
# 后面 6 条候选**全部不再尝试**。设错（少一层目录）就抛 FileNotFoundError，
# 被 rag.py 的 except Exception 吞掉 → 静默永久降级。这里要能报出「本来能命中哪条」。
RAG_PKL, RAG_NPZ = "all_records.pkl", "memory_index.npz"
# 字节数从磁盘实测（2026-09-23）。它是「有没有拷坏 / 拷了一半」最便宜的判据；
# 两个文件是一对，必须来自同一次构建（EXPECTED_N=74011 是硬断言）。
RAG_SIZE = {RAG_PKL: 71412669, RAG_NPZ: 158639920}
RAG_EXPECTED_N = 74011
# _pick() 的候选顺序，与 memory_retriever.py:75-80 一一对应
RAG_FALLBACK_HINT = [
    r"<_PKG_ROOT>\向量库",
    r"<_PKG_ROOT>\memory_index",
    "<脚本同目录>",
    r"<_PKG_ROOT>\数据",
    r"E:\GitHubRepos\rag-db-v5",
    r"E:\GitHubRepos\rag-db-v5\handoff\交付包-1号后端\数据",
]


def rag_candidates(retriever_py: str) -> list:
    """把 memory_retriever.py 的 6 条候选算出来（_PKG_ROOT = 上两级目录）。"""
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(retriever_py)))
    return [
        os.path.join(pkg_root, "向量库"),
        os.path.join(pkg_root, "memory_index"),
        os.path.dirname(os.path.abspath(retriever_py)),
        os.path.join(pkg_root, "数据"),
        r"E:\GitHubRepos\rag-db-v5",
        r"E:\GitHubRepos\rag-db-v5\handoff\交付包-1号后端\数据",
    ]


def public_version(v: str) -> str:
    """2.14.0+cu130 → 2.14.0。

    本地版本号后缀（`+cu130` 这类 CUDA 构建标记）**不算不一致** —— 否则每台装了
    CUDA 版 torch 的机器都会误报「版本不符」，那这条检查就废了。实测本机
    torch 就是 2.14.0+cu130，而 pin 写的是 2.14.0。
    """
    return v.split("+", 1)[0].strip()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n:,} B"
        n /= 1024.0
    return str(n)


# ============================================================
print("=" * 68)
print("A11 对话层 · 换机器部署自检（只读，不改任何东西）")
print(f"被检查的包: {_ROOT}")
print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 68)
print("标记口径: [FAIL] 起不来或结果是错的 | [WARN] 能跑但降级 | [INFO] 说明")

# ---- 前置：能不能读到真值源 ----
try:
    from app import config                                     # noqa: E402
except Exception as e:                                          # noqa: BLE001
    print(f"\n[FAIL] 读不到 app/config.py：{type(e).__name__}: {e}")
    print("       这个包不完整，或者解压时少了 app\\ 目录 —— 先解决这个再看别的")
    sys.exit(1)

head("一、解释器与依赖")
print(f"Python {platform.python_version()}  ({sys.executable})")
print(f"系统   {platform.system()} {platform.release()}")
if sys.version_info < (3, 10):
    add(WARN, f"Python 版本偏低（{platform.python_version()}）",
        "本项目在 3.14.7 上开发、实测通过", "换用 3.10+ 的解释器")
else:
    add(OK, f"Python 版本可用（{platform.python_version()}）")

# requirements.txt 就在包根，逐条比对 pin
req_path = os.path.join(_ROOT, "requirements.txt")
# 这些包缺了/版本不符**只报 WARN 不报 FAIL** —— A11 运行时根本不 import 它们。
# chromadb 只被向量库重建工具用；它的 pin 是「同机共用环境别连累 8003」的产物。
SOFT_DEPS = {"chromadb"}
# 语音转写那四条**单独成组**，留到第十节报（严重程度取决于 A11_ASR 开没开）。
# 若在这里逐条报，一个原因会刷出四行 FAIL（少装了 faster-whisper，它的三条传递依赖
# 必然一起缺）—— 那种刷屏只会让人以为问题比实际大。
# ⚠️ python-multipart **不在**这一组：它不是 ASR 的依赖，而是 `/asr` 这个路由本身
#    的依赖 —— 缺了 FastAPI 在注册路由时就抛 RuntimeError，服务整个起不来，
#    与 A11_ASR 开不开无关。所以它留在下面按常规逐条判 FAIL。
ASR_DEPS = ("faster-whisper", "ctranslate2", "av", "onnxruntime")
pins: list = []                       # 第十节也要用它（requirements.txt 缺失时不能是未定义）
if not os.path.exists(req_path):
    add(WARN, "找不到 requirements.txt", f"期望在 {req_path}", "从源码目录补一份")
else:
    with open(req_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#")[0].strip()
            if "==" in line:
                name, ver = line.split("==", 1)
                pins.append((name.strip(), ver.strip()))
    miss, mismatch = [], []
    for name, want in pins:
        if name in ASR_DEPS:
            continue                      # 第十节单独成组报
        try:
            got = md.version(name)
        except md.PackageNotFoundError:
            miss.append((name, want))
            continue
        if public_version(got) != public_version(want):
            mismatch.append((name, want, got))
    for name, want in miss:
        lvl = WARN if name in SOFT_DEPS else FAIL
        why = ("本框架**一处都不 import chromadb**（全项目搜过，只有 logging_conf.py:52 "
               "把它列在静音名单里，那不是 import）。只有重建向量库才需要它"
               if name in SOFT_DEPS else "缺这个包服务起不来或评分不对")
        add(lvl, f"依赖缺失：{name}=={want}", why,
            f"pip install \"{name}=={want}\""
            + ("；新机器上不重建向量库可以不装" if name in SOFT_DEPS else ""))
    for name, want, got in mismatch:
        if name in SOFT_DEPS:
            add(WARN, f"chromadb 版本不一致：装的是 {got}，pin 是 {want}",
                "A11 运行时**不 import chromadb**，这条 pin 的用意是「同机共用环境、"
                "别连累 8003 的 RAG 服务与向量库重建工具」（requirements.txt:12-13）。"
                "新机器上不重建库，装不装都不影响 A11 本身",
                f"装了就用 pip install \"chromadb=={want}\" 对齐；没装就忽略这条")
        else:
            # 原因按包分开写：torch 那三个是真的「换版本会崩」，其余只是「不是实测过的那组」
            why = ("torch / sentence-transformers / transformers 这三个与 hf_cache 里"
                   "的模型缓存格式绑死，换版本可能直接加载失败 → 评分全走默认 50"
                   if name in ("torch", "sentence-transformers", "transformers") else
                   "不是本机实测通过的那一组版本。requirements.txt 里的 pin 是"
                   "「2026-09-22 实测通过」的整组，换机器照装最省事")
            add(FAIL, f"依赖版本不一致：{name} 装的是 {got}，pin 是 {want}", why,
                f"pip install \"{name}=={want}\"")
    if not miss and not mismatch:
        add(OK, f"依赖版本与 requirements.txt 的 {len(pins) - len(ASR_DEPS)} 条 pin 全部一致（本节范围）",
            f"（语音那 {len(ASR_DEPS)} 条在这里不判 —— 见第十节；"
            f"它们缺了不影响面试，只影响 /asr）")

head("二、题库（最要紧的一项）")
print(f"config.MAIN_DB_DIR = {config.MAIN_DB_DIR}")
print(f"环境变量 A11_MAIN_DB = {os.environ.get('A11_MAIN_DB') or '(未设置，用上面的默认值)'}")
if not os.path.isdir(config.MAIN_DB_DIR):
    add(FAIL, "题库目录不存在",
        "**这是换机器最容易踩的一条**：题库缺失时服务照常启动、/health 也正常，"
        "只有第一次调 /next 才 500（question_bank.py:79 抛 BankError，"
        "interview.py 只捕 SessionError，所以变成了 500 internal_error）",
        f'$env:A11_MAIN_DB = "<新机器上的题库目录>"  '
        f"（目录里要有 {len(config.JOB_FILE_MAP)} 个文件，见下）")
    for job, fn in config.JOB_FILE_MAP.items():
        print(f"         · {fn}  ({job})  → 缺失")
else:
    bad = 0
    for job, fn in config.JOB_FILE_MAP.items():
        p = os.path.join(config.MAIN_DB_DIR, fn)
        if not os.path.exists(p):
            bad += 1
            add(FAIL, f"题库文件缺失：{fn}", f"岗位「{job}」的题全靠它", f"拷到 {p}")
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:                                  # noqa: BLE001
            bad += 1
            add(FAIL, f"题库文件读不了：{fn}", f"{type(e).__name__}: {e}",
                "文件可能拷坏了（用字节数核一下），或不是 JSON")
            continue
        n = len(data) if isinstance(data, list) else len(data.get("questions", data))
        want = config.JOB_BANK_SIZE.get(job)
        note = ""
        if want and n != want:
            note = f"（config.JOB_BANK_SIZE 记的是 {want}，不一致只提示不判死）"
        print(f"         · {fn}  {human(os.path.getsize(p))}  {n} 题  {note}")
    if not bad:
        add(OK, f"题库齐全：{len(config.JOB_FILE_MAP)} / {len(config.JOB_FILE_MAP)} 个文件都在且能解析")

head("三、知识图谱")
print(f"config.A11_KG = {config.A11_KG}   （A11_KG={'1' if config.A11_KG else '0'}）")
print(f"config.KG_PATH = {config.KG_PATH}")
if not config.A11_KG:
    add(INFO, "KG 已被关闭（A11_KG=0）", "不检查图谱文件。开它就设 A11_KG=1")
elif not os.path.exists(config.KG_PATH):
    add(WARN, "知识图谱不存在 → 会静默降级",
        "kg.py 的契约是「失败返回 None」，所以不会崩：只是**不避重**"
        "（可能重复考同一个知识点）、**没有深挖方向**",
        f'拷 D:\\A11-Data\\kg-enhanced\\ 下的 kg_question_graph.pkl 到新机器，'
        f'再 $env:A11_KG_PATH = "<那个文件>"（约 14.1 MB）')
else:
    sz = os.path.getsize(config.KG_PATH)
    add(OK, f"知识图谱存在（{human(sz)}）",
        "注意只搬 kg-enhanced\\ 那一份 —— kg_review\\ 下有同名副本（陷阱）")

head("四、模型缓存（reranker + RAG 编码器）")
hf = config.HF_HOME
print(f"config.HF_HOME = {hf}")
print(f"HF_HUB_OFFLINE = {os.environ.get('HF_HUB_OFFLINE', '(未设置)')}   "
      f"TRANSFORMERS_OFFLINE = {os.environ.get('TRANSFORMERS_OFFLINE', '(未设置)')}"
      "   ← app/__init__.py 会用 setdefault 设成 1")
hub = os.path.join(hf, "hub")
need = {
    "bge-reranker-v2-m3": "models--BAAI--bge-reranker-v2-m3",   # 评分器（必须）
    "bge-m3": "models--BAAI--bge-m3",                           # RAG 编码器（开 RAG 就必须）
}
missing_models = []
for label, dirname in need.items():
    d = os.path.join(hub, dirname)
    snaps = os.path.join(d, "snapshots")
    if os.path.isdir(snaps) and any(os.scandir(snaps)):
        add(OK, f"模型缓存存在：{label}")
    else:
        missing_models.append(label)
        add(FAIL, f"模型缓存缺失：{label}", f"期望在 {d}",
            f'拷 {dirname} 整个目录（bge-reranker-v2-m3 约 2.14 GB / '
            f'bge-m3 约 4.25 GB），或设 $env:HF_HOME 指向已有的 hub 目录')
if missing_models:
    add(FAIL, "模型缓存不全 → 评分会静默变错",
        "reranker 加载失败不抛异常：客观覆盖率恒走默认 50，"
        "/health 里 reranker_ok=false。面试能走完，但分是不对的 —— "
        "**这种错最难发现，必须修**",
        "两条路：(1) 把缓存拷过来（只搬上面这两个模型目录，别整个 hf_cache 搬 —— "
        "里面有 1.4 GB 是 datasets 与 MiniLM，本项目一处都没引用）；"
        "(2) 让新机器自己下载：设 $env:HF_ENDPOINT='https://hf-mirror.com'，"
        "并且注意 run.ps1:26-27 会**无条件**强制离线，走 run.ps1 就必须改那两行；"
        "直接 python app\\main.py 起的话 $env:HF_HUB_OFFLINE='0' 是有效的")

head("五、RAG")
# ⚠️ 口径（2026-09-24 统一）：**代码默认**（config.py:402）是 "0"，
#    而交付包模板 `环境变量.模板.ps1:24` 写的是 **=1** —— dot-source 模板之后就是**开**。
#    这两个默认并存没问题，出问题的是文档把它们混成一句「默认关」，1 号 因此按
#    「不开」处理（见 REPORT_TO_P5 §二.8）。所以这里**报出值 + 来源**，不替谁下结论。
_runtime_rag = os.environ.get("A11_RAG")
print(f"config.A11_RAG = {config.A11_RAG}   （A11_RAG={'1' if config.A11_RAG else '0'}）"
      + ("　← 来自环境变量 A11_RAG" if _runtime_rag is not None
         else "　← 环境变量 A11_RAG **未设**，用的是代码默认 config.py:402（=0）；"
              "\n         交付包模板 `环境变量.模板.ps1:24` 写的是 =1，dot-source 之后就是开"))
print("         开了之后注入的是**题库派生索引**的同岗位同难度其他问法（RAG_LAYERS="
      f"{tuple(getattr(config, 'RAG_LAYERS', ()))}）—— **不是知识库文档正文**。"
      "\n         知识库接的是 4a 学习资源推荐（见第十一节），不在面试 prompt 这条链上。")
print(f"config.A11_RAG_RETRIEVER_PY = {config.RAG_RETRIEVER_PY}")
print(f"config.RAG_DTYPE = {config.RAG_DTYPE}   "
      f"RAG_MIN_FREE_MB = {config.RAG_MIN_FREE_MB}   "
      f"RAG_ENCODER = {config.RAG_ENCODER}")
print(f"config.RAG_TOP_N = {config.RAG_TOP_N}"
      f"   RAG_CAND = {getattr(config, 'RAG_CAND', '（旧版 config.py 里没有这个键）')}")
print("         ⚠️ RAG_CAND 是**一次取多少条候选再丢自身命中**。它太小，片段会被整组丢掉："
      "\n         同一道题在「原题 + 语义变体」两层里占 3~6 条记录，取 4 条时候"
      "9/10 次全是它自己\n         → 丢完剩 0 条（实测注入率 1/10；默认 20 → 10/10）。"
      "见 rag.py:246-250")

# 严重程度取决于「你到底想不想开 RAG」：想开却起不来 = FAIL；没打算开 = 只是提示
LVL = FAIL if config.A11_RAG else INFO
ram_suffix = ("→ 现在 A11_RAG=1（开着），所以这些必须齐" if config.A11_RAG
              else "→ 现在 A11_RAG=0。要开就设 $env:A11_RAG='1'（模板里本来就是 1），"
                   "届时这些都得齐")

if not os.path.exists(config.RAG_RETRIEVER_PY):
    add(LVL, "RAG 检索器 memory_retriever.py 不存在", ram_suffix,
        f'把它和两个索引文件放同一目录，再 $env:A11_RAG_RETRIEVER_PY = "<那个 py>"'
        f"（注意：只搬这一个 7.7 KB 的 py + 下面两个数据文件，"
        f"E:\\GitHubRepos\\rag-db-v5 整个目录约 2.85 GB，绝大部分是构建遗留）")
    rag_base, rag_src = None, "检索器不存在，数据目录没法解析"
else:
    env_dir = os.environ.get("RAG_MEM_DIR")
    if env_dir:
        rag_base = env_dir
        rag_src = ("来自环境变量 RAG_MEM_DIR（**优先级最高**：memory_retriever.py:74 是 "
                   "`os.environ.get(...) or _pick(...)`，非空就不再走 6 条候选）")
        print(f"\nRAG_MEM_DIR = {env_dir}")
        print("         ⚠️ 这个变量一旦设了就没有兜底 —— 设错会直接抛 FileNotFoundError，"
              "被 rag.py 吞掉变成静默降级")
    else:
        cands = rag_candidates(config.RAG_RETRIEVER_PY)
        rag_base = next((c for c in cands if os.path.exists(c)), None)
        if rag_base:
            idx = cands.index(rag_base)
            rag_src = f"未设 RAG_MEM_DIR，_pick() 命中第 {idx + 1} 条候选：{rag_base}"
        else:
            rag_src = ("未设 RAG_MEM_DIR，_pick() 的 6 条候选**全部不存在**：\n         "
                       + "\n         ".join(RAG_FALLBACK_HINT))
    print(f"RAG 数据目录: {rag_base}\n         （{rag_src}）")
    if rag_base is None:
        add(LVL, "RAG 数据目录一条候选都没命中", ram_suffix,
            '把 all_records.pkl + memory_index.npz 放到与 memory_retriever.py 同一目录'
            '（_pick 的第 3 条候选），然后设 $env:RAG_MEM_DIR = "<那个目录>"')
    else:
        for fn, want in RAG_SIZE.items():
            p = os.path.join(rag_base, fn)
            if not os.path.exists(p):
                add(LVL, f"RAG 数据文件缺失：{fn}", f"在 {rag_base} 里没找到",
                    f'拷过来。**{RAG_PKL} 与 {RAG_NPZ} 必须来自同一次构建** —— '
                    f'memory_retriever.py:45 有硬断言 EXPECTED_N={RAG_EXPECTED_N}，'
                    f'条数不等直接 ValueError，同样是静默降级')
            else:
                got = os.path.getsize(p)
                if got != want:
                    add(LVL, f"RAG 数据文件大小不对：{fn}",
                        f"实际 {got:,} B，期望 {want:,} B（差 {got - want:+,} B）",
                        "多半是拷了一半 / 拷坏了。重新完整拷一次（两个文件都要）")
                else:
                    add(OK, f"RAG 数据文件正常：{fn}（{human(got)}）")

if config.A11_RAG:
    tot, avail = mem_mb()
    if avail is None:
        add(INFO, "内存可用量测不到", "按 rag.py:63-76 的语义，测不出来时**跳过预检**"
                                     "而不是判失败，所以 RAG 会照常尝试加载")
    elif avail < config.RAG_MIN_FREE_MB:
        add(FAIL, f"可用内存 {avail} MB < RAG_MIN_FREE_MB={config.RAG_MIN_FREE_MB} MB",
            "rag.py:174-183 的预检会直接 raise MemoryError → RAG 进程内永久降级",
            "关掉别的占内存的程序，或改小 A11_RAG_MIN_FREE_MB（那只是门槛，"
            "真正的需求见下面的内存账），或设 RAG_DTYPE=fp16")
    else:
        add(OK, f"可用内存 {avail} MB ≥ RAG_MIN_FREE_MB={config.RAG_MIN_FREE_MB} MB",
            "过了门槛。但门槛只是起步线，够不够跑整场见第八节的内存账")

if DEEP and rag_base and config.RAG_RETRIEVER_PY and os.path.exists(config.RAG_RETRIEVER_PY):
    print("\n--deep：真加载一次索引（约 300MB 内存、几秒）")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "a11_check_retriever", config.RAG_RETRIEVER_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        n = mod.MemoryRetriever().count()
        if n == RAG_EXPECTED_N:
            add(OK, f"--deep 通过：索引 {n} 条，与 EXPECTED_N 一致")
        else:
            add(FAIL, f"--deep 失败：索引 {n} 条，期望 {RAG_EXPECTED_N} 条",
                "导出/编码不完整，或两个文件不是同一次构建的",
                "重新完整拷贝两个文件；真要重建见 E:\\GitHubRepos\\rag-db-v5\\README.md")
    except Exception as e:                                      # noqa: BLE001
        add(FAIL, f"--deep 失败：加载不了索引（{type(e).__name__}）", str(e)[:300],
            "RAG 会在起服务时静默降级。先修文件，再看这行错误")
elif DEEP:
    add(INFO, "跳过 --deep", "RAG 要件不齐，没什么可加载的")

head("六、API key 与桩模式")
# run.ps1:56 里写死的 key 文件路径（**只在 DEEPSEEK_API_KEY 没设时才 dot-source**）。
# 本脚本只 stat 它，**绝不读内容** —— key 的值一个字符都不该被这个脚本碰。
KEYFILE = r"D:\A11-Data\interview_framework\local_env.ps1"
key = config.DEEPSEEK_API_KEY
if key:
    add(OK, f"DEEPSEEK_API_KEY 已设置（长度 {len(key)}）",
        "**本脚本不打印它的值**，也不写入任何文件")
elif os.path.exists(KEYFILE):
    add(WARN, "当前环境里没有 DEEPSEEK_API_KEY",
        f"但 {KEYFILE} 存在，而 run.ps1:55 只在变量**没设时**才去 dot-source 它 —— "
        f"所以用 run.ps1 起服务是能拿到 key 的，这条多半是误报（直接跑 python app\\main.py "
        f"才真的没有）。本脚本不读那个文件的内容",
        "用 run.ps1 起就行；想把 key 显式握在手里就 $env:DEEPSEEK_API_KEY = '...'")
else:
    add(FAIL, "DEEPSEEK_API_KEY 未设置，且找不到 key 文件",
        "LLM 调不通：/start 会 502，/chat 报 llm_unavailable",
        f"$env:DEEPSEEK_API_KEY = '...'（另一条路是把 key 写进 {KEYFILE}，"
        f"run.ps1 会自动 dot-source；但**别把 key 写进任何交付包或日志**）")
print(f"         base_url = {config.DEEPSEEK_BASE_URL}   model = {config.DEEPSEEK_MODEL}")
if config.LLM_MOCK or config.RERANKER_MOCK:
    add(WARN, f"桩模式开着（LLM_MOCK={int(config.LLM_MOCK)} RERANKER_MOCK={int(config.RERANKER_MOCK)}）",
        "这时候面试官的话是固定话术、分数是固定分 —— **用来验收会得出错误结论**",
        "清掉这两个环境变量（$env:LLM_MOCK=$null）再起服务")

head("七、端口")
for port, note in ((config.THIS_PORT, "本框架"), (8000, "禁忌端口")):
    s = socket.socket()
    s.settimeout(0.4)
    busy = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if port == config.THIS_PORT:
        if busy:
            add(WARN, f"{port} 已被占用", "可能是本框架已经在跑了；不是的话换端口",
                "$env:FRAMEWORK_PORT = '8006'（记得同步前端）")
        else:
            add(OK, f"{port} 空闲（{note}要用的端口）")
    else:
        add(INFO, f"{port} {'被占用（正常）' if busy else '空闲'}",
            "8000 是 Godot AI MCP 占的**禁忌端口，本框架绝不能改用 8000**。"
            "这里只是探一下，被占是预期内的")

head("八、硬件与参数建议（仅供参考，本脚本不改任何配置）")
tot, avail = mem_mb()
if tot is None:
    add(INFO, "内存总量测不到", "非 Windows 或 API 不可用 —— 与 rag.py 一样跳过")
else:
    print(f"物理内存: 总计 {tot:,} MB ({tot / 1024:.1f} GB)，可用 {avail:,} MB ({avail / 1024:.1f} GB)")
    add(OK, f"内存 {tot / 1024:.1f} GB 总计 / {avail / 1024:.1f} GB 可用",
        "config.py:285-287 记的实测口径：两个 fp32 模型 4.5 GB + 索引 303 MB + "
        "题库 100 MB ≈ 5.2 GB（**不含 Python/torch 自身约 1.5 GB**）→ "
        "开 RAG 建议**可用 ≥ 7 GB、整机 ≥ 16 GB**")
    if tot < 8192:
        add(WARN, f"整机内存只有 {tot / 1024:.1f} GB", "开 RAG 会很紧（或根本不够）",
            "先 A11_RAG=0 跑通，再考虑 RAG_DTYPE=fp16（编码器 2.27 GB → 1.14 GB）")
    elif tot < 16384:
        add(WARN, f"整机内存 {tot / 1024:.1f} GB 属于偏紧", "两个模型 + torch 基线会吃满",
            "建议 RAG_DTYPE=fp16；跑之前关掉浏览器等占内存的程序")

try:
    import torch                                                # noqa: PLC0415
    cuda = torch.cuda.is_available()
    if cuda:
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory // 1048576
        add(INFO, f"检测到 CUDA：{name}（{vram:,} MB 显存）",
            "SCORER_DEVICE=auto 会自动用 CUDA。但注意 config.py:237-238 的提醒："
            "reranker 上 GPU 可能 OOM，所以 run.ps1 默认仍走 CPU",
            "建议 SCORER_DEVICE 保持 cpu 先跑通，再试 cuda")
    else:
        add(INFO, "没有可用的 CUDA", "全走 CPU。SCORER_DEVICE=auto 会落到 cpu",
            "保持默认即可")
    add(INFO, f"RAG 编码器精度建议：A11_RAG_DTYPE={config.RAG_DTYPE}",
        "fp16 把编码器从约 2.27 GB 降到约 1.14 GB，但**CPU 上 fp16 不一定更快、"
        "有些算子还会回退**；显存/内存不够时才优先考虑它。**以实跑为准**")
except ImportError:
    add(WARN, "装不上 torch", "上面第 1 节的依赖检查已经报过；"
                              "torch 不在就没法探测 GPU，也不影响 A11 起服务")

head("九、写权限与包完整性")
if os.path.isdir(config.LOG_DIR):
    writable = os.access(config.LOG_DIR, os.W_OK)
    add(OK if writable else WARN, f"日志目录已存在：{config.LOG_DIR}",
        "" if writable else "不可写 → 日志会降级成只输出到控制台（不致命）",
        "" if writable else "换个位置或放开权限")
else:
    parent_ok = os.access(os.path.dirname(config.LOG_DIR), os.W_OK)
    add(OK if parent_ok else WARN,
        f"日志目录还不存在（首次启动会创建）：{config.LOG_DIR}",
        f"父目录{'可写，没问题' if parent_ok else '不可写，日志会降级成只输出到控制台'}"
        "（只查了权限位，没有真的写文件 —— 本脚本只读）",
        "" if parent_ok else "把包放到一个可写的目录下")
miss_pkg = [p for p in ("app\\main.py", "app\\config.py", "run.ps1", "smoke_test.py",
                        "requirements.txt")
            if not os.path.exists(os.path.join(_ROOT, p))]
for job, fn in config.PERSONA_FILE_MAP.items():
    if not os.path.exists(os.path.join(config.PERSONA_DIR, fn)):
        miss_pkg.append(f"app\\personas\\{fn}")
if miss_pkg:
    add(FAIL, f"包内文件缺失（{len(miss_pkg)} 个）", "、".join(miss_pkg),
        "解压不完整。重新解压一次 zip 再看其它结论")
else:
    add(OK, f"包内文件齐全（app/ + personas/{len(config.PERSONA_FILE_MAP)} 份人设 + "
            f"run.ps1 + smoke_test.py + requirements.txt）")

head("十、语音输入（ASR，赛题 2a / 3b）")
# 与第五节同一条口径：默认开（config.py:444）→ 想用却缺件是 FAIL；没打算开就只是提示。
# 缺件**不会**让面试出问题（/asr 返 503 asr_unavailable，文字链路一个字节都不变），
# 但「语音输入」是赛题明写的硬要求，默认档下缺了就是这台机器上少了一条要求。
ASR_LVL = FAIL if config.A11_ASR else WARN
asr_suffix = ("→ A11_ASR 默认就是 1（config.py:444），语音输入是赛题 2a 的硬要求，"
              "这些应该齐" if config.A11_ASR else
              "→ 现在 A11_ASR=0：/asr 返 503 asr_disabled。要开就设 $env:A11_ASR='1'，"
              "届时下面这些都得齐")

# 模型缓存目录：**不**在 hub\ 下面（与第四节那两个不同）。两件事共同决定它 ——
#   ① asr.py:292-295 `_repo_id()`：`small` → `Systran/faster-whisper-small`
#   ② asr.py:275 给 WhisperModel 显式传了 `download_root=config.HF_HOME`
#      （不给的话 huggingface_hub 会落到 C 盘的 ~/.cache/huggingface，违反「数据放 D/E 盘」）
# 所以位置是 <HF_HOME>\models--Systran--faster-whisper-small\（HF 的 `--` 命名规则）。
_asr_repo = (config.A11_ASR_MODEL if "/" in config.A11_ASR_MODEL
             else f"Systran/faster-whisper-{config.A11_ASR_MODEL}")
ASR_MODEL_DIR = os.path.join(config.HF_HOME, "models--" + _asr_repo.replace("/", "--"))
# 本机实测的权重字节数（2026-09-23）。只提示不判死：别的 revision 大小会不同。
ASR_BIN_BYTES = 483546902

print(f"config.A11_ASR = {config.A11_ASR}   （A11_ASR={'1' if config.A11_ASR else '0'}）")
print(f"模型档位 {config.A11_ASR_MODEL} → {_asr_repo}   "
      f"device={config.A11_ASR_DEVICE} compute={config.A11_ASR_COMPUTE_TYPE}")
print(f"门槛 A11_ASR_MIN_FREE_MB = {config.A11_ASR_MIN_FREE_MB}   "
      f"首次加载最长等 {config.A11_ASR_WAIT_SEC} 秒（超时回 503 asr_loading）")
print(f"上限 {config.A11_ASR_MAX_MB} MB / {config.A11_ASR_MAX_SEC} 秒（超了 413，不静默截断）"
      f"   语言 {config.A11_ASR_LANGUAGE}   beam {config.A11_ASR_BEAM}")
print(f"格式白名单 {'/'.join(config.ASR_FORMATS)}")
print(f"模型缓存位置 {ASR_MODEL_DIR}")

if config.A11_ASR_MOCK:
    add(WARN, "语音桩模式开着（A11_ASR_MOCK=1）",
        "/asr **不加载模型、也不解码音频**：传什么音频都回同一段固定转写"
        "（含一次 2.2 秒停顿与一个填充词）。它只给冒烟测试与 4 号 假服务用",
        "演示 / 验收前清掉：$env:A11_ASR_MOCK=$null（再重启服务）")

# ---- 依赖（那四条单独成组，见第一节的说明）----
_want = dict(pins)
asr_miss, asr_bad = [], []
for name in ASR_DEPS:
    want = _want.get(name, "?")
    try:
        got = md.version(name)
    except md.PackageNotFoundError:
        asr_miss.append((name, want))
        continue
    if want != "?" and public_version(got) != public_version(want):
        asr_bad.append((name, want, got))
if asr_miss:
    add(ASR_LVL, f"语音转写依赖缺失（{len(asr_miss)}/{len(ASR_DEPS)} 条）："
        + "、".join(f"{n}=={v}" for n, v in asr_miss),
        "这四条是一组：faster-whisper（转写）+ ctranslate2（推理引擎）+ av（解码任意音频）"
        "+ onnxruntime（跑 silero VAD —— **语速的分母与「停顿」次数都靠它量**）。"
        "缺了 /asr 返 503 asr_unavailable；**面试与文字作答一个字节都不受影响**",
        "pip install " + " ".join(f'"{n}=={v}"' for n, v in asr_miss)
        + "（或整包 pip install -r requirements.txt）")
else:
    add(OK, f"语音转写依赖齐了（{len(ASR_DEPS)} 条："
            + " / ".join(ASR_DEPS) + "）")
for name, want, got in asr_bad:
    add(WARN, f"语音转写依赖版本不一致：{name} 装的是 {got}，pin 是 {want}",
        "只影响 /asr，不影响面试。/asr 的结果里会带上真实档位标签，换版本后**语速口径**"
        "可能有细微差别，靠标签分辨即可",
        f"pip install \"{name}=={want}\"")

# ---- 模型缓存在不在（这是换机器时的第一道判据，config.py:443 点名了本脚本）----
_asr_snaps = os.path.join(ASR_MODEL_DIR, "snapshots")
_bins = sorted(glob.glob(os.path.join(_asr_snaps, "*", "model.bin")))
if not _bins:
    add(ASR_LVL, f"语音模型缓存缺失：{_asr_repo}",
        f"期望在 {ASR_MODEL_DIR}\n         {asr_suffix}",
        "(1) 拷 models--Systran--faster-whisper-small 整个目录（约 464 MB）到 "
        f"{config.HF_HOME}\\ 下；(2) 或让新机器自己下载（约 464 MB）："
        "设 $env:HF_ENDPOINT='https://hf-mirror.com'，并注意 run.ps1:26-27 会**无条件**"
        "强制离线 —— 走 run.ps1 就得改那两行，直接 python app\\main.py 起则 "
        "$env:HF_HUB_OFFLINE='0' 有效。"
        "⚠️ 缺了它 /health 会显示 asr_enabled=true / asr_ready=false —— 那是"
        "「**还没人调过 /asr**」（懒加载，不调就不加载模型），与「加载失败」"
        "（asr_error 非空）是两回事，别混")
else:
    _b = os.path.getsize(_bins[0])
    _note = (f"model.bin {human(_b)}"
             + ("" if _b == ASR_BIN_BYTES
                else f"（本机实测的是 {ASR_BIN_BYTES:,} B，**只提示不判死**："
                     f"别的 revision 大小本来就不同）"))
    add(OK, f"语音模型缓存存在：{_asr_repo}", _note
        + "；注意它**不在** hub\\ 下（asr.py:275 给 WhisperModel 传了 download_root）")

# ---- 情感分析 / 语气自信度（赛题 3b 的另一半，2026-09-25 加）----
# 与 ASR 同一条三态纪律，**「没开」与「坏了」必须分得开**（asr.py:430 那句）：
#   A11_ASR_EMOTION=0          → 运维选择，只提一句（要开却关着才是 FAIL，见下）
#   开着但权重不在 / 加载失败   → 这台机器上少做到 3b 的一半，按 ASR 的先例判 FAIL
#   齐了                       → OK
# ⚠️ **零新依赖**：用的就是 pin 里的 transformers==4.49.0 + torch==2.14.0，
#    模型是标准 `Wav2Vec2ForSequenceClassification`，不需要 funasr/modelscope
#    （那条路会跟 numpy pin 打架，已记档不做）。
# ⚠️ 位置**在 hub\ 下**（huggingface_hub 的标准布局）—— 与 whisper 那条刚好相反，
#    `asr.py` 的 EmotionEngine 没给 download_root，走的是 app/__init__.py 的 HF_HOME。
EMO_LVL = FAIL if (config.A11_ASR_EMOTION and config.A11_ASR) else WARN
_emo_repo = config.A11_ASR_EMOTION_MODEL
EMO_MODEL_DIR = os.path.join(config.HF_HOME, "hub",
                             "models--" + _emo_repo.replace("/", "--"))
# 本机实测的权重字节数（2026-09-25，revision 441a7599）。只提示不判死。
EMO_BIN_BYTES = 378361105

print(f"config.A11_ASR_LOUDNESS = {config.A11_ASR_LOUDNESS}（音量三指标）   "
      f"A11_ASR_EMOTION = {config.A11_ASR_EMOTION}（情感模型 + 自信度档位）")
# ⚠️ 这一个**没进 config.py**（是 asr.py:270 自己读的环境变量，为了给函数默认参数用）。
#    本脚本按同一口径照读一遍，**只用来打印**，不参与任何判断。
_emo_max_sec = os.environ.get("A11_ASR_EMOTION_MAX_SEC", "15")
print(f"情感模型 {_emo_repo}   device={config.A11_ASR_EMOTION_DEVICE}   "
      f"只喂前 {_emo_max_sec} 秒人声")
print(f"情感模型缓存位置 {EMO_MODEL_DIR}")

if not config.A11_ASR_EMOTION:
    add(WARN, "情感分析关着（A11_ASR_EMOTION=0）",
        "赛题 3b 原文是「集成语音识别**与情感分析**，评估…语气自信度」—— 关掉它，"
        "这一半就不在这台机器上生效。/asr 里那几个键恒为 None（**不是 0**）",
        "要开就设 $env:A11_ASR_EMOTION='1'，并确认权重在（下载命令见本包 "
        "`数据\\README.md` 与《交付说明-后端.md》§5.5）")
else:
    _emo_snaps = os.path.join(EMO_MODEL_DIR, "snapshots")
    _emo_bins = sorted(glob.glob(os.path.join(_emo_snaps, "*", "pytorch_model.bin"))
                       + glob.glob(os.path.join(_emo_snaps, "*", "model.safetensors")))
    if not _emo_bins:
        add(EMO_LVL, f"情感模型缓存缺失：{_emo_repo}",
            f"期望在 {EMO_MODEL_DIR}\n         "
            "→ 缺了**不会让服务起不来**：转写、面试、文字作答一个字节都不变，"
            "只是 /asr 里情感/自信度那几个键为 None，/health 的 emotion_error 会写明原因。"
            "但 3b 的情感那一半就成了「这台机器上没做到」",
            "(1) 拷 models--superb--wav2vec2-base-superb-er 整个目录（约 361 MB）到 "
            f"{config.HF_HOME}\\hub\\ 下（**注意是 hub\\ 里**，和 whisper 那个不一样）；"
            "(2) 或让新机器自己下（约 361 MB，与三大模型同一条命令）："
            "设 $env:HF_ENDPOINT='https://hf-mirror.com' 后跑 "
            "`from huggingface_hub import snapshot_download as d; "
            f"d('{_emo_repo}')`；"
            "⚠️ 走 run.ps1 起来的话它:26-27 会**无条件强制离线**，下载要在另一个窗口做。"
            "⚠️ **绝不允许**靠「第一次请求时现场下」来补 —— EmotionEngine 是 "
            "`local_files_only=True` 的（asr.py:432），就是不许在真实面试的请求里"
            "卡一个 360MB 下载")
    else:
        _eb = os.path.getsize(_emo_bins[0])
        _enote = (f"{os.path.basename(_emo_bins[0])} {human(_eb)}"
                  + ("" if _eb == EMO_BIN_BYTES
                     else f"（本机实测的是 {EMO_BIN_BYTES:,} B，**只提示不判死**："
                          f"别的 revision 大小本来就不同）"))
        add(OK, f"情感模型缓存存在：{_emo_repo}", _enote
            + "；在 hub\\ 下（与两个 BGE 同层，与 whisper 相反）")

    add(INFO, "音量/情感那几个键怎么读（**别读成情绪结论、也别读成自信得分**）",
        "`/asr` 多出来的 6 个键是 —— loudness / loudness_cv / tail_ratio（**只读波形**的"
        "韵律三指标，按**不超过 3 秒的窗**算）、emotion / emotion_score / emotion_dist"
        "（`superb/wav2vec2-base-superb-er` 的输出）。而 `confidence`（偏低/中等/偏高）是"
        "**拿韵律两指标按写死的规则融出的档位**（asr.py 的 confidence_band）—— "
        "**不是**模型给出的「自信度」，文档与界面都别这么写；"
        "它**不在 `/asr` 的返回里**，只出现在 `/finish` 的 `pace_note` 文案里（那句依据同处）。"
        "⚠️ 那个模型是 **IEMOCAP（英语、表演式情感）**训的，中文面试语音在它眼里是"
        "分布外输入：2026-09-25 拿 3 条真中文语音实测，**3/3 判成 hap**、sad 恒 0、"
        "**0/3 是 neu** —— 所以它的**标签**没有可信度，我们只拿**整个分布**当韵律信号，"
        "它**也没参与** confidence 的档位规则",
        "演示时可以说「这是语音的韵律观察」，**别说**「系统判断考生情绪激动/紧张」")

# ---- 内存（与第五节 RAG 那条同一套语义：取不到值就跳过，不当 0）----
if config.A11_ASR:
    _, avail_a = mem_mb()
    if avail_a is None:
        add(INFO, "内存可用量测不到，跳过语音预检",
            "asr.py:259-263 取不到值时**跳过预检**（不是当 0）—— 与 rag.py 同一条语义")
    elif avail_a < config.A11_ASR_MIN_FREE_MB:
        add(FAIL, f"可用内存 {avail_a} MB < A11_ASR_MIN_FREE_MB="
                  f"{config.A11_ASR_MIN_FREE_MB} MB",
            "asr.py:261-263 的预检会抛 MemoryError → 本进程内永久降级，"
            "之后每次 /asr 都 503（重启才重试）",
            "关掉别的占内存的程序；或改小 A11_ASR_MIN_FREE_MB（那只是门槛）；"
            "或换更小的档位 $env:A11_ASR_MODEL='base'/'tiny'")
    else:
        add(OK, f"可用内存 {avail_a} MB ≥ A11_ASR_MIN_FREE_MB="
                f"{config.A11_ASR_MIN_FREE_MB} MB",
            "门槛只是起步线。小档位 small(int8) 常驻约 +0.5~0.6 GB；"
            "若同时开着 RAG，两个模型会叠在同一个进程里（见第八节的内存账）")

add(INFO, "/health 里语音那三个键怎么读",
    "asr_enabled = A11_ASR 这个开关本身；asr_ready=true 才是模型真加载好了；"
    "**asr_ready=false 且 asr_error 为空 = 还没人调过 /asr**（懒加载），"
    "asr_error 非空才是加载失败（进程内永久降级）",
    "验收语音时：先 POST 一次 /asr，再看 /health 的 asr_ready / asr_error")

head("十一、学习资源与专项练习（赛题 4a / 4b）")
print(f"config.A11_RECOMMEND = {config.A11_RECOMMEND}   "
      f"A11_PRACTICE = {config.A11_PRACTICE}（默认练 {config.PRACTICE_QUESTIONS} 道，"
      f"上限 {config.PRACTICE_MAX}）")
print(f"config.RESOURCE_JSON = {config.RESOURCE_JSON or '(未设置，按候选顺序找)'}")
for i, c in enumerate(config.RESOURCE_JSON_CANDIDATES, 1):
    print(f"         候选 {i}: {c}   {'存在' if os.path.exists(c) else '不存在'}")

if not config.A11_RECOMMEND:
    add(INFO, "学习资源推荐已关闭（A11_RECOMMEND=0）",
        "raw.blindspots 里不会再挂 recommendations[]",
        "要开就设 $env:A11_RECOMMEND='1'（默认是开的）")
else:
    if config.RESOURCE_JSON:
        _rp, _rsrc = config.RESOURCE_JSON, \
            "来自环境变量 A11_RESOURCES_JSON（**优先级最高**：显式设了但不存在会把" \
            "「你设的路径不存在」原样报进 resource_error，**不会**静默回退到候选路径）"
    else:
        _rlist = [c for c in config.RESOURCE_JSON_CANDIDATES if os.path.exists(c)]
        _rp = _rlist[0] if _rlist else None
        _rsrc = (f"未设 A11_RESOURCES_JSON，按候选顺序命中第 "
                 f"{config.RESOURCE_JSON_CANDIDATES.index(_rp) + 1} 条"
                 if _rp else "未设 A11_RESOURCES_JSON，候选路径**一个都不存在**")
    print(f"实际使用的资源样例: {_rp}\n         （{_rsrc}）")

    if _rp is None or not os.path.exists(_rp):
        _degrade = ("这一条**不影响面试**：推荐条目仍在，只是退化成「只有漏掉的得分点原文」"
                    "（没有考点讲解 / 相关题目 / 样例题），4a 那条赛题要求就只剩一半。")
        if _rp is None:
            add(WARN, "找不到学习资源样例文件 → 4a 会降级",
                _degrade + "在 1 号包里它本该躺在 `数据\\学习资源样例.json`"
                "（打包.py 按字节数核过）—— 缺了多半是解压不全或漏拷",
                '把 学习资源样例.json（约 4.5 MB，**2026-09-25 起从 174 KB 涨上来的**，'
                '别拿旧尺寸认它）放到包内 `数据\\` 下，或 '
                f'$env:A11_RESOURCES_JSON = "<那个文件>"'
                f'（开发机上在 {config.RESOURCE_JSON_CANDIDATES[1]}）')
        else:
            add(WARN, f"A11_RESOURCES_JSON 指向的文件不存在：{_rp}",
                _degrade + "⚠️ resources.py:201-203 是「显式配置优先」：**设了就只用它**，"
                "不会回退到候选路径 —— 顺手把变量清掉（$env:A11_RESOURCES_JSON=$null）"
                "反而能命中包内那一份",
                "改成一个真存在的文件，或清掉这个环境变量")
    else:
        try:
            with open(_rp, encoding="utf-8-sig") as f:
                _rd = json.load(f)
        except Exception as e:                                  # noqa: BLE001
            add(WARN, "学习资源样例读不了", f"{type(e).__name__}: {e}",
                "多半是拷坏了（用字节数核一下）或不是 JSON。会被静默降级成空列表")
            _rd = None
        if isinstance(_rd, dict) and not _rd.get("岗位"):
            add(WARN, "学习资源样例结构不对：没有 `岗位` 数组",
                "resources.py:238-239 会直接判它不可用（与这里同一道闸）",
                "换回完整的 学习资源样例.json")
        elif isinstance(_rd, dict):
            _jobs = _rd.get("岗位") or []
            _kps = [e for j in _jobs for e in (j.get("考点") or [])]
            _no_id = [e for e in _kps if not str(e.get("kp_id") or "").strip()]
            _no_talk = [e for e in _kps if not str(e.get("考点讲解") or "").strip()]
            _pq = _rd.get("题目范文") or {}
            _pq_demo = sum(1 for v in _pq.values()
                           if isinstance(v, dict) and v.get("kind") == "示范作答")
            add(OK, f"学习资源样例可用：{len(_jobs)} 个岗位 / {len(_kps)} 个考点"
                    + (f" / 题目范文 {len(_pq):,} 条" if _pq else ""),
                f"{human(os.path.getsize(_rp))}；⚠️ 本文件**含得分点与核心答案**，"
                f"只进 1 号包（打包.py 的泄题闸管这条），4 号包连 `数据\\` 都没有")
            if not _pq:
                add(WARN, "学习资源样例里**没有** `题目范文` 平索引 —— 这是旧文件",
                    "「每题一条范例」靠的就是这张按题号挂的平索引；缺了它，"
                    "`/model_answer` 只能走「考点 → 代表题」那条路，"
                    "**1,110 道一个考点都不挂的题就取不到**（返回 404 no_material）",
                    "换回 2026-09-25 之后生成的 `学习资源样例.json`")
            elif _pq_demo:
                add(INFO, f"`题目范文` {len(_pq):,} 条里有 {_pq_demo:,} 条 kind=示范作答",
                    "这些题主库给的**只有答题结构（STAR 骨架）、没有判分内容**，"
                    "那条「范例」是模型照结构编的通用示例，**不是**真题的优秀答案",
                    "接口里同一条返回带着 `note`，**前端必须把它显示出来** —— "
                    "否则考生会把编出来的经历当范文背下来")
            if _no_id:
                add(WARN, f"有 {len(_no_id)} 个考点没有 kp_id",
                    "resources.py:93-94 按 kp_id 索引，**没有 kp_id 的会被静默丢掉**"
                    "（那些考点永远匹配不上资源）",
                    "检查生成脚本；正常导出不该有这种条目")
            if _no_talk:
                add(INFO, f"有 {len(_no_talk)} 个考点没有「考点讲解」",
                    "这些考点命中的推荐块里讲解字段会是空的（其余字段照给）")

# 4b 没有额外要件：它复用同一份题库（第二节已逐个查过）与同一条评分链路
if config.A11_PRACTICE:
    add(INFO, "专项强化练习（4b）已启用",
        "它从一份**已交卷**的成绩单挑薄弱项，按考点从题库取题 —— 依赖的是第二节那份题库，"
        "没有自己的数据文件。链路见 app/core/practice.py",
        "冒烟测试里有覆盖；真跑一遍就是 /start → /next → /chat… → /finish → /practice")
else:
    add(INFO, "专项强化练习已关闭（A11_PRACTICE=0）", "/practice 会返 503 disabled",
        "要开就设 $env:A11_PRACTICE='1'")

# 成长档案（赛题 4）没有额外要件：它**无状态**（不查库、不落盘、不认人），
# 只读第二节那份题库（考点地图的全量骨架）＋ KG（归类），身份与存档都在 1 号 那边。
if config.A11_GROWTH:
    add(INFO, "成长档案（赛题 4）已启用",
        "`POST /growth` 是唯一一个不碰会话、也没状态的端点：入参是一批成绩单摘要"
        "（`/finish` 与 `/result` 响应里那个顶层 `digest` 键），出参是错题本 / 考点地图 / "
        "历史成绩 / **提升路径（`plan`）** 四份聚合。链路见 app/core/growth.py",
        f"一次最多 {config.GROWTH_MAX_RECORDS} 份摘要、单份上限 "
        f"{config.GROWTH_MAX_DIGEST_BYTES} 字节（超了返 413）；"
        "冒烟里的纯函数节 + 端到端节覆盖了它")
else:
    add(INFO, "成长档案已关闭（A11_GROWTH=0）",
        "/growth 会返 503 growth_disabled，且 /finish 与 /result 的 `digest` 是 null"
        "（**不是 `{}`，也不是「这个键不存在」** —— 1 号 靠这个区别判断该不该存档）",
        "要开就设 $env:A11_GROWTH='1'（默认就是开的）")

# 学习材料（赛题 4a 的「知识点讲解 / 优秀回答范例」对考生可见的那个出口）。
# ⚠️ 这是**唯一一处「默认档也能把教学正文给考生」**的放宽 —— 它此前只在
#    `A11_RAW_DETAIL=1` 的 `raw` 里。为什么敢放宽：门是结构性的（见下）。
if config.A11_MODEL_ANSWER:
    add(INFO, "学习材料（考点讲解 / 优秀回答范例）已启用",
        "`POST /model_answer` 收 `{session_id, kp_id?, question_id?}`（**两个目标至少给"
        "一个**，都不给是 422 missing_target；两个都给走 kp_id 那条），出 `talk` / "
        "`model_answer` / `from_question_id` / `kind` / `note` 五样（**白名单构造**，"
        "`拉开差距` / `常见卡点` / 得分点原文"
        "一个字节都不出，也**不给代表题的题面**）。⚠️ `kind` 与 `note` **必须成对渲染**："
        "全量 5,012 题里有 **991 条** `kind=\"示范作答\"`（那些题主库只给了答题结构、没有"
        "判分内容，正文是照结构编的通用示例）—— **只显示 `model_answer` 不显示 `note`，"
        "等于让考生把一段编出来的经历当优秀范例背下来**。三道闸：源场次必须已交卷"
        "（否则 409 source_not_finished ⇒ 面试途中查不到答案）、kp_id / question_id 必须"
        "出现过在**那一场的诊断**里（否则 404 answer_target_not_found ⇒ 没法枚举刷资源）、"
        "资源侧查不到就是 404 no_material（与「这场没考」**不同码**）",
        "`/growth` 的 `plan.items[].material` 只说明**有没有**材料（四态：ready / "
        "disabled / broken / not_found —— 「开关没开」「文件坏了」「这个考点没材料」"
        "是三件事）；正文必须另调本端点")
else:
    add(INFO, "学习材料已关闭（A11_MODEL_ANSWER=0）",
        "`POST /model_answer` 会返 503 model_answer_disabled；`/health` 里 "
        "`model_answer_enabled=false`（「没开」看得见）",
        "要开就设 $env:A11_MODEL_ANSWER='1'（默认就是开的）。"
        "⚠️ 它**不跟着** `A11_RECOMMEND` 走：资源没开时是 503 resource_unavailable，"
        "两个码不同")

# ---- 端点数自检（**数源码，不数文档**）----
# 为什么必须有这一条：端点数散落在源码 6 处 + 交付文档 30 余处，全靠人眼 grep「九个」
# 一定会漏，而漏了**不会报错**（文档说 9 个、服务给 10 个，没人发现）。这里用 AST 数
# `@router.<method>("/路径")` —— 加了/删了端点却忘了同步文档时，这一条先响。
# 不 import `app.api.interview`：那会连带加载题库与日志目录（违反本脚本第 2 条约束）。
try:
    import ast as _ast
    # 路径从**已导入的 `config`** 反推，不用 `_ROOT`：本脚本在「包根」（app/ 同级）
    # 与「开发机的 D:\A11-交付」（app/ 不在这里）两种布局下都要能跑。
    _appdir = os.path.dirname(os.path.abspath(config.__file__))          # …/app
    _ivp = os.path.join(_appdir, "api", "interview.py")
    with open(_ivp, encoding="utf-8") as _f:
        _tree = _ast.parse(_f.read(), filename=_ivp)
    _eps = set()
    for _node in _ast.walk(_tree):
        if isinstance(_node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            for _dec in _node.decorator_list:
                _fn = _dec.func if isinstance(_dec, _ast.Call) else _dec
                if (isinstance(_fn, _ast.Attribute) and isinstance(_fn.value, _ast.Name)
                        and _fn.value.id == "router" and isinstance(_dec, _ast.Call)
                        and _dec.args and isinstance(_dec.args[0], _ast.Constant)):
                    _eps.add("%s %s" % (_fn.attr.upper(), _dec.args[0].value))
    _n_ep = len(_eps)
    if _n_ep == 10:
        add(OK, f"端点自检：源码里正好 {_n_ep} 个端点（与交付文档口径一致）",
            "、".join(sorted(_eps)))
    else:
        add(FAIL, f"端点自检：源码里数到 {_n_ep} 个，**不是 10 个**",
            "、".join(sorted(_eps)),
            "端点增删后必须同步改：README / 清单-给1号 / 清单-给4号 / 四份 gen_docx_*.py / "
            "包内《交付说明-后端.md》《交付说明-前端.md》—— 清单见 owed.md")
except Exception as _e:                                    # noqa: BLE001
    add(WARN, "端点自检没跑起来（源码读不到或语法变过）",
        f"{type(_e).__name__}: {_e}", "不影响其它检查")

# 考生复盘清单 `review`（`/finish` 与 `/result` 的顶层键，**不是端点**）：
# ⚠️ 与 `A11_GROWTH` 是**两个独立开关** —— 它读 `raw` 本身、**不从 `digest` 派生**，
# 所以 `A11_GROWTH=0` 不会把它一起关掉（给考生的复盘不该被「1 号要不要存档」连坐）。
if config.A11_REVIEW:
    add(INFO, "考生复盘清单 `review` 已启用",
        "`/finish` 与 `/result` 的**顶层多一个 `review` 键**（给考生看的那一份："
        "headline / gaps[] / covered[] / uncovered[] / actions[] / counts / caveats）。"
        "端点数**不变**（`review` 不是端点），所以关掉它**不会 503**。"
        "链路见 app/core/review.py",
        f"清单里最多给 {config.REVIEW_MAX_ACTIONS} 条「下一步」"
        "（`A11_REVIEW_MAX_ACTIONS`）；冒烟里的纯函数节 + 端到端节覆盖了它")
else:
    add(INFO, "考生复盘清单已关闭（A11_REVIEW=0）",
        "`/finish` 与 `/result` 的 `review` 会变成 null"
        "（**不是 `{}`，也不是「这个键不存在」**）—— 端点数不变，**不会 503**",
        "要开就设 $env:A11_REVIEW='1'（默认就是开的）；"
        "⚠️ 它**不跟着 `A11_GROWTH` 走**：`A11_GROWTH=0` 时 `digest` 是 null，"
        "但 `review` 照常出门（它读的是 `raw`）")

# 面试官风格三档（F）+ 考生自述进 prompt（E）。**两个独立开关**：
#   A11_PERSONA=0 → 传档名不报错、按 standard 跑、`/start` 回显实际生效的那一档；
#   A11_INTRO=0   → 自述仍进 `raw.candidate_intro` 原文，但**不进 prompt**、开场白退回通用那条。
# ⚠️ 这一对的共同前提是「**默认档下 system 逐字节不变**」—— 所以它俩关掉时，
#    送进模型的那段 system 与加这个功能之前一模一样（此前所有真 LLM 对照读数仍然可比）。
#    **真正打破「模板逐字节相同」的只有一种情况：某一场真的传了非空 intro。**
if config.A11_PERSONA:
    add(INFO, "面试官风格三档已启用",
        "`/start` 可传 `persona_style`（strict / standard / relaxed，即 严厉 / 标准 / 轻松），"
        "响应回显 `persona_style` + `persona_label`；档名写错 → **422 bad_persona_style**"
        "（报错，不静默按默认跑）。**标准档的追加块是空串** ⇒ 不传档名时"
        "送进模型的 system 与加这个功能之前**逐字节相同**",
        "冒烟里的纯函数节 + 端到端节覆盖了它；关掉见下一条")
else:
    add(INFO, "面试官风格三档已关闭（A11_PERSONA=0）",
        "`/start` 仍接受 `persona_style`、**不会 422**，但一律按 standard 跑，"
        "回显的也是 standard（回显的是**实际生效**值，所以「关掉」看得见）；"
        "system 逐字节回到基线",
        "要开就设 $env:A11_PERSONA='1'（默认就是开的）")

if config.A11_INTRO:
    add(INFO, f"考生自述（简历）会进提示词，上限 {config.INTRO_MAX_CHARS} 字",
        "`/start` 的 `intro` 进面试官 system 的**【考生自述】块**（渲染后追加在末尾，"
        "不是新槽位），开场白会引用其中第一句；响应里 `intro_read` 报"
        "enabled / chars / raw_chars / truncated / snippet。"
        "⚠️ 这是全项目**唯一一处「传了东西才会改提示词」**的地方：不传自述的场次"
        "（含此前所有真 LLM 对照）system **逐字节不变**，所以那批读数仍然可比",
        "自述在进 prompt 前会被压平换行/控制字符并截断；"
        "评分模板（ROUND_SCORING 等）里**一个字节都不放它**，这一条是结构性的")
else:
    add(INFO, "考生自述不进提示词（A11_INTRO=0）",
        "`/start` 仍收 `intro`、仍原样进 `raw.candidate_intro`（3 号 要的是原样），"
        "但**不进 system**、开场白退回通用那条；响应里 `intro_read.enabled=false`"
        "（与「没传」的 `null` 分得开）",
        "要开就设 $env:A11_INTRO='1'（默认就是开的）")

# ---- 4a 的可选件：真知识库索引（**不进包**，见 交付说明-后端.md §9.4）----
# 判定分级照 `A11_RESOURCES_JSON` 的「显式配置优先」先例：
#   A11_KB_DIR **显式设了**但索引不在 → FAIL（设了就必须在，且不许静默回退）；
#   未设、按代码默认路径找不到 → WARN（这是「可选件没装」，不是故障）。
# 注意：这里**不加载编码器**（2.3 GB）—— 那件事第一节和第四节已经查过模型在不在，
# 真加载一次是 `--deep` 之外的负担，而运行期 kb.py 本来就会自己加载并上报。
if not config.A11_KB_REC:
    add(INFO, "知识库检索已关闭（A11_KB_REC=0）",
        "recommendations[] 里不会挂 kb_refs 这个键，4a 退回纯题库派生"
        "（与加这个功能之前逐字节相同）",
        "要开就设 $env:A11_KB_REC='1'（默认就是开的；没有索引时开与不开输出逐字节相同）")
else:
    _kbenv = os.environ.get("A11_KB_DIR")
    print(f"config.KB_DIR = {config.KB_DIR}"
          + ("　← 来自环境变量 A11_KB_DIR" if _kbenv is not None
             else "　← 未设 A11_KB_DIR，用的是代码默认（build_kb_index.py 的产物目录）"))
    print(f"config.KB_TOP_N = {config.KB_TOP_N}   "
          f"KB_SNIPPET_CHARS = {config.KB_SNIPPET_CHARS}   "
          f"KB_MIN_SCORE = {config.KB_MIN_SCORE}   "
          f"KB_MAX_TOKENS = {config.KB_MAX_TOKENS}")
    _kbrec = os.path.join(config.KB_DIR, config.KB_RECORDS_PKL)
    _kbnpz = os.path.join(config.KB_DIR, config.KB_INDEX_NPZ)
    _kbmeta = os.path.join(config.KB_DIR, "build_meta.json")
    _kbmiss = [p for p in (_kbrec, _kbnpz) if not os.path.exists(p)]

    if _kbmiss:
        _kbhow = (f'两条路：(1) 整目录拷过来 —— 把开发机的 {config.KB_DIR} 拷到同一位'
                  f'置（约 100+ MB，两个文件必须来自同一次构建）；'
                  f'(2) 在新机器上重建 —— 需要 D:\\A11-Data\\ai-reference\\ 那 6 个 md '
                  f'（约 27 MB），然后 & $env:A11_PYTHON build_kb_index.py（本包根目录）')
        if _kbenv is not None:
            add(FAIL, f"A11_KB_DIR 显式设了但索引不在：{config.KB_DIR}",
                "缺：" + "、".join(os.path.basename(p) for p in _kbmiss)
                + "。⚠️ kb.py:113-121 是「显式配置优先」：**设了就只用它**，"
                  "不会回退到别处 —— 结果是 kb_refs 永远为空、且 kb_error 里写着这个路径",
                _kbhow)
        else:
            add(WARN, f"知识库索引没装（可选件）：{config.KB_DIR} 下找不到索引",
                "影响很小：4a 的推荐条目照常给（那是纯题库派生的），只是不带知识库参考。"
                "/health 里会是 kb_ready=false、kb_error 非空（**这是「没装」，不是「坏了」**）",
                _kbhow)
    else:
        _kbn, _kbdim = None, None
        try:
            import numpy as _np          # 懒 import：只有索引真的在才用得上
            import pickle as _pkl
            with open(_kbrec, "rb") as f:
                _kbrecs = _pkl.load(f)
            _z = _np.load(_kbnpz, allow_pickle=False)
            _kbe, _kbids = _z["embeddings"], _z["ids"]
            _kbn, _kbdim = int(_kbe.shape[0]), int(_kbe.shape[1])
            if not (len(_kbrecs) == len(_kbids) == _kbn):
                add(FAIL, "知识库索引自相矛盾：两个文件不是同一次构建的",
                    f"records={len(_kbrecs)} ids={len(_kbids)} embeddings={_kbn}"
                    "（kb.py:128-132 会直接判它不可用 → kb_refs 恒空）",
                    "重建一遍：& $env:A11_PYTHON build_kb_index.py")
            else:
                _norms = _np.linalg.norm(_kbe, axis=1)
                _bad = int((_np.abs(_norms - 1.0) > 1e-3).sum())
                add(OK, f"知识库索引可用：{_kbn:,} 块 × {_kbdim} 维",
                    f"{human(os.path.getsize(_kbrec) + os.path.getsize(_kbnpz))}"
                    f"（records {human(os.path.getsize(_kbrec))} + "
                    f"npz {human(os.path.getsize(_kbnpz))}）"
                    + (f"；⚠️ 有 {_bad} 条未 L2 归一化，运行时会就地归一化并告警"
                       "（检索按点积=余弦实现）" if _bad else "；全部已 L2 归一化"))
                # 岗位覆盖：哪个岗位一块都没有 = 那个岗位的 4a 拿不到知识库参考
                _cnt = {j: 0 for j in config.JOBS}
                _cnt["(未映射)"] = 0
                for _r in _kbrecs:
                    _js = (_r.get("metadata") or {}).get("岗位") or []
                    if not _js:
                        _cnt["(未映射)"] += 1
                    for _j in _js:
                        _cnt[_j if _j in _cnt else "(未映射)"] += 1
                _zero = [j for j in config.JOBS if not _cnt.get(j)]
                print("         按岗位（块可属多个岗位）："
                      + "　".join(f"{j}={_cnt.get(j, 0)}" for j in config.JOBS)
                      + f"　未映射={_cnt['(未映射)']}")
                if _zero:
                    add(WARN, f"知识库索引里这些岗位一块都没有：{'、'.join(_zero)}",
                        "它们的 4a 推荐一律拿不到 kb_refs（岗位过滤是「岗位必须在 "
                        "metadata.岗位 里」，见 kb.py:264）",
                        "多半是 build_kb_index.py 的 JOB_DOCS 表与该知识库的"
                        "「岗位与文件对应」表不同步了")
        except Exception as _e:                                 # noqa: BLE001
            add(FAIL, "知识库索引读不了",
                f"{type(_e).__name__}: {_e}",
                "多半是拷坏了（用上面的字节数核一下）。kb.py 会静默降级成空 kb_refs")
            _kbrecs = None

        if os.path.exists(_kbmeta):
            try:
                with open(_kbmeta, encoding="utf-8") as f:
                    _m = json.load(f)
            except Exception as _e:                             # noqa: BLE001
                add(WARN, "build_meta.json 读不了", f"{type(_e).__name__}: {_e}",
                    "它只是建库台账，不影响检索；重跑 build_kb_index.py 会重写")
            else:
                _drift = []
                if _kbn is not None and _m.get("块数") != _kbn:
                    _drift.append(f"块数 {_m.get('块数')} != 索引里的 {_kbn}")
                if _m.get("上限token") != config.KB_MAX_TOKENS:
                    _drift.append(f"建库上限 {_m.get('上限token')} != "
                                  f"config.KB_MAX_TOKENS={config.KB_MAX_TOKENS}")
                if _m.get("编码模型") != config.RAG_ENCODER:
                    _drift.append(f"建库模型 {_m.get('编码模型')} != "
                                  f"config.RAG_ENCODER={config.RAG_ENCODER}")
                if _drift:
                    add(FAIL, "索引与建库台账不一致",
                        "；".join(_drift) + "（上限/模型不一致 = 有一半会被静默截断，"
                        "检索结果看着能出、其实搜不全）",
                        "重建一遍，别手工改 build_meta.json")
                else:
                    print(f"         建库台账：{_m.get('生成时间')}　"
                          f"来源 {len(_m.get('来源文件') or {})} 个文件　"
                          f"token 中位数 "
                          f"{(_m.get('token分布') or {}).get('median')}")
                    # 知识库更新了但索引没重建 —— 这是最容易被忽略的一种「过期」
                    _sd = _m.get("来源目录")
                    if _sd and os.path.isdir(_sd):
                        import hashlib as _hl
                        _stale = []
                        for _fn, _info in (_m.get("来源文件") or {}).items():
                            _p = os.path.join(_sd, _fn)
                            if not os.path.exists(_p):
                                _stale.append(f"{_fn}（已删除）")
                                continue
                            _h = _hl.sha256()
                            with open(_p, "rb") as f:
                                for _c in iter(lambda: f.read(1 << 20), b""):
                                    _h.update(_c)
                            if _h.hexdigest()[:16] != _info.get("sha256"):
                                _stale.append(f"{_fn}（内容变了）")
                        if _stale:
                            add(WARN, "知识库比索引新（索引过期）",
                                "这些来源文件与建库时不一致：" + "、".join(_stale),
                                "重跑 build_kb_index.py 重建（索引是可再生的，重建约十几分钟）")
                        else:
                            add(OK, f"索引与 {_sd} 逐字节一致（{len(_m.get('来源文件') or {})} "
                                    "个来源文件都没变）")
                    else:
                        print(f"         来源目录 {_sd} 不在本机，跳过「索引是否过期」比对"
                              "（换机器时正常 —— 索引里已经有全部内容）")
        else:
            add(INFO, "没有 build_meta.json（只有索引文件）",
                "检索照样能用（kb.py 不读它），只是没法核「索引是哪一版建的」",
                "重跑 build_kb_index.py 会补上")

# ============================================================
head("结论")
fails = [r for r in RESULTS if r[0] == FAIL]
warns = [r for r in RESULTS if r[0] == WARN]
print(f"致命 [FAIL] {len(fails)} 项    警告 [WARN] {len(warns)} 项")
for _, title, _, fix in fails:
    print(f"  [FAIL] {title}")
    if fix:
        print(f"         → {fix}")
if warns:
    print("  （警告项不阻塞启动，但知道一下：")
    for _, title, _, _ in warns:
        print(f"     [WARN] {title}")
    print("  ）")

# smoke_test.py 的**断言项数会变**，所以这里按当前开关算出期望项数，别写死一个数 ——
# 写死过两次（1424、2032），1 号 照着数会以为没跑对。**唯一的判据是「失败 0 项」**。
#
# 四个实测值（**2026-09-25 深夜「3b 情感分析 + 优秀回答范例铺到每题一条」后重跑**，
# 四档各跑一遍，失败全 0）：
#   KG=1 RAG=1 → 2869   ← 交付包模板的默认档（模板设 A11_RAG=1）
#   KG=1 RAG=0 → 2872
#   KG=0 RAG=1 → 2857
#   KG=0 RAG=0 → 2860
# 规律：KG 关掉少 11~12 项（KG 专属断言）；RAG 开着少 2~3 项。
# ⚠️ 这一版**同一天量了两次**，两个基准都写下来，免得后面对不上：
#    · 把「音量起伏 / 收尾」从「VAD 人声段」改成「3 秒**窗**」（`asr._loudness_windows`）
#      **之前**那一轮：2855 / 2852 / 2867 / 2864；
#    · 切窗补了 5 条断言之后（现在这版）：**2860 / 2857 / 2872 / 2869** ⇒ **逐格 +5**；
#    · 再往前（把优秀回答范例换成真范文那一波）是 **2813 / 2810 / 2825 / 2822**
#      ⇒ 相对它**逐格 +47**。
#    ⚠️ 中间那波**没加新断言、只改了两条**，所以它与它的上一版（能力提升路径
#    2822/2825/2811/2813）同格只差 **±1**，那 1 项就是下面这条 `random.choice` 抖动。
# ⚠️ 上一版（能力提升路径）是 +76 项，它的相等性做到了**节一级**：新增/改动四节 ——
#    `学习材料·纯函数` 19 / `学习材料端到端` 18 / `成长档案…纯聚合` 99 / `成长档案端到端` 47，
#    **四档逐个相同**（工具 `_tmp_g_split_probe.py` + `_tmp_g_split_diff.py`，
#    证据 `_tmp_g_split_{00,01,10,11}.json`）。**r5 这一波的断言散在多节**
#    （语音 / 学习材料 / `/model_answer`），只核到「四档同增 + 两两差值一致
#    （`00−01 = 10−11 = 3`、`00−10 = 01−11 = 12`）」，**没再逐节拆**。
# ⚠️ 更早那几版的说明（风格三档 +65、复盘清单 +66、成长档案 +119、
#    检索词那两版 +24~25 / +2、素材契约 +67）仍然成立，只是基准又向前挪了，那几批断言**全部保留**。
# ⚠️ 还可能再少 1~2 项：专项练习那节有两三条断言挂在「薄弱考点不只一个 / 有 domain」
#    的分支上，而出题用的是 `random.choice`（question_bank.py:18）—— 每趟抽到的题不同，
#    源场次的薄弱考点就不同。所以**看到数差 1~2 不必慌，看的是失败 0 项**。
if config.A11_KG:
    _smoke_n = 2869 if config.A11_RAG else 2872
else:
    _smoke_n = 2857 if config.A11_RAG else 2860
_SMOKE_EXPECT = ("smoke_test.py，期望：通过 %d 项左右（±2），失败 0 项"
                 "（A11_KG=%d / A11_RAG=%d；**项数随开关变，只认「失败 0 项」**）"
                 % (_smoke_n, config.A11_KG, config.A11_RAG))

print("\n下一步：")
if fails:
    print("  1. 按上面的 → 把 [FAIL] 全部修掉（改环境变量即可，不用改代码）")
    print("  2. 再跑一次本脚本，直到 [FAIL] 为 0")
    print("  3. 然后跑 %s" % _SMOKE_EXPECT)
else:
    print("  1. 跑 %s" % _SMOKE_EXPECT)
    print("     $env:LLM_MOCK=1; $env:RERANKER_MOCK=1; & $env:A11_PYTHON smoke_test.py")
    print("  2. 起服务：.\\run.ps1  （换机器**不用改它一行**）")
    if config.A11_RAG:
        print("  3. 看 http://127.0.0.1:%d/health 的 rag_ready / rag_error"
              % config.THIS_PORT)
        print("     —— **RAG 的最终判据是 /health，不是本脚本**："
              "get_rag() 在 A11_RAG=1 时即使预热失败也返回对象，"
              "就是为了让 /health 把错误报出来")
        print("     期望 rag_enabled=true, rag_ready=true, rag_error=null")
    else:
        print("  3. 看 http://127.0.0.1:%d/health —— 期望 bank_loaded=true、"
              "reranker_ok=true" % config.THIS_PORT)
    if config.A11_ASR and not config.A11_ASR_MOCK:
        print("  4. 验语音（2a/3b）：往 /asr 传一段真音频走一次（**第一次会现场加载模型，"
              "实测 1~4 秒、最长等 %g 秒**），再回看 /health 的 asr_ready —— "
              "这才是「语音在这台机器上真能用」的判据，本脚本只证明文件都在磁盘上"
              % config.A11_ASR_WAIT_SEC)
    elif config.A11_ASR_MOCK:
        print("  4. ⚠️ 现在开着 A11_ASR_MOCK=1：/asr 不加载模型、回固定转写 —— "
              "验收/演示前务必清掉它再重启")
print("\n完整搬迁清单见 交付说明-后端.md 的「换机器部署清单」一节。")
print("本脚本全程只读：没有写文件、没有建目录、没有加载模型、没有打印 key 的值。")

sys.exit(1 if fails else 0)
