# -*- coding: utf-8 -*-
r"""
kb.py · 4a 用的**真知识库**检索（只读、只喂给「学习资源推荐」）
============================================================
`resources.py` 那套学习资源是**纯题库派生**的（数据来自 `gen_学习资源样例.py`，
只读主库 5 个 JSON + `all_records.pkl` + `kg_question_graph.pkl`）。
本模块把 `D:\A11-Data\ai-reference\` 那份约 27 MB 真知识库（16 个开源仓库 /
2,524 个来源文件清洗合并而成）建成向量索引，按**考点名**检索，
结果挂在 `raw.blindspots.recommendations[].kb_refs`。

索引由 `D:\A11-交付\build_kb_index.py` 生成，**不进交付包**（可再生资源）。
数据落盘格式见那个脚本的 docstring：`kb_records.pkl` + `kb_index.npz`。

⚠️ 四条铁律（改这个文件之前先读完）：

  1. **只读；时效性由调用方决定，不是结构上封死的。**
     ⚠️ **2026-09-24 修订**。原文是：「只读、只在交卷后生效。首次 `lookup()` 才懒加载；
     不在 import 时加载，也不在 `/next`、`/chat` 期间加载 —— 4a 只在 `/finish` 触发
     （`session.py:1669` 是唯一入口），所以「交卷前不泄题」是**结构上封住的**。」
     现在有**两个消费方、两个时机**：
       · **4a**（`/finish` 触发）—— 首次 `lookup()` 才懒加载，**允许自己加载**编码器；
       · **面试官**（每轮追问，`search_interview()`，赛题 2b）——**只借不载**，
         借不到就直接返回空列表，见 `_load_borrow_only()`。
         ⚠️ **2026-09-25 晚加过一档、当晚深夜又改回来**：那条通路的检索词**默认就是
         考生刚说的那段话**（= 赛题 6.2)b 的字面口径「根据**学生回答的关键词**」）；
         另有一档**保留的实验档** `config.RAG_KB_QUERY_SRC="miss"`：拿**他没答到的
         得分点**当检索词（材料**就是缺口本身**）。实测两档产出分不开（都 0 改善），
         所以按**赛题字面**选了默认档。理由与那轮对照的数字写在
         `config.RAG_KB_QUERY_SRC` 那段 —— **那段是唯一权威，别在别处复述结论**。
     ⚠️ 修订的代价**如实写下**：「交卷前不泄题」由此**从结构性保证降级为契约性保证**
     （prompt 块里明写「不要向考生透露」+ 冒烟断言扫标记串）。**保证强度确实变弱了**，
     别对外说成没变。降级的理由是收益（赛题 6.1)b 的「知识库作为 RAG 的基础」+
     6.2)b 的「根据学生回答的关键词智能追问」）大于风险 —— 知识库正文是
     **开源文档散文、不含得分点/示例话术**，与 `rag.py` 那类「别的题目文本+答题要点」
     不是一个量级的风险。
  2. **绝不参与出题、绝不参与评分。** 同 `rag.py:7-18` 铁律①②：它不改任何阈值、
     不参与 `question_bank.sample()`，取到的片段没有一条流进评分链路。
     ⚠️ 对**面试官**那条通路还多一条硬要求：**不得据此另出新题** ——
     知识库正文不在题库里，据此出的题那一轮没有主库得分点、**没法评分**。
     这条靠 prompt 块里的措辞 + 冒烟断言「面试官没被带出题库」守。
  3. **片段只在有命中时才出现**（`kb_refs` 键整个不出现），且**有硬上限**
     （`KB_TOP_N` 条 × `KB_SNIPPET_CHARS` 字）。索引不在 ⇒ **既有键一个字节都没变**
     （只多出 summary 里那四个 kb_* 状态键）—— 这是「新功能默认开」敢这么定的前提。
     ⚠️ **有命中时**会多改一处既有键：`reason` 尾巴加一句「另附 N 条知识库参考」
     （`resources.py` 里加的，刻意为之，别当成漏网之鱼）。
     岗位过滤的口径：metadata 的 `岗位` 是**空列表**记为**通用块，任何岗位都命中**
     （建库时映射表外的文件就是这种）；有值时按「岗位在里面」判。
  4. **失败即静默降级。** 加载/检索的任何异常都吞掉，置 `_failed` 闩，
     `error` 里留原文，经 `/health` 与 `blindspots.summary.kb_error` 如实报出；
     面试与报告照常（与 kg / rag / asr 同一条旁路纪律）。

⚠️ 与 `rag.py` **故意分成两个文件**，不是一个：
   · `rag.py` 的 `where` 过滤是按**题库 schema** 写的（`所属岗位`/`难度等级`/
     `对应层级`），且它的铁律把它钉在「面试官 prompt 的参考材料」这个语义上；
   · 本模块的 metadata 是**知识库 schema**（`岗位`/`来源仓库`/`来源路径`/`章节标题`），
     消费方是 4a 的推荐列表。
   两件事放一个文件，只会让两边互相迁就。

⚠️ **编码器优先借用 `rag.py` 那份**（同一个 `config.RAG_ENCODER`、同一个
   `max_seq_length`）：`A11_RAG=1` 时它已经在内存里躺着，借用进来**不额外占内存**；
   没得借（`A11_RAG=0`、或预热失败）才自己加载一份。见 `_acquire_encoder()`。
"""
import os
import pickle
import threading
import time
from typing import Optional

