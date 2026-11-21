"""Runtime settings for the backend.

Every value has a default that works for local development, and each can be
overridden with an environment variable so teammates do not need to edit code.
Tests build `Settings` directly instead of reading the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from enum import StrEnum

# backend/src/ai_coder/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# The Vite dev server binds to 127.0.0.1:5173 (see frontend/package.json).
# Browsers treat 127.0.0.1 and localhost as different origins, so allow both.
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


class EnvVar(StrEnum):
    """Supported backend environment keys, shared by loading and tests."""
    AI_CODER_WORKSPACES_ROOT = "AI_CODER_WORKSPACES_ROOT"
    AI_CODER_MAX_REPAIRS = "AI_CODER_MAX_REPAIRS"
    AI_CODER_MAX_FEATURES = "AI_CODER_MAX_FEATURES"
    AI_CODER_CORS_ORIGINS = "AI_CODER_CORS_ORIGINS"
    AI_CODER_AGENT_TIMEOUT_SECONDS = "AI_CODER_AGENT_TIMEOUT_SECONDS"
    AI_CODER_PLACEHOLDER_DELAY_SECONDS = "AI_CODER_PLACEHOLDER_DELAY_SECONDS"
    AI_CODER_PLACEHOLDER_TEST_FAILURES = "AI_CODER_PLACEHOLDER_TEST_FAILURES"
    GEMINI_API_KEY = "GEMINI_API_KEY"
    GEMINI_MODEL = "GEMINI_MODEL"
    GEMINI_TIMEOUT_SECONDS = "GEMINI_TIMEOUT_SECONDS"
    CHAT_RECORD_PATH = "CHAT_RECORD_PATH"
    LLM_RECORD_PATH = "LLM_RECORD_PATH"


@dataclass(frozen=True)
class Settings:
    # Root directory for runtime data; see workspaces/README.md for the layout.
    workspaces_root: Path = REPO_ROOT / "workspaces"
    # Repair rounds (Coder -> Tester again after failing tests) allowed per run,
    # shared by all features, to bound LLM calls on the free Gemini tier.
    max_repairs: int = 3
    # Most features the Planner may split the work into; each feature costs a
    # Coder and a Tester pass.
    max_features: int = 4
    # Longest one agent may work on one task before the run fails. Without it,
    # a hung agent (e.g. a stalled network call) would keep its run "running"
    # forever and block later runs of the same workspace.
    agent_timeout_seconds: float = 600.0
    # Browser origins allowed to call the API (the frontend dev server).
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)
    # Placeholder agents (used until stage 4 provides real ones):
    # seconds each placeholder waits, so the UI can show progress step by step;
    placeholder_delay_seconds: float = 1.0
    # how many of the run's first Tester tasks report failing tests, to
    # exercise the repair loop by hand.
    placeholder_test_failures: int = 0
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-flash-latest"
    gemini_timeout_seconds: float = 60.0
    chat_record_path: Path = REPO_ROOT / "backend" / "records" / "chat.jsonl"
    llm_record_path: Path = REPO_ROOT / "backend" / "records" / "llm.jsonl"


def load_settings() -> Settings:
    """Build settings from environment variables, falling back to defaults.

    AI_CODER_WORKSPACES_ROOT             directory for runtime data
    AI_CODER_MAX_REPAIRS                 integer, 0 or more
    AI_CODER_MAX_FEATURES                integer, 1 or more
    AI_CODER_CORS_ORIGINS                comma-separated list of origins
    AI_CODER_AGENT_TIMEOUT_SECONDS       number, more than 0
    AI_CODER_PLACEHOLDER_DELAY_SECONDS   number, 0 or more
    AI_CODER_PLACEHOLDER_TEST_FAILURES   integer, 0 or more
    """
    defaults = Settings()
    env = os.environ.get
    root = env(EnvVar.AI_CODER_WORKSPACES_ROOT)
    origins = env(EnvVar.AI_CODER_CORS_ORIGINS)
    return Settings(
        llm_record_path=Path(env(EnvVar.LLM_RECORD_PATH, str(defaults.llm_record_path))).expanduser().resolve(),
        chat_record_path=Path(env(EnvVar.CHAT_RECORD_PATH, str(defaults.chat_record_path))).expanduser().resolve(),
        gemini_api_key=env(EnvVar.GEMINI_API_KEY, "").strip(),
        gemini_model=env(EnvVar.GEMINI_MODEL, defaults.gemini_model).strip() or defaults.gemini_model,
        gemini_timeout_seconds=_positive_float(EnvVar.GEMINI_TIMEOUT_SECONDS, env(EnvVar.GEMINI_TIMEOUT_SECONDS), defaults.gemini_timeout_seconds),
        workspaces_root=Path(root).resolve() if root else defaults.workspaces_root,
        max_repairs=_non_negative_int(
            EnvVar.AI_CODER_MAX_REPAIRS, env(EnvVar.AI_CODER_MAX_REPAIRS), defaults.max_repairs
        ),
        max_features=_positive_int(
            EnvVar.AI_CODER_MAX_FEATURES, env(EnvVar.AI_CODER_MAX_FEATURES), defaults.max_features
        ),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
        if origins
        else defaults.cors_origins,
        agent_timeout_seconds=_positive_float(
            EnvVar.AI_CODER_AGENT_TIMEOUT_SECONDS,
            env(EnvVar.AI_CODER_AGENT_TIMEOUT_SECONDS),
            defaults.agent_timeout_seconds,
        ),
        placeholder_delay_seconds=_non_negative_float(
            EnvVar.AI_CODER_PLACEHOLDER_DELAY_SECONDS,
            env(EnvVar.AI_CODER_PLACEHOLDER_DELAY_SECONDS),
            defaults.placeholder_delay_seconds,
        ),
        placeholder_test_failures=_non_negative_int(
            EnvVar.AI_CODER_PLACEHOLDER_TEST_FAILURES,
            env(EnvVar.AI_CODER_PLACEHOLDER_TEST_FAILURES),
            defaults.placeholder_test_failures,
        ),
    )


def _non_negative_int(name: str, raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must be 0 or more, got {value}")
    return value


def _positive_int(name: str, raw: str | None, default: int) -> int:
    value = _non_negative_int(name, raw, default)
    if value < 1:
        raise ValueError(f"{name} must be 1 or more, got {value}")
    return value


def _non_negative_float(name: str, raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must be 0 or more, got {value}")
    return value


def _positive_float(name: str, raw: str | None, default: float) -> float:
    value = _non_negative_float(name, raw, default)
    if value <= 0:
        raise ValueError(f"{name} must be more than 0, got {value}")
    return value
