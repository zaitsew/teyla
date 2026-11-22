"""`teyla platform hook` — refuse the first edit of a closed secondary platform's file (POLICY §14).

The push check fires after the tokens are spent. This runs as a PreToolUse hook on Edit, Write, MultiEdit and
NotebookEdit, reads the tool call as JSON on stdin and decides before the first write:

    file_path -> git root of that file -> teyla.toml + docs/parity.toml in that worktree
              -> platforms_of(path) -> a non-primary platform whose gate is closed  => exit 2

It passes (exit 0, silently) for: no teyla.toml, no parity ledger, a path that maps to no platform or to the
primary, an open train or an unexpired override, and TEYLA_PLATFORM_LABEL set to a valid label (logged like the
push check). Any internal error passes: a gate that breaks must not break the tool call. The one deliberate
refusal besides the closed gate is a label that cannot be written to the log, because an exception must be on
record. `plugin/hooks/platform-gate.sh` runs this module only when the file's repo has a ledger, so a repo
without one pays no Python start.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys

from . import parity, platform_gate

MESSAGE = ("platform gate: {plat} is closed in {product}: {reason}. Primary first (POLICY §14). "
           "Build it on {primary}; the owner opens a train with his feedback (`teyla parity status`).")


def _root_of(path: pathlib.Path) -> pathlib.Path | None:
    for d in [path.parent, *path.parent.parents]:
        if (d / ".git").exists():
            return d
    return None


def decide(payload: dict, today: datetime.date | None = None) -> tuple[int, str]:
    """`(exit code, stderr text)` for one tool call. Pure apart from reading the repo and the label log."""
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    raw = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    if not raw:
        return 0, ""
    path = pathlib.Path(str(raw))
    if not path.is_absolute():
        path = pathlib.Path(str(payload.get("cwd") or ".")) / path
    path = pathlib.Path(os.path.abspath(path))
    root = _root_of(path)
    if root is None:
        return 0, ""
    ledger = parity.load(root)
    if ledger is None:
        return 0, ""
    manifest = parity.read_manifest(root)
    pz = manifest.get("productize") if isinstance(manifest.get("productize"), dict) else {}
    paths = pz.get("paths") if isinstance(pz.get("paths"), dict) else {}
    primary = str(pz.get("primary") or "").strip()
    if not paths or not primary:
        return 0, ""
    rel = path.relative_to(root).as_posix()
    hit = platform_gate.platforms_of(rel, paths)
    hit = [h for h in hit if h != primary]       # a file the primary also claims is still a secondary's file
    if not hit:
        return 0, ""
    today = today or datetime.date.today()
    triggers = pz.get("triggers") if isinstance(pz.get("triggers"), dict) else {}
    product = str((manifest.get("product") or {}).get("name") or root.name) if isinstance(
        manifest.get("product"), dict) else root.name
    for plat in hit:
        problem = platform_gate.trigger_problem(triggers, plat)
        is_open, reason = parity.gate_from(ledger, plat, today)
        if is_open and not problem:
            continue
        label = (os.environ.get("TEYLA_PLATFORM_LABEL") or "").strip()
        if label in platform_gate.LABELS:
            try:
                platform_gate.log_row(root, label, [plat], f"edit:{rel}")
            except platform_gate.GateError as e:
                return 2, f"platform gate: refused: {e}\n"
            continue
        return 2, MESSAGE.format(plat=plat, product=product, reason=problem or reason, primary=primary) + "\n"
    return 0, ""


def main(stdin=None, today: datetime.date | None = None) -> int:
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        code, text = decide(payload if isinstance(payload, dict) else {}, today)
    except (Exception, SystemExit):  # noqa: BLE001 — fail open: a broken gate never breaks the tool call
        return 0
    if text:
        sys.stderr.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
