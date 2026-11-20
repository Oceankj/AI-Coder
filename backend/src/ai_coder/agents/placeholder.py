"""Placeholder agents: stand-ins until stage 4 provides real Gemini agents.

They let the whole pipeline (API -> orchestrator -> agents -> files -> UI) run
without an LLM or an MCP server. They follow the same rules as real agents:
read their task, write project files, record a check execution (Tester), and
submit a result. They differ in two ways:

- They use `FileStorage` directly instead of MCP tools (the MCP server is
  built in stage 3).
- They write fixed content for two fixed features ("Filter by genre", then
  "Smooth transitions"), and the Tester *does not execute tests*: it records a
  result chosen by `test_failures`. Every event and check log says
  "placeholder" so nobody mistakes this for real generation.

To replace them, pass real agents to `create_app(agents=...)`; see
docs/backend-spec.md, "Agent interface".
"""
from __future__ import annotations

import asyncio

from ai_coder.models import AgentRole, RunContext
from ai_coder.orchestration.recorder import RunRecorder
from ai_coder.storage.repository import FileStorage

PLAN = """Placeholder plan for a Music Playlist Mixer.
Files: index.html (UI), playlist.js (logic), package.json, one *.test.js per feature.
playlist.js exports generatePlaylist(songs, genres, mood)."""

FEATURES = [
    {
        "title": "Filter by genre",
        "description": "generatePlaylist keeps only songs whose genre is in `genres`.",
    },
    {
        "title": "Smooth transitions",
        "description": "generatePlaylist orders songs by BPM so tempo changes gradually.",
    },
]

PACKAGE_JSON = """{
  "name": "playlist-mixer",
  "private": true,
  "type": "module",
  "scripts": { "test": "node --test" }
}
"""

# playlist.js after feature 1 (filter) and after feature 2 (filter + order).
PLAYLIST_JS_FEATURE_1 = """// Placeholder implementation written by the placeholder Coder (feature 1).
export function generatePlaylist(songs, genres, mood) {
  return songs.filter((song) => genres.includes(song.genre));
}
"""

PLAYLIST_JS_FEATURE_2 = """// Placeholder implementation written by the placeholder Coder (features 1-2).
export function generatePlaylist(songs, genres, mood) {
  return songs
    .filter((song) => genres.includes(song.genre))
    .sort((a, b) => a.bpm - b.bpm);
}
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Playlist Mixer (placeholder)</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }
    li { padding: 0.25rem 0; }
  </style>
</head>
<body>
  <h1>Playlist Mixer</h1>
  <p>Placeholder output from the backend's placeholder agents.</p>
  <ol id="playlist"></ol>
  <script>
    // Inline copy of playlist.js so the page works in the preview iframe.
    const songs = [
      { title: "Slow Jazz", genre: "jazz", bpm: 80 },
      { title: "Mid Rock", genre: "rock", bpm: 110 },
      { title: "Fast Rock", genre: "rock", bpm: 140 },
    ];
    const playlist = songs.slice().sort((a, b) => a.bpm - b.bpm);
    document.getElementById("playlist").innerHTML = playlist
      .map((s) => `<li>${s.title} (${s.genre}, ${s.bpm} BPM)</li>`)
      .join("");
  </script>
</body>
</html>
"""

# One test file per feature, so earlier features keep being checked.
GENRES_TEST_JS = """// Placeholder tests written by the placeholder Tester (feature 1).
import { test } from "node:test";
import assert from "node:assert/strict";
import { generatePlaylist } from "./playlist.js";

const songs = [
  { title: "A", genre: "rock", bpm: 140 },
  { title: "B", genre: "jazz", bpm: 80 },
];

test("keeps only the selected genres", () => {
  const playlist = generatePlaylist(songs, ["rock"], "energetic");
  assert.deepEqual(playlist.map((song) => song.title), ["A"]);
});
"""

TRANSITIONS_TEST_JS = """// Placeholder tests written by the placeholder Tester (feature 2).
import { test } from "node:test";
import assert from "node:assert/strict";
import { generatePlaylist } from "./playlist.js";

const songs = [
  { title: "A", genre: "rock", bpm: 140 },
  { title: "B", genre: "jazz", bpm: 80 },
  { title: "C", genre: "rock", bpm: 110 },
];

test("orders songs by BPM for gradual transitions", () => {
  const bpms = generatePlaylist(songs, ["rock", "jazz"], "relaxing").map((s) => s.bpm);
  assert.deepEqual(bpms, [80, 110, 140]);
});
"""

