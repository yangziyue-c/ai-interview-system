# -*- coding: utf-8 -*-
"""
smoke_test.py · 无头全流程冒烟测试
============================================================
跑通 /start → /next → /chat(SSE) → /finish → /result 全链路，并断言
「结构正确」与「一定能收敛」两件事。

默认**不联网、不加载真模型、不烧额度**：
    LLM_MOCK=1 + RERANKER_MOCK=1，用确定性桩替换 DeepSeek 与 reranker。
    所以它能在任何机器上秒级跑完，适合当作改完代码的回归。

用法：
    $env:LLM_MOCK=1; & $python smoke_test.py            # 进程内直连 ASGI（默认）
    & $python smoke_test.py --base-url http://127.0.0.1:8005   # 打真服务
       （这个模式连的是已启动的服务，跑的是真模型/真 key —— 会烧额度）

退出码：0 = 全部通过，1 = 有断言失败。
"""
import json
import os
import sys
import threading
import time
import traceback

# ⚠️ 必须在 import app.* 之前设好 —— config.py 是在导入时读环境变量的。
os.environ.setdefault("LLM_MOCK", "1")
os.environ.setdefault("RERANKER_MOCK", "1")
# RAG 默认关（见 config.A11_RAG）：它要 bge-m3 约 2.3GB，冒烟测试不该为了
# 跑结构断言去啃 2.3GB。**关掉不等于不测** —— RAG 那条链路全部改由纯函数
# 单测覆盖（format_block / _snippet / search 未就绪立刻返回）。
os.environ.setdefault("A11_RAG", "0")

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import config                                     # noqa: E402
from app.core import blindspot as BS                       # noqa: E402
from app.core import kg as KG                              # noqa: E402
from app.core import question_bank as qb                   # noqa: E402
from app.core import rag as RAG                            # noqa: E402
from app.core import scoring as S                          # noqa: E402
from app.core.kg import CoverageTracker, deepen_directions  # noqa: E402
from app.core.llm import MockLLM, get_llm                  # noqa: E402
from app.core.prompts import (CLOSE_DIRECTIVE, DEEPEN_BLOCK_EMPTY,
                              HINT_BLOCK_CLOSE, INTERVIEWER_SYSTEM,
                              RAG_BLOCK_EMPTY, ROUND_CONTEXT,
                              ROUND_SCORING)               # noqa: E402
from app.core.session import (AttemptRecord, RoundRecord,
                              load_persona)                # noqa: E402

# rag_meta 的白名单 —— 只有这四个键，**结构上不可能夹带片段原文**。
# 与 session.py 里那份字面量保持一致；两边同时改才算改对。
_RAG_META_KEYS = {"used", "hit_ids", "layers", "distances"}

# 只出现在 RAG「原题」层 document 里的字面量，可以当金丝雀。
_CANARY_WORDS = RAG.CANARY_WORDS
_SENTINEL = object()


def mock_llm():
    """
    只在"进程内 + 桩"这一种组合下返回桩实例。

    收尾轮的收尾旁白是直接拼进**消息列表**的，存在进程内存里 ——
    远程模式下请求发给了另一个进程，本地看不到，所以那几种情况跳过这些断言。
    """
    try:
        llm = get_llm()
    except Exception:
        return None
    return llm if isinstance(llm, MockLLM) else None


# 拿一次就够了：get_llm() 是单例，这里拿到的和 app 内部用的是同一个对象。
_LLM = mock_llm()

# ---------- 断言与计数 ----------
_PASS = 0
_FAIL: list[str] = []


def ok(cond, label, extra=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"    ✓ {label}")
    else:
        _FAIL.append(label)
        print(f"    ✗ {label}  {extra}")


def section(title):
    print(f"\n{title}")
    print("-" * 64)


# ============================================================
# 两种客户端适配器：进程内 TestClient / 远程 HTTP
# ============================================================
class LocalClient:
    """进程内直连 ASGI app —— 不起端口，测的是同一份代码。"""

    name = "进程内 TestClient"
    inproc = True

    def __init__(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._cm = TestClient(app)
        self.c = self._cm.__enter__()      # 触发 lifespan（题库预加载 + 预热）

    def close(self):
        self._cm.__exit__(None, None, None)

    def get(self, path):
        r = self.c.get(path)
        return r.status_code, _json(r)

    def post(self, path, payload):
        r = self.c.post(path, json=payload)
        return r.status_code, _json(r)

    def stream_post(self, path, payload):
        events = []
        with self.c.stream("POST", path, json=payload) as r:
            if r.status_code != 200:
                return r.status_code, events, r.read().decode("utf-8", "replace")
            for line in r.iter_lines():
                ev = _parse_sse(line)
                if ev is not None:
                    events.append(ev)
        return 200, events, ""


class HttpAdapter:
    """打真服务。用 httpx（openai 的依赖，一定装了）。"""

    name = "远程 HTTP"
    inproc = False

    def __init__(self, base):
        import httpx
        self.base = base.rstrip("/")
        self.c = httpx.Client(timeout=180.0)

    def close(self):
        self.c.close()

    def get(self, path):
        r = self.c.get(self.base + path)
        return r.status_code, _json(r)

    def post(self, path, payload):
        r = self.c.post(self.base + path, json=payload)
        return r.status_code, _json(r)

    def stream_post(self, path, payload):
        events = []
        with self.c.stream("POST", self.base + path, json=payload) as r:
            if r.status_code != 200:
                return r.status_code, events, r.read().decode("utf-8", "replace")
            for line in r.iter_lines():
                ev = _parse_sse(line)
                if ev is not None:
                    events.append(ev)
        return 200, events, ""


def _parse_sse(line: str):
    line = (line or "").strip()
    if not line.startswith("data:"):
        return None
    try:
        return json.loads(line[5:].strip())
    except Exception:
        return None


def _json(r):
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text[:500]}


