#!/bin/sh
# SessionStart: one or two lines of orientation, never a failure.
#
# - If .claude/rules/*.md exist in the current repo, print how many.
# - If ~/.teyla/doctor.summary is non-empty (doctor found something to fix or an
#   update waiting), print it. Doctor writes it; this only reads it, so the hook
#   costs nothing.
# - If no update check happened in the last day and `teyla` is on PATH, start one
#   in the background. This is the auto-update path on machines where launchd
#   agents cannot be installed (a managed laptop): every session start becomes a
#   chance to notice a new release. The next session shows the result.
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
  summary="$HOME/.teyla/doctor.summary"
  if [ -s "$summary" ]; then
    line=$(head -n 1 "$summary" 2>/dev/null)
    [ -n "$line" ] && echo "$line"
  fi
  stamp="$HOME/.teyla/update-check.json"
  if command -v teyla >/dev/null 2>&1; then
    if [ ! -f "$stamp" ] || [ -n "$(find "$stamp" -mmin +1440 2>/dev/null)" ]; then
      (nohup sh -c 'teyla update --check --quiet >/dev/null 2>&1; teyla doctor --quiet >/dev/null 2>&1' >/dev/null 2>&1 &)
    fi
  fi
} 2>/dev/null

exit 0
