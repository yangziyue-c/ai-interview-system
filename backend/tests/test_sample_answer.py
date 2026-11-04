"""示范作答接口测试：缓存命中、题库外题、大模型未配置、状态校验

不测真实 LLM 生成（测试环境清空了 LLM_API_KEY）；生成路径的输入组装由
`core/sample_answer.py` 的纯函数边界覆盖，接口层只负责缓存与错误转换。
"""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.models import Question, SampleAnswer
from tests.helpers import make_question

BASE = "/api/v1"


@pytest_asyncio.fixture
async def _cleanup_questions():
    yield
    from app.database import async_session

    async with async_session() as db:
        await db.execute(
            delete(Question).where(Question.question_no.like("JAVA_BACKEND-Q9000%"))
        )
        await db.commit()


async def _register(client: AsyncClient) -> dict:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": f"sample_{uuid.uuid4().hex[:8]}",
            "password": "pass123456",
            "nickname": "示范作答测试",
            "target_position": "backend",
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def _finished_interview(client: AsyncClient, headers: dict) -> tuple[int, int]:
    """跑完一场面试，返回 (interview_id, 第一条问答记录 id)"""
    resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
    interview_id = resp.json()["data"]["interview"]["id"]
    await client.post(
        f"{BASE}/interviews/{interview_id}/answers",
        json={"answer": "我会先讲结论，再分点说明依据。"},
        headers=headers,
    )
    finish = await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)
    assert finish.status_code == 200, finish.text

    detail = await client.get(f"{BASE}/interviews/{interview_id}", headers=headers)
    qa_id = detail.json()["data"]["qa_records"][0]["id"]
    return interview_id, qa_id


class TestSampleAnswer:
    async def test_requires_finished_interview(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]
        detail = await client.get(f"{BASE}/interviews/{interview_id}", headers=headers)
        qa_id = detail.json()["data"]["qa_records"][0]["id"]

        out = await client.post(
            f"{BASE}/interviews/{interview_id}/qa/{qa_id}/sample-answer", headers=headers
        )
        assert out.status_code == 409

    async def test_question_outside_bank(self, client: AsyncClient):
        headers = await _register(client)
        interview_id, qa_id = await _finished_interview(client, headers)
        resp = await client.post(
            f"{BASE}/interviews/{interview_id}/qa/{qa_id}/sample-answer", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["available"] is False
        assert data["content"] is None
        assert "不在题库" in data["notice"]

    async def test_cached_answer_returned(self, client: AsyncClient, _cleanup_questions):
        headers = await _register(client)
        interview_id, qa_id = await _finished_interview(client, headers)

        # 把这条问答改成题库里的题（造题后同步题干）
        from app.database import async_session
        from app.models import QARecord

        question = make_question(question=f"示范作答缓存题 {uuid.uuid4().hex[:6]}")
        async with async_session() as db:
            db.add(question)
            qa = await db.get(QARecord, qa_id)
            qa.question = question.question
            db.add(
                SampleAnswer(
                    qa_record_id=qa_id,
                    question_no=question.question_no,
                    content="这是一份已缓存的示范作答。",
                    model="test-model",
                )
            )
            await db.commit()

        resp = await client.post(
            f"{BASE}/interviews/{interview_id}/qa/{qa_id}/sample-answer", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["available"] is True
        assert data["cached"] is True
        assert data["content"] == "这是一份已缓存的示范作答。"
        assert data["question_no"] == question.question_no

    async def test_llm_not_configured_returns_503(self, client: AsyncClient, _cleanup_questions):
        headers = await _register(client)
        interview_id, qa_id = await _finished_interview(client, headers)

        from app.database import async_session
        from app.models import QARecord

        question = make_question(question=f"示范作答生成题 {uuid.uuid4().hex[:6]}")
        async with async_session() as db:
            db.add(question)
            qa = await db.get(QARecord, qa_id)
            qa.question = question.question
            await db.commit()

        resp = await client.post(
            f"{BASE}/interviews/{interview_id}/qa/{qa_id}/sample-answer", headers=headers
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["code"] == 50300

    async def test_qa_from_other_interview_404(self, client: AsyncClient):
        headers = await _register(client)
        first_id, _ = await _finished_interview(client, headers)
        _, other_qa_id = await _finished_interview(client, headers)

        resp = await client.post(
            f"{BASE}/interviews/{first_id}/qa/{other_qa_id}/sample-answer", headers=headers
        )
        assert resp.status_code == 404
