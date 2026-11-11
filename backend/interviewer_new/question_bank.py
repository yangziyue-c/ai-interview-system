"""题库策略（V5 结构化数据源版）：开场题 / 三级追问 / 换新题 / 收尾

数据源：`questions` 表（V5 交付包 5012 题 / 5 岗位，由
`scripts/import_question_bank.py` 导入）。

与旧版（`backend/interviewer/question_bank.py`，V4 xlsx 数据源）的差异
============================================================
**保留的决策骨架**（经两轮审查 + 2700 场模拟验证，行为不变）：
- 开场题：`interview_stage=开场热身` 且 `difficulty=easy` 随机；
- 追问锚点：`find_anchor_question` 以「history 尾部最近一条题库题干」为锚点，
  锚点之后已追问次数 n 决定层级（n=0→L1 / n=1→L2 / n=2→L3 / n≥3→换新题）；
- 最后两轮（round ≥ MAX_FOLLOW_UP_ROUNDS）强制换新题，保证收尾出现；
- 笼统判定 `is_vague_answer` 为全项目「回答简略程度」的唯一口径。

**重写的三处**：
1. 追问素材**直接读结构化列**（`follow_up_l1/l2/l3`、`fallback_strategy`），
   不再解析 V4 那种「【L1-触发追问】① 若提到"x" → 追问：…」的混合文本
   （旧解析层 119 行、6 种格式变体兼容，随 V5 换代整体废弃）；
2. L1 触发由「关键词子串匹配」改为**语义分流**：V5 的 L1 触发条件是描述式
   （实测 0/5012 是关键词式），关键词匹配命中率仅约 66%，会导致追问链大量断裂；
   现改为——完全答不出走降级引导，否则进入 L1 追问，命中率 100%；
3. 收尾题池由「`interview_stage=收尾交流`」改为**按题型 `行为素质题`**：
   V5 只有 3 个阶段（无「收尾交流」），沿用旧写法会池空 → 降级 Mock。
"""
import logging
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.config import settings
from app.models import Question

logger = logging.getLogger(__name__)

# ---------------- 阶段 / 题型常量 ----------------
# 与 app/models/question.QUESTION_STAGES 保持一致（tests/test_question_bank.py 有断言守护）。
# 刻意按名定义而非 `A, B, C = QUESTION_STAGES` 顺序解包：词表一旦增删值，
# 顺序解包会静默错位（旧算法踩过的坑），按名引用则报错可见。
STAGE_OPENING = "开场热身"
STAGE_CORE = "核心考察"
STAGE_DEEP = "深度压轴"
# 收尾题池：V5 无「收尾交流」阶段，改用题型。行为素质题题干形如
# 「请分享一次你…的经历」，与 V4 那 45 道收尾题（100% 行为面试类）语义一致。
CLOSING_CATEGORY = "行为素质题"
EASY = "easy"

# 笼统判定的精确短语表。刻意不用裸「不会」——技术回答最常见的「不会产生脏读/
# 不会导致数据不一致」等确定性否定句会被误伤；只收录明确的露怯表达。
_VAGUE_PHRASES = (
    "不知道", "不清楚", "不太懂", "不了解", "没接触过", "忘记了",
    "不会做", "不会答", "不太会", "没学过", "没做过", "没写过",
)

# V5 追问字段的标记前缀（格式恒定：`[触发] 条件` / `[追问] 文本`）
_ASK_MARK = "[追问]"


