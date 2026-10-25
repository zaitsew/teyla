"""The offers `teyla start` makes: one change each, with a saving worked out from the user's own sessions.

Each offer names the exact change (file, key path, new value), what it saves per month with a low and a
high figure and the sentence that explains them, what it costs the user, and how to undo it. An offer
whose saving cannot be computed from the data says what it brings instead (`benefit`), never a made-up
figure. `applies` is False when the setting is already there or the harness is not installed.

  O1  autoCompactWindow 335000 in ~/.claude/settings.json
  O2  the default subagent model set to Sonnet (env CLAUDE_CODE_SUBAGENT_MODEL)
  O3  a read-only `scout` agent on Haiku
  O4  Codex reasoning effort high -> medium
  O5  one rules file synced to every harness      (`teyla policy sync`)
  O6  hooks that keep your prompts and questions  (`teyla harness sync`)
  O7  a daily routine                             (`teyla routine install`)

A 30-day window is a month as it is; any other window scales linearly to 30 days.

Savings are list-price dollars. Where a range is given, the high end is the full arithmetic and the low
end allows for what the arithmetic cannot see (its basis sentence says which).
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import sys
from collections import defaultdict

from . import changes, config, diagnose as diagnose_mod, pricing
from .adapters import CACHE_1H_KEY, HANDOFF_CONTEXT, local_day

# O1: a session compacts about AUTOCOMPACT_MARGIN under the window; after a compaction it resumes at HANDOFF_CONTEXT.
COMPACT_AT = config.AUTOCOMPACT_RECOMMENDED - config.AUTOCOMPACT_MARGIN
SUMMARY_OUT_TOKENS = 10_000        # what the compaction summary writes
O1_LOW_SHARE = 0.5                 # a session regrows after a compaction and some turns would cross again
# O2: Sonnet 5.5 can need more tokens than Opus for the same lane.
SUBAGENT_MODEL = "sonnet"
VOLUME_MODEL = "claude-sonnet-5-5"
O2_LOW_SHARE = 0.7
# O3: Haiku 5.5 is priced at its short-prompt rates; above this a prompt is on the dearer card (pricing.py).
SCOUT_MODEL = "claude-haiku-5-5"
HAIKU_SHORT_PROMPT = 100_000
O3_LOW_SHARE, O3_HIGH_SHARE = 0.3, 0.6   # the share of read-only calls that would go to the scout agent
# O4: Codex counts for the offer when it is at least this share of the spend, and this many dollars.
O4_MIN_SHARE, O4_MIN_USD = 0.10, 5.0
MONTH_DAYS = 30

SCOUT_AGENT = """---
name: scout
description: Read-only research agent. Use it for surveys, audits, inventories and "where is X" searches. It reads and reports; it never edits a file.
tools: Read, Grep, Glob, Bash
model: haiku
---

You are a scout. Find the answer by reading files and running read-only commands, and report what you
found with file paths and line numbers. Never edit, write, move or delete a file, and never run a command
that changes state. If the question needs a change, say what you would change and stop.
"""


@dataclasses.dataclass
class Offer:
    id: str
    title: str
    change: dict                      # kind, file, key_path, old, new, summary; piece offers name the piece
    saving_usd_month: dict | None     # {"low": x, "high": y} or None
    basis: str
    benefit: str | None
    tradeoff: str
    undo: str
    applies: bool
    reason: str = ""                  # why `applies` is False
    explain: str = ""                 # the longer text behind [e]xplain
    short: str = ""                   # what it brings, in a few words: the summary card shows it when there is no figure

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @property
    def high(self) -> float:
        return (self.saving_usd_month or {}).get("high", 0.0)

    @property
    def low(self) -> float:
        return (self.saving_usd_month or {}).get("low", 0.0)


SHORT = {
    "O1": "caps what a long session re-reads",
    "O2": "subagents stop inheriting Opus",
    "O3": "reading tasks run on Haiku",
    "O4": "fewer reasoning tokens on Codex",
    "O5": "one rules file for every harness",
    "O6": "keeps your corrections and open questions",
    "O7": "a daily check, run for you",
}


def _money(x: float) -> str:
    from .spend import _money as m
    return m(x)


def _tilde(p: pathlib.Path, home: pathlib.Path) -> str:
    try:
        return "~/" + str(p.relative_to(home))
    except ValueError:
        return str(p)


def _scale(days: int) -> float:
    return MONTH_DAYS / max(1, days)


def _range(net: float, low_share: float, days: int, high_share: float = 1.0) -> dict:
    s = _scale(days)
    return {"low": round(net * low_share * s, 2), "high": round(net * high_share * s, 2)}


# --- the files offers read ---------------------------------------------------------------------

def claude_settings(home: pathlib.Path) -> dict | None:
    """~/.claude/settings.json as a dict; {} when absent; None when it does not parse."""
    p = home / ".claude" / "settings.json"
    try:
        raw = p.read_text()
    except OSError:
        return {}
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def codex_config_text(home: pathlib.Path) -> str | None:
    try:
        return (home / ".codex" / "config.toml").read_text()
    except OSError:
        return None


def agent_model(home: pathlib.Path, agent_type: str) -> str | None:
    """The `model:` in ~/.claude/agents/<type>.md's front matter, or None."""
    try:
        text = (home / ".claude" / "agents" / f"{agent_type}.md").read_text()
    except OSError:
        return None
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    mm = re.search(r"^model:\s*(\S+)", m.group(1), re.M)
    return mm.group(1) if mm else None


