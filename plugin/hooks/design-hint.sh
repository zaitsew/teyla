#!/bin/sh
# UserPromptSubmit: when the prompt asks for drawings, mockups, concepts or a screen redesign,
# prints up to three lines of context: static drawings first, two variants, full device context,
# no builds, simulators or tests unless asked (POLICY section 16, 2026-11-27). When the prompt
# also asks for implementation, it says implementation is authorized and PRs go one per screen.
#
# All of the logic is `teyla.design_hint.hook_main`; the word lists are `teyla.design_lexicon`.
# This script only finds a Python, in the order capture-correction.sh documents: $TEYLA_PYTHON,
# the interpreter of the installed `teyla` tool, then `python3` (never the macOS developer-tools
# stub). With no importable `teyla` it prints nothing.
#
# Unlike the capture hooks this one writes to stdout on purpose: UserPromptSubmit stdout is
# injected into the model's context in Claude Code and Codex. Stderr is dropped and every
# error path exits 0, so it never fails the session.

{
  py=""
  if [ -n "$TEYLA_PYTHON" ] && [ -x "$TEYLA_PYTHON" ]; then
    py="$TEYLA_PYTHON"
  else
    for t in "$(command -v teyla 2>/dev/null)" "$HOME/.local/bin/teyla"; do
      [ -n "$t" ] && [ -f "$t" ] || continue
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

  "$py" -m teyla.design_hint
} 2>/dev/null

exit 0
