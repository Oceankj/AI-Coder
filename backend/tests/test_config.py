"""Settings from environment variables (ai_coder/config.py)."""
import pytest

from ai_coder.config import EnvVar, Settings, load_settings

@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in EnvVar:
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_environment():
    assert load_settings() == Settings()


def test_defaults():
    settings = Settings()
    assert settings.max_repairs == 3
    assert settings.max_features == 4
    assert settings.agent_timeout_seconds == 600


def test_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CODER_WORKSPACES_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_CODER_MAX_REPAIRS", "1")
    monkeypatch.setenv("AI_CODER_MAX_FEATURES", "2")
    monkeypatch.setenv("AI_CODER_CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("AI_CODER_AGENT_TIMEOUT_SECONDS", "90")
    settings = load_settings()
    assert settings.workspaces_root == tmp_path.resolve()
    assert settings.max_repairs == 1
    assert settings.max_features == 2
    assert settings.cors_origins == ("http://a.test", "http://b.test")
    assert settings.agent_timeout_seconds == 90


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_CODER_MAX_REPAIRS", "-1"),
        ("AI_CODER_MAX_REPAIRS", "two"),
        ("AI_CODER_MAX_FEATURES", "0"),
        ("AI_CODER_AGENT_TIMEOUT_SECONDS", "0"),
        ("AI_CODER_AGENT_TIMEOUT_SECONDS", "-5"),
        ("AI_CODER_AGENT_TIMEOUT_SECONDS", "soon"),
        ("AI_CODER_PLACEHOLDER_DELAY_SECONDS", "-1"),
    ],
)
def test_invalid_values_are_rejected_with_the_variable_name(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_settings()
