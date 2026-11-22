# Backend Tests

Run from the `backend/` directory:

```bash
.venv/bin/python -m pytest
```

| File | Covers |
| --- | --- |
| `test_config.py` | Settings from environment variables: defaults, overrides, invalid values named in the error |
| `test_app.py` | Application skeleton: uniform error format, 400 for validation errors, CORS |
| `test_storage.py` | Run directory files: layout, JSON formats, ordering, unsafe IDs, event IDs under concurrency, usage totals, tasks, check executions, startup recovery |
| `test_workspace_routes.py` | `GET/POST /api/workspaces`, `GET /api/workspaces/{id}`: response shapes, name trimming, invalid bodies, unknown and unsafe IDs, `rootPath` |
| `test_run_routes.py` | `GET …/runs`, `GET …/runs/{id}`: shapes, cross-workspace 404, removed POST route, startup recovery |
| `test_tdd_workflow.py` | Production graph, plan validation, role handoffs, real checks, bounded repairs, resume, scheduling and cancellation |
| `test_paths.py` | Project-relative path rules shared with the MCP file tools: syntax, traversal, symlinked files and directories escaping the project |
| `test_file_routes.py` | `…/events` (cursor rules), `…/files` (bytes, nesting, symlinks skipped), `…/file` (all error cases in order: 404, 400, symlink escape, 413 at 2 MiB + 1, 415), `…/download` (409, ZIP contents, RUNNING.md, packaged on completion) |
| `test_imports.py` | Every module under `ai_coder/` stays importable after shared types change |

Browser checks that run the real frontend against the real backend live in
[`backend/e2e/`](../e2e/README.md) (`backend/e2e/run.sh`).
