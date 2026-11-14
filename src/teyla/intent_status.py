"""`teyla intent audit|mark|load` — which of the owner's requests were delivered, and what is still owed.

    teyla intent audit <product> [--open] [--json]      every request with status, evidence and age; entries not audited
    teyla intent mark <ref> <status> [--quote TEXT] [--evidence E] [--note N] [--product P]
    teyla intent load <product> <file.json> [--dry]     many records at once, all or nothing

`teyla intent` keeps the owner's words. Kept words are not delivered words: a request typed once and never
picked up looked exactly like one that shipped. This is the record of which is which. It holds statuses,
never the classification itself: an agent reads the entries, splits them into requests, looks for the
evidence (merged PRs, the feature list, the code) and writes the result here (`plugin/skills/intent-audit`).

    ~/.teyla/intent/<product>.status.json   the records, 0600, beside the product file; never in a repo
    ~/.teyla/intent/.coverage.tsv           one line per product, for the shell session-start hook

Ids. An entry's id is the first 8 hex characters of the hash `teyla intent` already dedupes by, so it
survives an index rebuild and does not change the entry file. A request is `<entry>.<n>`, numbered by the
CLI, never renumbered, and carries a verbatim quote: a run of the entry's own text (runs of spaces and line
breaks count as one space; case and punctuation must match), so an agent cannot record a request the owner
never made. The quote proves the request is his, not that every request in the entry was found.

A record on the bare entry id covers the whole entry. `split` says every request in it is recorded as
`<entry>.<n>`; `not-a-request` says it holds nothing to deliver; a one-request entry can take any status.
An entry is audited only with such a record. One with requests but no entry record is "partly audited":
an agent quoted some requests and may have missed others.

Statuses: open, partial, done, superseded, not-a-request, and `split` for an entry. `done` needs
`--evidence` (a PR URL, a file, a feature anchor). `partial` needs `--evidence` and a `--note` saying what is
still missing. `superseded` needs `--evidence` or `--note` naming what replaced it (another request id when
there is one). Owed means open or partial. Not audited and partly audited entries are counted apart.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys

from . import intent

VERSION = 1
STATUSES = ("open", "partial", "done", "superseded", "not-a-request", "split")
ENTRY_ONLY = ("split",)
OWED = ("open", "partial")
NEEDS_EVIDENCE = ("done", "partial")
ID_LEN = 8
QUOTE_MAX = 600
COVERAGE_NAME = ".coverage.tsv"
_REF_RE = re.compile(r"^([0-9a-f]{8})(?:\.([1-9]\d{0,3}))?$")
_ORDER = {s: i for i, s in enumerate(STATUSES)}


class StatusError(ValueError):
    """A record the store refuses. The message is the one line printed."""


# --- ids and files ------------------------------------------------------------------------------

def entry_id(e: dict) -> str:
    kept, _ = intent.kept_text(e["text"])
    return intent.digest(kept)[:ID_LEN]


def status_path(product: str) -> pathlib.Path:
    return intent.intent_dir() / f"{product}.status.json"


def coverage_path() -> pathlib.Path:
    return intent.intent_dir() / COVERAGE_NAME


def load_records(product: str) -> dict:
    """{id: record} for `product`; an unreadable file is an error, not an empty store."""
    p = status_path(product)
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise StatusError(f"{p}: unreadable ({e}); fix or move it, nothing was written") from e
    recs = data.get("records") if isinstance(data, dict) else None
    if not isinstance(recs, dict):
        raise StatusError(f"{p}: no records table; fix or move it, nothing was written")
    return recs


def _save(product: str, recs: dict) -> None:
    from . import config
    d = intent.intent_dir()
    tmp = d / f"{product}.status.json.{os.getpid()}.tmp"
    config.write_private(tmp, json.dumps({"version": VERSION, "product": product, "records": recs},
                                         ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, status_path(product))


def audited_products() -> list[str]:
    d = intent.intent_dir()
    return sorted(p.name[:-len(".status.json")] for p in d.glob("*.status.json")) if d.is_dir() else []


def _norm(s: str) -> str:
    return " ".join((s or "").split())


# --- checks -------------------------------------------------------------------------------------

def check(status: str, evidence: str, note: str) -> None:
    if status not in STATUSES:
        raise StatusError(f"unknown status {status!r}; one of {', '.join(STATUSES)}")
    if status in NEEDS_EVIDENCE and not evidence.strip():
        raise StatusError(f"{status} needs --evidence: a PR URL, a file or a feature anchor")
    if status == "partial" and not note.strip():
        raise StatusError("partial needs --note saying what is still missing")
    if status == "superseded" and not (evidence.strip() or note.strip()):
        raise StatusError("superseded needs --evidence or --note naming what replaced it")


def check_quote(quote: str, entry_text: str) -> str:
    q = " ".join((quote or "").split())
    if not q:
        raise StatusError("empty quote")
    if len(q) > QUOTE_MAX:
        raise StatusError(f"quote of {len(q)} characters; at most {QUOTE_MAX}: split it into requests")
    if _norm(q) not in _norm(intent.kept_text(entry_text)[0]):  # spacing only; case and punctuation count
        raise StatusError(f"quote is not in the entry's text: {q[:80]!r}")
    return q


# --- the record ---------------------------------------------------------------------------------

def _today() -> str:
    return _dt.date.today().isoformat()


def apply(recs: dict, entries: dict[str, dict], rec: dict, today: str | None = None) -> tuple[str, str]:
    """Apply one mark to `recs` in place. `rec` holds `ref` (an entry or request id), `status`, and
    optionally `quote`, `evidence`, `note`. Returns (id, what happened)."""
    today = today or _today()
    ref = str(rec.get("ref") or rec.get("id") or rec.get("entry") or "").strip().lower()
    status = str(rec.get("status") or "").strip()
    evidence = str(rec.get("evidence") or "").strip()
    note = str(rec.get("note") or "").strip()
    quote = rec.get("quote")
    m = _REF_RE.match(ref)
    if not m:
        raise StatusError(f"{ref or '(empty)'}: not an entry id (8 hex) or a request id (<entry>.<n>)")
    eid, n = m.group(1), m.group(2)
    if eid not in entries:
        raise StatusError(f"{eid}: no such entry for this product (`teyla intent audit` lists the ids)")
    check(status, evidence, note)
    children = [k for k in recs if k.startswith(eid + ".")]
    if status in ENTRY_ONLY and (n is not None or quote):
        raise StatusError(f"{status} is for a whole entry: `mark {eid} {status}`")
    if n is None and not quote and status == "not-a-request" and children:
        raise StatusError(f"{eid} has {len(children)} request(s) recorded; mark them, or the entry `split`")
    if n is None and quote and recs.get(eid, {}).get("status") == "not-a-request":
        raise StatusError(f"{eid} is marked not-a-request; mark the entry `split` first if it holds requests")
    if n is None and quote:
        q = check_quote(str(quote), entries[eid]["text"])
        same = [k for k, r in recs.items() if r.get("entry") == eid and _norm(r.get("quote", "")) == _norm(q)]
        if same:
            rid = same[0]
        else:
            nums = [int(k.split(".")[1]) for k in children]
            rid = f"{eid}.{max(nums, default=0) + 1}"
            recs[rid] = {"entry": eid, "quote": q, "status": "", "evidence": "", "note": "", "updated": today}
    elif n is None:
        rid = eid
        recs.setdefault(rid, {"entry": eid, "quote": "", "status": "", "evidence": "", "note": "", "updated": today})
    else:
        rid = ref
        if rid not in recs:
            raise StatusError(f"{rid}: no such request; add one with `mark {eid} <status> --quote TEXT`")
        if quote:
            raise StatusError(f"{rid}: a request's quote is fixed; add a new request on {eid} instead")
    r = recs[rid]
    before = r.get("status") or "new"
    if (r.get("status"), r.get("evidence", ""), r.get("note", "")) != (status, evidence, note):
        if r.get("status"):
            r.setdefault("history", []).append({k: r.get(k, "") for k in ("status", "evidence", "note", "updated")})
        r.update(status=status, evidence=evidence, note=note, updated=today)
        return rid, f"{before} -> {status}"
    return rid, f"{status}, unchanged"


def _entries_by_id(product: str) -> dict[str, dict]:
    return {entry_id(e): e for e in intent.entries(product)}


def find_product(eid: str) -> list[str]:
    return [p["product"] for p in intent.products() if eid in _entries_by_id(p["product"])]


# --- audit --------------------------------------------------------------------------------------

def _age(date: str, today: _dt.date) -> int:
    try:
        return (today - _dt.date.fromisoformat(date[:10])).days
    except ValueError:
        return 0


def audit(product: str, today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    entries = _entries_by_id(product)
    recs = load_records(product)
    rows, gone, seen, quoted = [], 0, set(), set()
    for rid, r in recs.items():
        e = entries.get(r.get("entry", ""))
        if e is None:
            gone += 1
            continue
        (seen if rid == r["entry"] else quoted).add(r["entry"])
        if r.get("status") == "split":
            continue
        rows.append({"id": rid, "entry": r["entry"], "date": e["date"][:10], "age_days": _age(e["date"], today),
                     "status": r.get("status", ""), "quote": r.get("quote", ""), "evidence": r.get("evidence", ""),
                     "note": r.get("note", ""), "updated": r.get("updated", ""), "history": r.get("history", [])})
    # what is owed comes first, oldest first whatever its status; then the rest by status and age
    rows.sort(key=lambda x: (0 if x["status"] in OWED else 1, 0 if x["status"] in OWED else _ORDER.get(x["status"], 9),
                             -x["age_days"], x["id"]))
    def _brief(eid, e):
        return {"entry": eid, "date": e["date"][:10], "age_days": _age(e["date"], today),
                "first": " ".join(e["text"].split())[:100]}
    unaudited = sorted((_brief(eid, e) for eid, e in entries.items() if eid not in seen and eid not in quoted),
                       key=lambda x: (-x["age_days"], x["entry"]))
    partly = sorted((_brief(eid, e) for eid, e in entries.items() if eid not in seen and eid in quoted),
                    key=lambda x: (-x["age_days"], x["entry"]))
    owed = [x for x in rows if x["status"] in OWED]
    counts = {s: sum(1 for x in rows if x["status"] == s) for s in STATUSES}
    return {"product": product, "entries": len(entries), "audited_entries": len(seen), "unaudited": unaudited,
            "partly_audited": partly,
            "requests": rows, "counts": counts, "gone": gone, "audited": bool(recs),
            "oldest_owed_days": max((x["age_days"] for x in owed), default=None),
            "oldest_owed_date": min((x["date"] for x in owed), default=None)}


def summary_line(a: dict) -> str:
    c = a["counts"]
    if not a["audited"]:
        return f"{a['product']}: not audited ({a['entries']} entries)"
    bits = [f"{c['open']} request{'' if c['open'] == 1 else 's'} open"]
    if c["partial"]:
        bits.append(f"{c['partial']} partial")
    if a["oldest_owed_days"] is not None:
        bits.append(f"oldest {a['oldest_owed_days']} days")
    line = f"{a['product']}: " + ", ".join(bits)
    if a["unaudited"]:
        line += f"; {len(a['unaudited'])} entr{'y' if len(a['unaudited']) == 1 else 'ies'} not audited"
    if a["partly_audited"]:
        line += f"; {len(a['partly_audited'])} partly audited"
    return line


def owed_summary(today: _dt.date | None = None) -> dict:
    """For `teyla you`: one line per audited product that still owes something, and how many products
    with entries were never audited."""
    today = today or _dt.date.today()
    audited = set(audited_products())
    lines, never = [], []
    for p in intent.products():
        if p["product"] not in audited:
            if p["entries"]:
                never.append(p["product"])
            continue
        try:
            a = audit(p["product"], today)
        except StatusError as e:
            lines.append({"product": p["product"], "line": f"{p['product']}: {e}", "owed": 0})
            continue
        owed = a["counts"]["open"] + a["counts"]["partial"] + len(a["unaudited"]) + len(a["partly_audited"])
        if owed:
            lines.append({"product": p["product"], "line": summary_line(a), "owed": owed,
                          "oldest_owed_days": a["oldest_owed_days"]})
    lines.sort(key=lambda x: -x["owed"])
    return {"products": lines, "never_audited": never}


def write_coverage(today: _dt.date | None = None) -> None:
    """`.coverage.tsv` for the shell hook: product, audited entries, open, partial, epoch of the oldest
    owed entry's date (0 when none). Rewritten after every write; a failure never fails the write."""
    from . import config
    rows = []
    for product in audited_products():
        try:
            a = audit(product, today)
        except StatusError:
            continue
        epoch = 0
        if a["oldest_owed_date"]:
            epoch = int(_dt.datetime.fromisoformat(a["oldest_owed_date"]).timestamp())
        rows.append(f"{product}\t{a['audited_entries']}\t{a['counts']['open']}\t{a['counts']['partial']}\t{epoch}\n")
    tmp = intent.intent_dir() / f"{COVERAGE_NAME}.{os.getpid()}.tmp"
    try:
        config.write_private(tmp, "".join(rows))
        os.replace(tmp, coverage_path())
    except OSError:
        pass


