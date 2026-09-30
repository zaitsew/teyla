"""~/.teyla/config.toml — the few machine-level settings Teyla needs.

    code_root = "~/repos"          where this machine keeps code repos (doctor scans it)
    ops_root  = "~/ops"            the ops root (run artifacts, wiki)
    [update]
    repo    = "zaitsew/teyla"      GitHub repo `teyla update` pulls releases from
    channel = "release"            "release" (published GitHub releases) or "none" (no routine
                                   ever updates; `teyla update` by hand still does)
    pin     = "0.12.0"             freeze updates to exactly this release version or commit sha
    python  = "3.12"               interpreter `teyla update` pins on every self-install
                                   (default: the one Teyla is running on right now)
    [safe]
    enabled = false                work mode (also env TEYLA_SAFE=1): no network, no self-update,
                                   no repo code run, no hand-edited plugin registry — see safe_mode()
    [products]
    repos = ["teyla", "~/work/x"]  the only repos `teyla products` runs `./check.sh usage` in
                                   (names under code_root, or paths); unset = every repo, outside safe mode
    [storage]
    auto_clean      = false        the daily routine removes finished worktrees + idle build output
    idle_days       = 3            a clean, pushed worktree untouched this long is finished
    agent_idle_days = 1            the same for a subagent's <repo>/.claude/worktrees/agent-*
    build_idle_days = 14           git-ignored build dirs of a repo idle this long are removed
    [corrections]
    store = "home"                 "home": ~/.teyla/corrections/<repo-key>.jsonl (default);
                                   "repo": <repo>/.teyla/corrections.jsonl, the pre-0.12 place
    [env]
    SSL_CERT_FILE = "~/.teyla/ca-bundle.pem"
    HTTPS_PROXY   = "http://127.0.0.1:9000"

`[env]` is the environment Teyla needs and cannot inherit: under launchd, from the
Claude Code desktop app's session hook, from `sh -c`, nothing reads a shell rc. Every
`teyla` process applies it at startup (`apply_env`, setdefault semantics — a variable
already set in the shell wins), and `teyla routine install` writes it into both
launchd plists and both wrapper scripts. Because the generator reads it from here on
every write, a local adaptation survives the update that regenerates the wrappers.

Every key has a default; the file is optional. `teyla policy init` writes it once so the
work laptop and the home laptop can differ in roots without differing in commands;
`teyla config set env.SSL_CERT_FILE=/path` edits one key without touching the rest.
"""
from __future__ import annotations

import copy
import os
import pathlib

HOME = pathlib.Path.home()
TEYLA_DIR = HOME / ".teyla"
CONFIG_PATH = TEYLA_DIR / "config.toml"

DEFAULTS = {
    "code_root": "~/repos",
    "ops_root": "~/ops",
    "update": {"repo": "zaitsew/teyla", "channel": "release"},
    "env": {},
    # `teyla storage`: auto_clean lets the daily routine remove finished worktrees (clean, on
    # the remote, idle >= idle_days) and git-ignored build output of repos idle >= build_idle_days.
    "storage": {"auto_clean": False, "idle_days": 3, "agent_idle_days": 1, "build_idle_days": 14},
    # Where `teyla correct` and the capture hook keep corrections; see corrections.py for why
    # the default is outside the repo.
    "corrections": {"store": "home"},
    "safe": {"enabled": False},
    "products": {"repos": []},
}


UNPARSEABLE = "unparseable"


def parse_error(p: pathlib.Path | None = None) -> str | None:
    """Why config.toml cannot be read, or None when it is absent or parses."""
    p = p or CONFIG_PATH
    import tomllib
    try:
        tomllib.loads(p.read_text())
    except FileNotFoundError:
        return None
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        return str(e)
    return None


def private_dir(d: pathlib.Path) -> pathlib.Path:
    """mkdir -p `d` at 0700, and tighten it if it already exists with group/other bits.
    ~/.teyla holds prompt excerpts, the update record (paths, proxy) and doctor output; on
    the machine this was written on it was 0755 with every file 0644 — readable by any
    other account on the Mac. Same user, same launchd agents: nothing Teyla runs needs more."""
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if d.stat().st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def write_all(fd: int, data: bytes) -> None:
    """Write every byte of `data` to `fd`, then fsync. `os.write` may write fewer bytes than
    asked — a full disk or quota — and says so only in its return value: an unchecked call
    reported a half-written record as saved, and the worktree rescue then deleted the
    original (review of #63, P1)."""
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(f"short write: {len(view)} bytes not written")
        view = view[n:]
    os.fsync(fd)


