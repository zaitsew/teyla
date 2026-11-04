"""The Playbook section of `teyla console` (docs/CONSOLE.md): what we have learned and standardized.

    guidelines   the standards in use (design, writing, voice, copy, the owner's policy), where they live, when they changed
    models       the ladder, its drift, models the catalogue shows that nobody looked at, and the arena shortlist
    knowledge    wiki status, intent entries, corrections, design decisions
    you          quotes, insights, a postcard and the chores to hand off (`you.py`); local, off the relay by default

Every part is built on its own: a part that fails shows `{"error": ...}` and the others still load. Nothing here
calls the network; the arena board is read from the snapshot `teyla models arena` keeps. The headline counts
unresolved contradictions, the number `you.py` computes.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import subprocess
import time

from . import config

LADDER_TIERS = ("orchestrate", "volume", "triage")
ARENA_ROWS = 8
NEW_MODELS_SHOWN = 10
SUMMARY_MAX = 140

# (id, title, path relative to the Teyla repo, summary). A summary is written by hand: a file's first line is
# often a heading or front matter, and this line is what the app shows beside the title.
STANDARDS = (
    ("ux", "UX and UI standard", "templates/design/STANDARD.md",
     "One standard for every screen: do one thing, show it first, say it in few words. Audited by `teyla ux check`."),
    ("writing", "Writing and reporting", "docs/WRITING.md",
     "Three registers: agent replies, product copy, marketing. Answer first, short sentences, a ban list."),
    ("voice", "Voice chart", "templates/voice/VOICE.md",
     "Per-language voice limits for marketing text: sentence length, post length, tone."),
    ("copy", "UI copy", "docs/COPY.md",
     "Strings come from a brief, written per language by a writer, never translated from one another."),
)
POLICY_SUMMARY = "The owner's rules for every harness: model ladder, reviews, merging, releases, money."


def _repo_root() -> pathlib.Path | None:
    """The Teyla checkout holding the standards: the one this module runs from, else `<code_root>/teyla`."""
    here = pathlib.Path(__file__).resolve().parents[2]
    for cand in (here, config.code_root() / "teyla"):
        if (cand / "templates" / "design" / "STANDARD.md").is_file():
            return cand
    return None


def _updated(path: pathlib.Path) -> str | None:
    """The date of the last commit that touched the file; the modification date when git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(path.parent), "log", "-1", "--format=%cs", "--", path.name],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return _dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _design_docs() -> list[pathlib.Path]:
    from . import design_md
    root = config.code_root()
    out = []
    try:
        for repo in sorted(root.iterdir()):
            if (repo / ".git").exists():
                p = design_md.find(repo)
                if p:
                    out.append(p)
    except OSError:
        pass
    return out


def _guidelines(now: float) -> list[dict]:
    from . import policy
    root = _repo_root()
    rows = []
    for gid, title, rel, summary in STANDARDS:
        p = root / rel if root else None
        rows.append(dict(id=gid, title=title, path=str(p) if p and p.is_file() else None, updated=_updated(p) if p and p.is_file() else None,
                         summary=summary, exists=bool(p and p.is_file())))
    pol = policy.POLICY
    rows.append(dict(id="policy", title="The owner's policy", path=str(pol) if pol.is_file() else None,
                     updated=_updated(pol) if pol.is_file() else None, summary=POLICY_SUMMARY, exists=pol.is_file()))
    docs = _design_docs()
    rows.append(dict(id="design-md", title="Product DESIGN.md files", path=str(config.code_root()),
                     updated=max((_updated(d) or "" for d in docs), default="") or None,
                     summary=f"{len(docs)} products carry their own design system (tokens, glossary, voice).",
                     exists=bool(docs), count=len(docs)))
    return rows


# --- models ----------------------------------------------------------------------------------

def _new_models() -> tuple[list[dict], str]:
    """Catalogue models nobody has acknowledged yet, from the local caches only. Never refreshes."""
    from . import models, models_watch
    state = models_watch.load_known()
    if state is None:
        return [], "no baseline yet: run `teyla models watch` once"
    md, _ = models.load_models_dev_catalogue(refresh=False)
    ladder_rows = models.parse_ladder(models_watch._policy_text())
    new = models_watch.new_models(md, models_watch.ladder_providers(ladder_rows, md), state["known"], [])
    return [dict(provider=n["provider"], id=n["id"], name=n["name"], date=n["date"], price=n["price"],
                 replaces=(n["replaces"] or {}).get("entry")) for n in new[:NEW_MODELS_SHOWN]], ""


