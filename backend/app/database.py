"""数据库：SQLAlchemy 2.0 异步引擎与会话管理

默认 SQLite（零配置），.env 中切换 MySQL：
    DATABASE_URL=mysql+aiomysql://user:password@host:3306/dbname
"""
from collections.abc import AsyncGenerator

from sqlalchemy import func, inspect, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


engine_kwargs: dict = {"echo": settings.SQL_ECHO}
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite 需要检查同一线程，异步场景下禁用
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _ensure_column(conn, table: str, column: str, ddl: str) -> bool:
    """轻量迁移：表已存在但缺列时补列（兼容老数据库，幂等）

    说明：create_all 只建表不加列；模型新增字段后，
    已存在的数据库需要手动补列才能继续使用。
    返回 True 表示本次执行了补列（调用方可继续做数据回填）。
    """
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return False
    existing = {c["name"] for c in insp.get_columns(table)}
    if column not in existing:
        conn.exec_driver_sql(ddl)
        return True
    return False


async def init_db() -> None:
    """启动时建表 + 轻量列迁移（表不存在才创建，不影响已有数据）"""
    # 导入模型，确保注册到 Base.metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 历史库补列（SQLite / MySQL 通用 DDL，可空列无默认值约束问题）
        await conn.run_sync(
            _ensure_column,
            "users",
            "student_id",
            "ALTER TABLE users ADD COLUMN student_id VARCHAR(32)",
        )
        # 评估维度从 4 维扩展为 5 维（2026-09-04，源自《评估维度.csv》的「应变能力」）
        await conn.run_sync(
            _ensure_column,
            "reports",
            "adaptability_score",
            "ALTER TABLE reports ADD COLUMN adaptability_score FLOAT DEFAULT 0.0",
        )
        # 历史报告回填：应变分留 0 会让前端雷达图畸变。
        # 自愈式按需回填（非仅在补列当次执行）：MySQL 的 ALTER 隐式提交导致补列与
        # 回填不在同一事务时，任何遗漏都会在下次启动补齐。
        # 口径与评估适配器的运行时兜底一致：用表达分近似（应变与临场表达高度相关）
        # 注（F7 决策记录）：此处刻意不重算 total_score——老行 total 是 4 维时代口径，
        # 无应变概念，强行按 5 维等式重算会改写历史分数且语义依旧失真。自 5 维代码
        # 上线起所有新报告均满足 total=Σ(维分×权重)；新老混用只存在于历史 4 维库
        # 升级场景，当前开发/上线库均从 5 维起，无实际影响，故维持现状。
        from app.models import Report

        need_fill = await conn.scalar(
            select(func.count()).select_from(Report).where(Report.adaptability_score == 0)
        )
        if need_fill:
            await conn.execute(
                update(Report)
                .where(Report.adaptability_score == 0)
                .values(adaptability_score=func.coalesce(Report.expression_score, 0.0))
            )
        # 岗位 seed：positions 表为空时插入默认 5 个岗位位（幂等，不覆盖已有数据）
        from app.models.position import DEFAULT_POSITIONS, Position

        position_count = await conn.scalar(select(func.count()).select_from(Position))
        if position_count == 0:
            await conn.execute(insert(Position), DEFAULT_POSITIONS)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个数据库会话"""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
