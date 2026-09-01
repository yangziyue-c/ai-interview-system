"""数据库：SQLAlchemy 2.0 异步引擎与会话管理

默认 SQLite（零配置），.env 中切换 MySQL：
    DATABASE_URL=mysql+aiomysql://user:password@host:3306/dbname
"""
from collections.abc import AsyncGenerator

from sqlalchemy import func, inspect, insert, select
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


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """轻量迁移：表已存在但缺列时补列（兼容老数据库，幂等）

    说明：create_all 只建表不加列；模型新增字段后，
    已存在的数据库需要手动补列才能继续使用。
    """
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    if column not in existing:
        conn.exec_driver_sql(ddl)


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
