# -*- coding: utf-8 -*-
"""
总评护栏（2026-09-27）：让 `summary` 里**点名一个本场没考过的考点**变得不可能。

要解决什么（真跑观测，不是推测）
--------------------------------
`/finish` 的 `summary` 里写着「强项：…**Spring 循环依赖**…」，而「Spring」与
「循环依赖」在**整份响应 JSON 里各只出现 1 次** —— 就在那句话里。
总评在凭空点名一场里根本没考过的知识点。

根因是**输入里没有真数据**：`Session._write_evaluation` 只喂了逐轮五维 + 一句评语 +
**截断到 10 条的考点名**（`[:10]` 是跨全场的），题干、逐轮对应关系、逐轮 `errors`
全都没给。于是「强项（具体到知识点）」这一条要求只能靠模型猜。
所以本波**先喂真数据**（`session._write_evaluation` 的 `$topics` 改成逐轮给），
再加这道护栏。

⚠️ 护栏**只做减法**。它能让「点名一个没考过的考点」变得不可能，
   **不能**让评价本身变好 —— 别把它当质量提升。
⚠️ 它**只作用于 `summary` 这一段自由文本**。`five_dim_avg` / `total_score` /
   `review` / `digest` / `blindspots` 一个都不碰（`summary` 是叶子字段：
   `digest`/`review`/`/growth` 都不读它，已核实）。

三道网，从便宜到贵
------------------
1. **标注约定**（`prompts.FINAL_SUMMARY`）：要求模型把提到的考点名用 `[[考点名]]`
   标出来，且只能用清单里给的名字。这是**让第 2 道网有依据**，不是指望它自觉。
2. **外来标题扫描**（本模块的主网，纯代码）：剥掉合法标注后，在正文里找
   `qb.all_knowledge_points(job)` 里**不属于本场**的标题。
3. **确定性兜底**（`fallback_summary`）：连重生一次也过不了，就用真数据拼一段，
   宁可平淡也不许编。

⚠️ 本模块**绝不抛异常**给调用方。`summary` 写不好不该把整场面试的收口打挂
   —— 与 `digest` / `review` / `pace_note` 同一条纪律。
⚠️ 本模块**不依赖 `blindspot`**：`diagnose` 跑在 `_write_evaluation` **之后**
   （顺序硬约束，见 `session.finish` 里那段注释），这里也拿不到它。
"""

from __future__ import annotations

import re

from app.core import question_bank as qb

# `[[考点名]]`。全角方括号一并认 —— 模型在中文语境里会写 `［［］］`。
_RE_TAG = re.compile(r"[\[［]{2}([^\[\]［］]+)[\]］]{2}")

# 连续空白（含全角空格）压成一个空格。`clean()` 只用它。
_RE_WS = re.compile(r"[ \t　]+")


def ground_truth(rounds: list) -> tuple[set[str], set[str]]:
    """
    本场**真实出现过**的考点名 —— 归一后集合 + 原文集合。

    取的是每轮 `RoundRecord.knowledge_points`（该题**自己的**「关联知识点」字段），
    也就是出题时真的绑在这道题上的那些。这是 `_write_evaluation` 喂给模型的同一份数据。

    ⚠️ 刻意**不**用 `blindspot` 那套（`diagnose` 在本函数之后才跑）。
    ⚠️ 刻意**不按软标签过滤**：这里只回答「这个名字这场考过吗」，
      不是「这个考点算不算硬考点」—— 后者是成长档案的口径（见 `blindspot.SOFT_TAGS`）。
    """
    norm: set[str] = set()
    raw: set[str] = set()
    for r in rounds or []:
        for kp in (getattr(r, "knowledge_points", None) or []):
            t = (kp.get("title") or "").strip()
            if t:
                raw.add(t)
                norm.add(qb.norm_kp_title(t))
    return norm, raw


