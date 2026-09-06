"""测试共享工厂（独立于 conftest：conftest 是 pytest 钩子文件且有环境副作用，
不应被测试模块以普通 import 依赖）"""
import uuid

from app.models import Question


def make_question(**overrides) -> Question:
    """测试造数：默认值铺底，只覆盖差异字段（test_api / test_question_bank 共用）

    question_no 默认带随机后缀：questions 表有 (position_code, question_no)
    唯一约束，默认键二次插入会 IntegrityError；随机后缀让调用方无需
    显式覆盖即可多次造数。
    """
    base = dict(
        position_code="backend",
        question_no=f"tech_001_{uuid.uuid4().hex[:8]}",
        category="技术知识", sub_category="Java基础", difficulty="easy",
        question="Java中==和equals()的区别是什么？",
        score_points="", follow_up_triggers="",
        reference_answer="", note="",
        interview_stage="开场热身", stage_order=1, suggested_minutes=3,
        alternative_directions="", excellent_example="",
    )
    return Question(**(base | overrides))