# --- writes -------------------------------------------------------------------------------------

def mark(product: str, rec: dict, dry: bool = False) -> tuple[str, str]:
    return load(product, [rec], dry=dry)[0]


def load(product: str, records: list[dict], dry: bool = False) -> list[tuple[str, str]]:
    """Apply every record or none: the first refusal raises with its position and nothing is written."""
    entries = _entries_by_id(product)
    if not entries:
        raise StatusError(f"no intent recorded for {product}")
    with intent.Store(wait_s=10.0, dry=dry):
        recs = load_records(product)
        out, errors = [], []
        for i, rec in enumerate(records, 1):
            if not isinstance(rec, dict):
                errors.append(f"record {i}: not an object")
                continue
            try:
                out.append(apply(recs, entries, rec))
            except StatusError as e:
                errors.append(f"record {i}: {e}" if len(records) > 1 else str(e))
        if errors:
            raise StatusError("\n".join(errors) + "\nnothing was written")
        if not dry:
            _save(product, recs)
            write_coverage()        # under the same lock, so overlapping marks cannot publish a stale table
    return out


# --- commands -----------------------------------------------------------------------------------

def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def render(a: dict, only_owed: bool = False) -> str:
    L = [summary_line(a) + f"  ({a['entries']} entries, {sum(a['counts'].values())} records)"]
    for x in a["requests"]:
        if only_owed and x["status"] not in OWED:
            continue
        what = f'"{_clip(x["quote"], 90)}"' if x["quote"] else "(whole entry)"
        L.append(f"  {x['status']:13} {x['age_days']:4}d  {x['id']:11} {what}")
        tail = "; ".join(t for t in (x["evidence"], x["note"]) if t)
        if tail:
            L.append(f"  {'':13} {'':5}  {'':11} {_clip(tail, 110)}")
    if a["partly_audited"]:
        L.append("partly audited (requests quoted, entry not closed: add what is missing, then `mark <id> split`):")
        for u in a["partly_audited"]:
            L.append(f"  {u['date']}  {u['entry']}  {_clip(u['first'], 90)}")
    if a["unaudited"]:
        L.append("not audited (`mark <id> <status> --quote TEXT` per request, then `mark <id> split`; or `mark <id> not-a-request`):")
        for u in a["unaudited"]:
            L.append(f"  {u['date']}  {u['entry']}  {_clip(u['first'], 90)}")
    if a["gone"]:
        L.append(f"note: {a['gone']} record(s) point at entries no longer in the file (`teyla intent clean`)")
    return "\n".join(L)


