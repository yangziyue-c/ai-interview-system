# -*- coding: utf-8 -*-
r"""
build_kb_index.py · 给 4a「学习资源推荐」建一份**真知识库**向量索引
============================================================
为什么需要它：`app/core/resources.py` 的 4a 现在是**纯题库派生**的
（数据来自 `gen_学习资源样例.py`，只读主库 5 个 JSON + `all_records.pkl` +
`kg_question_graph.pkl`），`ai-reference\` 那约 27 MB 知识库文档在代码里**零引用**。
本脚本把那份知识库建成向量索引，运行时由 `app/core/kb.py` 只读地查，
挂进 `raw.blindspots.recommendations[].kb_refs`。

## 来源：**只索引 `ai-reference\`，不索引 `md_bundle\`**

`ai-reference\README.md` 开头第一段写明它就是 `md_bundle` 那 2,664 个原始 md 清洗合并后的产物。
⚠️ **写入的标记数是 2,524，不是 2,651**（2026-09-25 实测；2,651 是更早一次合并的数，
那份 README 原先没跟着改，已订正。旁证：`ai-feed-package.jsonl` 里 `source=knowledge`
的行数实测也是 2,524）。两个目录都索引 = 同一份内容**双份进候选**，白占一个 top-N 名额。

7 个文件里**只索引 6 个** —— `README.md` 是这份知识库自己的说明书，不是面试知识，
索引它只会让「知识库怎么建」这种问题污染检索结果。

## 切块：照那份 README「使用建议 › RAG 知识库」的两条建议，但**两处必须修正**

  ✅ 照抄：**按 `## 【来源】` 切**（一个原始文件 = 一个天然语义边界），
          块内再按 `###`/`####` 细分；来源（仓库名 + 相对路径）落进 metadata。
  ⚠️ 修正 1：README 建议 **500–1000 token** —— 这里**降到 ≤512**。
     理由：`rag.py:196` 把编码器设成 `encoder.max_seq_length = 512`，
     超出的部分会被 sentence-transformers **静默截断**。一个编码器要同时服务
     题库索引（`rag.py`）和本索引，就只能用同一个上限；用 1000 会得到
     「索引里存的是全文、检索时只编码前 512 token」这种查不全的错配。
  ⚠️ 修正 2：README 建议 overlap 50–100 token —— 这里**不做 overlap**
     （见 `OVERLAP_SENTENCES = 0` 那段注释）。
  ➕ 补充：块正文前面**拼上标题路径**再编码 —— 标题是这段内容最强的上下文。

token 数用**真 tokenizer** 数（不是按字符估算），打包时若单块超限会**报错退出**，
绝不静默截断。

## 噪声过滤

`ai-reference` 里确实混着仓库的工程文件（已确证
`## 【来源】system-design-primer/CONTRIBUTING.md`）。按文件名剔除
`CONTRIBUTING / LICENSE / CHANGELOG / CODE_OF_CONDUCT / SECURITY / .github/`。

## 输出（**原子写入**：先写 .tmp 目录，再逐个改名）

    D:\A11-Data\kb_index\
      kb_records.pkl   list[{"id","document","metadata"}]，metadata 四键：
                       岗位(list) / 来源仓库 / 来源路径 / 章节标题
      kb_index.npz     embeddings float32[N,1024]（已 L2 归一化） + ids
      build_meta.json  建库参数与统计（**最后写**：它存在就代表这次构建完整）
      _probe.json      探针检索结果（供人眼复核、供标定 KB_MIN_SCORE）

⚠️ 索引**不进任何交付包**：它 99.9 MB（实测 20,396 块 × 1024 维），且是可再生资源。
见 `交付说明-后端.md` §9.4。

⚠️ 本脚本**不 import 服务代码**（除 config 的几个常量），所以它**不会跟着 `app\`
   一起自动更新** —— 换机器时 `build_kb_index.py` 与 `app/core/kb.py` 的口径
   （切块上限 `HARD_LIMIT`、`KB_MAX_TOKENS`、编码模型）**必须一起换**，
   否则「建库时截断 512 / 检索时截断 384」这种错会**静默**发生（检索结果失真但不报错）。

用法（先设好 `A11_PYTHON` / `HF_HOME`）：

    & $env:A11_PYTHON build_kb_index.py                 # 全量建库 + 探针
    & $env:A11_PYTHON build_kb_index.py --probe-only    # 只跑探针（不重建）
    & $env:A11_PYTHON build_kb_index.py --dry-run 200   # 只切 200 块看切得对不对，不编码不写盘
"""
import argparse
import hashlib
import json
import os
import pickle
import re
import shutil
import sys
import time
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

