"""数据库：SQLAlchemy 2.0 异步引擎与会话管理

默认 SQLite（零配置），.env 中切换 MySQL：
    DATABASE_URL=mysql+aiomysql://user:password@host:3306/dbname
"""
from collections.abc import AsyncGenerator

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


async def init_db() -> None:
    """启动时建表（表不存在才创建，不影响已有数据）"""
    # 导入模型，确保注册到 Base.metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个数据库会话"""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
