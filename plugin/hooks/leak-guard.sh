#!/bin/sh
# PreToolUse (Bash, Read, Edit, Write): the agent boundary. Nothing an agent publishes carries a secret
# or a private term, and the agent never reads a credential. docs/SHIELD.md, SH6 and 5.2.
#
# Exit 0 allows the call. Exit 2 refuses it and shows stderr to the model.
#
# TWO FAILURE MODES, and the line between them is a FIXED STRING MATCH, not a classifier:
#
#   A command whose text contains none of the tokens below passes at once: exit 0, no process started, no
#   Python. If this script itself errors on such a command it prints one warning line and exits 0, like the
#   machine guard, because a guard that blocks every `ls` over its own bug gets uninstalled.
#
#   A command that contains a token is FAIL-CLOSED. From the moment one matches, a missing python3, a missing
#   teyla package, a scanner that crashes or times out, or any error here is exit 2 with the reason. A
#   publication is never waved through unscanned. These commands are rare and explicit; a wrong refusal
#   costs one retry.
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
# the command with `TEYLA_LEAK_GUARD=0 ` (or by setting it in the hook's own environment). The skip is
# appended to $TEYLA_HOME/leak-skips.log. The prefix lifts the publication scan only: a credential path, a
# Keychain dump and a visibility change are refused whatever it says.
#
# `--grok`: Grok shows only the first stderr line of an exit 2, so the refusal is also printed to stdout as
# {"decision":"deny","reason":...}. Claude Code and Codex read stderr.
#
# TEYLA_HOME overrides ~/.teyla (tests, second profiles). TEYLA_PYTHON names the python3 to use.

mode="${1:-}"
phase=coarse
status=0

on_exit() {
    status=$?
    trap - EXIT
    case "$status" in 0|2) exit "$status" ;; esac
    if [ "$phase" = token ]; then
        echo "teyla leak-guard: refused — the guard failed (status $status) on a command that publishes text or touches a credential." >&2
        echo "  A guard that cannot run does not wave a publication through. Repair teyla, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>" >&2
        [ "$mode" = --grok ] && printf '{"decision": "deny", "reason": "teyla leak-guard: the guard failed on a command that publishes text or touches a credential"}\n'
        exit 2
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

hard=0
pub=0

# Credential paths, a Keychain dump, a visibility change: refused whatever a skip prefix says.
case "$after" in
    *s[s]h/id_*|*.aws/credentials*|*private-terms*|*PRIVATE_TERMS*|*.appstoreconnect*|*.grok/config.toml*) hard=1 ;;
    *.codex/auth.json*|*.codex/config.toml*|*.claude/.credentials.json*|*.netrc*|*.docker/config.json*) hard=1 ;;
    *.pem*|*.p8*|*--visibility*|*visibility=*|*private=*|*security*-password*|*security*dump-keychain*) hard=1 ;;
esac
if [ "$hard" = 0 ] && [ -n "${TEYLA_PRIVATE_TERMS:-}" ]; then
    case "$after" in *"$TEYLA_PRIVATE_TERMS"*) hard=1 ;; esac
fi

# Publications: `gh` with a verb group, `git` with commit, tag or merge, anywhere in the command.
case "$after" in
    *gh*pr*|*gh*issue*|*gh*release*|*gh*gist*|*gh*repo*|*gh*api*) pub=1 ;;
    *git*commit*|*git*tag*|*git*merge*) pub=1 ;;
esac

[ "$hard" = 1 ] || [ "$pub" = 1 ] || exit 0
# leak-guard:coarse-end

phase=token
# leak-guard:token-begin

skip=0
if [ "${TEYLA_LEAK_GUARD:-}" = 0 ]; then
    skip=env
    hard=0
else
    # The marker counts only at the start of a command: after the opening quote, or after ; & | ( or a
    # newline. A PR body that mentions it does not skip anything.
    case "$after" in
        *[!\\]\"TEYLA_LEAK_GUARD=0[\ \\]*|*[\;\&\|\(]TEYLA_LEAK_GUARD=0[\ \\]*|*[\;\&\|\(]\ TEYLA_LEAK_GUARD=0[\ \\]*|*\\nTEYLA_LEAK_GUARD=0[\ \\]*)
            skip=prefix ;;
    esac
fi

if [ "$skip" != 0 ] && [ "$hard" = 0 ]; then
    dir="${TEYLA_HOME:-$HOME/.teyla}"
    mkdir -p "$dir"
    printf '%s\tskip\t%s\tpublication\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$skip" >> "$dir/leak-skips.log"
    exit 0
fi

py="${TEYLA_PYTHON:-}"
if [ -z "$py" ] || [ ! -x "$py" ]; then
    py=$(command -v python3) || {
        echo "teyla leak-guard: refused — python3 is not on PATH, so this command's text cannot be scanned." >&2
        echo "  Install python3 and teyla, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>" >&2
        exit 2
    }
fi

# The enforcement code is teyla.leak_guard, from the installed package: -I ignores PYTHONPATH and the working
# directory, so a repo cannot plant its own copy. Exit 0 allows, 2 refuses, anything else is a failure and
# becomes a refusal in on_exit.
if printf '%s' "$payload" | "$py" -I -m teyla.leak_guard ${mode:+"$mode"}; then
    exit 0
else
    exit $?
fi
