<!-- Author: Ching Kao; Student ID: 85768427 -->
# API and MCP Responsibilities

[Back to README](../README.md) · [Architecture](./architecture.md)

This is the interface inventory for AI Coder. The frontend implements the HTTP
client and development-only MSW handlers for the routes below, and the backend
(`backend/src/ai_coder/api/`) implements all of them; see
[Backend implementation notes](#backend-implementation-notes). The MCP server,
tools, and client are implemented in `backend/src/ai_coder/mcp/`; see
[Agent MCP tools](#agent-mcp-tools). The wire contract below is the frontend
integration contract. The HTTP API belongs
to the generation system, not the generated application.

## Boundary overview

| Boundary | Caller | Responsibility |
| --- | --- | --- |
| HTTP API | Frontend | Create/select workspaces, submit requirements, retrieve progress and generated outputs |
| MCP tools | Planner, Coder, Tester via MCP clients | Exchange tasks/results, inspect/edit files, and execute build/test checks |
| Internal services | Backend and agent runtime | Schedule agents, call LLMs, account for usage, persist state, manage workspaces, and package outputs |

MCP exposes tools. In this design, agent-to-agent collaboration is indirect:
one agent submits a result and the next agent retrieves it through the task
store. The orchestrator chooses when each agent runs. The frontend uses HTTP;
it does not need an MCP client.

## Frontend HTTP API

Proposed routes use `/api/workspaces/{workspaceId}`. Run routes additionally
include `/runs/{runId}`. Those IDs are checked against the caller's scope.

| Method and route | UI action | Backend responsibility / result |
| --- | --- | --- |
| `POST /api/workspaces` | Create a project workspace | Allocate an ID, metadata, and root directory; return workspace summary |
| `GET /api/workspaces` | Populate workspace selector | Return available workspace summaries |
| `GET /api/workspaces/{workspaceId}` | Open a workspace | Return workspace metadata after access validation |
| `GET /api/workspaces/{workspaceId}/runs` | View generation history | Return run summaries for this workspace |
| `GET /api/workspaces/{workspaceId}/runs/{runId}` | View a generation result | Return status, active role, failure information, latest build/test summary, and usage totals |
| `GET /api/workspaces/{workspaceId}/runs/{runId}/events` | Show progress and execution logs | Return ordered events; initially polling with an after-event cursor is sufficient |
| `GET /api/workspaces/{workspaceId}/runs/{runId}/files` | Browse generated code and tests | Return project-relative paths and file metadata |
| `GET /api/workspaces/{workspaceId}/runs/{runId}/file?path=…` | Preview a generated file | Return bounded text content within the run's project root |
| `GET /api/workspaces/{workspaceId}/runs/{runId}/download` | Download the result | Return the packaged code, tests, and run instructions when available |

The selected workspace lives in frontend state; selecting it does not require a
"switch workspace" backend operation. Subsequent requests carry its ID.

The run response reports LLM API call count, input/output tokens when available,
and total tokens. Build/test summaries come from actual execution. Statuses
must distinguish queued/running/blocked/completed/failed, and the frontend must not
interpret "files generated" as "tests passed". The JSON schemas are defined below
and mirrored in `frontend/src/types/index.ts`.

File preview is read-only. The frontend Canvas now supports user-provided iframe
URLs and a bundled UI demo without a backend preview endpoint. Starting and
isolating preview servers still requires a separate backend interface decision.
UI editing, workspace deletion, cancellation, and manual reruns of individual
checks remain outside this initial inventory.

## Text chat

Gemini configuration and general conversation are available before workspace selection. A workspace-scoped conversation can start, query or resume a development run. History remains
in the browser tab (separate conversations per workspace, or General chat before
workspace selection). The backend receives the history on each send and does
not persist it. These routes have the same error envelope as the workspace API.

| Method and route | Request | Result |
| --- | --- | --- |
| `GET /api/chat/config` | None | `{configured: boolean, model: string}`; never includes the key |
| `POST /api/chat/config` | `{apiKey: string}` | Same config shape; replaces this single-user app's in-memory key until restart |
| `POST /api/chat` | `{workspaceId?: string, runId?: string, messages: [{role: "user" or "assistant", content: string}]}` | `{message: {role: "assistant", content: string}, model: string, runId?: string, status?: string, usage: {apiCalls: number, inputTokens: number or null, outputTokens: number or null, totalTokens: number or null}}` |

Messages alternate user/assistant, start and end with user, and contain at most
51 entries, 20,000 characters per entry and 100,000 characters total. The UI
sends at most the last 25 completed turns plus the new message. Unknown fields,
empty content, invalid roles, and invalid keys return `400 INVALID_INPUT`.
No system-role input or tool definitions are accepted. The Coordinator supplies the system instruction and server-scoped tools. A run ID must belong to the selected workspace. A successful start or resume returns its run ID and status. API key submissions are never echoed,
saved to env files, or added to history. A key being configured does not prove
Google accepts it; that is checked on the first chat request.

Errors: `409 GEMINI_KEY_REQUIRED`, `401 GEMINI_KEY_INVALID`,
`429 GEMINI_RATE_LIMIT`, `504 GEMINI_TIMEOUT`, `502 GEMINI_UNAVAILABLE`,
and `502 GEMINI_EMPTY_REPLY`. Raw provider errors are not exposed. Responses
also distinguish `502 GEMINI_MODEL_NOT_FOUND` when Google returns 404. Success
responses additionally include `resolvedModel` and
`timing: {providerMs: number, adapterMs: number}` for diagnostics. `X-Request-ID`
correlates HTTP records (`chat.jsonl`) with shared AI-call records (`llm.jsonl`), and
`Server-Timing` reports backend processing duration; both are exposed by CORS.
No key, prompt, reply text, or raw provider error is included in those records.
Responses are non-streaming. Missing provider usage is `null`; total tokens use the
provider's total, including thinking tokens. Usage is per reply, separate from
the generation-run usage records. Success responses use `Cache-Control: no-store`.
Model and timeout are configured with `GEMINI_MODEL` and `GEMINI_TIMEOUT_SECONDS`.

In MSW mode, config reports no key; mutation/chat calls return
`503 CHAT_REQUIRES_BACKEND`. MSW does not fabricate a Gemini reply or retain keys.

## AI-call record viewer

`GET /api/llm/records?limit=100` returns an array of `AICallRecord` objects,
newest call first. It reads the shared gateway's `LLM_RECORD_PATH`, merges
lifecycle events by `callId`, and never calls Gemini. No workspace or API key
is required. This is a local single-user diagnostic view, not an audit archive.

Each object has `callId`, nullable `requestId`, `startedAt`, `finishedAt`,
`event` (`started`, `completed`, `failed`, `cancelled`), `caller` (`chat`, `agent`),
nullable `role`, `model`, `resolvedModel`, `status`, `providerStatus`,
`durationMs`, `providerMs`, `inputTokens`, `outputTokens`, `totalTokens`,
and `errorCode`. Dates use ISO 8601; absent metrics are null, not zero.
`started` means no terminal event was found, not proof the call is still running.
Only these metadata fields are exposed; prompts, replies and keys are excluded.

`limit` accepts 1–200 (default 100); invalid values return `400 INVALID_INPUT`.
The reader scans at most the last 1 MiB / 1,000 valid JSON events. Older calls
may be absent and a start event may fall outside that window. Missing files
return `[]`; malformed lines/events are skipped. Other read errors return
`503 RECORDS_UNAVAILABLE`. Success uses `Cache-Control: no-store`.
The UI fetches on opening **Call records** or pressing **Refresh records**;
there is no polling. MSW returns an empty list rather than fabricated telemetry.

## HTTP wire contract (frontend + MSW)

JSON uses camelCase. List endpoints return arrays directly (no implicit `data`
envelope). Timestamps are ISO 8601 UTC strings. IDs are opaque strings; clients
must URL-encode path segments. Error bodies always use:

```json
{"error":{"code":"NOT_FOUND","message":"Workspace, run or file not found."}}
```

| Method / suffix | Request | Success response |
| --- | --- | --- |
| `GET /workspaces` | — | `WorkspaceSummary[]`, 200 |
| `POST /workspaces` | `{name: string}`; trimmed, nonempty | `WorkspaceSummary`, 201 |
| `GET /workspaces/{workspaceId}` | — | `WorkspaceDetail`, 200 |
| `GET …/runs` | — | `RunSummary[]`, newest first, 200 |
| `GET …/runs/{runId}` | — | `RunDetail`, 200 |
| `GET …/events?after=0` | Nonnegative integer event cursor | `{events: RunEvent[], nextCursor: number}`, 200 |
| `GET …/files` | — | `ArtifactFile[]`, 200 |
| `GET …/file?path=…` | URL-encoded project-relative file path | `FileContent`, 200 |
| `GET …/download` | — | ZIP bytes, `Content-Type: application/zip`, attachment filename, 200 |

All suffixes above are relative to `/api`; `…` retains the workspace/run scope
shown in the route inventory. Request bodies use `Content-Type: application/json`.
Run creation is initiated through `POST /api/chat` by the Coordinator.

```ts
interface WorkspaceSummary { id: string; name: string }
interface WorkspaceDetail extends WorkspaceSummary {
  rootPath: string; createdAt: string;
}
interface RunSummary {
  id: string; workspaceId: string;
  status: "queued" | "running" | "blocked" | "completed" | "failed";
  createdAt: string;
}
interface RunDetail extends RunSummary {
  coordinatorReport?: string;
  activeRole: "planner" | "coder" | "tester" | null;
  error: string | null;
  checks: {
    build: "not_run" | "passed" | "failed";
    tests: "not_run" | "passed" | "failed";
  };
  usage: {
    apiCalls: number; inputTokens: number;
    outputTokens: number; totalTokens: number;
  };
}
interface RunEvent {
  id: number; type: string; message: string; createdAt: string;
  role?: "planner" | "tester" | "coder" | "coordinator";
}
interface ArtifactFile { path: string; size: number; mediaType: string }
interface FileContent extends ArtifactFile {
  content: string; encoding: "utf-8";
}
```

`size` is bytes, not character count. File preview is bounded to 2 MiB of UTF-8
text. Binary and image previews require a future explicit API contract. Path validation rejects absolute
paths, drive prefixes, backslashes, empty/dot/traversal segments and NUL bytes.
An absent workspace, missing file, or a run belonging to another workspace returns
404. Invalid bodies, paths and event cursors return 400. Oversized previews return
413. Downloads of unfinished runs return 409. The backend must additionally
validate authorization and prevent filesystem/symlink escapes; MSW is not a
security boundary or a filesystem sandbox.

Events are ordered by ascending numeric ID, filtered by `id > after`.
`nextCursor` is the last returned ID, or the supplied cursor if no newer events
exist. Mock-created runs remain queued and expose no files until an execution
simulation is explicitly implemented. Seed runs contain fixture artifacts with
zero usage and checks marked `not_run`; they do not imply real generation/tests.

The current Canvas consumes create/list/detail workspaces, list runs, run detail,
run events, list files and read file. A shared watcher checks workspace runs every
3 seconds for sidebar task loaders and the selected conversation header, even
when collapsed. Active runs fetch events using the stored `nextCursor`; empty
batches retain the last progress message. Terminal details/events are cached,
and only the list is polled until new work appears. A different run resets its
cursor. Page restoration restarts cancelled watchers.

Running/queued runs take priority for the task indicator; otherwise it reports
the newest result. Artifact browsing uses the newest run. New runs and changes
to run status invalidate cached artifacts, selection revalidates them, and
Reload preview explicitly rereads files and source. Preview errors do not block
file browsing. A self-contained
`index.html`, if present, is fetched through the same file API for the iframe;
there is no invented preview endpoint. User-entered development URLs and message
drafts are view state. Create workspace sends only `{name}`; the backend allocates
the ID and root directory and persists metadata. The frontend does not import
local folders, choose filesystem roots, generate workspace IDs, or upload files.
The MSW handler simulates that same contract in memory during development; it
does not create directories on disk.

## Backend implementation notes

The backend follows the contract above and matches the MSW handlers. Where the
contract leaves a choice open, it decided as follows (details in the
[backend specification](./backend-spec.md)):

| Topic | Backend behavior |
| --- | --- |
| `checks.build` | Always `not_run`: the generated app has no build step. Only `checks.tests` changes |
| Downloads | Only `completed` runs; `queued`, `running`, `blocked`, and `failed` runs return 409 (as in MSW) |
| Non-UTF-8 files | `415 UNSUPPORTED_FILE` |
| Symlink escapes | A path that resolves outside the project returns `400 INVALID_PATH` |
| Event cursor | Missing or empty `after` is 0 (as in MSW); values above 2^53 − 1 return 400 |
| `mediaType` | Also distinguishes `.js`, `.css`, and `.md`; the frontend highlights by file name, so nothing changes visibly |
| Event types | `queued`, `running`, `role_started`, `role_finished`, `feature_started`, `checks`, `repair`, `feature_completed`, `completed`, `failed`, `diagnosis`, `blocked`, and `tool_call` (one per MCP call) |
| Extra route | `GET /api/health` returns `{"status": "ok"}` for connectivity checks; the frontend does not use it |

## Agent MCP tools

Implemented in `backend/src/ai_coder/mcp/` (stage 3): `server.py` (FastMCP
server), `tools/` (the tool code), `client.py` (`AgentMCPClient` for agents).

### Sessions

Each agent session starts its own server over stdio. Agents do this through
`AgentMCPClient`, which runs:

```text
python -m ai_coder.mcp.server --workspaces-root <dir> --workspace-id <id> \
    --run-id <id> --role planner|coder|tester [--check-timeout 60]
```

The workspace, run, and role are fixed by these arguments for the life of the
process. No tool argument names a workspace, run, or role, so a model cannot
reach another run or act as another role. The server receives only harmless
environment variables (`PATH`, `HOME`, …), never `GEMINI_API_KEY`.

Each role is offered only the tools it may use; `tools/list` returns these, in
this order:

| Tool | Planner | Coder | Tester |
| --- | --- | --- | --- |
| `listFiles` | ✓ | ✓ | ✓ |
| `readFile` | ✓ any file | ✓ any file | ✓ `*.test.js` only |
| `writeFile` | | ✓ not `*.test.js` | ✓ `*.test.js` only |
| `runChecks` | | | ✓ |

### Tools

Argument names are the JSON names the model sends. Every file path is relative
to the run's `project/` folder and follows the
[project path rules](./backend-spec.md#project-paths).

| Tool | Arguments | Result | Refused when |
| --- | --- | --- | --- |
| `listFiles` | `directory` string (default `"."`, the whole project) | `{"files": [{path, size}]}`, sorted by path; `size` in bytes; symlinks are skipped | Invalid `directory` |
| `readFile` | `path` string | The file's text | Invalid path, role not allowed, file missing, larger than 200,000 bytes, or not UTF-8 |
| `writeFile` | `path` string, `content` string | Text `Wrote <path> (<bytes> bytes).` Creates missing folders and replaces the whole file | Invalid path, role not allowed, content larger than 200,000 bytes, or the path is a folder |
| `runChecks` | none | `{outcome, passed, failed, exitCode, timedOut, log}`: `outcome` is `"passed"` or `"failed"`, `exitCode` is `null` after a timeout, `log` is the last 4,000 characters of the output. The same execution is appended to `checks.json` (with the last 20,000 characters) | Role is not the Tester, no `*.test.js` file exists, or Node.js is missing |

LangGraph records agent results directly in storage. `failed` in `runChecks` counts failed and cancelled tests.

### `runChecks` command

The agent cannot change the command:

```text
node --permission --allow-fs-read=<project> --allow-fs-write=<project>
     --test --test-isolation=none --test-reporter=tap "**/*.test.js"
```

- Only `*.test.js` files run, not other names `node --test` accepts by default
  (`test/x.js`, `x-test.js`), which the Coder could write.
- Node's permission model keeps the generated code inside `project/`: reading
  or writing elsewhere fails with `ERR_ACCESS_DENIED`, and starting other
  programs is blocked. `--test-isolation=none` runs all files in one process
  so the limits apply to every test.
- The process gets only `PATH` as its environment, and is killed after the
  timeout (60 seconds by default). When the agent is cancelled, the server and
  `node` stop as well, and nothing is recorded.
- Requires Node.js 22.13 or later.

### Results on the wire

- Success: `content[0].text` holds the result (JSON text for `listFiles` and `runChecks`). `structuredContent` holds the same value as
  JSON; text results are wrapped as `{"result": "..."}`.
- Refusal: `isError: true`, and the text is `Error executing tool <name>:
  <message>`. Messages say what is allowed (for example "The Tester may read
  only test files (*.test.js).") so the model can correct its next call.
  Arguments that do not match the tool's schema are refused the same way.
- `AgentMCPClient.call_tool` returns both cases as
  `ToolResult(text, is_error, structured)`; it raises `MCPServerError` only if
  the server cannot start or be reached.

### Roles

The Planner publishes a plan that names files, functions, inputs, and outputs
precisely, and splits the work into an ordered list of features. The Coder
builds one feature per task on top of the existing code and publishes its
results. The Tester writes tests
from the requirements and the plan without reading the implementation
(black-box testing), executes checks, and publishes the real result. During
repairs only the Coder changes code; tests stay as the specification. The server
enforces these role and path permissions (`workspaces/permissions.py`), checking
both the requested name and the real file behind any symlink.

## Internal backend responsibilities

| Service | Responsibility | Why it is internal |
| --- | --- | --- |
| Orchestrator | Publish tasks, run the Planner and schedule each feature through test authorship, execution, diagnosis and implementation, schedule bounded repairs, finalize run state | Workflow policy is controlled by the backend |
| Agent runtime | Supply role context, call the LLM, dispatch selected MCP tools, feed tool results back into the loop | Owns agent execution rather than UI requests |
| LLM gateway | Make provider requests and record calls/tokens, including retries | Usage comes from the actual model boundary, not agent self-reporting |
| Workspace service | Allocate roots, resolve scoped paths, enforce role permissions | Shared enforcement used by HTTP handlers and MCP tools |
| Storage | Persist inputs, tasks/results, events, execution results, artifacts, and usage by workspace/run | Shared state supports both boundaries |
| Artifact packaging | Package generated code, tests, and execution instructions | Orchestrator prepares output; HTTP API serves it |

API and MCP handlers can call the same underlying services. For example, the UI
previews a file through HTTP while a Coder reads it through MCP. Both use the
same path-scoping service. Do not have the UI call MCP just to reuse file access.

## One complete run

See the [Coordinator and feature TDD workflow](coordinator-tdd.md) for the current sequence and routing rules.

## Multiple workspaces

For workspace A and workspace B, the same routes and tool names are reused;
the server binds different contexts and storage roots. Every run ID must belong
to the referenced workspace. IDs alone are not access authorization.

HTTP file requests and MCP file tools reject absolute paths, traversal, and
symlinks escaping the project root. Commands are isolated by the execution
service. Frontend cache keys include both workspace and run IDs, and workspace
switching cancels or ignores responses for the previous selection.
