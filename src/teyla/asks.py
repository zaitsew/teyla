"""`teyla asks` — one list of every question an AI session left waiting on the owner.

A session ends on a question, the desktop app archives it, and nobody reads it again. In 14
days 40 Claude Code sessions ended that way; 38 sat in the archive and 1 got an answer. This
module reads what is already on disk, read-only, and lists the open ones in one place.

    teyla asks [--days 21] [--product P] [--all] [--flat] [--json]   open items, grouped by product (focus first)
    teyla asks done <id-prefix>... [--note TEXT]              close one (or several)
    teyla asks undo <id-prefix>...                            reopen a done one; an auto-closed ask stays open
    teyla asks snooze <id-prefix> <days>                      hide one for N days
    teyla asks triage [--product P] [--json]                  which asks need you, which an agent can act on, which look closable
    teyla asks accept-close [<id-prefix>...] [--json]         close the asks in bucket `close`; prints the `undo:` line
    teyla asks --html [-o FILE] [--open]                      one self-contained page (default ~/.teyla/asks.html)
    teyla asks --quiet                                        refresh ~/.teyla/asks.count only (what the hook reads)

An ask in a parked product is muted: left out of the list and the count, and summed up in one line at
the end. `--all` or `--product <id>` shows it. A critical ask is never muted (`CRITICAL_TERMS`).

Sources (nothing is written to them; `docs/ASKS.md` has the field-by-field detail):

1. Claude desktop session metadata (`claude-code-sessions/<account>/<workspace>/local_*.json`,
   root overridable with `TEYLA_CLAUDE_SESSIONS`): a session whose `postTurnSummary` is `blocked`
   or has a `needs_action` line.
2. Claude Code transcripts: the last assistant turn waits when it calls `mcp__ccd_turn__wrap_up`
   with an `ask`, or its final text ends with a question. Only the end of the file is read.
3. Codex rollouts: a `request_user_input_async` call with no output, or a final message that ends
   with a question. `codex exec` runs and spawned agents are automation and are skipped.
4. Teyla's own needs-you queue: pending gated runs (`teyla inbox`) and reminders due within 7 days.

Five automatic steps (`settle`) keep asks the owner never needed out of the list: a merged or closed PR (note
`auto: PR merged <url>`); a status report, which is kind `report` (`auto: report`); repeats, which collapse into the
newest ask that shows `(+N similar)` (repeat runs of one scheduled job by identity, other repeats by similarity);
a scheduled task that is off (`auto: scheduled task off <id>`); and a "View in TestFlight" tap the cached TestFlight
data shows done (`auto: testflight current <product>`). An ask that `needs_owner` (a price, a key or secret, another
person) is never closed by the last two. All show again with `--all`; `undo` reverses any of them.

A desktop session and its transcript are one record. An item closes by itself when a later human
prompt appears in its session; `done` and `snooze` live in `~/.teyla/asks.json`. Question text
passes through `corrections.scrub` and is cut at 600 characters.

`teyla asks` output is private: it holds session text. It is never part of `monitor --share`
or `feedback`, and `tests/test_share_leaks.py` holds that.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import functools
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

from . import chores, corrections, registry
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
KINDS = ("question", "blocked", "gate", "reminder", "report")
DESIGN_HARNESS = "teyla-design"      # an Ask from `teyla design options`: answered into pick.yaml, not into a session
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
    kind: str                 # question | blocked | gate | reminder | report (a status report, see `is_report`)
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
    status: str = "open"      # open | done | snoozed | duplicate (collapsed into a newer ask, see `settle`)
    due: str = ""
    session: str = ""         # the harness's own session id (Claude cliSessionId, Codex uuid); not in the JSON
    note: str = ""            # why it is done or a duplicate; "auto: ..." when Teyla decided; not in the JSON
    attributed_by: str = ""   # which registry rule chose the product: assign | pr | path | text | checkout | unassigned
    evidence: str = ""        # what that rule matched, for `--why`; not in the JSON
    dupes: list = dataclasses.field(default_factory=list)    # ids collapsed into this ask; in the JSON when any
    task: str = ""            # id of the scheduled task that started the session (desktop `scheduledTaskId`); not in the JSON

    def to_dict(self, now: float, attribution: bool = False) -> dict:
        """The JSON row. `attribution` adds `attributed_by` (`asks --json`); the `teyla state` snapshot
        keeps its version 2 keys."""
        d = dataclasses.asdict(self)
        if not attribution:
            d.pop("attributed_by")
        when = d.pop("when")
        d["ts"] = _iso(when)
        d["age_s"] = int(now - when)
        if not d["due"]:
            d.pop("due")
        d.pop("session")          # internal: `teyla answer` needs it, the `asks --json` schema stays as it was
        d.pop("note")
        d.pop("evidence")
        d.pop("task")
        if not d["dupes"]:
            d.pop("dupes")
        return d


# --- parked products: what stays quiet, and what never does ------------------------------------

# A parked product is muted, except for an ask that must not be missed: a `blocked` session, or text
# naming a security, money or release-failure matter. Case-insensitive, whole words; a trailing * lets
# the word go on (`leak*` is leak, leaked, leaks). One tuple, so the list is easy to read and to change.
CRITICAL_TERMS = (
    # security
    "security", "vulnerab*", "leak*", "secret*", "credential*", "token expired",
    # money
    "charge*", "billing", "invoice", "payment", "price",
    # release failure
    "rejected", "rejection", "crash*", "build failed", "release failed", "upload failed",
)


def _term_pattern(term: str) -> str:
    stem = re.escape(term.rstrip("*")).replace(r"\ ", r"\s+")
    return stem + (r"\w*" if term.endswith("*") else "")


_CRITICAL_RE = re.compile(r"\b(?:" + "|".join(_term_pattern(t) for t in CRITICAL_TERMS) + r")\b", re.I)


def is_critical(a: "Ask") -> bool:
    return a.kind == "blocked" or bool(_CRITICAL_RE.search(f"{a.title}\n{a.question}\n{a.context}"))


def stage_of(reg: dict, product: str) -> str:
    return (reg["product"].get(product) or {}).get("stage") or ""


def is_parked(a: "Ask", reg: dict) -> bool:
    return stage_of(reg, a.product) == "parked"


def is_muted(a: "Ask", reg: dict) -> bool:
    """In a parked product and not critical."""
    return is_parked(a, reg) and not is_critical(a)


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


# --- questions in text ------------------------------------------------------------------------

_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_CLOSERS = "*_`)\"'”»] "


def _paragraph_asks(p: str) -> bool:
    core = p.rstrip().rstrip(_CLOSERS)
    return core.endswith(("?", "？")) or "?" in p[-250:] or "let me know" in p.lower()


_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]*_`”»]*\s+|\n\s*\n")
_FRAGMENT_START = re.compile(r"^(?:…|\.\.\.|[a-z]|[)\]}>,;:.!?\"'”»*_`-])")
IMPERATIVES = frozenset((
    "say", "tell", "ask", "run", "start", "launch", "go", "proceed", "continue", "merge", "ship", "fix", "check",
    "approve", "confirm", "reply", "send", "let", "make", "use", "add", "remove", "delete", "wait", "stop", "pick",
    "choose", "decide", "open", "try", "review", "do", "keep", "move", "push", "pull", "release", "retry"))
SHORT_WORDS = 7


def is_fragment(text) -> bool:
    """True when `text` starts mid-sentence: an ellipsis, a lowercase letter, or a closing bracket or
    punctuation mark."""
    return bool(_FRAGMENT_START.match(str(text or "").lstrip()))


def sentence_start(text: str, i: int, blank_lines: bool = True) -> int:
    """The offset of the start of the sentence that holds offset `i` in `text`: just after the last
    sentence end (and, unless `blank_lines` is False, blank line) at or before `i`, else 0."""
    start = 0
    for m in _SENTENCE_END.finditer(text, 0, i):
        if m.end() <= i and (blank_lines or text[m.start()] != "\n"):
            start = m.end()
    return start


def _next_sentence_start(text: str, i: int) -> int | None:
    m = _SENTENCE_END.search(text, i)
    return m.end() if m and m.end() < len(text) else None


def is_bare_imperative(question) -> bool:
    """A short instruction that makes no sense without its session: fewer than SHORT_WORDS words, no
    question mark, and an imperative verb or a lowercase letter first."""
    words = str(question or "").split()
    if not words or len(words) >= SHORT_WORDS or "?" in str(question):
        return False
    first = words[0].strip("…\"'*_`").lower()
    return first in IMPERATIVES or words[0][:1].islower()


def with_title_lead(title: str, question: str) -> str:
    """`<title>: <question>` for a bare imperative, else the question."""
    t = str(title or "").strip()
    q = str(question or "").strip()
    if not t or not is_bare_imperative(q) or q.lower() in t.lower():
        return q
    return f"{clip(t, TITLE_MAX).rstrip(':.')}: {q}"      # a long title must not crowd out the instruction


def trailing_question(text) -> str | None:
    """The last paragraph of an agent's final text when it asks something, else None. A question
    followed by a short list of options is returned with the list. At most TRAILING_MAX characters
    when it can be cut at a sentence start, else cut from the front so the question itself
    survives. It never starts mid-sentence: a clipped tail is backed up to the start of its
    sentence in the text (at most QUESTION_MAX characters), else moved on to the next sentence."""
    if not text or not turn_end_candidate(text):
        return None
    full = str(text).strip()
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", full, re.S)]
    paras = [(full[a:b].strip(), a) for a, b in spans if full[a:b].strip()]
    if not paras:
        return None
    last, qstart = paras[-1]
    if all(_LIST_LINE.match(l) for l in last.splitlines() if l.strip()) and len(paras) > 1:
        if not _paragraph_asks(paras[-2][0]):
            return None
        last, qstart = paras[-2][0] + "\n" + last, paras[-2][1]
    elif not _paragraph_asks(last):
        return None
    if len(full) - qstart > TRAILING_MAX:
        cut = len(full) - TRAILING_MAX
        back = sentence_start(full, cut)
        fwd = _next_sentence_start(full, cut)
        if len(full) - back <= QUESTION_MAX - 1:
            start = back
        elif fwd is not None:
            start = fwd
        else:
            return "…" + full[len(full) - (TRAILING_MAX - 1):].lstrip()
    elif is_fragment(last):                  # a paragraph that starts lowercase continues the one before
        j = sentence_start(full, qstart, blank_lines=False)
        start = j if len(full) - j <= QUESTION_MAX - 1 else qstart
    else:
        return last
    return re.sub(r"\n\s*\n", "\n", full[start:])


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


# The desktop app's metadata files run to 400 KB each (prompt snapshots), 460 of them: parsing
# all of them took 1.4 s of every run. Only these keys are ever read, so the parse is cached
# by file stamp in ~/.teyla/desktop-sessions.cache.json (private, mode 600, like asks.json).
SLIM_KEYS = ("sessionId", "cliSessionId", "cwd", "originCwd", "worktreePath", "createdAt", "lastActivityAt",
             "isArchived", "title", "model", "permissionMode", "prs", "postTurnSummary", "scheduledTaskId")
SLIM_VERSION = 2          # 2: added scheduledTaskId


def _slim_cache_path() -> pathlib.Path:
    return state.home() / "desktop-sessions.cache.json"


def _desktop_sessions(root: str) -> list[dict]:
    try:
        cache = json.loads(_slim_cache_path().read_text())
        cache = cache.get("files") if isinstance(cache, dict) and cache.get("version") == SLIM_VERSION else {}
    except (OSError, ValueError):
        cache = {}
    cache = cache if isinstance(cache, dict) else {}
    fresh: dict = {}
    out = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*", "local_*.json"))):
        try:
            st = os.stat(f)
        except OSError:
            continue
        stamp = [st.st_mtime_ns, st.st_size]
        hit = cache.get(f)
        if isinstance(hit, list) and len(hit) == 3 and hit[:2] == stamp and isinstance(hit[2], dict):
            slim = hit[2]
        else:
            try:
                d = json.loads(pathlib.Path(f).read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict):
                continue
            slim = {k: d[k] for k in SLIM_KEYS if k in d}
        fresh[f] = [*stamp, slim]
        out.append(slim)
    prefix = root.rstrip(os.sep) + os.sep
    kept = {k: v for k, v in cache.items() if not k.startswith(prefix)}
    if {k: v for k, v in cache.items() if k.startswith(prefix)} != fresh:
        try:
            _atomic_write(_slim_cache_path(), json.dumps({"version": SLIM_VERSION, "files": {**kept, **fresh}}))
        except OSError:
            pass
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
        task = str(d.get("scheduledTaskId") or "")
    else:
        when = (ana or {}).get("ts") or 0.0
        link, title, pr, archived, harness = f"claude --resume {cli_id}", "", "", False, "claude-code"
        cwd, sid, task = (ana or {}).get("cwd"), "", ""
    if when < since:
        return None
    turn = (ana or {}).get("uuid") or su
    aid = make_id("claude", cli_id, turn)
    question = with_title_lead(title, text)
    product, how, why = registry.explain(cwd, session=(cli_id, sid), ask_id=aid, pr=pr, texts=(title, text))
    return Ask(id=aid, kind=kind, product=product,
               title=clip(title or text.splitlines()[0], TITLE_MAX), question=clip(question, QUESTION_MAX),
               context=clip(context or "", CONTEXT_MAX), options=[clip(o, 80) for o in (ana or {}).get("options") or []],
               when=when, archived=archived, link=link, pr=pr, harness=harness, session=cli_id,
               attributed_by=how, evidence=why, task=task)


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
            aid = make_id("codex", r["sid"], r["turn"])
            title = titles.get(r["sid"]) or ""
            question = with_title_lead(title, r["question"])
            product, how, why = registry.explain(r["cwd"], session=r["sid"], ask_id=aid, texts=(title, r["question"]))
            out.append(Ask(id=aid, kind=r["kind"], product=product,
                           title=clip(title or r["question"].splitlines()[0], TITLE_MAX),
                           question=clip(question, QUESTION_MAX), context="",
                           options=[clip(o, 80) for o in r["options"]], when=when, archived=archived,
                           link=f"codex resume {r['sid']}", pr="", harness="codex", session=r["sid"],
                           attributed_by=how, evidence=why))
    return out


# --- Teyla's own queue ------------------------------------------------------------------------

def collect_gates() -> list[Ask]:
    out = []
    for it in state.pending_inbox():
        when = _epoch(it.get("ts")) or 0.0
        rid = str(it.get("id") or "")
        aid = make_id("gate", rid, str(it.get("ts") or ""))
        product, how, why = (registry.explain(it.get("repo"), ask_id=aid) if it.get("repo")
                             else ("teyla", "", ""))
        out.append(Ask(id=aid, kind="gate", product=product, attributed_by=how, evidence=why,
                       title=clip(it.get("routine") or "gated run", TITLE_MAX),
                       question=clip(it.get("summary") or "A gated run is waiting for approval.", QUESTION_MAX),
                       context=clip(f"gate {it.get('gate', '?')}, state {it.get('state', '?')}", CONTEXT_MAX),
                       options=["approve", "reject"], when=when, archived=False,
                       link=f"teyla inbox show {rid}", pr="", harness="teyla"))
    return out


def collect_design_cards() -> list[Ask]:
    """An open design decision card (`teyla design options`): options valid, no pick yet. It is a question
    with the options as chips, recommended first; `teyla answer` on it writes the pick."""
    from . import design_cycle
    out = []
    for c in design_cycle.open_cards():
        ref = f"{c['repo']}::{c['decision']}"
        out.append(Ask(id=make_id("design", ref, ""), kind="question", product=registry.resolve(str(c["repo"])),
                       title=clip(f"Design decision: {c['title']}", TITLE_MAX),
                       question=clip(design_cycle.card_text(c), QUESTION_MAX), context="",
                       options=design_cycle.card_chips(c), when=_now(), archived=False,
                       link="teyla answer <id> <option> <your reason>", pr="", harness=DESIGN_HARNESS, session=ref))
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
    d.setdefault("undone", {})
    return d


def save_state(st: dict, path: pathlib.Path | None = None, now: float | None = None) -> None:
    p = path or state_path()
    cut = _iso((now or _now()) - STATE_KEEP_DAYS * 86400)
    st = {"version": 1,
          "done": {k: v for k, v in st["done"].items() if str(v.get("ts", "")) >= cut},
          "snoozed": {k: v for k, v in st["snoozed"].items() if str(v.get("until", "")) >= cut},
          "undone": {k: v for k, v in st.get("undone", {}).items() if str(v.get("ts", "")) >= cut}}
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
            a.note = str(st["done"][a.id].get("note") or "")
        elif a.id in st["snoozed"] and str(st["snoozed"][a.id].get("until", "")) > _iso(now):
            a.status = "snoozed"
    return items


# --- settling: resolve by PR state, collapse duplicates, close what live state answers -----------

AUTO_PR = "auto: PR "                  # note of an ask closed because its PR was merged or closed
AUTO_DUP = "auto: duplicate of "       # note of an ask that repeats a newer one
AUTO_RUN = "auto: repeat run of "      # note of an ask left by an earlier run of the same scheduled job
AUTO_OFF = "auto: scheduled task off " # note of an ask closed because its scheduled task is off
AUTO_TF = "auto: testflight current "  # note of an ask closed because the tester can install the build
AUTO_REPORT = "auto: report"           # note of a status report that was never a question
AUTO_CHORE = "auto: same chore "       # note of an ask that repeats a newer ask for the same manual chore
COLLAPSED = (AUTO_DUP, AUTO_RUN, AUTO_CHORE)   # notes of an ask hidden under a newer one
RUN_MIN_SESSIONS = 3                   # no scheduled-task signal: this many sessions with one title are one job
TF_FRESH_S = 48 * 3600                 # the cached TestFlight read must be this young
SIMILAR_MIN_WORDS = 6                  # both questions need this many words of 3+ letters for a Jaccard match
SIMILAR_JACCARD = 0.8
_MD_MARKS = re.compile(r"[*_`]")
_WORDS = re.compile(r"[^\W\d_]{3,}")


def norm_question(text) -> str:
    """Lower case, markdown `*_` and backticks dropped, whitespace collapsed."""
    return " ".join(_MD_MARKS.sub("", str(text or "")).lower().split())


def question_words(text) -> set[str]:
    return set(_WORDS.findall(norm_question(text)))


# --- the hard floor: what only the owner may close -----------------------------------------------

_MONEY_RE = re.compile(
    r"[$€£¥₽]\s?\d|\d\s?[$€£¥₽]|\b(?:usd|eur|gbp|chf|rub)\s?\d|\d\s?(?:usd|eur|gbp|chf|dollars?|euros?|pounds?)\b"
    r"|\b(?:price|prices|pricing|billing|invoice|invoices|payment|payments|charge|charges|charged|refund|refunds"
    r"|subscription|paywall)\b", re.I)
_SECRET_RE = re.compile(
    r"\b(?:api[ -]?keys?|keys?|keychain|secrets?|passwords?|passcodes?|credentials?|tokens?|otp|2fa|private keys?"
    r"|signing certificates?)\b|\.p8\b", re.I)
_PERSON_CUE = re.compile(
    r"\b(?i:ask|tell|e-?mail|message|ping|text|call|contact|thank|cc|reply to|forward to|send(?: it)? to"
    r"|waiting (?:on|for)|approved by|signed off by|from|with)\s+@?([A-Z][a-z]{2,})\b")
_POSSESSIVE = re.compile(r"\b([A-Z][a-z]{2,})['’]s\b")
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z][\w-]{2,}")
_CAP_PAIR = re.compile(r"\b([A-Z][a-z]{2,}) ([A-Z][a-z]{2,})\b")
_NOT_NAMES = frozenset((
    "apple google play store app testflight xcode github claude codex openai anthropic android ios macos mac iphone ipad "
    "watch safari chrome gmail vercel supabase cloudflare teyla gemini grok garmin connect health healthkit siri "
    "monday tuesday wednesday thursday friday saturday sunday january february march april may june july august "
    "september october november december the this that these those there here what when where which who why how "
    "please sign tap view open build version release stage production internal external beta review store console "
    "developer account team group tester testers owner mcp api cli web").split())


_MORE_IMPERATIVES = frozenset(("sign", "log", "tap", "accept", "install", "enable", "grant", "provide", "paste", "share",
                               "create", "set", "update", "upload", "download", "visit", "click", "press", "enter",
                               "connect", "view", "give", "write", "read", "answer"))


def _imperative_first(text: str) -> bool:
    words = text.split()
    return bool(words) and words[0].strip("…\"'*_`#:-").lower() in IMPERATIVES | _MORE_IMPERATIVES


@functools.lru_cache(maxsize=4096)
def _needs_owner(title: str, body: str, known: frozenset) -> bool:
    if _MONEY_RE.search(title) or _MONEY_RE.search(body) or _SECRET_RE.search(title) or _SECRET_RE.search(body):
        return True
    stop = _NOT_NAMES | known
    for text in (title, body):
        if _HANDLE.search(text):
            return True
        for rx in (_PERSON_CUE, _POSSESSIVE):
            for m in rx.finditer(text):
                if m.group(1).lower() not in stop:
                    return True
        for m in _CAP_PAIR.finditer(text):
            first, second = m.group(1).lower(), m.group(2).lower()
            if first in stop or second in stop or first in IMPERATIVES | _MORE_IMPERATIVES:
                continue
            return True
    return False


def needs_owner(a: "Ask", known: frozenset | None = None) -> bool:
    """True when only the owner may close this ask: its text names a price or currency amount, a key, secret,
    password or credential, or another person. Rules 2 and 4 of `settle` never close such an ask, and it never
    collapses into an ask with other words. A heuristic that errs toward keeping: a capitalised pair of words
    (First Last), a cue word before a capitalised name, a possessive or an @handle counts as a person unless the
    word is a platform or product name (`known` adds the registry's)."""
    return _needs_owner(a.title, f"{a.question}\n{a.context}", frozenset(known or ()))


def _known_words(reg: dict) -> frozenset:
    words: set[str] = set()
    for pid, p in (reg.get("product") or {}).items():
        for text in (pid, (p or {}).get("name") or ""):
            words |= {w.lower() for w in re.findall(r"[A-Za-z]{3,}", str(text))}
    return frozenset(words)


def _owner_text(a: "Ask") -> str:
    return norm_question(f"{a.question}\n{a.context}")


def same_request(a: "Ask", b: "Ask", known: frozenset | None = None) -> bool:
    """One request asked twice: the same session and the same normalised question, or a token-set Jaccard
    of at least 0.8 over words of 3+ letters when both questions have at least 6 such words. Asks aimed at
    different versions never match, and an ask that `needs_owner` matches only identical text and context."""
    na, nb = norm_question(a.question), norm_question(b.question)
    if not na or not nb or target_versions(a) != target_versions(b):
        return False
    if a.session and a.session == b.session and na == nb:
        return True
    wa, wb = question_words(na), question_words(nb)
    if len(wa) < SIMILAR_MIN_WORDS or len(wb) < SIMILAR_MIN_WORDS:
        return False
    if (needs_owner(a, known) or needs_owner(b, known)) and _owner_text(a) != _owner_text(b):
        return False
    return len(wa & wb) / len(wa | wb) >= SIMILAR_JACCARD


def _auto_done(a: "Ask", st: dict, now: float, note: str) -> None:
    st["done"][a.id] = {"ts": _iso(now), "note": note}
    st["snoozed"].pop(a.id, None)
    a.status, a.note = "done", note


def _resolve_prs(items: list["Ask"], st: dict, now: float, *, fetch: bool, runner) -> bool:
    cand = [a for a in items if a.status in ("open", "snoozed") and a.pr and a.id not in st["undone"]]
    if not cand:
        return False
    from . import backlog                 # backlog imports this module
    try:
        states = backlog.pr_states([a.pr for a in cand], now, runner=runner, fetch=fetch)
    except Exception:  # noqa: BLE001 — GitHub is an extra: no gh, no network or a bad answer resolves nothing
        return False
    changed = False
    for a in cand:
        s = states.get(backlog.canonical_pr_url(a.pr))
        if s and s["state"] in ("MERGED", "CLOSED") and s["at"] > a.when:
            _auto_done(a, st, now, f"{AUTO_PR}{s['state'].lower()} {a.pr}")
            changed = True
    return changed


# --- reports are not questions -------------------------------------------------------------------

_HEADING = re.compile(r"^\s*#{1,6}\s+\S")
_BOLD_LABEL = re.compile(r"^\s*(?:\*\*|__)\s*([^*_\n]{1,60}?)\s*(?:\*\*|__)")
_REPORT_LABEL = re.compile(
    r"^\s*(?:(?:not verified|verified|results?|status|summary|findings|recap|progress|shipped|changed)\s*:"
    r"|(?:done|failed)\s*(?::|—|–|-)\s)", re.I)
_REQUEST = re.compile(
    r"\b(?:please|let me know|need you|needs you|waiting (?:on|for) you|your call|your decision|tell me|reply|approve|"
    r"confirm|sign in|log in|choose|pick|decide|tap|accept|can you|could you|do you|should i|would you|want me|shall i|"
    r"ok to|go ahead)\b", re.I)


def is_report(a: "Ask") -> bool:
    """A status report shown as a question: no question mark, no options, and the text starts with a heading, a
    bold label or a report label ("Not verified:"), or holds three bullet lines. Conservative: any request word
    ("please", "approve", "sign in"), or an imperative verb first, keeps it an ask."""
    q = str(a.question or "")
    if a.kind != "question" or a.options or "?" in q or "？" in q or not q.strip():
        return False
    lead = re.sub(r"^\s*(?:#{1,6}\s*|\*\*|__)", "", q)
    if _imperative_first(lead) or _REQUEST.search(q):
        return False
    bullets = sum(1 for line in q.splitlines() if _LIST_LINE.match(line))
    return bool(_HEADING.match(q) or _BOLD_LABEL.match(q) or _REPORT_LABEL.match(q) or bullets >= 3)


def _classify_reports(items: list["Ask"], st: dict, now: float) -> bool:
    changed = False
    for a in items:
        if a.id in st["undone"]:
            continue
        if a.status == "done" and a.note == AUTO_REPORT:
            a.kind = "report"                                # closed on an earlier run: only the label is new
        elif a.status in ("open", "snoozed") and is_report(a):
            a.kind = "report"
            _auto_done(a, st, now, AUTO_REPORT)
            changed = True
    return changed


# --- repeats: the same question, the same job -----------------------------------------------------

_VERSION = re.compile(
    r"(?:\bv|\bversion\s+|\brelease\s+|\b(?:ios|macos|android|watchos|tvos)\s+)(\d+(?:\.\d+)+)\b"
    r"|\b(\d+\.\d+\.\d+(?:\.\d+)*)\b|\b(\d+\.\d+)\s*\(\d+\)", re.I)
_BUILD = re.compile(r"\bbuilds?\s*#?\s*(\d+)\b|\b\d+(?:\.\d+)+\s*\((\d+)\)", re.I)


def target_versions(a: "Ask") -> frozenset:
    """The versions and build numbers a question names. Two runs aimed at different versions are different asks."""
    text = f"{a.title}\n{a.question}"
    out = {"v" + next(g for g in m.groups() if g) for m in _VERSION.finditer(text)}
    out |= {"b" + next(g for g in m.groups() if g) for m in _BUILD.finditer(text)}
    return frozenset(out)


def _run_groups(items: list["Ask"], known: frozenset | None = None) -> list[list["Ask"]]:
    """Asks that are one job's repeat runs: the same product, title and scheduled task (the desktop session
    names it); or, with no task named, the same product, title and harness in `RUN_MIN_SESSIONS` or more
    sessions. Split by target version, and by exact text and context when the ask `needs_owner`."""
    rows = [a for a in items if a.kind in ("question", "blocked") and a.status in ("open", "snoozed", "done")
            and a.title and not a.note.startswith(COLLAPSED)]
    base: dict[tuple, list[Ask]] = {}
    loose: dict[tuple, list[Ask]] = {}
    for a in rows:
        if a.task:
            base.setdefault(("task", a.product, a.title, a.task), []).append(a)
        elif a.harness in ("claude-desktop", "claude-code", "codex"):
            loose.setdefault(("title", a.product, a.title, a.harness), []).append(a)
    base.update({k: v for k, v in loose.items() if len({a.session for a in v if a.session}) >= RUN_MIN_SESSIONS})
    out: list[list[Ask]] = []
    for group_rows in base.values():
        split: dict[tuple, list[Ask]] = {}
        for a in group_rows:
            split.setdefault((target_versions(a), _owner_text(a) if needs_owner(a, known) else None), []).append(a)
        out += [r for r in split.values() if len(r) > 1]
    return out


def _fold(rows: list["Ask"], st: dict, now: float, note: str, same) -> bool:
    """Fold the older rows into the newest. A repeat of a done ask is done too, and that is recorded; a repeat of an
    open ask is hidden (status `duplicate`) and listed in the kept ask's `dupes`."""
    changed = False
    rows.sort(key=lambda a: (-a.when, a.id))
    gone: set[str] = set()
    for i, k in enumerate(rows):
        if k.id in gone:
            continue
        for c in rows[i + 1:]:
            if c.id in gone or c.status == "done" or c.id in st["undone"] or not same(k, c):
                continue
            gone.add(c.id)
            if k.status == "done":
                _auto_done(c, st, now, note + k.id)
                changed = True
            else:
                c.status, c.note = "duplicate", note + k.id
                k.dupes.append(c.id)
    return changed


def _collapse_runs(items: list["Ask"], st: dict, now: float, known: frozenset | None = None) -> bool:
    """Repeat runs of one job collapse into the newest, `blocked` asks included; no fuzzy match is used."""
    changed = False
    for rows in _run_groups(items, known):
        changed = _fold(rows, st, now, AUTO_RUN, lambda k, c: True) or changed
    return changed


def _collapse(items: list["Ask"], st: dict, now: float, known: frozenset | None = None) -> bool:
    """Collapse the repeats of an ask into the newest one, product by product. A repeat of an ask that is
    done is done too, and that is recorded; a repeat of an open ask is hidden (status `duplicate`) and
    listed in the kept ask's `dupes`."""
    by: dict[str, list[Ask]] = {}
    for a in items:
        if a.kind == "question" and a.status in ("open", "snoozed", "done") and not a.note.startswith(COLLAPSED):
            by.setdefault(a.product, []).append(a)
    changed = False
    for rows in by.values():
        changed = _fold(rows, st, now, AUTO_DUP, lambda k, c: same_request(k, c, known)) or changed
    return changed


def chore_key(a: "Ask", known: frozenset | None = None) -> str | None:
    """The chore a `question` or `blocked` ask is, when it may be folded into a newer ask for the same chore, else None.
    Never an ask with options, one that offers a choice, one aimed at another version, or one that `needs_owner`
    (a price, a secret, another person); never a chore whose `collapse` is False (a key, a TestFlight tap, a device)."""
    if a.kind not in ("question", "blocked") or a.options:
        return None
    key = chores.classify(a.title, a.question, len(a.options))
    if key is None or not chores.BY_KEY[key].collapse or needs_owner(a, known):
        return None
    return key


def _collapse_chores(items: list["Ask"], st: dict, now: float, known: frozenset | None = None) -> bool:
    """Asks for one manual chore ("Sign Chrome in") collapse into the newest, per product and chore key. The key is a
    rule-based classifier (`chores.py`), not a similarity: it applies to those few chores only."""
    groups: dict[tuple, list[Ask]] = {}
    for a in items:
        if a.status in ("open", "snoozed", "done") and not a.note.startswith(COLLAPSED):
            key = chore_key(a, known)
            if key:
                groups.setdefault((a.product, key, target_versions(a)), []).append(a)
    changed = False
    for (_product, key, _versions), rows in groups.items():
        if len(rows) > 1:
            changed = _fold(rows, st, now, AUTO_CHORE, lambda k, c: True) or changed
    return changed


# --- live state that already answers an ask --------------------------------------------------------

def _schedule_home() -> pathlib.Path:
    return pathlib.Path.home()            # at call time; a test moves it


def schedule_states(home: pathlib.Path | None = None) -> dict[str, str] | None:
    """{task id: on | off | once | unknown} for the Claude desktop scheduled tasks, read from the app's records and
    the definition folder (`schedules.read_claude_desktop`, local files only). `off` is a recurring task that is
    disabled; `once` a one-shot that switched itself off after it ran; `unknown` a definition with no record, which
    is also what every task looks like while the records cannot be read, so it closes nothing. None when no record
    is readable at all, so a missing or broken store never reads as "all deleted"."""
    try:
        from . import schedules
        entries = schedules.read_claude_desktop(_schedule_home() if home is None else home)
    except Exception:  # noqa: BLE001 — a store that cannot be read says nothing
        return None
    out: dict[str, str] = {}
    for e in entries:
        tid = str(e.get("id") or "").split(":", 1)[-1]
        if not tid:
            continue
        if e.get("verdict") == "UNREGISTERED":
            out[tid] = "unknown"
        elif e.get("enabled") is False:
            out[tid] = "once" if e.get("fire_at") is not None else "off"
        else:
            out[tid] = "on"
    return out if any(v != "unknown" for v in out.values()) else None


def _close_off_tasks(items: list["Ask"], st: dict, now: float, tasks: dict | None, known: frozenset) -> bool:
    """An ask from a scheduled task that is disabled, or no longer exists, is done: `auto: scheduled task off <id>`.
    A one-shot that switched itself off after running keeps its ask, and so does an ask that `needs_owner`."""
    cand = [a for a in items if a.task and a.status in ("open", "snoozed") and a.kind in ("question", "blocked")
            and a.id not in st["undone"] and not needs_owner(a, known)]
    if not cand:
        return False
    tasks = schedule_states() if tasks is None else tasks
    if not tasks:
        return False
    changed = False
    for a in cand:
        if tasks.get(a.task, "gone") in ("off", "gone"):
            _auto_done(a, st, now, AUTO_OFF + a.task)
            changed = True
    return changed


_TF_PHRASE = re.compile(r"view in testflight", re.I)
_TF_TAP = re.compile(r"\b(?:tap|taps|click|press|accept|open)\b|invit", re.I)
_TF_OTHER = re.compile(
    r"\b(?:submit|send|upload|approve|confirm|merge|ship|release|fix|add|create|enable|sign|log|pick|choose|decide|reply|"
    r"tell|retry|run|start|delete|remove|paste|enter|share|provide|grant|check|wait|please)\b", re.I)
TF_ASK_MAX = 450


def is_testflight_tap(a: "Ask") -> bool:
    """An ask that only asks the owner to tap "View in TestFlight" in Apple's e-mail: it names that button, asks no
    question, offers no options and is short."""
    q = str(a.question or "")
    return (a.kind in ("question", "blocked") and not a.options and "?" not in q and len(q) <= TF_ASK_MAX
            and bool(_TF_PHRASE.search(q)) and bool(_TF_TAP.search(q)) and not _TF_OTHER.search(q))


def _testflight_current(rows, now: float, since: float) -> bool:
    """The cached TestFlight rows of a product: at least one, every one `current`, each read after the ask was
    written and within `TF_FRESH_S`. Anything missing or unclear is False."""
    tf = [r for r in (rows or {}).values() if isinstance(r, dict) and r.get("channel") == "testflight"]
    if not tf:
        return False
    for r in tf:
        at = _epoch(r.get("as_of")) if r.get("as_of") else None
        if r.get("state") != "current" or at is None or at <= since or now - at > TF_FRESH_S:
            return False
    return True


def _close_testflight(items: list["Ask"], st: dict, now: float, stores: dict | None, known: frozenset) -> bool:
    cand = [a for a in items if a.status in ("open", "snoozed") and a.id not in st["undone"]
            and is_testflight_tap(a) and not needs_owner(a, known)]
    if not cand:
        return False
    if stores is None:
        from . import portfolio              # portfolio imports this module
        try:
            stores = portfolio.load_cache()["stores"]
        except Exception:  # noqa: BLE001
            return False
    changed = False
    for a in cand:
        if _testflight_current(stores.get(a.product), now, a.when):
            _auto_done(a, st, now, AUTO_TF + a.product)
            changed = True
    return changed


def settle(items: list["Ask"], now: float, *, st: dict | None = None, fetch: bool = False, runner=None,
           tasks: dict | None = None, stores: dict | None = None) -> None:
    """Close what is already settled, in place, by these steps in order:

    1. an ask whose PR was merged or closed after the ask is done (`auto: PR merged <url>`);
    2. a status report is not a question: kind `report`, done (`auto: report`);
    3. the repeats of a newer ask collapse into it: repeat runs of one scheduled job by identity, then near-identical
       questions by similarity (never `blocked` asks), then repeats of one manual chore ("Sign Chrome in") by the rule
       key of `chores.py` (`auto: same chore <id>`; never an ask with options, or one that `needs_owner`);
    4. an ask of a scheduled task that is off closes (`auto: scheduled task off <id>`);
    5. a request to tap "View in TestFlight" closes when the cached TestFlight data says the tester can install
       (`auto: testflight current <product>`).

    Steps 4 and 5 never touch an ask that `needs_owner`. All go through the done store, so `undo` reverses them and an
    undone ask is not touched again. `fetch` lets one batched `gh` query run for PRs the caches do not know; without
    it only caches are read. `tasks` ({id: on|off|once}) and `stores` (the portfolio cache's `stores`) are read from
    local files when not given. With `st` given the caller owns the store."""
    own = st is None
    st = load_state() if own else st
    changed = _resolve_prs(items, st, now, fetch=fetch, runner=runner)
    changed = _classify_reports(items, st, now) or changed
    known = _known_words(registry.load())
    changed = _collapse_runs(items, st, now, known) or changed
    changed = _collapse(items, st, now, known) or changed
    changed = _collapse_chores(items, st, now, known) or changed
    changed = _close_off_tasks(items, st, now, tasks, known) or changed
    changed = _close_testflight(items, st, now, stores, known) or changed
    if changed and own:
        try:
            save_state(st, now=now)
        except OSError:
            pass


REASONS = ("resolved", "duplicates", "repeat_runs", "same_chore", "scheduled_off", "testflight_current", "reports")


def filtered_by_reason(items: list["Ask"]) -> dict:
    """How many asks each automatic step took out of the list: `resolved` (PR merged or closed), `duplicates` (similar
    questions), `repeat_runs` (earlier runs of one job), `scheduled_off`, `testflight_current` and `reports`."""
    out = dict.fromkeys(REASONS, 0)
    for a in items:
        n = a.note
        if a.status == "done" and n.startswith(AUTO_PR):
            out["resolved"] += 1
        elif a.status == "duplicate" or a.status == "done":
            if n.startswith(AUTO_RUN):
                out["repeat_runs"] += 1
            elif n.startswith(AUTO_CHORE):
                out["same_chore"] += 1
            elif n.startswith(AUTO_DUP):
                out["duplicates"] += 1
            elif a.status == "done" and n.startswith(AUTO_OFF):
                out["scheduled_off"] += 1
            elif a.status == "done" and n.startswith(AUTO_TF):
                out["testflight_current"] += 1
            elif a.status == "done" and n == AUTO_REPORT:
                out["reports"] += 1
    return out


def filtered_counts(items: list["Ask"]) -> tuple[int, int]:
    """(closed because the PR is merged or closed, repeats of a newer ask: similar questions and repeat runs)."""
    r = filtered_by_reason(items)
    return r["resolved"], r["duplicates"] + r["repeat_runs"]


def filtered_line(resolved: int, dupes: int, more: dict | None = None) -> str:
    """`filtered: 3 resolved (PR merged/closed), 22 duplicates (20 repeat runs), 1 scheduled task off, ...`. `dupes`
    counts every collapsed repeat; `more` is `filtered_by_reason`'s dict, from which the other reasons are named."""
    more = more or {}
    extra = [(more.get("same_chore", 0), "same-chore repeats"), (more.get("scheduled_off", 0), "scheduled task off"), (more.get("testflight_current", 0), "TestFlight current"),
             (more.get("reports", 0), "reports")]
    if not (resolved or dupes or any(n for n, _ in extra)):
        return ""
    runs = more.get("repeat_runs", 0)
    parts = [f"{resolved} resolved (PR merged/closed)", f"{dupes} duplicates" + (f" ({runs} repeat runs)" if runs else "")]
    parts += [f"{n} {label}" for n, label in extra if n]
    return "filtered: " + ", ".join(parts) + " — teyla asks --all"


AUTO_CLOSED_WINDOW_S = 24 * 3600       # `auto_closed` looks back this far
AUTO_CLOSED_MAX = 50                   # items listed; `count` is always the full number


def auto_closed(items: list["Ask"], st: dict, now: float) -> dict:
    """What Teyla closed on its own in the last 24 hours: `{count, items: [{id, title, product, reason}]}`, newest
    first. An ask counts when its done record carries an `auto:` note and a `ts` inside the window. Anything the
    owner closed (no `auto:` note, `answer`, `accept-close`) is left out, and so is a record with no timestamp.
    A repeat that is only hidden under a newer ask (status `duplicate`) is not in the done store and is not listed."""
    rows = []
    for a in items:
        if a.status != "done" or not a.note.startswith("auto:"):
            continue
        at = _epoch((st["done"].get(a.id) or {}).get("ts"))
        if at is None or not 0 <= now - at <= AUTO_CLOSED_WINDOW_S:
            continue
        rows.append((at, {"id": a.id, "title": a.title, "product": a.product,
                          "reason": clip(a.note[len("auto:"):].strip(), 160)}))
    rows.sort(key=lambda r: (-r[0], r[1]["id"]))
    return {"count": len(rows), "items": [r for _, r in rows[:AUTO_CLOSED_MAX]]}


# --- collecting everything --------------------------------------------------------------------

def collect(days: int = DEFAULT_DAYS, now: float | None = None, desktop: str | None = None,
            projects: str | None = None, codex_root: str | None = None, codex_archive: str | None = None,
            reminders: pathlib.Path | None = None, st: dict | None = None, fetch: bool = False,
            runner=None) -> list[Ask]:
    """Every waiting item from the four sources, state applied and settled (`settle`), oldest first. Deduped
    by id. `fetch` lets the PR check ask GitHub; without it only the caches are read."""
    now = _now() if now is None else now
    since = now - days * 86400
    items = (collect_claude(since, desktop, projects) + collect_codex(since, codex_root, codex_archive)
             + collect_design_cards() + collect_gates() + collect_reminders(reminders, _dt.datetime.fromtimestamp(now).date()))
    seen, unique = set(), []
    for a in items:
        if a.id not in seen:
            seen.add(a.id)
            unique.append(a)
    apply_state(unique, load_state() if st is None else st, now)
    settle(unique, now, st=st, fetch=fetch, runner=runner)
    unique.sort(key=lambda a: (a.harness != DESIGN_HARNESS, a.when))      # an open decision card first
    return unique


def resolve(prefix: str, items: list[Ask]) -> tuple[Ask | None, str]:
    p = prefix.strip().lower()
    if len(p) < 3:
        return None, f"{prefix!r} is too short: an id needs at least 3 characters"
    hits = [a for a in items if a.id.startswith(p)]
    if not hits:
        return None, f"no item with an id starting {prefix!r} (`teyla asks --all` lists closed and hidden items too)"
    if len(hits) > 1:
        return None, f"{prefix!r} matches {len(hits)} items: " + ", ".join(a.id for a in hits)
    return hits[0], ""


def why_line(prefix: str, items: list[Ask]) -> tuple[str, int]:
    """`<id> → <product> (by <how>: <evidence>)` for one ask."""
    a, err = resolve(prefix, items)
    if a is None:
        return err, 1
    if not a.attributed_by:
        return f"{a.id} → {a.product} (fixed: not chosen by the registry)", 0
    return f"{a.id} → {a.product} (by {a.attributed_by}: {a.evidence})", 0


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


def undo(prefixes: list[str], now: float | None = None) -> tuple[list[str], int]:
    """Reopen done asks. An ask closed by Teyla (a merged PR, a repeat) is remembered as undone and is
    not closed again. Asks that were closed as repeats of the reopened one go back under it."""
    now = _now() if now is None else now
    items = collect(max(DEFAULT_DAYS, 365), now)
    st = load_state()
    lines, code, changed = [], 0, False
    was_done = set(st["done"])            # before any cascade: `undo <kept> <dupe>` must not depend on the order
    for pre in prefixes:
        a, err = resolve(pre, items)
        if a is None:
            lines.append(err)
            code = 1
            continue
        if a.id not in was_done and a.status != "duplicate":
            lines.append(f"not done: {a.id}  {a.product}  {a.title}")
            code = 1
            continue
        st["done"].pop(a.id, None)
        st["undone"][a.id] = {"ts": _iso(now)}
        for k in [k for k, v in st["done"].items() if v.get("note") in (AUTO_DUP + a.id, AUTO_RUN + a.id, AUTO_CHORE + a.id)]:
            del st["done"][k]
        lines.append(f"reopened: {a.id}  {a.product}  {a.title}")
        changed = True
    if changed:
        save_state(st, now=now)
    return lines, code


def mark_done_older(days: float, note: str = "", product: str = "", now: float | None = None) -> tuple[list[str], int]:
    """Close every open question older than `days`, in one product when given. Reminders are
    left alone: their age is the due date, not a question someone left."""
    now = _now() if now is None else now
    if days <= 0:
        return ["--older-than needs a number of days above 0"], 1
    cutoff = now - days * 86400
    # look back a year past the cutoff, so --older-than 400 still sees a 500-day-old question
    old = [a for a in collect(max(DEFAULT_DAYS, 365, int(days) + 365), now)
           if a.status == "open" and a.kind != "reminder" and a.when < cutoff
           and (not product or a.product == product)]
    if not old:
        return [f"nothing open is older than {days:g} day(s)"], 0
    st = load_state()
    for a in old:
        st["done"][a.id] = {"ts": _iso(now), **({"note": note} if note else {})}
        st["snoozed"].pop(a.id, None)
    save_state(st, now=now)
    return [f"done: {a.id}  {a.product}  {a.title}" for a in old] + [f"closed {len(old)}"], 0


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


def group(items: list[Ask], reg: dict | None = None, flat: bool = False) -> list[tuple[str, list[Ask]]]:
    """(product, asks) pairs. Focus products first, then by the oldest ask in the group, `unassigned`
    last. The asks of a group keep the order they came in (oldest first). `flat`: the old order, by the
    oldest ask alone."""
    reg = registry.load() if reg is None else reg
    by: dict[str, list[Ask]] = {}
    for a in items:
        by.setdefault(a.product, []).append(a)
    if flat:
        return sorted(by.items(), key=lambda kv: min(a.when for a in kv[1]))
    return sorted(by.items(), key=lambda kv: (not any(a.harness == DESIGN_HARNESS for a in kv[1]),
                                              kv[0] == registry.UNASSIGNED,
                                              not (reg["product"].get(kv[0]) or {}).get("focus"),
                                              min(a.when for a in kv[1])))


def display_name(reg: dict, product: str) -> str:
    return (reg["product"].get(product) or {}).get("name") or ("Unassigned" if product == registry.UNASSIGNED else product)


def group_head(reg: dict, product: str, n: int) -> str:
    stage = stage_of(reg, product)
    return f"{display_name(reg, product)}  {n} waiting" + (f"  [{stage}]" if stage else "")


def muted_line(muted: list[Ask]) -> str:
    """The one line that says what the default list left out; empty when nothing was."""
    if not muted:
        return ""
    names = sorted({a.product for a in muted})
    return f"{len(muted)} muted in parked products ({', '.join(names)}) — teyla asks --all, or teyla product wake <id>"


def _flags(a: Ask, reg: dict) -> list[str]:
    return (["archived"] if a.archived else []) + ([a.status] if a.status != "open" else []) \
        + (["parked"] if is_parked(a, reg) else []) + [a.kind]


def _ask_lines(a: Ask, now: float, reg: dict) -> list[str]:
    similar = f"  (+{len(a.dupes)} similar)" if a.dupes else ""
    lines = [f"  {a.id}  {fmt_age(now - a.when):>5}  [{', '.join(_flags(a, reg))}]  {a.title}{similar}",
             "      " + a.question.replace("\n", "\n      ")]
    if a.note:
        lines.append("      -- " + a.note)
    if a.context:
        lines.append("      -- " + a.context.replace("\n", " "))
    if a.options:
        lines.append("      options: " + " | ".join(a.options))
    lines.append(f"      open: {a.link}" + (f"    pr: {a.pr}" if a.pr else ""))
    return lines


def render_text(items: list[Ask], now: float, *, flat: bool = False, muted: list[Ask] | None = None,
                reg: dict | None = None, filtered: str = "") -> str:
    """Grouped by product with a header per product; `flat` keeps the old list, one `product (n)` header each."""
    reg = registry.load() if reg is None else reg
    lines = [header(items)]
    for product, rows in group(items, reg, flat):
        lines += ["", f"{product} ({len(rows)})" if flat else group_head(reg, product, len(rows))]
        for a in rows:
            lines += _ask_lines(a, now, reg)
    if items:
        lines += ["", "close one: teyla asks done <id>   hide for a while: teyla asks snooze <id> <days>"]
    note = muted_line(muted or [])
    if note:
        lines += ["", note]
    if filtered:
        lines += ["", filtered] if not note else [filtered]
    return "\n".join(lines)


def group_dicts(items: list[Ask], reg: dict) -> list[dict]:
    return [{"product": product, "display_name": display_name(reg, product), "stage": stage_of(reg, product),
             "focus": bool((reg["product"].get(product) or {}).get("focus")), "count": len(rows),
             "ids": [a.id for a in rows]}
            for product, rows in group(items, reg)]


def render_json(items: list[Ask], now: float, *, muted: list[Ask] | None = None, reg: dict | None = None,
                counts: tuple[int, int] = (0, 0), reasons: dict | None = None) -> str:
    reg = registry.load() if reg is None else reg
    muted = muted or []
    filtered = dict.fromkeys(REASONS, 0) if reasons is None else {k: reasons.get(k, 0) for k in REASONS}
    return json.dumps({"waiting": len(items), "archived": sum(1 for a in items if a.archived),
                       "generated": _iso(now), "items": [a.to_dict(now, attribution=True) for a in items],
                       "groups": group_dicts(items, reg),
                       "muted": len(muted), "muted_products": sorted({a.product for a in muted}),
                       "resolved": counts[0], "duplicates": counts[1], "filtered": filtered}, indent=1)


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


def render_html(items: list[Ask], now: float, *, flat: bool = False, muted: list[Ask] | None = None,
                reg: dict | None = None, filtered: str = "") -> str:
    reg = registry.load() if reg is None else reg
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
    for product, rows in group(items, reg, flat):
        parts.append(f'<h2>{_e(product)} &middot; {len(rows)}</h2>' if flat else
                     f'<h2>{_e(group_head(reg, product, len(rows)))}</h2>')
        for a in rows:
            done_cmd = f"teyla asks done {a.id}"
            parts.append('<section class="card"><div class="meta">'
                         f'<span>{_e(product)}</span><span>{_e(fmt_age(now - a.when))}</span>'
                         f'<span class="badge">{_e(a.kind)}</span>'
                         + ('<span class="badge arch">archived</span>' if a.archived else '')
                         + ('<span class="badge">parked</span>' if is_parked(a, reg) else '')
                         + (f'<span class="badge">{_e(a.status)}</span>' if a.status != "open" else '')
                         + (f'<span class="badge">+{len(a.dupes)} similar</span>' if a.dupes else '')
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
    for note in (muted_line(muted or []), filtered):
        if note:
            parts.append(f'<p class="sum">{_e(note)}</p>')
    parts.append(f'</main><script>{_JS}</script></body></html>')
    return "".join(parts)


def write_html(items: list[Ask], now: float, out: str | None = None, **kw) -> pathlib.Path:
    p = pathlib.Path(out).expanduser() if out else html_path()
    _atomic_write(p, render_html(items, now, **kw))
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
    if args.why:
        if words:
            print("--why takes one ask id and no action", file=sys.stderr)
            return 64
        line, code = why_line(args.why, collect(args.days or DEFAULT_DAYS, now))
        print(line, file=sys.stderr if code else sys.stdout)
        return code
    if words and words[0] == "done" and args.older_than is not None:
        if len(words) > 1:
            print("give ids or --older-than, not both", file=sys.stderr)
            return 64
        lines, code = mark_done_older(args.older_than, args.note or "", args.product or "", now)
        print("\n".join(lines), file=sys.stderr if code else sys.stdout)
        return code
    if words and words[0] == "done":
        if len(words) < 2:
            print("usage: teyla asks done <id-prefix>... | done --older-than DAYS [--product P]  [--note TEXT]",
                  file=sys.stderr)
            return 64
        lines, code = mark_done(words[1:], args.note or "", now)
        print("\n".join(lines))
        return code
    if words and words[0] == "undo":
        if len(words) < 2:
            print("usage: teyla asks undo <id-prefix>...", file=sys.stderr)
            return 64
        lines, code = undo(words[1:], now)
        print("\n".join(lines), file=sys.stderr if code else sys.stdout)
        return code
    if words and words[0] == "triage":
        from . import triage
        if len(words) > 1:
            print("usage: teyla asks triage [--product P] [--json]", file=sys.stderr)
            return 64
        return triage.cmd_triage(args, now)
    if words and words[0] == "accept-close":
        from . import triage
        return triage.cmd_accept_close(args, words[1:], now)
    if words and words[0] == "expire":
        from . import expiry
        return expiry.cmd_expire(args, words[1:], now)
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
        print(f"unknown action {words[0]!r}: expected done, undo, snooze, triage, accept-close or expire", file=sys.stderr)
        return 64
    days = args.days or DEFAULT_DAYS
    everything = collect(days, now, fetch=True)
    reg = registry.load()
    if not args.product and days == DEFAULT_DAYS and not args.all:
        write_count([a for a in everything if not is_muted(a, reg)])      # what the default list shows
    if args.quiet:
        return 0
    items = [a for a in everything if args.all or a.status == "open"]
    if args.product:
        items = [a for a in items if a.product == args.product]
    scope = [a for a in everything if not args.product or a.product == args.product]
    counts, reasons = filtered_counts(scope), filtered_by_reason(scope)
    filtered = "" if args.all else filtered_line(*counts, reasons)
    muted: list[Ask] = []
    if not args.all and stage_of(reg, args.product or "") != "parked":
        muted = [a for a in items if is_muted(a, reg)]
        items = [a for a in items if not is_muted(a, reg)]
    if args.html:
        p = write_html(items, now, args.out, flat=args.flat, muted=muted, reg=reg, filtered=filtered)
        print(f"{header(items)}\n{p}")
        if args.open:
            _open_file(p)
        return 0
    print(render_json(items, now, muted=muted, reg=reg, counts=counts, reasons=reasons) if args.json
          else render_text(items, now, flat=args.flat, muted=muted, reg=reg, filtered=filtered))
    return 0


def register(sp):
    q = sp.add_parser("asks", help="every question an AI session left waiting on you, in one list")
    q.set_defaults(fn=cmd_asks)
    q.add_argument("words", nargs="*", help="done <id-prefix>... | undo <id-prefix>... | snooze <id-prefix> <days> | triage | accept-close [<id-prefix>...] | expire [--apply]; none lists")
    q.add_argument("--days", type=int, help=f"look back this far (default {DEFAULT_DAYS})")
    q.add_argument("--product", help="one product (registry id); a parked product shows its muted asks")
    q.add_argument("--all", action="store_true", help="include done and snoozed items, and the asks of parked products")
    q.add_argument("--flat", action="store_true", help="one list by product, not one group per product with its stage")
    q.add_argument("--json", action="store_true")
    q.add_argument("--html", action="store_true", help="write one self-contained page (default ~/.teyla/asks.html)")
    q.add_argument("-o", "--out", help="--html: write here instead")
    q.add_argument("--open", action="store_true", help="--html: open the page")
    q.add_argument("--why", metavar="ID", help="print which rule put one ask under its product, and what it matched")
    q.add_argument("--note", help="done, expire --apply: why")
    q.add_argument("--older-than", type=float, metavar="DAYS",
                   help="done: close every open question older than this (with --product, one product); expire: the age to list (default 14)")
    q.add_argument("--apply", action="store_true", help="expire: close the candidates (default is a dry run; sends no answer)")
    q.add_argument("--quiet", action="store_true", help="only refresh ~/.teyla/asks.count (the session-start line)")
    return q
