"""`teyla state` — one snapshot for the Teyla for Mac coordinator window (`docs/APP.md`).

    teyla state [--json]

Open questions ranked by what they unblock, where each product stands, which sessions are running
now, and today's spend. The snapshot itself makes no model call: ranking and the brief line are
rules, replaced by a model-written version when one is cached (below). The snapshot is private
(it holds session text), like `teyla asks`.

Ranking: score = kind weight (blocked or gate 3, question 2, reminder 0) + 3 when the text
mentions a release (App Review, TestFlight, release, store, build, deploy, merge) + 1 when the
item is younger than 24 hours. Ties go to the newer item. Reminders show only once due.

Cost: the desktop app's metadata parse is cached by `asks`; today's spend takes seconds, so it
is read from `~/.teyla/state-spend.json` and refreshed by a detached `teyla state --refresh-spend`
when older than 10 minutes (null until the first refresh lands).

Model brief: a detached `teyla state --refresh-brief` sends the open questions (at most 15) to
Claude Haiku in one `claude -p` call and caches the sentence and the ranking in
`~/.teyla/state-brief.json`. The snapshot uses the cache while its `ask_ids_hash` equals the
current set of open questions (`brief.source` is then "model"); otherwise it returns the rules and
starts one refresh. Off with `[state] model_brief = false`, in safe mode, or without `claude`.

Version 2 adds three things (`docs/APP.md`, "Version 2"). `done` lists the sessions that ended a turn in
the last 24 hours with a status, result lines and what they need. `tasks` lists what only the owner can
do: open PRs in repos that are not merge-approved, and issues assigned to the owner. Both come from
GitHub through `backlog.py`, which the snapshot reads from a cache and never calls live. `products` also
carry open issues, PRs that wait on a merge, the next step and the repo path, and two clones of one
GitHub repo share one row.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from . import asks, backlog, config, net, reviews
from .adapters import claude_code, codex, iter_jsonl, text_of
from .control import state as control

VERSION = 2
RUNNING_WINDOW_S = 600
QUIET_DAYS = 3
REPO_RECENT_DAYS = 30            # a repo with no session activity is listed only when it moved this recently
FRESH_S = 24 * 3600
SPEND_FRESH_S = 600
BRIEF_WORDS = 25
UNBLOCKS_WORDS = 5
BRIEF_MAX_ASKS = 15
BRIEF_FIELD_CHARS = 400
BRIEF_FRESH_S = 1800
BRIEF_LOCK_STALE_S = 300
BRIEF_TIMEOUT_S = 120
# A short summary and ranking over a few hundred words: Haiku-class work.
BRIEF_MODEL = "claude-haiku-5-5"
REVIEW_TITLE = "You are reviewing"      # a review lane's prompt: its desktop session is not one you work in
DONE_WINDOW_S = 24 * 3600        # a session that ended a turn this recently is in `done`
DONE_MAX = 40
RESULT_LINES = 3
RESULT_LINE_CHARS = 160
FIRST_LINE_CHARS = 120
NEEDS_CHARS = 200
DISPATCH_MAX_LINES = 500         # the newest lines of ~/.teyla/dispatch.jsonl that are read
KIND_WEIGHT = {"blocked": 3, "gate": 3, "question": 2, "reminder": 0}

_RELEASE_SIGNAL = re.compile(r"\b(app review|testflight|release|store|build|deploy|merge)", re.I)
_RELEASE_PHRASE = re.compile(r"\b(app review|testflight|release|app store|deploy)", re.I)
_SIGN_IN_PHRASE = re.compile(r"\b(sign[ -]?in|log[ -]?in|credential)", re.I)
_MERGE_PHRASE = re.compile(r"\b(merge|pr|pull request)\b", re.I)


# --- ranking ----------------------------------------------------------------------------------

def _text(a: asks.Ask) -> str:
    return f"{a.title}\n{a.question}\n{a.context}"


def unblocks(a: asks.Ask) -> str:
    t = _text(a)
    if _RELEASE_PHRASE.search(t):
        return "a release"
    if _SIGN_IN_PHRASE.search(t):
        return "a sign-in only you can do"
    if _MERGE_PHRASE.search(t):
        return "a merge"
    return ""


def score(a: asks.Ask, now: float) -> int:
    s = KIND_WEIGHT.get(a.kind, 2)
    if _RELEASE_SIGNAL.search(_text(a)):
        s += 3
    if now - a.when < FRESH_S:
        s += 1
    return s


def delivery(a: asks.Ask) -> str:
    """What `teyla answer` tries first for this item."""
    if a.harness == "codex" and a.session:
        return "codex"
    if a.harness in ("claude-desktop", "claude-code") and a.session:
        return "claude"
    return "open"


def _due(a: asks.Ask, today: _dt.date) -> bool:
    from . import remind
    try:
        return remind.days_until(a.due, today) <= 0
    except ValueError:
        return False


def ranked(items: list[asks.Ask], now: float) -> list[dict]:
    today = _dt.datetime.fromtimestamp(now).date()
    open_ = [a for a in items if a.status == "open" and (a.kind != "reminder" or _due(a, today))]
    open_.sort(key=lambda a: (-score(a, now), -a.when))
    out = []
    for i, a in enumerate(open_, 1):
        d = a.to_dict(now)
        d.update(unblocks=unblocks(a), rank=i, delivery=delivery(a))
        out.append(d)
    return out


# --- dispatched work --------------------------------------------------------------------------

def dispatch_path() -> pathlib.Path:
    return control.home() / "dispatch.jsonl"


def dispatched() -> list[dict]:
    """The runs `teyla dispatch` started, from the newest lines of ~/.teyla/dispatch.jsonl, each with its
    worktree resolved. Their sessions are headless, but the owner asked for them, so they are listed."""
    try:
        lines = dispatch_path().read_text(errors="replace").splitlines()[-DISPATCH_MAX_LINES:]
    except OSError:
        return []
    home = os.path.realpath(os.path.expanduser("~"))
    out = []
    for ln in lines:
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        w = o.get("worktree") if isinstance(o, dict) else None
        if not isinstance(w, str) or not w.strip():
            continue
        real = os.path.realpath(os.path.expanduser(w)).rstrip(os.sep)
        if real and real != home:              # "/" or the home folder would claim every session
            out.append({**o, "worktree": real})
    return out


def in_dispatch(cwd, runs: list[dict]) -> bool:
    """True when `cwd` is a dispatched worktree or inside one."""
    if not cwd or not runs:
        return False
    c = os.path.realpath(str(cwd)).rstrip(os.sep)
    return any(c == r["worktree"] or c.startswith(r["worktree"] + os.sep) for r in runs)


# --- sessions ---------------------------------------------------------------------------------

def _iso(epoch: float) -> str:
    return asks._iso(epoch)


def desktop_sessions(root: str | None = None) -> list[dict]:
    root = asks.desktop_root() if root is None else root
    return asks._desktop_sessions(root) if os.path.isdir(root) else []


def _desktop_skipped(d: dict, runs: list[dict]) -> bool:
    """Archived sessions, and review lanes (their prompt starts "You are reviewing") unless `teyla dispatch` started them."""
    if d.get("isArchived"):
        return True
    return (str(d.get("title") or "").startswith(REVIEW_TITLE)
            and not in_dispatch(d.get("cwd") or d.get("originCwd"), runs))


def running_desktop(now: float, root: str | None = None, runs: list[dict] | None = None,
                    sessions: list[dict] | None = None) -> list[dict]:
    runs = dispatched() if runs is None else runs
    out = []
    for d in desktop_sessions(root) if sessions is None else sessions:
        if _desktop_skipped(d, runs):
            continue
        last = asks._epoch(d.get("lastActivityAt"))
        if last is None or now - last > RUNNING_WINDOW_S:
            continue
        sid = str(d.get("sessionId") or "")
        out.append({"product": asks.product_of(d.get("cwd") or d.get("originCwd")),
                    "title": asks.clip(d.get("title") or "(untitled)", asks.TITLE_MAX),
                    "harness": "claude-desktop", "model": str(d.get("model") or ""),
                    "since": _iso(asks._epoch(d.get("createdAt")) or last),
                    "link": asks.OPEN_LINK + sid if sid.startswith("local_") else "",
                    "id": sid, "correct": "open", "_last": last})
    return out


def _codex_head(path: str) -> tuple[dict, str]:
    """session_meta payload and the first model named, from the first few records."""
    meta, model = {}, ""
    for n, o in enumerate(iter_jsonl(path)):
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        if o.get("type") == "session_meta":
            meta = p
        elif o.get("type") == "turn_context" and p.get("model"):
            model = str(p["model"])
        if (meta and model) or n > 30:
            break
    return meta, model


def recent_rollouts(root: str, since: float) -> list[tuple[str, float]]:
    """(path, mtime) of the rollouts written since `since`. By file time, not by the date directory: a
    session resumed after days keeps its old directory, and a walk pruned by directory date missed it."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not (name.startswith("rollout-") and name.endswith(".jsonl")):
                continue
            f = os.path.join(dirpath, name)
            try:
                m = os.stat(f).st_mtime
            except OSError:
                continue
            if m >= since:
                out.append((f, m))
    return out


