<!-- Author: Ching Kao; Student ID: 85768427 -->
# AI Coder

A final project to build a multi-agent system using the Model Context Protocol (MCP). Users submit a software description and requirements through a UI. The system generates executable application code and corresponding test cases, and reports LLM API call counts and total token usage.

**Music Playlist Mixer** is the selected demonstration application. Product requirements are supplied as input to the generation workflow.

## Status

The team works as a relay ([team responsibilities](docs/team-responsibilities.md)).

| Stage | Part | Status |
| --- | --- | --- |
| 1 | Frontend: Agent Canvas with workspace file trees, file preview, live preview iframe, and the agent panel ([frontend setup](frontend/README.md)) | Done |
| 2 | Backend core: all HTTP routes, run storage, background run scheduling ([backend specification](docs/backend-spec.md), [handoff](docs/stage2-handoff.md)) | Done |
| 3 | MCP server and tools, MCP client for agents ([tool contract](docs/interfaces.md#agent-mcp-tools), [handoff](docs/stage3-handoff.md)) | Done; Playlist Mixer requirements still open |
| 4 | Gemini and Groq chat with API key onboarding; real agents and generation controls | Coordinator chat, LangChain agents, LangGraph TDD workflow and ZIP API implemented |
| 5 | Prompt tuning, verification, demo | To do |

Select a workspace and ask the chat Coordinator to implement a feature. The Planner defines acceptance criteria, the Tester writes executable tests, and the Coder works from recorded failures. LangGraph runs the Node suite between steps. The chat reports completion or requests clarification. See the [two workflow diagrams](docs/coordinator-tdd.md) and [LangChain/LangGraph code guide](docs/langgraph-code-guide.md).

### Quick start

Prepare each project once, and repeat installation after its dependency files change:

```bash
(cd frontend && npm ci)
(cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]")
```

Start from the repository root:

```bash
./dev.sh           # Both services
./dev.sh frontend  # Frontend only
./dev.sh backend   # Backend only
```

Defaults: frontend http://127.0.0.1:5173, backend http://127.0.0.1:8000/docs.
MSW remains enabled. Press Ctrl+C to stop the selected services. The root
launcher supports macOS/Linux and requires Node.js; it only calls each project's
entry point and stops their process groups when interrupted or either service
exits. It does not install dependencies, load env files, or infer API/CORS URLs.
Each service reports startup errors in the terminal.

Each project also runs independently:

```bash
(cd frontend && npm run dev)
(cd backend && ./dev.sh)
```

- [Frontend setup and env](frontend/README.md): Node.js 20.19+ or 22.12+, npm,
  Vite settings, MSW, and the API URL. Frontend-only MSW use needs no Python.
- [Backend setup and env](backend/README.md): Python 3.11+, virtual environment,
  host/port, CORS, and backend settings. Its own entry point needs no Node.js.

To configure a project, copy its `.env.example` to `.env.local` and edit it.
Shell variables take priority. To use the real backend, set
`VITE_ENABLE_MSW=false` and `VITE_API_BASE_URL=http://127.0.0.1:8000/api` in
`frontend/.env.local`. If the frontend's address changes, update
`AI_CODER_CORS_ORIGINS` in `backend/.env.local`. Restart the affected service.

The former root env loader and `DEV_*` options have been removed. Move
`DEV_FRONTEND_HOST/PORT` to `frontend/.env.local` as `FRONTEND_HOST/PORT`,
`DEV_BACKEND_HOST/PORT` to `backend/.env.local` as `BACKEND_HOST/PORT`, and
`AI_CODER_*` settings to `backend/.env.local`. API and CORS URLs are now explicit;
root `.env` files are not read. Launcher startup/shutdown timeout settings and
`DEV_PYTHON` are no longer used; choose Python when creating the backend venv.

Tests: see each project's README. `backend/e2e/run.sh` runs the existing real
frontend/backend browser checks separately from the development launcher.

## Workflow

1. Submit a software description and requirements.
2. Agents collaborate using MCP to generate application code and tests.
3. Retrieve the generated output and LLM usage report.
4. Run the application and tests.

## Documentation

| Document | Purpose |
| --- | --- |
| [Architecture](docs/architecture.md) | Mermaid MCP collaboration diagram, workspace design, and module layout |
| [Coordinator and feature TDD workflow](docs/coordinator-tdd.md) | Implemented chat entry point, agent responsibilities, and Red/Green routing |
| [API and MCP responsibilities](docs/interfaces.md) | Frontend endpoints, agent tools, and internal service boundaries |
| [Project requirements](docs/project-requirements.md) | Assignment requirements and demo deliverables |
| [Team responsibilities](docs/team-responsibilities.md) | Proposed ownership and initial implementation steps |

## File structure

```text
frontend/src/             # AI Coder UI and workspace-scoped API client
backend/src/ai_coder/
  api/                   # Workspace and generation endpoints
  orchestration/         # Agent execution flow
  agents/                # Planner, Coder, Tester
  mcp/                   # Client/server boundaries and tools
  workspaces/            # Workspace lifecycle and path scoping
  storage/               # Workspace/run persistence
  llm/                   # Model calls and usage tracking
backend/tests/           # Planned verification
workspaces/              # Ignored generated outputs, separated by workspace/run
docs/                    # Requirements, architecture, and ownership
```

See the [frontend notes](frontend/README.md) for UI boundaries and the
[workspace layout](workspaces/README.md) for runtime output organization.
