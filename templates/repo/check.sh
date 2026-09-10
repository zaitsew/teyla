#!/usr/bin/env bash
# The first-run check: prints what's missing, verifies the toolchain, runs
# tests if any exist. Exits non-zero with a clear list if something is wrong.
#
#   ./check.sh
set -uo pipefail
cd "$(dirname "$0")"

# --- usage mode: real-usage counters, read by `teyla products` --------------
# Print key=value lines from the product's own store: rows logged, messages
# sent, sessions this week, active users. Zero is a finding, not an error.
case "${1:-}" in
  usage)
    # EDIT ME: replace with real counters, e.g.
    #   echo "items=$(sqlite3 data/app.db 'select count(*) from items')"
    echo "usage_probe=not_implemented"
    exit 0 ;;
esac

missing=()
warnings=()

# --- env vars listed in .env.example -----------------------------------
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
if [ -f .env.example ]; then
  while IFS= read -r line; do
    case "$line" in
      \#*|"") continue ;;
    esac
    var="${line%%=*}"
    [ -z "$var" ] && continue
    if [ -z "${!var:-}" ]; then
      missing+=("env: $var (see .env.example)")
    fi
  done < .env.example
fi

# --- toolchain -----------------------------------------------------------
if [ -f package.json ]; then
  command -v node >/dev/null 2>&1 || missing+=("toolchain: node (package.json present)")
  command -v npm  >/dev/null 2>&1 || missing+=("toolchain: npm (package.json present)")
fi
if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
  command -v python3 >/dev/null 2>&1 || missing+=("toolchain: python3")
fi
if [ -f Package.swift ] || ls -- *.xcodeproj >/dev/null 2>&1; then
  command -v swift >/dev/null 2>&1 || missing+=("toolchain: swift")
fi
if [ -f Cargo.toml ]; then
  command -v cargo >/dev/null 2>&1 || missing+=("toolchain: cargo")
fi

if [ "${#missing[@]}" -gt 0 ]; then
  echo "MISSING:"
  for m in "${missing[@]}"; do echo "  - $m"; done
  exit 1
fi

# --- tests, if any exist ---------------------------------------------------
ran_tests=0
if [ -f package.json ] && command -v npm >/dev/null 2>&1; then
  npm test && ran_tests=1 || { echo "npm test FAILED"; exit 1; }
fi
if { [ -f pyproject.toml ] || [ -d tests ]; } && command -v python3 >/dev/null 2>&1; then
  if python3 -m pytest --version >/dev/null 2>&1; then
    python3 -m pytest -q && ran_tests=1 || { echo "pytest FAILED"; exit 1; }
  fi
fi
if [ -f Package.swift ] && command -v swift >/dev/null 2>&1; then
  swift build && swift test && ran_tests=1 || { echo "swift test FAILED"; exit 1; }
fi

if [ "$ran_tests" -eq 0 ]; then
  warnings+=("no test runner found — nothing was actually run")
fi

echo "OK"
for w in "${warnings[@]}"; do echo "  note: $w"; done
exit 0