def _models(now: float) -> dict:
    from . import models, models_arena
    snap = models.snapshot(claude_used_models=[])       # no session scan: the ladder and the catalogue are enough here
    flags = models.drift(snap)
    ladder = [dict(provider=p, label=models.PROVIDER_LABEL.get(p, p), note=rows.get("note", ""),
                   **{t: list(rows.get(t) or []) for t in LADDER_TIERS}) for p, rows in snap["ladder"].items()]
    new, new_note = _new_models()
    board = models_arena.load()
    top = models_arena.shortlist(board, snap["ladder"], ARENA_ROWS)
    arena = dict(as_of=board["as_of"], url=models_arena.URL, stale=board["stale"], top=top, note=board["note"],
                 last_fetch=board["last_fetch"], status=models_arena.NOT_A_DECISION)
    return dict(ladder=ladder, drift=[{k: f.get(k) for k in ("flag", "provider", "entry", "detail")} for f in flags],
                new=new, new_note=new_note, arena=arena,
                policy="Per route, keep the current model until a comparison shows a gain; a paid comparison needs a yes first.")


# --- knowledge -------------------------------------------------------------------------------

def _wiki() -> dict:
    from . import wiki
    path = config.ops_root() / "wiki"
    if not path.is_dir():
        return dict(path=None, pages=None, note="no wiki at <ops_root>/wiki")
    rep = wiki.status(str(path))
    return {k: rep[k] for k in ("path", "pages", "drafts", "confirmed", "stale", "inbox")}


def _intent(now: float) -> dict:
    from . import intent
    rows = sorted(intent.products(), key=lambda r: -r["entries"])
    cutoff = _dt.date.fromtimestamp(now - 30 * 86400).isoformat()
    return dict(entries=sum(r["entries"] for r in rows), products=len(rows),
                recent=sum(1 for r in rows if (r["latest"] or "") >= cutoff),
                by_product=[dict(product=r["product"], entries=r["entries"], latest=r["latest"]) for r in rows[:8]])


def _corrections(now: float) -> dict:
    from . import corrections
    recs = corrections.all_records()
    cutoff = _dt.datetime.fromtimestamp(now - 30 * 86400, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    by: dict[str, int] = {}
    for repo, _rec in recs:
        by[repo] = by.get(repo, 0) + 1
    return dict(total=len(recs), last30=sum(1 for _r, rec in recs if str(rec.get("ts") or "")[:19] >= cutoff),
                repos=len(by))


def _taste() -> dict:
    from . import taste
    counts = dict.fromkeys(taste.DECISIONS, 0)
    repos = 0
    try:
        for repo in sorted(config.code_root().iterdir()):
            rows = taste.load_decisions(repo) if (repo / "design" / "decisions").is_dir() else []
            if rows:
                repos += 1
            for r in rows:
                counts[r["decision"]] += 1
    except OSError:
        pass
    return dict(total=sum(counts.values()), repos=repos, **counts)


def _knowledge(now: float) -> dict:
    out = {}
    for name, fn in (("wiki", lambda: _wiki()), ("intent", lambda: _intent(now)),
                     ("corrections", lambda: _corrections(now)), ("taste", lambda: _taste())):
        try:
            out[name] = fn()
        except Exception as e:  # a missing store is a part with an error, never a crash
            out[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    return out


# --- you -------------------------------------------------------------------------------------

def _you(now: float) -> dict:
    try:
        from . import you
    except ImportError:
        return dict(available=False, reason="teyla you is not installed in this build")
    return you.console_part(now)


# --- the section -----------------------------------------------------------------------------

def _headline(parts: dict) -> dict:
    you = parts.get("you") or {}
    c = you.get("contradictions") if isinstance(you, dict) else None
    if not isinstance(c, dict) or c.get("count") is None:
        return dict(label="Unresolved contradictions", value=None,
                    detail="needs `teyla you`: it counts repeats of a theme after a rule was written")
    return dict(label="Unresolved contradictions", value=c["count"], detail=c.get("detail", ""))


def section(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    parts = {}
    for name, fn in (("guidelines", _guidelines), ("models", _models), ("knowledge", _knowledge), ("you", _you)):
        try:
            parts[name] = fn(now)
        except Exception as e:
            parts[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    return dict(headline=_headline(parts), **parts)


def compact(sec: dict) -> dict:
    """What the phone gets through the relay: the headline and counts. The `you` part (quotes, insights,
    chores) stays off unless `[you] relay = true`, and then carries the quote of the day and the open chores only."""
    out: dict = {"headline": sec.get("headline")}
    if sec.get("error"):
        return {"error": sec["error"]}
    m = sec.get("models") or {}
    if isinstance(m, dict) and "error" not in m:
        arena = m.get("arena") or {}
        out["models"] = dict(drift=len(m.get("drift") or []), new=len(m.get("new") or []), arena_as_of=arena.get("as_of"))
    k = sec.get("knowledge") or {}
    out["knowledge"] = {n: {kk: vv for kk, vv in v.items() if isinstance(vv, int)} for n, v in k.items()
                        if isinstance(v, dict) and "error" not in v}
    if config.truthy(((config.load().get("you")) or {}).get("relay")):
        y = sec.get("you") or {}
        out["you"] = dict(quote=y.get("quote_of_the_day"),
                          chores_open=sum(1 for r in y.get("delegation") or [] if r.get("status") == "open"))
    return out
