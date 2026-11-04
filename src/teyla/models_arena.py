"""`teyla models arena`: the cost/value shortlist from arena.ai's agent Pareto board, as a candidate list.

    teyla models arena [--refresh] [--json] [--allow-network]

The board is https://arena.ai/leaderboard/agent/pareto. Two sources, newest `as_of` wins (the pasted one on a tie):

1. `~/.teyla/models/arena.json`, a snapshot the owner pastes (or an agent with a browser writes). Its schema is
   below. Teyla reads it and never edits it.
2. `--refresh`: one plain GET of the page (a public page, no user data; PRIVACY row 37), closed in safe mode through
   `net.py`. The page sits behind a bot check (a Cloudflare "Just a moment" page, HTTP 403 on 2026-11-04). Teyla does
   not try to pass a bot check. When the answer is a challenge, or the HTML holds no table it can read reliably, it
   reads nothing, says so, and leaves the pasted snapshot in charge. The last attempt is kept in
   `~/.teyla/models/arena-fetch.json`.

A ranking is a shortlist of candidates, never a decision: nothing here changes the ladder, a config or a route.
Policy §1 still decides, per route, on measured quality, speed and value.

Snapshot schema (`arena.json`):

    {"as_of": "2026-11-04", "source": "pasted", "unit": "USD per task",
     "entries": [{"model": "Example Model 1", "score": 1450, "cost": 0.35, "pareto": true}, ...]}

`model` is required; `score`, `cost` and `pareto` are optional. `as_of` is an ISO date.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import sys

from . import config, net

URL = "https://arena.ai/leaderboard/agent/pareto"
SNAPSHOT = "arena.json"
FETCHED = "arena-fetch.json"
STALE_DAYS = 14
MAX_ENTRIES = 40
MAX_BYTES = 4_000_000
NOT_A_DECISION = "candidate, not a decision"


def models_dir() -> pathlib.Path:
    return config.TEYLA_DIR / "models"


def snapshot_path() -> pathlib.Path:
    return models_dir() / SNAPSHOT


def fetched_path() -> pathlib.Path:
    return models_dir() / FETCHED


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*\$?\s*(-?\d+(?:[.,]\d+)?)\s*", v)
        return float(m.group(1).replace(",", ".")) if m else None
    return None


def _date(v) -> str | None:
    try:
        return _dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def clean(data) -> dict | None:
    """A snapshot in the documented shape, or None. Entries without a model name are dropped; at most MAX_ENTRIES kept."""
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    as_of = _date(data.get("as_of"))
    rows = []
    for e in data["entries"]:
        if not isinstance(e, dict) or not isinstance(e.get("model"), str) or not e["model"].strip():
            continue
        rows.append(dict(model=e["model"].strip()[:80], score=_num(e.get("score")), cost=_num(e.get("cost")),
                         pareto=e.get("pareto") if isinstance(e.get("pareto"), bool) else None))
        if len(rows) >= MAX_ENTRIES:
            break
    if not rows or not as_of:
        return None
    return dict(as_of=as_of, source=str(data.get("source") or "")[:20], unit=str(data.get("unit") or "")[:40], entries=rows)


def _read(path: pathlib.Path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# --- reading the page ---------------------------------------------------------------------------

_CHALLENGE = re.compile(r"just a moment|cf-chl|challenge-platform|enable javascript and cookies", re.I)
_NEXT_DATA = re.compile(r'<script[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_NAME_KEYS = ("model", "modelName", "model_name", "name")
_SCORE_KEYS = ("score", "rating", "elo", "performance")
_COST_KEYS = ("cost", "costPerTask", "cost_per_task", "price")


def is_challenge(status: int | None, headers: dict, body: str) -> bool:
    """A bot check, not the page: a 403/429/503, Cloudflare's mitigation header, or its interstitial."""
    low = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    return bool(status in (403, 429, 503) or "challenge" in low.get("cf-mitigated", "") or _CHALLENGE.search(body[:20000]))


