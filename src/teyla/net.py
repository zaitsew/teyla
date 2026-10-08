"""The one network gate. Every call that leaves this machine asks `allowed()` first.

On a managed work laptop (a TLS-intercepting proxy in the path, corporate code in the transcripts) an audit
found Teyla reaching out on its own from five places: the session-start hook's
update check, the daily routine's self-update, `gh` in `teyla routines`, models.dev, and the
plugin installer's git clone. Safe mode (`teyla config set safe.enabled=true`, or
TEYLA_SAFE=1) closes all of them here, in one place, so a new call site cannot forget.

A command the owner types by hand can still reach the network in safe mode by passing
`--allow-network` (`teyla update --allow-network`, `teyla models --refresh --allow-network`).
Nothing that runs unattended passes it: not the hook, not the launchd wrappers, not doctor.

One opt-in widens that, and only for one command: `safe.auto_update = true` lets `teyla update`
(the daily routine runs `teyla update --quiet`) look up the latest published release and install
it, as if it carried --allow-network. `update_scope()` is the only door; it covers the body of
`cmd_update` and nothing else, so doctor, the session hook, models, gh and the plugin installer
stay closed. Post-update steps run as child processes, which do not inherit the scope.
"""
from __future__ import annotations

import contextlib
import sys

from . import config

_allow_once = False
_update_scope = False


def allow_for_this_command(on: bool = True) -> None:
    """Set by the CLI when the command line carries --allow-network; lasts for this process."""
    global _allow_once
    _allow_once = bool(on)


@contextlib.contextmanager
def update_scope(cfg: dict | None = None):
    """Inside the block, the network is allowed when safe mode has `safe.auto_update` on (a no-op
    otherwise). Used by `teyla update` around its own body, nowhere else."""
    global _update_scope
    prev = _update_scope
    _update_scope = prev or config.safe_auto_update(cfg)
    try:
        yield
    finally:
        _update_scope = prev


def allowed(cfg: dict | None = None) -> bool:
    return _allow_once or _update_scope or not config.safe_mode(cfg)


def refusal(what: str) -> str:
    return (f"teyla: safe mode is on (safe.enabled / {config.SAFE_ENV}), so {what} is refused; "
            f"run it by hand with --allow-network, or: teyla config set safe.enabled=false")


def gate(what: str, cfg: dict | None = None, *, quiet: bool = False) -> bool:
    """True when `what` may use the network. When not, prints the one-line refusal to stderr
    (unless quiet) and returns False; the caller decides what "refused" means for its output."""
    if allowed(cfg):
        return True
    if not quiet:
        print(refusal(what), file=sys.stderr)
    return False