# ============================================================
# 单场面试跑一遍
# ============================================================
def play(client, job: str, answer_maker, label: str, quiet: bool = False):
    """
    answer_maker(round_no, attempt_no) -> str
    返回 dict：finish 结果 + 过程统计。
    每一步都有硬上限，**跑不收敛就直接失败** —— 这正是原实现 degrade
    分支无限空转那类 bug 的回归测试。
    """
    if not quiet:
        section(f"▸ 场景：{label}（{job}）")

    stats = {"rounds": 0, "attempts": [], "chat_calls": 0, "actions": [],
             "questions": [], "tok_events": 0, "diffs": [], "stages": [],
             "close_turns": 0, "close_asked": 0}

    # ---- /health ----
    code, h = client.get("/health")
    ok(code == 200, "/health 返回 200", f"got {code}")
    ok(h.get("status") == "ok", "/health.status == ok", str(h)[:200])

    # ---- /start ----
    code, s = client.post("/start", {"job": job})
    ok(code == 200, "/start 返回 200", f"got {code} {str(s)[:200]}")
    sid = s.get("session_id")
    ok(bool(sid), "/start 返回 session_id")
    ok(isinstance(s.get("message"), str) and s["message"],
       "/start.message 是非空字符串（前端直接展示）")
    ok(s.get("job") == job, f"/start.job 回显正确 ({job})")

    # ---- 主循环：出题 → 回答 → 直到题问完 ----
    # 累积 /next 的响应体，最后一次性做金丝雀断言（见下方）
    nx_blobs: list[str] = []
    guard = 0
    HARD_LIMIT = config.TOTAL_QUESTIONS * (config.MAX_ATTEMPTS_PER_QUESTION + 2) + 20
    while True:
        guard += 1
        if guard > HARD_LIMIT:
            ok(False, f"主循环在 {HARD_LIMIT} 步内收敛（没有死循环）")
            break

        code, nx = client.post("/next", {"session_id": sid, "message": ""})
        if code != 200:
            ok(False, "/next 返回 200", f"got {code} {str(nx)[:200]}")
            break

        if nx.get("finished"):
            ok(True, f"/next 正常收尾（reason={nx.get('reason')}）")
            break

        rno = nx.get("q_index")
        nx_blobs.append(json.dumps(nx, ensure_ascii=False))
        stats["rounds"] = max(stats["rounds"], rno or 0)
        stats["questions"].append(nx.get("question_id"))
        stats["diffs"].append(nx.get("difficulty"))
        stats["stages"].append(nx.get("stage"))

        ok(isinstance(nx.get("question"), str) and nx["question"],
           f"第 {rno} 题有题目正文")
        ok(nx.get("stage"), f"第 {rno} 题有阶段标签：{nx.get('stage')}")
        ok(nx.get("difficulty") in {"easy", "medium", "hard"},
           f"第 {rno} 题难度合法：{nx.get('difficulty')}")
        ok(1 <= (nx.get("q_index") or 0) <= config.TOTAL_QUESTIONS,
           f"第 {rno} 题序号在 1..{config.TOTAL_QUESTIONS} 内")

        # 修 #2 的回归：阶段标签与题目难度必须同源。
        # 原实现先推进 stage_idx 再读阶段名，边界题的标签会错位一格 ——
        # 表现出来就是「深度压轴」的题拿到 easy 难度。
        want_diff = config.STAGE_RULES[
            min(nx.get("stage_index") or 0, len(config.STAGE_RULES) - 1)][2]
        ok(nx.get("difficulty") in want_diff,
           f"第 {rno} 题阶段「{nx.get('stage')}」与难度「{nx.get('difficulty')}」匹配"
           f"（该阶段应为 {sorted(want_diff)}）")
        # 修 #3 的顺带收益：出题响应里不该出现主库原始记录（含答案 key）
        ok("_raw" not in nx and "raw" not in nx,
           f"第 {rno} 题响应不泄漏题库原始记录（答案 key）")

        # 本题内部：回答 → 追问 → … 直到本轮结束
        attempts = 0
        while True:
            attempts += 1
            if attempts > config.MAX_ATTEMPTS_PER_QUESTION:
                ok(False, f"第 {rno} 题在 {config.MAX_ATTEMPTS_PER_QUESTION} 次回答内收尾",
                   f"实际已经答了 {attempts} 次还没结束 —— 不收敛")
                break

            msg = answer_maker(rno, attempts)
            code, events, raw = client.stream_post(
                "/chat", {"session_id": sid, "message": msg})
            stats["chat_calls"] += 1
            if code != 200:
                ok(False, f"第 {rno} 题 /chat 返回 200", f"got {code} {raw[:200]}")
                break

            errs = [e for e in events if e.get("type") == "error"]
            if errs:
                ok(False, f"第 {rno} 题 /chat 无 error 事件", str(errs[0])[:200])
                break

            toks = [e for e in events if e.get("type") == "token"]
            dones = [e for e in events if e.get("type") == "done"]
            stats["tok_events"] += len(toks)
            text = "".join(e.get("text", "") for e in toks)

            ok(bool(toks), f"第 {rno} 题第 {attempts} 答：收到 token 事件（{len(toks)} 个）")
            ok(bool(text.strip()), f"第 {rno} 题第 {attempts} 答：面试官有实际回复")
            ok(len(dones) >= 1, f"第 {rno} 题第 {attempts} 答：收到 done 事件")
            if not dones:
                break

            d = dones[-1]
            ok(isinstance(d.get("follow_up"), bool),
               f"第 {rno} 题第 {attempts} 答：done.follow_up 是布尔值")
            # 语义一致性：follow_up 与 round_finished 必须互补（修 #4）
            ok(d.get("follow_up") != d.get("round_finished"),
               f"第 {rno} 题第 {attempts} 答：follow_up 与 round_finished 互补")
            ok(d.get("action") in {"L1", "L2", "L3", "degrade", "close"},
               f"第 {rno} 题第 {attempts} 答：action 合法（{d.get('action')}）")
            stats["actions"].append(d.get("action"))

            # ---- 判档字段**真的出得去**吗 ----
            # 守的是一个刚踩过的坑：字段在 session.round_status() 里加了，
            # 但 /chat 的 done 是**手搓 dict**，不铺开 round_status —— 于是加了
            # 等于没加，SSE 里一个都看不到，而所有单元测试照样全绿。
            # 桩模式下判档是关的，所以这里断言的是"键在、且值是关掉该有的样子"，
            # 不是判档结果本身（那由 judge_fusion() 的纯函数断言负责）。
            from app.core.session import band_of as _band_of
            _want_keys = ("reranker_band", "judge_band", "judge_ok", "judge_why",
                          "fuse_rule", "band_disagree")
            _miss = [k for k in _want_keys if k not in d]
            ok(not _miss, f"第 {rno} 题第 {attempts} 答：done 里 6 个判档字段齐",
               f"缺 {_miss}")
            ok(d.get("reranker_band") == _band_of(d.get("reranker_score") or 0.0),
               f"第 {rno} 题第 {attempts} 答：reranker_band 与覆盖率自洽"
               f"（{d.get('reranker_score')} → {d.get('reranker_band')}）")
            if config.LLM_MOCK:
                # 桩模式下判档整个不参与，融合必须恒等于 reranker 那一档 ——
                # 这就是"关掉后行为与加判档之前逐字节相同"的机器化断言。
                ok(d.get("judge_ok") is False,
                   f"第 {rno} 题第 {attempts} 答：桩模式下 judge_ok=false")
                ok(d.get("judge_band") is None,
                   f"第 {rno} 题第 {attempts} 答：桩模式下 judge_band 为 null"
                   "（null = 没判出来，不是判成降级）")
                ok(d.get("fuse_rule") == "reranker_only",
                   f"第 {rno} 题第 {attempts} 答：桩模式下 fuse_rule=reranker_only")
                ok(d.get("band_disagree") is False,
                   f"第 {rno} 题第 {attempts} 答：桩模式下 band_disagree=false")

            # ---- 收尾轮的接线检查（修：收尾后又追一句）----
            # 分两层，因为它们的确定性不一样：
            #   · 「接线」= 收尾旁白**只**在 close 轮传下去。消息列表只有进程内 + 桩
            #     才看得见，所以这层断言只在那一种组合下生效（结果是确定的）。
            #   · 「效果」= close 轮的回复里不含问句。真模型是随机的，所以只统计、
            #     不断言 —— 上线的信心来自实测的 0/10（见 CLOSE_DIRECTIVE 注释），
            #     拿它当回归门禁反而会在某次抖动上误报。
            if d.get("action") == "close":
                stats["close_turns"] += 1
                stats["close_asked"] += ("？" in text) or ("?" in text)

            if client.inproc and _LLM is not None:
                passed = any(m.get("content") == CLOSE_DIRECTIVE
                             for m in _LLM.last_messages)
                if d.get("action") == "close":
                    ok(passed, f"第 {rno} 题第 {attempts} 答：收尾轮传下了收尾旁白")
                else:
                    ok(not passed,
                       f"第 {rno} 题第 {attempts} 答：追问轮不带收尾旁白"
                       f"（action={d.get('action')}）")

                # ---- 深挖/RAG 块的门控（守 0/10 那条实测结论）----
                # 断言的是**输入**，不是模型输出：真模型是随机的，但"我们喂进去
                # 什么"是确定的。close 轮的实测事实是「system 是最弱的杠杆」——
                # 往里塞与收尾相反的内容，等于把一个已知 10/10 出问句的机制往
                # 更糟推。四条理由见 prompts.py 里 DEEPEN_BLOCK 上方那段注释。
                act = d.get("action")
                sys_txt = _LLM.last_system or ""
                if act in ("close", "degrade"):
                    ok("【可拓展的关联方向】" not in sys_txt
                       and "【同岗位参考片段】" not in sys_txt,
                       f"第 {rno} 题第 {attempts} 答：{act} 轮 system 不注入"
                       f"深挖方向 / RAG 片段")
                if act == "close":
                    ok(HINT_BLOCK_CLOSE in sys_txt,
                       f"第 {rno} 题第 {attempts} 答：close 轮仍用 HINT_BLOCK_CLOSE")
                if act in ("L1", "L2"):
                    # 这两个槽位必须**每次都被显式填**：safe_substitute 漏传时
                    # 占位符会原样留在 prompt 里，不报错。这是最容易静默回归的一处。
                    ok("$deepen_block" not in sys_txt and "$rag_block" not in sys_txt,
                       f"第 {rno} 题第 {attempts} 答：system 里没有未替换的槽位占位符")

            if not d.get("follow_up"):
                break

        stats["attempts"].append(attempts)
        if guard > HARD_LIMIT:
            break

    # ---- 阶段计划：3 easy → 5 medium → 2 hard，顺序不能乱 ----
    plan = []
    for name, n, diffs in config.STAGE_RULES:
        plan += [(name, sorted(diffs)[0])] * n
    got_plan = list(zip(stats["stages"], stats["diffs"]))
    ok(got_plan == plan[:len(got_plan)],
       f"阶段推进符合 {[(n, c) for n, c, _ in config.STAGE_RULES]}",
       f"实际 {got_plan}")
    ok(len(stats["questions"]) == len(set(stats["questions"])),
       "整场没有重复出同一道题（按题目ID 去重）")

    # ---- /finish ----
    code, fin = client.post("/finish", {"session_id": sid, "message": ""})
    ok(code == 200, "/finish 返回 200", f"got {code} {str(fin)[:300]}")

    # 顶层：旧字段原样（前端零改动的依据）
    for k in ("five_dim_avg", "total_score", "weights", "summary", "rounds"):
        ok(k in fin, f"/finish 顶层有旧字段 {k}")
    ok(isinstance(fin.get("weights"), str), "/finish.weights 是字符串（前端当字符串拼）")
    ok(isinstance(fin.get("summary"), str) and fin["summary"],
       "/finish.summary 是非空字符串")
    fda = fin.get("five_dim_avg") or {}
    ok(set(fda.keys()) <= set(config.DIMENSIONS),
       "/finish.five_dim_avg 的键都是五维名", str(list(fda.keys())))
    ok(set(fda.keys()) == set(config.DIMENSIONS),
       "/finish.five_dim_avg 五个维度齐全", str(list(fda.keys())))

    # raw：给 3 号的明细
    raw = fin.get("raw") or {}
    ok(bool(raw), "/finish 带 raw 明细")
    ok(isinstance(raw.get("rounds"), list) and len(raw["rounds"]) > 0,
       "raw.rounds 是非空列表")
    ok(isinstance(raw.get("weights"), dict), "raw.weights 是 dict（可程序化计算）")
    ok(isinstance(raw.get("asked_pids"), list), "raw.asked_pids 是列表")
    ok(isinstance(raw.get("scoring_failed_rounds"), list),
       "raw.scoring_failed_rounds 是列表（修 #5）")

    r0 = (raw.get("rounds") or [{}])[0]
    for k in ("round", "题目ID", "stage", "difficulty", "question",
              "knowledge_points", "exchanges", "five_dim", "comment", "errors"):
        ok(k in r0, f"raw.rounds[0] 有字段 {k}")
    for k in ("reranker_5", "tech_gap"):
        ok(k in r0, f"raw.rounds[0] 带一致性校验字段 {k}")
    ok(r0.get("tech_gap") is None or isinstance(r0["tech_gap"], float),
       "raw.rounds[0].tech_gap 是数值或 None（数据不足时不许填 0）",
       f"实际 {r0.get('tech_gap')!r}")
    if r0.get("reranker_5") is not None:
        ok(1.0 <= r0["reranker_5"] <= 5.0,
           "reranker_5 归一在 1-5 之间", f"实际 {r0['reranker_5']}")
    ex = (r0.get("exchanges") or [{}])[0]
    for k in ("answer", "reranker_score", "base_hit", "adv_hit", "follow_up_level",
              "base_miss", "adv_miss"):
        ok(k in ex, f"raw.rounds[0].exchanges[0] 有字段 {k}")
    ok(isinstance(ex.get("base_miss"), list) and isinstance(ex.get("adv_miss"), list),
       "exchanges[0] 的未命中点是列表（评分模型复核的依据）")

    # ---- 第一维的题型标签（行为素质题 = 岗位胜任力关联度）----
    # ⚠️ 要点是**键不改名**：five_dim 的第一维键永远是「技术水平」，dim1_label
    #    只说明那一列的分这轮在量什么 —— 所以 3 号 / 前端都不用分情况写。
    _labels = list(config.dim1_labels())
    for r in raw.get("rounds") or []:
        ok(r.get("dim1_label") in _labels,
           f"raw.rounds[].dim1_label 是两个合法值之一：{r.get('dim1_label')!r}")
        ok(r.get("dim1_label") == config.dim1_label(r.get("题型分类") or ""),
           "dim1_label 与本题型对得上（只有行为素质题换标签）",
           f"{r.get('题型分类')!r} → {r.get('dim1_label')!r}")
        if r.get("five_dim"):
            ok("技术水平" in r["five_dim"],
               "混型时 five_dim 的第一维键仍是「技术水平」（键不改名）")
    d1 = raw.get("dim1_labels") or {}
    ok(set(d1.keys()) == set(_labels),
       "raw.dim1_labels 固定两键、计数可能为 0（3 号的解析不用判空）", str(d1))
    ok(sum(d1.values()) == sum(1 for r in (raw.get("rounds") or []) if r.get("five_dim")),
       "raw.dim1_labels 的和 == 有分的轮数", f"{d1}")
    _counted: dict = {}
    for r in raw.get("rounds") or []:
        if r.get("five_dim"):
            _counted[r["dim1_label"]] = _counted.get(r["dim1_label"], 0) + 1
    ok(all(d1.get(k, 0) == v for k, v in _counted.items()),
       "raw.dim1_labels 与逐轮数出来的一致", f"{d1} vs {_counted}")
    # 这条混型的口径说明**只该在 raw 里** —— 一旦写进 notes，它会经
    # _write_evaluation 进 FINAL_SUMMARY 的【需要说明的情况】，污染给考生的评语。
    ok(not any("第一维" in n for n in (raw.get("notes") or [])),
       "混型说明不进 notes（notes 会流进给考生看的面试评价）")

    # ---- 权重与总分要能对上：手算一遍 ----
    tw = raw.get("weights") or {}
    usable = {d: v for d, v in fda.items() if v is not None}
    if usable:
        wsum = sum(tw[d] for d in usable)
        expect = round(sum(usable[d] * tw[d] for d in usable) / wsum, 2)
        got = fin.get("total_score")
        ok(got is not None and abs(got - expect) < 0.011,
           f"total_score 与 Σ(维度分×权重) 一致（期望 {expect}，实际 {got}）")
    else:
        ok(fin.get("total_score") is None and fin.get("partial") is True,
           "整场没有可用分数时 total_score=null 且 partial=true（不伪装成 0 分）")

    # ---- 修 #5：失败轮次必须点名，不能静默变 0 ----
    ok(fin.get("partial") is False or (raw.get("scoring_failed_rounds") or fin.get("notes")),
       "partial=true 时说明得清原因（failed_rounds / notes 非空）")

    # ---- 知识图谱 / RAG 新增的 raw 字段（纯加法，旧字段一个不动）----
    rounds_raw = raw.get("rounds") or []
    for r in rounds_raw:
        ok("deepen_directions" in r, f"raw.rounds[{r.get('round')}] 带 deepen_directions")
    ok(all(set((r.get("rag") or {}).keys()) == _RAG_META_KEYS for r in rounds_raw),
       "raw.rounds[].rag 四个键齐全（**关掉 RAG 时也是**，3 号不用分两种情况写）")
    ok(all(set((r.get("rag") or {}).keys()) <= _RAG_META_KEYS for r in rounds_raw),
       "raw.rounds[].rag 只有白名单四键（结构上不可能夹带片段原文）")
    ok(all("rag_refs" not in r for r in rounds_raw),
       "raw.rounds[] 不含 rag_refs 文本字段（它含答题要点/示例话术）")
    ok(isinstance(raw.get("coverage"), dict), "raw.coverage 是 dict")
    cov = raw.get("coverage") or {}
    ok(isinstance(cov.get("pick_levels"), dict)
       and set(cov["pick_levels"]) <= {"r0", "r1", "r2", "r3"},
       "raw.coverage.pick_levels 记下了用过的避重等级（调 θ 的唯一依据）",
       str(cov.get("pick_levels"))[:200])
    ok(cov.get("pick_levels") and sum(cov["pick_levels"].values()) == len(rounds_raw),
       "避重等级计数覆盖全部轮次（每轮必有一级）", str(cov.get("pick_levels"))[:200])
    ok(isinstance(cov.get("kp_seen"), int), "raw.coverage.kp_seen 是整数")
    ok("kg_error" in raw and "rag_error" in raw,
       "raw 带 kg_error / rag_error（区分「关掉」与「失败」）")
    ok(isinstance(raw.get("blindspots"), dict), "raw.blindspots 是 dict")
    bs = raw.get("blindspots") or {}
    bs_sm = bs.get("summary") or {}
    ok(isinstance(bs.get("domains"), list) and isinstance(bs.get("knowledge_points"), list),
       "blindspots 有 domains + knowledge_points 两张表（3 号直接 df 化）")
    ok(bs_sm.get("rounds_total") == len(rounds_raw),
       "blindspots.summary.rounds_total 与本场轮次一致（含没答题的轮）",
       f"actual {bs_sm.get('rounds_total')} vs {len(rounds_raw)}")
    ok(0.0 <= (bs_sm.get("domain_known") or 0.0) <= 1.0,
       "blindspots.summary.domain_known 在 0~1（如实上报覆盖率）")
    ok(all(e.get("hit") in (True, False, None)
           for e in bs.get("knowledge_points") or []),
       "每个知识点的 hit 是 true/false/null（null = 判不了，不是「没答上」）")
    ok(all("hit" in e and e.get("per_round") is not None
           for e in bs.get("knowledge_points") or []),
       "知识点明细带 hit 与 per_round")
    if config.A11_KG and KG.kg_status()["kg_ready"] and KG.get_kg() is not None:
        ok(bs_sm.get("kg_available") is True, "KG 就绪时 blindspots 标了 kg_available=true")
        kp_seen = {e["kp_id"] for e in bs.get("knowledge_points") or []}
        # 避重与盲区**必须共用同一个 kp_map** —— 否则同一个 kp 会出现
        # 「避重说考过、盲区说没考过」两种说法。两边都现算一遍来钉：
        #   ① 避重侧（CoverageTracker）：全部 kp_map 的知识点，一个不少
        #   ② 盲区侧：同集合 **减去软标签**（软标签不是知识点，只在盲区侧滤）
        # 这两条分开断言，是为了让「只在盲区侧滤」这个**有意的差异**变成
        # 机器可查的：将来若把过滤也搬到避重侧，①会立刻响，逼人显式改这里。
        _kg = KG.get_kg()
        all_kp, soft_kp = set(), set()
        for r in rounds_raw:
            m = _kg.kp_map(r["题目ID"], r["knowledge_points"])
            for kid, v in m.items():
                all_kp.add(kid)
                if BS._is_soft(v["title"]):
                    soft_kp.add(kid)
        ok(len(all_kp) == cov.get("kp_seen"),
           "避重的 kp_seen 仍按全部 kp_map 计（软标签不改变避重行为）",
           f"现算 {len(all_kp)} vs coverage {cov.get('kp_seen')}")
        ok(kp_seen == all_kp - soft_kp,
           "盲区的知识点集 = 避重记录的集合 − 软标签（同一个 kp_map，差异只有软标签）",
           f"blindspots {len(kp_seen)} vs 期望 {len(all_kp - soft_kp)}"
           f"（全量 {len(all_kp)}、软标签 {len(soft_kp)}）")
        ok(not (kp_seen & soft_kp) and not [e["title"] for e in bs["knowledge_points"]
                                            if e["title"] in BS.SOFT_TAGS],
           "盲区报告里一个软标签都没有（「职业素养」不该出现在薄弱领域里）",
           str(sorted({e["title"] for e in bs["knowledge_points"]} & BS.SOFT_TAGS)))

    # ---- 金丝雀：RAG 片段原文绝不进任何响应体 ----
    for api_name, body in (("/next", "\n".join(nx_blobs)), ("/finish", json.dumps(fin, ensure_ascii=False))):
        hit_words = [w for w in _CANARY_WORDS if w in body]
        ok(not hit_words, f"{api_name} 响应体不泄漏 RAG 片段原文", f"命中 {hit_words}")

    # ---- /result 与 /finish 一致 + /finish 幂等（修 #6）----
    code_r, res = client.get(f"/result/{sid}")
    ok(code_r == 200, f"/result/{{sid}} 返回 200", f"got {code_r}")
    ok(res.get("session_id") == sid, "/result 的 session_id 一致")
    for k in ("total_score", "summary", "rounds"):
        ok(res.get(k) == fin.get(k), f"/result.{k} 与 /finish 一致")
    ok(res.get("cached") is True, "/result 标记 cached=true")
    res_blob = json.dumps(res, ensure_ascii=False)
    hit_words = [w for w in _CANARY_WORDS if w in res_blob]
    ok(not hit_words, "/result 响应体不泄漏 RAG 片段原文", f"命中 {hit_words}")

    code_f2, fin2 = client.post("/finish", {"session_id": sid, "message": ""})
    ok(code_f2 == 200 and fin2.get("cached") is True,
       "/finish 幂等：第二次调用命中缓存、不重复评分")
    ok(fin2.get("total_score") == fin.get("total_score"),
       "/finish 两次结果一致")

    stats["finish"] = fin
    if not quiet:
        print(f"    · 实际问了 {stats['rounds']} 题，"
              f"每题回答次数 {stats['attempts']}，"
              f"/chat 调用 {stats['chat_calls']} 次")
        print(f"    · 阶段/难度 {list(zip(stats['stages'], stats['diffs']))}")
        print(f"    · action 序列 {stats['actions']}")
        # 收尾轮不该再追问。桩模式下这是确定的 0；打真服务时是实测值 ——
        # 真模型仍可能抖出一次问句，所以这里只报不判。
        print(f"    · 收尾轮 {stats['close_turns']} 次，其中又追问了 "
              f"{stats['close_asked']} 次")
    return stats


