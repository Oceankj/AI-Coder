# Agent Canvas

A runnable Vite + TypeScript frontend with no UI framework dependency.
The project UI is English, including accessible labels and error messages.
The canvas fills the viewport without a global brand/status header.
AI Coder tools use dark slate surfaces and violet accents; Live preview uses
separate light chrome. The iframe retains the embedded project’s own styling.
Requires Node.js 20.19+ or 22.12+.

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173).

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
  modal; Escape or the close button dismisses it and restores focus.
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
- File preview supports bounded UTF-8 text up to 2 MB. HTML and SVG source are
  displayed as text. Binary file preview requires a future API contract.
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
  right corner, or use arrow keys on either handle. Position and size dropdowns
  provide click/tap alternatives. Collapse keeps the movable title bar visible.
  Viewport changes clamp it back into view.
- Messages are explicitly **local drafts**, scoped per workspace and kept only
  for this browser tab session. No agent calls or simulated agent responses.

## Modules

- `src/app.ts`: canvas shell, selection, iframe and URL controls.
- `src/features/workspaces/`: workspace creation form, view model and file tree.
- `src/features/artifacts/`: read-only file preview dialog.
- `src/features/generation/`: floating draft conversation panel.
- `src/api/client.ts`: typed Fetch client for all documented HTTP routes.
- `src/mocks/`: development MSW worker, stateful handlers and fixture files.
- `src/types/index.ts`: JSON wire contract shared by client and handlers.
- `src/features/usage/`: usage UI integration placeholder.

Actual workspace persistence, agent execution and usage reporting remain backend
work. Requests carry workspace/run IDs. Workspace switches abort pending loads;
closing a file dialog aborts its pending request. The UI handles loading, empty,
and error states and offers retries. Credentials/model execution stay on the backend.

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

Restart Vite after changing environment variables. The backend must allow CORS
from the frontend origin, or use a same-origin `/api` reverse proxy. There is no
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
