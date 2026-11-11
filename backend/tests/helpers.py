"""测试共享工厂（独立于 conftest：conftest 是 pytest 钩子文件且有环境副作用，
不应被测试模块以普通 import 依赖）"""
import uuid

from app.models import Question


def make_question(**overrides) -> Question:
    """测试造数：默认值铺底，只覆盖差异字段（test_api / test_question_bank 共用）

    question_no 默认带随机后缀：questions 表有 (position_code, question_no)
    唯一约束，默认键二次插入会 IntegrityError；随机后缀让调用方无需
    显式覆盖即可多次造数。

    字段集对应 V5 表结构（19 列）——三列 V5 独有素材（得分点/追问/锚点等）
    默认留空，需要时由调用方覆盖。
    """
    base = dict(
        position_code="backend",
        question_no=f"JAVA_BACKEND-Q9000_{uuid.uuid4().hex[:8]}",
        category="技术知识题", difficulty="easy",
        question="JVM、JDK、JRE 三者有什么区别和联系？",
        interview_stage="开场热身", stage_order=1, suggested_minutes=3,
        keywords="JVM\nJDK\nJRE", exam_priority="高频必考题",
        basic_score_points="", advanced_score_points="",
        follow_up_l1="", follow_up_l2="", follow_up_l3="",
        fallback_strategy="", calibration_anchor="", related_knowledge="",
    )
    return Question(**(base | overrides))


def make_follow_up_field(trigger: str, text: str) -> str:
    """构造 V5 格式的追问字段（`[触发] 条件` + `[追问] 文本`），供测试造数"""
    return f"[触发] {trigger}\n[追问] {text}"