# ============================================================
# 错误路径
# ============================================================
def error_paths(client, job):
    section("▸ 错误路径")
    code, s = client.post("/start", {"job": "不存在的岗位"})
    ok(code == 422, "/start 未知岗位 → 422", f"got {code}")

    code, _ = client.post("/start", {})
    # job 有默认值，所以这是合法的
    ok(code == 200, "/start 不带 job → 用默认岗位（旧前端不传 job 也能跑）",
       f"got {code}")

    code, e = client.get("/result/deadbeef")
    ok(code == 404, "/result 未知会话 → 404", f"got {code}")
    ok(e.get("code") == "session_not_found", "404 错误体带 code=session_not_found",
       str(e)[:200])

    code, _ = client.post("/next", {"session_id": "deadbeef"})
    ok(code == 404, "/next 未知会话 → 404", f"got {code}")

    code, e = client.post("/chat", {"session_id": "deadbeef", "message": "x"})
    ok(code == 404, "/chat 未知会话 → 404", f"got {code}")

    code, _ = client.post("/chat", {"session_id": "deadbeef", "message": ""})
    ok(code == 422, "/chat 空回答 → 422", f"got {code}")

    # 建一场但一题不答就 /finish
    code, s = client.post("/start", {"job": job})
    sid = s.get("session_id")
    code, e = client.post("/finish", {"session_id": sid, "message": ""})
    ok(code == 409, "无任何问答就 /finish → 409", f"got {code}")
    code, e = client.get(f"/result/{sid}")
    ok(code == 409, "未结束就查 /result → 409", f"got {code}")


# ============================================================
# Prompt 语域（回归：面试官不能滑成老师）
# ============================================================
# 现象：面试官对考生说「这块基础还比较薄弱，列表和字典的遍历是你后面要补上的重点」。
# 根因是 prompt 里两种语域打架 —— 人设是课堂的（自称"陈老师"、称呼"同学"、
# "我们一起捋一捋"），纪律却是职场的（"不主动讲解知识点"）。模型在矛盾里滑向了老师，
# 开始给学生布置作业。实测（真模型，degrade/close 两种动作 × 2 个岗位 × 5 次）：
#     · 只改纪律措辞：20 次里 8 次带"回去看看/后面补一下/过一遍"这类作业句
#     · 纪律 + 人设一起去掉课堂语域：0 次（唯一一次命中是「不用急着回去看」，是拒绝布置）
# 真模型是随机的，没法在冒烟里断言它的输出；所以这里守**输入**：
# 人设文件里不许再出现课堂语域，system 里必须留着那两条禁令。
_BAD_PERSONA_REGISTER = ['称呼对方"同学"', "我们一起", "老师"]


def prompt_hygiene():
    section("▸ Prompt 语域（面试官不能滑成老师）")

    rendered = INTERVIEWER_SYSTEM.safe_substitute(job="X", persona="Y")
    ok("学习建议" in rendered,
       "system 明确禁止给学习建议（回去看看/后面补一下）")
    ok("整体基础" in rendered,
       "system 明确禁止对考生的整体基础下结论")

    for job in config.JOBS:
        text = load_persona(job)
        bad = [w for w in _BAD_PERSONA_REGISTER if w in text]
        ok(not bad, f"人设「{job}」不含课堂语域（{_BAD_PERSONA_REGISTER}）",
           f"实际出现：{bad}")
        ok(bool(text.strip()), f"人设「{job}」读得到（没退回兜底文案）")


# ============================================================
# reranker → LLM 的传导
# ============================================================
def _bare_round(**kw) -> RoundRecord:
    """造一条最小可用的 round 记录（不碰题库、不碰会话）。"""
    base = dict(round_no=1, question_id="T-1", stage="开场热身", stage_index=0,
                difficulty="easy", category="技术知识题", data_stage="",
                priority="", est_minutes=0, keywords=[], question="测试题",
                knowledge_points=[], base_points="基础点甲", adv_points="进阶点甲")
    base.update(kw)
    return RoundRecord(**base)


def _attempt(no: int, score: float, ok_: bool = True, hits=(), adv_hits=(),
             misses=()) -> AttemptRecord:
    return AttemptRecord(attempt_no=no, answer=f"第 {no} 次回答", reranker_score=score,
                         reranker_ok=ok_, base_hits=list(hits), adv_hits=list(adv_hits),
                         base_misses=list(misses), action="L2", hint="追问素材")


def scoring_bridge():
    """
    reranker → LLM 的传导（本轮改动）。

    守的是**输入**：明细要真的递进评分 Prompt，reranker 失败时不许拿默认分冒充。
    真模型是随机的，断言不了它的输出，所以断言我们喂进去的东西。
    """
    section("▸ reranker → LLM 传导（明细下传 / 失败不冒充 / 可复核）")

    rendered = ROUND_SCORING.safe_substitute(
        dim1_label=config.DIMENSIONS[0], dim1_rubric=config.DIM1_RUBRIC[config.DIMENSIONS[0]],
        question="Q", difficulty="easy", stage="开场热身",
        base_points="B", adv_points="A", qa_block="QA", reranker_note="N")
    ok("与后四维" in rendered,
       "评分 prompt 划清边界：客观分只锚第一维，不推后四维")
    ok("会出错" in rendered, "评分 prompt 承认客观匹配会出错（假阳性 / 假阴性）")
    ok("以你的判断为准" in rendered, "评分 prompt 要求复核，以模型自己的判断为准")
    ok("$reranker_score" not in rendered,
       "评分 prompt 里不再有裸分占位符 $reranker_score")

    # ---- reranker 失败：绝不拿默认分冒充 ----
    rec = _bare_round()
    rec.attempts.append(_attempt(1, 50.0, ok_=False))
    note = rec.reranker_note()
    ok("不可用" in note, "reranker 失败时摘要明说不可用", note)
    ok("50" not in note, "reranker 失败时摘要里不出现默认分 50", note)
    ok(rec.reranker_5 is None, "reranker 失败时归一值是 None，不是 0")
    ok(rec.tech_gap is None, "reranker 失败时一致性差值是 None，不是 0")
    ok("不可用" in rec.qa_block(), "qa_block 里也标出了 reranker 失败")

    # ---- 正常：明细与轨迹都要在 ----
    rec2 = _bare_round()
    rec2.attempts.append(_attempt(1, 20.0, hits=["基础点甲"], misses=["基础点乙"]))
    rec2.attempts.append(_attempt(2, 80.0, hits=["基础点甲", "基础点乙"],
                                  adv_hits=["进阶点甲"]))
    qa = rec2.qa_block()
    ok("基础点乙" in qa, "qa_block 列出了未命中的得分点（给模型翻案的机会）")
    ok("20" in qa and "80" in qa, "qa_block 里每次回答各带各的分（落差没被抹平）")
    ok("20 → 80" in rec2.reranker_note(), "摘要给出覆盖率轨迹",
       rec2.reranker_note())
    ok(rec2.reranker_5 == round(1 + 80 / 100 * 4, 2), "reranker_5 归一正确",
       f"实际 {rec2.reranker_5}")

    # ---- 一致性校验：只暴露信号，不改评分 ----
    rec2.five_dim = {d: 3.0 for d in config.DIMENSIONS}
    ok(rec2.tech_gap == 1.2, "tech_gap = |reranker 归一 - 技术水平|，只作信号",
       f"实际 {rec2.tech_gap}（reranker_5={rec2.reranker_5}，技术水平=3.0）")


# ============================================================
# 判档融合（LLM + reranker）
# ============================================================
class _CannedLLM:
    """判档用的假模型：chat_json 固定回一段 JSON，或者抛异常。"""

    def __init__(self, payload=None, boom=False):
        self.payload = payload
        self.boom = boom
        self.seen = []

    def chat_json(self, system, messages, temperature=None):
        self.seen.append((system, messages, temperature))
        if self.boom:
            raise RuntimeError("模拟判档调用失败")
        return self.payload


