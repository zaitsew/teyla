"""~/.teyla/config.toml — the few machine-level settings Teyla needs.

    code_root = "~/repos"          where this machine keeps code repos (doctor scans it)
    ops_root  = "~/ops"            the ops root (run artifacts, wiki)
    runs_root = "~/ops/runs"       where the weekly routine files its reports (default: <ops_root>/runs)
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
    auto_update = false            safe mode only: the daily `teyla update --quiet` may reach GitHub for
                                   the latest published release (nothing else may); `update.pin` still wins
    [products]
    repos = ["teyla", "~/work/x"]  the only repos `teyla products` runs `./check.sh usage` in
                                   (names under code_root, or paths); unset = every repo, outside safe mode
    [storage]
    auto_clean      = false        the daily routine removes finished worktrees + idle build output
    idle_days       = 3            a clean, pushed worktree untouched this long is finished
    agent_idle_days = 1            the same for a subagent's <repo>/.claude/worktrees/agent-*
    build_idle_days = 14           git-ignored build dirs of a repo idle this long are removed
    sim_idle_min    = 30           `storage sims --reap`: a booted simulator nothing uses this long is shut down
    sim_max_booted  = 3            above this many booted, idle ones go at once, longest idle first
    sim_prune_pattern = ""         regex on a device name (matched at its start): such devices that stay
                                   shut down sim_prune_days days are deleted; empty = never delete
    sim_prune_days  = 3
    sweep_*         = ...          `storage sweep` ages and limits (temp_hours, release_days, sim_days,
                                   derived_days, codex_days, grok_days, log_days, docker_days, log_max_mb,
                                   urgent_free_gb); docker_superseded_repos = ["registry/vendor/"] lets it
                                   remove older tags of those repositories (default none)
    sims_agent      = false        `teyla routine install` also writes an agent: storage sims --reap every 10 min
    sweep_agent     = false        ... and one for storage sweep --temp hourly; the weekly runs storage sweep
    [tidy]                         `teyla tidy`: the rule and memory files checked for junk
    max_kb     = 24                a file over this many KB is a finding (an always-loaded file this big is not read)
    stale_days = 120               a dated "until" / "for now" / "temporary" / "this week" / TODO line older than this is a finding
    [digest]
    notify = true                  the weekly digest posts a macOS notification when written
    [corrections]
    store = "home"                 "home": ~/.teyla/corrections/<repo-key>.jsonl (default);
                                   "repo": <repo>/.teyla/corrections.jsonl, the pre-0.12 place
    [spend]                        `teyla spend`: thresholds that act (every key optional)
    alert_session_usd = 250.0      --alert: a session that cost this much in the last day
    w1_usd            = 15.0       W1/W5: a session under this is not worth a finding
    daily_budget_usd  = 0.0        --alert: the day's total over this (API-equivalent); 0 = off
    budget.<project>  = 40.0       --alert: that project's day over this (project as `teyla spend` names it)
    a20_share         = 0.3        advice A20: explicit top-tier model in more than this share of a
                                   project's subagent calls ...
    a20_min_calls     = 10         ... and at least this many calls
    a20_models        = []         extra model names/aliases counted as top tier for A20
    [hooks]                        opt-in plugin hooks; off by default because a machine that
                                   already runs its own copies of both would double every message
    context_budget = false         at 240k tokens of context (then every 30k) the model writes a handoff
                                   to ~/.teyla/handoff/; it is put back after Claude Code compacts
                                   (~300k with "autoCompactWindow": 335000 in ~/.claude/settings.json)
    context_budget_first = 240000
    context_budget_step  = 30000
    land_check     = false         Stop: once per session, uncommitted or unpushed work is named, with
                                   how to land it (merge only into a MERGE-APPROVED repo)
    [harness]
    disabled = ["hermes", "grok"]  harnesses this machine does not use: doctor, health, `harness status|sync`
                                   and `policy sync` skip them entirely (claude-code, codex, grok, hermes,
                                   cursor); `teyla config set harness.disabled=hermes,grok`
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

import re
import copy
import json
import os
import pathlib

HOME = pathlib.Path.home()
TEYLA_DIR = HOME / ".teyla"
CONFIG_PATH = TEYLA_DIR / "config.toml"

DEFAULTS = {
    "code_root": "~/repos",
    "ops_root": "~/ops",
    "runs_root": "",  # empty = <ops_root>/runs (see runs_root())
    "update": {"repo": "zaitsew/teyla", "channel": "release"},
    "env": {},
    # `teyla storage`: auto_clean lets the daily routine remove finished worktrees (clean, on
    # the remote, idle >= idle_days) and git-ignored build output of repos idle >= build_idle_days.
    "storage": {"auto_clean": False, "idle_days": 3, "agent_idle_days": 1, "build_idle_days": 14,
                # `teyla storage sims`: shut down booted iOS simulators nothing is using.
                "sim_idle_min": 30, "sim_max_booted": 3, "sim_prune_pattern": "", "sim_prune_days": 3,
                # `teyla storage sweep`: what agent work leaves in temp, caches and logs.
                "sweep_temp_hours": 24, "sweep_release_days": 3, "sweep_urgent_free_gb": 20,
                "sweep_sim_days": 7, "sweep_derived_days": 14, "sweep_codex_days": 2, "sweep_grok_days": 14,
                "sweep_log_days": 14, "sweep_docker_days": 7, "sweep_log_max_mb": 50,
                "sweep_log_glob": "*.log", "docker_superseded_repos": [],
                # Optional launchd agents, written by `teyla routine install`.
                "sims_agent": False, "sweep_agent": False},
    # Where `teyla correct` and the capture hook keep corrections; see corrections.py for why
    # the default is outside the repo.
    "corrections": {"store": "home"},
    "safe": {"enabled": False, "auto_update": False},
    # Harnesses to leave alone: no health line, no FIX for their hooks or credits, no sync.
    "harness": {"disabled": []},
    "products": {"repos": []},
    # `teyla spend` thresholds; 0 = off for the budgets. Per-project budgets are `budget.<project>`
    # keys (or a [spend.budget] table): see spend.budgets().
    "spend": {"alert_session_usd": 250.0, "w1_usd": 15.0, "daily_budget_usd": 0.0,
              "a20_share": 0.3, "a20_min_calls": 10, "a20_models": []},
    # `teyla digest --write` (the weekly routine) posts a macOS notification with its headline.
    "digest": {"notify": True},
    # `teyla tidy`: size budget for a rule or memory file, and how old a dated "for now" may get.
    "tidy": {"max_kb": 24, "stale_days": 120},
    # The plugin's opt-in hooks (plugin/hooks/context-budget.sh, land-check.sh). Off by default: where
    # the same hooks are already wired some other way, a second copy doubles each note.
    # The hooks read these keys from the file with awk/tomllib, not through this module.
    "hooks": {"context_budget": False, "context_budget_first": 240000, "context_budget_step": 30000,
              "land_check": False},
}

# Claude Code compacts at autoCompactWindow minus the output reserve minus 13k: about 35k under
# the window. 335000 (compaction at ~300k) is the recommended value: a session that re-reads a long context
# every turn costs several times one that stays short, while a window much smaller than this
# compacts mid-task too often. The context-budget hook's 240k/30k reminders sit under it.
AUTOCOMPACT_RECOMMENDED = 335000
AUTOCOMPACT_MARGIN = 35000


def autocompact_window() -> int | None:
    """`autoCompactWindow` from ~/.claude/settings.json, or None when the file, the key or a
    usable number is missing. Read-only: the file belongs to Claude Code and to the person."""
    try:
        w = json.loads((HOME / ".claude" / "settings.json").read_text()).get("autoCompactWindow")
    except (OSError, ValueError, AttributeError):
        return None
    return w if isinstance(w, int) and not isinstance(w, bool) and w > AUTOCOMPACT_MARGIN else None


def compaction() -> tuple[int, int, bool]:
    """(window, compaction point, set): this machine's autoCompactWindow and where it compacts,
    or the recommended 335000 (~300k) with set=False when settings.json does not have one."""
    w = autocompact_window()
    window = w or AUTOCOMPACT_RECOMMENDED
    return window, window - AUTOCOMPACT_MARGIN, w is not None


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
    ~/.teyla holds prompt excerpts, the update record (paths, proxy) and doctor output; the
    default was 0755 with every file 0644 — readable by any other account on the Mac. Same user, same launchd agents: nothing Teyla runs needs more."""
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
    original (caught in review, P1)."""
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
    (caught in review, P1). Fail closed, and let doctor say why. Only a file that is really not
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
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k if re.fullmatch(r'[A-Za-z0-9_-]+', str(k)) else _toml_value(str(k))} = {_toml_value(x)}"
                                for k, x in v.items()) + " }"
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
        # [storage], [corrections], [digest], [spend] and [hooks] are kept: they are exactly the local adaptation a rewrite must not erase
        # (a work laptop that loses `safe.enabled` here would self-update the next morning).
        old = _read(p)
        for table in ("env", "safe", "products", "storage", "corrections", "digest", "hooks", "spend"):
            if isinstance(old.get(table), dict) and old[table]:
                data[table] = old[table]
        if old.get("runs_root"):
            data["runs_root"] = old["runs_root"]   # where the reports already go
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
    string read as false, and switched safe mode *off* (Codex review, P2)."""
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
    if isinstance(default, float):
        try:
            number = float(value)
        except ValueError:
            raise InvalidValue(f"{value!r} is not a number") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise InvalidValue(f"{value!r} is not a finite number")
        return number
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
                default = DEFAULTS[table].get(key)
                if default is None and table == "spend" and key.startswith("budget."):
                    default = 0.0  # a per-project budget is a dollar amount
                value = _coerce(default, value)
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
    body = dump(cfg)
    if not str(cfg.get("runs_root") or "").strip():
        body += f"# runs_root is unset; reports go to {runs_root(cfg)}\n"
    return head + body


