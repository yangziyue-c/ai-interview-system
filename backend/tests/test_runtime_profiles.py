"""运行版本测试：默认 8005 主版本，显式留空才进入无 8005 备用版本。"""

from app.config import Settings

import start


def _write_env(tmp_path, monkeypatch, content: str) -> None:
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    monkeypatch.setattr(start, "BASE_DIR", tmp_path)


def test_missing_setting_uses_primary_profile(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "DEBUG=true\n")

    assert start.dialogue_engine_mode() == start.PRIMARY_DIALOGUE_ENGINE
    assert start.dialogue_engine_enabled() is True


def test_explicit_blank_switches_to_backup_profile(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "DIALOGUE_ENGINE=\n")

    assert start.dialogue_engine_mode() == start.BACKUP_DIALOGUE_ENGINE
    assert start.dialogue_engine_enabled() is False


def test_a11_selects_primary_profile(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "DIALOGUE_ENGINE=a11\n")

    assert start.dialogue_engine_mode() == start.PRIMARY_DIALOGUE_ENGINE
    assert start.dialogue_engine_enabled() is True


def test_settings_default_to_primary_when_env_is_absent(monkeypatch):
    monkeypatch.delenv("DIALOGUE_ENGINE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.DIALOGUE_ENGINE == "a11"
    assert settings.engine_enabled is True
