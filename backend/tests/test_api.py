"""全流程回归测试（P5 验收参考）

覆盖：注册登录、开始面试、多轮问答、自动结束出报告、手动结束、
成长曲线、越权访问、非法状态、音频上传、异常兜底格式。
"""
import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


def _unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, prefix: str = "user", position: str = "backend") -> tuple[str, dict]:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": _unique_name(prefix),
            "password": "pass123456",
            "nickname": "测试选手",
            "target_position": position,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    token = body["data"]["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


class TestAuth:
    async def test_register_login_me(self, client: AsyncClient):
        token, headers = await _register(client)
        assert token

        # me
        resp = await client.get(f"{BASE}/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["nickname"] == "测试选手"

        # 重复注册 → 400
        username = _unique_name("dup")
        resp = await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        assert resp.status_code == 200
        resp = await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_login_wrong_password(self, client: AsyncClient):
        username = _unique_name("wrong")
        await client.post(
            f"{BASE}/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        resp = await client.post(
            f"{BASE}/auth/login", json={"username": username, "password": "bad-pass"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

    async def test_unauthorized(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/auth/me")
        assert resp.status_code == 401
        resp = await client.get(f"{BASE}/interviews")
        assert resp.status_code == 401


class TestInterviewFlow:
    async def test_full_interview_auto_finish(self, client: AsyncClient):
        """完整面试：开场题 + 追问至上限 → 自动结束并出报告"""
        _, headers = await _register(client, "full")

        # 开始面试
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        interview_id = data["interview"]["id"]
        assert data["interview"]["status"] == "in_progress"
        assert data["question"]

        # 持续作答直到自动结束（上限 = 1 + MAX_FOLLOW_UP_ROUNDS = 7 轮）
        finished = False
        for _ in range(10):  # 防御性上限
            resp = await client.post(
                f"{BASE}/interviews/{interview_id}/answers",
                json={"answer": "我认为这个问题可以从数据一致性和系统可扩展性两个角度来分析。" * 2},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            if body["finished"]:
                finished = True
                assert body["report"] is not None
                assert 0 <= body["report"]["total_score"] <= 100
                assert body["report"]["strengths"]  # 报告含评语字段
                break
            assert body["next_question"], "未结束时应返回下一题"
        assert finished, "达到轮次上限后应自动结束"

        # 结束后再提交答案 → 409
        resp = await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "已经结束了"},
            headers=headers,
        )
        assert resp.status_code == 409

        # 获取报告
        resp = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        assert resp.status_code == 200
        report = resp.json()["data"]
        for key in ("tech_score", "logic_score", "expression_score", "match_score"):
            assert 0 <= report[key] <= 100

    async def test_manual_finish_and_growth(self, client: AsyncClient):
        """手动结束 → 报告生成 → 成长曲线含该次面试"""
        _, headers = await _register(client, "manual")

        resp = await client.post(f"{BASE}/interviews", json={"position": "frontend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]

        await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "我会先从资源加载、渲染管线、缓存策略三个层面来优化首屏性能。" * 2},
            headers=headers,
        )
        # 手动结束
        resp = await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["interview"]["status"] == "finished"
        assert resp.json()["data"]["report"]["interview_id"] == interview_id

        # 成长曲线
        resp = await client.get(f"{BASE}/reports/growth", headers=headers)
        assert resp.status_code == 200
        points = resp.json()["data"]
        assert any(p["interview_id"] == interview_id for p in points)

    async def test_two_ongoing_conflict(self, client: AsyncClient):
        """同一用户不能同时进行两场面试"""
        _, headers = await _register(client, "ongoing")
        assert (
            await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        ).status_code == 200
        resp = await client.post(
            f"{BASE}/interviews", json={"position": "backend"}, headers=headers
        )
        assert resp.status_code == 409

    async def test_other_user_cannot_access(self, client: AsyncClient):
        """越权：他人面试一律 404"""
        _, headers_a = await _register(client, "owner")
        _, headers_b = await _register(client, "hacker")

        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers_a)
        interview_id = resp.json()["data"]["interview"]["id"]

        resp = await client.get(f"{BASE}/interviews/{interview_id}", headers=headers_b)
        assert resp.status_code == 404

    async def test_report_before_finish(self, client: AsyncClient):
        """未结束的面试取报告 → 409"""
        _, headers = await _register(client, "early")
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]
        resp = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        assert resp.status_code == 409


class TestUpload:
    async def test_upload_audio(self, client: AsyncClient):
        _, headers = await _register(client, "audio")
        resp = await client.post(
            f"{BASE}/uploads/audio",
            files={"file": ("answer.mp3", b"fake-audio-bytes", "audio/mpeg")},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["url"].startswith("/uploads/")

    async def test_upload_bad_extension(self, client: AsyncClient):
        _, headers = await _register(client, "badext")
        resp = await client.post(
            f"{BASE}/uploads/audio",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000


class TestHealth:
    async def test_health(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "healthy"