# --- the savings -------------------------------------------------------------------------------

def _rate(model: str, i: int) -> float:
    p = pricing.lookup(model)
    return p[i] if p else 0.0


def compaction_cost(model: str) -> float:
    """What one compaction costs: the summary reads the context once (cache read), writes its summary
    (output), and the new, short prefix is written to the cache (1-hour write, 2x input)."""
    p = pricing.lookup(model)
    if not p:
        return 0.0
    i, _cw, cr, o = p[:4]
    return (COMPACT_AT * cr + SUMMARY_OUT_TOKENS * o + HANDOFF_CONTEXT * 2 * i) / 1e6


def o1_net(sessions, since_day: str = "") -> tuple[float, int, int]:
    """(net dollars, turns, sessions) that autoCompactWindow 335000 would have saved.

    Only a turn whose context went past the compaction point (~300k) counts. With the setting that turn
    would have run after floor((context - 50k) / 250k) compactions, each dropping 250k tokens from what
    it re-reads; those tokens are priced at the model's cache-read rate. Each stretch of consecutive
    such turns pays for the compactions it would have needed, so a stretch that is cheaper than its
    own compaction saves nothing. A session that stayed between 250k and 300k contributes nothing."""
    drop = COMPACT_AT - HANDOFF_CONTEXT
    runs: dict = defaultdict(lambda: dict(usd=0.0, n=0, model=""))
    turns, sids = 0, set()
    for s in sessions:
        for model, ctx, run, day in s.long_msgs:
            if ctx <= COMPACT_AT or (day or local_day(s.last)) < since_day:
                continue
            n = (ctx - HANDOFF_CONTEXT) // drop
            r = runs[(s.sid, run)]
            r["usd"] += n * drop * _rate(model, 2) / 1e6
            r["n"] = max(r["n"], n)
            r["model"] = model
            turns += 1
            sids.add(s.sid)
    net = sum(max(0.0, r["usd"] - r["n"] * compaction_cost(r["model"])) for r in runs.values())
    return net, turns, len(sids)


def _usage_row(u: dict) -> dict:
    return {k: u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                       "output_tokens", CACHE_1H_KEY)}


def _unit_saving(unit: dict, to_model: str, only_family: str | None = None) -> float:
    """What the unit's tokens cost on the models they ran on, minus the same tokens on `to_model`."""
    total = 0.0
    for model, usage in unit["usage"].items():
        if only_family and pricing.family(model) != only_family:
            continue
        have = pricing.cost_usd(model, usage)
        want = pricing.cost_usd(to_model, usage)
        if have is not None and want is not None:
            total += max(0.0, have - want)
    return total


