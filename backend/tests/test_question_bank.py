"""题库策略测试（V5 结构化数据源版，`backend/interviewer_new/`）

分层：
- TestPositionConstants：阶段/题型常量与模型词表一致性（防两处漂移）
- TestIsVagueAnswer：笼统判定纯函数（V4 时代的口径，V5 继续沿用）
- TestExtractFollowUpText：V5 追问字段解析（含 L3 元信息行的坑）
- TestPickNextMatrix：决策矩阵单测（pick_next_from_questions 纯函数，不碰 DB）
- TestQuestionBankFlow：adapter 全链集成（DB 造数）+ 空库兜底

与旧版测试的差异（V5 换代）：
- 删除 15 个 `parse_follow_up_triggers` 格式解析用例——V5 把追问拆成了独立字段，
  119 行文本解析层整体废弃，改为 4 个 `extract_follow_up_text` 用例；
- L1 用例由「关键词命中/未命中」改为「答得好→追问 / 答不出→降级」语义分流；
- 收尾用例由「收尾交流阶段」改为「行为素质题题型」。
"""
import pytest_asyncio
from sqlalchemy import delete

from app.adapters import get_interviewer_adapter
from app.database import async_session, init_db
from app.models import Question
from app.models.question import QUESTION_CATEGORIES, QUESTION_DIFFICULTIES, QUESTION_STAGES
from interviewer_new.question_bank import (
    CLOSING_CATEGORY,
    STAGE_CORE,
    STAGE_DEEP,
    STAGE_OPENING,
    extract_follow_up_text,
    find_anchor_question,
    is_vague_answer,
    last_candidate_answer,
    pick_closing_question,
    pick_next_from_questions,
    pick_stage,
)
from tests.helpers import make_follow_up_field, make_question

# 集成测试用专属岗位，与 test_api.py 造数隔离，避免随机抽取断言 flaky
FLOW_POSITION = "bankflow"

# V5 追问文本样本（真实数据形态：L1/L2 为「[触发] 条件 + [追问] 文本」两行）
L1_TEXT = "你说的深拷贝，具体包含哪几个核心组成部分？"
L2_TEXT = "深拷贝的时间复杂度和空间复杂度分别是多少？为什么？"
L3_TEXT = "如果要在生产环境实现深拷贝，你会怎么选型？"
FALLBACK_TEXT = "先给个提示：深拷贝的核心是围绕对象图展开的，你能从这个角度想想吗？"

# 一段「答得不错」的回答：长度 > 20 且不含露怯短语 → 不判笼统
GOOD_ANSWER = (
    "HashMap 底层是数组加链表，插入时先按 hashCode 计算桶位置，链表长度超过阈值会树化，"
    "负载因子默认 0.75，扩容时容量翻倍并重新分配元素。"
)
SHORT_ANSWER = "不清楚，没写过。"


def _flow_questions() -> dict[str, Question]:
    """流程造数：开场 / 核心（带三级追问）/ 深度 / 收尾×2（行为素质题）

    收尾题刻意标 `category="行为素质题"`：V5 数据没有「收尾交流」阶段，
    收尾题池改按题型选取（这是本次换代最重要的行为变化）。
    """
    return {
        "opening": make_question(
            position_code=FLOW_POSITION, question_no="flow_001",
            question="请做一个简短的自我介绍，说说你的技术栈。",
        ),
        "core": make_question(
            position_code=FLOW_POSITION, question_no="flow_002",
            question="Java中HashMap的底层实现原理是什么？",
            difficulty="medium", interview_stage=STAGE_CORE, stage_order=2,
            follow_up_l1=make_follow_up_field("答出基础得分点时触发", L1_TEXT),
            follow_up_l2=make_follow_up_field("进阶概念答出时触发", L2_TEXT),
            follow_up_l3=make_follow_up_field("考生展示工程经验时触发", L3_TEXT),
            fallback_strategy=FALLBACK_TEXT,
        ),
        "deep": make_question(
            position_code=FLOW_POSITION, question_no="flow_003",
            question="如何设计一个高并发缓存系统？",
            difficulty="hard", interview_stage=STAGE_DEEP, stage_order=3,
        ),
        "closing": make_question(
            position_code=FLOW_POSITION, question_no="flow_004",
            question="讲一次你在团队中主动分享技术经验的经历。",
            category=CLOSING_CATEGORY, interview_stage=STAGE_CORE, stage_order=2,
        ),
        # 真实题库每岗 65~214 道收尾题，最后两轮各抽一道不会同题；fixture 备 2 道还原该形态
        "closing2": make_question(
            position_code=FLOW_POSITION, question_no="flow_005",
            question="未来一年你在技术上最想突破的方向是什么？",
            category=CLOSING_CATEGORY, interview_stage=STAGE_CORE, stage_order=2,
        ),
    }


