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
