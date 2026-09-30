#!/bin/sh
# SessionStart: one or two lines of orientation, never a failure.
#
# - If .claude/rules/*.md exist in the current repo, print how many.
# - Print only what is NEW since the last session start: doctor and `teyla routines`
#   precompute ~/.teyla/banner.items (key<TAB>text per thing that needs a human); the
#   keys shown last time are in ~/.teyla/banner.seen. One awk call prints
#   "teyla: new — …; N known (teyla doctor)", or nothing when nothing is new. The old
#   one-liner (~/.teyla/doctor.summary) showed on 44 of 44 starts with the same items
#   for 13 days and stopped being read. Without banner.items (a CLI older than this
#   hook) the summary is printed as before.
# - Once per weekly digest (~/.teyla/digest.md newer than ~/.teyla/digest.seen), print
#   its headline: the top action of the week and its command.
# - If ./teyla.toml names a product and the daily routine left a one-line routines
#   summary for it (~/.teyla/routines/<product>.line), print that line: "did it run?"
#   is then answered before the question is asked, and `teyla routines .` is named
#   for the fresh table.
# - If no update check happened in the last day and `teyla` can be found — on PATH,
#   or at ~/.local/bin/teyla (uv tool / pipx), since a GUI app inherits no shell PATH —
#   start one in the background, followed by `teyla routine catch-up`, which runs the
#   daily or weekly launchd job if the Mac was off at its minute (launchd skips those).
#   teyla itself applies ~/.teyla/config.toml [env] (SSL_CERT_FILE, a proxy) at startup,
#   so this needs no shell rc either. This is the auto-update path on machines where
#   launchd agents cannot be installed (a managed laptop): every session start becomes
#   a chance to notice a new release. The next session shows the result.
# - Safe mode (`[safe] enabled = true` in ~/.teyla/config.toml, or TEYLA_SAFE=1): no update
#   check at all — only doctor and catch-up, which are offline in safe mode — and the
#   once-a-day test uses doctor.json's age, since update-check.json is never refreshed then.
#
# Every failure here is silently swallowed and exit 0 always wins: a broken
# hook must never break someone's session start.
#
# One script for every harness; the argument says which caller it is, because the
# harnesses differ in how the orientation lines reach the model:
#
#   (none)            Claude Code SessionStart, Cursor sessionStart, Grok SessionStart,
#                     Hermes on_session_start. Plain stdout. Claude Code injects it into the
#                     model's context; the other three ignore it (see docs/HARNESSES.md).
#   --codex           Codex SessionStart (~/.codex/hooks.json). Codex also injects plain
#                     stdout, as a developer message tagged `hooks.additional_context`
#                     (verified with `codex exec` 0.153.4 and 0.158.0-alpha.2.1 on
#                     2026-09-29). The JSON payload on stdin names `transcript_path`; a
#                     rollout whose session_meta says `"originator":"codex_exec"` is a
#                     `codex exec` batch run (a script wrote its prompt): it gets nothing,
#                     neither the lines (no person reads them) nor the background check
#                     (509 of 520 Codex sessions in September 2026 were batch).
#   --context-json    Hermes pre_llm_call. Hermes ignores what on_session_start prints, but
#                     injects `{"context": "..."}` from a pre_llm_call shell hook into the
#                     user message (hermes-agent 0.20.4 agent/shell_hooks.py
#                     `_parse_response`; website/docs/user-guide/features/hooks.md). It
#                     fires every turn, so this mode prints only when the payload says
#                     `"is_first_turn": true`, and prints only the orientation: the
#                     background update/catch-up is on_session_start's job, and two
#                     starters racing on one stale stamp would run two updates.
#
# Only --codex and --context-json read stdin: the other callers may leave it open, and a
# `cat` waiting on it would outlive the 5-second hook timeout.

mode="${1:-}"
payload=""
if [ "$mode" = "--codex" ] || [ "$mode" = "--context-json" ]; then
  payload=$(cat 2>/dev/null)
fi

if [ "$mode" = "--context-json" ]; then
  case "$payload" in
    *'"is_first_turn": true'*|*'"is_first_turn":true'*) ;;
    *) exit 0 ;;
  esac
fi

if [ "$mode" = "--codex" ]; then
  transcript=$(printf '%s' "$payload" | sed -n 's/.*"transcript_path" *: *"\([^"]*\)".*/\1/p' 2>/dev/null)
  if [ -n "$transcript" ] && [ -f "$transcript" ] && head -c 8192 "$transcript" 2>/dev/null | grep -q '"originator" *: *"codex_exec"'; then
    exit 0
  fi
fi

