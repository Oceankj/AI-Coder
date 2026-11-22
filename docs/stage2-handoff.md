# Stage 2 Handoff: Backend Core (historical)

This describes the original Stage 2 interface. For the current API and agent
workflow, use [interfaces.md](./interfaces.md) and
[coordinator-tdd.md](./coordinator-tdd.md).

[Back to README](../README.md) · [Backend specification](./backend-spec.md) ·
[Team responsibilities](./team-responsibilities.md)

Stage 2 (Pete) is done. This page tells each later stage what exists, what to
read, and what to build. The full contract is in the
[backend specification](./backend-spec.md); this page does not repeat it.

## What works now

- All ten HTTP routes of [interfaces.md](./interfaces.md), matching the
  frontend's MSW handlers. The frontend works against the real backend with
  `VITE_ENABLE_MSW=false`.
- Run storage on disk: `run.json`, `tasks.json`, `checks.json`,
  `events.jsonl`, `usage.json`, `project/`, and the download ZIP.
- The orchestrator: the Planner runs once and returns a feature list; each
  feature then goes Coder → Tester, with a repair budget shared by the run.
  Whether tests passed comes only from `checks.json`.
- Placeholder agents that write a real two-feature Playlist Mixer (it passes
  `node --test`) so the whole pipeline runs without an LLM or MCP.

Verify it yourself:

```bash
cd backend
.venv/bin/python -m pytest        # 242 backend tests
e2e/run.sh                        # 28 browser checks, frontend + backend
```

## For stage 3: Member A (MCP layer)

**Read:** [Run directory files](./backend-spec.md#run-directory-files),
[Project paths](./backend-spec.md#project-paths), and the
[Agent MCP tools](./interfaces.md#agent-mcp-tools) table.

**Reuse, do not reimplement:**

| Need | Use |
| --- | --- |
| Read and write `tasks.json`, `checks.json` | `FileStorage` (`ai_coder/storage/repository.py`): `get_current_task`, `submit_result`, `append_check_execution` |
| The project folder | `FileStorage.project_dir(context)` |
| List files | `FileStorage.list_project_files(context)` |
| Path checks | `validate_relative_path` and `resolve_project_path` (`ai_coder/workspaces/service.py`) |
| Record types | `ai_coder/models.py` (`AgentTask`, `AgentResult`, `PlannedFeature`, `CheckExecution`, …) |

The MCP server is a separate process, but it imports the same package: create
your own `FileStorage(workspaces_root)` pointing at the same root as the
backend. No cross-process lock is needed, because agents run one at a time.

**Build:**

1. A FastMCP server over stdio with `getTask`, `submitResult`, `listFiles`,
   `readFile`, `writeFile`, `runChecks`.
2. Bind workspace ID, run ID, role, and workspaces root when the server starts
   (command-line arguments or environment), never from tool arguments.
3. Role permissions on top of the shared path checks: the Tester may read and
   write only `*.test.js` files; only the Coder writes application files.
4. `submitResult` accepts `features` (a list of `{title, description}`) and
   passes it to `FileStorage.submit_result`; only the Planner uses it.
5. `runChecks`: run `node --test` in `project_dir` with a timeout, count passed
   and failed tests, and call `append_check_execution`. Tip: pass
   `--test-reporter=tap` so the output always ends with `# pass N` and
   `# fail N` lines that are easy to parse.
6. A small MCP client wrapper for stage 4 (start the server for a role, call a
   tool, close).
7. **Document the six tools' argument and result schemas**: that is your
   handoff to Ching.
8. **Write the Playlist Mixer requirements as checkable rules** (for example
   "adjacent songs differ by at most 15 BPM"): that is your handoff to Member B,
   and the TA expects to discuss them.

Watch out for: generated projects need `package.json` with
`"type": "module"`, or the tests cannot import `playlist.js` and
`node --test` fails.

## For stage 4: Ching (real agents and frontend)

**Read:** [Orchestrator and agent interface](./backend-spec.md#orchestrator-and-agent-interface)
and `ai_coder/agents/base.py`.

**Agents:**

- Implement `PlannerAgent`, `CoderAgent`, `TesterAgent` (stubs in
  `ai_coder/agents/`) with `execute(context, recorder)`.
- Pass them to `create_app(agents=...)`, and add a setting so the default
  uvicorn command can choose them instead of the placeholders (for example
  `AI_CODER_AGENTS=gemini`).
- Count **every** Gemini call, retries included, with
  `recorder.add_usage(...)`; pass `total_tokens` so thinking tokens count.
- Log every MCP call with `recorder.event("tool_call", "Coder -> writeFile(index.html)")`.
- Use the **async** Gemini client and `await` every slow call. Each agent call
  has a 10-minute limit; when it passes, the agent is cancelled, so stop its
  MCP server in a `finally` block. A blocking call would freeze the whole
  server and cannot be interrupted.
- The Planner must submit `features` (1 to `max_features`, default 4), or the
  run fails.
- Tool loop, recommended rules: stop when `submitResult` succeeds (saves one
  call per agent); cap the number of rounds (for example 20) and raise a
  readable error when it is reached; if the model stops without submitting,
  remind it once.

**Frontend:**

- Submit requirements from the panel with the existing `api.createRun`, and add
  a download button using `api.download`.
- Feature progress is hard to see: the panel shows only the latest event per
  3-second poll, and `tool_call` events right after `feature_started` hide it.
  Consider showing the latest `feature_*` event separately.
- Optional: add a `<link rel="icon">` to `index.html`; the missing favicon is
  the only console error in development.
- Then switch `backend/e2e/run.mjs` from API calls to clicking the new
  controls.

## For stage 5: Member B (quality and demo)

- Tune prompts on Gemini until the generated app passes its tests; the
  settings `AI_CODER_MAX_FEATURES` and `AI_CODER_MAX_REPAIRS` bound the cost.
- A run with 4 features makes roughly 30–40 Gemini calls before repairs. Check
  the demo key's free-tier quota, and leave it unused the day before the demo.
- Keep `pytest` and `e2e/run.sh` green; add tests for the real agents.

## Open items

| # | Item | Status |
| --- | --- | --- |
| 1 | ~~No time limit per agent~~: each agent call now has a time limit (`AI_CODER_AGENT_TIMEOUT_SECONDS`, default 10 minutes); a hung agent is cancelled and the run fails | Done |
| 2 | Runs still waiting in the queue when the backend stops stay `queued` until the next start, which marks them failed | Accepted |
| 3 | No authentication: the backend is a local, single-user tool | Accepted for the course project |
| 4 | Storage reads whole files on each update (events, tasks); fine for runs of this size | Accepted |

## Stage 2 commits

| Commit | Content |
| --- | --- |
| `7aa8a52` | Architecture and relay plan documents |
| `6c3d27a` | Steps 1–3: app skeleton, storage, workspace routes |
| `3df4745` | Step 4: run routes, orchestrator, placeholder agents |
| `b319935` | One feature at a time, shared repair budget |
| `b1f0bf3` | Step 5: events, files, file content, download |
| `ac45425` | Step 6: browser checks |
| (next commits) | Step 7: handoff documents; time limit per agent |

The day-by-day record, including every problem found and how it was solved, is
in [WORK_LOG.md](../WORK_LOG.md).