# ---- 让 `app.config` 可导入 ------------------------------------------------
# 两种运行位置都要能跑：① 交付工作区（源码在 D:\Code\A11）
#                        ② 1 号 包根（脚本与 `app\` 并排，源码就是本目录）
_HERE = os.path.dirname(os.path.abspath(__file__))
_SOURCE_CANDIDATES = (_HERE, r"D:\Code\A11")
for _c in _SOURCE_CANDIDATES:
    if os.path.isdir(os.path.join(_c, "app")):
        if _c not in sys.path:
            sys.path.insert(0, _c)
        break
else:
    print("✗ 找不到 `app` 包（试过：%s）—— 请在源码或 1 号包根下运行"
          % "、".join(_SOURCE_CANDIDATES))
    sys.exit(2)

from app import config                                     # noqa: E402

# ============================================================
# 参数
# ============================================================
SRC_DIR = os.environ.get("A11_KB_SRC", r"D:\A11-Data\ai-reference")
OUT_DIR = config.KB_DIR

# 编码上限。硬上限与 `rag.py` 一致（同一个编码器，同一个 max_seq_length）
HARD_LIMIT = 512
# 打包预算。留 32 token 余量给特殊 token（`<s>` / `</s>`），保证打包后必然 ≤ 512。
PACK_BUDGET = HARD_LIMIT - 32
# 块内二次切分的下限：太短的块（一个标题 + 一行）不值得单独成块，合并到邻块
MIN_CHARS = 40
# ⚠️ 刻意**不做 overlap**（README 建议 50–100 token），与它不一致，理由：
#    本索引的块是**按标题边界**切的，本身就自包含；且块正文编码前已经拼了
#    标题路径，跨块那点上下文基本被它补回来了。而 overlap 会造出**近重复块**，
#    在 `KB_TOP_N=2` 这么窄的返回名额里，两条近似块同时命中 = 白扔一个名额。
#    要改回重叠就把这个数调成正整数（按句重叠）。
OVERLAP_SENTENCES = 0

# 工程文件过滤（`ai-reference` 里确实混着这些，已确证）
NOISE = re.compile(
    r"(^|/)(CONTRIBUTING|LICENSE|CHANGELOG|CODE_OF_CONDUCT|SECURITY|"
    r"PULL_REQUEST_TEMPLATE|ISSUE_TEMPLATE)[^/]*$|\.github/", re.I)


# ============================================================
# 岗位 ↔ 知识库文件
# ============================================================
# 逐字来自 `ai-reference\README.md` 「使用建议 › 岗位与文件对应」那张表，**方向反过来**
# （README 是「岗位 → 文件」，这里要的是「文件 → 岗位」）。
# 表里「系统架构 / 后端高级」对应本项目的岗位名 `系统设计工程师`（config.JOBS）。
#
# 值为 (主文件, [辅助文件…])。反向展开后，`common-interview-knowledge.md`
# 会出现在**每个**岗位的列表里 —— 这正是 README 的意图（通用 / 行为面人人都要看）。
#
# ⚠️ 运行时 `kb.py` 的过滤因此有**两条**规则（都实现过，别只留一条）：
#    ① metadata.岗位 里有这个岗位 → 命中（本表的常规情形）；
#    ② metadata.岗位 是**空列表** → **通用块，任何岗位都命中**。
#    ② 是为「映射表外的文件」留的（表里没有的文件拿到 `岗位=[]`）。若只留①，
#    那种块会变成**谁也搜不到**（每个岗位都被过滤掉）—— 比不过滤更坏。
#    当前 6 个文件全在表内，所以实测 `(未映射)=0`：② 这条规则现在**走不到**，
#    但它是给「以后往 ai-reference 里加第 7 个文件」准备的，不要删。
JOB_DOCS = {
    "Java 后端开发工程师": ("java-backend-knowledge.md",
                            ["algorithm-knowledge.md", "system-design-knowledge.md",
                             "common-interview-knowledge.md"]),
    "Web 前端开发工程师": ("web-frontend-knowledge.md",
                            ["algorithm-knowledge.md", "common-interview-knowledge.md"]),
    "算法工程师":         ("algorithm-knowledge.md",
                            ["system-design-knowledge.md", "common-interview-knowledge.md"]),
    "测试开发工程师":     ("test-dev-knowledge.md",
                            ["java-backend-knowledge.md", "common-interview-knowledge.md"]),
    "系统设计工程师":     ("system-design-knowledge.md",
                            ["java-backend-knowledge.md", "algorithm-knowledge.md",
                             "common-interview-knowledge.md"]),
}

