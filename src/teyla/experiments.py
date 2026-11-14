"""`teyla experiments` — a lab build, a design variant or a parallel test app, with a verdict per feature.

    teyla experiments [--all] [--json]                       open experiments: age, features, how many lack a verdict
    teyla experiments add <product> <id> --kind lab|variant|app [--title T] [--where W] [--since YYYY-MM-DD]
    teyla experiments feature <product> <id> <text...> [--request R]   one feature it carries; prints its id (f1, f2, ...)
    teyla experiments verdict <product> <id> <fid> promoted --pr URL | parked --trigger TEXT | dropped --reason TEXT
    teyla experiments retire <product> <id>                  refused while a feature has no verdict
    teyla experiments show <product> <id> [--json]
    teyla experiments parked [--json]                        every parked feature and its trigger, retired experiments too

Why: experimental work held features the owner needed, and it was retired with no verdict per feature, so
the features went nowhere. Here an experiment cannot be retired until each feature it carries is
promoted (the PR that brought it to the main line), parked (the trigger that brings it back) or dropped
(the reason). `teyla you` lists experiments older than 14 days with features that have no verdict, and
experiments that never had a feature written down. Parked features stay listed after their experiment is
retired (`parked`), so retiring does not hide a deferred decision. `--request` links a feature to the owner's
request (`teyla intent audit` ids); a verdict here never changes that request's status, which is marked apart.

The gate holds this command only: deleting a branch or a TestFlight group elsewhere is not stopped. The
workflow is to retire here first, then delete.

    ~/.teyla/experiments/<product>.json      0600, outside every repo; nothing leaves the machine
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys

from . import corrections

VERSION = 1
KINDS = ("lab", "variant", "app")
VERDICTS = {"promoted": "pr", "parked": "trigger", "dropped": "reason"}
STALE_DAYS = 14
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


class ExperimentError(ValueError):
    """A refusal. The message is the one line printed."""


def home() -> pathlib.Path:
    return corrections.teyla_home() / "experiments"


def _clean(product: str) -> str:
    if product == ".":
        from . import intent
        product = intent.product_for(os.getcwd())
    p = re.sub(r"[^A-Za-z0-9._-]+", "-", product or "").strip("-.")
    if not p:
        raise ExperimentError("a product name is needed")
    return p


def path(product: str) -> pathlib.Path:
    return home() / f"{_clean(product)}.json"


def load(product: str) -> dict:
    p = path(product)
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ExperimentError(f"{p}: unreadable ({e}); fix or move it, nothing was written") from e
    ex = data.get("experiments") if isinstance(data, dict) else None
    if not isinstance(ex, dict):
        raise ExperimentError(f"{p}: no experiments table; fix or move it, nothing was written")
    return ex


def save(product: str, ex: dict) -> None:
    from . import config
    config.private_dir(corrections.teyla_home())
    config.private_dir(home())
    p = path(product)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    config.write_private(tmp, json.dumps({"version": VERSION, "product": _clean(product), "experiments": ex},
                                         ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, p)


def products() -> list[str]:
    d = home()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def _today() -> str:
    return _dt.date.today().isoformat()


def _get(ex: dict, product: str, eid: str) -> dict:
    if eid not in ex:
        raise ExperimentError(f"{_clean(product)}/{eid}: no such experiment (`teyla experiments --all` lists them)")
    return ex[eid]


def unjudged(e: dict) -> list[str]:
    return [fid for fid, f in e.get("features", {}).items() if not f.get("verdict")]


# --- writes -------------------------------------------------------------------------------------

def add(product: str, eid: str, kind: str, title: str = "", where: str = "", since: str | None = None) -> dict:
    if not ID_RE.match(eid or ""):
        raise ExperimentError(f"{eid!r}: an id is lowercase letters, digits, '.', '_' or '-', at most 40")
    if kind not in KINDS:
        raise ExperimentError(f"kind {kind!r}; one of {', '.join(KINDS)}")
    started = since or _today()
    try:
        _dt.date.fromisoformat(started)
    except ValueError as e:
        raise ExperimentError(f"--since {started!r}: not a date (YYYY-MM-DD)") from e
    ex = load(product)
    if eid in ex:
        raise ExperimentError(f"{_clean(product)}/{eid} exists; `teyla experiments show {_clean(product)} {eid}`")
    ex[eid] = {"kind": kind, "title": title, "where": where, "started": started, "retired": None, "features": {}}
    save(product, ex)
    return ex[eid]


def feature(product: str, eid: str, text: str, request: str = "") -> str:
    text = " ".join((text or "").split())
    if not text:
        raise ExperimentError("a feature needs a line of text")
    ex = load(product)
    e = _get(ex, product, eid)
    if e.get("retired"):
        raise ExperimentError(f"{_clean(product)}/{eid} was retired on {e['retired']}")
    feats = e.setdefault("features", {})
    for fid, f in feats.items():
        if f.get("text", "").casefold() == text.casefold():
            if request and f.get("request") != request:
                f["request"] = request
                save(product, ex)
            return fid
    fid = f"f{max((int(k[1:]) for k in feats if k[1:].isdigit()), default=0) + 1}"
    feats[fid] = {"text": text, "verdict": None, "because": "", "decided": None}
    if request:
        feats[fid]["request"] = request
    save(product, ex)
    return fid


def verdict(product: str, eid: str, fid: str, what: str, because: str) -> dict:
    if what not in VERDICTS:
        raise ExperimentError(f"verdict {what!r}; one of {', '.join(VERDICTS)}")
    because = " ".join((because or "").split())
    if not because:
        raise ExperimentError(f"{what} needs --{VERDICTS[what]}")
    if what == "promoted" and not re.match(r"^(https?://\S+|[\w.-]+/[\w.-]+#\d+)$", because):
        raise ExperimentError("promoted needs --pr: the PR's URL, or owner/repo#N")
    ex = load(product)
    e = _get(ex, product, eid)
    f = e.get("features", {}).get(fid)
    if f is None:
        raise ExperimentError(f"{_clean(product)}/{eid}: no feature {fid}")
    f.update(verdict=what, because=because, decided=_today())
    save(product, ex)
    return f


def retire(product: str, eid: str) -> dict:
    ex = load(product)
    e = _get(ex, product, eid)
    if e.get("retired"):
        return e
    if not e.get("features"):
        raise ExperimentError(f"{_clean(product)}/{eid} has no features written down; add each one it carries "
                              "(`teyla experiments feature`), then a verdict for each")
    left = unjudged(e)
    if left:
        lines = [f"  {fid}  {e['features'][fid]['text']}" for fid in left]
        raise ExperimentError(f"{_clean(product)}/{eid}: {len(left)} feature(s) without a verdict; give each one "
                              "promoted --pr, parked --trigger or dropped --reason:\n" + "\n".join(lines))
    e["retired"] = _today()
    save(product, ex)
    return e


# --- reads --------------------------------------------------------------------------------------

def _age(e: dict, today: _dt.date) -> int:
    try:
        return (today - _dt.date.fromisoformat(str(e.get("started"))[:10])).days
    except ValueError:
        return 0


def rows(include_retired: bool = False, today: _dt.date | None = None) -> list[dict]:
    today = today or _dt.date.today()
    out = []
    for product in products():
        try:
            ex = load(product)
        except ExperimentError as err:
            out.append({"product": product, "id": "?", "error": str(err)})
            continue
        for eid, e in ex.items():
            if e.get("retired") and not include_retired:
                continue
            feats = e.get("features", {})
            out.append({"product": product, "id": eid, "kind": e.get("kind"), "title": e.get("title", ""),
                        "where": e.get("where", ""), "started": e.get("started"), "age_days": _age(e, today),
                        "retired": e.get("retired"), "features": len(feats), "unjudged": len(unjudged(e)),
                        "verdicts": {v: sum(1 for f in feats.values() if f.get("verdict") == v) for v in VERDICTS}})
    return sorted(out, key=lambda r: (r.get("retired") or "", -r.get("age_days", 0), r["product"], r["id"]))


def parked() -> list[dict]:
    out = []
    for product in products():
        try:
            ex = load(product)
        except ExperimentError:
            continue
        for eid, e in ex.items():
            for fid, f in e.get("features", {}).items():
                if f.get("verdict") == "parked":
                    out.append({"product": product, "id": eid, "feature": fid, "text": f.get("text", ""),
                                "trigger": f.get("because", ""), "decided": f.get("decided"),
                                "retired": e.get("retired"), "request": f.get("request", "")})
    return out


def stale(today: _dt.date | None = None, days: int = STALE_DAYS) -> list[dict]:
    """Open experiments at least `days` old with a feature that has no verdict, or no feature at all."""
    return [r for r in rows(today=today) if "error" in r
            or (r["age_days"] >= days and (r["unjudged"] or not r["features"]))]


def stale_line(r: dict) -> str:
    if "error" in r:
        return f"{r['product']}: {r['error']}"
    what = (f"{r['unjudged']} of {r['features']} features without a verdict" if r["features"]
            else "no features written down")
    return f"{r['product']}/{r['id']} ({r['kind']}, {r['age_days']} days): {what}"


def _line(r: dict) -> str:
    if "error" in r:
        return f"{r['product']}: {r['error']}"
    v = r["verdicts"]
    state = f"retired {r['retired']}" if r["retired"] else f"{r['age_days']}d"
    return (f"{r['product'] + '/' + r['id']:32} {r['kind']:7} {state:16} {r['features']:3} features  "
            f"{r['unjudged']:3} no verdict  ({v['promoted']} promoted, {v['parked']} parked, {v['dropped']} dropped)"
            + (f"  {r['title']}" if r["title"] else ""))


def show(product: str, eid: str) -> str:
    e = _get(load(product), product, eid)
    L = [f"{_clean(product)}/{eid}  {e.get('kind')}  started {e.get('started')}"
         + (f"  retired {e['retired']}" if e.get("retired") else "")]
    if e.get("title"):
        L.append(f"  {e['title']}")
    if e.get("where"):
        L.append(f"  where: {e['where']}")
    for fid, f in e.get("features", {}).items():
        v = f"{f['verdict']} ({f['because']})" if f.get("verdict") else "NO VERDICT"
        L.append(f"  {fid:4} {f['text']}" + (f"  (request {f['request']})" if f.get("request") else "")
                 + f"\n       {v}")
    if not e.get("features"):
        L.append("  no features written down")
    return "\n".join(L)


# --- command ------------------------------------------------------------------------------------

USAGE = ("usage: teyla experiments [--all] [--json] | add <product> <id> --kind lab|variant|app [--title T] [--where W] "
         "[--since DATE] | feature <product> <id> <text> [--request R] | verdict <product> <id> <fid> promoted --pr URL|parked --trigger T|"
         "dropped --reason R | retire <product> <id> | show <product> <id> | parked")


def cmd(args) -> int:
    w = list(args.words or [])
    try:
        if not w or w[0] == "list":
            rs = rows(include_retired=args.all)
            if args.json:
                print(json.dumps(rs, ensure_ascii=False, indent=2))
            elif not rs:
                print("no open experiments" + ("" if args.all else " (--all shows retired ones)")
                      + "; `teyla experiments add <product> <id> --kind lab` registers one")
            else:
                for r in rs:
                    print(_line(r))
            return 0
        sub = w[0]
        if sub == "add" and len(w) == 3:
            if not args.kind:
                raise ExperimentError("add needs --kind lab|variant|app")
            add(w[1], w[2], args.kind, args.title or "", args.where or "", args.since)
            print(f"{_clean(w[1])}/{w[2]}: added; now `teyla experiments feature {_clean(w[1])} {w[2]} <text>` for each feature")
            return 0
        if sub == "parked" and len(w) == 1:
            ps = parked()
            if args.json:
                print(json.dumps(ps, ensure_ascii=False, indent=2))
            for x in ps if not args.json else []:
                print(f"{x['product']}/{x['id']} {x['feature']}: {x['text']}\n    trigger: {x['trigger']}"
                      + (f"  (experiment retired {x['retired']})" if x["retired"] else ""))
            if not ps and not args.json:
                print("no parked features")
            return 0
        if sub == "feature" and len(w) >= 4:
            fid = feature(w[1], w[2], " ".join(w[3:]), args.request or "")
            print(f"{_clean(w[1])}/{w[2]} {fid}")
            return 0
        if sub == "verdict" and len(w) == 5:
            what = w[4]
            because = {"promoted": args.pr, "parked": args.trigger, "dropped": args.reason}.get(what) or ""
            verdict(w[1], w[2], w[3], what, because)
            print(f"{_clean(w[1])}/{w[2]} {w[3]}: {what}")
            return 0
        if sub == "retire" and len(w) == 3:
            e = retire(w[1], w[2])
            print(f"{_clean(w[1])}/{w[2]}: retired {e['retired']}")
            return 0
        if sub == "show" and len(w) == 3:
            if args.json:
                print(json.dumps(_get(load(w[1]), w[1], w[2]), ensure_ascii=False, indent=2))
            else:
                print(show(w[1], w[2]))
            return 0
    except ExperimentError as e:
        print(f"teyla: {e}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 64


def register(sp):
    q = sp.add_parser("experiments", help="lab builds, variants and test apps: a verdict per feature before retiring")
    q.set_defaults(fn=cmd)
    q.add_argument("words", nargs="*", metavar="[add|feature|verdict|retire|show] <product> <id> ...")
    q.add_argument("--kind", choices=KINDS, help="add: lab (a lab build), variant (a design variant), app (a parallel test app)")
    q.add_argument("--title", help="add: one line")
    q.add_argument("--where", help="add: a branch, a scheme, a TestFlight group, a folder")
    q.add_argument("--since", metavar="YYYY-MM-DD", help="add: when it started, for one registered late (default today)")
    q.add_argument("--pr", help="verdict promoted: the PR that brought the feature to the main line")
    q.add_argument("--trigger", help="verdict parked: what brings it back")
    q.add_argument("--reason", help="verdict dropped: why")
    q.add_argument("--request", help="feature: the owner's request it serves (an id from `teyla intent audit`)")
    q.add_argument("--all", action="store_true", help="list: retired experiments too")
    q.add_argument("--json", action="store_true")
    return q
