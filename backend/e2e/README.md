# Browser checks (frontend + backend)

These checks drive the **real frontend** (Vite dev server, MSW off) against the
**real backend** in Google Chrome. They complement the pytest suite in
`backend/tests/`, which tests the backend alone.

## Run

```bash
backend/e2e/run.sh           # All scenarios
backend/e2e/run.sh chat-run  # Only chat to verified ZIP
```

One command starts the frontend, starts the backend once per scenario with that
scenario's settings, runs the scenario, and stops everything. Runtime data goes
to a temporary folder and is deleted afterwards. The exit code is 0 only if
every check passed.

Requirements (one-time):

| Requirement | How |
| --- | --- |
| Backend virtual environment | See [docs/backend-spec.md](../../docs/backend-spec.md#running-the-backend) |
| Frontend packages (Playwright comes from here) | `npm ci` in `frontend/` |
| Google Chrome | Installed normally. Or use Playwright's Chromium: `npx playwright install chromium` in `frontend/`, then `E2E_BROWSER_CHANNEL=bundled backend/e2e/run.sh` |
| Free test ports 18081 and 15174 | Stop other dev servers first; the script refuses to start otherwise |

## Scenarios

| Script | Backend settings | Checks |
| --- | --- | --- |
| `workspaces.mjs` | Defaults | The list comes from the backend; a workspace created in the UI is trimmed, selected, shows its `rootPath`, and survives a reload |
| `blocked-run.mjs` | Scripted Gemini, zero repairs | The chat shows the budget blocker, the active role clears, and download returns 409 |
| `chat-run.mjs` | Production graph with scripted Gemini responses | Send through the chat bar, see the final Coordinator report, observe real Red/repair/Green executions and download the generated ZIP |
| `backend-down.mjs` | No backend | The UI shows a Retry button and no workspaces, and never falls back to MSW sample data |

The chat scenario submits through the UI and replaces only Google's responses. ZIP downloads are verified through the HTTP API.

## Files

| File | Purpose |
| --- | --- |
| `run.sh` | Starts the servers and runs every scenario |
| `common.mjs` | Shared helpers: browser launch, PASS/FAIL reporting, creating a workspace in the UI |
| `*.mjs` (others) | One scenario each; can also be run alone with `node` while both servers are running |
