# -*- coding: utf-8 -*-
"""
session.py · 面试会话状态机
============================================================
一个 InterviewSession 就是一场面试。

阶段（phase）只有 4 个，且每个都对应「前端下一步该干什么」，没有中间态：

  awaiting_start  已创建、还没出题            → 合法下一步：/next（或 /chat 会自动出题）
  awaiting_answer 有一道题或一个追问悬着没答   → 合法下一步：/chat
  awaiting_next   本轮已收尾，考生无话可答     → 合法下一步：/next
  finished        /finish 已产出结果          → /finish 与 /result 都返回缓存

（对应设计稿里的 OPENING / ASKED+FOLLOWING / ROUND_CLOSED / FINISHED。
 ASKED 与 FOLLOWING 合并了 —— 两者对接口而言完全一样，都是"等一个回答"，
 拆开只会多出一个可能和别的计数器打架的状态。）

本轮的所有计数器都挂在 RoundRecord 上，开新轮即天然归零 —— 不存在
"session 级计数器忘了重置" 这类 bug。
"""
import difflib
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Generator, Optional

from app import config
from app.core import blindspot, question_bank as qb
from app.core import kg as kgmod
from app.core import rag as ragmod
from app.core.llm import get_llm
from app.core.prompts import (
    ACTION_DESC, CLOSE_DIRECTIVE, DEEPEN_BLOCK, DEEPEN_BLOCK_EMPTY,
    FINAL_SUMMARY, HINT_BLOCK, HINT_BLOCK_CLOSE, HINT_BLOCK_EMPTY,
    INTERVIEWER_SYSTEM, OPENING_LINE, RAG_BLOCK, RAG_BLOCK_EMPTY,
    ROUND_CONTEXT, SWAP_LINE, SYSTEM_SUMMARY,
)
from app.core.scoring import get_scorer
from app.logging_conf import get_logger

logger = get_logger(__name__)

# ---------- phase 常量 ----------
PHASE_START = "awaiting_start"
PHASE_ANSWER = "awaiting_answer"
PHASE_NEXT = "awaiting_next"
PHASE_DONE = "finished"


class SessionError(RuntimeError):
    code = "session_error"
    http_status = 400


class UnknownJob(SessionError):
    code = "unknown_job"
    http_status = 422


class NoActiveQuestion(SessionError):
    code = "no_active_question"
    http_status = 409


class EmptyMessage(SessionError):
    code = "empty_message"
    http_status = 400


class SessionFinished(SessionError):
    code = "session_finished"
    http_status = 409


# ============================================================
# 记录结构
# ============================================================
# 单条上限放宽到 80：题库里一条得分点常常是一整行（比如 Q0193 的基础第一条
# 把「优点」4 项写在了一行，约 57 字）。原来卡 40 会把它截成半句，
# 评分模型复核「这条到底中没中」时就看不全了。总量本来就被 truncate 兜着。
_POINT_CLIP = 80
_POINT_MAX = 6          # 最多列几条，超出的折成「（等 N 条）」


def _clip_points(points: list[str]) -> str:
    """把得分点列表压成一行 —— 明细太长会把问答本身挤出上下文。"""
    if not points:
        return "无"
    shown = [qb.truncate(p, _POINT_CLIP) for p in points[:_POINT_MAX]]
    more = len(points) - len(shown)
    return "、".join(shown) + (f"（等 {more} 条）" if more > 0 else "")


@dataclass
class AttemptRecord:
    """一次回答（首答或某次追问后的回答）。"""
    attempt_no: int
    answer: str
    reranker_score: float
    reranker_ok: bool
    base_hits: list[str]
    adv_hits: list[str]
    action: str                      # 由这次回答决定的动作 L1/L2/degrade/close
    hint: Optional[str]              # 因此要问出的追问（close 时为 None）
    # 判为**未**命中的得分点。给评分模型复核用 —— reranker 的假阴性
    # （考生用自己的话讲对了）只有把未命中的点也摆出来，模型才有机会翻案。
    base_misses: list[str] = field(default_factory=list)
    adv_misses: list[str] = field(default_factory=list)
    interviewer_reply: str = ""      # 面试官实际说的话
    llm_ok: bool = True
    ts: float = field(default_factory=time.time)
    # ---- 判档的两个源与融合结果（加法；全部有默认值，老构造点不受影响）----
    # 为什么要三个都存：只存"最后用了哪个档"的话，两个源打架的轮次就查不出来了，
    # 而这正是日后调 JUDGE_FUSE 与 LEVEL_*_MIN 的唯一依据。判档失败时
    # judge_band 是 None（**不是** "degrade"）—— "没判出来"和"判了降级"必须能分。
    reranker_band: str = ""                  # 覆盖率换算出来的档
    judge_band: Optional[str] = None         # LLM 判的档；None = 没判出来
    judge_ok: bool = False
    judge_why: str = ""                      # LLM 给的一句话理由（只进 raw / SSE）
    fuse_rule: str = "reranker_only"         # agree / llm_first / disagree_shallow …
    # 融合之后的**最终档位**（≠ action：action 还要过 caps，最终档位没有）。
    # 难度自适应要的就是这个 —— 问"考生答成什么样"而不是"系统最后做了什么动作"，
    # 拿 action 当走势样本会被 caps 压平的 close 污染。
    band: str = ""
    # ---- 重复作答守卫（加法，有默认值）----
    # 这次回答是否被判为「与本轮之前的回答实质重复」。两道闸谁触发的看组合：
    #   repeat=True 且 repeat_sim ≥ REPEAT_SIM → 确定性那一道（band 已被压成 degrade）
    #   repeat=False 但 judge_why 里写了重复 → 判档器自己认出来的（只影响档位措辞，
    #                                          不压 band，故意如此）
    repeat: bool = False
    repeat_sim: float = 0.0

    def match_note(self) -> str:
        """
        这一次回答的客观匹配情况 —— 拼进评分 Prompt 给模型复核。

        只给分数是没用的（「60 分」不告诉模型哪里出了问题）；给命中/未命中**两边**的
        明细，模型才能判断「命中的是真懂还是撞词」「没中的是不是换个说法讲对了」。
        """
        if not self.reranker_ok:
            return "  ↳ 客观匹配：reranker 本次不可用，没有匹配结果（请只看回答本身）"
        hit = self.base_hits + self.adv_hits
        miss = self.base_misses + self.adv_misses
        return (f"  ↳ 客观匹配 {self.reranker_score:g}/100"
                f"｜判为命中：{_clip_points(hit)}"
                f"｜判为未命中：{_clip_points(miss)}")

    def to_raw(self) -> dict:
        return {
            "answer": self.answer,
            "answer_chars": len(self.answer),
            "reranker_score": self.reranker_score,
            "reranker_ok": self.reranker_ok,
            "base_hit": self.base_hits,
            "adv_hit": self.adv_hits,
            "base_miss": self.base_misses,
            "adv_miss": self.adv_misses,
            # follow_up_level 是本轮评完才定的**下一轮**追问层级（"close" = 本轮到此为止）
            "follow_up_level": self.action,
            "hint": self.hint,
            "interviewer_reply": self.interviewer_reply,
            "llm_ok": self.llm_ok,
            "attempt_no": self.attempt_no,
            "ts": round(self.ts, 3),
            # ---- 判档的两个源 + 融合结果（加法）----
            # reranker_band 与 judge_band 各是一个档，fuse_rule 说明最后听了谁、
            # 是不是一致。judge_band 为 None = LLM 没判出来（超时/非 JSON），
            # **不是**判成了降级 —— 统计时要分开算。
            "reranker_band": self.reranker_band,
            "judge_band": self.judge_band,
            "judge_ok": self.judge_ok,
            "judge_why": self.judge_why,
            "fuse_rule": self.fuse_rule,
            # 融合之后的最终档位（不受 caps 影响）。难度自适应拿它当走势样本。
            "band": self.band,
            # 复读判定。repeat_sim 是与本轮历史回答的最高归一化相似度，
            # 调 REPEAT_SIM 的唯一依据（光看 repeat 布尔值调不了阈值）。
            "repeat": self.repeat,
            "repeat_sim": self.repeat_sim,
            "band_disagree": bool(self.judge_ok and self.judge_band
                                  and self.judge_band != self.reranker_band),
        }