def o2_units(units: list[dict], home: pathlib.Path) -> list[dict]:
    """The subagent calls the default subagent model would change: Opus calls that named no model.

    A call that passed its own `model` is left out, because the default is a fallback and the
    call's own model wins. So is a call whose agent type pins a model in its definition, and a call
    whose Agent record has no meta file (we cannot tell whether it named one)."""
    out = []
    for u in units:
        if u.get("explicit") is not None:       # None = named no model; "?" = unknown; else it named one
            continue
        if pricing.family(u["model"]) != "opus":
            continue
        pinned = agent_model(home, u["type"]) if u["type"] != "(untyped)" else None
        if pinned and pinned != "inherit":
            continue
        out.append(u)
    return out


def o2_net(units: list[dict], home: pathlib.Path) -> tuple[float, int, int]:
    chosen = o2_units(units, home)
    return sum(_unit_saving(u, VOLUME_MODEL, "opus") for u in chosen), len(chosen), len(units)


def o3_units(units: list[dict], home: pathlib.Path) -> list[dict]:
    """Read-only calls on a dearer model than Haiku that O2 does not already cover."""
    taken = {u["agent"] for u in o2_units(units, home)}
    out = []
    for u in units:
        if u["agent"] in taken or u["writes"] or u["peak"] > HAIKU_SHORT_PROMPT:
            continue
        if pricing.family(u["model"]) in ("haiku", "other"):
            continue
        out.append(u)
    return out


def o3_net(units: list[dict], home: pathlib.Path) -> tuple[float, int]:
    chosen = o3_units(units, home)
    return sum(_unit_saving(u, SCOUT_MODEL) for u in chosen), len(chosen)


# --- the offers --------------------------------------------------------------------------------

def _o1(inp, home, settings, with_savings) -> Offer:
    f = home / ".claude" / "settings.json"
    change = dict(kind="json", file=_tilde(f, home), key_path=["autoCompactWindow"],
                  old=None, new=config.AUTOCOMPACT_RECOMMENDED,
                  summary=f"set autoCompactWindow to {config.AUTOCOMPACT_RECOMMENDED} in {_tilde(f, home)}")
    saving, basis, benefit = None, "", ("A long session re-reads its whole context on every turn; compacting at about "
                                         f"{COMPACT_AT // 1000}k tokens caps that cost.")
    applies, reason = True, ""
    if not (home / ".claude").is_dir():
        applies, reason = False, "Claude Code is not installed"
    elif settings is None:
        applies, reason = False, f"{_tilde(f, home)} is not valid JSON"
    elif settings.get("autoCompactWindow") is not None:
        applies, reason = False, f"autoCompactWindow is already {settings['autoCompactWindow']}"
    elif with_savings and inp is not None:
        net, turns, sessions = o1_net((s for s in inp.sessions if s.harness == "claude-code" and not s.sidechain),
                                      diagnose_mod.window_start(inp.days))
        if net * _scale(inp.days) >= 1.0:
            saving = _range(net, O1_LOW_SHARE, inp.days)
            basis = (f"{turns} turns in {sessions} sessions went past {COMPACT_AT // 1000}k tokens of context. "
                     f"Each would have re-read 250k fewer cached tokens per compaction, minus the cost of the "
                     f"compaction itself. Sessions between 250k and {COMPACT_AT // 1000}k are not counted. "
                     f"The low end halves it, because a session grows back after it compacts.")
            benefit = None
        else:
            basis = f"No turn in the last {inp.days} days went past {COMPACT_AT // 1000}k tokens, so this saves nothing today."
    return Offer(
        id="O1", title="Compact long sessions earlier", change=change, saving_usd_month=saving, basis=basis,
        benefit=benefit,
        tradeoff=(f"A session compacts at about {COMPACT_AT // 1000}k tokens instead of running on, so very long tasks "
                  "meet a summary sooner and can lose detail the summary leaves out."),
        undo="teyla undo O1 removes autoCompactWindow again; nothing else in the file is touched.",
        applies=applies, reason=reason,
        explain=(f"Claude Code compacts a session about 35k tokens under autoCompactWindow. Without the setting, a "
                 f"session grows until the model's own limit and pays for the whole context on every turn. "
                 f"This writes \"autoCompactWindow\": {config.AUTOCOMPACT_RECOMMENDED} to {_tilde(f, home)}, "
                 f"after copying the file to {_tilde(f, home)}.teyla-bak-<time>."))


