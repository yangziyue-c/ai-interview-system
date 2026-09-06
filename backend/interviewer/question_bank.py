"""题库策略：开场题 / 四层追问 / 换新题 / 收尾（P2 算法落地，数据源 questions 表）

背景（2026-09-06）：P2（后端开发 B）交付的模拟面试算法经两轮审查，
策略骨架正确（题库驱动开场/追问/收尾 + 触发条件解析 + 锚点层级推断），
本模块将该策略落地到主项目，数据源从 xlsx 改为 questions 表（451 题），
供 AIInterviewerAdapter 作为最高优先级数据源调用。

策略要点（唯一入口 pick_next）：
- 开场题：stage=开场热身 且 difficulty=easy
- 追问：从 history 尾部找最近一条题库题干作「锚点」，锚点之后已追问
  次数 n 决定层级：n=0 → L1 关键词触发；n=1 → L2 递进；n=2 → L3 极限；
  n>=3 或无锚点 → 换新题
- 换新题：最后两轮强制收尾交流（真实题库每题都带非空追问计划，若不强制，
  追问链会一直延伸到最后一轮，收尾永不出现——实测 0/2700 场模拟验证）；
  round>=3 深度考察（无则核心考察）；否则核心考察

分层说明：pick_next 是唯一的 async 入口（加载该岗位题目后交给纯函数
pick_next_from_questions），决策与解析全部在同步纯函数中——便于 P2 修改
与单元测试（见 backend/tests/test_question_bank.py 的决策矩阵用例）。
"""
import logging
import random
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.config import settings
from app.models import Question
from app.models.question import QUESTION_DIFFICULTIES, QUESTION_STAGES

logger = logging.getLogger(__name__)

# 阶段/难度词表从模型常量解包（单一来源，词表调整时策略自动跟随）
STAGE_OPENING, STAGE_CORE, STAGE_DEEP, STAGE_CLOSING = QUESTION_STAGES
EASY, _MEDIUM, _HARD = QUESTION_DIFFICULTIES


@dataclass
class FollowUpPlan:
    """一道题的四层追问计划（parse_follow_up_triggers 的解析结果）"""

    l1: list[tuple[str, str]] = field(default_factory=list)  # (触发关键词, 追问文本)
    l1_vague: list[str] = field(default_factory=list)        # 回答笼统时的兜底追问
    l2: list[str] = field(default_factory=list)              # 递进追问（按 ①② 顺序）
    l3: list[str] = field(default_factory=list)              # 极限追问
    fallback: list[str] = field(default_factory=list)        # 降级策略追问


# ---------------- 追问触发条件解析 ----------------

# L2/L3 行箭头后的引导词前缀（真实题库措辞：L2 行「→ 追问：…」、
# L3 行「→ 极限场景：/综合场景：/深度追问：…」、fallback 行「→ 追问：…」）
# 冒号必选：无冒号的「追问X」是追问文本本体（如「追问实战经验」），不可剥
_FOLLOW_UP_PREFIX_RE = re.compile(r"^追问[:：]\s*")
_L3_PREFIX_RE = re.compile(r"^(?:极限场景|综合场景|深度追问)[:：]\s*")

# 四段标题识别表：只认行首的【L1 /【L2 /【L3 /【降级策略 前缀——真实题库段头
# 均带【】括号；刻意不用裸词匹配（「降级策略」「L1-触发追问」等词会出现在内容行
# 开头/中间，如 L3 行「…结合消息合并与降级策略，设计专项测试方案？」，会误切段）
_SECTION_MARKERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("【L1",), "l1"),
    (("【L2",), "l2"),
    (("【L3",), "l3"),
    (("【降级策略",), "fallback"),
)

