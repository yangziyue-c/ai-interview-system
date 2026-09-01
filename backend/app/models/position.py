"""岗位表：岗位由数据库动态维护，替代硬编码枚举

启动时若 positions 表为空，自动 seed DEFAULT_POSITIONS（5 个岗位位）。
岗位清单确定后，只需更新数据库记录（enabled 控制上/下线），无需改代码。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 默认 5 个岗位位：3 个已有题库支撑的岗位 + 2 个占位（岗位清单未定，待团队确定后更新）
DEFAULT_POSITIONS: list[dict] = [
    {
        "code": "backend",
        "name": "后端开发工程师",
        "description": "负责服务端架构与业务逻辑开发，考察编程语言、数据库、并发与系统设计能力。",
        "tech_stack": ["Java", "Python", "MySQL", "Redis", "Spring Boot"],
        "focus": ["数据结构与算法", "数据库", "并发编程", "分布式系统"],
        "enabled": True,
        "sort_order": 1,
    },
    {
        "code": "frontend",
        "name": "前端开发工程师",
        "description": "负责 Web 界面与交互开发，考察 HTML/CSS/JavaScript 基础、框架与工程化能力。",
        "tech_stack": ["HTML/CSS", "JavaScript", "TypeScript", "Vue3", "React"],
        "focus": ["CSS 布局", "JavaScript 核心", "前端框架", "性能优化"],
        "enabled": True,
        "sort_order": 2,
    },
    {
        "code": "test_engineer",
        "name": "测试开发工程师",
        "description": "负责软件质量保障，考察测试理论、用例设计与测试自动化能力。",
        "tech_stack": ["Python", "pytest", "Selenium", "JMeter", "Jenkins"],
        "focus": ["测试用例设计", "接口测试", "自动化测试", "缺陷管理"],
        "enabled": True,
        "sort_order": 3,
    },
    {
        "code": "pending_a",
        "name": "岗位待定 A",
        "description": "预留岗位位，岗位名称与考察方向待团队确定后更新。",
        "tech_stack": [],
        "focus": [],
        "enabled": False,
        "sort_order": 4,
    },
    {
        "code": "pending_b",
        "name": "岗位待定 B",
        "description": "预留岗位位，岗位名称与考察方向待团队确定后更新。",
        "tech_stack": [],
        "focus": [],
        "enabled": False,
        "sort_order": 5,
    },
]


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="岗位唯一标识（注册/面试传此值）")
    name: Mapped[str] = mapped_column(String(64), comment="岗位中文名")
    description: Mapped[str] = mapped_column(Text, default="", comment="岗位简介")
    tech_stack: Mapped[list] = mapped_column(JSON, default=list, comment="技术栈列表")
    focus: Mapped[list] = mapped_column(JSON, default=list, comment="考察重点列表")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否开放（占位岗位置 False）")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="岗位大厅展示顺序")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
