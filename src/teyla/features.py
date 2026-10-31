"""`teyla features` — Teyla as a kit: pick the packs you need, turn on only those, and hear about a pack
when the problem it solves shows up on this Mac.

    teyla features                   every pack: on, partly or off, what it does, a problem seen here
    teyla features --json            the same, for an AI agent
    teyla features on load disk      turn packs on: the pack's offers, switches, hooks and jobs (--yes, --dry)
    teyla features on load --no-offers   only the switches, hooks and jobs; the offers stay with `teyla apply`
    teyla features off load          turn a pack's switches off and undo its O1 to O4 changes
    teyla features off load --quiet  ... and never remind me of it
    teyla features choose cost load  record the checklist answer; changes nothing else

A pack is one of two kinds. An *automatic* pack changes settings, hooks or launchd jobs, so it works without
you. A *toolkit* pack installs nothing: its commands work on any repo when you call them, and choosing it only
records that you use it. `teyla start` opens with the checklist; `docs/FEATURES.md` lists every pack.

A reminder is a doctor row `feature:<pack>` (WARN), so the session-start banner shows it once: the pack is not
on, it is not muted, and its problem was seen (CRITICAL load, a kernel panic, a low disk, token waste that
`teyla start` priced, unread questions). Nothing here leaves the machine.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

from . import config

AUTO, KIT = "automatic", "toolkit"
ON, PARTLY, OFF = "on", "partly", "off"
PLUGIN_INSTALL = "teyla plugin install zaitsew/teyla"
ROUTINE_INSTALL = "teyla routine install"
# These packs are suggested on a first run when nothing else points at them.
CORE = ("cost", "inbox")


@dataclasses.dataclass
class Pack:
    id: str
    title: str
    kind: str
    need: str                          # the problem, in the words of the person who has it
    does: str                          # what the pack does about it, one line
    commands: tuple[str, ...]          # what to run once it is on
    offers: tuple[str, ...] = ()       # `teyla start` offers that belong to it
    switches: dict = dataclasses.field(default_factory=dict)   # "table.key" -> value while the pack is on
    routine: bool = False              # the switches name launchd agents: `teyla routine install` writes them
    plugin: bool = False               # its hooks come with Teyla's Claude Code plugin
    # Written when the plugin comes in through another pack and this one was not chosen, only while the key
    # is still at its default: the plugin's hooks for this pack then stay quiet.
    quiet_when_unchosen: dict = dataclasses.field(default_factory=dict)
    # Its problem can take the Mac down, so a pack that is only partly on reminds too; any other reminds only while off.
    acute: bool = False


PACKS: tuple[Pack, ...] = (
    Pack("cost", "Token cost", AUTO,
         "Long sessions re-read their whole context every turn, and subagents run on the top model.",
         "Compacts earlier, runs subagents on Sonnet and reading on Haiku, writes a handoff at 240k tokens.",
         ("teyla spend --days 7", "teyla lanes", "teyla models"),
         offers=("O1", "O2", "O3", "O4"), switches={"hooks.context_budget": True}),
    Pack("load", "Machine guard", AUTO,
         "Parallel agents boot simulators and builds until the Mac swaps, hangs or panics.",
         "Admits one heavy job at a time, holds new ones while memory is critical, records load every minute.",
         ("teyla load", "teyla load --wait --kind build", "teyla crash"),
         switches={"guard.enabled": True, "guard.agent": True}, routine=True, plugin=True,
         quiet_when_unchosen={"guard.enabled": False}, acute=True),
    Pack("disk", "Disk cleanup", AUTO,
         "Worktrees, DerivedData, idle simulators and caches fill the disk, and a full disk leaves swap no room.",
         "Shuts down idle simulators every 10 minutes and sweeps temp build output every hour.",
         ("teyla storage", "teyla storage sweep --dry", "teyla storage sims"),
         switches={"storage.sims_agent": True, "storage.sweep_agent": True}, routine=True, acute=True),
    Pack("inbox", "Questions and ideas", AUTO,
         "A session ends on a question, the app archives it, and nobody reads it again.",
         "Hooks keep the questions agents leave and your long prompts; one screen lists what waits on you.",
         ("teyla today", "teyla asks", "teyla note \"an idea\"", "teyla intent"),
         offers=("O6",), switches={"intent.enabled": True}, plugin=True,
         quiet_when_unchosen={"intent.enabled": False}),
    Pack("policy", "One policy", AUTO,
         "Each agent has its own rules file, so a correction made in one is unknown to the next.",
         "One POLICY.md, linked into Claude Code, Codex, Cursor, Grok and Hermes.",
         ("teyla policy sync", "teyla tidy", "teyla correct"),
         offers=("O5",)),
    Pack("daily", "Morning check", AUTO,
         "Nobody runs the checks by hand, so a broken hook or a stale routine goes unseen for weeks.",
         "A daily and a weekly launchd job: doctor, the banner, and a six-line weekly digest.",
         ("teyla doctor", "teyla digest", "teyla routines"),
         offers=("O7",)),
    Pack("security", "Security", KIT,
         "A secret or a private name ends up in a commit, a pull request or a public repo.",
         "Refuses an agent's publish or credential read that carries a secret; audits repos and dependencies.",
         ("teyla leak install", "teyla shield", "teyla deps <repo>", "teyla hosts <repo>", "teyla mcp probe <url>"),
         plugin=True),
    Pack("design", "UX and UI", KIT,
         "Agents ship screens with noise, weak hierarchy and copy nobody reviewed.",
         "Checks UI code against one standard, judges two screens, keeps accepted screenshots and design decisions.",
         ("teyla ux check <repo>", "teyla ux judge <a.png> <b.png>", "teyla ux shots", "teyla taste", "teyla kit")),
    Pack("ship", "Ship and test", KIT,
         "A build is uploaded but no tester can install it, and pull requests merge without a review.",
         "Tracks every product per platform, whether a build reached a person, unreviewed merges, comments from the real app.",
         ("teyla portfolio", "teyla testflight", "teyla play", "teyla reviews", "teyla review", "teyla productize")),
    Pack("writing", "Writing", KIT,
         "Agent replies and product docs are long and padded, and a README describes last month's product.",
         "Measures reply length and filler, checks drafts against a voice chart, finds stale docs and non-English text.",
         ("teyla prose", "teyla voice check <draft>", "teyla docs check <repo>", "teyla lang <repo>", "teyla copy")),
)
BY_ID = {p.id: p for p in PACKS}
OFFER_PACK = {o: p.id for p in PACKS for o in p.offers}


# --- state -----------------------------------------------------------------------------------------

def _home() -> pathlib.Path:
    return pathlib.Path.home()


def _cfg_get(cfg: dict, dotted: str):
    table, key = dotted.split(".", 1)
    sub = cfg.get(table)
    if isinstance(sub, dict) and key in sub:
        return sub[key]
    return (config.DEFAULTS.get(table) or {}).get(key)


def _switch_on(cfg: dict, dotted: str, want) -> bool:
    v = _cfg_get(cfg, dotted)
    return config.truthy(v) == bool(want) if isinstance(want, bool) else v == want


def _user_has(dotted: str) -> bool:
    """Is the key in the person's own config.toml? `config.load()` merges the defaults in, so it cannot say."""
    table, key = dotted.split(".", 1)
    sub = config._read(config.CONFIG_PATH).get(table)
    return isinstance(sub, dict) and key in sub


