"""Ask triage: which open questions need you, which an agent can act on, and which look closable.

    teyla asks triage [--json]            the buckets; reads the done store and the cache, writes nothing
    teyla asks accept-close [id...]       close the asks in bucket `close`; the only way they close

Every open question gets, when it can, a `triage` object: `bucket` (owner | agent | close), `action` (pay | decide
| do, or empty), `default` (a proposed answer, or empty), `why` (at most 12 words) and `source` (rule | model).

Rules run first and decide alone wherever they can (`rule`). The model sees only what the rules left, through
`state.refresh_triage` (one `claude -p` call, the same setting as the brief), and its answer is cached per ask id
and per text (`~/.teyla/state-triage.json`), so a question is classified once unless its words change.

The hard floor, enforced here in code and not in the prompt:

- `rule` runs before the cache is read. An ask that `asks.needs_owner` (a price, a key, a person) is `owner`
  whatever the model said.
- A model `close` closes nothing. The ask stays open with bucket `close`; only `accept_close`, run by the owner,
  writes the done store. A model `agent` only moves the ask out of the owner count.
- Age closes nothing, and similarity merges nothing: this module never compares two questions.
- An ask the owner reopened (`undone`) is `owner`.
- When the setting is off or the call fails, the ask has no `triage` and counts as an ordinary owner question.

Question text is data: the prompt says so and `validate` accepts only the exact enum values.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

from . import asks
from .control import state as control

BUCKETS = ("owner", "agent", "close")
ACTIONS = ("pay", "decide", "do", "")
SOURCES = ("rule", "model")
WHY_WORDS = 12
DEFAULT_WORDS = 20
DEFAULT_CHARS = 160
BLOCKER_WORDS = 12
CACHE_VERSION = 1
CACHE_KEEP_DAYS = 30
ACCEPT_NOTE = "accepted: triage close"        # not "auto:" — the owner closed it, so it is not in `auto_closed`

_BUCKET_ORDER = {"owner": 0, "agent": 1, "close": 2}


# --- small helpers ----------------------------------------------------------------------------

def words(text, n: int) -> str:
    """At most n words of `text`, whitespace collapsed, with an ellipsis when cut."""
    w = str(text or "").split()
    return " ".join(w) if len(w) <= n else " ".join(w[:n]) + "…"


def _tidy(text, n_words: int, n_chars: int = 0) -> str:
    """One line, at most `n_words` words and `n_chars` characters (0 = no limit): control characters go."""
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    t = words(t, n_words)
    return t[:n_chars].rstrip() if n_chars and len(t) > n_chars else t


def _as_ask(row: dict) -> asks.Ask:
    """The `Ask` a state row stands for, for the rules that take one (`asks.needs_owner`)."""
    return asks.Ask(id=str(row.get("id") or ""), kind=str(row.get("kind") or "question"), product=str(row.get("product") or ""),
                    title=str(row.get("title") or ""), question=str(row.get("question") or ""),
                    context=str(row.get("context") or ""), options=list(row.get("options") or []), when=0.0,
                    archived=False, link="", pr="", harness="")


def text_hash(row: dict) -> str:
    """The words of a question: a cached model answer is good only while they stay the same."""
    parts = [str(row.get(k) or "") for k in ("title", "question", "context")] + [str(o) for o in row.get("options") or []]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def make(bucket: str, action: str, default: str, why: str, source: str) -> dict:
    return {"bucket": bucket, "action": action, "default": default, "why": why, "source": source}


# --- the rules ---------------------------------------------------------------------------------

_DEVICE_RE = re.compile(
    r"\b(?:tap|taps|sign[ -]?in|log[ -]?in|enter the (?:code|passcode)|scan the|plug in|unlock"
    r"|on your (?:iphone|ipad|mac|phone|device|watch|tv)|in your browser)\b", re.I)
_PERMISSION_RE = re.compile(
    r"\b(?:shall i|should i|want me to|would you like me to|do you want me to|ok(?:ay)? to|may i|can i"
    r"|ready for me to)\b", re.I)
_HAZARD_RE = re.compile(
    r"\b(?:merge[sd]?|deploy\w*|releas\w+|publish\w*|submit\w*|ship\w*|delet\w+|remov\w+|drop\w*|force\w*|send\w*"
    r"|e-?mail\w*|post\w*|purchas\w+|buy\w*|pay\w*|spend\w*|cost\w*|install\w*|production|app store|testflight|review\w*"
    r"|reset|wipe\w*|overwrit\w+|renam\w+|migrat\w+|rotat\w+|revok\w+|public\w*|main|master)\b", re.I)
PERMISSION_MAX = 240


def _is_permission(row: dict) -> bool:
    """A short yes/no permission question about a routine step ("Want me to add the test?"): one question mark, no
    choice, no options, and none of the words that mean money, publishing, deleting or a release."""
    q = str(row.get("question") or "").strip()
    if not q or len(q) > PERMISSION_MAX or q.count("?") != 1 or row.get("options"):
        return False
    text = f"{row.get('title') or ''}\n{q}\n{row.get('context') or ''}"
    return bool(_PERMISSION_RE.search(q)) and not re.search(r"\bor\b", q, re.I) and not _HAZARD_RE.search(text)


def rule(row: dict, known: frozenset = frozenset()) -> dict | None:
    """The triage a rule decides alone, or None when only the model could say. `needs_owner` comes first and
    nothing downstream can overrule it."""
    a = _as_ask(row)
    if asks.needs_owner(a, known):
        text = f"{a.title}\n{a.question}\n{a.context}"
        if asks._MONEY_RE.search(text):
            return make("owner", "pay", "", "Names a price or a charge.", "rule")
        if asks._SECRET_RE.search(text):
            return make("owner", "do", "", "Needs a key or a login only you hold.", "rule")
        return make("owner", "decide", "", "Names a person or needs your word.", "rule")
    if a.kind == "reminder":
        return make("owner", "do", "", "A reminder you set for yourself.", "rule")
    if a.kind == "gate":
        return make("owner", "decide", "", "A gated run waits for your go.", "rule")
    if len(a.options) >= 2:
        return make("owner", "decide", "", "Offers you a choice.", "rule")
    if _DEVICE_RE.search(f"{a.title}\n{a.question}\n{a.context}"):
        return make("owner", "do", "", "A step only you can take on your device.", "rule")
    if _is_permission(row):
        return make("agent", "", "Yes, go ahead.", "A routine permission question; the agent can proceed.", "rule")
    return None


def decide(row: dict, cache: dict | None, known: frozenset = frozenset(), undone=frozenset(),
           use_model: bool = False) -> dict | None:
    """The triage of one row: an ask you reopened is yours; then the rules; then, only when `use_model`, the cached
    model answer for exactly these words. None means no triage (the ask is an ordinary owner question)."""
    if str(row.get("id")) in undone:
        return make("owner", "", "", "You reopened it.", "rule")
    r = rule(row, known)
    if r is not None:
        return r
    if not use_model:
        return None
    e = ((cache or {}).get("items") or {}).get(str(row.get("id")))
    if not isinstance(e, dict) or e.get("h") != text_hash(row):
        return None
    if e.get("bucket") not in BUCKETS or e.get("action") not in ACTIONS:
        return None
    return make(e["bucket"], e["action"] if e["bucket"] == "owner" else "", _tidy(e.get("default"), DEFAULT_WORDS, DEFAULT_CHARS),
                _tidy(e.get("why"), WHY_WORDS), "model")


def apply(rows: list[dict], *, cache: dict | None = None, known: frozenset = frozenset(), undone=frozenset(),
          use_model: bool = False) -> int:
    """Set `row["triage"]` where rules or the cache decide (removing a stale one where not). Returns how many
    non-muted rows are left without triage while the model is on: the work the next refresh has to do."""
    pending = 0
    for r in rows:
        t = decide(r, cache, known, undone, use_model)
        if t is None:
            r.pop("triage", None)
            if use_model and not r.get("muted"):
                pending += 1
        else:
            r["triage"] = t
    return pending


def counts_for_owner(row: dict) -> bool:
    """An ask with no triage counts as an owner question: a missing answer never hides anything."""
    t = row.get("triage")
    return not isinstance(t, dict) or t.get("bucket") == "owner"


def order(rows: list[dict]) -> list[dict]:
    """Owner questions first, then agent, then close, then muted; the order inside each group is kept. Ranks
    are renumbered 1..n."""
    def key(r):
        t = r.get("triage") or {}
        return (1, 0) if r.get("muted") else (0, _BUCKET_ORDER.get(t.get("bucket"), 0))
    out = sorted(rows, key=key)
    for n, r in enumerate(out, 1):
        r["rank"] = n
    return out


def blocker(rows: list[dict]) -> str:
    """The product's top owner question as a blocker, at most 12 words; empty when there is none. `rows` are the
    product's state rows in rank order."""
    mine = [r for r in rows if not r.get("muted") and counts_for_owner(r)]
    if not mine:
        return ""
    top = min(mine, key=lambda r: r.get("rank", 10 ** 9))
    text = re.sub(r"[*_`#]+", "", str(top.get("question") or top.get("title") or ""))
    return words(re.sub(r"\s+", " ", text).strip(), BLOCKER_WORDS)


