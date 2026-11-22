"""`teyla parity` — the parity gate ledger (POLICY §14): a secondary platform gets a feature only after a
primary build reached a person and the owner liked it.

A dated trigger in `[productize.triggers]` says a platform may exist. It never says a port may run now.
This module keeps `docs/parity.toml` in the product repo (committed, reviewed like code):

    [candidate]            the newest primary build a person can install
    [[accepted]]           the owner's positive feedback on a primary build
    [train.<platform>]     closed | queued | open, the synced-to commit, the tip and the expiry
    [[override]]           the owner's explicit "now, skip the gate", with an expiry

`gate(repo, platform, today)` answers whether a platform's files may change now. The push check
(`teyla platform check`) and the edit hook (`teyla platform hook`) both ask it. Dates are TOML dates; every
function that reads the clock takes `today`, so tests inject it.

    teyla parity init | status | deliver | accept | queue | open | sync | override
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import tomllib

LEDGER = "docs/parity.toml"
STATES = ("closed", "queued", "open")
SETTLE_DAYS = 3
SETTLE_DAYS_ENGINE = 7
TRAIN_DAYS = 7
SOURCES = ("chat", "testflight", "in-app")
HEADER = ("# Parity gate ledger (POLICY §14). Written by `teyla parity`; hand edits are fine.\n"
          "# candidate: the newest primary build a person can install. accepted: the owner's positive feedback on a\n"
          "# primary build. train.<platform>: closed | queued | open. override: the owner's explicit \"now, skip the gate\".\n")


class ParityError(Exception):
    """A refusal with a reason; the command prints it and exits 1."""


# --- the ledger file -------------------------------------------------------------------------

def ledger_path(repo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(repo) / LEDGER


def parse(text: str) -> dict | None:
    return parse_checked(text)[0]


def validate(data: dict) -> str | None:
    """What is wrong with a parsed ledger, or None: every train needs a known state."""
    trains = data.get("train") or {}
    if not isinstance(trains, dict):
        return "train is not a table"
    for plat, t in trains.items():
        if not isinstance(t, dict) or str(t.get("state") or "closed") not in STATES:
            return f"train.{plat} has an unknown state"
    return None


def parse_checked(text: str) -> tuple[dict | None, str | None]:
    """`(ledger, None)`, or `(None, why)` for text that does not parse or does not validate."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return None, str(e)
    bad = validate(data)
    return (None, bad) if bad else (data, None)


def broken(why: str) -> str:
    return f"{LEDGER} does not parse: {why}; fix it or `teyla parity init`"


def read(repo: pathlib.Path) -> tuple[dict | None, str | None]:
    """The working-tree ledger: `(None, None)` when absent, `(None, why)` when broken."""
    try:
        text = ledger_path(repo).read_text(encoding="utf-8")
    except OSError:
        return None, None
    return parse_checked(text)


def load(repo: pathlib.Path) -> dict | None:
    """The ledger as it is in the working tree; None when absent or unreadable."""
    return read(repo)[0]


def read_at(repo: pathlib.Path, rev: str) -> tuple[dict | None, str | None]:
    """The ledger as committed at `rev` (an uncommitted opening is not pushed): `(None, None)` when absent."""
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{LEDGER}"], capture_output=True)
    return parse_checked(p.stdout.decode("utf-8", "replace")) if p.returncode == 0 else (None, None)


def load_at(repo: pathlib.Path, rev: str) -> dict | None:
    return read_at(repo, rev)[0]


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _table(head: str, row: dict) -> str:
    return "\n".join([head] + [f"{k} = {_val(v)}" for k, v in row.items()]) + "\n"


def dumps(data: dict) -> str:
    """The small TOML writer: tables and arrays of tables holding strings, bools, ints, dates, string lists."""
    out = [HEADER]
    if isinstance(data.get("candidate"), dict):
        out.append(_table("[candidate]", data["candidate"]))
    for row in data.get("accepted") or []:
        out.append(_table("[[accepted]]", row))
    for plat, row in (data.get("train") or {}).items():
        out.append(_table(f"[train.{plat}]", row))
    for row in data.get("override") or []:
        out.append(_table("[[override]]", row))
    return "\n".join(out)


def save(repo: pathlib.Path, data: dict) -> None:
    p = ledger_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(data), encoding="utf-8")


# --- the repo --------------------------------------------------------------------------------

