# AI Coder Frontend

Framework selection and executable frontend setup are TODO. `src/` contains
module placeholders and shared view models only.

- `features/workspaces/`: list, create, and select workspaces.
- `features/generation/`: submit descriptions/requirements and show run progress.
- `features/artifacts/`: browse and download generated code/tests.
- `features/usage/`: show API calls and token totals for the selected run.
- `api/`: workspace-scoped backend access.

Switching workspaces must reset selected runs and scope cached responses,
subscriptions, artifacts, and usage to the selected workspace. API credentials
and model execution belong in the backend.
