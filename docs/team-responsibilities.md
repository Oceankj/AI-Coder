<!-- Author: Ching Kao; Student ID: 85768427 -->
# Team Responsibilities (historical)

This records the original team plan. The current API and MCP contracts are in
[interfaces.md](interfaces.md).

[Back to README](../README.md)

Human team roles are separate from runtime agent roles. See the
[architecture](./architecture.md) for the agreed design.

## Relay order

The team works as a relay: one stage at a time. Each stage finishes its part,
documents the interfaces it owns, and hands off to the next stage.

```text
1. Ching (done) → 2. Pete → 3. Member A → 4. Ching → 5. Member B
```

## Stages

| Stage | Member | Responsibility | Deliverables |
| --- | --- | --- | --- |
| 1 | Ching | Frontend and design (done) | Agent Canvas, workspaces, file preview, API client and mocks, the [interfaces.md](./interfaces.md) contract, architecture scaffold |
| 2 | Pete | Backend core | FastAPI routes per `interfaces.md`; run directory storage (`run.json`, `tasks.json`, `events.jsonl`, `usage.json`); orchestrator that runs the Planner once, then Coder → Tester for each planned feature with a shared repair budget, using placeholder agents; run status and events; ZIP packaging |
| 3 | Member A | MCP layer and requirements | FastMCP server over stdio with the six tools (`submitResult` also accepts the Planner's `features` list); context bound at startup; path checks; role permissions (Tester cannot read application source); `runChecks` with `node --test` and a timeout; MCP client wrapper; **Playlist Mixer requirements document** |
| 4 | Ching | Make the agents run, connect the frontend | Gemini gateway (`google-genai`) with call/token accounting and 429 retry; fake LLM; agent tool loop; runnable Planner/Coder/Tester connected to the orchestrator (the Planner submits a feature list; the Coder builds one feature at a time on existing code); one complete pipeline on the fake LLM; frontend submission, usage display, MCP call events, download |
| 5 | Member B | Make the agents good, verify, demo | Planner/Coder/Tester prompts tuned on Gemini until the generated Playlist Mixer passes its tests; repair loop verified; backend tests (path escapes, workspace isolation, usage totals); demo script and recorded backup demo |

The presentation is shared: each member presents their own part.

## Handoffs

The upstream stage defines and documents the interface; the downstream stage
builds on it as written.

| From | Hands off | To |
| --- | --- | --- |
| 1 — Ching | HTTP API contract (`interfaces.md`, done) | 2 — Pete |
| 2 — Pete | Run directory layout and JSON formats of `run.json`, `tasks.json`, `events.jsonl`, `usage.json` | 3 — Member A, 4 — Ching |
| 2 — Pete | Orchestrator → agent interface; how events and usage are recorded | 4 — Ching |
| 3 — Member A | MCP tool schemas and client wrapper | 4 — Ching |
| 3 — Member A | Playlist Mixer requirements as checkable rules | 5 — Member B |
| 4 — Ching | Complete pipeline on the fake LLM; how to switch to Gemini | 5 — Member B |
| 5 — Member B | Final system, test results, demo script, and recorded backup demo | All members (presentation and demo) |

## Working rules

- Each stage has a deadline. If a stage runs late, hand off the parts that
  already run rather than blocking the next stage.
- A handoff is only as good as its documentation: the next stage builds on what
  is written down.
- Each member uses their own AI Studio key in an uncommitted `.env`
  (`GEMINI_API_KEY`). Never commit keys.
- Use the fake LLM while developing the pipeline; call Gemini only when tuning
  prompts or testing end to end.
- Before the demo, leave the demo key's daily quota unused and record a backup
  demo video.
