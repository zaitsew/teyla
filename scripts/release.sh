#!/usr/bin/env bash
# scripts/release.sh 0.7.1 — in a temporary clean worktree at origin/main: run ./check.sh, move
# "## Unreleased" of CHANGELOG.md under a dated version heading, bump the version strings (package, plugin, listing, apps), commit, tag,
# push, and create the GitHub release from this laptop (POLICY §10: no Actions). `teyla
# update` on every machine picks it up within a day (daily routine) or at the next session
# start; it reads releases/latest, so the release — not only the tag — must exist.
set -euo pipefail
v="${1:?version, e.g. 0.7.1}"
# The release runs in a temporary clean worktree at origin/main, never in the caller's checkout:
# that checkout often holds another tool's uncommitted files, and none of them may block a release
# or leak into it. The caller's branch and working tree are not touched.
home="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$home" fetch -q origin main || { echo "cannot fetch origin/main"; exit 1; }
git -C "$home" rev-parse --verify -q origin/main >/dev/null || { echo "cannot resolve origin/main"; exit 1; }
tmp="$(mktemp -d "${TMPDIR:-/tmp}/teyla-release.XXXXXX")"
cleanup() {
  cd "$home" 2>/dev/null || true
  git -C "$home" worktree remove --force "$tmp/wt" >/dev/null 2>&1 || true
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT
git -C "$home" worktree add -q --detach "$tmp/wt" origin/main
cd "$tmp/wt"
./check.sh
cur=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
# Refuse to go backwards: two sessions releasing on the same day must not undo each other.
newest=$(printf '%s\n%s\n' "$cur" "$v" | sort -V | tail -1)
[ "$newest" = "$v" ] && [ "$v" != "$cur" ] || { echo "main is already $cur; $v is not newer"; exit 1; }
# Everything under "## Unreleased" becomes the notes of this release (refused when it is empty).
python3 scripts/changelog_release.py CHANGELOG.md "$v" "$(date +%F)"
sed -i '' "s/^version = \".*\"/version = \"$v\"/" pyproject.toml
sed -i '' "s/^__version__ = \".*\"/__version__ = \"$v\"/" src/teyla/__init__.py
sed -i '' "s/\"version\": \".*\"/\"version\": \"$v\"/" plugin/.claude-plugin/plugin.json
sed -i '' "s/^| Version | .* |$/| Version | $v |/" docs/DIRECTORY.md   # the listing pack quotes the manifest's version
# The install lines of the quick start name the release tag, so a stranger gets the release `teyla update` follows
# and not whatever main holds. The tag itself is pushed below, after the bump merges.
sed -i '' -E "s#(git\+https://github\.com/zaitsew/teyla)(@v[0-9][0-9.]*)?([^A-Za-z0-9@/._-]|$)#\1@v$v\3#g" \
  README.md AGENTS.md docs/GUIDE.md site/public/index.html
# The apps carry the release version too, so TestFlight and the Mac show the same number as the CLI.
# Build numbers (CURRENT_PROJECT_VERSION) stay a separate, per-upload bump.
sed -i '' -E "s/^( +CFBundleShortVersionString: )\"[^\"]*\"/\\1\"$v\"/" apps/ios/project.yml apps/mac/project.yml
git checkout -q -b "release-$v"
git add CHANGELOG.md pyproject.toml src/teyla/__init__.py plugin/.claude-plugin/plugin.json docs/DIRECTORY.md \
  README.md AGENTS.md docs/GUIDE.md site/public/index.html \
  apps/ios/project.yml apps/mac/project.yml
git commit -q -m "release $v"
git push -q -u origin "release-$v"
# One PR per logical unit, merged not squashed — a release bump is a unit like any other.
gh pr create --title "release $v" --body "Version bump only. The tag on the merge commit is released from the laptop by scripts/release.sh." >/dev/null
# No --delete-branch: gh would then switch this worktree to local main, which git refuses when main is
# checked out in another worktree. The PR would merge and the script would stop before the tag.
if ! gh pr merge --merge; then
  state=$(gh pr view "release-$v" --json state --jq .state 2>/dev/null || true)
  [ "$state" = "MERGED" ] || { echo "the release PR was not merged (state: ${state:-unknown})"; exit 1; }
fi
# The remote branch is deleted explicitly; a failure here only leaves a stale branch behind.
git push -q origin --delete "release-$v" || echo "note: could not delete origin/release-$v"
git fetch -q origin main && git checkout -q --detach origin/main
git branch -D "release-$v" >/dev/null 2>&1 || true
git tag -a "v$v" -m "$v"
git push origin "v$v"
[ "$(PYTHONPATH=src python3 -m teyla --version)" = "$v" ] || { echo "package version is not $v"; exit 1; }
gh release create "v$v" --title "$v" --generate-notes
echo "merged the bump, pushed v$v and created the release"
# Install the release on this Mac the way every other machine gets it. `teyla update` keeps the
# installed extras (work = truststore, reel = Pillow); a bare `uv tool install --force git+...`
# drops them, and 0.47.0 lost the daily video that way. The release exists already, so a failed
# install only warns.
if command -v teyla >/dev/null; then
  teyla update || echo "release v$v is out, but installing it here failed: run \`teyla update\`"
fi
