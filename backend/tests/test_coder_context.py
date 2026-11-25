"""The implement step includes bounded files before asking the model to act."""

import asyncio
from unittest.mock import AsyncMock

from ai_coder.config import Settings
from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.tdd import TDDRun
from ai_coder.storage.repository import FileStorage


def test_coder_supplies_relevant_files_and_keeps_hidden_or_external_text_out(tmp_path):
    settings = Settings(workspaces_root=tmp_path / "workspaces")
    storage = FileStorage(settings.workspaces_root)
    workspace = storage.create_workspace("Context test")
    run = storage.create_run(workspace.id, "Build local playlist", [])
    context = RunContext(workspace.id, run.id)
    project = storage.project_dir(context)
    files = {
        "package.json": '{"type":"module"}',
        "index.html": "<main></main>",
        "playlist.js": "export const playlist = [];",
        "playlist.test.js": "import './playlist.js';",
        ".env": "TEST_SECRET=sentinel",
        "long.js": "x" * 15_000,
    }
    for path, content in files.items():
        (project / path).write_text(content)
    outside = tmp_path / "outside.js"
    outside.write_text("outside sentinel")
    (project / "external.js").symlink_to(outside)
    workflow = TDDRun(storage, None, settings, context)
    workflow.run_agent = AsyncMock()

    asyncio.run(workflow.code({
        "index": 0, "features": [{"title": "Playlist", "criteria": ["Return local tracks"]}],
        "spec": "Test", "execution": {"log": "playlist.test.js: expected an array"},
    }))

    role, prompt, payload = workflow.run_agent.await_args.args
    assert role is AgentRole.CODER
    assert "Read or list only missing context" in prompt
    assert payload["execution"]["log"].startswith("playlist.test.js")
    prefetched = payload["workspaceContext"]
    assert prefetched["paths"][0] == "playlist.test.js"
    assert prefetched["files"] == {name: files[name] for name in files if name not in {".env", "long.js"}}
    assert "external.js" not in prefetched["paths"]
