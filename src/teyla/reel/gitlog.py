"""The git history a session produced: commits between its start and end, with their line counts.

Everything here is optional: a session whose directory is gone, or is not a repository, simply
has no git numbers (`commits` returns None) and the Story falls back to what the transcript shows.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import os
import re
import subprocess

_WORKTREE = re.compile(r"/\.worktrees/([^/]+)/[^/]+/?$")


@dataclasses.dataclass
class GitCommit:
    sha: str
    subject: str
    at: float                      # committer time, POSIX
    added: int = 0
    removed: int = 0
    files: list = dataclasses.field(default_factory=list)


def _git(top: str, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", top, *args], capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def toplevel(path: str | None) -> str | None:
    """The root of the working tree holding `path` (a file or a directory), or None."""
    if not path:
        return None
    d = path if os.path.isdir(path) else os.path.dirname(path)
    if not d or not os.path.isdir(d):    # a removed worktree: do not climb into whatever encloses it
        return None
    out = _git(d, "rev-parse", "--show-toplevel")
    return out.strip() or None if out else None


def repo_name(top: str) -> str:
    """`teyla` for ~/repos/teyla and for ~/.worktrees/teyla/<branch>."""
    m = _WORKTREE.search(top.rstrip("/") + "/")
    return m.group(1) if m else os.path.basename(top.rstrip("/"))


def commits(top: str, start: _dt.datetime, end: _dt.datetime, slack_s: int = 60) -> list[GitCommit] | None:
    """Non-merge commits on any local branch of `top` committed by the repo's own user between
    `start` and `end`, oldest first, with their numstat. None when git cannot answer."""
    since = (start - _dt.timedelta(seconds=slack_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (end + _dt.timedelta(seconds=slack_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    args = ["log", "--branches", "--no-merges", f"--since={since}", f"--until={until}", "--numstat",
            "--format=%x1e%H%x1f%ct%x1f%s"]
    email = (_git(top, "config", "user.email") or "").strip()
    if email:
        args += ["--fixed-strings", "--author=" + email]
    out = _git(top, *args)
    if out is None:
        return None
    result: list[GitCommit] = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        c = GitCommit(parts[0][:7], parts[2].strip(), float(parts[1]))
        for line in body.splitlines():
            m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line)
            if m:
                c.added += int(m.group(1)) if m.group(1) != "-" else 0
                c.removed += int(m.group(2)) if m.group(2) != "-" else 0
                c.files.append(m.group(3))
        result.append(c)
    result.sort(key=lambda c: c.at)
    return result
