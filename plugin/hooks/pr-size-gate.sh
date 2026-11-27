#!/bin/sh
# PreToolUse (Bash): one PR per logical unit. `gh pr create` and `gh pr merge` are refused for a PR over
# the size limits (default 800 changed lines or 20 files; lock files, generated files, string catalogs and
# media are not counted). Claude Code and Codex get the same hook.
#
# The logic is Python: `python3 -I -m teyla.pr_size_gate`. Limits and mode come from `[pr_size]` in
# ~/.teyla/config.toml (`max_lines`, `max_files`, `mode = "refuse" | "warn" | "off"`, default refuse).
# Exit 2 + stderr refuses. Escapes, each logged to ~/.teyla/pr-size-gate.tsv:
#   a line `Size-OK: <reason>` in the PR body, or  TEYLA_SIZE_OK="<reason>" <command>
#
# THIS HOOK FAILS OPEN: no python, no teyla package, a crash, a timeout or a garbage payload is exit 0.
# Cost: a command without `gh` and `pr` in it is pure sh, no process.
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles). TEYLA_PYTHON names the python3 to use.

[ "${TEYLA_PR_SIZE_GATE:-}" = 0 ] && exit 0

payload=$(cat 2>/dev/null)

# Coarse prefilter over the raw payload: only a `gh ... pr` command can be refused.
case "$payload" in
    *gh*pr*) ;;
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
    elif py=$(command -v python3) && "$py" -I -c 'import teyla.pr_size_gate' >/dev/null 2>&1; then
        :
    else
        exit 0
    fi
fi

# Exit 0 allows, 2 refuses; any other status (a crash) is an allow.
printf '%s' "$payload" | "$py" -I -m teyla.pr_size_gate
[ $? -eq 2 ] && exit 2
exit 0
