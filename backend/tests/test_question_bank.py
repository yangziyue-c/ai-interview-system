"""题库策略测试（P2 算法落地：四层追问解析 + 锚点层级推断 + 选题兜底）

分层：
- TestParseFollowUpTriggers / TestIsVagueAnswer：纯函数单测（真实题库格式 + 措辞变体）
- TestPickNextMatrix：决策矩阵单测（pick_next_from_questions 纯函数，不碰 DB）
- TestQuestionBankFlow：adapter 全链集成（DB 造数）+ 空库兜底

真实数据形态（开发库 451 行实测）与早期 fixture 的关键差异，测试均已覆盖：
- 每道题都带非空追问计划 → 收尾窗口必须强制，否则收尾题永不出现
- 段头与内容挤同行 / 无引号关键词 / 条件式行 / 单行多子句 / 「深度追问：」前缀
"""
import pytest_asyncio
from sqlalchemy import delete

from app.adapters import get_interviewer_adapter
from app.database import async_session, init_db
from app.models import Question
from interviewer.question_bank import (
    find_anchor_question,
    is_vague_answer,
    last_candidate_answer,
    parse_follow_up_triggers,
    pick_next_from_questions,
    pick_stage,
)
from tests.helpers import make_question

# 集成测试用专属岗位，与 test_api.py 造数隔离，避免随机抽取断言 flaky
FLOW_POSITION = "bankflow"

# 真实题库 v13 格式样本（含抽查发现的措辞变体）：
# L1 兜底行有「笼统/很浅显/只答理论缺乏实践」多种措辞；L2 行箭头后带「追问：」；
# L3 行箭头后带「极限场景：」——解析时均应剥离引导词
SAMPLE_TRIGGERS = """【L1-触发追问】根据候选人回答中的关键词触发
① 若提到"hashCode" → 追问：HashMap中key的hash计算过程
② 若提到"String" → 追问：String为什么设计为不可变
③ 若回答笼统/缺乏细节 → 追问：能否结合你实际项目中的经验，举一个具体的使用场景？
④ 若回答很浅显 → 追问：针对这个问题，你能说说缺少访问边界时怎么办吗？
⑤ 若只答理论缺乏实践 → 追问：在你踩过的坑里，这个问题是如何暴露的？

【L2-递进追问】在L1基础上进一步深入，考察实践深度
① 承接L1-①深入 → 追问：在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？
② 承接L1-②深入 → 追问：如果让你重新设计这个机制，你会做哪些改进？

【L3-极限追问】仅当候选人L1和L2回答流畅准确时使用，考察知识融会贯通
→ 极限场景：假设你需要设计一个高并发的缓存系统，请从三个维度阐述。

【降级策略】当候选人回答困难或明显不熟悉时使用
→ 那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？
"""


def _flow_questions() -> dict[str, Question]:
    """流程造数：开场 / 核心（带四层触发条件）/ 深度 / 收尾×2（纯对象构造，DB 版见 _seed）"""
    return {
        "opening": make_question(
            position_code=FLOW_POSITION, question_no="flow_001",
            question="请做一个简短的自我介绍，说说你的技术栈。",
        ),
        "core": make_question(
            position_code=FLOW_POSITION, question_no="flow_002",
            question="Java中HashMap的底层实现原理是什么？",
            difficulty="medium", interview_stage="核心考察", stage_order=2,
            follow_up_triggers=SAMPLE_TRIGGERS,
        ),
        "deep": make_question(
            position_code=FLOW_POSITION, question_no="flow_003",
            question="如何设计一个高并发缓存系统？",
            difficulty="hard", interview_stage="深度考察", stage_order=3,
        ),
        "closing": make_question(
            position_code=FLOW_POSITION, question_no="flow_004",
            question="你对本次面试还有什么想问我的吗？",
            difficulty="easy", interview_stage="收尾交流", stage_order=4,
        ),
        # 真实题库每岗 15 道收尾题，最后两轮各抽一道不会同题；fixture 备 2 道还原该形态
        "closing2": make_question(
            position_code=FLOW_POSITION, question_no="flow_005",
            question="未来一年你在技术上最想突破的方向是什么？",
            difficulty="easy", interview_stage="收尾交流", stage_order=4,
        ),
    }


