"""`teyla product` — the product registry: which directories, aliases and stage belong to which product.

    teyla product [list] [--json]                    one line per registered product
    teyla product init [--write]                     propose a registry from the git repos under code_root; --write adds the missing ones
    teyla product add <id> [--repo PATH] [--name N] [--stage S]   register one product
    teyla product set <id> key=value...              name, stage, primary, focus, aliases (comma list), add-repo, add-path
    teyla product park <id> | wake <id>              stage parked (the old stage is remembered) / back to it
    teyla product assign <ask-id-prefix|session-id> <id> [--ask-only]   file a session's asks under another product

The product of a session used to be guessed from its working directory. A session that ran outside
any repo landed under "(no repo)", one that ran in the wrong repo under the wrong product, and a
scratch folder became a product named after the folder. This module replaces the guess with a file,
`~/.teyla/products.toml`, and one rule that never invents a name:

1. `[assign]`: the owner filed this ask, else this session, by hand. Wins over everything.
2. Title: the session title names exactly one registered product. Two or more make no match.
3. The repo of a pull request link the session produced, when a registered product owns that repo.
4. The longest `repos` / `paths` entry that contains the directory. A worktree
   (`<repo>/.claude/worktrees/<x>`, `~/.worktrees/<repo>/<branch>`) maps to its repo.
5. Question text names exactly one registered product, only when rule 4 found none.
6. A git checkout under `code_root` that nobody registered: its repo directory name.
7. Otherwise the literal `unassigned`.

`attribute()` returns the product and which rule decided; `resolve()` returns the product only.
`docs/PRODUCTS.md` has the file format.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

from . import config, corrections

UNASSIGNED = "unassigned"
STAGES = ("idea", "building", "beta", "live", "parked")
PARK_AFTER_DAYS = 30                    # init: no commit for this long proposes "parked"
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*$")
_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+$")
# Worktrees: <repo>/.claude/worktrees/<x> and <home>/.worktrees/<repo>/<branch>.
_CLAUDE_WT_RE = re.compile(r"^(?P<root>.+?)/\.claude/worktrees(?:/|$)")
_HOME_WT_RE = re.compile(r"/\.worktrees/(?P<name>[^/]+)(?:/|$)")
# Written in this order; any other key a product carries (stage_before_park) follows.
_FIELDS = ("name", "repos", "paths", "aliases", "stage", "primary", "focus", "stage_before_park")


class RegistryError(Exception):
    """The registry file exists but is not valid; nothing is written over it."""


# --- the file ---------------------------------------------------------------------------------

def path() -> pathlib.Path:
    return corrections.teyla_home() / "products.toml"


def _empty() -> dict:
    return {"product": {}, "assign": {}}


def _normalise(raw: dict) -> dict:
    """The tables the registry uses, with the list and boolean fields in their types. Keys the
    code does not know are kept: the owner may have added their own."""
    reg = _empty()
    prods = raw.get("product")
    for pid, p in (prods.items() if isinstance(prods, dict) else []):
        if not isinstance(p, dict):
            continue
        row = dict(p)
        for k in ("repos", "paths", "aliases"):
            v = row.get(k, [])
            row[k] = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        row["aliases"] = [a.lower() for a in row["aliases"]]
        row["focus"] = row.get("focus") is True
        for k in ("name", "stage", "primary"):
            row[k] = str(row.get(k) or "")
        reg["product"][str(pid)] = row
    asg = raw.get("assign")
    if isinstance(asg, dict):
        reg["assign"] = {str(k): str(v) for k, v in asg.items()}
    return reg


_cache: dict = {}
_warned: set = set()


def _warn_once(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        print(f"teyla: {msg}", file=sys.stderr)


def load(strict: bool = False) -> dict:
    """{"product": {id: {...}}, "assign": {key: id}}. A missing file is an empty registry. A file
    that does not parse is empty too, so `teyla asks` keeps working, unless `strict`: the commands
    that write use it, so a typo never costs the owner his hand edits."""
    import tomllib
    p = path()
    try:
        st = p.stat()
    except OSError:
        return _empty()
    stamp = (str(p), st.st_mtime_ns, st.st_size)
    hit = _cache.get("reg")
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        reg = _normalise(tomllib.loads(p.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        if strict:
            raise RegistryError(f"{p} does not parse ({e}); fix it by hand first") from e
        _warn_once(f"{p} does not parse ({e}); no product is registered until it is fixed")
        return _empty()
    _cache["reg"] = (stamp, reg)
    return reg


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r", "\b": "\\b", "\f": "\\f"}


def _str(v: str) -> str:
    """A TOML basic string. `config._toml_value` escapes only the backslash and the quote; a name
    with a line break would write a file that does not parse."""
    return '"' + "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if ord(c) < 0x20 or ord(c) == 0x7F else c)
                         for c in v) + '"'


def _val(v) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, (bool, int, float)):
        return config._toml_value(v)
    return _str(str(v))


def _key(k: str) -> str:
    return k if _BARE_KEY_RE.match(k) else _str(k)


def dump(reg: dict) -> str:
    """The registry as TOML, in `config.dump`'s style. Comments are not kept: `teyla product`
    rewrites the file."""
    lines = ["# Managed by `teyla product`. Hand edits are kept; comments are not.", ""]
    for pid, p in reg["product"].items():
        lines.append(f"[product.{_key(pid)}]")
        keys = [k for k in _FIELDS if k in p] + [k for k in p if k not in _FIELDS]
        for k in keys:
            lines.append(f"{_key(k)} = {_val(p[k])}")
        lines.append("")
    lines.append("[assign]")
    for k, v in reg["assign"].items():
        lines.append(f"{_key(k)} = {_val(v)}")
    return "\n".join(lines) + "\n"


def save(reg: dict) -> pathlib.Path:
    p = path()
    config.write_private(p, dump(reg))
    _cache.pop("reg", None)
    return p


# --- which product a directory belongs to -----------------------------------------------------

def worktree_repo(cwd) -> tuple[pathlib.Path | None, str]:
    """(repo checkout, repo name) when `cwd` is a worktree, else (None, ""). Pure path matching: a
    worktree deleted since still maps to its repo. `<repo>/.claude/worktrees/<x>` names the repo
    path itself; `~/.worktrees/<repo>/<branch>` only its directory name."""
    s = str(cwd or "").rstrip("/")
    m = _CLAUDE_WT_RE.match(s)
    if m:
        root = pathlib.PurePosixPath(m.group("root"))
        return pathlib.Path(root), root.name
    m = _HOME_WT_RE.search(s)
    if m:
        return None, m.group("name")
    return None, ""


def abs_path(p) -> pathlib.Path:
    q = pathlib.Path(str(p)).expanduser()
    try:
        return q.resolve()
    except (OSError, RuntimeError):
        return pathlib.Path(os.path.abspath(q))


def _within(child: pathlib.Path, base: pathlib.Path) -> bool:
    return child == base or base in child.parents


def _is_checkout(d: pathlib.Path) -> bool:
    return (d / ".git").exists()        # a directory in a main checkout, a file in a worktree


def _code_root(root) -> pathlib.Path | None:
    if root is not None:
        return abs_path(root)
    try:
        return abs_path(config.code_root())
    except Exception:  # noqa: BLE001 — no readable config is "no code root", not a failed attribution
        return None


def _entries(reg: dict) -> list[tuple[pathlib.Path, str]]:
    return [(abs_path(d), pid) for pid, p in reg["product"].items() for d in (*p["repos"], *p["paths"])]


HOW = ("assign", "title", "pr", "path", "text", "checkout", "unassigned")
_PR_RE = re.compile(r"github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s?#]+)/pull/\d+", re.I)


def _registered_path(here: pathlib.Path, cwd, reg: dict) -> tuple[str, str]:
    """(product, evidence) of the longest registered repo/path holding `here`, else ("", "")."""
    best, best_len, best_dir = "", -1, None
    for base, pid in _entries(reg):
        if _within(here, base) and len(base.parts) > best_len:
            best, best_len, best_dir = pid, len(base.parts), base
    if best:
        return best, _tilde(best_dir)
    wt_root, wt_name = worktree_repo(cwd)
    if wt_name:                      # a worktree whose checkout lives elsewhere: match it by name
        for pid, p in reg["product"].items():
            if any(abs_path(d).name == wt_name for d in p["repos"]):
                return pid, f"worktree of {wt_name}"
    return "", ""


def _pr_product(pr, reg: dict) -> tuple[str, str]:
    """(product, evidence) for the repo of a GitHub pull request URL, else ("", ""). A product whose
    `repos` entry has the repo's directory name wins; else one whose id or alias is the repo name.
    Two products at the same level make no match."""
    m = _PR_RE.search(str(pr or ""))
    if not m:
        return "", ""
    repo = m.group("repo").lower()
    if repo.endswith(".git"):
        repo = repo[:-4]
    by_dir = [pid for pid, p in reg["product"].items() if any(abs_path(d).name.lower() == repo for d in p["repos"])]
    by_name = [pid for pid, p in reg["product"].items() if pid.lower() == repo or repo in p["aliases"]]
    for hits in (by_dir, by_name):
        if len(hits) == 1:
            return hits[0], f"{m.group('owner')}/{m.group('repo')}"
        if hits:
            return "", ""
    return "", ""


def _only(text, reg: dict) -> str:
    """The one registered product `text` names, else "" (none, or two or more)."""
    hits = match_text(text, reg)
    return hits[0] if len(hits) == 1 else ""


def attribute(cwd, *, session=None, ask_id=None, pr="", texts=(), reg: dict | None = None, root=None,
              ) -> tuple[str, str]:
    """(product, how) for an ask. `how` is one of HOW. See the module docstring for the order.
    `texts` is (session title, question); `pr` the last pull request link of the session."""
    product, how, _ = explain(cwd, session=session, ask_id=ask_id, pr=pr, texts=texts, reg=reg, root=root)
    return product, how


def explain(cwd, *, session=None, ask_id=None, pr="", texts=(), reg: dict | None = None, root=None,
            ) -> tuple[str, str, str]:
    """`attribute` plus the evidence: (product, how, what decided it)."""
    reg = load() if reg is None else reg
    assign = reg["assign"]
    keys = [ask_id, *(session if isinstance(session, (list, tuple, set)) else [session])]   # the ask is the narrower correction
    for key in keys:
        if key and str(key) in assign:
            return assign[str(key)], "assign", f"[assign] {key}"
    title, question = (list(texts) + ["", ""])[:2]
    product = _only(title, reg)
    if product:
        return product, "title", f"title names {product}"
    product, ev = _pr_product(pr, reg)
    if product:
        return product, "pr", f"PR {ev}"
    here = abs_path(cwd) if cwd else None
    cwd_product, cwd_ev = _registered_path(here, cwd, reg) if here else ("", "")
    if cwd_product:
        return cwd_product, "path", cwd_ev
    product = _only(question, reg)
    if product:
        return product, "text", f"question names {product}"
    if here is None:
        return UNASSIGNED, "unassigned", "no working directory"
    wt_root, wt_name = worktree_repo(cwd)
    code = _code_root(root)
    if code is None:
        return UNASSIGNED, "unassigned", "no code root"
    if wt_name and not wt_root and _is_checkout(code / wt_name):
        return wt_name, "checkout", f"worktree of {wt_name}"
    if _within(here, code) and here != code:
        top = code / here.relative_to(code).parts[0]
        if _is_checkout(top):
            return top.name, "checkout", top.name
    return UNASSIGNED, "unassigned", "no rule matched"


def resolve(cwd, session=None, ask_id=None, reg: dict | None = None, root=None) -> str:
    """The product id for a session that ran in `cwd`, by the working directory alone (`attribute`
    without a PR link or text). `session` is one session id or several (a desktop session has two).
    The answer is a registered id, a repo directory name under `code_root`, or "unassigned"."""
    return attribute(cwd, session=session, ask_id=ask_id, reg=reg, root=root)[0]


def _term_pattern(term: str) -> str:
    """A whole-word pattern for `term`; a space, hyphen or underscore in it matches any run of those."""
    words = [w for w in re.split(r"[\s_-]+", term.strip()) if w]
    return r"(?<!\w)" + r"[\s_-]+".join(re.escape(w) for w in words) + r"(?!\w)"


def match_text(text, reg: dict | None = None) -> list[str]:
    """The products whose id, display name or alias appears in `text` as a whole word, ignoring case,
    in registry order. An id's hyphens match spaces ("tool-c" finds "Tool C")."""
    reg = load() if reg is None else reg
    t = str(text or "")
    out = []
    for pid, p in reg["product"].items():
        for term in {pid, p.get("name") or "", p.get("display_name") or "", *p["aliases"]}:
            if term.strip() and re.search(_term_pattern(term), t, re.IGNORECASE):
                out.append(pid)
                break
    return out


