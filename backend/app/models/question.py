"""面试题库表：存储岗位化题库（V5，5 岗位 × 5012 题）

数据来源：`backend/rag/数据/{岗位}-v5.json`（P5 交付的 V5 知识库），
由 `scripts/import_question_bank.py` 导入。
题目编号 = V5 原题ID（如 `JAVA_BACKEND-Q0001`），与 RAG 向量库元数据的
「原题ID」同键，唯一约束为 (position_code, question_no)。

供面试官算法（backend/interviewer_new/）抽取使用：
- 开场题：按 interview_stage + difficulty 过滤；
- 追问：直接读 follow_up_l1/l2/l3 与 fallback_strategy——V5 已把三级追问
  拆成独立字段，无需再做文本解析（V4 时代那段 119 行正则兼容层已废弃）。
"""
from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 受控词表（V5 交付包口径，导入脚本与查询接口共用，非法值返回 400）
# V5（2026-09-14）：题型由 V4 的 6 类收敛为交付包的 4 类
QUESTION_CATEGORIES = ("技术知识题", "场景应用题", "项目经历题", "行为素质题")
QUESTION_DIFFICULTIES = ("easy", "medium", "hard")
# V5 的面试阶段：原样使用交付包取值（不做「深度压轴→深度考察」之类的翻译，
# 翻译层已随 V4 算法一起废弃）
QUESTION_STAGES = ("开场热身", "核心考察", "深度压轴")
# 阶段顺序（V5 无「阶段顺序」列，导入时按此派生 stage_order）
STAGE_ORDERS = {"开场热身": 1, "核心考察": 2, "深度压轴": 3}


def expected_columns() -> set[str]:
    """模型期望的业务列（不含自增主键 id）

    「表结构是否过旧」的**单一事实源**，供两处消费：
    - `app/database.py::_warn_questions_schema`（服务启动，缺列只告警）
    - `scripts/import_question_bank.py::_assert_schema`（导入命令，缺列直接报错）

    从 `__table__.columns` 派生而非手抄列表：加字段时两处守卫自动跟随。
    """
    return {c.name for c in Question.__table__.columns} - {"id"}


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("position_code", "question_no", name="uq_question_position_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 岗位 code（backend / frontend / test_engineer / algorithm / system_design），与 positions 表对齐
    position_code: Mapped[str] = mapped_column(String(32), index=True, comment="岗位 code")
    # V5 原题ID（JAVA_BACKEND-Q0001），与 RAG 向量库元数据「原题ID」同键
    question_no: Mapped[str] = mapped_column(String(32), comment="V5 原题ID")
    # 题型：技术知识题 / 场景应用题 / 项目经历题 / 行为素质题
    category: Mapped[str] = mapped_column(String(32), comment="题型分类")
    # 难度：easy / medium / hard
    difficulty: Mapped[str] = mapped_column(String(16), comment="难度等级")
    # 题干（可直接读给候选人）
    question: Mapped[str] = mapped_column(Text, comment="面试问题题干")
    # 面试阶段：开场热身(1) / 核心考察(2) / 深度压轴(3)
    interview_stage: Mapped[str] = mapped_column(String(16), comment="面试阶段")
    stage_order: Mapped[int] = mapped_column(Integer, comment="阶段顺序 1~3")
    suggested_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="建议用时(分)")
    # ---------------- 以下为 V5 交付包独有素材 ----------------
    keywords: Mapped[str] = mapped_column(Text, default="", comment="核心关键词（换行分隔）")
    exam_priority: Mapped[str] = mapped_column(
        String(16), default="", comment="考点优先级：常规题/高频必考题/拓展题"
    )
    basic_score_points: Mapped[str] = mapped_column(Text, default="", comment="基础得分点")
    advanced_score_points: Mapped[str] = mapped_column(Text, default="", comment="进阶得分点")
    # 三级追问：原文含 [触发] / [追问] 标记行，解析由 interviewer_new 负责
    follow_up_l1: Mapped[str] = mapped_column(Text, default="", comment="L1 基础追问")
    follow_up_l2: Mapped[str] = mapped_column(Text, default="", comment="L2 递进追问")
    follow_up_l3: Mapped[str] = mapped_column(Text, default="", comment="L3 拓展追问")
    fallback_strategy: Mapped[str] = mapped_column(
        Text, default="", comment="降级策略（考生答不出时的引导话术）"
    )
    # 单题校准锚点：[技术水平] / [岗位匹配度] 两行，P3 单题评分素材
    calibration_anchor: Mapped[str] = mapped_column(Text, default="", comment="单题校准锚点")
    # 关联知识点：{知识点ID}|{名称}|{学习建议}，多行
    related_knowledge: Mapped[str] = mapped_column(Text, default="", comment="关联知识点")
