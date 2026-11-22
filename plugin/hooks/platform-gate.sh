#!/bin/sh
# PreToolUse (Edit, Write, MultiEdit, NotebookEdit): the parity gate before the first write (POLICY §14).
#
# Exit 0 allows the call. Exit 2 refuses it and shows stderr to the model.
#
# The push check (`teyla platform check`) fires after the tokens are spent. This one refuses the first edit of
# a closed secondary platform's file. The decision is `teyla.platform_hook` (Python); this script exists to keep
# the common case free. It takes the file path from the JSON with builtins, walks up to the git root of that
# file, and starts Python only when that root holds docs/parity.toml. No ledger, no process.
#
# Fail open on purpose: no python with teyla, a crash, an odd path. A gate that breaks must not break the call.
# TEYLA_PYTHON names the python to use.

payload=""
while IFS= read -r line || [ -n "$line" ]; do
    payload="$payload$line
"
done

path=""
for key in file_path notebook_path; do
    after=${payload#*\"$key\"}
    if [ "$after" != "$payload" ]; then
        v=${after#*:}
        v=${v#*\"}
        path=${v%%\"*}
        break
    fi
done
[ -n "$path" ] || exit 0

case "$path" in
    /*) d=$path ;;
    *)
        cwd=${payload#*\"cwd\"}
        [ "$cwd" != "$payload" ] || exit 0       # a relative path with no cwd: nothing to anchor it to
        cwd=${cwd#*:}; cwd=${cwd#*\"}; cwd=${cwd%%\"*}
        d="$cwd/$path" ;;
esac

root=""
while [ -n "$d" ] && [ "$d" != "/" ]; do
    d=${d%/*}
    [ -n "$d" ] || break
    if [ -e "$d/.git" ]; then root=$d; break; fi
done
[ -n "$root" ] && [ -f "$root/docs/parity.toml" ] && [ -f "$root/teyla.toml" ] || exit 0

teyla_python() {
    t=$(command -v teyla) || t="$HOME/.local/bin/teyla"     # a uv tool install is not on a GUI app's PATH
    [ -f "$t" ] && [ -r "$t" ] || return 1
    IFS= read -r first < "$t" || return 1
    case "$first" in
        "#!"*python*) ;;
        *) return 1 ;;
    esac
    p=${first#"#!"}
    p=${p#"${p%%[! ]*}"}
    case "$p" in
        /usr/bin/env*) return 1 ;;
    esac
    p=${p%% *}
    case "$p" in /*) ;; *) return 1 ;; esac
    [ -x "$p" ] || return 1
    printf '%s\n' "$p"
}

py="${TEYLA_PYTHON:-}"
if [ -z "$py" ] || [ ! -x "$py" ]; then
    py=$(teyla_python 2>/dev/null) || py=""
fi
if [ -z "$py" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -I -c 'import teyla.platform_hook' >/dev/null 2>&1; then
        py=python3
    else
        exit 0
    fi
fi

# -I: the working directory and PYTHONPATH are not searched, so a repo cannot plant its own copy of the gate.
printf '%s' "$payload" | "$py" -I -m teyla.platform_hook
status=$?
[ "$status" -eq 2 ] && exit 2
exit 0
