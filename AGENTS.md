<!-- Author: Ching Kao; Student ID: 85768427 -->
# Coding Preferences and Project Boundaries

Apply these rules when implementing, reviewing, or extending this project.
The user values simple designs, clear ownership, and reuse of existing boundaries.

## Inspect before implementing

- Read the relevant code, interfaces, and handoff documents before adding a new
  client, service, adapter, recorder, or configuration loader.
- Trace the existing caller → shared service → provider path. Identify where the
  change belongs before editing; explain a material boundary change briefly.
- If the intended shared entry point is a stub, implement that entry point
  instead of bypassing it with a separate feature-specific path.
- Check the final wiring, not just whether the new feature works in isolation.

## Share infrastructure, keep workflow responsibilities clear

- Chat and agents may have different prompts and workflows. They must share the
  AI-call gateway, provider adapter, timeout handling, diagnostics, and normalized
  usage reporting. Do not build a second AI client for a new caller.
- For this project, the path is chat/real agent → `LLMGateway.complete` →
  `GeminiAdapter` → Google SDK. Only the provider adapter imports/calls the SDK.
- `RunRecorder` owns generation-run events and totals; it is not an AI client.
  Per-run accounting should consume normalized gateway results rather than
  implement another provider-call or token-counting path.
- Record AI calls at the shared gateway so callers outside HTTP are covered.
  HTTP access/request records are a separate concern; correlate them with IDs.
- Do not claim placeholder agents use Gemini or MCP. State exactly which paths
  are implemented, tested, or still pending.

## Prefer the smallest useful design

- Split modules by real responsibility, not merely to make files shorter.
- Share code when there is actual repeated behavior. A small amount of explicit
  code is preferable to a registry or generic pipeline built for hypothetical use.
- Do not introduce a reusable step framework just to launch two services.
- Avoid duplicate mechanisms, unnecessary layers, and one-function forwarding
  modules without a clear ownership or reuse benefit.
- Use Enum/StrEnum for shared, named closed sets (such as supported env names),
  rather than duplicating string lists between configuration and tests.
- Prefer named options when a factory has several settings. Large handler
  factories should visibly compose domain groups that share state explicitly.
- Keep cross-cutting HTTP middleware in its own module; the application entry
  point registers it and composes services/routes.

## Let each project own its startup and configuration

- The frontend owns its npm/Vite entry point, dependencies, and frontend env.
- The backend owns its Python entry point, dependencies, and backend env.
- The root launcher only selects/delegates to project entry points and manages
  their process lifecycles. It must not know internal dependency paths, merge
  project env files, or install each project's packages on its behalf.
- Put deployment-specific values such as host, port, model, credentials, timeout,
  and record locations in the owning project's env/configuration boundary.
  Keep defaults centralized. Do not turn every implementation constant into env.
- Shell overrides take priority. Do not silently override a project's local env
  or infer another project's API/CORS settings behind the user's back.

## Include observability in the initial implementation

- New external AI calls need success, failure, timeout, and cancellation records
  from the shared call boundary, with call/request IDs, model, duration and usage
  when available. Do not leave instrumentation as a later feature-specific fix.
- Preserve safe provider status/reason codes for diagnosis. Do not flatten every
  error into an unexplained 502 or silently discard diagnostic information.
- Never log API keys, authorization headers, or raw errors that may contain
  secrets. Diagnostic logs should contain metadata, not prompt/reply contents.
- Distinguish key received/configured, key accepted by the provider, and key
  persisted to disk. These are different states.
- Document where records live, their scope, when they begin, and what is not
  persisted. Do not promise recovery of requests that were never recorded.

## Verify behavior and explain evidence accurately

- Use meaningful tests at shared boundaries and real frontend/backend integration
  checks. Distinguish a real provider call from a stubbed provider test.
- Wait for explicit readiness or expected responses in integration tests;
  avoid fixed sleeps. Do not hide failures with blanket retries or longer timeouts.
- Measure before explaining slowness. Distinguish initialization, provider time,
  rendering, and test synchronization; label hypotheses as hypotheses.
- One failed diagnostic request does not invalidate a user's successful request.
  Correlate individual calls instead of generalizing from a single result.
- State limits of verification. Do not report all tests passing when only a
  subset passed, or claim drag/collapse is broken if the test failed before it ran.
- Prefer isolated test ports and temporary data so existing services and user
  workspaces remain usable. Never put real secrets in test fixtures or artifacts.
- Keep setup, env ownership/precedence, entry points, shared call flow, record
  locations, and known limitations documented alongside the owning project.

## Commit migration notes

When a Git commit is requested for an incompatible change, include a structured
`Migration` section with `Affected`, `Before`, `After`, `Steps`, `Verification`,
and `Rollback`. Name behavior-changing/removed CLI options, paths, schemas,
APIs, and machine-readable output. For durable file/data migrations, include
self-contained Bash commands with safety checks, verification, and rollback
that preserve existing data. Do not add a maintained migration command unless
the migration is complex/recurring or the user requests it.

## Shared memory

Use the personal memory MCP (`personcal_brain` / second-brain) for durable context
shared across agents. Retrieve relevant prior decisions when they could change
the answer; save explicit user preferences and confirmed useful outcomes. Keep
local continuity here, avoid duplicate unchanged memories, and never store
secrets. Claim a memory write succeeded only after the tool confirms success.
