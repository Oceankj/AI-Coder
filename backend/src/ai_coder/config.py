"""Runtime settings for the backend.

Every value has a default that works for local development, and each can be
overridden with an environment variable so teammates do not need to edit code.
Tests build `Settings` directly instead of reading the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/src/ai_coder/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# The Vite dev server binds to 127.0.0.1:5173 (see frontend/package.json).
# Browsers treat 127.0.0.1 and localhost as different origins, so allow both.
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


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
    # Browser origins allowed to call the API (the frontend dev server).
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)
    # Placeholder agents (used until stage 4 provides real ones):
    # seconds each placeholder waits, so the UI can show progress step by step;
    placeholder_delay_seconds: float = 1.0
    # how many of the run's first Tester tasks report failing tests, to
    # exercise the repair loop by hand.
    placeholder_test_failures: int = 0


def load_settings() -> Settings:
    """Build settings from environment variables, falling back to defaults.

    AI_CODER_WORKSPACES_ROOT             directory for runtime data
    AI_CODER_MAX_REPAIRS                 integer, 0 or more
    AI_CODER_MAX_FEATURES                integer, 1 or more
    AI_CODER_CORS_ORIGINS                comma-separated list of origins
    AI_CODER_PLACEHOLDER_DELAY_SECONDS   number, 0 or more
    AI_CODER_PLACEHOLDER_TEST_FAILURES   integer, 0 or more
    """
    defaults = Settings()
    env = os.environ.get
    root = env("AI_CODER_WORKSPACES_ROOT")
    origins = env("AI_CODER_CORS_ORIGINS")
    return Settings(
        workspaces_root=Path(root).resolve() if root else defaults.workspaces_root,
        max_repairs=_non_negative_int(
            "AI_CODER_MAX_REPAIRS", env("AI_CODER_MAX_REPAIRS"), defaults.max_repairs
        ),
        max_features=_positive_int(
            "AI_CODER_MAX_FEATURES", env("AI_CODER_MAX_FEATURES"), defaults.max_features
        ),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
        if origins
        else defaults.cors_origins,
        placeholder_delay_seconds=_non_negative_float(
            "AI_CODER_PLACEHOLDER_DELAY_SECONDS",
            env("AI_CODER_PLACEHOLDER_DELAY_SECONDS"),
            defaults.placeholder_delay_seconds,
        ),
        placeholder_test_failures=_non_negative_int(
            "AI_CODER_PLACEHOLDER_TEST_FAILURES",
            env("AI_CODER_PLACEHOLDER_TEST_FAILURES"),
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
