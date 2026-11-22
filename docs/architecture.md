<!-- Author: Ching Kao; Student ID: 85768427 -->
# AI Coder Architecture

[Back to README](../README.md)

This document records the agreed architecture.

Workspace chat enters through the Coordinator. LangGraph runs the Planner, Tester, Coder and the Node test runner. The [workflow diagrams](coordinator-tdd.md) show routing, the [code guide](langgraph-code-guide.md) maps the implementation, and the [backend specification](backend-spec.md) describes persisted run data.

## Decisions

| Area | Decision |
| --- | --- |
| Collaboration pattern | LangGraph schedules each role and records task handoffs. Workers use role-scoped MCP file tools. |
| Runtime agents | Coordinator, Planner, Tester and Coder. |
| Generated application | Plain HTML/CSS/JavaScript (`index.html`, `playlist.js`) with tests run by Node's built-in runner (`node --test`). No `npm install` in generated projects. |
| Backend framework | FastAPI (Python 3.11+), serving the contract in [interfaces.md](./interfaces.md) on port 8000. |
| MCP | Official `mcp` Python SDK (FastMCP), **stdio** transport. Each agent session starts its own MCP server subprocess. |
| LLM | Google Gemini via the `google-genai` SDK (AI Studio, free tier). Automatic function calling is disabled; the agent runtime runs its own tool loop so every model call is counted. |
| API keys | Each member uses their own AI Studio key (`GEMINI_API_KEY` in an uncommitted `.env`). The demo uses one key with its daily quota left unused beforehand. |
| Testing strategy | Black-box: the Tester writes tests from the requirements and the Planner's interface spec, without reading the implementation. Only the Coder changes code during repairs. |
| Feature-by-feature flow | The Planner splits the work into at most 4 features (`max_features`). Each feature goes through Tester authorship, a deterministic pre-implementation run, Coder implementation if needed, and a full regression run. |
| Repair limit | At most 3 repair rounds per run (`max_repairs`), shared by all features. A feature that cannot be repaired stops the run and the run reports the real test result. |
| Time limit | Each agent call may take at most 10 minutes (`agent_timeout_seconds`); a hung agent is cancelled and the run fails, so it cannot block its workspace. |
| Coordination | The LangChain Coordinator interprets chat intent. LangGraph routes each feature using structured Tester diagnoses and recorded Node outcomes. |
| Development mode | Integration tests use scripted Google responses through the production gateway. Normal development uses the configured Gemini model. |

## Runtime boundaries

The [Coordinator and TDD workflow diagrams](coordinator-tdd.md) describe the current production flow. The browser calls HTTP for chat, workspace and run reads, progress, file previews, usage records, and ZIP download. `POST /api/chat` is the run creation entry point: the Coordinator calls `startRun` or `resumeRun` through the internal `RunService`.

LangGraph passes task context to Planner, Tester, and Coder and records their results in storage. Each worker starts a role-scoped MCP server over stdio to list, read, or write project files. The deterministic Red and Green nodes call the shared Node test execution service directly; the MCP `runChecks` tool remains available to Tester but is not used by the graph. All model calls share the LLM gateway and call records.

### Shared files on disk

| File | Written by | Read by |
| --- | --- | --- |
| `project/` | MCP `writeFile` | MCP file tools, HTTP preview and download, Node runner |
| `run.json` | Backend orchestration | Backend run APIs |
| `tasks.json` | Backend orchestration | Backend orchestration |
| `checks.json` | Shared test execution service | Backend routing and run APIs |
| `events.jsonl` | Backend orchestration and agent runtime | Backend events API |
| `usage.json` | LLM gateway | Backend run detail API |

## Security checks (MCP server)

The MCP server treats every agent argument as untrusted:

- Workspace, run, and role come from the server's startup arguments, never from
  tool arguments.
- Paths must stay inside the run's `project/` directory: absolute paths,
  traversal segments, and symlink escapes are rejected.
- Role permissions are enforced: only the Coder writes application files; the
  Tester writes test files only and cannot read application source.
- `runChecks` runs only the fixed `node --test` command, with a timeout and
  bounded output. No arbitrary shell command is exposed.

## Multiple workspaces

- A workspace represents an independent user project. Each generation is a run
  within that workspace, identified by `(workspaceId, runId)`.
- Generated code, tasks, results, events, artifacts, and usage are scoped to that
  pair.
- Different runs use separate project directories. A blocked run can resume
  after clarification with the same run ID.
- Runs within a workspace execute one at a time. Concurrent workspaces are not
  required for the demo.
- The UI scopes run selections, caches, and subscriptions to the current
  workspace. Workspace switching must not display results from a previous
  workspace.

## Project history

The original stage ownership and handoffs are archived in [team responsibilities](team-responsibilities.md). The current interfaces are documented in [interfaces.md](interfaces.md).
