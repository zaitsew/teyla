"""`teyla gtm` — the go-to-market cockpit: what waits for you today, and the week's funnel per goal (docs/GTM.md).

    teyla gtm [today] [--json]          approvals, items to send, replies, today's distribution, the week's outcomes, deadlines
    teyla gtm week [--week YYYY-Www] [--json]   funnel per goal, conversion per stage, stalled items, channels, next targets
    teyla gtm init [--force]            write ~/.teyla/gtm/goals.toml with neutral example goals
    teyla gtm doctor                    each source: read, stale, broken or missing, one line each
    teyla gtm goal add --title T [--weekly STAGE=N ...] [--deadline D] [--done-when TEXT]   add a goal (the app's first run)
    teyla gtm goal set ID [--weekly STAGE=N ...] [--title T] [--deadline D] [--done-when TEXT]   change one goal

Three counters never mix. Preparation is what agents produced (ideas, drafts, cuts); it is never a success metric.
Distribution is what the owner sent: posts he published and approaches he logged. A row logged from an agent session
counts 0 here. Outcomes are what came back: replies, conversations, intros, activated testers, offers, proposals, revenue.

Counts come from the growth ledger and from read-only sources: a command or a JSON file that returns
`{source, counts:{stage:n}, waiting:{kind:n}, updated}`. Goals and targets live in ~/.teyla/gtm/goals.toml, never in a
repo. A missing source prints one doctor line and never fails the command. Teyla never sends anything.
Exit 0 ok, 2 usage.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import time
import tomllib

from . import corrections

VERSION = 1
SOURCE_TIMEOUT_S = 20
STALE_DAYS = 7
MAX_COUNT = 100_000
WAITING_KINDS = ("approve", "send", "reply", "follow_up")
# A stage counts as distribution or as an outcome by name; every other stage a source reports is preparation.
DISTRIBUTION_STAGES = ("posted", "approached", "sent", "invited", "applied")
OUTCOME_STAGES = ("replied", "conversation", "intro", "signed_up", "activated", "retained", "offer_fit", "offer",
                  "proposal", "won", "paid", "revenue")
OFFER_FITS = ("hire", "consulting", "product")
# Growth ledger rows. `published` is a post the owner recorded; an `attempt` of these kinds is an approach he made.
LEDGER_APPROACH_KINDS = ("comment", "reply", "email", "dm", "outreach", "ad")
LEDGER_CONVERSATION_KINDS = ("call", "meeting", "icp-meeting")
LEDGER_PREP_EVENTS = {"idea": "ideas", "draft": "drafts", "cut": "cuts", "video": "videos"}
BUILTIN = ("growth",)                       # always read: the growth ledger and its review queue
USAGE_ADAPTERS = ("batrack",)       # fall back to the product's cached usage probe (`teyla products`)
# A usage-probe counter -> (where, key). `gtm_<stage>` and `gtm_waiting_<kind>` counters map themselves.
# Only `_week`/`_7d` counters count: an all-time total would inflate the week.
USAGE_KEYS = {"drafts": ("waiting", "approve"), "drafts_waiting": ("waiting", "approve"), "drafts_pending": ("waiting", "approve"),
              "drafts_open": ("waiting", "approve"),
              "sent_week": ("counts", "sent"), "sent_7d": ("counts", "sent"), "replies_week": ("counts", "replied"),
              "replies_7d": ("counts", "replied"), "calls_week": ("counts", "conversation"),
              "meetings_week": ("counts", "conversation")}


class GtmError(Exception):
    """A usage error; the message says what to fix."""


# --- paths and time ------------------------------------------------------------------------------------------

def home() -> pathlib.Path:
    """`TEYLA_GTM_DIR`, or the `gtm` folder of Teyla's home. Sibling products honour the same variable."""
    env = os.environ.get("TEYLA_GTM_DIR")
    return pathlib.Path(env).expanduser() if env else corrections.teyla_home() / "gtm"


def goals_path() -> pathlib.Path:
    return home() / "goals.toml"


def drop_dir() -> pathlib.Path:
    return home() / "sources"


def weeks_dir() -> pathlib.Path:
    return home() / "weeks"


def day_of(now: float) -> str:
    return _dt.datetime.fromtimestamp(now).date().isoformat()


def week_of(day: str) -> str:
    y, w, _ = _dt.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def week_range(week: str) -> tuple[str, str]:
    """Monday and Sunday of an ISO week `YYYY-Www`."""
    try:
        y, w = week.split("-W")
        mon = _dt.date.fromisocalendar(int(y), int(w), 1)
    except (ValueError, AttributeError):
        raise GtmError(f"--week reads YYYY-Www (for example 2026-W45), not {week!r}") from None
    return mon.isoformat(), (mon + _dt.timedelta(days=6)).isoformat()


