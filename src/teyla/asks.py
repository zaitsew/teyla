"""`teyla asks` — one list of every question an AI session left waiting on the owner.

A session ends on a question, the desktop app archives it, and nobody reads it again. In 14
days 40 Claude Code sessions ended that way; 38 sat in the archive and 1 got an answer. This
module reads what is already on disk, read-only, and lists the open ones in one place.

    teyla asks [--days 21] [--product P] [--all] [--json]    open items, grouped by product, oldest first
    teyla asks done <id-prefix>... [--note TEXT]              close one (or several)
    teyla asks snooze <id-prefix> <days>                      hide one for N days
    teyla asks --html [-o FILE] [--open]                      one self-contained page (default ~/.teyla/asks.html)
    teyla asks --quiet                                        refresh ~/.teyla/asks.count only (what the hook reads)

Sources (nothing is written to them; `docs/ASKS.md` has the field-by-field detail):

1. Claude desktop session metadata (`claude-code-sessions/<account>/<workspace>/local_*.json`,
   root overridable with `TEYLA_CLAUDE_SESSIONS`): a session whose `postTurnSummary` is `blocked`
   or has a `needs_action` line.
2. Claude Code transcripts: the last assistant turn waits when it calls `mcp__ccd_turn__wrap_up`
   with an `ask`, or its final text ends with a question. Only the end of the file is read.
3. Codex rollouts: a `request_user_input_async` call with no output, or a final message that ends
   with a question. `codex exec` runs and spawned agents are automation and are skipped.
4. Teyla's own needs-you queue: pending gated runs (`teyla inbox`) and reminders due within 7 days.

A desktop session and its transcript are one record. An item closes by itself when a later human
prompt appears in its session; `done` and `snooze` live in `~/.teyla/asks.json`. Question text
passes through `corrections.scrub` and is cut at 600 characters.

`teyla asks` output is private: it holds session text. It is never part of `monitor --share`
or `feedback`, and `tests/test_share_leaks.py` holds that.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import glob
import hashlib
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

from . import corrections
from .adapters import (claude_code, codex, human_text, is_noise_turn, is_retry, iter_jsonl,
                       strip_reminders, text_of, turn_end_candidate)
from .control import state

DEFAULT_DAYS = 21
WRAP_UP = "mcp__ccd_turn__wrap_up"
QUESTION_MAX = 600
CONTEXT_MAX = 300
TRAILING_MAX = 400
TITLE_MAX = 100
REMINDER_WINDOW_DAYS = 7
TAIL_BYTES = 256 * 1024          # enough for the last turn of a transcript; they run to tens of MB
STATE_KEEP_DAYS = 180
KINDS = ("question", "blocked", "gate", "reminder")
OPEN_LINK = "claude://claude.ai/epitaxy/"


# --- where things live ------------------------------------------------------------------------

def desktop_root() -> str:
    """The Claude desktop app's session metadata. `TEYLA_CLAUDE_SESSIONS` moves it (tests do)."""
    env = os.environ.get("TEYLA_CLAUDE_SESSIONS")
    if env:
        return env
    home = pathlib.Path.home()
    for base in (home / "Library" / "Application Support" / "Claude", home / ".config" / "Claude"):
        if (base / "claude-code-sessions").is_dir():
            return str(base / "claude-code-sessions")
    return str(home / "Library" / "Application Support" / "Claude" / "claude-code-sessions")


def state_path() -> pathlib.Path:
    return state.home() / "asks.json"


def count_path() -> pathlib.Path:
    return state.home() / "asks.count"


def html_path() -> pathlib.Path:
    return state.home() / "asks.html"


def stamp_path() -> pathlib.Path:
    return state.home() / "asks.stamp"


# --- the record -------------------------------------------------------------------------------

@dataclasses.dataclass
class Ask:
    id: str
    kind: str                 # question | blocked | gate | reminder
    product: str
    title: str
    question: str
    context: str
    options: list
    when: float               # last activity, POSIX seconds
    archived: bool
    link: str
    pr: str
    harness: str              # claude-desktop | claude-code | codex | teyla
    status: str = "open"      # open | done | snoozed
    due: str = ""

    def to_dict(self, now: float) -> dict:
        d = dataclasses.asdict(self)
        when = d.pop("when")
        d["ts"] = _iso(when)
        d["age_s"] = int(now - when)
        if not d["due"]:
            d.pop("due")
        return d