HARNESS_NAMES = ("claude-code", "codex", "grok", "hermes", "cursor")
_HARNESS_ALIAS = {"claude": "claude-code", "claudecode": "claude-code", "claude_code": "claude-code"}


def disabled_harnesses(cfg: dict | None = None) -> tuple[list[str], list[str]]:
    """([known names], [unknown entries]) of `[harness] disabled`, in the order written, without
    duplicates. A string is read as a comma list, so a hand-edited `disabled = "hermes"` works too."""
    raw = ((cfg if cfg is not None else load()).get("harness") or {}).get("disabled") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    known: list[str] = []
    unknown: list[str] = []
    for item in raw:
        name = str(item).strip().lower()
        if not name:
            continue
        name = _HARNESS_ALIAS.get(name, name)
        bucket = known if name in HARNESS_NAMES else unknown
        if name not in bucket:
            bucket.append(name)
    return known, unknown


def harness_disabled(name: str, cfg: dict | None = None) -> bool:
    return name in disabled_harnesses(cfg)[0]


def truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


def hook_on(name: str, cfg: dict | None = None) -> bool:
    """Is the opt-in plugin hook `[hooks] <name>` switched on? Read the same way the hook's own
    sh wrapper reads it (true/1/yes/on), so doctor and `harness sync` agree with what runs."""
    return truthy(((cfg or load()).get("hooks") or {}).get(name))