class TestParseFollowUpTriggers:
    """四段解析：真实格式 + 措辞变体"""

    def _parse(self) -> object:
        return parse_follow_up_triggers(SAMPLE_TRIGGERS)

    def test_l1_keywords(self):
        plan = self._parse()
        assert plan.l1 == [
            ("hashCode", "HashMap中key的hash计算过程"),
            ("String", "String为什么设计为不可变"),
        ]

    def test_l1_vague_variants(self):
        """L1 兜底行措辞多变（笼统/很浅显/只答理论缺乏实践），均应解析到"""
        plan = self._parse()
        assert plan.l1_vague == [
            "能否结合你实际项目中的经验，举一个具体的使用场景？",
            "针对这个问题，你能说说缺少访问边界时怎么办吗？",
            "在你踩过的坑里，这个问题是如何暴露的？",
        ]

    def test_l2_strips_prefix(self):
        """L2 行箭头后的「追问：」引导词应剥离，追问文本不脏"""
        plan = self._parse()
        assert plan.l2 == [
            "在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？",
            "如果让你重新设计这个机制，你会做哪些改进？",
        ]

    def test_l3_strips_prefix(self):
        """L3 行箭头后的「极限场景：」引导词应剥离"""
        plan = self._parse()
        assert plan.l3 == ["假设你需要设计一个高并发的缓存系统，请从三个维度阐述。"]

    def test_fallback(self):
        plan = self._parse()
        assert plan.fallback == [
            "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"
        ]

    def test_empty_and_non_str(self):
        for bad in ("", None, 123):
            plan = parse_follow_up_triggers(bad)
            assert not plan.l1 and not plan.l1_vague and not plan.l2 and not plan.l3 and not plan.fallback

    def test_halfwidth_arrow(self):
        """半角箭头 -> 的兼容"""
        plan = parse_follow_up_triggers(
            "【L1-触发追问】\n① 若提到\"hash\" -> 追问：hash算法如何避免碰撞？"
        )
        assert plan.l1 == [("hash", "hash算法如何避免碰撞？")]

    def test_header_and_content_on_same_line(self):
        """段头与内容挤同一行（真实题库 scene_039~043 系统设计题格式）"""
        plan = parse_follow_up_triggers(
            '【L1-触发追问】①若提到"协议"→SNMP和TCP的协议报文结构差异；'
            '②若提到"消息队列"→消息堆积时如何排查消费瓶颈'
        )
        assert plan.l1 == [
            ("协议", "SNMP和TCP的协议报文结构差异"),
            ("消息队列", "消息堆积时如何排查消费瓶颈"),
        ]

    def test_unquoted_keyword_line(self):
        """无引号关键词行（真实题库「② 若提到类型兼容 → 追问…」，无冒号）
        「追问」后无冒号时保留本体——剥碎后（如「实战经验」）语义更差"""
        plan = parse_follow_up_triggers(
            "【L1-触发追问】\n② 若提到类型兼容 → 追问结构化类型与名义类型的区别"
        )
        assert plan.l1 == [("类型兼容", "追问结构化类型与名义类型的区别")]

    def test_conditional_line(self):
        """条件式行（「① 若未处理空数组 → 追问…」）→ 条件文本即触发关键词"""
        plan = parse_follow_up_triggers(
            "【L1-触发追问】\n① 若未处理空数组 → 追问：空数组时为什么会抛异常？"
        )
        assert plan.l1 == [("未处理空数组", "空数组时为什么会抛异常？")]

    def test_multi_clause_single_line(self):
        """单行多子句（「若A→追问X；若B→追问Y」）→ 按「；若」切分逐子句解析，不残留模板条件；
        正向条件（若回答有深度）归 L2 头部——答得好的深挖素材，不落入笼统兜底"""
        plan = parse_follow_up_triggers(
            "【L1-触发追问】\n"
            "① 按回答深度分层追问：若回答有深度 → 追问「请阐述等价类划分的组合使用」的实践细节；"
            "若回答笼统 → 追问具体案例；若只答理论 → 追问实战经验"
        )
        assert plan.l2[0] == "追问「请阐述等价类划分的组合使用」的实践细节"
        assert plan.l1_vague == ["追问具体案例", "追问实战经验"]

    def test_content_line_with_marker_word_not_misrouted(self):
        """内容行内嵌「降级策略」字样不应被误切成段头（真实题库 scene_043 L3 行）"""
        plan = parse_follow_up_triggers(
            "【L3-极限追问】\n"
            "→ 极限场景：结合消息合并与降级策略，设计专项测试方案？"
        )
        assert plan.l3 == ["结合消息合并与降级策略，设计专项测试方案？"]

    def test_l3_deep_prefix_stripped(self):
        """L3 行「→ 深度追问：」前缀（真实题库 100 条）应剥离"""
        plan = parse_follow_up_triggers(
            "【L3-极限追问】\n→ 深度追问：在你刚才描述的经历中，如果时间倒流你会改变哪三处关键决策？"
        )
        assert plan.l3 == ["在你刚才描述的经历中，如果时间倒流你会改变哪三处关键决策？"]

    def test_fallback_prefix_stripped(self):
        """fallback 段「追问：」前缀（真实题库 45 条）应剥离"""
        plan = parse_follow_up_triggers(
            "【降级策略】\n→ 追问：能否举一个你实际遇到的例子来说明？"
        )
        assert plan.fallback == ["能否举一个你实际遇到的例子来说明？"]

    def test_fallback_header_variants(self):
        """降级策略段头带【】括号的写法"""
        plan = parse_follow_up_triggers(
            "【降级策略】当候选人回答困难时使用\n→ 我们先从更基础的角度看——能说说基本定义吗？"
        )
        assert plan.fallback == ["我们先从更基础的角度看——能说说基本定义吗？"]


