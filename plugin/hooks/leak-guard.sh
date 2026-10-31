#!/bin/sh
# PreToolUse (Bash, Read, Edit, Write): the agent boundary. Nothing an agent publishes carries a secret
# or a private term, and the agent never reads a credential. docs/SHIELD.md, SH6 and 5.2.
#
# Exit 0 allows the call. Exit 2 refuses it and shows stderr to the model.
#
# THREE OUTCOMES, and the lines between them are FIXED STRING MATCHES, not a classifier:
#
#   Plain. The command's text holds none of the tokens below and none of the characters ' $ ` (or an escaped
#   quote or backslash in the JSON): exit 0 at once, no process started, no Python. If this script itself
#   errors on such a command it prints one warning line and exits 0, like the machine guard, because a guard
#   that blocks every `ls` over its own bug gets uninstalled.
#
#   Quoted. No token, but quoting or an expansion could spell one another way (`g''h p''r`, `cred''entials`):
#   Python runs and matches on the shell-split words. If Python cannot run, the quoting is stripped and the
#   tokens are matched once more; a hit is a refusal, a miss is the one-line warning and exit 0.
#
#   Token. A command that contains a token is FAIL-CLOSED. A missing python3, a missing teyla package, a
#   scanner that crashes or times out, or any error here is exit 2 with the reason. A publication is never
#   waved through unscanned. These commands are rare and explicit; a wrong refusal costs one retry.
#
# The tokens (substring matches over the text after "tool_input" in the JSON payload):
#   publication  gh .. pr|issue|release|gist|repo|api    git .. commit|tag|merge
#   keychain     security .. -password   security .. dump-keychain
#   visibility   --visibility   visibility=   private=
#   credentials  .ssh/id_  .aws/credentials  private-terms  PRIVATE_TERMS  .appstoreconnect  .grok/config.toml
#                .codex/auth.json  .codex/config.toml  .claude/.credentials.json  .netrc  .docker/config.json
#                .pem  .p8  and the file $TEYLA_PRIVATE_TERMS names
# Python (teyla.leak_guard, run with -I) then parses the command like a shell, pulls out the text a command
# publishes, and pipes it to `teyla leak --text -`. It also decides what is really a credential read, a
# Keychain dump or a visibility change. The script never prints the text it scanned.
#
# Skip once, on the record. A publication scan that cannot run, or a false positive, is skipped by starting
# the command with `TEYLA_LEAK_GUARD=0 ` (a leading assignment word, before the executable) or by setting it in
# the hook's own environment. Python reads it, and appends one line per skipped publication to
# $TEYLA_HOME/leak-skips.log. Both forms lift the publication scan only: a credential path, a Keychain dump and
# a visibility change are refused whatever the variable says.
#
# `--grok`: Grok shows only the first stderr line of an exit 2, so the refusal is also printed to stdout as
# {"decision":"deny","reason":...}. Claude Code and Codex read stderr.
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles). TEYLA_PYTHON names the python3 to use.

mode="${1:-}"
phase=coarse
status=0
tok=0

# The fixed tokens, matched as substrings. Sets $tok to 1 when the text holds one.
match_tokens() {
    case "$1" in
        *s[s]h/id_*|*.aws/credentials*|*private-terms*|*PRIVATE_TERMS*|*.appstoreconnect*|*.grok/config.toml*) tok=1 ;;
        *.codex/auth.json*|*.codex/config.toml*|*.claude/.credentials.json*|*.netrc*|*.docker/config.json*) tok=1 ;;
        *.pem*|*.p8*|*--visibility*|*visibility=*|*private=*|*security*-password*|*security*dump-keychain*) tok=1 ;;
        *gh*pr*|*gh*issue*|*gh*release*|*gh*gist*|*gh*repo*|*gh*api*) tok=1 ;;
        *git*commit*|*git*tag*|*git*merge*) tok=1 ;;
    esac
    if [ "$tok" = 0 ] && [ -n "${TEYLA_PRIVATE_TERMS:-}" ]; then
        case "$1" in *"$TEYLA_PRIVATE_TERMS"*) tok=1 ;; esac
    fi
}

refuse_failed() {
    echo "teyla leak-guard: refused — the guard failed ($1) on a command that publishes text or touches a credential." >&2
    echo "  A guard that cannot run does not wave a publication through. Repair teyla, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>" >&2
    [ "$mode" = --grok ] && printf '{"decision": "deny", "reason": "teyla leak-guard: the guard failed on a command that publishes text or touches a credential"}\n'
    exit 2
}

# A command whose quoting hides a token (`g''h p''r`, `cred''entials`) is only found once the quotes are gone.
# That check costs a process, so it runs only when the guard itself could not (no python, a crash).
unquoted_match() {
    stripped=$(printf '%s' "$after" | tr -d "\\\\\"'\`\$") || return 1
    tok=0
    match_tokens "$stripped"
    [ "$tok" = 1 ]
}

on_exit() {
    status=$?
    trap - EXIT
    case "$status" in 0|2) exit "$status" ;; esac
    if [ "$phase" = token ]; then
        refuse_failed "status $status"
    fi
    if [ "$phase" = suspect ] && unquoted_match; then
        refuse_failed "status $status"
    fi
    echo "teyla leak-guard: warning — the guard hit an error (status $status) and let this command through." >&2
    exit 0
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP
set -e

# leak-guard:coarse-begin
# Read stdin with builtins only: the common path starts no process.
payload=""
while IFS= read -r line || [ -n "$line" ]; do
    payload="$payload$line
"
done

after=${payload#*\"tool_input\"}
[ "$after" != "$payload" ] || exit 0

# Three outcomes. A fixed token: the guard runs, and any failure of it is a refusal. No token, but the command
# has quoting, escapes, a variable or a substitution (in the JSON text: ' $ ` or an escaped " or \): the guard
# runs, because quoting can spell a token another way; if it cannot run, a second look with the quoting
# stripped decides. Neither: the command passes now, no process started.
match_tokens "$after"
susp=0
case "$after" in
    *\'*|*\$*|*\`*|*'\"'*|*'\\'*|*'\u'*) susp=1 ;;
esac
[ "$tok" = 1 ] || [ "$susp" = 1 ] || exit 0
# leak-guard:coarse-end

phase=suspect
[ "$tok" = 0 ] || phase=token
# leak-guard:token-begin

# The python must carry the teyla package. TEYLA_PYTHON first; then the interpreter named by the shebang of
# the `teyla` on PATH (a uv tool or a venv keeps the package out of the system python3, which is what
# `python3` resolves to on most machines); python3 itself last.
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
    py=$(teyla_python) || py=$(command -v python3) || {
        if [ "$phase" = token ]; then
            echo "teyla leak-guard: refused — python3 is not on PATH, so this command's text cannot be scanned." >&2
            echo "  Install python3 and teyla, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>" >&2
            [ "$mode" = --grok ] && printf '{"decision": "deny", "reason": "teyla leak-guard: python3 is not on PATH"}\n'
            exit 2
        fi
        exit 70
    }
fi

# The enforcement code is teyla.leak_guard, from the installed package: -I ignores PYTHONPATH and the working
# directory, so a repo cannot plant its own copy. Exit 0 allows, 2 refuses, anything else is a failure and
# becomes a refusal in on_exit. The skip (TEYLA_LEAK_GUARD=0, in the environment or as a leading assignment
# word) is read there, so it can lift the publication scan and nothing else.
if printf '%s' "$payload" | "$py" -I -m teyla.leak_guard ${mode:+"$mode"}; then
    exit 0
else
    exit $?
fi
