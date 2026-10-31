"""`teyla leak install` and `teyla leak terms --suggest` — the leak gate in every repo (Shield, SH5).

    teyla leak install [repo] [--all] [--uninstall]
    teyla leak terms --suggest [--yes] [--json]

`install` writes `.githooks/pre-commit` (the index) and `.githooks/pre-push` (the commits the remote lacks),
POSIX `sh`, and points `core.hooksPath` at them. A hook that is already there and is not ours keeps its
content: our call goes in as a delimited block at the top, and `--uninstall` takes the block out again.
A missing `teyla` on PATH is exit 2 (a coverage gap is not a pass); `TEYLA_LEAK=0` skips one command and the
skip is logged to `~/.teyla/leak-skips.log`.

`terms --suggest` lists private-term candidates from facts the machine already knows (git identity, the
login and home names, the computer name, tester e-mails and bundle-id organisations in this repo's
`teyla.toml`, hosts in `platform.toml`). It never reads another repo's content, prints every candidate
masked, and appends the full values to the terms file only with `--yes`.

The argparse parser of `teyla leak` takes a positional repo, so it cannot also carry sub-commands; the two
are registered as `leak-install` and `leak-terms`, and `alias()` lets `teyla leak install` mean the first.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import platform as stdlib_platform
import shutil
import stat
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

from . import leak

MARK = "# teyla leak gate"
BEGIN = "# >>> teyla leak gate"
END = "# <<< teyla leak gate"
META = ".teyla-leak-gate"
DEFAULT_DIR = ".githooks"
HOOKS = ("pre-commit", "pre-push")
GENERIC = {"user", "users", "root", "admin", "home", "runner", "ubuntu", "vagrant", "docker", "test", "localhost",
           "macbook", "imac", "ci", "build", "github", "example", "local"}
MIN_TERM = 4
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# --- the hooks ---------------------------------------------------------------------------------

def block(hook: str) -> str:
    """The delimited sh snippet: skip when TEYLA_LEAK=0 (logged), scan, exit non-zero on a finding or a gap."""
    if hook == "pre-commit":
        remote, scan, show = "", "teyla leak --staged --quiet", "teyla leak --staged"
    else:
        remote = '_tlg_remote="${1:-origin}"\n'
        scan, show = 'teyla leak --outgoing "$_tlg_remote" --quiet', 'teyla leak --outgoing "$_tlg_remote"'
    return f"""{BEGIN} ({hook}) -- written by `teyla leak install`; `teyla leak install --uninstall` removes it
{remote}if [ "${{TEYLA_LEAK:-1}}" = "0" ]; then
  _tlg_home="${{TEYLA_HOME:-$HOME/.teyla}}"
  mkdir -p "$_tlg_home" 2>/dev/null
  printf '%s\\t%s\\t%s\\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")" "{hook}" >> "$_tlg_home/leak-skips.log" 2>/dev/null
elif ! command -v teyla >/dev/null 2>&1; then
  echo "teyla leak gate: teyla not found; install it or set TEYLA_LEAK=0 for this command" >&2
  exit 2
else
  {scan} </dev/null >/dev/null 2>&1
  _tlg_rc=$?
  if [ "$_tlg_rc" -ne 0 ]; then
    {show} </dev/null >&2
    echo "teyla leak gate: {hook} refused (exit $_tlg_rc); fix the findings, or set TEYLA_LEAK=0 for this command" >&2
    exit "$_tlg_rc"
  fi