def codex_sessions(now: float, root: str | None = None, runs: list[dict] | None = None) -> list[dict]:
    """Codex sessions written in the last 24 hours that the owner works in, plus dispatched headless runs.
    Spawned agents and other `codex exec` runs (reviews, lanes) are left out."""
    root = codex.DEFAULT_ROOT if root is None else root
    if not root or not os.path.isdir(root):
        return []
    runs = dispatched() if runs is None else runs
    titles = None
    out = []
    for f, last in recent_rollouts(root, now - DONE_WINDOW_S):
        meta, model = _codex_head(f)
        if isinstance(meta.get("source"), dict) and "subagent" in meta["source"]:
            continue
        sid = str(meta.get("session_id") or meta.get("id") or "")
        if not sid:
            continue
        headless = meta.get("source") == "exec" or meta.get("originator") == "codex_exec"
        if headless and not in_dispatch(meta.get("cwd"), runs):
            continue                       # headless `codex exec`: reviews and lanes, not a session you can answer
        if titles is None:
            titles = codex._load_titles(codex.DEFAULT_INDEX)
        out.append({"sid": sid, "path": f, "cwd": meta.get("cwd"), "model": model, "headless": headless,
                    "title": titles.get(sid) or "", "created": asks._epoch(meta.get("timestamp")) or last,
                    "_last": last})
    return out


def running_codex(now: float, root: str | None = None, runs: list[dict] | None = None,
                  sessions: list[dict] | None = None) -> list[dict]:
    out = []
    for s in codex_sessions(now, root, runs) if sessions is None else sessions:
        if now - s["_last"] > RUNNING_WINDOW_S:
            continue
        out.append({"product": asks.product_of(s["cwd"]), "title": asks.clip(s["title"] or "Codex session", asks.TITLE_MAX),
                    "harness": "codex", "model": s["model"], "since": _iso(s["created"]),
                    "link": f"codex://threads/{s['sid']}", "id": s["sid"],
                    # `codex queue` reaches a live interactive session; a headless run has nobody to queue for
                    "correct": "open" if s["headless"] else "codex-queue", "_last": s["_last"]})
    return out


def claude_dispatch_sessions(now: float, projects: str | None, runs: list[dict]) -> list[dict]:
    """Transcripts of Claude runs `teyla dispatch` started in the last 24 hours. They have no record in the
    desktop app, so they are found by the transcript folder of their worktree."""
    projects = claude_code.DEFAULT_ROOT if projects is None else projects
    if not runs or not os.path.isdir(projects):
        return []
    out, seen = [], set()
    for r in runs:
        if str(r.get("harness") or "") != "claude" or r["worktree"] in seen:
            continue
        seen.add(r["worktree"])
        for f in glob.glob(os.path.join(projects, re.sub(r"[/.]", "-", r["worktree"]), "*.jsonl")):
            try:
                last = os.stat(f).st_mtime
            except OSError:
                continue
            if now - last > DONE_WINDOW_S:
                continue
            title, model, created = "", "", None
            for n, o in enumerate(iter_jsonl(f)):
                msg = o.get("message") if isinstance(o.get("message"), dict) else {}
                if o.get("type") == "user" and not title and not o.get("isMeta"):
                    t = text_of(msg.get("content")).strip()
                    if t and not t.startswith("<"):
                        title, created = _first_line(t, asks.TITLE_MAX), asks._epoch(o.get("timestamp"))
                elif o.get("type") == "assistant" and msg.get("model"):
                    model = str(msg["model"])
                if (title and model) or n > 40:
                    break
            out.append({"id": os.path.basename(f)[:-len(".jsonl")], "path": f, "cwd": r["worktree"],
                        "title": title, "model": model, "created": created or last, "_last": last})
    return out


