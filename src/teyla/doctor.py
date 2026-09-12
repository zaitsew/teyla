"""`teyla doctor` — everything that has to be true for Teyla to work on this machine
without anyone remembering to run something.

Each check is (level, name, detail, fix): level is OK, INFO, WARN or FIX. FIX means a
command exists that repairs it and doctor names it. Absent harnesses and absent CLIs are
INFO, never failures: the work laptop has Claude Code only and no `gh`, and that is a
different tool scope, not a broken install.

Writes ~/.teyla/doctor.json (full) and ~/.teyla/doctor.summary (one line) so the
session-start hook can show "teyla: 2 fix(es) pending" without running Python.
Exit status: 1 if any FIX, else 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import shutil
import stat
import sys

from . import __version__, config

DOCTOR_JSON = config.TEYLA_DIR / "doctor.json"
DOCTOR_SUMMARY = config.TEYLA_DIR / "doctor.summary"


def _check(level, name, detail, fix=None):
    return {"level": level, "name": name, "detail": detail, "fix": fix}


def checks(refresh_update: bool = False, scan_repos: bool = True) -> list[dict]:
    from . import policy, update, routine_install, plugin_install
    from .adapters import claude_code, codex, grok, hermes
    cfg = config.load()
    out = []

    # --- version ---------------------------------------------------------------
    rec = update.check(refresh=refresh_update, max_age_hours=24)
    method = rec.get("method")
    when = rec.get("checked", "")[:16]
    how = f"cached {when}, not retried" if rec.get("from_cache") else f"checked {when}"
    if rec.get("latest") is None:
        out.append(_check("WARN", "version", f"{__version__} ({method}); latest unknown — see network ({how})"))
    elif rec.get("newer"):
        out.append(_check("FIX", "version", f"{__version__} installed, {rec['latest']} available ({method})", "teyla update"))
    else:
        out.append(_check("OK", "version", f"{__version__} ({method}) is current; {how}"))

    # --- network: can this machine reach its own update source? -----------------------
    # The one check every future update depends on. Proxy, trust store and interpreter are
    # the three facts that decide it, and the three a managed laptop hides in places nothing
    # under launchd or a GUI app reads; naming them here turns a debugging session into a glance.
    py_running = f"{sys.version_info.major}.{sys.version_info.minor}"
    pin = rec.get("python_pin") or update.python_spec(cfg)
    proxy = rec.get("proxy") if "proxy" in rec else update.proxy_in_use()
    trust = rec.get("trust") or update.trust_source()
    facts = (f"{'via proxy ' + proxy if proxy else 'no proxy'}; trust: {trust}; "
             f"python {rec.get('python') or py_running} ({method}, update pins {pin})")
    repo = rec.get("repo") or cfg["update"]["repo"]
    if rec.get("latest") is not None:
        out.append(_check("OK", "network", f"github.com reachable for {repo} — {facts}"))
    elif rec.get("reachable"):
        out.append(_check("WARN", "network", f"github.com reachable for {repo} but no release or v* tag found ({how}): {rec.get('note')} — {facts}"))
    else:
        hint = update.explain_tls_error(rec.get("note"))
        out.append(_check("FIX", "network", f"github.com UNREACHABLE for {repo} ({how}): {rec.get('note')} — {facts}",
                          hint or "check the proxy/VPN, then: teyla update --check   (retries now)"))
    if pin != py_running:
        out.append(_check("WARN", "network:python", f"running on python {py_running} but `[update] python` pins {pin}: the next update moves the install",
                          f"teyla config set update.python={py_running}   (or teyla update --force to move now)"))

    # --- config --------------------------------------------------------------
    if config.CONFIG_PATH.exists():
        out.append(_check("OK", "config", f"{config.CONFIG_PATH}: code_root={cfg['code_root']} ops_root={cfg['ops_root']} repo={cfg['update']['repo']}"))
    else:
        out.append(_check("INFO", "config", f"no {config.CONFIG_PATH}; defaults code_root={cfg['code_root']} ops_root={cfg['ops_root']}",
                          "teyla policy init  (writes it)"))

    # --- harness stores --------------------------------------------------------
    for mod in (claude_code, codex, grok, hermes):
        root = getattr(mod, "DEFAULT_ROOT", None)
        ok = bool(root) and os.path.exists(os.path.expanduser(root))
        if not ok:
            out.append(_check("INFO", f"harness:{mod.NAME}", "absent on this machine"))
            continue
        try:
            n = len(mod.load())
            out.append(_check("OK", f"harness:{mod.NAME}", f"{root}: {n} session(s)"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("WARN", f"harness:{mod.NAME}", f"{root}: adapter error: {e}"))

    # --- policy wiring ----------------------------------------------------------
    st = policy.status()
    if not st.get("policy-file"):
        out.append(_check("FIX", "policy:file", f"{policy.POLICY} missing", "teyla policy init && teyla policy sync"))
    else:
        out.append(_check("OK", "policy:file", str(policy.POLICY)))
    for k, v in st.items():
        if k == "policy-file":
            continue
        if v is None:
            out.append(_check("INFO", f"policy:{k}", "harness not installed"))
        elif v:
            out.append(_check("OK", f"policy:{k}", "wired"))
        else:
            out.append(_check("FIX", f"policy:{k}", "not wired", "teyla policy sync"))
    if policy.POLICY.exists():
        if policy.CONFLICT_PATH.exists():
            out.append(_check("FIX", "policy:template", f"merge conflict waiting in {policy.CONFLICT_PATH}",
                              f"resolve, copy into {policy.POLICY}, then: teyla policy refresh --resolved"))
        elif not policy.BASE_PATH.exists():
            out.append(_check("FIX", "policy:template", "no template base recorded; future template changes cannot be merged",
                              "teyla policy refresh"))
        else:
            try:
                drift = policy.BASE_PATH.read_text() != policy.render_template(policy._owner_from(policy.POLICY.read_text()))
            except OSError:
                drift = False
            if drift:
                out.append(_check("FIX", "policy:template", "the shipped template changed since it was last merged", "teyla policy refresh"))
            else:
                out.append(_check("OK", "policy:template", "base matches the shipped template"))
        ack = policy.ACK_PATH
        if policy.CLAUDE_GLOBAL.exists():
            import hashlib
            cur = hashlib.sha256(policy.CLAUDE_GLOBAL.read_bytes()).hexdigest()
            try:
                rec_ack = json.loads(ack.read_text())["claude_md"]["sha256"] if ack.exists() else None
            except (OSError, ValueError, KeyError):
                rec_ack = None
            if rec_ack is None:
                out.append(_check("INFO", "policy:ack", f"{policy.CLAUDE_GLOBAL} never acknowledged", "teyla policy ack"))
            elif rec_ack != cur:
                out.append(_check("WARN", "policy:ack", f"{policy.CLAUDE_GLOBAL} changed since it was acknowledged (advice A10 will fire)",
                                  "teyla policy ack   (if you made or accepted the edit)"))
            else:
                out.append(_check("OK", "policy:ack", "global CLAUDE.md matches its acknowledgement"))

    # --- Claude Code plugin ----------------------------------------------------
    claude_home = pathlib.Path.home() / ".claude"
    claude_present = shutil.which("claude") or (claude_home / "projects").is_dir() or (claude_home / "plugins").is_dir()
    if claude_present:
        pv = plugin_install.installed_version()
        if pv is None:
            out.append(_check("FIX", "plugin", "teyla plugin not installed in Claude Code",
                              "teyla plugin install zaitsew/teyla   (or: claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla)"))
        elif pv != __version__:
            out.append(_check("FIX", "plugin", f"installed copy is {pv}, CLI is {__version__}", "teyla plugin refresh"))
        else:
            out.append(_check("OK", "plugin", f"teyla@{pv} in Claude Code"))
    else:
        out.append(_check("INFO", "plugin", "Claude Code absent (no `claude`, no ~/.claude/projects or plugins)"))

    # --- routines ----------------------------------------------------------------
    if sys.platform == "darwin":
        for label, plist, wrapper in ((routine_install.DAILY_LABEL, routine_install.DAILY_PLIST_PATH, routine_install.DAILY_WRAPPER_PATH),
                                      (routine_install.LABEL, routine_install.PLIST_PATH, routine_install.WRAPPER_PATH)):
            ok, pid, code = routine_install.loaded(label)
            stale = routine_install._wrapper_stale(wrapper, routine_install._teyla_bin(),
                                                   routine_install.launchd_env(routine_install._teyla_bin()))
            if not plist.exists():
                out.append(_check("FIX", f"routine:{label.rsplit('.', 1)[-1]}", "not installed", "teyla routine install"))
            elif stale:
                out.append(_check("FIX", f"routine:{label.rsplit('.', 1)[-1]}", f"{wrapper.name} names a teyla binary that is not the current one, or lacks the [env] in config.toml", "teyla routine install"))
            elif not ok:
                out.append(_check("FIX", f"routine:{label.rsplit('.', 1)[-1]}", "plist exists but launchd has not loaded it", "teyla routine install"))
            else:
                out.append(_check("OK", f"routine:{label.rsplit('.', 1)[-1]}", f"loaded" + (f", last exit {code}" if code not in (None, "0") else "")))
    else:
        out.append(_check("INFO", "routine", "not macOS: schedule ~/.teyla/daily.sh and weekly.sh with cron"))

    # --- control plane -----------------------------------------------------------
    key = config.TEYLA_DIR / "hmac.key"
    if key.exists():
        mode = stat.S_IMODE(key.stat().st_mode)
        if mode & 0o077:
            out.append(_check("FIX", "control:hmac", f"{key} mode {oct(mode)} is group/world readable", f"chmod 600 {key}"))
        else:
            out.append(_check("OK", "control:hmac", "signing key present, mode 600"))
    else:
        out.append(_check("INFO", "control:hmac", "no signing key yet (created on first `teyla run`)"))
    kill = config.TEYLA_DIR / "kill"
    if kill.exists():
        out.append(_check("WARN", "control:kill", "kill switch is ON — no routine acts", "teyla kill off"))
    inbox = config.TEYLA_DIR / "inbox"
    if inbox.is_dir():
        pending = [p for p in inbox.iterdir() if p.suffix == ".json"]
        if pending:
            out.append(_check("WARN", "control:inbox", f"{len(pending)} run(s) waiting for you", "teyla inbox"))

    # --- tools on this machine (scope, not failures) ----------------------------
    present = [t for t in ("uv", "pipx", "git", "gh", "claude", "codex", "grok", "hermes", "launchctl") if shutil.which(t)]
    absent = [t for t in ("uv", "git", "gh", "claude", "codex", "grok") if not shutil.which(t)]
    out.append(_check("INFO", "tools", f"present: {', '.join(present) or '-'}; absent: {', '.join(absent) or '-'}"))
    if not shutil.which("codex") and not shutil.which("grok"):
        out.append(_check("INFO", "tools:second-opinion", "no second-provider CLI: policy §2 falls back to a fresh same-provider session"))

    # --- reminders ---------------------------------------------------------------
    from . import remind
    for row in remind.due_checks():
        out.append(_check(row["level"], f"remind:{row['name']}", row["detail"], row["fix"]))

    # --- repos under code_root ----------------------------------------------------
    if scan_repos:
        root = config.code_root(cfg)
        rs = policy.repos_status(root)
        missing = [n for s_, n in rs if s_ == "missing"]
        differ = [n for s_, n in rs if s_ == "differ"]
        if not rs:
            out.append(_check("INFO", "repos", f"no git repos under {root}"))
        else:
            if missing:
                out.append(_check("WARN", "repos:agents-md", f"{len(missing)} repo(s) have only one of AGENTS.md/CLAUDE.md: {', '.join(missing[:8])}",
                                  "teyla policy sync-repo " + " ".join(str(root / n) for n in missing[:8])))
            if differ:
                out.append(_check("WARN", "repos:agents-md", f"{len(differ)} repo(s) have AGENTS.md and CLAUDE.md that differ: {', '.join(differ[:8])}",
                                  "merge by hand, or teyla policy sync-repo <path> --prefer agents|claude"))
            if not missing and not differ:
                out.append(_check("OK", "repos:agents-md", f"{len(rs)} repo(s) under {root}: AGENTS.md ⇄ CLAUDE.md consistent"))
    return out


def summary_line(cs: list[dict]) -> str:
    n = {lvl: sum(1 for c in cs if c["level"] == lvl) for lvl in ("FIX", "WARN")}
    parts = []
    if n["FIX"]:
        parts.append(f"{n['FIX']} fix(es)")
    if n["WARN"]:
        parts.append(f"{n['WARN']} warning(s)")
    ver = next((c for c in cs if c["name"] == "version"), None)
    if ver and ver["level"] == "FIX":
        parts.append("update available")
    return ("teyla: " + ", ".join(parts) + " — run `teyla doctor`") if parts else ""


def write_state(cs: list[dict]) -> None:
    try:
        config.TEYLA_DIR.mkdir(parents=True, exist_ok=True)
        DOCTOR_JSON.write_text(json.dumps({"version": __version__, "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                                           "checks": cs}, indent=2) + "\n")
        DOCTOR_SUMMARY.write_text(summary_line(cs) + "\n")
    except OSError:
        pass


def render(cs: list[dict], quiet: bool = False) -> str:
    lines = [f"teyla {__version__}"]
    for c in cs:
        if quiet and c["level"] in ("OK", "INFO"):
            continue
        lines.append(f"{c['level']:4} {c['name']:22} {c['detail']}")
        if c["fix"] and c["level"] != "OK":
            lines.append(f"{'':4} {'':22} → {c['fix']}")
    s = summary_line(cs)
    lines.append(s or "all clear")
    return "\n".join(lines)


def cmd_doctor(args):
    cs = checks(refresh_update=getattr(args, "refresh", False), scan_repos=not getattr(args, "no_repos", False))
    write_state(cs)
    if getattr(args, "json", False):
        print(json.dumps(cs, indent=2))
    else:
        print(render(cs, quiet=getattr(args, "quiet", False)))
    return 1 if any(c["level"] == "FIX" for c in cs) else 0


def register(sp):
    q = sp.add_parser("doctor", help="what must be true for Teyla to work here, with the fix for each thing that is not")
    q.set_defaults(fn=cmd_doctor)
    q.add_argument("--quiet", action="store_true", help="only WARN/FIX lines")
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh", action="store_true", help="ask GitHub for the latest release now instead of using the daily cache")
    q.add_argument("--no-repos", action="store_true", help="skip scanning code_root for AGENTS.md/CLAUDE.md")