# --- editing ----------------------------------------------------------------------------------

def _tilde(p) -> str:
    s = str(p)
    home = str(pathlib.Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def _title(pid: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_.\s]+", pid) if w)


def new_product(pid: str, repos=(), paths=(), stage: str = "", name: str = "") -> dict:
    return {"name": name or _title(pid), "repos": [_tilde(r) for r in repos], "paths": [_tilde(r) for r in paths],
            "aliases": [], "stage": stage or ("building" if repos else "idea"), "primary": "", "focus": False}


def check_id(pid: str) -> str | None:
    if pid == UNASSIGNED:
        return f"{UNASSIGNED!r} is the bucket for sessions nobody filed; pick another id"
    if not _ID_RE.match(pid):
        return f"{pid!r} is not a product id: letters, digits, '.', '_' and '-' only"
    return None


def park(reg: dict, pid: str) -> str:
    p = reg["product"][pid]
    if p["stage"] == "parked":
        return f"{pid} is already parked"
    p["stage_before_park"] = p["stage"]
    p["stage"] = "parked"
    return f"parked {pid} (was {p['stage_before_park'] or 'unset'})"


def wake(reg: dict, pid: str) -> str:
    p = reg["product"][pid]
    if p["stage"] != "parked":
        return f"{pid} is not parked (stage {p['stage'] or 'unset'})"
    p["stage"] = p.pop("stage_before_park", "") or "building"
    return f"woke {pid}: stage {p['stage']}"


def set_field(reg: dict, pid: str, key: str, value: str) -> str:
    """One `key=value` of `teyla product set`. Returns the line to print; raises ValueError."""
    p = reg["product"][pid]
    key = key.strip().lower().replace("_", "-")
    value = value.strip()
    if key in ("name", "primary"):
        p[key] = value
    elif key == "stage":
        if value not in STAGES:
            raise ValueError(f"stage must be one of {', '.join(STAGES)}")
        if value == "parked":
            return park(reg, pid)
        p["stage"] = value
        p.pop("stage_before_park", None)
    elif key == "focus":
        if value.lower() not in ("true", "false", "yes", "no", "1", "0", "on", "off"):
            raise ValueError("focus must be true or false")
        p["focus"] = value.lower() in ("true", "yes", "1", "on")
    elif key == "aliases":
        p["aliases"] = [a.strip().lower() for a in value.split(",") if a.strip()]
    elif key in ("add-repo", "add-path"):
        slot = "repos" if key == "add-repo" else "paths"
        if not value:
            raise ValueError(f"{key} needs a directory")
        v = _tilde(abs_path(value))
        if v not in p[slot]:
            p[slot].append(v)
    else:
        raise ValueError(f"unknown key {key!r}: name, stage, primary, focus, aliases, add-repo, add-path")
    return f"{pid}: {key} = {value}"


# --- init -------------------------------------------------------------------------------------

def _last_commit(repo: pathlib.Path) -> float | None:
    """POSIX time of the newest commit, else of the last move of HEAD, else None."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ct"], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        return (repo / ".git" / "logs" / "HEAD").stat().st_mtime
    except OSError:
        return None


def propose(reg: dict, now: float | None = None, root=None) -> dict:
    """{id: product} for each git repo directly under code_root that no registered product holds
    yet. Stage: no commit for PARK_AFTER_DAYS days (or none at all) is parked, else building."""
    now = time.time() if now is None else now
    code = _code_root(root)
    if code is None or not code.is_dir():
        return {}
    held = {d for d, _ in _entries(reg)}
    out = {}
    for d in sorted(code.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or not _is_checkout(d):
            continue
        if d.name in reg["product"] or abs_path(d) in held:
            continue
        last = _last_commit(d)
        parked = last is None or now - last > PARK_AFTER_DAYS * 86400
        out[d.name] = new_product(d.name, repos=[d], stage="parked" if parked else "building")
    return out


# --- CLI --------------------------------------------------------------------------------------

def _row(pid: str, p: dict) -> str:
    return (f"{pid:<22} {p['stage'] or '-':<9} {'*' if p['focus'] else ' '} {p['primary'] or '-':<8} "
            + (", ".join(p["repos"]) or "-"))


def _load_for_edit() -> dict | None:
    try:
        return load(strict=True)
    except RegistryError as e:
        print(f"teyla: {e}", file=sys.stderr)
        return None


def _known(reg: dict, pid: str) -> bool:
    if pid in reg["product"]:
        return True
    print(f"no product {pid!r}; registered: {', '.join(reg['product']) or 'none'}. "
          f"`teyla product add {pid}` registers it.", file=sys.stderr)
    return False


def cmd_list(args) -> int:
    reg = _load_for_edit()
    if reg is None:
        return 1
    if args.json:
        rows = [{"id": pid, **p} for pid, p in reg["product"].items()]
        print(json.dumps({"products": rows, "assign": reg["assign"]}, indent=1))
        return 0
    if not reg["product"]:
        print(f"no products registered ({path()}). `teyla product init` proposes them from your repos.")
        return 0
    print(f"{'id':<22} {'stage':<9} F {'primary':<8} repos")
    for pid, p in reg["product"].items():
        print(_row(pid, p))
    return 0


def cmd_init(args) -> int:
    reg = _load_for_edit()
    if reg is None:
        return 1
    new = propose(reg)
    if not new:
        print("nothing to add: every git repo under code_root is registered.")
        return 0
    for pid, p in new.items():
        print(_row(pid, p))
    if not args.write:
        print(f"\n{len(new)} proposed; `teyla product init --write` adds them to {path()}")
        return 0
    reg["product"].update(new)
    save(reg)
    print(f"\nadded {len(new)} to {path()}")
    return 0


def cmd_add(args) -> int:
    reg = _load_for_edit()
    if reg is None:
        return 1
    err = check_id(args.id)
    if err or args.stage and args.stage not in STAGES:
        print(err or f"stage must be one of {', '.join(STAGES)}", file=sys.stderr)
        return 2
    if args.id in reg["product"]:
        print(f"{args.id} is already registered; use `teyla product set`.", file=sys.stderr)
        return 1
    repos = [abs_path(args.repo)] if args.repo else []
    reg["product"][args.id] = new_product(args.id, repos=repos, stage=args.stage or "", name=args.name or "")
    save(reg)
    print(_row(args.id, reg["product"][args.id]))
    return 0


def cmd_set(args) -> int:
    reg = _load_for_edit()
    if reg is None or not _known(reg, args.id):
        return 1
    if not args.assignments:
        print("usage: teyla product set <id> key=value...", file=sys.stderr)
        return 2
    rc = 0
    for a in args.assignments:
        if "=" not in a:
            print(f"not key=value: {a!r}", file=sys.stderr)
            rc = 2
            continue
        k, v = a.split("=", 1)
        try:
            print(set_field(reg, args.id, k, v))
        except ValueError as e:
            print(f"{k}: {e}", file=sys.stderr)
            rc = 2
    save(reg)
    return rc


def cmd_park_wake(args) -> int:
    reg = _load_for_edit()
    if reg is None or not _known(reg, args.id):
        return 1
    print((park if args.cmd == "park" else wake)(reg, args.id))
    save(reg)
    return 0


_SESSION_RE = re.compile(r"(?:local_)?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)


def assign(target: str, pid: str, ask_only: bool = False, items=None, now: float | None = None) -> tuple[list[str], int]:
    """File the session behind an ask (or the ask itself with `ask_only`) under product `pid`.
    `target` is an ask id prefix or a full session id. Returns the lines to print and the exit code."""
    from . import asks
    try:
        reg = load(strict=True)
    except RegistryError as e:
        return [f"teyla: {e}"], 1
    if pid not in reg["product"]:
        return [f"no product {pid!r}; registered: {', '.join(reg['product']) or 'none'}. "
                f"`teyla product add {pid}` registers it."], 1
    now = asks._now() if now is None else now
    items = asks.collect(max(asks.DEFAULT_DAYS, 365), now) if items is None else items
    same = [a for a in items if target and a.session == target]
    if same:
        hit, key = same[0], target
    else:
        hit, err = asks.resolve(target, items)
        if hit is None and _SESSION_RE.match(target):
            reg["assign"][target] = pid
            save(reg)
            return [f"assigned session {target} to {pid} (no current ask uses it)"], 0
        if hit is None:
            return [err], 1
        key = hit.id if ask_only or not hit.session else hit.session
    moved = [a for a in items if (a.id == key or (a.session == key and a.id not in reg["assign"]))
             and a.product != pid]
    reg["assign"][key] = pid
    save(reg)
    what = "ask" if key == hit.id else "session"
    lines = [f"assigned {what} {key} to {pid}"]
    lines += [f"  {a.id}  {a.product} -> {pid}  {a.title}" for a in moved]
    if not moved:
        lines.append("  nothing else moved")
    return lines, 0


def cmd_assign(args) -> int:
    lines, code = assign(args.target, args.id, args.ask_only)
    print("\n".join(lines), file=sys.stderr if code else sys.stdout)
    return code


def cmd_product(args) -> int:
    return {"list": cmd_list, "init": cmd_init, "add": cmd_add, "set": cmd_set, "park": cmd_park_wake,
            "wake": cmd_park_wake, "assign": cmd_assign}[args.cmd or "list"](args)


def register(sp):
    q = sp.add_parser("product", help="the product registry (~/.teyla/products.toml): repos, aliases, stage; "
                                      "`teyla products` is the usage table")
    q.set_defaults(fn=cmd_product)
    q.add_argument("--json", action="store_true", help="list: machine-readable")
    sub = q.add_subparsers(dest="cmd")
    s = sub.add_parser("list", help="one line per product"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("init", help="propose products from the git repos under code_root")
    s.add_argument("--write", action="store_true", help="add the proposed products that are not registered yet")
    s = sub.add_parser("add", help="register one product")
    s.add_argument("id"); s.add_argument("--repo"); s.add_argument("--name")
    s.add_argument("--stage", choices=STAGES)
    s = sub.add_parser("set", help="change fields: name stage primary focus aliases add-repo add-path")
    s.add_argument("id"); s.add_argument("assignments", nargs="*", metavar="key=value")
    for name in ("park", "wake"):
        s = sub.add_parser(name, help=f"{name} a product" + ("; the old stage is remembered" if name == "park" else ""))
        s.add_argument("id")
    s = sub.add_parser("assign", help="file the session behind an ask under a product")
    s.add_argument("target", help="ask id prefix, or a full session id")
    s.add_argument("id", help="product id")
    s.add_argument("--ask-only", action="store_true", help="move only this ask, not its whole session")
    return q
