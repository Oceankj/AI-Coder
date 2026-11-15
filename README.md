# AI Coder

A final project to build a multi-agent system using the Model Context Protocol (MCP). Users submit a software description and requirements through a UI. The system generates executable application code and corresponding test cases, and reports LLM API call counts and total token usage.

**Music Playlist Mixer** is the selected demonstration application. Product requirements are supplied as input to the generation workflow.

## Status

Architecture scaffold. The repository contains requirements, module placeholders, and workspace/run context models. Agent execution, API endpoints, MCP integration, and workspace management are marked TODO.

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
