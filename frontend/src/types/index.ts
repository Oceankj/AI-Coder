// Proposed view models, not a finalized API contract.
export interface RunContext {
  workspaceId: string;
  runId: string;
}

export interface GenerationInput {
  workspaceId: string;
  description: string;
  requirements: string[];
}

export interface WorkspaceSummary {
  id: string;
  name: string;
}

// TODO: Define run states, events, artifacts, errors, and usage with backend.
