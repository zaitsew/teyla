"""Harness adapters. Each adapter turns a harness's local session store into Session objects.

A Session is harness-neutral: tokens by model, tool counts, subagent calls, the human turns,
and a few shape signals (compactions, duration). Adapters never send anything anywhere; they read
files on this machine.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import re
from collections import Counter, defaultdict
from typing import Iterable

# "Correction-shaped": the human pushing back on work already produced. English + Russian, a
# heuristic, tuned for precision over recall. The 0.11 pattern matched any "don't", "never",
# "always", "instead", "actually", "again", "зачем" or "снова": over 2026-09-01..29 it flagged
# "I don't mind", "don't worry", "use X instead", "Any tools I can use instead?", "run again
# with OpenAI", "Зачем мне нужен gbrain?" and 17× "Try again", and it missed the two
# corrections that mattered that month — "You use too much GitHub actions" (no keyword) and
# "don’t use GitHub actions at all" (a typographic apostrophe). A missed correction costs one
# data point; a false one teaches the owner to ignore the rate, so each branch below needs
# either an unambiguous word ("wrong", "revert", "не так") or a shape that is pushback and not
# an instruction: "don't X at all/anymore" is a correction, "don't forget to deploy" is not.
# Turns of 800+ characters are briefs, never corrections (`is_correction`).
CORRECTION_RE = re.compile(
    r"(?:^|[.!?;\n]\s*)(?:no|nope|нет)\s*[,.!—–-]"                                 # "No, I mean…" as a reply
    r"|\b(?:wrong|incorrect|not like (?:that|this)|not what i (?:asked|wanted|meant|said)|(?:don't|do not) do (?:that|this|it))\b"
    r"|\b(?:revert|undo|roll ?back)\b"
    r"|\bi (?:said|told you|already (?:said|told|asked)|meant|asked (?:you )?(?:to|for|not))\b"
    r"|\bi (?:didn't|did not|haven't|have not|never) (?:ask|asked|say|said|want|wanted)\b"
    r"|\bwhy (?:did|are|have|would|were) you\b"
    r"|(?<!do )(?<!did )(?<!can )\byou (?:should have|shouldn't have|forgot|missed|broke|ignored|keep|kept|still|again|didn't|did not)\b"
    r"|\byou (?:use|used|do|did|add|added|make|made|run|ran|spend|spent) (?:too|so) (?:much|many)\b"
    r"|\b(?:don't|do not|stop|never)\b[^.!?\n]{0,60}\b(?:at all|anymore|any more|ever again)\b"
    r"|(?:^|[.!?;\n]\s*)(?:stop|never) (?:using|doing|adding|creating|asking|use|do|add|create|ask|run|push|merge|touch|change)\b"
    r"|\bi (?:don't|do not) like\b"
    r"|\b(?:doesn't|don't|does not|do not|isn't|is not) work(?:ing)?\b|\b(?:still )?broken\b"
    r"|\b(?:again|still)\b[^.!?\n]{0,20}(?:\bnot\b|n't\b|\bwrong\b|\bfail|\bbroken\b)"
    r"|не так\b|(?:это|совсем) не то\b|неправильно|неверно|ошибся|ошиблась|я же (?:говорил|сказал|просил|писал)|"
    r"я (?:сказал|говорил|просил)|не надо|не нужно было|верни|откати|зачем ты|сделай сам|"
    r"опять[^.!?\n]{0,40}(?:\bне\b|ничего|ошиб|слома)|ты (?:снова|опять)|"
    r"ты не (?:заметил|сделал|понял|учёл|учел|прочитал|проверил|то)|(?<!не )\bзря\b|перестань",
    re.I,
)

TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")

# Typographic apostrophes a Mac and a phone type by default; the patterns spell them ASCII.
_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u2032": "'"})

# A retry is the human re-sending after an API error, not a correction and not a new turn.
# "proceed", "go on" and "keep going" are left out on purpose: after a plan they are a
# decision, not a re-send.
# 17 of 126 correction-shaped turns in 2026-09-01..29 were a bare "Try again" after
# "API Error: Can't reach the API server", and A9's "repeats 13×" was that phrase.
RETRY_RE = re.compile(
    r"^(?:please[, ]+)?(?:try again|retry|try it again|again|continue|"
    r"продолжай|продолжи|ещё раз|еще раз|повтори|попробуй (?:ещё|еще) раз)(?:[\s,.!…]+(?:please|пожалуйста))?[\s.!…]*$",
    re.I,
)
_RETRY_HEAD_RE = re.compile(r"^(?:please[, ]+)?(?:try again|retry|again|continue|ещё раз|еще раз|повтори)\b", re.I)
_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def is_retry(txt: str, after_error: bool = False) -> bool:
    """A bare retry ("Try again", "continue", "ещё раз"), or — right after an API error — a short
    turn that opens with one ("Try again - the connector is back")."""
    t = (txt or "").strip().translate(_QUOTES)
    if RETRY_RE.match(t):
        return True
    return after_error and len(t) < 120 and bool(_RETRY_HEAD_RE.match(t))


def is_correction(txt: str) -> bool:
    """The one correction test: every adapter and the capture hook call it."""
    t = (txt or "").translate(_QUOTES)
    if len(t) >= 800 or is_retry(t):
        return False
    return bool(CORRECTION_RE.search(t))
TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


@dataclasses.dataclass
class Turn:
    ts: str | None
    text: str
    corr: bool


@dataclasses.dataclass
class AgentCall:
    model: str | None  # None = inherited the parent model
    kind: str | None
    desc: str | None


@dataclasses.dataclass
class Session:
    harness: str
    project: str            # harness-specific project key (Claude: slug; Codex: cwd)
    sid: str
    path: str
    size: int = 0
    first: str | None = None
    last: str | None = None
    cwd: str | None = None
    title: str | None = None
    sidechain: bool = False
    models: Counter = dataclasses.field(default_factory=Counter)
    usage: dict = dataclasses.field(default_factory=lambda: defaultdict(Counter))  # model -> Counter(TOKEN_KEYS)
    tools: Counter = dataclasses.field(default_factory=Counter)
    skills: Counter = dataclasses.field(default_factory=Counter)
    agents: list = dataclasses.field(default_factory=list)
    user_turns: list = dataclasses.field(default_factory=list)
    assistant_turns: int = 0
    compactions: int = 0
    active_hours: float = 0.0  # sum of gaps ≤ 30 min between consecutive assistant/user record
                                # timestamps; distinguishes busy sessions from ones merely resumed
                                # over a long wall-clock span (see `hours`)
    pr_links: int = 0
    repos: Counter = dataclasses.field(default_factory=Counter)
    gov_edits: int = 0     # tool calls that touched the global instructions file (~/.claude/CLAUDE.md)
    batch: bool = False    # non-interactive session (`claude -p`, `codex exec`, `grok -p` from a pipeline or
                           # another agent): counted, but its prompts are machine-written, not human turns
    connector_calls: list = dataclasses.field(default_factory=list)  # [{server, tool, turn_index, result}] for every mcp__ tool call
    skills_read: Counter = dataclasses.field(default_factory=Counter)  # skill dir name -> Read-tool_use hits on its SKILL.md

    # ---- derived ----
    @property
    def hours(self) -> float | None:
        try:
            a = _dt.datetime.fromisoformat(self.first.replace("Z", "+00:00"))
            b = _dt.datetime.fromisoformat(self.last.replace("Z", "+00:00"))
            return round((b - a).total_seconds() / 3600, 2)
        except Exception:
            return None

    @property
    def tokens(self) -> Counter:
        t = Counter()
        for u in self.usage.values():
            t.update(u)
        return t

    @property
    def n_prompts(self) -> int:
        """Every prompt the session received, human or machine-written."""
        return len(self.user_turns)

    @property
    def n_user(self) -> int:
        """Human turns. A batch session has none: its prompt came from a script or another agent."""
        return 0 if self.batch else len(self.user_turns)

    @property
    def n_corr(self) -> int:
        return 0 if self.batch else sum(1 for u in self.user_turns if u.corr)

    @property
    def first_prompt(self) -> str:
        return self.user_turns[0].text[:400] if self.user_turns else ""

    @property
    def day(self) -> str:
        return (self.first or "")[:10]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["usage"] = {m: dict(c) for m, c in self.usage.items()}
        d["models"] = dict(self.models); d["tools"] = dict(self.tools); d["skills"] = dict(self.skills); d["repos"] = dict(self.repos)
        d["skills_read"] = dict(self.skills_read)
        d["hours"] = self.hours; d["tokens"] = dict(self.tokens); d["n_user"] = self.n_user; d["n_corr"] = self.n_corr
        d["first_prompt"] = self.first_prompt
        return d


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "\n".join(parts)


# Harness-injected user turns that are not the human typing: tags the harness wraps around
# tool output and events, plus the bare-text shapes Claude Code files as user turns (an
# interrupted request; the summary that opens a continued session; a background-task
# notice; a comment relayed from an Artifact page). The plugin's capture-correction hook
# calls this same function — a subagent's "done, but…" notification was 35 of 35 captured
# "corrections" in one repo before it did, and artifact relays were 8 of 107 records in
# 2026-09's correction files.
NOISE_TAGS = ("system-reminder", "command-name", "command-message", "local-command", "task-notification",
              "ci-monitor", "ide_", "artifact-view-context")
NOISE_PREFIXES = ("[Request interrupted", "This session is being continued from a previous conversation",
                  "[SYSTEM NOTIFICATION", "[Artifact comment sent to Claude]")


def is_noise_turn(txt: str) -> bool:
    """Harness-injected user turns that are not the human typing."""
    txt = txt.lstrip()
    head = txt[:60]
    if txt.startswith("<") and any(k in head for k in NOISE_TAGS):
        return True
    return txt.startswith(NOISE_PREFIXES)


def human_text(txt: str, after_error: bool = False) -> str | None:
    """What the human typed in a user turn, or None when there is nothing: a harness-injected
    turn, a turn that is only `<system-reminder>` blocks, or a retry. A reminder appended to a
    real prompt is cut off, not allowed to decide the turn."""
    if not txt or is_noise_turn(txt):
        return None
    t = _REMINDER_RE.sub("", txt).strip()
    if not t or is_noise_turn(t) or is_retry(t, after_error):
        return None
    return t


# A report window (`--days N`) keeps sessions whose first timestamp is inside it. A file or
# directory last written before the window opened cannot hold such a session, so adapters skip
# it on a stat alone, before reading a byte. The slack absorbs clock and timezone skew between a
# record's timestamp and the filesystem's mtime; pruning must never drop an in-window session.
PRUNE_SLACK_S = 6 * 3600


def since_epoch(days: int | None) -> float | None:
    """The window's opening as a POSIX timestamp, or None for "all time"."""
    if not days:
        return None
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).timestamp()


def stale(mtime: float, since: float | None) -> bool:
    """True when something last written at `mtime` is certainly older than the window."""
    return since is not None and mtime < since - PRUNE_SLACK_S


def load_all(roots: dict | None = None, since: float | None = None) -> list[Session]:
    """Load sessions from every adapter that finds its store on this machine. `since` (a POSIX
    timestamp, see `since_epoch`) lets adapters skip files that cannot hold a session starting
    inside the window; callers still filter on `Session.first`."""
    from . import claude_code, codex, grok, hermes, cursor  # local import to keep adapters optional
    out: list[Session] = []
    for mod in (claude_code, codex, grok, hermes, cursor):
        try:
            out.extend(mod.load(since=since, **(roots or {}).get(mod.NAME, {})))
        except FileNotFoundError:
            continue
    return out
