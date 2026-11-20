#!/bin/sh
# PreToolUse: the kill switch, and the capability grants of a `teyla run`.
#
# Exit 0 allows the tool call. Exit 2 blocks it and shows stderr to the model.
# There is no third answer here on purpose — "the hook broke" must never quietly
# become "the tool ran".
#
# Four states, cheapest first, because this runs before *every* tool call and a
# hook that costs a Python interpreter start on an ordinary session is a hook
# people uninstall:
#
#   1. ~/.teyla/KILL exists      -> exit 2 with the reason. Pure sh, no python.
#   2. TEYLA_GRANTS unset, and
#      ~/.teyla/active-runs empty-> exit 0, silently. Not a routine run.
#   3. TEYLA_GRANTS unset, but a
#      run is in flight          -> hand it to python, which prunes dead markers and
#                                   then refuses: a session with no grants while a
#                                   run is running is a way out of that run.
#   4. TEYLA_GRANTS set          -> hand the call to teyla.control.hook.
#
# Only states 3 and 4 start python. Which python: the one that carries `teyla` — TEYLA_PYTHON, then
# the interpreter named by the shebang of the `teyla` executable (the lookup the machine guard's sibling hooks use),
# then `python3` if it can import teyla. On a machine where teyla is a uv tool, the `python3` on PATH
# has no teyla module, and using it denied every tool call during a run (HK-3).
#
# Two failure shapes, on purpose different:
#   - teyla is found but the enforcement crashes (status other than 0 or 2): the call is refused. A
#     run launched under grants with broken enforcement is exactly the case the grants exist for.
#   - teyla is not found at all: the call is allowed, with one line on stderr. The control plane is
#     teyla's own feature; no `teyla run` can have started without teyla, so a missing teyla means
#     there is nothing to enforce, and refusing would lock the owner out of their own session with
#     no way to fix it from inside it. (The kill switch above is pure sh and needs no python.)
#
# An ordinary session on an idle machine never reaches python and never pays for an interpreter.
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles).

TEYLA_DIR="${TEYLA_HOME:-$HOME/.teyla}"

if [ -f "$TEYLA_DIR/KILL" ]; then
    reason=$(head -n 1 "$TEYLA_DIR/KILL" 2>/dev/null)
    [ -n "$reason" ] || reason="no reason given"
    echo "teyla: KILL SWITCH IS ON — every tool call is denied." >&2
    echo "  reason: $reason" >&2
    echo "  clear it with: teyla kill off" >&2
    exit 2
fi

if [ -z "${TEYLA_GRANTS:-}" ]; then
    # `ls -A` rather than a glob so a dotfile still counts, and so an unreadable
    # directory reads as empty rather than as an error.
    if [ -d "$TEYLA_DIR/active-runs" ] && [ -n "$(ls -A "$TEYLA_DIR/active-runs" 2>/dev/null)" ]; then
        : # a run may be in flight — python decides, after pruning stale markers
    else
        exit 0
    fi
fi


# --- which python carries teyla ---
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
        /usr/bin/env*) return 1 ;;          # names no file: python3 on PATH is what it would run
    esac
    p=${p%% *}
    # The shebang is followed only into a known interpreter root (uv tools, pipx, Homebrew, /usr, python.org,
    # pyenv; TEYLA_PYTHON_ROOTS adds more, colon-separated), never into the directory the command runs in:
    # a console script planted in a repo (`.` or node_modules/.bin on PATH) must not pick the guard's
    # interpreter. An install elsewhere names its python with TEYLA_PYTHON.
    # Both paths are taken canonical: absolute, no `.` or `..` components, their directories resolved with
    # `pwd -P`, so `./teyla` from a `.` on PATH and `/usr/bin/../../repo/x` are judged by where they really are.
    case "$t" in /*) ;; *) return 1 ;; esac
    case "$p" in /*) ;; *) return 1 ;; esac
    dots='/.''./'                                      # the parent-directory component, spelt in two pieces
    case "/$t/" in *"/./"*|*"$dots"*) return 1 ;; esac
    case "/$p/" in *"/./"*|*"$dots"*) return 1 ;; esac
    tdir=$(cd "${t%/*}" 2>/dev/null && pwd -P) || return 1
    pdir=$(cd "${p%/*}" 2>/dev/null && pwd -P) || return 1
    t="$tdir/${t##*/}"
    p="$pdir/${p##*/}"
    cwd=$(pwd -P) || return 1
    case "$t" in "$cwd"/*) return 1 ;; esac
    case "$p" in "$cwd"/*) return 1 ;; esac
    roots="$HOME/.local/share/uv/tools:$HOME/.local/pipx/venvs:$HOME/Library/Application Support/pipx/venvs:$HOME/.pyenv:/opt/homebrew:/usr/local:/usr/bin:/Library/Frameworks/Python.framework${TEYLA_PYTHON_ROOTS:+:$TEYLA_PYTHON_ROOTS}"
    ok=0
    oldifs=$IFS; IFS=:
    for root in $roots; do
        [ -n "$root" ] || continue
        case "$p" in "$root"/*) ok=1 ;; esac
    done
    IFS=$oldifs
    [ "$ok" = 1 ] || return 1
    [ -x "$p" ] || return 1
    printf '%s\n' "$p"
}

py="${TEYLA_PYTHON:-}"
if [ -z "$py" ] || [ ! -x "$py" ]; then
    py=$(teyla_python 2>/dev/null) || py=""
fi
if [ -z "$py" ]; then
    # No teyla executable to read an interpreter from: use python3 only if it really has the package.
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import teyla.control.hook' >/dev/null 2>&1; then
        py=python3
    else
        echo "teyla: no python with the teyla package was found, so the kill switch is the only control checked and this call is allowed. Install teyla, or set TEYLA_PYTHON." >&2
        exit 0
    fi
fi

# The enforcement code is `teyla.control.hook`, from the installed `teyla` package (or from
# PYTHONPATH, when run from a checkout). There is no copy of it in the plugin. Its own exits
# are 0 (allow) and 2 (block); any other status means the interpreter or the import failed.
"$py" -m teyla.control.hook
status=$?

# Anything other than allow/block is normalised to block: a crashed interpreter
# under an armed run is a denial, not a permission.
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
    echo "teyla: this call runs under TEYLA_GRANTS or during a run but capability enforcement crashed" \
         "($py exited $status), so it is refused. Repair teyla, or remove the markers in $TEYLA_DIR/active-runs." >&2
fi
[ "$status" -eq 0 ] && exit 0
exit 2
