"""`teyla console` — the data behind the app's admin sections (`docs/CONSOLE.md`).

    teyla console [SECTION] [--json] [--refresh]

One JSON object per section. Each section is built by one function in its own module, so a section
that fails shows its own error and the others still load. The result is cached in
~/.teyla/console-cache.json (mode 0600); `teyla state` carries the compact part to the phone.
"""
from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
import time

VERSION = 1
MAX_AGE_S = 30 * 60

# section name -> module that has `section(now) -> dict` (and may have `compact(section) -> dict`).
# A module that does not exist yet is a section with an error, never a crash.
SECTIONS: dict[str, str] = {
    "operations": "console_operations",
    "money": "console_money",
    "playbook": "console_playbook",
    "growth": "growth",
}


def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def cache_path() -> pathlib.Path:
    return home() / "console-cache.json"


def _module(name: str):
    return importlib.import_module(f"{__package__}.{SECTIONS[name]}")


def build_section(name: str, now: float) -> dict:
    """One section, or `{"error": ...}` when its source fails."""
    try:
        return _module(name).section(now)
    except Exception as e:  # a broken source must not take the other sections down
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def build(now: float | None = None, only: str | None = None) -> dict:
    now = time.time() if now is None else now
    names = [only] if only else list(SECTIONS)
    return {"version": VERSION, "generated": now, **{n: build_section(n, now) for n in names}}


def write_cache(rep: dict) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rep, f)
    os.replace(tmp, path)


def read_cache() -> dict | None:
    try:
        rep = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return None
    return rep if isinstance(rep, dict) else None


def compact(rep: dict | None) -> dict | None:
    """What `teyla state` carries: each section's `compact`, or its headline. Keeps the phone's file small."""
    if not rep:
        return None
    out: dict = {"version": rep.get("version", VERSION), "generated": rep.get("generated")}
    for name in SECTIONS:
        sec = rep.get(name)
        if not isinstance(sec, dict):
            continue
        try:
            fn = getattr(_module(name), "compact", None)
            out[name] = fn(sec) if fn else {k: sec[k] for k in ("headline", "error") if k in sec}
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    return out


def render_text(rep: dict) -> str:
    lines = []
    for name in SECTIONS:
        sec = rep.get(name)
        if sec is None:
            continue
        if sec.get("error"):
            lines.append(f"{name}: unavailable ({sec['error']})")
            continue
        h = sec.get("headline") or {}
        lines.append(f"{name}: {h.get('label', '')} {h.get('value', '-')}".rstrip())
    return "\n".join(lines) + "\n"


def cmd_console(args) -> int:
    cached = None if args.refresh else read_cache()
    fresh = cached and time.time() - float(cached.get("generated") or 0) < MAX_AGE_S
    if args.section:
        rep = {"version": VERSION, "generated": time.time(), args.section: build_section(args.section, time.time())} \
            if not fresh or args.section not in cached else cached
    elif fresh:
        rep = cached
    else:
        rep = build()
        write_cache(rep)
    if args.section:
        rep = {k: rep[k] for k in ("version", "generated", args.section)}
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        sys.stdout.write(render_text(rep))
    return 0


def register(sp):
    q = sp.add_parser("console", help="the data behind the app's admin sections (operations, money, playbook, growth)")
    q.set_defaults(fn=cmd_console)
    q.add_argument("section", nargs="?", choices=list(SECTIONS), help="one section only")
    q.add_argument("--json", action="store_true", help="JSON, for the Mac app")
    q.add_argument("--refresh", action="store_true", help="rebuild now instead of reading a cache under 30 minutes old")
    return q