from app import config
from app.core.rag import free_mb          # 复用，不抄第二份（同 asr.py:42 的做法）
from app.logging_conf import get_logger

logger = get_logger(__name__)


# ============================================================
# 片段截断
# ============================================================
def snippet(text: str, limit: int) -> str:
    r"""
    正文 → 一段可直接给考生看的片段。超长时**尽量切在句末**，不拦腰砍。

    为什么不复用 `rag._snippet`：那个是「首行优先 + 按行用空格拼接」，
    针对的是题库里 `题目\n答题要点\n示例话术` 那种短行结构；知识库是成段的
    技术散文，按行拼空格会把段落结构和 markdown 列表全抹平。
    """
    s = (text or "").strip()
    if not s or limit <= 0:
        return ""
    if len(s) <= limit:
        return s
    head = s[:limit]
    # 在**后半段**找最后一个句末标点；找不到就硬切（也别切出半个词）
    cut = -1
    floor = limit * 6 // 10
    for i in range(len(head) - 1, floor - 1, -1):
        if head[i] in "。！？；!?;\n":
            cut = i
            break
    return (head[:cut + 1] if cut >= 0 else head).rstrip() + "…"


# ============================================================
# 索引
# ============================================================
class KbIndex:
    """知识库向量索引的只读包装。`usable` 是唯一判据；`error` 非空即「没得用」。"""

    def __init__(self):
        self._ready_ev = threading.Event()
        self._lock = threading.Lock()
        self._failed = False
        self.error = ""
        self.load_error = ""        # 索引文件本身的错（与编码器的错分开报）
        self.encoder = None
        self.borrowed = False       # 编码器是借来的还是自己加载的（诊断用）
        self.dir = config.KB_DIR
        self.n = 0
        self.dim = 0
        self._emb = None
        self._records: list = []
        self.warmup_sec: Optional[float] = None

    # ---------- 读索引文件 ----------
    def _read_index(self):
        """
        读 `kb_records.pkl` + `kb_index.npz`，并做一致性校验。

        ⚠️ 与 `memory_retriever.py` **故意不同的一处**：那边有
        `EXPECTED_N = 74011` 的硬断言（题库索引的条数是它自己的契约）；
        这里**不写死条数** —— 知识库会随来源更新而变，条数是**建库期的事实**，
        不是运行期契约。写死只会让「重建了一次索引」变成服务起不来。
        留下的只有**内部一致性**：三处行数必须相等，否则是半个索引。
        """
        import numpy as np

        # 读过就不读（幂等）。为面试期通路加的一道保险：它可能先读了索引、却没借到
        # 编码器，交卷后 `load()` 还会再进来一次 —— 那 80 MB 的盘不必重读。
        if self._emb is not None:
            return

        rec_path = os.path.join(self.dir, config.KB_RECORDS_PKL)
        npz_path = os.path.join(self.dir, config.KB_INDEX_NPZ)
        missing = [p for p in (rec_path, npz_path) if not os.path.exists(p)]
        if missing:
            # 报**两个**路径，不只报缺的那个 —— 「少一层目录」是最常见的错法
            raise FileNotFoundError(
                "索引文件不存在：" + "、".join(missing)
                + f"（整个目录 {self.dir} 应含 {config.KB_RECORDS_PKL} 与 "
                  f"{config.KB_INDEX_NPZ}；用 build_kb_index.py 生成）")

        with open(rec_path, "rb") as f:
            records = pickle.load(f)
        z = np.load(npz_path, allow_pickle=False)
        emb, ids = z["embeddings"], z["ids"]

        if not (len(records) == len(ids) == emb.shape[0]):
            raise ValueError(
                f"索引自相矛盾：records={len(records)} ids={len(ids)} "
                f"embeddings={emb.shape[0]} —— 两个文件不是同一次构建的，"
                f"重建一遍（build_kb_index.py）")
        # 归一化校验：检索用的是点积 = 余弦，前提是两边都已归一化。
        # 建库脚本用 normalize_embeddings=True，正常必然成立；这里兜住
        # 「手工换了索引 / 换了别的工具建」的情形 —— 不修的话相似度会静默失真。
        norms = np.linalg.norm(emb, axis=1)
        bad = int((np.abs(norms - 1.0) > 1e-3).sum())
        if bad:
            logger.warning("索引里有 %d/%d 条未归一化，已就地 L2 归一化"
                           "（检索按点积=余弦实现，不修会失真）", bad, len(norms))
            emb = emb / np.maximum(norms, 1e-12)[:, None]
        self._emb = np.asarray(emb, dtype="float32")
        self._records = records
        self.n, self.dim = int(emb.shape[0]), int(emb.shape[1])

    # ---------- 取编码器 ----------
    def _borrow_encoder(self):
        """
        **只借不载**：拿得到就返回编码器，拿不到返回 `None`。**绝不自己加载。**

        `A11_RAG=1` 且它已就绪时，那个编码器已经在内存里躺着（约 2.3 GB），
        借用进来**不额外占内存** —— 因为两者用的是同一个 `config.RAG_ENCODER`、
        同一个 `max_seq_length`（见 `config.KB_MAX_TOKENS` 那段），**就是一个东西**。

        面试期通路（`_load_borrow_only`）只用这一半；4a 通路（`_acquire_encoder`）
        借不到时会退到「自己加载」。
        """
        from app.core import rag as ragmod
        if not config.A11_RAG:
            return None
        try:
            r = ragmod.get_rag()
            if r is not None and r.usable:
                limit = getattr(r.encoder, "max_seq_length", None)
                if limit and limit != config.KB_MAX_TOKENS:
                    # 上限不一致 = 有一条链会被静默截断，宁可自己加载
                    logger.error("借来的编码器 max_seq_length=%s 与 KB_MAX_TOKENS=%d "
                                 "不一致，改为自行加载", limit, config.KB_MAX_TOKENS)
                    return None
                self.borrowed = True
                return r.encoder
        except Exception:                                       # noqa: BLE001
            logger.exception("借用 rag 编码器失败，改为自行加载")
        return None

    def _acquire_encoder(self):
        """
        **4a 通路**：优先借用，借不到再**自己加载一份**（进程内只加载一次）。

        面试期通路**不用这个** —— 它自己加载要 1.2 GB，而那是在面试进行中。
        见 `_load_borrow_only()`。
        """
        enc = self._borrow_encoder()
        if enc is not None:
            return enc

        avail = free_mb()
        if avail is not None and avail < config.RAG_MIN_FREE_MB:
            raise MemoryError(f"空闲内存 {avail}MB < 门槛 {config.RAG_MIN_FREE_MB}MB")
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(config.RAG_ENCODER)
        m.max_seq_length = config.KB_MAX_TOKENS       # ⚠️ 必须与建库时一致
        return m

    # ---------- 加载 ----------
    def load(self, encoder=None) -> None:
        """
        懒加载。**任何异常都必须吞掉**（照抄 `rag.py::warmup` 的理由）：
        失败后置 `_failed` 闩，本进程内永久降级，`/health` 报出原因，面试照常。
        幂等：重复调用直接返回。

        `encoder` 是**注入缝**：传了就用它，不传走 `_acquire_encoder()`。
        冒烟测试靠它塞一个假编码器，从而**不加载 2.3 GB 的真模型**也能验完整条链路
        （读取 / 岗位过滤 / 阈值 / 降级）。生产链路从不传它。
        """
        if self._ready_ev.is_set():
            return
        with self._lock:
            if self._ready_ev.is_set():
                return
            t0 = time.time()
            try:
                # ① 先读索引。**放在编码器之前**是刻意的：索引不存在是最常见的
                #    情形（可选件没装），这条路上一个字节的模型都不会加载 ——
                #    「默认开」的代价因此是零。
                self._read_index()
                # ② 再取编码器
                self.encoder = encoder if encoder is not None else self._acquire_encoder()
                self.warmup_sec = time.time() - t0
                logger.info("知识库检索就绪 n=%d dim=%d 编码器=%s 耗时 %.1fs",
                            self.n, self.dim,
                            "借用 rag" if self.borrowed else "自行加载",
                            self.warmup_sec)
            except Exception as e:                              # noqa: BLE001
                self._failed = True
                self.error = f"{type(e).__name__}: {e}"
                # 索引本身的错与编码器的错分开报：前者是「可选件没装 / 装错了」，
                # 后者是「模型不可用」。运维看一行就知道该修哪边。
                if self._emb is None:
                    self.load_error = self.error
                logger.error("知识库检索不可用，本进程内永久降级"
                             "（4a 退回「只有题库派生的资源」，面试与报告照常）：%s",
                             self.error)
            finally:
                self._ready_ev.set()

    @property
    def usable(self) -> bool:
        return (self._ready_ev.is_set() and not self._failed
                and self._emb is not None and self.encoder is not None)

    # ---------- 面试期通路（只借不载） ----------
    def _load_borrow_only(self) -> bool:
        """
        面试期专用加载：**只借编码器，绝不自己加载**。返回「现在能不能用」。

        ⚠️ 为什么单开一条路，而不是给 `load()` 加个参数 —— 关键在 **`_ready_ev` 那个闩**。
        `load()` 无论成败都会在 `finally` 里把它置上（`usable` 才有意义），而这里
        **故意不置**，两个原因：
          · 借不到编码器（`A11_RAG=0`）是**「这个档位下没有」，不是「坏了」** ——
            置 `_failed` 会让 `/health` 报出一个假故障；
          · 更要紧的是**交卷后 4a 还要用同一个对象**：`lookup()` 走 `load()`，而
            `load()` 第一行就是「闩已置 → 直接 return」。面试期要是把闩置上、编码器又
            没借到，4a 那条路就**永远加载不了编码器**了 —— 症状是「4a 以后都没有
            知识库参考」，**不报错、只是少东西**，极难发现。所以这里的纪律是：
            **面试期永不置闩、永不置 `_failed`（索引读不出来除外）**。
        索引读进来之后是**留着**的（`_emb`/`_records`），所以即使这次没借到编码器，
        那次读盘也不白费 —— `_read_index()` 自带「读过就不读」。
        """
        if self.usable:
            return True
        if self._failed:
            return False
        with self._lock:
            if self.usable:
                return True
            if self._failed:
                return False
            if self._emb is None:
                try:
                    self._read_index()
                except Exception as e:                          # noqa: BLE001
                    self._failed = True
                    self.error = f"{type(e).__name__}: {e}"
                    self.load_error = self.error
                    logger.error("知识库索引不可用（面试期通路，本轮不带背景参考）：%s",
                                 self.error)
                    return False
            enc = self._borrow_encoder()
            if enc is None:
                # 不置闩、不报错：这是「本次没有可借的编码器」。每轮都重试一次是廉价的
                # （`get_rag()` 只是取个单例引用），而且 `A11_RAG=1` 但预热尚未完成时，
                # 下一轮就可能借到了。
                return False
            self.encoder = enc
            return True

    # ---------- 检索 ----------
    def search(self, query: str, job: Optional[str] = None,
               n: Optional[int] = None, min_score: Optional[float] = None,
               snippet_chars: Optional[int] = None) -> list[dict]:
        r"""
        按 `query`（考点名）检索知识库片段。**这是 4a 那条路。**

        **未就绪时先 `load()` 一次**（这是 4a 懒加载的唯一触发点），仍然不可用就返回 []。
        与 `rag.search()` 有一处不同：**这里会等加载** —— 4a 在 `/finish` 里跑、
        用户已经在等整份报告了，多等几秒加载编码器可以接受；
        而 `/next` 那边绝不能等（那条铁律属于 rag.py）。

        `job` 过滤照 `ai-reference\README.md` 的「岗位与文件对应」表，**两条规则**：
          · metadata 的 `岗位` 里**有**这个岗位 → 命中；
          · metadata 的 `岗位` 是**空列表** → 视为**通用块，任何岗位都命中**
            （与建库脚本 metadata 那段的注释一致；那种块是「映射表外的文件」）。
        `job=None` / 空 = 不过滤（看全部）。

        `min_score` / `snippet_chars` 是给**第二个消费方（面试官）**留的缝：
        **不传 = 沿用 `config.KB_MIN_SCORE` / `config.KB_SNIPPET_CHARS`**，
        也就是 4a 的行为**逐字节不变**。面试期那条见 `search_interview()`。
        """
        if not config.A11_KB_REC:
            return []
        if not self._ready_ev.is_set():
            self.load()
        if not self.usable:
            return []
        return self._search(query, job, n, min_score, snippet_chars)

    def _search(self, query: Optional[str], job: Optional[str], n: Optional[int],
                min_score: Optional[float], snippet_chars: Optional[int]) -> list[dict]:
        """
        真正的检索实现。**开关与「能不能用」由调用方判**（两条通路的判法不同：
        4a 看 `usable`，面试期看 `_load_borrow_only()`）。
        """
        n = int(n or config.KB_TOP_N)
        # `None` = 用 4a 那个量出来的门槛；给了数就用给的数；
        # **`<=0` = 不设门槛**（面试期通路的默认，理由见 config 里 `RAG_KB_MIN_SCORE` 那段）
        threshold = config.KB_MIN_SCORE if min_score is None else float(min_score)
        limit = int(snippet_chars or config.KB_SNIPPET_CHARS)
        q = (query or "").strip()
        if not q or n <= 0:
            return []
        try:
            import numpy as np
            qv = self.encoder.encode([q], normalize_embeddings=True)[0]
            scores = self._emb @ np.asarray(qv, dtype="float32")
            order = np.argsort(-scores)
        except Exception:                                       # noqa: BLE001
            # 单次检索失败不该影响整份报告 —— 少一份参考材料而已
            logger.exception("知识库检索失败，本次不带知识库参考")
            return []

        out: list[dict] = []
        for i in order:
            i = int(i)
            score = float(scores[i])
            if threshold > 0 and score < threshold:
                break                       # 已按分数降序，后面只会更低
            meta = self._records[i].get("metadata") or {}
            jobs = meta.get("岗位") or []
            if job and jobs and job not in jobs:
                continue
            txt = snippet(self._records[i].get("document") or "", limit)
            if not txt:
                continue
            # 键名与建库脚本的 metadata 逐字对应（前端/报告要能一眼溯源）
            out.append({
                "kb_id": self._records[i].get("id", ""),
                "来源仓库": meta.get("来源仓库", ""),
                "来源路径": meta.get("来源路径", ""),
                "章节标题": meta.get("章节标题", ""),
                "片段": txt,
                "score": round(score, 4),
            })
            if len(out) >= n:
                break
        return out

    def search_interview(self, query: str,
                         job: Optional[str] = None) -> list[dict]:
        r"""
        **面试期通路**：按本轮**检索词**检索知识库（赛题 6.2)b「能根据学生回答的关键词
        进行智能追问」）。

        ⚠️ 检索词**默认是考生刚说的那段话**（= 赛题 6.2)b 的字面口径）；另有**保留的
        实验档** `config.RAG_KB_QUERY_SRC="miss"`：拿**他没答到的得分点**当检索词
        （拼装规则见 `query_from_misses()` / `interview_query()`）。**选档的理由只写在
        `config.RAG_KB_QUERY_SRC` 那段**，这里不复制结论。

        与 4a 那条（`search()`）**四处刻意的不同**：
          · **只借不载** —— 借不到编码器就返回 []，绝不自己加载（见 `_load_borrow_only()`）。
            代价如实写下：`A11_RAG=0` 时这条通路整体失效，而 4a **不受影响**
            （交卷后它照旧自己加载那份编码器，靠的是「面试期不置闩」那条纪律）。
          · **不设门槛**（`config.RAG_KB_MIN_SCORE` 默认 `0.0` = 无门槛）。那些门槛数
            是在**考点名**分布上标出来的（中位 8 个字），不能平移到「考生回答」这种
            成段散文上 —— 分布不是一回事。攒够数据再标定，见 config 那段。
          · **自己的条数/片段预算**（`RAG_KB_TOP_N` / `RAG_KB_SNIPPET_CHARS`）：
            进 prompt 的东西和进 raw 的东西分开算账。
          · **短 query 不检索**：`RAG_KB_MIN_CHARS` 以下直接返回 []（「不知道」当 query
            只会捞回噪声，而噪声进了 prompt 就是实打实的干扰）。`interview_query()`
            已经**提前**在拼装侧拦了一道，这里这道是给别的调用方留的。

        ⚠️ 调用方**还要自己确认** `action in ("L1","L2")` —— 门控在 `session.py` 里，
        理由写在 `prompts.py` 的 `DEEPEN_BLOCK` 上方（收尾轮/降级轮不注入任何素材）。
        """
        if not config.A11_RAG_KB:
            return []
        q = (query or "").strip()
        if len(q) < config.RAG_KB_MIN_CHARS:
            return []
        if not self._load_borrow_only():
            return []
        return self._search(q[:config.RAG_KB_QUERY_CHARS], job,
                            n=config.RAG_KB_TOP_N,
                            min_score=config.RAG_KB_MIN_SCORE,
                            snippet_chars=config.RAG_KB_SNIPPET_CHARS)