def cmd(args, words: list[str]) -> int:
    sub = words[0]
    try:
        if sub == "audit":
            if len(words) != 2:
                print("usage: teyla intent audit <product> [--open] [--json]", file=sys.stderr)
                return 64
            name = intent.resolve(words[1])
            if name is None:
                print(f"teyla: no intent recorded for {words[1]}", file=sys.stderr)
                return 2
            a = audit(name)
            try:
                with intent.Store(wait_s=2.0):
                    write_coverage()
            except TimeoutError:
                pass                # the next write rebuilds it
            if args.json:
                print(json.dumps(a, ensure_ascii=False, indent=2))
            else:
                print(render(a, only_owed=args.open))
            return 0
        if sub == "mark":
            if len(words) != 3:
                print("usage: teyla intent mark <entry|entry.n> <status> [--quote TEXT] [--evidence E] [--note N] [--product P]",
                      file=sys.stderr)
                return 64
            ref = words[1].strip().lower()
            if args.product:
                product = intent.resolve(args.product)
                if product is None:
                    print(f"teyla: no intent recorded for {args.product}", file=sys.stderr)
                    return 2
            else:
                hits = find_product(ref.split(".")[0])
                if len(hits) != 1:
                    print(f"teyla: entry {ref.split('.')[0]} is in {len(hits)} products"
                          + (f" ({', '.join(hits)}); pass --product" if hits else "; `teyla intent audit <product>` lists the ids"),
                          file=sys.stderr)
                    return 2
                product = hits[0]
            rid, what = mark(product, {"ref": ref, "status": words[2], "quote": args.quote,
                                       "evidence": args.evidence, "note": args.note}, dry=args.dry)
            print(f"{product} {rid}: {what}" + ("  (dry, nothing written)" if args.dry else ""))
            return 0
        if sub == "load":
            if len(words) != 3:
                print("usage: teyla intent load <product> <file.json> [--dry]", file=sys.stderr)
                return 64
            name = intent.resolve(words[1])
            if name is None:
                print(f"teyla: no intent recorded for {words[1]}", file=sys.stderr)
                return 2
            raw = sys.stdin.read() if words[2] == "-" else pathlib.Path(words[2]).read_text()
            data = json.loads(raw)
            if isinstance(data, dict):
                if data.get("product") and intent.resolve(str(data["product"])) != name:
                    print(f"teyla: the file is for {data['product']}, not {name}", file=sys.stderr)
                    return 64
                data = data.get("records")
            if not isinstance(data, list):
                print("teyla: the file holds a list of records, or {\"records\": [...]}", file=sys.stderr)
                return 64
            res = load(name, data, dry=args.dry)
            changed = [r for r in res if "unchanged" not in r[1]]
            for rid, what in changed:
                print(f"  {rid}: {what}")
            print(f"{name}: {len(changed)} changed, {len(res) - len(changed)} unchanged"
                  + ("  (dry, nothing written)" if args.dry else ""))
            if not args.dry:
                print(summary_line(audit(name)))
            return 0
    except StatusError as e:
        print(f"teyla: {e}", file=sys.stderr)
        return 1
    except TimeoutError:
        print("teyla: the intent store is locked; try again in a moment", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"teyla: {e}", file=sys.stderr)
        return 1
    return 64