@dataclass
class RoundRecord:
    """一道题的完整记录。题目元数据在**出题时**就存进来（修 #3）。"""
    round_no: int
    question_id: str
    stage: str                 # 出题时冻结的阶段名（修 #2：绝不在推进后回读）
    stage_index: int
    difficulty: str
    category: str              # 题型分类
    data_stage: str            # 主库「面试阶段」字段，仅作参考（其分布与 3/5/2 不一致）
    priority: str              # 考点优先级
    est_minutes: int
    keywords: list[str]
    question: str
    knowledge_points: list[dict]
    base_points: str
    adv_points: str
    # 主库原始记录。出题时就存进来，于是追问取材与 finish 明细都无需回查题库。
    raw: dict = field(default_factory=dict, repr=False)
    asked_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    open: bool = True
    attempts: list[AttemptRecord] = field(default_factory=list)
    follow_ups_used: int = 0
    degrade_used: int = 0
    # ---- 知识图谱 / RAG（全部是加法，不参与评分）----
    # 出题避重用了哪一级：r0/r1/r2/r3。事后调 KP_OVERLAP_THRESHOLD 的唯一依据。
    pick_level: str = ""
    # 本题被选中时的已考知识点重叠度（0~1）
    kp_overlap: Optional[float] = None
    # ---- 难度自适应（加法，全部有默认值）----
    # 出题时这一阶段**允许**的难度集合（可能已被整场走势调整过），以及为什么。
    # 存下来是为了事后能回答"这一题为什么是 hard" —— 光看 difficulty 答不了，
    # 因为那只是从这个集合里抽中的那一个，抽中的过程本身没留下痕迹。
    diffs_planned: list[str] = field(default_factory=list)
    adapt_note: str = ""
    # ---- 换题出路（加法，有默认值）----
    # 这一轮是否被换掉。**被换掉的轮次不在 self.rounds 里**（见 _swap_round），
    # 所以这两个字段只会出现在 self.swapped_rounds 里、只进报告不进任何流程。
    swapped: bool = False
    swap_reason: str = ""
    # 追问深挖方向：[{kp_id,title,weight}]，只有 id/名字/权重 —— 可安全序列化
    deepen: list[dict] = field(default_factory=list)
    # ⚠️ RAG 检索到的**片段原文**（含答题要点/示例话术）。
    #    repr=False 且**绝不进 to_raw()** —— raw 由 /finish 与 /result 返回，
    #    前端可见。要文本就别要安全，二者只能选一。
    rag_refs: list[dict] = field(default_factory=list, repr=False)
    # 可序列化的白名单元信息，四个键**结构上不可能夹带文本**。
    #
    # 默认值就带齐四个键、而不是空 dict：RAG **默认是关的**，若关掉时给 {}，
    # 3 号就得写「先判 rag 是不是空、再取 rag.used」两种情况 —— 与
    # blindspot 那条「键名完全不变，解析逻辑不用分两种情况写」是同一条原则。
    # 空 dict 只该表示「这段数据不存在」，而这里它存在、只是没启用。
    rag_meta: dict = field(default_factory=lambda: {
        "used": False, "hit_ids": [], "layers": [], "distances": [],
    })
    # 评分结果（finish 时填）
    five_dim: Optional[dict] = None
    comment: str = ""
    errors: list[str] = field(default_factory=list)
    scored: bool = False
    score_error: Optional[str] = None

    @property
    def last_score(self) -> float:
        return self.attempts[-1].reranker_score if self.attempts else 0.0

    @property
    def last_ok(self) -> bool:
        return self.attempts[-1].reranker_ok if self.attempts else True

    def qa_block(self) -> str:
        """
        把整轮的问答过程拼成评分 Prompt 里的一段。

        每次回答后面都挂上**那一次**的客观匹配明细（本轮改）—— 而不是只在末尾
        给一个笼统的总分。理由：评的是整轮，而「应变能力」看的正是首答与追问后
        的落差；只给最后一次的分数，会把这个落差整个抹平。
        """
        lines = []
        for i, a in enumerate(self.attempts):
            label = "第 1 次回答（无提示）" if i == 0 else f"第 {i + 1} 次回答"
            lines.append(f"【{label}】「{a.answer}」")
            lines.append(a.match_note())
            if a.action != "close" and (a.interviewer_reply or a.hint):
                lines.append(f"【面试官追问】{a.interviewer_reply or a.hint}")
        return "\n".join(lines) or "（本轮没有有效回答）"

    def reranker_note(self) -> str:
        """
        给评分模型的一行客观匹配摘要。

        reranker 失败时**明说用不了** —— 以前失败会返回默认 50 分，那个假分被
        当成「客观命中 50」喂进评分 Prompt，等于凭空空降一个中等分（它既不真
        也不假，模型无从分辨）。宁可不给，也不给一个假的。
        """
        if not self.attempts:
            return "本轮没有有效回答。"
        if not self.last_ok:
            return ("reranker 本次不可用，没有客观匹配结果 —— "
                    "请完全依据上面的实际问答判断，不要参考任何覆盖率数字。")
        if len(self.attempts) == 1:
            return f"本次回答覆盖率 {self.last_score:g}/100。"
        traj = " → ".join(f"{a.reranker_score:g}" for a in self.attempts)
        return (f"各次回答覆盖率（满分 100）：{traj}。"
                "注意看**首答到追问之后的变化** —— 那才是「应变能力」的主要依据。")

    @property
    def reranker_5(self) -> Optional[float]:
        """
        把 0-100 的覆盖率归一到五维的 1-5 量纲（0→1、100→5）。
        reranker 失败或没有回答时为 None —— 不是 0。
        """
        if not self.attempts or not self.last_ok:
            return None
        return round(1 + self.last_score / 100 * 4, 2)

    @property
    def tech_gap(self) -> Optional[float]:
        """
        一致性校验：reranker 归一值 与 LLM 判的「技术水平」之差。

        **不改评分，只暴露信号。** 差值大的轮次说明两个评分器在这一题上打架，
        值得人工看一眼是 reranker 误判还是 LLM 判偏 —— 这是调阈值的前提数据。
        None = 数据不足（reranker 失败 / 该轮没评上分），**不是 0**。
        """
        r5 = self.reranker_5
        tech = (self.five_dim or {}).get(config.DIMENSIONS[0])
        if r5 is None or not isinstance(tech, (int, float)):
            return None
        return round(abs(r5 - float(tech)), 2)

    @property
    def dim1_label(self) -> str:
        """
        本题型第一维的**标签**：行为素质题 = 「岗位胜任力关联度」，其余题型 = 「技术水平」。

        ⚠️ 由 category **派生**、不单独存字段 —— 存两份迟早会不一致，而这里
        「题型 → 标签」是一条纯函数关系，没有独立存一份的必要。
        ⚠️ five_dim 的**键**恒为 config.DIMENSIONS[0]，这个标签只说明那一列的
        分这轮是在量什么。键不变 → 3 号 / 前端 / 聚合一律不用分情况。
        """
        return config.dim1_label(self.category)

    def to_raw(self) -> dict:
        """3 号评估报告消费的结构。字段名与交接对齐；多余的键都是加法，不影响取用。"""
        return {
            "round": self.round_no,
            "题目ID": self.question_id,
            "stage": self.stage,
            "difficulty": self.difficulty,
            "题型分类": self.category,
            "question": self.question,
            "knowledge_points": self.knowledge_points,
            "exchanges": [a.to_raw() for a in self.attempts],
            "five_dim": self.five_dim,
            # 第一维这一轮量的**是什么**（行为素质题 = 岗位胜任力关联度）。
            # ⚠️ five_dim 的键永远是「技术水平」，键不变是为了 3 号不用分情况；
            #    这个字段补上「那一列的标签是什么」这一层信息。
            "dim1_label": self.dim1_label,
            "comment": self.comment,
            "errors": self.errors,
            # ---- 以下为附加信息 ----
            "stage_index": self.stage_index,
            "主库面试阶段": self.data_stage,
            "priority": self.priority,
            "est_minutes": self.est_minutes,
            "core_keywords": self.keywords,
            "asked_at": round(self.asked_at, 3),
            "closed_at": round(self.closed_at, 3) if self.closed_at else None,
            "reranker_score": self.last_score,
            "reranker_ok": self.last_ok,
            # ---- 一致性校验（加法，不改任何评分）----
            # 两个评分器打架的轮次在这里能一眼看出来：reranker_5 是覆盖率归一值，
            # tech_gap 是它跟 LLM 判的「技术水平」之差。都是 None = 数据不足，不是 0。
            "reranker_5": self.reranker_5,
            "tech_gap": self.tech_gap,
            # ---- 知识图谱 / RAG（加法；不参与任何评分）----
            # ⚠️ self.rag_refs **故意不在这里** —— 它含「答题要点/示例话术」原文，
            #    而 raw 会返回给前端。这里只出白名单四键的 rag_meta。
            "deepen_directions": self.deepen,
            "rag": self.rag_meta,
            "pick_level": self.pick_level,
            "kp_overlap": self.kp_overlap,
            # 这一阶段允许的难度集合 + 为什么是它。diffs_planned 是**候选范围**，
            # difficulty 是从中抽中的那一个 —— 只报 difficulty 的话，
            # "难度有没有跟着考生走"这件事在数据里是看不见的。
            "diffs_planned": self.diffs_planned,
            "adapt_note": self.adapt_note,
            # ---- 换题出路（加法）----
            # 这一轮**是否已被作废**。true 只会出现在 swapped_rounds[] 里；
            # rounds[] 里恒为 false —— 因为被换掉的轮次根本不在 rounds 里。
            # 键恒在（哪怕从没换过），与 swapped/swaps_used/swaps_left 同一条原则。
            #
            # ⚠️ 判「这一轮被换掉了吗」**只能看这个键，不能看 exchanges[].band**：
            #    本场换题名额用尽时 band 仍会记成 "swap"（判档确实说了 swap），
            #    但系统按「降级 + 给一次提示」处理，轮次**留在 rounds 里、照常评分**。
            #    真跑实测（2026-09-23，judge 开着的 4 场 125 次作答）：15 次
            #    fuse_rule=judge_swap 里只有 4 次真换掉 —— 光按 band=="swap" 筛
            #    会多算 11 次，而多出来的那 11 次恰恰是**考生真答了、也真被评了分**的轮。
            "swapped": self.swapped,
            "follow_ups_used": self.follow_ups_used,
            "degrade_used": self.degrade_used,
            "scored": self.scored,
            "score_error": self.score_error,
        }


# ============================================================
# 本轮动作决策（纯函数，唯一决策点）
# ============================================================
# 档位常量：三个档就是「往深里问 / 追基础 / 降难度」
BAND_L2, BAND_L1, BAND_DEGRADE = "L2", "L1", "degrade"
# 第 4 个档：**不是深浅判断，是类别判断** —— "这个方向他从没接触过"。
# 它必须进 _BAND_DEPTH，否则 fuse_bands 开头的白名单检查会把它当"没判出来"丢回
# reranker（那就永远换不了题了）。深度给 -1：语义上它比 degrade 还浅 ——
# degrade 是"这题他没答上来"，swap 是"这题根本就不该问他"。
# 真正决定它不被拿去比大小的是 fuse_bands 里那条提前返回。
BAND_SWAP = "swap"
# 深浅序，融合规则拿它比大小
_BAND_DEPTH = {BAND_SWAP: -1, BAND_DEGRADE: 0, BAND_L1: 1, BAND_L2: 2}