def judge_fusion():
    """
    判档的两半：**解析容错** 和 **融合规则**。

    为什么要单独测解析：踩过一次 —— 模型回 "DEGRADE"（大写），而上游刚把
    结果 .upper() 过，再拿它去 startswith 小写的 "degrade" 就永远为假。
    90 条真实回答里 30 条被判成"无法识别"，而那 30 条正好全是该降难度的
    弱考生 —— 判档在「该降难度」这条分支上完全失效，且**失败是静默的**
    （规矩是退回 reranker，不报错）。所以三个档的大写小写都要覆盖到。

    为什么要测融合规则：融合是唯一能"把好答案往下压"的地方 ——
    E agree 规则在两边不一致时取较浅的一档，实测把 11/30 的好答案降成了
    追基础（见 D:\\A11-Data\\A11-真实跑分\\judge_eval.json）。默认的
    llm_first 必须保证**不往下压**，这条要有断言守着。
    """
    section("▸ 判档融合（解析容错 / 融合规则 / 不往下压）")

    # ---- 一、DepthJudge 的解析 ----
    D = S.DepthJudge
    cases = [
        ({"depth": "L2"}, "L2"),
        ({"depth": "l2"}, "L2"),
        ({"depth": "L2 原理深挖"}, "L2"),
        ({"depth": "L1。"}, "L1"),
        # ↓ 这三条就是那个 bug：大写/小写/带尾巴的 degrade 都必须认
        ({"depth": "degrade"}, "degrade"),
        ({"depth": "DEGRADE"}, "degrade"),
        ({"depth": "Degrade，该给提示"}, "degrade"),
    ]
    for payload, want in cases:
        band, _, okk = D(_CannedLLM(payload)).judge("Q", "easy", "开场热身", "B", "A", "答")
        ok(okk and band == want, f"判档解析 {payload['depth']!r} → {want}",
           f"实际 ok={okk} band={band!r}")

    # 认不出来 / 调用炸了 → 必须如实说"没判出来"，不许伪装成一个档
    bad = [({"depth": "不知道"}, "回了没意义的词"),
           ({"depth": ""}, "回了空字符串"),
           ({}, "没回 depth 键"),
           (None, "回了空 JSON")]
    for payload, why in bad:
        band, _, okk = D(_CannedLLM(payload)).judge("Q", "easy", "开场热身", "B", "A", "答")
        ok(band is None and not okk, f"判档 {why} → 如实返回「没判出来」（不伪装成档位）",
           f"实际 ok={okk} band={band!r}")
    band, _, okk = D(_CannedLLM(boom=True)).judge("Q", "easy", "开场热身", "B", "A", "答")
    ok(band is None and not okk, "判档调用抛异常 → 如实返回「没判出来」（不吞成默认档）")

    # 判档用的是**低温度**：判档要的是稳，不是文采
    fake = _CannedLLM({"depth": "L1"})
    D(fake).judge("Q", "easy", "开场热身", "B", "A", "答")
    ok(fake.seen and fake.seen[0][2] == config.LLM_TEMPERATURE_SCORE,
       f"判档用评分档温度 {config.LLM_TEMPERATURE_SCORE}（不是对话的 "
       f"{config.LLM_TEMPERATURE}）", f"实际 {fake.seen and fake.seen[0][2]}")

    # ---- 二、覆盖率 → 档位 ----
    from app.core.session import (BAND_DEGRADE, BAND_L1, BAND_L2,
                                  band_of, decide_action, fuse_bands)
    ok(band_of(config.LEVEL_L2_MIN) == BAND_L2, "刚好到 L2 线 = L2（不是 L1）")
    ok(band_of(config.LEVEL_L2_MIN - 0.1) == BAND_L1, "差 0.1 分到 L2 线 = L1")
    ok(band_of(config.LEVEL_L1_MIN) == BAND_L1, "刚好到 L1 线 = L1（不是降难度）")
    ok(band_of(config.LEVEL_L1_MIN - 0.1) == BAND_DEGRADE, "差 0.1 分到 L1 线 = 降难度")
    ok(band_of(0.0) == BAND_DEGRADE, "0 分 = 降难度")

    # ---- 三、四种融合规则 ----
    ok(fuse_bands(BAND_DEGRADE, BAND_L2, True)[0] == BAND_L2,
       "llm_first：判档说 L2 就 L2（不被 reranker 的降难度拽下来）")
    ok(fuse_bands(BAND_L2, BAND_L1, True)[0] == BAND_L1,
       "llm_first：判档说 L1 就 L1")
    ok(fuse_bands(BAND_L2, BAND_L1, True)[1] == "llm_first",
       "llm_first：两边不一致时标注规则名，供 3 号统计")
    ok(fuse_bands(BAND_L2, BAND_L2, True)[1] == "agree", "两边一致时标注 agree")

    old_fuse = config.JUDGE_FUSE
    try:
        config.JUDGE_FUSE = "agree"
        ok(fuse_bands(BAND_DEGRADE, BAND_L2, True)[0] == BAND_DEGRADE,
           "agree：不一致时取较浅的一档（宁可多给一次引导）")
        config.JUDGE_FUSE = "deepest"
        ok(fuse_bands(BAND_DEGRADE, BAND_L2, True)[0] == BAND_L2,
           "deepest：不一致时取较深的一档")
        config.JUDGE_FUSE = "reranker"
        ok(fuse_bands(BAND_DEGRADE, BAND_L2, True)[0] == BAND_DEGRADE,
           "reranker：完全忽略判档（可一键退回改动前的行为）")
        # 大小写 / 前后空格不该改变行为
        config.JUDGE_FUSE = "  LLM_First "
        ok(fuse_bands(BAND_DEGRADE, BAND_L2, True)[0] == BAND_L2,
           "规则名大小写与空格不敏感（env 传进来的值不该炸）")
    finally:
        config.JUDGE_FUSE = old_fuse

    # ---- 四、判档没成功 → 任何规则都退回 reranker ----
    for rule in ("llm_first", "agree", "deepest", "reranker"):
        config.JUDGE_FUSE = rule
        try:
            got = fuse_bands(BAND_L1, None, False)
            ok(got == (BAND_L1, "reranker_only"),
               f"判档失败时 {rule} 也退回 reranker（没有第二意见只能听第一意见）",
               f"实际 {got}")
            got = fuse_bands(BAND_L1, "乱码档位", True)
            ok(got == (BAND_L1, "reranker_only"),
               f"判档回了个不认识的值时 {rule} 也退回 reranker", f"实际 {got}")
        finally:
            config.JUDGE_FUSE = old_fuse

    # ---- 五、桩模式下判档必须彻底关掉 ----
    # 这是「关掉后行为逐字节不变」的保证：桩模型回的不是可解析的 JSON，
    # 漏掉这条门会让整场动作决策全变，带 `if` 的那些断言成片地响。
    ok(config.LLM_MOCK, "冒烟测试跑在 LLM_MOCK=1 下（下面两条才有意义）")
    ok(S._make_judge(MockLLM()) is None, "桩模式下不建判档器（否则会改掉每次动作决策）")
    ok(S._make_judge(None) is None, "没接 llm 时不建判档器")
    _old_judge = config.A11_JUDGE
    try:
        config.A11_JUDGE = False
        ok(S._make_judge(_CannedLLM({"depth": "L1"})) is None,
           "A11_JUDGE=0 时判档整个关掉（可一键退回纯 reranker 判档）")
    finally:
        config.A11_JUDGE = _old_judge

    # ---- 六、动作决策：caps 仍然压得住 ----
    rec = _bare_round()
    ok(decide_action(BAND_L2, rec) == "L2", "档位 L2 → 动作 L2")
    ok(rec.follow_ups_used == 1, "决策同时记账：follow_ups_used +1（决策与计数不能分家）")
    rec.follow_ups_used = config.MAX_FOLLOW_UP
    ok(decide_action(BAND_L1, rec) == "close",
       f"追问用满 {config.MAX_FOLLOW_UP} 次 → close（终止性保证）")
    rec2 = _bare_round()
    rec2.degrade_used = config.MAX_DEGRADE
    ok(decide_action(BAND_DEGRADE, rec2) == "close",
       f"降难度用满 {config.MAX_DEGRADE} 次 → close")
    rec3 = _bare_round()
    rec3.attempts = [_attempt(i, 50.0) for i in range(1, config.MAX_ATTEMPTS_PER_QUESTION + 1)]
    ok(decide_action(BAND_L2, rec3) == "close",
       f"同一题答满 {config.MAX_ATTEMPTS_PER_QUESTION} 次 → close（不会无限空转）")

    # ---- 七、谁上线程池：reranker 必须留在调用线程上 ----
    # 守的是一个**真炸过**的坑。跑批实测两次、Windows 事件日志同签名：
    #   出错模块 c10.dll（PyTorch 原生核心）
    #   异常代码 0xc0000005 (ACCESS_VIOLATION)  偏移 0x91444
    # 最初把 reranker 也丢进 ThreadPoolExecutor，服务中途就这样没了 ——
    # 无 traceback、日志停在一次 /chat 中途、进程直接消失。
    # 这条断言把「reranker 留调用线程、只有纯网络的判档进池」变成机器可查的，
    # 免得以后有人看它"只用了一个 worker"就顺手优化回去。
    import threading
    from app.core.session import InterviewSession
    seen = {}

    class _StubJudge:
        def judge(self, *a, **k):
            seen["judge"] = threading.current_thread()
            return (BAND_L2, "桩理由", True)

    class _StubScorer:
        judge = _StubJudge()

        def score_answer(self, *a, **k):
            seen["reranker"] = threading.current_thread()
            return {"reranker_score": 42.0, "reranker_ok": True}

    class _StubSelf:
        scorer = _StubScorer()
        session_id = "smoke"

    _caller = threading.current_thread()
    _sc, _jb, _jw, _jok = InterviewSession._score_and_judge(
        _StubSelf(), "一段回答", _bare_round())
    ok(seen.get("reranker") is _caller,
       "reranker 在**调用线程**上跑（丢进池会在 c10.dll 里原生崩溃，踩过）",
       f"实际 {seen.get('reranker')}")
    ok(seen.get("judge") is not _caller,
       "判档确实在另一个线程上跑（否则并行是假的，白等一倍延迟）",
       f"实际 {seen.get('judge')}")
    ok(_jok is True and _jb == BAND_L2 and _sc["reranker_score"] == 42.0,
       "并行取回来的结果一个都没串味", f"{_sc} {_jb} {_jok}")


# ============================================================
# 难度自适应（整场走势 → 阶段难度集合）
# ============================================================
def adaptive_difficulty():
    """
    守三件事：**不越界**、**不改配置**、**两个阈值不可能同时满足**。

    为什么"不改配置"要单独守：STAGE_RULES 里的难度集合是**模块级可变对象**，
    adapt/widen 一旦原地改它，改的就不是这一场，而是**整个进程** —— 之后
    所有会话、包括冒烟测试自己的阶段断言，都会读到一个被改过的配置。
    这种错一次就能污染全进程，值得一条断言。
    """
    section("▸ 难度自适应（扩档边界 / 配置不被改 / 阈值互斥）")

    from app.core.session import (adapt_difficulties, widen_difficulties,
                                  InterviewSession, DIFFICULTY_ORDER)
    W = widen_difficulties

    # ---- 一、扩档的边界 ----
    ok(W({"medium"}, +1) == {"medium", "hard"}, "偏强：{medium} 向上扩一档 → {medium,hard}")
    ok(W({"medium"}, -1) == {"easy", "medium"}, "偏弱：{medium} 向下扩一档 → {easy,medium}")
    ok(W({"hard"}, +1) == {"hard"}, "已经是最难的 hard：向上扩不越界")
    ok(W({"easy"}, -1) == {"easy"}, "已经是最简单的 easy：向下扩不越界")
    ok(W({"hard"}, -1) == {"medium", "hard"}, "hard 向下扩 → {medium,hard}（下限动了）")
    ok(W({"medium"}, 0) == {"medium"}, "delta=0 原样返回")
    ok(W(set(), +1) == set(), "空集合不炸（返回空集）")
    ok(W({"很奇怪"}, +1) == {"很奇怪"}, "认不出的难度原样返回，不静默丢掉")

    # 只动一端：向上扩不许动下限，向下扩不许动上限
    ok(min(W({"medium"}, +1), key=DIFFICULTY_ORDER.index) == "medium",
       "向上扩只抬上限，下限不动（否则等于替考生假设他一定答得上 medium）")
    ok(max(W({"medium"}, -1), key=DIFFICULTY_ORDER.index) == "medium",
       "向下扩只压下限，上限不动")

    # ---- 二、绝不改到传进来的那个集合（尤其是 config.STAGE_RULES 里的）----
    base = {"medium"}
    W(base, +1)
    W(base, -1)
    ok(base == {"medium"}, "widen 不改传进来的集合（纯函数）")
    before = [tuple(sorted(d)) for _, _, d in config.STAGE_RULES]
    adapt_difficulties("核心考察", config.STAGE_RULES[1][2],
                       ["L2"] * 9, 3, config.ADAPT_L2_RATE, config.ADAPT_DEGRADE_RATE)
    after = [tuple(sorted(d)) for _, _, d in config.STAGE_RULES]
    ok(before == after, "adapt 不改 config.STAGE_RULES 本身（改了就是污染全进程）",
       f"{before} → {after}")

    # ---- 三、阶段与阈值语义 ----
    ok(adapt_difficulties("开场热身", {"easy"}, ["degrade"] * 9, 3, 0.6, 0.5)[0]
       == {"easy"}, "开场热身不参与自适应（固定 easy）")
    note = adapt_difficulties("开场热身", {"easy"}, ["degrade"] * 9, 3, 0.6, 0.5)[1]
    ok("不参与" in note, "开场热身不参与时说明写清楚了", note)

    d, note = adapt_difficulties("核心考察", {"medium"}, ["L2", "L2"], 3, 0.6, 0.5)
    ok(d == {"medium"} and "样本不足" in note,
       "走势样本不足（2/3 轮）时不调整，按原计划走", f"{sorted(d)} {note}")

    d, _ = adapt_difficulties("核心考察", {"medium"}, ["degrade"] * 3, 3, 0.6, 0.5)
    ok(d == {"easy", "medium"}, "三轮都被判降难度 → 向下扩一档", f"实际 {sorted(d)}")

    d, _ = adapt_difficulties("核心考察", {"medium"}, ["L2"] * 3, 3, 0.6, 0.5)
    ok(d == {"medium", "hard"}, "三轮都被判深挖 → 向上扩一档", f"实际 {sorted(d)}")

    d, _ = adapt_difficulties("核心考察", {"medium"}, ["L1"] * 4, 3, 0.6, 0.5)
    ok(d == {"medium"}, "走势正常（全 L1）→ 不动", f"实际 {sorted(d)}")

    # 阈值是 >= 语义：3/5 = 0.6 恰好等于 ADAPT_L2_RATE，必须触发
    d, _ = adapt_difficulties("核心考察", {"medium"}, ["L2"] * 3 + ["L1"] * 2, 3, 0.6, 0.5)
    ok(d == {"medium", "hard"}, "恰好等于阈值（3/5=0.60）就触发，不是「超过才触发」",
       f"实际 {sorted(d)}")

    # ---- 四、两个阈值不可能同时满足（config 里那条注释的机器化版本）----
    ok(config.ADAPT_L2_RATE + config.ADAPT_DEGRADE_RATE > 1,
       f"阈值之和 {config.ADAPT_L2_RATE}+{config.ADAPT_DEGRADE_RATE} > 1 —— "
       "正因为 l2 与 degrade 互斥、两比例之和恒 ≤ 1，两个分支才不可能同时成立；"
       "若哪天把和调到 ≤ 1，就需要一条优先级规则了")

    # ---- 五、走势样本的取样口径 ----
    class _FakeSess:
        def __init__(self, rounds):
            self.rounds = rounds

    r_with = _bare_round()
    r_with.attempts = [_attempt(1, 80.0), _attempt(2, 20.0), _attempt(3, 10.0)]
    r_with.attempts[0].band = "L2"
    r_with.attempts[1].band = "degrade"
    r_with.attempts[2].band = "degrade"
    r_empty = _bare_round()                       # 出了题但还没答
    r_noband = _bare_round()
    r_noband.attempts = [_attempt(1, 50.0)]       # 答了但没记档位（老数据）
    traj = InterviewSession._trajectory(_FakeSess([r_with, r_empty, r_noband]))
    ok(traj == ["L2"], "走势只取每轮**首答**的档位（追问出来的不算，否则是回声）",
       f"实际 {traj}")
    ok(InterviewSession._trajectory(_FakeSess([r_empty])) == [],
       "没答过的轮次不进走势（不会把空档当成一个样本）")