class TestPositionConstants:
    """阶段/题型常量与模型词表一致（两处漂移会在运行时静默选不到题）"""

    def test_stages_match_model_vocabulary(self):
        assert (STAGE_OPENING, STAGE_CORE, STAGE_DEEP) == QUESTION_STAGES

    def test_closing_category_in_vocabulary(self):
        assert CLOSING_CATEGORY in QUESTION_CATEGORIES

    def test_difficulties_unchanged(self):
        assert QUESTION_DIFFICULTIES == ("easy", "medium", "hard")


class TestIsVagueAnswer:
    def test_short_answer_vague(self):
        assert is_vague_answer("")
        assert is_vague_answer(None)
        assert is_vague_answer("会一点")
        assert is_vague_answer("我不清楚")

    def test_no_false_positive(self):
        """「简单/基本/大概」是正常技术词，不应误伤（旧版踩过的坑）"""
        assert not is_vague_answer("简单工厂模式把对象的创建封装在工厂类中，客户端不直接 new 对象。")
        assert not is_vague_answer(
            "基本类型有八种：byte、short、int、long、float、double、char、boolean，各自占用的字节数不同。"
        )
        assert not is_vague_answer(
            "大概的思路是先做限流保护下游，再通过缓存和异步削峰来扛住流量，最后兜底降级。"
        )

    def test_negative_phrases_hit(self):
        """明确的露怯短语应命中笼统"""
        assert is_vague_answer("这道题我不会做，上课没有讲过这个方向。")
        assert is_vague_answer("没接触过消息队列，说不上来具体的用法。")
        assert is_vague_answer("这部分没学过，不太清楚细节。")

    def test_buhui_negation_not_vague(self):
        """确定性否定句「不会产生/导致/造成」不应误判为露怯（旧版审查实证的误伤）"""
        assert not is_vague_answer("这里不会产生脏读，因为我们加了行级锁并固定了加锁顺序。")
        assert not is_vague_answer("这个方案不会导致数据不一致，因为更新走了事务保证原子性。")
        assert not is_vague_answer("不会造成死锁，两把锁的获取顺序在代码里是固定的。")
        assert not is_vague_answer("即使流量翻十倍也不会影响正确性，幂等键去重是稳定的。")


class TestExtractFollowUpText:
    """V5 追问字段解析：格式恒定，但 L3 有 31.1% 的题带元信息首行"""

    def test_standard_two_lines(self):
        assert extract_follow_up_text(make_follow_up_field("答出基础得分点时触发", L1_TEXT)) == L1_TEXT

    def test_l3_with_meta_first_line(self):
        """L3 首行是「本题为 easy 难度，一般不触达 L3」元信息 → 取最后一个 [追问] 行"""
        field = (
            "[触发] 本题为easy难度，一般不触达L3；若考生表现优异可酌情触发以下追问。\n"
            "[触发] 考生展示工程经验时触发\n"
            f"[追问] {L3_TEXT}"
        )
        assert extract_follow_up_text(field) == L3_TEXT

    def test_empty_field(self):
        assert extract_follow_up_text("") == ""
        assert extract_follow_up_text(None) == ""

    def test_field_without_ask_mark(self):
        """只有触发条件、没有 [追问] 行 → 空串（调用方会落到换新题）"""
        assert extract_follow_up_text("[触发] 答出得分点时触发") == ""


