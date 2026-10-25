"""`teyla lanes` — what each kind of subagent lane costs on each model, and what its reviews found.

`teyla spend --by-day` says how much of the subagent money each model family spent. This says where:
one row per (subagent type, model) over the transcripts' subagent files, so "Opus ran 37 of the 90
build lanes at twice the cost" is one line rather than a hand-made script.

A unit is one subagent file (`<session>/subagents/agent-*.jsonl`, one Agent call) with its
`agent-*.meta.json` (agentType). Its model is the one that wrote most of its output. Messages are
deduplicated by (message id, request id), the last record of a message wins, and each is priced with
`pricing.cost_usd`. Columns: units, median turns (assistant messages), median peak context (the largest
prompt, input + cache), median and total dollars.

Reviews come from the review ledger (`review.ledger`, see teyla.reviews). A unit is matched to a review
when its transcript holds a hex string of 7+ characters that is a prefix of the reviewed commit and the
review was made after the unit started. "P1 per unit" counts the first-round reviews of matched units
(`branch*`, `diff*`; a `commit` review is a fix round and a skip is not a review).

That P1 rate is confounded by task difficulty: a model given the hard lanes finds more P1s in them.
It is a prompt to look, not a verdict on a model.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import pathlib
import re
import statistics
from collections import defaultdict

from . import config

# 7 to 40 hex characters not inside a longer word: a full sha or any usable prefix of one.
_HEX = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
_ESCAPES = re.compile(r"\\[nrt]")
FIRST_ROUND = ("branch", "diff", "diff-file")
# A unit that calls none of these changed no file: a read-only lane (`teyla start`'s scout offer).
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# `explicit` on a unit when no .meta.json says whether the Agent call named a model.
UNKNOWN_MODEL = "?"


def _when(ts: str | None) -> _dt.datetime | None:
    try:
        d = _dt.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _scan_file(path: str, cutoff: _dt.datetime | None, want_tokens: bool = True) -> dict | None:
    """One subagent file as a unit, or None when no message of it falls in the window. `want_tokens`
    False skips collecting the commit-sha tokens review matching needs (about half the scan time)."""
    from .adapters import claude_code
    from .pricing import cost_usd
    seen: dict = {}
    tokens: set = set()
    first = None
    writes = False
    try:
        fh = open(path, errors="replace")
    except OSError:
        return None
    with fh:
        for n, line in enumerate(fh):
            # JSON writes a newline as \n: without this a sha after one reads as part of a word.
            if want_tokens:
                tokens.update(_HEX.findall(_ESCAPES.sub(" ", line)))
            if '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "assistant":
                continue
            m = o.get("message") or {}
            model = m.get("model") or "?"
            if model.startswith("<"):                       # <synthetic>: not a model call
                continue
            ts = o.get("timestamp")
            at = _when(ts)
            if cutoff is not None and (at is None or at < cutoff):
                continue
            first = first or ts
            if not writes and any(isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in WRITE_TOOLS
                                  for b in (m.get("content") if isinstance(m.get("content"), list) else [])):
                writes = True
            seen[(m.get("id") or ("line", n), o.get("requestId"))] = (model, claude_code._usage_row(m.get("usage") or {}))
    if not seen:
        return None
    usd, peak, out_by_model = 0.0, 0, defaultdict(int)
    usage: dict = {}
    for model, row in seen.values():
        usd += cost_usd(model, row) or 0.0
        into = usage.setdefault(model, {})
        for k, v in row.items():
            into[k] = into.get(k, 0) + v
        peak = max(peak, row["input_tokens"] + row["cache_creation_input_tokens"] + row["cache_read_input_tokens"])
        out_by_model[model] += row["output_tokens"]
    kind, explicit = "", UNKNOWN_MODEL
    try:
        meta = json.loads(pathlib.Path(path[:-len(".jsonl")] + ".meta.json").read_text())
        kind = str(meta.get("agentType") or "")
        # The Agent call's own `model` parameter; a meta file without one means the call named none.
        explicit = str(meta["model"]) if meta.get("model") else None
    except (OSError, ValueError, AttributeError):
        pass
    return dict(agent=os.path.basename(path)[:-len(".jsonl")], type=kind or "(untyped)", turns=len(seen), peak=peak,
                usd=usd, model=max(out_by_model, key=out_by_model.get), first=first, tokens=tokens,
                usage=usage, explicit=explicit, writes=writes)


def scan(days: int | None = 7, project: str | None = None, root: str | None = None,
         now: _dt.datetime | None = None, want_tokens: bool = True) -> list[dict]:
    """Every subagent unit with a message in the last `days` days (None: all), optionally only the
    projects whose transcript folder name contains `project`. `want_tokens` False leaves each unit's
    `tokens` empty (nothing but review matching reads them)."""
    from .adapters import claude_code, since_epoch, stale
    root = claude_code.DEFAULT_ROOT if root is None else root   # at call time, so tests can move it
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=days) if days else None
    since = cutoff.timestamp() if cutoff else None
    units = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.jsonl"))):
        proj = f.split(os.sep)[-4]
        if project and project.lower() not in proj.lower():
            continue
        try:
            if stale(os.stat(f).st_mtime, since):
                continue
        except OSError:
            continue
        u = _scan_file(f, cutoff, want_tokens)
        if u:
            u["project"] = proj
            units.append(u)
    return units


def match_reviews(units: list[dict], ledger: dict) -> None:
    """Set `matched` (reviews of any round) and `p1` (first-round P1s, one count per reviewed commit)
    on every unit, in place."""
    from .reviews import _same_sha
    by_prefix = defaultdict(list)
    for r in ledger["reviews"]:
        by_prefix[r["sha"][:7]].append(r)
    for u in units:
        start = _when(u["first"])
        hits = {}
        for tok in u["tokens"]:
            for r in by_prefix.get(tok[:7], ()):
                if not _same_sha(tok, r["sha"]):
                    continue
                at = _when(r["time"])
                if start and at and at < start:           # reviewed before this lane began: not its work
                    continue
                hits[r["seq"]] = r
        newest = {}                                       # a commit reviewed twice counts once, by its last review
        for r in hits.values():
            if r["mode"] in FIRST_ROUND and r["seq"] > newest.get(r["sha"], {"seq": -1})["seq"]:
                newest[r["sha"]] = r
        u["matched"] = len(hits) > 0
        u["p1"] = sum(r["p1"] for r in newest.values())


def summarize(units: list[dict], with_ledger: bool) -> list[dict]:
    groups = defaultdict(list)
    for u in units:
        groups[(u["type"], u["model"])].append(u)
    rows = []
    for (kind, model), us in groups.items():
        row = dict(type=kind, model=model, units=len(us),
                   median_turns=statistics.median(u["turns"] for u in us),
                   median_peak=statistics.median(u["peak"] for u in us),
                   median_usd=round(statistics.median(u["usd"] for u in us), 2),
                   total_usd=round(sum(u["usd"] for u in us), 2),
                   matched=None, p1_per_unit=None, units_with_p1=None)
        if with_ledger:
            m = [u for u in us if u.get("matched")]
            row.update(matched=len(m), units_with_p1=sum(1 for u in m if u["p1"] > 0),
                       p1_per_unit=round(sum(u["p1"] for u in m) / len(m), 2) if m else None)
        rows.append(row)
    return sorted(rows, key=lambda r: -r["total_usd"])


def report(days: int | None = 7, project: str | None = None, root: str | None = None,
           ledger: pathlib.Path | None = None, now: _dt.datetime | None = None) -> dict:
    from . import reviews
    units = scan(days, project, root, now)
    path = reviews.ledger_path() if ledger is None else ledger
    led = reviews.load_ledger(path)
    if led is not None:
        match_reviews(units, led)
    return dict(days=days, project=project, units=len(units), ledger=str(path) if led is not None else None,
                total_usd=round(sum(u["usd"] for u in units), 2), rows=summarize(units, led is not None))


CONFOUNDED = ("P1 per unit is confounded by task difficulty: hard lanes get the strong model and find more. "
              "A match is a commit sha in the lane's transcript that a later review covered.")


def render(rep: dict) -> str:
    from .spend import _money
    where = f" in projects matching {rep['project']!r}" if rep["project"] else ""
    L = [f"teyla lanes — {rep['units']} subagent lanes{where}, last {rep['days']} days, API list price, "
         f"{_money(rep['total_usd'])} in all", ""]
    if not rep["rows"]:
        return "\n".join(L + ["no subagent lanes in the window"])
    head = (f"{'type':<22} {'model':<20} {'units':>5} {'turns':>6} {'peak ctx':>9} {'med $':>8} {'total $':>9}"
            f" {'matched':>8} {'P1/unit':>8} {'with P1':>8}")
    L.append(head)
    for r in rep["rows"]:
        led = rep["ledger"] is not None
        L.append(f"{r['type'][:22]:<22} {r['model'][:20]:<20} {r['units']:>5} {r['median_turns']:>6.0f} "
                 f"{r['median_peak'] / 1000:>8.0f}k {_money(r['median_usd']):>8} {_money(r['total_usd']):>9} "
                 f"{(r['matched'] if led else '-'):>8} "
                 f"{('-' if not led or r['p1_per_unit'] is None else format(r['p1_per_unit'], '.2f')):>8} "
                 f"{(r['units_with_p1'] if led else '-'):>8}")
    L.append("")
    if rep["ledger"] is None:
        L.append("no review ledger: the matched and P1 columns are empty")
    L.append(CONFOUNDED)
    return "\n".join(L)


def cmd_lanes(args) -> int:
    rep = report(args.days, args.project)
    print(json.dumps(dict(rep, footer=CONFOUNDED), indent=1) if args.json else render(rep))
    return 0


def register(sp):
    q = sp.add_parser("lanes", help="subagent lanes by type and model: units, turns, peak context, cost, and the P1s their reviews found")
    q.set_defaults(fn=cmd_lanes)
    q.add_argument("--days", type=int, default=7, help="window by message time (default 7)")
    q.add_argument("--project", metavar="SUBSTR", help="only projects whose transcript folder name contains SUBSTR")
    q.add_argument("--json", action="store_true")
    return q