def band_of(score: float) -> str:
    """覆盖率（0-100）→ 档位。**判档线只在这里出现一次。**"""
    if score >= config.LEVEL_L2_MIN:
        return BAND_L2
    if score >= config.LEVEL_L1_MIN:
        return BAND_L1
    return BAND_DEGRADE


# 去掉空白、标点、下划线，只留字与数字（\w 在 str 模式下含中文）。
_RE_NONWORD = re.compile(r"[\W_]+")


def _norm_answer(s: str) -> str:
    """归一化后再比"说得一样不一样" —— 不让标点和空格影响判定。"""
    return _RE_NONWORD.sub("", s or "")


def detect_repeat(answer: str, attempts: list) -> tuple[bool, float]:
    """
    这次回答与**本轮之前**的回答是不是复读。返回 (是否复读, 最高相似度)。

    纯函数。两道闸里的**确定性**那一道（另一道是把历史喂给 LLM，见
    config.A11_REPEAT_GUARD）：判档器会超时、会返回非 JSON，而"逐字复述"
    这种最好认的重复不该依赖一个会失败的组件。

    ⚠️ 只跟**本轮**历史比。跨轮比会误伤：不同题目本来就可能答到同一个知识点，
      那是正常的，不是复读。
    ⚠️ **桩模式下必须关掉**，与 _make_judge 在 LLM_MOCK 时返回 None 是同一条约定
      （「关掉新功能 = 端到端行为与加这个功能之前逐字节相同」）：冒烟测试的第 2、
      第 3 次回答是为了走完三条分支而**构造成相同文本**的，复读守卫在那里必然触发，
      会把 fuse_rule 从 reranker_only 改成 repeat，成片地打掉既有断言。
      注意只认 LLM_MOCK、不认 RERANKER_MOCK：后者只换尺子，考生回答仍是真的。
    """
    if not config.A11_REPEAT_GUARD or config.LLM_MOCK or not attempts:
        return False, 0.0
    cur = _norm_answer(answer)
    if len(cur) < config.REPEAT_MIN_CHARS:
        return False, 0.0
    best = 0.0
    for a in attempts:
        prev = _norm_answer(a.answer)
        if not prev:
            continue
        best = max(best, difflib.SequenceMatcher(None, cur, prev).ratio())
        if best >= 1.0:
            break
    return best >= config.REPEAT_SIM, round(best, 4)


def fuse_bands(reranker_band: str, judge_band: Optional[str],
               judge_ok: bool) -> tuple[str, str]:
    """
    两个判档源 → 一个档。返回 (档位, 用了哪条规则)。

    为什么要有这一步，而不是直接二选一：两个源各有失效模式，而且**不一致本身
    就是有用的信号**（AGREE/DISAGREE 会随 SSE 一起返回，可供 3 号统计）。
      · reranker：覆盖率量的是「命中了几条得分点」，实测不稳定 —— 只换一次
        (得分点, 回答) 的传参顺序，29% 的题判档就翻（见 config.A11_JUDGE）。
      · LLM 判档：判断力够（同项目的五维分把三档考生分成 91/60/27），但会超时、
        会返回非 JSON，**失败时必须是"没判出来"，不能伪装成一个档**。
    规则由 config.JUDGE_FUSE 决定，默认 llm_first。判档没成功时，**任何**规则
    都退回 reranker —— 没有第二意见时只能听第一意见。
    """
    if not judge_ok or judge_band not in _BAND_DEPTH:
        return reranker_band, "reranker_only"
    rule = (config.JUDGE_FUSE or "llm_first").strip().lower()
    if rule == "reranker":
        return reranker_band, "reranker_only"
    # swap 是**类别**不是深浅，所以不进下面的比大小 —— 直接提前返回。
    #
    # 为什么必须放在 rule == "reranker" 之后：那条分支的语义是"完全不采信判档器"，
    # 而 swap **只能**来自判档器（reranker 的 band_of 只会给出 L2/L1/degrade），
    # 所以那个模式下换题天然关着 —— 这是对的，不是遗漏。
    # 而放在 agree/deepest/llm_first 之前：swap 一旦被 LLM 判出来就照办，
    # 不让 reranker 的深浅去覆盖它 —— 两者量的根本不是同一件事
    # （"他答得深不深" vs "他学没学过这个方向"），没有可比的序。
    if judge_band == BAND_SWAP:
        return BAND_SWAP, "judge_swap"
    if rule == "agree":
        if judge_band == reranker_band:
            return judge_band, "agree"
        # 不一致时取**较浅**的一档：判不准就别往深里挖，宁可多给一次引导
        shallower = min((judge_band, reranker_band), key=lambda b: _BAND_DEPTH[b])
        return shallower, "disagree_shallow"
    if rule == "deepest":
        deepest = max((judge_band, reranker_band), key=lambda b: _BAND_DEPTH[b])
        return deepest, ("agree" if judge_band == reranker_band else "deepest")
    # llm_first（默认）
    return judge_band, ("agree" if judge_band == reranker_band else "llm_first")


# ============================================================
# 难度自适应（纯函数，便于单测）
# ============================================================
# 难度由易到难。判定与扩展都只认这一个序，不在别处再写一份。
DIFFICULTY_ORDER = ("easy", "medium", "hard")


def widen_difficulties(diffs, delta: int) -> set[str]:
    """
    把难度集合向上（delta>0）或向下（delta<0）**扩一档**。纯函数。

    只动**一端**、且只动一格：delta>0 抬高上限，delta<0 压低下限，
    另一端不动。这样 {medium} 偏弱时变 {easy, medium}、偏强时变 {medium, hard}，
    而不是整体平移 —— 平移会把下限也抬到 medium，等于替考生做了"他一定答得上
    medium"的假设，而我们要的只是"多给题库一个档位可选"。

    ⚠️ 假设集合是**连续**的（{easy, medium} 这种）。STAGE_RULES 里都是单元素，
    成立。若以后配成 {easy, hard} 这种跳档集合，本函数会把中间的 medium 补进来，
    那多半不是你想要的。
    """
    idxs = [DIFFICULTY_ORDER.index(d) for d in diffs if d in DIFFICULTY_ORDER]
    if not idxs:
        return set(diffs)
    lo, hi = min(idxs), max(idxs)
    if delta > 0:
        hi = min(len(DIFFICULTY_ORDER) - 1, hi + 1)
    elif delta < 0:
        lo = max(0, lo - 1)
    return {DIFFICULTY_ORDER[i] for i in range(lo, hi + 1)}


def adapt_difficulties(stage: str, base, trajectory: list[str],
                       min_rounds: int, l2_rate: float, dg_rate: float
                       ) -> tuple[set[str], str]:
    """
    按整场走势决定**这个阶段**该出哪些难度。返回 (难度集合, 一句说明)。

    trajectory —— 已答过的每一轮的判档结果（**只取每轮首答**，一题一样本）。
                  空/样本不足时不调整，宁可先按原计划走。
    说明文字会进 raw，供 3 号核对"难度到底动没动、为什么动"，不进任何 prompt。
    """
    base = set(base)
    if stage not in config.ADAPT_STAGES:
        return base, f"{stage} 不参与自适应（固定 {sorted(base)}）"
    n = len(trajectory)
    if n < min_rounds:
        return base, f"走势样本不足（{n}/{min_rounds} 轮），按原计划 {sorted(base)}"
    l2 = sum(1 for b in trajectory if b == BAND_L2) / n
    dg = sum(1 for b in trajectory if b == BAND_DEGRADE) / n
    # 两个分支互斥：L2 与 degrade 不可能落在同一条首答上，l2+dg ≤ 1，
    # 而两个阈值之和 > 1。所以这里不需要优先级规则（config 里也写了这条）。
    if dg >= dg_rate:
        return (widen_difficulties(base, -1),
                f"走势偏弱（降难度 {dg:.0%} ≥ {dg_rate:.0%}）→ 向下扩一档")
    if l2 >= l2_rate:
        return (widen_difficulties(base, +1),
                f"走势偏强（深挖 {l2:.0%} ≥ {l2_rate:.0%}）→ 向上扩一档")
    return base, f"走势正常（深挖 {l2:.0%}／降难度 {dg:.0%}），按原计划 {sorted(base)}"


def decide_action(band: str, record: RoundRecord, repeat: bool = False) -> str:
    """
    返回 L1 / L2 / degrade / close。band 是 fuse_bands 给的三个档之一。

    终止性保证（修 #4）：每个非 close 分支都会递增 follow_ups_used，
    而它有 MAX_FOLLOW_UP 上限；degrade_used 与 attempts 数量各有一个上限。
    所以最多两轮追问之后必然返回 close —— 考生一句话不说也不会无限空转。
    （原实现 degrade 分支不递增任何计数，follow_up_count 永远 < 上限，
      前端就会一直等下去。）

    repeat —— 这次回答是否被判为复读（见 detect_repeat）。复读一律**不再深挖**：
      还没给过引导 → 走 degrade，给一次方向性提示，看他能不能借台阶说出新的；
      已经给过一次引导还复读 → 直接 close。**为什么第二次直接收尾而不是再降一次**：
      degrade 的素材是题面上固定的「降级策略」字段，复读时必然与上次**一字不差**
      —— 再把同一句提示说第二遍，考生只会再复读一遍，纯属空转。

    ⚠️ band 可能是 BAND_SWAP，**但它走不到这里来**：正常的换题在 submit_answer 里
       就被拦下并作废整轮了。能走到这里的 swap 只有一个来源 —— **本场换题次数已用尽**
       （_can_swap 为假）。这时它按"没答上来"处理、落到最下面的 degrade：
       考生说"这个方向我没学过"，系统给一次提示让他试试，是**比收尾更合理**的兜底
       —— 至少他还有机会说点什么。别把这里改成 close。

    ⚠️ 本函数有副作用（递增计数器），故意如此：动作决策与计数必须是同一步，
       否则两者可能对不上 —— 这正是原 bug 的成因。
    ⚠️ 参数从 reranker_score（数字）改成了 band（档位）：判档源现在有两个，
       阈值换算挪到 band_of() 里做，决策点只认档位。
    """
    if len(record.attempts) >= config.MAX_ATTEMPTS_PER_QUESTION:
        return "close"
    if record.follow_ups_used >= config.MAX_FOLLOW_UP:
        return "close"
    if record.degrade_used >= config.MAX_DEGRADE:
        return "close"
    if repeat and record.degrade_used >= 1:
        return "close"

    record.follow_ups_used += 1          # 每个追问分支都计数（含 degrade）
    if repeat:
        record.degrade_used += 1
        return "degrade"
    if band == BAND_L2:
        return "L2"
    if band == BAND_L1:
        return "L1"
    # BAND_DEGRADE 与 BAND_SWAP 都落到这里（swap 只在换题次数用尽时才会到，
    # 原因见上面那条 ⚠️）。BAND_SWAP 的 -1 深度只在 fuse_bands 里比大小用，
    # 与这里的动作选择无关 —— 这里只认"不是 L2、不是 L1"。
    record.degrade_used += 1
    return "degrade"


