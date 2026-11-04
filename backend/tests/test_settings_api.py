"""设置接口测试：默认值、部分更新、非法取值"""
import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


async def _register(client: AsyncClient) -> dict:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": f"settings_{uuid.uuid4().hex[:8]}",
            "password": "pass123456",
            "nickname": "设置测试",
            "target_position": "backend",
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


class TestSettings:
    async def test_defaults_without_row(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.get(f"{BASE}/settings", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {
            "default_position": "",
            "voice_answer": True,
            "auto_tts": True,
            "body_language": True,
            "report_preference": "detailed",
            "theme": "system",
        }

    async def test_partial_update(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.put(
            f"{BASE}/settings",
            json={"theme": "dark", "voice_answer": False, "default_position": "frontend"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["theme"] == "dark"
        assert data["voice_answer"] is False
        assert data["default_position"] == "frontend"
        # 未提交的字段保持默认
        assert data["auto_tts"] is True
        assert data["report_preference"] == "detailed"

        # 第二次读取仍是已保存的值（不是默认值）
        again = await client.get(f"{BASE}/settings", headers=headers)
        assert again.json()["data"]["theme"] == "dark"

    async def test_clear_default_position_with_empty_string(self, client: AsyncClient):
        headers = await _register(client)
        await client.put(
            f"{BASE}/settings", json={"default_position": "backend"}, headers=headers
        )
        resp = await client.put(
            f"{BASE}/settings", json={"default_position": ""}, headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["default_position"] == ""

    @pytest.mark.parametrize(
        "payload, message",
        [
            ({"theme": "blue"}, "theme"),
            ({"report_preference": "verbose"}, "report_preference"),
            ({"default_position": "not_a_position"}, "岗位"),
        ],
    )
    async def test_invalid_values(self, client: AsyncClient, payload: dict, message: str):
        headers = await _register(client)
        resp = await client.put(f"{BASE}/settings", json=payload, headers=headers)
        assert resp.status_code == 400, resp.text
        assert message in resp.json()["message"]

    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/settings")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100
