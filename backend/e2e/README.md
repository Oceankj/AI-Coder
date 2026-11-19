# Browser checks (frontend + backend)

These checks drive the **real frontend** (Vite dev server, MSW off) against the
**real backend** in Google Chrome. They complement the pytest suite in
`backend/tests/`, which tests the backend alone.

## Run

```bash
backend/e2e/run.sh
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
| Free ports 8000 and 5173 | Stop other dev servers first; the script refuses to start otherwise |

## Scenarios

| Script | Backend settings | Checks |
| --- | --- | --- |
| `workspaces.mjs` | Defaults | The list comes from the backend; a workspace created in the UI is trimmed, selected, shows its `rootPath`, and survives a reload |
| `run.mjs` | Placeholder Tester fails once | The panel shows agents working, then `Completed`; events include a repair and both features; files appear in the sidebar; file preview works; `index.html` renders in the preview iframe; the ZIP downloads |
| `failed-run.mjs` | Placeholder Tester always fails, 1 repair allowed | The panel shows `Failed ·` with the backend's reason; the run is failed with `activeRole` cleared; download is refused (409); feature 2 never started |
| `backend-down.mjs` | No backend | The UI shows a Retry button and no workspaces, and never falls back to MSW sample data |

Every scenario with a backend also checks that the page logged no console
errors and the API returned no unexpected errors. The Vite dev server's
missing `/favicon.ico` is ignored; it is unrelated to the backend.

## Not covered yet

The panel cannot submit requirements and has no download button yet (stage 4
frontend work), so `run.mjs` starts the run and downloads the ZIP through the
API, exactly as the frontend's `createRun` and `download` calls would. When
stage 4 adds those controls, switch these steps to clicking them.

## Files

| File | Purpose |
| --- | --- |
| `run.sh` | Starts the servers and runs every scenario |
| `common.mjs` | Shared helpers: browser launch, PASS/FAIL reporting, creating a workspace in the UI, starting a run, watching the panel status |
| `*.mjs` (others) | One scenario each; can also be run alone with `node` while both servers are running |
