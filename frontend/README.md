# Agent Canvas

A runnable Vite + TypeScript frontend with no UI framework dependency.
The project UI is English, including accessible labels and error messages.
The canvas fills the viewport without a global brand/status header.
AI Coder tools use dark frosted glass surfaces and cyan/purple neon accents, with blur
on outer panels and translucent inner layers. Unsupported backdrop filters,
reduced transparency, or higher contrast preferences use opaque surfaces.
Live preview uses separate light chrome. The iframe retains the embedded project’s own styling.
Requires Node.js 20.19+ or 22.12+.

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173).

Frontend startup is owned by this project: `npm run dev` starts Vite using
`vite.config.ts`. It needs no Python or backend while MSW is enabled. The root
`../dev.sh frontend` delegates to this same command.

Copy `.env.example` to `.env.local` once to customize settings. Vite reads
`.env`, `.env.local`, `.env.development`, and `.env.development.local` for
development, with later files winning and shell variables taking priority.
Example files are templates, not loaded settings. No backend or root env file
is read. `FRONTEND_HOST` and `FRONTEND_PORT` configure the dev server (defaults
`127.0.0.1` and `5173`); `VITE_ENABLE_MSW` controls interception and
`VITE_API_BASE_URL` selects the API. Only `VITE_*` values are exposed to browser
code. Restart Vite after changing env files.

Run `npm ci` initially and after `package.json` or `package-lock.json` changes.
Startup does not install dependencies. If the configured port is occupied,
Vite exits instead of switching ports. Stop the existing service or change
`FRONTEND_PORT`; when using a real backend, update its CORS origins to match.

```bash
npm run build       # TypeScript check and production bundle
npm run preview     # Serve the production bundle
npx playwright install chromium  # Once, if no Playwright browser is installed
npm test            # Browser integration tests
```

## Canvas behavior

- Collapse the workspace sidebar with the panel button in the canvas toolbar.
- Expand/collapse each workspace and nested directory independently. Click a
  workspace name to switch its preview and drafts. Click a file to open a native
  modal; clicking outside, Escape or the close button dismisses it and restores focus.
- Workspace summaries, latest runs, file metadata and file content load through
  `src/api/client.ts` using the [documented API](../docs/interfaces.md).
  Development MSW handlers seed two workspaces from `src/mocks/fixtures/workspaces/`;
  UI modules never import these fixtures. The self-contained Playlist Mixer
  artifact is fetched through the file endpoint into the sandboxed iframe.
- **Create workspace** opens a name form and sends `POST /api/workspaces` with
  `{name}`. The backend owns ID allocation, root directory creation and storage.
  Only the returned workspace is added and selected; files are read through its
  workspace/run endpoints. There is no folder picker, upload or browser-created
  workspace ID. Pending submissions prevent duplicate POSTs; failures keep the
  name available for retry. Closing the dialog does not undo a submitted POST.
- File preview supports bounded UTF-8 text up to 2 MB. Shiki adds GitHub Dark
  syntax colors and line numbers for HTML, CSS, JS/TS, JSX/TSX, Python, JSON/JSONC,
  YAML, Markdown, Bash, Dockerfile and SQL. The highlighter and selected grammars
  load lazily on the first supported preview. Unknown formats, empty files, files
  above 100 KiB or 3,000 lines, and highlighting failures retain plain text.
  Line numbers are excluded from source text and hidden from screen readers.
  Token content is rendered using textContent, so HTML/scripts stay inert.
  Binary file preview requires a future API contract.
- Use **Set preview URL** (the code icon) to connect a running subproject's HTTP
  or HTTPS URL. URLs are scoped per workspace. The iframe cannot start a local
  development server. Workspaces can also preview a self-contained root
  `index.html` artifact with `srcdoc`.
- Embedded pages must permit iframe embedding. The sandbox allows scripts,
  forms and downloads, but isolates the embedded origin; storage/authentication
  features can be restricted. A persistent hint and open-in-new-tab action are
  available for URL previews. No successful app connection is inferred from an
  iframe load event.
- The Agent panel starts at the upper right. Drag its grip, resize its lower
  right corner, or use arrow keys on either handle. The entire header can be dragged, including
  when collapsed. Its purple top edge breathes gently; click the sparkle icon
  to pause/resume. Failed runs and task-status errors turn the light red; normal
  states restore purple. Reduced-motion preferences use a static glow.
  Its compact 40px header retains the selected project and task
  status. Every 3 seconds a shared watcher per workspace checks for runs.
  Active runs fetch detail and events using a per-run cursor; terminal runs
  reuse their final snapshot until new work appears,
  showing the active role/latest progress, queued, completed, failed or idle
  state. Sidebar rows show a loader only for queued/running work, including
  background workspaces; file counts are omitted. The header uses the selected
  workspace’s same status. Requests pause on page exit and resume on restoration;
  failures are explicit.
  Long text is truncated with the full value available on hover. Viewport changes
  clamp the panel back into view.
