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
| `test_imports.py` | Every module under `ai_coder/` stays importable after shared types change |

Still to be added by later stages:

- Workspace and run isolation, including traversal and symlink escapes.
- MCP task/result handoffs and context validation.
- Planner -> Coder -> Tester execution and bounded repair behavior.
- Usage aggregation across roles, retries, runs, and workspaces.
- Workspace switching and artifact access through the API.