class TestPickNextMatrix:
    """决策矩阵：pick_next_from_questions 纯函数单测（不碰 DB）"""

    def _rows(self) -> dict[str, Question]:
        return _flow_questions()

    def _pick(self, rows, round_no: int, history: list[dict], is_follow_up: bool) -> str | None:
        return pick_next_from_questions(list(rows.values()), round_no, history, is_follow_up)

    def _qa(self, question: str, answer: str = "") -> list[dict]:
        return [
            {"role": "interviewer", "content": question},
            {"role": "candidate", "content": answer},
        ]

    # ---------------- 开场题 ----------------

    def test_opening_picks_easy_warmup(self):
        rows = self._rows()
        assert self._pick(rows, 1, [], False) == rows["opening"].question

    def test_opening_empty_pool_returns_none(self):
        """无开场题 → None（调用方降级到下一数据源）"""
        rows = self._rows()
        del rows["opening"]
        assert self._pick(rows, 1, [], False) is None

    def test_empty_questions_returns_none(self):
        assert pick_next_from_questions([], 1, [], False) is None
        assert pick_next_from_questions([], 2, self._qa("x"), True) is None

    def test_opening_question_not_anchored(self):
        """开场题不做锚点追问 → 换新题（否则会挤掉核心考察阶段）

        注：换新题按「核心考察」阶段选，而真实数据里行为素质题也标该阶段，
        故断言「不是开场题自己的追问，且是题库内某道新题」而非指定某一道。
        """
        rows = self._rows()
        history = self._qa(rows["opening"].question, GOOD_ANSWER)
        q = self._pick(rows, 2, history, True)
        assert q in {r.question for r in rows.values()}
        assert q != L1_TEXT  # 不是 core 题（被锚定的那类）的追问

    # ---------------- L1（V5 语义分流）----------------

    def test_l1_good_answer_triggers_l1(self):
        """考生答得好 → 发 L1 追问（V5 触发条件是描述式，无法关键词匹配，改为语义分流）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        assert self._pick(rows, 2, history, True) == L1_TEXT

    def test_l1_vague_answer_uses_fallback(self):
        """考生答不出 → 发降级引导话术（而非继续追问）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, SHORT_ANSWER)
        assert self._pick(rows, 2, history, True) == FALLBACK_TEXT

    # ---------------- L2 / L3 ----------------

    def test_l2_l3_progression(self):
        rows = self._rows()
        # 锚点后 1 次追问 → L2
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        history += [{"role": "interviewer", "content": L1_TEXT},
                    {"role": "candidate", "content": GOOD_ANSWER}]
        assert self._pick(rows, 3, history, True) == L2_TEXT
        # 锚点后 2 次追问 → L3
        history += [{"role": "interviewer", "content": L2_TEXT},
                    {"role": "candidate", "content": GOOD_ANSWER}]
        assert self._pick(rows, 4, history, True) == L3_TEXT

    def test_l2_l3_vague_answer_uses_fallback(self):
        """L2/L3 层回答笼统 → 落降级策略而非继续递进（候选人说不知道时不该再深挖）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        history += [{"role": "interviewer", "content": L1_TEXT},
                    {"role": "candidate", "content": SHORT_ANSWER}]
        assert self._pick(rows, 3, history, True) == FALLBACK_TEXT

    def test_follow_up_exhausted_picks_new_question(self):
        """三层追问尽（n>=3）→ 换新题"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        for text in (L1_TEXT, L2_TEXT, L3_TEXT):
            history += [{"role": "interviewer", "content": text},
                        {"role": "candidate", "content": GOOD_ANSWER}]
        q = self._pick(rows, 5, history, True)
        assert q in (rows["deep"].question, rows["core"].question)

    def test_follow_up_dedup_within_anchor_chain(self):
        """同一锚点链内已问过的追问文本不重复发（去重范围=本链）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        history += [{"role": "interviewer", "content": L1_TEXT},
                    {"role": "candidate", "content": GOOD_ANSWER}]
        # L1 已问过 → 应推进到 L2，而不是重发 L1
        assert self._pick(rows, 3, history, True) != L1_TEXT

    # ---------------- 收尾（V5 改按题型）----------------

    def test_closing_window_picks_behavior_question(self):
        """round>=MAX_FOLLOW_UP_ROUNDS 强制收尾：按「行为素质题」选（V5 无收尾交流阶段）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        q = self._pick(rows, 6, history, True)
        assert q in (rows["closing"].question, rows["closing2"].question)

    def test_closing_falls_back_when_no_behavior_question(self):
        """无行为素质题时收尾窗口落回核心考察（而非返回 None 降级 Mock）"""
        rows = self._rows()
        del rows["closing"], rows["closing2"]
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        q = self._pick(rows, 6, history, True)
        assert q is not None

    def test_closing_alternates_two_questions(self):
        """两道收尾题在最后两轮各用一次（真实题库形态）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        first = self._pick(rows, 6, history, True)
        history += [{"role": "interviewer", "content": first},
                    {"role": "candidate", "content": GOOD_ANSWER}]
        second = self._pick(rows, 7, history, True)
        assert second != first

    # ---------------- 阶段推进与难度控制 ----------------

    def test_new_question_stage_progression(self):
        """换新题：round<3 只在「核心考察」阶段选"""
        rows = self._rows()
        del rows["opening"]
        q = self._pick(rows, 2, self._qa("不在题库里的题", GOOD_ANSWER), True)
        core_stage = {r.question for r in rows.values() if r.interview_stage == STAGE_CORE}
        assert q in core_stage

    def test_avoid_hard_skips_deep_stage(self):
        """追问链末尾且连续露怯 → 换新题时跳过深度压轴

        （avoid_hard 只在「锚点链走完/用尽」的换新题分支生效；无锚点直接换新题
        时按阶段推进，不传该标记——这是旧算法沿用下来的设计。）
        """
        rows = self._rows()
        history = self._qa(rows["core"].question, GOOD_ANSWER)
        for text in (L1_TEXT, L2_TEXT, L3_TEXT):
            history += [{"role": "interviewer", "content": text},
                        {"role": "candidate", "content": GOOD_ANSWER}]
        history[-1]["content"] = SHORT_ANSWER  # 末次回答露怯 → n>=3 且 avoid_hard
        q = self._pick(rows, 4, history, True)
        assert q != rows["deep"].question


class TestAnchorAndHelpers:
    """锚点定位与辅助函数"""

    def test_anchor_exact_match_only(self):
        """锚点只做精确匹配：追问文本内嵌题干引用时不误判为新锚点"""
        rows = _flow_questions()
        core_q = rows["core"].question
        history = [
            {"role": "interviewer", "content": core_q},
            {"role": "candidate", "content": GOOD_ANSWER},
            {"role": "interviewer", "content": f"在「{core_q}」的实际场景中你会怎么做？"},
            {"role": "candidate", "content": GOOD_ANSWER},
        ]
        anchor, trailing = find_anchor_question(list(rows.values()), history)
        assert anchor is not None and anchor.question == core_q
        assert len(trailing) == 1  # 那条内嵌引用的追问计为 trailing，不是新锚点

    def test_anchor_not_found(self):
        rows = _flow_questions()
        anchor, trailing = find_anchor_question(list(rows.values()), [{"role": "interviewer", "content": "无题"}])
        assert anchor is None and trailing == []

    def test_last_candidate_answer(self):
        history = [{"role": "candidate", "content": "第一个"},
                   {"role": "interviewer", "content": "追问"},
                   {"role": "candidate", "content": "最后一个回答"}]
        assert last_candidate_answer(history) == "最后一个回答"
        assert last_candidate_answer([]) == ""

    def test_pick_stage_respects_stage_and_asked(self):
        """pick_stage 按阶段过滤 + 排除已问题目"""
        rows = _flow_questions()
        core_qs = {r.question for r in rows.values() if r.interview_stage == STAGE_CORE}
        row = pick_stage(list(rows.values()), (STAGE_CORE,), set())
        assert row is not None and row.question in core_qs
        # 全部标为已问 → 返回 None（调用方据此降级）
        assert pick_stage(list(rows.values()), (STAGE_CORE,), core_qs) is None

    def test_pick_closing_question_picks_behavior_category(self):
        """收尾题按题型选（V5 无「收尾交流」阶段）"""
        rows = _flow_questions()
        row = pick_closing_question(list(rows.values()), set())
        assert row is not None and row.category == CLOSING_CATEGORY

    def test_pick_closing_question_none_when_no_pool(self):
        rows = _flow_questions()
        del rows["closing"], rows["closing2"]
        assert pick_closing_question(list(rows.values()), set()) is None


# ---------------- adapter 全链集成（DB 造数）----------------


@pytest_asyncio.fixture
async def _flow_db():
    """把 _flow_questions() 落库，用例结束后清理（test_api 的空库计数断言依赖干净库）"""
    await init_db()
    async with async_session() as session:
        for q in _flow_questions().values():
            session.add(q)
        await session.commit()
    yield
    async with async_session() as session:
        await session.execute(delete(Question).where(Question.position_code == FLOW_POSITION))
        await session.commit()


class TestQuestionBankFlow:
    """adapter 全链：真实 DB 造数 → generate_question 走题库策略（不落 Mock）"""

    @pytest_asyncio.fixture(autouse=True)
    async def _setup(self, _flow_db):
        self.adapter = get_interviewer_adapter()

    async def test_opening_from_bank(self):
        q = await self.adapter.generate_question(
            position=FLOW_POSITION, round_no=1, history=[], interview_id=1, is_follow_up=False)
        assert q == "请做一个简短的自我介绍，说说你的技术栈。"

    async def test_full_chain_follow_up(self):
        """答得好 → L1 追问（证明走的是题库策略而非 Mock 模板）"""
        history = [
            {"role": "interviewer", "content": "Java中HashMap的底层实现原理是什么？"},
            {"role": "candidate", "content": GOOD_ANSWER},
        ]
        q = await self.adapter.generate_question(
            position=FLOW_POSITION, round_no=2, history=history, interview_id=1, is_follow_up=True)
        assert q == L1_TEXT

    async def test_full_chain_vague_uses_fallback(self):
        """答不出 → 降级引导话术"""
        history = [
            {"role": "interviewer", "content": "Java中HashMap的底层实现原理是什么？"},
            {"role": "candidate", "content": SHORT_ANSWER},
        ]
        q = await self.adapter.generate_question(
            position=FLOW_POSITION, round_no=2, history=history, interview_id=1, is_follow_up=True)
        assert q == FALLBACK_TEXT

    async def test_closing_round_uses_behavior_question(self):
        """收尾窗口走行为素质题（V5 适配的核心行为）"""
        history = [
            {"role": "interviewer", "content": "Java中HashMap的底层实现原理是什么？"},
            {"role": "candidate", "content": GOOD_ANSWER},
        ]
        q = await self.adapter.generate_question(
            position=FLOW_POSITION, round_no=6, history=history, interview_id=1, is_follow_up=True)
        assert q in ("讲一次你在团队中主动分享技术经验的经历。",
                     "未来一年你在技术上最想突破的方向是什么？")

    async def test_empty_bank_falls_back_to_mock(self):
        """空库岗位 → 题库策略未命中 → 降级 Mock（流程不中断）"""
        q = await self.adapter.generate_question(
            position="no_such_position", round_no=1, history=[], interview_id=1, is_follow_up=False)
        assert q and isinstance(q, str)