def _walk(node, out: list):
    if isinstance(node, list):
        rows = [r for r in node if isinstance(r, dict) and any(isinstance(r.get(k), str) for k in _NAME_KEYS)
                and any(_num(r.get(k)) is not None for k in _SCORE_KEYS + _COST_KEYS)]
        if len(rows) >= 3 and len(rows) >= len(node) // 2:
            out.append(rows)
        for x in node:
            _walk(x, out)
    elif isinstance(node, dict):
        for x in node.values():
            _walk(x, out)


def parse_page(html: str) -> dict | None:
    """Rows from the page's embedded JSON (`__NEXT_DATA__`), when it holds a list of at least three records that
    each have a model name and a score or a cost. Anything else is not read: no scraping of rendered markup."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    found: list = []
    _walk(data, found)
    if not found:
        return None
    best = max(found, key=len)
    entries = []
    for r in best:
        name = next(r[k] for k in _NAME_KEYS if isinstance(r.get(k), str))
        entries.append(dict(model=name,
                            score=next((_num(r[k]) for k in _SCORE_KEYS if _num(r.get(k)) is not None), None),
                            cost=next((_num(r[k]) for k in _COST_KEYS if _num(r.get(k)) is not None), None)))
    return clean(dict(as_of=_dt.date.today().isoformat(), source="fetched", entries=entries))


def _get(url: str) -> tuple[int | None, dict, str]:
    """(status, headers, body) of one plain GET. Tests replace this one function."""
    import urllib.error
    import urllib.request
    from .update import ssl_context
    req = urllib.request.Request(url, headers={"User-Agent": "teyla-models/1", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:  # noqa: S310 — public page, explicit --refresh only
            return r.status, dict(r.headers), r.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read(20000).decode("utf-8", "replace") if e.fp else "")


def refresh(today: _dt.date | None = None) -> dict:
    """One attempt to read the board. Returns and stores `{checked, status, http}`:
    status is `ok`, `blocked` (a bot check), `unreadable` (a page with no table Teyla can read reliably),
    `offline` or `safe_mode`. Only `ok` carries `snapshot`."""
    today = (today or _dt.date.today()).isoformat()
    rep: dict = dict(checked=today, url=URL)
    if not net.gate(f"fetching {URL}", quiet=True):
        rep.update(status="safe_mode", http=None)
        return rep           # a refusal is not stored: it says nothing about the page
    try:
        status, headers, body = _get(URL)
    except Exception as e:  # noqa: BLE001 — a network error is a status, never a crash
        rep.update(status="offline", http=None, error=type(e).__name__)
        _store(rep)
        return rep
    rep["http"] = status
    if is_challenge(status, headers, body):
        rep["status"] = "blocked"
    else:
        snap = parse_page(body) if status == 200 else None
        rep["status"] = "ok" if snap else "unreadable"
        if snap:
            rep["snapshot"] = snap
    _store(rep)
    return rep


def _store(rep: dict) -> None:
    try:
        config.write_private(fetched_path(), json.dumps(rep, indent=1) + "\n")
    except OSError:
        pass


# --- the shortlist ------------------------------------------------------------------------------

def load(today: _dt.date | None = None) -> dict:
    """The board as the owner can use it today: `{as_of, source, unit, stale, entries, last_fetch}`, or `entries: []`
    with a `note` that says why there is nothing."""
    today = today or _dt.date.today()
    cands = []
    snap = clean(_read(snapshot_path()))
    if snap:
        cands.append((snap["as_of"], 1, snap))
    fetched = _read(fetched_path())
    last = None
    if isinstance(fetched, dict):
        last = {k: fetched.get(k) for k in ("checked", "status", "http")}
        f = clean(fetched.get("snapshot"))
        if f:
            cands.append((f["as_of"], 0, f))
    if not cands:
        why = {"blocked": "the page is behind a bot check, so nothing was read",
               "unreadable": "the page holds no table Teyla can read reliably",
               "offline": "the page could not be reached"}.get((last or {}).get("status") or "", "")
        note = (why + "; " if why else "") + f"paste a snapshot into {_tilde(snapshot_path())} (schema in src/teyla/models_arena.py)"
        return dict(url=URL, as_of=None, source="", unit="", stale=None, entries=[], last_fetch=last, note=note)
    best = max(cands, key=lambda c: (c[0], c[1]))[2]
    age = (today - _dt.date.fromisoformat(best["as_of"])).days
    return dict(url=URL, as_of=best["as_of"], source=best["source"], unit=best["unit"], stale=age > STALE_DAYS,
                entries=best["entries"], last_fetch=last, note="")


def _tilde(p: pathlib.Path) -> str:
    s, home = str(p), str(pathlib.Path.home())
    return "~" + s[len(home):] if s.startswith(home) else s


PROVIDER_WORDS = {"claude", "gpt", "grok", "model", "the", "and"}


def _tokens(text: str, strip: bool = True) -> set[str]:
    toks = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))
    return toks - PROVIDER_WORDS if strip else toks


def in_ladder(model: str, ladder: dict) -> bool:
    """Does the policy ladder already name this model? Every word and number of a ladder entry's name (without
    the parenthesised note) appears in the board's name."""
    for rows in (ladder or {}).values():
        for tier in ("orchestrate", "volume", "triage"):
            for entry in rows.get(tier, []) or []:
                name = re.sub(r"\([^)]*\)", "", str(entry))
                # without the provider word two tokens must match ("Opus 5.5"); a name that has only one left
                # ("Grok 4.7") keeps its provider word
                for strip in (True, False):
                    toks = _tokens(name, strip)
                    if len(toks) >= 2 and toks <= _tokens(model, strip):
                        return True
                    if len(toks) >= 2:
                        break
    return False


