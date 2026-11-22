<!-- Author: Ching Kao; Student ID: 85768427 -->
# Backend Core Specification

[Back to README](../README.md) · [Architecture](./architecture.md) ·
[API and MCP responsibilities](./interfaces.md)

This specification covers stage 2 of the relay (backend core): the FastAPI
application, run storage, and the orchestrator. It is also the handoff document
for stage 3 (MCP layer) and stage 4 (agents).

The HTTP wire contract itself is defined in [interfaces.md](./interfaces.md);
this document records how the backend implements it and the decisions that the
contract leaves open.

## Running the backend

From the `backend/` directory, with Python 3.11 or later:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000
```

Run the tests:

```bash
.venv/bin/python -m pytest
```

Run the browser checks (real frontend against the real backend in Chrome; see
[backend/e2e/README.md](../backend/e2e/README.md)):

```bash
e2e/run.sh
```

`GET /api/health` returns `{"status": "ok"}` and can be used to confirm that
the frontend or a teammate can reach the backend. It is not part of the
frontend contract.

## Settings

Settings live in `ai_coder/config.py`. Each one can be overridden with an
environment variable.

| Setting | Variable | Default | Purpose |
| --- | --- | --- | --- |
| `workspaces_root` | `AI_CODER_WORKSPACES_ROOT` | `<repo>/workspaces` | Root directory for runtime data |
| `max_repairs` | `AI_CODER_MAX_REPAIRS` | `3` | Repair rounds allowed per run, **shared by all features** |
| `max_features` | `AI_CODER_MAX_FEATURES` | `4` | Most features the Planner may split the work into (1 or more) |
| `agent_timeout_seconds` | `AI_CODER_AGENT_TIMEOUT_SECONDS` | `600` | Longest one agent may work on one task; more than 0 |
| `cors_origins` | `AI_CODER_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | Browser origins allowed to call the API |

## Error responses

Every error, including errors produced by FastAPI itself, uses the shape from
`interfaces.md`:

```json
{"error": {"code": "NOT_FOUND", "message": "Workspace, run, or file not found."}}
```

