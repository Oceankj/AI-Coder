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
    project/           # Current application and tests, shared by runs
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
[architecture](../docs/architecture.md). Checks run only the fixed
`node --test` command with a timeout, as described in the architecture's
security checks.
