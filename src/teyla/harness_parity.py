"""`teyla harness parity` — one table, capability x harness (Claude Code, Codex), with the one command
or click that fixes each gap. The tests of the code (`tests/test_hook_parity_codex.py`) prove both harnesses
are *wired* to run the same hooks; this module checks the machine: is each hook in ~/.codex/hooks.json,
has the person trusted it in Codex (a hook nobody trusted is skipped without a word), is
~/.codex/AGENTS.md current, are the skills there.

The expected Codex hooks come from `harness._codex_hooks`, the function `teyla harness sync` writes
them with; nothing here lists a hook by hand. Trust is read the way `harness._codex_trust` reads it:
`[hooks.state."<hooks.json path>:<event label>:<group>:<handler>"]` in ~/.codex/config.toml holds
`trusted_hash`, compared with `harness.codex_hook_hash`. When config.toml cannot be parsed the state is
"unknown", never a guess.
"""
from __future__ import annotations

import json
import pathlib

from . import harness as H

OK, NO, TRUST, NA = "ok", "missing", "needs trust", "n/a"

# Plain words per state for the table; `fix` per state lives in `_fix`.
SYMBOL = {"ok": "✓", "missing": "✗ missing", "needs trust": "needs trust", "modified": "✗ modified since trusted",
          "disabled": "✗ disabled", "outdated": "✗ outdated", "unknown": "? trust unknown", "n/a": "n/a",
          "off": "off (opt-in)", "no plugin": "✗ no plugin", "stale": "✗ stale", "absent": "n/a"}

TRUST_FIX = "open Codex → \"Hooks need review\" → Trust all (or /hooks)"
UNKNOWN_FIX = "trust unknown — open Codex once and approve \"Hooks need review\""


def _claude_plugin_hooks() -> list[tuple[str, str]]:
    """(event, script) the Claude Code plugin runs, from plugin/hooks/hooks.json."""
    from . import plugin_dir
    try:
        d = json.loads((plugin_dir() / "hooks" / "hooks.json").read_text())["hooks"]
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for event, groups in d.items():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = str(h.get("command", "")).split("hooks/", 1)[-1].split(" ")[0].strip('"')
                out.append((event, H._script_of(cmd)))
    return out


def _codex_state_table(h: H.Harness):
    """({(label, gi, hi): trust record} or None when config.toml is unreadable)."""
    import tomllib
    try:
        text = (h.home / "config.toml").read_text()
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        return (tomllib.loads(text).get("hooks") or {}).get("state") or {}
    except ValueError:
        return None


def codex_hooks(h: H.Harness, land_check: bool | None = None) -> list[dict]:
    """One row per hook Teyla expects in Codex: {event, script, state}. State is ok, missing, outdated
    (present but not what sync writes), needs trust, modified, disabled or unknown."""
    want = H._codex_hooks(None, land_check=land_check)["hooks"]
    try:
        have = (json.loads(h.hooks_path.read_text()).get("hooks") or {})
    except (OSError, ValueError, AttributeError):
        have = {}
    state = _codex_state_table(h)
    rows = []
    for event, groups in want.items():
        for wg in groups:
            for wh in wg["hooks"]:
                script = H._script_of(wh["command"])
                found = None
                for gi, g in enumerate(have.get(event) or []):
                    for hi, hh in enumerate(g.get("hooks") or []):
                        if H._is_teyla_handler(hh) and H._script_of(hh["command"]) == script:
                            found = (gi, hi, g, hh)
                            break
                    if found:
                        break
                if not found:
                    rows.append(dict(event=event, script=script, state="missing"))
                    continue
                gi, hi, g, hh = found
                if hh != wh or g.get("matcher") != wg.get("matcher"):
                    rows.append(dict(event=event, script=script, state="outdated"))
                    continue
                if state is None:
                    rows.append(dict(event=event, script=script, state="unknown"))
                    continue
                rec = state.get(f"{h.hooks_path}:{H._CODEX_EVENT_LABELS[event]}:{gi}:{hi}") or {}
                if rec.get("enabled") is False:
                    st = "disabled"
                elif rec.get("trusted_hash") == H.codex_hook_hash(event, hh, g.get("matcher")):
                    st = "ok"
                elif rec.get("trusted_hash"):
                    st = "modified"
                else:
                    st = "needs trust"
                rows.append(dict(event=event, script=script, state=st))
    return rows


def _skills(h: H.Harness) -> tuple[list[str], list[str]]:
    """(present, missing-or-stale) plugin skill names in the harness's skills dir."""
    ok, bad = [], []
    for src, name in zip(H.PLUGIN_SKILLS, H.skill_names()):
        p = H._skill_path(h, name)
        try:
            good = p.read_text() == H.render_skill(src, h.name)
        except OSError:
            good = False
        (ok if good else bad).append(name)
    return ok, bad