# 追问素材来自主库哪一列
_FOLLOW_FIELDS = {"L1": qb.F_FOLLOW_L1, "L2": qb.F_FOLLOW_L2, "L3": qb.F_FOLLOW_L3}


def record_follow(record: RoundRecord, level: str) -> str:
    """
    L1/L2/L3 追问字段 → 那一句 [追问]。

    这类字段带 [触发]/[追问] 标记，必须走 parse_follow_up 取正文；
    直接把整段塞给模型，等于连「什么情况下才该问这句」的判据一起给了它。
    """
    text = record.raw.get(_FOLLOW_FIELDS.get(level, ""), "")
    return qb.parse_follow_up(text)


def record_degrade(record: RoundRecord) -> str:
    """「降级策略」是纯散文，**没有** [触发]/[追问] 标记，不能走 parse_follow_up。"""
    return record.raw.get(qb.F_DEGRADE, "") or ""


def hint_for(action: str, record: RoundRecord) -> Optional[str]:
    """按动作取追问素材。"""
    if action == "close":
        return None
    if action == "degrade":
        text = record_degrade(record)
    elif action == "L2":
        text = record_follow(record, "L2") or record_follow(record, "L1")
    else:  # L1
        text = record_follow(record, "L1") or record_degrade(record)
    return qb.truncate(text.strip(), config.HINT_TRUNCATE) or None


