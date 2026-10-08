#!/bin/sh
# UserPromptSubmit, PostToolUse, SessionStart(compact): the context budget — opt-in.
#
# The work is context-budget.py; this wrapper exists for the cost when it is OFF. It is wired
# on PostToolUse, so it runs after every tool call of every session: a long autonomous run
# makes hundreds. Starting Python for each one (~40 ms) to learn that the feature is off is a
# tax nobody agreed to, so the off path is sh + one awk over ~/.teyla/config.toml, and no
# config file at all is one `test`. Python starts only when `[hooks] context_budget = true`.
#
# Off by default: a machine that already wires its own context-budget hook in
# ~/.claude/settings.json would ask for every handoff twice.
# `teyla config set hooks.context_budget=true` turns this copy on.
#
# Interpreter, in the same order as capture-correction.sh and for the same reasons:
#   1. $TEYLA_PYTHON (tests; an unusual install).
#   2. The shebang of the installed `teyla` (on PATH, else ~/.local/bin/teyla — a GUI app such
#      as the Claude desktop app has no shell PATH).
#   3. `python3` on PATH, except the macOS /usr/bin/python3 stub when the Command Line Tools
#      are absent: it would pop an "install developer tools" dialog on every tool call.
# context-budget.py is stdlib only, so any of the three can run it.
#
# Never fails a session: every path exits 0, stderr is dropped. Only the Python's stdout —
# the hook's JSON — reaches Claude Code.

cfg="$HOME/.teyla/config.toml"
[ -f "$cfg" ] || exit 0
# The [hooks] table's context_budget key, TOML-ish: comments and quotes ignored, last wins.
awk '
  /^[ \t]*\[/ { t = $0; sub(/#.*/, "", t); gsub(/[ \t]/, "", t); inside = (t == "[hooks]"); next }
  inside {
    line = $0; sub(/#.*/, "", line); n = index(line, "="); if (!n) next
    k = substr(line, 1, n - 1); v = substr(line, n + 1)
    gsub(/[ \t"\047]/, "", k); gsub(/[ \t"\047\r]/, "", v)
    if (k == "context_budget") { v = tolower(v); on = (v == "true" || v == "1" || v == "yes" || v == "on") }
  }
  END { exit on ? 0 : 1 }' "$cfg" 2>/dev/null || exit 0

hook_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || exit 0
py=""
if [ -n "$TEYLA_PYTHON" ] && [ -x "$TEYLA_PYTHON" ]; then
  py="$TEYLA_PYTHON"
else
  for t in "$(command -v teyla 2>/dev/null)" "$HOME/.local/bin/teyla"; do
    [ -n "$t" ] && [ -f "$t" ] || continue
    # `#!/path/to/python`; pip's long-path form is `#!/bin/sh` + `'''exec' "/path/python" …`.
    cand=$(head -n 1 "$t" 2>/dev/null | sed -n 's/^#! *\([^ ]*\).*/\1/p')
    case "$cand" in
      */python*) ;;
      *) cand=$(sed -n "2s/^'''exec' *\"\{0,1\}\([^\" ]*\).*/\1/p" "$t" 2>/dev/null) ;;
    esac
    if [ -n "$cand" ] && [ -x "$cand" ]; then py="$cand"; break; fi
  done
fi
if [ -z "$py" ]; then
  cand=$(command -v python3 2>/dev/null)
  if [ -n "$cand" ]; then
    if [ "$cand" = "/usr/bin/python3" ] && [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
      xcode-select -p >/dev/null 2>&1 && py="$cand"
    else
      py="$cand"
    fi
  fi
fi
[ -n "$py" ] || exit 0

"$py" "$hook_dir/context-budget.py" 2>/dev/null
exit 0