# --- the model's answer ------------------------------------------------------------------------

def validate(reply, ids: set[str]) -> dict[str, dict] | None:
    """{id: {bucket, action, default, why}} from the model's reply, or None when it cannot be trusted. Only the
    exact enum values pass: an unknown bucket or action, an unknown or repeated id, a non-string field or no
    items at all rejects the whole reply. `why` and `default` are cut. An id the model left out is simply not
    classified."""
    if not isinstance(reply, dict) or not isinstance(reply.get("items"), list) or not reply["items"]:
        return None
    out: dict[str, dict] = {}
    for it in reply["items"]:
        if not isinstance(it, dict):
            return None
        i, bucket, action = it.get("id"), it.get("bucket"), it.get("action", "")
        if not isinstance(i, str) or i not in ids or i in out:
            return None
        if not isinstance(bucket, str) or bucket not in BUCKETS or not isinstance(action, str) or action not in ACTIONS:
            return None
        default, why = it.get("default", ""), it.get("why", "")
        if not isinstance(default, str) or not isinstance(why, str):
            return None
        out[i] = {"bucket": bucket, "action": action if bucket == "owner" else "",
                  "default": _tidy(default, DEFAULT_WORDS, DEFAULT_CHARS), "why": _tidy(why, WHY_WORDS)}
    return out


