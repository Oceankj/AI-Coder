# Backend Tests

Run from the `backend/` directory:

```bash
.venv/bin/python -m pytest
```

| File | Covers |
| --- | --- |
| `test_app.py` | Application skeleton: uniform error format, 400 for validation errors, CORS |
| `test_storage.py` | Run directory files: layout, JSON formats, ordering, unsafe IDs, event IDs under concurrency, usage totals, tasks, check executions, startup recovery |
| `test_workspace_routes.py` | `GET/POST /api/workspaces`, `GET /api/workspaces/{id}`: response shapes, name trimming, invalid bodies, unknown and unsafe IDs, `rootPath` |
| `test_orchestrator.py` | Feature-by-feature flow with scripted agents: Planner's feature list and its limits, Coder → Tester per feature, events, task handoffs, `activeRole`, repairs within a feature, the shared repair budget, an unrepairable feature stopping the run, results taken only from `checks.json` of the current attempt, agents that do not submit or crash, scheduler serialization per workspace, shutdown |
| `test_run_routes.py` | `GET/POST …/runs`, `GET …/runs/{id}`: shapes, validation order, cross-workspace 404, background completion with placeholder agents, repair loop through settings, startup recovery |
| `test_placeholder_agents.py` | Placeholder agents plan two features, follow the handoff rules, label themselves, and write a project that really passes `node --test` (skipped without Node.js) |
| `test_paths.py` | Project-relative path rules shared with the MCP file tools: syntax, traversal, symlinked files and directories escaping the project |
| `test_file_routes.py` | `…/events` (cursor rules), `…/files` (bytes, nesting, symlinks skipped), `…/file` (all error cases in order: 404, 400, symlink escape, 413 at 2 MiB + 1, 415), `…/download` (409, ZIP contents, RUNNING.md, packaged on completion) |
| `test_imports.py` | Every module under `ai_coder/` stays importable after shared types change |

Still to be added by later stages:

- MCP task/result handoffs and context validation.
- Usage aggregation across roles, retries, runs, and workspaces.
- Workspace switching and artifact access through the API.