def _counts(dotted: str, want) -> bool:
    """A switch whose default already is the pack's value says nothing until the person sets it: guard.enabled is
    true out of the box, and a fresh Mac would read as "partly" on for a guard that runs nowhere."""
    table, key = dotted.split(".", 1)
    return _user_has(dotted) or (config.DEFAULTS.get(table) or {}).get(key) != want


def chosen(cfg: dict | None = None) -> list[str]:
    v = ((cfg or config.load()).get("features") or {}).get("chosen") or []
    return [x for x in v if x in BY_ID] if isinstance(v, list) else []


def muted(cfg: dict | None = None) -> list[str]:
    v = ((cfg or config.load()).get("features") or {}).get("muted") or []
    return [x for x in v if x in BY_ID] if isinstance(v, list) else []


def _claude_present(home: pathlib.Path) -> bool:
    return (home / ".claude").is_dir() and not config.harness_disabled("claude-code")


def plugin_installed(home: pathlib.Path) -> bool:
    from . import plugin_install
    try:
        return plugin_install.installed_version(plugins_dir=home / ".claude" / "plugins") is not None
    except Exception:  # noqa: BLE001 — a registry that does not parse is "not installed"
        return False


def _agent_labels(p: Pack) -> list[str]:
    from . import routine_install as ri
    return [label for label, o in ri.OPTIONAL.items() if f"{o['table']}.{o['key']}" in p.switches]