# --- the cache ---------------------------------------------------------------------------------

def cache_path():
    return control.home() / "state-triage.json"


def load_cache() -> dict:
    try:
        c = json.loads(cache_path().read_text())
        if isinstance(c, dict) and isinstance(c.get("items"), dict):
            return {"version": CACHE_VERSION, "items": c["items"]}
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "items": {}}


def store(cache: dict, rows_by_id: dict[str, dict], answers: dict[str, dict], now: float) -> dict:
    """The cache with the model's answers added for the exact text of each row; entries older than 30 days go."""
    cut = asks._iso(now - CACHE_KEEP_DAYS * 86400)
    items = {k: v for k, v in cache.get("items", {}).items() if isinstance(v, dict) and str(v.get("at", "")) >= cut}
    for i, a in answers.items():
        if i in rows_by_id:
            items[i] = {"h": text_hash(rows_by_id[i]), "at": asks._iso(now), **a}
    return {"version": CACHE_VERSION, "items": items}


def save_cache(cache: dict) -> None:
    asks._atomic_write(cache_path(), json.dumps(cache, indent=1, sort_keys=True) + "\n")


# --- stale tasks -------------------------------------------------------------------------------

_MERGE_RE = re.compile(r"\bmerg(?:e|es|ed|ing)\b", re.I)


def drop_stale_tasks(tasks: list[dict], items: list[asks.Ask]) -> list[dict]:
    """The owner's tasks without those whose question is already closed. A merge task is stale when a done ask about
    merging that PR exists and no open ask names it; closing another question on the PR (its title, say) leaves the
    merge decision open. Issue tasks have no question behind them."""
    from . import backlog                   # backlog imports asks
    closed: set[str] = set()
    live: set[str] = set()
    for a in items:
        url = backlog.canonical_pr_url(a.pr)
        if not url:
            continue
        if a.status == "done":
            if _MERGE_RE.search(f"{a.question}\n{a.note}"):     # not the title: it names the session, not this question
                closed.add(url)
        elif a.status in ("open", "snoozed"):
            live.add(url)
    stale = closed - live
    return [t for t in tasks if not (t.get("kind") == "merge" and backlog.canonical_pr_url(t.get("link")) in stale)]


# --- the commands ------------------------------------------------------------------------------

def _context(now: float, *, use_model: bool | None = None, st: dict | None = None):
    """(state rows with triage, known words, the done store, whether the model's cache counts)."""
    from . import registry, state
    st = asks.load_state() if st is None else st
    reg = registry.load()
    if use_model is None:
        use_model = state.model_brief_enabled()
    items = asks.collect(asks.DEFAULT_DAYS, now, st=st)
    rows = state.ranked(items, now, reg)
    apply(rows, cache=load_cache(), known=asks._known_words(reg), undone=set(st.get("undone") or ()), use_model=use_model)
    return items, rows, st, use_model


def _row_json(r: dict) -> dict:
    return {"id": r["id"], "product": r["product"], "title": r["title"], "question": asks.clip(r["question"], 300),
            "age_s": r["age_s"], "muted": bool(r.get("muted")), "triage": r.get("triage")}