def _iso(epoch: float) -> str:
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(ts) -> float | None:
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e11 else float(ts)
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)).timestamp()


def make_id(source: str, session: str, turn: str) -> str:
    return hashlib.sha1(f"{source}|{session}|{turn}".encode()).hexdigest()[:8]


def clip(text, limit: int) -> str:
    """Scrubbed, then cut at `limit` characters with an ellipsis. The text is otherwise verbatim."""
    t = corrections.scrub(str(text or "")).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def product_of(cwd) -> str:
    """The repo a working directory belongs to; a worktree maps to its repo."""
    if not cwd:
        return "unknown"
    raw = str(cwd).rstrip("/")
    parts = [p for p in pathlib.PurePosixPath(raw).parts if p != "/"]
    for i in range(1, len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return parts[i - 1]
    if ".worktrees" in parts:
        i = parts.index(".worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    if "repos" in parts:
        i = parts.index("repos")
        return parts[i + 1] if i + 1 < len(parts) else "(no repo)"
    if raw == str(pathlib.Path.home()).rstrip("/"):
        return "(home)"
    if parts and parts[0] in ("tmp", "private", "var"):
        return "(scratch)"
    return parts[-1] if parts else "unknown"


# --- questions in text ------------------------------------------------------------------------

_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_CLOSERS = "*_`)\"'”»] "


def _paragraph_asks(p: str) -> bool:
    core = p.rstrip().rstrip(_CLOSERS)
    return core.endswith(("?", "？")) or "?" in p[-250:] or "let me know" in p.lower()


def trailing_question(text) -> str | None:
    """The last paragraph of an agent's final text when it asks something, else None. A question
    followed by a short list of options is returned with the list. At most TRAILING_MAX characters,
    cut from the front so the question itself survives."""
    if not text or not turn_end_candidate(text):
        return None
    paras = [p.strip() for p in re.split(r"\n\s*\n", str(text).strip()) if p.strip()]
    if not paras:
        return None
    last = paras[-1]
    if all(_LIST_LINE.match(l) for l in last.splitlines() if l.strip()) and len(paras) > 1:
        if not _paragraph_asks(paras[-2]):
            return None
        last = paras[-2] + "\n" + last
    elif not _paragraph_asks(last):
        return None
    if len(last) > TRAILING_MAX:
        last = "…" + last[-(TRAILING_MAX - 1):].lstrip()
    return last


def _is_reply(txt: str) -> bool:
    """A human turn that answers: what `human_text` keeps, plus a bare "continue", which is a retry
    to the turn counters and an answer to a question."""
    if human_text(txt):
        return True
    bare = strip_reminders(txt)
    return bool(bare) and not is_noise_turn(bare) and is_retry(bare)


# --- Claude Code transcripts ------------------------------------------------------------------

def scan_claude(path: str, tail_bytes: int = TAIL_BYTES) -> dict | None:
    """What the end of a Claude Code transcript says: the last assistant turn's wrap-up ask or
    trailing question, and whether a human prompt came after it. None when the file has no
    assistant turn in the part read."""
    run: list[dict] = []
    last_assistant = None
    human_after = False
    batch = False
    cwd = None
    try:
        for o in iter_jsonl(path, tail_bytes=tail_bytes):
            if o.get("cwd"):
                cwd = o["cwd"]
            if str(o.get("entrypoint") or "").startswith(claude_code.BATCH_ENTRYPOINT_PREFIX):
                batch = True
            if o.get("isSidechain"):
                continue
            t = o.get("type")
            if t == "assistant":
                last_assistant = o
                human_after = False
                if o.get("isApiErrorMessage"):
                    run = []                   # a synthetic error turn asks nothing
                else:
                    run.append(o)
            elif t == "user":
                content = (o.get("message") or {}).get("content") if isinstance(o.get("message"), dict) else None
                if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                if o.get("isMeta"):
                    continue
                txt = text_of(content).strip()
                if txt and _is_reply(txt):
                    run, human_after = [], True
    except OSError:
        return None
    if last_assistant is None:
        return None
    blocks = []
    for rec in run:
        c = (rec.get("message") or {}).get("content")
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
        blocks += [b for b in (c or []) if isinstance(b, dict)]
    last_tool = max((i for i, b in enumerate(blocks) if b.get("type") == "tool_use" and b.get("name") != WRAP_UP),
                    default=-1)
    ask = recap = None
    options: list = []
    for i, b in enumerate(blocks):
        if i > last_tool and b.get("type") == "tool_use" and b.get("name") == WRAP_UP:
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            a = str(inp.get("ask") or "").strip()
            ask = a or None
            recap = str(inp.get("recap") or "").strip() or None
            options = [str(x.get("label")) for x in inp.get("actions") or []
                       if isinstance(x, dict) and x.get("label")] if a else []
    question = None
    texts = [b.get("text") for i, b in enumerate(blocks) if i > last_tool and b.get("type") == "text"]
    if texts:
        question = trailing_question(texts[-1])
    return {"uuid": last_assistant.get("uuid") or "", "ts": _epoch(last_assistant.get("timestamp")),
            "cwd": cwd, "batch": batch, "human_after": human_after,
            "ask": ask, "recap": recap, "options": options, "question": question}


def find_transcript(cli_id: str, cwd: str, root: str) -> str | None:
    """`<root>/<cwd with "/" and "." as "-">/<id>.jsonl`, else the file of that name anywhere under root."""
    if not cli_id or not re.fullmatch(r"[0-9A-Za-z_-]+", str(cli_id)):
        return None
    direct = os.path.join(root, re.sub(r"[/.]", "-", cwd or ""), f"{cli_id}.jsonl")
    if os.path.isfile(direct):
        return direct
    found = glob.glob(os.path.join(root, "*", f"{cli_id}.jsonl"))
    return found[0] if found else None


def _desktop_sessions(root: str) -> list[dict]:
    out = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*", "local_*.json"))):
        try:
            d = json.loads(pathlib.Path(f).read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _claude_ask(d: dict | None, ana: dict | None, cli_id: str, since: float) -> Ask | None:
    """One record from a desktop session (`d`), its transcript scan (`ana`), or both."""
    pts = (d or {}).get("postTurnSummary") or {}
    needs = str(pts.get("needs_action") or "").strip()
    blocked = pts.get("status_category") == "blocked"
    detail = str(pts.get("status_detail") or "").strip()
    if ana and ana["human_after"]:
        return None                                   # answered
    if ana and ana["batch"]:
        return None                                   # a script's session, nobody to ask
    summary_current = True
    su = str(pts.get("summarizes_uuid") or "")
    if ana and ana["uuid"] and su and su != ana["uuid"]:
        summary_current = False                       # the session went on after the summary was written
    ask, trailing = (ana or {}).get("ask"), (ana or {}).get("question")
    needs_action = needs if summary_current else ""
    if not (ask or trailing or needs_action or (blocked and summary_current)):
        return None
    text = ask or needs_action or trailing or detail or "The session is blocked; its summary names no question."
    kind = "question" if (ask or trailing) else "blocked"
    context = (ana or {}).get("recap") if ask else (detail if summary_current else "")
    if d:
        when = (_epoch(d.get("lastActivityAt") or d.get("createdAt")) or 0.0)
        sid = str(d.get("sessionId") or "")
        link = OPEN_LINK + sid if sid.startswith("local_") else f"claude --resume {cli_id}"
        title = d.get("title") or ""
        cwd = d.get("cwd") or d.get("originCwd") or (ana or {}).get("cwd")
        prs = [p for p in d.get("prs") or [] if isinstance(p, dict) and p.get("url")]
        pr = str(prs[-1]["url"]) if prs else ""
        archived = bool(d.get("isArchived"))
        harness = "claude-desktop"
    else:
        when = (ana or {}).get("ts") or 0.0
        link, title, pr, archived, harness = f"claude --resume {cli_id}", "", "", False, "claude-code"
        cwd = (ana or {}).get("cwd")
    if when < since:
        return None
    turn = (ana or {}).get("uuid") or su
    return Ask(id=make_id("claude", cli_id, turn), kind=kind, product=product_of(cwd),
               title=clip(title or text.splitlines()[0], TITLE_MAX), question=clip(text, QUESTION_MAX),
               context=clip(context or "", CONTEXT_MAX), options=[clip(o, 80) for o in (ana or {}).get("options") or []],
               when=when, archived=archived, link=link, pr=pr, harness=harness)


def collect_claude(since: float, desktop: str | None = None, projects: str | None = None) -> list[Ask]:
    desktop = desktop_root() if desktop is None else desktop
    projects = claude_code.DEFAULT_ROOT if projects is None else projects
    out: list[Ask] = []
    known: set[str] = set()
    for d in _desktop_sessions(desktop) if os.path.isdir(desktop) else []:
        cli_id = str(d.get("cliSessionId") or "")
        if not cli_id:
            continue
        known.add(cli_id)
        last = _epoch(d.get("lastActivityAt") or d.get("createdAt")) or 0.0
        if last < since:
            continue
        tpath = find_transcript(cli_id, d.get("cwd") or "", projects) if os.path.isdir(projects) else None
        ana = scan_claude(tpath) if tpath else None
        a = _claude_ask(d, ana, cli_id, since)
        if a:
            out.append(a)
    if os.path.isdir(projects):
        for f in sorted(glob.glob(os.path.join(projects, "*", "*.jsonl"))):
            cli_id = os.path.basename(f)[:-len(".jsonl")]
            if cli_id in known:
                continue
            try:
                if os.stat(f).st_mtime < since:
                    continue
            except OSError:
                continue
            ana = scan_claude(f)
            if ana is None:
                continue
            a = _claude_ask(None, ana, cli_id, since)
            if a:
                out.append(a)
    return out


# --- Codex rollouts ---------------------------------------------------------------------------

_REVIEW_PROMPTS = ("One-pass code review",)


def _is_automation(meta: dict) -> bool:
    src = meta.get("source")
    return (src in codex.BATCH_SOURCES or meta.get("originator") in codex.BATCH_ORIGINATORS
            or (isinstance(src, dict) and "subagent" in src))


def _codex_user_text(p: dict) -> str:
    return strip_reminders(codex.strip_injected(codex._text_of(p.get("content")).strip()))


def _codex_options(args: dict) -> tuple[str, list]:
    titles, opts = [], []
    for q in args.get("questions") or []:
        if not isinstance(q, dict):
            continue
        if q.get("title") or q.get("question"):
            titles.append(str(q.get("title") or q.get("question")))
        for o in q.get("options") or []:
            label = o.get("label") if isinstance(o, dict) else o
            if label:
                opts.append(str(label))
    return "\n".join(titles), opts


def scan_codex(path: str, tail_bytes: int = TAIL_BYTES) -> dict | None:
    """The open question at the end of a Codex rollout, or None (automation, answered, or none)."""
    meta: dict = {}
    try:
        head = iter_jsonl(path)
        for n, o in enumerate(head):
            p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if o.get("type") == "session_meta":
                meta = p
                if _is_automation(p):
                    head.close()
                    return None
            elif o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                txt = _codex_user_text(p)
                if txt.startswith(_REVIEW_PROMPTS):
                    head.close()
                    return None
                if txt and not txt.startswith("# AGENTS.md instructions"):
                    break
            if n > 40:
                break
        head.close()
        pending: dict[str, tuple] = {}
        async_ids: set[str] = set()
        last_msg = None
        last_ts = None
        human_after = False
        for o in iter_jsonl(path, tail_bytes=tail_bytes):
            p = o.get("payload") if isinstance(o.get("payload"), dict) else None
            if p is None:
                continue
            ts = o.get("timestamp")
            if o.get("type") == "event_msg":
                et = p.get("type")
                if et == "task_complete":
                    human_after = False
                    m = p.get("last_agent_message")
                    last_msg = (ts, m, p.get("turn_id") or "") if isinstance(m, str) and m.strip() else None
                    last_ts = ts
                elif et == "task_started":
                    last_msg = None
            elif o.get("type") == "response_item":
                pt = p.get("type")
                if pt == "message" and p.get("role") == "user":
                    clean = _codex_user_text(p)
                    if clean.startswith("# AGENTS.md instructions") or "<INSTRUCTIONS>" in clean[:300]:
                        continue
                    if _is_reply(clean) if clean else False:
                        pending.clear()
                        last_msg, human_after = None, True
                elif pt == "message" and p.get("role") == "assistant":
                    human_after = False
                elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                    human_after = False
                    name = (p.get("name") or "").rsplit(".", 1)[-1]
                    if name == "request_user_input_async":
                        try:
                            args = json.loads(p.get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        title, opts = _codex_options(args if isinstance(args, dict) else {})
                        if title and p.get("call_id"):
                            pending[p["call_id"]] = (ts, title, opts)
                            async_ids.add(p["call_id"])
                            last_ts = ts
                    else:
                        last_msg = None
                elif pt in ("function_call_output", "custom_tool_call_output"):
                    # request_user_input_async returns at once, before the owner answers:
                    # only a later human message closes it.
                    if p.get("call_id") not in async_ids:
                        pending.pop(p.get("call_id"), None)
    except OSError:
        return None
    if human_after:
        return None
    sid = str(meta.get("session_id") or meta.get("id") or "")
    if not sid:
        m = re.match(r"rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-(.+)\.jsonl$", os.path.basename(path))
        sid = m.group(1) if m else os.path.basename(path)
    base = {"sid": sid, "cwd": meta.get("cwd")}
    if pending:
        call_id, (ts, title, opts) = next(reversed(pending.items()))
        return dict(base, ts=_epoch(ts), question=title, options=opts, turn=call_id, kind="question")
    if last_msg:
        q = trailing_question(last_msg[1])
        if q:
            return dict(base, ts=_epoch(last_msg[0]), question=q, options=[], turn=last_msg[2] or str(last_ts), kind="question")
    return None


def collect_codex(since: float, root: str | None = None, archive: str | None = None) -> list[Ask]:
    root = codex.DEFAULT_ROOT if root is None else root
    archive = codex.DEFAULT_ARCHIVE_ROOT if archive is None else archive
    titles = codex._load_titles(codex.DEFAULT_INDEX)
    out: list[Ask] = []
    for base, archived in ((root, False), (archive, True)):
        if not base or not os.path.isdir(base):
            continue
        for f in codex._rollouts(base, since):
            r = scan_codex(f)
            if not r or not r["question"]:
                continue
            when = r["ts"] or os.stat(f).st_mtime
            if when < since:
                continue
            out.append(Ask(id=make_id("codex", r["sid"], r["turn"]), kind=r["kind"], product=product_of(r["cwd"]),
                           title=clip(titles.get(r["sid"]) or r["question"].splitlines()[0], TITLE_MAX),
                           question=clip(r["question"], QUESTION_MAX), context="",
                           options=[clip(o, 80) for o in r["options"]], when=when, archived=archived,
                           link=f"codex resume {r['sid']}", pr="", harness="codex"))
    return out


# --- Teyla's own queue ------------------------------------------------------------------------

def collect_gates() -> list[Ask]:
    out = []
    for it in state.pending_inbox():
        when = _epoch(it.get("ts")) or 0.0
        rid = str(it.get("id") or "")
        out.append(Ask(id=make_id("gate", rid, str(it.get("ts") or "")), kind="gate",
                       product=product_of(it.get("repo")) if it.get("repo") else "teyla",
                       title=clip(it.get("routine") or "gated run", TITLE_MAX),
                       question=clip(it.get("summary") or "A gated run is waiting for approval.", QUESTION_MAX),
                       context=clip(f"gate {it.get('gate', '?')}, state {it.get('state', '?')}", CONTEXT_MAX),
                       options=["approve", "reject"], when=when, archived=False,
                       link=f"teyla inbox show {rid}", pr="", harness="teyla"))
    return out


def collect_reminders(path: pathlib.Path | None = None, today: _dt.date | None = None) -> list[Ask]:
    from . import remind
    today = today or _dt.date.today()
    out = []
    for r in remind.load(path):
        try:
            d = remind.days_until(r["due"], today)
        except ValueError:
            continue
        if d > REMINDER_WINDOW_DAYS:
            continue
        due_at = _dt.datetime.combine(remind.parse_due(r["due"]), _dt.time(), tzinfo=_dt.timezone.utc).timestamp()
        when_txt = f"overdue by {-d}d" if d < 0 else ("due today" if d == 0 else f"due in {d}d")
        out.append(Ask(id=make_id("reminder", r["what"], r["due"]), kind="reminder", product="reminders",
                       title=clip(r["what"], TITLE_MAX), question=clip(r["what"], QUESTION_MAX),
                       context=clip(f"{when_txt} ({r['due']})" + (f": {r['how']}" if r.get("how") else ""), CONTEXT_MAX),
                       options=[], when=due_at, archived=False, link="teyla remind list", pr="",
                       harness="teyla", due=r["due"]))
    return out


# --- state: done and snoozed ------------------------------------------------------------------

def load_state(path: pathlib.Path | None = None) -> dict:
    p = path or state_path()
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("done", {})
    d.setdefault("snoozed", {})
    return d


def save_state(st: dict, path: pathlib.Path | None = None, now: float | None = None) -> None:
    p = path or state_path()
    cut = _iso((now or _now()) - STATE_KEEP_DAYS * 86400)
    st = {"version": 1,
          "done": {k: v for k, v in st["done"].items() if str(v.get("ts", "")) >= cut},
          "snoozed": {k: v for k, v in st["snoozed"].items() if str(v.get("until", "")) >= cut}}
    _atomic_write(p, json.dumps(st, indent=1, sort_keys=True) + "\n")


def _atomic_write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> float:
    return _dt.datetime.now(_dt.timezone.utc).timestamp()


def apply_state(items: list[Ask], st: dict, now: float) -> list[Ask]:
    for a in items:
        if a.id in st["done"]:
            a.status = "done"
        elif a.id in st["snoozed"] and str(st["snoozed"][a.id].get("until", "")) > _iso(now):
            a.status = "snoozed"
    return items


# --- collecting everything --------------------------------------------------------------------

def collect(days: int = DEFAULT_DAYS, now: float | None = None, desktop: str | None = None,
            projects: str | None = None, codex_root: str | None = None, codex_archive: str | None = None,
            reminders: pathlib.Path | None = None, st: dict | None = None) -> list[Ask]:
    """Every waiting item from the four sources, state applied, oldest first. Deduped by id."""
    now = _now() if now is None else now
    since = now - days * 86400
    items = (collect_claude(since, desktop, projects) + collect_codex(since, codex_root, codex_archive)
             + collect_gates() + collect_reminders(reminders, _dt.datetime.fromtimestamp(now).date()))
    seen, unique = set(), []
    for a in items:
        if a.id not in seen:
            seen.add(a.id)
            unique.append(a)
    apply_state(unique, load_state() if st is None else st, now)
    unique.sort(key=lambda a: a.when)
    return unique


def resolve(prefix: str, items: list[Ask]) -> tuple[Ask | None, str]:
    p = prefix.strip().lower()
    if len(p) < 3:
        return None, f"{prefix!r} is too short: give at least 3 characters of an id"
    hits = [a for a in items if a.id.startswith(p)]
    if not hits:
        return None, f"no item with an id starting {prefix!r} (try `teyla asks --all`)"
    if len(hits) > 1:
        return None, f"{prefix!r} matches {len(hits)} items: " + ", ".join(a.id for a in hits)
    return hits[0], ""


def mark_done(prefixes: list[str], note: str = "", now: float | None = None) -> tuple[list[str], int]:
    now = _now() if now is None else now
    items = collect(max(DEFAULT_DAYS, 365), now)
    st = load_state()
    lines, code, changed = [], 0, False
    for pre in prefixes:
        a, err = resolve(pre, items)
        if a is None:
            lines.append(err)
            code = 1
            continue
        st["done"][a.id] = {"ts": _iso(now), **({"note": note} if note else {})}
        st["snoozed"].pop(a.id, None)
        lines.append(f"done: {a.id}  {a.product}  {a.title}")
        changed = True
    if changed:
        save_state(st, now=now)
    return lines, code


def snooze(prefix: str, days: float, now: float | None = None) -> tuple[str, int]:
    now = _now() if now is None else now
    if days <= 0:
        return "snooze needs a number of days above 0", 1
    items = collect(max(DEFAULT_DAYS, 365), now)
    a, err = resolve(prefix, items)
    if a is None:
        return err, 1
    st = load_state()
    st["snoozed"][a.id] = {"until": _iso(now + days * 86400)}
    save_state(st, now=now)
    return f"snoozed {a.id} for {days:g} day(s): {a.product}  {a.title}", 0


# --- the banner count -------------------------------------------------------------------------

def banner_line(items: list[Ask]) -> str:
    n = sum(1 for a in items if a.status == "open" and a.kind != "reminder")
    if not n:
        return ""
    return f"{n} question waits for you — teyla asks" if n == 1 else f"{n} questions wait for you — teyla asks"


def write_count(items: list[Ask]) -> None:
    """~/.teyla/asks.count: the line the session-start hook prints, or no file when nothing waits.
    The hook does no scanning; this is written by `teyla asks` (the daily routine, the hook's
    hourly background refresh, or any plain run)."""
    line = banner_line(items)
    try:
        if line:
            _atomic_write(count_path(), line + "\n")
        else:
            count_path().unlink(missing_ok=True)
        stamp_path().parent.mkdir(parents=True, exist_ok=True)
        stamp_path().touch()
    except OSError:
        pass


# --- output -----------------------------------------------------------------------------------

def fmt_age(age_s: float) -> str:
    if age_s < 0:
        return f"in {int(-age_s // 86400)}d"
    if age_s < 3600:
        return f"{int(age_s // 60)}m"
    if age_s < 48 * 3600:
        return f"{int(age_s // 3600)}h"
    return f"{int(age_s // 86400)}d"


def header(items: list[Ask]) -> str:
    n = len(items)
    m = sum(1 for a in items if a.archived)
    if not n:
        return "nothing is waiting on you."
    return f"{n} waiting on you ({m} in archived sessions)"


def group(items: list[Ask]) -> list[tuple[str, list[Ask]]]:
    by: dict[str, list[Ask]] = {}
    for a in items:
        by.setdefault(a.product, []).append(a)
    return sorted(by.items(), key=lambda kv: min(a.when for a in kv[1]))


def render_text(items: list[Ask], now: float) -> str:
    lines = [header(items)]
    for product, rows in group(items):
        lines += ["", f"{product} ({len(rows)})"]
        for a in rows:
            flags = (["archived"] if a.archived else []) + ([a.status] if a.status != "open" else []) + [a.kind]
            lines.append(f"  {a.id}  {fmt_age(now - a.when):>5}  [{', '.join(flags)}]  {a.title}")
            lines.append("      " + a.question.replace("\n", "\n      "))
            if a.context:
                lines.append("      -- " + a.context.replace("\n", " "))
            if a.options:
                lines.append("      options: " + " | ".join(a.options))
            lines.append(f"      open: {a.link}" + (f"    pr: {a.pr}" if a.pr else ""))
    if items:
        lines += ["", "close one: teyla asks done <id>   hide for a while: teyla asks snooze <id> <days>"]
    return "\n".join(lines)


def render_json(items: list[Ask], now: float) -> str:
    return json.dumps({"waiting": len(items), "archived": sum(1 for a in items if a.archived),
                       "generated": _iso(now), "items": [a.to_dict(now) for a in items]}, indent=1)


_CSS = """
:root{color-scheme:light dark;--bg:#f6f5f2;--card:#fff;--fg:#1c1b19;--mut:#6b675f;--line:#e2dfd8;--acc:#1f5fbf;--chip:#eceae4;--warn:#a5530a}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--card:#201f1c;--fg:#ecebe6;--mut:#a09c92;--line:#34322d;--acc:#7fb0ff;--chip:#2b2a26;--warn:#f0a35e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 4px}
.sum{color:var(--mut);margin:0 0 16px}.sum b{color:var(--fg)}
h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:24px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:0 0 12px;overflow-wrap:anywhere}
.meta{font-size:13px;color:var(--mut);display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.badge{background:var(--chip);border-radius:999px;padding:1px 8px;font-size:12px}.badge.arch{color:var(--warn)}
.q{font-size:18px;font-weight:600;margin:8px 0;white-space:pre-wrap}.ctx{font-size:14px;color:var(--mut);margin:0 0 8px;white-space:pre-wrap}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}.chip{background:var(--chip);border-radius:8px;padding:4px 10px;font-size:14px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
a.open,button{font:inherit;font-size:14px;border:1px solid var(--line);background:var(--chip);color:var(--acc);border-radius:8px;padding:8px 12px;text-decoration:none;cursor:pointer;min-height:40px}
code{font:13px ui-monospace,Menlo,monospace;background:var(--chip);border-radius:6px;padding:2px 6px}
.none{color:var(--mut);padding:24px 0}
"""

_JS = """
document.querySelectorAll('button[data-cmd]').forEach(function(b){b.addEventListener('click',function(){
var t=b.getAttribute('data-cmd'),done=function(){var o=b.textContent;b.textContent='copied';setTimeout(function(){b.textContent=o},1200)};
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,fb)}else{fb()}
function fb(){var x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(x);done()}
})});
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def render_html(items: list[Ask], now: float) -> str:
    kinds = {}
    for a in items:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    arch = sum(1 for a in items if a.archived)
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Waiting on you</title><style>', _CSS, '</style></head><body><main>',
             '<h1>Waiting on you</h1>',
             f'<p class="sum"><b>{len(items)}</b> open'
             f' &middot; <b>{arch}</b> in archived sessions'
             + "".join(f' &middot; {_e(k)} <b>{v}</b>' for k, v in sorted(kinds.items()))
             + f' &middot; as of {_e(_iso(now))}</p>']
    if not items:
        parts.append('<p class="none">Nothing is waiting on you.</p>')
    for product, rows in group(items):
        parts.append(f'<h2>{_e(product)} &middot; {len(rows)}</h2>')
        for a in rows:
            done_cmd = f"teyla asks done {a.id}"
            parts.append('<section class="card"><div class="meta">'
                         f'<span>{_e(product)}</span><span>{_e(fmt_age(now - a.when))}</span>'
                         f'<span class="badge">{_e(a.kind)}</span>'
                         + ('<span class="badge arch">archived</span>' if a.archived else '')
                         + (f'<span class="badge">{_e(a.status)}</span>' if a.status != "open" else '')
                         + f'<span>{_e(a.id)}</span></div>')
            parts.append(f'<div class="q">{_e(a.question)}</div>')
            if a.context:
                parts.append(f'<p class="ctx">{_e(a.context)}</p>')
            if a.options:
                parts.append('<div class="chips">' + "".join(f'<span class="chip">{_e(o)}</span>' for o in a.options) + '</div>')
            parts.append('<div class="row">')
            if a.link.startswith("claude://"):
                parts.append(f'<a class="open" href="{_e(a.link)}">Open session</a>')
            else:
                parts.append(f'<code>{_e(a.link)}</code><button type="button" data-cmd="{_e(a.link)}">copy open command</button>')
            if a.pr.startswith("https://"):
                parts.append(f'<a class="open" href="{_e(a.pr)}">PR</a>')
            parts.append(f'<button type="button" data-cmd="{_e(done_cmd)}">copy &ldquo;done&rdquo; command</button>')
            parts.append('</div></section>')
    parts.append(f'</main><script>{_JS}</script></body></html>')
    return "".join(parts)


def write_html(items: list[Ask], now: float, out: str | None = None) -> pathlib.Path:
    p = pathlib.Path(out).expanduser() if out else html_path()
    _atomic_write(p, render_html(items, now))
    return p


# --- CLI --------------------------------------------------------------------------------------

def _open_file(path: pathlib.Path) -> None:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([opener, str(path)], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        print(f"could not open {path}; open it by hand", file=sys.stderr)


def cmd_asks(args) -> int:
    words = list(args.words or [])
    now = _now()
    if words and words[0] == "done":
        if len(words) < 2:
            print("usage: teyla asks done <id-prefix>... [--note TEXT]", file=sys.stderr)
            return 64
        lines, code = mark_done(words[1:], args.note or "", now)
        print("\n".join(lines))
        return code
    if words and words[0] == "snooze":
        try:
            if len(words) != 3:
                raise ValueError
            days = float(words[2])
        except ValueError:
            print("usage: teyla asks snooze <id-prefix> <days>", file=sys.stderr)
            return 64
        line, code = snooze(words[1], days, now)
        print(line, file=sys.stderr if code else sys.stdout)
        return code
    if words:
        print(f"unknown action {words[0]!r}: expected done or snooze", file=sys.stderr)
        return 64
    days = args.days or DEFAULT_DAYS
    everything = collect(days, now)
    if not args.product and days == DEFAULT_DAYS and not args.all:
        write_count(everything)
    if args.quiet:
        return 0
    items = [a for a in everything if args.all or a.status == "open"]
    if args.product:
        items = [a for a in items if a.product == args.product]
    if args.html:
        p = write_html(items, now, args.out)
        print(f"{header(items)}\n{p}")
        if args.open:
            _open_file(p)
        return 0
    print(render_json(items, now) if args.json else render_text(items, now))
    return 0


def register(sp):
    q = sp.add_parser("asks", help="every question an AI session left waiting on you, in one list")
    q.set_defaults(fn=cmd_asks)
    q.add_argument("words", nargs="*", help="done <id-prefix>... | snooze <id-prefix> <days>; none lists")
    q.add_argument("--days", type=int, help=f"look back this far (default {DEFAULT_DAYS})")
    q.add_argument("--product", help="one product (repo name)")
    q.add_argument("--all", action="store_true", help="include done and snoozed items")
    q.add_argument("--json", action="store_true")
    q.add_argument("--html", action="store_true", help="write one self-contained page (default ~/.teyla/asks.html)")
    q.add_argument("-o", "--out", help="--html: write here instead")
    q.add_argument("--open", action="store_true", help="--html: open the page")
    q.add_argument("--note", help="done: why")
    q.add_argument("--quiet", action="store_true", help="only refresh ~/.teyla/asks.count (the session-start line)")
    return q
