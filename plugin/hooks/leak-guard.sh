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
#                git .. push with --no-verify (or a prefix of it) or core.hooksPath: the pre-push gate is skipped
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
credtok=0

# The fixed tokens. Credential and visibility tokens are substring matches. The gh and git tokens are matched
# on whole words of the command: the text is cut at every character that cannot be part of a shell word, so
# `git log --grep=commit` (one word, `--grep=commit`) and `ghost prose` are not publications, while
# `git -C dir commit` and `gh -R a/b pr create` are. Sets $tok to 1 when the text holds a token, and $credtok
# to 1 when it is a credential or visibility token (those never get the read-only exemption below).
words_of() {
    unescape "$1"
    printf ' %s ' "$dec" | tr -c 'A-Za-z0-9_.=:%@+,-' ' '
}

# The command arrives as JSON text, so a tab, a newline or a control character is a two- or six-character
# escape (`gh\tpr\tcreate`). Shell words are split on whitespace, so each such escape becomes one space before
# any word matching. Sets $dec. Builtins only: no process starts, and the test box has no sed.
unescape() {
    dec=""
    rest=$1
    while :; do
        case "$rest" in
            *\\*) ;;
            *) dec="$dec$rest"; break ;;
        esac
        dec="$dec${rest%%\\*}"
        rest=${rest#*\\}                       # what follows the first backslash
        case "$rest" in
            \\*) dec="$dec\\"; rest=${rest#?} ;;           # an escaped backslash: one literal backslash, not an escape lead
            [tnrfb]*) dec="$dec "; rest=${rest#?} ;;
            u00[0-2][0-9a-fA-F]*) dec="$dec "; rest=${rest#?????} ;;
            *) dec="$dec\\" ;;
        esac
    done
}

# has2 A B: in $w, the word A is followed, at any distance, by the word B.
has2() {
    case "$w" in *" $1 $2 "*|*" $1 "*" $2 "*) return 0 ;; esac
    return 1
}

match_tokens() {
    case "$1" in
        *s[s]h/id_*|*.aws/credentials*|*private-terms*|*PRIVATE_TERMS*|*.appstoreconnect*|*.grok/config.toml*) tok=1; credtok=1 ;;
        *.codex/auth.json*|*.codex/config.toml*|*.claude/.credentials.json*|*.netrc*|*.docker/config.json*) tok=1; credtok=1 ;;
        *.pem*|*.p8*|*--visibility*|*visibility=*|*private=*|*security*-password*|*security*dump-keychain*) tok=1; credtok=1 ;;
    esac
    if [ "$tok" = 0 ]; then
        # A text without these substrings cannot hold the words: skip the process.
        # (a coarse substring pre-check first, so `git status` and `ls` start nothing)
        case "$1" in
            *gh*pr*|*gh*issue*|*gh*release*|*gh*gist*|*gh*repo*|*gh*api*|*git*commit*|*git*tag*|*git*merge*|*git*push*)
                w=$(words_of "$1") || { tok=1; w=""; }        # no tr: take it as a token
                has2 gh pr || has2 gh issue || has2 gh release || has2 gh gist || has2 gh repo || has2 gh api && tok=1
                has2 git commit || has2 git tag || has2 git merge && tok=1
                # A push is the pre-push hook's to scan. One that skips the hook (`--no-verify` or an unambiguous
                # prefix of it, `-c core.hooksPath=...`) is a publication of its own.
                if has2 git push; then
                    case "$w" in *" --no-v"*|*[hH]ooks[pP]ath*) tok=1 ;; esac
                fi ;;
        esac
    fi
    if [ "$tok" = 0 ] && [ -n "${TEYLA_PRIVATE_TERMS:-}" ]; then
        case "$1" in *"$TEYLA_PRIVATE_TERMS"*) tok=1; credtok=1 ;; esac
    fi
}

