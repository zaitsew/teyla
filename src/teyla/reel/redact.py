"""Redaction for Session Reel: every string passes through here before it can enter a Story.

A string is dropped rather than masked: a masked secret still tells the viewer where a secret
was. What happens to a string, in this order:

  1. secret shapes (the ones scripts/leak_check.py knows, `NAME=value` with KEY/TOKEN/SECRET/
     PASSWORD in the name) ........................................ the beat is dropped
  2. URLs become their host (a GitHub pull-request URL becomes `#<n>`)
  3. paths: inside a known root they become relative, any other absolute path becomes
     `…/<basename>`; a home directory or a user name never survives
  4. private terms (the list leak_check uses), and a run of 32+ base64/hex characters
     ......................................................... the beat is dropped
  5. e-mail addresses and phone numbers ........................... the line is dropped
  6. length: cut at a word boundary with `…`, never mid-token

The secret patterns and the private-terms loader are leak_check's own: this module imports
scripts/leak_check.py (shipped inside the wheel as `teyla/_leak_check.py`), it does not copy it.
"""
from __future__ import annotations

import collections
import getpass
import importlib.util
import os
import re
from pathlib import Path
from typing import NamedTuple

REASONS = ("secret", "private-term", "email", "path", "too-long")
ELLIPSIS = "\u2026"


def _leak():
    """scripts/leak_check.py as a module: from the wheel's copy, else the source checkout's."""
    here = Path(__file__).resolve()
    for cand in (here.parents[1] / "_leak_check.py", here.parents[3] / "scripts" / "leak_check.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("teyla_reel_leak_check", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError("teyla reel: scripts/leak_check.py not found; redaction cannot run without it")


# An environment-style name (upper case) with `=` or `: `, or any-case `name=value`.
_NAME_VALUE = (
    re.compile(r"\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*\s*(?:=\s*\S{3,}|:\s*\S{8,})"),
    re.compile(r"\b[A-Za-z0-9_.-]*(?:key|token|secret|password|passwd)[A-Za-z0-9_.-]*=\S{3,}", re.I),
)
_LONG_RUN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_=-]{32,}(?![A-Za-z0-9+/=_-])")
_HEX_RUN = re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])(?:\+\d[\d ().-]{7,}\d|\(\d{3}\)[ .-]?\d{3}[ .-]?\d{4}|\d{3}[ .-]\d{3}[ .-]\d{2,4}(?:[ .-]\d{2,4})?|\d{10,})(?![\w])")
_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"`<>)\]]+")
_GH_PR = re.compile(r"^https?://(?:www\.)?github\.com/[^/\s]+/[^/\s]+/pull/(\d+)")
# An absolute path (not the tail of a URL or a word) or a ~ path.
_PATH = re.compile(r"(?<![\w:/.~\u2026-])(?:~|/[A-Za-z0-9._@+-]+)(?:/[^\s'\"`<>|;,()\[\]{}:=]*)+|(?<![\w:/.~\u2026-])~(?![\w/])")
# A checkout under a home directory: .worktrees/<repo>/<branch>/…, .codex/worktrees/<id>/<repo>/…, repos/<repo>/…
_CHECKOUT = re.compile(r"^(?:\.worktrees/[^/]+/[^/]+|\.codex/worktrees/[^/]+/[^/]+|repos/[^/]+)/(.+)$")
_OTHER_HOME = re.compile(r"^(?:/Users|/home)/[^/]+/(.+)$")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


class Out(NamedTuple):
    text: str
    fatal: bool = False  # the whole beat must go (secret, private term)
    skip: bool = False   # this line must go (e-mail, phone)