# ============================================================
# 单例
# ============================================================
_kb: Optional[KbIndex] = None
_kb_lock = threading.Lock()


def get_kb() -> Optional[KbIndex]:
    """
    取全局知识库索引。**两个开关都关**时才返回 None（那是配置，不是故障）。

    ⚠️ 判据是 `A11_KB_REC **或** A11_RAG_KB`，不是只看前者：两者是**独立的消费方**
    （4a / 面试官），共用同一份索引。只看 `A11_KB_REC` 会让
    「4a 关掉、面试官开着」这种合法配置静默失效。

    与 `get_rag()` 同一条：**不因为加载失败而返回 None** —— 失败原因要能被
    `/health` 报出来，所以对象留着，由 `usable` / `error` 表达状态。
    """
    global _kb
    if not (config.A11_KB_REC or config.A11_RAG_KB):
        return None
    if _kb is not None:
        return _kb
    with _kb_lock:
        if _kb is None:
            _kb = KbIndex()
        return _kb


def lookup(query: str, job: Optional[str] = None,
           n: Optional[int] = None) -> list[dict]:
    """便利函数：**绝不抛异常**，任何情况下都返回一个（可能是空的）列表。

    给 `resources.py` 用 —— 推荐链路是「旁路的旁路」，它挂了不该让整份报告拿不到。
    """
    if not config.A11_KB_REC:
        return []
    try:
        idx = get_kb()
        return idx.search(query, job, n) if idx is not None else []
    except Exception:                                           # noqa: BLE001
        logger.exception("知识库检索入口异常，本次不带知识库参考")
        return []


