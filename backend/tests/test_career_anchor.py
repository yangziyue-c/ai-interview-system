"""职业锚定测试：题目下发、计分推荐、非法作答"""
import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


async def _register(client: AsyncClient) -> dict:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": f"anchor_{uuid.uuid4().hex[:8]}",
            "password": "pass123456",
            "nickname": "锚定测试",
            "target_position": "backend",
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


class TestCareerAnchor:
    async def test_questions_hide_scores(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.get(f"{BASE}/career-anchor/questions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 5
        assert len(data["questions"]) == 5
        for question in data["questions"]:
            assert set(question) == {"id", "text", "options"}
            for option in question["options"]:
                # 计分权重绝不能下发给前端
                assert set(option) == {"key", "text"}

    async def test_submit_recommends_enabled_position(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A"}},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["recommended"]["position"] in {
            "backend", "frontend", "algorithm", "test_engineer", "system_design"
        }
        assert data["recommended"]["name"]
        assert data["recommended"]["reason"]
        assert data["guide"]
        # alternatives 不含推荐岗位本身
        alt_positions = {item["position"] for item in data["alternatives"]}
        assert data["recommended"]["position"] not in alt_positions
        # scores 覆盖全部 5 个岗位，且按降序
        scores = [item["score"] for item in data["scores"]]
        assert len(scores) == 5
        assert scores == sorted(scores, reverse=True)

    async def test_frontend_answers_recommend_frontend(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": {"q1": "B", "q2": "B", "q3": "B", "q4": "B", "q5": "B"}},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["recommended"]["position"] == "frontend"

    async def test_missing_answer_rejected(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": {"q1": "A", "q2": "A"}},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "未作答" in resp.json()["message"]

    async def test_unknown_option_rejected(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": {"q1": "Z", "q2": "A", "q3": "A", "q4": "A", "q5": "A"}},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "选项非法" in resp.json()["message"]

    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/career-anchor/questions")
        assert resp.status_code == 401
