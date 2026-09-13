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
# 测试必须禁用大模型直连（本机 .env 若配置了 LLM_API_KEY，空库测试会误调真实大模型）
os.environ["LLM_API_KEY"] = ""
# RAG 源也要禁用：config.py 里它默认为 http://localhost:8003（不像上三个默认为空），
# 不禁用会让每个「题库未命中」的用例真去连本机 8003——服务没起时每次白等 1 秒探测超时，
# 服务起了则拿到真实题目，「空库降级 Mock」这类断言就失去了意义。
os.environ["RAG_API_URL"] = ""

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
