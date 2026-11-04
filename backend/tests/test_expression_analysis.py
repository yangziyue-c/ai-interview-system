"""表达与表现分析：聚合口径单测 + 报告接口与体态落库的集成测试"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.expression_analysis import build_expression_analysis
from app.models import QARecord

BASE = "/api/v1"


def _qa(round_no: int, speech: dict | None = None, body: dict | None = None) -> QARecord:
    """构造未入库的问答记录：聚合函数只读属性，不需要数据库"""
    return QARecord(round=round_no, question="题", answer="答", speech=speech, body_language=body)


class TestAggregation:
    def test_voice_weighted_by_duration(self):
        result = build_expression_analysis(
            [
                _qa(
                    1,
                    speech={
                        "chars_per_min": 200,
                        "duration_ms": 60000,
                        "pauses": 2,
                        "pause_total_ms": 1500,
                        "pause_rate_per_min": 2,
                        "fillers": 1,
                        "filler_rate": 0.02,
                        "loudness_cv": 0.2,
                    },
                ),
                _qa(
                    2,
                    speech={
                        "chars_per_min": 240,
                        "duration_ms": 30000,
                        "pauses": 1,
                        "pause_total_ms": 500,
                        "pause_rate_per_min": 2,
                        "fillers": 0,
                        "filler_rate": 0.0,
                        "loudness_cv": 0.3,
                    },
                ),
            ]
        )
        voice = result["voice"]
        assert result["available"] is True
        # (200*60000 + 240*30000) / 90000 = 213.3
        assert voice["avg_chars_per_min"] == 213.3
        assert voice["total_pauses"] == 3
        assert voice["total_pause_ms"] == 2000
        assert voice["total_fillers"] == 1
        assert voice["round_count"] == 2
        assert any("语速适中" in line for line in voice["feedback"])

    def test_empty_is_not_zero(self):
        result = build_expression_analysis([_qa(1), _qa(2, speech={})])
        assert result["available"] is False
        assert result["voice"]["available"] is False
        assert result["voice"]["avg_chars_per_min"] is None
        assert result["body"]["available"] is False
        assert "没有语音或体态数据" in result["notice"]

    def test_simulated_speech_ignored(self):
        """P3 的按字数模拟值不能混进真实读数"""
        result = build_expression_analysis(
            [_qa(1, speech={"simulated": True, "chars_per_min": 120, "pauses": 5})]
        )
        assert result["voice"]["available"] is False
        assert result["voice"]["total_pauses"] == 0

    def test_body_aggregation(self):
        result = build_expression_analysis(
            [
                _qa(1, body={"available": True, "score": 4.2, "confidence": "high", "feedback": ["保持得不错"]}),
                _qa(2, body={"available": True, "score": 3.8, "confidence": "low", "feedback": ["注意肩线"]}),
                _qa(3, body={"available": False, "score": None, "confidence": "low", "feedback": []}),
            ]
        )
        body = result["body"]
        assert body["available"] is True
        assert body["round_count"] == 2
        assert body["avg_score"] == 4.0
        # 置信度取最保守的一档
        assert body["confidence"] == "low"
        assert body["feedback"] == ["保持得不错", "注意肩线"]
        assert "稳定" in body["summary"]

    def test_voice_only_has_no_notice(self):
        result = build_expression_analysis([_qa(1, speech={"chars_per_min": 210})])
        assert result["voice"]["available"] is True
        assert result["body"]["available"] is False
        assert result["notice"] is None

    def test_body_only_explains_missing_voice(self):
        result = build_expression_analysis(
            [_qa(1, body={"available": True, "score": 4.0, "confidence": "high", "feedback": []})]
        )
        assert result["voice"]["available"] is False
        assert result["body"]["available"] is True
        assert result["notice"] == "本场没有语音数据，表达分析仅包含体态部分。"


class TestJudgeBand:
    """引擎链路逐题判档：取最后一轮，原链路 / 没判出来都是 None"""

    def test_last_turn_wins(self):
        qa = QARecord(
            round=1,
            engine_turns=[{"judge_band": "L3"}, {"judge_band": "degrade"}],
        )
        assert qa.judge_band == "degrade"
        assert qa.needs_improvement is True

    def test_hit_band_is_not_improvement(self):
        qa = QARecord(round=1, engine_turns=[{"judge_band": "L1"}])
        assert qa.judge_band == "L1"
        assert qa.needs_improvement is False

    def test_unknown_is_none_not_false(self):
        assert QARecord(round=1).judge_band is None
        assert QARecord(round=1).needs_improvement is None
        # 最后一轮没判出来（judge_band=None）同样是「不知道」
        qa = QARecord(round=1, engine_turns=[{"judge_band": None}])
        assert qa.needs_improvement is None


async def _register(client: AsyncClient) -> dict:
    resp = await client.post(
        f"{BASE}/auth/register",
        json={
            "username": f"expr_{uuid.uuid4().hex[:8]}",
            "password": "pass123456",
            "nickname": "表达分析测试",
            "target_position": "backend",
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


_SPEECH = {
    "chars_per_min": 220,
    "duration_ms": 30000,
    "pauses": 2,
    "pause_total_ms": 1200,
    "pause_rate_per_min": 4,
    "fillers": 1,
    "filler_rate": 0.01,
    "loudness_cv": 0.2,
}


class TestReportIntegration:
    async def test_report_includes_voice_analysis(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]

        await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "先讲结论，再分点说明依据。", "speech": _SPEECH},
            headers=headers,
        )
        finish = await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)
        assert finish.status_code == 200, finish.text

        report = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        assert report.status_code == 200, report.text
        data = report.json()["data"]
        analysis = data["expression_analysis"]
        assert analysis is not None
        assert analysis["available"] is True
        assert analysis["voice"]["avg_chars_per_min"] == 220.0
        assert analysis["voice"]["total_pauses"] == 2
        # 原链路没有单题分：逐题摘要存在，但「是否待提升」必须是 None（不是 False）
        assert data["qa_review"]
        assert data["qa_review"][0]["needs_improvement"] is None

    async def test_body_language_stored_and_reported(self, client: AsyncClient, monkeypatch):
        headers = await _register(client)
        resp = await client.post(f"{BASE}/interviews", json={"position": "backend"}, headers=headers)
        interview_id = resp.json()["data"]["interview"]["id"]

        class _FakeAdapter:
            async def analyze_body_language(self, frames):
                return {
                    "available": True,
                    "score": 4.5,
                    "confidence": "high",
                    "feedback": ["保持得不错"],
                    "metrics": {},
                    "notes": [],
                }

        monkeypatch.setattr(
            "app.api.body_language.get_dialogue_adapter", lambda: _FakeAdapter()
        )
        analyzed = await client.post(
            f"{BASE}/body-language/analyze",
            json={
                "frames": [{"timestamp_ms": 0, "landmarks": []}],
                "interview_id": interview_id,
                "round": 1,
            },
            headers=headers,
        )
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["data"]["stored"] is True

        await client.post(
            f"{BASE}/interviews/{interview_id}/answers",
            json={"answer": "文字作答。"},
            headers=headers,
        )
        finish = await client.post(f"{BASE}/interviews/{interview_id}/finish", headers=headers)
        assert finish.status_code == 200, finish.text

        report = await client.get(f"{BASE}/reports/{interview_id}", headers=headers)
        body = report.json()["data"]["expression_analysis"]["body"]
        assert body["available"] is True
        assert body["avg_score"] == 4.5
        assert body["feedback"] == ["保持得不错"]

    async def test_body_language_requires_both_params(self, client: AsyncClient):
        headers = await _register(client)
        resp = await client.post(
            f"{BASE}/body-language/analyze",
            json={"frames": [{"timestamp_ms": 0, "landmarks": []}], "interview_id": 1},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "同时提供" in resp.json()["message"]