def cut(text: str, limit: int) -> str:
    """`text` cut to `limit` characters at a word boundary, ending in `…`; a single token longer
    than the limit is cut to the limit and ends in `…` too (the only mid-token cut: nothing else fits)."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if text[limit - 1] != " " and " " in head:
        head = head[: head.rindex(" ")]
    head = head.rstrip(" ,;:.-")
    return (head or text[: limit - 1]) + ELLIPSIS


def shorten_path(path: str, limit: int) -> str:
    """A path kept by its tail, starting at a directory boundary: `…/reel/select.py`."""
    if len(path) <= limit:
        return path
    tail = path[-(limit - 1):]
    i = tail.find("/")
    if 0 <= i < len(tail) - 1:
        tail = tail[i:]
    return ELLIPSIS + tail


class Redactor:
    """Holds the term list, the roots a path may be made relative to, and the drop counters."""

    def __init__(self, roots: list[str] | tuple[str, ...] = (), *, home: str | None = None, terms: bool = True):
        self._leak = _leak()
        cfg = self._leak.Config()
        if terms:
            self._leak.load_terms(cfg)
        self.notes = list(cfg.notes)
        self._terms = [r for _t, r in cfg.terms]
        self._secrets = list(self._leak.SECRET_RES)
        self.home = os.path.expanduser("~") if home is None else home
        # The login name and the home directory's name are private whatever the term list says.
        for name in {Path(self.home).name, _login()}:
            if name and len(name) > 2:
                self._terms.append(re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I))
        self.roots = sorted({r.rstrip("/") for r in roots if r and r != "/"}, key=len, reverse=True)
        self.dropped: collections.Counter = collections.Counter()

    # -- checks ------------------------------------------------------------------------------

    def has_secret(self, text: str) -> bool:
        return any(r.search(text) for r in self._secrets) or any(r.search(text) for r in _NAME_VALUE)

    def has_term(self, text: str) -> bool:
        return any(r.search(text) for r in self._terms)

    def term_spans(self, text: str) -> list[tuple[int, int]]:
        """Where each private term matches in `text`, as (start, end) pairs."""
        return [(m.start(), m.end()) for r in self._terms for m in r.finditer(text)]

    @staticmethod
    def has_entropy_run(text: str) -> bool:
        if _HEX_RUN.search(text):
            return True
        for m in _LONG_RUN.finditer(text):
            run = m.group(0)
            if re.search(r"\d", run) and re.search(r"[a-z]", run) and re.search(r"[A-Z]", run):
                return True
        return False

    # -- rewrites ----------------------------------------------------------------------------

    def _url(self, m: re.Match) -> str:
        url = m.group(0).rstrip(".,;:!?")
        pr = _GH_PR.match(url)
        if pr:
            return "#" + pr.group(1)
        host = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^/@\s]*@)?([^/:?#\s]*)", url)
        return (host.group(1) if host and host.group(1) else "link") + m.group(0)[len(url):]

    def _path(self, m: re.Match) -> str:
        path = m.group(0).rstrip(".")
        trail = m.group(0)[len(path):]
        self.dropped["path"] += 1
        return self.path(path) + trail

    def path(self, path: str) -> str:
        """One path as it may be shown. Inside a known root: relative. Otherwise `…/<basename>`."""
        home = self.home.rstrip("/")
        if path.startswith("~/") or path == "~":
            path = home + path[1:]
        for root in self.roots:
            if path == root:
                return "."
            if path.startswith(root + "/"):
                return path[len(root) + 1:]
        under = path[len(home) + 1:] if path.startswith(home + "/") else (_OTHER_HOME.match(path) or [None, None])[1]
        m = _CHECKOUT.match(under or "")
        if m:
            return m.group(1)
        parts = [p for p in path.split("/") if p]
        if path.rstrip("/") == home or len(parts) <= 2 and parts[:1] in (["Users"], ["home"]):
            return ELLIPSIS + "/~"
        return ELLIPSIS + "/" + (parts[-1] if parts else "")

    def clean(self, raw: str, limit: int | None = None) -> Out:
        """One string through every rule. `limit` is the slot it must fit (cut with `…`)."""
        text = " ".join(_CTRL.sub(" ", raw or "").split())
        if self.has_secret(text):
            self.dropped["secret"] += 1
            return Out("", fatal=True)
        text = _URL.sub(self._url, text)
        text = _PATH.sub(self._path, text)
        if self.has_term(text):
            self.dropped["private-term"] += 1
            return Out("", fatal=True)
        if self.has_entropy_run(text):
            self.dropped["secret"] += 1
            return Out("", fatal=True)
        if _EMAIL.search(text) or _PHONE.search(text):
            self.dropped["email"] += 1
            return Out("", skip=True)
        if limit is not None and len(text) > limit:
            text = cut(text, limit)
            self.dropped["too-long"] += 1
        return Out(text)

    def allow(self, name: str) -> None:
        """Stop treating `name` (the session's own repo, shown on request) as a private term."""
        self._terms = [r for r in self._terms if not r.search(name)]

    def check_repo(self, name: str) -> bool:
        """True when a repo name is itself a private term."""
        return self.has_term(name)


def _login() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no login name on a stripped-down container
        return ""
