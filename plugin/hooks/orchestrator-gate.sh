#!/bin/sh
# PreToolUse (Bash): the top-tier model orchestrates; a worker builds, commits and merges.
#
# Owner policy (2026-11-27): Claude Fable (`claude-fable-*`) and OpenAI Astra (`gpt-*-astra`) brief
# workers, decide, check evidence and report. A build, a test run, a commit, a push, a merge or a store
# upload belongs to a worker session (Claude: the builder agent; Codex: the volume role). Policy text
# alone did not hold, so this hook enforces it in both harnesses the same way.
#
# The logic is Python: `python3 -I -m teyla.orchestrator_gate`. It reads the session's model from the hook
# payload (Codex sends `model`) or from the tail of the transcript (Claude Code), never gates a sub-agent,
# and decides from `[orchestrator] gate = "refuse" | "warn" | "off"` in ~/.teyla/config.toml (default
# refuse). Exit 2 + stderr refuses. The reason to override once, on the record:
#   TEYLA_ORCH_OK="<reason>" <command>      (a leading assignment word, or the hook's own environment)
# One row per refusal, warning and override goes to ~/.teyla/orchestrator-gate.tsv.
#
# THIS HOOK FAILS OPEN, like the machine guard: no python, no teyla package, a crash or a garbage payload
# is exit 0. Cost: an ordinary command (no worker word anywhere in the payload) is pure sh, no process.
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles). TEYLA_PYTHON names the python3 to use.

[ "${TEYLA_ORCH_GATE:-}" = 0 ] && exit 0

payload=$(cat 2>/dev/null)

# Coarse prefilter over the raw payload: only a worker word can be refused.
case "$payload" in
    *xcodebuild*|*swift*|*simctl*|*gradle*|*npm*|*pnpm*|*yarn*|*pytest*|*check.sh*|*git*|*gh*|*testflight*|*-review*|*sh*|*eval*) ;;
    *) exit 0 ;;
esac

teyla_python() {
    t=$(command -v teyla) || t="$HOME/.local/bin/teyla"
    [ -f "$t" ] && [ -r "$t" ] || return 1
    IFS= read -r first < "$t" || return 1
    case "$first" in
        "#!"*python*) ;;
        *) return 1 ;;
    esac
    p=${first#"#!"}
    p=${p#"${p%%[! ]*}"}
    case "$p" in /usr/bin/env*) return 1 ;; esac
    p=${p%% *}
    case "$t" in /*) ;; *) return 1 ;; esac
    case "$p" in /*) ;; *) return 1 ;; esac
    dots='/.''./'
    case "/$p/" in *"/./"*|*"$dots"*) return 1 ;; esac
    pdir=$(cd "${p%/*}" 2>/dev/null && pwd -P) || return 1
    p="$pdir/${p##*/}"
    cwd=$(pwd -P) || return 1
    case "$p" in "$cwd"/*) return 1 ;; esac
    roots="$HOME/.local/share/uv/tools:$HOME/.local/pipx/venvs:$HOME/Library/Application Support/pipx/venvs:$HOME/.pyenv:/opt/homebrew:/usr/local:/usr/bin:/Library/Frameworks/Python.framework${TEYLA_PYTHON_ROOTS:+:$TEYLA_PYTHON_ROOTS}"
    ok=0
    oldifs=$IFS; IFS=:
    for root in $roots; do
        [ -n "$root" ] || continue
        case "$p" in "$root"/*) ok=1 ;; esac
    done
    IFS=$oldifs
    [ "$ok" = 1 ] && [ -x "$p" ] || return 1
    printf '%s\n' "$p"
}

py="${TEYLA_PYTHON:-}"
if [ -z "$py" ] || [ ! -x "$py" ]; then
    if py=$(teyla_python); then
        :
    elif py=$(command -v python3) && "$py" -I -c 'import teyla.orchestrator_gate' >/dev/null 2>&1; then
        :
    else
        exit 0
    fi
fi

# Exit 0 allows, 2 refuses; any other status (a crash) is an allow.
printf '%s' "$payload" | "$py" -I -m teyla.orchestrator_gate
[ $? -eq 2 ] && exit 2
exit 0
