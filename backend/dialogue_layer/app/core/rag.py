# -*- coding: utf-8 -*-
"""
rag.py · RAG 参考片段（只读，只喂给面试官）
============================================================
给面试官在追问时手上一份「同岗位、同难度、同知识点的其他问法 / 题目背景」。

⚠️ 三条铁律（改这个文件之前先读完）：

  1. **不参与选题**。出题仍然是 question_bank.sample() 的 random.choice，
     RAG 只往 prompt 里塞参考材料。它不是"更好的抽题器"。
  2. **不参与评分**。任何阈值（MATCH_THRESHOLD / LEVEL_L1_MIN / LEVEL_L2_MIN）
     都不因此改动 —— 这里取到的片段没有一条流进评分链路。
  3. **片段绝不进 raw**。raw 由 /finish 与 /result/{sid} 返回，**前端可见**，
     而这里取到的 document 含「答题要点 / 示例话术」。要文本就别要安全，
     二者只能选一 —— 所以 RagIndex.search() 的结果存在 RoundRecord.rag_refs
     上（repr=False、不序列化），只有白名单四键的 rag_meta 进 raw。

默认关闭，原因见 config.A11_RAG 的注释（内存放不下，不是保守）。
"""
import ctypes
import importlib.util
import os
import threading
import time
from typing import Optional

from app import config
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 片段里的这两个词可以当金丝雀：冒烟测试断言 /next、/finish、/result
# 的响应体里不含它们。
#
# 实测（不是猜的）：
#   「原题」层    6/6 条 document 都含这两个词（它就是 题目 + 答题要点 + 示例话术）
#   「语义变体」层 0/6 —— 它是问法改写，第 2、3 行是得分点摘录，但**不含**这两个词
# RAG_LAYERS 默认含「原题」，所以这个金丝雀守的是真正危险的那一层。
#
# ⚠️ 它是**次级**检查：唯一能把片段原文带出去的结构是 RoundRecord.rag_refs，
#    而那条路径由「to_raw() 不含 rag_refs」直接断言（smoke_test 的
#    rag_never_in_raw）。金丝雀只是防将来有人新开一条把 document 直接透传的路。
CANARY_WORDS = ("答题要点", "示例话术")


# ============================================================
# 内存预检
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