orientation() {
  if [ -d ".claude/rules" ]; then
    count=$(find ".claude/rules" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
      echo "teyla: ${count} rule file(s) in .claude/rules/"
    fi
  fi
  summary="$HOME/.teyla/doctor.summary"
  items="$HOME/.teyla/banner.items"
  seen="$HOME/.teyla/banner.seen"
  if [ -f "$items" ]; then
    [ -f "$seen" ] || : > "$seen"
    awk -F '\t' 'FILENAME == ARGV[1] { s[$1] = 1; next }
      ($1 in s) { k++; next }
      { n++; if (n <= 3) t = t (n > 1 ? "; " : "") $2 }
      END { if (n) { l = "teyla: new — " t; if (n > 3) l = l " (+" n - 3 " more)"; if (k) l = l "; " k " known"; print l " (teyla doctor)" } }' "$seen" "$items"
    cut -f1 "$items" > "$seen.tmp" && mv "$seen.tmp" "$seen"
  elif [ -s "$summary" ]; then
    line=$(head -n 1 "$summary" 2>/dev/null)
    [ -n "$line" ] && echo "$line"
  fi
  digest="$HOME/.teyla/digest.md"
  if [ -s "$digest" ] && { [ ! -f "$HOME/.teyla/digest.seen" ] || [ "$digest" -nt "$HOME/.teyla/digest.seen" ]; }; then
    head -n 1 "$digest"
    touch "$HOME/.teyla/digest.seen"
  fi
  if [ -f "teyla.toml" ]; then
    product=$(sed -n 's/^name *= *"\([^"]*\)".*/\1/p' teyla.toml 2>/dev/null | head -n 1)
    if [ -n "$product" ] && [ -s "$HOME/.teyla/routines/$product.line" ]; then
      echo "teyla: $(head -n 1 "$HOME/.teyla/routines/$product.line")"
    fi
  fi
}

if [ "$mode" = "--context-json" ]; then
  text=$(orientation 2>/dev/null)
  if [ -n "$text" ]; then
    printf '%s' "$text" | python3 -c 'import json, sys; print(json.dumps({"context": sys.stdin.read().strip()}))' 2>/dev/null
  fi
  exit 0
fi

{
  orientation
  stamp="$HOME/.teyla/update-check.json"
  teyla_bin=""
  if command -v teyla >/dev/null 2>&1; then
    teyla_bin="teyla"
  elif [ -x "$HOME/.local/bin/teyla" ]; then
    teyla_bin="$HOME/.local/bin/teyla"
  fi
  if [ -z "$teyla_bin" ] && [ -f "$HOME/.teyla/config.toml" ]; then
    # Teyla was set up here (config exists) but no binary answers: a failed
    # `uv tool install --force` removes the old tool before building the new one.
    echo "teyla: no \`teyla\` binary found although ~/.teyla/config.toml exists — reinstall: uv tool install --force git+https://github.com/zaitsew/teyla (or pipx)"
  fi
  safe=""
  case "$TEYLA_SAFE" in 1|true|TRUE|True|yes|on) safe=1 ;; esac
  if [ -z "$safe" ] && [ -n "$TEYLA_SAFE" ]; then
    # Fail closed, as config.safe_mode() does: only an explicit false word leaves it off.
    case "$TEYLA_SAFE" in 0|false|FALSE|False|no|off) ;; *) safe=1 ;; esac
  fi
  if [ -z "$safe" ] && [ -f "$HOME/.teyla/config.toml" ]; then
    val=$(sed -n '/^\[safe\]/,/^\[/p' "$HOME/.teyla/config.toml" 2>/dev/null | sed -n 's/^enabled *= *//p' | head -n 1 | tr -d '" \r' | tr 'A-Z' 'a-z')
    case "$val" in ""|false|0|no|off) ;; *) safe=1 ;; esac
  fi
  if [ -n "$teyla_bin" ]; then
    if [ -n "$safe" ]; then
      stamp="$HOME/.teyla/doctor.json"
      if [ ! -f "$stamp" ] || [ -n "$(find "$stamp" -mmin +1440 2>/dev/null)" ]; then
        (nohup sh -c "\"$teyla_bin\" doctor --quiet >/dev/null 2>&1; nice \"$teyla_bin\" routine catch-up --quiet >/dev/null 2>&1" >/dev/null 2>&1 &)
      fi
    elif [ ! -f "$stamp" ] || [ -n "$(find "$stamp" -mmin +1440 2>/dev/null)" ]; then
      (nohup sh -c "\"$teyla_bin\" update --check --quiet >/dev/null 2>&1; \"$teyla_bin\" doctor --quiet >/dev/null 2>&1; nice \"$teyla_bin\" routine catch-up --quiet >/dev/null 2>&1" >/dev/null 2>&1 &)
    fi
  fi
} 2>/dev/null

exit 0