def summary(rows: list[dict]) -> dict:
    live = [r for r in rows if not r.get("muted")]
    n = {b: sum(1 for r in live if (r.get("triage") or {}).get("bucket") == b) for b in BUCKETS}
    n["untriaged"] = sum(1 for r in live if not r.get("triage"))
    n["raw"] = len(live)
    n["owner_count"] = sum(1 for r in live if counts_for_owner(r))
    return n


def render_text(rows: list[dict], counts: dict, closed: dict, use_model: bool) -> str:
    live = [r for r in rows if not r.get("muted")]
    lines = [f"{counts['owner_count']} need you, {counts['agent']} for the agents, {counts['close']} to close "
             f"({counts['raw']} open)"]
    groups = (("owner", "Need you", lambda r: counts_for_owner(r)),
              ("agent", "Agents can act (nothing is closed)", lambda r: (r.get("triage") or {}).get("bucket") == "agent"),
              ("close", "Look closable (nothing is closed until you accept)", lambda r: (r.get("triage") or {}).get("bucket") == "close"))
    for _, head, pick in groups:
        sel = [r for r in live if pick(r)]
        if not sel:
            continue
        lines += ["", f"{head} ({len(sel)})"]
        for r in sel:
            t = r.get("triage") or {}
            tag = (t.get("action") or "-") if t else "untriaged"
            lines.append(f"  {r['id']}  {tag:<9} {r['product']}: {words(r['question'].replace(chr(10), ' '), 18)}")
            if t.get("why"):
                lines.append(f"      why: {t['why']}" + (f"   default: {t['default']}" if t.get("default") else ""))
    if counts["close"]:
        lines += ["", "close the ones above: teyla asks accept-close"]
    if not use_model and counts["untriaged"]:
        lines += ["", f"{counts['untriaged']} not triaged by a rule; the model is off (teyla config set state.model_brief=true)"]
    if closed["count"]:
        lines += ["", f"Teyla closed {closed['count']} on its own in the last 24 hours — teyla asks --all"]
    return "\n".join(lines)


def cmd_triage(args, now: float) -> int:
    """`teyla asks triage`: reads the done store and the cache, calls nothing and writes nothing."""
    items, rows, st, use_model = _context(now)
    closed = asks.auto_closed(items, st, now)
    if getattr(args, "product", None):
        rows = [r for r in rows if r["product"] == args.product]
    counts = summary(rows)
    if getattr(args, "json", False):
        print(json.dumps({"generated": asks._iso(now), "model": use_model, "counts": counts,
                          "items": [_row_json(r) for r in rows if not r.get("muted")], "auto_closed": closed}, indent=1))
    else:
        print(render_text(rows, counts, closed, use_model))
    return 0


def accept_close(prefixes: list[str], now: float, *, use_model: bool | None = None) -> tuple[dict, int]:
    """Close the open asks whose triage bucket is `close` (or only those named by `prefixes`). Another bucket is
    refused: an ask in `owner` or `agent` is never closed here. Returns ({closed, errors, undo}, exit code)."""
    items, rows, st, _ = _context(now, use_model=use_model)
    by_id = {a.id: a for a in items}
    close = [r for r in rows if not r.get("muted") and (r.get("triage") or {}).get("bucket") == "close"]
    errors: list[str] = []
    if prefixes:
        picked = []
        for pre in prefixes:
            a, err = asks.resolve(pre, [by_id[r["id"]] for r in rows if r["id"] in by_id])
            if a is None:
                errors.append(err)
            elif a.id not in {r["id"] for r in close}:
                errors.append(f"{a.id} is not in bucket close: nothing was closed")
            else:
                picked.append(a.id)
        close = [r for r in close if r["id"] in set(picked)]
    for r in close:
        st["done"][r["id"]] = {"ts": asks._iso(now), "note": ACCEPT_NOTE}
        st["snoozed"].pop(r["id"], None)
    if close:
        asks.save_state(st, now=now)
    ids = [r["id"] for r in close]
    out = {"closed": [{"id": r["id"], "product": r["product"], "title": r["title"]} for r in close],
           "errors": errors, "undo": ("teyla asks undo " + " ".join(ids)) if ids else ""}
    return out, 1 if errors else 0


def cmd_accept_close(args, words_: list[str], now: float) -> int:
    out, code = accept_close(words_, now)
    if getattr(args, "json", False):
        print(json.dumps(out, indent=1))
        return code
    lines = [f"closed: {c['id']}  {c['product']}  {c['title']}" for c in out["closed"]]
    if out["closed"]:
        lines.append(f"closed {len(out['closed'])}")
        lines.append("undo: " + out["undo"])
    elif not out["errors"]:
        lines.append("nothing is in bucket close")
    print("\n".join(lines))
    for e in out["errors"]:
        print(e, file=sys.stderr)
    return code