# ============================================================
# 换题出路（Step 6）
# ============================================================
def swap_exit():
    """
    守三件事，都是"坏了也不报错、只是悄悄算错"的那种：

    1. **换题不作废流程** —— 不占 10 题名额、不进评分轮次、换完还能继续答满；
       同时被换掉的那道题的 qid 要留在 asked_pids 里（否则会被再抽一次）。
    2. **状态退回是精确的** —— 覆盖度与阶段进度都必须**逐字节**回到换题前。
       退少了：没考过的考点被记成考过，避重与盲区诊断一起歪。
       退多了：把别的轮次的考点也抹掉，同样歪。**两头都要卡。**
    3. **上限真的封得住** —— 一场只换一次，第 2 次"我没学过"落到 degrade。
       没有这条，"一直说不熟"就能把整场躲掉。

    ⚠️ 本段临时把 LLM_MOCK 与 A11_ADAPTIVE 关掉，并在 finally 里还原：
      · LLM_MOCK 关掉 —— _can_swap() 有「桩模式恒关」的守卫（守住"关掉新功能
        = 端到端行为与加它之前逐字节相同"），不关就一条分支都跑不到；
      · A11_ADAPTIVE 关掉 —— 非桩模式下 _current_stage() 会按走势扩难度，
        阶段断言就不再是 STAGE_RULES 原样的可预测值。
      两个开关都只影响本段自己建的会话（用完即弃），且立刻还原。
    """
    section("▸ 换题出路（Step 6）：不占名额 / 状态精确退回 / 上限封得住")

    from app.core import kg as _KG
    from app.core.prompts import SWAP_LINE
    from app.core.session import (BAND_DEGRADE, BAND_L1, BAND_L2,
                                  BAND_SWAP, InterviewSession,
                                  PHASE_ANSWER, PHASE_NEXT,
                                  fuse_bands, _BAND_DEPTH)

    # ---- 一、纯函数：swap 怎么融合 ----
    ok(BAND_SWAP in _BAND_DEPTH,
       "swap 在 _BAND_DEPTH 白名单里 —— 不在的话 fuse_bands 会把它当"
       "「判档没判出来」丢回 reranker，换题永远触发不了")
    ok(fuse_bands(BAND_L2, BAND_SWAP, True) == (BAND_SWAP, "judge_swap"),
       "判档说 swap → 结果就是 swap（不让 reranker 的深浅覆盖它）",
       f"实际 {fuse_bands(BAND_L2, BAND_SWAP, True)}")
    ok(fuse_bands(BAND_DEGRADE, BAND_SWAP, True) == (BAND_SWAP, "judge_swap"),
       "reranker 说 degrade 也不影响 —— swap 是**类别**判断（学没学过），"
       "不是深浅判断，两者没有可比的序")
    ok(fuse_bands(BAND_L2, BAND_SWAP, False) == (BAND_L2, "reranker_only"),
       "判档没成功（judge_ok=False）→ 退回 reranker，swap 进不来")
    _old_fuse = config.JUDGE_FUSE
    config.JUDGE_FUSE = "reranker"
    try:
        ok(fuse_bands(BAND_L2, BAND_SWAP, True) == (BAND_L2, "reranker_only"),
           "JUDGE_FUSE=reranker 时不采信判档器 → 换题天然关着（这是对的，不是漏洞）")
    finally:
        config.JUDGE_FUSE = _old_fuse

    # ---- 二、桩：判档按题面给 swap；reranker 恒给 L2 档的分 ----
    # 融合规则是 llm_first，判档成功时 reranker 的档不参与结果 —— 给它固定值
    # 反而是去随机化。另外 judge 跑在池线程、score_answer 在调用线程，两者并发，
    # 真去读共享状态就是数据竞争。
    class _SwapJudge:
        def __init__(self):
            self.swap_q: set[str] = set()
            self.swap_after = 1
            self.per_q: dict[str, int] = {}

        def judge(self, question, difficulty, stage, base_points, adv_points,
                  answer, history=None):
            n = self.per_q.get(question, 0) + 1
            self.per_q[question] = n
            if question in self.swap_q and n >= self.swap_after:
                return BAND_SWAP, "考生表示该技术方向从未接触过", True
            return BAND_L2, "桩理由", True

    class _SwapScorer:
        def __init__(self):
            self.judge = _SwapJudge()
            self.llm = None      # 没有真 LLM：/finish 会把各轮标成评分失败，本段不看分

        def score_answer(self, answer, base_points, adv_points):
            return {"reranker_score": 80.0, "reranker_ok": True,
                    "base_hit": [], "adv_hit": [],
                    "base_miss": [], "adv_miss": []}

    _n = [0]

    def _new():
        s = InterviewSession(config.JOBS[0], llm=MockLLM(), scorer=_SwapScorer())
        return s

    def _say():
        # 每次作答都换一句明显不同的长回答：复读守卫在这套环境里是开着的
        # （LLM_MOCK 被临时关掉），一模一样的文本会先把 band 压成 degrade。
        _n[0] += 1
        return f"第{_n[0]}次作答。" + "我的理解是要先做参数校验再走反射拿元数据。" * 3

    def _ans(s, text):
        toks = [ev["text"] for ev in s.submit_answer(text) if ev.get("type") == "token"]
        return toks, s.round_status()

    def _close_round(s):
        for _ in range(config.MAX_ATTEMPTS_PER_QUESTION + 1):
            toks, st = _ans(s, _say())
            if s.phase != PHASE_ANSWER:
                return toks, st
        raise AssertionError("这一轮没能收尾 —— 终止性出问题了")

    _old_mock, _old_adapt = config.LLM_MOCK, config.A11_ADAPTIVE
    config.LLM_MOCK, config.A11_ADAPTIVE = False, False
    try:
        ok(_new()._can_swap() is True, "非桩模式下可以换题")
        config.LLM_MOCK = True
        ok(_new()._can_swap() is False, "桩模式下恒不可换题（守住老的端到端行为）")
        config.LLM_MOCK = False

        # ---- 三、整场：第 3 题（阶段边界）被换掉 ----
        s = _new()
        q1 = s.ask_next_question()
        _close_round(s)
        q2 = s.ask_next_question()
        _close_round(s)
        pre_rounds, pre_idx, pre_used = s.questions_asked, s.stage_idx, s.stage_used
        ok((pre_idx, pre_used) == (0, 2), "两轮之后还在开场热身、用了 2 个名额",
           f"{pre_idx}/{pre_used}")
        seen_before = set(s.cov.seen_ids())

        q3 = s.ask_next_question()
        qid3 = q3["question_id"]
        # 第 3 题出题时开场热身刚满 3 → 阶段推进到核心考察。**故意挑这个边界**，
        # 因为换题要撤回的正是这一次推进。
        ok(q3["q_index"] == 3 and (s.stage_idx, s.stage_used) == (1, 0),
           "第 3 题出题时阶段刚好推进（开场热身 3 题用完 → 核心考察）",
           f"{s.stage_idx}/{s.stage_used}")
        # KG 关掉时 `s.kg is None`，`_kp_map_of` 会直接 AttributeError —— 下面三条
        # 「覆盖度精确撤回」的证据只有开 KG 才谈得上，**自动少这几项**（与整套
        # 「项数随开关浮动」的约定一致），不能让 KG=0 的跑法直接崩。
        _kpw3 = (_KG.overlap_weights(s._kp_map_of(qid3, s.current_round.raw))
                 if s.kg is not None else None)

        s.scorer.judge.swap_q.add(q3["question"])
        toks, st = _ans(s, _say())

        ok(toks == [SWAP_LINE],
           "换题只发一句**固定**过场话（不走 LLM，不另调一次模型）", str(toks))
        ok(st["action"] == BAND_SWAP and st["swapped"] is True,
           "round_status 报 action=swap / swapped=true", f"{st['action']}")
        ok(st["follow_up"] is False,
           "follow_up=False —— 前端据此调 /next；若是 True 就会让他再答一道已作废的题")
        ok(s.phase == PHASE_NEXT,
           "phase 落到 awaiting_next（与 close 轮等价，**前端零改动**）", s.phase)
        ok(s.questions_asked == pre_rounds,
           f"**换题不占名额**：questions_asked 仍是 {pre_rounds}", str(s.questions_asked))
        ok(len(s.rounds) == pre_rounds and len(s.swapped_rounds) == 1,
           "被换掉的那轮从 rounds 搬进了 swapped_rounds（只进报告、不进流程）")
        ok(s.swapped_rounds[0].question_id == qid3 and s.swapped_rounds[0].swap_reason,
           "报告记得住换掉的是哪道、为什么", s.swapped_rounds[0].swap_reason)
        ok((s.stage_idx, s.stage_used) == (pre_idx, pre_used),
           "**阶段进度精确退回**（换题不推进阶段，否则换一次就少问一道本阶段的题）",
           f"{s.stage_idx}/{s.stage_used}，期望 {pre_idx}/{pre_used}")
        if _kpw3 is not None:
            ok(set(s.cov.seen_ids()) == seen_before and s.cov.size == len(seen_before),
               "**覆盖度精确撤回**（集合与换题前逐个相同 —— 退少了是漏、退多了是伤及别人）",
               f"{sorted(s.cov.seen_ids())} vs {sorted(seen_before)}")
            _new_kps = set(_kpw3) - seen_before
            ok(not _new_kps or not (_new_kps & set(s.cov.seen_ids())),
               "第 3 题新引入的考点已从「已考过」里消失（非空性证据）",
               f"残留 {sorted(_new_kps & set(s.cov.seen_ids()))}")
        ok(qid3 in s.asked_pids,
           "但 qid 留在 asked_pids 里 —— 被换掉的题不该再被抽第二次")
        ok(s.swaps_used == 1, "本场已用掉 1 次换题机会")
        ok(s.current_round is s.swapped_rounds[0],
           "current_round 刻意不清空 —— round_status 要靠它把这次换题报给前端")

        q3b = s.ask_next_question()
        ok(q3b["q_index"] == 3 and q3b["question_id"] != qid3,
           "换题后下一题**复用同一个题号**（考生看到的仍是连续 1..10），但换了一道题",
           f"{q3b['q_index']}")
        ok((s.stage_idx, s.stage_used) == (1, 0),
           "新题把开场热身的第 3 个名额补上、阶段重新推进 —— 与没换过题时完全一致",
           f"{s.stage_idx}/{s.stage_used}")

        # ---- 四、答满 10 题 + finish 的报告 ----
        guard = 0
        while s.questions_asked < config.TOTAL_QUESTIONS and guard < 200:
            guard += 1
            _close_round(s)
            if s.questions_asked >= config.TOTAL_QUESTIONS:
                break
            if s.ask_next_question().get("finished"):
                break
        if s.phase == PHASE_ANSWER:
            _close_round(s)
        ok(s.questions_asked == config.TOTAL_QUESTIONS,
           f"换过 1 题也仍然问满 {config.TOTAL_QUESTIONS} 题（没让他少答一道）",
           str(s.questions_asked))
        ok(len({r.question_id for r in s.rounds}) == config.TOTAL_QUESTIONS,
           "10 道题互不相同")

        raw = s.finish()["raw"]
        ok(raw["swaps_used"] == 1 and len(raw["swapped_rounds"]) == 1,
           "finish 的 raw 里带着换题记录")
        _sw = raw["swapped_rounds"][0]
        ok(_sw["题目ID"] == qid3 and _sw["swap_reason"],
           "记录了换掉哪道题、为什么")
        ok(_sw["scored"] is False and _sw["five_dim"] is None,
           "被换掉的轮**没有分**（None ≠ 0 分）")
        ok(set(_sw) - set(raw["rounds"][0]) == {"swap_reason"},
           "换题明细的键 = rounds[] 的键 + swap_reason（复用 to_raw，不手搓结构）",
           str(sorted(set(_sw) - set(raw["rounds"][0]))))
        # swapped 两个表里**都有**：这是判「这一轮真被换掉了吗」的唯一可靠依据。
        # ⚠️ 不能用 exchanges[].band == "swap" 代替 —— 名额用尽时 band 仍记 swap
        #    而轮次没作废（真跑实测 15 次 judge_swap 只有 4 次真换掉）。
        ok(_sw["swapped"] is True,
           "被换掉的轮 swapped=true")
        ok(all("swapped" in r and r["swapped"] is False for r in raw["rounds"]),
           "rounds[] 每一轮都带 swapped 键、且恒为 false（键恒在，消费方不用判空）",
           str([r.get("swapped") for r in raw["rounds"] if r.get("swapped") is not False]))
        ok(not ({"raw", "base_points", "adv_points", "rag_refs"} & set(_sw)),
           "换题明细里不含答案键与片段原文（to_raw 那道筛子照旧生效）")
        ok(any("本场换过 1 题" in n for n in raw["notes"]),
           "notes 里注明了换题及原因", str(raw["notes"]))
        ok(not any("只问了" in n for n in raw["notes"]),
           "**没有**误报「只问了 N 题」—— 换题不占名额，他确实答满了")
        ok(len(raw["rounds"]) == config.TOTAL_QUESTIONS
           and raw["rounds"][2]["题目ID"] != qid3,
           "报告的第 3 轮是新题，被换掉的那道不在 rounds 里")
        ok(len(raw["asked_pids"]) == config.TOTAL_QUESTIONS + 1,
           "asked_pids 比 questions_asked 多 1 —— 被换掉的题也占住了「别再抽它」的坑",
           str(len(raw["asked_pids"])))

        # ---- 五、上限：一场只换一次 ----
        s2 = _new()
        s2.scorer.judge.swap_q.add(s2.ask_next_question()["question"])
        _, st = _ans(s2, _say())
        ok(st["action"] == BAND_SWAP and s2.swaps_used == 1, "第 1 次：换题成功")
        s2.scorer.judge.swap_q.add(s2.ask_next_question()["question"])
        _, st = _ans(s2, _say())
        ok(st["action"] == BAND_DEGRADE and s2.swaps_used == 1,
           "第 2 次（判档又说 swap）：机会已用尽 → 不换题，按「没答上来」给一次引导",
           str(st["action"]))
        ok(st["follow_up"] is True, "这一轮是正常追问，不是换题")
        ok(s2.rounds[-1].attempts[-1].band == BAND_SWAP,
           "这一轮的 band 如实记成 swap（供 3 号统计判档质量）")

        # ---- 六、复读压过换题 ----
        s3 = _new()
        s3.scorer.judge.swap_after = 2      # 第 2 次作答时判档才说 swap
        qq = s3.ask_next_question()
        s3.scorer.judge.swap_q.add(qq["question"])
        same = _say()
        _ans(s3, same)
        _, st = _ans(s3, same)              # 一字不差地复述
        ok(st["fuse_rule"] == "repeat" and st["action"] == "degrade",
           "复读把 band 压成 degrade，**压过了判档给的 swap**"
           "（在复述旧答案的人不是在说「这个方向我没学过」）",
           f"{st['action']}/{st['fuse_rule']}")
        ok(s3.swaps_used == 0, "复读那一轮没有触发换题")

        # ---- 七、_unadvance_stage 与 _advance_stage 严格互逆 ----
        def _at(idx, used):
            x = _new()
            x.stage_idx, x.stage_used = idx, used
            return x

        x = _at(1, 2)
        x._advance_stage()
        ok((x.stage_idx, x.stage_used) == (1, 3), "阶段内 +1")
        x._unadvance_stage()
        ok((x.stage_idx, x.stage_used) == (1, 2), "阶段内退回来一模一样")
        _p0 = config.STAGE_RULES[0][1]
        x = _at(0, _p0 - 1)
        x._advance_stage()
        ok((x.stage_idx, x.stage_used) == (1, 0), "跨边界：推进到下一阶段、计数归零")
        x._unadvance_stage()
        ok((x.stage_idx, x.stage_used) == (0, _p0 - 1),
           "跨边界退回来也一模一样（换题刚好压在阶段边界上的情形）",
           f"{x.stage_idx}/{x.stage_used}，期望 0/{_p0 - 1}")
        x = _at(0, 0)
        x._unadvance_stage()
        ok((x.stage_idx, x.stage_used) == (0, 0),
           "已经在最开始：退回是空操作，不会出负数")

        # ---- 八、没换过题的一场：键恒在、notes 干净 ----
        s4 = _new()
        s4.ask_next_question()
        _, st = _ans(s4, _say())
        ok(st["swapped"] is False and st["swaps_used"] == 0 and st["swaps_left"] == 1,
           "从没换过时 swapped/swaps_used/swaps_left 三个键**依然存在**（消费方不用判空）",
           str({k: st[k] for k in ("swapped", "swaps_used", "swaps_left")}))
        _raw4 = s4.finish()["raw"]
        ok(_raw4["swaps_used"] == 0 and _raw4["swapped_rounds"] == []
           and not any("换过" in n for n in _raw4["notes"]),
           "没换过就是空值 / 空列表 / 一句不提，而不是缺键")
        _st5 = _new().round_status()
        ok(all(k in _st5 for k in ("swapped", "swaps_used", "swaps_left")),
           "round_status 的**空分支**也有这三个键", str(_st5))
    finally:
        config.LLM_MOCK, config.A11_ADAPTIVE = _old_mock, _old_adapt

    # ---- 九、CoverageTracker.remove 与 add 严格互逆（纯结构，不依赖上面的开关）----
    ct = CoverageTracker()
    ct.add({"a": 0.5, "b": 1.0}, 1)
    ct.add({"a": 0.5}, 2)
    ct.remove({"a": 0.5}, 2)
    ok(ct.size == 2, "remove 按 round_no 精确退 —— 只退掉第 2 轮那一份，a 还在")
    ct.remove({"a": 0.5, "b": 1.0}, 1)
    ok(ct.size == 0 and ct.overlap({"a": 1.0}) == 0.0,
       "第 1 轮也退掉之后清空（浮点残差被 1e-9 清掉）")


