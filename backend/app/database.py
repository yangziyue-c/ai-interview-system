"""数据库：SQLAlchemy 2.0 异步引擎与会话管理

默认 SQLite（零配置），.env 中切换 MySQL：
    DATABASE_URL=mysql+aiomysql://user:password@host:3306/dbname
"""
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import func, inspect, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


engine_kwargs: dict = {"echo": settings.SQL_ECHO}
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite 需要检查同一线程，异步场景下禁用；busy_timeout 让并发写等待而非立刻报锁
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

if settings.DATABASE_URL.startswith("sqlite"):
    # 每个连接启用 WAL + busy_timeout：WAL 下读不阻塞写，配合 timeout 让
    # 并发写（两场面试同时提交答案）等待锁释放而非抛 database is locked
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


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


# V5 题库换代（2026-09-14）：questions 表由 18 列重构为 19 列，涉及删列，
# 无法用 _ensure_column 自动迁移，故只做启动告警——结构更新走导入脚本的 --rebuild。
def _warn_questions_schema(conn) -> None:
    """比对 questions 实际列与模型列，缺列/多列时打日志（不抛异常）。

    刻意「只告警不阻断」：老库结构下服务仍能启动（题库策略查不到字段会自行降级），
    比直接 500 更利于排查；但日志必须醒目，提示执行 rebuild 命令。
    期望列由 `models.question.expected_columns()` 派生（与导入脚本共用同一事实源）。
    """
    insp = inspect(conn)
    if "questions" not in insp.get_table_names():
        return
    from app.models.question import expected_columns

    expected = expected_columns()
    existing = {c["name"] for c in insp.get_columns("questions")}
    missing = expected - existing
    stale = existing - expected - {"id"}
    if missing:
        logger.error(
            "questions 表结构过旧，缺少列：%s。请执行："
            "python -m scripts.import_question_bank --rebuild --yes",
            "、".join(sorted(missing)),
        )
    if stale:
        logger.warning(
            "questions 表存在 V5 已废弃的列：%s（不影响运行，可忽略）",
            "、".join(sorted(stale)),
        )


# 占位岗位位 → 正式岗位（V5 知识库换代：5 岗位全开，2026-09-14）
_PLACEHOLDER_REMAP = {"pending_a": "algorithm", "pending_b": "system_design"}


async def _align_positions(conn) -> None:
    """老库岗位对齐：占位位改名 + 缺失岗位补插（幂等，不覆盖已有岗位的其它字段）

    seed 只在 positions 表为空时生效，因此已建库的机器不会自动拿到新岗位，
    此函数补上这一步。用改名而非删建：pending_* 从未 enabled（无存量用户
    选中过），且 interviews.position 是字符串无外键，改名不影响历史会话。
    """
    from app.models.position import DEFAULT_POSITIONS, Position

    # 只取 code 列（在 Core 连接上执行 ORM 实体 select 需 ORM-enabled session，
    # 这里拿标量列更直接，也避免把整行加载进内存）
    defaults = {item["code"]: item for item in DEFAULT_POSITIONS}
    existing = set((await conn.execute(select(Position.code))).scalars().all())
    for old, new in _PLACEHOLDER_REMAP.items():
        if old in existing and new not in existing:
            # 占位岗位的 name/enabled/描述本就是无效占位值，改名时一并写入正式配置
            # （非占位岗位不在改名范围，其自定义字段不会被覆盖）
            await conn.execute(
                update(Position).where(Position.code == old).values(**defaults[new])
            )
            logger.info("岗位对齐：占位位 %s 已改名为正式岗位 %s", old, new)
            existing.discard(old)
            existing.add(new)
    for item in DEFAULT_POSITIONS:
        if item["code"] not in existing:
            await conn.execute(insert(Position).values(**item))
            logger.info("岗位对齐：补插缺失岗位 %s", item["code"])


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
        # 头像地址（个人中心支持更换头像；老库补列后为 NULL，前端回退首字母占位）
        await conn.run_sync(
            _ensure_column,
            "users",
            "avatar_url",
            "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)",
        )
        # 评估维度从 4 维扩展为 5 维（2026-09-04，源自《评估维度.csv》的「应变能力」）
        await conn.run_sync(
            _ensure_column,
            "reports",
            "adaptability_score",
            "ALTER TABLE reports ADD COLUMN adaptability_score FLOAT DEFAULT 0.0",
        )
        # AI 对话层引擎集成（2026-09-23）：三张表各补一列，老库启动即自愈。
        # 顺带一提：interviews.engine 的默认值必须是 ''（不是 NULL）——判链路用的
        # 是字符串比较，历史行走 NULL 会让「原链路」这个判断多一种写法。
        await conn.run_sync(
            _ensure_column,
            "interviews",
            "engine",
            "ALTER TABLE interviews ADD COLUMN engine VARCHAR(16) DEFAULT ''",
        )
        await conn.run_sync(
            _ensure_column,
            "interviews",
            "engine_session_id",
            "ALTER TABLE interviews ADD COLUMN engine_session_id VARCHAR(64)",
        )
        await conn.run_sync(
            _ensure_column,
            "qa_records",
            "engine_turns",
            "ALTER TABLE qa_records ADD COLUMN engine_turns JSON",
        )
        await conn.run_sync(
            _ensure_column,
            "reports",
            "engine_meta",
            "ALTER TABLE reports ADD COLUMN engine_meta JSON",
        )
        # 注：原「题库 V4 第 16 列 expression_points」的补列语句已随 V5 换代删除——
        # 该列在新表结构中不存在，留着会在每次启动把已删列 ALTER 回来。
        # questions 的结构变更走 scripts/import_question_bank.py --rebuild，
        # 此处只做告警（见 _warn_questions_schema 调用）。
        await conn.run_sync(_warn_questions_schema)
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
        # 岗位对齐（幂等，不覆盖已有岗位的其它字段）：
        # 空表时等价于最初的 seed；老库升级时把占位位改名为正式岗位并补插缺失岗位。
        # 统一走一个函数——原实现「空表 seed / 非空对齐」两分支各自补插，同一规则写了两遍。
        await _align_positions(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个数据库会话"""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