def running_claude_dispatch(now: float, sessions: list[dict]) -> list[dict]:
    return [{"product": asks.product_of(s["cwd"]), "title": s["title"] or "Claude session", "harness": "claude-code",
             "model": s["model"], "since": _iso(s["created"]), "link": f"claude --resume {s['id']}",
             "id": s["id"], "correct": "open", "_last": s["_last"]}
            for s in sessions if now - s["_last"] <= RUNNING_WINDOW_S]


def running(now: float, desktop: str | None = None, codex_root: str | None = None, *,
            runs: list[dict] | None = None, dk: list[dict] | None = None, cx: list[dict] | None = None,
            cc: list[dict] | None = None, projects: str | None = None) -> list[dict]:
    runs = dispatched() if runs is None else runs
    cc = claude_dispatch_sessions(now, projects, runs) if cc is None else cc
    rows = (running_desktop(now, desktop, runs, dk) + running_codex(now, codex_root, runs, cx)
            + running_claude_dispatch(now, cc))
    rows.sort(key=lambda r: -r["_last"])
    return rows


# --- what got done ----------------------------------------------------------------------------

SUMMARY_STATUS = {"completed": "done", "review_ready": "review_ready", "failed": "failed", "error": "failed",
                  "blocked": "blocked"}
CARD_STATUS = {"done": "done", "blocked": "blocked", "needs you": "needs_you", "failed": "failed"}
_CARD_HEAD = re.compile(r"^(done|blocked|needs you|failed)(?:\s*[—–]\s*|\s+-\s+)\S", re.I)
_CARD_KEY = re.compile(r"^(result|needs you|not verified)\s*:\s*(.*)$", re.I)
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+(.*)$")
_NO_NEED = re.compile(r"^(none|nothing|n/a|no|-|—)\.?$", re.I)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_GH_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/\d+")


def _plain(line: str) -> str:
    """One line of markdown as plain text: links keep their label, bold marks go."""
    return _MD_LINK.sub(r"\1", line).replace("**", "").replace("__", "").strip()


def _first_line(text: str, limit: int = FIRST_LINE_CHARS) -> str:
    for ln in str(text or "").splitlines():
        t = _plain(ln.lstrip("#> \t")).lstrip("-*• ").strip()
        if t:
            return asks.clip(t, limit)
    return ""


def parse_card(text: str) -> dict | None:
    """The session-end card of POLICY §16 — "<Done|Blocked|Needs you|Failed> — <product>", then "Result:"
    bullets and a "Needs you:" line — as {status, result, needs}; None when the text is not a card.
    Any "Needs you:" line that is not "none" makes the status `needs_you`."""
    raw = str(text or "").splitlines()
    first = next((i for i, ln in enumerate(raw) if ln.strip()), None)
    if first is None:
        return None
    m = _CARD_HEAD.match(_plain(raw[first].lstrip("#> \t")))
    if not m:
        return None
    status = CARD_STATUS[m.group(1).lower()]
    result: list[str] = []
    needs, section = "", None
    for ln in raw[first + 1:]:
        t = _plain(ln.strip())
        if not t:
            if section == "result" and result:
                section = None            # a blank line after the bullets ends them
            continue
        b = _BULLET.match(t)
        body = b.group(1).strip() if b else t
        k = _CARD_KEY.match(body)
        if k:
            name, rest = k.group(1).lower(), k.group(2).strip()
            section = {"result": "result", "needs you": "needs"}.get(name, "skip")
            if rest and section == "result":
                result.append(rest)
            elif rest and section == "needs":
                needs = rest
        elif section == "result":
            result.append(body)
        elif section == "needs" and not needs:
            needs = body
    if _NO_NEED.match(needs):
        needs = ""
    if needs:
        status = "needs_you"
    lines = [asks.clip(x, RESULT_LINE_CHARS) for x in result if x][:RESULT_LINES]
    return {"status": status, "result": lines or [_first_line(raw[first])], "needs": asks.clip(needs, NEEDS_CHARS)}


def card_from_text(text: str) -> dict | None:
    """The card in a session's last message, else its first line as the one result line (status `done`)."""
    card = parse_card(text)
    if card:
        return card
    line = _first_line(text)
    return {"status": "done", "result": [line], "needs": ""} if line else None


def card_from_summary(pts: dict) -> dict:
    """A card from the desktop app's turn summary. Any needs_action makes it `needs_you`; the rest is the status category."""
    needs = str(pts.get("needs_action") or "").strip()
    detail = str(pts.get("status_detail") or "").strip()
    cat = str(pts.get("status_category") or "").strip().lower()
    status = "needs_you" if needs else SUMMARY_STATUS.get(cat, "done")
    parts = [p.strip(" -•\t") for ln in detail.splitlines() for p in ln.split(";")]
    return {"status": status, "result": [asks.clip(p, RESULT_LINE_CHARS) for p in parts if p][:RESULT_LINES],
            "needs": asks.clip(needs, NEEDS_CHARS)}


def links_in(*texts, extra=()) -> list[str]:
    """Up to three GitHub PR or issue URLs, in the order found."""
    seen: list[str] = []
    for t in texts:
        for u in _GH_LINK.findall(str(t or "")):
            if u not in seen:
                seen.append(u)
    for u in extra:
        if isinstance(u, str) and _GH_LINK.fullmatch(u) and u not in seen:
            seen.append(u)
    return seen[:3]


def last_claude_message(path: str) -> tuple[str, float | None]:
    """(text, time) of the last assistant message of a Claude transcript when the turn has ended, else ("", None).
    A turn has ended when the last record is assistant text with no tool call after it."""
    text, ts, ended = "", None, False
    try:
        for o in iter_jsonl(path, tail_bytes=asks.TAIL_BYTES):
            if o.get("isSidechain"):
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            if o.get("type") == "assistant":
                content = msg.get("content")
                blocks = content if isinstance(content, list) else []
                has_tool = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
                t = text_of(content).strip()
                if o.get("isApiErrorMessage"):
                    text, ended = "", False
                    continue
                if t:
                    text, ts = t, asks._epoch(o.get("timestamp"))
                ended = bool(t) and not has_tool
            elif o.get("type") == "user" and not o.get("isMeta"):
                ended = False                  # a prompt or a tool result: the turn goes on
    except OSError:
        return "", None
    return (text, ts) if ended else ("", None)


