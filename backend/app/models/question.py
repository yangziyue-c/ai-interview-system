"""面试题库表：存储岗位化题库（v13，3 岗位 × 150 题）

数据来源：仓库根目录 题库/*.xlsx，由 scripts/import_question_bank.py 导入。
题目编号在岗位内唯一（跨岗位重复，如每岗都有 tech_001），
唯一约束为 (position_code, question_no)。

供后端开发 B（AI专项1）的面试官对话逻辑抽取使用：
开场题/追问按 interview_stage + stage_order + difficulty 过滤选题。
"""
from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 受控词表（题库 xlsx 与查询接口共用，导入脚本/API 校验非法值）
QUESTION_CATEGORIES = ("技术知识", "场景与设计", "编码与算法", "项目深挖", "行为面试")
QUESTION_DIFFICULTIES = ("easy", "medium", "hard")
QUESTION_STAGES = ("开场热身", "核心考察", "深度考察", "收尾交流")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("position_code", "question_no", name="uq_question_position_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 岗位 code（backend / frontend / test_engineer），与 positions 表对齐
    position_code: Mapped[str] = mapped_column(String(32), index=True, comment="岗位 code")
    # 题库编号（tech_001 / scene_012 / code_003 / project_001 / behavior_001）
    question_no: Mapped[str] = mapped_column(String(32), comment="题库编号")
    # 大类：技术知识 / 场景与设计 / 编码与算法 / 项目深挖 / 行为面试
    category: Mapped[str] = mapped_column(String(32), comment="大类")
    # 题目分类（如 Java基础 / 排障Debug / 测试用例设计）
    sub_category: Mapped[str] = mapped_column(String(64), default="", comment="题目分类")
    # 难度：easy / medium / hard
    difficulty: Mapped[str] = mapped_column(String(16), comment="难度等级")
    # 题干（已剥离「【岗位软技能考察：X】」元信息，可直接读给候选人）
    question: Mapped[str] = mapped_column(Text, comment="面试问题题干")
    # 从题干剥离出的软技能考察标签（如「故障应急响应意识」），仅作选题参考
    soft_skill_tag: Mapped[str] = mapped_column(String(64), default="", comment="软技能考察标签")
    # 得分点：【basic x】【core y】【advanced z】三段加权，合计 1.0，评分 Prompt 素材
    score_points: Mapped[str] = mapped_column(Text, default="", comment="得分点")
    # 追问触发条件：L1 关键词触发 / L2 深入 / L3 极限 / 降级策略，追问生成核心依据
    follow_up_triggers: Mapped[str] = mapped_column(Text, default="", comment="追问触发条件")
    reference_answer: Mapped[str] = mapped_column(Text, default="", comment="参考答案")
    note: Mapped[str] = mapped_column(Text, default="", comment="备注（选题参考）")
    # 面试阶段：开场热身(1) / 核心考察(2) / 深度考察(3) / 收尾交流(4)
    interview_stage: Mapped[str] = mapped_column(String(16), comment="面试阶段")
    stage_order: Mapped[int] = mapped_column(Integer, comment="阶段顺序 1~4")
    suggested_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="建议用时(分钟)")
    alternative_directions: Mapped[str] = mapped_column(Text, default="", comment="替代回答方向")
    excellent_example: Mapped[str] = mapped_column(Text, default="", comment="优秀回答范例")