def free_mb() -> Optional[int]:
    """
    当前物理内存空闲量（MB）。取不到就返回 None —— 非 Windows 或调用失败时
    我们**跳过预检**而不是当成 0：把「测不出来」当成「内存不足」会让 RAG
    在能跑的机器上也永远起不来。
    """
    try:
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return int(st.ullAvailPhys // (1024 * 1024))
    except Exception:
        return None


# ============================================================
# 片段截断
# ============================================================
def _snippet(text: str, limit: int) -> str:
    """
    **首行优先**截断。

    为什么不直接 text[:limit]：实测 document 长度中位 182、均值 285，平铺截 150
    会拦腰砍在第二行中间，语义断掉。而 document 的第一行就是题目文本本身，
    是最有用的部分；首行优先还能**天然丢掉「示例话术」**（它在第 3 行之后）。
    """
    s = (text or "").strip()
    if not s or limit <= 0:
        return ""
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    if not lines:
        return ""
    out = lines[0]
    truncated = len(lines) > 1
    for ln in lines[1:]:
        if len(out) + 1 + len(ln) > limit:
            truncated = True
            break
        out += " " + ln
    if len(out) > limit:
        out = out[:limit].rstrip()
        truncated = True
    return out + ("…" if truncated else "")


def format_block(refs: list[dict]) -> str:
    """
    检索结果 → prompt 里的一段。空列表返回**空串**（不是一句提示句）。

    返回空串这一点是刻意的：ROUND_CONTEXT 里这个槽位一旦填进"（没有参考片段）"
    这种看似无害的话，system 就不再是「关掉开关时逐字节不变」了。
    HINT_BLOCK_EMPTY 的教训（prompts.py）就是一句无害的提示句和动作指令打架。
    """
    if not refs:
        return ""
    lines = []
    total = 0
    for i, r in enumerate(refs, 1):
        txt = (r.get("text") or "").strip()
        if not txt:
            continue
        line = f"{i}. {txt}"
        if total + len(line) > config.RAG_BLOCK_MAX_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


# ============================================================
# 检索索引
# ============================================================
class RagIndex:
    """包装第三方 memory_retriever + bge-m3 编码器，只读、只查。"""

    def __init__(self):
        self._ready_ev = threading.Event()
        self._lock = threading.Lock()
        self._failed = False
        self.error = ""
        self.retriever = None
        self.encoder = None
        self.model = config.RAG_ENCODER
        self.dtype = config.RAG_DTYPE
        self.warmup_sec = 0.0

    # ---------- 预热 ----------
    def _load_retriever_module(self):
        path = config.RAG_RETRIEVER_PY
        if not os.path.exists(path):
            raise FileNotFoundError(f"检索器模块不存在：{path}")
        spec = importlib.util.spec_from_file_location("a11_rag_memory_retriever", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法从该路径加载模块：{path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def warmup(self) -> None:
        """
        启动时在后台线程调用。**任何异常都必须吞掉** —— 见下面那段注释。
        幂等：重复调用直接返回。
        """
        if self._ready_ev.is_set():
            return
        with self._lock:
            if self._ready_ev.is_set():
                return
            t0 = time.time()
            try:
                # ① 内存预检 —— 放在加载任何东西之前
                avail = free_mb()
                if avail is not None and avail < config.RAG_MIN_FREE_MB:
                    # 与其加载到一半被系统 OOM 掉（那会连 reranker 一起带走），
                    # 不如在这里主动放弃，并如实上报原因。
                    raise MemoryError(
                        f"空闲内存 {avail}MB < 门槛 {config.RAG_MIN_FREE_MB}MB")
                logger.info("RAG 内存预检通过：空闲 %s MB（门槛 %d MB）",
                            avail if avail is not None else "未知",
                            config.RAG_MIN_FREE_MB)

                # ② 检索器（74011 条内存精确余弦）
                mod = self._load_retriever_module()
                self.retriever = mod.MemoryRetriever()

                # ③ 编码器
                from sentence_transformers import SentenceTransformer
                kw = {}
                if self.dtype == "fp16":
                    import torch
                    kw["model_kwargs"] = {"torch_dtype": torch.float16}
                self.encoder = SentenceTransformer(self.model, **kw)
                self.encoder.max_seq_length = 512     # 与建索引时一致，不能改

                self.warmup_sec = time.time() - t0
                logger.info("RAG 就绪 model=%s dtype=%s n=%d 耗时 %.1fs（空闲内存现为 %s MB）",
                            self.model, self.dtype, self.retriever.count(),
                            self.warmup_sec,
                            free_mb() if free_mb() is not None else "?")
            except Exception as e:
                # ⚠️ 必须是 except Exception，不能只抓 FileNotFoundError：
                #    memory_retriever 类内**没有任何降级** ——
                #      · 6 个候选路径全落空 → raise FileNotFoundError
                #      · 条数 != EXPECTED_N(74011) → raise ValueError
                #      · 反序列化失败 → 各种 pickle 异常
                #    少抓一种就是一次 500。失败后置 _failed 闩，本进程永久降级。
                self._failed = True
                self.error = f"{type(e).__name__}: {e}"
                logger.error("RAG 预热失败，本进程内永久降级（面试照常进行）：%s",
                             self.error)
            finally:
                self._ready_ev.set()

    @property
    def usable(self) -> bool:
        return (self._ready_ev.is_set() and not self._failed
                and self.retriever is not None and self.encoder is not None)

    # ---------- 检索 ----------
    def search(self, query: str, job: str, difficulty: str,
               exclude_id: Optional[str] = None, n: Optional[int] = None) -> list[dict]:
        """
        检索同岗位 / 同难度 / 指定层的参考片段。

        **未就绪时立刻返回 []，绝不阻塞** —— 这条是硬要求：模型加载要 10 秒，
        若在这里等，/next 会卡 10 秒，前端看起来就是服务挂了。
        第一次请求赶在预热完成之前是常态，不是异常。

        exclude_id 用来丢掉**自身命中**：拿题目原文去检索，top1 就是它自己
        （实测 dist 0.2537），自己参考自己没有意义。
        """
        if not self.usable:
            return []
        n = n or config.RAG_TOP_N
        try:
            qv = self.encoder.encode([query], normalize_embeddings=True)[0].tolist()
            where = {
                "所属岗位": job,
                "难度等级": difficulty,
                # 值是 list → memory_retriever 的 _where_matches 当成 $in 处理
                "对应层级": list(config.RAG_LAYERS),
            }
            # 多取一条，好在丢掉自身命中之后仍然凑得满 n 条
            res = self.retriever.query([qv], n_results=n + 1, where=where)
        except Exception:
            # 单轮检索失败不该影响这一轮面试 —— 少一份参考材料而已
            logger.exception("RAG 检索失败，本轮将不带参考片段")
            return []

        out: list[dict] = []
        for i, doc in enumerate(res.get("documents") or []):
            meta = (res.get("metadatas") or [{}])[i] or {}
            if exclude_id and str(meta.get("原题ID")) == str(exclude_id):
                continue
            txt = _snippet(doc, config.RAG_SNIPPET_CHARS)
            if not txt:
                continue
            out.append({
                "id": (res.get("ids") or [""])[i],
                "question_id": meta.get("原题ID"),
                "layer": meta.get("对应层级"),
                "distance": round(float((res.get("distances") or [0.0])[i]), 4),
                "text": txt,
            })
            if len(out) >= n:
                break
        return out


# ============================================================
# 单例（照抄 scoring.py:237-258 的双检锁）
# ============================================================
_rag: Optional[RagIndex] = None
_rag_lock = threading.Lock()


def get_rag() -> Optional[RagIndex]:
    """
    取全局 RAG 索引。A11_RAG=0 时返回 None（那是配置，不是故障）。

    与 get_kg() 不同：这里**不因为预热失败而返回 None** —— 失败原因要能被
    /health 报出来，所以对象留着，由 usable / error 表达状态。
    """
    global _rag
    if not config.A11_RAG:
        return None
    if _rag is not None:
        return _rag
    with _rag_lock:
        if _rag is None:
            _rag = RagIndex()
        return _rag


def rag_status() -> dict:
    """ /health 用。区分「关掉」与「失败」，理由同 kg_status()。"""
    r = _rag
    return {
        "rag_enabled": config.A11_RAG,
        "rag_ready": bool(r is not None and r.usable),
        "rag_error": (r.error if r is not None else ""),
        "rag_model": (f"{r.model}({r.dtype})" if r is not None else ""),
        "rag_free_mb": (free_mb() if r is not None else None),
    }
