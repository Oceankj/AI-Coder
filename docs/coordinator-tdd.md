<!-- Author: Ching Kao; Student ID: 85768427 -->
# Coordinator and feature TDD workflow

Workspace chat invokes the LangChain Coordinator. The production backend schedules a LangGraph StateGraph for each development run. Planner, Tester, Coder and Coordinator all share the instrumented Gemini gateway.

## From chat to a run

```mermaid
flowchart TD
    user["User enters a request in chat"] --> coord{"Coordinator agent interprets intent"}
    coord -->|"Conversation or clarification"| reply["Coordinator replies or asks a question"]
    reply --> user
    coord -->|"Progress request"| query["getRun reads the selected run"]
    query --> reply
    coord -->|"Answer to a blocked run"| resume["resumeRun saves clarification against the same run ID"]
    resume --> plan
    coord -->|"Development request is clear"| start["startRun creates and schedules a run"]
    start --> ack["Coordinator acknowledges the request with its run ID"]
    start --> plan["Planner agent defines the spec, acceptance criteria and ordered features"]
    plan --> loop["LangGraph runs the TDD cycle for each feature"]
    loop --> result["Backend records the outcome or blocker"]
    result --> notify["Coordinator reports back to the user"]
```

The chat can clarify a request before a workspace is selected. Starting a run binds it to a workspace. If a run needs clarification, the Coordinator attaches the user's answer to that run ID. The Planner revises the spec and the graph resumes the affected feature.

## One feature from Red to Green

```mermaid
flowchart TD
    spec["LangGraph passes the feature spec and acceptance criteria"]
    spec --> write["Tester agent designs cases and writes tests with writeFile"]
    write --> before["Runner executes the suite and records the pre-implementation result"]
    before --> review["Tester agent compares the actual result with the spec"]
    review --> redRoute{"LangGraph routes the Tester's assessment"}
    redRoute -->|"Feature is missing as expected: Red"| code["Coder agent reads the spec, tests and failure, then writes application code"]
    redRoute -->|"Test is invalid or misses a criterion"| write
    redRoute -->|"Already passing and criteria verified"| done["LangGraph completes the feature"]
    redRoute -->|"Unclear spec or environment blocker"| pause["Record the blocker and notify the Coordinator"]
    code --> after["Same runner executes new and regression tests and records the result"]
    after --> greenRoute{"LangGraph checks the runner result"}
    greenRoute -->|"All required tests pass: Green"| done
    greenRoute -->|"Failure or execution error"| diagnose["Tester agent diagnoses this execution"]
    diagnose --> fixRoute{"LangGraph applies the diagnosis and repair limit"}
    fixRoute -->|"Implementation defect and budget available"| code
    fixRoute -->|"Test defect"| write
    fixRoute -->|"Blocker, unknown cause or budget exhausted"| pause
```

Both runner nodes execute a fixed test command without an LLM. Each hands the next agent a recorded execution from the same run and feature. A failing assertion about required behavior can establish Red. A missing test runtime is an environment blocker. During implementation repairs the Coder changes application code and reruns the same tests. The Tester revises tests only when the diagnosis identifies a defect in the tests or the spec changes.

## Running and verifying the workflow

Use Node.js 22.13+ for the runner. Install the backend dependencies, start both services with MSW disabled, select a workspace, and configure Gemini in the chat panel. A small development request is “Implement a CommonJS module that exports add(a, b). It must add two integers.” Progress and the final Coordinator report appear in that conversation. A blocked run accepts clarification in the same chat.

Each run stores role handoffs in `tasks.json`, Node executions in `checks.json`, and routing decisions and Coordinator reports in `events.jsonl`. The runner executes the entire project suite at both checkpoints. A blocked run keeps the current feature and spec in `run.json` across backend restarts. An interrupted active run is marked failed on startup. Completed runs expose their project ZIP through the download API.

The graph gives workers only the MCP file tools needed for their phase. Planner and diagnosis can list and read, Tester authors test files, and Coder writes implementation files. MCP enforces role-specific path permissions. LangGraph publishes tasks and records submissions through the existing storage service. Both test nodes call the same execution service as the MCP `runChecks` tool.

Run `backend/e2e/run.sh chat-run` for the Chrome walkthrough, or run `.venv/bin/python -m pytest tests/test_tdd_workflow.py` from `backend/` for the chat API, clarification/resume, repair and ZIP checks. Both tests substitute deterministic Gemini responses and execute the real graph, MCP processes, file writes and Node tests.
