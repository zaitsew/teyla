"""`teyla leak install` and `teyla leak terms --suggest` — the leak gate in every repo (Shield, SH5).

    teyla leak install [repo] [--all] [--uninstall]
    teyla leak terms --suggest [--yes] [--json]
    teyla leak terms list [--json]
    teyla leak terms move <index>... --to teyla|everywhere [--json]

`install` writes `.githooks/pre-commit` (the index) and `.githooks/pre-push` (the commits the remote lacks),
POSIX `sh`, and points `core.hooksPath` at them. A hook that is already there and is not ours keeps its
content: our call goes in as a delimited block at the top, and `--uninstall` takes the block out again.
A missing `teyla` on PATH is exit 2 (a coverage gap is not a pass); `TEYLA_LEAK=0` skips one command and the
skip is logged to `~/.teyla/leak-skips.log`.

`terms --suggest` lists private-term candidates from facts the machine already knows (git identity, the
login and home names, the computer name, tester e-mails and bundle-id organisations in this repo's
`teyla.toml`, hosts in `platform.toml`). It never reads another repo's content, prints every candidate
masked, and appends the full values to the terms file only with `--yes`. Product and organisation names go
under `[teyla]`, everything else under `[everywhere]`.

`terms list` and `terms move` let the owner sort an existing terms file into its two sections without a term
ever reaching stdout: both print an index, a section and a masked form.

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
      _tlg_obj=$_tlg_lsha; _tlg_depth=0
      while :; do
        _tlg_type=$(git cat-file -t "$_tlg_obj" 2>/dev/null)
        if [ -z "$_tlg_type" ]; then
          echo "teyla leak gate: cannot read the tag chain of $_tlg_l; refusing the push" >&2
          [ "$_tlg_rc" -lt 2 ] && _tlg_rc=2
          break
        fi
        [ "$_tlg_type" = "tag" ] || break
        _tlg_depth=$(( _tlg_depth + 1 ))
        if [ "$_tlg_depth" -gt 20 ] || ! git cat-file -p "$_tlg_obj" > "$_tlg_in.tag" 2>/dev/null; then
          echo "teyla leak gate: cannot read the tag chain of $_tlg_l; refusing the push" >&2
          [ "$_tlg_rc" -lt 2 ] && _tlg_rc=2
          break
        fi
        teyla leak --text "$_tlg_in.tag" --quiet </dev/null >/dev/null 2>&1
        _tlg_one=$?
        if [ "$_tlg_one" -ne 0 ]; then
          teyla leak --text "$_tlg_in.tag" </dev/null >&2
          echo "teyla leak gate: pre-push refused the annotated tag $_tlg_l (exit $_tlg_one); fix the findings, or set TEYLA_LEAK=0 for this command" >&2
          [ "$_tlg_one" -gt "$_tlg_rc" ] && _tlg_rc=$_tlg_one
        fi
        _tlg_obj=$(sed -n '1s/^object //p' "$_tlg_in.tag")
        rm -f "$_tlg_in.tag"
        if [ -z "$_tlg_obj" ]; then
          echo "teyla leak gate: cannot read the tag chain of $_tlg_l; refusing the push" >&2
          [ "$_tlg_rc" -lt 2 ] && _tlg_rc=2
          break
        fi
      done ;;
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


# --- the repo's visibility ---------------------------------------------------------------------

def _gh_visibility(slug: str) -> tuple[str | None, str]:
    """(`public` | `private` | None, why not): what `gh repo view` says about OWNER/NAME. Anything else gh prints
    (`internal`, an error) is None, so nothing but those two words is ever stored."""
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    try:
        p = subprocess.run(["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"],
                           capture_output=True, text=True, timeout=30, env=env)
    except FileNotFoundError:
        return None, "gh is not installed"
    except (OSError, subprocess.SubprocessError):
        return None, "gh did not answer"
    if p.returncode != 0:
        return None, "gh could not read the repo (not signed in, or no access)"
    value = p.stdout.strip().lower()
    if value in leak.VISIBILITY_VALUES:
        return value, ""
    return None, f"gh reports {value or 'nothing'!r}, which is neither public nor private"


def record_visibility(root: Path) -> str:
    """Store `private` or `public` in the local git config `teyla.visibility` from the repo's origin (or upstream),
    and return one line to print. Without a GitHub remote, gh, a signed-in gh or the network gate, nothing is
    stored: the scanner treats an unset repo as public (a private repo then lists its terms and e-mails as
    blockers, which is the safe way to be wrong)."""
    from . import net, shield
    current = leak.repo_visibility(root)
    hand = f"git config {leak.VISIBILITY_KEY} private"
    slug = shield.github_slug(root)
    if slug is None:
        why = "no GitHub remote"
    elif not net.gate("the repo visibility lookup (gh repo view)", quiet=True):
        why = "safe mode is on"
    else:
        value, why = _gh_visibility(slug)
        if value:
            r = _git(root, "config", leak.VISIBILITY_KEY, value)
            if r.returncode == 0:
                tail = "terms and e-mails are triage" if value == "private" else "terms and e-mails block"
                return f"  visibility: {value} ({leak.VISIBILITY_KEY}); {tail}"
            why = f"cannot write the git config: {r.stderr.strip()}"
    if current:
        return f"  visibility: {current} kept ({why})"
    return f"  visibility: not recorded ({why}); treated as public. For a private repo: {hand}"


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
        if c == 0 and not args.uninstall:
            print(record_visibility(r))
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
    return {t for t, _ in _engine().distinct_terms(raw)}


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


# Facts that name a product or an organisation belong in Teyla's `[teyla]` section: they are in every product's
# own repo and must stay out of Teyla's. Every other fact is the owner's own data and goes everywhere.
TEYLA_SOURCES = {"bundle id organisation"}


def section_of(source: str) -> str:
    return "teyla" if source in TEYLA_SOURCES else "everywhere"


def candidates(root: Path | None, existing: set[str]) -> list[tuple[str, str]]:
    seen, out = set(existing), []
    for value, source in collect_facts(root):
        v = (value or "").strip()
        if len(v) < MIN_TERM or v.lower() in seen or v.lower() in GENERIC or "\n" in v:
            continue
        seen.add(v.lower())
        out.append((v, source))
    return out


def _engine():
    return leak._engine()


def _prepare_dir(path: Path) -> None:
    default = Path.home() / ".config" / "teyla"
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        path.parent.chmod(0o700)
    elif path.parent == default and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        path.parent.chmod(0o700)


def _append_terms(path: Path, values: list[tuple[str, str]]) -> None:
    """Append `(value, section)` pairs under a private mode that is set before the first byte is written. The
    section in force at the end of the file takes its values first, so a file with no headers stays one
    block; the other section follows under its own header. Any failure raises OSError with nothing written."""
    _prepare_dir(path)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)                         # on an existing loose file too, before any write
        size = os.fstat(fd).st_size
        if size > _engine().CONFIG_CAP:
            raise OSError("the terms file is over the size cap")
        body = os.pread(fd, size, 0).decode("utf-8", "replace") if size else ""
        lead = "\n" if size and not body.endswith("\n") else ""
        at_end = "everywhere"
        for _no, _kind, section, _p in _engine().terms_lines(body):
            at_end = section
        stamp = f"# added by teyla leak terms --suggest on {date.today().isoformat()}\n"
        out, first = lead, True
        for section in (at_end, *(x for x in _engine().TERM_SECTIONS if x != at_end)):
            vals = [v for v, sec in values if sec == section]
            if not vals:
                continue
            if section != at_end:
                out += ("\n" if not first or size else "") + f"[{section}]\n"
            out += stamp + "".join(v + "\n" for v in vals)
            first = False
        os.write(fd, out.encode("utf-8"))
    finally:
        os.close(fd)


def _write_private_atomic(path: Path, text: str) -> None:
    """Replace the terms file with `text`: a 0600 temporary file in the same directory, then `os.replace`. A
    symlink is refused, like the append does."""
    if path.is_symlink():
        raise OSError("the terms file is a symlink")
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        data = text.encode("utf-8")
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    os.close(fd)
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _place(raw: str, section: str, values: list[str]) -> str:
    """`raw` with `values` added as term lines at the end of `section`: after the last non-blank line the section
    owns. A section with no lines is created at the end of the file; `everywhere` with none goes first, ahead
    of any header, where headerless lines already mean everywhere."""
    lines = raw.splitlines()
    last = 0
    for no, kind, sec, _p in _engine().terms_lines(raw):
        if sec == section and kind != "blank":
            last = no
    if last or section == "everywhere":
        lines[last:last] = values                    # last == 0 for everywhere: ahead of any header
    else:
        lines += ([""] if lines and lines[-1].strip() else []) + [f"[{section}]"] + (
            ["# never in Teyla's repo: product and organisation names"] if section == "teyla" else []) + values
    return "\n".join(lines) + "\n"


def _read_terms_file(path: Path) -> str:
    return _engine().read_capped(path)


def mask_term(term: str) -> str:
    """A term as two characters, `…` and its length; under 4 characters it shows none (`*…2`), because the first
    two characters of a short term are the term."""
    return f"*{leak.ELLIPSIS}{len(term)}" if len(term) < 4 else leak.mask(term)


def _term_rows(raw: str) -> list[dict]:
    rows = []
    for i, (term, section) in enumerate(_engine().distinct_terms(raw)):
        rows.append({"index": i, "section": section, "masked": mask_term(term)})
    return rows


def _parse_indices(words: list[str]) -> list[int]:
    out: list[int] = []
    for w in words:
        w = w[5:] if w.startswith("term:") else w
        if not w.isdigit():
            raise ValueError(f"not an index: {mask_term(w)}")
        if int(w) not in out:
            out.append(int(w))
    return out


def move_terms(raw: str, indices: list[int], to: str) -> tuple[str, list[dict]]:
    """Move the terms at `indices` to section `to`. Returns the new file text and one `{from, to, section}` row
    per moved term. Comments and `allow` lines stay where they are. A term already in `to` stays put. Each moved
    term is written once, at the end of `to`, in index order; the indices of the others keep their order but
    shift to close the gap, so the new index of a moved term is reported."""
    eng = _engine()
    distinct = eng.distinct_terms(raw)
    for i in indices:
        if not 0 <= i < len(distinct):
            raise ValueError(f"no term with index {i}")
    pick = [i for i in indices if distinct[i][1] != to]
    names = {distinct[i][0] for i in pick}
    first_text: dict[str, str] = {}
    keep: list[str] = []
    for line in raw.splitlines():
        k = next(iter(eng.terms_lines(line)), None)
        if k and k[1] == "term" and k[3].lower() in names:
            first_text.setdefault(k[3].lower(), k[3])
            continue
        keep.append(line)
    # a header changes the section of the lines after it, so the kept text is re-read as a whole
    text = "\n".join(keep) + ("\n" if keep else "")
    values = [first_text[distinct[i][0]] for i in sorted(pick)]
    if values:
        text = _place(text, to, values)
    new = [t for t, _ in eng.distinct_terms(text)]
    rows = [{"from": i, "to": new.index(distinct[i][0]), "section": to} for i in sorted(pick)]
    return text, rows


def _cmd_list(args, path: Path) -> int:
    try:
        raw = _read_terms_file(path)
    except FileNotFoundError:
        raw = ""
    except (OSError, ValueError) as e:
        print(f"teyla leak terms: cannot read the terms file ({type(e).__name__})", file=sys.stderr)
        return 2
    rows = _term_rows(raw)
    if args.json:
        print(json.dumps({"terms": rows}, indent=2, ensure_ascii=False))
    elif not rows:
        print("no terms")
    else:
        for r in rows:
            print(f"term:{r['index']}  {r['section']:<10}  {r['masked']}")
    return 0


def _cmd_move(args, path: Path, words: list[str]) -> int:
    if args.to not in _engine().TERM_SECTIONS:
        print("teyla leak terms move: --to teyla|everywhere is required", file=sys.stderr)
        return 2
    try:
        indices = _parse_indices(words)
        if not indices:
            raise ValueError("no index given")
        raw = _read_terms_file(path)
        text, rows = move_terms(raw, indices, args.to)
        if rows:
            _write_private_atomic(path, text)
    except FileNotFoundError:
        print("teyla leak terms move: no terms file", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"teyla leak terms move: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"teyla leak terms move: cannot write the terms file ({type(e).__name__})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"moved": rows, "to": args.to}, indent=2))
    else:
        for r in rows:
            print(f"term:{r['from']} -> term:{r['to']}  {r['section']}")
        print(f"moved {len(rows)} term{'s' if len(rows) != 1 else ''} to [{args.to}]")
    return 0


def cmd_terms(args) -> int:
    words = list(args.words or [])
    path = terms_path()
    if words and words[0] in ("list", "move"):
        if args.suggest or args.yes:
            print("teyla leak terms: --suggest and --yes do not combine with list or move", file=sys.stderr)
            return 2
        return _cmd_list(args, path) if words[0] == "list" else _cmd_move(args, path, words[1:])
    if words or not args.suggest:
        print("teyla leak terms: nothing to do; use --suggest, list or move", file=sys.stderr)
        return 2
    root = _root(Path.cwd())
    cands = candidates(root, _existing_terms(path))
    added = 0
    if args.yes and cands:
        try:
            _append_terms(path, [(v, section_of(s)) for v, s in cands])
        except OSError as e:
            print(f"teyla leak terms: cannot write the terms file ({type(e).__name__})", file=sys.stderr)
            return 2
        added = len(cands)
    rows = [{"masked": mask_term(v), "source": s, "section": section_of(s)} for v, s in cands]
    if args.json:
        print(json.dumps({"candidates": rows, "added": added}, indent=2, ensure_ascii=False))
    elif args.yes:
        print(f"added {added} term{'s' if added != 1 else ''}")
    elif not rows:
        print("no new candidates")
    else:
        print(f"{len(rows)} candidate{'s' if len(rows) != 1 else ''} (masked; nothing written):")
        for r in rows:
            print(f"  {r['masked']:<14} {r['section']:<10} {r['source']}")
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
    t.add_argument("words", nargs="*", metavar="list | move INDEX...", help="`list` prints index, section and masked form; `move INDEX... --to SECTION` re-sections terms")
    t.add_argument("--to", choices=("teyla", "everywhere"), help="move: the section the terms go to")
    t.add_argument("--suggest", action="store_true", help="list candidates, masked")
    t.add_argument("--yes", action="store_true", help="append the full values to the terms file (0600) and print the count")
    t.add_argument("--json", action="store_true", help="masked candidates and the count added; list and move: the same rows as JSON")
    return q