SAFE_ENV = "TEYLA_SAFE"
SAFE_SUMMARY = "on (network off, no auto-update, no repo commands)"
SAFE_SUMMARY_AUTO = "on (network off except `teyla update` for published releases, no repo commands)"


def safe_mode(cfg: dict | None = None) -> bool:
    """Work mode: `[safe] enabled = true` in config.toml, or TEYLA_SAFE=1 in the environment.
    The variable can only switch it on — a stray TEYLA_SAFE=0 in some shell must not undo
    what the config file on a managed laptop says."""
    if _fail_closed(os.environ.get(SAFE_ENV)):
        return True
    return _fail_closed(((cfg or load()).get("safe") or {}).get("enabled"))


def safe_auto_update(cfg: dict | None = None) -> bool:
    """Safe mode with `[safe] auto_update = true`: `teyla update` (and only it) may reach GitHub for
    the latest published release. Fails open to *off*: anything but an explicit true word is false,
    because this setting only ever widens what a work laptop does."""
    cfg = cfg or load()
    return safe_mode(cfg) and truthy(((cfg.get("safe") or {}).get("auto_update")))


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


# Kept so installs from before runs_root keep their history.
_LEGACY_RUNS = ("startup", "os", "ai-dev", "runs")


def runs_root(cfg: dict | None = None) -> pathlib.Path:
    """Where the weekly routine files its reports: `runs_root` from config.toml (`~` expanded)
    when set, else <ops_root>/runs — the git-ignored directory `teyla policy init
    --ops-root-init` creates. An install that predates the key and already has a report tree in
    an older place keeps using that one until `runs_root` is set."""
    cfg = cfg or load()
    raw = str(cfg.get("runs_root") or "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    ops = ops_root(cfg)
    legacy = ops.joinpath(*_LEGACY_RUNS)
    return legacy if legacy.is_dir() else ops / "runs"


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