fi
unset _tlg_home _tlg_rc _tlg_remote
{END}
"""


def standalone(hook: str) -> str:
    return f"#!/bin/sh\n{MARK} ({hook}): written by `teyla leak install`; rerun it instead of editing\n{block(hook)}"


def _is_ours(text: str) -> bool:
    lines = text.splitlines()
    return len(lines) > 1 and lines[0].startswith("#!") and lines[1].startswith(MARK + " (")


def _has_block(text: str) -> bool:
    return any(ln.startswith(BEGIN) for ln in text.splitlines())


def _strip_block(text: str) -> str:
    out, skip = [], False
    for ln in text.splitlines(keepends=True):
        if not skip and ln.startswith(BEGIN):
            skip = True
            continue
        if skip:
            if ln.startswith(END):
                skip = False
            continue
        out.append(ln)
    return "".join(out)


def _insert_block(text: str, hook: str) -> str:
    if text.startswith("#!"):
        first, _, rest = text.partition("\n")
        return first + "\n" + block(hook) + rest
    return block(hook) + text


def chain(text: str, hook: str) -> str:
    """`text` with our block at the top (after a shebang), replacing an older block of ours."""
    return _insert_block(_strip_block(text) if _has_block(text) else text, hook)


# --- git helpers -------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _root(start: Path) -> Path | None:
    p = _git(start, "rev-parse", "--show-toplevel") if start.is_dir() else None
    return Path(p.stdout.strip()) if p is not None and p.returncode == 0 and p.stdout.strip() else None


def _local_hooks_path(root: Path) -> str | None:
    p = _git(root, "config", "--local", "--get", "core.hooksPath")
    return p.stdout.strip() or None if p.returncode == 0 else None


def _hooks_dir(root: Path, configured: str | None) -> Path | None:
    """The directory the hooks live in; None when `core.hooksPath` leads outside the repo."""
    rel = configured or DEFAULT_DIR
    p = Path(rel).expanduser()
    d = p if p.is_absolute() else root / p
    try:
        d.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return d


def _read_meta(d: Path) -> dict:
    try:
        m = json.loads((d / META).read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_exec(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o755)


# --- install / uninstall -----------------------------------------------------------------------

def install(root: Path) -> tuple[int, str]:
    """Install the gate in one repo; returns (exit code, one line)."""
    name = root.name
    configured = _local_hooks_path(root)
    d = _hooks_dir(root, configured)
    if d is None:
        return 2, f"{name}: core.hooksPath points outside the repo ({configured}); not touched"
    rel = os.path.relpath(d, root)
    meta = _read_meta(d)
    set_by_us = bool(meta.get("hooks_path_set")) and meta.get("hooks_path") == configured and configured is not None
    d.mkdir(parents=True, exist_ok=True)
    done, notes = {}, []
    for hook in HOOKS:
        f = d / hook
        if f.is_symlink():
            return 2, f"{name}: {rel}/{hook} is a symlink; not touched"
        before = f.read_text(encoding="utf-8", errors="surrogateescape") if f.exists() else None
        if before is None:
            _write_exec(f, standalone(hook))
            done[hook], state = "file", "new"
        elif _is_ours(before):
            done[hook] = "file"
            state = "unchanged" if before == standalone(hook) else "updated"
            if state == "updated":
                _write_exec(f, standalone(hook))
        else:
            new = chain(before, hook)
            done[hook] = "block"
            state = "unchanged" if new == before else "chained"
            if new != before:
                f.write_text(new, encoding="utf-8", errors="surrogateescape")
            if not os.access(f, os.X_OK):
                notes.append(f"{hook} is not executable, so git skips it (chmod +x)")
        notes.append(f"{hook} {state}")
    path_state = "core.hooksPath unchanged"
    if configured is None:
        r = _git(root, "config", "--local", "core.hooksPath", DEFAULT_DIR)
        if r.returncode != 0:
            return 2, f"{name}: cannot set core.hooksPath: {r.stderr.strip()}"
        set_by_us, path_state = True, f"core.hooksPath set to {DEFAULT_DIR}"
    elif configured != DEFAULT_DIR and not set_by_us:
        path_state = f"core.hooksPath already {configured}; installed there"
    new_meta = {"hooks": done, "hooks_path": configured or DEFAULT_DIR, "hooks_path_set": set_by_us, "version": 1}
    if _git(root, "config", "--global", "--get", "core.hooksPath").returncode == 0 and configured is None:
        notes.append("this repo's hooks now override your global core.hooksPath")
    text = json.dumps(new_meta, indent=2, sort_keys=True) + "\n"
    mp = d / META
    if not mp.exists() or mp.read_text(encoding="utf-8") != text:
        mp.write_text(text, encoding="utf-8")
    return 0, f"{name}: {', '.join(notes)} in {rel}; {path_state}"


def uninstall(root: Path) -> tuple[int, str]:
    name = root.name
    configured = _local_hooks_path(root)
    d = _hooks_dir(root, configured)
    if d is None:
        return 2, f"{name}: core.hooksPath points outside the repo ({configured}); not touched"
    meta = _read_meta(d)
    removed = []
    for hook in HOOKS:
        f = d / hook
        if f.is_symlink() or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="surrogateescape")
        if _is_ours(text):
            f.unlink()
            removed.append(f"{hook} removed")
        elif _has_block(text):
            f.write_text(_strip_block(text), encoding="utf-8", errors="surrogateescape")
            removed.append(f"{hook} block removed")
    tail = ""
    if meta.get("hooks_path_set") and configured is not None and meta.get("hooks_path") == configured:
        _git(root, "config", "--local", "--unset", "core.hooksPath")
        tail = "; core.hooksPath unset"
    if (d / META).exists():
        (d / META).unlink()
    try:
        d.rmdir()                                    # only when nothing else is in it
    except OSError:
        pass
    return 0, f"{name}: {', '.join(removed) or 'nothing of ours found'}{tail}"


def _target_repos(args) -> list[Path]:
    if args.all:
        from . import lang
        return lang.resolve_repos([])
    from . import config
    given = Path(args.repo or ".").expanduser()
    if not given.exists() and args.repo and "/" not in args.repo:
        given = config.code_root() / args.repo
    root = _root(given)
    if root is None:
        raise ValueError(f"{given} is not inside a git repository")
    return [root]


def cmd_install(args) -> int:
    try:
        repos = _target_repos(args)
    except ValueError as e:
        print(f"teyla leak install: {e}", file=sys.stderr)
        return 2
    code = 0
    for r in repos:
        c, line = (uninstall if args.uninstall else install)(r)
        print(line)
        code = max(code, c)
    if code == 0 and not args.uninstall:
        print("Not committed: review and commit the hooks directory in each repo.")
    return code


# --- private terms -----------------------------------------------------------------------------

def terms_path() -> Path:
    env = os.environ.get("TEYLA_PRIVATE_TERMS")
    return Path(env).expanduser() if env else Path.home() / ".config" / "teyla" / "private-terms.txt"


def _existing_terms(path: Path) -> set[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    out = set()
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not re.match(r"(?i)allow\s+.+?\s+in\s+\S+$", line):
            out.add(line.lower())
    return out


def _run(*cmd: str) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def git_facts(root: Path | None) -> list[tuple[str, str]]:
    out = []
    for scope, args in (("global", ("--global",)), ("repo", ("--local",))):
        if scope == "repo" and root is None:
            continue
        for key in ("user.name", "user.email"):
            cmd = ["git", *(["-C", str(root)] if scope == "repo" else []), "config", *args, "--get", key]
            out.append((_run(*cmd), f"git {key}"))
    return out


def machine_facts() -> list[tuple[str, str]]:
    out = []
    try:
        out.append((os.environ.get("USER") or getpass.getuser(), "login name"))
    except Exception:                                # noqa: BLE001 — no login name is not an error
        pass
    out.append((Path.home().name, "home directory"))
    if sys.platform == "darwin" and shutil.which("scutil"):
        out.append((_run("scutil", "--get", "ComputerName"), "computer name"))
        out.append((_run("scutil", "--get", "LocalHostName"), "local host name"))
    else:
        out.append((stdlib_platform.node(), "hostname"))
    return out


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def manifest_facts(root: Path | None) -> list[tuple[str, str]]:
    """Tester e-mails in `[productize]` and bundle-id organisations in `[release]` of this repo's teyla.toml."""
    if root is None or not (root / "teyla.toml").is_file():
        return []
    try:
        data = tomllib.loads((root / "teyla.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for section in ("productize", "release"):
        for s in _walk_strings(data.get(section, {})):
            out += [(m, "teyla.toml tester e-mail") for m in EMAIL.findall(s)]
    rel = data.get("release", {}) if isinstance(data.get("release"), dict) else {}
    for key in ("apple_bundle_id", "android_package"):
        parts = str(rel.get(key, "")).split(".")
        if len(parts) >= 3:
            out.append((parts[1], "bundle id organisation"))
    return out


def platform_facts() -> list[tuple[str, str]]:
    home = Path(os.environ.get("TEYLA_HOME") or (Path.home() / ".teyla")).expanduser()
    try:
        data = tomllib.loads((home / "platform.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    picks = (("server", "host", "platform.toml server host"), ("domain", "name", "platform.toml domain"),
             ("mail", "from", "platform.toml mail sender"), ("apple", "tester", "platform.toml tester e-mail"),
             ("owner", "name", "platform.toml owner name"), ("owner", "org", "platform.toml owner organisation"))
    out = []
    for sec, key, src in picks:
        v = (data.get(sec) or {}).get(key) if isinstance(data.get(sec), dict) else None
        if isinstance(v, str):
            out.append((v, src))
    return out


def collect_facts(root: Path | None) -> list[tuple[str, str]]:
    return git_facts(root) + machine_facts() + manifest_facts(root) + platform_facts()


def candidates(root: Path | None, existing: set[str]) -> list[tuple[str, str]]:
    seen, out = set(existing), []
    for value, source in collect_facts(root):
        v = (value or "").strip()
        if len(v) < MIN_TERM or v.lower() in seen or v.lower() in GENERIC or "\n" in v:
            continue
        seen.add(v.lower())
        out.append((v, source))
    return out


def _append_terms(path: Path, values: list[str]) -> None:
    default = Path.home() / ".config" / "teyla"
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        path.parent.chmod(0o700)
    elif path.parent == default and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        path.parent.chmod(0o700)
    existed = path.exists()
    lead = ""
    if existed and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        lead = "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(lead + f"# added by teyla leak terms --suggest on {date.today().isoformat()}\n")
        fh.write("".join(v + "\n" for v in values))
    if stat.S_IMODE(path.stat().st_mode) & 0o177:
        path.chmod(0o600)


def cmd_terms(args) -> int:
    if not args.suggest:
        print("teyla leak terms: nothing to do; use --suggest", file=sys.stderr)
        return 2
    root = _root(Path.cwd())
    path = terms_path()
    cands = candidates(root, _existing_terms(path))
    added = 0
    if args.yes and cands:
        try:
            _append_terms(path, [v for v, _ in cands])
        except OSError as e:
            print(f"teyla leak terms: cannot write the terms file ({type(e).__name__})", file=sys.stderr)
            return 2
        added = len(cands)
    rows = [{"masked": leak.mask(v), "source": s} for v, s in cands]
    if args.json:
        print(json.dumps({"candidates": rows, "added": added}, indent=2, ensure_ascii=False))
    elif args.yes:
        print(f"added {added} term{'s' if added != 1 else ''}")
    elif not rows:
        print("no new candidates")
    else:
        print(f"{len(rows)} candidate{'s' if len(rows) != 1 else ''} (masked; nothing written):")
        for r in rows:
            print(f"  {r['masked']:<14} {r['source']}")
        print("Add them all: teyla leak terms --suggest --yes")
    return 0


# --- wiring ------------------------------------------------------------------------------------

def alias(argv: list[str]) -> list[str]:
    """`teyla leak install ...` -> `teyla leak-install ...`; a repo directory named install: pass `./install`."""
    if len(argv) >= 2 and argv[0] == "leak" and argv[1] in ("install", "terms"):
        return [f"leak-{argv[1]}", *argv[2:]]
    return argv


def register(sp):
    q = sp.add_parser("leak-install", help="install the leak gate (pre-commit and pre-push hooks) in a repo; also `teyla leak install`")
    q.set_defaults(fn=cmd_install)
    q.add_argument("repo", nargs="?", help="a path inside the repo, or a name under code_root (default: the current directory)")
    q.add_argument("--all", action="store_true", help="every repo under code_root; one line each, nothing committed")
    q.add_argument("--uninstall", action="store_true", help="remove only our hooks or our delimited block")
    t = sp.add_parser("leak-terms", help="suggest private terms from facts this machine knows, masked; also `teyla leak terms`")
    t.set_defaults(fn=cmd_terms)
    t.add_argument("--suggest", action="store_true", help="list candidates, masked")
    t.add_argument("--yes", action="store_true", help="append the full values to the terms file (0600) and print the count")
    t.add_argument("--json", action="store_true", help="masked candidates and the count added")
    return q
