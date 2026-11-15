# Runtime Workspaces

Generated runtime data belongs here and is ignored by Git. Directory creation,
persistence, locking, and sandbox execution are TODO.

```text
workspaces/
  <workspaceId>/
    metadata.json
    runs/
      <runId>/
        project/       # Generated application and tests
        artifacts/     # Packaged downloadable outputs
        events.jsonl   # Progress and tool execution events
        tasks.json     # Agent tasks and results
        usage.json     # LLM calls and tokens for this run
```

Each workspace can contain multiple runs. Runs have independent project roots;
agents participating in one run share that run's project. Cross-workspace file
access is not allowed. A directory alone is not a security sandbox: command
execution must use the sandbox boundary described in the architecture document.
