# Author: Ching Kao
# Student ID: 85768427
"""Factories for isolated browser tests. Production always uses ai_coder.main."""

from dataclasses import replace
import json
from unittest.mock import AsyncMock, PropertyMock, patch

from ai_coder.config import load_settings
from ai_coder.main import create_app
from ai_coder.llm.codex import CodexAdapter
from scripted_gemini import ScriptedGemini


def tdd():
    # Each factory runs in its own disposable uvicorn process.
    patch(
        "google.genai.models.AsyncModels.generate_content", new=AsyncMock(side_effect=ScriptedGemini())
    ).start()
    return create_app(replace(load_settings(), gemini_api_key="integration-fixture", groq_api_key=""))


def codex():
    """Real HTTP/gateway/adapter conversion, with local login and model transport stubbed."""
    async def run(self, prompt, schema, tools):
        return self._decision(json.dumps({"content": "Hello from the Codex fixture.", "tool_calls": []}),
                              {"input_tokens": 7, "output_tokens": 3}, tools, 1)

    patch.object(CodexAdapter, "configured", new_callable=PropertyMock, return_value=True).start()
    patch.object(CodexAdapter, "login_configured", new=AsyncMock(return_value=True)).start()
    patch.object(CodexAdapter, "_run", new=run).start()
    return create_app(load_settings())
