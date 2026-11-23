<!-- Author: Ching Kao; Student ID: 85768427 -->
# Runtime Workspaces

Generated runtime data belongs here and is ignored by Git. The backend creates
and manages it through `FileStorage` (`backend/src/ai_coder/storage/`); the JSON
format of every file is in the
[backend specification](../docs/backend-spec.md#run-directory-files).

```text
workspaces/
  <workspaceId>/
    metadata.json
    project/           # Current application, tests, and workspace-local npm dependencies
    runs/
      <runId>/
        run.json       # Status, active role, error, checks, input
        artifacts/     # Packaged downloadable outputs
        events.jsonl   # Progress and tool execution events
        tasks.json     # Agent tasks and results
        checks.json    # Real test executions recorded by runChecks
        usage.json     # LLM calls and tokens for this run
```

Each workspace has one current project directory. New runs continue editing
that directory, including after a failed run; they do not copy files or restore
an earlier state. Runs keep separate status, events, checks, usage, and completed
ZIP outputs. Cross-workspace file access is not allowed. The backend and the MCP server subprocess share state
through these files; see "Shared files on disk" in the
[architecture](../docs/architecture.md). Checks select a fixed `node --test`
or Jest command from `package.json`, with a timeout and the architecture's
security checks.
After the first successful Architect setup, `project/.ai-coder-environment.json`
lets later runs bypass that planning call; setup errors consult Architect again.
When a project declares npm dependencies, setup keeps `node_modules/`,
`.npm-cache/`, and `.npm-home/` inside this `project/` directory. Jest also uses
`.ai-coder-jest-cache/` and `.ai-coder-jest-tmp/` there. Those runtime
directories are omitted from file listings and download ZIPs; the manifest and
lockfile are included so a download can run `npm ci --ignore-scripts`.