| Code | Status | When |
| --- | --- | --- |
| `INVALID_INPUT` | 400 | Malformed or invalid body or query parameter (FastAPI's 422 is mapped to 400) |
| `INVALID_CURSOR` | 400 | Events `after` is not a nonnegative integer |
| `INVALID_PATH` | 400 | File path is not a valid project-relative path |
| `NOT_FOUND` | 404 | Workspace, run, file, or route does not exist; also a run that belongs to another workspace |
| `METHOD_NOT_ALLOWED` | 405 | Route exists but not for this HTTP method |
| `NOT_READY` | 409 | Download requested for a run that is not `completed` |
| `FILE_TOO_LARGE` | 413 | File preview larger than 2 MiB |
| `UNSUPPORTED_FILE` | 415 | File is not valid UTF-8 text |
| `INTERNAL_ERROR` | 500 | Unexpected server error; the cause is logged, never returned |

All missing resources share one message so callers cannot probe which IDs exist
in other workspaces. Route code raises `ai_coder.api.errors.ApiError`; it never
builds error bodies itself.

## CORS

The frontend dev server runs on `http://127.0.0.1:5173` and has no proxy, so the
browser calls the backend cross-origin. To use the real backend, create
`frontend/.env.local` with:

```dotenv
VITE_ENABLE_MSW=false
VITE_API_BASE_URL=http://localhost:8000/api
```

The backend allows `GET` and `POST` from the configured origins and exposes the
`Content-Disposition` header so the frontend can read the download file name.

## Decisions not covered by interfaces.md

| # | Question | Decision |
| --- | --- | --- |
| 1 | How does the frontend reach the backend? | CORS for both `127.0.0.1:5173` and `localhost:5173` (different origins to a browser). |
| 2 | What is `checks.build`? | The generated app has no build step, so `build` is always `not_run`; only `tests` changes. |
| 3 | How does the orchestrator know tests really passed? | `runChecks` records each execution in `checks.json`; the orchestrator reads that file, never the agent's own summary. |
| 4 | Can a failed run be downloaded? | No. Only `completed` runs can be downloaded; others return 409, matching the MSW handlers. |
| 5 | What if a file is not UTF-8? | `415 UNSUPPORTED_FILE`. Generated projects contain only text files in practice. |
| 6 | What happens to runs interrupted by a backend restart? | On startup, `queued` and `running` runs become `failed` with an explanatory error. |
| 7 | Where does path validation live? | A basic version in `workspaces/service.py`, shared by the HTTP file route and the MCP file tools; stage 3 extends it with role permissions. |
| 8 | How many repair rounds? | A budget shared by the whole run, default 3 (`max_repairs`). |
| 9 | What is the agent interface? | `execute(context, recorder)`; each agent creates its own MCP client because the MCP server is started per role. |
| 10 | One pass for the whole app, or one per feature? | One per feature: the Planner splits the work into at most `max_features` (default 4) features, and each goes Coder → Tester before the next starts. See [Run lifecycle](#run-lifecycle). |
| 11 | Should an LLM agent assign and monitor the work? | No. Splitting the work needs judgement and is the Planner's job; assigning and monitoring follow fixed rules, so the orchestrator is ordinary code: predictable, testable, and free of API calls. |
| 12 | What if an agent hangs? | Each agent call has a time limit (`agent_timeout_seconds`, default 10 minutes). The agent is cancelled and the run fails, releasing the workspace for queued runs. |

## Run directory files

All runtime data lives under the workspaces root. **Only
`ai_coder.storage.repository.FileStorage` reads or writes these files**; other
code (including the MCP server) calls its methods instead of opening the files.
That keeps one implementation of every format.

```text
<workspaceId>/
  metadata.json            workspace record
  project/                 current application and tests
  runs/<runId>/
    run.json               run status and input
    tasks.json             agent tasks and results (the blackboard)
    checks.json            real test executions
    events.jsonl           progress events, one JSON object per line
    usage.json             LLM call and token totals
    artifacts/<runId>.zip  packaged download: the project plus RUNNING.md
```

### Conventions

- JSON keys are camelCase; the Python models in `ai_coder/models.py` use
  snake_case attributes and convert automatically.
- Timestamps are ISO 8601 UTC with milliseconds, e.g. `2026-11-18T08:00:01.000Z`.
- IDs are server-generated UUIDs. Any ID that is not 1–64 letters, digits, or
  hyphens is treated as not found, so an ID can never contain path syntax.
- JSON files are replaced atomically (temporary file, then rename), so a reader
  in another process never sees a half-written file.
- Within the backend process, changes to one run are serialized with a lock.
  Across processes no lock is used: agents run one at a time, and the backend
  does not write `tasks.json` or `checks.json` while an agent is running.

### `metadata.json`

```json
{"id": "6f1c…", "name": "Demo", "createdAt": "2026-11-18T08:00:01.000Z"}
```

### `run.json`

```json
{
  "id": "a2b3…",
  "workspaceId": "6f1c…",
  "status": "running",
  "createdAt": "2026-11-18T08:00:02.000Z",
  "activeRole": "coder",
  "error": null,
  "checks": {"build": "not_run", "tests": "not_run"},
  "repairCount": 0,
  "provider": "groq",
  "input": {"description": "Music Playlist Mixer", "requirements": ["…"]}
}
```

| Field | Meaning |
| --- | --- |
| `status` | `queued` → `running` → `completed` or `failed` |
| `activeRole` | Agent currently working (`planner`, `coder`, `tester`), or `null` |
| `error` | Human-readable reason when `status` is `failed`, else `null` |
| `checks.build` | Always `not_run`: the generated app has no build step |
| `checks.tests` | Result of the latest real test execution |
| `provider` | Provider selected at creation. Resumed runs use the same provider. Older records default to Gemini. |
| `repairCount` | Repair rounds used so far, across all features |
| `input` | The description and requirements the user submitted |

`RunDetail` in the HTTP API is built from this file plus `usage.json`;
`provider`, `repairCount` and `input` are internal and not returned to the frontend.

### `tasks.json` — handoffs between agents

The orchestrator publishes tasks and records agent results directly in storage.
Agent prompts receive their task context from LangGraph state.

```json
{
  "tasks": [
    {
      "id": "coder-3",
      "role": "coder",
      "sequence": 3,
      "status": "submitted",
      "instructions": "The tests failed after this feature was added …",
      "description": "Music Playlist Mixer",
      "requirements": ["…"],
      "plan": "Files: index.html, playlist.js …",
      "feature": {
        "number": 2,
        "total": 3,
        "title": "Smooth transitions",
        "description": "Order songs so adjacent BPMs differ by at most 15."
      },
      "repair": true,
      "previousFailure": "2 passed, 1 failed.\nnot ok 3 - adjacent songs differ by at most 15 BPM …",
      "createdAt": "2026-11-18T08:01:00.000Z",
      "result": {
        "summary": "Fixed the BPM ordering.",
        "artifactPaths": ["playlist.js"],
        "outcome": "success",
        "features": [],
        "submittedAt": "2026-11-18T08:01:30.000Z"
      }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | `<role>-<sequence>` |
| `sequence` | This role's n-th task in the run (1, 2, 3 …), across all features and repairs |
| `status` | `pending` until the agent submits, then `submitted` |
| `description`, `requirements` | Copied from the run input, so the task is self-contained |
| `plan` | The Planner's plan (`result.summary` of the Planner's task); `null` for the Planner |
| `feature` | The feature this Coder or Tester task is about: its position (`number` of `total`), `title`, and `description`; `null` for the Planner |
| `repair` | `true` when the Coder must fix a feature whose tests failed, or the Tester must re-run the unchanged tests |
| `previousFailure` | Test output from the failed attempt; set only on Coder repair tasks |
| `result.summary` | The agent's report; for the Planner, the full plan |
| `result.features` | **Planner only**: the ordered list of features (`title`, `description`) to build one at a time; empty for other roles |
| `result.outcome` | The agent's own claim (`success` or `failure`). **Never used to decide whether tests passed** |

The orchestrator reads the latest task for each role and records its result.

### `checks.json` — real test executions

Written by MCP `runChecks` after running `node --test`. The orchestrator
decides whether tests passed from this file only.

```json
{
  "executions": [
    {
      "id": 1,
      "command": "node --test",
      "startedAt": "2026-11-18T08:01:40.000Z",
      "finishedAt": "2026-11-18T08:01:41.000Z",
      "exitCode": 1,
      "timedOut": false,
      "passed": 4,
      "failed": 1,
      "outcome": "failed",
      "log": "… not ok 5 - export includes every song …"
    }
  ]
}
```

`outcome` is computed by storage, not supplied by the caller: `passed` only if
`exitCode` is 0, `timedOut` is false, and `failed` is 0. `exitCode` is `null`
when the timeout killed the process. `log` keeps the last 20,000 characters,
where test runners print their summary.

### `events.jsonl`

One `RunEvent` per line, IDs starting at 1. The first event of every run is
`queued`. Agent events include a structured `role` (`planner`, `tester`,
`coder`, or `coordinator`). System events such as runner checks omit it, as do
older events written before this field was added.

```json
{"id": 1, "type": "queued", "message": "Run queued.", "createdAt": "2026-11-18T08:00:02.000Z"}
```

Event types written by the backend core:

| Type | Written when | Example message |
| --- | --- | --- |
| `queued` | The run is created | `Run queued.` |
| `running` | The orchestrator starts the run | `Run started.` |
| `role_started` | An agent starts | `Coder started.` |
| `role_finished` | An agent submitted its result | `Coder finished: Wrote playlist.js` |
| `feature_started` | A feature starts | `Feature 2/3 started: Smooth transitions` |
| `checks` | The Tester's check execution was read | `Feature 2/3 tests failed: 2 passed, 1 failed.` |
| `repair` | A repair round starts | `Feature 2/3 tests failed; starting repair 1 of 3.` |
| `feature_completed` | A feature's tests passed | `Feature 2/3 completed: Smooth transitions` |
| `completed` | Every feature passed | `Run completed.` |
| `failed` | The run failed for any reason | The same text as the run's `error` |

Agents add `tool_call` events through `FileStorage.append_event`, one per MCP tool call
(e.g. `Coder -> writeFile(index.html)`), so the UI shows the MCP traffic.

### `usage.json`

```json
{"apiCalls": 3, "inputTokens": 1200, "outputTokens": 300, "totalTokens": 1650}
```

Each LLM call adds to these totals, retries included. `totalTokens` defaults to
input + output but can be larger when the provider reports extra tokens, such
as Gemini thinking tokens.

### `FileStorage` methods for other stages

| Method | Used by | Purpose |
| --- | --- | --- |
| `project_dir(context)` | MCP file tools | Root that every project-relative path resolves against |
| `get_current_task(context, role)` | LangGraph orchestration | The role's latest task |
| `submit_result(context, role, summary=, artifact_paths=, outcome=, features=)` | LangGraph orchestration | Record the agent's result; `features` is the Planner's list of `{title, description}` |
| `append_check_execution(context, command=, exit_code=, timed_out=, passed=, failed=, log=)` | MCP `runChecks` | Record a real test execution |
| `append_event(context, type, message, role=)` | Orchestration and agent runtime | Add a progress event with optional agent role |
| `add_usage(context, input_tokens=, output_tokens=, total_tokens=)` | `GatewayModel` | Add one LLM call to the run totals |
| `list_project_files(context)` | MCP `listFiles` | Regular files in the project (path, size in bytes), sorted; symlinks skipped |

Path checks are not in `FileStorage`; see [Project paths](#project-paths).

The MCP server runs as a separate process but uses the same code: it creates
its own `FileStorage` pointing at the same workspaces root.

## HTTP routes

Routes live in `ai_coder/api/routes.py` and only validate input, call
`FileStorage`, and convert records to the response schemas in
`ai_coder/api/schemas.py`. Their behavior matches the frontend's MSW handlers
(`frontend/src/mocks/handlers.ts`), so the frontend works against either one
without code changes.

Request bodies are parsed by hand rather than declared as FastAPI parameters,
so checks run in the contract's order (404 for a missing workspace before 400
for a bad body) and every failure uses the error format above.

### Workspaces

| Route | Behavior |
| --- | --- |
| `GET /api/workspaces` | `WorkspaceSummary[]` (`{id, name}`), oldest first |
| `POST /api/workspaces` | Body `{"name": string}`. The name is trimmed; a missing, non-string, or blank name, a non-JSON body, or a body that is not an object returns `400 INVALID_INPUT`. Returns `201` with `{id, name}` |
| `GET /api/workspaces/{workspaceId}` | `WorkspaceDetail` (`{id, name, rootPath, createdAt}`); unknown or unsafe IDs return `404 NOT_FOUND` |

`rootPath` is `workspaces/<id>` (repository-relative, as in MSW) when the
workspaces root is inside the repository, which is the default. If
`AI_CODER_WORKSPACES_ROOT` points outside the repository, it is the absolute
path.

### Runs

| Route | Behavior |
| --- | --- |
| `GET /api/workspaces/{workspaceId}/runs` | `RunSummary[]` (`{id, workspaceId, status, createdAt}`), newest first; `404` for an unknown workspace |
| `GET /api/workspaces/{workspaceId}/runs/{runId}` | `RunDetail`: the summary plus `activeRole`, `error`, `checks`, and `usage`. `404` when the run does not exist or belongs to another workspace |

### Events, files, and download

| Route | Behavior |
| --- | --- |
| `GET …/runs/{runId}/events?after=N` | `{events, nextCursor}`: events with `id > after`, oldest first. `nextCursor` is the last returned ID, or `after` when nothing is newer. A missing or empty `after` is `0` (as in MSW). Anything other than digits, or a value above JavaScript's safe integer (2^53 − 1), returns `400 INVALID_CURSOR`. The run is checked first (`404`) |
| `GET /api/workspaces/{workspaceId}/files` | `ArtifactFile[]` (`{path, size, mediaType}`) for every regular file in the current project, sorted by path, including subdirectories. `size` is bytes. Symlinks are skipped |
| `GET /api/workspaces/{workspaceId}/file?path=…` | `FileContent` (`ArtifactFile` plus `content` and `encoding: "utf-8"`). The workspace is checked first (`404`), then the path (see below) |
| `GET …/runs/{runId}/download` | ZIP bytes, `Content-Type: application/zip`, `Content-Disposition: attachment; filename="<runId>.zip"`. Only `completed` runs; others return `409 NOT_READY` |

File preview errors, in the order they are checked:

| Situation | Status |
| --- | --- |
| Workspace missing | `404 NOT_FOUND` |
| `path` missing, or invalid syntax | `400 INVALID_PATH` |
| `path` is a symlink (or under a symlinked directory) that points outside the project | `400 INVALID_PATH` |
| No such file, or the path is a directory | `404 NOT_FOUND` |
| Larger than 2 MiB (2,097,152 bytes; exactly 2 MiB is allowed) | `413 FILE_TOO_LARGE` |
| Not valid UTF-8 | `415 UNSUPPORTED_FILE` |

`mediaType` comes from the extension: `.html`/`.htm` → `text/html`, `.css` →
`text/css`, `.js`/`.mjs` → `text/javascript`, `.json` → `application/json`,
`.md` → `text/markdown`, anything else → `text/plain`. (MSW maps `.js` to
`text/plain`; the frontend chooses syntax highlighting from the file name, so
the difference has no visible effect.)

## Generation workflow

See the [Coordinator and feature TDD workflow](coordinator-tdd.md) for agent handoffs, test execution and repair limits.

## Project paths

Every file path from outside (a browser request or an agent's MCP tool call) is
relative to the workspace's `project/` directory and must pass the checks in
`ai_coder/workspaces/service.py`. The HTTP file route uses them now; **the MCP
file tools (stage 3) must use the same functions** and add role permissions on
top (the Tester may only read and write `*.test.js` files).

| Function | Checks | Raises |
| --- | --- | --- |
| `validate_relative_path(path)` | Syntax: not empty; no leading `/`; no drive prefix (`C:`); no `\`; no NUL byte; no empty, `.` or `..` segment | `InvalidPathError` |
| `resolve_project_path(project_root, path)` | The syntax above, then follows symlinks and requires the real location to be inside the project. The file does not need to exist, so writers can use it too | `InvalidPathError` |

Valid: `index.html`, `src/playlist.js`, `.gitignore`. Invalid: `/etc/passwd`,
`../secret`, `a/../b`, `./a`, `a//b`, `a/`, `a\b`, `C:x`. A symlink inside the
project that points to another file inside the project is allowed.

## Download package

When every feature has passed, the orchestrator writes
`artifacts/<runId>.zip` **before** marking the run completed, so a completed
run has a fixed download. If the ZIP is missing, the download route returns
`404 NOT_FOUND`; it does not package a later version of the current project.

The ZIP contains the project files present when that run completed, at their
project paths, plus
`RUNNING.md` with instructions (open `index.html`, or serve the folder with
`python3 -m http.server` if the browser blocks module scripts from disk; run
`node --test`). If the project already has a `RUNNING.md`, the project's file is
kept.
