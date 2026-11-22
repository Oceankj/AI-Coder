# Author: Ching Kao
# Student ID: 85768427
"""Factories for isolated browser tests. Production always uses ai_coder.main."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

from ai_coder.config import load_settings
from ai_coder.main import create_app
from scripted_gemini import ScriptedGemini


def tdd():
    # Each factory runs in its own disposable uvicorn process.
    patch(
        "google.genai.models.AsyncModels.generate_content", new=AsyncMock(side_effect=ScriptedGemini())
    ).start()
    return create_app(replace(load_settings(), gemini_api_key="integration-fixture", groq_api_key=""))
