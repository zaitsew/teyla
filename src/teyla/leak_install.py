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

SH_FAMILY = {"sh", "bash", "zsh", "dash"}
CHAIN_MARK = "# teyla leak gate: then runs"

_PUSH_SCAN = """  while read -r _tlg_l _tlg_lsha _tlg_r _tlg_rsha; do
    case "$_tlg_lsha" in *[!0]*) ;; *) continue ;; esac
    _tlg_range="$_tlg_lsha --not --remotes=$_tlg_remote"
    case "$_tlg_rsha" in *[!0]*) git cat-file -e "$_tlg_rsha^{commit}" 2>/dev/null && _tlg_range="$_tlg_lsha --not $_tlg_rsha" ;; esac
    teyla leak --commits "$_tlg_range" --quiet </dev/null >/dev/null 2>&1
    _tlg_one=$?
    if [ "$_tlg_one" -ne 0 ]; then
      teyla leak --commits "$_tlg_range" </dev/null >&2
      echo "teyla leak gate: pre-push refused (exit $_tlg_one); fix the findings, or set TEYLA_LEAK=0 for this command" >&2
      [ "$_tlg_one" -gt "$_tlg_rc" ] && _tlg_rc=$_tlg_one
    fi
    case "$_tlg_l" in refs/tags/*)
      if [ "$(git cat-file -t "$_tlg_lsha" 2>/dev/null)" = "tag" ]; then
        if ! git cat-file -p "$_tlg_lsha" > "$_tlg_in.tag" 2>/dev/null; then
          echo "teyla leak gate: cannot read the tag object $_tlg_l; refusing the push" >&2
          [ "$_tlg_rc" -lt 2 ] && _tlg_rc=2
        else
          teyla leak --text "$_tlg_in.tag" --quiet </dev/null >/dev/null 2>&1
          _tlg_one=$?
          if [ "$_tlg_one" -ne 0 ]; then
            teyla leak --text "$_tlg_in.tag" </dev/null >&2
            echo "teyla leak gate: pre-push refused the annotated tag $_tlg_l (exit $_tlg_one); fix the findings, or set TEYLA_LEAK=0 for this command" >&2
            [ "$_tlg_one" -gt "$_tlg_rc" ] && _tlg_rc=$_tlg_one
          fi
        fi
        rm -f "$_tlg_in.tag"
      fi ;;
    esac
  done < "$_tlg_in"
"""
_COMMIT_SCAN = """  teyla leak --staged --quiet </dev/null >/dev/null 2>&1
  _tlg_rc=$?
  if [ "$_tlg_rc" -ne 0 ]; then
    teyla leak --staged </dev/null >&2
    echo "teyla leak gate: pre-commit refused (exit $_tlg_rc); fix the findings, or set TEYLA_LEAK=0 for this command" >&2
  fi
"""
_TAKE = """_tlg_in=$(mktemp "${TMPDIR:-/tmp}/teyla-leak-gate.XXXXXX") || { echo "teyla leak gate: cannot create a temp file" >&2; exit 2; }
_tlg_want=$(cat | tee "$_tlg_in" | wc -c)
_tlg_got=$(wc -c < "$_tlg_in")
if [ -z "$_tlg_want" ] || [ "$(( _tlg_want + 0 ))" -ne "$(( _tlg_got + 0 ))" ]; then
  rm -f "$_tlg_in"
  echo "teyla leak gate: could not read the pushed refs; not scanning a partial list" >&2
  exit 2
fi
"""


