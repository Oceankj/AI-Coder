<!-- Author: Ching Kao; Student ID: 85768427 -->
# Stage 3 Handoff: MCP Layer (historical)

This records the original Stage 3 interface, including tools that have since
been removed. The current production tool contract is in
[interfaces.md](./interfaces.md#agent-mcp-tools). LangGraph now owns task
handoffs, and the runner calls the shared check service directly.

[Back to README](../README.md) · [MCP tool contract](./interfaces.md#agent-mcp-tools) ·
[Stage 2 handoff](./stage2-handoff.md) · [Team responsibilities](./team-responsibilities.md)

Stage 3 (Shih-Yun Huang) is done. The MCP server, its six tools, and the
client that agents use are implemented and tested. The full contract (every
argument, result, and refusal) is in
[interfaces.md → Agent MCP tools](./interfaces.md#agent-mcp-tools); this page
does not repeat it.

## What works now

- A FastMCP server over stdio, one process per agent session, bound at startup
  to one workspace, run, and role (`python -m ai_coder.mcp.server`).
- Six tools: `getTask`, `submitResult`, `listFiles`, `readFile`, `writeFile`,
  `runChecks`. Each role is offered only the tools it may use.
- Role permissions: the Planner writes nothing; the Coder never edits
  `*.test.js`; the Tester reads and writes only `*.test.js`. Checked on the
  requested name and on the real file behind a symlink.
- `runChecks` runs real `node --test` on `*.test.js` only, sandboxed to the
  project folder with Node's permission model, with only `PATH` in its
  environment and a 60-second timeout, and records the result in
  `checks.json`.
- `AgentMCPClient`: starts a role's server, lists and calls tools, and stops
  the server (and any running `node`) when the agent finishes or is cancelled.

Not done yet: the placeholder agents still write files directly; nothing in
the running backend uses MCP until stage 4 replaces them.

Verify it yourself, from `backend/`:

```bash
.venv/bin/python -m pytest        # 317 tests; the MCP ones need Node.js 22.13+
```

| File | What it tests |
| --- | --- |
| `tests/test_permissions.py` | Role rules, symlink tricks |
| `tests/test_mcp_tools.py` | The five non-execution tools as plain Python |
| `tests/test_run_checks.py` | `runChecks` with real `node`: sandbox, secrets, timeout |
| `tests/test_mcp_server.py` | The server through a real MCP session (`tools/list`, `tools/call`) |
| `tests/test_mcp_client.py` | The client against a real stdio subprocess, including cancellation |

## Code map

| Path | Content |
| --- | --- |
| `ai_coder/workspaces/permissions.py` | Who may read and write which files |
| `ai_coder/mcp/tools/scope.py` | `ToolScope`: the storage, run, and role a server is bound to |
| `ai_coder/mcp/tools/collaboration.py` | `getTask`, `submitResult` |
| `ai_coder/mcp/tools/files.py` | `listFiles`, `readFile`, `writeFile` |
| `ai_coder/mcp/tools/execution.py` | `runChecks` |
| `ai_coder/mcp/server.py` | Startup arguments, tool registration, tool descriptions the LLM reads |
| `ai_coder/mcp/client.py` | `AgentMCPClient`, `ToolSpec`, `ToolResult`, `MCPServerError` |

The SDK is pinned to `mcp>=1.30,<2`: version 2 renamed `FastMCP` to
`MCPServer`.

## For stage 4: Ching (real agents)

Inside each agent's `execute(context, recorder)`:

```python
from ai_coder.mcp.client import AgentMCPClient

async with AgentMCPClient(
    settings.workspaces_root, context, self.role, max_features=settings.max_features
) as mcp:
    tools = await mcp.list_tools()          # ToolSpec(name, description, input_schema)
    # ... tool loop with Gemini:
    result = await mcp.call_tool(name, args)
    recorder.event("tool_call", f"Coder -> {name}({args.get('path', '')})")
    # send result.text back to Gemini, error or not
```

- **Use `async with`, in the agent's own task.** Leaving it, including on the
  orchestrator's time-limit cancellation, stops the server and `node`. No
  extra `finally` is needed for MCP.
- **Refusals are results, not exceptions.** `result.is_error` is `True` and
  `result.text` explains the rule; give it to Gemini so it can correct itself.
  Only `MCPServerError` (the server could not start) should end the agent.
- **Schemas for Gemini.** `input_schema` is standard JSON Schema.
  `submitResult`'s schema uses `$defs` for the feature item and
  `additionalProperties: false`; check that the Gemini function declaration
  accepts it, or inline the definition when converting.
- **Planner mistakes are recoverable.** `submitResult` refuses an empty or
  too-long feature list, so the Planner can retry instead of failing the run.
- **The Tester must call `runChecks`.** The orchestrator fails the run
  otherwise. Only the Tester can call it.
- **The Coder must write `package.json` with `"type": "module"`**, or the
  tests cannot import `playlist.js`. Put this in the Coder prompt.
- `runChecks` uses a 60-second timeout. There is no setting for it yet; pass
  `check_timeout_seconds=` to `AgentMCPClient` if you add one.

## For stage 5: Member B (prompts and demo)

- The tool descriptions in `ai_coder/mcp/server.py` (the inner functions'
  docstrings and `Field(description=...)`) are part of the prompt; tune them
  there with the agent prompts.
- Each role sees only its tools, which keeps the tool definitions sent on
  every Gemini call short.
- `runChecks` returns the last 4,000 characters of the test log to the model
  (full tail of 20,000 in `checks.json`); lower it if repairs use too many
  tokens.

## Open items

| # | Item | Status |
| --- | --- | --- |
| 1 | Playlist Mixer requirements written as checkable rules (listed for stage 3 in the relay plan; the assignment asks the team to define them and discuss them with the TA) | Not written; the team decides who writes them before the demo |
| 2 | A `*.test.js` file containing no `test(...)` call is reported by Node as one passing test | Accepted: rare, and later checks still run |
| 3 | Stopping the server and `node` on cancellation is tested on macOS; on Windows the SDK uses a different mechanism | Untested on Windows |

## Stage 3 commits

| Commit | Content |
| --- | --- |
| `5085829` | Step 0: `mcp` dependency |
| `6e51854` | Step 1: role permissions |
| `54e18fa` | Step 2: collaboration and file tools |
| `a9104b2` | Step 3: `runChecks` |
| `9798add` | Step 4: FastMCP server |
| `cff19cf` | Step 5: MCP client |
| (next) | Tool contract in `interfaces.md`, this handoff, `listFiles` returns `{"files": [...]}` |