class TestIsVagueAnswer:
    def test_short_answer_vague(self):
        assert is_vague_answer("")
        assert is_vague_answer(None)
        assert is_vague_answer("会一点")
        assert is_vague_answer("我不清楚")

    def test_no_false_positive(self):
        """「简单/基本/大概」是正常技术词，不应误伤（P2 初版踩过的坑）"""
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
        """确定性否定句「不会产生/导致/造成」不应误判为露怯（审查实证的误伤）"""
        assert not is_vague_answer("这里不会产生脏读，因为我们加了行级锁并固定了加锁顺序。")
        assert not is_vague_answer("这个方案不会导致数据不一致，因为更新走了事务保证原子性。")
        assert not is_vague_answer("不会造成死锁，两把锁的获取顺序在代码里是固定的。")
        assert not is_vague_answer("即使流量翻十倍也不会影响正确性，幂等键去重是稳定的。")


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

    def test_opening_picks_easy_warmup(self):
        rows = self._rows()
        q = self._pick(rows, 1, [], False)
        assert q == rows["opening"].question

    def test_opening_empty_pool_returns_none(self):
        """无开场题 → None（调用方降级）"""
        rows = self._rows()
        del rows["opening"]
        assert self._pick(rows, 1, [], False) is None

    def test_empty_questions_returns_none(self):
        assert pick_next_from_questions([], 1, [], False) is None
        assert pick_next_from_questions([], 2, self._qa("x"), True) is None

    def test_l1_keyword_hit(self):
        rows = self._rows()
        history = self._qa(
            rows["core"].question,
            "HashMap 底层是数组加链表，插入时会先调用 hashCode 计算 key 的存储位置。",
        )
        q = self._pick(rows, 2, history, True)
        assert q == "HashMap中key的hash计算过程"

    def test_l1_keyword_first_match_only(self):
        """同时命中两个关键词 → 只取第一个命中的关键词追问"""
        rows = self._rows()
        history = self._qa(
            rows["core"].question,
            "hashCode 和 String 在 HashMap 中的应用我都很熟悉，底层结构是数组加链表。",
        )
        q = self._pick(rows, 2, history, True)
        assert q == "HashMap中key的hash计算过程"

    def test_l1_vague_uses_vague_then_fallback(self):
        rows = self._rows()
        history = self._qa(rows["core"].question, "我不清楚")
        q = self._pick(rows, 2, history, True)
        assert q == "能否结合你实际项目中的经验，举一个具体的使用场景？"

    def test_l1_no_hit_picks_new_question(self):
        """胜任但未命中关键词 → 换新题（降级策略只用于回答困难时，不发降级题）"""
        rows = self._rows()
        history = self._qa(
            rows["core"].question,
            "HashMap 的负载因子默认是 0.75，扩容时机和链表树化阈值我都有了解。",
        )
        q = self._pick(rows, 3, history, True)
        assert q == rows["deep"].question

    def test_l2_l3_progression(self):
        rows = self._rows()
        # 锚点后 1 次追问 → L2
        history = self._qa(rows["core"].question, "hash 计算过程是高位参与运算减少碰撞。")
        history += [{"role": "interviewer", "content": "HashMap中key的hash计算过程"},
                    {"role": "candidate", "content": "hash 计算过程是高位参与运算减少碰撞。"}]
        q = self._pick(rows, 3, history, True)
        assert q == "在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？"
        # 锚点后 2 次追问 → L3
        history += [{"role": "interviewer", "content": q},
                    {"role": "candidate", "content": "实际项目里我用 HashMap 做过本地缓存。"}]
        q = self._pick(rows, 4, history, True)
        assert q == "假设你需要设计一个高并发的缓存系统，请从三个维度阐述。"

    def test_l2_l3_vague_answer_uses_fallback(self):
        """L2/L3 层回答笼统 → 落降级策略而非继续递进（候选人说不知道时不该再深挖）"""
        rows = self._rows()
        history = self._qa(
            rows["core"].question,
            "HashMap 底层是数组加链表，插入时会先调用 hashCode 计算 key 的存储位置。",
        )
        history += [{"role": "interviewer", "content": "HashMap中key的hash计算过程"},
                    {"role": "candidate", "content": "不清楚，没实际写过。"}]
        q = self._pick(rows, 3, history, True)  # follow_count=1、回答笼统 → 降级策略
        assert q == "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"

    def test_follow_up_exhausted_picks_new_stage(self):
        """三层追问尽 → 换新题：round=5 深度考察、round=6 收尾交流"""
        rows = self._rows()
        history = self._qa(rows["core"].question, "hashCode 在 HashMap 里用来计算 key 的存储位置。")
        for text in (
            "HashMap中key的hash计算过程",
            "在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？",
            "假设你需要设计一个高并发的缓存系统，请从三个维度阐述。",
        ):
            history += [{"role": "interviewer", "content": text},
                        {"role": "candidate", "content": "我对这部分有比较深入的理解，也积累过实际的工程实践经验。"}]
        assert self._pick(rows, 5, history, True) == rows["deep"].question

        history += [{"role": "interviewer", "content": rows["deep"].question},
                    {"role": "candidate", "content": "高并发缓存我会从一致性和可用性两个维度设计。"}]
        q6 = self._pick(rows, 6, history, True)
        assert q6 in (rows["closing"].question, rows["closing2"].question)

    def test_closing_window_forced_even_with_active_anchor(self):
        """最后两轮强制收尾：即使锚点追问链仍活跃（真实题库 100% 非空计划），
        r6/r7 仍收尾交流——审查实证：不强制时 0/2700 场模拟到过收尾"""
        rows = self._rows()
        # 核心题带完整计划（真实形态）：r3 L1 → r4 L2 → r5 L3 链活跃，r6/r7 强制收尾
        history = self._qa(
            rows["core"].question,
            "HashMap 底层是数组加链表，插入时会先调用 hashCode 计算 key 的存储位置。",
        )
        for text in (
            "HashMap中key的hash计算过程",
            "在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？",
            "假设你需要设计一个高并发的缓存系统，请从三个维度阐述。",
        ):
            history += [{"role": "interviewer", "content": text},
                        {"role": "candidate", "content": "这个问题我理解得比较深入，也有实际项目经验支撑。"}]
        closing_set = {rows["closing"].question, rows["closing2"].question}
        q6 = self._pick(rows, 6, history, True)
        assert q6 in closing_set
        history += [{"role": "interviewer", "content": q6},
                    {"role": "candidate", "content": "谢谢，我了解了。"}]
        q7 = self._pick(rows, 7, history, True)
        assert q7 in closing_set and q7 != q6, "最后一轮仍应为收尾交流，且不与上一轮同题"

    def test_opening_anchor_not_followed(self):
        """开场题不做锚点追问：即使开场题带完整计划且回答命中关键词，
        r2 仍换新题进核心考察（阶段推进 开场→核心→深度→收尾 不被挤占）"""
        rows = self._rows()
        rows["opening"].follow_up_triggers = SAMPLE_TRIGGERS
        history = self._qa(rows["opening"].question, "hashCode 和 String 的应用我都很熟悉。")
        q = self._pick(rows, 2, history, True)
        assert q == rows["core"].question

    def test_vague_new_question_avoids_hard(self):
        """连续露怯（fallback 已问过）换新题时不优先 hard 深度题——
        避免把最难的技术题发给最弱的候选人"""
        rows = self._rows()
        history = self._qa(
            rows["core"].question,
            "HashMap 底层是数组加链表，插入时会先调用 hashCode 计算 key 的存储位置。",
        )
        # 已消耗降级策略一次（锚点链内已问过）
        history += [
            {"role": "interviewer", "content": "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"},
            {"role": "candidate", "content": "还是不清楚，没学过。"},
        ]
        # 锚点后 1 次追问且回答笼统 → fallback 已问过 → 换新题（avoid_hard：跳过深度考察）
        q = self._pick(rows, 3, history, True)
        assert q is None  # 核心题已问过、深度题被 avoid_hard 跳过 → 池空（调用方降级）

    def test_anchor_missing_picks_new(self):
        """无锚点（history 题目不在题库）→ 换新题"""
        rows = self._rows()
        history = self._qa("这是一道题库里没有的题", "我的回答也比较长，超过了二十个字符的阈值。")
        assert self._pick(rows, 3, history, True) == rows["deep"].question

    def test_asked_exclusion_skips_repeated_follow_up(self):
        """本锚点链内已问过的追问文本不再重复（取组内下一条）"""
        rows = self._rows()
        history = self._qa(rows["core"].question, "我不清楚")
        history += [
            {"role": "interviewer", "content": "能否结合你实际项目中的经验，举一个具体的使用场景？"},
            {"role": "candidate", "content": "还是不太了解这个点。"},
        ]
        # 锚点仍是 core（最后一条 interviewer 不在题库），follow_count=1、笼统 → 降级策略
        q = self._pick(rows, 3, history, True)
        assert q == "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"

    def test_shared_template_across_anchors_not_excluded(self):
        """追问去重只在锚点链内：跨锚点共享模板不互相排挤（真实题库模板文本跨题大量重复）"""
        rows = self._rows()
        # 锚点 A（core）消耗共享降级模板后，锚点 B（deep，只带同款降级模板）仍可问同文本
        history = self._qa(rows["core"].question, "我不清楚")
        history += [
            {"role": "interviewer", "content": "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"},
            {"role": "candidate", "content": "现在理解了，就是哈希表加链表的结构。"},
        ]
        rows["deep"].follow_up_triggers = (
            "【降级策略】当候选人回答困难时使用\n"
            "→ 那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"
        )
        history += [{"role": "interviewer", "content": rows["deep"].question},
                    {"role": "candidate", "content": "我不清楚"}]
        q = self._pick(rows, 5, history, True)
        # 锚点=deep（follow_count=0）、笼统 → 降级模板虽然上一锚点问过，仍可用
        assert q == "那我们先从更基础的角度看——你能简单说一下这个概念的基本定义和最常见用法吗？"

    def test_pick_stage_fallback_chain(self):
        """pick_stage：深度优先、无题降级核心；difficulty 过滤"""
        rows = self._rows()
        questions = list(rows.values())
        asked = {rows["deep"].question}
        assert pick_stage(questions, ("深度考察", "核心考察"), asked).question == rows["core"].question
        asked = {rows["core"].question, rows["deep"].question}
        assert pick_stage(questions, ("深度考察", "核心考察"), asked) is None
        # 开场 = 开场热身 + easy
        assert pick_stage(questions, ("开场热身",), set(), difficulty="easy").question == rows["opening"].question
        # 无 easy 开场题时 difficulty 过滤生效
        assert pick_stage(questions, ("核心考察",), set(), difficulty="easy") is None

    def test_last_candidate_answer(self):
        assert last_candidate_answer([]) == ""
        history = [
            {"role": "interviewer", "content": "Q1"},
            {"role": "candidate", "content": "A1"},
            {"role": "interviewer", "content": "Q2"},
        ]
        assert last_candidate_answer(history) == "A1"