def block(hook: str) -> str:
    """The delimited sh snippet. TEYLA_LEAK=0 skips the scan, but the skip must be on record: when the log cannot
    be written the hook refuses. Otherwise it scans, then runs a hook left in `.git/hooks`, and exits non-zero on a
    finding or a gap. A pre-push block reads git's ref lines from stdin, scans `<remote sha>..<local sha>` for
    each (a new branch: what no remote-tracking ref has), and hands stdin back unread to the hook that follows."""
    push = hook == "pre-push"
    head = '_tlg_remote="${1:-origin}"\n' + _TAKE if push else ""
    scan = _PUSH_SCAN if push else _COMMIT_SCAN
    legacy_in = ' < "$_tlg_in"' if push else ""
    cleanup = 'rm -f "$_tlg_in"; ' if push else ""
    tail = 'exec < "$_tlg_in"\nrm -f "$_tlg_in"\n' if push else ""
    return f"""{BEGIN} ({hook}) -- written by `teyla leak install`; `teyla leak install --uninstall` removes it
{head}_tlg_rc=0
if [ "${{TEYLA_LEAK:-1}}" = "0" ]; then
  _tlg_home="${{TEYLA_HOME:-$HOME/.teyla}}"
  {{ mkdir -p "$_tlg_home" && printf '%s\\t%s\\t%s\\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")" "{hook}" >> "$_tlg_home/leak-skips.log"; }} || {{
    echo "teyla leak gate: cannot record the skip in $_tlg_home/leak-skips.log; a skip that is not on record is not a skip" >&2
    _tlg_rc=1
  }}
elif ! command -v teyla >/dev/null 2>&1; then
  echo "teyla leak gate: teyla not found; install it or set TEYLA_LEAK=0 for this command" >&2
  _tlg_rc=2
else
{scan}fi
_tlg_legacy="$(git rev-parse --git-common-dir 2>/dev/null)/hooks/{hook}"
if [ "$_tlg_rc" -eq 0 ] && [ -z "${{TEYLA_LEAK_CHAIN:-}}" ] && [ -f "$_tlg_legacy" ] && [ -x "$_tlg_legacy" ] && ! [ "$_tlg_legacy" -ef "$0" ]; then
  TEYLA_LEAK_CHAIN=1 "$_tlg_legacy" "$@"{legacy_in} || _tlg_rc=$?
fi
if [ "$_tlg_rc" -ne 0 ]; then
  {cleanup}exit "$_tlg_rc"
fi
{tail}unset _tlg_home _tlg_rc _tlg_remote _tlg_in _tlg_want _tlg_got _tlg_l _tlg_lsha _tlg_r _tlg_rsha _tlg_range _tlg_one _tlg_legacy
{END}
"""


def standalone(hook: str, chained: bool = False) -> str:
    """Our whole hook file. `chained`: the previous hook (not sh) was renamed `<hook>.chain` and runs after the gate."""
    text = f"#!/bin/sh\n{MARK} ({hook}): written by `teyla leak install`; rerun it instead of editing\n{block(hook)}"
    if chained:
        text += f'{CHAIN_MARK} {hook}.chain\nexec "$(dirname "$0")/{hook}.chain" "$@"\n'
    return text


def _sh_family(text: str) -> bool:
    """True when sh can safely go at the top: no shebang, or sh, bash, zsh or dash (also via env)."""
    if not text.startswith("#!"):
        return True
    toks = text.split("\n", 1)[0][2:].split()
    prog = os.path.basename(toks[0]) if toks else ""
    if prog == "env":
        rest = [t for t in toks[1:] if not t.startswith("-") and "=" not in t]
        prog = os.path.basename(rest[0]) if rest else ""
    return prog in SH_FAMILY


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


