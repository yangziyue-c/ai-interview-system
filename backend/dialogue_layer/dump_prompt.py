# -*- coding: utf-8 -*-
"""
把「模型每轮真正收到的完整 prompt」原样打出来 —— system + messages 全给。

调试用：改了 prompts.py 或 personas/ 之后跑一遍，肉眼确认模型看到的东西。
不需要 LLM、不需要联网、不需要 reranker（全是桩）。

每轮请求 = system + messages，两段都要看：
  system   = INTERVIEWER_SYSTEM(job, persona) + ROUND_CONTEXT(本轮题目/得分点/动作/素材)
             ＋ 深挖方向（**只在 L1/L2 轮**注入）+ RAG 参考
               （**代码默认关**：config.py:402 的 A11_RAG="0"；交付包模板
                环境变量.模板.ps1 设的是 =1，dot-source 后即开。本工具按代码默认跑，
                所以这里是空串；A11_RAG=1 时注入的是**题库派生索引**的
                「同岗位同难度的其他问法」，**不是知识库文档正文** —— 知识库正文走的是
                另外两条路（面试期的末尾旁白、4a 的资源推荐，见 kb.py）
  messages = transcript（考生与面试官**双向**历史）+ 本次回答
             ＋ 收尾轮额外临时追加的一条 CLOSE_DIRECTIVE（不写进 transcript）
             ＋ L1/L2 轮额外临时追加的一条知识库材料旁白（同样不写进 transcript）

⚠️ 深挖方向那段用的是**固定示例文字**（DEEPEN_SAMPLE），不是知识图谱的真实输出 ——
   本工具刻意不加载图谱（要几十 MB 和几秒）。门的开合是真的：L1/L2 有、close/degrade 没有。

输出写到文件（UTF-8 带 BOM，记事本直接打开不乱码）。

用法：
    & $python .dump_prompt.py                 # 默认 Web 岗 + Q0193
    $env:JOB="Java 后端开发工程师"; & $python .dump_prompt.py
"""
import os
import sys

os.environ.setdefault("HF_HOME", r"D:\A11-Data\hf_cache")
os.environ.setdefault("LLM_MOCK", "1")
os.environ.setdefault("RERANKER_MOCK", "1")

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import config                                       # noqa: E402
from app.core import question_bank as qb                     # noqa: E402
from app.core.prompts import (ACTION_DESC, CLOSE_DIRECTIVE, DEEPEN_BLOCK,
                              DEEPEN_BLOCK_EMPTY, HINT_BLOCK,
                              HINT_BLOCK_CLOSE, HINT_BLOCK_EMPTY,
                              INTERVIEWER_SYSTEM, KB_ASIDE, RAG_BLOCK_EMPTY,
                              RAG_KB_BLOCK_EMPTY,
                              ROUND_CONTEXT)                     # noqa: E402
from app.core.session import RoundRecord, hint_for, load_persona   # noqa: E402

JOB = os.environ.get("JOB", "Web 前端开发工程师")
QID = os.environ.get("QID", "WEB_FRONTEND-Q0193")
OUT = os.environ.get("OUT", os.path.join(_ROOT, "面试官完整prompt样例.txt"))

# 深挖方向的**示例**文字。真实运行时它来自知识图谱的共现图
# （kg.deepen_directions，见 README 11 节）；本工具刻意不加载图谱，
# 所以这里给一段固定示例，文件头会注明。
# ⚠️ 为什么必须填这个槽 —— 见 build_system 里的注释。
DEEPEN_SAMPLE = "线程池参数与拒绝策略、AQS 与锁升级、事件循环与微任务队列"

# 末尾旁白里那段知识库材料的**示例**（同上：本工具不检索，编一段固定文字）。
# 位置与真实运行时一致：L1／L2 轮、**消息列表的最后一条**、材料只出现在它自己的位置上。
# ⚠️ 真实运行时这段是**按本轮检索词**检索出来的（`kb.py`，赛题 6.2)b）——
#    检索词**默认就是考生刚说的那段话**（= 赛题字面）；另有保留的实验档
#    `A11_RAG_KB_QUERY_SRC=miss` 用**他没答到的得分点**（见 `kb.interview_query()`）。
#    出现与否取决于检索结果。这里恒给一段，是为了让读样例的人看见**形式**。
KB_ASIDE_SAMPLE = ("〔JavaGuide、并发编程〕AQS 内部用 volatile int state 表示同步状态，"
                   "独占模式靠 CAS 抢锁，抢不到就进 CLH 队列排队。")

LINE = "=" * 78
THIN = "-" * 78

# 考生与面试官的真实历史（修 #1：双向都进 transcript）
HIST = [
    {"role": "user", "content": "Promise 主要是能避免回调地狱，代码可读性更好，"
                                "也能用 .then 链把顺序异步逻辑串起来。"},
    {"role": "assistant", "content": "提到回调地狱了。那我往下抠一层："
                                     "then 链相比嵌套回调，到底解决了什么？"},
]
ANSWER = "它把嵌套结构改成扁平的链式结构，错误也能统一冒泡到 .catch。"