def lookup_interview(query: str, job: Optional[str] = None) -> list[dict]:
    """便利函数（**面试期通路**）：**绝不抛异常**，任何情况下都返回一个（可能是空的）列表。

    给 `session.py` 的追问链路用 —— 与 `lookup()` 同一条纪律：这是旁路的旁路，
    它挂了不该让面试本身出问题。

    ⚠️ `query` **由调用方拼好**：面试期默认传的是「他漏掉的得分点」而不是他的原话
    （`interview_query()`），所以这个入口**不再假设 query = 考生回答**。

    ⚠️ 它**不会**触发「自己加载编码器」（`A11_RAG=0` 时借不到就返回空），
    也**不会**因此影响交卷后 4a 的加载 —— 那两条约束的实现见 `_load_borrow_only()`，
    改那个函数前先读它的 docstring。
    """
    if not config.A11_RAG_KB:
        return []
    try:
        idx = get_kb()
        return idx.search_interview(query, job) if idx is not None else []
    except Exception:                                           # noqa: BLE001
        logger.exception("知识库面试期检索入口异常，本轮不带背景参考")
        return []


# ============================================================
# 检索词的拼装（**纯函数**，2026-09-25 晚加）
# ============================================================
# 为什么单独拎成模块级纯函数：`session.py` 与离线重放/预检脚本**必须共用同一条规则** ——
# 分析器那条「重放强校验」（证明手上的片段就是模型当时看到的那份）靠的就是这个：
# 各写一份的话，「重放对上了」只证明复制品一致，不证明服务当时用的是这条规则。
# 与 `snippet()` / `format_block()` 同类：不碰索引、不碰任何状态。
#
# 起因（**这是这一档的实验动机，不是默认行为**）：同题两臂证明**机制全通但产出 0 改善**，
# 当时认为根因是**检索词就是考生自己的回答** ⇒ 捞回的材料与他刚说的话同义反复（复印），
# 面试官要么照念、要么用不上。于是试了「换成**他没答到的得分点**」：材料本身就是缺口，
# 契约里「借它的具体度把追问问得更具体」这条既有许可会自动打在缺口上 ——
# 转向来自「检索到了什么」，不来自新权限。
# ⚠️ **这一档实测仍是 0 改善**（两臂 0.0842 / CI 跨 0），且事后查明面试官每轮本来就
# 拿着本题全部得分点（`ROUND_CONTEXT`），缺口信息是**冗余投喂** ⇒ 默认档回到了
# 考生原话（赛题 6.2)b 字面）。**函数保留、随时可切**。见 `config.RAG_KB_QUERY_SRC` 那段
# （选档理由、回退语义、adv 子预算都写在那里，这里不复制）。
def query_from_misses(base_miss: Optional[list] = None,
                      adv_miss: Optional[list] = None,
                      limit: Optional[int] = None) -> str:
    r"""
    漏掉的得分点条目 → 一条检索 query。**一条都拼不出来就返回空串。**

    规则（每一条都有冒烟断言守着）：
      · **base 在前、adv 在后**（基础没答上先补基础），按原顺序，不排序、不去重；
      · `；` 连接，**整条拼不切半条** —— 超预算就停。与 `format_block()` 同一条
        「超顶就停」的纪律，但**理由不同**：那里的半条片段进 prompt 比没有更坏，
        这里是**得分点是语义单元**，切一半交给编码器等于换了个话题（前半句与后半句的向量不一样）；
      · **首条自身就超限** ⇒ 只截它。宁可截一条，也不能拼出一条空 query；
      · **`adv` 有独立子预算**（`limit // 3`）：L1 轮（30~60 分）的 `adv_hit` 恒空
        ⇒ `adv_miss` = **全部进阶点**，不加限的话检索词会被「整道题的进阶答案」占掉三分之二，
        捞回本轮范围外的材料（契约只许「借具体度、不引入它的话题」）。检索词应当 **base 主导**。

    ⚠️ **不原地改入参**：那两个 list 是会话的历史快照（`rec.attempts[].base_misses` 与
       `raw` 里同源），被这个函数排序/截断掉的话，报告里的漏点与当轮实际就对不上了 ——
       而且是**静默**的。所以下面一律 `list(...)` 拷一份再动。
    """
    lim = int(config.RAG_KB_QUERY_CHARS if limit is None else limit)
    adv_lim = lim // 3
    picked: list[str] = []
    used = 0                       # **拼好之后的**总长（`；` 全算在内）

    def _take(seg: str) -> bool:
        r"""
        收下一条：按**拼完的真实长度**算，装不下就整条放弃（**不切半条**）。

        ⚠️ 2026-09-25 晚修：这里原来写的是 `used + len(seg) + 1 > lim`，而 `used`
           只累加**正文**字数 ⇒ 每多一条就少算一个 `；`。四条 99 字的漏点会被拼成
           **302 字**，`search_interview()` 再 `q[:RAG_KB_QUERY_CHARS]` 一截，
           最后那条得分点**被切掉尾巴** —— 正是本函数明令禁止的事，而且是**静默**的
           （只有 query 恰好落在 `(lim-(k-1), lim]` 这一小段区间才会触发，
           所以四组合冒烟里偶发、单跑必不现）。冒烟现在有边界长度枚举守着。
        """
        nonlocal used
        joined = used + 1 + len(seg) if picked else len(seg)
        if joined > lim:
            return False
        picked.append(seg)
        used = joined
        return True

    for p in list(base_miss or []):
        seg = " ".join(str(p or "").split())      # 换行与连续空白压成一个空格
        if not seg:
            continue
        if not picked and len(seg) > lim:
            picked.append(seg[:lim])              # 首条自身超顶：只截它，保证 query 非空
            used = lim
            break
        if not _take(seg):
            break

    adv_used = 0                                  # adv 只**补位**，吃自己的子预算
    for p in list(adv_miss or []):
        seg = " ".join(str(p or "").split())
        if not seg:
            continue
        if adv_used + len(seg) > adv_lim:
            break
        if not _take(seg):
            break
        adv_used += len(seg)

    return "；".join(picked)