def write_private(path: pathlib.Path, text: str) -> None:
    """Write `text` to `path` as 0600, its directory 0700. An existing file is tightened too:
    O_CREAT's mode only applies when the file is new."""
    private_dir(path.parent)
    # Mode fixed on the descriptor before the old content is truncated or the new written;
    # O_NOFOLLOW so a symlink planted at the path cannot redirect the write.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        write_all(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _read(p: pathlib.Path) -> dict:
    """The file's tables, or — when it exists and does not parse — a config whose only content
    is a safe mode that cannot be read as off. Returning {} here made one stray quote in [env]
    turn safe mode off: doctor then asked GitHub, routines ran gh, products ran every check.sh
    (review of #59, P1). Fail closed, and let doctor say why. Only a file that is really not
    there reads as {}: Path.exists() is False when stat itself is refused (a 0000 parent
    directory), which made an unreadable config look absent — safe mode off (review, P1)."""
    import tomllib
    try:
        return tomllib.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        return {"safe": {"enabled": f"{UNPARSEABLE} {p.name}: {e}"}}


def load(path: pathlib.Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in _read(path or CONFIG_PATH).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    env_repo = os.environ.get("TEYLA_REPO")
    if env_repo:
        cfg["update"]["repo"] = env_repo
    return cfg


def env_vars(cfg: dict | None = None) -> dict[str, str]:
    """The `[env]` block as {NAME: value}, values stringified and `~` expanded. Only string,
    int, float and bool values are accepted; anything else is skipped rather than guessed."""
    out = {}
    for k, v in ((cfg or load()).get("env") or {}).items():
        if isinstance(v, bool):
            v = "1" if v else "0"
        if isinstance(v, (str, int, float)):
            out[str(k)] = os.path.expanduser(str(v))
    return out


def apply_env(cfg: dict | None = None) -> list[str]:
    """os.environ.setdefault for every `[env]` entry. Returns the names that were applied
    (not already set). Called once, at CLI startup, before anything opens a socket."""
    applied = []
    for k, v in env_vars(cfg).items():
        if k not in os.environ:
            os.environ[k] = v
            applied.append(k)
    return applied


def _toml_value(v) -> str:
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dump(data: dict) -> str:
    """Serialise the config shape (scalars, then one level of tables) as TOML. Keys are kept
    in the order given; tables come after the top-level scalars, as TOML requires."""
    lines = []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    for k, v in data.items():
        if isinstance(v, dict):
            lines += ["", f"[{k}]"]
            for kk, vv in v.items():
                key = kk if kk.replace("_", "").replace("-", "").isalnum() else _toml_value(kk)
                lines.append(f"{key} = {_toml_value(vv)}")
    return "\n".join(lines).lstrip("\n") + "\n"


def write(code_root: str = "~/repos", ops_root: str = "~/ops", repo: str = "zaitsew/teyla",
          channel: str = "release", path: pathlib.Path | None = None, force: bool = False) -> str:
    p = path or CONFIG_PATH
    if p.exists() and not force:
        return f"exists: {p}"
    err = parse_error(p)
    if err:
        return f"invalid config: {p} does not parse ({err}); not rewritten — fix it by hand"
    data = {"code_root": code_root, "ops_root": ops_root, "update": {"repo": repo, "channel": channel}}
    if p.exists():
        # --force rewrites the roots and the update block; [env], [safe], [products],
        # [storage] and [corrections] are kept: they are exactly the local adaptation a rewrite must not erase
        # (a work laptop that loses `safe.enabled` here would self-update the next morning).
        old = _read(p)
        for table in ("env", "safe", "products", "storage", "corrections"):
            if isinstance(old.get(table), dict) and old[table]:
                data[table] = old[table]
        # The same for a pin, an interpreter pin and channel = "none": a frozen update that
        # silently thaws on `policy init --force` is not frozen.
        for key in ("pin", "python", "channel"):
            if isinstance(old.get("update"), dict) and old["update"].get(key):
                data["update"][key] = old["update"][key]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump(data))
    return f"wrote {p}"


TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")


class InvalidValue(ValueError):
    pass


def _coerce(default, value: str):
    """A `config set` string as the type its default has: `safe.enabled=true` must be a TOML
    boolean and `products.repos=a,b` a list, or every reader has to re-guess the string.
    A value that is not of that type raises InvalidValue: `safe.enabled=treu` stored as a
    string read as false, and switched safe mode *off* (Codex review of #59, P2)."""
    if isinstance(default, bool):
        low = value.strip().lower()
        if low in TRUE_WORDS:
            return True
        if low in FALSE_WORDS:
            return False
        raise InvalidValue(f"{value!r} is not a boolean: true or false")
    if isinstance(default, int):
        try:
            return int(value)
        except ValueError:
            raise InvalidValue(f"{value!r} is not a whole number") from None
    if isinstance(default, list):
        return [x.strip() for x in value.split(",") if x.strip()]
    return value