# **刻意不索引** `README.md`：它是这份知识库自己的说明书，不是面试知识。
SKIP_FILES = {"readme.md"}


def _doc_jobs() -> dict:
    """文件 → 岗位列表。同时校验表里的文件名都真的存在、岗位名都是 config.JOBS 里的。"""
    out: dict[str, list] = {}
    for job, (main, aux) in JOB_DOCS.items():
        if job not in config.JOBS:
            raise SystemExit(f"✗ 岗位名 {job!r} 不在 config.JOBS 里：{list(config.JOBS)}")
        for f in [main, *aux]:
            out.setdefault(f, [])
            if job not in out[f]:
                out[f].append(job)
    # 岗位顺序固定，保证两次构建的 metadata 逐字节可比
    for f in out:
        out[f] = [j for j in config.JOBS if j in out[f]]
    return out


# ============================================================
# 切块
# ============================================================
_SRC_MARK = re.compile(r"^## 【来源】(.+?)\s*$", re.M)
_HEADING = re.compile(r"^(#{3,6})\s+(.*?)\s*$")


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _fence_marker(line: str) -> Optional[str]:
    """这一行是不是围栏（开或闭）？是就返回它的围栏字符（``` 或 ~~~），否则 None。"""
    m = _FENCE.match(line)
    return (m.group(1)[0] * 3) if m else None


def _split_lines(text: str):
    """
    行序列 → [(kind, payload)]，kind ∈ {"head", "text"}。

    **围栏代码块内的一切都是 text** —— 里面的 `### 注释` 是代码不是标题，
    按标题切会把一段代码拦腰砍断（`ai-reference` 实测 **16,352 对**围栏、未闭合 0，
    口径见 `README.md` 的「知识库文件一览」表注与「质量验收」一节，
    切块时不能把这个性质弄坏）。

    ⚠️ 判「是不是围栏」用的是**前缀**（```` ``` ```` / `~~~` 开头），
       **绝不能再要求「整行只有围栏字符」** —— 开围栏那行还带语言标签
       （```` ```js ````），加了这个条件就认不出它、反而把**闭**围栏当成开围栏，
       于是每段代码**之后**的正文都被当成围栏内，`###` 标题成片被吞掉、
       块碎成代码碎片（实测：不打包时块长中位数只有 20 token）。
       同理，只有围栏字符完全相同的开/闭才算一对（```` ``` ```` 不被 `~~~` 关掉）。
    """
    out: list[tuple[str, object]] = []
    in_fence: Optional[str] = None      # None = 不在围栏里；否则是当前围栏的字符
    for ln in text.split("\n"):
        marker = _fence_marker(ln)
        if in_fence is not None:
            out.append(("text", ln))            # 围栏内一律是正文
            if marker == in_fence:
                in_fence = None
            continue
        if marker is not None:
            in_fence = marker
            out.append(("text", ln))
            continue
        m = _HEADING.match(ln)
        if m:
            out.append(("head", (len(m.group(1)), m.group(2))))
        else:
            out.append(("text", ln))
    return out


def _body_only(text: str) -> str:
    """去掉标题行之后剩下的正文 —— 用来判「这块是不是只有标题、没有内容」。"""
    return "\n".join(ln for ln in text.split("\n")
                     if not _HEADING.match(ln)).strip()


def _blocks(body: str):
    """
    一段正文 → [(标题路径, 该标题下的文本)]，**标题行本身包含在文本里**。

    标题路径 = 从 `###` 到当前层的**全部**标题用 " / " 连起来（如
    "2. 并发编程 / 2.1 AQS"），它同时是 metadata 与**编码文本的前缀**。

    为什么标题行要留在文本里：打包会把几个相邻标题并进同一块，
    若把标题行抽走，拼出来的正文就只剩一堆没有小标题的段落，读起来是断的。
    """
    out: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []          # [(层级, 标题)]
    cur_path, buf = "", []

    def flush():
        if cur_path or any(x.strip() for x in buf):
            out.append((cur_path, "\n".join(buf).strip()))

    for kind, payload in _split_lines(body):
        if kind == "head":
            flush()
            level, title = payload
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_path = " / ".join(t for _, t in stack)
            buf = [f"{'#' * level} {title}"]      # 标题行留在正文里
        else:
            buf.append(payload)
    flush()
    return [(p, t) for p, t in out if t.strip()]