def _o2(inp, home, settings, with_savings) -> Offer:
    f = home / ".claude" / "settings.json"
    key = ["env", "CLAUDE_CODE_SUBAGENT_MODEL"]
    change = dict(kind="json", file=_tilde(f, home), key_path=key, old=None, new=SUBAGENT_MODEL,
                  summary=f"set env.CLAUDE_CODE_SUBAGENT_MODEL to \"{SUBAGENT_MODEL}\" in {_tilde(f, home)}")
    saving, basis, benefit = None, "", "Subagents that name no model stop inheriting the Opus or Fable of the session that spawned them."
    applies, reason = True, ""
    cur = ((settings or {}).get("env") or {}).get("CLAUDE_CODE_SUBAGENT_MODEL") if isinstance((settings or {}).get("env"), dict) else None
    if not (home / ".claude").is_dir():
        applies, reason = False, "Claude Code is not installed"
    elif settings is None:
        applies, reason = False, f"{_tilde(f, home)} is not valid JSON"
    elif cur:
        applies, reason = False, f"the default subagent model is already {cur}"
    elif with_savings and inp is not None:
        net, calls, total = o2_net(inp.units, home)
        if net * _scale(inp.days) >= 1.0:
            saving = _range(net, O2_LOW_SHARE, inp.days)
            basis = (f"{calls} of {total} subagent calls ran on Opus without naming a model; the same tokens at "
                     f"Sonnet 5.5's list price cost less. Calls that named their model, or whose agent pins one, are not counted. "
                     f"The low end allows 30% more tokens on Sonnet.")
            benefit = None
        else:
            basis = f"{total} subagent calls in the last {inp.days} days; none ran on Opus by default, so this saves nothing today."
    return Offer(
        id="O2", title="Run subagents on Sonnet unless they say otherwise", change=change, saving_usd_month=saving,
        basis=basis, benefit=benefit,
        tradeoff=("Subagents that name no model run on Sonnet 5.5 instead of your session's model. A task that needs "
                  "Opus must ask for it with the Agent call's model parameter. Needs Claude Code 2.1.251 or newer: older versions let this "
                  "setting override a model a call asked for."),
        undo="teyla undo O2 removes the setting again; the other keys in env stay.",
        applies=applies, reason=reason,
        explain=("CLAUDE_CODE_SUBAGENT_MODEL is a default: a model passed in the Agent call, or pinned in an agent's "
                 "definition, still wins. This writes it under \"env\" in " + _tilde(f, home) + ", after a backup."))


def _o3(inp, home, with_savings) -> Offer:
    f = home / ".claude" / "agents" / "scout.md"
    change = dict(kind="file", file=_tilde(f, home), key_path=[], old=None, new="a read-only agent on Haiku",
                  summary=f"create {_tilde(f, home)}, a read-only agent on Haiku (Read, Grep, Glob, Bash)")
    saving, basis, benefit = None, "", "Surveys, audits and \"where is X\" searches can run on Haiku, at a fraction of Sonnet's price."
    applies, reason = True, ""
    if not (home / ".claude").is_dir():
        applies, reason = False, "Claude Code is not installed"
    elif f.exists():
        applies, reason = False, f"{_tilde(f, home)} already exists"
    elif with_savings and inp is not None:
        net, calls = o3_net(inp.units, home)
        if net * _scale(inp.days) >= 1.0:
            saving = _range(net, O3_LOW_SHARE, inp.days, O3_HIGH_SHARE)
            basis = (f"{calls} read-only subagent calls (no Edit or Write) ran on a dearer model than Haiku. "
                     f"The range assumes {int(O3_LOW_SHARE * 100)}% to {int(O3_HIGH_SHARE * 100)}% of them would use the scout agent. "
                     f"Calls O2 already covers and prompts past {HAIKU_SHORT_PROMPT // 1000}k tokens are left out.")
            benefit = None
        else:
            basis = f"No read-only subagent call in the last {inp.days} days ran on a dearer model than Haiku."
    return Offer(
        id="O3", title="Add a cheap read-only scout agent", change=change, saving_usd_month=saving, basis=basis,
        benefit=benefit,
        tradeoff="Haiku reads less carefully than Sonnet on subtle questions; the agent can only read, so it cannot break anything.",
        undo="teyla undo O3 deletes the file, unless you edited it; then it asks first.",
        applies=applies, reason=reason,
        explain=("Claude Code picks an agent by its description. The scout's says it is for surveys, audits and "
                 "lookups, so reading work goes to it. Teyla writes the file only when no scout agent exists."))