# L1 触发行：若[提到X / 回答… / 只答… / 条件短语] → 追问：Y
# 真实题库变体（解析均覆盖）：
# - 带引号：① 若提到"hashCode" → 追问：…
# - 无引号：② 若提到类型兼容 → 追问结构化类型与名义类型的区别
# - 条件式：① 若未处理空数组 → 追问：…（条件文本即触发关键词）
# - 无冒号：③ 若只答理论 → 追问实战经验（「追问」为文本本体，不剥）
# - 半角箭头：若提到"hash" -> 追问：…（箭头按整体匹配，避免 "-" 落入 condition）
# - 引述式：若回答有深度 → 追问「请阐述…」的实践细节（「追问」后无冒号，保留）
_L1_TRIGGER_RE = re.compile(r"若(.+?)\s*(?:→|->)\s*(?:追问[:：]\s*)?(.+)$")


def _split_arrow(line: str) -> str | None:
    """按箭头拆分行，返回箭头后的文本（兼容全角 → 与半角 ->）；无箭头返回 None"""
    if "→" in line:
        return line.split("→", 1)[1].strip()
    if "->" in line:
        return line.split("->", 1)[1].strip()
    return None




def parse_follow_up_triggers(text: str) -> FollowUpPlan:
    """解析题库四段结构：【L1-触发追问】【L2-递进追问】【L3-极限追问】【降级策略】

    兼容真实题库的全部行格式（均已用开发库 451 行实测覆盖）：
    - 段头与内容挤同一行（scene_039~043 系统设计题：「【L1-触发追问】①若提到"协议"→…」）
    - 无引号关键词行与条件式行（若提到类型兼容 / 若未处理空数组）
    - 单行多子句（「若回答有深度 → 追问X；若回答笼统 → 追问Y」）
    """
    plan = FollowUpPlan()
    if not isinstance(text, str) or not text.strip():
        return plan

    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 一行可能同时含段头与内容（挤行格式），while 逐段消费
        while line:
            matched = None
            for markers, section in _SECTION_MARKERS:
                for marker in markers:
                    if line.startswith(marker):
                        matched = (len(marker), section)
                        break
                if matched:
                    break
            if matched:
                current_section = matched[1]
                line = line[matched[0]:].strip()
            else:
                _parse_content_line(plan, current_section, line)
                break
    return plan


def _parse_content_line(plan: FollowUpPlan, section: str | None, line: str) -> None:
    """把一行内容按当前段分类进 FollowUpPlan；无箭头的行跳过（防脏数据，宁可漏不可脏）"""
    if section == "l1":
        # 单行多子句（「若A→追问X；②若B→追问Y」挤一行）按「；[序号]若」切分逐段解析，
        # 避免把后续子句的模板条件残留在追问文本里
        for part in re.split(r"[;；]\s*(?=(?:[①②③④⑤⑥⑦⑧⑨]\s*)?若)", line):
            _parse_l1_part(plan, part)
        return

    if section in ("l2", "l3", "fallback"):
        tail = _split_arrow(line)
        if tail is None:
            return
        prefix_re = {"l2": _FOLLOW_UP_PREFIX_RE, "l3": _L3_PREFIX_RE, "fallback": _FOLLOW_UP_PREFIX_RE}.get(section)
        if prefix_re is not None:
            tail = prefix_re.sub("", tail)
        getattr(plan, section).append(tail)


# 正向条件词：若回答有深度/流畅/准确 → 深挖追问（答得好的进阶素材，归入 L2 头部，
# 与 L2 递进语义一致；若归 l1_vague 会方向反转——胜任者永不触发、笼统者收到深挖题）
_POSITIVE_CONDITIONS = ("有深度", "流畅", "准确", "正确", "详细", "完整")


def _parse_l1_part(plan: FollowUpPlan, part: str) -> None:
    """解析 L1 段的一个触发行片段（已被切掉多子句）"""
    match = _L1_TRIGGER_RE.search(part)
    if match is None:
        return
    condition = match.group(1).strip()
    tail = match.group(2).strip()
    if condition.startswith("提到"):
        trigger = condition[2:].strip().strip('"“”')
        if trigger:
            plan.l1.append((trigger, tail))
    elif condition.startswith(("回答", "只答")):
        if any(word in condition for word in _POSITIVE_CONDITIONS):
            plan.l2.insert(0, tail)
        else:
            plan.l1_vague.append(tail)
    else:
        # 条件式行（若未处理空数组/若只返回最大和）→ 条件文本即触发关键词
        plan.l1.append((condition, tail))


