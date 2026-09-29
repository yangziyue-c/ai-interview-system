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
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Generator, Optional

from app import config
from app.core import blindspot, question_bank as qb
from app.core import asr as asrmod
from app.core import body_language as bodymod
from app.core import kb as kbmod
from app.core import kg as kgmod
from app.core import objective as objectivemod
from app.core import rag as ragmod
from app.core import resume as resumemod
from app.core import summary_guard as sg
from app.core.llm import get_llm
from app.core.prompts import (
    ACK_REPLIES, ACTION_DESC, CLOSE_DIRECTIVE, DEEPEN_BLOCK, DEEPEN_BLOCK_EMPTY,
    DEGRADE_DIRECTIVE,
    FINAL_SUMMARY, HINT_BLOCK, HINT_BLOCK_CLOSE, HINT_BLOCK_EMPTY,
    HINT_REQUEST_FALLBACK, HINT_REQUEST_REPLY,
    INTERVIEWER_SYSTEM, INTRO_BLOCK, INTRO_SNIPPET_MAX, KB_ASIDE,
    NO_INFO_CLOSE_REPLIES, NO_INFO_DEGRADE_REPLIES,
    NO_INFO_WITH_HINT_REPLIES,
    OPENING_LINE, OPENING_LINE_INTRO, OPENING_LINE_TONE, PERSONA_STYLE_LABELS,
    PROBE_BLOCK, RAG_BLOCK,
    RAG_BLOCK_EMPTY,
    RAG_BLOCK_LEGACY, RAG_KB_BLOCK, RAG_KB_BLOCK_EMPTY, RAG_KB_BLOCK_LEGACY,
    RESUME_BLOCK, ROUND_CONTEXT, SESSION_MEMORY_BLOCK, SWAP_LINE,
    SYSTEM_SUMMARY, WRAPUP_NUDGE,
    persona_style_block, persona_style_directive,
)
from app.core.scoring import get_scorer, weighted_llm_score
from app.logging_conf import get_logger

logger = get_logger(__name__)

