"""离线版首次启动时补齐本地题库。

只在 questions 表为空时导入 backend/rag/数据/*-v5.json。已有数据不做重建，
避免离线启动误删用户面试记录或题库修改。
"""
import asyncio
import sys

from sqlalchemy import func, select

from app.database import async_session, engine, init_db
from app.models import Question
from scripts.import_question_bank import import_bank


async def ensure_question_bank() -> int:
    await init_db()
    async with async_session() as session:
        count = int((await session.scalar(select(func.count()).select_from(Question))) or 0)
    if count:
        print(f"离线题库已就绪：{count} 题")
        return count

    print("离线题库为空，开始导入 V5 主库（仅首次执行）...")
    await import_bank()
    async with async_session() as session:
        count = int((await session.scalar(select(func.count()).select_from(Question))) or 0)
    print(f"离线题库导入完成：{count} 题")
    return count


def main() -> None:
    try:
        asyncio.run(ensure_question_bank())
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
