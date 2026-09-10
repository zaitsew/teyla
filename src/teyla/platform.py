"""`teyla platform` — the shared resources you set up once and then reuse for every product.

A person who builds small apps alone accumulates the same gap seven times: the app works,
and there is no always-on host, no domain, no mail sender, no signing key, no place to put
a secret. Each of those is bought once and reused forever, but nothing on the machine
records that they exist, so every new product re-decides them from scratch — and usually
decides "later", which is the same as "never share this".

`~/.teyla/platform.toml` is the manifest of those shared resources. It holds identifiers
and the *names* of environment variables, never a secret value: the values live in one
mode-0600 file (`[secrets].file`), and this command only ever reports which names are
present in it.

    teyla platform init [--owner NAME]   write the manifest from the template
    teyla platform [--json] [--no-net]   what is set up, what is missing, the step for each
    teyla platform env-example           the secrets skeleton, names only, no values

Every missing resource prints the owner's step in one line: the URL where the thing is
created, and the file plus key name where its value goes. That sentence is the whole
point — a missing resource that does not say how to get it is a to-do nobody does.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import stat
import subprocess

from . import config

PLATFORM_PATH = config.TEYLA_DIR / "platform.toml"

# States. Anything in FAIL_STATES makes the command exit 1: "unreachable" is not a
# milder "missing" — a host you cannot reach is a host no product can deploy to.
OK = "ok"
MISSING = "MISSING"
UNREACHABLE = "UNREACHABLE"
WARN = "WARN"
NA = "n/a"
FAIL_STATES = {MISSING, UNREACHABLE}

SSH_TIMEOUT = 8


def template_path() -> pathlib.Path:
    import teyla
    return teyla.templates_dir() / "platform" / "platform.toml"


def platform_templates() -> pathlib.Path:
    """Where the shared-server scripts live, quoted verbatim in the `what to do` column."""
    import teyla
    return teyla.templates_dir() / "platform"


# --- the manifest ----------------------------------------------------------------

def load(path: pathlib.Path | None = None) -> dict:
    """Parse platform.toml. A missing or unparseable file is an empty manifest — every
    section is optional and absent means "not set up", which is exactly what to report."""
    p = path or PLATFORM_PATH
    if not p.exists():
        return {}
    import tomllib
    try:
        return tomllib.loads(p.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def init(owner: str | None = None, force: bool = False, path: pathlib.Path | None = None) -> str:
    p = path or PLATFORM_PATH
    if p.exists() and not force:
        return f"exists: {p}  (use --force to overwrite)"
    text = template_path().read_text().replace("{{owner}}", owner or os.environ.get("USER", "you"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return f"wrote {p}"


def secrets_file(cfg: dict) -> pathlib.Path:
    raw = (cfg.get("secrets") or {}).get("file") or "~/.config/teyla/platform.env"
    return pathlib.Path(raw).expanduser()


def env_names(path: pathlib.Path) -> set[str]:
    """The KEY names defined in a KEY=value file. Values are never read into memory as
    values — only the part before the first `=` is kept."""
    if not path.exists():
        return set()
    out = set()
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        # A name with nothing after `=` is the skeleton `env-example` writes: not set.
        # The value itself is looked at only for emptiness and never kept or printed.
        if name and value:
            out.add(name)
    return out


def declared_env_names(cfg: dict) -> list[str]:
    """Every `*_env` value in the manifest — the names a secrets file is expected to hold."""
    names = []
    for section in cfg.values():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if key.endswith("_env") and isinstance(value, str) and value:
                names.append(value)
    return sorted(dict.fromkeys(names))


def env_example(cfg: dict | None = None) -> str:
    cfg = cfg if cfg is not None else load()
    names = declared_env_names(cfg) or [
        "DIGITALOCEAN_ACCESS_TOKEN", "CLOUDFLARE_API_TOKEN",
        "SUPABASE_ACCESS_TOKEN", "RESEND_API_KEY", "OPENAI_API_KEY",
    ]
    path = secrets_file(cfg)
    lines = [
        f"# {path} — mode 0600, one KEY=value per line, never committed.",
        "# `teyla platform` reads the NAMES in this file and never a value.",
        "#",
        f"#   mkdir -p {path.parent} && touch {path} && chmod 600 {path}",
        "",
    ]
    lines += [f"{n}=" for n in names]
    return "\n".join(lines) + "\n"


# --- the checks ------------------------------------------------------------------

def _row(resource, state, todo, detail=""):
    return {"resource": resource, "state": state, "detail": detail, "todo": todo}


def _mode(path: pathlib.Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _ssh_ok(user: str, host: str) -> bool:
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", "true"],
            capture_output=True, timeout=SSH_TIMEOUT,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _resolves(name: str) -> bool:
    try:
        socket.gethostbyname(name)
        return True
    except OSError:
        return False


def _check_secrets(cfg, present, path):
    declared = declared_env_names(cfg)
    if not path.exists():
        return _row("secrets", MISSING, f"create it: mkdir -p {path.parent} && touch {path} && chmod 600 {path} "
                                        f"— then `teyla platform env-example` lists every name it wants",
                    f"{path} absent")
    mode = _mode(path)
    if mode != 0o600:
        return _row("secrets", MISSING, f"tighten it: chmod 600 {path}", f"{path} is mode {mode:04o}, want 0600")
    have = sorted(n for n in declared if n in present)
    miss = [n for n in declared if n not in present]
    detail = f"{path} 0600; {len(have)}/{len(declared)} names present"
    if miss:
        return _row("secrets", WARN, f"still unset in {path}: {', '.join(miss)}", detail)
    return _row("secrets", OK, "-", detail)


def _check_server(cfg, no_net):
    s = cfg.get("server") or {}
    provider = s.get("provider", "none")
    tmpl = platform_templates()
    if provider in ("", "none"):
        return _row("server", NA, "-", "no shared server declared")
    host = (s.get("host") or "").strip()
    name = s.get("name") or "apps-1"
    user = s.get("ssh_user") or "deploy"
    if not host:
        return _row("server", MISSING,
                    f"provision it: bash {tmpl}/provision-droplet.sh --yes  (needs {s.get('token_env', 'DIGITALOCEAN_ACCESS_TOKEN')}), "
                    f"then paste the IP as host = in {PLATFORM_PATH} — runbook: {tmpl}/README.md",
                    f"{provider} droplet '{name}' not provisioned")
    if no_net:
        return _row("server", OK, "-", f"{user}@{host} (not probed: --no-net)")
    if _ssh_ok(user, host):
        return _row("server", OK, "-", f"{user}@{host} reachable")
    return _row("server", UNREACHABLE,
                f"check the box and your key: ssh {user}@{host} — first setup is bash {tmpl}/setup-server.sh run as root",
                f"{user}@{host} did not answer")


def _check_domain(cfg, present, no_net):
    d = cfg.get("domain") or {}
    name = (d.get("name") or "").strip()
    token_env = d.get("token_env") or "CLOUDFLARE_API_TOKEN"
    path = secrets_file(cfg)
    if not name:
        return _row("domain", MISSING,
                    f"register one (https://dash.cloudflare.com/?to=/:account/domains/register) → put it as name = in {PLATFORM_PATH}, "
                    f"and an API token as {token_env}= in {path}",
                    "no domain")
    if no_net:
        return _row("domain", OK, "-", f"{name} (not resolved: --no-net)")
    if not _resolves(name):
        return _row("domain", UNREACHABLE,
                    f"point {name} at the server: an A record for {d.get('pattern', '<product>.{domain}')} → the server host",
                    f"{name} does not resolve")
    extra = "" if token_env in present else f"; {token_env} not in {path}"
    return _row("domain", OK if not extra else WARN,
                "-" if not extra else f"add {token_env}= to {path} so DNS records can be written without the dashboard",
                f"{name} resolves{extra}")


def _check_identity(cfg, present):
    i = cfg.get("identity") or {}
    provider = i.get("provider", "none")
    path = secrets_file(cfg)
    if provider in ("", "none"):
        return _row("identity", NA, "-", "no shared identity provider declared")
    org = (i.get("org") or "").strip()
    token_env = i.get("access_token_env") or "SUPABASE_ACCESS_TOKEN"
    tool = "supabase" if provider == "supabase" else provider
    have_tool = shutil.which(tool) is not None
    if not have_tool:
        return _row("identity", MISSING,
                    f"install the CLI: brew install {tool} (then `{tool} login`)",
                    f"{tool} not on PATH")
    if not org:
        return _row("identity", MISSING,
                    f"copy the org id from https://supabase.com/dashboard/organizations → org = in {PLATFORM_PATH}",
                    f"{tool} present, org unset")
    extra = "" if token_env in present else f"; {token_env} not in {path}"
    return _row("identity", OK if not extra else WARN,
                "-" if not extra else f"create a token at https://supabase.com/dashboard/account/tokens → {token_env}= in {path}",
                f"{tool} present, org {org}{extra}")


def _check_mail(cfg, present):
    m = cfg.get("mail") or {}
    provider = m.get("provider", "none")
    path = secrets_file(cfg)
    if provider in ("", "none"):
        return _row("mail", MISSING,
                    f"pick a sender (https://resend.com/signup — free tier is enough) → provider/from in {PLATFORM_PATH}, key as RESEND_API_KEY= in {path}",
                    "no mail sender: sign-in codes reach only your own inbox")
    key_env = m.get("key_env") or "RESEND_API_KEY"
    if key_env not in present:
        return _row("mail", MISSING,
                    f"create the key at https://resend.com/api-keys → paste as {key_env}= in {path}",
                    f"{provider}: {key_env} absent")
    sender = (m.get("from") or "").strip()
    if not sender:
        return _row("mail", WARN, f"set from = in {PLATFORM_PATH} to a verified sender address", f"{provider}: no from address")
    return _row("mail", OK, "-", f"{provider}, from {sender}")


def _check_apple(cfg):
    a = cfg.get("apple") or {}
    cfg_path = pathlib.Path(a.get("config") or "~/.appstoreconnect/config.env").expanduser()
    tool = pathlib.Path(a.get("release_tool") or "~/ops/bin/testflight").expanduser()
    if not cfg_path.exists():
        return _row("apple", MISSING,
                    f"create an App Store Connect API key (https://appstoreconnect.apple.com/access/integrations/api) → "
                    f"ids in {cfg_path}, the .p8 in {cfg_path.parent}/private_keys/ at mode 600",
                    f"{cfg_path} absent")
    names = env_names(cfg_path)
    want = {"ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_TEAM_ID"}
    missing = sorted(want - names)
    if missing:
        return _row("apple", MISSING, f"add {', '.join(missing)} to {cfg_path}", f"{cfg_path}: {', '.join(missing)} unset")
    keys_dir = cfg_path.parent / "private_keys"
    p8 = sorted(keys_dir.glob("*.p8")) if keys_dir.is_dir() else []
    if not p8:
        return _row("apple", MISSING,
                    f"download the .p8 once (it is shown once) into {keys_dir}/ and chmod 600 it",
                    f"no .p8 in {keys_dir}")
    if not tool.exists():
        return _row("apple", WARN, f"the release tool named in {PLATFORM_PATH} is not at {tool}", f"ids and key ok; {tool} absent")
    if not os.access(tool, os.X_OK):
        return _row("apple", WARN, f"chmod +x {tool}", f"ids and key ok; {tool} not executable")
    return _row("apple", OK, "-", f"3 ids, {len(p8)} key(s), {tool}")


def _check_android(cfg):
    a = cfg.get("android") or {}
    if not a.get("play_console"):
        return _row("android", MISSING,
                    "open a Play Console account ($25 once, https://play.google.com/console/signup) → play_console = true in "
                    f"{PLATFORM_PATH}. Until then Android ships as a PWA, which needs nothing.",
                    "no Play Console")
    ks = (a.get("keystore") or "").strip()
    if not ks:
        return _row("android", MISSING,
                    "generate an upload keystore (keytool -genkeypair -v -keystore <path> -alias upload -keyalg RSA -keysize 2048 -validity 10000) "
                    f"→ keystore = in {PLATFORM_PATH}; back it up, it cannot be regenerated",
                    "Play Console yes, no keystore")
    p = pathlib.Path(ks).expanduser()
    if not p.exists():
        return _row("android", MISSING, f"the keystore named in {PLATFORM_PATH} is not at {p} — restore it from your backup", f"{p} absent")
    return _row("android", OK, "-", f"Play Console, keystore {p}")


def _check_llm(cfg, present):
    l = cfg.get("llm") or {}
    provider = l.get("provider", "none")
    path = secrets_file(cfg)
    if provider in ("", "none"):
        return _row("llm", NA, "-", "no shared model provider declared")
    key_env = l.get("key_env") or "OPENAI_API_KEY"
    if key_env not in present:
        return _row("llm", MISSING,
                    f"create a project key at https://platform.openai.com/api-keys, cap its budget in the dashboard → {key_env}= in {path}",
                    f"{provider}: {key_env} absent")
    return _row("llm", OK, "-", f"{provider}, {key_env} set" + (f"; policy: {l['policy']}" if l.get("policy") else ""))


def checks(cfg: dict | None = None, *, no_net: bool = False) -> list[dict]:
    cfg = cfg if cfg is not None else load()
    if not cfg:
        return [_row("platform.toml", MISSING, f"teyla platform init --owner \"Your Name\"  (writes {PLATFORM_PATH})",
                     f"{PLATFORM_PATH} absent")]
    path = secrets_file(cfg)
    present = env_names(path)
    return [
        _check_secrets(cfg, present, path),
        _check_server(cfg, no_net),
        _check_domain(cfg, present, no_net),
        _check_identity(cfg, present),
        _check_mail(cfg, present),
        _check_apple(cfg),
        _check_android(cfg),
        _check_llm(cfg, present),
    ]


def mail_ready(cfg: dict | None = None) -> bool:
    """Whether a product targeting `public` can send its own sign-in mail. Used by
    `teyla productize`, which is why it is a function here and not a line in the table."""
    cfg = cfg if cfg is not None else load()
    if not cfg:
        return False
    return _check_mail(cfg, env_names(secrets_file(cfg)))["state"] == OK


def failing(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["state"] in FAIL_STATES]


def owner_steps(rows: list[dict]) -> list[str]:
    """One line per resource that needs the owner. These go first in
    `teyla productize --owner-steps`: a platform resource unblocks several products at once."""
    return [f"platform/{r['resource']}: {r['todo']}" for r in rows if r["state"] in FAIL_STATES or r["state"] == WARN]


# --- rendering -------------------------------------------------------------------

def render(rows: list[dict]) -> str:
    from .routines import _table
    body = _table(["resource", "state", "what to do"],
                  [[r["resource"], r["state"], r["todo"] if r["state"] != OK else (r["detail"] or "-")] for r in rows])
    bad = failing(rows)
    tail = ["", f"{len(bad)} resource(s) not set up." if bad else "", "Every resource here is bought once and reused by every product."]
    return "\n".join(body + [t for t in tail if t != ""] + [""])


def to_json(rows: list[dict]) -> dict:
    return {"resources": rows, "missing": [r["resource"] for r in failing(rows)]}


# --- command ---------------------------------------------------------------------

def cmd_platform(args):
    action = getattr(args, "action", None)
    if action == "init":
        print(init(owner=getattr(args, "owner", None), force=getattr(args, "force", False)))
        return 0
    if action == "env-example":
        print(env_example(), end="")
        return 0
    rows = checks(no_net=getattr(args, "no_net", False))
    if getattr(args, "json", False):
        print(json.dumps(to_json(rows), indent=2))
    else:
        print(render(rows), end="")
    return 1 if failing(rows) else 0


def register(sp):
    q = sp.add_parser("platform", help="the shared resources set up once and reused by every product")
    q.set_defaults(fn=cmd_platform)
    q.add_argument("action", nargs="?", choices=["init", "env-example"],
                   help="init: write ~/.teyla/platform.toml; env-example: the secrets skeleton, names only")
    q.add_argument("--owner", help="init: the name written into the manifest")
    q.add_argument("--force", action="store_true", help="init: overwrite an existing manifest")
    q.add_argument("--json", action="store_true")
    q.add_argument("--no-net", action="store_true", help="skip the ssh and DNS probes")
    return q