- Messages are explicitly **local drafts**, scoped per workspace and kept only
  for this browser tab session. No agent calls or simulated agent responses.

## Responsibilities and shared patterns

- `src/app.ts`: composition and view wiring only.
- `src/components/canvas-shell.ts`: layout and sidebar visibility.
- `src/features/workspaces/store.ts`: selection, subscriptions, run invalidation,
  request ownership, and page lifecycle.
- `src/features/workspaces/repository.ts`: workspace/run artifact reads. A failed
  `index.html` read returns a separate `previewError` while retaining the file list.
- `src/features/workspaces/sidebar.ts`: file-tree presentation and task indicators.
- `src/features/preview/`: iframe, URL connection and preview-specific states.
- `src/features/generation/`: conversation drafts and cursor-based task monitoring.
- `src/features/artifacts/`: safe file decoding, syntax tokens and source presentation.
- `src/api/client.ts`, `src/types/`: HTTP transport and wire types.
- `src/mocks/`: development MSW handlers and fixtures.

Shared components and patterns:

| Module | Reused responsibility |
| --- | --- |
| `components/dialog.ts` | Native modal, title, close action and optional backdrop dismissal |
| `components/input-dialog.ts` | Labeled single-field forms, validation, pending/error feedback and submit lifecycle |
| `components/floating-panel.ts` | Pointer/keyboard movement, resize and viewport clamping |
| `components/feedback.ts` | Loading/error/retry state and transient status notices |
| `core/latest-request.ts` | Cancel replaced reads and reject late results after awaits |
| `core/poll.ts` | Non-overlapping polling with cancellation and error handling |

Selection revalidates artifacts. A new run or run-status change invalidates its
cached output; the selected workspace refreshes automatically. **Reload preview**
reads the current run/files/HTML again, including changes within the same run.
Manual preview URLs and conversation drafts remain scoped view state. Closing a
file preview cancels its read; closing a submitted create form does not attempt
to undo a server mutation. Source selection preserves blank lines and its final
newline, with line numbers kept outside selectable code.

Workspace persistence, run orchestration, and usage reporting are implemented
in the backend (see [backend specification](../docs/backend-spec.md)); real
agent execution with Gemini is stage 4. Credentials/model execution stay on the
backend.

## Mock API and real backend

`npm run dev` enables MSW by default. `src/main.ts` awaits worker registration
before importing the application, so initial API calls are intercepted. Only
`src/mocks/` owns sample data. Handlers return real HTTP statuses, validate scope
and input, persist creates in memory, paginate events by cursor, and generate ZIP
archives from the same file store. State resets on page reload. Unknown API
requests fail loudly; Vite assets and external iframe requests pass through.

To use the backend, create `.env.local` from `.env.example` and set:

```dotenv
VITE_ENABLE_MSW=false
VITE_API_BASE_URL=http://localhost:8000/api
```

Restart Vite after changing environment variables. To start the backend, see
[Running the backend](../docs/backend-spec.md#running-the-backend). The backend
allows CORS from `http://127.0.0.1:5173` and `http://localhost:5173`. Otherwise
the backend must allow CORS from the frontend origin, or use a same-origin `/api` reverse proxy. There is no
fallback to sample data on backend failures. Production builds always use HTTP:
MSW and fixtures are excluded from the production JavaScript graph, even if
`VITE_ENABLE_MSW=true`. The inert generated worker file is copied as a public
asset, but production does not register or activate it.

Regenerate the service worker after upgrading MSW:

```bash
npx msw init public --save
```

`tests/api.spec.ts` uses the same handlers with MSW's Node integration to verify
create/read consistency, file metadata/content/ZIP consistency, workspace/run
isolation, validation, cancellation, and HTTP failures. Browser tests verify that
Canvas requests actually receive responses from the MSW service worker, plus
workspace creation, name validation, workspace switching and canvas interactions.
`tests/task-status.spec.ts` verifies cursor advancement, empty event batches,
terminal caching and new-run cursor reset. `tests/regressions.spec.ts` tests a
fresh production build (port 4173) using the same MSW Node boundary to serve the
documented API; it covers run transitions, explicit refresh, independent preview
failure, actual source selection and page lifecycle restoration.

## Main visual palette

AI Coder uses the supplied five-color palette, sampled and converted to sRGB:

| Token | Color | Use |
| --- | --- | --- |
| Midnight | `#080B14` | Canvas and inset backgrounds |
| Navy | `#12172B` | Main tool surfaces |
| Slate | `#242B45` | Raised surfaces |
| Cyan | `#24D3EE` | Sparse focus and running indicators |
| Purple | `#A88BFA` | Primary actions, selection, AI identity and panel glow |

Opacity and color mixtures derive from these tokens. Neutral text and semantic
error colors remain available for readability. Borders and interaction glows
reference the ai-job-search desktop design; Live preview and syntax-token colors
retain their independent themes.
