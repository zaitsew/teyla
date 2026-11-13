"""Inbox expiry: `teyla asks expire [--older-than DAYS] [--product P] [--json] [--apply] [--note TEXT]`.

A question older than DAYS (default 14) takes its default or is dropped. The default mode is a dry run: it lists
each candidate and the outcome it would get, and changes nothing. `--apply` closes them in the done store, the
same way `teyla asks done` does. It sends no answer into any session (`teyla answer` does that).

The default of an ask is never guessed. First match wins, and the rule is recorded as `default_source`:
  triage       the cached triage default (`~/.teyla/state-triage.json`, read only, no model call)
  recommended  an option marked "(Recommended)"
  stated       a sentence in the question or context that states a default
  design       the first option of a design card (recommended first by contract)
  none         no default: the outcome is `drop`
An ask that needs the owner (a price, a key, a person) or is critical is never expired: outcome `keep`.
"""
from __future__ import annotations

import json
import re
import sys

from . import asks

DEFAULT_OLDER_THAN = 14.0
CLIP_DEFAULT = 160
CLIP_TITLE = 70
OUTCOMES = ("default", "drop", "keep")

_RECOMMENDED_RE = re.compile(r"\s*\(\s*recommended\s*\)\s*", re.I)
_STATED_RE = re.compile(
    r"\bdefault\s*:|\bby default\b|\bif you say nothing\b|\bdefault if you do nothing\b"
    r"|\bunless you say otherwise\b", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _clip(text: str, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _option_text(o) -> str:
    if isinstance(o, dict):
        return str(o.get("label") or o.get("title") or o.get("text") or "")
    return str(o or "")


def stated_default(a: asks.Ask) -> str:
    """The first sentence of the question or context that states a default, clipped."""
    for text in (a.question, a.context):
        for s in _SENTENCE_SPLIT.split(str(text or "")):
            if _STATED_RE.search(s):
                return _clip(s.strip(), CLIP_DEFAULT)
    return ""


def find_default(a: asks.Ask, now: float, cache: dict, known: frozenset, undone) -> tuple[str, str]:
    """(default text, source). Source is `none` and the text empty when no rule matches."""
    from . import triage
    t = triage.decide(a.to_dict(now), cache, known, undone, use_model=True)
    if t and str(t.get("default") or "").strip():
        return _clip(t["default"], CLIP_DEFAULT), "triage"
    options = [_option_text(o) for o in a.options or []]
    for o in options:
        if _RECOMMENDED_RE.search(o):
            return _clip(_RECOMMENDED_RE.sub(" ", o), CLIP_DEFAULT), "recommended"
    s = stated_default(a)
    if s:
        return s, "stated"
    if a.harness == asks.DESIGN_HARNESS and options and options[0].strip():
        return _clip(options[0], CLIP_DEFAULT), "design"
    return "", "none"


def candidates(days: float, product: str = "", now: float | None = None) -> list[dict]:
    """Open questions older than `days`, oldest first, each with its outcome. Local data only."""
    from . import registry, triage
    now = asks._now() if now is None else now
    cutoff = now - days * 86400
    old = [a for a in asks.collect(max(asks.DEFAULT_DAYS, 365, int(days) + 365), now)
           if a.status == "open" and a.kind != "reminder" and a.when < cutoff
           and (not product or a.product == product)]
    old.sort(key=lambda a: a.when)
    reg = registry.load()
    known = asks._known_words(reg)
    undone = set(asks.load_state().get("undone") or ())
    cache = triage.load_cache()
    items = []
    for a in old:
        default, source = "", "none"
        if asks.is_critical(a):
            outcome, reason = "keep", "critical"
        elif asks.needs_owner(a, known):
            outcome, reason = "keep", "needs the owner (money, key or person)"
        else:
            default, source = find_default(a, now, cache, known, undone)
            outcome = "default" if default else "drop"
            reason = f"default from {source}" if default else "no default found"
        items.append({"id": a.id, "product": a.product, "title": a.title, "age_days": int((now - a.when) // 86400),
                      "age": asks.fmt_age(now - a.when), "kind": a.kind, "muted": asks.is_muted(a, reg),
                      "outcome": outcome, "default": default, "default_source": source, "reason": reason})
    return items


def render_json(items: list[dict], days: float) -> str:
    rows = [{k: v for k, v in i.items() if k != "age"} for i in items]
    counts = {o: sum(1 for i in items if i["outcome"] == o) for o in OUTCOMES}
    return json.dumps({"version": 1, "older_than_days": days, "dry_run": True, "items": rows, "counts": counts},
                      indent=1)


def render_text(items: list[dict], days: float) -> str:
    n = len(items)
    out = [f"{n} question{'' if n == 1 else 's'} {'is' if n == 1 else 'are'} older than {days:g} days. "
           "Dry run: nothing changed."]
    titles = {"default": "Would take its default", "drop": "Would be dropped (no default found)",
              "keep": "Kept (never expired)"}
    for o in OUTCOMES:
        group = [i for i in items if i["outcome"] == o]
        if not group:
            continue
        out += ["", f"{titles[o]} ({len(group)})"]
        for i in group:
            flag = " [muted]" if i["muted"] else ""
            out.append(f"  {i['id']}  {i['product']}  {i['age']}  {_clip(i['title'], CLIP_TITLE)}{flag}")
            if o == "default":
                out.append(f"      default ({i['default_source']}): {i['default']}")
            elif o == "keep":
                out.append(f"      {i['reason']}")
    if n:
        out += ["", "Apply: teyla asks expire --apply   (closes default and drop only; sends no answer to any session)",
                "Undo:  teyla asks undo <id>...   (reopens)"]
    return "\n".join(out)


def apply(items: list[dict], note: str = "", now: float | None = None) -> list[str]:
    """Close every non-keep item in the done store, like `asks.mark_done`. Sends nothing to any session."""
    now = asks._now() if now is None else now
    st = asks.load_state()
    lines, closed = [], []
    for i in items:
        if i["outcome"] == "keep":
            continue
        what = (f"expired: default {i['default']} ({i['default_source']})" if i["outcome"] == "default"
                else "expired: dropped")
        st["done"][i["id"]] = {"ts": asks._iso(now), "note": f"{note} {what}".strip() if note else what}
        st["snoozed"].pop(i["id"], None)
        closed.append(i["id"])
        lines.append(f"closed: {i['id']}  {i['product']}  {_clip(i['title'], CLIP_TITLE)}  ({i['outcome']})")
    if closed:
        asks.save_state(st, now=now)
        lines += [f"closed {len(closed)}", "Undo: teyla asks undo " + " ".join(closed)]
    else:
        lines.append("nothing to close")
    return lines


def cmd_expire(args, words: list[str], now: float) -> int:
    if words:
        print("usage: teyla asks expire [--older-than DAYS] [--product P] [--json] [--apply] [--note TEXT]",
              file=sys.stderr)
        return 64
    days = DEFAULT_OLDER_THAN if args.older_than is None else args.older_than
    if days <= 0:
        print("--older-than needs a number of days above 0", file=sys.stderr)
        return 64
    items = candidates(days, args.product or "", now)
    if getattr(args, "apply", False):
        print("\n".join(apply(items, args.note or "", now)))
        return 0
    print(render_json(items, days) if args.json else render_text(items, days))
    return 0