def _common_prefix(paths: list[str]) -> str:
    """几个标题路径的公共祖先（"A / B" + "A / C" → "A"）。全不同则返回 ""。"""
    parts = [p.split(" / ") for p in paths if p]
    if not parts:
        return ""
    out = []
    for i in range(min(len(x) for x in parts)):
        seg = parts[0][i]
        if all(x[i] == seg for x in parts):
            out.append(seg)
        else:
            break
    return " / ".join(out)


def _pack_blocks(blocks: list, n_tokens, budget: int, stats: dict) -> list[tuple[str, str]]:
    """
    [(标题路径, 文本)] → 若干大块：**把相邻的小块按预算并起来**。

    为什么必须跨标题打包：知识库里的 `###` 很细，一个标题下常常只有一两行
    （实测不打包时块长度中位数只有 20 token —— 那种块几乎没有语义可言，
    检索出来的东西对不上考点）。并到接近预算上限，块才有内容。

    单块本身就超预算的走 `_hard_split`（按行 → 按句），并记账。
    """
    out: list[tuple[str, str]] = []
    cur: list[str] = []
    cur_n = 0
    cur_paths: list[str] = []

    def flush():
        if cur:
            out.append((_common_prefix(cur_paths) or cur_paths[0],
                        "\n\n".join(cur)))

    for hpath, text in blocks:
        text = (text or "").strip()
        if not text:
            continue
        n = n_tokens(text)
        if n > budget:
            flush()
            cur, cur_n, cur_paths = [], 0, []
            pieces = _hard_split(text, n_tokens, budget)
            stats["硬切_源块"] += 1
            stats["硬切_结果块"] += len(pieces)
            out.extend((hpath, p) for p in pieces)
            continue
        if cur and cur_n + n > budget:
            flush()
            cur, cur_n, cur_paths = [], 0, []
        cur.append(text)
        cur_paths.append(hpath)
        cur_n += n
    flush()
    return out


def _hard_split(text: str, n_tokens, budget: int) -> list[str]:
    """
    单个段落本身就超预算时的最后手段：按行切，再按句切。
    仍然切不动（一行就超）就原样返回，交给调用方报错 —— **绝不截断**。
    已知局限（如实写下，不假装没有）：切点只认行与句子，**不认围栏** ——
    所以极端情况下（整整一段围栏自己就超预算）会把一段代码切成两截、
    两截各带一个不闭合的围栏。它只影响**可读性**，不影响召回：
    技术内容仍然落在索引里、仍然能被检索到，只是片段看起来断。
    真出现得多的话，收紧 PACK_BUDGET 或给本函数加围栏感知。
    """
    # ① 先切到「每一小块都 ≤ 预算」：整行达标就整行留，单行超预算再按句切。
    pieces: list[str] = []
    for line in text.split("\n"):
        if n_tokens(line) <= budget:
            pieces.append(line)
            continue
        cur = ""
        for s in re.split(r"(?<=[。！？；.!?;])", line):
            if cur and n_tokens(cur + s) > budget:
                pieces.append(cur)
                cur = s
            else:
                cur += s
        if cur:
            pieces.append(cur)

    # ② **再打包回预算**。⚠️ 少了这一步就会退化成「一行一块」：
    #    进来的 text 本身是超预算的大块（常常是一整节），只按行切会把
    #    它劈成几十上百个十几 token 的小片，检索时一个名额就被这种碎片占掉。
    #    实测忘掉这一步时，全库 72,499 块里绝大部分是这种碎片。
    out: list[str] = []
    cur = ""
    for p in pieces:
        if not p.strip():
            continue
        if cur and n_tokens(cur) + n_tokens(p) > budget:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur.strip():
        out.append(cur)
    return out