# 两块素材的**新/旧契约文本**由 `A11_RAG_TASK` 选：默认（"1"）用新文本（给了「被允许的用法」），
# "0" 逐字回到改动前的「只作背景参考：不要照念、不要向考生透露、不要拿来出新题」。
# 选择放在这里而不是 `prompts.py`，是为了让 `prompts.py` 保持**纯模板**（不 import config）
# —— 冒烟要能把两套文本**各自直接渲染**出来比对，那是「开关全关 ⇒ 与改动前逐字节相同」的证明。
RAG_BLOCK_ACTIVE = RAG_BLOCK if config.RAG_TASK else RAG_BLOCK_LEGACY
RAG_KB_BLOCK_ACTIVE = RAG_KB_BLOCK if config.RAG_TASK else RAG_KB_BLOCK_LEGACY

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
    action: str                      # 由这次回答决定的动作 L1/L2/L3/degrade/close
    hint: Optional[str]              # 因此要问出的追问（close 时为 None）
    # 追问规划（加法）。action 说明“哪一级”，这三个字段说明“具体追什么”。
    # to_raw() 只暴露目标和类型，不额外展开知识库/得分点正文。
    probe_level: str = ""
    probe_target: str = ""
    probe_kind: str = ""
    # 判为**未**命中的得分点。给评分模型复核用 —— reranker 的假阴性
    # （考生用自己的话讲对了）只有把未命中的点也摆出来，模型才有机会翻案。
    base_misses: list[str] = field(default_factory=list)
    adv_misses: list[str] = field(default_factory=list)
    interviewer_reply: str = ""      # 面试官实际说的话
    llm_ok: bool = True
    # False = 这段回答没有提供可判分的有效信息（“不知道”、乱码等）。
    # 它仍保留原文和动作，但不再被后续话术当作“答到了一点”。
    effective: bool = True
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
    # ---- 语音作答的表达指标（加法；文字作答时恒为 SPEECH_EMPTY 那个形状）----
    # 由 asr.derive_speech() 从「净时长 + 段级时间戳 + 转写文本」算出来的一组**数字**，
    # 全部键恒在、空值用 None。转写原文不进这里（它已作为 answer 存在）。
    speech: dict = field(default_factory=lambda: dict(asrmod.SPEECH_EMPTY))
    # Camera pose summary for this answer. Numeric/closed fields only; no video,
    # image, raw landmarks or free-form model output is retained here.
    body_language: dict = field(default_factory=lambda: dict(bodymod.BODY_EMPTY))
    # 覆盖率怎样算出来的。`reranker_score` 是覆盖率信号，不是技术正确性结论；
    # 这两个键让报告能区分旧版整段匹配与新版「整段 + 句窗取最大」。
    coverage_method: str = ""
    coverage_windows: int = 0

    def match_note(self) -> str:
        """
        这一次回答的覆盖率信号 —— 拼进评分 Prompt 给模型复核。

        只给分数是没用的（「60 分」不告诉模型哪里出了问题）；给命中/未命中**两边**的
        明细，模型才能判断「命中的是真懂还是撞词」「没中的是不是换个说法讲对了」。
        """
        if not self.reranker_ok:
            return "  ↳ 覆盖率信号：reranker 本次不可用，没有匹配结果（请只看回答本身）"
        hit = self.base_hits + self.adv_hits
        miss = self.base_misses + self.adv_misses
        return (f"  ↳ 覆盖率信号 {self.reranker_score:g}/100"
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
            "probe_level": self.probe_level,
            "probe_target": self.probe_target,
            "probe_kind": self.probe_kind,
            "interviewer_reply": self.interviewer_reply,
            "llm_ok": self.llm_ok,
            "effective": self.effective,
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
            # ---- 语音作答的表达指标（加法；键恒在）----
            # 一组纯数字：净时长 / 语速 / 长停顿 / 填充词。没有语音时
            # used=false、其余为 None —— 「没用语音」与「语速是 0」必须能分开。
            "speech": self.speech,
            "body_language": self.body_language,
            "coverage_method": self.coverage_method,
            "coverage_windows": self.coverage_windows,
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
    # 本轮的起点在全局 transcript 中的下标。面试官生成只看这一轮，
    # 防止上一题的 assistant 回复污染新题。
    transcript_start: int = 0
    follow_ups_used: int = 0
    degrade_used: int = 0
    # “好的 / 给点提示”这类辅助轮。不计作一次回答，不计分，但有上限，
    # 防止考生连续发“好的”让系统无限等待。
    assist_used: int = 0
    # 其中已经真正给过几次提示。给过提示后再说“不知道”，现场应直接收题，
    # 不应把同一提示再复述一遍。
    hint_used: int = 0
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
    # ⚠️ 知识库检索到的**片段原文**（来自 `ai-reference` 那 6 份 md，不是题库）。
    #    与 rag_refs 同一条纪律：repr=False 且**绝不进 to_raw()**。
    #    这一份比 rag_refs 更需要小心：它按**本轮检索词**检索（赛题 6.2b），
    #    默认检索词是**考生刚说的那段话**；另有一档（`A11_RAG_KB_QUERY_SRC=miss`，
    #    保留的实验档）用**他没答到的得分点**，那一档命中的极可能就是本题标准答案
    #    所在的章节 ⇒ **无论哪一档**都不许露给前端。
    kb_refs: list[dict] = field(default_factory=list, repr=False)
    # 可序列化的白名单元信息，四个键**结构上不可能夹带文本**。
    #
    # 默认值就带齐四个键、而不是空 dict：RAG **默认是关的**，若关掉时给 {}，
    # 3 号就得写「先判 rag 是不是空、再取 rag.used」两种情况 —— 与
    # blindspot 那条「键名完全不变，解析逻辑不用分两种情况写」是同一条原则。
    # 空 dict 只该表示「这段数据不存在」，而这里它存在、只是没启用。
    rag_meta: dict = field(default_factory=lambda: {
        "used": False, "hit_ids": [], "layers": [], "distances": [],
    })
    # 知识库那一路的元信息。**键名与 rag_meta 刻意不同**：知识库没有「层级」，
    # 硬套 layers/distances 会误导读的人；改成 sources/scores，形状一一对应，
    # 3 号那边的解析逻辑可以照搬。
    kb_meta: dict = field(default_factory=lambda: {
        "used": False, "hit_ids": [], "sources": [], "scores": [],
    })
    # ---- 语音作答的表达指标（加法，有默认值）----
    # 轮次级：取**最后一次带语音的回答**的那一份（追问后再说话，以最新为准）。
    # 与 exchanges[].speech 同一份数据 —— 这里是为了让「按轮看表达」不用先遍历
    # exchanges。形状与 SPEECH_EMPTY 逐键相同，文字作答时 used=false。
    speech: dict = field(default_factory=lambda: dict(asrmod.SPEECH_EMPTY))
    # Latest camera summary for this round. Independent from speech and only
    # used as a bounded weak signal after the answer has been scored.
    body_language: dict = field(default_factory=lambda: dict(bodymod.BODY_EMPTY))
    # 评分结果（finish 时填）
    five_dim: Optional[dict] = None
    code_check: dict = field(default_factory=lambda: {
        "applicable": False, "correct": None, "note": "",
    })
    # 逐维评分依据：reason / evidence / confidence + missing_points /
    # misconceptions。旧五维分与权重完全不变，这里只是让报告可复核。
    score_detail: dict = field(default_factory=dict)
    objective_detail: dict = field(default_factory=dict)
    body_score_adjustment: dict = field(default_factory=dict)
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

        每次回答后面都挂上**那一次**的覆盖率信号明细（本轮改）—— 而不是只在末尾
        给一个笼统的总分。理由：评的是整轮，而「应变能力」看的正是首答与追问后
        的落差；只给最后一次的分数，会把这个落差整个抹平。
        """
        lines = []
        for i, a in enumerate(self.attempts):
            label = "第 1 次回答（无提示）" if i == 0 else f"第 {i + 1} 次回答"
            lines.append(f"【{label}】「{a.answer}」")
            lines.append(a.match_note())
            if a.action != "close":
                lines.append(
                    "【本轮追问规划】"
                    f"层级：{a.probe_level or a.action}｜"
                    f"类型：{a.probe_kind or '未标注'}｜"
                    f"目标：{a.probe_target or a.hint or '未标注'}"
                )
            if a.action != "close" and (a.interviewer_reply or a.hint):
                lines.append(f"【面试官追问】{a.interviewer_reply or a.hint}")
        return "\n".join(lines) or "（本轮没有有效回答）"

    def reranker_note(self) -> str:
        """
        给评分模型的一行覆盖率摘要。

        reranker 失败时**明说用不了** —— 以前失败会返回默认 50 分，那个假分被
        当成「客观命中 50」喂进评分 Prompt，等于凭空空降一个中等分（它既不真
        也不假，模型无从分辨）。宁可不给，也不给一个假的。
        """
        if not self.attempts:
            return "本轮没有有效回答。"
        if not self.last_ok:
            return ("reranker 本次不可用，没有覆盖率信号 —— "
                    "请完全依据上面的实际问答判断，不要参考任何覆盖率数字。")
        if len(self.attempts) == 1:
            return f"本次回答覆盖率 {self.last_score:g}/100。"
        traj = " → ".join(f"{a.reranker_score:g}" for a in self.attempts)
        return (f"各次回答覆盖率（满分 100）：{traj}。"
                "注意看**首答到追问之后的变化** —— 那才是「应变能力」的主要依据。")

    # ---------- 表达：客观测量（赛题 3b）----------
    # 这一段是「**不用 ASR 也能算**」的那两条（用时 vs 建议用时、答题长度）+
    # 由 ASR 指标拼出的那一段。设计出处：多模态接入方案.md §5.1 / §5.2。
    @property
    def used_sec(self) -> Optional[float]:
        """
        整轮用时（秒）：出题 → 本轮收尾。没收尾（还在追问中）时为 None。

        ⚠️ **它不是「考生说了多久」**。这条链路是同步 SSE，这段时间里混着
        「reranker 打分 + 判档 + 生成面试官回复」的服务端耗时（实测数秒级）。
        拿它冒充说话时长会得出一个离谱的语速 —— 语速只能用 ASR 的
        `duration_ms`（见 speech）。这里就按「整轮耗时」如实用。
        """
        if self.closed_at is None:
            return None
        return round(self.closed_at - self.asked_at, 1)

    @property
    def est_sec(self) -> int:
        """题库给的「建议用时(分)」换算成秒。0 = 题库没给这一题（不是 0 秒的基准）。"""
        return int(self.est_minutes or 0) * 60

    @property
    def over_ratio(self) -> Optional[float]:
        """
        用时 ÷ 建议用时。>1 = 超时，<1 = 提前答完。
        None = 数据不足（没建议用时，或本轮还没收尾）—— **不是 0**。
        """
        u, e = self.used_sec, self.est_sec
        if u is None or e <= 0:
            return None
        return round(u / e, 2)

    def pace_note(self) -> str:
        """
        给评分模型的「表达客观测量」摘要 —— 与 `reranker_note()` 同一个位置、
        同一套写法（一句事实 + 几条使用规则），只是量的东西不同。

        为什么要有它：五维里的「沟通表达 / 应变能力」本来只能靠模型读文本印象，
        现在给它一组**测出来的数**（用时 / 语速 / 停顿 / 填充词），这一维从
        「凭印象」变成「有数的判断」。**评分模型不改、五维结构不改、权重不改。**

        ⚠️ 三条使用规则与 reranker_note 那三条同构（划边界 / 承认它会错 /
           冲突以内容为准），而且这里还多一层必要：**这些数字天生偏向"鼓励快"**。
           不写死「答得快不等于答得好」，一个求稳的模型很容易把「30 秒答完」
           读成「干脆利落」。所以规则写在返回值里，跟着数据一起进 prompt。
        """
        lines: list[str] = []
        u, e = self.used_sec, self.est_sec
        if u is None:
            lines.append("本轮尚未收尾，没有用时数据。")
        elif e > 0:
            lines.append(
                f"整轮用时 {u:.0f} 秒（出题到本轮收尾），本题库建议用时 "
                f"{e / 60:.0f} 分钟（={e} 秒），实际约为建议的 {u / e * 100:.0f}%。")
        else:
            lines.append(
                f"整轮用时 {u:.0f} 秒（出题到本轮收尾）；"
                "本题库没给建议用时，**没有基准可比**，不要自行假设快慢。")

        sp = self.speech or asrmod.SPEECH_EMPTY
        if sp.get("used"):
            bits = []
            if sp.get("duration_ms") is not None:
                bits.append(f"净说话 {sp['duration_ms'] / 1000:.1f} 秒")
            if sp.get("chars_per_min") is not None:
                bits.append(f"语速 {sp['chars_per_min']:.0f} 字/分")
            if sp.get("pauses") is not None:
                bits.append(f"长停顿（>{asrmod.PAUSE_MIN_MS / 1000:g} 秒）"
                            f"{sp['pauses']} 次")
            if sp.get("filler_rate") is not None:
                bits.append(f"填充词（嗯/那个/然后…）{sp['fillers']} 个、"
                            f"占字数 {sp['filler_rate'] * 100:.1f}%")
            # 韵律（2026-09-25 加法）。⚠️ **只报相对量，不报 `loudness` 的绝对值**：
            #    RMS 的绝对水平由麦克风增益 / 说话距离 / 房间混响决定 —— 同一个人
            #    换台机器能差几倍。把它当数喂进 prompt，等于递过去一个「看起来像
            #    测量值、其实跨设备不可比」的数，模型一定会拿它推音量大小。
            #    绝对量留在 `/asr` 里（诊断与前端展示用），不进评分 prompt。
            if sp.get("loudness_cv") is not None:
                bits.append(f"段间音量起伏（变异系数）{sp['loudness_cv']:.2f}")
            if sp.get("tail_ratio") is not None:
                bits.append(f"收尾音量/全段均值 {sp['tail_ratio']:.2f}")
            if sp.get("pitch_variation") is not None:
                bits.append(f"音高起伏（对数标准差）{sp['pitch_variation']:.3f}")
            lines.append("本次为**语音作答**（转写模型 %s）：%s。"
                         % (sp.get("asr_model") or "ASR", "，".join(bits) or "（无可比值）"))

            # 情感分布与融合档位：**单起一段**，因为这里有两个必须现场说清的口径
            # （模型是什么料训的、档位是谁算的），混在上一行里说不下。
            emo = sp.get("emotion_dist") or {}
            if emo:
                try:
                    ranked = sorted(emo.items(), key=lambda kv: -float(kv[1]))
                except (TypeError, ValueError):
                    ranked = list(emo.items())
                lines.append(
                    "情感模型（SER）给出的分布：%s。⚠️ 这是**语音情感**，"
                    "**不是自信度**；该模型在英语、表演式情感语料上训练，"
                    "**在中文上没有标注数据可验证**，且实测对平淡的中文语音也"
                    "给出高置信（3 段合成中文语音全部判 happy、置信 0.71~0.95）"
                    "—— 即它在域外输入上**过度自信**。所以它在这里**只作原始观察**，"
                    "**不参与**下面那个档位的计算；**禁止**据此判断考生"
                    "「当时是什么心情」。"
                    % "，".join(f"{k} {float(v) * 100:.0f}%" for k, v in ranked))
            band = sp.get("confidence")
            if band:
                # ⚠️ 只喂韵律两指标 —— 与 `derive_speech` 里那次调用**必须同一套参数**，
                #    否则依据句会与实际算出的档位对不上（那是最难查的一类错）。
                _b, basis = asrmod.confidence_band(sp.get("loudness_cv"),
                                                   sp.get("tail_ratio"))
                lines.append(
                    "「语气自信度」融合档位：**%s**（依据：%s）。"
                    "⚠️ 这个档位是**用上面那些数按写死的规则算出来的**，"
                    "既不是模型输出，也不是心理测量意义上的自信度量表；"
                    "**只由音量是否平稳、收尾是否收得住这两件事决定**。"
                    "（音量的**绝对**大小、语速、情感模型的标签，都不参与 —— "
                    "前两者跨设备/跨习惯不可比，后者在中文上不可信。）"
                    % (band, "；".join(basis) or "无可用信号"))
        else:
            lines.append("本次为**文字作答**，没有语速/停顿/填充词数据"
                         "（语音未启用，或前端没走 /asr）—— 不要凭空猜这些数。")

        if sp.get("baseline_used"):
            parts = ["本次表达数据已与本人前几轮的个人基线做相对比较"]
            if sp.get("baseline_chars_per_min") is not None:
                parts.append("个人基线语速约 %.0f 字/分"
                             % sp["baseline_chars_per_min"])
            if sp.get("baseline_deviation") is not None:
                parts.append("综合相对偏差 %.2f" % sp["baseline_deviation"])
            lines.append("；".join(parts) + "。这只用于解释变化，不代表好坏。")

        body_note = bodymod.prompt_note(self.body_language)
        if body_note:
            lines.append(body_note)

        # 使用规则。前三条恒在（划边界 / 快≠好 / 冲突以内容为准），
        # 第四条随**数据的有无**而变 —— 因为「有多弱」这件事本身取决于有没有语音。
        rules = [
            "使用规则：",
            "- 它**只**与「沟通表达」「应变能力」有关，与第一维、逻辑思维、"
            "岗位匹配度**无关**，不要拿它推那三维。",
            "- **答得快不等于答得好，答得慢不等于答得差**：语速快可能只是说得浅，"
            "语速慢可能是在讲细节；题目难度与个人说话习惯都会影响这些数字。"
            "**禁止**因为用时短就给高分、或因为用时长/停顿多就判低分。",
            "- 只有当它与你**从问答内容**得出的判断方向一致时，才可以引用它当旁证；"
            "若两者冲突，**以内容为准**，并在 errors 里写明原因。",
        ]
        if not sp.get("used"):
            rules.append(
                "- 本次没有语速/停顿数据，整轮用时这一条**更弱**：那段时间里还混着"
                "服务端打分与生成回复的耗时，不要把它当成考生思考或说话的时长。")
        # 第五条同样是**条件式**（只有语音作答且算出了档位才出现）——
        # ⚠️ 前三条共用规则一个字都不能改：它们是 16 场已归档真 LLM 对照的输入，
        #    而那些对照全是文字作答。`sp.get("used")` 为假时这一条不会加，
        #    所以文字作答的 pace_note **逐字节不变**（这条约束有基线断言守着）。
        if sp.get("used") and sp.get("confidence"):
            rules.append(
                "- 「语气自信度」那个档位**天生比别的数字更容易被误用**：它已经是一个"
                "**结论**，不是一个测量值。**禁止**因为它是「偏高」就给高分、"
                "因为「偏低」就扣分 —— 它与「沟通表达」有关，**与第一维、逻辑思维、"
                "岗位匹配度无关**。只在它与内容判断方向一致时当旁证，冲突以内容为准。")
        if body_note:
            rules.append(
                "（摄像头只提供可解释的上半身姿态弱信号；不得推断情绪、"
                "性格、紧张、诚实或自信，也不得据此改变技术水平、逻辑思维、"
                "岗位匹配度。）")
        else:
            rules.append("（表达分析只做语音与文本，**不做**摄像头与肢体语言。）")
        lines.append("\n".join(rules))
        return "\n".join(lines)

    @property
    def reranker_5(self) -> Optional[float]:
        """
        把 0-100 的覆盖率归一到五维的 0-5 量纲（0→0、100→5）。
        reranker 失败或没有回答时为 None —— 不是 0。
        """
        if not self.attempts or not self.last_ok:
            return None
        return round(self.last_score / 100 * 5, 2)

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
            "code_check": self.code_check,
            "score_detail": self.score_detail,
            "objective_detail": self.objective_detail,
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
            # ---- 表达：客观测量（加法）----
            # 用时那三条是**派生**的（asked_at/closed_at/est_minutes 本来就在上面
            # 这几行里），在这里给出来只是免得 3 号 和前端各算一遍、还算岔了。
            # ⚠️ used_sec 是「整轮耗时」，不是「说话时长」（混着服务端耗时）——
            #    语速/停顿只在 speech 里，且只可能来自 ASR。
            "used_sec": self.used_sec,
            "est_sec": self.est_sec,
            "over_ratio": self.over_ratio,
            "speech": self.speech,
            "body_language": self.body_language,
            "body_score_adjustment": self.body_score_adjustment,
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
            # ⚠️ self.kb_refs 同样**不在这里**（理由同上，而且更硬：
            #    它按**本轮检索词**检索，默认就是**他没答到的得分点** ——
            #    命中的极可能就是**本题答案所在的那一章节**）。
            "rag_kb": self.kb_meta,
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
            "assist_used": self.assist_used,
            "hint_used": self.hint_used,
            "scored": self.scored,
            "score_error": self.score_error,
        }


# ============================================================
# 本轮动作决策（纯函数，唯一决策点）
# ============================================================
# 档位常量：三级追问 + 降级。
BAND_L3, BAND_L2, BAND_L1, BAND_DEGRADE = "L3", "L2", "L1", "degrade"
# 第 4 个档：**不是深浅判断，是类别判断** —— "这个方向他从没接触过"。
# 它必须进 _BAND_DEPTH，否则 fuse_bands 开头的白名单检查会把它当"没判出来"丢回
# reranker（那就永远换不了题了）。深度给 -1：语义上它比 degrade 还浅 ——
# degrade 是"这题他没答上来"，swap 是"这题根本就不该问他"。
# 真正决定它不被拿去比大小的是 fuse_bands 里那条提前返回。
BAND_SWAP = "swap"
# 深浅序，融合规则拿它比大小
_BAND_DEPTH = {
    BAND_SWAP: -1, BAND_DEGRADE: 0, BAND_L1: 1, BAND_L2: 2, BAND_L3: 3,
}


def band_of(score: float) -> str:
    """覆盖率（0-100）→ 档位。**判档线只在这里出现一次。**"""
    if score >= config.LEVEL_L3_MIN:
        return BAND_L3
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


# 回答意图分类。现场话术和评分状态都从这里分叉，避免把“好的”和“不知道”
# 当成同一种东西。
ANSWER_EFFECTIVE = "effective"
ANSWER_ACK = "ack"
ANSWER_HINT_REQUEST = "hint_request"
ANSWER_UNKNOWN_DIRECTION = "unknown_direction"
ANSWER_NO_INFO = "no_info"
ANSWER_NONSENSE = "nonsense"

_ACK_PHRASES = (
    "好的", "好", "嗯", "嗯嗯", "明白", "知道了", "收到", "行", "可以",
    "继续", "你说", "是的", "对", "ok", "okay",
)
_HINT_REQUEST_PHRASES = (
    "给点提示", "提示一下", "提醒一下", "能不能提示", "可以提示",
    "没听清", "再说一遍", "什么意思", "怎么答",
    "没理解", "不理解", "换个说法", "解释一下", "题目是什么意思",
)
_UNKNOWN_DIRECTION_PHRASES = (
    "没学过", "没接触过", "没做过", "没用过", "没使用过", "不熟悉", "不了解",
)
_NO_ANSWER_PHRASES = (
    "不知道", "不会", "不清楚", "不懂", "不记得", "忘了", "想不起来",
    "没思路", "答不上来", "跳过",
    "idontknow", "none", "nothing", "skip",
)
# 很短但已经表达了判断/比较，不能按乱码处理。它们可能答错，
# 应该交给评分链路，而不是进入“没答上来”的固定话术。
_SHORT_SUBSTANTIVE_MARKERS = (
    "没区别", "有区别", "不一样", "一样", "相同", "不同",
    "不是", "不能", "可以", "因为", "所以", "更高", "更低",
)
_ASCII_TECH_ALLOW = {
    "java", "jvm", "redis", "mysql", "sql", "http", "https", "tcp", "udp",
    "api", "mvcc", "cas", "aqs", "thread", "lock", "queue", "cache",
    "spring", "docker", "kafka", "rocketmq", "nginx", "linux",
}


def _cjk_chars(s: str) -> str:
    return "".join(ch for ch in (s or "") if "\u4e00" <= ch <= "\u9fff")


def _has_context_overlap(s: str, context: str) -> bool:
    """短文本至少有一个连续二字片段出现在题目/得分点里，才算有话题关联。"""
    if len(s) < 2:
        return False
    grams = {s[i:i + 2] for i in range(len(s) - 1)}
    return any(g in context for g in grams)


def classify_answer(answer: str, record: "RoundRecord") -> str:
    """
    把考生这一句分成“可评分回答 / 确认 / 请求提示 / 没学过 / 不知道 / 乱码”。

    这是现场话术与评分链路共用的入口。拿不准时返回 ANSWER_EFFECTIVE，
    让原有 reranker + LLM 判档处理，绝不在代码层冒充语义判断器。
    """
    if not config.A11_NO_EFFECTIVE_GUARD:
        return ANSWER_EFFECTIVE
    raw = (answer or "").strip()
    s = _norm_answer(raw).lower()
    if not s:
        return ANSWER_NO_INFO

    if s in _ACK_PHRASES:
        return ANSWER_ACK
    if any(p in s for p in _HINT_REQUEST_PHRASES) and len(s) <= 24:
        return ANSWER_HINT_REQUEST
    if any(p in s for p in _UNKNOWN_DIRECTION_PHRASES) and len(s) <= 18:
        return ANSWER_UNKNOWN_DIRECTION
    if any(p in s for p in _NO_ANSWER_PHRASES) and len(s) <= 14:
        if any(m in s for m in ("因为", "所以", "但是", "不过")):
            return ANSWER_EFFECTIVE
        return ANSWER_NO_INFO

    context = _norm_answer(
        (record.question or "") + (record.base_points or "") + (record.adv_points or "")
    ).lower()
    cjk = _cjk_chars(s)
    if cjk:
        if len(cjk) <= 5 and not _has_context_overlap(cjk, context):
            if any(p in cjk for p in _SHORT_SUBSTANTIVE_MARKERS):
                return ANSWER_EFFECTIVE
            return ANSWER_NONSENSE
        return ANSWER_EFFECTIVE

    tokens = re.findall(r"[a-z0-9_+#.]{2,}", s)
    if not tokens:
        return ANSWER_NONSENSE
    known = [t for t in tokens if t in _ASCII_TECH_ALLOW or t in context]
    if len(tokens) == 1 and len(tokens[0]) >= 10 and not known:
        return ANSWER_NONSENSE
    if len(raw) >= 8 and not known and all(len(t) >= 4 for t in tokens):
        return ANSWER_NONSENSE
    return ANSWER_EFFECTIVE


def is_no_effective_answer(answer: str, record: "RoundRecord") -> bool:
    """
    纯代码识别“没有可判分信息”的回答。

    只覆盖高置信度形态：明确不会、极短回答、与当前题面/得分点零关联的乱码。
    它不是答案质量评分器；拿不准时返回 False，仍交给原评分与判档链路。
    """
    return classify_answer(answer, record) in (
        ANSWER_UNKNOWN_DIRECTION, ANSWER_NO_INFO, ANSWER_NONSENSE,
    )


def no_effective_score(record: "RoundRecord") -> dict:
    """无有效回答的确定性覆盖率结果：全部未命中，不调用 reranker。"""
    base_all = qb.split_points(record.base_points)
    adv_all = qb.split_points(record.adv_points)
    return {
        "reranker_score": 0.0,
        "reranker_ok": True,
        "base_hit": [],
        "adv_hit": [],
        "base_miss": list(base_all),
        "adv_miss": list(adv_all),
        "coverage_method": "no_effective_answer",
        "coverage_windows": 0,
    }


_CONF_ORDER = {"low": 0, "medium": 1, "high": 2}


def combine_scores(objective_score, subjective_score,
                   objective_confidence: str,
                   subjective_confidence: str,
                   objective_detail: Optional[dict] = None) -> dict:
    """
    Confidence-aware composition of objective and subjective scores.

    The old rule was always 60/40 even when the objective model explicitly said
    its confidence was low. This keeps the two-line design, but lets a low-
    confidence objective result move the final score less; an unavailable line
    is ignored instead of being replaced with a fake number.
    """
    if objective_score is None and subjective_score is None:
        return {
            "score": None, "rule": "no_score", "objective_weight": 0.0,
            "subjective_weight": 0.0, "agreement": "", "confidence": "",
            "calibrated": False,
        }
    if objective_score is None:
        return {
            "score": round(float(subjective_score), 2),
            "rule": "subjective only", "objective_weight": 0.0,
            "subjective_weight": 1.0, "agreement": "",
            "confidence": subjective_confidence or "",
            "calibrated": False,
        }
    if subjective_score is None:
        return {
            "score": round(float(objective_score), 2),
            "rule": "objective only", "objective_weight": 1.0,
            "subjective_weight": 0.0, "agreement": "",
            "confidence": objective_confidence or "",
            "calibrated": False,
        }

    obj_conf = objective_confidence if objective_confidence in _CONF_ORDER else "low"
    subj_conf = subjective_confidence if subjective_confidence in _CONF_ORDER else ""
    # The five-job calibration showed that the objective line had lower
    # correlation with independent reference labels than the subjective line.
    # Keep it as a correction signal instead of letting it dominate.
    objective_weight = {"high": 0.40, "medium": 0.25, "low": 0.10}[obj_conf]
    if subj_conf == "low":
        objective_weight = min(0.50, objective_weight + 0.05)
    elif subj_conf == "high":
        objective_weight = max(0.05, objective_weight - 0.05)
    detail = objective_detail if isinstance(objective_detail, dict) else {}
    claim_counts = detail.get("claim_counts") or {}
    contradictions = int(claim_counts.get("contradicted") or 0)
    misconceptions = detail.get("misconceptions") or []
    if contradictions or misconceptions:
        # Contradictions are the strongest objective evidence. Use the
        # objective line more when it has explicit counter-evidence.
        objective_weight = max(
            objective_weight, 0.60 if obj_conf == "high" else 0.50)
    elif (float(objective_score) - float(subjective_score) >= 0.30
          and obj_conf == "high"):
        # A high-confidence objective line can rescue concise but fully
        # correct answers that the subjective prompt under-rates.
        objective_weight = max(objective_weight, 0.55)
    objective_weight = round(objective_weight, 2)
    subjective_weight = round(1.0 - objective_weight, 2)

    gap = abs(float(objective_score) - float(subjective_score))
    agreement = "high" if gap <= 0.75 else "medium" if gap <= 1.5 else "low"
    confidence_values = [obj_conf] if obj_conf else []
    if subj_conf:
        confidence_values.append(subj_conf)
    confidence_values.append(agreement)
    confidence = min(confidence_values, key=lambda x: _CONF_ORDER[x])
    score = round(
        objective_weight * float(objective_score)
        + subjective_weight * float(subjective_score),
        2,
    )
    return {
        "score": score,
        "rule": (f"objective {int(objective_weight * 100)}% + "
                 f"subjective {int(subjective_weight * 100)}%"),
        "objective_weight": objective_weight,
        "subjective_weight": subjective_weight,
        "gap": round(gap, 2),
        "agreement": agreement,
        "confidence": confidence,
        "calibrated": False,
    }


def objective_round_score(coverage_05: float, correctness: float,
                          claims: Optional[list] = None,
                          misconceptions: Optional[list] = None,
                          point_atoms: Optional[list] = None) -> float:
    """
    Combine point coverage with claim-level verification.

    Keyword coverage is only one signal. A contradicted technical claim gets a
    larger penalty than a missing point, while `insufficient` claims do not get
    treated as factual errors.
    """
    atoms = [row for row in (point_atoms or []) if isinstance(row, dict)]
    atom_penalty = 0.0
    coverage_for_score = float(coverage_05)
    atom_total = 0
    supported_atoms = 0
    insufficient_atoms = 0
    for row in atoms:
        verdict = str(row.get("verdict") or "")
        if verdict not in ("supported", "contradicted", "insufficient"):
            continue
        atom_total += 1
        if verdict == "supported":
            supported_atoms += 1
        elif verdict == "insufficient":
            insufficient_atoms += 1
        else:
            severity = str(row.get("severity") or "none").lower()
            atom_penalty += {"minor": 0.30, "major": 0.65}.get(
                severity, 0.40)
    if atom_total:
        # Atomic verification is more reliable than raw keyword coverage.
        coverage_for_score = round(
            (supported_atoms + 0.5 * insufficient_atoms) / atom_total * 5,
            2,
        )
    # Coverage is currently much less reliable than claim-level correctness.
    base = 0.25 * coverage_for_score + 0.75 * float(correctness)
    claim_penalty = 0.0
    for row in claims or []:
        if not isinstance(row, dict) or row.get("verdict") != "contradicted":
            continue
        severity = str(row.get("severity") or "none").lower()
        claim_penalty += {"minor": 0.30, "major": 0.65}.get(severity, 0.40)
    legacy_penalty = 0.40 * len(misconceptions or [])
    penalty = min(2.2, max(claim_penalty, legacy_penalty, atom_penalty))
    score = base - penalty
    if misconceptions and float(correctness) <= 1.5:
        score = min(score, 0.75)
    return round(max(0.0, min(5.0, score)), 2)


def detect_repeat(answer: str, attempts: list) -> tuple[bool, float]:
    """
    这次回答与**本轮之前**的回答是不是复读。返回 (是否复读, 最高相似度)。

    纯函数。两道闸里的**确定性**那一道（另一道是把历史喂给 LLM，见
    config.A11_REPEAT_GUARD）：判档器会超时、会返回非 JSON，而"逐字复述"
    这种最好认的重复不该依赖一个会失败的组件。

    ⚠️ 只跟**本轮**历史比。跨轮比会误伤：不同题目本来就可能答到同一个知识点，
      那是正常的，不是复读。
    ⚠️ **跨轮"撞车"是另一个问题，不在这里管。** 出题侧另有一套去重
      （`exclude_ids=self.asked_pids` 只排同 ID；考点重叠走 `_overlap_filters`
      的 r0→r3 回退链，读数在 `RoundRecord.kp_overlap`）。真跑里观测到的
      跨题撞车（第 3 题 select/poll/epoll 与第 9 题 NIO Selector）是**语义级**的
      —— 那两道题的**考点键交集为空**、题面相似度只有 0.3684，任何字面判据
      都抓不到它而不误伤近两成题库（全库实测 1145 对 ≥0.85 的"重复"逐对看
      全是正常的不同的题）。别把两者混为一谈，也别在这里加跨轮比对。
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


# 面试官"该提问却没提问"的措辞。**只用于观测与兜底修补**，不改变任何判分。
#
# 为什么是这几组词（全部来自真跑观测，不是想出来的）：
#   · 「换一个方向」——实测原句「行，这题你答得住。换一个方向。」里就有它，
#     而 `SWAP_LINE` 也长这样（那是**合法换题**，走 `_swap_round`，不经过这里）。
#   · 「下一题」「先放一放」——收尾语的另外两种常见形态。
#   · 「回去看/回去补/后面补/后面再」——`ACTION_DESC["degrade"]` 明写禁止的
#     "辅导腔"（"不要布置'回去看什么''后面补什么'"），模型越界时会出现。
_RE_WRAPUP = re.compile(
    r"下一题|下一个话题|换一个方向|换一个话题|先放一放|"
    r"回去(看|补|复习|再)|后面(补|再)|建议你")


def needs_question(text: str) -> bool:
    """
    这一轮面试官的话里**有没有在问考生**。纯函数，无副作用。

    判据是两条的**或**：
      ① 出现了收尾/换题/辅导腔的措辞（`_RE_WRAPUP`）—— 这些措辞在 project
         的语境里一律意味着"这题不问了"；
      ② 整段**一个问号都没有**。

    ⚠️ 为什么是"或"而不是"且"：漏判（明明没提问却放过去）会让考生继续被带偏，
      而误判（其实提问了却触发兜底）只是多追加一句邀请他说话的短句 ——
      **两个方向的代价不对称**，所以取宽。
    ⚠️ 只认问号本身（全角 `？` 与半角 `?`），不看句式。中文面试里没有问号
      却是在提问的句子（"说说你的思路。"）存在，但那种情形下追加一句
      `WRAPUP_NUDGE` 也**不冲突** —— 它同样是在邀请他说话。
    """
    t = text or ""
    if _RE_WRAPUP.search(t):
        return True
    return ("？" not in t) and ("?" not in t)


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
    # 而 swap **只能**来自判档器（reranker 的 band_of 只会给出 L3/L2/L1/degrade），
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
    返回 L1 / L2 / L3 / degrade / close。

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
    if band == BAND_L3:
        return "L3"
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


def _contextualize_hint(text: str, record: RoundRecord) -> str:
    """Append a concrete question anchor when the bank hint is topic-agnostic."""
    text = str(text or "").strip()
    question = str(record.question or "").strip()
    if not text or not question:
        return text
    q_cjk = "".join(re.findall(r"[\u4e00-\u9fff]", question))
    terms = {q_cjk[i:i + 2] for i in range(max(0, len(q_cjk) - 1))}
    if any(term and term in text for term in terms):
        return text
    return f"围绕「{qb.truncate(question, 36)}」来说，{text}"


def hint_for(action: str, record: RoundRecord) -> Optional[str]:
    """按动作取追问素材。"""
    if action == "close":
        return None
    if action == "degrade":
        text = record_degrade(record)
    elif action == "L3":
        text = (record_follow(record, "L3") or record_follow(record, "L2")
                or record_follow(record, "L1"))
    elif action == "L2":
        text = record_follow(record, "L2") or record_follow(record, "L1")
    else:  # L1
        text = record_follow(record, "L1") or record_degrade(record)
    if action != "degrade":
        text = _contextualize_hint(text, record)
    return qb.truncate(text.strip(), config.HINT_TRUNCATE) or None


def _cycle_reply(options: tuple[str, ...], record: RoundRecord,
                 attempt_no: int, salt: int = 0) -> str:
    """按轮次/尝试确定性轮换话术，避免同一句逐题重复。"""
    if not options:
        return ""
    idx = (record.round_no + attempt_no + salt) % len(options)
    return options[idx]


_EXPERIENCE_CATEGORIES = ("行为素质题", "项目经历题")
_EXPERIENCE_QUESTION_RE = re.compile(
    r"描述一次|讲一次|讲一个|说说你|经历|怎么达成|如何处理|团队|同事|项目")


def _is_experience_question(record: RoundRecord) -> bool:
    return (
        str(record.category or "").strip() in _EXPERIENCE_CATEGORIES
        or bool(_EXPERIENCE_QUESTION_RE.search(str(record.question or "")))
    )


def _experience_guiding_hint(record: RoundRecord) -> str:
    """A concrete STAR-style entry for behavioral/project questions."""
    question = str(record.question or "")
    if re.search(r"分歧|冲突|不一致|争论|说服", question):
        return (
            "先不用讲完整。只说一个真实场景：当时你和对方各自主张什么，"
            "最后依据什么信息达成一致？"
        )
    if re.search(r"失败|教训|犯错|失误|复盘", question):
        return (
            "先讲一个真实片段：当时发生了什么，你具体做了什么，"
            "结果怎样？"
        )
    if re.search(r"项目|系统|平台|需求|落地|上线", question):
        return (
            "先选一个你亲自做过的项目：当时的业务目标是什么，"
            "你负责的具体部分是什么？"
        )
    if re.search(r"沟通|解释|汇报|协作|团队|同事", question):
        return (
            "先说一个真实场景：当时的沟通对象和目标是什么，"
            "你采取了哪一个具体做法？"
        )
    return (
        "先讲一个真实场景：当时的情况、你承担的任务，"
        "以及你采取的一个具体动作分别是什么？"
    )


def _guiding_hint(record: RoundRecord) -> str:
    """无有效回答时优先用题库专门写的降级引导，再退回中性化后的 L1 入口。"""
    if _is_experience_question(record):
        return qb.truncate(
            _experience_guiding_hint(record), config.HINT_TRUNCATE) or ""
    text = hint_for("degrade", record) or record_follow(record, "L1") or ""
    if "如果候选人" in text:
        quoted = re.findall(r"「([^」]+)」", text)
        if quoted:
            text = quoted[0]
    elif "若仍卡壳" in text:
        quoted = re.findall(r"「([^」]+)」", text)
        if quoted:
            text = quoted[-1]
    # The source bank repeats these two boilerplate clauses in thousands of
    # rows. Keep the concrete entry point, remove the copy that made every
    # question sound identical.
    text = re.sub(r"^先不用讲原理[，,]\s*", "", text)
    text = re.sub(r"[，。]?说说你知道的部分就行[。]?$", "", text).strip()
    text = _contextualize_hint(text, record)
    return qb.truncate(text.strip(), config.HINT_TRUNCATE) or ""


_PROBE_LABELS = {
    "extend_engineering": "追一个工程落地问题",
    "clarify_basic": "补齐一个基础缺口",
    "deepen_reason": "追一层原理或边界",
    "scaffold": "给一个最小入口",
}


def build_probe_plan(action: str, record: RoundRecord, score: Optional[dict]) -> dict:
    """
    Pick exactly one target for the next interviewer turn.

    The model previously received the whole missing-point list plus several
    background blocks and often asked a broad, multi-part question. This plan
    narrows the turn to one target and one probe type; it does not alter scoring.
    """
    if action == "close":
        return {}
    score = score or {}
    preferred_target = str(score.get("judge_probe_target") or "").strip()
    preferred_kind = str(score.get("judge_probe_kind") or "").strip()
    if preferred_target and preferred_kind in _PROBE_LABELS:
        target = preferred_target
        kind = preferred_kind
        instruction = {
            "clarify_basic": "只补一个基础缺口，先问定义、区别或一个最短的具体例子。",
            "deepen_reason": "只追一个缺失的进阶点，问它为什么成立、底层怎么实现，或边界/取舍是什么。",
            "extend_engineering": "只追一个工程落地问题，问真实项目用法、失败案例、极端场景或替代方案。",
            "scaffold": "给一个最小入口，让考生说出一个相关概念、场景或步骤。",
        }[kind]
    elif action == "degrade":
        target = _guiding_hint(record) or record.question
        kind = "scaffold"
        instruction = "给一个最小入口，让考生说出一个相关概念、场景或步骤。"
    elif action == "L3":
        target = (record.deepen[0]["title"] if record.deepen
                  else "当前方案的工程落地、失败场景与取舍")
        kind = "extend_engineering"
        instruction = "只追一个工程落地问题，问真实项目用法、失败案例、极端场景或替代方案。"
    elif action == "L2":
        misses = (score.get("adv_miss") or score.get("base_miss") or [])
        target = misses[0] if misses else (_guiding_hint(record) or record.question)
        kind = "deepen_reason"
        instruction = "只追一个缺失的进阶点，问它为什么成立、底层怎么实现，或边界/取舍是什么。"
    else:
        misses = (score.get("base_miss") or score.get("adv_miss") or [])
        target = misses[0] if misses else (_guiding_hint(record) or record.question)
        kind = "clarify_basic"
        instruction = "只补一个基础缺口，先问定义、区别或一个最短的具体例子。"
    target = qb.truncate(str(target or "").strip(), 100)
    if not target:
        return {}
    return {
        "target": target,
        "kind": kind,
        "kind_label": _PROBE_LABELS[kind],
        "instruction": instruction,
    }


_WEAK_PROBE_NAMES = {
    "特殊情况处理",
    "怎么处理",
    "如何处理",
    "为什么",
    "还有呢",
    "然后呢",
    "具体呢",
    "继续",
    "举个例子",
}
_PROBE_RELEASE_CHARS = 24


def _probe_reply_too_weak(text: str) -> bool:
    """Detect descriptor-only replies that are not real interview questions."""
    clean = re.sub(r"\s+", "", str(text or ""))
    if not clean:
        return True
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", clean))
    if cjk_count < 12:
        return True
    if "?" not in clean and "？" not in clean:
        return True
    plain = re.sub(r"[\s。！？!?，,：:；;]+", "", clean)
    if plain in _WEAK_PROBE_NAMES:
        return True
    return False


def repair_probe_reply(record: RoundRecord, probe_plan: Optional[dict]) -> str:
    """Build a complete contextual probe without revealing the answer."""
    kind = (probe_plan or {}).get("kind") or "clarify_basic"
    question = qb.truncate(record.question, 48)
    answer = ""
    if record.attempts:
        answer = qb.truncate(record.attempts[-1].answer or "", 32)
    prefix = f"你刚才提到「{answer}」。" if answer else ""
    if kind == "deepen_reason":
        body = (
            f"针对「{question}」里的具体机制，你能否进一步说明它为什么成立，"
            "以及边界条件下会出现什么变化？"
        )
    elif kind == "extend_engineering":
        body = (
            f"把「{question}」放到真实项目场景里，如果出现失败、超时或数据不一致，"
            "你会先判断什么、再怎么兜底？"
        )
    elif kind == "scaffold":
        body = (
            f"先不用讲完整答案。围绕「{question}」，说一个你确定的关键概念、"
            "场景或步骤就行，你最先想到什么？"
        )
    else:
        body = (
            f"围绕「{question}」，请先给其中一个关键概念下定义，"
            "再简要说明它在题目里起什么作用？"
        )
    return prefix + body


_STYLE_ACK_REPLIES = {
    "relaxed": (
        "嗯，你说，我听着。",
        "可以，想到多少说多少。",
        "好，你慢慢说。",
    ),
    "strict": (
        "请直接说你的思路。",
        "不用确认，直接回答这个问题。",
        "请给出你的判断或理由。",
    ),
}


def _ack_reply(style: str, record: RoundRecord, attempt_no: int) -> str:
    options = _STYLE_ACK_REPLIES.get(style)
    if options:
        return _cycle_reply(options, record, attempt_no, salt=1)
    return _cycle_reply(ACK_REPLIES, record, attempt_no, salt=1)


def _guided_no_info_reply(record: RoundRecord, attempt_no: int,
                          style: str = "standard") -> str:
    hint = _guiding_hint(record)
    if style == "relaxed":
        if hint:
            return (f"没关系，我们从最小的地方开始：{hint}\n"
                    "你先说一个你确定的概念就行，说错也没关系。")
        return "没关系，我们慢一点。先说一个你能想到的关键词、场景或步骤就行。"
    if style == "strict":
        if hint:
            return f"这轮还没有有效信息。只回答一个点：{hint}"
        return "这题还没有有效信息。请只回答一个确定的概念、步骤或例子。"
    if hint:
        idx = (record.round_no + attempt_no) % len(NO_INFO_WITH_HINT_REPLIES)
        return NO_INFO_WITH_HINT_REPLIES[idx].safe_substitute(hint=hint)
    return _cycle_reply(NO_INFO_DEGRADE_REPLIES, record, attempt_no)


def _hint_request_reply(record: RoundRecord, style: str = "standard") -> str:
    hint = _guiding_hint(record)
    if style == "relaxed":
        if hint:
            return f"可以，我给你一个入口：{hint}\n你先按这个方向说说看。"
        return "可以，先不用讲完整答案，说一个你确定的概念或步骤就行。"
    if style == "strict":
        if hint:
            return f"提示只给一次：{hint}\n现在直接回答。"
        return "只给一次提示：抓住题目里的一个核心概念，直接回答。"
    if hint:
        return HINT_REQUEST_REPLY.safe_substitute(hint=hint)
    return HINT_REQUEST_FALLBACK


def _no_info_close_reply(style: str, record: RoundRecord,
                         attempt_no: int) -> str:
    if style == "relaxed":
        return _cycle_reply((
            "没关系，这题先放一放，我们换个轻松点的方向继续。",
            "这题先跳过，不用有压力，我们看下一题。",
        ), record, attempt_no, salt=2)
    if style == "strict":
        return _cycle_reply((
            "这道题结束。下一题请回答到关键点。",
            "这题到此为止，下一题直接给结论和依据。",
        ), record, attempt_no, salt=2)
    return _cycle_reply(NO_INFO_CLOSE_REPLIES, record, attempt_no, salt=2)


# ============================================================
# 给**考生**看的表达客观测量（/finish 顶层 `pace_note`）
# ============================================================
# 情感标签的中文白名单。⚠️ **必须走白名单**：`emotion_dist` 的**键**是前端从
# `/chat` 的 speech 原样带上来的（`derive_speech` 只做 `dict(...)`，**不校验键名**）。
# 把键名直接拼进这句话，等于在一个**交付默认档（A11_RAW_DETAIL=0）也照常出门**的
# 字符串里开一个自由文本入口 —— 而这段字符串会被整包金丝雀扫、还会被前端当原文
# 展示给考生。不认识的键**整条丢掉**（宁可少一句，不可漏一个口子）。
_EMOTION_CN = {"neu": "中性", "hap": "高兴", "ang": "生气", "sad": "低落"}


def candidate_pace_note(rounds: list) -> str:
    """
    整场的「表达客观测量」汇总 —— **给考生看的**那一份（`/finish` 顶层 `pace_note`）。

    ⚠️ 它与 `RoundRecord.pace_note()`（上面那个·**逐轮**）**同名，但不是同一样东西**：
      · `RoundRecord.pace_note()` 写给**评分模型**，里面带着给模型划边界的**指令**
        （「**禁止**因为它是「偏高」就给高分」「不要拿它推那三维」「**禁止**据此判断
        考生当时是什么心情」）—— 原样展示给考生会出现一堆「禁止…」，所以前端**不能**
        拿它当报告文案；而且它的逐字节形态被 prompt 基线钉死（改它必打红）。
      · 本函数写给**考生**，只陈述测出来的事实，**一条指令都不含**。
    两者数据同源（都是 `RoundRecord.speech`）、口径必须一致：改一头时看一眼另一头。

    为什么要有它：赛题 3b 要「**评估**学生的表达流畅度、语速、语气自信度」，而这套
    测量此前**只以 `$pace_note` 的形式进了评分 prompt**（见 `submit_answer`），考生的
    报告上**一个字都看不到** —— 他无从知道自己哪里说得不好。这一份就是把它端到
    考生眼前（4 号 的前端文档早就写成「照 `/finish` 的 `pace_note` 原文展示」）。

    三条纪律（与 `asr.py` 顶部那条「取值域封闭」一脉相承）：
      1. **逐字白名单构造**：全部文字来自本函数的模板与 `_EMOTION_CN`，**不搬运任何
         原文**（没有转写文本、没有题目、没有得分点）—— 这段字符串在交付默认档也
         出门，它必须自己就是干净的。
      2. **绝不抛**：它挂在交卷链路上，抛了会把整场面试的收口打挂。
      3. **不给 `loudness` 绝对值、不给「整轮用时」**：前者跨设备不可比（麦克风增益 /
         说话距离 / 房间混响都能差几倍，见 `asr.loudness_metrics` 的注释）；后者那段
         时间里混着**服务端打分与生成回复**的耗时，对考生说「这题你用了 3 分钟」是
         误导。⇒ 与 prompt 版一致，这两样**整条不报**。

    全篇**不分段、只有一个换行都没有**：4 号 的文档写的是「照那句话原文展示」，一整个
    段落最好摆；判断句一律用「。」断开，不用 Markdown 记号（`**` / 反引号）—— 与
    `app/core/review.py` 那份给考生看的文案同一个写法，前端不必先渲染 Markdown。
    """
    answered = [r for r in rounds if getattr(r, "attempts", None)]
    total = len(answered)
    if not total:
        return "本场没有产生作答记录，没有表达数据可报。"
    # `used` 由 `derive_speech` 定：拿到了净时长（duration_ms > 0）才为真。
    sps = [dict(r.speech or {}) for r in answered if (r.speech or {}).get("used")]
    n_v = len(sps)
    if not n_v:
        return ("本场共 %d 轮作答，全部为文字作答，所以没有语速、停顿、填充词与语气"
                "自信度数据可报。这些指标只在用语音作答时才有；文字作答不会因为缺"
                "这些数据而被扣分。" % total)

    # ---- 逐项聚合（缺哪一项就整条不报，绝不拿 0 顶替「没测到」）----
    dur_ms = sum(int(s.get("duration_ms") or 0) for s in sps)
    rated = [s for s in sps if s.get("chars_per_min") is not None]
    silent = [s for s in sps if s.get("chars_per_min") is None]
    paused = [s["pauses"] for s in sps if s.get("pauses") is not None]
    filled = [int(s.get("fillers") or 0) for s in sps]
    cvs = [float(s["loudness_cv"]) for s in sps if s.get("loudness_cv") is not None]
    tails = [float(s["tail_ratio"]) for s in sps if s.get("tail_ratio") is not None]
    bands = [s["confidence"] for s in sps if s.get("confidence")]

    parts: list[str] = []
    head = []
    head.append("本场共 %d 轮作答，其中 %d 轮用语音作答" % (total, n_v))
    if dur_ms > 0:
        sec = int(round(dur_ms / 1000.0))
        if sec >= 60:
            # 整分钟时不写「3 分 0 秒」（读起来像掉了个数）
            _m, _s = divmod(sec, 60)
            dur_txt = ("%d 分 %d 秒" % (_m, _s)) if _s else ("%d 分" % _m)
        else:
            dur_txt = "%d 秒" % sec
        head.append("这 %d 轮共说话 %s" % (n_v, dur_txt))
    if rated:
        # ⚠️ **总字数 ÷ 总净时长**（加权），不是「各轮语速求平均」—— 后者会被一次
        #    两秒的短答带飞。且**只算转写出了内容的轮**：没转写出内容的轮不是语速样本。
        c = sum(int(s.get("chars") or 0) for s in rated)
        d = sum(int(s.get("duration_ms") or 0) for s in rated)
        if c > 0 and d > 0:
            head.append("平均语速 %.0f 字/分" % (c / (d / 60000.0)))
    if paused:
        head.append("长停顿（>%.1f 秒）合计 %d 次"
                    % (asrmod.PAUSE_MIN_MS / 1000.0, sum(paused)))
    fc = sum(int(s.get("chars") or 0) for s in sps)
    n_fill = sum(filled)
    if fc > 0:
        # 一个填充词都没有时不报「占字数 0.0%」—— 那是句废话，读起来像没算出来。
        head.append("填充词（嗯 / 那个 / 然后…）%d 个%s"
                    % (n_fill, "、占字数 %.1f%%" % (n_fill / fc * 100) if n_fill else ""))
    elif n_fill:
        head.append("填充词（嗯 / 那个 / 然后…）%d 个" % n_fill)
    parts.append("，".join(head) + "。")

    if silent:
        parts.append("另有 %d 轮录到了语音但没有转写出内容，算不出语速"
                     "（没有并进上面的平均）。" % len(silent))

    # ---- 音量（只报相对量：变异系数与收尾比，**不报 `loudness` 绝对值**）----
    if cvs or tails:
        vol = []
        if cvs:
            vol.append("段间音量起伏（变异系数）平均 %.2f" % (sum(cvs) / len(cvs)))
        if tails:
            vol.append("收尾音量约为全段均值的 %.2f" % (sum(tails) / len(tails)))
        n_vol = len([s for s in sps if s.get("loudness_cv") is not None
                     or s.get("tail_ratio") is not None])
        parts.append("音量：%s%s。" % (
            "，".join(vol),
            "" if n_vol >= n_v else "（%d 轮里量到 %d 轮）" % (n_v, n_vol)))
    else:
        miss = ["音量"]
        if not paused:
            miss.append("停顿")
        parts.append("本次没有量到%s数据（前端回传的语音数据里少了这几项）—— 这不是"
                     "故障，也已经按「没有这项数据」处理，不会因此扣分。" % "与".join(miss))

    # ---- 「语气自信度」：档位由 `confidence_band()` 按写死的规则融合，只吃上面那
    #      两个韵律信号。依据句**必须用同一套参数重算**（整场平均），否则会与列出
    #      的档位对不上 —— 那是最难查的一类错（`RoundRecord.pace_note()` 有同款约束）。
    basis = []
    if cvs or tails:
        basis = asrmod.confidence_band(
            (sum(cvs) / len(cvs)) if cvs else None,
            (sum(tails) / len(tails)) if tails else None)[1]
    if bands:
        order = (asrmod.CONFIDENCE_LOW, asrmod.CONFIDENCE_MID, asrmod.CONFIDENCE_HIGH)
        cnt = "、".join("%d 轮「%s」" % (bands.count(b), b)
                       for b in order if bands.count(b))
        msg = ("「语气自信度」：%s。它只由「段间音量稳不稳、收尾收不收得住」这两件事"
               "按写死的规则算出来" % cnt)
        msg += ("（整场平均：%s）" % "；".join(basis)) if basis else ""
        parts.append(msg + "，不是模型输出，也不是心理测量意义上的自信度量表。")

    # ---- 情感：**照报**（赛题 3b 要求集成情感分析），但必须现场说清它的可信边界。
    #      标签走 `_EMOTION_CN` 白名单；几轮之间取**平均分布**（每轮的分布和恒为 1）。
    dist: dict = {}
    n_d = 0
    for s in sps:
        d = s.get("emotion_dist")
        if not isinstance(d, dict):
            continue
        n_d += 1
        for k, v in d.items():
            if k in _EMOTION_CN:
                try:
                    dist[_EMOTION_CN[k]] = dist.get(_EMOTION_CN[k], 0.0) + float(v)
                except (TypeError, ValueError):
                    continue
    if n_d and dist:
        avg = [(k, v / n_d) for k, v in sorted(dist.items(), key=lambda kv: -kv[1])]
        shown = [x for x in avg if x[1] >= 0.01] or avg[:1]
        parts.append(
            "语音情感模型给出的标签是 %s —— ⚠️ 该模型训在英语、表演式情感语料上，"
            "中文上没有标注数据可验证（实测对平淡的中文语音也会给出高置信），所以"
            "我们不据此判断你当时的心情，只把它当一条原始记录。"
            % "、".join("%s %.0f%%" % (k, v * 100) for k, v in shown))

    body_rows = [
        dict(getattr(r, "body_language", {}) or {})
        for r in answered
        if (getattr(r, "body_language", {}) or {}).get("used")
    ]
    body_scores = [
        float(row["score"]) for row in body_rows
        if row.get("score") is not None
    ]
    if body_rows:
        usable = [row for row in body_rows if row.get("available")
                  and row.get("confidence") in ("medium", "high")]
        if body_scores:
            parts.append(
                "摄像头姿态共记录 %d 轮，其中 %d 轮达到可用质量，平均 %.2f/5。"
                "它最多只调整沟通表达与应变能力，不用于判断紧张、自信、"
                "诚实、性格或技术能力。" % (
                    len(body_rows), len(usable),
                    sum(body_scores) / len(body_scores)))
        else:
            parts.append(
                "摄像头姿态共记录 %d 轮，但没有一轮达到可用质量，因此未计分。"
                % len(body_rows))

    parts.append("以上都是测出来的发音与节奏事实，与答得对不对无关：语速快不等于答得"
                 "好，停顿多也不等于答得差。")
    return "".join(parts)


# ============================================================
# 会话
# ============================================================
class InterviewSession:
    def __init__(self, job: str, intro: str = "",
                 llm=None, scorer=None, persona_style=None,
                 resume_text: str = "", interview_mode: str = "general"):
        if job not in config.JOBS:
            raise UnknownJob(f"未知岗位：{job!r}；可选：{config.JOBS}")
        self.session_id = uuid.uuid4().hex[:8]
        self.job = job
        # ⚠️ 这里是**原文**（未压平/未截断），它直接进 `raw.candidate_intro`
        #    给 3 号 看 —— 与加 E 之前逐字节相同。进 prompt 的那一份是下面的
        #    `_intro_for_prompt`（sanitize 过），两者**刻意分开**：
        #    报告要忠实原文，prompt 要结构安全，两件事。
        resume_text = (resume_text or "").strip()
        if len(resume_text) > config.RESUME_MAX_CHARS:
            resume_text = resume_text[:config.RESUME_MAX_CHARS] + "…"
        self.candidate_intro = intro or resume_text
        self.resume_text = resume_text
        self.interview_mode = (
            "resume" if (config.A11_RESUME and interview_mode == "resume"
                         and resume_text) else "general"
        )
        self.resume_profile = resumemod.parse_resume(resume_text)
        self._resume_vector_cache: dict[str, list[float]] = {}
        self._resume_query_vector: Optional[list[float]] = None
        self._resume_semantic_attempted = False
        self.created_at = time.time()
        self.finished_at: Optional[float] = None

        # 面试官风格三档（F）。关掉 `A11_PERSONA` 时不报错 —— 按默认档跑，
        # 但 `/start` 回显的是**实际生效**的这一档，所以「关掉」看得见。
        if not config.A11_PERSONA:
            persona_style = config.PERSONA_STYLE_DEFAULT
        self.persona_style = (persona_style
                              or config.PERSONA_STYLE_DEFAULT)
        if self.persona_style not in PERSONA_STYLE_LABELS:
            self.persona_style = config.PERSONA_STYLE_DEFAULT

        # 考生自述进 prompt 的那一份（E）。空串 = 不注入。
        self._intro_for_prompt = (sanitize_intro(self.candidate_intro)
                                  if config.A11_INTRO else "")

        # 场次类型。正式面试恒为 "exam"；专项强化练习（赛题 4b）是 "practice"
        # —— 见 app/core/practice.py。练习会话是靠覆写方法改变行为的，不靠这个字段。
        # ⚠️ 2026-09-25 起**有一处按它分支**：`app/core/growth.py` 的 `_history()`
        #    —— 成长档案的历史走势只吃 exam，练习那一节单列（练习分数按
        #    practice.py 自己那句 disclaimer 不与正式场次横向比较）。
        #    这行注释原来写着「全项目没有任何一处按它分支」，那一轮之后就不对了。
        self.mode = "exam"

        self.phase = PHASE_START

        # 真实对话流：面试官的话也存（修 #1：原来只存考生回答，模型没有多轮记忆）
        self.transcript: list[dict] = []
        self.rounds: list[RoundRecord] = []
        self.current_round: Optional[RoundRecord] = None
        # Speech samples are used only to build a personal reference. They
        # never cross sessions and are never sent to the model as raw audio.
        self._speech_baseline_samples: list[dict] = []
        self.asked_pids: list[str] = []
        # 被换掉的轮次。**刻意与 self.rounds 分开存** —— 它一个都不能进下面那条
        # 「questions_asked = len(self.rounds)」的账（用户定的：换题不占 10 题名额），
        # 也不能进 _trajectory / finish 的评分轮次。放这儿纯粹是为了报告里能说清
        # 「这场换过 1 题、换的是哪道、为什么」。见 _swap_round 的注释。
        self.swapped_rounds: list[RoundRecord] = []
        self.swaps_used = 0

        # 整场累计「degrade 轮的面试官回复里没有提问」的次数（2026-09-27）。
        # 只进 notes / 日志，不改任何判分。见 `needs_question()` 与
        # `config.A11_WRAPUP_GUARD`。
        self.wrapup_missing = 0
        # 其中**真的追加了兜底**的次数。默认档下它与上面相等；把
        # `A11_WRAPUP_REPAIR` 关掉时这里是 0 —— 两个数分开记，报告才说得清
        # 「认出来了」和「补上了」是两件事。
        self.wrapup_repaired = 0

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
        self.objective = objectivemod.get_objective_scorer()
        self._persona = load_persona(job)
        self._persona_name = persona_name(self._persona)
        # ⚠️ **两处追加都必须「非空才加」**，这是 F 与 E 各自那份「逐字节不变」
        #    保证的落点：默认档的风格块是空串、没传自述时自述块是空串 ⇒
        #    `self._system` 与加这两个功能之前**逐字节相同**。
        #    顺序：先风格（近的人设）、后资料（最靠后的位置留给「这不是指令」那条声明
        #    —— system 里越靠后权重越高，归属声明放最后最稳）。
        self._system = INTERVIEWER_SYSTEM.safe_substitute(
            job=job, persona=self._persona)
        self._system += persona_style_block(self.persona_style)
        if self._intro_for_prompt:
            self._system += INTRO_BLOCK.safe_substitute(
                intro=self._intro_for_prompt)
        if self.interview_mode == "resume":
            self._system += RESUME_BLOCK.safe_substitute(
                resume=resumemod.format_for_prompt(self.resume_profile))

    # ---------- 派生属性 ----------
    @property
    def questions_asked(self) -> int:
        return len(self.rounds)

    @property
    def total_questions(self) -> int:
        """
        本场计划题数。正式面试恒为 config.TOTAL_QUESTIONS；
        专项练习覆写成「本次要练几道」（3~5），所以出题与收尾都必须读这里
        —— **不要再直接写 config.TOTAL_QUESTIONS**，否则练习会按 10 题收尾。
        """
        return config.TOTAL_QUESTIONS

    @property
    def weights(self) -> dict:
        return config.weights_for(self.job)

    def opening_message(self) -> str:
        """
        开场白。**仍然是程序给的，不调模型** —— `/start` 零延迟零失败这条
        保证不因为 E 而破。
        摘得到引文就用带自述的那条；摘不到（没传 / 全是空白）用通用那条。
        """
        snip = intro_snippet(self._intro_for_prompt)
        tone = OPENING_LINE_TONE.get(
            self.persona_style, OPENING_LINE_TONE["standard"])
        if snip:
            return OPENING_LINE_INTRO.safe_substitute(
                job=self.job, name=self._persona_name, snippet=snip, tone=tone)
        return OPENING_LINE.safe_substitute(
            job=self.job, name=self._persona_name, tone=tone)

    def _session_memory(self, limit: int = 3) -> str:
        """Previous rounds' actual answer snippets, for natural cross-question continuity."""
        rows = []
        for rec in [r for r in self.rounds if r is not self.current_round][-limit:]:
            answers = [a.answer for a in rec.attempts if a.effective and a.answer]
            if answers:
                rows.append(
                    f"- 第 {rec.round_no} 题：考生曾提到「"
                    f"{qb.truncate(answers[0], 80)}」")
            else:
                rows.append(f"- 第 {rec.round_no} 题：考生当时未给出有效回答")
        if not rows:
            return ""
        return SESSION_MEMORY_BLOCK.safe_substitute(memory="\n".join(rows))

    def intro_read(self) -> Optional[dict]:
        """
        `/start` 回显「读到多少自述」用。

        三态，**刻意分得开**（本项目「关掉 / 坏了 / 没有」那条纪律）：
          · 没传自述            → `None`
          · 传了但开关关掉      → `enabled=False`（其余键照样给，chars=0）
          · 传了且真进了 prompt → `enabled=True`

        `chars` 是**进 prompt 的那一份**的长度（已截断），原文长度另给
        `raw_chars` —— 两个数都给，「被截断了」才看得出来。
        """
        if not (self.candidate_intro or "").strip():
            return None
        flat = sanitize_intro(self.candidate_intro, max_chars=0)
        src = sanitize_intro(self.candidate_intro) if config.A11_INTRO else ""
        return {
            "enabled": config.A11_INTRO,
            "chars": len(src),
            "raw_chars": len(flat),
            "truncated": bool(src) and len(src) != len(flat),
            "snippet": intro_snippet(src),
        }

    def resume_read(self) -> Optional[dict]:
        if not self.resume_text:
            return None
        return {
            "enabled": self.interview_mode == "resume",
            "mode": self.interview_mode,
            "chars": len(self.resume_text),
            "skills": self.resume_profile.get("skills") or [],
            "projects": self.resume_profile.get("projects") or [],
            "skills_with_evidence": (
                self.resume_profile.get("skills_with_evidence") or []),
            "technology_choices": (
                self.resume_profile.get("technology_choices") or []),
            "difficulties": self.resume_profile.get("difficulties") or [],
            "outcomes": self.resume_profile.get("outcomes") or [],
            "probe_points": self.resume_profile.get("probe_points") or [],
            "uncertainties": self.resume_profile.get("uncertainties") or [],
        }

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

        if self.questions_asked >= self.total_questions:
            self.phase = PHASE_NEXT
            logger.info("sid=%s 计划内 %d 题已问完", self.session_id, self.total_questions)
            return self._finished_payload("plan_complete",
                                         f"面试到这里就结束了（共 {self.total_questions} 题）。"
                                         f"请交卷，稍等片刻就能看到这场面试的成绩单。")

        # 顺序是有意义的：先读阶段 → 再抽题 → 把阶段名冻结进记录 → 最后才推进
        stage_name, _planned, difficulties, adapt_note = self._current_stage()
        stage_index = min(self.stage_idx, len(config.STAGE_RULES) - 1)

        trace: dict = {}
        raw = self._pick_question(difficulties, trace)
        if raw is None:
            self.phase = PHASE_NEXT
            logger.warning("sid=%s 题库已抽空", self.session_id)
            return self._finished_payload("bank_exhausted",
                                          "这个岗位的题目已经问完了。"
                                          "请交卷，稍后就能看到成绩单。")

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
            transcript_start=len(self.transcript),
        )

        # RAG 参考片段：**每轮检索一次**（成本已付），整轮复用；
        # 但注不注入 prompt 由 submit_answer 按 action 决定（收尾轮不注入）。
        # 检索与注入是两件事 —— 这个区分是 close 轮禁令能成立的前提。
        if self.rag is not None:
            refs = self.rag.search(rec.question, self.job, rec.difficulty,
                                   exclude_id=qid,
                                   head_only=config.RAG_HEAD_ONLY)
            rec.rag_refs = refs
            rec.rag_meta = {
                "used": bool(refs),
                "hit_ids": [r.get("question_id") for r in refs],
                "layers": [r.get("layer") for r in refs],
                "distances": [r.get("distance") for r in refs],
            }

        self.rounds.append(rec)
        self.current_round = rec
        # 当前问题必须成为本轮消息列表里最后一条 assistant 内容。
        # 只看 system 会被上一轮面试官回复压过，真跑已复现跨题污染。
        self.transcript.append({
            "role": "assistant",
            "content": f"【{rec.stage}】{rec.question}",
        })
        self.phase = PHASE_ANSWER
        self._advance_stage()          # ← 必须最后

        logger.info("sid=%s phase->%s round=%d qid=%s stage=%s diff=%s "
                    "pick=%s overlap=%s kp=%d deepen=%d rag=%s ｜ 难度范围 %s（%s）",
                    self.session_id, self.phase, rec.round_no, qid,
                    rec.stage, rec.difficulty, rec.pick_level, rec.kp_overlap,
                    len(km), len(deepen), rec.rag_meta.get("used"),
                    rec.diffs_planned, rec.adapt_note)
        return self._question_payload(rec)

    # ---------- 抽题（唯一的「选哪道题」入口，练习模式覆写它） ----------
    def _pick_question(self, difficulties: set, trace: dict) -> Optional[dict]:
        """
        抽下一题。**默认实现 = 原来的 qb.sample 调用，逐字节未改**。

        为什么抽成一个方法：专项强化练习（`practice.PracticeSession`）要换的
        只有「选哪道题」这一件事 —— 追问、判档、评分、复读守卫、覆盖度统计
        全都该原样复用。把它抽出来之后，练习侧只需覆写这一个方法，
        `ask_next_question` 的其余部分（冻结阶段名、cov.add、RAG 检索、
        KG 深挖方向、幂等 return）一个字节都不用抄第二遍。

        出题避重：把两个档位的过滤器注入题库。题库层**不知道图谱的存在** ——
        它只收到两个接受单题的谓词（见 question_bank.sample 的说明）。
        """
        accept = accept_relaxed = None
        if self.kg is not None:
            accept, accept_relaxed = self._overlap_filters()
        if (self.interview_mode == "resume"
                and (self.resume_profile.get("skills")
                     or self.resume_profile.get("projects"))):
            hit = self._pick_resume_question(
                difficulties, trace, accept, accept_relaxed)
            if hit is not None:
                return hit
        return qb.sample(self.job, difficulties, self.asked_pids,
                         accept=accept, accept_relaxed=accept_relaxed, trace=trace)

    def _pick_resume_question(self, difficulties: set,
                              trace: dict,
                              accept=None, accept_relaxed=None
                              ) -> Optional[dict]:
        """Rank a small resume-relevant pool, then optionally rerank by BGE."""
        expected = next(iter(difficulties)) if len(difficulties) == 1 else ""
        bank = qb.load_bank(self.job)
        excluded = set(self.asked_pids)

        def eligible(q: dict, acc=None) -> bool:
            if q.get(qb.F_ID) in excluded:
                return False
            if q.get(qb.F_DIFFICULTY) not in difficulties:
                return False
            return acc is None or bool(acc(q))

        pool = [q for q in bank if eligible(q, accept)]
        level = "resume_hybrid"
        if not pool and accept_relaxed is not None:
            pool = [q for q in bank if eligible(q, accept_relaxed)]
            level = "resume_relaxed"
        if not pool:
            return None

        ranked = []
        for question in pool:
            details = resumemod.question_match_details(
                question, self.resume_profile, difficulty=expected)
            ranked.append((details["score"], question, details))
        ranked.sort(key=lambda row: (-row[0], str(row[1].get(qb.F_ID) or "")))
        shortlist = ranked[:40]

        semantic = self._resume_semantic_scores(
            [row[1] for row in shortlist if row[0] >= 3.0] or
            [row[1] for row in shortlist])
        if semantic:
            combined = []
            for score, question, details in shortlist:
                sem = semantic.get(str(question.get(qb.F_ID) or ""), 0.0)
                combined.append((round(score + sem * 4.0, 3),
                                 question, details, sem))
            combined.sort(
                key=lambda row: (-row[0], str(row[1].get(qb.F_ID) or "")))
            shortlist = [(row[0], row[1], row[2]) for row in combined[:8]]
            level = "resume_semantic"

        top = shortlist[:min(3, len(shortlist))]
        picked = random.choice(top)[1] if top else None
        if trace is not None:
            trace["level"] = level if picked is not None else "none"
        if picked is not None:
            details = resumemod.question_match_details(
                picked, self.resume_profile, difficulty=expected,
                semantic_score=semantic.get(str(picked.get(qb.F_ID) or ""))
                if semantic else None)
            trace["resume_match"] = details
        return picked

    def _resume_semantic_scores(self, questions: list[dict]) -> dict[str, float]:
        """Use an already-loaded BGE/online encoder; failures always degrade."""
        if self._resume_semantic_attempted and not self._resume_vector_cache:
            return {}
        encoder = getattr(self.rag, "encoder", None) if self.rag is not None else None
        if encoder is None:
            self._resume_semantic_attempted = True
            return {}
        self._resume_semantic_attempted = True
        try:
            import numpy as np
            if self._resume_query_vector is None:
                query = resumemod.format_match_query(self.resume_profile)
                if not query:
                    return {}
                vector = encoder.encode(
                    [query], normalize_embeddings=True)[0]
                self._resume_query_vector = vector.tolist()
            missing = [
                q for q in questions
                if str(q.get(qb.F_ID) or "") not in self._resume_vector_cache
            ]
            if missing:
                texts = [
                    "；".join([
                        str(q.get(qb.F_QUESTION) or ""),
                        str(q.get(qb.F_KEYWORDS) or ""),
                        str(q.get(qb.F_KNOWLEDGE) or ""),
                    ])
                    for q in missing
                ]
                vectors = encoder.encode(texts, normalize_embeddings=True)
                for q, vector in zip(missing, vectors):
                    qid = str(q.get(qb.F_ID) or "")
                    if qid:
                        self._resume_vector_cache[qid] = vector.tolist()
            if not self._resume_vector_cache:
                return {}
            query_vec = np.asarray(self._resume_query_vector, dtype="float32")
            out = {}
            for q in questions:
                qid = str(q.get(qb.F_ID) or "")
                vector = self._resume_vector_cache.get(qid)
                if vector is None:
                    continue
                out[qid] = float(np.dot(
                    query_vec, np.asarray(vector, dtype="float32")))
            return out
        except Exception:
            logger.exception("sid=%s 简历语义重排失败，退回关键词匹配",
                             self.session_id)
            self._resume_vector_cache = {}
            return {}

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
            "total": self.total_questions,
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
            "total": self.total_questions,
            "phase": self.phase,
        }

    # ---------- 回答 ----------
    def _score_and_judge(self, answer: str, rec: RoundRecord
                         ) -> tuple[dict, Optional[str], str, bool]:
        """
        覆盖率信号与 LLM 判档**并行**跑。返回 (sc, judge_band, judge_why, judge_ok)。

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
                j_band, j_why, j_target, j_kind, j_ok = f_j.result()
            except Exception:
                logger.exception("sid=%s round=%d 判档线程异常，退回 reranker",
                                 self.session_id, rec.round_no)
                j_band, j_why, j_target, j_kind, j_ok = None, "", "", "", False
            if j_target:
                sc["judge_probe_target"] = j_target
            if j_kind:
                sc["judge_probe_kind"] = j_kind
        return sc, j_band, j_why, j_ok

    def submit_answer(self, answer: str,
                      speech: Optional[dict] = None,
                      body_language: Optional[dict] = None
                      ) -> Generator[dict, None, None]:
        """ 
        yield {"type":"token","text":...}。
        结束后的状态推进在 finally 里做 —— 哪怕 LLM 中途失败、或客户端断开，
        本轮也一定会收尾，不会把会话卡在 awaiting_answer。

        `speech`（加法，可选）：考生用语音作答时，前端把 `/asr` 返回的那几个
        **数字**（`duration_ms` / `segments` / `asr_model` / `pauses` /
        `pause_total_ms`）原样带回来。
        不传 = 文字作答，行为与加这个参数之前**逐字节相同**。
        它只派生表达指标（语速/停顿/填充词），**不参与**判档、评分、复读守卫
        —— 语音与手打的唯一区别就是多了这几个数，评分链路完全共用。
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

        # 0) 语音作答的表达指标（需要的话）。转写文本就是 answer 本身 ——
        #    前端不再单独传文本，免得出现「message 与转写不一致」这种没法查的岔子。
        sp = dict(asrmod.SPEECH_EMPTY)
        if speech:
            try:
                sp = asrmod.derive_speech(
                    answer,
                    duration_ms=speech.get("duration_ms"),
                    segments=speech.get("segments"),
                    asr_model=speech.get("asr_model") or "",
                    audio_ms=speech.get("audio_ms"),
                    # `/asr` 在音频上量好的停顿（原样带回来的），优先采信
                    pauses=speech.get("pauses"),
                    pause_total_ms=speech.get("pause_total_ms"),
                    # 韵律 + 情感（2026-09-25）：同样是 `/asr` 在音频上量好的，
                    # **原样采信**。`confidence` 不在这里传 —— 它由 `derive_speech`
                    # 内部用这几个数融合出来（见 `confidence_band`）。
                    loudness=speech.get("loudness"),
                    loudness_cv=speech.get("loudness_cv"),
                    tail_ratio=speech.get("tail_ratio"),
                    pitch_variation=speech.get("pitch_variation"),
                    emotion=speech.get("emotion"),
                    emotion_score=speech.get("emotion_score"),
                    emotion_dist=speech.get("emotion_dist"),
                )
            except Exception:
                # 派生失败绝不能挡住作答：日志留痕，这一轮按文字作答记。
                logger.exception("sid=%s 语音指标派生失败，本轮按文字作答记录",
                                 self.session_id)
        sp = asrmod.apply_personal_baseline(
            sp, self._speech_baseline_samples)
        if sp.get("used"):
            self._speech_baseline_samples.append(dict(sp))
        body = bodymod.normalize_summary(body_language)

        kind = classify_answer(answer, rec)
        if kind in (ANSWER_ACK, ANSWER_HINT_REQUEST):
            if rec.assist_used < config.MAX_ASSIST_PER_QUESTION:
                rec.assist_used += 1
                if kind == ANSWER_HINT_REQUEST:
                    rec.hint_used += 1
                    reply = _hint_request_reply(rec, self.persona_style)
                else:
                    reply = _ack_reply(self.persona_style, rec, rec.assist_used)
                self.transcript.append({"role": "user", "content": answer})
                self.transcript.append({"role": "assistant", "content": reply})
                yield {"type": "token", "text": reply}
                logger.info(
                    "sid=%s round=%d 辅助轮 kind=%s assist=%d/%d phase=%s",
                    self.session_id, rec.round_no, kind, rec.assist_used,
                    config.MAX_ASSIST_PER_QUESTION, self.phase)
                return
            # 连续确认/反复要提示也有上限；超过后按“这题没说有效内容”处理。
            kind = ANSWER_NO_INFO

        # 1) 覆盖率信号 + LLM 判档 —— **并行**发起。
        #    明显没有可判分信息时走确定性短路，避免 mock reranker 按篇幅
        #    给乱码高覆盖率，也避免 LLM 对空话硬夸。
        invalid = kind in (
            ANSWER_UNKNOWN_DIRECTION, ANSWER_NO_INFO, ANSWER_NONSENSE,
        )
        unknown_direction = (
            kind == ANSWER_UNKNOWN_DIRECTION and self._can_swap()
        )
        if invalid:
            sc = no_effective_score(rec)
            judge_band = BAND_SWAP if unknown_direction else BAND_DEGRADE
            judge_why = "该方向未接触过" if unknown_direction else "无有效回答"
            judge_ok = True
        else:
            sc, judge_band, judge_why, judge_ok = self._score_and_judge(answer, rec)

        # 2) 两个源融合成一个档，再定动作（同时递增计数器）
        r_band = band_of(sc["reranker_score"])
        if invalid:
            band = BAND_SWAP if unknown_direction else BAND_DEGRADE
            fuse_rule = "no_effective_swap" if unknown_direction else "no_effective"
        else:
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
        repeat, repeat_sim = (
            (False, 0.0) if invalid else detect_repeat(answer, rec.attempts)
        )
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
                                        r_band, judge_band, judge_why, judge_ok,
                                        sp, body)
            return

        if invalid:
            prior_invalid = any(not a.effective for a in rec.attempts)
            if prior_invalid or rec.hint_used > 0:
                action = "close"
            else:
                rec.follow_ups_used += 1
                rec.degrade_used += 1
                action = "degrade"
        else:
            action = decide_action(band, rec, repeat)
        hint = hint_for(action, rec)
        probe_plan = build_probe_plan(action, rec, sc)

        attempt = AttemptRecord(
            attempt_no=attempt_no, answer=answer,
            reranker_score=sc["reranker_score"], reranker_ok=sc["reranker_ok"],
            base_hits=sc["base_hit"], adv_hits=sc["adv_hit"],
            base_misses=sc.get("base_miss", []), adv_misses=sc.get("adv_miss", []),
            action=action, hint=hint,
            probe_level=action if probe_plan else "",
            probe_target=probe_plan.get("target", ""),
            probe_kind=probe_plan.get("kind", ""),
            reranker_band=r_band, judge_band=judge_band,
            judge_ok=judge_ok, judge_why=judge_why, fuse_rule=fuse_rule,
            band=band,
            repeat=repeat, repeat_sim=repeat_sim,
            effective=not invalid,
            speech=sp,
            body_language=body,
            coverage_method=sc.get("coverage_method", ""),
            coverage_windows=int(sc.get("coverage_windows") or 0),
        )
        rec.attempts.append(attempt)
        # 轮次级 speech 跟着**最后一次带语音的回答**走（后面再补一次文字追问，
        # 不会把已经测到的语速擦掉）。
        if sp.get("used"):
            rec.speech = dict(sp)
        if body.get("used"):
            rec.body_language = dict(body)

        if invalid:
            # 无效回答的回应必须是确定性文本，不再交给 LLM。
            # 否则真实模型和桩模型都可能把“不知道/乱码”续写成“你抓到了主干”，
            # 与 effective=false 和评分状态直接矛盾。
            if action == "close":
                reply = _no_info_close_reply(
                    self.persona_style, rec, attempt_no)
            else:
                reply = _guided_no_info_reply(
                    rec, attempt_no, self.persona_style)
            attempt.interviewer_reply = reply
            attempt.llm_ok = True
            self.transcript.append({"role": "assistant", "content": reply})
            yield {"type": "token", "text": reply}
            self._settle_round(rec, action, attempt)
            return

        # 3) 组装本轮 system（本轮指令放 system，不放进消息列表 —— 修 #1：
        #    原来把考生原话既 append 进历史又塞进 prompt，同一句出现两次）
        #    hint_block 按动作分三种，收尾轮**不能**用 HINT_BLOCK_EMPTY（原因见 prompts.py）
        if action == "close":
            hint_block = HINT_BLOCK_CLOSE
        elif hint:
            hint_block = HINT_BLOCK.safe_substitute(hint=hint)
        else:
            hint_block = HINT_BLOCK_EMPTY

        # 深挖方向 / RAG 参考：**只在 L1/L2/L3 轮注入**。
        #
        # 收尾轮（close）与降级轮（degrade）一律注入空串 —— 四条理由写在
        # prompts.py 的 DEEPEN_BLOCK 上方（一句话版：system 是最弱的杠杆，
        # 而收尾轮的提问倾向是上下文里概率最高的续写；给 close 轮递"问什么"
        # 的素材，是在把一个已知 0/10 的机制往 10/10 推）。
        # degrade 一并排除：那个动作要的是**收拢**，灌"可拓展方向"与它反向。
        # 知识库材料的**末尾旁白**（只在本轮 L1/L2/L3 且检索到时才有值）。
        # 默认空串 = 「一条都不加」——这是 `A11_RAG=0` 那条基线能成立的前提：
        # 借不到编码器时这一轮的消息列表必须与改动前**逐字节相同**。
        kb_narration = ""
        # ⚠️ `rag_kb_block` 必须在这里给默认值，不能只在 `if kb_refs:` 里赋值 ——
        #    `kb_refs` 为空（`A11_RAG=0` 借不到编码器、或回答太短没检索）时
        #    下面 `ROUND_CONTEXT.safe_substitute` 会直接 UnboundLocalError，
        #    整条 /chat 500。（加这个默认值时冒烟 22 项红，就是这个原因。）
        rag_kb_block = RAG_KB_BLOCK_EMPTY
        if action in ("L1", "L2", "L3"):
            deepen_block = (DEEPEN_BLOCK.safe_substitute(
                directions="、".join(d["title"] for d in rec.deepen))
                if rec.deepen else DEEPEN_BLOCK_EMPTY)
            rag_block = (RAG_BLOCK_ACTIVE.safe_substitute(
                refs=ragmod.format_block(rec.rag_refs))
                if rec.rag_refs else RAG_BLOCK_EMPTY)
            # ---- 知识库背景参考（赛题 6.1b + 6.2b）----
            # 这是**本场的第二次检索，与上面那次是两个来源、两个时机**，别合并：
            #   · 上面那次：**出题时**按**题面**检索**题库**派生索引（rag.py），
            #     结果在 rec.rag_refs —— 「这道题还可能怎么问」；
            #   · 这一次：**作答后**按**本轮检索词**检索**真知识库**（kb.py，
            #     ai-reference 那 6 份 md）—— 「这个点，材料里是怎么说的」。
            #     ⚠️ 检索词**默认就是考生刚说的那段话**（= 赛题 6.2)b 字面）；另有保留的
            #        实验档设 `A11_RAG_KB_QUERY_SRC=miss` 改用**他没答到的得分点**（见下）。
            # 为什么非等在这儿：出题那一刻考生还没开口，「根据学生回答的关键词
            # 进行智能追问」（赛题 6.2b）在当时**没有 key 可循**。
            #
            # ⚠️ 走 `lookup_interview()`（只借不载、绝不抛异常）。**借不到编码器就是空**——
            #    实现见 kb.py 的 `_load_borrow_only()`，它刻意不置 `_ready_ev` 闩：
            #    否则面试期置了闩又没借到编码器，交卷后 4a 就永远加载不上了
            #    （静默少东西、连错误都不报）。
            #
            # ---- 检索词从哪来（2026-09-25 晚加档、当晚深夜改回默认）----
            # **默认 = 考生刚说的那段话**（原样透传 `answer`，= 赛题 6.2)b 的字面口径）。
            # 另有一档**保留的实验档** `A11_RAG_KB_QUERY_SRC=miss`：改用**他没答到的得分点**
            # （`sc["base_miss"]` 在前、`adv_miss` 在后）。那一档的实验动机是「拿考生回答
            # 检索捞回来的是同义反复（他刚说过的话的另一份说法），换成漏点后材料本身就是
            # 缺口」—— ⚠️ **实测两档都 0 改善，且事后查明面试官每轮本来就拿着本题全部
            # 得分点（`ROUND_CONTEXT`），缺口信息对它是冗余投喂** ⇒ 按赛题字面选了默认档。
            # **选档理由与那轮对照的数字只写在 `config.RAG_KB_QUERY_SRC` 那段**，这里不复制。
            # ⚠️ 时机（只对 `miss` 档有意义）：漏点在 `session.py:1223` 的 `score_answer()`
            #    里就算好了（比这一行早一百多行），而且是**本轮**的，不是上一轮的。
            #    默认档根本不读它，所以「拿错轮次的漏点」这类风险只在切到 `miss` 时存在。
            # ⚠️ 拼装规则在 `kb.interview_query()` 里（**纯函数**）—— 离线重放与预检脚本
            #    共用同一个，别在这边另写一份，否则「重放对上了」只证明复制品一致。
            # ⚠️ `kb_src` 只进下面那行**日志**（是元数据）：`rag_kb` 的四键白名单**不许加键**
            #    （冒烟里有断言），而且脱敏档下 `raw` 只有占位键。
            kb_query, kb_src = kbmod.interview_query(
                answer, sc.get("base_miss"), sc.get("adv_miss"))
            kb_refs = kbmod.lookup_interview(kb_query, self.job)
            rec.kb_refs = kb_refs
            rec.kb_meta = {
                "used": bool(kb_refs),
                "hit_ids": [r.get("kb_id") for r in kb_refs],
                "sources": [r.get("来源仓库") for r in kb_refs],
                "scores": [r.get("score") for r in kb_refs],
            }
            # ---- 材料**放哪**：system 里的块，还是末尾 user 旁白（2026-09-25）----
            # `A11_RAG_KB_ASIDE=1`（默认）⇒ 材料进旁白、system 里那块留**空串**；
            # =0 ⇒ 留 system = 改动前的位置。**两种情况下材料都只出现一次**。
            #
            # 为什么试末尾：本项目实测**末尾 user 轮是最强的杠杆**（收尾轮 0/10 vs
            # system 全套改法的 4/10~10/10）。⚠️ 但那条证明的是「末尾能**放大指令**」，
            # 不是「内容放末尾也有效」—— 所以这是一次**机制实验**：
            # 先跑 `_tmp_rag_eff_mech.py` 量照念率与误归属率，不合格就设回 "0"。
            #
            # 预算：旁白里材料自己的硬顶是 `RAG_KB_ASIDE_MAX_CHARS`（300），
            # 比 system 那块（600）小；而且旁白**只带最相关的那一条**（system 带 2 条）。
            #
            # ⚠️ 为什么 `max_chars` 不能再往下压（实测，2026-09-25）：`format_block` 是
            #    **整条丢**（`total + len(line) > limit: break`，见 kb.py:519），
            #    而一条 line = 前缀「1. 〔仓库、章节标题〕」+ 片段正文，其中**章节标题
            #    可能是一整段**（实测最长前缀 443 字），片段正文自己还含换行。
            #    真实索引 20,396 条里，单行长度的分布是「200~240 占 61%」，
            #    但最长的一条 **643 字**。所以预算压到 240 时，那几条会**整条丢**、
            #    `material` 变成空串 —— 材料没了而 `raw.rag_kb.hit_ids` 照旧记 2 条，
            #    **没有任何断言会红**。300 能让 98.6% 的记录装下第一条。
            material = ""
            kb_injected = 0
            kb_where = "none"
            if kb_refs:
                if config.RAG_KB_ASIDE:
                    material = kbmod.format_block(
                        kb_refs[:1], max_chars=config.RAG_KB_ASIDE_MAX_CHARS)
                    if material:
                        kb_narration = KB_ASIDE.safe_substitute(kb_aside=material)
                        kb_where = "aside"
                        rag_kb_block = RAG_KB_BLOCK_EMPTY
                if not material:
                    # 旁白放不下（那 ~1.4%）⇒ **回退到 system**，而不是把材料丢掉。
                    # 位置是这一轮要实验的变量，**少一段材料不是** —— 丢掉的话新臂在
                    # 这些轮里凭空少一份材料，两臂的差就掺进了「有没有材料」这个无关因素。
                    material = kbmod.format_block(kb_refs)
                    kb_where = "system(回退)" if config.RAG_KB_ASIDE else "system"
                    rag_kb_block = (RAG_KB_BLOCK_ACTIVE.safe_substitute(kb_refs=material)
                                    if material else RAG_KB_BLOCK_EMPTY)
                # 实际进 prompt 的**条数**（≤ len(kb_refs)）：`format_block` 是整条丢，
                # 而 `kb_meta.hit_ids` 记的是**检索到**的条数 —— 两个口径不同，
                # 所以这一行把「注入几条」也打出来，供日后调字数时对照。
                # ⚠️ 只能数「行首是 `数字. `」的那些 —— 片段正文自己带换行，
                #    按 `split("\n")` 数会把一条算成三条（2026-09-25 修）。
                kb_injected = sum(1 for ln in material.split("\n")
                                  if re.match(r"^\d+\. ", ln))
                # 命中才打（每场最多 10 题 × 2 轮，量可控）。
                # ⚠️ 这一行的用处是**不依赖 `raw` 的旁证**：脱敏档下 `raw` 只有占位键，
                #    而 `A11_RAG=0`（借不到编码器）时这条通路也是「什么都没发生」——
                #    两者从 `raw` 上分不开，服务日志能分开。
                # ⚠️ 2026-09-25 改口径：`片段=` 从 `len(rag_kb_block)`（旁白档下恒为 0！）
                #    改成**材料本身**的长度。行尾的 `注入=` 是**追加**的，既有
                #    「知识库背景参考 n=…」的正则不做锚定 ⇒ 不会被打断。
                # ⚠️ 2026-09-25 晚再加两个**行尾**字段（同一理由：追加在尾部不会打断既有正则）：
                #      `词源=`  —— `answer`（**默认**，原样透传考生回答）/ `miss`（保留的
                #                 实验档，用漏点当检索词）/ `answer_fallback`（**只可能在
                #                 `miss` 档出现**：漏点一条都没有 = 他全答到了，退回回答）。
                #                 切到 `miss` 时，回退率是「那一档有没有被稀释」的**分母**。
                #      `漏点=`  —— base+adv 的**条数**与检索词**字数**，看清 adv 有没有占满
                #                 （L1 轮的 `adv_miss` 常常 = 全部进阶点，见 kb.query_from_misses）。
                # ⚠️⚠️ **绝不许为排障把 `kb_query` 打进来** —— 那是得分点**原文**，
                #    会把答案写进 `logs\`。只打元数据（条数/字数）。要查原文请走离线重放。
                logger.info("sid=%s round=%d attempt=%d 知识库背景参考 n=%d 来源=%s "
                            "片段=%d字 注入=%d 位置=%s 词源=%s 漏点=%d+%d条/%d字",
                            self.session_id, rec.round_no, attempt_no, len(kb_refs),
                            "、".join(sorted({(r.get("来源仓库") or "?")
                                              for r in kb_refs})),
                            len(material), kb_injected, kb_where, kb_src,
                            len(sc.get("base_miss") or []), len(sc.get("adv_miss") or []),
                            len(kb_query))
        else:
            deepen_block, rag_block = DEEPEN_BLOCK_EMPTY, RAG_BLOCK_EMPTY
            rag_kb_block = RAG_KB_BLOCK_EMPTY

        system = self._system + ROUND_CONTEXT.safe_substitute(
            question=rec.question,
            base_points=qb.truncate(rec.base_points, config.POINT_TRUNCATE) or "（无）",
            adv_points=qb.truncate(rec.adv_points, config.POINT_TRUNCATE) or "（无）",
            action_desc=ACTION_DESC.get(action, ACTION_DESC["close"]),
            hint_block=hint_block,
            deepen_block=deepen_block,
            rag_block=rag_block,
            rag_kb_block=rag_kb_block,
        )
        system += self._session_memory()
        if probe_plan:
            system += PROBE_BLOCK.safe_substitute(
                target=probe_plan["target"],
                kind_label=probe_plan["kind_label"],
                instruction=probe_plan["instruction"],
            )
            logger.info("sid=%s round=%d 追问目标 kind=%s target_chars=%d",
                        self.session_id, rec.round_no, probe_plan["kind"],
                        len(probe_plan["target"]))

        # 4) 消息列表 = 真实对话流（含面试官说过的话）+ 本次回答，回答只出现一次
        #    超长回答进 prompt 前截断（记录里仍存原文），防止一个人粘贴五千字撑爆上下文
        self.transcript.append({
            "role": "user",
            "content": qb.truncate(answer, config.ANSWER_TRUNCATE),
        })
        messages = self.transcript[rec.transcript_start:][-config.TRANSCRIPT_LIMIT:]
        style_directive = persona_style_directive(self.persona_style)
        if style_directive:
            messages = messages + [{"role": "user", "content": style_directive}]
        if action == "close":
            # 收尾轮的临时旁白：只发这一次请求，**不写进 transcript**
            # （切片出来的 messages 是新列表，+ 不会污染 transcript）
            messages = messages + [{"role": "user", "content": CLOSE_DIRECTIVE}]
        elif kb_narration:
            # 知识库材料的**末尾 user 旁白**（只有 L1/L2/L3 且检索到材料时才非空）。
            # ⚠️ 顺序硬要求：**先切片、后追加**。反过来的话，`TRANSCRIPT_LIMIT` 到达之后
            #    这条旁白会被下一次切片挤出窗口 —— **间歇消失**（前几轮有、后面没有），
            #    是最难查的一类 bug。这里 `messages` 是切片出来的**新列表**，
            #    `+` 不会污染 `self.transcript` ⇒ 旁白不进对话历史、下一轮不会重复出现。
            # ⚠️ 与 close 互斥（kb_narration 只在 L1/L2/L3 赋值），用 elif 是把这个互斥
            #    写在代码里，而不是靠"反正不会同时发生"。
            messages = messages + [{"role": "user", "content": kb_narration}]
        elif action == "degrade":
            # 降级轮的末尾 user 旁白（2026-09-27）。与上面两条**互斥**，理由同
            # kb_narration 那条：action 只有一个值，用 elif 把这个互斥写进代码，
            # 而不是靠"反正不会同时发生"。
            #
            # 要解决什么：真跑里 degrade 轮的回复写出了收尾语（实测原句
            # 「行，这题你答得住。换一个方向。」），考生顺着它答"我们看下一题吧"
            # ⇒ 那次作答被判"未作答，属敷衍"、reranker 0.0。
            # **是面试官自己的话把考生带进了敷衍。** 详见 prompts.DEGRADE_DIRECTIVE。
            #
            # ⚠️ 顺序硬要求与 kb_narration 完全相同：**先切片、后追加**
            #    （`messages = self.transcript[-LIMIT:]` 已在上方完成）。
            #    反过来会在 TRANSCRIPT_LIMIT 到达后间歇消失 —— 最难查的一类 bug。
            messages = messages + [{"role": "user", "content": DEGRADE_DIRECTIVE}]

        # 5) 流式要面试官的话
        collected, llm_ok = "", True
        pending = ""
        released = False
        probe_gate = bool(
            config.A11_PROBE_QUALITY_GUARD
            and action in ("L1", "L2", "L3", "degrade")
            and probe_plan
        )
        try:
            for piece in self.llm.chat_stream(system, messages):
                collected += piece
                pending += piece
                if (not probe_gate
                        or len(re.sub(r"\s+", "", collected)) >= _PROBE_RELEASE_CHARS):
                    released = True
                    if pending:
                        yield {"type": "token", "text": pending}
                        pending = ""
            if probe_gate and not released:
                if _probe_reply_too_weak(collected):
                    repaired = repair_probe_reply(rec, probe_plan)
                    collected = repaired
                    logger.info(
                        "sid=%s round=%d 追问过短或残缺，已替换为确定性追问",
                        self.session_id, rec.round_no)
                    yield {"type": "token", "text": repaired}
                elif pending:
                    yield {"type": "token", "text": pending}
                    pending = ""
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

        # 6) 收尾污染守卫 —— **只在 degrade 轮**，且在 try/finally **之后**。
        #
        # ⚠️ 为什么必须在 finally 之外：`finally` 里有 `yield`（`_settle_round`
        #    不 yield，但整段包着上面那个 yield 循环），客户端断流时生成器被
        #    close()，`finally` 里再 yield 会抛 `GeneratorExit`。而且真失败
        #    （`llm_ok=False`）时上面已经 raise 走了，这里根本到不了。
        # ⚠️ 只查 degrade：L1/L2/L3 本来就要提问，close 本来就**不该**提问 ——
        #    对 close 跑这个检测会 100% 命中，把观测数字变成噪声。
        #    这一条只针对"该提问却写了收尾语"的那一种越界。
        #
        # ⚠️ 为什么**不像 `detect_repeat` 那样挡掉 `LLM_MOCK`**：那条挡是因为
        #    冒烟第 2/3 次回答是**故意构造成相同文本**的，守卫必然触发、会打掉
        #    成片既有断言。这里没有这个冲突 —— 桩在追问轮返回的
        #    `_MOCK_REPLY` 自带问句、也不含任何收尾措辞 ⇒ `needs_question` 恒 False、
        #    一次都不会触发。于是这里**不挡**，冒烟就能真的跑到这段生产代码
        #    （而不是绕过它），"桩下与改动前逐字节相同"也顺带被验了。
        if action == "degrade" and config.A11_WRAPUP_GUARD:
            if needs_question(collected):
                self.wrapup_missing += 1
                logger.info("sid=%s round=%d 面试官 degrade 轮没有提问"
                            "（回复 %d 字），不计分，只观测",
                            self.session_id, rec.round_no, len(collected))
                if config.A11_WRAPUP_REPAIR:
                    # 兜底：把一句"邀请他继续说"追加到**流尾**。
                    # ⚠️ 绝不改写 `collected` 里已经流出的 token —— 考生可能已经
                    #    读到了前半句，回填等于屏幕上的字凭空变形。
                    # ⚠️ transcript 末条要同步，否则下一轮的上下文里那句追问凭空消失，
                    #    模型会以为自己没问过 → 再问一遍。
                    yield {"type": "token", "text": WRAPUP_NUDGE}
                    collected += WRAPUP_NUDGE
                    if self.transcript and self.transcript[-1].get("role") == "assistant":
                        self.transcript[-1]["content"] = collected
                    attempt.interviewer_reply = collected
                    self.wrapup_repaired += 1
                    logger.info("sid=%s round=%d 已追加收尾修补 %d 字",
                                self.session_id, rec.round_no, len(WRAPUP_NUDGE))

    def _swap_round(self, rec: RoundRecord, answer: str, attempt_no: int, sc: dict,
                    r_band: str, judge_band: Optional[str], judge_why: str,
                    judge_ok: bool, sp: Optional[dict] = None,
                    body: Optional[dict] = None) -> Generator[dict, None, None]:
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
            # 表达指标与正常路径同一份（这一轮虽然作废，但仍会进 swapped_rounds
            # 的报告 —— 报告里那一轮用时/语速不该是空的）。
            speech=sp or dict(asrmod.SPEECH_EMPTY),
            body_language=body or dict(bodymod.BODY_EMPTY),
            coverage_method=sc.get("coverage_method", ""),
            coverage_windows=int(sc.get("coverage_windows") or 0),
        )
        rec.attempts.append(attempt)
        if sp and sp.get("used"):
            rec.speech = dict(sp)
        if body and body.get("used"):
            rec.body_language = dict(body)
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
            pending = bool(rec is not None and rec.assist_used)
            action = "degrade" if pending else "close"
            return {
                "action": action,
                "follow_up": pending,
                "round_open": bool(rec.open) if rec is not None else False,
                "attempts": 0,
                "effective": False,
                "follow_ups_used": rec.follow_ups_used if rec is not None else 0,
                "degrade_used": rec.degrade_used if rec is not None else 0,
                "assist_used": rec.assist_used if rec is not None else 0,
                "hint_used": rec.hint_used if rec is not None else 0,
                "reranker_score": None, "reranker_ok": True,
                "coverage_method": "", "coverage_windows": 0,
                "reranker_band": None,
                "judge_band": None,
                "judge_ok": False,
                "judge_why": "",
                "fuse_rule": "assist" if pending else "",
                "band_disagree": False,
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
            "effective": bool(last.effective),
            "follow_ups_used": rec.follow_ups_used,
            "degrade_used": rec.degrade_used,
            "assist_used": rec.assist_used,
            "hint_used": rec.hint_used,
            "reranker_score": last.reranker_score,
            "reranker_ok": last.reranker_ok,
            "coverage_method": last.coverage_method,
            "coverage_windows": last.coverage_windows,
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
        # 只有至少包含一次有效回答的轮次才值得调用评分模型。
        # 全无效的轮次若也送进去，会浪费调用，还可能把“模型 JSON 抖动”
        # 误记成“评分失败”，污染无效场次的说明。
        scorable = [
            r for r in self.rounds
            if any(bool(getattr(a, "effective", True)) for a in r.attempts)
        ]
        failed_rounds: list[int] = []

        # 每轮一次五维评分；4 路并发（一轮一次 LLM 调用，串行太慢）
        def _score(rec: RoundRecord
                   ) -> tuple[RoundRecord, dict, Optional[str], dict, Optional[str]]:
            # 每一轮的失败都就地捕获成 (data={}, err)，绝不让异常穿出线程池 ——
            # 一轮评分挂掉不该让整场面试拿不到结果
            try:
                if self.scorer.llm is None:
                    return rec, {}, "评分器未初始化（没有可用的 LLM）", {}, ""
                ctx = {
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
                    "kb_evidence": (
                        kbmod.format_block(rec.kb_refs)
                        if config.A11_KB_SCORE and rec.kb_refs else "（无）"
                    ),
                    # 表达客观测量（用时 vs 建议用时 / 语音作答时的语速·停顿·
                    # 填充词）。与 reranker_note 同一个位置、同一套写法：
                    # 它只是**证据**，不给它单独一维、不改任何权重。
                    "pace_note": rec.pace_note(),
                }
                data, err = self.scorer.llm.score_round(ctx)
                obj, obj_err = self.objective.score_round(ctx)
                return rec, data, err, obj, obj_err
            except Exception as e:
                logger.exception("sid=%s round=%d 评分线程异常", self.session_id, rec.round_no)
                return rec, {}, f"{type(e).__name__}: {e}", {}, ""

        if scorable:
            with ThreadPoolExecutor(max_workers=min(4, len(scorable))) as pool:
                for rec, data, err, obj, obj_err in pool.map(_score, scorable):
                    rec.objective_detail = obj or {}
                    rec.objective_detail["error"] = obj_err or ""
                    if err or not data.get("five_dim"):
                        rec.scored = False
                        rec.score_error = err or "模型未返回可解析的五维分"
                        failed_rounds.append(rec.round_no)
                    else:
                        adjusted = dict(data["five_dim"])
                        adjustment = (
                            bodymod.score_adjustment(rec.body_language)
                            if config.A11_BODY_SCORE
                            else {
                                "applied": False,
                                "reason": "disabled",
                                "communication_delta": 0.0,
                                "adaptability_delta": 0.0,
                            }
                        )
                        if adjustment.get("applied"):
                            adjusted = bodymod.apply_to_five_dim(
                                adjusted, rec.body_language)
                        rec.body_score_adjustment = adjustment
                        rec.five_dim = adjusted
                        rec.code_check = data.get("code_check") or {
                            "applicable": False, "correct": None, "note": "",
                        }
                        rec.score_detail = data.get("score_detail") or {}
                        if adjustment.get("applied"):
                            rec.score_detail["body_language_adjustment"] = adjustment
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

        completion_rate = (
            round(self.questions_asked / self.total_questions, 4)
            if self.total_questions else 0.0
        )
        effective_rounds = [
            r for r in scorable
            if any(bool(getattr(a, "effective", True)) for a in r.attempts)
        ]
        has_objective = any(
            isinstance((r.objective_detail or {}).get("correctness_score"),
                       (int, float))
            for r in scorable
        )
        if (not has_any and not has_objective) or not effective_rounds:
            score_status = "invalid"
        elif failed_rounds or self.questions_asked < self.total_questions:
            score_status = "partial"
        else:
            score_status = "valid"
        final_score = score_status == "valid"
        partial = score_status != "valid"
        invalid_session = score_status == "invalid"
        if invalid_session:
            # 没有任何有效回答时，最低档 1 也不该被展示成“20 分”。
            # 分数键保留为 null，与“没有数据”同一语义；原始逐轮记录仍在 raw。
            avg = {d: None for d in config.DIMENSIONS}
            total = None

        score_by_difficulty: dict[str, dict] = {}
        for diff in ("easy", "medium", "hard"):
            rows = [r for r in scorable if r.difficulty == diff and r.five_dim]
            vals = {d: [] for d in config.DIMENSIONS}
            for rec in rows:
                for d in config.DIMENSIONS:
                    v = (rec.five_dim or {}).get(d)
                    if isinstance(v, (int, float)):
                        vals[d].append(float(v))
            d_avg = {d: (round(sum(v) / len(v), 2) if v else None)
                     for d, v in vals.items()}
            score_by_difficulty[diff] = {
                "rounds": len(rows),
                "five_dim_avg": d_avg,
                "total_score": weighted_llm_score(d_avg, self.job),
            }
        _diff_totals = [x["total_score"] for x in score_by_difficulty.values()
                        if x["total_score"] is not None]
        difficulty_adjusted_total = (
            round(sum(_diff_totals) / len(_diff_totals), 2)
            if _diff_totals else None)

        technical_rows = [
            r for r in scorable
            if r.five_dim and r.dim1_label == config.DIMENSIONS[0]
        ]
        tech_values = [
            (r.five_dim or {}).get(config.DIMENSIONS[0]) for r in technical_rows
        ]
        tech_values = [float(v) for v in tech_values if isinstance(v, (int, float))]
        technical_correctness = (
            round(sum(tech_values) / len(tech_values), 2) if tech_values else None)
        content_analysis = {
            "technical_correctness": {
                "score": technical_correctness,
                "rounds": [r.round_no for r in technical_rows],
                "note": "只统计第一维标签为“技术水平”的轮次；行为素质题不参与该值。",
            },
            "knowledge_depth": {
                "score": avg.get(config.DIMENSIONS[0]),
                "rounds": [r.round_no for r in scorable if r.five_dim],
                "note": "与第一维共用证据，不宣称独立测量；明细仍看逐轮分与评语。",
            },
            "logical_rigor": {
                "score": avg.get("逻辑思维"),
                "rounds": [r.round_no for r in scorable if r.five_dim],
                "note": "直接对应“逻辑思维”维度。",
            },
            "job_fit": {
                "score": avg.get("岗位匹配度"),
                "rounds": [r.round_no for r in scorable if r.five_dim],
                "note": "直接对应“岗位匹配度”维度。",
            },
        }

        # ---- 评分依据明细（加法）----
        # 五维分本身与权重完全不动；这里把每一维的理由/证据/可信度聚合成
        # 可复核报告。模型没给明细时 available=false，不伪造依据。
        def _uniq_text(items, limit: int, chars: int = 120) -> list[str]:
            out: list[str] = []
            for item in items:
                text = str(item or "").strip()[:chars]
                if text and text not in out:
                    out.append(text)
                if len(out) >= limit:
                    break
            return out

        detail_rows = [] if invalid_session else [
            r for r in scorable
            if r.scored and isinstance(r.score_detail, dict)
        ]
        detail_available = any(
            bool((r.score_detail or {}).get("available")) for r in detail_rows)
        detail_dims: dict[str, dict] = {}
        for d in config.DIMENSIONS:
            reasons, evidence = [], []
            conf_counts = {"high": 0, "medium": 0, "low": 0}
            for r in detail_rows:
                row = (((r.score_detail or {}).get("dimensions") or {}).get(d) or {})
                if not isinstance(row, dict):
                    continue
                if row.get("reason"):
                    reasons.append(str(row["reason"]))
                evidence.extend(row.get("evidence") or [])
                conf = str(row.get("confidence") or "").lower()
                if conf in conf_counts:
                    conf_counts[conf] += 1
            detail_dims[d] = {
                "score": avg.get(d),
                "reasons": _uniq_text(reasons, 5, 80),
                "evidence": _uniq_text(evidence, 8, 80),
                "confidence_counts": conf_counts,
            }

        missing_points = _uniq_text(
            [p for r in detail_rows
             for p in ((r.score_detail or {}).get("missing_points") or [])],
            10, 100)
        misconceptions = _uniq_text(
            [p for r in detail_rows
             for p in ((r.score_detail or {}).get("misconceptions") or [])],
            10, 100)
        followup_rows = [
            row for r in detail_rows
            for row in ((r.score_detail or {}).get("followup_eval") or [])
            if isinstance(row, dict)
        ]
        gains = [row.get("depth_gain") for row in followup_rows
                 if isinstance(row.get("depth_gain"), int)]
        followup_summary = {
            "transitions": len(followup_rows),
            "target_hits": sum(1 for row in followup_rows
                               if row.get("target_hit") is True),
            "new_information": sum(1 for row in followup_rows
                                   if row.get("new_information") is True),
            "corrected_errors": sum(1 for row in followup_rows
                                    if row.get("corrected_error") is True),
            "avg_depth_gain": round(sum(gains) / len(gains), 2) if gains else None,
        }

        base_hit = base_total = adv_hit = adv_total = 0
        for r in scorable:
            if not r.attempts:
                continue
            best = max(r.attempts, key=lambda a: a.reranker_score)
            base_hit += len(best.base_hits)
            adv_hit += len(best.adv_hits)
            base_total += len(best.base_hits) + len(best.base_misses)
            adv_total += len(best.adv_hits) + len(best.adv_misses)
        conf_values = [
            str((r.score_detail or {}).get("confidence") or "").lower()
            for r in detail_rows
        ]
        if conf_values and all(x == "high" for x in conf_values):
            overall_confidence = "high"
        elif conf_values and all(x == "low" for x in conf_values):
            overall_confidence = "low"
        elif any(x in ("high", "medium") for x in conf_values):
            overall_confidence = "medium"
        else:
            overall_confidence = ""
        score_breakdown = {
            "available": detail_available,
            "dimensions": detail_dims,
            "coverage": {
                "base_hit": base_hit,
                "base_total": base_total,
                "adv_hit": adv_hit,
                "adv_total": adv_total,
                "base_rate": round(base_hit / base_total, 3) if base_total else None,
                "adv_rate": round(adv_hit / adv_total, 3) if adv_total else None,
                "note": "取每轮覆盖率最高的一次作答；这是覆盖率信号，不是事实正确性。",
            },
            "missing_points": missing_points,
            "misconceptions": misconceptions,
            "followup_eval": followup_rows,
            "followup_summary": followup_summary,
            "confidence": overall_confidence,
        }

        # ---- 客观线：SiliconFlow 覆盖率 + Qwen 事实核验 ----
        objective_rows = []
        objective_errors = []
        objective_conf = []
        for rec in scorable:
            detail = rec.objective_detail or {}
            if detail.get("error"):
                objective_errors.append(
                    f"第 {rec.round_no} 题：{detail['error']}")
            correctness = detail.get("correctness_score")
            if not isinstance(correctness, (int, float)):
                continue
            best = (max(rec.attempts, key=lambda a: a.reranker_score)
                    if rec.attempts else None)
            if best is None:
                continue
            b_total = len(best.base_hits) + len(best.base_misses)
            a_total = len(best.adv_hits) + len(best.adv_misses)
            b_rate = len(best.base_hits) / b_total if b_total else 1.0
            a_rate = len(best.adv_hits) / a_total if a_total else 0.0
            coverage_05 = round((0.6 * b_rate + 0.4 * a_rate) * 5, 2)
            misconceptions = detail.get("misconceptions") or []
            claims = detail.get("claims") or []
            objective_round = objective_round_score(
                coverage_05, float(correctness), claims, misconceptions,
                detail.get("point_atoms") or [])
            objective_rows.append({
                "round": rec.round_no,
                "coverage_score": coverage_05,
                "correctness_score": round(float(correctness), 2),
                "objective_score": round(objective_round, 2),
                "evidence": detail.get("evidence") or [],
                "missing_points": detail.get("missing_points") or [],
                "misconceptions": misconceptions,
                "claims": claims,
                "claim_counts": detail.get("claim_counts") or {},
                "target_results": detail.get("target_results") or [],
                "point_atoms": detail.get("point_atoms") or [],
                "confidence": detail.get("confidence") or "",
            })
            if detail.get("confidence") in ("high", "medium", "low"):
                objective_conf.append(detail["confidence"])
        objective_score = (
            round(sum(r["objective_score"] for r in objective_rows)
                  / len(objective_rows), 2)
            if objective_rows else None
        )
        objective_confidence = (
            "low" if "low" in objective_conf
            else "medium" if "medium" in objective_conf
            else "high" if objective_conf else ""
        )
        objective_claims = [
            claim for row in objective_rows for claim in (row.get("claims") or [])
        ]
        objective_claim_counts = {
            key: sum(1 for row in objective_rows
                     for claim in (row.get("claims") or [])
                     if claim.get("verdict") == key)
            for key in ("supported", "contradicted", "insufficient")
        }
        objective = {
            "available": bool(objective_rows),
            "provider": config.OBJECTIVE_PROVIDER,
            "model": config.OBJECTIVE_MODEL,
            "score": objective_score,
            "rounds": objective_rows,
            "errors": objective_errors,
            "confidence": objective_confidence,
            "claims": objective_claims,
            "claim_counts": objective_claim_counts,
            "contradictions": [
                claim for claim in objective_claims
                if claim.get("verdict") == "contradicted"
            ],
        }
        if invalid_session:
            objective["available"] = False
            objective["score"] = None
            objective["rounds"] = []
        subjective = {
            "score": total,
            "five_dim": avg,
            "breakdown": score_breakdown,
        }
        combined = combine_scores(
            objective["score"],
            total,
            objective["confidence"],
            overall_confidence,
            objective_detail=objective,
        )

        notes: list[str] = []
        if not scorable:
            notes.append("没有有效问答轮次")
        if failed_rounds:
            notes.append(f"{len(failed_rounds)} 轮评分失败：{failed_rounds}")
        deg = sum(1 for r in scorable if r.degrade_used > 0)
        if deg:
            notes.append(f"{deg} 轮触发降级引导")
        # 收尾污染（2026-09-27）。两个数分开写：前者是"发生过几次"，
        # 后者是"补上了几次" —— 只写前者会把关掉 REPAIR 的那一档读成"已修好"。
        if self.wrapup_missing:
            notes.append(
                f"{self.wrapup_missing} 轮面试官的引导里没带提问"
                f"（已用兜底补问 {self.wrapup_repaired} 轮）")
        if self.swaps_used:
            # 用户要求报告里注明。措辞只陈述事实与原因，不带评价 —— 换题是
            # 「这题不该问他」，不是「他答砸了」，报告里不能读成后者。
            # 注意这里**不会**连带触发下面那条"只问了 N 题"：换题不占名额，
            # 他最后还是答满了 10 题，那条 note 不该出现。
            why = "；".join(r.swap_reason for r in self.swapped_rounds if r.swap_reason)
            notes.append(f"本场换过 {self.swaps_used} 题（原因：{why or '考生表示不熟悉'}），"
                         f"被换掉的题不计入 {self.total_questions} 题")
        if self.questions_asked < self.total_questions:
            notes.append(f"只问了 {self.questions_asked}/{self.total_questions} 题")
        effective_n = sum(
            1 for r in scorable for a in r.attempts
            if bool(getattr(a, "effective", True))
        )
        if scorable and effective_n == 0:
            notes.append("全部回答均未提供有效技术内容")

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

        # ---- 避重阶梯 + 考点重叠闸的**可见化**（2026-09-27）----
        # 为什么要单独打一行：那两道闸（`pick_level` 的 r0→r3 回退链、以及
        # `KP_OVERLAP_THRESHOLD` 那道重叠闸）**不进任何分数**，只影响抽到哪道题。
        # 于是「它们到底有没有在工作」在报告里是个**沉默**的问题 ——
        # 上一波是靠事后把 `/finish` 整份翻出来数 `pick_levels`（十轮全是 r0）
        # 才看出来的，而 `kp_overlap` 那次读数九轮 0.0、一轮 0.5，
        # 阈值 0.6 ⇒ **一次都没拦下过**。这种事不该每次都靠翻报告。
        # `pick=`/`overlap=` 本来就逐轮打了（见 ask_next_question），
        # 这里补一条**收口**：一场一行，grep 得到。
        #
        # ⚠️ 刻意**不写进 `notes`**：notes 会经 `_write_evaluation` 进
        #    FINAL_SUMMARY 的【需要说明的情况】，也就是**给考生看的那段评语**。
        #    这是 3 号/开发者的内部口径，只该进 raw 与日志
        #    （与 `dim1_labels`、`raw.blindspots` 同一条规矩，见下面那段注释）。
        _ov = [r.kp_overlap for r in self.rounds if r.kp_overlap is not None]
        logger.info("sid=%s finish 避重阶梯 pick_levels=%s ｜ 考点重叠 n=%d "
                    "max=%.3f 闸=%.2f/%.2f（读数 ≥ 闸说明那一轮是靠回退档抽的，"
                    "重叠闸本身不计数，只能靠这两个数判断）",
                    self.session_id, pick_levels or "空", len(_ov),
                    max(_ov) if _ov else -1.0,
                    config.KP_OVERLAP_THRESHOLD, config.KP_OVERLAP_RELAXED)

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

        difficulty_mix: dict[str, int] = {}
        for r in scorable:
            difficulty_mix[r.difficulty] = difficulty_mix.get(r.difficulty, 0) + 1

        self.finished_at = time.time()
        self.phase = PHASE_DONE

        raw = {
            "session_id": self.session_id,
            "job": self.job,
            # 场次类型：exam（正式面试）/ practice（专项强化练习，赛题 4b）。
            # 只进 raw 供 3 号 分辨报告。
            # ⚠️ 2026-09-25 起**有一处按它分支**了：`app/core/growth.py` 的
            #    `_history()` —— 成长档案的走势只吃 exam，练习那一节单列。
            #    理由见 practice.py 文件头第 1 条（练习分数不与正式场次可比）。
            "mode": self.mode,
            "candidate_intro": self.candidate_intro,
            # 面试官风格三档里**实际生效**的那一档（F，2026-09-25）。
            # 只进 raw 供 3 号 分辨「这场是怎么问的」—— 报告里能看出同一岗位
            # 不同风格下的分数分布，否则那批数据又是一堆「只能靠行为反推」的读数。
            # ⚠️ 它**只出、不进**：全项目没有任何一处读它来分支
            #    （与 `mode` 不同 —— 那个有一处分支了，见 __init__ 里的注释）。
            "persona_style": self.persona_style,
            "started_at": round(self.created_at, 3),
            "finished_at": round(self.finished_at, 3),
            "duration_sec": round(self.finished_at - self.created_at, 1),
            "total_questions": config.TOTAL_QUESTIONS,
            "questions_asked": self.questions_asked,
            "total_questions": self.total_questions,
            "completion_rate": completion_rate,
            "effective_rounds": len(effective_rounds),
            "score_status": score_status,
            "score_scope": "completed_rounds_only" if not final_score else "full_session",
            "final_score": final_score,
            "chat_turns": len(self.transcript),
            "weights": weights,
            "difficulty_mix": difficulty_mix,
            "score_by_difficulty": score_by_difficulty,
            "difficulty_adjusted_score": difficulty_adjusted_total,
            "content_analysis": content_analysis,
            "score_breakdown": score_breakdown,
            "objective": objective,
            "subjective": subjective,
            "combined": combined,
            "code_review": [
                {
                    "round": r.round_no,
                    "question_id": r.question_id,
                    **(r.code_check or {}),
                }
                for r in scorable
                if (r.code_check or {}).get("applicable")
            ],
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
            # self.job 只透给 4a 的知识库检索做岗位过滤（见 blindspot.diagnose）
            "blindspots": blindspot.diagnose(self.rounds, self.kg, self.job),
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
            "dimension_info": [
                {
                    "key": d,
                    "label": d,
                    "alternate_label": (config.DIM1_LABEL_BEHAVIORAL
                                        if d == config.DIMENSIONS[0] else ""),
                    "alternate_when": (config.CATEGORY_BEHAVIORAL
                                       if d == config.DIMENSIONS[0] else ""),
                    "behavioral_rounds": (dim1_labels.get(
                        config.DIM1_LABEL_BEHAVIORAL, 0)
                        if d == config.DIMENSIONS[0] else 0),
                }
                for d in config.DIMENSIONS
            ],
            "difficulty_mix": difficulty_mix,
            "difficulty_adjusted_score": difficulty_adjusted_total,
            "score_by_difficulty": score_by_difficulty,
            "content_analysis": content_analysis,
            "score_breakdown": score_breakdown,
            "objective": objective,
            "subjective": subjective,
            "combined": combined,
            "code_review": [
                {
                    "round": r.round_no,
                    "question_id": r.question_id,
                    **(r.code_check or {}),
                }
                for r in scorable
                if (r.code_check or {}).get("applicable")
            ],
            "score_semantics": {
                "scoring_version": config.SCORING_VERSION,
                "five_dim_avg": "0-5 分；null 表示该维度没有数据，不是 0 分",
                "score_step": config.SCORE_STEP,
                "score_status": "valid=完整正式分；partial=完成度或评分失败；invalid=没有有效评分",
                "completion_rate": "questions_asked / total_questions",
                "reranker_score": "得分点覆盖率信号，不是技术正确性结论",
                "coverage_method": "full_then_window_max",
                "total_score_100": "由 0-5 总分折算，仅用于展示",
                "difficulty_adjusted_score": "easy/medium/hard 各自均分后再等权平均；"
                                             "避免难度构成直接改变总均分",
                "content_analysis": "从已有逐轮五维派生；knowledge_depth 与第一维共用证据，"
                                    "不是独立模型指标",
                "score_breakdown": "逐维评分依据、覆盖率与 followup_eval 明细；"
                                   "不新增第六维、不改五维权重",
                "objective": "SiliconFlow 覆盖信号 + Qwen 逐主张事实核验；"
                             "不评价表达和软技能",
                "subjective": "DeepSeek 五维评分；覆盖逻辑、表达、应变和岗位匹配",
                "combined": "客观与主观的未校准合成分，仅用于展示",
                "code_review": "算法/编程题的附加检查，不新增维度、不改五维权重",
            },
            # ---- 新增：给 3 号评估用的完整明细 ----
            "completion_rate": completion_rate,
            "effective_rounds": len(effective_rounds),
            "score_status": score_status,
            "score_scope": "completed_rounds_only" if not final_score else "full_session",
            "final_score": final_score,
            "partial": partial,
            "notes": notes,
            "raw": raw,
            "cached": False,
        }

        # ---- 成长档案摘要（加法：**顶层新键**，raw 里一个键都不动）----
        # 错题本 / 考点地图 / 历史成绩追踪（赛题 4）要的那份「成绩单摘要」，
        # 由 1 号 存进他的库、之后回传给 `POST /growth` 做聚合。见 app/core/growth.py。
        #
        # ⚠️ 函数内 import：growth 在模块层 import 了本模块的 SessionError，
        #    模块层互相 import 会成环。
        # ⚠️ 为什么挂在 /finish 的响应里、而不是单开一个端点：1 号 交卷时就**顺手**
        #    拿到了要存档的那份，不用多一次往返；`/result/{sid}` 是同一个 FinishResp，
        #    自动也有。
        # ⚠️ 关掉开关时是 **None**，不是 `{}` 也不是「这个键不存在」：
        #    None =「本次响应不含摘要」，{} =「有摘要但它是空的」—— 两者必须分得开，
        #    否则 1 号 会把「没开」存成一堆空档案。
        # ⚠️ 它是 `raw` 之外**第一个无论 A11_RAW_DETAIL 都会出门**的新字段，
        #    所以必须白名单构造（build_digest 全程 .get()，且**绝不抛** ——
        #    它挂了会把整场面试的收口打挂）。
        if config.A11_GROWTH:
            from app.core import growth as growmod
            envelope["digest"] = growmod.build_digest(envelope)
        else:
            envelope["digest"] = None

        # ⚠️ 上面这个开关是**交卷那一刻**读的，不是每次应答时读的 —— 与
        #    `A11_RAW_DETAIL`（每次组响应时读，所以同一场能翻档重读）**不一样**：
        #    摘要一旦生成就存在 `_result` 里，之后改这个开关不会让已交卷的场次
        #    变出/变没摘要。本项目的 env 改动本来就要重启进程才生效，所以这是
        #    有意的：存档的那份摘要在交卷那一刻就定稿，事后翻档不会让 1 号
        #    存过的和重新读到的两个版本对不上。

        # ---- 复盘清单（加法：**顶层新键**，给考生看的）----
        # `summary` 那段话是**评价**；考生看完知道自己「中上」，不知道差在哪、下一步做什么。
        # 考点级的诊断（hit）本来就有，但只在 `raw.blindspots` 里 —— 脱敏档下他看不到。
        # 这份清单把诊断搬出来、翻成人话，再配一个今天就能做的动作。见 app/core/review.py。
        # ⚠️ 与 digest 同款：白名单构造、绝不抛、`raw` 一个键都不动、不受 A11_RAW_DETAIL
        #    影响、开关是**交卷那一刻**读的（理由同上）。
        # ⚠️ 严格说 review 可以**从 digest 派生**（考点那部分同源）。仍然让它自己读 `raw`：
        #    digest 会在 `A11_GROWTH=0` 时整份关掉，而「给考生看复盘」不该被
        #    「给 1 号存档」那个开关连坐 —— 两个功能各自能单独关。
        if config.A11_REVIEW:
            from app.core import review as reviewmod
            envelope["review"] = reviewmod.build_review(envelope)
        else:
            envelope["review"] = None

        # ---- 表达客观测量（加法：**顶层新键**，给考生看的）----
        # 语音链（whisper / VAD / 停顿 / 填充词 / 音量三指标 / SER 情感 /
        # `confidence_band()`）此前**只**以 `$pace_note` 的形式进了评分 prompt：
        # 它偷偷影响「沟通表达 / 应变能力」两维，考生却在报告上一个字都看不到，
        # 无从知道自己哪里说得不好（赛题 020 的痛点正是「难以全面自我评估」，
        # 038 逐字要求「**评估**…流畅度、语速、语气自信度」）。这一份把它端出来。
        #
        # ⚠️ 与 `digest`/`review` 同款：白名单构造、绝不抛、`raw` 一个键都不动。
        # ⚠️ 与它们**唯一的**不同：**不挂开关**。另两个各有 `A11_GROWTH` /
        #    `A11_REVIEW`（一个是给 1 号 存档、一个是给考生复盘，各自可单独关）；
        #    这一个就是「把已经算出来的测量告诉考生」，没有关掉的理由
        #    —— 关掉它等于把 3b 对考生的可见价值清零，那正是本波要修的病。
        # ⚠️ 也不受 `A11_RAW_DETAIL` 影响：它在 `raw` **外面**的顶层
        #    （`_with_raw_detail` 只替换 `out["raw"]`），所以交付默认档
        #    （`A11_RAW_DETAIL=0`）下照常出门 —— 这是本波的全部意义。
        try:
            envelope["pace_note"] = candidate_pace_note(self.rounds)
        except Exception:
            # 与 digest/review 同一条纪律：它挂了不能把整场面试的收口打挂。
            logger.exception("sid=%s 表达客观测量汇总失败，本场 pace_note 置 None",
                             self.session_id)
            envelope["pace_note"] = None

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
        if not any(
            bool(getattr(a, "effective", True))
            for r in self.rounds for a in r.attempts
        ):
            return ("本场所有回答都没有提供有效技术内容，无法判断具体考点掌握程度，"
                    "也不能据此得出岗位胜任力结论。"
                    + ("（" + "；".join(notes) + "）" if notes else ""))
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
        # ---- 逐轮给「题 + 该轮全部考点名 + 该轮评语」（2026-09-27 改）----
        # 旧写法是 `[... for r in self.rounds for kp in r.knowledge_points][:10]` ——
        # **跨全场截断到 10 条**，于是：① 后面几轮的考点整批消失；② 考点名与轮次
        # 的对应关系全丢，模型不知道哪个点是哪道题的；③ 题干一个都没有。
        # 「强项（具体到知识点）」这个要求在那份输入下只能靠猜 —— 真跑里就猜出了
        # 一个本场没考过的「Spring 循环依赖」。
        # ⚠️ 截断**仍在**，但改成按轮截（每张卷子都不丢），且不再砍考点名 ——
        #    考点名是护栏的白名单，砍它等于让护栏自己失明。
        _tp_lines: list[str] = []
        for r in self.rounds:
            if not r.attempts:
                continue                      # 没作答过的轮不给（评分口径同此）
            _names = [(kp.get("title") or "").strip() for kp in r.knowledge_points]
            _names = [n for n in _names if n]
            _tp_lines.append(
                f"  第 {r.round_no} 题（{r.stage}/{r.difficulty}）："
                f"{qb.truncate(r.question, config.SUMMARY_STEM_MAX) or '（题面未记录）'}"
                f"｜考点：{'、'.join(_names) or '（该题未绑考点）'}")
        topics = "\n".join(_tp_lines) or "（未记录）"
        extra = ("\n【需要说明的情况】" + "；".join(notes) + "\n") if notes else "\n"

        user = FINAL_SUMMARY.safe_substitute(
            job=self.job, scores=scores_text, topics=topics,
            weights_text=config.weights_text_for(self.job), extra=extra)

        # ---- 总评护栏（2026-09-27）----
        # 关掉开关 ⇒ **逐字回到旧样**（同一条"关掉新功能 = 与加之前逐字节相同"的约定）。
        if not config.A11_SUMMARY_GUARD:
            try:
                return self.llm.chat(SYSTEM_SUMMARY, [{"role": "user", "content": user}],
                                     temperature=config.LLM_TEMPERATURE)
            except Exception as e:
                logger.exception("sid=%s 生成面试评价失败", self.session_id)
                return f"（面试评价生成失败：{type(e).__name__}: {e}）"

        try:
            truth_norm, _truth_raw = sg.ground_truth(self.rounds)
            alien = sg.make_alien_index(self.job)
            msgs = [{"role": "user", "content": user}]
            last_problems: list[str] = []
            # 最多两次：第一次 + 带具体错处的一次重生。**不做局部修补**
            # （局部修补要在自由文本上做手术，比整段重生更容易把话改坏）。
            for attempt in (1, 2):
                text = self.llm.chat(SYSTEM_SUMMARY, msgs,
                                     temperature=config.LLM_TEMPERATURE)
                if not (text or "").strip():
                    last_problems = ["上一次输出为空"]
                else:
                    rep = sg.audit(text, truth_norm, alien,
                                   config.SUMMARY_ALIEN_KP_MIN_CHARS)
                    if rep["ok"] and rep["tags"]:
                        logger.info("sid=%s 总评通过护栏（第 %d 次，标注 %d 个考点，"
                                    "%d 字）", self.session_id, attempt,
                                    len(rep["tags"]), len(text))
                        return sg.clean(text)
                    # 没有标注也当"不干净"：标注是这道网能工作的前提，
                    # 放过它等于让护栏退化成"什么都不查"。
                    last_problems = rep["problems"] or ["没有用 [[考点名]] 标出任何考点"]
                if attempt == 1:
                    msgs = msgs + [{"role": "assistant", "content": text or ""},
                                   {"role": "user", "content": sg.feedback(last_problems)}]
                    logger.info("sid=%s 总评第 1 次没过护栏，带错处重生一次：%s",
                                self.session_id, "；".join(last_problems)[:300])
            logger.warning("sid=%s 总评两次都没过护栏，改用确定性兜底：%s",
                           self.session_id, "；".join(last_problems)[:300])
            return sg.fallback_summary(self.rounds, avg)
        except Exception:
            # 与 digest/review 同一条纪律：护栏自己挂了，退回**不用护栏**的老路，
            # 而不是让整场面试的收口打挂。
            logger.exception("sid=%s 总评护栏失败，退回无护栏生成", self.session_id)
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
_RE_PERSONA_NAME = re.compile(r'自称\s*[“"]([^”"]{1,12})[”"]')


def persona_name(persona: str, fallback: str = "面试官") -> str:
    """Extract the in-character interviewer name from the persona file."""
    match = _RE_PERSONA_NAME.search(persona or "")
    return match.group(1).strip() if match else fallback


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


# ============================================================
# 考生自述（简历）的预处理（E，2026-09-25）
# ============================================================
# 两件事，都是**纯函数**（冒烟直接 import 断言，不烧 LLM）：
#   `sanitize_intro()` 把自述压成能安全放进 prompt 的一段纯文本；
#   `intro_snippet()`  从里面摘一句短引文给开场白用。
#
# ⚠️ 为什么第一件是安全件而不是美化件：自述是**考生可控的自由文本**，
#    而它要进 system。system 里多一个换行就多一个「新的一段指令」的位置 ——
#    `_CTRL_RE` 把换行/制表/零宽字符全部压成单个空格，所以它**只能**是一句话，
#    伪造不出新的段落结构。这是结构性的，不靠提示词自觉。
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f​-‏  ﻿]+")
_WS_RE = re.compile(r"\s+")
# 开场白引文要剥掉的开头寒暄（只在**最前面**剥一次，不碰正文里的同形词）
_SNIPPET_GREET_RE = re.compile(r"^(大家好|各位好|你们好|你好|您好|面试官好|考官好)[，,、:： ]*")


