<!-- Author: Ching Kao; Student ID: 85768427 -->
# Backend development

Requires Python 3.11+. From this directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env.local  # Once; edit your local settings
./dev.sh
```

The server listens at http://127.0.0.1:8000 by default. API documentation is at
`/docs`, and `/api/health` reports readiness. Ctrl+C stops the server.
No Node.js or frontend checkout is required to start the HTTP backend. Generated
JavaScript checks and the MCP execution tool require Node.js separately.

`dev.sh` selects this project's `.venv` and runs `dev.py`. The Python entry point
loads only backend env files, then starts uvicorn. Priority is shell variables,
`.env.local`, `.env`, then code defaults. Example files are templates and are not
loaded automatically. Env files use python-dotenv syntax; they are not shell scripts.

| Setting | Default | Purpose |
| --- | --- | --- |
| `BACKEND_HOST` | `127.0.0.1` | Bind address |
| `BACKEND_PORT` | `8000` | HTTP port |
| `AI_CODER_CORS_ORIGINS` | Localhost/127.0.0.1 on port 5173 | Comma-separated permitted frontend origins |

The [backend specification](../docs/backend-spec.md) documents the remaining
`AI_CODER_*` settings. The backend never reads frontend or root env files.
Supported backend env names are defined once in `config.EnvVar` (`StrEnum`);
the settings loader and test environment cleanup both use that definition.
When connecting a separately running frontend, explicitly permit its origin.

After `pyproject.toml` changes, rerun `.venv/bin/python -m pip install -e ".[dev]"`.
Startup deliberately does not install packages. A missing `.venv` produces setup
instructions; a missing package requires reinstalling dependencies. If the port
is occupied, stop its owner or change `BACKEND_PORT`; the server will not silently
select another port. Shell overrides also work, for example:

```bash
BACKEND_PORT=8001 ./dev.sh
.venv/bin/python -m pytest
```

The root `../dev.sh backend` delegates to this same entry point. The root
coordinator is for local development on macOS/Linux, not production deployment.

The application factory schedules every generation run through `TDDWorkflow`.

HTTP middleware is registered by `api/middleware.py`: CORS policy and chat
request diagnostics live there. `main.py` calls `install_middleware(app, settings)`
and composes services/routes; route modules contain endpoint behavior.

## Gemini chat and agent runs

Reinstall dependencies to install LangChain, LangGraph and the Gemini SDK:

```bash
.venv/bin/python -m pip install -e ".[dev]"
./dev.sh
```

Use **Add API key** in the chat panel, or set `GEMINI_API_KEY` in backend
`.env.local`. Never put it in a frontend `VITE_*` variable. `GEMINI_MODEL`
defaults to `gemini-flash-latest`; `GEMINI_TIMEOUT_SECONDS` defaults to 60.
Shell variables override backend env files as described above.

The UI guides users to [Google AI Studio](https://aistudio.google.com/apikey).
A panel-submitted key is held only in this running, local single-user backend's
memory and is shared across its tabs. It does not rewrite any env file; a
restart restores the environment key (if any). Configuration returns only a
boolean and model, never the key. Adding a key does not spend a model call or
claim validation; authentication errors are handled on the first message.
Replace the key through **Gemini settings**.

All AI calls go through `LLMGateway.complete` (`llm/gateway.py`). The gateway
owns call IDs, shared call records, time limits and safe error propagation.
`llm/gemini.py` is the provider adapter: SDK conversion, role mapping, provider
errors and normalized replies/usage. Only that adapter imports Google's SDK;
HTTP routes and agents must not call it directly.

```text
Chat API -------------------+                        +--> Gemini SDK
                            +--> LLMGateway --> GeminiAdapter
LangChain run agents -------+
```

Chat supplies its own system instruction. Agent calls use the same method with
`context=RunContext(...)` and `role=AgentRole.PLANNER` (or Coder/Tester). The
gateway records the run/role alongside those calls. RunRecorder remains the
business layer for a run's events and totals; it is not another AI client.
LangChain handles tool calls. Workspace chat can start a run, read progress or resume a blocked run after clarification. LangGraph schedules Planner, Tester, Coder and the deterministic Node runner. Each agent request contributes its normalized usage to the run total. The Coordinator records a final report. See the [workflow and verification commands](../docs/coordinator-tdd.md).

Each gateway call makes one SDK request with automatic retry disabled. Chat history comes from the client. Missing provider token usage remains null in call records.

The [chat API contract](../docs/interfaces.md#text-chat) documents payloads.
`tests/test_chat.py` exercises routes and the adapter with Google's transport
replaced: no real API key or billable request is required. The implementation
uses the [official async SDK](https://googleapis.github.io/python-genai/).

### Chat request records

Every `POST /api/chat` appends `started` and `completed`/`failed` events to
`backend/records/chat.jsonl` by default. `CHAT_RECORD_PATH` overrides the file
location; it is independent of workspace/run storage. Records are ignored by
Git. Earlier requests cannot be recovered: recording begins after restarting
the backend with this version.

HTTP records contain timestamps, request IDs, HTTP status, backend duration
and safe application error code. Unknown routes and key configuration are not
included. Provider details belong to the shared AI-call log described below.

The response's `X-Request-ID` matches the JSONL events; `Server-Timing` reports
backend processing time. These headers are exposed through CORS. To inspect
recent records, from `backend/`:

```bash
tail -n 10 records/chat.jsonl
```

### Shared AI-call records

Open **Call records** in the chat panel to view recent calls in a modal table.
`GET /api/llm/records` reads the existing JSONL file and merges lifecycle events
into one row per call; no separate database or recorder is introduced. Restart
the backend after updating to register this route. See the
[record viewer contract](../docs/interfaces.md#ai-call-record-viewer) for limits
and fields. This view needs neither a workspace nor a configured Gemini key.

The gateway appends `started` and `completed`/`failed`/`cancelled` events to
`backend/records/llm.jsonl` (`LLM_RECORD_PATH` overrides the location). This
includes both chat and agent calls, even those with no HTTP request. Each call
has its own `callId`; HTTP-initiated calls also carry the HTTP `requestId`.
Agent calls include workspace/run IDs and role. Calls rejected by HTTP
validation have an HTTP record but no AI-call record.

AI-call records include the requested/resolved model, message count and input
character count, duration, adapter/provider timings and token usage, or safe
error code and provider HTTP status. Neither log stores keys, prompts, replies,
HTTP headers, system instructions or raw provider errors. Both use the same
small JSONL writer (`storage/records.py`) and are ignored by Git.

```bash
tail -n 10 records/llm.jsonl
```

Large `providerMs` indicates waiting within the Gemini call; a large difference
between `adapterMs` and `providerMs` suggests client setup/cleanup overhead.
Timings do not measure the browser network path or separate Google's queueing,
thinking and generation. Logs append without rotation; archive/remove as needed.
Record write failures are reported without discarding the provider reply. Both
logs start after restarting the backend with this version. Earlier HTTP records
remain readable but new HTTP records no longer duplicate AI metrics; find those
in `llm.jsonl` by matching `requestId`. Panel-added keys remain memory-only.
