# AI Coder

A final project to build a multi-agent system using the Model Context Protocol (MCP). Users submit a software description and requirements through a UI. The system generates executable application code and corresponding test cases, and reports LLM API call counts and total token usage.

**Music Playlist Mixer** is the selected demonstration application. Product requirements are supplied as input to the generation workflow.

## Status

The team works as a relay ([team responsibilities](docs/team-responsibilities.md)).

| Stage | Part | Status |
| --- | --- | --- |
| 1 | Frontend: Agent Canvas with workspace file trees, file preview, live preview iframe, and the agent panel ([frontend setup](frontend/README.md)) | Done |
| 2 | Backend core: all HTTP routes, run storage, feature-by-feature orchestrator, placeholder agents ([backend specification](docs/backend-spec.md), [handoff](docs/stage2-handoff.md)) | Done |
| 3 | MCP server and tools, MCP client for agents ([tool contract](docs/interfaces.md#agent-mcp-tools), [handoff](docs/stage3-handoff.md)) | Done; Playlist Mixer requirements still open |
| 4 | Gemini gateway and real agents; frontend submission and download | To do |
| 5 | Prompt tuning, verification, demo | To do |

The frontend and backend already run together end to end: a run goes through
the Planner, then Coder → Tester for each feature, and its files, preview, and
download appear in the UI. The agents are placeholders that write fixed
content until stage 4.

### Quick start

```bash
# Backend (Python 3.11+), from backend/
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn ai_coder.main:create_app --factory --app-dir src --port 8000

# Frontend against the real backend, from frontend/
npm ci
VITE_ENABLE_MSW=false VITE_API_BASE_URL=http://localhost:8000/api npm run dev
```

Tests: `.venv/bin/python -m pytest` in `backend/`, and `backend/e2e/run.sh`
for the browser checks.

## Workflow

1. Submit a software description and requirements.
2. Agents collaborate using MCP to generate application code and tests.
3. Retrieve the generated output and LLM usage report.
4. Run the application and tests.

## Documentation

| Document | Purpose |
| --- | --- |
| [Architecture](docs/architecture.md) | Mermaid MCP collaboration diagram, workspace design, and module layout |
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