class TestQuestionBankFlow:
    """adapter 全链集成（DB 造数）：开场 → 核心 → L1 → L2 → L3 → 收尾 + 空库兜底"""

    @pytest_asyncio.fixture(autouse=True)
    async def _init_db(self):
        await init_db()
        yield
        # 清理本类播种的数据：test_api 的全表计数断言（total==0）依赖空库，
        # 不清理则测试收集顺序（CLI 参数序/xdist）改变时断言 flaky
        async with async_session() as db:
            await db.execute(delete(Question).where(Question.position_code == FLOW_POSITION))
            await db.commit()

    async def _seed(self) -> dict[str, Question]:
        async with async_session() as db:
            await db.execute(delete(Question).where(Question.position_code == FLOW_POSITION))
            rows = _flow_questions()
            db.add_all(rows.values())
            await db.commit()
            return rows

    async def test_full_follow_up_chain(self):
        """真实 7 轮面试节奏：开场(答) → 核心题 → L1 → L2 → L3 → 收尾"""
        rows = await self._seed()
        adapter = get_interviewer_adapter()

        # round=1 开场：开场热身 + easy
        opening = await adapter.generate_question(
            position=FLOW_POSITION, round_no=1, history=[], interview_id=1, is_follow_up=False
        )
        assert opening == rows["opening"].question

        # round=2：开场题无触发条件 → 换新题 → 核心考察
        history = [
            {"role": "interviewer", "content": opening},
            {"role": "candidate", "content": "我是计算机专业学生，主要用 Java 做后端开发，做过商城和博客项目。"},
        ]
        q2 = await adapter.generate_question(
            position=FLOW_POSITION, round_no=2, history=history, interview_id=1, is_follow_up=True
        )
        assert q2 == rows["core"].question

        # round=3：核心题 L1——回答含"hashCode" → 关键词追问
        history += [
            {"role": "interviewer", "content": q2},
            {"role": "candidate", "content": "HashMap 底层是数组加链表，插入时会先调用 hashCode 计算 key 的存储位置。"},
        ]
        q3 = await adapter.generate_question(
            position=FLOW_POSITION, round_no=3, history=history, interview_id=1, is_follow_up=True
        )
        assert q3 == "HashMap中key的hash计算过程"

        # round=4：同一锚点已追问 1 次 → L2 递进追问
        history += [
            {"role": "interviewer", "content": q3},
            {"role": "candidate", "content": "hash 计算过程是取 key 的 hashCode 后让高位参与运算，目的是减少哈希碰撞。"},
        ]
        q4 = await adapter.generate_question(
            position=FLOW_POSITION, round_no=4, history=history, interview_id=1, is_follow_up=True
        )
        assert q4 == "在实际项目中这个知识点是如何应用的？能否举一个你踩过的坑？"

        # round=5：已追问 2 次 → L3 极限追问
        history += [
            {"role": "interviewer", "content": q4},
            {"role": "candidate", "content": "在实际项目里我用 HashMap 做过本地缓存，遇到过并发场景下扩容导致的数据不一致问题。"},
        ]
        q5 = await adapter.generate_question(
            position=FLOW_POSITION, round_no=5, history=history, interview_id=1, is_follow_up=True
        )
        assert q5 == "假设你需要设计一个高并发的缓存系统，请从三个维度阐述。"

        # round=6：最后两轮强制收尾交流
        history += [
            {"role": "interviewer", "content": q5},
            {"role": "candidate", "content": "高并发缓存系统我会从缓存一致性、失效策略和高可用三个维度来设计。"},
        ]
        q6 = await adapter.generate_question(
            position=FLOW_POSITION, round_no=6, history=history, interview_id=1, is_follow_up=True
        )
        assert q6 in (rows["closing"].question, rows["closing2"].question)

    async def test_new_question_prefers_deep_stage(self):
        """round>=3 换新题优先深度考察"""
        rows = await self._seed()
        adapter = get_interviewer_adapter()

        # 开场题无触发条件 → round=3 换新题 → 深度考察
        history = [
            {"role": "interviewer", "content": rows["opening"].question},
            {"role": "candidate", "content": "我是计算机专业学生，熟悉 Java 和数据库。"},
        ]
        q = await adapter.generate_question(
            position=FLOW_POSITION, round_no=3, history=history, interview_id=1, is_follow_up=True
        )
        assert q == rows["deep"].question

    async def test_find_anchor_counts_follow_ups(self):
        """锚点：精确匹配题库题干；锚点之后的非题库追问消息计入追问文本（次数=len 派生）"""
        rows = _flow_questions()
        questions = list(rows.values())

        history = [
            {"role": "interviewer", "content": rows["core"].question},
            {"role": "candidate", "content": "……"},
            {"role": "interviewer", "content": "这是题库里没有的一条追问文本"},
        ]
        anchor, trailing = find_anchor_question(questions, history)
        assert anchor is not None and anchor.question == rows["core"].question
        assert trailing == ["这是题库里没有的一条追问文本"]

        # 追问文本内嵌题干（如 L1 兜底追问引用原题）不应被误判为新锚点
        history_with_quote = [
            {"role": "interviewer", "content": rows["core"].question},
            {"role": "interviewer", "content": f"结合「{rows['core'].question}」能举一个实际例子吗？"},
        ]
        anchor, trailing = find_anchor_question(questions, history_with_quote)
        assert anchor is not None and anchor.question == rows["core"].question
        assert trailing == [f"结合「{rows['core'].question}」能举一个实际例子吗？"]

    async def test_empty_bank_falls_back_to_mock(self):
        """岗位无题 → 落内置 Mock 题库，流程不中断"""
        from app.adapters.ai_interviewer import GENERAL_OPENING_QUESTIONS

        adapter = get_interviewer_adapter()
        question = await adapter.generate_question(
            position="nobank_position", round_no=1, history=[], interview_id=0, is_follow_up=False
        )
        assert question in GENERAL_OPENING_QUESTIONS
