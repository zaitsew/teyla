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

# Heuristic for "correction-shaped" human turns. English + Russian. Deliberately broad; the
# monitor reports it as a rate, and `teyla corrections` lets a model judge refine it.
# Adapters apply it only to turns under 800 chars: long turns are briefs, not corrections.
CORRECTION_RE = re.compile(
    r"(?<!\w)(no[,.!]|not like that|don'?t|do not|wrong|again|stop|undo|revert|actually|instead|"
    r"i said|i told|why did|you should have|never|always|shouldn'?t|"
    r"не так|нет[,.!]|не надо|неправильно|опять|снова|я же|я сказал|верни|откати|зачем)(?!\w)",
    re.I,
)

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
    batch: bool = False    # programmatic one-shot session (e.g. `grok -p` from a pipeline): counted, but its turns are not "human turns"
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
    def n_user(self) -> int:
        return len(self.user_turns)

    @property
    def n_corr(self) -> int:
        return sum(1 for u in self.user_turns if u.corr)

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


def is_noise_turn(txt: str) -> bool:
    """Harness-injected user turns that are not the human typing."""
    head = txt[:60]
    return txt.startswith("<") and any(k in head for k in (
        "system-reminder", "command-name", "local-command", "task-notification", "ci-monitor", "ide_"))


def load_all(roots: dict | None = None) -> list[Session]:
    """Load sessions from every adapter that finds its store on this machine."""
    from . import claude_code, codex, grok, hermes  # local import to keep adapters optional
    out: list[Session] = []
    for mod in (claude_code, codex, grok, hermes):
        try:
            out.extend(mod.load(**(roots or {}).get(mod.NAME, {})))
        except FileNotFoundError:
            continue
    return out
