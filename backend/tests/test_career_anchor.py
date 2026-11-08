"""岗位倾向速测：题目下发、20 条评分、岗位推荐与非法作答"""
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


def _answers_for(position: str, high: int = 5, low: int = 2) -> list[int]:
    """构造偏向某个岗位的 20 条评分：该岗位 4 条给高分，其余给低分"""
    from app.core.career_anchor import SCALE_QUESTIONS

    return [
        high if question["role"] == position else low
        for question in SCALE_QUESTIONS
    ]


class TestCareerAnchor:
    async def test_questions_shape(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.get(f"{BASE}/career-anchor/questions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 20
        assert len(data["questions"]) == 20
        assert len(data["interest_ratings"]) == 5
        assert len(data["ability_ratings"]) == 5
        for question in data["questions"]:
            assert set(question) == {"id", "category", "role", "text"}
            assert question["category"] in ("interest", "ability")
            assert question["role"] in {
                "backend", "frontend", "test_engineer", "algorithm", "system_design"
            }

    @pytest.mark.parametrize(
        "position", ["backend", "frontend", "test_engineer", "algorithm", "system_design"]
    )
    async def test_position_specific_answers(self, client: AsyncClient, position: str):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": _answers_for(position)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["recommended"]["position"] == position
        assert data["recommended"]["name"]
        assert data["recommended"]["reason"]
        assert 0 <= data["recommended"]["index"] <= 100
        assert len(data["scores"]) == 5
        assert data["scores"][0]["position"] == position
        assert data["confidence"] in ("高", "中", "低")
        assert 0 <= data["consistency_percent"] <= 100
        assert data["guide"]

    async def test_all_same_scores_are_unclear(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": [5] * 20},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        # 五个岗位同分，分差为 0，不能形成明确推荐
        assert data["margin"] == 0
        assert data["title"] == "方向暂不明确"
        assert data["confidence"] == "低"
        assert data["consistency_percent"] == 100

    async def test_result_saved_to_settings(self, client: AsyncClient):
        headers = await _register(client)
        before = await client.get(f"{BASE}/settings", headers=headers)
        assert before.json()["data"]["career_anchor_result"] is None

        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": _answers_for("backend")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()["data"]

        after = await client.get(f"{BASE}/settings", headers=headers)
        saved = after.json()["data"]["career_anchor_result"]
        assert saved["position"] == "backend"
        assert saved["name"] == result["recommended"]["name"]
        assert saved["index"] == result["recommended"]["index"]
        assert saved["consistency_percent"] == result["consistency_percent"]
        assert saved["confidence"] == result["confidence"]
        assert saved["tested_at"]

    async def test_missing_answers_rejected(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": [5] * 19},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "20 条" in resp.json()["message"]

    @pytest.mark.parametrize("bad", [0, 6])
    async def test_out_of_range_rejected(self, client: AsyncClient, bad):
        headers = await _register(client)
        answers = [5] * 20
        answers[3] = bad
        resp = await client.post(
            f"{BASE}/career-anchor/submit",
            json={"answers": answers},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "1~5" in resp.json()["message"]

    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/career-anchor/questions")
        assert resp.status_code == 401
