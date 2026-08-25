"""pytest 公共夹具

注意：必须在 import app 之前设置环境变量，指向独立测试库，
避免污染开发数据库（backend/interview.db）。
"""
import os
import pathlib

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_interview.db"
os.environ["REDIS_URL"] = ""
os.environ["AI_INTERVIEWER_URL"] = ""
os.environ["AI_EVALUATOR_URL"] = ""

# 每次测试会话开始时清空旧测试库，保证用例可重复执行
pathlib.Path("test_interview.db").unlink(missing_ok=True)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
