<!-- Author: Ching Kao; Student ID: 85768427 -->
# LangChain and LangGraph code guide

This guide maps the running implementation to its files. For the user-facing flow and its two diagrams, see [Coordinator and feature TDD workflow](coordinator-tdd.md).

## Reading order

| Read | File | Responsibility |
| --- | --- | --- |
| 1 | `backend/src/ai_coder/api/chat.py` and `agents/coordinator.py` | Chat entry point and LangChain Coordinator. The Coordinator interprets intent and calls `startRun`, `getRun`, or `resumeRun` through `RunService`. It runs outside the TDD graph. |
| 2 | `backend/src/ai_coder/orchestration/runs.py` and `scheduler.py` | Create or resume a run, then schedule it in the background. Runs in one workspace execute serially. |
| 3 | `backend/src/ai_coder/orchestration/tdd.py` | Build and execute the LangGraph state machine for one run. Own transitions, repair limits, saved continuation state, and final outcome. |
| 4 | `backend/src/ai_coder/agents/planner.py`, `tester.py`, and `coder.py` | Role prompts and structured Planner/Tester outputs. The Tester authors tests and later diagnoses results; the Coder writes application code. |
| 5 | `backend/src/ai_coder/agents/runtime.py` | Adapt the shared gateway to LangChain's chat model interface, run agent tool loops, and expose role-scoped MCP file tools. |
| 6 | `backend/src/ai_coder/workspaces/checks.py` | Execute the fixed Node test command and return recorded evidence. The graph calls this service directly; it is not an LLM role. |
| 7 | `backend/src/ai_coder/llm/gateway.py`, `llm/gemini.py`, `llm/groq.py`, and `storage/repository.py` | Shared AI call recording/provider boundary and durable run data. |

## How `tdd.py` fits together

`TDDWorkflow.run(context)` creates a `TDDRun` for that run. `TDDRun.build_graph()` declares nodes and transitions; `execute()` loads the initial or saved continuation state, streams the graph, then packages and reports a successful run or records a blocker/failure.

The graph state contains the spec, ordered features, current feature index, most recent test execution, Tester assessment, optional clarification, and next route. This state is also the continuation saved for a blocked run. Keep its persisted field names stable when changing the code.

| Node or method | Work |
| --- | --- |
| `plan` | Ask the Planner for the spec and features. After clarification, revise only the current feature. |
| `tests` | Ask the Tester to write executable black-box tests for the current feature. |
| `red` and `green` | Call the same deterministic `run_checks` service and store its result in graph state. Red runs before implementation; Green runs after each Coder change. |
| `red_review` and `diagnose` | Ask the Tester to interpret a specific runner result. `route_assessment` checks that diagnosis against the evidence; `assess` enforces the shared repair budget and records the route. |
| `code` | Ask the Coder to implement or repair the feature using the spec, tests, and recorded failure. |
| `advance` | Mark the current feature complete and move to the next one. |
| `pause` | Save the graph state and blocker so the same run can resume after clarification. |
| `run_agent` | Shared handoff for a Planner, Tester, or Coder invocation: record the active role/task, open scoped MCP tools, run the LangChain agent through `GatewayModel`, parse structured output when needed, and submit the result. |
| `report` | Ask the Coordinator to summarize the already recorded outcome. Reporting cannot change the verdict. |

The normal feature sequence is `plan → tests → red → red_review → code → green → advance`. The Red review can skip Coder only when the Tester reports adequate coverage and the recorded tests pass. Invalid tests return to `tests`. A failed Green run goes to `diagnose`, then returns to `code` or `tests` when supported by the evidence and repair budget. Blockers and contradictory diagnoses pause the run. After the final feature, `execute()` packages the project ZIP and marks the run complete.

LangGraph controls the order and routing. LangChain executes each model/tool conversation. `GatewayModel` sends every model call through `LLMGateway.complete`, which records calls and invokes the selected Gemini or Groq adapter. The graph's runner steps call `run_checks` directly. MCP file tools are scoped by role; storage records tasks, events, test executions, run status, and usage. These are separate responsibilities even when one node uses several of them.

## Readability boundaries

- The graph topology lives in `build_graph`; lifecycle, error handling, and packaging stay in `execute`.
- `route_assessment` is an evidence-only decision. `assess` applies the run's repair budget and writes the diagnostic event.
- Each role supplies an explicit event stage to `run_agent`; event text does not depend on parsing prompt punctuation.
- The graph state remains a small `TypedDict` of JSON-compatible values because blocked runs persist it. Planner and Tester model outputs use Pydantic where their structure is enforced.
- Add a new module only when it gains a separate responsibility. A new graph node does not automatically need a new agent or a new MCP tool.

The integration tests in `backend/tests/test_tdd_workflow.py` replace Google responses with deterministic fixtures while exercising the real graph, MCP processes, file writes, Node checks, clarification/resume, and download path.
