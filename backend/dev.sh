#!/usr/bin/env bash
set -euo pipefail
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND_DIR"
if [ ! -x .venv/bin/python ]; then
  echo 'Missing backend/.venv. From backend/, run:' >&2
  echo '  python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"' >&2
  exit 1
fi
exec .venv/bin/python dev.py