def shortlist(board: dict, ladder: dict, limit: int = 8) -> list[dict]:
    """The top entries, Pareto ones first, then by score. Each says whether the ladder names it and that it is a
    candidate, not a decision."""
    rows = list(board.get("entries") or [])
    rows.sort(key=lambda r: (r.get("pareto") is not True, -(r.get("score") or 0), r.get("cost") if r.get("cost") is not None else 1e9))
    return [dict(r, in_ladder=in_ladder(r["model"], ladder), status=NOT_A_DECISION) for r in rows[:limit]]


def render(board: dict, rows: list[dict], attempt: dict | None = None) -> str:
    lines = [f"arena: {URL}"]
    if attempt:
        lines.append(f"fetch: {attempt['status']}" + (f" (HTTP {attempt['http']})" if attempt.get("http") else ""))
    if not board["entries"]:
        lines.append(board["note"])
        return "\n".join(lines) + "\n"
    lines.append(f"as of {board['as_of']} ({board['source'] or 'unknown source'})" + (" - stale" if board["stale"] else ""))
    unit = f" ({board['unit']})" if board["unit"] else ""
    lines.append(f"{'model':32} {'score':>8} {'cost' + unit:>16}  ladder  note")
    for r in rows:
        score = "-" if r["score"] is None else f"{r['score']:g}"
        cost = "-" if r["cost"] is None else f"{r['cost']:g}"
        lines.append(f"{r['model'][:32]:32} {score:>8} {cost:>16}  {'yes' if r['in_ladder'] else 'no':6}  {r['status']}")
    lines.append("A shortlist for the next ladder review. Nothing switches by itself.")
    return "\n".join(lines) + "\n"


def cmd_arena(args) -> int:
    attempt = refresh() if getattr(args, "refresh", False) else None
    if attempt and attempt["status"] == "safe_mode":
        print(net.refusal(f"fetching {URL}"), file=sys.stderr if args.json else sys.stdout)
    board = load()
    from . import models
    from . import policy as _policy
    ladder = models.parse_ladder(_policy.POLICY.read_text() if _policy.POLICY.exists() else "")
    rows = shortlist(board, ladder)
    if args.json:
        print(json.dumps(dict(board=board, shortlist=rows, attempt={k: v for k, v in (attempt or {}).items() if k != "snapshot"} or None),
                         indent=2, default=str))
    else:
        print(render(board, rows, attempt), end="")
    return 0 if board["entries"] else 1
