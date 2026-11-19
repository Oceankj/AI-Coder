# Backend Core Specification

[Back to README](../README.md) · [Architecture](./architecture.md) ·
[API and MCP responsibilities](./interfaces.md)

This specification covers stage 2 of the relay (backend core): the FastAPI
application, run storage, and the orchestrator. It is also the handoff document
for stage 3 (MCP layer) and stage 4 (agents). Sections marked *Planned* are
filled in as the corresponding implementation step lands.

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
| `cors_origins` | `AI_CODER_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | Browser origins allowed to call the API |
| `placeholder_delay_seconds` | `AI_CODER_PLACEHOLDER_DELAY_SECONDS` | `1.0` | Pause in each placeholder agent so the UI can show progress |
| `placeholder_test_failures` | `AI_CODER_PLACEHOLDER_TEST_FAILURES` | `0` | How many of the run's first placeholder Tester tasks report failing tests, to try the repair loop by hand |

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
| 10 | One pass for the whole app, or one per feature? | One per feature: the Planner splits the work into at most `max_features` (default 4) features, and each goes Coder → Tester before the next starts. See [Run lifecycle](#run-lifecycle). |
| 9 | What is the agent interface? | `execute(context, recorder)`; each agent creates its own MCP client because the MCP server is started per role. |

## Run directory files

All runtime data lives under the workspaces root. **Only
`ai_coder.storage.repository.FileStorage` reads or writes these files**; other
code (including the MCP server) calls its methods instead of opening the files.
That keeps one implementation of every format.

```text
<workspaceId>/
  metadata.json            workspace record
  runs/<runId>/
    run.json               run status and input
    tasks.json             agent tasks and results (the blackboard)
    checks.json            real test executions
    events.jsonl           progress events, one JSON object per line
    usage.json             LLM call and token totals
    project/               generated application and tests
    artifacts/             packaged downloads
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
| `repairCount` | Repair rounds used so far, across all features |
| `input` | The description and requirements the user submitted |

`RunDetail` in the HTTP API is built from this file plus `usage.json`;
`repairCount` and `input` are internal and not returned to the frontend.

### `tasks.json` — handoffs between agents

The orchestrator publishes a task; the agent reads it with MCP `getTask` and
answers with MCP `submitResult`.

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

`getTask` returns the role's latest task. If an agent submits twice, the last
submission wins.

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
`queued`.

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

Agents add `tool_call` events through the `RunRecorder`, one per MCP tool call
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
| `get_current_task(context, role)` | MCP `getTask` | The role's latest task |
| `submit_result(context, role, summary=, artifact_paths=, outcome=, features=)` | MCP `submitResult` | Record the agent's result; `features` is the Planner's list of `{title, description}` |
| `append_check_execution(context, command=, exit_code=, timed_out=, passed=, failed=, log=)` | MCP `runChecks` | Record a real test execution |
| `append_event(context, type, message)` | Agent runtime | Add a progress event |
| `add_usage(context, input_tokens=, output_tokens=, total_tokens=)` | LLM gateway | Add one LLM call to the totals |

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
| `POST /api/workspaces/{workspaceId}/runs` | Body `{"description": string, "requirements": string[]}`. The workspace is checked first (`404`), then the body: a missing, non-string, or blank description, or `requirements` that is not an array of strings, returns `400 INVALID_INPUT`. An empty `requirements` array is allowed. The description is trimmed. Returns `201` with a `RunSummary` whose status is `queued`, **immediately**; the run executes in the background |
| `GET /api/workspaces/{workspaceId}/runs/{runId}` | `RunDetail`: the summary plus `activeRole`, `error`, `checks`, and `usage`. `404` when the run does not exist or belongs to another workspace |

Events, files, and download: *planned (step 5).*

## Orchestrator and agent interface

### Run lifecycle

`POST …/runs` creates the run and hands it to `RunScheduler`
(`orchestration/scheduler.py`), which starts it as a background task and
returns at once. Runs of the same workspace wait for each other; runs of
different workspaces may run concurrently.

`Orchestrator.run` (`orchestration/orchestrator.py`) then executes:

```text
status = running
Planner                          -> plan (summary) + features (1 .. maxFeatures)
for each feature, in order:
    Coder   (plan, feature)       -> adds the feature on top of the existing code
    Tester  (plan, feature)       -> adds tests for it, then runs ALL tests
    checks.tests = outcome of the Tester's newest execution in this attempt
    passed?              -> next feature
    repair budget left?  -> repairCount += 1;
                            Coder (repair, previousFailure = test output),
                            Tester (repair: re-run the unchanged tests), check again
    otherwise            -> status = failed; later features never start
all features passed      -> status = completed
any error                -> status = failed, error = readable reason
always                   -> activeRole = null when the run ends
```

Work is assigned and monitored by this code, not by an LLM: the rules are
fixed, so behavior is predictable, testable, and costs no API calls. Splitting
the work, which needs understanding of the requirements, is the Planner's job.