def make_alien_index(job: str) -> list[tuple[str, str]]:
    """
    该岗位题库里**全部**考点标题，归一后 → `[(norm, 原题), ...]`，按归一长度降序。

    降序是为了让扫描时**先撞长的**：`哈希表` 与 `哈希表扩容` 归一后前者是后者的子串，
    先匹配长的，报出来的名字才是对的那个。

    ⚠️ 这是**每场调一次**的东西（`/finish` 才走一次），不在热路径上。
       `qb` 内部有缓存（`_KP_LIST`），同一岗位第二次调用是 O(1) 取列表。
    """
    out: list[tuple[str, str]] = []
    for kp in qb.all_knowledge_points(job):
        t = (kp.get("title") or "").strip()
        n = qb.norm_kp_title(t)
        if n:
            out.append((n, t))
    out.sort(key=lambda p: -len(p[0]))
    return out


def extract_tags(text: str) -> list[str]:
    """`[[X]]` 里的 X，按出现顺序。全角方括号一并认。"""
    return [m.group(1).strip() for m in _RE_TAG.finditer(text or "")]


def audit(text: str, truth_norm: set[str],
          alien_index: list[tuple[str, str]],
          min_chars: int) -> dict:
    """
    两道网一起跑，返回一份**可读的**报告（不抛异常）。

    ```
    {"ok": bool, "tags": [...], "unknown_tags": [...], "aliens": [...],
     "problems": [str, ...], "stripped": "剥掉合法标注后的正文"}
    ```

    判据：
      · `unknown_tags` —— `[[...]]` 里**不是**本场考点的名字。这是硬错：模型被明确
        要求"只能用清单里的名字"，它标注了一个不在清单里的，说明那句话是编的。
      · `aliens` —— 剥掉合法标注后，正文里出现的**场外考点标题**（归一后匹配，
        长度 ≥ `min_chars`，且与本场考点标题**互不包含**）。
        那个"互不包含"的排除很要紧，两个方向都要排：本场有 `哈希表` 时，正文里写
        `哈希表扩容` 会命中题库里**另一个**考点 `哈希表扩容` —— 那不是幻觉，
        是同一个知识点说得更细；反过来本场有 `哈希表扩容` 时写 `哈希表` 同理。
        ⚠️ 排除得越宽，护栏越弱 —— 这是刻意的：**误报的代价是丢掉一段本来能用的
          总评（进而落到兜底文案），漏报的代价只是少抓一次幻觉。** 宁可弱一点。
    """
    t = text or ""
    tags = extract_tags(t)
    unknown = [x for x in tags if qb.norm_kp_title(x) not in truth_norm]

    # 剥掉**合法**标注（留下名字本身），剩下的正文才是"没被标注覆盖的自由文本"。
    def _strip(m: re.Match) -> str:
        return m.group(1) if qb.norm_kp_title(m.group(1)) in truth_norm else m.group(0)

    stripped = _RE_TAG.sub(_strip, t)
    body = qb.norm_kp_title(stripped)

    aliens: list[str] = []
    for n, title in alien_index:
        if len(n) < min_chars or n in truth_norm:
            continue
        # 与本场某个真值标题**互不包含**才继续查 —— 任一方向包含都放过
        # （「同一个点说得更细/更简」，不是外来考点）。理由见 docstring 末尾。
        if any(n in tt or tt in n for tt in truth_norm):
            continue
        if n in body:
            aliens.append(title)
        # 上限：报告只要够定位问题，不需要穷举（真跑里一次最多两三处）
        if len(aliens) >= 8:
            break

    problems: list[str] = []
    if unknown:
        problems.append("这些名字不在本场考点清单里，却被标注成了考点："
                        + "、".join(dict.fromkeys(unknown)))
    if aliens:
        problems.append("正文里点到了本场没考过的考点："
                        + "、".join(dict.fromkeys(aliens)))
    return {"ok": not problems, "tags": tags, "unknown_tags": unknown,
            "aliens": aliens, "problems": problems, "stripped": stripped}


def clean(text: str) -> str:
    """
    收尾清理：去掉标注方括号、压平空白。**只在两道网都过了之后调。**

    ⚠️ 只去方括号，**不留**任何"（来源：…）"之类的痕迹 —— 考生看到的应该是一段
      正常评语。标注是给护栏看的内部约定，不是给考生看的引用格式。
    """
    t = _RE_TAG.sub(lambda m: m.group(1).strip(), text or "")
    return _RE_WS.sub(" ", t).strip()