def _agents_written(p: Pack) -> bool:
    from . import routine_install as ri
    return all(ri.optional_paths(label)["plist"].exists() for label in _agent_labels(p))


def parts(p: Pack, cfg: dict, offers_by_id: dict, home: pathlib.Path) -> list[tuple[str, bool]]:
    """(what, in place) for each part of the pack that applies on this machine."""
    out = []
    for oid in p.offers:
        o = offers_by_id.get(oid)
        # An offer that does not apply is in place only when its reason says so ("... is already 335000"). Its
        # tool missing, a file that does not parse or a share too small to matter make it no part of the pack here.
        if o is not None and (o.applies or "already" in (o.reason or "")):
            out.append((f"{oid} {o.title}", not o.applies))
    for k, v in p.switches.items():
        if _counts(k, v):
            out.append((f"{k} = {_value_text(v)}", _switch_on(cfg, k, v)))
    if p.plugin and _claude_present(home):
        out.append(("Teyla's Claude Code plugin", plugin_installed(home)))
    if p.routine and sys.platform == "darwin" and _agent_labels(p):
        out.append(("its launchd agents", _agents_written(p)))
    return out


def status(p: Pack, cfg: dict, offers_by_id: dict, home: pathlib.Path) -> str:
    rows = parts(p, cfg, offers_by_id, home)
    picked = p.id in chosen(cfg)
    if p.kind == KIT:
        rows = rows + [("chosen", picked)]
    done = sum(1 for _, ok in rows if ok)
    if rows and done == len(rows):
        return ON
    return PARTLY if done else OFF


# --- signals: the problem a pack solves, seen on this machine ------------------------------------

def _doctor_rows() -> list[dict]:
    from . import doctor
    try:
        return json.loads(doctor.DOCTOR_JSON.read_text()).get("checks") or []
    except (OSError, ValueError, AttributeError):
        return []


def signals(checks: list[dict] | None = None) -> dict[str, str]:
    """pack id -> what was seen, from doctor's rows (the last `teyla doctor` when none are given), the
    last `teyla start` report and the first-screen cache. Reads files only."""
    rows = {c.get("name"): c for c in (_doctor_rows() if checks is None else checks)}
    out: dict[str, str] = {}
    if (rows.get("machine:crash") or {}).get("level") == "WARN":
        out["load"] = "this Mac had a kernel panic or a watchdog reset"
    elif (rows.get("machine:load") or {}).get("level") == "WARN":
        out["load"] = "this Mac hit CRITICAL load"
    disk = rows.get("storage:disk") or {}
    if disk.get("level") in ("WARN", "FIX"):
        out["disk"] = f"the disk is down to {str(disk.get('detail') or 'little free space').split(' (')[0]}"
    from . import figures
    rep = figures.start_report()
    waste = 0.0
    for o in rep.get("offers") or []:
        s = o.get("saving_usd_month") if isinstance(o, dict) else None
        if o.get("applies") and OFFER_PACK.get(o.get("id")) == "cost" and isinstance(s, dict):
            waste += float(s.get("high") or 0)
    if waste >= 20:
        out["cost"] = f"`teyla start` priced up to ${waste:,.0f} a month of token waste"
    q, _age = figures.cached("questions")
    n = (q or {}).get("waiting")
    if isinstance(n, int) and n >= 3:
        out["inbox"] = f"{n} questions wait on you unread"
    return out