For each role the orchestrator publishes the task in `tasks.json`, sets
`activeRole`, writes a `role_started` event, calls the agent, and then requires
that the agent submitted a result. The Planner runs once. Finished features are
never rerun. Because the Tester always runs every test, a feature that breaks
an earlier one fails its own checks and is repaired.

The repair budget (`max_repairs`) is shared by the whole run rather than given
to each feature, so a run makes a bounded number of LLM calls (important on the
free Gemini tier). With the defaults, a run has at most 4 features and 3 repairs.

The run fails, with the reason in `error`, when:

| Situation | `error` |
| --- | --- |
| The Planner returns no features, or more than `max_features` | `The Planner must split the work into 1 to 4 features; it returned 0.` |
| A planned feature has a blank title | `The Planner's feature 2 has a blank title.` |
| An agent returns without submitting | `The Coder finished without submitting a result.` |
| An agent raises | `Coder failed: RuntimeError: <message>` |
| The Tester records no check execution in this attempt | `The Tester finished without running the checks.` |
| A feature's tests fail and the repair budget is used up | `Feature 2 of 3 (Smooth transitions) failed its tests and no repair rounds are left (limit 3 per run).` |
| The backend shuts down during the run | `The backend stopped before this run finished.` |
| The backend restarts with the run still queued or running | `The backend restarted before this run finished.` |

Whether tests passed comes **only** from `checks.json`, and only from an
execution recorded during the current attempt. The Tester's own `outcome`
never overrides it, and an older passing execution (from an earlier attempt or
feature) is never reused.

### Agent interface

Every agent implements `ai_coder.agents.base.Agent`:

```python
class Agent(Protocol):
    role: AgentRole

    async def execute(self, context: RunContext, recorder: RunRecorder) -> None:
        ...
```

| Rule | Detail |
| --- | --- |
| Before `execute` | The role's task is in `tasks.json` and `activeRole` is set |
| During `execute` | Read the task (MCP `getTask`), work through MCP tools, finish with MCP `submitResult`. The Planner must submit `features`. The Coder builds only the task's feature, on top of the existing code. The Tester adds tests for the task's feature (on a `repair` task it changes nothing) and must call MCP `runChecks` |
| Finishing | Return normally when done. Returning without a submitted result fails the run |
| Errors | Raise; the run fails and the exception's type and message are shown to the user, so keep messages readable |
| MCP client | Each agent creates its own, because the MCP server is started with the run and role bound |
| Events and usage | Only through `recorder`, never directly to storage |

`RunRecorder` (`orchestration/recorder.py`) is everything an agent may record:

| Method | Purpose |
| --- | --- |
| `recorder.event(type, message)` | Add a progress event. Use `tool_call` for each MCP call, e.g. `Coder -> writeFile(index.html)` |
| `recorder.add_usage(input_tokens=, output_tokens=, total_tokens=)` | Count one LLM API call, retries included. Pass `total_tokens` when the provider reports more than input + output (Gemini thinking tokens) |
| `recorder.context` | The run's `RunContext` |

### Placeholder agents

Until stage 4 the backend runs the placeholder agents in
`agents/placeholder.py`. They follow the handoff rules (read the task, write
files, record a check execution, submit) but write fixed content, use
`FileStorage` directly instead of MCP, and the placeholder Tester **does not run
tests**: it reports failures for the run's first `placeholder_test_failures`
Tester tasks and passes afterwards. Every placeholder event and check log says
"placeholder".

The placeholder Planner always plans two features, so `max_features` must be at
least 2 while placeholders are in use:

| Feature | Placeholder Coder writes | Placeholder Tester writes |
| --- | --- | --- |
| 1. Filter by genre | `package.json`, `index.html`, `playlist.js` (filter) | `genres.test.js` |
| 2. Smooth transitions | `playlist.js` (filter + order by BPM) | `transitions.test.js` |

The placeholder project is nevertheless a valid project: `node --test` passes
in it after the run (covered by a test). Note for the generated application:
the test files import `playlist.js` as an ES module, which Node.js only allows
when the project has a `package.json` with `"type": "module"`, so the
placeholder Coder writes one. Real agents need to do the same. Writing one test
file per feature keeps earlier features' tests in place, so `node --test` keeps
checking them.

### Replacing the placeholders (stage 4)

Pass the real agents to the app factory, one per role:

```python
from ai_coder.main import create_app
app = create_app(agents={
    AgentRole.PLANNER: PlannerAgent(...),
    AgentRole.CODER: CoderAgent(...),
    AgentRole.TESTER: TesterAgent(...),
})
```

The stubs `agents/planner.py`, `coder.py`, and `tester.py` already have the
right signature. The uvicorn command calls `create_app()` without arguments, so
stage 4 also decides how the default switches from placeholders to real agents
(for example a new setting such as `AI_CODER_AGENTS=gemini`).

## File routes and downloads

*Planned (step 5).* Path validation, media types, size limits, and ZIP
contents.