# 笼统判定的精确短语表。刻意不用裸「不会」——技术回答最常见的「不会产生脏读/
# 不会导致数据不一致」等确定性否定句会被误伤；只收录明确的露怯表达。
_VAGUE_PHRASES = (
    "不知道", "不清楚", "不太懂", "不了解", "没接触过", "忘记了",
    "不会做", "不会答", "不太会", "没学过", "没做过", "没写过",
)


def is_vague_answer(text: str) -> bool:
    """判断候选人回答是否笼统（触发「展开说说」兜底追问）

    注意：不用「简单/基本/大概」——「简单工厂模式」「基本类型」会被误伤；
    也不用裸「不会」——「不会产生脏读」是确定性否定而非露怯。
    本函数是项目内「回答简略程度」的唯一口径（Mock 追问与题库策略共用）。
    """
    if not text or len(text.strip()) < 20:
        return True
    return any(phrase in text for phrase in _VAGUE_PHRASES)


def last_candidate_answer(history: list[dict]) -> str:
    """取 history 中最后一条候选人回答（无则空串）"""
    for msg in reversed(history):
        if msg.get("role") == "candidate":
            return (msg.get("content") or "").strip()
    return ""


# ---------------- 题库查询与选题 ----------------

async def _questions_of_position(db: AsyncSession, position: str) -> list[Question]:
    """该岗位全部题目（每岗约 150 题，单轮内一次加载后内存过滤）

    只投影决策用到的 4 列：8 个长文本列（reference_answer/score_points 等）
    每行 1~3KB，全列加载每轮浪费数百 KB，评分素材与出题策略无关。
    """
    result = await db.execute(
        select(Question)
        .options(load_only(
            Question.id, Question.question, Question.interview_stage,
            Question.difficulty, Question.follow_up_triggers,
        ))
        .where(Question.position_code == position)
    )
    return list(result.scalars())


async def pick_next(
    db: AsyncSession, position: str, round_no: int, history: list[dict], is_follow_up: bool
) -> str | None:
    """策略唯一入口：加载该岗位题目后交给纯函数决策；无题/未命中返回 None（调用方降级）"""
    questions = await _questions_of_position(db, position)
    return pick_next_from_questions(questions, round_no, history, is_follow_up)


def pick_next_from_questions(
    questions: list[Question], round_no: int, history: list[dict], is_follow_up: bool
) -> str | None:
    """题库策略决策（纯函数，决策矩阵可直接单测）"""
    if not questions:
        return None
    asked = {
        (msg.get("content") or "").strip()
        for msg in history
        if msg.get("role") == "interviewer"
    }
    if not is_follow_up:
        row = pick_stage(questions, (STAGE_OPENING,), asked, difficulty=EASY)
        return row.question if row is not None else None
    return _pick_follow_up(questions, round_no, history, asked)


def pick_stage(
    questions: list[Question],
    stages: tuple[str, ...],
    asked: set[str],
    difficulty: str | None = None,
) -> Question | None:
    """按阶段顺序随机抽一题（开场/换新/收尾共用），前一个阶段无题自动降级下一个"""
    for stage in stages:
        pool = [
            q for q in questions
            if q.interview_stage == stage
            and (difficulty is None or q.difficulty == difficulty)
            and q.question not in asked
        ]
        if pool:
            return random.choice(pool)
    return None


def find_anchor_question(
    questions: list[Question], history: list[dict]
) -> tuple[Question | None, list[str]]:
    """从 history 尾部向前找最近一条题库题干作「锚点」

    返回 (锚点题, 锚点之后的追问文本列表)——追问次数 = len(列表)，单一事实源
    永不脱钩。只做精确匹配（索引 O(1)、strip 归一集中一处）：history 中的
    interviewer 消息要么是从题库抽出的原文（精确可中），要么是追问文本
    /Mock/LLM 产物（不在题库），计入追问文本。刻意不用包含匹配——L1 追问
    文本常内嵌引用题干（如「在「String、StringBuilder、StringBuffer有什么
    区别？」的实际使用过程中…」），包含匹配会把追问误判成新锚点，追问链断链。
    """
    index = {q.question.strip(): q for q in questions}
    trailing: list[str] = []
    for msg in reversed(history):
        if msg.get("role") != "interviewer":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        anchor = index.get(content)
        if anchor is not None:
            return anchor, trailing
        trailing.append(content)
    return None, []


