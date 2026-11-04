#!/usr/bin/env bash
# The gate (POLICY §10): what CI used to run, on this laptop. scripts/release.sh runs it;
# run it before pushing.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { uv venv -q && uv pip install -q -e '.[reel]' pytest; }
# Private data and non-English text must never reach this public repo: see CONTRIBUTING.md.
PYTHONPATH=src .venv/bin/python scripts/leak_check.py
# The web review package (packages/review-web): type check and unit tests. The pytest run below builds
# its fixture with Vite, so the dependencies must be installed; a Mac without node skips both.
if command -v npm >/dev/null 2>&1; then
  [ -d packages/review-web/node_modules ] || (cd packages/review-web && npm ci --silent)
  (cd packages/review-web && npm run --silent check)
fi
PYTHONPATH=src .venv/bin/python -m pytest -q
