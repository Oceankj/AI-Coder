# Runtime Workspaces

Generated runtime data belongs here and is ignored by Git. Directory creation,
persistence, and check execution are TODO.

```text
workspaces/
  <workspaceId>/
    metadata.json
    runs/
      <runId>/
        run.json       # Status, active role, error, checks, input
        project/       # Generated application and tests
        artifacts/     # Packaged downloadable outputs
        events.jsonl   # Progress and tool execution events
        tasks.json     # Agent tasks and results
        checks.json    # Real test executions recorded by runChecks
        usage.json     # LLM calls and tokens for this run
```

Each workspace can contain multiple runs. Runs have independent project roots;
agents participating in one run share that run's project. Cross-workspace file
access is not allowed. The backend and the MCP server subprocess share state
through these files; see "Shared files on disk" in the
[architecture](../docs/architecture.md). Checks run only the fixed
`node --test` command with a timeout, as described in the architecture's
security checks.
