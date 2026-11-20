#!/usr/bin/env bash
# Keep the entry point independent of the caller's working directory.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "$PROJECT_DIR/scripts/dev.mjs" "$@"