# ============================================================
# 会话
# ============================================================
class InterviewSession:
    def __init__(self, job: str, intro: str = "",
                 llm=None, scorer=None):
        if job not in config.JOBS:
            raise UnknownJob(f"未知岗位：{job!r}；可选：{config.JOBS}")
        self.session_id = uuid.uuid4().hex[:8]
        self.job = job
        self.candidate_intro = intro or ""
        self.created_at = time.time()
        self.finished_at: Optional[float] = None

        self.phase = PHASE_START

        # 真实对话流：面试官的话也存（修 #1：原来只存考生回答，模型没有多轮记忆）
        self.transcript: list[dict] = []
        self.rounds: list[RoundRecord] = []
        self.current_round: Optional[RoundRecord] = None
        self.asked_pids: list[str] = []
        # 被换掉的轮次。**刻意与 self.rounds 分开存** —— 它一个都不能进下面那条
        # 「questions_asked = len(self.rounds)」的账（用户定的：换题不占 10 题名额），
        # 也不能进 _trajectory / finish 的评分轮次。放这儿纯粹是为了报告里能说清
        # 「这场换过 1 题、换的是哪道、为什么」。见 _swap_round 的注释。
        self.swapped_rounds: list[RoundRecord] = []
        self.swaps_used = 0

        # 知识图谱 / RAG。两个 get_* 都是单例，拿到的引用全程复用；
        # 关掉开关或加载失败时是 None，下面所有用到的地方都按 None 处理，
        # 行为与加这两个功能之前逐字节相同。
        self.kg = kgmod.get_kg()
        self.rag = ragmod.get_rag()
        # 整场累计「已考过的知识点」，供出题避重与盲区诊断共用
        self.cov = kgmod.CoverageTracker()

        # 阶段进度
        self.stage_idx = 0
        self.stage_used = 0

        self._result: Optional[dict] = None   # /finish 的缓存信封

        self.llm = llm or get_llm()
        self.scorer = scorer or get_scorer(self.llm)
        self._persona = load_persona(job)
        self._system = INTERVIEWER_SYSTEM.safe_substitute(
            job=job, persona=self._persona)

    # ---------- 派生属性 ----------
    @property
    def questions_asked(self) -> int:
        return len(self.rounds)

    @property
    def weights(self) -> dict:
        return config.weights_for(self.job)

    def opening_message(self) -> str:
        return OPENING_LINE.safe_substitute(job=self.job)

    # ---------- 阶段推进（修 #2）----------
    def _trajectory(self) -> list[str]:
        """
        整场走势：已答过的每一轮**首答**的融合档位。

        为什么只取首答：一题取一样本，被追问出来的第二三答不重复计权
        （否则越是被追着问的题，在走势里越"重"，而追问本身正是判档的结果，
        用它当样本会把走势喂成回声）。
        为什么用融合档位而不是 action：action 还要过 caps，第 3 次答完必然
        变成 close，那不是"考生答成什么样"，是"系统到上限了"。
        """
        return [r.attempts[0].band for r in self.rounds
                if r.attempts and r.attempts[0].band]

    def _current_stage(self) -> tuple[str, int, set[str], str]:
        """
        纯读，不改任何状态。返回 (阶段名, 计划题数, 难度集合, 为什么是这个集合)。

        难度集合**可能已被整场走势调整过** —— 调整只在 A11_ADAPTIVE 开且不在
        桩模式下发生（桩模式关掉是为了让冒烟测试那条「阶段↔难度同源」的断言保持
        逐字节可预测，不是为了省什么）。第 4 项只是给人看的一句话，进 raw，
        **不进任何 prompt**。
        """
        idx = min(self.stage_idx, len(config.STAGE_RULES) - 1)
        name, planned, diffs = config.STAGE_RULES[idx]
        if not (config.A11_ADAPTIVE and not config.LLM_MOCK):
            return name, planned, set(diffs), "难度自适应未启用"
        diffs, note = adapt_difficulties(
            name, diffs, self._trajectory(),
            config.ADAPT_MIN_ROUNDS, config.ADAPT_L2_RATE, config.ADAPT_DEGRADE_RATE)
        return name, planned, diffs, note

    def _advance_stage(self) -> None:
        """只改 stage_idx / stage_used，且必须在调用方已把阶段名写进 round 之后调。"""
        _, planned, _, _ = self._current_stage()
        self.stage_used += 1
        if self.stage_used >= planned and self.stage_idx < len(config.STAGE_RULES) - 1:
            self.stage_idx += 1
            self.stage_used = 0

    def _unadvance_stage(self) -> None:
        """
        撤回一次 _advance_stage。**只给换题用**。

        换掉的那道题不该占用阶段进度：否则考生换一次题，本阶段的题就少问一道。
        ⚠️ 必须与 _advance_stage 严格互逆，所以两处都只认 STAGE_RULES 的 planned
        （planned 不随难度自适应变，这是互逆成立的前提）。分两种情况：
          · stage_used > 0 —— 阶段没推进过，减一即可。
          · stage_used == 0 —— 说明上次 _advance_stage 刚好把阶段推进了，
            要退回到上一阶段、并把它记到"上一阶段只问了一道"的那个数上。
        """
        if self.stage_used > 0:
            self.stage_used -= 1
            return
        if self.stage_idx > 0:
            self.stage_idx -= 1
            self.stage_used = config.STAGE_RULES[self.stage_idx][1] - 1

    def _can_swap(self) -> bool:
        """
        还能不能换题。两个条件缺一不可。

        ⚠️ 桩模式下天然关着，不是靠这个函数判的：LLM_MOCK 时 _make_judge 返回
           None → judge_ok 恒为 False → fuse_bands 走 reranker_only →
           拿不到 BAND_SWAP。这里再显式挡一道，是为了守住与另外两个开关
           （A11_REPEAT_GUARD / A11_ADAPTIVE）同一条约定 ——
           「关掉新功能 = 端到端行为与加这个功能之前逐字节相同」。
        """
        return (config.A11_SWAP and not config.LLM_MOCK
                and self.swaps_used < config.MAX_SWAP_PER_SESSION)

    # ---------- 出题 ----------
    def ask_next_question(self) -> dict:
        if self.phase == PHASE_DONE:
            raise SessionFinished("面试已结束，请调用 /finish 或 /result 取结果。")

        # 幂等：题目还没答就再调 /next，返回同一道题，避免误点消耗题目。
        #
        # ⚠️ 这个提前 return 同时守住了 CoverageTracker：它在 qb.sample **之前**
        #    就返回了，所以重复调 /next 根本走不到下面的 self.cov.add，
        #    同一轮的覆盖不会被累计两次。**不要把它挪到抽题之后。**
        if self.phase == PHASE_ANSWER and self.current_round is not None:
            logger.info("sid=%s phase=awaiting_answer 重复调 /next，返回同一题 qid=%s",
                        self.session_id, self.current_round.question_id)
            return self._question_payload(self.current_round)

        if self.questions_asked >= config.TOTAL_QUESTIONS:
            self.phase = PHASE_NEXT
            logger.info("sid=%s 计划内 %d 题已问完", self.session_id, config.TOTAL_QUESTIONS)
            return self._finished_payload("plan_complete",
                                         f"题目已全部问完（{config.TOTAL_QUESTIONS} 题），请调用 /finish 结束面试。")

        # 顺序是有意义的：先读阶段 → 再抽题 → 把阶段名冻结进记录 → 最后才推进
        stage_name, _planned, difficulties, adapt_note = self._current_stage()
        stage_index = min(self.stage_idx, len(config.STAGE_RULES) - 1)

        # 出题避重：把两个档位的过滤器注入题库。题库层**不知道图谱的存在** ——
        # 它只收到两个接受单题的谓词（见 question_bank.sample 的说明）。
        accept = accept_relaxed = None
        if self.kg is not None:
            accept, accept_relaxed = self._overlap_filters()

        trace: dict = {}
        raw = qb.sample(self.job, difficulties, self.asked_pids,
                        accept=accept, accept_relaxed=accept_relaxed, trace=trace)
        if raw is None:
            self.phase = PHASE_NEXT
            logger.warning("sid=%s 题库已抽空", self.session_id)
            return self._finished_payload("bank_exhausted", "题库已抽完，请调用 /finish 结束面试。")

        qid = raw.get(qb.F_ID, "")
        round_no = self.questions_asked + 1

        km, kpw, deepen, picked_overlap = {}, {}, [], None
        if self.kg is not None:
            km = self._kp_map_of(qid, raw)
            kpw = kgmod.overlap_weights(km)
            picked_overlap = (self.cov.overlap(kpw) if kpw else None)
            # ⚠️ 顺序写死：**先**算深挖方向（此刻 cov 里还只有之前的轮次，语义才对），
            #    **再** cov.add。反过来的话本题自己的知识点会被当成"已考过"而排除。
            deepen = kgmod.deepen_directions(kpw, self.cov.seen_ids(), self.kg)

        # 两个累计结构同生共死 —— 物理相邻是它们不走散的唯一可靠保证
        self.asked_pids.append(qid)
        self.cov.add(kpw, round_no)

        rec = RoundRecord(
            round_no=round_no,
            question_id=qid,
            stage=stage_name,
            stage_index=stage_index,
            difficulty=raw.get(qb.F_DIFFICULTY, ""),
            category=raw.get(qb.F_CATEGORY, ""),
            data_stage=raw.get(qb.F_STAGE, ""),
            priority=raw.get(qb.F_PRIORITY, ""),
            est_minutes=raw.get(qb.F_EST_MINUTES, 0) or 0,
            keywords=qb.split_lines(raw.get(qb.F_KEYWORDS, "")),
            question=raw.get(qb.F_QUESTION, ""),
            knowledge_points=qb.parse_knowledge_points(raw.get(qb.F_KNOWLEDGE, "")),
            base_points=raw.get(qb.F_BASE_POINTS, "") or "",
            adv_points=raw.get(qb.F_ADV_POINTS, "") or "",
            raw=raw,
            pick_level=trace.get("level", ""),
            kp_overlap=picked_overlap,
            deepen=deepen,
            diffs_planned=sorted(difficulties),
            adapt_note=adapt_note,
        )

        # RAG 参考片段：**每轮检索一次**（成本已付），整轮复用；
        # 但注不注入 prompt 由 submit_answer 按 action 决定（收尾轮不注入）。
        # 检索与注入是两件事 —— 这个区分是 close 轮禁令能成立的前提。
        if self.rag is not None:
            refs = self.rag.search(rec.question, self.job, rec.difficulty,
                                   exclude_id=qid)
            rec.rag_refs = refs
            rec.rag_meta = {
                "used": bool(refs),
                "hit_ids": [r.get("question_id") for r in refs],
                "layers": [r.get("layer") for r in refs],
                "distances": [r.get("distance") for r in refs],
            }

        self.rounds.append(rec)
        self.current_round = rec
        self.phase = PHASE_ANSWER
        self._advance_stage()          # ← 必须最后

        logger.info("sid=%s phase->%s round=%d qid=%s stage=%s diff=%s "
                    "pick=%s overlap=%s kp=%d deepen=%d rag=%s ｜ 难度范围 %s（%s）",
                    self.session_id, self.phase, rec.round_no, qid,
                    rec.stage, rec.difficulty, rec.pick_level, rec.kp_overlap,
                    len(km), len(deepen), rec.rag_meta.get("used"),
                    rec.diffs_planned, rec.adapt_note)
        return self._question_payload(rec)

    # ---------- 知识图谱辅助（KG 关掉/失败时全部不参与） ----------
    def _kp_map_of(self, qid: str, raw: dict) -> dict:
        """
        本题知识点的**并集**（主库 ∪ 图谱）。

        ⚠️ 与 blindspot.diagnose 走的是同一个 kg.kp_map —— 否则同一个知识点
        会出现「避重说考过、盲区说没考过」两种说法。
        """
        return self.kg.kp_map(qid, qb.parse_knowledge_points(
            raw.get(qb.F_KNOWLEDGE, "")))

    def _overlap_filters(self):
        """
        造两个候选过滤器：(r0 档, r1 档)。

        返回的是**闭包**而不是在这里筛题 —— 题库层只收到两个谓词，
        全程不知道图谱/知识点这回事（与「字段名集中在 question_bank 常量里」
        同一条原则：只读数据层不承载业务策略）。

        重叠度的分母是**候选自己**（见 CoverageTracker.overlap），
        所以一道知识点少的题不会因为"能命中的少"而被系统性惩罚。
        """
        cache: dict[str, dict[str, float]] = {}

        def _kpw_of(q: dict) -> dict[str, float]:
            cid = q.get(qb.F_ID) or ""
            if cid not in cache:
                cache[cid] = kgmod.overlap_weights(
                    self.kg.kp_map(cid, qb.parse_knowledge_points(
                        q.get(qb.F_KNOWLEDGE, ""))))
            return cache[cid]

        def _mk(limit: float):
            def _acc(q: dict) -> bool:
                return self.cov.overlap(_kpw_of(q)) < limit
            return _acc

        return _mk(config.KP_OVERLAP_THRESHOLD), _mk(config.KP_OVERLAP_RELAXED)

    def _question_payload(self, rec: RoundRecord) -> dict:
        return {
            "type": "question",
            "finished": False,
            "session_id": self.session_id,
            "stage": rec.stage,
            "stage_index": rec.stage_index,
            "q_index": rec.round_no,
            "total": config.TOTAL_QUESTIONS,
            "difficulty": rec.difficulty,
            "question_id": rec.question_id,
            "question": rec.question,
            "knowledge_points": [kp["title"] for kp in rec.knowledge_points[:5]],
            "opening_text": f"【{rec.stage}】请回答：{rec.question}",
            "phase": self.phase,
            # 注意：这里**不返回**主库原始记录（含得分点/三级追问/校准锚点），
            # 那是答案key，原实现把它整个塞给了浏览器。
        }

    def _finished_payload(self, reason: str, message: str) -> dict:
        return {
            "type": "finished",
            "finished": True,
            "session_id": self.session_id,
            "reason": reason,
            "message": message,
            "q_index": self.questions_asked,
            "total": config.TOTAL_QUESTIONS,
            "phase": self.phase,
        }

    # ---------- 回答 ----------
    def _score_and_judge(self, answer: str, rec: RoundRecord
                         ) -> tuple[dict, Optional[str], str, bool]:
        """
        客观命中分与 LLM 判档**并行**跑。返回 (sc, judge_band, judge_why, judge_ok)。

        为什么并行：两个都是几百毫秒到几秒的外部等待，串行就是白等一倍。
        reranker 约 3s（本地 CPU 推理），判档是一个短 JSON 的 API 往返（约 1~2s），
        并行之后总延迟 ≈ max(两者) —— 加了判档，考生几乎察觉不到。

        ⚠️ 判档失败**绝不能**拖慢或弄挂这一轮：judge 抛异常就被吞成
          (None, "", False)，由 fuse_bands 退回 reranker。它是个增强，不是依赖。
        ⚠️ **谁上线程池是硬约束，别"顺手优化"回去**：只有判档能进池，reranker
          必须在调用线程上（否则 c10.dll 原生崩溃，见下面那段注释）。
        ⚠️ 线程池只在这里建、用完就关：一轮一次，开销可忽略；换来的好处是不用
          维护一个跨请求的长生命周期池（那个要处理线程泄漏与会话隔离，代价远大于收益）。
        """
        judge = getattr(self.scorer, "judge", None)
        if judge is None:
            # 判档关掉时（含桩模式）连线程池都不建 —— 行为与加这个功能之前相同
            return (self.scorer.score_answer(answer, rec.base_points, rec.adv_points),
                    None, "", False)

        # ⚠️ **reranker 必须留在调用线程上，只有纯网络的判档进池。**
        #    踩过（跑批实测，两次同签名）：最初把两者都丢进池 —— reranker 上工作
        #    线程 —— 服务中途**原生崩溃**，无 traceback、进程直接消失，日志停在
        #    一次 /chat 中途。Windows 事件日志：
        #        出错模块 c10.dll（PyTorch 原生核心）
        #        异常代码 0xc0000005 (ACCESS_VIOLATION)  偏移 0x91444
        #    两次崩溃的模块与偏移**完全相同**。而改这个功能之前 reranker 一直在调用
        #    线程（uvicorn 的长命工作线程）上跑，8 场会话一次没崩；改完 2 次全崩。
        #    机制推断：池线程是「用完即销毁」的，torch 存在线程局部（TLS）里的状态
        #    跟着线程一起析构，在 c10.dll 里炸掉。判档只是 httpx 往返、没有原生状态，
        #    进池无害 —— 本文件下面 /finish 的多线程 LLM 评分一直这么干，从没出过事。
        #    并行度不变：judge 先 submit，再在调用线程上跑 reranker，两者仍然重叠。
        with ThreadPoolExecutor(max_workers=1) as pool:
            # ⚠️ 此刻 rec.attempts 里**只有本轮之前的回答** —— 这一次的
            #    AttemptRecord 要到下面第 3 步才 append。这个顺序是历史快照
            #    能成立的前提，别把 append 提前。
            f_j = pool.submit(judge.judge, rec.question, rec.difficulty, rec.stage,
                              rec.base_points, rec.adv_points, answer,
                              [a.answer for a in rec.attempts])
            sc = self.scorer.score_answer(answer, rec.base_points, rec.adv_points)
            try:
                j_band, j_why, j_ok = f_j.result()
            except Exception:
                logger.exception("sid=%s round=%d 判档线程异常，退回 reranker",
                                 self.session_id, rec.round_no)
                j_band, j_why, j_ok = None, "", False
        return sc, j_band, j_why, j_ok

    def submit_answer(self, answer: str) -> Generator[dict, None, None]:
        """
        yield {"type":"token","text":...}。
        结束后的状态推进在 finally 里做 —— 哪怕 LLM 中途失败、或客户端断开，
        本轮也一定会收尾，不会把会话卡在 awaiting_answer。
        """
        answer = (answer or "").strip()
        if self.phase == PHASE_DONE:
            raise SessionFinished("面试已结束。")
        if not answer:
            raise EmptyMessage("回答不能为空。")
        if self.phase != PHASE_ANSWER or self.current_round is None:
            raise NoActiveQuestion("当前没有待回答的题目，请先调用 /next 出题。")

        rec = self.current_round
        attempt_no = len(rec.attempts) + 1

        # 1) 客观命中分 + LLM 判档 —— **并行**发起
        sc, judge_band, judge_why, judge_ok = self._score_and_judge(answer, rec)

        # 2) 两个源融合成一个档，再定动作（同时递增计数器）
        r_band = band_of(sc["reranker_score"])
        band, fuse_rule = fuse_bands(r_band, judge_band, judge_ok)

        # 2b) 重复作答守卫 —— 确定性那一道闸（另一道在 _score_and_judge 里
        #     把历史喂给了判档器）。判为复读就把档位**压到最浅**，不再往深里问。
        #
        # ⚠️ 为什么还要压 band（压 band 只是**记录**上的事，不改变实时行为）：
        #    `decide_action` 在 repeat=True 时压根不看 band（两个 repeat 分支都在
        #    最前面返回），所以压不压 band，考生这一轮看到的追问/提示**完全一样**。
        #    真正的读者是**报告**：band 会写进 attempt、进而进 `/finish` 的 raw，
        #    3 号 的「动作 vs 覆盖率」配对表与 tech_gap 一致性统计都读它 ——
        #    留着 L2，一次复读在报告里就是"又深挖成功一次"，那是假数据。
        #
        # ⚠️ 这里原来写的是「不压 band 的话 _trajectory() 会读成走势偏强 →
        #    难度自适应向上扩一档 → 复读反而把题越出越难」。**这句话是错的**，
        #    2026-09-23 真跑数据推翻了它：`_trajectory()` 取的是
        #    `r.attempts[0].band`（只取首答），而复读只可能出现在第 2/3 次
        #    （第 1 次没有历史，detect_repeat 必返 False）—— 复读的 band
        #    永远进不了走势。别再把这条理由抄回来。
        repeat, repeat_sim = detect_repeat(answer, rec.attempts)
        if repeat:
            band, fuse_rule = BAND_DEGRADE, "repeat"
            logger.info("sid=%s round=%d attempt=%d 判为复读（相似度 %.3f ≥ %.2f），"
                        "档位压到 degrade（判档原判 %s，reranker 档 %s）",
                        self.session_id, rec.round_no, attempt_no,
                        repeat_sim, config.REPEAT_SIM, judge_band, r_band)

        # 2c) 换题出路 —— 判档 LLM 说「这个方向他从没接触过」（fuse 出 BAND_SWAP）。
        #
        # ⚠️ 位置在 decide_action **之前**：换题要作废的是**整轮**，不是一个 action。
        #    走 decide_action 会顺手把 follow_ups_used / degrade_used 加一，
        #    而那一轮的计数器马上就随整轮一起被丢掉了 —— 加了也是白加，
        #    更糟的是它在"这一场只剩最后一次换题机会"的那一轮会真的生效。
        #    另外 repeat 分支在上一步已经把 band 压成 degrade，所以"复读"永远
        #    压过"换题"：一个在复述旧答案的人，不是"没学过"。
        if band == BAND_SWAP and self._can_swap():
            yield from self._swap_round(rec, answer, attempt_no, sc,
                                        r_band, judge_band, judge_why, judge_ok)
            return

        action = decide_action(band, rec, repeat)
        hint = hint_for(action, rec)

        attempt = AttemptRecord(
            attempt_no=attempt_no, answer=answer,
            reranker_score=sc["reranker_score"], reranker_ok=sc["reranker_ok"],
            base_hits=sc["base_hit"], adv_hits=sc["adv_hit"],
            base_misses=sc.get("base_miss", []), adv_misses=sc.get("adv_miss", []),
            action=action, hint=hint,
            reranker_band=r_band, judge_band=judge_band,
            judge_ok=judge_ok, judge_why=judge_why, fuse_rule=fuse_rule,
            band=band,
            repeat=repeat, repeat_sim=repeat_sim,
        )
        rec.attempts.append(attempt)

        # 3) 组装本轮 system（本轮指令放 system，不放进消息列表 —— 修 #1：
        #    原来把考生原话既 append 进历史又塞进 prompt，同一句出现两次）
        #    hint_block 按动作分三种，收尾轮**不能**用 HINT_BLOCK_EMPTY（原因见 prompts.py）
        if action == "close":
            hint_block = HINT_BLOCK_CLOSE
        elif hint:
            hint_block = HINT_BLOCK.safe_substitute(hint=hint)
        else:
            hint_block = HINT_BLOCK_EMPTY

        # 深挖方向 / RAG 参考：**只在 L1、L2 轮注入**。
        #
        # 收尾轮（close）与降级轮（degrade）一律注入空串 —— 四条理由写在
        # prompts.py 的 DEEPEN_BLOCK 上方（一句话版：system 是最弱的杠杆，
        # 而收尾轮的提问倾向是上下文里概率最高的续写；给 close 轮递"问什么"
        # 的素材，是在把一个已知 0/10 的机制往 10/10 推）。
        # degrade 一并排除：那个动作要的是**收拢**，灌"可拓展方向"与它反向。
        if action in ("L1", "L2"):
            deepen_block = (DEEPEN_BLOCK.safe_substitute(
                directions="、".join(d["title"] for d in rec.deepen))
                if rec.deepen else DEEPEN_BLOCK_EMPTY)
            rag_block = (RAG_BLOCK.safe_substitute(
                refs=ragmod.format_block(rec.rag_refs))
                if rec.rag_refs else RAG_BLOCK_EMPTY)
        else:
            deepen_block, rag_block = DEEPEN_BLOCK_EMPTY, RAG_BLOCK_EMPTY

        system = self._system + ROUND_CONTEXT.safe_substitute(
            question=rec.question,
            base_points=qb.truncate(rec.base_points, config.POINT_TRUNCATE) or "（无）",
            adv_points=qb.truncate(rec.adv_points, config.POINT_TRUNCATE) or "（无）",
            action_desc=ACTION_DESC.get(action, ACTION_DESC["close"]),
            hint_block=hint_block,
            deepen_block=deepen_block,
            rag_block=rag_block,
        )

        # 4) 消息列表 = 真实对话流（含面试官说过的话）+ 本次回答，回答只出现一次
        #    超长回答进 prompt 前截断（记录里仍存原文），防止一个人粘贴五千字撑爆上下文
        self.transcript.append({
            "role": "user",
            "content": qb.truncate(answer, config.ANSWER_TRUNCATE),
        })
        messages = self.transcript[-config.TRANSCRIPT_LIMIT:]
        if action == "close":
            # 收尾轮的临时旁白：只发这一次请求，**不写进 transcript**
            # （切片出来的 messages 是新列表，+ 不会污染 transcript）
            messages = messages + [{"role": "user", "content": CLOSE_DIRECTIVE}]

        # 5) 流式要面试官的话
        collected, llm_ok = "", True
        try:
            for piece in self.llm.chat_stream(system, messages):
                collected += piece
                yield {"type": "token", "text": piece}
        except Exception:
            llm_ok = False
            logger.exception("sid=%s round=%d 面试官回复流式失败", self.session_id, rec.round_no)
            raise
        finally:
            attempt.interviewer_reply = collected
            attempt.llm_ok = llm_ok
            if collected:
                self.transcript.append({"role": "assistant", "content": collected})
            else:
                self.transcript.pop()      # 没说出话就别留下一条空的 user
            self._settle_round(rec, action, attempt)

    def _swap_round(self, rec: RoundRecord, answer: str, attempt_no: int, sc: dict,
                    r_band: str, judge_band: Optional[str], judge_why: str,
                    judge_ok: bool) -> Generator[dict, None, None]:
        """
        换题出路：把这**一整轮作废**，让考生换一道别的方向的题。

        ⚠️ 唯一不变式：**`self.rounds` 里不留这一轮**。这不是「这道题答得不好」，
           是「这道题根本不该问他」。留在 self.rounds 里会让四件事同时出错：
             · questions_asked 涨了 —— 他本该答 10 道，换过一次就只剩 9 道
               （用户定的：换题**不占**名额）
             · _trajectory() 多一个 swap 样本 —— 拉低 L2/degrade 占比 → 难度误判
             · finish 的评分轮次里混进一道他没答过的题
             · 覆盖统计把从没考过的考点记成考过了
           所以是「pop 出 rounds、记进 swapped_rounds」—— 只进报告，不进任何流程。

        题号复用是自洽的，不是巧合：round_no 由 `self.questions_asked + 1` 即
        `len(self.rounds) + 1` 生成，pop 之后下一题自然还用同一个号，
        考生看到的仍是连续的 1..10。

        `self.current_round` **刻意不清空** —— round_status() 还要靠它把这次
        "换掉了哪道题、为什么"报给前端。清掉的话前端只能看到一个空轮次。
        下次 /next 会用新的一轮覆盖它，所以不留后患。
        """
        # 考生原话与面试官那句过场话都进 transcript：否则下一题的上下文里
        # 会出现"他说了句话、面试官没接"的断层。
        self.transcript.append({
            "role": "user",
            "content": qb.truncate(answer, config.ANSWER_TRUNCATE),
        })
        self.transcript.append({"role": "assistant", "content": SWAP_LINE})

        attempt = AttemptRecord(
            attempt_no=attempt_no, answer=answer,
            reranker_score=sc["reranker_score"], reranker_ok=sc["reranker_ok"],
            base_hits=sc["base_hit"], adv_hits=sc["adv_hit"],
            base_misses=sc.get("base_miss", []), adv_misses=sc.get("adv_miss", []),
            action=BAND_SWAP, hint=None,
            reranker_band=r_band, judge_band=judge_band,
            judge_ok=judge_ok, judge_why=judge_why,
            fuse_rule="judge_swap",
            band=BAND_SWAP,
            interviewer_reply=SWAP_LINE, llm_ok=True,
        )
        rec.attempts.append(attempt)
        rec.swapped = True
        rec.swap_reason = judge_why or "判档判定该方向未接触过"
        rec.open = False
        rec.closed_at = time.time()

        # 撤回这一轮对全局状态的三处副作用。三件事都要退，缺一个都会留下偏差。
        # · 覆盖：被换掉的题的考点从没被考过，必须退回（kg.remove 按 round_no 精确退）
        # · 阶段进度：换题不该推进阶段，否则换一次就少问一道本阶段的题
        # · 轮次表：见上面那段
        if self.kg is not None:
            try:
                # ⚠️ 必须**和 ask_next_question 里 cov.add 收到的是同一个东西**：
                #    那边是 `overlap_weights(kp_map)`（kp→权重），不是 kp_map
                #    （kp→信息 dict）。少这一步就会拿 dict 去做减法，直接 TypeError。
                #    kg.kp_map 有缓存，两次算出来的逐字节相同，所以减回去是严格互逆的。
                self.cov.remove(
                    kgmod.overlap_weights(
                        self._kp_map_of(rec.question_id, rec.raw)),
                    rec.round_no)
            except Exception:
                # 撤回失败只影响避重精度，绝不该让整场面试挂掉 —— 与 KG 全程
                # "降级不崩"的约定一致。
                logger.exception("sid=%s round=%d 换题撤回覆盖度失败",
                                 self.session_id, rec.round_no)
        self._unadvance_stage()
        idx = next((i for i, r in enumerate(self.rounds) if r is rec), -1)
        if idx >= 0:
            self.rounds.pop(idx)
        self.swapped_rounds.append(rec)
        self.swaps_used += 1

        # 过场话由**固定文本**给出、不走 LLM：这是一条控制流路径上的旁白，
        # 让 LLM 来说它多半会顺势追问一句 —— 而"别再问这道题"正是这一步要做的事。
        yield {"type": "token", "text": SWAP_LINE}

        # phase 走 PHASE_NEXT（= 等价于 action == close 的效果），
        # **前端因此零改动**：它只看 follow_up=false / round_finished=true 就调 /next。
        self.phase = PHASE_NEXT
        logger.info("sid=%s round=%d qid=%s 换题（本场第 %d/%d 次）：%s ｜ "
                    "判档 %s（reranker 档 %s）阶段退回 %s/%d",
                    self.session_id, rec.round_no, rec.question_id,
                    self.swaps_used, config.MAX_SWAP_PER_SESSION, rec.swap_reason,
                    judge_band, r_band, self.stage_idx, self.stage_used)

    def _settle_round(self, rec: RoundRecord, action: str, attempt: AttemptRecord) -> None:
        """本轮收尾判定：唯一决定 phase 的地方之一。"""
        if action == "close":
            rec.open = False
            rec.closed_at = time.time()
            self.phase = PHASE_NEXT
        else:
            self.phase = PHASE_ANSWER
        logger.info(
            "sid=%s round=%d attempt=%d r=%.1f rerank_ok=%s action=%s "
            "follow_ups=%d/%d degrade=%d/%d phase->%s",
            self.session_id, rec.round_no, attempt.attempt_no,
            attempt.reranker_score, attempt.reranker_ok, action,
            rec.follow_ups_used, config.MAX_FOLLOW_UP,
            rec.degrade_used, config.MAX_DEGRADE, self.phase)

    def round_status(self) -> dict:
        """给 SSE 的 done / round_end 事件用。"""
        rec = self.current_round
        if rec is None or not rec.attempts:
            return {"action": "close", "follow_up": False, "round_open": False,
                    "attempts": 0, "follow_ups_used": 0, "degrade_used": 0,
                    "reranker_score": None, "reranker_ok": True,
                    # 换题的三件套，见下面那条注释 —— 键恒在，消费方不用判空
                    "swapped": False, "swaps_used": self.swaps_used,
                    "swaps_left": max(0, config.MAX_SWAP_PER_SESSION - self.swaps_used)}
        last = rec.attempts[-1]
        return {
            "action": last.action,
            # follow_up 完全由 action 推导 —— 不是另算一个可能对不上的谓词。
            # ⚠️ swap 必须一并算作"不追问"：换题是作废整轮，前端要是把它读成
            #    follow_up=true，就会让考生再答一次一道已经作废的题。
            "follow_up": last.action not in ("close", BAND_SWAP),
            "round_open": rec.open,
            "attempts": len(rec.attempts),
            "follow_ups_used": rec.follow_ups_used,
            "degrade_used": rec.degrade_used,
            "reranker_score": last.reranker_score,
            "reranker_ok": last.reranker_ok,
            # ---- 判档的两个源 + 融合结果（加法，前端可忽略）----
            # 给前端 / 4 号 / 3 号一个「这次为什么这么问」的可解释出口。
            # judge_band 为 None = LLM 没判出来，**不是**判成降级。
            "reranker_band": last.reranker_band,
            "judge_band": last.judge_band,
            "judge_ok": last.judge_ok,
            "judge_why": last.judge_why,
            "fuse_rule": last.fuse_rule,
            "band_disagree": bool(last.judge_ok and last.judge_band
                                  and last.judge_band != last.reranker_band),
            # ---- 换题（加法，前端可忽略）----
            # swapped=true 表示这一轮**已被作废**：考生答的这道题不占 10 题名额、
            # 不进评分、不进走势。前端可拿它显示一句"这道题已换掉"。
            # 键恒在（哪怕从没换过）—— 与 rag_meta / dim1_labels 同一条原则：
            # 消费方不用写"先判有没有这个键"两种情况。
            "swapped": rec.swapped,
            "swaps_used": self.swaps_used,
            "swaps_left": max(0, config.MAX_SWAP_PER_SESSION - self.swaps_used),
        }

    # ---------- 结束与评分 ----------
    def finish(self) -> dict:
        """幂等：第二次调用直接返回缓存，不再调 LLM。"""
        if self._result is not None:
            logger.info("sid=%s /finish 命中缓存", self.session_id)
            return dict(self._result, cached=True)

        t0 = time.time()
        scorable = [r for r in self.rounds if r.attempts]
        failed_rounds: list[int] = []

        # 每轮一次五维评分；4 路并发（一轮一次 LLM 调用，串行太慢）
        def _score(rec: RoundRecord) -> tuple[RoundRecord, dict, Optional[str]]:
            # 每一轮的失败都就地捕获成 (data={}, err)，绝不让异常穿出线程池 ——
            # 一轮评分挂掉不该让整场面试拿不到结果
            try:
                if self.scorer.llm is None:
                    return rec, {}, "评分器未初始化（没有可用的 LLM）"
                data, err = self.scorer.llm.score_round({
                    "question": rec.question,
                    "difficulty": rec.difficulty,
                    "stage": rec.stage,
                    # 题型决定第一维的标签（行为素质题 = 岗位胜任力关联度）。
                    # 只影响喂进去的 prompt 文字，不影响分的键。
                    "category": rec.category,
                    "base_points": qb.truncate(rec.base_points, config.POINT_TRUNCATE),
                    "adv_points": qb.truncate(rec.adv_points, config.POINT_TRUNCATE),
                    "qa_block": rec.qa_block(),
                    # 传摘要而不是裸分：reranker 失败时它会明说「不可用」，
                    # 而不是把默认分 50 当成真实结果递下去。
                    "reranker_note": rec.reranker_note(),
                })
                return rec, data, err
            except Exception as e:
                logger.exception("sid=%s round=%d 评分线程异常", self.session_id, rec.round_no)
                return rec, {}, f"{type(e).__name__}: {e}"

        if scorable:
            with ThreadPoolExecutor(max_workers=min(4, len(scorable))) as pool:
                for rec, data, err in pool.map(_score, scorable):
                    if err or not data.get("five_dim"):
                        rec.scored = False
                        rec.score_error = err or "模型未返回可解析的五维分"
                        failed_rounds.append(rec.round_no)
                    else:
                        rec.five_dim = data["five_dim"]
                        rec.comment = data.get("comment", "")
                        rec.errors = data.get("errors", [])
                        rec.scored = True

        # 汇总（修 #5：失败轮次不进均分，且**不伪装成 0 分**）
        dims: dict[str, list[float]] = {d: [] for d in config.DIMENSIONS}
        for rec in scorable:
            if not rec.five_dim:
                continue
            for d in config.DIMENSIONS:
                if d in rec.five_dim:
                    dims[d].append(rec.five_dim[d])

        avg = {d: (round(sum(v) / len(v), 2) if v else None) for d, v in dims.items()}
        has_any = any(v is not None for v in avg.values())
        weights = self.weights
        total = None
        if has_any:
            usable = {d: v for d, v in avg.items() if v is not None}
            wsum = sum(weights[d] for d in usable)
            # 权重归一化：某个维度整体缺失时，不能拿 0 去顶
            total = round(sum(usable[d] * weights[d] for d in usable) / wsum, 2) if wsum else None

        notes: list[str] = []
        if not scorable:
            notes.append("没有有效问答轮次")
        if failed_rounds:
            notes.append(f"{len(failed_rounds)} 轮评分失败：{failed_rounds}")
        deg = sum(1 for r in scorable if r.degrade_used > 0)
        if deg:
            notes.append(f"{deg} 轮触发降级引导")
        if self.swaps_used:
            # 用户要求报告里注明。措辞只陈述事实与原因，不带评价 —— 换题是
            # 「这题不该问他」，不是「他答砸了」，报告里不能读成后者。
            # 注意这里**不会**连带触发下面那条"只问了 N 题"：换题不占名额，
            # 他最后还是答满了 10 题，那条 note 不该出现。
            why = "；".join(r.swap_reason for r in self.swapped_rounds if r.swap_reason)
            notes.append(f"本场换过 {self.swaps_used} 题（原因：{why or '考生表示不熟悉'}），"
                         f"被换掉的题不计入 {config.TOTAL_QUESTIONS} 题")
        if self.questions_asked < config.TOTAL_QUESTIONS:
            notes.append(f"只问了 {self.questions_asked}/{config.TOTAL_QUESTIONS} 题")

        # 知识图谱 / RAG 的降级也如实点名 —— 但只在**失败**时提。
        # 「关掉」是配置，「失败」是故障，两者混为一谈会让 3 号误以为
        # 盲区地图是空的而不是没生成。
        kg_st, rag_st = kgmod.kg_status(), ragmod.rag_status()
        if config.A11_KG and not kg_st["kg_ready"]:
            notes.append(f"知识图谱不可用（{kg_st['kg_error']}），未做出题避重与深挖")
        if config.A11_RAG and not rag_st["rag_ready"]:
            notes.append(f"RAG 不可用（{rag_st['rag_error']}），本轮无参考片段")

        # 避重阶梯各用了多少次 —— 日后调 KP_OVERLAP_THRESHOLD 的唯一依据
        pick_levels: dict[str, int] = {}
        for r in self.rounds:
            if r.pick_level:
                pick_levels[r.pick_level] = pick_levels.get(r.pick_level, 0) + 1

        # 整场第一维的**构成**。一场里行为素质题与技术题混着抽时，
        # five_dim_avg["技术水平"] 是**两种东西的平均**：算法本身没错（第一维那一格的
        # 权重不变，文档也没给行为素质题单独一套权重），但不加标注会被 3 号读成
        # 单一量 —— 所以这里如实给出两种标签各占几轮。
        #
        # ⚠️ 为什么不写进 notes：notes 会经 _write_evaluation 进 FINAL_SUMMARY 的
        #    【需要说明的情况】，进而污染**给考生看的那段评语**。这是内部口径说明，
        #    只该给 3 号，所以只进 raw。
        # ⚠️ 固定两个键（计数可能为 0），而不是「只出现过的那些」：与 rag_meta
        #    同一条原则 —— 键恒在，3 号的解析不用判空。
        dim1_labels: dict[str, int] = {lab: 0 for lab in config.dim1_labels()}
        for r in scorable:
            if r.five_dim:
                dim1_labels[r.dim1_label] += 1

        evaluation = self._write_evaluation(avg, notes)

        self.finished_at = time.time()
        self.phase = PHASE_DONE

        raw = {
            "session_id": self.session_id,
            "job": self.job,
            "candidate_intro": self.candidate_intro,
            "started_at": round(self.created_at, 3),
            "finished_at": round(self.finished_at, 3),
            "duration_sec": round(self.finished_at - self.created_at, 1),
            "total_questions": config.TOTAL_QUESTIONS,
            "questions_asked": self.questions_asked,
            "chat_turns": len(self.transcript),
            "weights": weights,
            "asked_pids": list(self.asked_pids),
            "rounds": [r.to_raw() for r in self.rounds],
            # 修 #5：失败轮次在这里点名，且**不计入** five_dim_avg（绝不伪装成 0 分）
            "scoring_failed_rounds": failed_rounds,
            "scoring": {
                "rounds_total": len(scorable),
                "rounds_scored": len(scorable) - len(failed_rounds),
                "rounds_failed": len(failed_rounds),
            },
            "degraded_rounds": deg,
            # ---- 换题（加法）----
            # 被换掉的题**不在 rounds 里**（所以不进评分、不进 five_dim_avg、
            # 不进 asked_pids 之外的任何流程）。这里单列出来，是为了让报告能回答
            # "换掉了哪道、为什么" —— 只给计数的话，一场换过题的报告就和一场没换过的
            # 长得一模一样，事后想复盘换题规则准不准就无从下手。
            # ⚠️ 复用 RoundRecord.to_raw()、而不是手搓一份结构：键名与 rounds[] 逐字
            #    相同（"round"/"题目ID"/"exchanges"…），3 号读报告时不用分两套；
            #    更要紧的是 to_raw() 已经是**筛过的**（rag_refs / base_points /
            #    adv_points / raw 都不在里面），手搓一份等于把这道筛子重新做一遍，
            #    迟早会漏。
            #    唯一多出来的是 swap_reason：换题的理由只在这里、不在别处。
            #    （`swapped` 两个表里都有 —— rounds[] 恒 false，这里恒 true。
            #      下面仍**显式**写死 True 作第二道保险：万一将来有别的路径往
            #      swapped_rounds 里塞轮次却忘了设 rec.swapped，报告也不会说谎。）
            # ⚠️ 这些轮的 five_dim / scored 全是 None/False（它们**没有被评分**）
            #    —— 这是有意的：换掉的题不该有分，"没有分"与"0 分"必须能分开。
            "swaps_used": self.swaps_used,
            "swapped_rounds": [
                dict(r.to_raw(), swapped=True, swap_reason=r.swap_reason)
                for r in self.swapped_rounds
            ],
            "notes": notes,
            # ---- 知识图谱 / RAG（加法；不参与任何评分、不进任何阈值）----
            # ⚠️ blindspots 必须在上面那个评分 pool.map **之后**才算 ——
            #    它的 five_dim 直接来自 rec.five_dim。这是顺序硬约束。
            "kg_error": kg_st["kg_error"],
            "rag_error": rag_st["rag_error"],
            "coverage": {
                "kp_seen": self.cov.size,
                "pick_levels": pick_levels,
                "kg_available": self.kg is not None,
                "rag_available": self.rag is not None,
            },
            # 第一维的题型构成（固定两键）。five_dim_avg["技术水平"] 混型时要看这里。
            "dim1_labels": dim1_labels,
            "blindspots": blindspot.diagnose(self.rounds, self.kg),
        }

        envelope = {
            # ---- 顶层：与旧接口完全一致的字段，前端零改动 ----
            "session_id": self.session_id,
            "job": self.job,
            "five_dim_avg": avg,
            "total_score": total,
            "total_score_100": (round(total / 5 * 100, 1) if total is not None else None),
            "weights": config.weights_text_for(self.job),
            "summary": evaluation,
            "rounds": len(scorable),
            # ---- 新增：给 3 号评估用的完整明细 ----
            "partial": (not has_any) or bool(failed_rounds),
            "notes": notes,
            "raw": raw,
            "cached": False,
        }
        self._result = envelope
        logger.info("sid=%s finish rounds=%d scored=%d failed=%d total=%s 耗时 %.1fs",
                    self.session_id, len(scorable),
                    len(scorable) - len(failed_rounds), len(failed_rounds),
                    total, time.time() - t0)
        return envelope

    def result(self) -> Optional[dict]:
        """/result/{sid} 用：已结束就返回与 /finish 完全一致的载荷，否则 None。"""
        return dict(self._result, cached=True) if self._result is not None else None

    def _write_evaluation(self, avg: dict, notes: list[str]) -> str:
        if not any(v is not None for v in avg.values()):
            return "本场面试没有产生可评分的数据，无法给出评价。" + (
                "（" + "；".join(notes) + "）" if notes else "")

        # ⚠️ 第一维用**本题型的标签**（行为素质题 = 岗位胜任力关联度）而不是键名。
        #    否则总结模型看到的仍是「行为素质题那一轮：技术水平3.5」—— 正是本次
        #    要修的那个错。只影响这段自由文本，不涉及任何契约字段。
        d0 = config.DIMENSIONS[0]
        scores_text = "\n".join(
            f"  第 {r.round_no} 题【{r.stage}/{r.difficulty}】"
            + (", ".join(f"{(r.dim1_label if d == d0 else d)}{v}"
                         for d, v in r.five_dim.items()) if r.five_dim else "未评分")
            + (f"｜评语：{r.comment}" if r.comment else "")
            for r in self.rounds if r.attempts)
        topics = ", ".join([kp["title"] for r in self.rounds
                            for kp in r.knowledge_points][:10]) or "（未记录）"
        extra = ("\n【需要说明的情况】" + "；".join(notes) + "\n") if notes else "\n"

        user = FINAL_SUMMARY.safe_substitute(
            job=self.job, scores=scores_text, topics=topics,
            weights_text=config.weights_text_for(self.job), extra=extra)
        try:
            return self.llm.chat(SYSTEM_SUMMARY, [{"role": "user", "content": user}],
                                 temperature=config.LLM_TEMPERATURE)
        except Exception as e:
            logger.exception("sid=%s 生成面试评价失败", self.session_id)
            return f"（面试评价生成失败：{type(e).__name__}: {e}）"


# ============================================================
# 人设加载
# ============================================================
_PERSONA_CACHE: dict[str, str] = {}


def load_persona(job: str) -> str:
    """读 app/personas/<岗>.md；读不到就退回一句兜底人设，不让面试开不起来。"""
    if job in _PERSONA_CACHE:
        return _PERSONA_CACHE[job]
    fname = config.PERSONA_FILE_MAP.get(job)
    text = ""
    if fname:
        path = os.path.join(config.PERSONA_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except Exception as e:
            logger.warning("人设文件读取失败 %s：%s", path, e)
    if not text:
        text = "你是一位资深技术面试官，风格严厉但公正，直击原理，不绕弯子，喜欢追问到底。"
    _PERSONA_CACHE[job] = text
    return text