def last_codex_message(path: str) -> tuple[str, float | None]:
    """(text, time) of the last finished turn of a Codex rollout, else ("", None)."""
    text, ts, ended, assistant = "", None, False, ""
    try:
        for o in iter_jsonl(path, tail_bytes=asks.TAIL_BYTES):
            p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if o.get("type") == "event_msg":
                if p.get("type") == "task_complete":
                    m = p.get("last_agent_message")
                    text = (m if isinstance(m, str) else "").strip() or assistant
                    ts, ended = asks._epoch(o.get("timestamp")), True
                elif p.get("type") == "task_started":
                    ended, assistant = False, ""
            elif (o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "assistant"
                  and p.get("phase") != "commentary"):
                assistant = codex._text_of(p.get("content")).strip() or assistant
    except OSError:
        return "", None
    return (text, ts) if ended else ("", None)


def _done_row(id_, product, title, card, links, ended, harness, link) -> dict:
    return {"id": id_, "product": product, "title": asks.clip(title, asks.TITLE_MAX), "status": card["status"],
            "result": card["result"], "needs": card["needs"], "links": links, "ended": _iso(ended),
            "harness": harness, "link": link}


def _summary_is_stale(pts: dict, tpath: str | None) -> bool:
    """True when the transcript's last assistant turn is not the one the desktop summary describes
    (`summarizes_uuid`), as `asks` decides for questions. No uuid or no transcript: the summary stands."""
    su = str(pts.get("summarizes_uuid") or "")
    if not su or not tpath:
        return False
    ana = asks.scan_claude(tpath)
    return bool(ana and ana["uuid"] and ana["uuid"] != su)


def done_feed(now: float, desktop: str | None = None, codex_root: str | None = None, projects: str | None = None, *,
              runs: list[dict] | None = None, dk: list[dict] | None = None, cx: list[dict] | None = None,
              cc: list[dict] | None = None, skip_ids=()) -> list[dict]:
    """Sessions that ended a turn in the last 24 hours, newest first. A session still in `running` is not
    listed (`skip_ids`). The source is the desktop turn summary, else the card in the last message."""
    runs = dispatched() if runs is None else runs
    projects = claude_code.DEFAULT_ROOT if projects is None else projects
    cut = now - DONE_WINDOW_S
    out: list[dict] = []
    for d in desktop_sessions(desktop) if dk is None else dk:
        if _desktop_skipped(d, runs):
            continue
        last = asks._epoch(d.get("lastActivityAt"))
        sid = str(d.get("sessionId") or "")
        if last is None or last < cut or not sid or sid in skip_ids:
            continue
        pts = d.get("postTurnSummary") if isinstance(d.get("postTurnSummary"), dict) else {}
        text = ""
        cli = str(d.get("cliSessionId") or "")
        has_summary = bool(pts.get("status_category") or pts.get("status_detail") or pts.get("needs_action"))
        tpath = None
        if cli and os.path.isdir(projects) and (not has_summary or pts.get("summarizes_uuid")):
            tpath = asks.find_transcript(cli, d.get("cwd") or "", projects)
        if has_summary and _summary_is_stale(pts, tpath):
            has_summary = False                  # the session went on after the summary: read its last message
        if has_summary:
            card = card_from_summary(pts)
            text = f"{pts.get('status_detail') or ''}\n{pts.get('needs_action') or ''}"
        else:
            text, ts = last_claude_message(tpath) if tpath else ("", None)
            card = card_from_text(text) if text else None
            last = ts or last
        if not card:
            continue
        prs = [p.get("url") for p in d.get("prs") or [] if isinstance(p, dict)]
        out.append(_done_row(sid, asks.product_of(d.get("cwd") or d.get("originCwd")), d.get("title") or "(untitled)",
                             card, links_in(text, extra=prs), last, "claude-desktop", asks.OPEN_LINK + sid
                             if sid.startswith("local_") else ""))
    for s in codex_sessions(now, codex_root, runs) if cx is None else cx:
        if s["sid"] in skip_ids or s["_last"] < cut:
            continue
        text, ts = last_codex_message(s["path"])
        card = card_from_text(text) if text else None
        if not card or (ts or s["_last"]) < cut:
            continue
        out.append(_done_row(s["sid"], asks.product_of(s["cwd"]), s["title"] or card["result"][0] or "Codex session",
                             card, links_in(text), ts or s["_last"], "codex", f"codex://threads/{s['sid']}"))
    for s in claude_dispatch_sessions(now, projects, runs) if cc is None else cc:
        if s["id"] in skip_ids:
            continue
        text, ts = last_claude_message(s["path"])
        card = card_from_text(text) if text else None
        if card:
            out.append(_done_row(s["id"], asks.product_of(s["cwd"]), s["title"] or card["result"][0] or "Claude session",
                                 card, links_in(text), ts or s["_last"], "claude-code", f"claude --resume {s['id']}"))
    out.sort(key=lambda r: r["ended"], reverse=True)
    return out[:DONE_MAX]


# --- products ---------------------------------------------------------------------------------

def repo_index() -> dict:
    """{name: path} for the repos `teyla products` walks. Cheap: no network, no subprocess."""
    try:
        from . import products
        repos, _ = products.repos_to_probe()
        return {p.name: p for p in repos}
    except Exception:  # noqa: BLE001 — a missing config or code root is "no repos", not a failed snapshot
        return {}


def _repo_signals(path: pathlib.Path, today: _dt.date) -> tuple[float | None, bool]:
    """(time of the last commit or checkout, a release tag written today), from file stamps only."""
    last = None
    for rel in (".git/logs/HEAD", ".git"):
        try:
            last = (path / rel).stat().st_mtime
            break
        except OSError:
            continue
    tagged = False
    try:
        with os.scandir(path / ".git" / "refs" / "tags") as it:
            tagged = any(_dt.datetime.fromtimestamp(e.stat().st_mtime).date() == today for e in it)
    except OSError:
        pass
    return last, tagged