def set_value(dotted: str, value: str | None, path: pathlib.Path | None = None) -> str:
    """`teyla config set env.SSL_CERT_FILE=/path` / `update.python=3.12` / `code_root=~/work`.
    value None deletes the key. Only the file's own content is rewritten — defaults are
    not materialised into it, so a later release can still change a default."""
    p = path or CONFIG_PATH
    err = parse_error(p)
    if err:
        # Rewriting from what _read() returns would keep one key and drop [env], the roots and
        # [products] — the whole local adaptation — on top of a typo.
        return f"invalid config: {p} does not parse ({err}); nothing written — fix it by hand"
    data = _read(p)
    parts = dotted.split(".", 1)
    if len(parts) == 2:
        table, key = parts
        if table not in DEFAULTS or not isinstance(DEFAULTS[table], dict):
            return f"unknown table {table!r}; known: {', '.join(k for k, v in DEFAULTS.items() if isinstance(v, dict))}"
        sub = data.setdefault(table, {})
        if not isinstance(sub, dict):
            return f"{table} is not a table in {p}"
        if value is None:
            if key not in sub:
                return f"{dotted} not set"
            del sub[key]
        else:
            try:
                value = _coerce(DEFAULTS[table].get(key), value)
            except InvalidValue as e:
                return f"invalid {dotted}: {e}; nothing written"
            sub[key] = value
    else:
        key = parts[0]
        if key not in DEFAULTS or isinstance(DEFAULTS[key], dict):
            return f"unknown key {key!r}; known: {', '.join(k for k, v in DEFAULTS.items() if not isinstance(v, dict))}"
        if value is None:
            if key not in data:
                return f"{dotted} not set"
            del data[key]
        else:
            data[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump(data))
    return (f"unset {dotted} in {p}" if value is None else f"set {dotted} = {value!r} in {p}")


def show(path: pathlib.Path | None = None) -> str:
    p = path or CONFIG_PATH
    cfg = load(p)
    head = f"# {p} ({'exists' if p.exists() else 'absent — defaults'})\n"
    return head + dump(cfg)


def truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


SAFE_ENV = "TEYLA_SAFE"
SAFE_SUMMARY = "on (network off, no auto-update, no repo commands)"


def safe_mode(cfg: dict | None = None) -> bool:
    """Work mode: `[safe] enabled = true` in config.toml, or TEYLA_SAFE=1 in the environment.
    The variable can only switch it on — a stray TEYLA_SAFE=0 in some shell must not undo
    what the config file on a managed laptop says."""
    if _fail_closed(os.environ.get(SAFE_ENV)):
        return True
    return _fail_closed(((cfg or load()).get("safe") or {}).get("enabled"))


def _fail_closed(v) -> bool:
    """Absent or an explicit false word → off; true, or anything present that is neither
    (`"treu"`, `2`, a list) → on. A typo must never be what turns a work laptop's safe mode off."""
    if v is None or v is False:
        return False
    if v is True:
        return True
    low = str(v).strip().lower()
    return low != "" and low not in FALSE_WORDS


def safe_setting_invalid(cfg: dict | None = None):
    """The raw `[safe] enabled` value when it is present but not a boolean, else None."""
    v = ((cfg or load()).get("safe") or {}).get("enabled")
    if v is None or isinstance(v, bool) or str(v).strip().lower() in TRUE_WORDS + FALSE_WORDS:
        return None
    return v


def products_allowlist(cfg: dict | None = None) -> list[pathlib.Path]:
    """`[products] repos` resolved to paths: a bare name is a directory under code_root, anything
    with a slash or a `~` is a path."""
    cfg = cfg or load()
    raw = (cfg.get("products") or {}).get("repos") or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    root = code_root(cfg)
    return [(pathlib.Path(r).expanduser() if ("/" in r or r.startswith("~")) else root / r).resolve()
            for r in (str(x) for x in raw)]


def runs_root(cfg: dict | None = None) -> pathlib.Path:
    """Where the weekly routine files its reports: the owner's existing
    <ops_root>/startup/os/ai-dev/runs when that tree exists, else <ops_root>/runs — the
    git-ignored directory `teyla policy init --ops-root-init` creates."""
    ops = ops_root(cfg)
    legacy = ops / "startup" / "os" / "ai-dev"
    return legacy / "runs" if legacy.is_dir() else ops / "runs"


def code_root(cfg: dict | None = None) -> pathlib.Path:
    return pathlib.Path((cfg or load())["code_root"]).expanduser()


def ops_root(cfg: dict | None = None) -> pathlib.Path:
    return pathlib.Path((cfg or load())["ops_root"]).expanduser()


# --- CLI --------------------------------------------------------------------

def cmd_config(args):
    if args.action == "show":
        print(show(), end="")
        return 0
    if not args.assignments:
        print("usage: teyla config set KEY=VALUE [KEY=VALUE ...]   (KEY=  unsets; e.g. env.SSL_CERT_FILE=~/.teyla/ca.pem, update.python=3.12)")
        return 2
    rc = 0
    for a in args.assignments:
        if "=" not in a:
            print(f"not KEY=VALUE: {a!r}"); rc = 2; continue
        k, v = a.split("=", 1)
        msg = set_value(k.strip(), v.strip() or None)
        print(msg)
        if msg.startswith(("unknown", "invalid")) or msg.endswith("not set") or "is not a table" in msg:
            rc = 1
    return rc


def register(sp):
    q = sp.add_parser("config", help="show ~/.teyla/config.toml, or set one key: teyla config set env.SSL_CERT_FILE=/path")
    q.set_defaults(fn=cmd_config)
    q.add_argument("action", choices=["show", "set"])
    q.add_argument("assignments", nargs="*", help="set: KEY=VALUE; KEY= removes the key")
