#!/bin/sh
# PreToolUse: the kill switch, and the capability grants of a `teyla run`.
#
# Exit 0 allows the tool call. Exit 2 blocks it and shows stderr to the model.
# There is no third answer here on purpose — "the hook broke" must never quietly
# become "the tool ran".
#
# Three states, cheapest first, because this runs before *every* tool call and a
# hook that costs a Python interpreter start on an ordinary session is a hook
# people uninstall:
#
#   1. ~/.teyla/KILL exists      -> exit 2 with the reason. Pure sh, no python.
#   2. TEYLA_GRANTS unset        -> exit 0, silently. Not a routine run.
#   3. TEYLA_GRANTS set          -> hand the call to teyla.control.hook.
#
# Only state 3 starts python, and only state 3 fails closed: if the enforcement
# code cannot be imported there, the call is refused rather than waved through,
# because a run launched under grants with no working enforcement is exactly the
# case the grants exist for. An ordinary session never reaches that branch.
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

[ -n "${TEYLA_GRANTS:-}" ] || exit 0

# The plugin ships inside the teyla repo, so its sources sit one level up. Used
# only as a fallback, when teyla is not installed as a package on this machine.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    TEYLA_HOOK_SRC="${CLAUDE_PLUGIN_ROOT}/../src"
else
    TEYLA_HOOK_SRC="${0%/*}/../../src"
fi
export TEYLA_HOOK_SRC

python3 -c '
import os, sys

src = os.environ.get("TEYLA_HOOK_SRC")
try:
    from teyla.control.hook import main
except Exception:
    if src and os.path.isdir(src):
        sys.path.insert(0, os.path.abspath(src))
    try:
        from teyla.control.hook import main
    except Exception as e:
        sys.stderr.write(
            "teyla: this call runs under TEYLA_GRANTS but capability enforcement could not be "
            "loaded (%s), so it is refused. Install teyla, or unset TEYLA_GRANTS.\n" % e
        )
        raise SystemExit(2)

raise SystemExit(main())
'
status=$?

# Anything other than allow/block is normalised to block: a crashed interpreter
# under an armed run is a denial, not a permission.
[ "$status" -eq 0 ] && exit 0
exit 2