def _o4(inp, diag, home) -> Offer:
    f = home / ".codex" / "config.toml"
    change = dict(kind="toml", file=_tilde(f, home), key_path=["model_reasoning_effort"], old=None, new="medium",
                  summary=f"set model_reasoning_effort to \"medium\" in {_tilde(f, home)}")
    applies, reason = True, ""
    text = codex_config_text(home)
    cur = None
    if not (home / ".codex").is_dir():
        applies, reason = False, "Codex is not installed"
    elif text is None:
        applies, reason = False, f"{_tilde(f, home)} does not exist"
    else:
        have, cur = changes.toml_get(text, "model_reasoning_effort")
        change["old"] = cur if have else None
        if not have:
            applies, reason = False, "no model_reasoning_effort is set, so the Codex default applies"
        elif cur not in ("high", "xhigh"):
            applies, reason = False, f"reasoning effort is already {cur}"
        elif diag is not None:
            total = diag.get("total_usd") or 0
            codex = (diag.get("by_harness") or {}).get("codex", 0)
            if codex < O4_MIN_USD or (total and codex / total < O4_MIN_SHARE):
                applies, reason = False, "Codex is a small part of your spend"
    out = (diag or {}).get("codex_output_usd", 0)
    return Offer(
        id="O4", title="Run Codex at medium reasoning effort", change=change, saving_usd_month=None,
        basis="",
        benefit=(f"Reasoning tokens bill as output, and Codex output cost {_money(out)} in the window. Medium effort uses "
                 "fewer of them; by how many depends on the task, so Teyla gives no dollar figure." if out else
                 "Reasoning tokens bill as output; medium effort uses fewer of them."),
        tradeoff="Hard problems get less thinking time per turn; raise it for one run with `codex -c model_reasoning_effort=high`.",
        undo="teyla undo O4 puts the old value back; the rest of config.toml is untouched.",
        applies=applies, reason=reason,
        explain=(f"This changes one line in {_tilde(f, home)} (currently \"{cur}\"), keeping every other line, comment "
                 "and table as it is, after a backup."))


def _piece(oid, title, piece, change_text, benefit, tradeoff, undo, applies, reason, explain) -> Offer:
    return Offer(id=oid, title=title, change=dict(kind="piece", piece=piece, file="", key_path=[], old=None, new=piece,
                                                  summary=change_text),
                 saving_usd_month=None, basis="", benefit=benefit, tradeoff=tradeoff, undo=undo,
                 applies=applies, reason=reason, explain=explain)


def _o5(home) -> Offer:
    from . import policy
    applies, reason = False, "every harness already reads the same rules"
    try:
        st = policy.status()
        applies = any(v is False for k, v in st.items() if k != "policy-file")
        reason = "" if applies else reason
    except Exception as e:  # noqa: BLE001
        reason = f"could not read the policy wiring ({type(e).__name__})"
    return _piece(
        "O5", "Give every agent the same rules", "policy",
        "run `teyla policy sync`: one policy file, linked into the AGENTS.md or CLAUDE.md of each installed harness",
        "One rules file is read by Claude Code, Codex and the others, so a correction made once holds everywhere.",
        "Teyla writes a starter policy to ~/.agents/POLICY.md when you have none, and adds one import line to ~/.claude/CLAUDE.md; "
        "edit the policy to match how you work.",
        "teyla undo O5 puts every file it changed back from its backup and removes the ones it created, while you have not edited them; the policy file goes only if it is still the starter.",
        applies, reason,
        "`teyla policy sync` writes ~/.agents/POLICY.md if it is missing, links or generates ~/.codex/AGENTS.md and ~/.grok/AGENTS.md, "
        "and adds `@~/.agents/POLICY.md` to ~/.claude/CLAUDE.md. It never touches a harness that is not installed.")


