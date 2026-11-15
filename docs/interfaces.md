# API and MCP Responsibilities

[Back to README](../README.md) · [Architecture](./architecture.md)

This is the interface inventory for AI Coder. The frontend implements the HTTP
client and development-only MSW handlers for the routes below. Backend HTTP
handlers and MCP registration are still TODO. The wire contract below is the
frontend integration contract to implement on the backend. The HTTP API belongs
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
| `POST /api/workspaces/{workspaceId}/runs` | Submit description and requirements | Create a run, save the input, schedule generation; return its ID and initial status |
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
must distinguish queued/running/completed/failed, and the frontend must not
interpret "files generated" as "tests passed". The JSON schemas are defined below
and mirrored in `frontend/src/types/index.ts`.

File preview is read-only. The frontend Canvas now supports user-provided iframe
URLs and a bundled UI demo without a backend preview endpoint. Starting and
isolating preview servers still requires a separate backend interface decision.
UI editing, workspace deletion, cancellation, and manual reruns of individual
checks remain outside this initial inventory.

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
| `POST …/runs` | `{description: string, requirements: string[]}`; nonempty description | `RunSummary` with `status: "queued"`, 201 |
| `GET …/runs/{runId}` | — | `RunDetail`, 200 |
| `GET …/events?after=0` | Nonnegative integer event cursor | `{events: RunEvent[], nextCursor: number}`, 200 |
| `GET …/files` | — | `ArtifactFile[]`, 200 |
| `GET …/file?path=…` | URL-encoded project-relative file path | `FileContent`, 200 |
| `GET …/download` | — | ZIP bytes, `Content-Type: application/zip`, attachment filename, 200 |

All suffixes above are relative to `/api`; `…` retains the workspace/run scope
shown in the route inventory. Request bodies use `Content-Type: application/json`.
The route carries workspace identity; run creation does not duplicate it in JSON.

```ts
interface WorkspaceSummary { id: string; name: string }
interface WorkspaceDetail extends WorkspaceSummary {
  rootPath: string; createdAt: string;
}
interface RunSummary {
  id: string; workspaceId: string;
  status: "queued" | "running" | "completed" | "failed";
  createdAt: string;
}
interface RunDetail extends RunSummary {
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

The current Canvas consumes create/list/detail workspaces, list runs, list files
and read file. It selects the newest run for each API workspace. A self-contained
`index.html`, if present, is fetched through the same file API for the iframe;
there is no invented preview endpoint. User-entered development URLs and message
drafts are view state. Create workspace sends only `{name}`; the backend allocates
the ID and root directory and persists metadata. The frontend does not import
local folders, choose filesystem roots, generate workspace IDs, or upload files.
The MSW handler simulates that same contract in memory during development; it
does not create directories on disk.

## Agent MCP tools

Workspace/run/role identity is bound by the server when establishing the agent
session. The table shows agent-facing business arguments, not trusted scope
arguments. Internal Python handlers also receive the server-bound `RunContext`.

| Tool | Arguments | Result / effect | Intended callers |
| --- | --- | --- | --- |
| `getTask` | None | Assigned instructions, submitted requirements, and relevant predecessor results or artifact references | Planner, Coder, Tester |
| `submitResult` | Structured summary, artifact paths, outcome | Persist the current role's result for handoff; failure reports can trigger a repair decision | Planner, Coder, Tester |
| `listFiles` | Optional project-relative directory | List generated files in this run | All roles as needed |
| `readFile` | Project-relative file path | Return text file content from this run | All roles as needed |
| `writeFile` | Project-relative file path, content | Create or update a permitted file in this run | Coder; Tester for test files |
| `runChecks` | None initially | Run configured build and tests; return execution ID, exit codes, bounded logs, and structured results | Coder, Tester |

The Planner publishes a plan rather than creating the next run or starting an
agent. The Coder publishes implementation results. The Tester writes tests,
executes checks, and publishes its findings. The server enforces role and path
permissions; the table is a proposed policy, not an implemented guarantee.

`runChecks` uses commands configured for the supported generated stack. This
initial design does not expose arbitrary host shell execution. The execution
service runs checks inside the run sandbox with a timeout and records results.

## Internal backend responsibilities

| Service | Responsibility | Why it is internal |
| --- | --- | --- |
| Orchestrator | Publish tasks, sequence Planner → Coder → Tester, schedule bounded repairs, finalize run state | Workflow policy is controlled by the backend |
| Agent runtime | Supply role context, call the LLM, dispatch selected MCP tools, feed tool results back into the loop | Owns agent execution rather than UI requests |
| LLM gateway | Make provider requests and record calls/tokens, including retries | Usage comes from the actual model boundary, not agent self-reporting |
| Workspace service | Allocate roots, resolve scoped paths, manage write locks and run sandboxes | Shared enforcement used by HTTP handlers and MCP tools |
| Storage | Persist inputs, tasks/results, events, execution results, artifacts, and usage by workspace/run | Shared state supports both boundaries |
| Artifact packaging | Package generated code, tests, and execution instructions | Orchestrator prepares output; HTTP API serves it |

API and MCP handlers can call the same underlying services. For example, the UI
previews a file through HTTP while a Coder reads it through MCP. Both use the
same path-scoping service. Do not have the UI call MCP just to reuse file access.

## One complete run

1. UI calls `POST /api/workspaces` if needed, then submits requirements to the workspace's run API.
2. Backend creates the run; the orchestrator publishes the Planner task.
3. Planner calls MCP `getTask`, uses the internal LLM gateway, then calls MCP `submitResult` with its plan.
4. Orchestrator publishes the Coder task with the plan. Coder calls MCP `getTask`, `listFiles`, `readFile`, and `writeFile`, then submits its result.
5. Tester reads its task and generated code, writes tests, runs MCP `runChecks`, and submits its findings.
6. Orchestrator schedules a bounded repair if necessary. Execution results remain recorded even if an agent reports success incorrectly.
7. Backend records the final state and packages available outputs. UI retrieves events, results, file previews, usage, and downloads through HTTP.

## Multiple workspaces

For workspace A and workspace B, the same routes and tool names are reused;
the server binds different contexts and storage roots. Every run ID must belong
to the referenced workspace. IDs alone are not access authorization.

HTTP file requests and MCP file tools reject absolute paths, traversal, and
symlinks escaping the project root. Commands are isolated by the execution
service. Frontend cache keys include both workspace and run IDs, and workspace
switching cancels or ignores responses for the previous selection.
