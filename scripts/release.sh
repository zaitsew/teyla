#!/usr/bin/env bash
# scripts/release.sh 0.7.1 — bump the three version strings, commit, tag, push.
# The release workflow runs the tests and creates the GitHub release; `teyla update`
# on every machine picks it up within a day (daily routine) or at the next session start.
set -euo pipefail
v="${1:?version, e.g. 0.7.1}"
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean"; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "release from main"; exit 1; }
git pull -q --ff-only origin main
cur=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
# Refuse to go backwards: two sessions releasing on the same day must not undo each other.
newest=$(printf '%s\n%s\n' "$cur" "$v" | sort -V | tail -1)
[ "$newest" = "$v" ] && [ "$v" != "$cur" ] || { echo "main is already $cur; $v is not newer"; exit 1; }
sed -i '' "s/^version = \".*\"/version = \"$v\"/" pyproject.toml
sed -i '' "s/^__version__ = \".*\"/__version__ = \"$v\"/" src/teyla/__init__.py
sed -i '' "s/\"version\": \".*\"/\"version\": \"$v\"/" plugin/.claude-plugin/plugin.json
git checkout -q -b "release-$v"
git add pyproject.toml src/teyla/__init__.py plugin/.claude-plugin/plugin.json
git commit -q -m "release $v"
git push -q -u origin "release-$v"
# One PR per logical unit, merged not squashed — a release bump is a unit like any other.
gh pr create --title "release $v" --body "Version bump only. The tag on the merge commit triggers the release workflow." >/dev/null
gh pr merge --merge --delete-branch
git checkout -q main && git pull -q --ff-only
git tag -a "v$v" -m "$v"
git push origin "v$v"
echo "merged the bump and pushed v$v — the release workflow publishes it"
