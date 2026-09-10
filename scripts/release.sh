#!/usr/bin/env bash
# scripts/release.sh 0.7.1 — bump the three version strings, commit, tag, push.
# The release workflow runs the tests and creates the GitHub release; `teyla update`
# on every machine picks it up within a day (daily routine) or at the next session start.
set -euo pipefail
v="${1:?version, e.g. 0.7.1}"
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean"; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "release from main"; exit 1; }
sed -i '' "s/^version = \".*\"/version = \"$v\"/" pyproject.toml
sed -i '' "s/^__version__ = \".*\"/__version__ = \"$v\"/" src/teyla/__init__.py
sed -i '' "s/\"version\": \".*\"/\"version\": \"$v\"/" plugin/.claude-plugin/plugin.json
git add pyproject.toml src/teyla/__init__.py plugin/.claude-plugin/plugin.json
git commit -q -m "release $v"
git tag -a "v$v" -m "$v"
git push origin main "v$v"
echo "pushed v$v — the release workflow publishes it"