def build_chunks(n_tokens, limit: int = 0) -> tuple[list[dict], dict]:
    """读 `SRC_DIR` 下 6 个知识库文件 → chunk 列表 + 统计。"""
    doc_jobs = _doc_jobs()
    files = sorted(f for f in os.listdir(SRC_DIR)
                   if f.lower().endswith(".md") and f.lower() not in SKIP_FILES)
    if not files:
        raise SystemExit(f"✗ {SRC_DIR} 下没有 .md 文件")

    # 所有键**先建好**：`--dry-run` 会在文件循环中途 return，缺键会抛 KeyError
    stats = {"按文件": {}, "跳过_来源": 0, "跳过_空块": 0,
             "硬切_源块": 0, "硬切_结果块": 0, "去重丢弃": 0}
    chunks: list[dict] = []
    seen: set = set()
    dup = 0

    for fname in files:
        path = os.path.join(SRC_DIR, fname)
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        jobs = doc_jobs.get(fname, [])          # 表外的文件 → 岗位=[]（不参与任何岗位过滤）

        # 按 `## 【来源】` 切。`re.split` 带一个捕获组 → 结果形如
        # [前导, 来源1, 正文1, 来源2, 正文2, …]。第 0 段是文件头（标题 + 引言），
        # 留着当「无来源」段（它的 repo/rel 为空，仍然参与索引）。
        parts = _SRC_MARK.split(raw)
        sections = []
        if parts[0].strip():
            sections.append(("", parts[0]))
        for i in range(1, len(parts) - 1, 2):
            sections.append((parts[i].strip(), parts[i + 1]))

        per_file = 0
        for src, body in sections:
            if src:
                if NOISE.search(src):
                    stats["跳过_来源"] += 1
                    continue
                # `仓库/相对路径` → 来源仓库 + 来源路径
                repo, _, rel = src.partition("/")
            else:
                repo, rel = "", ""
            # 两级：① **跨标题**贪心打包到预算 → ② 打包后仍擦到硬上限的按行/句切。
            # ⚠️ 为什么必须跨标题打包，见 `_pack_blocks` 的 docstring
            #    （逐标题打包实测把块切到中位数 20 token）。
            staged: list[tuple[str, str]] = []
            for hpath, g in _pack_blocks(_blocks(body), n_tokens, PACK_BUDGET, stats):
                g = g.strip()
                if not g:
                    continue
                # `_pack_blocks` 按**正文**算预算，标题路径那一段没算进去；
                # 长标题 + 满预算正文会擦到上限。按余量再切一次。
                embed = f"{hpath}\n{g}".strip() if hpath else g
                if n_tokens(embed) <= HARD_LIMIT:
                    staged.append((hpath, g))
                    continue
                room = max(64, PACK_BUDGET - n_tokens(hpath))
                pieces = _hard_split(g, n_tokens, room)
                stats["硬切_源块"] += 1
                stats["硬切_结果块"] += len(pieces)
                staged.extend((hpath, p) for p in pieces)

            for hpath, piece in staged:
                piece = piece.strip()
                if not piece:
                    continue
                # 一个块只剩标题行（`### 参考` 这种）就是纯噪声：检索得到它，
                # 却给不出任何内容，白白占掉 KB_TOP_N 里的一个名额。
                if len(_body_only(piece)) < MIN_CHARS:
                    stats["跳过_空块"] += 1
                    continue
                embed_text = f"{hpath}\n{piece}".strip() if hpath else piece
                n = n_tokens(embed_text)
                if n > HARD_LIMIT:
                    # 走到这里说明 _hard_split 也没切开（单独一行就超 512 token）。
                    # **报错退出，不截断** —— 静默截断会让索引里存着一份
                    # 「看得见、搜不到」的尾巴，是查不出原因的那种坏。
                    raise SystemExit(
                        f"✗ 有块切不开：{fname} / {src} / {hpath} 计 {n} token "
                        f"> {HARD_LIMIT}。请调小 PACK_BUDGET 或加一条过滤规则。")
                key = (embed_text,)
                if key in seen:
                    dup += 1
                    continue
                seen.add(key)
                chunks.append({
                    "id": f"kb-{len(chunks):06d}",
                    "document": piece,
                    "metadata": {
                        "岗位": list(jobs),
                        "来源仓库": repo,
                        "来源路径": rel,
                        "章节标题": hpath,
                    },
                    "_file": fname,
                    "_embed": embed_text,
                })
                per_file += 1
                if limit and len(chunks) >= limit:
                    stats["按文件"][fname] = per_file
                    stats["截断"] = limit
                    return chunks, stats
        stats["按文件"][fname] = per_file

    stats["去重丢弃"] = dup
    return chunks, stats


# ============================================================
# 编码
# ============================================================
def encode(texts: list[str], log=print):
    """与 `rag.py` 完全同参：同一个模型、同一个 max_seq_length、同样 L2 归一化。

    返回 `(embeddings, model)` —— 把 model 交回调用方，让后面的探针**复用**它。
    bge-m3 fp32 约 2.3 GB，多加载一次纯属浪费（也避免瞬时双份内存）。
    """
    import numpy as np
    from sentence_transformers import SentenceTransformer

    log(f"  加载编码器 {config.RAG_ENCODER} …")
    t0 = time.time()
    model = SentenceTransformer(config.RAG_ENCODER)
    model.max_seq_length = HARD_LIMIT          # ⚠️ 与 rag.py:196 必须一致
    log(f"  编码器就绪 {time.time() - t0:.1f}s；开始编码 {len(texts):,} 块"
        f"（batch=32，CPU）…")
    t0 = time.time()
    arr = model.encode(texts, batch_size=32, normalize_embeddings=True,
                       show_progress_bar=True, convert_to_numpy=True)
    arr = np.asarray(arr, dtype="float32")
    log(f"  编码完成 {time.time() - t0:.1f}s，shape={arr.shape}")
    return arr, model