def rows(checks: list[dict] | None = None, home: pathlib.Path | None = None, offer_list=None) -> list[dict]:
    """One dict per pack, in catalog order: what `teyla features --json` and `teyla start --agent` print."""
    from . import offers as offers_mod
    home = home or _home()
    cfg = config.load()
    try:
        by_id = {o.id: o for o in (offer_list if offer_list is not None else offers_mod.build(with_savings=False, home=home))}
    except Exception:  # noqa: BLE001 — a settings file that does not parse must not hide the catalog
        by_id = {}
    seen, picked, quiet = signals(checks), chosen(cfg), muted(cfg)
    out = []
    for p in PACKS:
        st = status(p, cfg, by_id, home)
        out.append(dict(id=p.id, title=p.title, kind=p.kind, need=p.need, does=p.does, status=st,
                        chosen=p.id in picked, muted=p.id in quiet, signal=seen.get(p.id, ""),
                        suggested=st != OFF or p.id in seen or (not picked and p.id in CORE),
                        offers=list(p.offers), commands=list(p.commands),
                        parts=[dict(what=w, done=ok) for w, ok in parts(p, cfg, by_id, home)],
                        on=f"teyla features on {p.id}"))
    return out


def nudges(checks: list[dict]) -> list[dict]:
    """Doctor rows for packs whose problem showed up while they are off (an acute pack: not on) and not muted."""
    out = []
    for r in rows(checks):
        due = r["status"] == OFF or (r["status"] == PARTLY and BY_ID[r["id"]].acute)
        if r["signal"] and due and not r["muted"]:
            out.append({"level": "WARN", "name": f"feature:{r['id']}",
                        "detail": f"{r['signal']}; the {r['title']} pack is {r['status']}",
                        "fix": f"teyla features on {r['id']}   (stop reminding: teyla features off {r['id']} --quiet)"})
    return out


# --- changing state ---------------------------------------------------------------------------------

def _set_list(key: str, values: list[str]) -> None:
    config.set_value(f"features.{key}", ",".join(values))


def record_choice(ids: list[str]) -> None:
    _set_list("chosen", [p.id for p in PACKS if p.id in ids])


def quiet_unchosen(picked: list[str], rs: list[dict]) -> list[str]:
    """The plugin brings the hooks of every pack. For a pack left out of the checklist and off, write its quiet
    value while the key is still at its default, so its hook does nothing. A key the person set stays as it is,
    and so does a pack that is partly on: someone uses it."""
    lines = []
    off = {r["id"] for r in rs if r["status"] == OFF}
    for p in PACKS:
        if p.id in picked or p.id not in off:
            continue
        for k, v in p.quiet_when_unchosen.items():
            if not _user_has(k):
                lines.append(config.set_value(k, _value_text(v)))
    return lines


