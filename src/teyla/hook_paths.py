"""The files a tool call edits, from either harness's PreToolUse payload.

Claude Code (and Grok, through its matcher aliases) name one file in `tool_input.file_path`,
`notebook_path` or `path`. Codex has one edit tool, `apply_patch`: its hook payload has
`tool_name: "apply_patch"` and the whole patch text in `tool_input.command`, with one header line per
file (`*** Add File: p`, `*** Update File: p`, `*** Delete File: p`, and `*** Move to: p` after an
update). The guards keep one decision function; only this parsing differs.
"""
from __future__ import annotations

import re

PATCH_TOOLS = frozenset({"apply_patch", "ApplyPatch"})
_HEADER = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to):[ \t]*(.+?)[ \t]*$")
_KEYS = ("file_path", "notebook_path", "path")


def patch_paths(text: str) -> list[str]:
    """Every path an apply_patch text adds, updates, deletes or moves to, in order, without repeats."""
    out: list[str] = []
    for line in str(text or "").splitlines():
        m = _HEADER.match(line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def is_patch_call(payload: dict) -> bool:
    return payload.get("tool_name") in PATCH_TOOLS


def edit_paths(payload: dict) -> list[str]:
    """The files the call names: the patch's files for apply_patch, else the one path key set."""
    ti = payload.get("tool_input")
    if is_patch_call(payload):
        if isinstance(ti, dict):
            ti = ti.get("command") or ti.get("input") or ti.get("patch")
        return patch_paths(ti if isinstance(ti, str) else "")
    if not isinstance(ti, dict):
        return []
    for key in _KEYS:
        v = ti.get(key)
        if isinstance(v, str) and v:
            return [v]
    return []