# ============================================================
# 第一维的题型标签（行为素质题 = 岗位胜任力关联度）
# ============================================================
def dim1_by_category():
    """
    确定性断言，**不依赖随机抽题**。

    为什么不能只靠端到端：行为素质题在题库里占 8~10%，10 轮里出不出现是抽签。
    而这一节要守的两条关键路径（prompt 的标签渲染、模型按标签回键的别名归一）
    恰恰只在那一种题型上才走到 —— 靠抽签等于没测。所以这里直接构造两种题型各一次。
    """
    section("▸ 第一维的题型标签（标签随题型变，键恒不变）")

    d0 = config.DIMENSIONS[0]
    beh = config.DIM1_LABEL_BEHAVIORAL

    # ---- 判定的边界 ----
    ok(config.dim1_label(config.CATEGORY_BEHAVIORAL) == beh,
       f"行为素质题 → {beh}")
    for other in ("技术知识题", "场景应用题", "项目经历题"):
        ok(config.dim1_label(other) == d0, f"{other} → 仍是「{d0}」")
    ok(config.dim1_label("") == d0 and config.dim1_label(None) == d0,
       "题型缺失 / None → 回落到「技术水平」（与今天的行为一致，不抛异常）")
    ok(config.dim1_label("  " + config.CATEGORY_BEHAVIORAL + " ") == beh,
       "题型串带空白也算行为素质题（主库数据不保证没空格）")
    ok(config.dim1_labels() == (d0, beh) and len(set(config.dim1_labels())) == 2,
       "dim1_labels() 给出两个互不相同的标签")
    ok(set(config.DIM1_RUBRIC) == set(config.dim1_labels()),
       "两套锚点与两个标签一一对应（加标签忘了配锚点会在这里响）",
       str(sorted(config.DIM1_RUBRIC)))

    # ---- RoundRecord 的派生属性 + raw ----
    r_beh = _bare_round(category=config.CATEGORY_BEHAVIORAL)
    r_tec = _bare_round(category="技术知识题")
    ok(r_beh.dim1_label == beh and r_tec.dim1_label == d0,
       "RoundRecord.dim1_label 由 category 派生")
    ok(r_beh.to_raw()["dim1_label"] == beh,
       "raw.rounds[].dim1_label 出得去（3 号据此知道那一列在量什么）")
    ok(r_beh.to_raw()["dim1_label"] != d0 and r_tec.to_raw()["dim1_label"] == d0,
       "同一份 raw 结构里两种题型的标签能区分开")

    # ---- 渲染：标签真的换掉了，且**没有留下未填的槽位** ----
    def render(cat: str) -> str:
        label = config.dim1_label(cat)
        return ROUND_SCORING.safe_substitute(
            dim1_label=label, dim1_rubric=config.DIM1_RUBRIC[label],
            **_DIM1_SCORING_PARAMS)

    rb, rt = render(config.CATEGORY_BEHAVIORAL), render("技术知识题")
    # ⚠️ 本条是这一节最硬的断言：技术题的 prompt 与**改动前逐字节相同**。
    #    只查关键词是不够的 —— 我在把第一维改成占位符时就漏过一个空格，
    #    关键词断言全绿、只有逐字节比对会响。
    ok(rt == _FROZEN_ROUND_SCORING,
       "技术知识题的评分 prompt 与改动前逐字节相同（技术题一个字都没变）")
    ok(rb != _FROZEN_ROUND_SCORING,
       "行为素质题的 prompt 与冻结串不同（否则等于没改）")
    ok(_FROZEN_ROUND_SCORING.count(d0) >= 5,
       f"冻结串里第一维出现 ≥5 处（锚点/平移 3 行/JSON 键），实测 "
       f"{_FROZEN_ROUND_SCORING.count(d0)}")
    ok("【" + beh + "】" in rb, f"行为素质题的 prompt 用【{beh}】做第一维锚点")
    ok(d0 not in rb, f"行为素质题的 prompt 里**不出现**「{d0}」（否则等于没修）")
    ok("【" + d0 + "】" in rt and beh not in rt,
       f"技术题的 prompt 用【{d0}】，且不误染成「{beh}」")
    for name, txt in (("行为素质题", rb), ("技术题", rt)):
        # ⚠️ 这条是给**将来**的：safe_substitute 不会因为漏传而报错，
        #    少传一个槽位只会把 "$xxx" 原样留在 prompt 里。所以必须显式断言。
        ok("$" not in txt, f"{name}渲染后不留任何未填占位符")
        ok(beh in txt or d0 in txt, f"{name}的 prompt 有第一维的名字")
    ok(rb.count(beh) >= 4, f"第一维的名字在行为素质题 prompt 里出现多处（实测 {rb.count(beh)}）",
       "锚点行 / 难度平移 3 行 / JSON 键都该换到")

    # ---- 别名归一：模型按标签回键，必须落回存储键 ----
    llm = MockLLM()
    ctx = {"question": "Q", "difficulty": "hard", "stage": "深度压轴",
           "base_points": "B", "adv_points": "A", "qa_block": "QA",
           "reranker_note": "N"}
    for cat in (config.CATEGORY_BEHAVIORAL, "技术知识题"):
        data, err = S.LLMScorer(llm).score_round(dict(ctx, category=cat))
        ok(err is None and bool(data.get("five_dim")),
           f"{cat}：能评出五维分", str(err))
        dims = data.get("five_dim") or {}
        ok(set(dims) == set(config.DIMENSIONS),
           f"{cat}：five_dim 键集恒为五维名（键不改名）", str(sorted(dims)))
        ok(list(dims) == list(config.DIMENSIONS),
           f"{cat}：five_dim 键序恒为 DIMENSIONS 序（评语按 items() 拼）", str(list(dims)))
        ok(isinstance(dims.get(d0), float),
           f"{cat}：第一维的分落在「{d0}」这个键上"
           + ("（模型按别名回键，已归一）" if cat == config.CATEGORY_BEHAVIORAL else ""))
    ok(ctx.get("category") is None, "ctx 里没有 category 时也不报错（旧调用方）")
    data, err = S.LLMScorer(llm).score_round(dict(ctx))
    ok(err is None and len(data.get("five_dim") or {}) == 5,
       "缺 category 时按「技术水平」渲染 —— 与加这个分支之前逐字节相同")


# ============================================================
# 知识图谱 / RAG 的纯函数
# ============================================================
class _FakeKG:
    """只实现 deepen_directions 用到的两个方法 —— 比造真图谱确定得多。"""

    def __init__(self, cooc, names):
        self._cooc, self._names = cooc, names

    def cooccur(self, kp_id):
        return self._cooc.get(kp_id, [])

    def kp_name(self, kp_id):
        return self._names.get(kp_id, "")


def kg_rag_pure():
    """
    这两个模块的价值全在纯函数里，而它们**不依赖随机抽题** —— 所以能断言
    精确值，而不是"跑通了"。这一节是 KG/RAG 回归的主体。
    """
    section("▸ 知识图谱：覆盖率累计与深挖方向")

    # ---- CoverageTracker.overlap ----
    cov = CoverageTracker()
    ok(cov.overlap({}) == 0.0, "overlap：候选没有知识点 → 0.0（不是 1.0，也不报错）")
    ok(cov.overlap({"a": 1.0}) == 0.0, "overlap：没见过的 → 0.0")
    cov.add({"a": 1.0}, 1)
    ok(cov.overlap({"a": 1.0}) == 1.0, "overlap：全命中 → 1.0")
    ok(cov.overlap({"a": 1.0, "b": 1.0}) == 0.5, "overlap：一半命中 → 0.5")
    # ⚠️ 分母是**候选自己**：候选是已考过集合的子集时，它「自己 100% 重复」。
    #    这不是 bug，是刻意 —— 否则知识点少的题会被系统性优待。
    ok(cov.overlap({"a": 0.5}) == 1.0,
       "overlap：候选是已考过的子集 → 1.0（分母是候选自己，不是全集）")
    ok(cov.seen_ids() == {"a"} and cov.size == 1, "seen_ids / size 只含已累计的")
    ok(cov.rounds_of("a") == [1], "rounds_of 记得是哪一轮考的")
    ok(cov.rounds_of("nope") == [], "rounds_of 查不到就返回空列表")

    # ---- deepen_directions 的四重过滤 ----
    fake = _FakeKG(
        cooc={"s": [("n1", 0.9), ("covered", 0.8), ("s", 0.7), ("noName", 0.6),
                    ("q", 0.5), ("long", 0.4), ("n2", 0.35), ("n3", 0.30)]},
        names={"n1": "关联方向甲", "covered": "已考过的", "s": "种子自己",
               "q": "线程池的核心参数有哪些", "long": "超" * 99,
               "n2": "关联方向乙", "n3": "关联方向丙"})
    got = deepen_directions({"s": 1.0}, {"covered"}, fake)
    titles = [d["title"] for d in got]
    ok(titles == ["关联方向甲", "关联方向乙", "关联方向丙"],
       "深挖方向：排除已考过的、排除种子自己、滤掉查不到名字的，按权重降序取前 N",
       f"实际 {titles}")
    ok("已考过的" not in titles, "深挖方向排除已考过的 kp（否则等于重复问）")
    ok("种子自己" not in titles, "深挖方向排除本题自己的知识点")
    ok("线程池的核心参数有哪些" not in titles,
       "深挖方向滤掉问句式名字（实测 kp_names 里这种有 88 个）")
    ok("超" * 99 not in titles, "深挖方向滤掉超长名字")
    ok(len(got) <= config.DEEPEN_TOPN, f"深挖方向条数 ≤ DEEPEN_TOPN={config.DEEPEN_TOPN}")
    ok(all(set(d) == {"kp_id", "title", "weight"} for d in got),
       "深挖方向只有 id/名字/权重三个键（可安全序列化，不含片段原文）")
    ok(deepen_directions({"s": 1.0}, set(), None) == [],
       "图谱不可用（idx=None）→ 空列表，不抛异常")
    ok(deepen_directions({}, set(), fake) == [], "本题没有知识点 → 空列表")

    # ---- 出题避重的四级阶梯 ----
    _sample_ladder()

    # ---- RAG 的格式化与截断 ----
    _rag_formatting()

    # ---- 盲区诊断 ----
    _blindspots()