def is_vague_answer(text: str) -> bool:
    """判断候选人回答是否笼统（触发降级引导）

    注意：不用「简单/基本/大概」——「简单工厂模式」「基本类型」会被误伤；
    也不用裸「不会」——「不会产生脏读」是确定性否定而非露怯。
    本函数是项目内「回答简略程度」的唯一口径（本题库策略与 Mock 追问共用）。
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


def extract_follow_up_text(field: str) -> str:
    """从 V5 追问字段中取追问正文

    V5 格式恒定：L1/L2 为 2 行（`[触发] 条件` + `[追问] 文本`），
    L3 有 31.1% 的题为 3 行（首行是「本题为 easy 难度，一般不触达 L3…」元信息，
    真正触发条件在次行）。取**最后一个** `[追问]` 行可同时覆盖两种情况，
    元信息行天然被跳过。
    """
    lines = [ln.strip() for ln in (field or "").splitlines()
             if ln.strip().startswith(_ASK_MARK)]
    return lines[-1][len(_ASK_MARK):].strip() if lines else ""


# ---------------- 题库查询与选题 ----------------

async def questions_of_position(db: AsyncSession, position: str) -> list[Question]:
    """该岗位全部题目（V5 每岗 655~2146 题，单轮内一次加载后内存过滤）

    只投影决策用到的 8 列：得分点 / 校准锚点 / 关联知识点等长文本列
    （每行 1~3KB）与出题策略无关，全列加载每轮会浪费数 MB。

    公开（无下划线）：`scripts/simulate_interview.py` 复用同一投影口径，
    避免仿真与真实出题路径加载的列集不一致而削弱结论。
    """
    result = await db.execute(
        select(Question)
        .options(load_only(
            Question.question, Question.interview_stage, Question.difficulty,
            Question.category, Question.follow_up_l1, Question.follow_up_l2,
            Question.follow_up_l3, Question.fallback_strategy,
        ))
        .where(Question.position_code == position)
    )
    return list(result.scalars())


async def pick_next(
    db: AsyncSession, position: str, round_no: int, history: list[dict], is_follow_up: bool
) -> str | None:
    """策略唯一入口：加载该岗位题目后交给纯函数决策；无题/未命中返回 None（调用方降级）"""
    questions = await questions_of_position(db, position)
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
    """按阶段顺序随机抽一题（开场/换新题用），前一个阶段无题自动降级下一个

    注：按**题型**选收尾题走独立的 `pick_closing_question`（V5 无「收尾交流」阶段，
    题型与阶段是两个维度，硬塞进同一个签只会让调用方以为收尾也走阶段池）。
    """
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


def pick_closing_question(questions: list[Question], asked: set[str]) -> Question | None:
    """收尾题：按题型「行为素质题」随机抽一题

    V5 的三个阶段（开场热身/核心考察/深度压轴）里没有「收尾交流」，
    若沿用旧版按阶段选取会池空 → 返回 None → 面试降级到 Mock 通用模板。
    行为素质题每岗 65~214 道，题型定位与收尾交流一致，故改按题型选取。
    """
    pool = [
        q for q in questions
        if q.category == CLOSING_CATEGORY and q.question not in asked
    ]
    return random.choice(pool) if pool else None


def find_anchor_question(
    questions: list[Question], history: list[dict]
) -> tuple[Question | None, list[str]]:
    """从 history 尾部向前找最近一条题库题干作「锚点」

    返回 (锚点题, 锚点之后的追问文本列表)——追问次数 = len(列表)，单一事实源
    永不脱钩。只做精确匹配（索引 O(1)、strip 归一集中一处）：history 中的
    interviewer 消息要么是从题库抽出的原文（精确可中），要么是追问文本
    /Mock/LLM 产物（不在题库），计入追问文本。刻意不用包含匹配——追问文本
    常内嵌引用题干（如「在「String、StringBuilder、StringBuffer有什么区别？」
    的实际使用过程中…」），包含匹配会把追问误判成新锚点，追问链断链。
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

    - 最后两轮强制收尾交流（否则追问链会延伸到最后一轮，收尾永不出现）
    - 开场题不做锚点追问：阶段推进为 开场 → 核心考察 → 深度压轴，
      开场题深挖会挤掉核心考察阶段
    - **L1 分流（V5 适配点）**：V5 的 L1 触发条件（如「回答缺乏细节时触发」）
      是描述式而非关键词式，无法做子串匹配。改为统一口径——回答完全笼统/露怯
      时发降级引导话术，否则发 L1 追问。这使追问链的触达率从约 66% 提升到 100%。
    - 回答笼统在任一层级都落降级策略（候选人说不知道时不该继续递进追问）
    """
    if _in_closing_window(round_no):
        return _pick_new_question_text(questions, round_no, asked)

    anchor, trailing_texts = find_anchor_question(questions, history)
    if anchor is None or anchor.interview_stage == STAGE_OPENING:
        return _pick_new_question_text(questions, round_no, asked)

    answer = last_candidate_answer(history)
    # 追问去重范围 = 本锚点链内（trailing）：跨题共享的降级话术不应互相排挤
    asked_follow_ups = set(trailing_texts)
    follow_count = len(trailing_texts)

    candidates: list[str] = []
    if follow_count == 0:
        if is_vague_answer(answer):
            candidates = [anchor.fallback_strategy]                 # 答不出 → 降级引导
        else:
            candidates = [extract_follow_up_text(anchor.follow_up_l1)]
    elif follow_count in (1, 2):
        if is_vague_answer(answer):
            candidates = [anchor.fallback_strategy]
        else:
            field = anchor.follow_up_l2 if follow_count == 1 else anchor.follow_up_l3
            candidates = [extract_follow_up_text(field)]
    # follow_count >= 3 → candidates 空 → 换新题

    hit = next((t for t in candidates if t and t not in asked_follow_ups), None)
    if hit:
        return hit
    # 换新题：本轮回答笼统（连续露怯）时不优先 hard 深度题
    return _pick_new_question_text(questions, round_no, asked, avoid_hard=is_vague_answer(answer))


def _pick_new_question_text(
    questions: list[Question], round_no: int, asked: set[str], avoid_hard: bool = False
) -> str | None:
    """换新题：最后两轮收尾交流；round>=3 深度压轴（无则核心考察）；否则核心考察"""
    if _in_closing_window(round_no):
        row = pick_closing_question(questions, asked)
        if row is not None:
            return row.question
    # 换新题的阶段推进：前段核心考察、后半段（round>=3，经验值）深度优先；
    # 连续露怯的回答（avoid_hard）跳过深度压轴，避免把最难题发给最弱候选人
    stages = (STAGE_DEEP, STAGE_CORE) if round_no >= 3 and not avoid_hard else (STAGE_CORE,)
    row = pick_stage(questions, stages, asked)
    return row.question if row is not None else None
