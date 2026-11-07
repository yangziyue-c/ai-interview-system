"""离线版：不依赖大模型、RAG、8005 或外部评估服务。"""

import pytest

from app.adapters.ai_evaluator import AIEvaluatorAdapter
from app.adapters.ai_interviewer import AIInterviewerAdapter
from app.adapters.llm import LLMError, chat
from app.config import settings

import start


def test_offline_launcher_precedes_primary_profile(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "OFFLINE_MODE=1\nDIALOGUE_ENGINE=a11\n", encoding="utf-8"
    )
    monkeypatch.setattr(start, "BASE_DIR", tmp_path)
    monkeypatch.delenv("OFFLINE_MODE", raising=False)

    assert start.offline_mode() is True
    assert start.dialogue_engine_mode() == start.OFFLINE_PROFILE
    assert start.dialogue_engine_enabled() is False


def test_offline_mode_overrides_engine_flag(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE_MODE", True)
    monkeypatch.setattr(settings, "DIALOGUE_ENGINE", "a11")

    assert settings.engine_enabled is False


async def test_offline_interviewer_uses_bank_or_mock_only(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE_MODE", True)
    adapter = AIInterviewerAdapter()

    async def no_bank(*_args, **_kwargs):
        return None

    monkeypatch.setattr(adapter, "_generate_via_bank", no_bank)

    question = await adapter.generate_question(
        position="backend",
        round_no=1,
        history=[],
        interview_id=0,
        is_follow_up=False,
    )

    assert question in adapter_module_questions()


def adapter_module_questions() -> set[str]:
    from app.adapters import ai_interviewer

    return set(ai_interviewer.GENERAL_OPENING_QUESTIONS)


async def test_offline_evaluator_returns_local_report(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE_MODE", True)
    adapter = AIEvaluatorAdapter()

    report = await adapter.evaluate(
        "backend",
        [{"round": 1, "question": "测试题", "answer": "这是一段用于离线规则评分的回答。"}],
    )

    assert report["total_score"] >= 0
    assert report["tech_score"] >= 0
    assert report["summary"]


async def test_offline_llm_refuses_before_network(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE_MODE", True)

    with pytest.raises(LLMError, match="离线版"):
        await chat([{"role": "user", "content": "生成示范回答"}])