def _sample_ladder():
    """
    把合成题库喂进 sample，逐级断言退化顺序。

    ⚠️ 这里猴子补丁了 qb.load_bank。理由是 sample() 按**岗位名**去全局缓存取题，
    没有注入候选的入口 —— 而这四级阶梯（尤其 r0/r1 是新增的）恰恰是最需要
    精确断言的部分。补丁在 finally 里一定还原。
    """
    saved = qb.load_bank
    fake_bank = [
        {qb.F_ID: "Q1", qb.F_DIFFICULTY: "easy"},
        {qb.F_ID: "Q2", qb.F_DIFFICULTY: "easy"},
    ]
    try:
        qb.load_bank = lambda job: fake_bank

        tr = {}
        hit = qb.sample("X", {"easy"}, [], accept=lambda q: q[qb.F_ID] == "Q2",
                        accept_relaxed=lambda q: False, trace=tr)
        ok(hit and hit[qb.F_ID] == "Q2" and tr["level"] == "r0",
           "避重阶梯：r0 命中（最严，重叠度最低）", str(tr))

        tr = {}
        hit = qb.sample("X", {"easy"}, [], accept=lambda q: False,
                        accept_relaxed=lambda q: q[qb.F_ID] == "Q1", trace=tr)
        ok(hit and hit[qb.F_ID] == "Q1" and tr["level"] == "r1",
           "避重阶梯：r0 无解 → 退 r1（放宽一档）", str(tr))

        tr = {}
        hit = qb.sample("X", {"easy"}, [], accept=lambda q: False,
                        accept_relaxed=lambda q: False, trace=tr)
        ok(hit is not None and tr["level"] == "r2",
           "避重阶梯：r0/r1 都无解 → 退 r2（原有行为，且不报错）", str(tr))

        tr = {}
        hit = qb.sample("X", {"hard"}, [], accept=lambda q: False,
                        accept_relaxed=lambda q: False, trace=tr)
        ok(hit is not None and tr["level"] == "r3",
           "避重阶梯：难度筛空 → 退 r3（放宽难度，原有行为）", str(tr))

        tr = {}
        hit = qb.sample("X", {"easy"}, ["Q1", "Q2"], trace=tr)
        ok(hit is None and tr["level"] == "none",
           "避重阶梯：题抽空 → None + level=none", str(tr))

        tr = {}
        hit = qb.sample("X", {"easy"}, [], trace=tr)
        ok(hit is not None and tr["level"] == "r2",
           "accept=None（KG 关闭）时**跳过** r0/r1、直接走 r2 —— 与加图谱之前逐字节相同",
           str(tr))
        ok(qb.sample("X", {"easy"}, []) is not None, "trace=None 时不报错（旧调用方照常）")
    finally:
        qb.load_bank = saved


def _rag_formatting():
    section("▸ RAG：片段截断与拼块")
    ok(RAG.format_block([]) == "",
       "format_block([]) 返回空串（不是「（没有参考片段）」这种提示句 ——"
       "一句无害的话会让 system 逐字节变化）")
    ok(RAG.format_block([{"text": "  "}]) == "", "全是空文本 → 空串")
    ok(RAG.format_block([{"text": "甲"}, {"text": "乙"}]) == "1. 甲\n2. 乙",
       "format_block 编号拼接")

    many = [{"text": "X" * 200} for _ in range(10)]
    blk = RAG.format_block(many)
    ok(len(blk) <= config.RAG_BLOCK_MAX_CHARS,
       f"format_block 硬顶 RAG_BLOCK_MAX_CHARS={config.RAG_BLOCK_MAX_CHARS}", f"实际 {len(blk)}")
    ok(blk.count("\n") + 1 < len(many), "format_block 超顶后停止追加")

    # 首行优先：document 的第一行就是题目正文，是最有用的部分；
    # 平铺截断会拦腰砍在第二行中间。顺带**天然丢掉「示例话术」**（在第 3 行之后）。
    # 注意是 "\n" + "乙"*100（一行 100 字），不是 "\n乙"*100（100 行各 1 字）
    ok(RAG._snippet("甲" * 140 + "\n" + "乙" * 100, 150).count("乙") == 0,
       "_snippet 首行优先：首行填满预算后不再拼后续行")
    long_first = RAG._snippet("甲" * 400 + "\n第二行", 150)
    ok(len(long_first) <= 151 and long_first.endswith("…"), "_snippet 超长截断并加省略号")
    ok(RAG._snippet("", 150) == "", "_snippet 空文本 → 空串")

    if config.A11_RAG:
        r = RAG.get_rag()
        if r is not None and not r.usable:
            t0 = time.time()
            got = r.search("任意题目文本", config.JOBS[0], "easy")
            ok(got == [] and time.time() - t0 < 1.0,
               "RAG 未就绪时 search 立刻返回 []，绝不阻塞 /next（模型加载要 10s）")
    else:
        ok(RAG.get_rag() is None, "A11_RAG=0 → get_rag() 是 None（配置，不是故障）")
        st = RAG.rag_status()
        ok(st["rag_enabled"] is False and st["rag_error"] == "",
           "A11_RAG=0 时 rag_enabled=false 且 rag_error 为空串（区分「关掉」与「失败」）")


def _blindspots():
    section("▸ 知识盲区诊断（纯结构化，含 attempts=[] 的轮）")
    kp = lambda kid, title: {"id": kid, "title": title, "description": ""}

    r1 = _bare_round(round_no=1, question_id="T-1", knowledge_points=[kp("k1", "甲")])
    r1.attempts.append(_attempt(1, 80.0))
    r1.five_dim = {d: 4.0 for d in config.DIMENSIONS}

    r2 = _bare_round(round_no=2, question_id="T-2", knowledge_points=[kp("k2", "乙")])
    # 出了题、一答没答 —— 这一轮必须留痕，且绝不能被读成「考了 0 分」

    r3 = _bare_round(round_no=3, question_id="T-3", knowledge_points=[kp("k3", "丙")])
    r3.attempts.append(_attempt(1, 50.0, ok_=False))     # reranker 全程失败

    r4 = _bare_round(round_no=4, question_id="T-4", knowledge_points=[kp("k4", "丁")])
    r4.attempts.append(_attempt(1, 5.0))
    r4.five_dim = {d: 2.0 for d in config.DIMENSIONS}

    d = BS.diagnose([r1, r2, r3, r4], None)
    sm = d["summary"]
    ok(sm["rounds_total"] == 4, "rounds_total 含没答题的轮（跟 raw.rounds 走，不是 scorable）")
    ok(sm["rounds_scored"] == 2, "rounds_scored 只数有 five_dim 的轮", str(sm))
    ok(sm["rounds_without_attempts"] == [2], "没答题的轮被单独点名", str(sm))
    ok(sm["kg_available"] is False and sm["domain_known"] == 0.0,
       "kg=None 时不抛异常、domain_known=0.0、键名不变（3 号不用分两种情况写）")

    by = {e["kp_id"]: e for e in d["knowledge_points"]}
    ok(set(by) == {"k1", "k2", "k3", "k4"}, "四个知识点都在", str(sorted(by)))
    ok(by["k1"]["hit"] is True, "答到了 → hit=true（复用既有阈值 LEVEL_L1_MIN，不自创）")
    ok(by["k4"]["hit"] is False, "有客观依据地没答到 → hit=false")
    ok(by["k2"]["hit"] is None,
       "出了题没答 → hit=null（**绝不用 false 冒充「没答上来」**）")
    ok(by["k3"]["hit"] is None,
       "reranker 全程失败 → hit=null（判不了，不是「没答上」）")
    ok(by["k1"]["last_score"] == 80.0, "答到了的轮 last_score 是真的分")
    # ⚠️ 这里守的是 RoundRecord.last_score 的陷阱：它在 attempts 为空时返回 0.0，
    #    直接拿来诊断会把「出了题没答」读成「考了 0 分」。诊断必须显式取 None。
    ok(by["k2"]["last_score"] is None and by["k2"]["best_score"] is None,
       "没答题的轮分数是 null，不是 0.0（RoundRecord.last_score 的陷阱）")
    ok(by["k3"]["last_score"] is None,
       "reranker 失败时的兜底 50.0 **不参与**统计（那是个假分）")
    ok(all("per_round" in e for e in by.values()), "每个知识点带 per_round 明细")
    ok(all(0.0 <= v <= 5.0 for v in (d["domains"][0]["five_dim_avg"].values()
                                     if d["domains"][0]["five_dim_avg"] else [])),
       "领域五维均分在 1~5 之间")
    # 五维均分不能被按 kp 个数加权：同领域两个 kp 命中同一轮时，那一轮只算一次
    ok(all("未归类" in dd["domain"] for dd in d["domains"]),
       "kg=None 时所有领域都归「未归类」（不假装知道）", str([x["domain"] for x in d["domains"]]))

    # ---- 软标签必须在**收集前**滤掉 ----
    # 图谱侧已经滤过一次（06_build_kg.py 的 SOFT_TAGS），但 kp_map() 取的是
    # 「主库 ∪ 图谱」，主库是真值源 —— 软标签会从那一侧兜回来。实测 11 场里
    # 「未归类」桶混进了 职业素养 / 场景设计 / Java版本特性。
    r5 = _bare_round(round_no=5, question_id="T-5",
                     knowledge_points=[kp("s1", "职业素养"), kp("k5", "戊")])
    r5.attempts.append(_attempt(1, 5.0))
    d2 = BS.diagnose([r5], None)
    ids = {e["kp_id"] for e in d2["knowledge_points"]}
    ok("s1" not in ids and "k5" in ids,
       "软标签（职业素养）不进知识点明细，真考点照进", str(sorted(ids)))
    ok(all("职业素养" not in dd["weak_kps"] for dd in d2["domains"]),
       "软标签不进 domains[].weak_kps（否则报告榜首领域里躺着「职业素养」）")
    ok(d2["summary"]["kp_total"] == 1,
       "软标签不进 kp_total —— 计数与清单一致（只滤名字会留下自相矛盾的一行）",
       str(d2["summary"]))

    # 整题的考点**全是**软标签时：这一题不该产生任何知识点，也不该崩
    r6 = _bare_round(round_no=6, question_id="T-6",
                     knowledge_points=[kp("s2", "场景设计")])
    r6.attempts.append(_attempt(1, 80.0))
    d3 = BS.diagnose([r6], None)
    ok(d3["knowledge_points"] == [] and d3["summary"]["kp_total"] == 0,
       "整题全是软标签 → 一个知识点都不产生", str(d3["summary"]))
    ok(d3["summary"]["domain_known"] == 0.0,
       "分母为 0 时 domain_known 给 0.0（不是 ZeroDivisionError）", str(d3["summary"]))


# ============================================================
# 全局评分器的单例 + LLM 绑定
# ============================================================
def scorer_singleton():
    """
    守的是 get_scorer 的**交错**，不是它的顺序调用。

    预热线程（main.py 的 _warmup_async）会在后台先建一个 llm=None 的评分器。
    会话创建时的 get_scorer(llm) 必须把 LLM 补上 —— 哪怕它是在预热线程出锁
    之后才拿到锁的。这个窗口很窄但真会中：交付样例的第一版就是这么挂的，
    整场 /finish 报「评分器未初始化」、五维全 null。
    断言的是修复后的行为，防止以后把那段判断挪回外层 if/elif。
    """
    section("▸ 评分器单例：预热线程抢先建实例后，LLM 仍要接上")

    saved = S._scorer
    try:
        S._scorer = None
        S._scorer_lock.acquire()                # 假装预热线程正握着锁
        box = {}
        t = threading.Thread(
            target=lambda: box.update(sc=S.get_scorer(get_llm())))
        t.start()
        time.sleep(0.3)                         # 让它走到「阻塞在锁上」
        S._scorer = S.Scorer(llm=None)          # 预热线程在里面建好了实例
        S._scorer_lock.release()                # 预热线程出锁
        t.join(timeout=10)

        sc = box.get("sc")
        ok(sc is not None, "会话线程拿到了评分器")
        ok(sc is S._scorer, "拿到的就是全局那一个（单例没被拆成两个）")
        ok(sc.llm is not None,
           "预热线程抢先建实例后，会话这次调用仍把 LLM 接上了")
    finally:
        if S._scorer_lock.locked():             # 中途失败时别把锁留在手上
            S._scorer_lock.release()
        S._scorer = saved