# With no teyla to scan with, a command that only READS may go on; a publication may not. Read-only means: the
# words hold a viewing shape (gh pr|issue view|list|diff|checks|status, git log|show|diff|status, or a bare
# `gh api` GET) and none of the words that write (push, commit, create, merge, -X, -f, --input ...). A
# credential or visibility token is never read-only. Anything unsure is not read-only, so it is refused.
readonly_shape() {
    [ "$credtok" = 0 ] || return 1
    # Chaining, redirection, a substitution or a newline can append a second command to a read: no exemption.
    # (`gh pr view 12; cat ~/.aws/cred''entials`). The check runs on the raw text, before any decoding.
    case "$after" in
        *\;*|*\&*|*\|*|*\<*|*\>*|*\`*|*\$*|*'\n'*|*'\r'*|*'\u'*) return 1 ;;
    esac
    chk=${after%"
"}                                  # the payload ends in the newline the reader added
    case "$chk" in *"
"*) return 1 ;; esac
    # Quoting can hide a credential path from the substring tokens: look again with the quoting stripped.
    unescape "$after"
    stripped=$(printf '%s' "$dec" | tr -d "\\\\\"'\`\$") || return 1
    save=$tok; tok=0; credtok=0
    match_tokens "$stripped"
    hidden=$credtok; tok=$save; credtok=0
    [ "$hidden" = 0 ] || { credtok=1; return 1; }
    w=$(words_of "$after") || return 1
    case "$w" in
        *\ push\ *|*\ commit\ *|*\ tag\ *|*\ merge\ *|*\ create\ *|*\ edit\ *|*\ comment\ *|*\ close\ *|*\ reopen\ *|*\ ready\ *) return 1 ;;
        *\ review\ *|*\ delete\ *|*\ upload\ *|*\ fork\ *|*\ rename\ *|*\ archive\ *|*\ transfer\ *|*\ sync\ *|*\ publish\ *) return 1 ;;
        *\ release\ *|*\ gist\ *|*\ repo\ *|*\ lock\ *|*\ unlock\ *|*\ pin\ *|*\ unpin\ *|*\ develop\ *|*\ rerun\ *|*\ cancel\ *) return 1 ;;
        *\ -X*|*\ --method*|*\ -f*|*\ -F*|*\ --field*|*\ --raw-field*|*\ --input*|*\ PUT\ *|*\ POST\ *|*\ PATCH\ *|*\ DELETE\ *) return 1 ;;
    esac
    for sub in view list diff checks status; do
        has2 gh pr && has2 pr "$sub" && return 0
    done
    for sub in view list status; do
        has2 gh issue && has2 issue "$sub" && return 0
    done
    has2 git log || has2 git show || has2 git diff || has2 git status || has2 gh api && return 0
    return 1
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
    unescape "$after"
    stripped=$(printf '%s' "$dec" | tr -d "\\\\\"'\`\$") || return 1
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

# No teyla to scan with (no python3, or a python3 without the package, and no teyla executable to read an
# interpreter from): a read-only command goes on with one line on stderr, anything else is refused. This is the
# only place the guard fails open on a token, so a machine where teyla is a uv tool does not lose `gh pr view`
# and `git log` to a guard that cannot run.
no_teyla() {
    why="teyla is not installed for any python3 here"
    [ -z "${1:-}" ] || why="$1"
    if [ "$phase" = token ] && readonly_shape; then
        echo "teyla leak-guard: warning — teyla is not installed for any python3 here, so this read-only command is not scanned." >&2
        exit 0
    fi
    if [ "$phase" = token ]; then
        echo "teyla leak-guard: refused — $why, so this command's text cannot be scanned." >&2
        echo "  Install teyla, name its python with TEYLA_PYTHON, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>" >&2
        [ "$mode" = --grok ] && printf '{"decision": "deny", "reason": "teyla leak-guard: the guard cannot run here"}\n'
        exit 2
    fi
    exit 70
}

py="${TEYLA_PYTHON:-}"
if [ -z "$py" ] || [ ! -x "$py" ]; then
    if py=$(teyla_python); then
        :
    elif py=$(command -v python3); then
        # python3 on PATH is a guess: use it only if it really carries the package.
        "$py" -I -c 'import teyla.leak_guard' >/dev/null 2>&1 || no_teyla
    else
        no_teyla "python3 is not on PATH"
    fi
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