# ---------------- 追问决策 ----------------

def _in_closing_window(round_no: int) -> bool:
    """最后两轮强制收尾（总轮数 = 1 + MAX_FOLLOW_UP_ROUNDS，round 从 1 起，
    round>=MAX_FOLLOW_UP_ROUNDS 即第 6/7 轮）；窗口判定单一事实源，
    MAX_FOLLOW_UP_ROUNDS 调整时自动跟随"""
    return round_no >= settings.MAX_FOLLOW_UP_ROUNDS


def _pick_follow_up(
    questions: list[Question], round_no: int, history: list[dict], asked: set[str]
) -> str | None:
    """追问主逻辑：锚点 + 层级推断（n=0 L1 / n=1 L2 / n=2 L3 / n>=3 换新题）

    - 最后两轮强制收尾交流（真实题库每题都带非空追问计划，若仍走锚点链，
      追问会延伸到最后一轮，收尾永不出现）
    - 开场题不做锚点追问：阶段推进设计为 开场(1) → 核心考察 → 深度考察 → 收尾，
      开场题深挖会挤掉核心考察阶段
    - 候选优先级：L1 关键词命中 → 笼统兜底 → 降级策略 → L2 → L3
    - 回答笼统在任一层级都落降级策略（候选人说不知道时不该继续递进追问）
    - 胜任但未命中关键词 → 换新题（降级策略只用于回答困难时）
    """
    if _in_closing_window(round_no):
        return _pick_new_question_text(questions, round_no, asked)

    anchor, trailing_texts = find_anchor_question(questions, history)
    if anchor is None or anchor.interview_stage == STAGE_OPENING:
        return _pick_new_question_text(questions, round_no, asked)

    plan = parse_follow_up_triggers(anchor.follow_up_triggers)
    answer = last_candidate_answer(history)
    # 追问去重范围=本锚点链内（trailing）：题库追问模板跨题大量重复，
    # 全场去重会让前一锚点消耗的共享文本排挤后续锚点，导致提前换新题
    asked_follow_ups = set(trailing_texts)
    follow_count = len(trailing_texts)

    candidates: list[str] = []
    if follow_count == 0:
        for keyword, follow_up in plan.l1:
            if keyword and keyword.lower() in answer.lower():
                candidates = [follow_up]
                break
        if not candidates and is_vague_answer(answer):
            candidates = plan.l1_vague + plan.fallback
        # 胜任但未命中关键词 → candidates 空 → 换新题
    elif follow_count in (1, 2):
        if is_vague_answer(answer):
            candidates = plan.fallback
        else:
            candidates = plan.l2 if follow_count == 1 else plan.l3
    # follow_count >= 3 → candidates 空 → 换新题

    hit = next((t for t in candidates if t and t not in asked_follow_ups), None)
    if hit:
        return hit
    # 换新题：本轮回答笼统（连续露怯）时不优先 hard 深度题
    return _pick_new_question_text(questions, round_no, asked, avoid_hard=is_vague_answer(answer))


def _pick_new_question_text(
    questions: list[Question], round_no: int, asked: set[str], avoid_hard: bool = False
) -> str | None:
    """换新题：最后两轮收尾交流；round>=3 深度考察（无则核心考察）；否则核心考察"""
    if _in_closing_window(round_no):
        row = pick_stage(questions, (STAGE_CLOSING,), asked)
        if row is not None:
            return row.question
    # 换新题的阶段推进：前段核心考察、后半段（round>=3，经验值）深度优先；
    # 连续露怯的回答（avoid_hard）跳过深度考察，避免把 hardest 题发给最弱候选人
    stages = (STAGE_DEEP, STAGE_CORE) if round_no >= 3 and not avoid_hard else (STAGE_CORE,)
    row = pick_stage(questions, stages, asked)
    return row.question if row is not None else None