# ============================================================
# 关掉 KG / RAG 时 system 逐字节不变
# ============================================================
# 这段字符串是**加 RAG/KG 之前** ROUND_CONTEXT 渲染出来的原文（从改动前的
# 备份里抄下来的，不是照着新模板反推的 —— 反推等于自己证明自己）。
# 它守的是一条承诺：A11_KG=0 A11_RAG=0 时，送进模型的 system 与加这两个功能之前
# 一模一样。没有它，「可开关」只是嘴上说说。
# 技术知识题的评分 prompt，**逐字节冻结**。
# 出处：改动前的 app/core/prompts.py 同名模板，用 _DIM1_SCORING_PARAMS 渲染得到。
# 行为素质题的渲染**不在**这里 —— 它是本次的新行为，另行断言（见 dim1_by_category）。
# ⚠️ 为什么冻结整段、而不是只查几个关键词：把第一维改成占位符时我漏了一个空格
#    （渲染成「技术水平 即可给 4 分」），关键词断言**全绿**，只有逐字节比对会响。
_DIM1_SCORING_PARAMS = {'question': 'Q', 'difficulty': 'hard', 'stage': '深度压轴', 'base_points': 'B', 'adv_points': 'A', 'qa_block': 'QA', 'reranker_note': 'N'}
_FROZEN_ROUND_SCORING = """你是严格的技术面试官，现在要为一个「hard / 深度压轴」难度的题目打分。

【题目】Q

【基础得分点】
B

【进阶得分点】
A

【实际问答过程】
QA

【客观匹配参考】N

每次回答后面那行「客观匹配」是 reranker 逐条比对得分点的结果（字面语义相似度），使用规则：
- 它**只**反映得分点覆盖情况，**不**反映表达质量、逻辑条理、临场应变 —— 与后四维**无关**，不要拿它去推后四维。
- 它**会出错**：判为命中的可能只是提到了关键词而没真理解；判为未命中的可能用别的话把意思讲对了。
- 请对照上面的实际问答**复核**这些判断，**以你的判断为准**；若你对「技术水平」的判断与它相差超过 1 分，在 errors 里写明原因。

请按五个维度打分（1-5 分，允许 0.5 步进），并给一句简短评语：

【技术水平】1=概念模糊或答错；2=少量基础点且有明显错误；3=大部分基础点、无原则错误；4=全部基础点+部分进阶点；5=全部基础+进阶，能从源码/工程层面讲。
【逻辑思维】1=逻辑混乱跑偏；2=零散想法串不起来；3=思路基本清晰；4=层次分明、能自圆其说；5=结构化强，抓住本质层层递进。
【沟通表达】1=表述混乱；2=零散抓不住重点；3=基本能说清；4=流畅、重点突出、术语准确；5=严谨生动，能引导沟通节奏。
【应变能力】1=一追问就慌；2=简单追问能答、深追就卡；3=大部分追问能应对；4=压力追问下从容；5=高压下冷静，能主动化解难题。
【岗位匹配度】1=完全脱节；2=只懂概念不知道怎么用；3=知道基本应用场景；4=能结合开发场景讲应用；5=能结合真实项目讲落地和踩坑。

【难度平移规则（重要）】
- 开场热身(easy)：答全基础得分点且概念准确，技术水平即可给 4 分。
- 核心考察(medium)：要答全基础 + 进阶得分点，技术水平才给 4 分。
- 深度压轴(hard)：要答全并且给出源码/工程/架构层面的见解，技术水平才给 5 分。
- 跨难度的分数不要直接比较。

【评分要求】
- 评分必须能引用考生原话或命中的得分点作为依据，禁止凭印象打分。
- 「应变能力」重点看他被追问之后的表现，不是只看第一次回答。

只输出 JSON，不要任何多余文字：
{"技术水平": <1-5>, "逻辑思维": <1-5>, "沟通表达": <1-5>, "应变能力": <1-5>, "岗位匹配度": <1-5>, "comment": "<30字以内评语>", "errors": ["<考生讲错的技术点，没有就空数组>"]}"""


_FROZEN_ROUND_CONTEXT = """
============ 本轮上下文（考生看不到这部分）============

【当前题目】Q

【考察要点】
基础：B
进阶：A

【本轮你要做的事】D
H
============ 本轮上下文结束 ============"""


def prompts_frozen():
    section("▸ 关掉 KG / RAG 时 ROUND_CONTEXT 逐字节不变")

    got = ROUND_CONTEXT.safe_substitute(
        question="Q", base_points="B", adv_points="A", action_desc="D",
        hint_block="H", deepen_block=DEEPEN_BLOCK_EMPTY, rag_block=RAG_BLOCK_EMPTY)
    ok(got == _FROZEN_ROUND_CONTEXT,
       "填两个空串后与加 KG/RAG 之前的字符串**逐字节相同**")
    ok("【可拓展的关联方向】" not in _FROZEN_ROUND_CONTEXT
       and "【同岗位参考片段】" not in _FROZEN_ROUND_CONTEXT,
       "冻结串里本来就没有那两个新块")

    # ⚠️ 这条断言记录的是**陷阱本身**，不是我们想要的行为：
    #    safe_substitute 漏传槽位时**保留占位符原样**、不抛异常 —— 于是
    #    字面的 "$deepen_block" 会被喂给模型，而且完全静默。
    #    所以两个 *_EMPTY 必须由调用方**每次显式传**（session.py 里确实传了）。
    leak = ROUND_CONTEXT.safe_substitute(
        question="Q", base_points="B", adv_points="A", action_desc="D",
        hint_block="H")
    ok("$deepen_block" in leak and "$rag_block" in leak,
       "漏传新槽位时占位符会原样留在 prompt 里（这就是为什么必须显式传空串）")

    ok(DEEPEN_BLOCK_EMPTY == "" and RAG_BLOCK_EMPTY == "",
       "两个空串常量都是 ''，不是一句提示句（HINT_BLOCK_EMPTY 的教训："
       "一句看似无害的提示句会和动作指令打架）")
    ok(HINT_BLOCK_CLOSE and HINT_BLOCK_CLOSE.strip(),
       "HINT_BLOCK_CLOSE 仍然是非空的收尾专用块")


def kg_rag_singleton():
    """
    与 scorer_singleton() 同一个形状：守的是**交错**，不是顺序调用。

    KG 与 RAG 都是"加载很贵"的东西，双检锁里少一次重检查就会在并发请求下
    建出两份 —— KG 是白占 30-60MB，RAG 是白占 2.3GB 并且把内存预检的账算错。
    """
    section("▸ 知识图谱 / RAG 单例：交错下不产生第二个实例")

    st = KG.kg_status()
    ok(st["kg_enabled"] == config.A11_KG, "kg_status.kg_enabled 与开关一致")
    if not config.A11_KG:
        ok(KG.get_kg() is None, "A11_KG=0 → get_kg() 返回 None（是配置，不是故障）")
        ok(st["kg_error"] == "", "A11_KG=0 → kg_error 是空串（不冒充故障）")
        ok(st["kg_ready"] is False, "A11_KG=0 → kg_ready=false")
    if not config.A11_RAG:
        ok(RAG.get_rag() is None, "A11_RAG=0 → get_rag() 返回 None（是配置，不是故障）")
        ok(RAG.rag_status()["rag_error"] == "", "A11_RAG=0 → rag_error 是空串")

    for mod, lock_name, getter, label in (
            (KG, "_kg_lock", KG.get_kg, "KG"),
            (RAG, "_rag_lock", RAG.get_rag, "RAG")):
        inst_name = "_kg" if label == "KG" else "_rag"
        if not (config.A11_KG if label == "KG" else config.A11_RAG):
            continue
        lock = getattr(mod, lock_name)
        saved = getattr(mod, inst_name)
        try:
            setattr(mod, inst_name, None)
            lock.acquire()                    # 假装预热线程正握着锁
            box = {}
            t = threading.Thread(target=lambda: box.update(x=getter()))
            t.start()
            time.sleep(0.3)                   # 让它走到「阻塞在锁上」
            setattr(mod, inst_name, _SENTINEL)   # 预热线程在里面建好了实例
            lock.release()
            t.join(timeout=10)
            ok(box.get("x") is _SENTINEL,
               f"{label}：等锁期间别人建好实例后，拿到的就是那一个（单例没被拆成两个）")
        finally:
            if lock.locked():
                lock.release()
            setattr(mod, inst_name, saved)


def rag_never_in_raw():
    """
    **这一条才是「片段绝不进 raw」的真正门禁。**

    上面那些金丝雀（断言响应体里没有「答题要点」「示例话术」）只是次级检查：
    它们只在有人新开一条把 document 原样透传的路时才可能响。而唯一**现成**的
    泄漏面是 RoundRecord.rag_refs —— 它是什么、会不会被序列化，这里确定性地说清楚，
    不需要真加载 bge-m3（省 2.3GB），也不依赖随机抽题。
    """
    section("▸ RAG 片段绝不进 raw（确定性注入，不加载模型）")

    secret = "答题要点：金丝雀-决策树的分裂增益 示例话术：金丝雀-你可以这样回答"
    rec = _bare_round(question_id="T-SECRET")
    rec.rag_refs = [{"id": "r1", "question_id": "Q-SECRET", "layer": "原题",
                     "distance": 0.2537, "text": secret}]
    rec.rag_meta = {"used": True, "hit_ids": ["Q-SECRET"],
                    "layers": ["原题"], "distances": [0.2537]}

    raw = rec.to_raw()
    blob = json.dumps(raw, ensure_ascii=False)
    ok(secret not in blob, "rag_refs 的片段原文不进 to_raw()（raw 会返回给前端）")
    for w in _CANARY_WORDS:
        ok(w not in blob, f"金丝雀词「{w}」不进 to_raw()")
    ok(set((raw.get("rag") or {}).keys()) == _RAG_META_KEYS,
       "to_raw().rag 恰好是白名单四键", str(sorted((raw.get('rag') or {}).keys())))
    # 片段 ID 出得去（白名单里就有 hit_ids），但它只是个 ID —— 关键是它**只**在
    # 那一处，不会顺着别的字段漏出去。
    outside = json.dumps({k: v for k, v in raw.items() if k != "rag"},
                         ensure_ascii=False)
    ok("Q-SECRET" not in outside, "命中片段的 ID 只出现在 rag.hit_ids 一处")
    ok(raw["rag"]["hit_ids"] == ["Q-SECRET"]
       and raw["rag"]["distances"] == [0.2537]
       and isinstance(raw["rag"]["used"], bool),
       "白名单四键是 bool/ID 列表/字符串列表/数字列表 —— 结构上带不了片段原文")
    ok("rag_refs" not in raw, "to_raw() 里没有 rag_refs 这个键")
    ok(secret not in repr(rec), "repr(round) 里也没有片段原文（字段标了 repr=False）")
    # 深挖方向是可以出去的（只有 id/名字/权重），别把它一起封了
    ok("deepen_directions" in raw, "deepen_directions 照常出（它不含片段原文）")


# ============================================================
# main
# ============================================================
def main():
    base = None
    if "--base-url" in sys.argv:
        base = sys.argv[sys.argv.index("--base-url") + 1]

    client = HttpAdapter(base) if base else LocalClient()
    print("=" * 64)
    print(f"  A11 面试框架冒烟测试 ｜ {client.name}"
          + (f" ｜ {base}" if base else ""))
    print(f"  LLM_MOCK={config.LLM_MOCK}  RERANKER_MOCK={config.RERANKER_MOCK}")
    print(f"  A11_KG={config.A11_KG}  A11_RAG={config.A11_RAG}"
          "   （KG/RAG 只进 /finish 的 raw，不改任何接口契约与阈值）")
    print(f"  端口={config.THIS_PORT}  每场题数={config.TOTAL_QUESTIONS}  "
          f"单题最多追问={config.MAX_FOLLOW_UP}")
    print("=" * 64)

    t0 = time.time()
    try:
        # 场景 1：正常考生（长回答 → 高分 → 走 L2 追问）
        play(client, config.JOBS[0],
             lambda r, a: "这道题我的理解是这样的：" + "详细说明。" * 60,
             "正常考生（长回答，触发 L2）")

        # 场景 2：沉默考生（超短回答 → 低于 30 分 → 走 degrade）
        # 这是原实现会无限空转的分支，必须能正常收尾。
        play(client, config.JOBS[4],
             lambda r, a: "不会。",
             "沉默考生（触发 degrade，验收敛）")

        # 场景 3：中等考生
        play(client, config.JOBS[3],
             lambda r, a: "大概是这样，" * 6,
             "中等考生（触发 L1）")

        error_paths(client, config.JOBS[0])
        prompt_hygiene()
        scoring_bridge()
        judge_fusion()
        adaptive_difficulty()
        swap_exit()
        dim1_by_category()
        scorer_singleton()
        prompts_frozen()
        kg_rag_pure()
        rag_never_in_raw()
        kg_rag_singleton()
    except Exception:
        print("\n" + "!" * 64)
        traceback.print_exc()
        _FAIL.append("测试过程抛出未捕获异常")
    finally:
        try:
            client.close()
        except Exception:
            pass

    print("\n" + "=" * 64)
    print(f"  通过 {_PASS} 项，失败 {len(_FAIL)} 项，耗时 {time.time() - t0:.1f}s")
    if _FAIL:
        print("  失败清单：")
        for f in _FAIL:
            print(f"    - {f}")
        print("=" * 64)
        return 1
    print("  ✅ 全部通过")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