def products_view(items: list[dict], run: list[dict], repos: dict, now: float, keep=()) -> list[dict]:
    """One row per product. A repo is listed when it moved in the last 30 days, or has a name in `keep`
    (a product with a task waiting on the owner)."""
    today = _dt.datetime.fromtimestamp(now).date()
    by: dict[str, dict] = {}

    def slot(name):
        return by.setdefault(name, {"waiting": 0, "last": 0.0, "title": "", "title_ts": 0.0, "run": "", "tag": False})
    for a in items:
        s = slot(a["product"])
        s["waiting"] += 1
        ts = asks._epoch(a["ts"]) or 0.0
        s["last"] = max(s["last"], ts)
        if ts >= s["title_ts"]:
            s["title"], s["title_ts"] = a["title"], ts
    for r in run:
        s = slot(r["product"])
        s["last"] = max(s["last"], r["_last"])
        s["run"] = s["run"] or r["title"]
    for name, path in repos.items():
        sig = [_repo_signals(p, today) for p in (path if isinstance(path, (list, tuple)) else [path])]
        last = max((t for t, _ in sig if t is not None), default=None)    # the newest of the clones
        tagged = any(g for _, g in sig)
        if name not in by and name not in keep and (last is None or now - last > REPO_RECENT_DAYS * 86400):
            continue
        s = slot(name)
        s["last"] = max(s["last"], last or 0.0)
        s["tag"] = tagged
    out = []
    for name, s in by.items():
        if not s["waiting"] and (name.startswith("(") or name in ("unknown", "reminders")):
            continue
        idle_days = int((now - s["last"]) // 86400) if s["last"] else None
        if s["waiting"]:
            st = "waiting"
        elif s["run"]:
            st = "active"
        elif s["last"] and idle_days is not None and idle_days >= QUIET_DAYS:
            st = "quiet"
        elif s["tag"]:
            st = "shipped"
        else:
            st = "active"
        if s["title"]:
            line = s["title"]
        elif s["run"]:
            line = s["run"]
        elif st == "shipped":
            line = "release tagged today"
        elif idle_days is None:
            line = "no activity recorded"
        elif idle_days >= 1:
            line = f"no activity for {idle_days} days" if idle_days != 1 else "no activity for 1 day"
        else:
            line = "active today"
        out.append({"name": name, "waiting": s["waiting"], "state": st, "line": line,
                    "last_activity": _iso(s["last"]) if s["last"] else ""})
    out.sort(key=lambda p: (-p["waiting"], p["state"] == "quiet", -(asks._epoch(p["last_activity"]) or 0), p["name"]))
    return out


def product_names(repos: dict, canonical: dict) -> tuple[dict, dict]:
    """(alias, info). `alias` maps a repo folder name to its product name, `info` maps a product name to
    {path, paths, slug}. The product name is the GitHub repo name: GitHub answers an old name with the
    current one (`canonical`, from the backlog cache), so two clones of one repo share a row, and `paths`
    lists every clone. Two owners with one repo name (`alice/app`, `bob/app`) are two products, named
    `owner/name`. A folder with no GitHub remote keeps its own name."""
    fulls: dict[str, str] = {}
    owners: dict[str, set] = {}
    for name, path in sorted(repos.items()):
        slug = backlog.remote_slug(path)
        full = canonical.get(slug.lower(), slug) if slug else ""
        fulls[name] = full
        if full:
            owners.setdefault(full.split("/", 1)[1].lower(), set()).add(full.split("/", 1)[0].lower())
    alias, info, spelled = {}, {}, {}
    for name, path in sorted(repos.items()):
        full = fulls[name]
        if not full:
            key = name
        else:
            repo = full.split("/", 1)[1]
            key = spelled.setdefault(full.lower(), full) if len(owners[repo.lower()]) > 1 else repo
        alias[name] = key
        have = info.get(key)
        if have is None:
            info[key] = {"path": path, "paths": [path], "slug": full, "name": name}
            continue
        have["paths"].append(path)
        if name == key and have["name"] != key:
            have.update(path=path, name=name)
    return alias, info


def home_path(path) -> str:
    """A path with the home folder written as ~."""
    s = str(path)
    home = str(pathlib.Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def enrich_products(prods: list[dict], info: dict, counts: dict, tasks: list[dict], done: list[dict]) -> list[dict]:
    """Adds issues, prs_waiting, next and repo to each product row."""
    waiting: dict[str, int] = {}
    for t in tasks:
        if t["kind"] == "merge":
            waiting[t["product"]] = waiting.get(t["product"], 0) + 1
    newest: dict[str, dict] = {}
    for d in done:                              # newest first
        newest.setdefault(d["product"], d)
    for p in prods:
        i = info.get(p["name"]) or {}
        p["issues"] = int(counts.get((i.get("slug") or "").lower(), 0))
        p["prs_waiting"] = waiting.get(p["name"], 0)
        p["next"] = (newest.get(p["name"]) or {}).get("needs", "")
        p["repo"] = home_path(i["path"]) if i.get("path") else ""
    return prods


# --- spend ------------------------------------------------------------------------------------

def _spend_cache() -> pathlib.Path:
    return control.home() / "state-spend.json"


def _local_day(now: float) -> str:
    return _dt.datetime.fromtimestamp(now).date().isoformat()


def compute_spend(now: float) -> float:
    from . import spend
    day = _local_day(now)
    return round(sum((r.get("day_usd") or {}).get(day, 0.0) for r in spend.session_rows(days=1)), 2)


def refresh_spend(now: float | None = None) -> None:
    now = asks._now() if now is None else now
    usd = compute_spend(now)
    asks._atomic_write(_spend_cache(), json.dumps({"day": _local_day(now), "usd": usd, "at": now}))


def _spawn_refresh() -> None:
    lock = control.home() / "state-spend.lock"
    try:
        if lock.exists() and asks._now() - lock.stat().st_mtime < 120:
            return
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        subprocess.Popen([sys.executable, "-m", "teyla", "state", "--refresh-spend"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        pass


def spent_today(now: float) -> float | None:
    """Today's spend from the cache; a stale or missing cache starts a background refresh."""
    try:
        c = json.loads(_spend_cache().read_text())
        usd = float(c["usd"]) if c.get("day") == _local_day(now) else None
        fresh = usd is not None and now - float(c.get("at", 0)) < SPEND_FRESH_S
    except (OSError, ValueError, KeyError, TypeError):
        usd, fresh = None, False
    if not fresh:
        _spawn_refresh()
    return usd


# --- the brief --------------------------------------------------------------------------------

def _words(text: str) -> str:
    w = text.split()
    return text if len(w) <= BRIEF_WORDS else " ".join(w[:BRIEF_WORDS - 1]) + "…"


def brief_line(st: dict) -> dict:
    """The rule-based sentence on top: the fallback when no model brief is cached for the open questions."""
    items = st["asks"]
    if not items:
        return {"line": "Nothing waits on you.", "source": "rules"}
    top = items[:5]
    rel = [a for a in top if a["unblocks"] == "a release"]
    if rel:
        counts: dict[str, int] = {}
        for a in rel:
            counts[a["product"]] = counts.get(a["product"], 0) + 1
        product = max(counts, key=lambda p: (counts[p], -min(a["rank"] for a in rel if a["product"] == p)))
        n = counts[product]
        line = (f"{n} answer{'s' if n != 1 else ''} unblock{'' if n != 1 else 's'} {product}'s release today.")
        rest = [a for a in top if a["product"] != product]
        if rest:
            line += f" {rest[0]['product'].capitalize()} is waiting on you too."
    else:
        n = len(items)
        first = items[0]
        line = (f"{n} question{'s' if n != 1 else ''} wait{'' if n != 1 else 's'} for you, "
                f"the first one in {first['product']}.")
    return {"line": _words(line), "source": "rules"}


# --- the model brief --------------------------------------------------------------------------

BRIEF_SYSTEM = (
    "You write the morning brief for one person who runs several software products. You get their open "
    "questions as JSON and reply with strict JSON only, no prose and no code fence:\n"
    '{"brief": "<one sentence, at most 25 words, plain English, what matters today and why>", '
    '"items": [{"id": "...", "rank": 1, "unblocks": "<at most 5 words, what an answer unblocks, or empty>"}]}\n'
    "Keep the brief short, about 18 words; count them, and never go over 25. Rules: rank by what an answer unblocks for a person or a release, then by age (older first). Every id "
    "appears once with a unique rank, 1 = first. Never invent facts that are not in the input. Leave "
    "unblocks empty when it is unclear. A question about a small tool or a read-only command does not "
    "unblock a release. Do not mention ids in the brief."
)


def _brief_cache() -> pathlib.Path:
    return control.home() / "state-brief.json"


def _brief_lock() -> pathlib.Path:
    return control.home() / "state-brief.lock"


def ask_ids_hash(rows: list[dict]) -> str:
    return hashlib.sha256("\n".join(sorted(r["id"] for r in rows)).encode()).hexdigest()[:16]


def model_brief_enabled() -> bool:
    """On unless `[state] model_brief` is false, safe mode is on (session text must stay local), or
    there is no `claude` on PATH."""
    try:
        cfg = config.load()
        v = (cfg.get("state") or {}).get("model_brief", True)
        if v is False or str(v).strip().lower() in config.FALSE_WORDS or config.safe_mode(cfg):
            return False
    except Exception:  # noqa: BLE001 — an unreadable config is "rules only", not a failed snapshot
        return False
    return shutil.which("claude") is not None


def brief_candidates(rows: list[dict]) -> list[dict]:
    """The questions the model sees: blocked and gate items first, then the newest, at most 15."""
    pick = sorted(rows, key=lambda r: (r["kind"] not in ("blocked", "gate"), r["age_s"]))[:BRIEF_MAX_ASKS]
    return [{"id": r["id"], "product": r["product"], "kind": r["kind"], "age_hours": round(r["age_s"] / 3600, 1),
             "question": asks.clip(r["question"], BRIEF_FIELD_CHARS), "context": asks.clip(r["context"], BRIEF_FIELD_CHARS)}
            for r in pick]


def brief_command() -> list[str]:
    """`claude -p` with no tools, no skills, no MCP servers, no settings files and no saved session;
    the prompt goes in on stdin so session text never shows in `ps`."""
    return ["claude", "-p", "--model", BRIEF_MODEL, "--output-format", "json", "--tools", "",
            "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config",
            "--setting-sources", "", "--system-prompt", BRIEF_SYSTEM]


def _run_claude(cmd: list[str], input_text: str, timeout: int = BRIEF_TIMEOUT_S) -> tuple[int, str]:
    """(exit code, stdout). Tests replace this one function; none starts a real claude."""
    home = control.home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        # run from inside a Claude Code session (a hook, the coordinator), claude refuses a nested
        # session unless the markers of the outer one are dropped
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        r = subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout,
                           cwd=str(home), env=env)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, r.stdout


def _cut(text: str, n: int) -> str:
    w = text.split()
    return " ".join(w) if len(w) <= n else " ".join(w[:n - 1]) + "…"


def _cut_brief(text: str) -> str:
    """At most 25 words. A longer text is cut at the last clause break (; , :) that leaves at least
    eight words, else at the word limit, so the line does not end mid-phrase."""
    w = text.split()
    if len(w) <= BRIEF_WORDS:
        return " ".join(w)
    head = " ".join(w[:BRIEF_WORDS])
    cut = max(head.rfind(c) for c in ";,:")
    if cut > 0 and len(head[:cut].split()) >= 8:
        return head[:cut].rstrip() + "."
    return " ".join(w[:BRIEF_WORDS - 1]) + "…"


def validate_brief(reply, ids: set[str]) -> dict | None:
    """{brief, items} from the model's reply, or None when it cannot be trusted. A long brief or
    unblocks text is cut; an unknown or repeated id, a repeated or non-integer rank, or no brief
    at all rejects the whole reply."""
    if not isinstance(reply, dict) or not isinstance(reply.get("brief"), str) or not reply["brief"].strip():
        return None
    raw = reply.get("items")
    if not isinstance(raw, list) or not raw:
        return None
    seen, ranks, items = set(), set(), []
    for it in raw:
        if not isinstance(it, dict):
            return None
        i, rank = it.get("id"), it.get("rank")
        if i not in ids or i in seen or isinstance(rank, bool) or not isinstance(rank, int) or rank in ranks:
            return None
        seen.add(i)
        ranks.add(rank)
        u = it.get("unblocks")
        items.append({"id": i, "rank": rank, "unblocks": _cut(u, UNBLOCKS_WORDS) if isinstance(u, str) else ""})
    items.sort(key=lambda x: x["rank"])
    return {"brief": _cut_brief(reply["brief"]), "items": items}


def _parse_reply(stdout: str) -> tuple[object, dict]:
    """(the model's JSON reply, usage figures) from `claude -p --output-format json`; ValueError if unusable."""
    out = json.loads(stdout)
    if not isinstance(out, dict) or out.get("is_error") or not isinstance(out.get("result"), str):
        raise ValueError("claude reported an error")
    text = out["result"].strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    usage = {"cost_usd": out.get("total_cost_usd"), "latency_ms": out.get("duration_ms")}
    return json.loads(m.group(1) if m else text), usage


def refresh_brief(now: float | None = None, *, rows: list[dict] | None = None) -> int:
    """Ask the model once and replace the cache; on any failure keep the old cache and leave the
    lock in place, which holds the next attempt back for the stale-lock time."""
    now = asks._now() if now is None else now
    if not model_brief_enabled():
        _brief_lock().unlink(missing_ok=True)
        return 0
    if rows is None:
        rows = ranked(asks.collect(asks.DEFAULT_DAYS, now), now)
    if not rows:
        _brief_lock().unlink(missing_ok=True)
        return 0
    cand = brief_candidates(rows)
    try:
        code, out = _run_claude(brief_command(), json.dumps({"questions": cand}, ensure_ascii=False))
        if code != 0:
            return 1
        reply, usage = _parse_reply(out)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 1
    ok = validate_brief(reply, {c["id"] for c in cand})
    if ok is None:
        return 1
    asks._atomic_write(_brief_cache(), json.dumps({"generated": _iso(now), "ask_ids_hash": ask_ids_hash(rows),
                                                  "model": BRIEF_MODEL, **usage, **ok}))
    _brief_lock().unlink(missing_ok=True)
    return 0


def _spawn_brief_refresh(now: float | None = None) -> None:
    """Start one detached refresh. The lock is created exclusively; one older than five minutes is stale."""
    now = asks._now() if now is None else now
    lock = _brief_lock()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            if now - lock.stat().st_mtime < BRIEF_LOCK_STALE_S:
                return
            os.utime(lock, (now, now))      # stale: take it over
        subprocess.Popen([sys.executable, "-m", "teyla", "state", "--refresh-brief"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        pass


def cached_brief(rows: list[dict], now: float) -> dict | None:
    """The model's brief for exactly this set of open questions, or None (rules apply). A missing,
    other-set or older-than-30-minutes cache starts one refresh."""
    if not rows or not model_brief_enabled():
        return None
    try:
        c = json.loads(_brief_cache().read_text())
        match = c.get("ask_ids_hash") == ask_ids_hash(rows) and isinstance(c.get("brief"), str) \
            and isinstance(c.get("items"), list)
        fresh = now - (asks._epoch(c.get("generated")) or 0) < BRIEF_FRESH_S
    except (OSError, ValueError, AttributeError, TypeError):
        c, match, fresh = None, False, False
    if not (match and fresh):
        _spawn_brief_refresh(now)
    return c if match else None


def apply_model_brief(rows: list[dict], c: dict) -> list[dict]:
    """Rows in the model's order with its `unblocks`; questions the model did not rank keep their
    rule values and follow. Ranks are renumbered 1..n."""
    mine = {i["id"]: i for i in c["items"] if isinstance(i, dict) and isinstance(i.get("rank"), int)}
    first = sorted((r for r in rows if r["id"] in mine), key=lambda r: mine[r["id"]]["rank"])
    out = []
    for r in first:
        u = mine[r["id"]].get("unblocks")
        out.append({**r, "unblocks": u if isinstance(u, str) else ""})
    out += [r for r in rows if r["id"] not in mine]
    for n, r in enumerate(out, 1):
        r["rank"] = n
    return out


# --- tasks, backlog, relay --------------------------------------------------------------------

def _cfg() -> dict:
    try:
        return config.load()
    except Exception:  # noqa: BLE001 — an unreadable config is "defaults", not a failed snapshot
        return {}


def backlog_enabled() -> bool:
    """GitHub is read only outside safe mode and with `gh` on PATH."""
    try:
        return net.allowed(_cfg()) and shutil.which("gh") is not None
    except Exception:  # noqa: BLE001
        return False


def backlog_view(now: float) -> dict:
    try:
        return backlog.view(now, refresh=backlog_enabled())
    except Exception:  # noqa: BLE001 — GitHub data is an extra; the rest of the snapshot always works
        return dict(backlog.EMPTY, prs=[], issues=[], counts={}, canonical={})


def active_slugs(repos: dict, now: float) -> list[str]:
    """GitHub names of the repos that moved in the last 30 days: the ones whose open issues are counted."""
    today = _dt.datetime.fromtimestamp(now).date()
    out = set()
    for path in repos.values():
        last, _ = _repo_signals(path, today)
        slug = backlog.remote_slug(path)
        if slug and last is not None and now - last <= REPO_RECENT_DAYS * 86400:
            out.add(slug)
    return sorted(out)


def refresh_backlog(now: float | None = None, runner=None, repos: dict | None = None) -> int:
    now = asks._now() if now is None else now
    if runner is None and not backlog_enabled():
        backlog.lock_path().unlink(missing_ok=True)
        return 0
    return backlog.refresh(active_slugs(repo_index() if repos is None else repos, now), now, runner)


def review_note(pr: dict, ledger: dict | None) -> str:
    """What the review ledger says about a PR's head commit, in a sentence."""
    repo = pr["repo"].lower()
    short = repo.split("/", 1)[1]
    if ledger is not None:
        hit = [r for r in ledger["reviews"] if r["repo"] in (repo, short) and reviews._same_sha(r["sha"], pr["head"])]
        if hit:
            last = max(hit, key=lambda r: r["seq"])
            if last["p1"] > 0:
                return f"Reviewed with {last['p1']} open P1. Fix it before you merge."
            return "Reviewed, no open P1."
        skip = [k for k in ledger["skips"] if k["repo"] in (repo, short)
                and (k["pr"] == pr["number"] or (k["sha"] and reviews._same_sha(k["sha"], pr["head"])))]
        if skip:
            why = skip[-1]["reason"]
            return "Review skipped" + (f": {why}." if why else ".")
    return "No review of the head commit in the ledger."


def tasks_view(bl: dict, approved: set, ledger: dict | None, now: float) -> list[dict]:
    """What only the owner can do, oldest first: his open PRs in repos that are not merge-approved, and the
    issues assigned to him."""
    out = []
    for pr in bl["prs"]:
        if pr.get("draft") or pr["repo"].lower() in approved:
            continue
        out.append({"id": f"pr:{pr['repo']}#{pr['number']}", "kind": "merge", "product": pr["repo"].split("/", 1)[1],
                    "title": asks.clip("Merge: " + pr["title"], asks.TITLE_MAX),
                    "detail": f"{review_note(pr, ledger)} The repo is not merge-approved, so it waits on you.",
                    "link": pr["url"], "age_s": max(0, int(now - pr["created"]))})
    for it in bl["issues"]:
        labels = it.get("labels") or []
        out.append({"id": f"issue:{it['repo']}#{it['number']}", "kind": "task", "product": it["repo"].split("/", 1)[1],
                    "title": asks.clip(it["title"], asks.TITLE_MAX),
                    "detail": "Assigned to you." + (f" Labels: {', '.join(labels[:4])}." if labels else ""),
                    "link": it["url"], "age_s": max(0, int(now - it["created"]))})
    out.sort(key=lambda t: -t["age_s"])
    return out


def relay_view() -> dict:
    """The iPhone relay: `teyla relay` writes ~/.teyla/relay.json and the pairing key."""
    out = {"on": False, "paired": False, "folder": "", "synced": ""}
    try:
        j = json.loads((control.home() / "relay.json").read_text())
        if isinstance(j, dict):
            out.update(on=j.get("on") is True, folder=str(j.get("folder") or ""), synced=str(j.get("synced") or ""))
    except (OSError, ValueError):
        pass
    out["paired"] = (control.home() / "relay.key").exists()
    return out


# --- the snapshot -----------------------------------------------------------------------------

def build(now: float | None = None, *, days: int = asks.DEFAULT_DAYS, repos: dict | None = None,
          spent="cache", items: list[asks.Ask] | None = None, desktop: str | None = None,
          projects: str | None = None, codex_root: str | None = None, codex_archive: str | None = None,
          reminders: pathlib.Path | None = None, model_brief: bool = True, runs: list[dict] | None = None,
          backlog_data: dict | None = None, approved: set | None = None, ledger: dict | None = None,
          relay: dict | None = None) -> dict:
    now = asks._now() if now is None else now
    if items is None:
        items = asks.collect(days, now, desktop=desktop, projects=projects, codex_root=codex_root,
                             codex_archive=codex_archive, reminders=reminders)
    rows = ranked(items, now)
    model = None
    if model_brief:
        try:
            model = cached_brief(rows, now)
        except Exception:  # noqa: BLE001 — the model brief is an upgrade; the rules always work
            model = None
    if model:
        rows = apply_model_brief(rows, model)
    runs = dispatched() if runs is None else runs
    dk, cx = desktop_sessions(desktop), codex_sessions(now, codex_root, runs)
    cc = claude_dispatch_sessions(now, projects, runs)
    run = running(now, desktop, codex_root, runs=runs, dk=dk, cx=cx, cc=cc)
    done = done_feed(now, desktop, codex_root, projects, runs=runs, dk=dk, cx=cx, cc=cc,
                     skip_ids={r["id"] for r in run})
    repos = repo_index() if repos is None else repos
    bl = backlog_view(now) if backlog_data is None else backlog_data
    alias, info = product_names(repos, bl["canonical"])
    tasks = []
    if bl["prs"] or bl["issues"]:
        if bl["prs"]:
            approved = backlog.merge_approved(_cfg()) if approved is None else approved
            ledger = reviews.load_ledger(reviews.ledger_path(_cfg())) if ledger is None else ledger
        tasks = tasks_view(bl, approved or set(), ledger, now)
    for r in rows + run + done:
        r["product"] = alias.get(r["product"], r["product"])
    prods = products_view(rows, run, {k: v["paths"] for k, v in info.items()}, now,
                          keep={t["product"] for t in tasks})
    enrich_products(prods, info, bl["counts"], tasks, done)
    if spent == "cache":
        try:
            spent = spent_today(now)
        except Exception:  # noqa: BLE001
            spent = None
    st = {"version": VERSION, "generated": _iso(now), "brief": None,
          "totals": {"questions": len(rows), "running": len(run), "spent_today_usd": spent,
                     "tasks": len(tasks), "done": len(done)},
          "asks": rows, "tasks": tasks, "done": done, "products": prods,
          "running": [{k: v for k, v in r.items() if k != "_last"} for r in run],
          "relay": relay_view() if relay is None else relay}
    st["brief"] = {"line": _words(model["brief"]), "source": "model"} if model else brief_line(st)
    return st


def render_text(st: dict, now: float) -> str:
    t = st["totals"]
    spent = "n/a" if t["spent_today_usd"] is None else f"${t['spent_today_usd']:.2f}"
    lines = [st["brief"]["line"] if st["brief"] else "",
             f"{t['questions']} waiting, {t.get('tasks', 0)} tasks, {t.get('done', 0)} done, "
             f"{t['running']} running, {spent} today"]
    for a in st["asks"][:4]:
        why = f"  [{a['unblocks']}]" if a["unblocks"] else ""
        q = a["question"].replace("\n", " ")
        lines.append(f"{a['rank']}. {a['id']} {a['product']}: {q[:70]}{'…' if len(q) > 70 else ''}{why}")
    if len(st["asks"]) > 4:
        lines.append(f"   + {len(st['asks']) - 4} more (teyla asks)")
    tasks = st.get("tasks") or []
    if tasks:
        lines.append("Tasks")
        lines += [f"  {x['product']}: {x['title'][:60]}" for x in tasks[:2]]
        if len(tasks) > 2:
            lines.append(f"  + {len(tasks) - 2} more")
    done = st.get("done") or []
    if done:
        lines.append("Done")
        lines += [f"  {x['product']} [{x['status']}]: {(x['result'][0] if x['result'] else x['title'])[:55]}"
                  for x in done[:2]]
        if len(done) > 2:
            lines.append(f"  + {len(done) - 2} more")
    for p in st["products"][:max(0, min(4, 15 - len(lines)))]:
        lines.append(f"{p['name']:14} {p['state']:8} {p['line'][:50]}")
    return "\n".join(lines[:15])


def cmd_state(args) -> int:
    if args.refresh_brief:
        try:
            return refresh_brief()
        except Exception:  # noqa: BLE001 — a background job
            return 1
    if args.refresh_spend:
        try:
            refresh_spend()
        except Exception:  # noqa: BLE001 — a background job: no spend data is not an error anyone reads
            return 1
        return 0
    if args.refresh_backlog:
        try:
            return refresh_backlog()
        except Exception:  # noqa: BLE001 — a background job
            return 1
    now = asks._now()
    st = build(now)
    print(json.dumps(st, indent=1) if args.json else render_text(st, now))
    return 0


def register(sp):
    q = sp.add_parser("state", help="one snapshot for the Teyla for Mac window: questions, tasks, what got done, products, running sessions")
    q.set_defaults(fn=cmd_state)
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh-spend", action="store_true", help=argparse.SUPPRESS)
    q.add_argument("--refresh-brief", action="store_true", help=argparse.SUPPRESS)
    q.add_argument("--refresh-backlog", action="store_true", help=argparse.SUPPRESS)
    return q