def _git(repo: pathlib.Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def read_manifest(repo: pathlib.Path) -> dict:
    try:
        return tomllib.loads((pathlib.Path(repo) / "teyla.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def productize(repo: pathlib.Path) -> dict:
    pz = read_manifest(repo).get("productize")
    return pz if isinstance(pz, dict) else {}


def secondaries(pz: dict) -> list[str]:
    primary = str(pz.get("primary") or "").strip()
    return [str(p) for p in (pz.get("platforms") or []) if str(p) != primary]


def _need(repo: pathlib.Path) -> dict:
    data = load(repo)
    if data is None:
        raise ParityError(f"no readable {LEDGER}: run `teyla parity init`")
    return data


def _date(text, default: datetime.date) -> datetime.date:
    if text in (None, ""):
        return default
    if isinstance(text, datetime.date):
        return text
    try:
        return datetime.date.fromisoformat(str(text))
    except ValueError as e:
        raise ParityError(f"bad date '{text}' (want YYYY-MM-DD)") from e


# --- the gate --------------------------------------------------------------------------------

def _as_date(v) -> datetime.date | None:
    return v if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime) else None


def settle_days(entry: dict) -> int:
    return SETTLE_DAYS_ENGINE if entry.get("engine") else SETTLE_DAYS


def _eligible(data: dict, today: datetime.date) -> dict | None:
    """The newest accepted entry whose settle time has passed."""
    best = None
    for e in data.get("accepted") or []:
        d = _as_date(e.get("date"))
        if d and d + datetime.timedelta(days=settle_days(e)) <= today:
            if best is None or d >= _as_date(best["date"]):
                best = e
    return best


def _closed_reason(data: dict, today: datetime.date) -> str:
    """Why a closed train is closed, and what it waits for."""
    if _eligible(data, today):
        return "the owner's feedback is accepted and settled: open a train"
    accepted = [e for e in data.get("accepted") or [] if _as_date(e.get("date"))]
    if accepted:
        e = max(accepted, key=lambda x: x["date"])
        until = e["date"] + datetime.timedelta(days=settle_days(e))
        return f"waits for the owner's accepted build {e.get('build', '?')} to settle until {until}"
    cand = data.get("candidate") if isinstance(data.get("candidate"), dict) else None
    if cand:
        return (f"waits for the owner's feedback on {cand.get('build', '?')}, "
                f"delivered {cand.get('delivered', '?')}")
    return "waits for a primary build to reach a person"


def gate_from(data: dict | None, platform: str, today: datetime.date) -> tuple[bool, str]:
    """Pure: the ledger and the day in, `(open, reason)` out."""
    if data is None:
        return True, "no parity ledger"
    for o in data.get("override") or []:
        exp = _as_date(o.get("expires"))
        if o.get("platform") == platform and exp and exp >= today:
            return True, f"owner override until {exp}"
    train = (data.get("train") or {}).get(platform)
    if not isinstance(train, dict):
        return False, "no train entry in the ledger"
    state = str(train.get("state") or "closed")
    if state == "open":
        exp = _as_date(train.get("expires"))
        if exp and exp >= today:
            return True, f"train open until {exp}"
        return False, f"the train expired on {exp or 'an unknown date'}: " + _closed_reason(data, today)
    if state == "queued":
        return False, f"queued ({train.get('queued_ref') or 'owner request'}); " + _closed_reason(data, today)
    return False, _closed_reason(data, today)


def gate(repo_root, platform: str, today: datetime.date | None = None) -> tuple[bool, str]:
    return gate_from(load(pathlib.Path(repo_root)), platform, today or datetime.date.today())


# --- commands --------------------------------------------------------------------------------

def init(repo: pathlib.Path, today: datetime.date) -> str:
    pz = productize(repo)
    if not str(pz.get("primary") or "").strip():
        raise ParityError("[productize] primary is not set in teyla.toml; set it first")
    if ledger_path(repo).exists():
        raise ParityError(f"{LEDGER} already exists")
    base = _git(repo, "rev-parse", "origin/main") or _git(repo, "rev-parse", "HEAD")
    save(repo, {"train": {p: {"state": "closed", "base": base} for p in secondaries(pz)}})
    return f"wrote {LEDGER}: {', '.join(secondaries(pz)) or 'no secondary platform'} closed at {base[:12] or '?'}"


def deliver(repo, build: str, commit: str, to: str, today: datetime.date) -> str:
    data = load(repo) or {}
    data["candidate"] = {"build": build, "commit": commit, "delivered": today, "to": to}
    save(repo, data)
    return f"candidate: {build} delivered {today} to {to}"


def accept(repo, *, build, commit, source, ref, summary, features, engine, today) -> str:
    if source not in SOURCES:
        raise ParityError(f"source must be one of {', '.join(SOURCES)}")
    data = _need(repo)
    data.setdefault("accepted", []).append({
        "build": build, "commit": commit, "date": today, "source": source, "ref": ref, "summary": summary,
        "features": features, "engine": bool(engine)})
    save(repo, data)
    return f"accepted {build} on {today}; settles {settle_days({'engine': engine})} days"


def _train(repo: pathlib.Path, data: dict, platform: str) -> dict:
    pz = productize(repo)
    if platform not in secondaries(pz) and platform not in (data.get("train") or {}):
        raise ParityError(f"{platform} is not a secondary platform of this repo")
    return data.setdefault("train", {}).setdefault(platform, {"state": "closed", "base": ""})


def queue(repo, platform: str, ref: str) -> str:
    data = _need(repo)
    t = _train(repo, data, platform)
    if t.get("state") == "open":
        raise ParityError(f"{platform} is already open")
    t.update(state="queued", queued_ref=ref)
    save(repo, data)
    return f"{platform} queued: the request waits for the owner's feedback; nothing is open"


def open_train(repo, platform: str, today: datetime.date) -> str:
    data = _need(repo)
    t = _train(repo, data, platform)
    e = _eligible(data, today)
    if e is None:
        raise ParityError(f"cannot open {platform}: {_closed_reason(data, today)}")
    exp = today + datetime.timedelta(days=TRAIN_DAYS)
    t.update(state="open", tip=e.get("commit", ""), opened=today, expires=exp)
    t.pop("queued_ref", None)
    save(repo, data)
    return f"{platform} open until {exp}: port up to {str(e.get('commit', ''))[:12]} ({e.get('build', '?')})"


def sync(repo, platform: str, to: str) -> str:
    data = _need(repo)
    t = _train(repo, data, platform)
    data["train"][platform] = {"state": "closed", "base": to}
    save(repo, data)
    return f"{platform} closed, synced to {to[:12]}"


def override(repo, platform: str, ref: str, summary: str, days: int, today: datetime.date) -> str:
    from . import platform_gate
    data = _need(repo)
    exp = today + datetime.timedelta(days=days)
    try:
        platform_gate.log_row(repo, "parity-override", [platform], f"{today}..{exp}")
    except platform_gate.GateError as e:
        raise ParityError(str(e)) from e
    data.setdefault("override", []).append({"platform": platform, "date": today, "ref": ref,
                                            "summary": summary, "expires": exp})
    save(repo, data)
    return f"override: {platform} may change until {exp} (logged)"


# --- status ----------------------------------------------------------------------------------

def debt(repo: pathlib.Path, base: str, primary_paths, today: datetime.date) -> tuple[int | None, int | None]:
    """Commits touching the primary's paths since `base`, and days since `base`; None when unknown."""
    if not base or not _git(repo, "rev-parse", "--verify", "-q", base + "^{commit}"):
        return None, None
    specs = [":(glob)" + str(p) for p in ([primary_paths] if isinstance(primary_paths, str) else primary_paths or [])
             if not str(p).startswith("!")]
    args = ["rev-list", "--count", f"{base}..HEAD"] + (["--"] + specs if specs else [])
    n = _git(repo, *args)
    when = _git(repo, "show", "-s", "--format=%cs", base)
    days = None
    try:
        days = (today - datetime.date.fromisoformat(when)).days
    except ValueError:
        pass
    return (int(n) if n.isdigit() else None), days


def status(repo: pathlib.Path, today: datetime.date) -> dict:
    from . import platform_gate
    pz = productize(repo)
    data = load(repo)
    primary = str(pz.get("primary") or "").strip()
    paths = pz.get("paths") if isinstance(pz.get("paths"), dict) else {}
    triggers = pz.get("triggers") if isinstance(pz.get("triggers"), dict) else {}
    rows = []
    for plat in secondaries(pz):
        problem = platform_gate.trigger_problem(triggers, plat)
        is_open, reason = gate_from(data, plat, today)
        train = ((data or {}).get("train") or {}).get(plat) or {}
        state = "frozen-by-trigger-missing" if problem else (str(train.get("state") or "closed") if data else "no-ledger")
        if state == "open" and not is_open:
            state = "closed"
        if problem:
            reason = f"{problem}: add a dated [productize.triggers] entry"
        n, days = debt(repo, str(train.get("base") or ""), paths.get(primary), today)
        rows.append({"platform": plat, "state": state, "open": is_open and not problem, "reason": reason,
                     "debt_commits": n, "debt_days": days, "expires": _val(train["expires"]).strip('"')
                     if state == "open" and train.get("expires") else None,
                     "next": _next_step(state, is_open, reason, data, plat, today)})
    return {"repo": str(repo), "primary": primary, "ledger": data is not None, "platforms": rows}


def _next_step(state, is_open, reason, data, plat, today) -> str:
    if state == "frozen-by-trigger-missing":
        return "write the dated trigger first"
    if state == "no-ledger":
        return "teyla parity init"
    if is_open:
        return f"port to the tip, then `teyla parity sync {plat} --to <sha>`"
    if data and _eligible(data, today):
        return f"teyla parity open {plat}"
    return reason


def line(st: dict) -> str:
    """The one-line session summary."""
    parts = []
    for r in st["platforms"]:
        if r["state"] == "open":
            parts.append(f"{r['platform']} open until {r['expires']}")
        else:
            bit = f"{r['platform']} {r['state']}"
            if r["debt_commits"] is not None:
                bit += f", {r['debt_commits']} commits / {r['debt_days'] if r['debt_days'] is not None else '?'} days behind"
            parts.append(bit)
    return ("parity: " + "; ".join(parts) + " — teyla parity status") if parts else ""


def render(st: dict) -> str:
    if not st["platforms"]:
        return "parity: no secondary platform declared\n"
    out = [f"parity (primary {st['primary'] or '?'}):"]
    for r in st["platforms"]:
        behind = ""
        if r["debt_commits"] is not None:
            behind = f"  debt {r['debt_commits']} commits / {r['debt_days'] if r['debt_days'] is not None else '?'} days"
        out.append(f"  {r['platform']}: {r['state']}{behind}")
        out.append(f"    why: {r['reason']}")
        out.append(f"    next: {r['next']}")
    return "\n".join(out) + "\n"


# --- argparse --------------------------------------------------------------------------------

def cmd_parity(args) -> int:
    repo = pathlib.Path(getattr(args, "repo", None) or ".").expanduser().resolve()
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top:
        repo = pathlib.Path(top)
    verb = args.verb
    try:
        today = _date(getattr(args, "date", None), datetime.date.today())
        if verb == "init":
            msg = init(repo, today)
        elif verb == "status":
            st = status(repo, today)
            if getattr(args, "json", False):
                print(json.dumps(st, indent=2))
            elif getattr(args, "line", False):
                text = line(st) if st["ledger"] else ""
                if text:
                    print(text)
            else:
                print(render(st), end="")
            return 0
        elif verb == "deliver":
            msg = deliver(repo, _req(args, "build"), _req(args, "commit"), args.to or "owner", today)
        elif verb == "accept":
            feats = [f.strip() for f in (args.features or "").split(",") if f.strip()]
            msg = accept(repo, build=_req(args, "build"), commit=_req(args, "commit"), source=_req(args, "source"),
                         ref=_req(args, "ref"), summary=_req(args, "summary"), features=feats,
                         engine=args.engine, today=today)
        elif verb == "queue":
            msg = queue(repo, _req(args, "platform"), _req(args, "ref"))
        elif verb == "open":
            msg = open_train(repo, _req(args, "platform"), today)
        elif verb == "sync":
            msg = sync(repo, _req(args, "platform"), _req(args, "to"))
        elif verb == "override":
            msg = override(repo, _req(args, "platform"), _req(args, "ref"), _req(args, "summary"),
                           args.days, today)
        else:
            raise ParityError(f"unknown verb {verb}")
    except ParityError as e:
        print(f"parity: {e}")
        return 1
    print(msg)
    return 0


def _req(args, name: str) -> str:
    v = getattr(args, name, None)
    if v in (None, ""):
        raise ParityError(f"{name.replace('_', '-')} is required")
    return str(v)


def register(sp):
    q = sp.add_parser("parity", help="the parity gate ledger: when a secondary platform may get the primary's features")
    q.set_defaults(fn=cmd_parity)
    q.add_argument("verb", choices=["init", "status", "deliver", "accept", "queue", "open", "sync", "override"])
    q.add_argument("platform", nargs="?", help="queue, open, sync, override: the secondary platform")
    q.add_argument("--repo", help="the product repo (default: the current directory)")
    q.add_argument("--date", help="today, YYYY-MM-DD (default: the real date)")
    q.add_argument("--build", help="deliver, accept: the build, e.g. '2.0.3 (197)'")
    q.add_argument("--commit", help="deliver, accept: the primary commit the build was cut from")
    q.add_argument("--to", help="deliver: who can install it (default owner); sync: the commit the secondary now matches")
    q.add_argument("--source", help="accept: chat, testflight or in-app")
    q.add_argument("--ref", help="accept, queue, override: where the owner's words live")
    q.add_argument("--summary", help="accept, override: one English line")
    q.add_argument("--features", help="accept: comma list; empty means the whole build")
    q.add_argument("--engine", action="store_true", help="accept: the build changes the engine or stored data (settle 7 days)")
    q.add_argument("--days", type=int, default=1, help="override: how many days it lasts (default 1)")
    q.add_argument("--json", action="store_true", help="status")
    q.add_argument("--line", action="store_true", help="status: the one session line, nothing when no ledger")
    return q
