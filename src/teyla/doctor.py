"""`teyla doctor` — everything that has to be true for Teyla to work on this machine
without anyone remembering to run something.

Each check is (level, name, detail, fix): level is OK, INFO, WARN or FIX. FIX means a
command exists that repairs it and doctor names it. Absent harnesses and absent CLIs are
INFO, never failures: the work laptop has Claude Code only and no `gh`, and that is a
different tool scope, not a broken install.

Writes ~/.teyla/doctor.json (full), ~/.teyla/doctor.summary (one line, kept for hooks
installed before the banner existed) and ~/.teyla/banner.items, from which the session-start
hook shows only what is new since the last session (teyla.digest) without running Python.
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
import time

from . import __version__, config

DOCTOR_JSON = config.TEYLA_DIR / "doctor.json"
DOCTOR_SUMMARY = config.TEYLA_DIR / "doctor.summary"


def _check(level, name, detail, fix=None, **extra):
    return {"level": level, "name": name, "detail": detail, "fix": fix, **extra}


def checks(refresh_update: bool = False, scan_repos: bool = True) -> list[dict]:
    from . import policy, update, routine_install, plugin_install
    from .adapters import claude_code, codex, grok, hermes, cursor
    cfg = config.load()
    out = []
    safe = config.safe_mode(cfg)

    # --- safe mode: first, because it changes what every line below means --------
    out.append(_check("INFO", "safe", config.SAFE_SUMMARY if safe else "off"))
    cfg_err = config.parse_error()
    bad_safe = config.safe_setting_invalid(cfg)
    if cfg_err:
        out.append(_check("FIX", "safe:setting", f"{config.CONFIG_PATH} does not parse ({cfg_err}) — safe mode forced ON, "
                          "every other setting ignored", "fix the file by hand, then: teyla config show"))
    elif bad_safe is not None:
        out.append(_check("FIX", "safe:setting", f"[safe] enabled = {bad_safe!r} is not true or false — treated as ON",
                          "teyla config set safe.enabled=true   (or =false)"))

    # --- version ---------------------------------------------------------------
    rec = update.check(refresh=refresh_update, max_age_hours=24)
    method = rec.get("method")
    when = rec.get("checked", "")[:16]
    how = f"cached {when}, not retried" if rec.get("from_cache") else f"checked {when}"
    channel, upin = update.update_settings(cfg)
    if upin or channel != "release":
        bad = channel not in ("release", "none")
        out.append(_check("FIX" if bad else "INFO", "update",
                          f"channel {channel}" + (" (unknown: release or none)" if bad else "")
                          + (f", pinned to {upin}" if upin else "")
                          + (" — the daily routine never updates" if channel == "none" else ""),
                          "teyla config set update.channel=release" if bad else
                          ("teyla config set update.pin=   (unpins)" if upin else None)))
    if safe:
        # Doctor never passes --allow-network: it runs from the hook and the daily routine.
        known = f"; {rec['latest']} was the latest at {when}" if rec.get("latest") else ""
        out.append(_check("FIX" if rec.get("newer") else "INFO", "version",
                          f"{__version__} ({method}); update checks off in safe mode{known}",
                          "teyla update --allow-network   (when you choose to)"))
    elif upin and rec.get("sha") and not rec.get("latest"):
        state = "not installed yet" if rec.get("newer") else "installed"
        out.append(_check("FIX" if rec.get("newer") else "OK", "version",
                          f"{__version__} ({method}); pinned commit {rec['sha'][:12]} {state}; {how}",
                          "teyla update" if rec.get("newer") else None))
    elif rec.get("latest") is None:
        out.append(_check("WARN", "version", f"{__version__} ({method}); latest unknown — see network ({how})"))
    elif rec.get("newer"):
        out.append(_check("FIX", "version", f"{__version__} installed, {rec['latest']} "
                          + ("pinned" if upin else "available") + f" ({method})", "teyla update"))
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
    # truststore reads the OS keychain, where MDM puts the proxy's root CA; without it (and
    # without SSL_CERT_FILE) Python 3.13 behind a TLS-intercepting proxy fails every HTTPS call.
    tls_fix = update.WORK_EXTRA_HINT if (proxy and not update.truststore_available()
                                          and not update._explicit_bundle()) else None
    if safe:
        out.append(_check("INFO", "network", f"not probed (safe mode) — {facts}", tls_fix))
    elif rec.get("latest") is not None or rec.get("sha"):
        out.append(_check("OK", "network", f"github.com reachable for {repo} — {facts}"))
    elif rec.get("reachable"):
        out.append(_check("WARN", "network", f"github.com reachable for {repo} but no published release found ({how}): {rec.get('note')} — {facts}"))
    else:
        hint = update.explain_tls_error(rec.get("note"))
        out.append(_check("FIX", "network", f"github.com UNREACHABLE for {repo} ({how}): {rec.get('note')} — {facts}",
                          hint or tls_fix or "check the proxy/VPN, then: teyla update --check   (retries now)"))
    if pin != py_running:
        out.append(_check("WARN", "network:python", f"running on python {py_running} but `[update] python` pins {pin}: the next update moves the install",
                          f"teyla config set update.python={py_running}   (or teyla update --force to move now)"))

    # --- config --------------------------------------------------------------
    if config.CONFIG_PATH.exists():
        out.append(_check("OK", "config", f"{config.CONFIG_PATH}: code_root={cfg['code_root']} ops_root={cfg['ops_root']} runs_root={config.runs_root(cfg)} repo={cfg['update']['repo']}"))
    else:
        out.append(_check("INFO", "config", f"no {config.CONFIG_PATH}; defaults code_root={cfg['code_root']} ops_root={cfg['ops_root']} runs_root={config.runs_root(cfg)}",
                          "teyla policy init  (writes it)"))

    # --- harnesses this machine does not use (`[harness] disabled`) ----------------
    off, unknown_off = config.disabled_harnesses(cfg)
    if off:
        out.append(_check("INFO", "harness:disabled", f"disabled: {', '.join(off)}"))
    if unknown_off:
        out.append(_check("WARN", "harness:disabled-unknown",
                          f"[harness] disabled names {', '.join(unknown_off)}, which "
                          f"{'is' if len(unknown_off) == 1 else 'are'} not a harness Teyla knows "
                          f"({', '.join(config.HARNESS_NAMES)})",
                          "teyla config set harness.disabled=" + ",".join(off)))

    # --- harness stores --------------------------------------------------------
    loaded = {}
    for mod in (claude_code, codex, grok, hermes, cursor):
        if mod.NAME in off:
            continue
        root = getattr(mod, "DEFAULT_ROOT", None)
        ok = bool(root) and os.path.exists(os.path.expanduser(root))
        if not ok:
            out.append(_check("INFO", f"harness:{mod.NAME}", "absent on this machine"))
            continue
        try:
            # The last week only: parsing every transcript ever written cost 30 s here, and
            # "used this week" is the fact a reader of this line wants.
            since = time.time() - 7 * 86400
            cutoff = _dt.datetime.fromtimestamp(since, _dt.timezone.utc).isoformat()
            # Adapters that cannot skip files by date still return everything; count by `last`.
            recent = [x for x in mod.load(since=since) if (x.last or x.first or "") >= cutoff[:19]]
            loaded[mod.NAME] = recent
            nb = sum(1 for x in recent if x.batch)
            out.append(_check("OK", f"harness:{mod.NAME}", f"{root}: {len(recent)} session(s) in the last 7 days"
                              + (f" ({len(recent) - nb} interactive, {nb} batch)" if recent else "")))
        except Exception as e:  # noqa: BLE001
            out.append(_check("WARN", f"harness:{mod.NAME}", f"{root}: adapter error: {e}"))

    # --- can each harness do work right now? -------------------------------------
    # "wired" is not "working": a Grok that answers 402 on every call, or a Hermes that
    # has lost its token, still shows OK in the lines above. Version, auth, the newest quota/auth error
    # the harness itself recorded, and its batch volume (health.py).
    from . import health
    try:
        out += health.doctor_checks(loaded)
    except Exception as e:  # noqa: BLE001 — never take doctor down
        out.append(_check("WARN", "health", f"harness health check failed: {e}"))

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
            # codex/grok carry a generated copy of CLAUDE.md, so "not wired" is usually "a day
            # behind ~/.claude/CLAUDE.md" — say which, and what to run.
            why = policy.drift(k) if k in ("codex", "grok") else None
            out.append(_check("FIX", f"policy:{k}", f"not wired: {why[0]}" if why else "not wired",
                              why[1] if why else "teyla policy sync"))
    if policy.POLICY.exists():
        if policy.CONFLICT_PATH.exists():
            out.append(_check("FIX", "policy:template", f"merge conflict waiting in {policy.CONFLICT_PATH}",
                              f"resolve, copy into {policy.POLICY}, then: teyla policy refresh --resolved"))
        elif policy.PROPOSED_PATH.exists():
            out.append(_check("FIX", "policy:template", f"a template change is proposed in {policy.PROPOSED_PATH} "
                              "(safe mode merges nothing into POLICY.md by itself)", policy.proposal_commands()))
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

    # Edits made inside a generated copy (a rule added to ~/.codex/AGENTS.md from within Codex) that
    # `policy sync` found and filed before it overwrote the copy: the person decides where they live.
    edits = policy.pending_edits()
    if edits:
        c = _check("WARN", "policy:inbox",
                   f"{len(edits)} hand edit{'s' if len(edits) != 1 else ''} to generated policy files "
                   f"wait{'s' if len(edits) == 1 else ''} for review", "teyla policy inbox")
        c["n"] = len(edits)
        out.append(c)

    # --- Claude Code plugin ----------------------------------------------------
    claude_home = pathlib.Path.home() / ".claude"
    claude_present = shutil.which("claude") or (claude_home / "projects").is_dir() or (claude_home / "plugins").is_dir()
    if "claude-code" in off:
        pass
    elif claude_present:
        pv = plugin_install.installed_version()
        pref = plugin_install.pin_ref(cfg) if safe else None   # `v<pin>`: hooks pinned like the CLI
        add = (f"claude plugin marketplace add {plugin_install.pinned_source(pref)}" if pref
               else "claude plugin marketplace add zaitsew/teyla")
        if pv is None:
            out.append(_check("FIX", "plugin", "teyla plugin not installed in Claude Code",
                              f"{add} && claude plugin install teyla@teyla" if safe else
                              "teyla plugin install zaitsew/teyla   (or: claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla)"))
        elif pv != __version__:
            out.append(_check("FIX", "plugin", f"installed copy is {pv}, CLI is {__version__}",
                              (plugin_install.repin_command(pref) if pref else
                               "claude plugin marketplace update teyla && claude plugin update teyla@teyla") if safe else "teyla plugin refresh"))
        else:
            out.append(_check("OK", "plugin", f"teyla@{pv} in Claude Code"))
        if safe:
            found, ref, kind = plugin_install.marketplace_ref()
            follows = ref or ("main" if kind in ("github", "git") else f"a {kind} source, not a tag")
            if pref and found and ref != pref:
                out.append(_check("WARN", "plugin:pin", f"the plugin's hooks follow {follows}, not {pref} (update.pin): "
                                  "they can be newer than the pinned CLI", plugin_install.repin_command(pref)))
            elif plugin_install.pin_is_sha(cfg) and found:
                out.append(_check("WARN", "plugin:pin", f"update.pin is a commit sha; Claude Code pins a marketplace to a tag, "
                                  f"not a commit, so the plugin's hooks follow {follows}",
                                  "teyla config set update.pin=<release version>   (then re-pin the plugin)"))
    else:
        out.append(_check("INFO", "plugin", "Claude Code absent (no `claude`, no ~/.claude/projects or plugins)"))

    # --- opt-in plugin hooks (`[hooks]` in config.toml) ---------------------------------
    out += hook_checks(cfg)

    # --- the other harnesses: skills + hooks ------------------------------------------
    from . import harness as _harness
    for row in _harness.status():
        if not row["present"]:
            continue
        missing = []
        if row["skills"] != row["skills_total"]:
            missing.append(f"skills {row['skills']}/{row['skills_total']}")
        if row["hooks"] is False:
            missing.append("hooks not wired")
        if missing:
            out.append(_check("FIX", f"harness:{row['harness']}", ", ".join(missing), "teyla harness sync"))
        elif (tr := row.get("trust")) and tr["approved"] < tr["total"]:
            # Wired but never approved: the harness skips the hook silently (Codex's trust
            # review, Hermes's first-use consent), so "wired" alone would be a false OK.
            out.append(_check("WARN", f"harness:{row['harness']}",
                              f"skills {row['skills']}/{row['skills_total']}, hooks wired but not approved "
                              f"({tr['approved']}/{tr['total']}: {', '.join(tr['missing'])}) — they do not run",
                              _harness.TRUST_HOWTO.get(row["harness"])))
        else:
            out.append(_check("OK", f"harness:{row['harness']}", f"skills {row['skills']}/{row['skills_total']}"
                              + (", hooks wired" if row["hooks"] else ", no hook mechanism")
                              + (", approved" if row.get("trust") else "")))

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
                out.append(_check("FIX", f"routine:{label.rsplit('.', 1)[-1]}", f"{wrapper.name} names a teyla binary that is not the current one, lacks the [env] in config.toml, does not match safe mode or ops_root, or predates a step this release adds", "teyla routine install"))
            elif not ok:
                out.append(_check("FIX", f"routine:{label.rsplit('.', 1)[-1]}", "plist exists but launchd has not loaded it", "teyla routine install"))
            elif routine_install.missed(label):
                due = routine_install.missed(label)
                out.append(_check("WARN", f"routine:{label.rsplit('.', 1)[-1]}",
                                  f"loaded, but the run due {due:%Y-%m-%d %H:%M} did not start (the Mac was off or asleep at that minute; launchd does not fire late)",
                                  "teyla routine catch-up"))
            else:
                started = routine_install.last_started(label)
                out.append(_check("OK", f"routine:{label.rsplit('.', 1)[-1]}", f"loaded" + (f", last exit {code}" if code not in (None, "0") else "")
                                  + (f", last started {started:%Y-%m-%d %H:%M}" if started else ", not yet due")))
        for row in routine_install.optional_checks():
            out.append(_check(*row))
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
    if safe:
        from .control import triggers as _triggers
        for plist in _triggers.installed_plists():
            label = plist.stem
            out.append(_check("FIX", "control:trigger", f"{plist.name} runs `teyla run` unattended; safe mode refuses it",
                              f"launchctl bootout gui/{os.getuid()}/{label}; rm {plist}"))
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

    # --- storage: free space, and worktrees agents finished with ---------------------
    if scan_repos:
        from . import storage
        for row in storage.doctor_checks(cfg):
            out.append(_check(row["level"], row["name"], row["detail"], row["fix"], **({"free": row["free"]} if "free" in row else {})))

    # --- policy detectors: the rules in POLICY.md that files can prove broken --------------
    from . import detect
    for row in detect.doctor_checks(cfg, scan_repos=scan_repos):
        out.append(_check(row["level"], row["name"], row["detail"], row["fix"]))

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
            # Per file, not per repo: each instruction file loads whole (rules_lifecycle.budget).
            from . import rules_lifecycle
            b = rules_lifecycle.doctor_check(root)
            if b:
                out.append(_check(b["level"], b["name"], b["detail"], b["fix"]))
            # INFO, not WARN: an unprepared repo is a fact about where cloud work can finish, not
            # a broken install — and a WARN here would sit in every session-start line for weeks.
            try:
                from . import cloud
                c = cloud.doctor_check(cfg)
                out.append(_check(c["level"], c["name"], c["detail"], c["fix"]))
            except Exception as e:  # noqa: BLE001 — a readiness line must never take doctor down
                out.append(_check("INFO", "cloud", f"readiness not computed: {e}"))
    return out


def hook_checks(cfg: dict) -> list[dict]:
    """One INFO line per opt-in hook that is on; nothing for one that is off (the default). Context budget without
    `autoCompactWindow` in ~/.claude/settings.json is a WARN: the hook asks for the handoff at
    240k, but Claude Code then compacts only near the model's full window, so the session keeps
    paying for the re-read it was meant to stop. So is a first threshold at or past the point the
    window compacts at (window − 35k): the handoff would be asked for after the compaction it is
    meant to survive. Doctor names the fix; it never writes settings.json, which belongs to Claude
    Code and to the person."""
    out = []
    hooks = cfg.get("hooks") or {}
    if config.hook_on("context_budget", cfg):
        def num(key, default):
            try:
                return int(hooks.get(key, default))
            except (TypeError, ValueError):
                return default
        d = config.DEFAULTS["hooks"]
        first, step = num("context_budget_first", d["context_budget_first"]), num("context_budget_step", d["context_budget_step"])
        out.append(_check("INFO", "hooks:context-budget", f"on: a handoff at {first // 1000}k tokens of context, again every "
                          f"{step // 1000}k, into ~/.teyla/handoff/; put back after Claude Code compacts"))
        settings = config.HOME / ".claude" / "settings.json"
        try:
            data = json.loads(settings.read_text())
            why = None if isinstance(data, dict) and "autoCompactWindow" in data else "has no autoCompactWindow"
        except FileNotFoundError:
            why = "does not exist, so has no autoCompactWindow"
        except (OSError, ValueError) as e:
            why = f"cannot be read ({e.__class__.__name__}), so autoCompactWindow is unknown"
        if why:
            out.append(_check("WARN", "hooks:autocompact",
                              f"{settings} {why}: Claude Code compacts only near the model's full window, so the "
                              "session keeps re-reading everything above the handoff threshold",
                              f'/config in Claude Code, or add "autoCompactWindow": {config.AUTOCOMPACT_RECOMMENDED} '
                              f"to {settings} (merge the key; keep the rest of the file)"))
        else:
            window, at, is_set = config.compaction()
            if is_set and first >= at:
                # 240k/30k under ~300k: two reminders before the compaction
                fit = max(at - 60000, at * 4 // 5)
                out.append(_check("WARN", "hooks:context-budget-late",
                                  f"the handoff is asked for at {first // 1000}k, but autoCompactWindow {window} "
                                  f"compacts at about {at // 1000}k: the compaction comes first and the handoff is lost",
                                  f"teyla config set hooks.context_budget_first={fit} "
                                  f"hooks.context_budget_step={max(1000, (at - fit) // 2)}"))
    if config.hook_on("land_check", cfg):
        out.append(_check("INFO", "hooks:land-check", "on: at Stop, once per session, uncommitted or unpushed work is named "
                          "with how to land it (merge only into a repo on the MERGE-APPROVED list in ~/.claude/CLAUDE.md)"))
    return out


def _problems(cs: list[dict]) -> list[str]:
    n = {lvl: sum(1 for c in cs if c["level"] == lvl) for lvl in ("FIX", "WARN")}
    parts = []
    if n["FIX"]:
        parts.append(f"{n['FIX']} fix(es)")
    if n["WARN"]:
        parts.append(f"{n['WARN']} warning(s)")
    ver = next((c for c in cs if c["name"] == "version"), None)
    if ver and ver["level"] == "FIX":
        parts.append("update available")
    inbox = next((c for c in cs if c["name"] == "policy:inbox"), None)
    if inbox:
        parts.append(f"{inbox.get('n', 1)} policy edit(s) to review")
    return parts


def disk_free(cs: list[dict]) -> str:
    """`disk 64 GB free` from the storage:disk row, or '' when doctor did not check the disk."""
    free = next((c.get("free") for c in cs if c["name"] == "storage:disk"), None)
    if not isinstance(free, (int, float)) or isinstance(free, bool):
        return ""
    gb = free / 1024 ** 3
    return f"disk {gb:.0f} GB free" if gb >= 10 else f"disk {gb:.1f} GB free"


def summary_line(cs: list[dict]) -> str:
    """The one line the session-start hook falls back to: what needs you, then the free disk
    space — shown even when everything is fine, so a filling disk is seen before it is an error."""
    parts, disk = _problems(cs), disk_free(cs)
    if parts:
        return "teyla: " + ", ".join(parts + ([disk] if disk else [])) + " — run `teyla doctor`"
    return f"teyla: {disk}" if disk else ""


def write_state(cs: list[dict]) -> None:
    try:
        config.write_private(DOCTOR_JSON, json.dumps({"version": __version__, "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                                                      "checks": cs}, indent=2) + "\n")
        config.write_private(DOCTOR_SUMMARY, summary_line(cs) + "\n")
    except OSError:
        pass
    # The session-start banner shows what is new since the last session, from this file.
    from . import digest
    digest.write_banner_items(cs)


def render(cs: list[dict], quiet: bool = False) -> str:
    lines = [f"teyla {__version__}"]
    for c in cs:
        if quiet and c["level"] in ("OK", "INFO"):
            continue
        lines.append(f"{c['level']:4} {c['name']:22} {c['detail']}")
        if c["fix"] and c["level"] != "OK":
            lines.append(f"{'':4} {'':22} → {c['fix']}")
    lines.append(summary_line(cs) if _problems(cs) else "all clear" + (f" ({disk_free(cs)})" if disk_free(cs) else ""))
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