# What each placeholder writes for feature 1 and feature 2.
CODER_FILES = [
    {"package.json": PACKAGE_JSON, "playlist.js": PLAYLIST_JS_FEATURE_1, "index.html": INDEX_HTML},
    {"playlist.js": PLAYLIST_JS_FEATURE_2},
]
TESTER_FILES = [
    {"genres.test.js": GENRES_TEST_JS},
    {"transitions.test.js": TRANSITIONS_TEST_JS},
]


class _PlaceholderAgent:
    role: AgentRole

    def __init__(self, storage: FileStorage, delay_seconds: float) -> None:
        self._storage = storage
        self._delay = delay_seconds

    async def _pause(self) -> None:
        # Gives the UI time to show each step; 0 in tests.
        if self._delay:
            await asyncio.sleep(self._delay)

    def _tool_call(self, recorder: RunRecorder, call: str) -> None:
        name = self.role.value.capitalize()
        recorder.event("tool_call", f"{name} -> {call} (placeholder, no MCP)")

    def _write(self, context: RunContext, name: str, content: str) -> None:
        # Fixed file names only, so no path validation is needed here.
        (self._storage.project_dir(context) / name).write_text(content, encoding="utf-8")


class PlaceholderPlanner(_PlaceholderAgent):
    role = AgentRole.PLANNER

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        self._tool_call(recorder, "getTask")
        await self._pause()
        self._tool_call(recorder, "submitResult")
        self._storage.submit_result(
            context,
            self.role,
            summary=PLAN,
            artifact_paths=[],
            outcome="success",
            features=FEATURES,
        )


class PlaceholderCoder(_PlaceholderAgent):
    role = AgentRole.CODER

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        task = self._storage.get_current_task(context, self.role)
        self._tool_call(recorder, "getTask")
        await self._pause()
        # A repair rewrites the same feature's files, which is idempotent here.
        files = CODER_FILES[task.feature.number - 1]
        for name, content in files.items():
            self._tool_call(recorder, f"writeFile({name})")
            self._write(context, name, content)
        self._tool_call(recorder, "submitResult")
        self._storage.submit_result(
            context,
            self.role,
            summary=f"Wrote placeholder code for: {task.feature.title}.",
            artifact_paths=list(files),
            outcome="success",
        )


class PlaceholderTester(_PlaceholderAgent):
    role = AgentRole.TESTER

    def __init__(
        self, storage: FileStorage, delay_seconds: float, test_failures: int
    ) -> None:
        super().__init__(storage, delay_seconds)
        self._test_failures = test_failures

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        task = self._storage.get_current_task(context, self.role)
        self._tool_call(recorder, "getTask")
        await self._pause()
        test_files = TESTER_FILES[task.feature.number - 1]
        if not task.repair:  # on a re-check the tests stay unchanged
            for name, content in test_files.items():
                self._tool_call(recorder, f"writeFile({name})")
                self._write(context, name, content)

        # The run's first `test_failures` Tester tasks report failing tests.
        fails = task.sequence <= self._test_failures
        self._tool_call(recorder, "runChecks")
        self._storage.append_check_execution(
            context,
            command="placeholder (node --test not run)",
            exit_code=1 if fails else 0,
            timed_out=False,
            passed=1 if fails else 2,
            failed=1 if fails else 0,
            log=(
                "Placeholder Tester: no tests were executed. "
                f"Reporting a {'failing' if fails else 'passing'} result for "
                f"Tester task {task.sequence}."
            ),
        )
        self._tool_call(recorder, "submitResult")
        self._storage.submit_result(
            context,
            self.role,
            summary="Placeholder test result recorded.",
            artifact_paths=list(test_files),
            outcome="failure" if fails else "success",
        )


def placeholder_agents(
    storage: FileStorage, *, delay_seconds: float = 1.0, test_failures: int = 0
) -> dict[AgentRole, _PlaceholderAgent]:
    """One placeholder per role, ready to pass to the orchestrator."""
    return {
        AgentRole.PLANNER: PlaceholderPlanner(storage, delay_seconds),
        AgentRole.CODER: PlaceholderCoder(storage, delay_seconds),
        AgentRole.TESTER: PlaceholderTester(storage, delay_seconds, test_failures),
    }
