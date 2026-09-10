#!/bin/sh
# SessionStart: one line of orientation, never a failure.
#
# - If .claude/rules/*.md exist in the current repo, print how many, so the
#   count is visible without having to go look.
# - If ~/.agents/POLICY.md exists, do nothing: Claude Code already imports it
#   on its own, and a hook echoing "found POLICY.md" would just be restating
#   something the harness already surfaced.
#
# Every failure here is silently swallowed and exit 0 always wins: a broken
# hook must never break someone's session start.

{
  if [ -d ".claude/rules" ]; then
    count=$(find ".claude/rules" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
      echo "teyla: ${count} rule file(s) in .claude/rules/"
    fi
  fi
} 2>/dev/null

exit 0