# ============================================================
# 探针
# ============================================================
# 手工写的探针（每个岗位两条 + 通用两条）。**刻意不读 `学习资源样例.json`** ——
# 那个文件含得分点与核心答案，而这个脚本是**要进 1 号包的**，不该依赖敏感文件；
# 常量探针还有额外好处：两次构建之间完全可比。
PROBES = [
    ("Java 后端开发工程师",  "JVM 内存模型与垃圾回收"),
    ("Java 后端开发工程师",  "synchronized 与 ReentrantLock 的区别"),
    ("Web 前端开发工程师",   "浏览器事件循环与宏任务微任务"),
    ("Web 前端开发工程师",   "前端性能优化首屏加载"),
    ("测试开发工程师",       "接口测试用例设计方法"),
    ("测试开发工程师",       "自动化测试框架选型"),
    ("算法工程师",           "动态规划解题思路"),
    ("算法工程师",           "二叉树遍历的非递归实现"),
    ("系统设计工程师",       "高并发系统限流方案"),
    ("系统设计工程师",       "缓存穿透与缓存雪崩"),
    ("",                     "自我介绍怎么讲"),
    ("",                     "项目难点如何回答"),
]


def run_probe(records, embeddings, ids, encode_fn, log=print):
    """探针检索：报告每个 query 的 top-3 与分数，供人眼复核 + 标定 KB_MIN_SCORE。"""
    import numpy as np
    log("\n" + "=" * 64)
    log("探针检索（人眼复核用；也是 KB_MIN_SCORE 的标定依据）")
    log("=" * 64)
    qv = encode_fn([q for _, q in PROBES])
    scores = qv @ embeddings.T                      # 两边都已归一化 → 点积即余弦

    out, top1 = [], []
    for (job, q), row in zip(PROBES, scores):
        order = np.argsort(-row)
        hits = []
        for i in order:
            meta = records[int(i)]["metadata"]
            if job and job not in (meta.get("岗位") or []):
                continue
            hits.append({
                "score": round(float(row[int(i)]), 4),
                "章节标题": meta.get("章节标题", ""),
                "来源仓库": meta.get("来源仓库", ""),
                "来源路径": meta.get("来源路径", ""),
                "岗位": meta.get("岗位") or [],
            })
            if len(hits) >= 3:
                break
        if hits:
            top1.append(hits[0]["score"])
        out.append({"岗位": job or "(通用)", "query": q, "hits": hits})
        log(f"\n[{job or '通用'}] {q}")
        for h in hits:
            log(f"    {h['score']:.4f}  {h['来源仓库']}/{h['来源路径']}"
                f"  —— {h['章节标题'][:60]}")

    if top1:
        st = {"top1_min": min(top1), "top1_median": sorted(top1)[len(top1) // 2],
              "top1_max": max(top1), "n": len(top1)}
        log(f"\ntop-1 分数：min={st['top1_min']:.4f}  "
            f"median={st['top1_median']:.4f}  max={st['top1_max']:.4f}")
        log("⚠️ **别拿这 12 条的分布去定 KB_MIN_SCORE**（也不要「低于 min 一档」）——")
        log("   它们是**手写的长句**，而生产里传进来的是**考点名**（实测中位 8 个字），")
        log("   短 query 的余弦天然偏低 ⇒ 拿长句标出来的门槛**偏松**、会放噪声进来。")
        log("   真实标定用的是**全部 1,349 个真实考点名**的 top-1 分布取 p10：")
        log("   `D:\\A11-Data\\kb_index\\_calib.json`（做法见 交付说明-后端.md §9.4）。")
        log("   2026-09-24 实测：真实分布 min=0.4356 / p10=0.5829 / median=0.6813，")
        log("   故 KB_MIN_SCORE=0.58。**换来源 / 换模型 / 改切块后必须重新标定。**")
    return out


# ============================================================
# main
# ============================================================
def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-only", action="store_true", help="只用现有索引跑探针")
    ap.add_argument("--dry-run", type=int, default=0, metavar="N",
                    help="只切前 N 块并打印统计，**不编码、不写盘**（验证切块用）")
    ap.add_argument("--keep-tmp", action="store_true", help="保留 .tmp 目录，便于排错")
    args = ap.parse_args()

    t_all = time.time()
    print("=" * 64)
    print("build_kb_index.py · 4a 知识库索引")
    print("=" * 64)
    print(f"来源目录 : {SRC_DIR}")
    print(f"输出目录 : {OUT_DIR}")
    print(f"编码模型 : {config.RAG_ENCODER}   上限 {HARD_LIMIT} token"
          f"（打包预算 {PACK_BUDGET}）")

    import numpy as np

    # 数 token 时难免对**整行**调 tokenizer（有些行很长），transformers 会警告
    # 「> 8192 会 indexing errors」。那条针对的是**送进模型**的序列；这里只是拿它
    # 数长度，随后必然切到 ≤512，所以在这个脚本里是**假警报**。压掉，免得日志里
    # 全是它、把真问题淹掉（只压这一个 logger，不动全局）。
    import logging as _logging
    _logging.getLogger("transformers.tokenization_utils_base").setLevel(_logging.ERROR)

    from transformers import AutoTokenizer
    print(f"\n加载 tokenizer（只读词表，不占模型内存）…")
    tok = AutoTokenizer.from_pretrained(config.RAG_ENCODER)

    def n_tokens(text: str) -> int:
        return len(tok(text, add_special_tokens=True, truncation=False)["input_ids"])

    if args.probe_only:
        rec_path = os.path.join(OUT_DIR, config.KB_RECORDS_PKL)
        npz_path = os.path.join(OUT_DIR, config.KB_INDEX_NPZ)
        print(f"只跑探针：读 {rec_path}")
        with open(rec_path, "rb") as f:
            records = pickle.load(f)
        z = np.load(npz_path, allow_pickle=False)
        embeddings, ids = z["embeddings"], z["ids"]

        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(config.RAG_ENCODER)
        model.max_seq_length = HARD_LIMIT
        probe = run_probe(records, embeddings, ids,
                          lambda qs: np.asarray(
                              model.encode(qs, batch_size=32,
                                           normalize_embeddings=True),
                              dtype="float32"))
        with open(os.path.join(OUT_DIR, "_probe.json"), "w", encoding="utf-8") as f:
            json.dump(probe, f, ensure_ascii=False, indent=2)
        print(f"\n探针结果已写 {os.path.join(OUT_DIR, '_probe.json')}")
        return 0

    # ---- 1. 切块 ----
    print("\n[1/4] 切块 …")
    t0 = time.time()
    chunks, stats = build_chunks(n_tokens, limit=args.dry_run)
    print(f"  {len(chunks):,} 块，耗时 {time.time() - t0:.1f}s")
    print(f"  按文件：")
    for f, n in stats["按文件"].items():
        print(f"    {f:<40} {n:>6,}")
    print(f"  跳过（工程文件）{stats['跳过_来源']}　空壳块 {stats['跳过_空块']}"
          f"　去重丢弃 {stats['去重丢弃']}　"
          f"超限硬切 {stats['硬切_源块']} → {stats['硬切_结果块']} 块")
    if not chunks:
        print("✗ 一块都没有，检查 SRC_DIR")
        return 1

    # 岗位分布（构建期就该看得见「有没有哪个岗位一条都没有」）
    print("  按岗位（块可属多个岗位）：")
    for j in list(config.JOBS) + [""]:
        n = sum(1 for c in chunks if j in (c["metadata"]["岗位"] or []))
        print(f"    {j or '(未映射)' :<24} {n:>6,}")

    # 编码长度分布
    ns = [n_tokens(c["_embed"]) for c in chunks]
    ns_sorted = sorted(ns)
    print(f"  编码长度 token：min={ns_sorted[0]}  median="
          f"{ns_sorted[len(ns_sorted) // 2]}  p90={ns_sorted[int(len(ns_sorted) * .9)]}  "
          f"max={ns_sorted[-1]}（上限 {HARD_LIMIT}）")

    if args.dry_run:
        print(f"\n--dry-run {args.dry_run}：只切块，下面抽 3 块看切得对不对")
        for c in chunks[:1] + chunks[len(chunks) // 2:len(chunks) // 2 + 1] + chunks[-1:]:
            print("\n" + "-" * 64)
            print(f"id={c['id']}  岗位={c['metadata']['岗位']}  "
                  f"来源={c['metadata']['来源仓库']}/{c['metadata']['来源路径']}")
            print(f"章节标题={c['metadata']['章节标题'][:80]}")
            print(f"token={n_tokens(c['_embed'])}  正文 {len(c['document'])} 字：")
            print(c["document"][:400])
        print("\n（dry-run 结束，未编码、未写盘）")
        return 0

    print("\n[2/4] 编码 …")

    # ---- 2. 编码 ----
    embeddings, model = encode([c["_embed"] for c in chunks])

    # ---- 3. 写盘（原子：先 .tmp，再逐个改名）----
    print("\n[3/4] 写盘 …")
    tmp_dir = OUT_DIR + ".tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)
    records = [{"id": c["id"], "document": c["document"],
                "metadata": c["metadata"]} for c in chunks]
    with open(os.path.join(tmp_dir, config.KB_RECORDS_PKL), "wb") as f:
        pickle.dump(records, f, protocol=4)
    np.savez_compressed(os.path.join(tmp_dir, config.KB_INDEX_NPZ),
                        embeddings=embeddings,
                        ids=np.asarray([c["id"] for c in chunks]))

    # 来源哈希：让「索引是哪一版知识库建的」可核
    src_hash = {f: {"sha256": _sha(os.path.join(SRC_DIR, f))[:16],
                    "字节": os.path.getsize(os.path.join(SRC_DIR, f))}
                for f in sorted(stats["按文件"])}
    meta = {
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "来源目录": SRC_DIR,
        "来源文件": src_hash,
        "编码模型": config.RAG_ENCODER,
        "上限token": HARD_LIMIT,
        "打包预算token": PACK_BUDGET,
        "重叠句数": OVERLAP_SENTENCES,
        "块数": len(chunks),
        "维度": int(embeddings.shape[1]),
        "token分布": {"min": ns_sorted[0], "median": ns_sorted[len(ns_sorted) // 2],
                      "p90": ns_sorted[int(len(ns_sorted) * .9)], "max": ns_sorted[-1]},
        "岗位块数": {j or "(未映射)":
                     sum(1 for c in chunks if j in (c["metadata"]["岗位"] or []))
                     for j in list(config.JOBS) + [""]},
        "切块口径": ("按 `## 【来源】` 切源文件 → 块内按 ###/#### 切成小块 → "
                     "**跨标题**贪心打包到预算上限（打包后仍超上限的按行/句再切）；"
                     "不做重叠"),
        "对齐说明": "上限与 rag.py 的 encoder.max_seq_length=512 一致，"
                    "所以同一个编码器可同时服务题库索引与本索引",
        "去重丢弃": stats["去重丢弃"],
        "跳过_工程文件": stats["跳过_来源"],
    }
    # 最后写：它存在 = 这次构建完整
    with open(os.path.join(tmp_dir, "build_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    os.makedirs(OUT_DIR, exist_ok=True)
    for name in (config.KB_RECORDS_PKL, config.KB_INDEX_NPZ, "build_meta.json"):
        dst = os.path.join(OUT_DIR, name)
        os.replace(os.path.join(tmp_dir, name), dst)
    if not args.keep_tmp:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    total = sum(os.path.getsize(os.path.join(OUT_DIR, n))
                for n in (config.KB_RECORDS_PKL, config.KB_INDEX_NPZ))
    print(f"  已写 {OUT_DIR}")
    print(f"    {config.KB_RECORDS_PKL:<20}"
          f"{os.path.getsize(os.path.join(OUT_DIR, config.KB_RECORDS_PKL)):>12,} 字节")
    print(f"    {config.KB_INDEX_NPZ:<20}"
          f"{os.path.getsize(os.path.join(OUT_DIR, config.KB_INDEX_NPZ)):>12,} 字节")
    print(f"    合计 {total / 1048576:.1f} MB")

    # ---- 4. 探针 ----
    print("\n[4/4] 探针 …")
    # 复用上面那个编码器实例（不再加载第二遍）
    probe = run_probe(records, embeddings, np.asarray([c["id"] for c in chunks]),
                      lambda qs: np.asarray(
                          model.encode(qs, batch_size=32, normalize_embeddings=True),
                          dtype="float32"))
    with open(os.path.join(OUT_DIR, "_probe.json"), "w", encoding="utf-8") as f:
        json.dump(probe, f, ensure_ascii=False, indent=2)

    print(f"\n完成，总耗时 {time.time() - t_all:.1f}s")
    print(f"索引：{OUT_DIR}")
    print("⚠️ 索引**不进交付包**（100+ MB 的可再生资源）。")
    print("   1 号 换机器时按 交付说明-后端.md §9.4 重建，或整目录拷 D:\\A11-Data\\kb_index。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
