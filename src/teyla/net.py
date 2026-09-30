"""The one network gate. Every call that leaves this machine asks `allowed()` first.

On a managed work laptop (Zscaler in the path, corporate code in the transcripts) an audit on
2026-09-29 found Teyla reaching out on its own from five places: the session-start hook's
update check, the daily routine's self-update, `gh` in `teyla routines`, models.dev, and the
plugin installer's git clone. Safe mode (`teyla config set safe.enabled=true`, or
TEYLA_SAFE=1) closes all of them here, in one place, so a new call site cannot forget.

A command the owner types by hand can still reach the network in safe mode by passing
`--allow-network` (`teyla update --allow-network`, `teyla models --refresh --allow-network`).
Nothing that runs unattended passes it: not the hook, not the launchd wrappers, not doctor.
"""
from __future__ import annotations

import sys

from . import config

_allow_once = False


def allow_for_this_command(on: bool = True) -> None:
    """Set by the CLI when the command line carries --allow-network; lasts for this process."""
    global _allow_once
    _allow_once = bool(on)


def allowed(cfg: dict | None = None) -> bool:
    return _allow_once or not config.safe_mode(cfg)


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