def _value_text(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def plan(p: Pack, home: pathlib.Path, offers_by_id: dict, with_offers: bool = True) -> list[str]:
    """What `on` would change, one line each; empty when the pack is already on."""
    cfg = config.load()
    L = []
    if with_offers:
        L += [f"apply {oid}: {offers_by_id[oid].change['summary']}" for oid in p.offers
              if oid in offers_by_id and offers_by_id[oid].applies]
    L += [f"set {k} = {_value_text(v)} in ~/.teyla/config.toml" for k, v in p.switches.items() if not _switch_on(cfg, k, v)]
    if p.plugin and _claude_present(home) and not plugin_installed(home):
        L.append(f"run `{PLUGIN_INSTALL}`: hooks, skills and the MCP server in Claude Code")
    if p.routine and sys.platform == "darwin" and _agent_labels(p) and not _agents_written(p):
        L.append(f"run `{ROUTINE_INSTALL}`: writes and loads the pack's launchd agents")
    return L


def turn_on(p: Pack, home: pathlib.Path | None = None, with_offers: bool = True) -> list[str]:
    """Make the pack's changes. Offers go through `offers.apply`, so each is logged with its undo; the plugin
    and the routine install are logged as commands, like O6 and O7."""
    from . import changes, offers as offers_mod, routine_install
    home = home or _home()
    by_id = {o.id: o for o in offers_mod.build(with_savings=False, home=home)}
    out: list[str] = []
    if with_offers:
        for oid in p.offers:
            o = by_id.get(oid)
            if o is not None and o.applies:
                _rec, lines = offers_mod.apply(o, home=home)
                out += lines[:3]
    cfg = config.load()
    for k, v in p.switches.items():
        if not _switch_on(cfg, k, v):
            out.append(config.set_value(k, _value_text(v)))
    if p.plugin and _claude_present(home) and not plugin_installed(home):
        _rec, lines = changes.apply_command(
            f"pack:{p.id}", PLUGIN_INSTALL, lambda: offers_mod._plugin_step(home),
            "`teyla plugin uninstall teyla` removes the plugin; other packs use it too.")
        out += lines[:3]
    if p.routine and sys.platform == "darwin" and _agent_labels(p) and not _agents_written(p):
        _rec, lines = changes.apply_command(
            f"pack:{p.id}", ROUTINE_INSTALL, routine_install.install,
            f"`teyla features off {p.id}` turns the agents' switches off; `teyla routine install` then removes them.")
        out += lines[:3]
    picked = chosen()
    if p.id not in picked:
        record_choice(picked + [p.id])
    return out


def turn_off(p: Pack, quiet: bool = False) -> list[str]:
    """Switches to their off value, O1 to O4 undone. The plugin stays (other packs use it) and so do O5 to O7,
    which only `teyla uninstall` reverses."""
    from . import changes, routine_install
    out: list[str] = []
    for oid in p.offers:
        for rec in changes.resolve(oid):
            if rec.get("kind") == "command" or rec.get("undone"):
                continue
            try:
                out += [f"undid {rec['id']}"] + changes.revert(rec)
            except changes.ChangeError as e:
                out.append(str(e))
    cfg = config.load()
    for k, v in p.switches.items():
        if isinstance(v, bool) and _switch_on(cfg, k, v):
            out.append(config.set_value(k, _value_text(not v)))
    if p.routine and sys.platform == "darwin" and routine_install.DAILY_PLIST_PATH.exists():
        out += routine_install.install()[:3]
    for oid in p.offers:
        if oid in ("O5", "O6", "O7"):
            out.append(f"{oid} stays: `teyla uninstall --dry` lists what removes it")
    _set_list("chosen", [x for x in chosen() if x != p.id])
    if quiet and p.id not in muted():
        _set_list("muted", muted() + [p.id])
        out.append(f"no more reminders for {p.title}; `teyla features on {p.id}` brings it back")
    return out


# --- the checklist ----------------------------------------------------------------------------------

def checklist_lines(rs: list[dict], picked: set[str]) -> list[str]:
    w = max(len(r["title"]) for r in rs)
    L = []
    for i, r in enumerate(rs, 1):
        box = "[x]" if r["id"] in picked else "[ ]"
        note = r["signal"] or r["need"]
        L.append(f"  {box} {i:>2} {r['title']:<{w}}  {note}")
    return L


def pick(rs: list[dict], ask) -> list[str] | None:
    """The checklist in a terminal. `ask(prompt)` returns the line typed. Numbers switch a box, Enter accepts,
    q quits (None). The suggested packs start checked."""
    picked = {r["id"] for r in rs if r["suggested"]}
    print("\nWhat do you want Teyla for? Type numbers to switch them (\"2 3\"), Enter to go on, q to quit.")
    while True:
        print("\n".join(checklist_lines(rs, picked)))
        a = ask("Packs: ")
        if a in ("q", "quit"):
            return None
        if a == "":
            return [r["id"] for r in rs if r["id"] in picked]
        for tok in a.replace(",", " ").split():
            if tok.isdigit() and 1 <= int(tok) <= len(rs):
                picked ^= {rs[int(tok) - 1]["id"]}
            else:
                print(f"  {tok!r}: type a number from 1 to {len(rs)}")


# --- the command ------------------------------------------------------------------------------------

def render(rs: list[dict]) -> str:
    mark = {ON: "●", PARTLY: "◐", OFF: "○"}
    w = max(len(r["title"]) for r in rs)
    L = []
    for kind in (AUTO, KIT):
        L.append("Automatic: they change settings, hooks or jobs" if kind == AUTO else
                 "Toolkit: commands you run on a repo; nothing is installed")
        for r in (x for x in rs if x["kind"] == kind):
            L.append(f"  {mark[r['status']]} {r['id']:<8} {r['title']:<{w}}  {r['does']}")
            if r["signal"] and r["status"] != ON:
                L.append(f"      seen here: {r['signal']}" + ("  (muted)" if r["muted"] else f"  ->  {r['on']} --dry"))
        L.append("")
    L.append("● on  ◐ partly  ○ off.   Turn one on: teyla features on <pack>.   Detail: docs/FEATURES.md")
    return "\n".join(L)


def _ids(args) -> list[Pack] | None:
    out = []
    for ref in args.packs:
        p = BY_ID.get(ref.lower())
        if p is None:
            print(f"no pack {ref!r}: the packs are {', '.join(BY_ID)}", file=sys.stderr)
            return None
        out.append(p)
    return out


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def cmd_features(args) -> int:
    action = args.action or "list"
    if action == "list":
        rs = rows()
        print(json.dumps(rs, indent=2) if args.json else render(rs))
        return 0
    packs = _ids(args)
    if packs is None:
        return 2
    if not packs:
        print(f"name at least one pack: {', '.join(BY_ID)}", file=sys.stderr)
        return 2
    if action == "choose":
        record_choice([p.id for p in packs])
        print("chosen: " + ", ".join(p.title for p in packs) + ". Nothing else was changed.")
        return 0
    if action == "off":
        for p in packs:
            print(f"{p.title}:")
            for line in turn_off(p, quiet=args.quiet):
                print(f"  {line}")
        return 0
    from . import changes, offers as offers_mod
    home = _home()
    by_id = {o.id: o for o in offers_mod.build(with_savings=False, home=home)}
    code = 0
    for p in packs:
        todo = plan(p, home, by_id, with_offers=not args.no_offers)
        print(f"{p.title}: {p.does}")
        if not todo:
            print("  already on." + (f" Try: {p.commands[0]}" if p.commands else ""))
            if p.id not in chosen() and not args.dry:
                record_choice(chosen() + [p.id])
            continue
        for line in todo:
            print(f"  - {line}")
        if args.dry:
            continue
        if not args.yes:
            if not _is_tty():
                print(f"  not turned on: nothing can ask here. Run `teyla features on {p.id} --yes`.", file=sys.stderr)
                code = 1
                continue
            try:
                if input("  Turn it on? [y]es / [n]o  ").strip().lower() not in ("y", "yes"):
                    continue
            except EOFError:
                continue
        try:
            for line in turn_on(p, home, with_offers=not args.no_offers):
                print(f"  {line}")
        except changes.ChangeError as e:
            print(f"  {p.id}: {e}", file=sys.stderr)
            code = 1
        print(f"  Try: {p.commands[0]}")
    if args.dry:
        print("\n--dry: nothing was written.")
    return code


def register(sp):
    q = sp.add_parser("features", help="the packs Teyla is made of: which are on, and turn on only the ones you need")
    q.set_defaults(fn=cmd_features)
    q.add_argument("action", nargs="?", choices=["list", "on", "off", "choose"], help="default: list")
    q.add_argument("packs", nargs="*", metavar="PACK", help=", ".join(BY_ID))
    q.add_argument("--json", action="store_true", help="list: print the packs as JSON")
    q.add_argument("--yes", action="store_true", help="on: do not ask")
    q.add_argument("--dry", action="store_true", help="on: show the changes, write nothing")
    q.add_argument("--no-offers", action="store_true", help="on: leave the pack's offers (O1..O7) to `teyla apply`")
    q.add_argument("--quiet", action="store_true", help="off: and never remind me of this pack")
    return q
