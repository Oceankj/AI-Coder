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

## Chat and agent providers

Choose **Groq** in the chat panel’s **Provider** menu. Select **Add API key** and paste a key from [Groq Console](https://console.groq.com/keys). To keep the key across restarts, set `AI_CODER_GROQ_API_KEY` in the backend environment (`GROQ_API_KEY` is also accepted). The default Groq model is `openai/gpt-oss-120b`. **Groq settings** can select `openai/gpt-oss-20b` or `openai/gpt-oss-120b` for subsequent calls. The browser remembers this choice and reapplies it after a backend restart; `GROQ_MODEL` sets the initial backend model before a browser choice is applied. `GROQ_TIMEOUT_SECONDS` defaults to 60.

Gemini is the default provider. It uses `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-flash-latest`) and `GEMINI_TIMEOUT_SECONDS` (default 60). The chat panel links to the selected provider's key console. Keys submitted in chat last for the lifetime of this single-user backend process. The first model request verifies the credential. Keep environment keys in the backend.

The backend accepts `provider: "codex"` to use the local ChatGPT sign-in for chat and generation.
The current chat panel still offers Gemini and Groq only.
The default model is GPT-5.6 Luna (`gpt-5.6-luna`) with low reasoning effort.
Install the Codex command on the backend host and sign in there with `codex login`
using file-backed credentials. The web panel does not ask for an API key.
The backend starts one resident Codex `app-server` on the first model request.
Each decision opens a new ephemeral conversation and passes the current role's
history through the gateway. The child has a private Codex settings directory
that links only the existing login file. AI Coder still executes the role-scoped
workspace tools. Set `AI_CODER_CODEX_TRANSPORT=exec` to use one process per
decision with older Codex installations.

Chat and LangChain agents call `LLMGateway.complete` in `llm/gateway.py`. The gateway records the provider, model, call ID, timing and usage. Each chat request names its provider. New runs store that choice in `run.json` and use it for all agent calls, including after clarification. `llm/gemini.py` uses Google's SDK and `llm/groq.py` uses Groq's chat completions HTTP API. The adapters translate messages, tool calls and provider errors.

The gateway depends on the `ModelAdapter` protocol in `llm/adapter.py`.
All configuration routes await `LLMGateway.configuration(provider)`, which delegates
to the selected adapter. Each adapter owns its authentication settings, local
prerequisite errors, and safe call metadata. The gateway owns the overall timeout
and started/completed/failed/cancelled records, including prerequisite failures.
For Gemini and Groq, `configured` means an in-memory key is present. Codex returns
`cliAvailable` for executable discovery and `configured` for a local ChatGPT login.
Neither state proves that the provider will accept the next model request.

When the Coordinator starts a run, every provider appends the current request's
original user messages, in order, to `input.requirements` in `run.json`, after the
model's extracted requirements. Assistant messages are excluded; the appended
entry states that the latest clarification takes precedence. Existing runs are
unchanged. General chat history is still owned by the browser.

Groq tool calls use a lower temperature and retry once when Groq reports an invalid generated tool call. A short provider-supplied rate-limit delay is retried up to twice. Tester and Coder may write multiple files within their per-step budgets. A Green failure caused by missing implementation files returns to the Coder within the repair budget.

The workspace's `package.json` test script selects a supported runner: `jest` uses the locally installed Jest CLI, while an absent script or `node --test` uses Node's built-in runner. The executor does not execute arbitrary npm scripts. Both commands run only `*.test.js` under Node's project-only permission boundary, with a minimal environment and a timeout. Unsupported scripts stop environment setup with an actionable error. The runner choice is passed to Tester before it authors tests and must remain stable through each feature's Red and Green checks.

Each Coordinator or worker invocation is limited to 10 model calls and 12 tool calls. Three consecutive tool errors stop that step with a recorded blocker; a successful tool call resets only the consecutive-error count. These limits are in `agents/runtime.py` and apply even when calls succeed. Graph repairs remain bounded by `AI_CODER_MAX_REPAIRS`, and Node checks have their own process timeout. Rate limits and other model outages leave the run blocked with its continuation, so it can be retried after the provider recovers. Blocked reports use the recorded reason directly instead of another model call.

The Tester may read `package.json` to inspect installed test dependencies but cannot read application source. During environment repair, the Coder's `writeFile` tool accepts only `package.json`; other Coder steps retain their normal implementation-file permissions.

Provider failures retain the interrupted graph node as well as its input in the run continuation. Retrying resumes that node, including after backend restart, without rerunning Planner or completed features. Requirement blockers still return to Planner for clarification. The Node runner recognizes absent implementation modules before asking an LLM to diagnose them. On parser failures it uses a bounded Node syntax check to identify whether the broken file belongs to Tester or Coder. Environment repairs repeat the affected Red/Green check; npm host/network errors pause instead of asking Coder to rewrite package.json. See the [workflow guide](../docs/coordinator-tdd.md) for checkpoint compatibility and limits.

Chat supplies its own system instruction. Agent calls use the same method with
`context=RunContext(...)` and `role=AgentRole.PLANNER` (or Coder/Tester). The
gateway records the run and role for those calls. The workflow stores run events and usage separately.
LangChain handles tool calls. Workspace chat can start a run, read progress or resume a blocked run after clarification. LangGraph schedules Planner, Tester, Coder and the deterministic Node runner. Each agent request contributes its normalized usage to the run total. The Coordinator records a final report. See the [workflow and verification commands](../docs/coordinator-tdd.md).

A Codex call can request one correction after a malformed or empty reply.
The Coder task includes a bounded list of project paths and selected source
and test files alongside the recorded failure. The Coder can request additional
files and submit multiple related writes through its normal tools.
Chat history comes from the client. Missing provider token usage remains null in call records.

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
and fields. This view works before a workspace or provider key has been configured.

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

Large `providerMs` indicates waiting within the provider call; a large difference
between `adapterMs` and `providerMs` suggests client setup/cleanup overhead.
Timings do not measure the browser network path or separate the provider's queueing,
thinking and generation. Logs append without rotation; archive/remove as needed.
For Groq 429 responses, `providerErrorType` distinguishes token/request limits per minute/day when supplied by the provider. Numeric `rateLimitLimit`, `rateLimitUsed`, and `rateLimitRequested` fields are recorded when present. No account identifiers or raw provider message are saved. A request larger than its per-minute limit requires a smaller request or higher quota; repeating it after a delay cannot make it fit.
Record write failures are reported without discarding the provider reply. Both
logs start after restarting the backend with this version. Earlier HTTP records
remain readable but new HTTP records no longer duplicate AI metrics; find those
in `llm.jsonl` by matching `requestId`. Panel-added keys remain memory-only.
