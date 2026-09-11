"""~/.teyla/config.toml — the few machine-level settings Teyla needs.

    code_root = "~/repos"          where this machine keeps code repos (doctor scans it)
    ops_root  = "~/ops"            the ops root (run artifacts, wiki)
    [update]
    repo    = "zaitsew/teyla"      GitHub repo `teyla update` pulls releases from
    channel = "release"            "release" (tags) or "main" (tip of main)
    python  = "3.12"               interpreter `teyla update` pins on every self-install
                                   (default: the one Teyla is running on right now)
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
}


def _read(p: pathlib.Path) -> dict:
    if not p.exists():
        return {}
    import tomllib
    try:
        return tomllib.loads(p.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return {}


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
    data = {"code_root": code_root, "ops_root": ops_root, "update": {"repo": repo, "channel": channel}}
    if p.exists():
        # --force rewrites the roots and the update block; an existing [env] block is kept,
        # it is exactly the local adaptation a rewrite must not erase.
        old_env = _read(p).get("env")
        if isinstance(old_env, dict) and old_env:
            data["env"] = old_env
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump(data))
    return f"wrote {p}"


def set_value(dotted: str, value: str | None, path: pathlib.Path | None = None) -> str:
    """`teyla config set env.SSL_CERT_FILE=/path` / `update.python=3.12` / `code_root=~/work`.
    value None deletes the key. Only the file's own content is rewritten — defaults are
    not materialised into it, so a later release can still change a default."""
    p = path or CONFIG_PATH
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
        if msg.startswith("unknown") or msg.endswith("not set") or "is not a table" in msg:
            rc = 1
    return rc


def register(sp):
    q = sp.add_parser("config", help="show ~/.teyla/config.toml, or set one key: teyla config set env.SSL_CERT_FILE=/path")
    q.set_defaults(fn=cmd_config)
    q.add_argument("action", choices=["show", "set"])
    q.add_argument("assignments", nargs="*", help="set: KEY=VALUE; KEY= removes the key")
