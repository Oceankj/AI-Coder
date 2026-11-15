# Team Responsibilities

[Back to README](../README.md)

## Proposed four-person ownership

Each member owns implementation and verification of their module. Human team roles are separate from runtime agent roles.

| Member | Responsibility | Deliverables |
| --- | --- | --- |
| 1 — Frontend | AI Coder UI | Requirements form, run status and error states, generated code and test output, downloads, LLM usage display |
| 2 — Backend & Orchestration | Generation API and agent coordination | Task lifecycle, agent roles and collaboration flow, result storage, shared LLM call and token accounting |
| 3 — MCP & Tools | MCP integration and execution environment | MCP servers/clients, file and command tools, workspace isolation, tool permissions and execution results |
| 4 — Generation & Testing | Code generation and verification | Implementation/testing agent prompts, executable test generation, test execution and repair flow, playlist acceptance cases |

## Integration responsibilities

- **Members 1 and 2:** agree on requirement submission, run status, result retrieval, errors, and usage fields.
- **Members 2 and 3:** define how agents exchange tasks and results through MCP and access tools.
- **Members 2 and 4:** integrate generation, testing, and repair; include all LLM calls, including retries, in usage totals.
- **Members 3 and 4:** connect generated files, build commands, and test execution to the workspace tools.
- **All members:** finalize playlist requirements, integrate the system, and prepare the presentation and demo.

## Initial implementation steps

1. Agree on supported application scope, technology stack, runtime agent roles, and collaboration pattern.
2. Define the AI Coder frontend/backend interface and MCP tool schemas.
3. Complete one generation run that returns code, tests, and usage totals.
4. Run the generated Music Playlist Mixer and tests against the agreed requirements.

Specific agent names, frameworks, and API routes remain design decisions.