def _hooks_path(root: Path) -> tuple[str | None, str | None]:
    """(value, scope) of the effective `core.hooksPath` as seen from inside this worktree: a worktree-level value
    (`extensions.worktreeConfig`) wins over the repo's. A global or system value that does not lead into the repo
    is not the repo's own setting: it counts as unset (the repo then sets its own)."""
    p = _git(root, "config", "--show-scope", "--get", "core.hooksPath")
    if p.returncode != 0 or not p.stdout.strip():
        return None, None
    scope, _, value = p.stdout.strip().splitlines()[-1].partition("\t")
    if scope in ("global", "system") and _hooks_dir(root, value) is None:
        return None, None
    return value or None, scope


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
    configured, scope = _hooks_path(root)
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
        chain_file = d / f"{hook}.chain"
        if f.is_symlink():
            return 2, f"{name}: {rel}/{hook} is a symlink; not touched"
        before = f.read_text(encoding="utf-8", errors="surrogateescape") if f.exists() else None
        if before is None:
            _write_exec(f, standalone(hook))
            done[hook], state = "file", "new"
        elif _is_ours(before):
            chained = CHAIN_MARK in before
            done[hook] = "chain-file" if chained else "file"
            want = standalone(hook, chained)
            state = "unchanged" if before == want else "updated"
            if state == "updated":
                f.write_text(want, encoding="utf-8")
            f.chmod(0o755)                           # a generated hook always regains +x
        elif not _sh_family(before):
            if chain_file.exists() or chain_file.is_symlink():
                return 2, f"{name}: {rel}/{hook} is not sh and {hook}.chain already exists; not touched"
            mode = stat.S_IMODE(f.stat().st_mode)
            os.replace(f, chain_file)
            _write_exec(f, standalone(hook, True))
            chain_file.chmod(mode)
            done[hook], state = "chain-file", f"chained (old hook now {hook}.chain)"
        else:
            new = chain(before, hook)
            done[hook] = "block"
            state = "unchanged" if new == before else "chained"
            if new != before:
                f.write_text(new, encoding="utf-8", errors="surrogateescape")
            if not os.access(f, os.X_OK):
                notes.append(f"{hook} made executable (git skips a hook that is not)")
            f.chmod(0o755)
        notes.append(f"{hook} {state}")
    path_state = f"core.hooksPath unchanged ({scope} scope)"
    if configured is None:
        r = _git(root, "config", "core.hooksPath", DEFAULT_DIR)          # the default scope: the repo's own config
        if r.returncode != 0:
            return 2, f"{name}: cannot set core.hooksPath: {r.stderr.strip()}"
        set_by_us, scope, path_state = True, "local", f"core.hooksPath set to {DEFAULT_DIR} (local scope)"
        if _git(root, "config", "--global", "--get", "core.hooksPath").returncode == 0:
            notes.append("this repo's hooks now override your global core.hooksPath")
    elif configured != DEFAULT_DIR and not set_by_us:
        path_state = f"core.hooksPath already {configured} ({scope} scope); installed there"
    new_meta = {"hooks": done, "hooks_path": configured or DEFAULT_DIR, "hooks_path_set": set_by_us,
                "hooks_path_scope": scope if set_by_us else None, "version": 1}
    text = json.dumps(new_meta, indent=2, sort_keys=True) + "\n"
    mp = d / META
    if not mp.exists() or mp.read_text(encoding="utf-8") != text:
        mp.write_text(text, encoding="utf-8")
    return 0, f"{name}: {', '.join(notes)} in {rel}; {path_state}"


def uninstall(root: Path) -> tuple[int, str]:
    name = root.name
    configured, _scope = _hooks_path(root)
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
        chain_file = d / f"{hook}.chain"
        if _is_ours(text) and CHAIN_MARK in text and chain_file.is_file():
            os.replace(chain_file, f)
            removed.append(f"{hook} restored from {hook}.chain")
        elif _is_ours(text):
            f.unlink()
            removed.append(f"{hook} removed")
        elif _has_block(text):
            f.write_text(_strip_block(text), encoding="utf-8", errors="surrogateescape")
            removed.append(f"{hook} block removed")
    tail = ""
    if meta.get("hooks_path_set") and configured is not None and meta.get("hooks_path") == configured:
        sc = meta.get("hooks_path_scope") if meta.get("hooks_path_scope") in ("local", "worktree") else "local"
        _git(root, "config", f"--{sc}", "--unset", "core.hooksPath")
        tail = f"; core.hooksPath unset ({sc} scope)"
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
    """Append under a private mode that is set before the first byte is written. Any failure raises OSError with
    nothing written."""
    default = Path.home() / ".config" / "teyla"
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        path.parent.chmod(0o700)
    elif path.parent == default and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        path.parent.chmod(0o700)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)                         # on an existing loose file too, before any write
        size = os.fstat(fd).st_size
        lead = "\n" if size and os.pread(fd, 1, size - 1) != b"\n" else ""
        stamp = f"# added by teyla leak terms --suggest on {date.today().isoformat()}\n"
        os.write(fd, (lead + stamp + "".join(v + "\n" for v in values)).encode("utf-8"))
    finally:
        os.close(fd)


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