def feedback(problems: list[str]) -> str:
    """把 `audit()` 的具体错处转成**给模型看的**一句纠正，附在重生请求后面。"""
    return ("\n【上一次的问题】" + "；".join(problems)
            + "。请重写：提到的考点必须来自上面那份清单，并且用 [[考点名]] 标出。")


def fallback_summary(rounds: list, avg: dict) -> str:
    """
    确定性兜底：用**真数据**拼一段，宁可平淡也不许编。

    ⚠️ 只用三样，一样都不许加：`rec.five_dim` / `rec.comment` /
      `rec.knowledge_points`。它们都是报告里已有的读数 ——
      也就是说这段话里**每一个字都能被报告本身核验**。
    ⚠️ 它不评价"水平高低"，只陈述测得的口径。这是**刻意的**：
      护栏的职责是"不许编"，不是"替你写一段好话"。
    """
    scored = [r for r in (rounds or []) if getattr(r, "five_dim", None)]

    def _kp_of(rec, n: int = 2) -> str:
        ts = [(kp.get("title") or "").strip()
              for kp in (getattr(rec, "knowledge_points", None) or [])]
        ts = [t for t in ts if t][:n]
        return "、".join(ts)

    lines: list[str] = []

    # 1) 总体：只说"评了几轮"，不说"水平如何"
    if not scored:
        lines.append("本场面试没有产生可评分的轮次，无法给出评价。")
    else:
        vals = {d: v for d, v in (avg or {}).items() if v is not None}
        if vals:
            # 五维里最高/最低的**维名**，不换算成任何"档次"措辞 ——
            # 那需要一套锚点，而本项目没有为总结文本定义过锚点。
            hi = max(vals.items(), key=lambda kv: kv[1])
            lo = min(vals.items(), key=lambda kv: kv[1])
            lines.append(f"本场共评价 {len(scored)} 轮。"
                         f"五维里相对靠前的是「{hi[0]}」（{hi[1]}），"
                         f"相对靠后的是「{lo[0]}」（{lo[1]}）。")
            # 2) 强项 / 薄弱点：用**具体某轮**的考点名，不用全局排序（全局排序
            #    会平均掉"某一轮答得好"这种真实信息，正是旧总评犯的错）。
            best = max(scored, key=lambda r: _round_avg(r))
            worst = min(scored, key=lambda r: _round_avg(r))
            if best is not worst:
                b, w = _kp_of(best), _kp_of(worst)
                if b:
                    lines.append(f"相对扎实的是第 {best.round_no} 题这一块（{b}）。")
                if w:
                    lines.append(f"需要再补的是第 {worst.round_no} 题这一块（{w}）。")

    # 3) 逐轮评语里已经写下的问题，原样带出来（不重写、不概括）
    cs = [(r.round_no, (r.comment or "").strip()) for r in scored if (r.comment or "").strip()]
    if cs:
        lines.append("各轮评语：" + "；".join(f"第 {n} 题 {c}" for n, c in cs[:5])
                     + ("…" if len(cs) > 5 else ""))

    lines.append("（本段由本场记录的各项读数直接汇总，未做额外发挥。）")
    return "".join(lines)


def _round_avg(rec) -> float:
    """
    一轮五维里非空值的**平均**，用来挑"相对扎实/相对需要补"的各一轮。

    ⚠️ 刻意取平均、**不取"技术水平"那一维**：第一维的**名字随题型变**（行为素质题
      叫「岗位胜任力关联度」，其余叫「技术水平」，见 `config.CATEGORY_BEHAVIORAL`），
      按名字取会在混型场次里静默取错。按平均取没有这个问题，而且与
      `five_dim_avg` 的口径同源。
    ⚠️ 一个值都没有 ⇒ 0.0。这是**排序用的中性值**，不是"他得 0 分"——
      它只影响谁跟谁比，不会被写进任何文字。
    """
    fd = getattr(rec, "five_dim", None) or {}
    vals = [float(v) for v in fd.values() if v is not None]
    return sum(vals) / len(vals) if vals else 0.0