def sanitize_intro(text, max_chars=None) -> str:
    """
    考生自述 → 进 prompt 的安全形态。空/全空白返回空串（调用方据此不注入）。

    ① 控制字符与换行压成单空格（**防伪造段落**，见上）
    ② 连续空白折叠
    ③ 截到 `max_chars`，截断处补一个省略号 —— 不留半个字，也不静默变短
    """
    if not text:
        return ""
    cap = config.INTRO_MAX_CHARS if max_chars is None else int(max_chars)
    s = _WS_RE.sub(" ", _CTRL_RE.sub(" ", str(text))).strip()
    if cap > 0 and len(s) > cap:
        s = s[:cap].rstrip() + "……"
    return s


def intro_snippet(text, limit=None) -> str:
    """
    从自述里摘一句短引文，给开场白用。摘不到就回空串。

    取**第一句**（按中英文句读切）而不是前 N 个字：
    「做过三年订单系统。另外我……」的前一句是身份，后一句常是套话。
    切不出句读就退回整段的前 N 个字符。

    ⚠️ **逗号不算句读** —— 所以「我做过三年订单系统，熟悉 JVM 调优。」是**一句**，
    截到 40 字为止。这是刻意的：中文简历的第一句常常是「身份 + 技术栈」一长句，
    按逗号切会把最该被引用的那半句丢掉。

    另外剥掉开头的寒暄（「大家好」「您好」「面试官好」之类）：引文要接在
    「我看了你的自我介绍，其中提到「…」」后面，开头挂一句「大家好」读起来很怪。
    """
    lim = INTRO_SNIPPET_MAX if limit is None else int(limit)
    s = sanitize_intro(text, max_chars=0)      # 0 = 不截断，先拿全量再决定
    if not s:
        return ""
    # ⚠️ 顺序要紧：**先剥寒暄再切句**。反过来会踩「大家好！我做过…」——
    #    第一个句读落在寒暄里，切出来的 head 是「大家好」，剥完就剩空串。
    src = _SNIPPET_GREET_RE.sub("", s, count=1).strip("，,、:： ！!。.？?；;")
    head = re.split(r"[。！？；!?;]", src, maxsplit=1)[0].strip("，,、:： ")
    if not head:
        return ""
    if len(head) > lim:
        head = head[:lim].rstrip()
    return head