def build_record():
    """取一道真实题目，装成 round 记录（和出题时存进记录的结构一致）。"""
    r = qb.by_id(JOB, QID)
    if r is None:                      # 指定题号不在这个岗位，就随机抽一道
        r = qb.sample(JOB, {"easy"}, [])
    return RoundRecord(
        round_no=1, question_id=r.get(qb.F_ID, ""),
        stage="开场热身", stage_index=0,
        difficulty=r.get(qb.F_DIFFICULTY, ""),
        category=r.get(qb.F_CATEGORY, ""),
        data_stage=r.get(qb.F_STAGE, ""), priority=r.get(qb.F_PRIORITY, ""),
        est_minutes=r.get(qb.F_EST_MINUTES, 0) or 0,
        keywords=qb.split_lines(r.get(qb.F_KEYWORDS, "")),
        question=r.get(qb.F_QUESTION, ""),
        knowledge_points=qb.parse_knowledge_points(r.get(qb.F_KNOWLEDGE, "")),
        base_points=r.get(qb.F_BASE_POINTS, "") or "",
        adv_points=r.get(qb.F_ADV_POINTS, "") or "",
        raw=r,
    )


def build_system(rec, action):
    """与 session.answer_stream 完全同源。"""
    hint = hint_for(action, rec)
    if action == "close":
        block = HINT_BLOCK_CLOSE
    elif hint:
        block = HINT_BLOCK.safe_substitute(hint=hint)
    else:
        block = HINT_BLOCK_EMPTY

    # 深挖方向 / RAG 参考 —— **这两个槽必须每次都填**。
    #
    # ⚠️ 踩过一次：KG/RAG 那次给 ROUND_CONTEXT 加了 $deepen_block / $rag_block，
    #    session.py 填了，这个工具忘了填。用的是 safe_substitute，漏传**不抛异常**，
    #    占位符原样留在 prompt 里 —— 于是「模型真正收到的 prompt」这份样例里出现了
    #    字面的 "$deepen_block$rag_block"，而文件头还写着「一字未改」。
    #    所以下面除了填槽，末尾还有一道「不许剩 $ 占位符」的自检。
    if action in ("L1", "L2"):
        deepen_block = DEEPEN_BLOCK.safe_substitute(directions=DEEPEN_SAMPLE)
        # RAG 的**代码默认**是关（config.py:402），本工具要的是「默认部署会看到什么」，
        # 所以这里恒为空串。开了之后注入的是题库派生索引的「其他问法」，不是知识库正文。
        rag_block = RAG_BLOCK_EMPTY          # 见 README 11.4（口径是两段：代码默认 0 / 模板 1）
        # 知识库背景参考也一样恒空：它要按**本轮检索词**检索（赛题 6.2b）——
        # 默认是**考生刚说的那段话**（另有 `A11_RAG_KB_QUERY_SRC=miss` 的实验档用漏点，
        # 见 `kb.interview_query()`），而这个工具里既没有真实回答、也没有当轮的漏点
        # 可当检索词，编一段只会让样例失真。
        rag_kb_block = RAG_KB_BLOCK_EMPTY
    else:
        # close / degrade 一律空串。门控与 session.py 里那一处逐字一致 ——
        # 收尾轮递给面试官一份现成的提问素材，是把已知 0/10 的机制推向 10/10。
        deepen_block, rag_block = DEEPEN_BLOCK_EMPTY, RAG_BLOCK_EMPTY
        rag_kb_block = RAG_KB_BLOCK_EMPTY

    system = INTERVIEWER_SYSTEM.safe_substitute(
        job=JOB, persona=load_persona(JOB)) + ROUND_CONTEXT.safe_substitute(
        question=rec.question,
        base_points=qb.truncate(rec.base_points, 500) or "（无）",
        adv_points=qb.truncate(rec.adv_points, 500) or "（无）",
        action_desc=ACTION_DESC[action], hint_block=block,
        deepen_block=deepen_block, rag_block=rag_block,
        rag_kb_block=rag_kb_block)

    # 自检：模板槽位漏传时占位符会原样留在文中，只会静默地把垃圾喂给模型。
    # 宁可这里炸，也不要输出一份骗人的「真实 prompt」。
    return _no_slots(system)


def _no_slots(text: str) -> str:
    """
    槽位漏传自检（system 与**每一条 message** 都要过）。

    ⚠️ 2026-09-25 扩到 messages：末尾旁白（`KB_ASIDE`）是**唯一**一条进消息列表的
       模板渲染结果，而上面那道自检原来只看 `system` —— 漏传 `$kb_aside` 的话，
       字面占位符会**绕过自检**直接出现在这份"真实 prompt 样例"里。
    """
    if "$" in text:
        raise SystemExit(
            f"❌ 还有没填的槽位，prompt 不完整：\n"
            f"   {[t for t in text.split() if t.startswith('$')]}\n"
            f"   模板加了新槽位却忘了在这里传参，改 build_system() / build_messages()。")
    return text


