#!/bin/sh
# UserPromptSubmit: keeps the owner's own long prompts, word for word, in
# ~/.teyla/intent/<product>.md (`teyla intent`). A plan written later is checked against
# the source, not against a summary of it.
#
# All of the logic is `teyla.intent.hook_main`: the length threshold (`[intent] min_chars`,
# default 400), the off switch (`[intent] enabled`), the filters for prompts a script or
# another agent wrote, `teyla.corrections.scrub` for secrets, and the dedupe. This script
# only finds a Python that can run it without harm, in the same order and for the same
# reasons as capture-correction.sh (read its header): $TEYLA_PYTHON, the interpreter of the
# installed `teyla` tool, then `python3` (never the macOS developer-tools stub). With no
# importable `teyla`, nothing is recorded.
#
# An optional first argument names the harness for the entry header (`codex`, `grok`,
# `hermes`); without it the payload decides.
#
# Silent by construction: UserPromptSubmit stdout is injected into the model's context,
# so this hook never writes to stdout. It never fails the session either: every error
# path exits 0.

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

  "$py" -m teyla.intent "$1"
} >/dev/null 2>&1

exit 0
