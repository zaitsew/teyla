"""Grok CLI adapter: $GROK_HOME/sessions/<urlencoded-cwd>/<session-uuid>/... (GROK_HOME defaults
to ~/.grok).

Layout, one directory per cwd the CLI was ever run from (its path is that cwd, percent-encoded),
containing:
  prompt_history.jsonl   -- flat, append-only log of every prompt typed in *any* session under
                             this cwd: {timestamp, session_id, prompt, is_bash}. This is the
                             cleanest source of "what did the human actually type" — no injected
                             system/environment turns to filter out.
  <session-uuid>/         -- one directory per session: summary.json (id, cwd, created_at,
                             updated_at, current_model_id, git info), signals.json (per-session
                             counters: modelsUsed, toolCallCount, compactionCount, ...), and
                             chat_history.jsonl (full transcript incl. tool_calls).
  session_search.sqlite   -- an FTS index over session content, no usage/token data. Not read here.

A newer layout also seen on disk drops the urlencoded-cwd container: a session directory sits
directly under the sessions root, named by a hash rather than an encoded path, and carries a
`.cwd` file instead of leaning on its parent directory's name for the cwd. Both layouts are
handled here; a `.cwd` file, when present, always wins over a name-derived guess.

Token counts and cost are not in summary.json, signals.json or chat_history.jsonl, so
`Session.usage` is left empty rather than guessing from `contextTokensUsed` (a context-window
snapshot, not cumulative spend). They are in updates.jsonl: every `turn_completed` record carries
`params.update.usage` (inputTokens, cachedReadTokens, outputTokens, modelCalls, costUsdTicks, ...).
`session_costs()` below reads those, on a fast path of its own — it never opens chat_history.jsonl
or walks the directory — and `teyla grok-cost` reports from it. Tool-call names come from `chat_history.jsonl`'s assistant `tool_calls`,
which is the only place they're broken out by name.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import urllib.parse
from typing import Iterator

from . import AgentCall, Session, Turn, human_text, is_correction, stale

NAME = "grok"
GROK_HOME = os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok")
DEFAULT_ROOT = os.path.join(GROK_HOME, "sessions")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_SID_RE = re.compile(r'"session_id"\s*:\s*"([^"]+)"')
_NON_INTERACTIVE_RE = re.compile(rb'"is_non_interactive"\s*:\s*(true|false)')


def _load_json(path: str) -> dict:
    try:
        with open(path, errors="replace") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _prompts_by_session(prompt_history: str, wanted: set | None = None) -> dict:
    """{session_id: [(timestamp, prompt), ...]} from a cwd's prompt log. With `wanted`, lines of
    other sessions are skipped on a substring test, before any JSON is decoded: a pipeline's log
    runs to ten thousand lines, and a report window needs a handful of them."""
    by_sid: dict = {}
    if not os.path.isfile(prompt_history):
        return by_sid
    with open(prompt_history, errors="replace") as fh:
        for line in fh:
            if wanted is not None:
                m = _SID_RE.search(line)
                if m is None or m.group(1) not in wanted:
                    continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            sid = o.get("session_id")
            if not sid:
                continue
            by_sid.setdefault(sid, []).append((o.get("timestamp"), o.get("prompt") or ""))
    return by_sid


def _assistant_records(chat: str):
    """The assistant records of a chat_history.jsonl. They are a small share of its bytes — the
    system prompt, injected context and tool output are most of it — so the file is searched in
    bytes for the word and only the lines holding it are decoded, instead of decoding them all."""
    try:
        with open(chat, "rb") as fh:
            data = fh.read()
    except OSError:
        return
    i = data.find(b'"assistant"')
    while i != -1:
        start = data.rfind(b"\n", 0, i) + 1
        end = data.find(b"\n", i)
        if end == -1:
            end = len(data)
        try:
            o = json.loads(data[start:end].decode("utf-8", "replace"))
        except Exception:
            o = None
        if isinstance(o, dict) and o.get("type") == "assistant":
            yield o
        i = data.find(b'"assistant"', end)


def _dir_size(path: str) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        total += _dir_size(e.path)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _is_session_dir(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "summary.json")) or os.path.isfile(
        os.path.join(path, "chat_history.jsonl"))


def _cwd_from_dotfile(path: str) -> str | None:
    fp = os.path.join(path, ".cwd")
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, errors="replace") as fh:
            v = fh.read().strip()
        return v or None
    except OSError:
        return None


def _stale_session(path: str, since: float | None) -> bool:
    """summary.json is written when the session starts and rewritten as it runs, and carries
    `created_at` — so its mtime bounds the session's first timestamp from above. Without it,
    the transcript or the directory itself stands in."""
    if since is None:
        return False
    for name in ("summary.json", "chat_history.jsonl", ""):
        try:
            return stale(os.stat(os.path.join(path, name) if name else path).st_mtime, since)
        except OSError:
            continue
    return True


def load(root: str | None = None, since: float | None = None, **kw) -> list[Session]:
    root = root or DEFAULT_ROOT  # at call time, so tests and callers that move DEFAULT_ROOT are obeyed
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    sessions = []
    for entry in sorted(os.listdir(root)):
        entry_path = os.path.join(root, entry)
        if not os.path.isdir(entry_path):
            continue  # session_search.sqlite and friends

        if _is_session_dir(entry_path):
            # Newer layout: a hash-named session dir lives directly under root, cwd comes from
            # its own .cwd file (the dir name itself isn't a decodable path).
            if _stale_session(entry_path, since):
                continue
            cwd_guess = _cwd_from_dotfile(entry_path) or urllib.parse.unquote(entry)
            s = parse(entry_path, entry, cwd_guess, [])
            if s is not None:
                sessions.append(s)
            continue

        # A cwd container gains a subdirectory for every session started under it, so its own
        # mtime is at least the start of its newest session: older than the window, nothing in
        # it can be in the window — not even its prompt log, which is read only for kept sessions.
        try:
            if stale(os.stat(entry_path).st_mtime, since):
                continue
        except OSError:
            continue
        cwd_guess = urllib.parse.unquote(entry)
        subs = []
        for sub in sorted(os.listdir(entry_path)):
            subpath = os.path.join(entry_path, sub)
            if os.path.isdir(subpath) and not _stale_session(subpath, since):
                subs.append((sub, subpath))
        if not subs:
            continue
        prompts_by_sid = _prompts_by_session(os.path.join(entry_path, "prompt_history.jsonl"),
                                             {sub for sub, _ in subs})
        for sub, subpath in subs:
            sub_cwd_guess = _cwd_from_dotfile(subpath) or cwd_guess
            s = parse(subpath, sub, sub_cwd_guess, prompts_by_sid.get(sub, []))
            if s is not None:
                sessions.append(s)
    return sessions


def parse(subpath: str, sid: str, cwd_guess: str, prompts: list) -> Session | None:
    summary = _load_json(os.path.join(subpath, "summary.json"))
    signals = _load_json(os.path.join(subpath, "signals.json"))
    info = summary.get("info") or {}
    cwd = info.get("cwd") or cwd_guess

    s = Session(harness=NAME, project=cwd, sid=sid, path=subpath, size=_dir_size(subpath))
    s.cwd = cwd
    s.compactions = signals.get("compactionCount") or 0

    model = signals.get("primaryModelId") or summary.get("current_model_id")
    for m in (signals.get("modelsUsed") or ([model] if model else [])):
        s.models[m] += 1

    # Timestamps come from three places that don't agree: summary.json's created_at/updated_at/
    # last_active_at, any timestamp fields signals.json carries, and the prompt log. Taking the
    # min/max across all of them (rather than letting the last prompt processed clobber s.last)
    # avoids a spurious zero-duration session when the human's last typed prompt lands well
    # before the assistant's final tool call.
    ts_candidates = [v for src in (summary, signals) for v in src.values()
                      if isinstance(v, str) and _TS_RE.match(v)]

    for o in _assistant_records(os.path.join(subpath, "chat_history.jsonl")):
        s.assistant_turns += 1
        for tc in o.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name")
            if not name:
                continue
            s.tools[name] += 1
            if name == "spawn_subagent":
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except Exception:
                    args = {}
                s.agents.append(AgentCall(None, "grok-subagent", args.get("description")))

    for ts, prompt in sorted(prompts, key=lambda p: p[0] or ""):
        txt = human_text((prompt or "").strip())
        if not txt:
            continue
        s.user_turns.append(Turn(ts, txt[:1500], is_correction(txt)))
        if ts:
            ts_candidates.append(ts)

    if ts_candidates:
        s.first = min(ts_candidates)
        s.last = max(ts_candidates)

    if not s.first:
        return None
    s.batch = _is_batch(subpath, signals, len(s.user_turns))
    return s


def _is_batch(subpath: str, signals: dict, n_prompts: int) -> bool:
    """A `grok -p` call (a pipeline, or a Claude session consulting Grok) rather than a human at
    the keyboard. prompt_context.json records it directly (`is_non_interactive`); without that
    file, a session with at most one prompt is taken as batch. monitor.py counts batch sessions
    and their tools but never their prompts as human turns."""
    m = None
    try:
        # ~20 KB of prompt context with the flag near its end: scan the tail, then the whole file.
        with open(os.path.join(subpath, "prompt_context.json"), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 2048))
            m = _NON_INTERACTIVE_RE.search(fh.read())
            if m is None and size > 2048:
                fh.seek(0)
                m = _NON_INTERACTIVE_RE.search(fh.read())
    except OSError:
        pass
    if m:
        return m.group(1) == b"true"
    return max(n_prompts, signals.get("userMessageCount") or 0) <= 1


# ---------------------------------------------------------------------------
# Cost: what a session (or a week of them) billed at list price
# ---------------------------------------------------------------------------

TICKS_PER_USD = 1e10  # costUsdTicks; checked against grok's own total_cost_usd

_TURN_DONE = b'"turn_completed"'
_TURN_USAGE = b'"usage"'


@dataclasses.dataclass
class SessionCost:
    sid: str
    path: str
    cwd: str
    created: str            # summary.json created_at, ISO-8601
    title: str = ""
    model: str = ""
    effort: str = ""
    usd: float = 0.0        # list price, from costUsdTicks
    calls: int = 0          # model calls
    turns: int = 0          # turn_completed records that carried usage
    input: int = 0          # inputTokens as grok reports it (cached reads included)
    cached: int = 0
    output: int = 0
    reasoning: int = 0
    tool_calls: int = 0
    context: int = 0        # contextTokensUsed: the context window at the end of the session
    compactions: int = 0
    prs: int = 0

    @property
    def cached_pct(self) -> float:
        return min(100.0, 100.0 * self.cached / self.input) if self.input else 0.0

    @property
    def day(self) -> str:
        return self.created[:10]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["cached_pct"] = round(self.cached_pct, 1)
        d["usd"] = round(self.usd, 4)
        return d


def read_usage(subpath: str) -> dict:
    """Sum the `usage` of every `turn_completed` record in a session's updates.jsonl. Streamed in
    bytes: a long session's file is megabytes of streamed chunks, and the two byte-string tests
    keep json.loads for the few lines that carry a total. A turn that ended in an API error has no
    usage block and adds nothing. Only the top-level block is summed — `modelUsage` inside it
    repeats the same numbers per model."""
    tot = dict(ticks=0, calls=0, turns=0, input=0, cached=0, output=0, reasoning=0)
    try:
        fh = open(os.path.join(subpath, "updates.jsonl"), "rb")
    except OSError:
        return tot
    with fh:
        for line in fh:
            if _TURN_DONE not in line or _TURN_USAGE not in line:
                continue
            try:
                u = json.loads(line)["params"]["update"]["usage"]
            except Exception:
                continue
            if not isinstance(u, dict):
                continue
            tot["turns"] += 1
            tot["ticks"] += u.get("costUsdTicks") or 0
            tot["calls"] += u.get("modelCalls") or 0
            tot["input"] += u.get("inputTokens") or 0
            tot["cached"] += u.get("cachedReadTokens") or 0
            tot["output"] += u.get("outputTokens") or 0
            tot["reasoning"] += u.get("reasoningTokens") or 0
    return tot


def cwd_under(cwd: str, base: str) -> bool:
    """`cwd` is `base` or a path below it."""
    base = base.rstrip("/") or "/"
    return cwd.rstrip("/") == base or cwd.startswith(base.rstrip("/") + "/")


def _candidates(root: str, since: float | None, cwd: str | None, sid_prefix: str | None) -> Iterator[tuple]:
    """(path, sid, cwd guess, summary mtime) for each session directory that might match. The
    filters here are stats and names only: in a store of fourteen thousand sessions the week you
    want is a few hundred, and a summary.json is opened only for those."""
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    for entry in os.listdir(root):
        ep = os.path.join(root, entry)
        if not os.path.isdir(ep):
            continue
        if _is_session_dir(ep):  # newer layout: a session directly under the root
            guess = _cwd_from_dotfile(ep) or urllib.parse.unquote(entry)
            if sid_prefix and not entry.startswith(sid_prefix):
                continue
            yield ep, entry, guess, _mtime(os.path.join(ep, "summary.json"))
            continue
        guess = urllib.parse.unquote(entry)
        if cwd and not cwd_under(guess, cwd):
            continue
        if since is not None and not sid_prefix and stale(_mtime(ep), since):
            continue
        try:
            subs = os.listdir(ep)
        except OSError:
            continue
        for sub in subs:
            if sid_prefix and not sub.startswith(sid_prefix):
                continue
            sp = os.path.join(ep, sub)
            if not os.path.isdir(sp):
                continue
            mt = _mtime(os.path.join(sp, "summary.json"))
            if since is not None and not sid_prefix and stale(mt, since):
                continue
            yield sp, sub, _cwd_from_dotfile(sp) or guess, mt


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _cost_of(path: str, sid: str, cwd_guess: str) -> SessionCost | None:
    summary = _load_json(os.path.join(path, "summary.json"))
    created = summary.get("created_at")
    if not isinstance(created, str):
        return None
    signals = _load_json(os.path.join(path, "signals.json"))
    u = read_usage(path)
    return SessionCost(
        sid=sid, path=path, cwd=(summary.get("info") or {}).get("cwd") or cwd_guess, created=created,
        title=(summary.get("generated_title") or summary.get("session_summary") or "").strip(),
        model=summary.get("current_model_id") or signals.get("primaryModelId") or "",
        effort=summary.get("reasoning_effort") or "",
        usd=u["ticks"] / TICKS_PER_USD, calls=u["calls"], turns=u["turns"], input=u["input"],
        cached=u["cached"], output=u["output"], reasoning=u["reasoning"],
        tool_calls=signals.get("toolCallCount") or 0, context=signals.get("contextTokensUsed") or 0,
        compactions=signals.get("compactionCount") or 0, prs=signals.get("prCreatedCount") or 0)


def session_costs(root: str | None = None, since: float | None = None, cwd: str | None = None,
                  session: str | None = None, last: bool = False) -> list[SessionCost]:
    """Cost rows for sessions created at or after `since` (a POSIX timestamp), under `cwd`, or whose
    id starts with `session`. With `last`, only the most recently written session that matches.
    Sessions that never billed (an API error, a probe) are returned with zero cost; callers that
    aggregate skip them."""
    cands = _candidates(root or DEFAULT_ROOT, since, cwd, session)
    if last:
        cands = sorted(cands, key=lambda c: -c[3])
    out = []
    for path, sid, guess, _mt in cands:
        c = _cost_of(path, sid, guess)
        if c is None:
            continue
        if since is not None and _epoch(c.created) < since:
            continue
        if cwd and not cwd_under(c.cwd, cwd):
            continue
        out.append(c)
        if last:
            break
    return out


def _epoch(iso: str) -> float:
    import datetime as _dt
    try:
        return _dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
