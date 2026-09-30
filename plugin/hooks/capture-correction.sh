#!/bin/sh
# UserPromptSubmit: records correction-shaped prompts, catching what the model
# might not notice mid-turn. The test is `teyla.adapters.is_correction` — the same
# one `teyla monitor` counts with, tuned for precision: in 2026-09 the old broad
# net filed 107 records of which about 3 were real corrections. Prompts from
# `claude -p`, `grok -p` and `hermes -z` are skipped (`teyla.corrections.headless`).
#
# All of the logic is `teyla.corrections.hook_main` — the same code `teyla correct`
# writes through — so there is one secret scrubber and one store, not a copy of each
# here. What this script does is find a Python that can run it without harm:
#
#   1. $TEYLA_PYTHON, if set (tests; an unusual install).
#   2. The interpreter of the installed `teyla` tool — its entry script's shebang
#      (`uv tool` / `pipx` put it at ~/.local/bin/teyla, which a GUI app's PATH lacks).
#   3. `python3` on PATH — but on macOS, /usr/bin/python3 without the Command Line
#      Tools is a stub that pops an "install developer tools" dialog. This hook runs on
#      every prompt, so it asks `xcode-select -p` first and stays silent if the tools
#      are absent.
#
# When the script runs from a checkout (plugin/hooks/ beside src/teyla), that source is
# put first on sys.path, so the hook and the code it calls are the same version. With no
# importable `teyla` at all, nothing is recorded: writing an unscrubbed prompt is the
# failure this design exists to prevent.
#
# Not every prompt is the human typing (`is_noise_turn` drops `<task-notification>`,
# `<system-reminder>`, `[SYSTEM NOTIFICATION …]` …), and the prompt arrives under
# different keys per harness — `teyla harness sync` wires this one script into Cursor,
# Grok and Hermes too; `teyla.corrections._pick` reads every shape.
#
# Codex fires UserPromptSubmit for `codex exec` too, whose prompt a script or another
# agent wrote (a review brief full of "don't"); `teyla.corrections.headless` reads the
# rollout at `transcript_path` and skips it when its first record says
# `"originator":"codex_exec"` (Codex 0.158.0-alpha.2.1, 2026-09-29).
#
# Silent by construction: UserPromptSubmit stdout is injected into the model's
# context, so this hook never writes to stdout, match or no match. It also
# never fails the session — every error path below still exits 0.

{
  hook_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
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

  "$py" -c '
import os, sys
src = os.path.join(sys.argv[1], "..", "..", "src") if len(sys.argv) > 1 and sys.argv[1] else ""
if src and os.path.isfile(os.path.join(src, "teyla", "corrections.py")):
    sys.path.insert(0, os.path.abspath(src))
try:
    from teyla.corrections import hook_main
except Exception:
    sys.exit(0)
hook_main()
' "$hook_dir"
} >/dev/null 2>&1

exit 0