def interview_query(answer: str,
                    base_miss: Optional[list] = None,
                    adv_miss: Optional[list] = None) -> tuple[str, str]:
    r"""
    本轮检索词 + **词源**（`src`）。`src ∈ {"miss", "answer", "answer_fallback"}`。

    返回**元组**而不是让调用方拿 query 去猜词源：回答恰好等于漏点拼接时，
    字符串比较会把它误判成 `miss` —— 而那正是对照实验里最不能出错的地方。

    ⚠️ **默认档走第一个分支**（`RAG_KB_QUERY_SRC != "miss"` ⇒ 原样返回考生回答，
    `src="answer"`）。下面的回退语义**只作用于保留的实验档**。

    ⚠️ 回退（`answer_fallback`，仅 `"miss"` 档）：漏点一条都拼不出来 = 他**全答到了**
    （含进阶点）。这时退回考生回答，**不是**为了「总得有材料」，而是为了让这一档两臂
    **逐字节相同** ⇒ 它只会**稀释**结论（这些轮的 Δ 恒 0），**不会引入混杂**。
    改成「干脆不检索」会让这些轮的两臂差掺进「**有没有材料**」这个无关变量 ——
    `session.py` 已经为「材料放哪」那个变体拒绝过一次同样的做法。
    改成「回退到 `base_points` 全文」更糟：那是**第三种处理**，Δ=0 的前提没了，结论没法归因。
    ✅ 一条算术（回退几乎只发生在「全答到了」）：`split_points()` 丢掉短于
    `MIN_POINT_CHARS`(=15) 的行，而漏点正是它的产物 ⇒ **单条漏点最短 15 字 >
    `RAG_KB_MIN_CHARS`(=12)** ⇒ 只要漏点列表非空就必然过闸。

    ⚠️ `src` 只进**服务日志**（元数据），绝不进 `raw`、绝不进 prompt。
    """
    if config.RAG_KB_QUERY_SRC != "miss":
        return (answer or ""), "answer"
    q = query_from_misses(base_miss, adv_miss)
    if len(q) >= config.RAG_KB_MIN_CHARS:
        return q, "miss"
    return (answer or ""), "answer_fallback"


