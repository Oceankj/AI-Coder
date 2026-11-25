# Author: Ching Kao
# Student ID: 85768427
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
DEFAULT_SETUP_TIMEOUT_SECONDS = 120.0


class Provider(StrEnum):
    GEMINI = "gemini"
    GROQ = "groq"
    CODEX = "codex"


class GroqModel(StrEnum):
    GPT_OSS_120B = "openai/gpt-oss-120b"
    GPT_OSS_20B = "openai/gpt-oss-20b"


class CodexTransport(StrEnum):
    APP_SERVER = "app-server"
    EXEC = "exec"


class EnvVar(StrEnum):
    """Supported backend environment keys, shared by loading and tests."""
    AI_CODER_WORKSPACES_ROOT = "AI_CODER_WORKSPACES_ROOT"
    AI_CODER_MAX_REPAIRS = "AI_CODER_MAX_REPAIRS"
    AI_CODER_MAX_FEATURES = "AI_CODER_MAX_FEATURES"
    AI_CODER_CORS_ORIGINS = "AI_CODER_CORS_ORIGINS"
    AI_CODER_AGENT_TIMEOUT_SECONDS = "AI_CODER_AGENT_TIMEOUT_SECONDS"
    AI_CODER_SETUP_TIMEOUT_SECONDS = "AI_CODER_SETUP_TIMEOUT_SECONDS"
    PROJECT_VERIFIER = "AI_CODER_PROJECT_VERIFIER"
    AI_CODER_GROQ_API_KEY = "AI_CODER_GROQ_API_KEY"
    GROQ_API_KEY = "GROQ_API_KEY"
    GROQ_MODEL = "GROQ_MODEL"
    GROQ_TIMEOUT_SECONDS = "GROQ_TIMEOUT_SECONDS"
    GEMINI_API_KEY = "GEMINI_API_KEY"
    GEMINI_MODEL = "GEMINI_MODEL"
    GEMINI_TIMEOUT_SECONDS = "GEMINI_TIMEOUT_SECONDS"
    CODEX_EXECUTABLE = "AI_CODER_CODEX_EXECUTABLE"
    CODEX_MODEL = "AI_CODER_CODEX_MODEL"
    CODEX_TIMEOUT = "AI_CODER_CODEX_TIMEOUT_SECONDS"
    CODEX_TRANSPORT = "AI_CODER_CODEX_TRANSPORT"
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
    setup_timeout_seconds: float = DEFAULT_SETUP_TIMEOUT_SECONDS
    project_verifier: Path | None = None
    # Browser origins allowed to call the API (the frontend dev server).
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-flash-latest"
    gemini_timeout_seconds: float = 60.0
    chat_record_path: Path = REPO_ROOT / "backend" / "records" / "chat.jsonl"
    llm_record_path: Path = REPO_ROOT / "backend" / "records" / "llm.jsonl"
    groq_api_key: str = field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 60.0
    codex_executable: str = "codex"
    codex_model: str = "gpt-5.6-luna"
    codex_timeout_seconds: float = 150.0
    codex_transport: CodexTransport = CodexTransport.APP_SERVER


def load_settings() -> Settings:
    """Build settings from environment variables, falling back to defaults.

    AI_CODER_WORKSPACES_ROOT             directory for runtime data
    AI_CODER_MAX_REPAIRS                 integer, 0 or more
    AI_CODER_MAX_FEATURES                integer, 1 or more
    AI_CODER_CORS_ORIGINS                comma-separated list of origins
    AI_CODER_AGENT_TIMEOUT_SECONDS       number, more than 0
    AI_CODER_SETUP_TIMEOUT_SECONDS       number, more than 0
    AI_CODER_PROJECT_VERIFIER             optional trusted executable, absolute path
    """
    defaults = Settings()
    env = os.environ.get
    root = env(EnvVar.AI_CODER_WORKSPACES_ROOT)
    origins = env(EnvVar.AI_CODER_CORS_ORIGINS)
    verifier = env(EnvVar.PROJECT_VERIFIER)
    return Settings(
        llm_record_path=Path(env(EnvVar.LLM_RECORD_PATH, str(defaults.llm_record_path))).expanduser().resolve(),
        chat_record_path=Path(env(EnvVar.CHAT_RECORD_PATH, str(defaults.chat_record_path))).expanduser().resolve(),
        groq_api_key=(env(EnvVar.AI_CODER_GROQ_API_KEY) or env(EnvVar.GROQ_API_KEY, "")).strip(),
        groq_model=env(EnvVar.GROQ_MODEL, defaults.groq_model).strip() or defaults.groq_model,
        groq_timeout_seconds=_positive_float(EnvVar.GROQ_TIMEOUT_SECONDS, env(EnvVar.GROQ_TIMEOUT_SECONDS), defaults.groq_timeout_seconds),
        gemini_api_key=env(EnvVar.GEMINI_API_KEY, "").strip(),
        gemini_model=env(EnvVar.GEMINI_MODEL, defaults.gemini_model).strip() or defaults.gemini_model,
        gemini_timeout_seconds=_positive_float(EnvVar.GEMINI_TIMEOUT_SECONDS, env(EnvVar.GEMINI_TIMEOUT_SECONDS), defaults.gemini_timeout_seconds),
        codex_executable=env(EnvVar.CODEX_EXECUTABLE, "").strip() or defaults.codex_executable,
        codex_model=env(EnvVar.CODEX_MODEL, "").strip() or defaults.codex_model,
        codex_timeout_seconds=_positive_float(EnvVar.CODEX_TIMEOUT, env(EnvVar.CODEX_TIMEOUT), defaults.codex_timeout_seconds),
        codex_transport=CodexTransport(env(EnvVar.CODEX_TRANSPORT, defaults.codex_transport)),
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
        project_verifier=Path(verifier) if verifier else None,
        setup_timeout_seconds=_positive_float(
            EnvVar.AI_CODER_SETUP_TIMEOUT_SECONDS,
            env(EnvVar.AI_CODER_SETUP_TIMEOUT_SECONDS),
            defaults.setup_timeout_seconds,
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
