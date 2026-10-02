#!/bin/sh
# Stop: notice work that never reached a remote, once per session — opt-in
# (`teyla config set hooks.land_check=true`).
#
# "Land work one PR per logical unit" is already in the owner's CLAUDE.md, and it mostly works.
# What it cannot cover is the end of a session: the model finishes, the turn ends, and a branch
# with real commits sits on the laptop until somebody remembers. An instruction that has to be
# remembered at exactly the moment attention is leaving is the one that fails; this runs whether
# or not anyone remembers it.
#
# Deliberately NOT a block. Blocking every session end would make it something you disable in a
# week, and plenty of sessions legitimately end mid-thought. It states the fact once, as
# additionalContext the model sees, and gets out of the way.
#
# What it says about merging comes from the `MERGE-APPROVED REPOS` block of ~/.claude/CLAUDE.md
# (inside a ``` fence, one `owner/repo` per line, first word): a repo on it is "open the PR/MR
# and merge it"; anything else — including no list, no origin, a repo merely writable — is
# "open the PR/MR and STOP". Until 2026-08-16 the ~/ops version said "merged without being
# asked" with no qualification, the one thing the standing rule does not say; until 2026-10-02
# it read a mirror of the list that had fallen seven repos behind. So: the one file, read now.
# The slug is origin's path, from GitHub or GitLab, ssh or https, nested GitLab groups whole
# (`group/sub/repo`), compared case-insensitively.
#
# Ported to sh from the owner's ~/ops/bin/land-work-check.mjs: the work MacBook has no Node,
# and needs no Python for this either.
#
#   (none)    Claude Code Stop: {"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":…}}
#   --codex   Codex Stop (~/.codex/hooks.json, written by `teyla harness sync` when the key is
#             on): {"systemMessage": …}, the field Codex documents for Stop. A `codex exec`
#             batch run (rollout originator "codex_exec") gets nothing: a script wrote its
#             prompt, and a review lane is not the place to open a PR.
#
# Off costs one awk over ~/.teyla/config.toml (none at all without the file). Every failure
# exits 0 with nothing printed.

mode="${1:-}"
cfg="$HOME/.teyla/config.toml"
[ -f "$cfg" ] || exit 0
awk '
  /^[ \t]*\[/ { t = $0; sub(/#.*/, "", t); gsub(/[ \t]/, "", t); inside = (t == "[hooks]"); next }
  inside {
    line = $0; sub(/#.*/, "", line); n = index(line, "="); if (!n) next
    k = substr(line, 1, n - 1); v = substr(line, n + 1)
    gsub(/[ \t"\047]/, "", k); gsub(/[ \t"\047\r]/, "", v)
    if (k == "land_check") { v = tolower(v); on = (v == "true" || v == "1" || v == "yes" || v == "on") }
  }
  END { exit on ? 0 : 1 }' "$cfg" 2>/dev/null || exit 0

{
  payload=$(cat)
  field() { printf '%s' "$payload" | sed -n "s/.*\"$1\" *: *\"\([^\"]*\)\".*/\1/p" | head -n 1; }

  if [ "$mode" = "--codex" ]; then
    transcript=$(field transcript_path)
    if [ -n "$transcript" ] && [ -f "$transcript" ] && head -c 8192 "$transcript" | grep -q '"originator" *: *"codex_exec"'; then
      exit 0
    fi
  fi

  # /usr/bin/git on a Mac without the developer tools pops an install dialog instead of running.
  command -v git >/dev/null || exit 0
  if [ "$(command -v git)" = /usr/bin/git ] && [ "$(uname)" = Darwin ]; then
    xcode-select -p >/dev/null 2>&1 || exit 0
  fi

  cwd=$(field cwd)
  [ -n "$cwd" ] && [ -d "$cwd" ] || cwd="$PWD"
  # Once per session. A hook that repeats itself every turn is noise, and noise is what gets a
  # hook uninstalled. The id is payload input: only [A-Za-z0-9_-] reaches the file name.
  sid=$(field session_id | tr -cd 'A-Za-z0-9_-')
  [ -n "$sid" ] || sid=unknown
  stamps="${TMPDIR:-/tmp}/teyla-land-check"
  [ -f "$stamps/$sid" ] && exit 0

  g() { git -C "$cwd" --no-optional-locks "$@"; }
  [ "$(g rev-parse --is-inside-work-tree)" = true ] || exit 0
  branch=$(g branch --show-current)
  [ -n "$branch" ] || branch="detached HEAD"
  dirty=$(g status --porcelain | grep -c .)
  # Commits that exist here and on no remote. `--remotes` rather than a named upstream: a branch
  # with no upstream is not a branch whose commits are missing. HEAD is not optional: with no
  # remote refs at all, `log --not --remotes` names no positive ref, walks nothing and reports
  # "all pushed" for exactly the repo most at risk, one never pushed anywhere (0 without HEAD,
  # 1 with it).
  unpushed=$(g log --oneline HEAD --not --remotes | grep -c .)
  [ "${dirty:-0}" -eq 0 ] && [ "${unpushed:-0}" -eq 0 ] && exit 0

  mkdir -p "$stamps" && : > "$stamps/$sid"

  parts=""
  [ "$unpushed" -gt 0 ] && parts="$unpushed commit$([ "$unpushed" -gt 1 ] && echo s) on no remote"
  if [ "$dirty" -gt 0 ]; then
    [ -n "$parts" ] && parts="$parts, "
    parts="${parts}$dirty uncommitted file$([ "$dirty" -gt 1 ] && echo s)"
  fi

  # owner/repo from origin: https://host/a/b(.git), ssh://git@host:22/a/b, git@host:a/b, host:a/b.
  slug=$(g remote get-url origin | sed -e 's#^[A-Za-z][A-Za-z0-9+.-]*://[^/]*/##' -e 's#^[^@/]*@[^:/]*:##' \
         -e 's#^[^/]*:##' -e 's#/*$##' -e 's#\.git$##')
  approved=""
  if [ -n "$slug" ] && [ -f "$HOME/.claude/CLAUDE.md" ]; then
    want=$(printf '%s' "$slug" | tr 'A-Z' 'a-z')
    awk -v want="$want" '
      /^[ \t]*```/ { fence = !fence; block = 0; next }
      fence && /MERGE-APPROVED REPOS/ { block = 1; next }
      block && tolower($1) == want { found = 1 }
      END { exit found ? 0 : 1 }' "$HOME/.claude/CLAUDE.md" && approved=1
  fi
  if [ -n "$approved" ]; then
    landing="This repo ($slug) is on the MERGE-APPROVED list in ~/.claude/CLAUDE.md, so open the PR/MR and merge it — merge, not squash, never force-push."
  else
    landing="Open the PR/MR and STOP. ${slug:-This repo} is not on the MERGE-APPROVED list in ~/.claude/CLAUDE.md, so the merge is the owner's call — say what it changes, why, and who owns the repo. Write access is not permission."
  fi
  msg="[unlanded work] $cwd on \"$branch\": $parts. Work is landed one PR/MR per logical unit. $landing If this work is a complete unit, land it now. If it is genuinely mid-thought, say so in one line so the user knows it is sitting here."
  esc=$(printf '%s' "$msg" | tr -d '\000-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
  if [ "$mode" = "--codex" ]; then
    printf '{"systemMessage": "%s"}\n' "$esc" >&3
  else
    printf '{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "%s"}}\n' "$esc" >&3
  fi
} 3>&1 >/dev/null 2>&1

exit 0
