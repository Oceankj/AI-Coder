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
    # Maximum Coder -> Tester repair rounds after the first attempt fails.
    max_repairs: int = 2
    # Browser origins allowed to call the API (the frontend dev server).
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)


def load_settings() -> Settings:
    """Build settings from environment variables, falling back to defaults.

    AI_CODER_WORKSPACES_ROOT  directory for runtime data
    AI_CODER_MAX_REPAIRS      integer, 0 or more
    AI_CODER_CORS_ORIGINS     comma-separated list of origins
    """
    defaults = Settings()
    root = os.environ.get("AI_CODER_WORKSPACES_ROOT")
    repairs = os.environ.get("AI_CODER_MAX_REPAIRS")
    origins = os.environ.get("AI_CODER_CORS_ORIGINS")
    return Settings(
        workspaces_root=Path(root).resolve() if root else defaults.workspaces_root,
        max_repairs=_non_negative_int("AI_CODER_MAX_REPAIRS", repairs)
        if repairs is not None
        else defaults.max_repairs,
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
        if origins
        else defaults.cors_origins,
    )


def _non_negative_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must be 0 or more, got {value}")
    return value