def build_messages(action):
    """与 session.answer_stream 同源：先切片（这里是 HIST + 本次回答），**后追加**旁白。"""
    msgs = list(HIST) + [{"role": "user", "content": ANSWER}]
    if action == "close":
        msgs = msgs + [{"role": "user", "content": CLOSE_DIRECTIVE}]
    elif action in ("L1", "L2") and config.RAG_KB_ASIDE:
        # 知识库材料进末尾旁白（`A11_RAG_KB_ASIDE=1`，代码默认）。关掉它材料就回 system，
        # 这一条不再追加 —— 与 session.py 的分支一一对应。
        msgs = msgs + [{"role": "user", "content": KB_ASIDE.safe_substitute(
            kb_aside=KB_ASIDE_SAMPLE)}]
    for m in msgs:
        _no_slots(m["content"])
    return msgs


rec = build_record()
out = []
w = out.append

w(LINE)
w("模型每轮真正收到的完整 prompt —— 原样输出，一字未改")
w(LINE)
w(f"岗位：{JOB}")
w(f"题目：{QID}  「{rec.question}」")
w(f"难度：{rec.difficulty}   阶段：{rec.stage}   题型：{rec.category}")
w("")
w("一轮请求 = system + messages：")
w("  system   = 固定纪律 + 岗位人格 + 本轮上下文（题目/得分点/动作/素材）")
w("  messages = transcript（考生与面试官双向历史）+ 本次回答")
w("             ＋ 收尾轮额外临时追加 1 条收尾旁白（只发这一次，不写进 transcript）")
w("             ＋ L1/L2 轮额外临时追加 1 条知识库材料旁白（同样只发这一次）")
w("")
w("下面 4 个样例用**同一道题、同一段历史**，只有「本轮动作」不同 ——")
w("这样能直接看出 ROUND_CONTEXT 那段是怎么随动作变的。")
w("")
w("另外注意【可拓展的关联方向】那一段：L1／L2 轮有，degrade／close 轮**没有**。")
w("这是刻意的门控（理由见 prompts.py 里 DEEPEN_BLOCK 上方）。本样例里的方向文字是")
w("固定示例，真实运行时来自知识图谱；RAG 那段按**代码默认**（config.py:402 = 关）算，所以始终为空。")
w("")
w("末尾那条知识库材料旁白（L1／L2 轮才有）是**示例**：真实运行时它按**本轮检索词**")
w("检索知识库得来（默认 = 考生刚说的那段话，A11_RAG_KB_QUERY_SRC=answer），命不命中、")
w("命中哪一段都由检索决定；本工具不检索，所以给一段固定文字，")
w("只用来展示**形式与位置**（消息列表的最后一条）。它的开关是 A11_RAG_KB_ASIDE。")
w("")

for i, action in enumerate(("L1", "L2", "degrade", "close"), 1):
    w("")
    w("#" * 78)
    w(f"#  样例 {i}／4   本轮动作 = {action}")
    w(f"#  {ACTION_DESC[action]}")
    w("#" * 78)
    w("")
    w(THIN)
    w(f"[system]  ← 这一段每次都不一样（随题目和动作变）")
    w(THIN)
    w(build_system(rec, action))
    w("")
    w(THIN)
    w(f"[messages]  ← 真实对话历史 + 本次回答"
      + ("（末尾多了 1 条收尾旁白）" if action == "close" else "")
      + ("（末尾多了 1 条知识库材料旁白）"
         if action in ("L1", "L2") and config.RAG_KB_ASIDE else ""))
    w(THIN)
    for j, m in enumerate(build_messages(action)):
        head = f"[{j}] {m['role']:<9}"
        body = m["content"]
        w(head + body)
        if m["content"] == CLOSE_DIRECTIVE:
            w("      ↑↑ 这条是收尾轮临时拼进去的，只发这一次请求，")
            w("         不写进 transcript，下一轮就不在了")
        elif "这不是考生说的话" in m["content"]:
            w("      ↑↑ 这条是 L1/L2 轮临时拼进去的**知识库材料旁白**（示例文字）：")
            w("         材料夹在前后两句指令中间；材料本身是示例，真实运行时按**本轮检索词**检索")
            w("         （默认 = 他没答到的得分点）。")
            w("         同样只发这一次请求，不写进 transcript。")
    w("")

text = "\n".join(out)
with open(OUT, "w", encoding="utf-8-sig") as f:
    f.write(text)

print(f"已写出：{OUT}")
print(f"共 {len(text)} 字符")
print()
print(text[:1500] + "\n…（余下见文件）")