def format_block(refs: list[dict], max_chars: Optional[int] = None) -> str:
    r"""
    检索结果 → prompt 里那段「知识库背景参考」。空列表返回**空串**。

    与 `rag.format_block()` 是**兄弟函数，不是重复实现** —— 两处刻意的不同：
      · **每条带来源仓库**。题库那块不写来源（检索时已经按岗位/层级筛过，出处是冗余的）；
        知识库片段来自 6 份不同的 md（JavaGuide / leetcode 之类），
        **「这条材料是谁说的」本身就是模型判断相关性的线索**，而且它得知道
        这些是外部参考资料、不是本题的得分点。
      · **单条先按 `RAG_KB_SNIPPET_CHARS` 切过**（在 `_search` 里做的），
        这里只管**整块的硬顶** `RAG_KB_BLOCK_MAX_CHARS`。

    空串这条与 `rag.format_block()` 同一条纪律：槽位里填「（没有参考片段）」
    这种无害话，`system` 就不再是「开关全关时逐字节不变」了（教训见 `prompts.py`）。
    **超顶就停，不截半条** —— 半条片段进 prompt 比没有更坏。
    """
    if not refs:
        return ""
    limit = int(config.RAG_KB_BLOCK_MAX_CHARS if max_chars is None else max_chars)
    lines: list[str] = []
    total = 0
    for i, r in enumerate(refs, 1):
        txt = (r.get("片段") or "").strip()
        if not txt:
            continue
        src = (r.get("来源仓库") or "").strip()
        head = (r.get("章节标题") or "").strip()
        tag = "、".join(x for x in (src, head) if x)
        line = f"{i}. {('〔' + tag + '〕') if tag else ''}{txt}"
        if total + len(line) > limit:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def kb_status() -> dict:
    """ `/health` 用。区分「关掉」「没装」「坏了」，理由同 kg_status() / rag_status()。

    `kb_ready=false` 且 `kb_error=""` 的含义是**「还没人用过它」**（懒加载，
    探活端点不主动加载一个 2.3 GB 的模型 —— 同 `asr_status()` 的约定）；
    `kb_error` 非空才是「坏了」。`kb_n` 只在就绪后才有值。
    """
    k = _kb
    return {
        "kb_enabled": config.A11_KB_REC,
        "kb_ready": bool(k is not None and k.usable),
        "kb_error": (k.error if k is not None else ""),
        "kb_n": (k.n if (k is not None and k.usable) else 0),
        "kb_dir": config.KB_DIR,
    }