def parse_ts(s) -> float | None:
    try:
        d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def iso(now: float) -> str:
    return _dt.datetime.fromtimestamp(now, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _private_dir(d: pathlib.Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass


def _write(path: pathlib.Path, text: str) -> None:
    _private_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# --- goals ---------------------------------------------------------------------------------------------------

EXAMPLE_GOALS = '''# Goals for `teyla gtm` (docs/GTM.md). Local only: this file never goes into a repo.
version = 1

# Posts you publish plus approaches you send, per day. Agent work never counts toward it.
[distribution]
per_day = 10

# One relationship pipeline: people you approach, the conversation, then the offer fit you decide after the call.
[[goal]]
id = "relationships"
title = "Conversations with founders and executives"
done_when = "A hire, a consulting deal or a product sale"
deadline = "2027-03-01"
funnel = ["identified", "approached", "replied", "conversation", "intro", "offer_fit"]
offer_fit = ["hire", "consulting", "product"]
sources = ["growth", "outreach", "batrack", "contacts"]
stage_prefix = "network"   # a source stage `network.sent` feeds this goal; `investor.sent` does not
[goal.map]                 # a source's stage name -> this funnel's stage name
sent = "approached"
[goal.weekly]
approached = 60
conversation = 15
intro = 3
offer_fit = 1

[[goal]]
id = "testers"
title = "Activated testers on two focus products"
deadline = "2027-01-31"
funnel = ["invited", "signed_up", "activated", "retained"]
sources = ["accounts"]
[goal.weekly]
invited = 40
activated = 12

[[goal]]
id = "investors"
title = "Investor relationships"
deadline = "2027-06-30"
funnel = ["identified", "approached", "conversation", "follow_up"]
sources = ["outreach", "contacts"]
stage_prefix = "investor"
[goal.map]
sent = "approached"
[goal.weekly]
conversation = 2

# A source is a read-only command or file that prints the JSON in docs/GTM.md. Files dropped in
# ~/.teyla/gtm/sources/*.json are read without an entry here.
# [[source]]
# id = "batrack"
# command = ["/path/to/a/read-only/exporter", "--json"]
# [[source]]
# id = "outreach"
# file = "~/path/to/outreach-gtm.json"
'''


def _clean_stage(s) -> str:
    return str(s).strip().lower().replace("-", "_").replace(" ", "_")[:60]


def split_stage(stage: str) -> tuple[str, str]:
    """`network.sent` -> ("network", "sent"); `sent` -> ("", "sent"). A prefix names the funnel a stage belongs to."""
    pre, _, name = stage.rpartition(".")
    return pre, name


def _count(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_COUNT else None


def load_goals(path: pathlib.Path | None = None) -> dict:
    """{exists, errors, per_day, goals: [...], sources: [...]} from goals.toml. A broken file is an error line, never a crash."""
    path = path or goals_path()
    out = dict(exists=path.is_file(), errors=[], per_day=None, goals=[], sources=[])
    if not out["exists"]:
        return out
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        out["errors"].append(f"{path.name}: {e}")
        return out
    def table(v) -> dict:
        return v if isinstance(v, dict) else {}

    def strings(v) -> list:
        return [x for x in v if isinstance(x, (str, int))] if isinstance(v, list) else []

    for key, kind in (("distribution", dict), ("goal", list), ("source", list)):
        if key in raw and not isinstance(raw[key], kind):
            out["errors"].append(f"`{key}` must be a {'table' if kind is dict else 'list of tables'}")
    out["per_day"] = _count(table(raw.get("distribution")).get("per_day"))
    seen = set()
    for i, g in enumerate(raw.get("goal") if isinstance(raw.get("goal"), list) else []):
        if not isinstance(g, dict) or not str(g.get("id") or "").strip():
            out["errors"].append(f"goal {i + 1}: needs an id")
            continue
        gid = _clean_stage(g["id"])
        for key, kind in (("funnel", list), ("sources", list), ("offer_fit", list), ("weekly", dict), ("map", dict)):
            if key in g and not isinstance(g[key], kind):
                out["errors"].append(f"goal {gid}: `{key}` must be a {'list' if kind is list else 'table'}")
        if gid in seen:
            out["errors"].append(f"goal {gid}: the id is used twice")
            continue
        seen.add(gid)
        funnel = [_clean_stage(s) for s in strings(g.get("funnel")) if str(s).strip()]
        deadline = str(g.get("deadline") or "")
        if deadline:
            try:
                deadline = _dt.date.fromisoformat(deadline).isoformat()
            except ValueError:
                out["errors"].append(f"goal {gid}: deadline {deadline!r} is not YYYY-MM-DD")
                deadline = ""
        weekly = {}
        for k, v in table(g.get("weekly")).items():
            n = _count(v)
            if n is None:
                out["errors"].append(f"goal {gid}: weekly.{k} is not a whole number")
            else:
                weekly[_clean_stage(k)] = n
        out["goals"].append(dict(
            id=gid, title=str(g.get("title") or gid)[:120], deadline=deadline, funnel=funnel, weekly=weekly,
            done_when=str(g.get("done_when") or "").strip()[:160],
            sources=[_clean_stage(s) for s in strings(g.get("sources"))],
            prefix=_clean_stage(g.get("stage_prefix") or ""),
            map={_clean_stage(k): _clean_stage(v) for k, v in table(g.get("map")).items() if isinstance(v, str)},
            offer_fit=[_clean_stage(s) for s in strings(g.get("offer_fit"))]))
    for i, s in enumerate(raw.get("source") if isinstance(raw.get("source"), list) else []):
        if not isinstance(s, dict) or not str(s.get("id") or "").strip():
            out["errors"].append(f"source {i + 1}: needs an id")
            continue
        cmd, f = s.get("command"), s.get("file")
        if isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd):
            out["sources"].append(dict(id=_clean_stage(s["id"]), command=[os.path.expanduser(x) for x in cmd]))
        elif isinstance(f, str) and f.strip():
            out["sources"].append(dict(id=_clean_stage(s["id"]), file=os.path.expanduser(f)))
        else:
            out["errors"].append(f"source {s['id']}: give `command` (a list of strings) or `file`")
    return out


def init(force: bool = False) -> pathlib.Path:
    p = goals_path()
    if p.exists() and not force:
        raise GtmError(f"{p} exists; --force replaces it")
    _write(p, EXAMPLE_GOALS)
    _private_dir(drop_dir())
    return p


# --- writing goals (the app's first run and "Set a number") ----------------------------------------------------

_HEADER = __import__("re").compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\-]+)\s*\]\]?\s*(#.*)?$")


def _toml_str(v: str) -> str:
    return json.dumps(str(v), ensure_ascii=False)


def parse_weekly(pairs: list[str]) -> dict:
    """["conversation=15", "intro=3"] -> {"conversation": 15, "intro": 3}. 0 removes a target."""
    out = {}
    for raw in pairs or []:
        k, sep, v = str(raw).partition("=")
        stage = _clean_stage(k)
        n = _count(int(v)) if sep and v.strip().isdigit() else None
        if not stage or n is None:
            raise GtmError(f"--weekly {raw!r}: give STAGE=N, N a whole number from 0 to {MAX_COUNT}")
        out[stage] = n
    return out


def render_goal(g: dict) -> str:
    """One `[[goal]]` block from a goal as `load_goals` returns it."""
    L = ["[[goal]]", f"id = {_toml_str(g['id'])}", f"title = {_toml_str(g['title'])}"]
    if g.get("done_when"):
        L.append(f"done_when = {_toml_str(g['done_when'])}")
    if g.get("deadline"):
        L.append(f"deadline = {_toml_str(g['deadline'])}")
    for key in ("funnel", "offer_fit", "sources"):
        if g.get(key):
            L.append(f"{key} = [{', '.join(_toml_str(x) for x in g[key])}]")
    if g.get("prefix"):
        L.append(f"stage_prefix = {_toml_str(g['prefix'])}")
    if g.get("map"):
        L += ["[goal.map]"] + [f"{k} = {_toml_str(v)}" for k, v in g["map"].items()]
    if g.get("weekly"):
        L += ["[goal.weekly]"] + [f"{k} = {n}" for k, n in g["weekly"].items()]
    return "\n".join(L) + "\n"


def _goal_spans(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) line ranges of each `[[goal]]` block with its `[goal.*]` tables, in file order."""
    spans, start = [], None
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if not m:
            continue
        name = m.group(1)
        if line.lstrip().startswith("[[") and name == "goal":
            if start is not None:
                spans.append((start, i))
            start = i
        elif start is not None and not name.startswith("goal."):
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(lines)))
    out = []
    for a, b in spans:          # comments and blank lines after a block belong to what follows it
        while b > a + 1 and (not lines[b - 1].strip() or lines[b - 1].lstrip().startswith("#")):
            b -= 1
        out.append((a, b))
    return out


def _check_deadline(deadline: str | None) -> str | None:
    if deadline is None:
        return None
    if deadline == "":
        return ""
    try:
        return _dt.date.fromisoformat(deadline).isoformat()
    except ValueError:
        raise GtmError(f"--deadline {deadline!r} is not YYYY-MM-DD") from None


def add_goal(title: str, *, gid: str = "", weekly: dict | None = None, deadline: str | None = None,
             done_when: str = "", sources: list[str] | None = None, per_day: int | None = None) -> dict:
    """Append one goal to goals.toml, creating the file when there is none. Returns the goal as `load_goals` reads it."""
    title = " ".join(str(title).split())[:120]
    if not title:
        raise GtmError("--title is empty")
    path = goals_path()
    cur = load_goals(path)
    if cur["errors"]:
        raise GtmError(f"{path.name} has errors; fix them first: {cur['errors'][0]}")
    gid = _clean_stage(gid or title)[:40].strip("_") or "goal"
    taken = {g["id"] for g in cur["goals"]}
    base, n = gid, 2
    while gid in taken:
        gid, n = f"{base}_{n}", n + 1
    weekly = weekly or {}
    g = dict(id=gid, title=title, done_when=" ".join(str(done_when or "").split())[:160],
             deadline=_check_deadline(deadline) or "", funnel=list(weekly), weekly={k: v for k, v in weekly.items() if v},
             sources=[_clean_stage(s) for s in (sources or ["growth"])], prefix="", map={}, offer_fit=[])
    if cur["exists"]:
        text = path.read_text(encoding="utf-8")
        if per_day is not None and cur["per_day"] != per_day:
            raise GtmError("--per-day changes an existing file; edit [distribution] per_day in goals.toml")
    else:
        text = "# Goals for `teyla gtm` (docs/GTM.md). Local only: this file never goes into a repo.\nversion = 1\n"
        if per_day is not None:
            text += f"\n[distribution]\nper_day = {per_day}\n"
    text = text.rstrip("\n") + "\n\n" + render_goal(g)
    _write_checked(path, text, gid)
    return next(x for x in load_goals(path)["goals"] if x["id"] == gid)


def set_goal(gid: str, *, weekly: dict | None = None, title: str | None = None, deadline: str | None = None,
             done_when: str | None = None) -> dict:
    """Change one goal in goals.toml. Only that goal's block is rewritten; comments inside it are not kept."""
    path = goals_path()
    cur = load_goals(path)
    if not cur["exists"]:
        raise GtmError("no goals.toml yet: `teyla gtm goal add` creates it")
    if cur["errors"]:
        raise GtmError(f"{path.name} has errors; fix them first: {cur['errors'][0]}")
    gid = _clean_stage(gid)
    order = [g["id"] for g in cur["goals"]]
    if gid not in order:
        raise GtmError(f"no goal {gid!r}; goals: {', '.join(order) or 'none'}")
    g = dict(cur["goals"][order.index(gid)])
    if title is not None:
        g["title"] = " ".join(title.split())[:120] or g["title"]
    if done_when is not None:
        g["done_when"] = " ".join(done_when.split())[:160]
    if deadline is not None:
        g["deadline"] = _check_deadline(deadline) or ""
    if weekly:
        w = dict(g["weekly"])
        for k, n in weekly.items():
            if n:
                w[k] = n
            else:
                w.pop(k, None)
        g["weekly"] = w
        g["funnel"] = (g["funnel"] + [k for k in w if k not in g["funnel"]]) if g["funnel"] else list(w)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    spans = _goal_spans(lines)
    if len(spans) != len(order):
        raise GtmError(f"{path.name}: could not find each [[goal]] block; edit it by hand")
    a, b = spans[order.index(gid)]
    trail = "\n" if b < len(lines) and lines[b].strip() else ""
    text = "".join(lines[:a]) + render_goal(g) + trail + "".join(lines[b:])
    _write_checked(path, text, gid)
    return next(x for x in load_goals(path)["goals"] if x["id"] == gid)


def _write_checked(path: pathlib.Path, text: str, gid: str) -> None:
    """Write goals.toml only when the new text parses and still holds the goal; the old file stays otherwise."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise GtmError(f"the change would break {path.name} ({e}); nothing written") from None
    if not any(isinstance(g, dict) and _clean_stage(g.get("id") or "") == gid for g in doc.get("goal") or []):
        raise GtmError(f"the change lost goal {gid!r}; nothing written")
    _write(path, text)


# --- sources -------------------------------------------------------------------------------------------------

def validate(doc, fallback_id: str = "") -> tuple[dict | None, str]:
    """A source document checked against schema 1: (normalised doc, "") or (None, why)."""
    if not isinstance(doc, dict):
        return None, "not a JSON object"
    sid = _clean_stage(doc.get("source") or fallback_id)
    if not sid:
        return None, "no `source`"
    out = dict(source=sid, counts={}, today={}, waiting={}, stalled={}, channels={}, offer_fit={}, links={},
               updated=None, week=None)
    if not isinstance(doc.get("counts"), dict):
        return None, "no `counts` object"
    for key in ("counts", "today", "waiting", "stalled", "offer_fit"):
        v = doc.get(key)
        if v is None:
            continue
        if not isinstance(v, dict):
            return None, f"`{key}` is not an object"
        for k, n in v.items():
            c = _count(n)
            if c is None:
                return None, f"`{key}.{k}` is not a whole number from 0 to {MAX_COUNT}"
            out[key][_clean_stage(k)] = c
    for ch, stages in (doc.get("channels") or {}).items() if isinstance(doc.get("channels"), dict) else ():
        if isinstance(stages, dict):
            row = {_clean_stage(k): _count(n) for k, n in stages.items() if _count(n) is not None}
            if row:
                out["channels"][_clean_stage(ch)] = row
    for k, url in (doc.get("links") or {}).items() if isinstance(doc.get("links"), dict) else ():
        if isinstance(url, str) and url.startswith(("https://", "http://")) and len(url) <= 500:
            out["links"][_clean_stage(k)] = url
    ts = parse_ts(doc.get("updated")) if doc.get("updated") else None
    if ts is None:
        return None, "no valid `updated` timestamp (ISO 8601)"
    out["updated"] = ts
    wk = doc.get("week")
    if wk is not None:
        try:
            week_range(str(wk))
        except GtmError:
            return None, f"`week` {wk!r} is not YYYY-Www"
        out["week"] = str(wk)
    return out, ""


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=SOURCE_TIMEOUT_S, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {SOURCE_TIMEOUT_S} s"
    except OSError as e:
        return 126, "", str(e)


def _from_text(text: str, sid: str) -> tuple[dict | None, str]:
    try:
        doc = json.loads(text)
    except ValueError:
        return None, "not JSON"
    return validate(doc, sid)


def read_configured(spec: dict, runner=None) -> tuple[dict | None, str]:
    if "command" in spec:
        code, out, err = (runner or _run)(spec["command"])
        if code != 0:
            last = (err or out).strip().splitlines()[-1:] or [f"exit {code}"]
            return None, f"`{' '.join(spec['command'][:2])}` failed: {last[0][:160]}"
        return _from_text(out, spec["id"])
    try:
        return _from_text(pathlib.Path(spec["file"]).read_text(encoding="utf-8"), spec["id"])
    except OSError:
        return None, f"no file at {spec['file']}"


def from_usage(sid: str, counters: dict, at: float | None) -> dict | None:
    """A source document built from a product's cached usage probe, or None when it carries nothing GTM can use."""
    doc = dict(source=sid, counts={}, today={}, waiting={}, stalled={}, channels={}, offer_fit={}, links={},
               updated=at, week=None, via="usage probe")
    for k, v in counters.items():
        try:
            n = int(str(v).strip())
        except ValueError:
            continue
        if n < 0:
            continue
        k = str(k).lower()
        if k.startswith("gtm_waiting_"):
            doc["waiting"][_clean_stage(k[len("gtm_waiting_"):])] = n
        elif k.startswith("gtm_"):
            doc["counts"][_clean_stage(k[4:])] = n
        elif k in USAGE_KEYS:
            where, key = USAGE_KEYS[k]
            doc[where].setdefault(key, n)
    return doc if (doc["counts"] or doc["waiting"]) else None


def ledger_source(rows: list[dict], items: dict, day: str, week: str, now: float) -> dict:
    """The growth ledger as a source: posts and approaches the owner logged, replies and meetings, agent output, and the
    review queue. An agent's claimed attempt counts only under `claimed`."""
    mon, sun = week_range(week)
    counts: dict[str, int] = {}
    today: dict[str, int] = {}
    prep_week: dict[str, int] = {}
    prep_today: dict[str, int] = {}
    claimed = 0

    def add(d, k, n):
        d[k] = d.get(k, 0) + n

    for r in rows:
        d = str(r.get("day") or "")
        if not (mon <= d <= sun):
            continue
        n = r.get("n") if isinstance(r.get("n"), int) and not isinstance(r.get("n"), bool) and 1 <= r["n"] <= 50 else 1
        ev, kind = r.get("ev"), r.get("kind")
        if ev in LEDGER_PREP_EVENTS:
            add(prep_week, LEDGER_PREP_EVENTS[ev], 1)
            if d == day:
                add(prep_today, LEDGER_PREP_EVENTS[ev], 1)
            continue
        stage = None
        if ev == "published":
            stage = "posted"
        elif ev == "attempt":
            if r.get("by") == "agent":
                claimed += n
                continue
            stage = ("posted" if kind == "post" else "approached" if kind in LEDGER_APPROACH_KINDS
                     else "conversation" if kind in LEDGER_CONVERSATION_KINDS else "replied" if kind == "response" else None)
        if stage:
            add(counts, stage, n)
            if d == day:
                add(today, stage, n)
    review = sum(1 for i in items.values() if i.get("status") in ("review", "checked") and i.get("kind") != "episode"
                 and i.get("platform") != "master" and not i.get("hold_reason"))
    formats: dict[str, int] = {}
    for i in items.values():
        if i.get("status") == "published":
            pd = _local_day(i.get("published_at"))
            if mon <= pd <= sun:
                add(formats, f"{i.get('platform') or '?'}/{i.get('format') or '?'}", 1)
    return dict(source="growth", counts=counts, today=today, waiting={"approve": review} if review else {}, stalled={},
                channels={}, offer_fit={}, links={}, updated=now, week=week, via="growth ledger",
                preparation=dict(week=prep_week, today=prep_today), claimed=claimed, formats=formats)


def _local_day(ts) -> str:
    t = parse_ts(ts) if ts else None
    return day_of(t) if t is not None else ""


def collect(goals: dict, day: str, now: float, *, runner=None, usage: dict | None = None,
            usage_ages: dict | None = None, growth_rows: list[dict] | None = None, growth_items: dict | None = None,
            outreach_repos: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """(source docs, status rows). Order of precedence per id: an entry in goals.toml, a dropped file, then the built-in
    usage-probe adapter. Every id a goal names and finds nowhere becomes one `missing` row."""
    week = week_of(day)
    if growth_rows is None or growth_items is None:
        from . import growth
        store = growth.Store()
        growth_rows = store.ledger() if growth_rows is None else growth_rows
        growth_items = store.items() if growth_items is None else growth_items
        if outreach_repos is None:
            try:
                outreach_repos = growth.load_config(store).get("outreach_repos") or []
            except Exception:  # noqa: BLE001 - a broken growth config never breaks the cockpit
                outreach_repos = []
    docs: dict[str, dict] = {"growth": ledger_source(growth_rows, growth_items, day, week, now)}
    status: list[dict] = [dict(id="growth", state="ok", via="growth ledger", line="the growth ledger and its review queue")]

    def accept(doc, via):
        doc.setdefault("via", via)
        age = (now - doc["updated"]) / 86400 if doc.get("updated") else None
        state, line = "ok", via
        if doc.get("week") and doc["week"] != week:
            state, line = "stale", f"{via}: its counts are for {doc['week']}, not {week}; they count as 0 this week"
            for k in ("counts", "today", "stalled", "channels", "offer_fit"):   # last week's numbers say nothing of this one
                doc[k] = {}
        elif age is not None and age > STALE_DAYS:
            state, line = "stale", f"{via}: updated {int(age)} days ago; its counts are shown but may be old"
        if doc.get("updated") is None or day_of(doc["updated"]) != day:
            doc["today"] = {}                  # a count for "today" from another day is not today's
        docs[doc["source"]] = doc
        status.append(dict(id=doc["source"], state=state, via=via, line=line))

    for spec in goals.get("sources") or []:
        if spec["id"] in docs:
            continue
        doc, why = read_configured(spec, runner)
        if doc is None:
            status.append(dict(id=spec["id"], state="broken", via="goals.toml", line=why))
            docs[spec["id"]] = None  # type: ignore[assignment]   # reserve the id: a broken source is not replaced silently
            continue
        doc["source"] = spec["id"]
        accept(doc, "command" if "command" in spec else "file")
    d = drop_dir()
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            doc, why = _from_text(f.read_text(encoding="utf-8"), f.stem)
        except OSError as e:
            doc, why = None, str(e)
        sid = (doc or {}).get("source") or _clean_stage(f.stem)
        if sid in docs:
            continue
        if doc is None:
            status.append(dict(id=sid, state="broken", via=f"sources/{f.name}", line=f"sources/{f.name}: {why}"))
            docs[sid] = None  # type: ignore[assignment]
            continue
        accept(doc, f"sources/{f.name}")
    wanted = {s for g in goals.get("goals") or [] for s in g["sources"]}
    adapters = list(dict.fromkeys([*USAGE_ADAPTERS, *[_clean_stage(r) for r in outreach_repos or []]]))
    if usage is None:
        try:
            from . import portfolio
            usage, usage_ages = portfolio.load_usage_cache(), portfolio.load_usage_ages()
        except Exception:  # noqa: BLE001
            usage, usage_ages = {}, {}
    for sid in adapters:
        if sid in docs or (sid not in wanted and sid not in usage):
            continue
        doc = from_usage(sid, usage.get(sid) or {}, (usage_ages or {}).get(sid)) if sid in usage else None
        if doc is None:
            status.append(dict(id=sid, state="missing", via="usage probe",
                               line=f"no command in goals.toml, no sources/{sid}.json and no GTM counters in its cached "
                                    f"usage probe (`teyla products` refreshes it)"))
            docs[sid] = None  # type: ignore[assignment]
            continue
        if doc["updated"] is None:
            doc["updated"] = now
        doc["week"] = week_of(day_of(doc["updated"]))   # a probe from last week says nothing of this week's counts
        accept(doc, "usage probe")
    for sid in sorted(wanted - set(docs)):
        status.append(dict(id=sid, state="missing", via="", line=f"a goal names it, but nothing feeds it: drop "
                                                                 f"~/.teyla/gtm/sources/{sid}.json or add a [[source]]"))
    return [v for v in docs.values() if v], status


# --- the counters --------------------------------------------------------------------------------------------

def counter_of(stage: str) -> str:
    stage = split_stage(stage)[1]
    return "distribution" if stage in DISTRIBUTION_STAGES else "outcomes" if stage in OUTCOME_STAGES else "preparation"


def counters(docs: list[dict]) -> dict:
    """Preparation, distribution and outcomes for the week and for today, summed over every source."""
    out = {k: dict(week=0, today=0, by_stage={}) for k in ("preparation", "distribution", "outcomes")}
    claimed = 0
    for doc in docs:
        for span in ("week", "today"):
            src = doc["counts"] if span == "week" else doc["today"]
            for stage, n in src.items():
                c = out[counter_of(stage)]
                c[span] += n
                if span == "week":
                    c["by_stage"][stage] = c["by_stage"].get(stage, 0) + n
            for stage, n in ((doc.get("preparation") or {}).get(span) or {}).items():
                out["preparation"][span] += n
                if span == "week":
                    out["preparation"]["by_stage"][stage] = out["preparation"]["by_stage"].get(stage, 0) + n
        claimed += doc.get("claimed") or 0
    out["distribution"]["claimed_by_agents"] = claimed
    return out


def goal_funnel(goal: dict, docs: list[dict]) -> dict:
    by_id = {d["source"]: d for d in docs}
    feeds = [by_id[s] for s in goal["sources"] if s in by_id]

    def resolve(raw: str) -> str | None:
        """The goal's stage for a source's stage name, or None when the stage belongs to another funnel."""
        if raw in goal["map"]:
            return goal["map"][raw]
        pre, name = split_stage(raw)
        if pre and pre != goal["prefix"]:
            return None
        return goal["map"].get(name, name)

    stages = goal["funnel"] or sorted({s for d in feeds for k in d["counts"] if (s := resolve(k))})
    count = {s: 0 for s in stages}
    stalled = {s: 0 for s in stages}
    fit = {k: 0 for k in goal["offer_fit"]}
    for d in feeds:
        for raw, n in d["counts"].items():
            s = resolve(raw)
            if s in count:
                count[s] += n
        for raw, n in d["stalled"].items():
            s = resolve(raw)
            if s in stalled:
                stalled[s] += n
        for raw, n in d["offer_fit"].items():
            pre, k = split_stage(raw)
            if k in fit and (not pre or pre == goal["prefix"]):
                fit[k] += n
    rows, prev = [], None
    for s in stages:
        conv = round(count[s] / count[prev], 2) if prev is not None and count[prev] else None
        rows.append(dict(stage=s, count=count[s], target=goal["weekly"].get(s), conversion=conv,
                         counter=counter_of(s), stalled=stalled[s]))
        prev = s
    return dict(rows=rows, offer_fit=fit, fed_by=[d["source"] for d in feeds],
                unfed=[s for s in goal["sources"] if s not in by_id])


def days_left(deadline: str, day: str) -> int | None:
    if not deadline:
        return None
    return (_dt.date.fromisoformat(deadline) - _dt.date.fromisoformat(day)).days


def _waiting(docs: list[dict], kind: str) -> dict:
    """One waiting kind over every source. A prefixed key (`network.send`) counts under its last part (`send`)."""
    by, links = {}, {}
    for d in docs:
        n = sum(v for k, v in d["waiting"].items() if split_stage(k)[1] == kind)
        if n:
            by[d["source"]] = n
            url = d["links"].get(kind) or next((u for k, u in d["links"].items() if split_stage(k)[1] == kind), None)
            if url:
                links[d["source"]] = url
    return dict(total=sum(by.values()), by_source=by, links=links)


def next_actions(t: dict) -> list[dict]:
    """The short ordered list the cockpit leads with: replies, approvals, sends, then the distribution gap."""
    acts = []
    if t["reply"]["total"]:
        acts.append(dict(kind="reply", count=t["reply"]["total"], label=f"answer {t['reply']['total']} replies",
                         sources=sorted(t["reply"]["by_source"])))
    if t["approve"]["total"]:
        acts.append(dict(kind="approve", count=t["approve"]["total"], label=f"approve or skip {t['approve']['total']} drafts",
                         command="teyla growth review" if t["approve"]["by_source"].get("growth") else "",
                         sources=sorted(t["approve"]["by_source"])))
    if t["send"]["total"]:
        acts.append(dict(kind="send", count=t["send"]["total"], label=f"send {t['send']['total']} approved approaches by hand",
                         sources=sorted(t["send"]["by_source"])))
    if t["follow_up"]["total"]:
        acts.append(dict(kind="follow_up", count=t["follow_up"]["total"], label=f"follow up {t['follow_up']['total']}",
                         sources=sorted(t["follow_up"]["by_source"])))
    dist = t["distribution"]
    if dist["target"] and dist["today"] < dist["target"]:
        gap = dist["target"] - dist["today"]
        acts.append(dict(kind="distribute", count=gap, label=f"{gap} more posts or approaches to reach {dist['target']} today",
                         command="teyla growth log --kind <kind>"))
    return acts


HISTORY_WEEKS = 7     # past weeks shown beside this one: eight in all


def past_weeks(week: str, n: int) -> list[str]:
    """The n ISO weeks before `week`, oldest first."""
    mon = _dt.date.fromisoformat(week_range(week)[0])
    return [week_of((mon - _dt.timedelta(weeks=i)).isoformat()) for i in range(n, 0, -1)]


def goal_history(gid: str, stage: str, weeks: list[str]) -> list[int | None]:
    """A stage's count in each saved week (`save_week`); None for a week no run saved."""
    out: list[int | None] = []
    for w in weeks:
        n = None
        try:
            rep = json.loads((weeks_dir() / f"{w}.json").read_text(encoding="utf-8"))
            g = next((x for x in rep.get("goals") or [] if x.get("id") == gid), None)
            r = next((x for x in (g or {}).get("funnel") or [] if x.get("stage") == stage), None)
            n = _count(r.get("count")) if r else (0 if g else None)
        except (OSError, ValueError, AttributeError):
            n = None
        out.append(n)
    return out


def today_report(goals: dict, docs: list[dict], status: list[dict], day: str) -> dict:
    c = counters(docs)
    t = dict(version=VERSION, day=day, week=week_of(day), has_goals=goals["exists"])
    for kind in WAITING_KINDS:
        t[kind] = _waiting(docs, kind)
    t["distribution"] = dict(today=c["distribution"]["today"], target=goals.get("per_day"), week=c["distribution"]["week"],
                             claimed_by_agents=c["distribution"]["claimed_by_agents"])
    t["preparation"] = dict(today=c["preparation"]["today"], week=c["preparation"]["week"])
    t["outcomes"] = dict(today=c["outcomes"]["today"], week=c["outcomes"]["week"])
    t["week_end"] = week_range(t["week"])[1]
    t["goals"] = []
    past = past_weeks(t["week"], HISTORY_WEEKS)
    for g in goals["goals"]:
        f = goal_funnel(g, docs)
        dl = days_left(g["deadline"], day)
        targets = [dict(stage=r["stage"], count=r["count"], target=r["target"], counter=r["counter"],
                        history=[dict(week=w, count=n) for w, n in zip(past, goal_history(g["id"], r["stage"], past))]
                        + [dict(week=t["week"], count=r["count"])])
                   for r in f["rows"] if r["target"] is not None]
        # How far the week's outcomes are from their targets. Distribution and preparation never count toward a goal.
        short = sum(max(0, x["target"] - x["count"]) for x in targets if x["counter"] == "outcomes")
        t["goals"].append(dict(id=g["id"], title=g["title"], done_when=g.get("done_when") or None,
                               deadline=g["deadline"] or None, days_left=dl,
                               weeks_left=None if dl is None else max(0, -(-dl // 7)),
                               targets=targets, short=short, fed_by=f["fed_by"], unfed=f["unfed"]))
    t["next"] = next_actions(t)
    t["sources"] = status
    t["doctor"] = doctor_lines(goals, status)
    return t


def week_report(goals: dict, docs: list[dict], status: list[dict], week: str, day: str) -> dict:
    mon, sun = week_range(week)
    c = counters(docs)
    channels: dict[str, dict[str, int]] = {}
    for d in docs:
        for ch, stages in d["channels"].items():
            row = channels.setdefault(ch, {})
            for s, n in stages.items():
                row[s] = row.get(s, 0) + n
    out_channels = {ch: {s: n for s, n in st.items() if counter_of(s) == "outcomes"} for ch, st in channels.items()}
    formats: dict[str, int] = {}
    for d in docs:
        for k, n in (d.get("formats") or {}).items():
            formats[k] = formats.get(k, 0) + n
    gl = []
    for g in goals["goals"]:
        f = goal_funnel(g, docs)
        missed = {r["stage"]: r["target"] - r["count"] for r in f["rows"] if r["target"] is not None and r["count"] < r["target"]}
        gl.append(dict(id=g["id"], title=g["title"], deadline=g["deadline"] or None, days_left=days_left(g["deadline"], day),
                       funnel=f["rows"], offer_fit=f["offer_fit"], fed_by=f["fed_by"], unfed=f["unfed"],
                       stalled={r["stage"]: r["stalled"] for r in f["rows"] if r["stalled"]},
                       missed=missed, next_targets=dict(g["weekly"])))
    return dict(version=VERSION, week=week, start=mon, end=sun, day=day, has_goals=goals["exists"],
                counters=c, goals=gl, channels={k: v for k, v in out_channels.items() if v}, formats=formats,
                sources=status, doctor=doctor_lines(goals, status))


def doctor_lines(goals: dict, status: list[dict]) -> list[str]:
    lines = []
    if not goals["exists"]:
        lines.append("goals: no ~/.teyla/gtm/goals.toml; run `teyla gtm init` and edit the example")
    lines += [f"goals: {e}" for e in goals["errors"]]
    lines += [f"{s['id']}: {s['state']}: {s['line']}" for s in status if s["state"] != "ok"]
    return lines


def save_week(rep: dict) -> None:
    """Keep the week's numbers so `teyla gtm week --week` can show a week the sources no longer report."""
    try:
        _write(weeks_dir() / f"{rep['week']}.json", json.dumps(rep, indent=2) + "\n")
    except OSError:
        pass


# --- rendering -----------------------------------------------------------------------------------------------

def _by(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))


def render_today(t: dict) -> str:
    L = [f"GTM today {t['day']} ({t['week']})"]
    if t["next"]:
        L.append("do next:")
        for i, a in enumerate(t["next"], 1):
            extra = f"  `{a['command']}`" if a.get("command") else (f"  ({', '.join(a['sources'])})" if a.get("sources") else "")
            L.append(f"  {i}. {a['label']}{extra}")
    else:
        L.append("do next: nothing waits for you")
    d = t["distribution"]
    tgt = f"/{d['target']}" if d["target"] else ""
    L.append(f"distribution today {d['today']}{tgt} · this week {d['week']}"
             + (f" · {d['claimed_by_agents']} claimed by agents, not counted" if d["claimed_by_agents"] else ""))
    L.append(f"outcomes this week {t['outcomes']['week']} · preparation this week {t['preparation']['week']} (agent work, not a result)")
    for g in t["goals"]:
        dl = f", {g['days_left']} days left" if g["days_left"] is not None else ""
        L.append(f"{g['title']} (deadline {g['deadline'] or 'none'}{dl})")
        L.append("  " + ("  ".join(f"{r['stage']} {r['count']}/{r['target']}" for r in g["targets"]) or "no weekly targets"))
    for line in t["doctor"]:
        L.append(f"doctor  {line}")
    return "\n".join(L) + "\n"


def render_week(w: dict) -> str:
    c = w["counters"]
    L = [f"GTM week {w['week']} ({w['start']} to {w['end']})",
         f"preparation {c['preparation']['week']} (agent work) · distribution {c['distribution']['week']} · "
         f"outcomes {c['outcomes']['week']}"]
    for g in w["goals"]:
        dl = f", {g['days_left']} days left" if g["days_left"] is not None else ""
        L.append(f"{g['title']} (deadline {g['deadline'] or 'none'}{dl})")
        for r in g["funnel"]:
            tgt = f"/{r['target']}" if r["target"] is not None else ""
            conv = f"  {int(r['conversion'] * 100)}% of the stage before" if r["conversion"] is not None else ""
            st = f"  {r['stalled']} stalled" if r["stalled"] else ""
            L.append(f"  {r['stage']:<14} {r['count']}{tgt}{conv}{st}")
        if any(g["offer_fit"].values()):
            L.append(f"  offer fit: {_by(g['offer_fit'])}")
        if g["missed"]:
            L.append(f"  missed: {_by(g['missed'])}")
        if g["unfed"]:
            L.append(f"  not fed: {', '.join(g['unfed'])}")
        L.append(f"  next week: {_by(g['next_targets']) or 'no targets'} (edit goals.toml to change)")
    if w["channels"]:
        L.append("outcomes by channel: " + "; ".join(f"{ch} {_by(st)}" for ch, st in sorted(w["channels"].items())))
    else:
        L.append("outcomes by channel: no source reports channels yet")
    if w["formats"]:
        L.append("posts by platform/format: " + _by(w["formats"]))
    for line in w["doctor"]:
        L.append(f"doctor  {line}")
    return "\n".join(L) + "\n"


# --- the command line ----------------------------------------------------------------------------------------

def build(now: float, runner=None) -> tuple[dict, list[dict], list[dict], str]:
    goals = load_goals()
    day = day_of(now)
    docs, status = collect(goals, day, now, runner=runner)
    return goals, docs, status, day


def cmd_today(args) -> int:
    now = time.time()
    goals, docs, status, day = build(now)
    t = today_report(goals, docs, status, day)
    save_week(week_report(goals, docs, status, week_of(day), day))
    print(json.dumps(t, indent=2) if getattr(args, "json", False) else render_today(t), end="\n" if getattr(args, "json", False) else "")
    return 0


def cmd_week(args) -> int:
    now = time.time()
    day = day_of(now)
    try:
        week = args.week or week_of(day)
        week_range(week)
    except GtmError as e:
        print(f"teyla gtm: {e}", file=sys.stderr)
        return 2
    if week != week_of(day):
        try:
            w = json.loads((weeks_dir() / f"{week}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"teyla gtm: no saved numbers for {week}; a week is saved each time `teyla gtm` runs in it", file=sys.stderr)
            return 1
    else:
        goals, docs, status, _ = build(now)
        w = week_report(goals, docs, status, week, day)
        save_week(w)
    print(json.dumps(w, indent=2) if args.json else render_week(w), end="\n" if args.json else "")
    return 0


def cmd_init(args) -> int:
    try:
        p = init(args.force)
    except GtmError as e:
        print(f"teyla gtm: {e}", file=sys.stderr)
        return 1
    print(f"wrote {p}; edit the goals, titles, deadlines and weekly targets. Sources drop JSON in {drop_dir()}")
    return 0


def cmd_doctor(args) -> int:
    goals, _docs, status, _ = build(time.time())
    print(f"  {'ok' if goals['exists'] and not goals['errors'] else 'MISSING':<8} {'goals':<12} "
          + (str(goals_path()) if goals["exists"] and not goals["errors"] else
             (goals["errors"][0] if goals["errors"] else "no goals.toml: run `teyla gtm init`")))
    for s in status:
        print(f"  {s['state'] if s['state'] == 'ok' else s['state'].upper():<8} {s['id']:<12} {s['line']}")
    return 0


def cmd_goal(args) -> int:
    try:
        weekly = parse_weekly(args.weekly)
        if args.goal_cmd == "add":
            g = add_goal(args.title, gid=args.id or "", weekly=weekly, deadline=args.deadline, done_when=args.done_when or "",
                         sources=args.source or None, per_day=args.per_day)
        else:
            if not (weekly or args.title is not None or args.deadline is not None or args.done_when is not None):
                raise GtmError("nothing to change: give --weekly, --title, --deadline or --done-when")
            g = set_goal(args.id, weekly=weekly, title=args.title, deadline=args.deadline, done_when=args.done_when)
    except GtmError as e:
        print(f"teyla gtm: {e}", file=sys.stderr)
        return 2
    out = dict(id=g["id"], title=g["title"], done_when=g.get("done_when") or None, deadline=g["deadline"] or None,
               weekly=g["weekly"], sources=g["sources"])
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"{'added' if args.goal_cmd == 'add' else 'changed'} goal {g['id']}: {g['title']} · "
              + (_by(g["weekly"]) or "no weekly numbers yet"))
    return 0


def register(sp):
    q = sp.add_parser("gtm", help="the GTM cockpit: what waits for you today, the week's funnel per goal; never sends",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_today, json=False)
    q.add_argument("--json", action="store_true", help="today's screen as JSON (docs/GTM.md)")
    g = q.add_subparsers(dest="gtm_cmd")
    a = g.add_parser("today", help="approvals, items to send, replies, distribution vs target, outcomes vs targets, deadlines")
    a.set_defaults(fn=cmd_today)
    a.add_argument("--json", action="store_true")
    a = g.add_parser("week", help="the weekly review: funnel and conversion per goal, stalled, channels, next targets")
    a.set_defaults(fn=cmd_week)
    a.add_argument("--week", metavar="YYYY-Www", help="a past week saved by an earlier run (default: this week)")
    a.add_argument("--json", action="store_true")
    a = g.add_parser("init", help="write ~/.teyla/gtm/goals.toml with neutral example goals")
    a.set_defaults(fn=cmd_init)
    a.add_argument("--force", action="store_true")
    a = g.add_parser("doctor", help="each source: ok, stale, broken or missing")
    a.set_defaults(fn=cmd_doctor)
    a = g.add_parser("goal", help="add a goal or change one in goals.toml (the app's first run uses this)")
    gg = a.add_subparsers(dest="goal_cmd", required=True)
    b = gg.add_parser("add", help="append a goal; creates goals.toml when there is none")
    b.set_defaults(fn=cmd_goal)
    b.add_argument("--title", required=True, help="the outcome, in your words")
    b.add_argument("--id", help="a short id (default: from the title)")
    b.add_argument("--per-day", type=int, help="the daily send target, when this creates goals.toml")
    b.add_argument("--source", action="append", metavar="ID", help="a source that feeds it (default: growth)")
    c = gg.add_parser("set", help="change one goal's weekly numbers, title, deadline or done-when; STAGE=0 removes a number")
    c.set_defaults(fn=cmd_goal)
    c.add_argument("id")
    c.add_argument("--title")
    for x in (b, c):
        x.add_argument("--weekly", action="append", metavar="STAGE=N", help="a weekly number, e.g. conversation=15")
        x.add_argument("--deadline", metavar="YYYY-MM-DD")
        x.add_argument("--done-when", help="what reaching the goal means, one line")
        x.add_argument("--json", action="store_true")
    return q