def table(home: pathlib.Path | None = None) -> dict:
    """{rows: [{capability, claude-code, codex, fix}], harnesses: {...present}}. A harness that is not
    installed has "absent" in every cell."""
    from . import plugin_install, policy
    home = home or H.HOME
    codex = H.harnesses(home)["codex"]
    claude_present = (home / ".claude").is_dir()
    codex_present = codex.present()
    land = H._land_check_on()
    rows = []

    def add(cap, claude, cdx, fix=None):
        rows.append({"capability": cap, "claude-code": claude, "codex": cdx, "fix": fix})

    # --- plugin / hook scripts ------------------------------------------------------------
    pv = plugin_install.installed_version(plugins_dir=home / ".claude" / "plugins") if claude_present else None
    claude_hooks = _claude_plugin_hooks()
    cs = {s for _, s in claude_hooks}
    add("plugin", "absent" if not claude_present else ("ok" if pv else "no plugin"),
        "absent" if not codex_present else "n/a",
        "claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla" if claude_present and not pv else None)
    scripts_ok = all((H.HOOKS_DIR / s).exists() for s in H.HOOK_SCRIPTS) if home == H.HOME else None
    add("hook scripts in ~/.teyla/hooks", "n/a", "absent" if not codex_present else
        ("ok" if scripts_ok else "missing" if scripts_ok is False else "unknown"),
        "teyla harness sync" if codex_present and scripts_ok is False else None)

    # --- one row per hook -----------------------------------------------------------------
    cx = {}
    if codex_present:
        for r in codex_hooks(codex, land_check=land):
            cx.setdefault(r["script"], []).append(r)
    expected_cx = {r["script"] for r in (codex_hooks(codex, land_check=land) if codex_present else
                                         [dict(script=H._script_of(h["command"])) for g in
                                          H._codex_hooks(None, land_check=land)["hooks"].values()
                                          for gg in g for h in gg["hooks"]])}
    opt_in = {"land-check.sh": land, "context-budget.sh": config_on("context_budget")}
    for script in sorted(cs | expected_cx):
        events = sorted({e for e, s in claude_hooks if s == script} | {r["event"] for r in cx.get(script, [])})
        cap = f"hook {script} ({', '.join(events)})" if events else f"hook {script}"
        if not claude_present:
            c = "absent"
        elif script not in cs:
            c = "n/a"
        elif not pv:
            c = "no plugin"
        elif script in opt_in and not opt_in[script]:
            c = "off"
        else:
            c = "ok"
        fix = None
        if not codex_present:
            x = "absent"
        elif script in cx:
            states = {r["state"] for r in cx[script]}
            for s in ("missing", "outdated", "disabled", "modified", "unknown", "needs trust"):
                if s in states:
                    x = s
                    break
            else:
                x = "ok"
            fix = {"missing": "teyla harness sync", "outdated": "teyla harness sync", "disabled": "/hooks in Codex: enable it",
                   "modified": TRUST_FIX, "needs trust": TRUST_FIX, "unknown": UNKNOWN_FIX}.get(x)
        elif script in opt_in and not opt_in[script]:
            x = "off"
        else:
            x = "n/a"  # a Claude hook with no Codex row: tests/test_hook_parity_codex.py names why
        add(cap, c, x, fix)

    # --- skills, policy -------------------------------------------------------------------
    ok, bad = _skills(codex) if codex_present else ([], [])
    add(f"skills ({len(H.PLUGIN_SKILLS)} plugin skills)", "absent" if not claude_present else ("ok" if pv else "no plugin"),
        "absent" if not codex_present else ("ok" if not bad else "missing"),
        "teyla harness sync" if bad else None)
    drift = policy.drift("codex") if codex_present else None
    claude_policy = (home / ".claude" / "CLAUDE.md").exists() if claude_present else None
    add("policy text (POLICY.md + owner rules)",
        "absent" if not claude_present else ("ok" if claude_policy else "missing"),
        "absent" if not codex_present else ("stale" if drift else "ok"),
        drift[1] if drift else None)
    return dict(rows=rows, skills_missing=bad, claude_present=claude_present, codex_present=codex_present,
                drift=drift[0] if drift else None)


def config_on(name: str) -> bool:
    from . import config
    try:
        return config.hook_on(name)
    except Exception:  # noqa: BLE001
        return False


def gaps(t: dict) -> list[dict]:
    """Rows with a fix: the ✗ and needs-trust cells."""
    return [r for r in t["rows"] if r["fix"]]


def render(t: dict) -> str:
    rows = t["rows"]
    w = max(len(r["capability"]) for r in rows)
    lines = [f"{'capability':{w}}  {'claude-code':16}  codex"]
    for r in rows:
        lines.append(f"{r['capability']:{w}}  {SYMBOL[r['claude-code']]:16}  {SYMBOL[r['codex']]}")
    g = gaps(t)
    if g:
        lines += ["", "to fix:"]
        seen = set()
        for r in g:
            key = r["fix"]
            lines.append(f"  {r['capability']}: {key}" if key not in seen else f"  {r['capability']}: same as above")
            seen.add(key)
    else:
        lines += ["", "parity: every capability present in every installed harness, every Codex hook trusted"]
    return "\n".join(lines)
