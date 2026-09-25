#!/usr/bin/env bash
# The gate (POLICY §10): what CI used to run, on this laptop. scripts/release.sh runs it;
# run it before pushing.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { uv venv -q && uv pip install -q -e . pytest; }
PYTHONPATH=src .venv/bin/python -m pytest -q