def _o6(home) -> Offer:
    from . import harness
    applies, reason = False, "hooks and skills are already in place"
    try:
        applies = any(r.get("present") and (r.get("hooks") is False or r.get("skills", 0) < r.get("skills_total", 0))
                      for r in harness.status())
        reason = "" if applies else reason
    except Exception as e:  # noqa: BLE001
        reason = f"could not read the harness wiring ({type(e).__name__})"
    return _piece(
        "O6", "Keep your prompts and questions", "hooks",
        "run `teyla harness sync`: skills and hooks into Cursor, Codex, Grok and Hermes",
        "Hooks record the corrections you type and the questions agents leave unanswered, so Teyla can list what is waiting on you.",
        "Each hook runs a small script from ~/.teyla/hooks on every prompt; Codex asks you to approve a new hook once.",
        "teyla undo O6 removes the hook entries and skills it created; your own hooks stay.",
        applies, reason,
        "`teyla harness sync` copies five small scripts to ~/.teyla/hooks and registers them in each installed harness's hooks file. "
        "Nothing leaves the machine.")


def _o7(home) -> Offer:
    from . import routine_install as ri
    applies, reason = True, ""
    if sys.platform != "darwin":
        applies, reason = False, "the daily routine uses launchd, which is macOS only"
    elif ri.DAILY_PLIST_PATH.exists():
        applies, reason = False, "the daily routine is already installed"
    return _piece(
        "O7", "Check in every morning", "routine",
        "run `teyla routine install`: a daily and a weekly launchd job",
        "A daily run keeps Teyla current, refreshes the waiting-asks count and flags problems before you hit them.",
        "Two launchd jobs run on your Mac at fixed times; they use no network except the update check, and `teyla config set safe.enabled=true` turns that off.",
        "teyla undo O7 unloads and removes the jobs it created.",
        applies, reason,
        "`teyla routine install` writes two wrapper scripts to ~/.teyla and two plists to ~/Library/LaunchAgents, then loads them with launchctl.")


def build(days: int = 30, inputs=None, diag: dict | None = None, with_savings: bool = True,
          home: pathlib.Path | None = None) -> list[Offer]:
    """All seven offers in order, each with `applies` set. `with_savings` False skips the session
    arithmetic (what `teyla apply` needs: the change, not the figure)."""
    home = home or pathlib.Path.home()
    settings = claude_settings(home)
    if with_savings and inputs is None:
        from . import diagnose
        inputs = diagnose.collect(days)
    if diag is None and with_savings and inputs is not None:
        from . import diagnose
        diag = diagnose.diagnose(days, inputs, with_asks=False)
    built = [_o1(inputs, home, settings, with_savings), _o2(inputs, home, settings, with_savings),
             _o3(inputs, home, with_savings), _o4(inputs, diag, home), _o5(home), _o6(home), _o7(home)]
    for o in built:
        o.short = SHORT[o.id]
    return built


# --- applying ------------------------------------------------------------------------------------

def apply(offer: Offer, home: pathlib.Path | None = None) -> tuple[dict, list[str]]:
    """Make the offer's change. Returns (the change record, lines to show). Raises changes.ChangeError."""
    home = home or pathlib.Path.home()
    c = offer.change
    if c["kind"] == "json":
        rec = changes.apply_json(offer.id, home / pathlib.Path(c["file"].removeprefix("~/")), c["key_path"], c["new"])
        return rec, [offer.change["summary"], f"backup: {rec['backup']}" if rec.get("backup") else "(no file existed; created)"]
    if c["kind"] == "toml":
        rec = changes.apply_toml(offer.id, home / pathlib.Path(c["file"].removeprefix("~/")), c["key_path"][0], c["new"])
        return rec, [offer.change["summary"], f"backup: {rec['backup']}"]
    if c["kind"] == "file":
        rec = changes.apply_file(offer.id, home / pathlib.Path(c["file"].removeprefix("~/")), SCOUT_AGENT)
        return rec, [offer.change["summary"]]
    from . import harness, policy, routine_install
    run = {"policy": lambda: policy.sync(), "hooks": lambda: harness.sync(),
           "routine": lambda: routine_install.install()}[c["piece"]]
    rec, lines = changes.apply_piece(offer.id, c["piece"], run, home)
    return rec, lines
