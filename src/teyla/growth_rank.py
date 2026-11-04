"""Which idea earns the next slot (docs/GROWTH.md, "The planner").

The editor passes a draft only when it has a number and an artifact a reader can open. The planner used to rank ideas by
a fixed score, so product spotlights and worklogs took slots the editor then held back, while stories with numbers
waited. This module ranks by what passes:

    story_class(item)       "story" (a lesson or spec-product with a number and an artifact), "lesson", or the format
    thin_reason(item)       why an idea cannot make a post at all ("" when it can): a bare product summary, or facts the
                            editor already called thin
    history(store)          per (source, format): how many drafts the editor passed and how many it held
    quality(item, hist)     0 to 1: a prior by class, pulled toward the observed pass rate as the history grows
    unused_stories(...)     stories still waiting for a slot

No model call and no network. Everything is read from the items and the ledger in ~/.teyla/growth/.
"""
from __future__ import annotations

import collections
import re

from . import growth as g

PRIOR_N = 3                                        # a prior counts as this many observed drafts
PRIOR = dict(story=0.85, lesson_partial=0.55, lesson=0.35, reaction=0.45, worklog=0.3, spotlight=0.1, other=0.3)
ELIGIBLE = 0.25                                    # a product with no sale attempts gets its bonus only at or above this

_ARTIFACT = re.compile(r"https?://\S+|`[^`\n]{2,}`|\bteyla [a-z][a-z-]+\b|\bPR #\d+|#\d{2,}\b", re.I)
_DIGITS = re.compile(r"(?<![\w#])[$€]?\d[\d,.]*")
_THIN = re.compile(r"\b(facts? (are|is|were) (too |very )?(thin|sparse|slight)|(too|very) thin|thin facts?|"
                   r"facts? (give|gives|hold|holds|carry|carries|contain|contains) (just|only)|the only facts? (is|are)|only fact is)\b", re.I)


def source_kind(item: dict) -> str:
    return str(((item.get("sources") or [{}])[0] or {}).get("kind") or "")


def has_number(item: dict) -> bool:
    text = " ".join([item.get("idea", ""), *(item.get("facts") or [])])
    return bool(_DIGITS.search(text))            # any figure counts: "3 calls" is a number, "PR #7" is a reference


def has_artifact(item: dict) -> bool:
    if item.get("artifact_missing"):                 # the story miner found none: the excerpt's own backticks do not count
        return False
    if any(str(s.get("url") or "").startswith("http") for s in item.get("sources") or [] if isinstance(s, dict) and s.get("kind") != "evergreen"):
        return True
    return bool(_ARTIFACT.search(" ".join([item.get("idea", ""), *(item.get("facts") or [])])))


def story_class(item: dict) -> str:
    """"story": a lesson or spec-product idea with a number and an artifact. "lesson-partial": one of the two. Otherwise
    the format name."""
    fmt = item.get("format", "")
    if fmt in ("lesson", "spec-product"):
        n, a = has_number(item), has_artifact(item)
        if n and a:
            return "story"
        return "lesson-partial" if (n or a) else fmt
    return fmt


def facts_called_thin(critique: str) -> bool:
    return bool(_THIN.search(critique or ""))


def thin_reason(item: dict, master: dict | None = None) -> str:
    """Why this idea cannot make a post, or "". A bare product summary has nothing to say but the registry line; an
    idea whose facts the editor already called thin stays thin until its facts change."""
    if item.get("format") == "product-spotlight" and source_kind(item) == "evergreen" and len(item.get("facts") or []) <= 1:
        return "thin: a bare product summary; a post needs a story or a demo fact"
    for it in (item, master or {}):
        if it.get("thin_facts"):
            return "thin: " + g.clip_text(str(it["thin_facts"]) if it["thin_facts"] is not True else "the editor already called these facts thin", 200)
    return ""


def outcome(item: dict) -> bool | None:
    """True when the editor passed this planned item, False when it was held or failed as thin, None when it says nothing
    about the idea (not drafted yet, a model failure, a video gap, a rejection by the owner)."""
    if item.get("platform") == g.MASTER:
        return None
    ed = item.get("editor")
    if isinstance(ed, dict) and isinstance(ed.get("score"), (int, float)):
        from . import growth_quality as q            # the editor's own verdict, not the item's status: an owner's edit or a
        hook = (ed.get("parts") or {}).get("hook")    # rejection later changes the status but not what the editor thought
        return ed["score"] >= q.EDITOR_BAR and isinstance(hook, (int, float)) and hook >= q.HOOK_FLOOR
    if item.get("status") == "failed" and str(item.get("fail_reason") or "").startswith("thin"):
        return False
    return None


def history(store: g.Store) -> dict[tuple[str, str], tuple[int, int]]:
    """{(source kind, format): (passed, total)} over every planned item the editor judged."""
    out: dict[tuple[str, str], list[int]] = collections.defaultdict(lambda: [0, 0])
    for it in store.items().values():
        r = outcome(it)
        if r is None:
            continue
        row = out[(source_kind(it), it.get("format", ""))]
        row[0] += 1 if r else 0
        row[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def prior(item: dict) -> float:
    cls = story_class(item)
    if cls == "story":
        return PRIOR["story"]
    if cls == "lesson-partial":
        return PRIOR["lesson_partial"]
    if cls in ("lesson", "spec-product"):
        return PRIOR["lesson"]
    if cls == "reaction":
        return PRIOR["reaction"]
    if cls == "worklog":
        return PRIOR["worklog"]
    if cls == "product-spotlight":
        return PRIOR["spotlight"]
    return PRIOR["other"]


def quality(item: dict, hist: dict[tuple[str, str], tuple[int, int]]) -> float:
    """0 to 1. The prior by class, pulled toward the pass rate of this source and format as drafts pile up: with no
    history it is the prior; after 9 judged drafts the history carries 75%."""
    base = prior(item)
    passed, total = hist.get((source_kind(item), item.get("format", "")), (0, 0))
    if not total:
        return base
    w = PRIOR_N / (PRIOR_N + total)
    return w * base + (1 - w) * (passed / total)


def usable(store: g.Store, cfg: dict) -> list[dict]:
    """The masters the planner may still give a slot: not thin."""
    items = store.items()
    return [m for m in g.available_masters(store, cfg) if not thin_reason(m, items.get(m.get("parent") or ""))]


def unused_stories(store: g.Store, cfg: dict) -> int:
    return sum(1 for m in usable(store, cfg) if story_class(m) == "story")


def mark_thin(store: g.Store, item: dict, why: str, now: float) -> None:
    """The editor or the thin check called an idea's facts thin: its master is not planned again until the facts change."""
    why = g.clip_text(why, 200) or True
    item["thin_facts"] = why
    master = store.items().get(item.get("parent") or "")
    if master and master["platform"] == g.MASTER and not master.get("thin_facts"):
        master["thin_facts"] = why
        store.save(master, now)
