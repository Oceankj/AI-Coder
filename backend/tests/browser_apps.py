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


def preview():
    """Static fixture served by the production preview API and HTTP listener."""
    app = create_app(load_settings())
    workspace = app.state.storage.create_workspace("Preview integration")
    project = app.state.storage.workspace_dir(workspace.id) / "project"
    (project / "index.html").write_text(
        '<link rel="stylesheet" href="style.css"><h1>Preview integration</h1>'
        '<button id="save">Save playlist</button><p id="status"></p>'
        '<script type="module" src="app.js"></script>', encoding="utf-8",
    )
    (project / "style.css").write_text("h1 { color: rgb(12, 34, 56); }", encoding="utf-8")
    (project / "label.js").write_text('export const label = "Saved playlist";', encoding="utf-8")
    (project / "app.js").write_text(
        'import { label } from "./label.js";'
        'const status = document.getElementById("status");'
        'status.textContent = localStorage.getItem("playlist") ?? "Ready";'
        'document.getElementById("save").onclick = () => {'
        'localStorage.setItem("playlist", label); status.textContent = label; };', encoding="utf-8",
    )
    return app
