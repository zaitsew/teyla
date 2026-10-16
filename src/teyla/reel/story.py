"""The Story: the one thing the renderer sees.

    Story  { id, harness, repo, started, ended, ask, title, beats[], totals, dropped }
    Beat   { t, kind, headline, lines[], diff? }

`build` turns a session's events plus its git history into a Story. Every string passes
`teyla.reel.redact` on the way in; nothing else (assistant prose, tool output beyond counts) is
ever taken from the transcript. Pure functions over plain data except for the git calls in
`session_repo` / `build(git=True)`.
"""
from __future__ import annotations

import collections
import dataclasses
import difflib
import os
import re
from typing import Iterable

from . import commands as cmd
from . import gitlog
from .events import Event, SessionInfo, parse_ts
from .redact import ELLIPSIS, REASONS, Redactor, cut, shorten_path
from .select import Cand, max_beats, pick

KINDS = ("ask", "lane", "edit", "test", "command", "commit", "pr", "review")
HEADLINE_MAX = 48
LINE_MAX = 34
LINES_MAX = 8
DIFF_MAX = 10
ASK_MAX = 140
ASK_WINDOW = 400
REPO_MAX = 24
TICKS_MAX = 48
MINUS = "−"
HARNESS_DIRS = {".claude", ".codex", ".agents", ".grok", ".cursor", ".teyla", ".hermes"}


class PrivateRepo(Exception):
    """The session's repo name is itself a private term (`--allow-repo` overrides)."""


@dataclasses.dataclass
class Beat:
    t: int
    kind: str
    headline: str
    lines: list = dataclasses.field(default_factory=list)
    diff: list | None = None

    def to_dict(self) -> dict:
        d = {"t": self.t, "kind": self.kind, "headline": self.headline, "lines": list(self.lines)}
        if self.diff is not None:
            d["diff"] = list(self.diff)
        return d


@dataclasses.dataclass
class Totals:
    wall_clock: int = 0          # seconds from the first record to the last
    commits: int = 0
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    tests_passed: int = 0        # as the last test run that printed counts reported them
    tests_failed: int = 0
    test_runs: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    lanes: int = 0
    cost_usd: float | None = None


@dataclasses.dataclass
class Story:
    id: str
    harness: str
    repo: str
    started: str
    ended: str
    ask: str
    title: str
    beats: list
    totals: Totals
    dropped: dict = dataclasses.field(default_factory=dict)
    # [seconds, commits, tests passed, PRs opened] samples of the whole session, for the renderer's live counters
    ticks: list = dataclasses.field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["beats"] = [b.to_dict() for b in self.beats]
        if self.totals.cost_usd is None:
            d["totals"].pop("cost_usd")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Story":
        beats = [Beat(int(b.get("t", 0)), str(b["kind"]), str(b.get("headline", "")), [str(x) for x in b.get("lines") or []],
                      [str(x) for x in b["diff"]] if b.get("diff") is not None else None) for b in d.get("beats") or []]
        tot = {f.name: (d.get("totals") or {}).get(f.name, f.default) for f in dataclasses.fields(Totals)}
        return cls(id=str(d.get("id", "")), harness=str(d.get("harness", "")), repo=str(d.get("repo", "")),
                   started=str(d.get("started", "")), ended=str(d.get("ended", "")), ask=str(d.get("ask", "")),
                   title=str(d.get("title", "")), beats=beats, totals=Totals(**tot),
                   dropped=dict(d.get("dropped") or {}), version=int(d.get("version", 1)),
                   ticks=[[int(x) for x in row] for row in d.get("ticks") or [] if len(row) == 4])

    def problems(self) -> list[str]:
        """What breaks the Story's own limits (a hand-edited story.json)."""
        out = []
        for i, b in enumerate(self.beats):
            if b.kind not in KINDS:
                out.append(f"beat {i}: unknown kind {b.kind!r}")
            if len(b.headline) > HEADLINE_MAX:
                out.append(f"beat {i}: headline over {HEADLINE_MAX} characters")
            if len(b.lines) > LINES_MAX or any(len(x) > LINE_MAX for x in b.lines):
                out.append(f"beat {i}: more than {LINES_MAX} lines or a line over {LINE_MAX} characters")
            if b.diff is not None and (len(b.diff) > DIFF_MAX or any(len(x) > LINE_MAX or x[:1] not in "+- " for x in b.diff)):
                out.append(f"beat {i}: diff over {DIFF_MAX} lines, a line over {LINE_MAX}, or a line without a +, - or space prefix")
        return out


# --- small helpers ------------------------------------------------------------------------

def wrap(text: str, width: int = LINE_MAX, max_lines: int = LINES_MAX) -> list[str]:
    """`text` as lines of at most `width` characters; a word longer than that is cut with `…`."""
    lines, cur = [], ""
    for word in text.split():
        if len(word) > width:
            word = cut(word, width)
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = cut(lines[-1] + " " + ELLIPSIS, width) if len(lines[-1]) < width else lines[-1][: width - 1] + ELLIPSIS
    return lines


def fmt_span(seconds: float) -> str:
    s = int(seconds)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}h{m:02d}" if h else f"{m}m" if m else f"{s}s"


def fmt_clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]


# --- edits --------------------------------------------------------------------------------

def edit_stats(hunks: Iterable[tuple[str, str]]) -> tuple[int, int]:
    added = removed = 0
    for old, new in hunks:
        a, b = old.split("\n") if old else [], new.split("\n") if new else []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
    return added, removed


def telling_hunk(hunks: list[tuple[str, str]], new_file: bool) -> list[str]:
    """The most changed hunk as '+', '-' or ' ' prefixed lines, at most DIFF_MAX, dedented."""
    best: list[str] = []
    best_score = -1
    for old, new in hunks:
        if new_file and not old:
            lines = [ln for ln in new.split("\n")]
            while lines and not lines[-1].strip():
                lines.pop()
            body = ["+" + ln for ln in lines[:DIFF_MAX]]
            score = len(lines)
            if score > best_score:
                best, best_score = body, score
            continue
        a, b = old.split("\n") if old else [], new.split("\n") if new else []
        chunks, cur = [], []
        for ln in difflib.unified_diff(a, b, n=1, lineterm=""):
            if ln.startswith(("---", "+++")):
                continue
            if ln.startswith("@@"):
                if cur:
                    chunks.append(cur)
                cur = []
            else:
                cur.append(ln)
        if cur:
            chunks.append(cur)
        for ch in chunks:
            score = sum(1 for ln in ch if ln[:1] in "+-")
            if score > best_score:
                best, best_score = ch[:DIFF_MAX], score
    return _dedent(best)


def _dedent(lines: list[str]) -> list[str]:
    body = [ln[0] + ln[1:].expandtabs(4) for ln in lines]
    indents = [len(ln[1:]) - len(ln[1:].lstrip(" ")) for ln in body if ln[1:].strip()]
    cut_by = min(indents) if indents else 0
    return [ln[0] + ln[1 + cut_by:] for ln in body]


# --- the build ----------------------------------------------------------------------------

class _Build:
    """One Story under construction: the redactor, the roots and the candidate beats."""

    def __init__(self, info: SessionInfo, events: list[Event], red: Redactor, git_commits, repo: str, ask: str | None):
        self.info, self.events, self.red = info, events, red
        self.git_commits = git_commits
        self.repo = repo
        self.ask_override = ask
        self.cands: list[Cand] = []
        self.totals = Totals()
        self.sha_seen: dict[str, str] = {}      # sha -> subject, commits seen in the transcript
        self.pr_titles: dict[int, str] = {}
        self.commit_t: dict[str, float] = {}    # sha -> seconds into the session, from the transcript
        self.tick_events: list[tuple[float, str, int]] = []   # (t, "test" | "pr" | "commit", value) for Story.ticks

    # redaction of one beat's strings; None when the beat must go
    def beat(self, t: float, kind: str, headline: str, lines: Iterable[str] = (), diff: list[str] | None = None) -> Beat | None:
        h = self.red.clean(headline, HEADLINE_MAX)
        if h.fatal or h.skip or not h.text:
            return None
        out = []
        for ln in lines:
            o = self.red.clean(ln, LINE_MAX)
            if o.fatal:
                return None
            if o.skip or not o.text:
                continue
            out.append(o.text)
        d = None
        if diff:
            d = []
            for ln in diff[:DIFF_MAX]:
                prefix, body = ln[0], ln[1:]
                indent = min(len(body) - len(body.lstrip(" ")), 12)
                o = self.red.clean(body.strip())
                if o.fatal:
                    return None
                if o.skip:
                    continue
                room = LINE_MAX - 1 - indent
                text = o.text
                if len(text) > room:
                    text = cut(text, room)
                    self.red.dropped["too-long"] += 1
                d.append(prefix + " " * indent + text)
            if not any(x[0] in "+-" for x in d):
                return None
        # A term can straddle two lines even though neither line holds it: check what a viewer reads.
        for joined in (" ".join([h.text, *out]), " ".join(x[1:].strip() for x in d or [])):
            if self.red.has_secret(joined) or self.red.has_term(joined):
                self.red.dropped["private-term"] += 1
                return None
        return Beat(int(t), kind, h.text, out[:LINES_MAX], d)

    def ask_beat(self) -> tuple[Beat, str]:
        ev = next((e for e in self.events if e.kind == "ask"), None)
        raw = self.ask_override if self.ask_override is not None else (ev.text if ev else "")
        window = raw.strip()
        if len(window) > ASK_WINDOW:
            window = window[:ASK_WINDOW]
            if " " in window and not raw.strip()[ASK_WINDOW].isspace():
                window = window[: window.rindex(" ")]
        # Sentence by sentence: a sentence that holds a secret, a private term or an address is
        # left out, the rest of the ask stays (the ask itself cannot be dropped).
        kept, withheld = [], False
        units = [u for u in re.split(r"(?<=[.!?])\s+|\n\s*\n", window) if u.strip()]
        if len(window) < len(raw.strip()) and len(units) > 1:
            units.pop()          # the window ended mid-sentence: a half sentence says less than none
        for unit in units:
            if not unit.strip():
                continue
            o = self.red.clean(unit)
            if o.fatal or o.skip:
                withheld = True
            elif o.text:
                kept.append(o.text)
        text = " ".join(kept)
        if not text:
            text = "(the ask is withheld by redaction; pass --ask)" if withheld else "(no ask recorded)"
        elif len(text) > ASK_MAX:
            text = cut(text, ASK_MAX)
            self.red.dropped["too-long"] += 1
        return Beat(0, "ask", "The ask", wrap(text)), text

    def _shown(self, path: str) -> bool:
        """Only files of a checkout are shown: not a scratch file, not a harness's own memory or config."""
        parts = path.split("/")
        if any(p in HARNESS_DIRS for p in parts):
            return False
        if not path.startswith(("/", "~")):
            return ".." not in parts          # a path relative to the session's working directory
        if any(path == r or path.startswith(r + "/") for r in self.red.roots):
            return True
        return any(m in path for m in ("/repos/", "/.worktrees/", "/.codex/worktrees/"))

    # -- candidates ----------------------------------------------------------------------------

    def collect(self) -> None:
        t = self.totals
        last_counts = None
        edits_added = edits_removed = 0
        edit_files: set[str] = set()
        for ev in self.events:
            if ev.kind == "agent":
                t.lanes += 1
                self.cands.append(Cand("lane", ev.t, 1, render=self._lane(ev)))
            elif ev.kind == "edit" and not ev.failed and self._shown(ev.path):
                added, removed = edit_stats(ev.hunks)
                if ev.new_file and not any(o for o, _n in ev.hunks):
                    removed = 0
                if added + removed == 0:
                    continue
                edits_added += added
                edits_removed += removed
                edit_files.add(ev.path)
                self.cands.append(Cand("edit", ev.t, added + removed, key=ev.path, render=self._edit(ev, added, removed)))
            elif ev.kind == "command":
                last_counts = self._command(ev, last_counts)
        if last_counts:
            t.tests_passed, t.tests_failed = last_counts
        self._commits(edits_added, edits_removed, edit_files)

    def _command(self, ev: Event, last_counts):
        t = self.totals
        raw = ev.text
        tool = cmd.review_tool(raw)
        if tool:
            counts = cmd.review_counts(ev.output)
            if counts:
                self.cands.append(Cand("review", ev.t, 1, render=lambda ev=ev, tool=tool, c=counts: self.beat(
                    ev.t, "review", f"{tool}: {c[0]} P1, {c[1]} P2", ["no blockers" if c[0] == 0 else "blockers found"])))
        action = cmd.pr_action(raw)
        if action and not ev.failed:
            num = cmd.pr_number(raw, ev.output)
            title = cmd.pr_title(raw) if action == "create" else cmd.pr_merge_title(ev.output)
            if action == "create":
                t.prs_opened += 1
                self.tick_events.append((ev.t, "pr", 1))
                if num and title:
                    self.pr_titles[num] = title
            else:
                t.prs_merged += 1
                title = title or self.pr_titles.get(num or 0)
            self.cands.append(Cand("pr", ev.t, 1, render=lambda ev=ev, a=action, n=num, ti=title: self._pr(ev, a, n, ti)))
        runner = cmd.test_runner(raw)
        if runner and ev.session is not None:
            pass        # the process was still running when last heard from: no verdict, so no claim either way
        elif runner and (ev.output or ev.exit_code is not None or ev.failed):
            ok, passed, failed_n = cmd.test_outcome(runner, ev.output, ev.exit_code, ev.failed)
            t.test_runs += 1
            if passed is not None or failed_n is not None:
                last_counts = (passed or 0, failed_n or 0)
                self.tick_events.append((ev.t, "test", passed or 0))
            self.cands.append(Cand("test_pass" if ok else "test_fail", ev.t, 1,
                                   render=lambda ev=ev, r=runner, ok=ok, p=passed, f=failed_n: self._test(ev, r, ok, p, f)))
        if cmd.is_commit(raw) and not ev.failed:
            for sha, subject in cmd.commits_in(ev.output):
                self.sha_seen.setdefault(sha[:7], subject)
                self.commit_t.setdefault(sha[:7], ev.t)
        elif not (tool or action or runner):
            level = cmd.notable(raw)
            if level and not ev.failed:
                self.cands.append(Cand("command", ev.t, level, render=lambda ev=ev: self.beat(
                    ev.t, "command", raw.strip().splitlines()[0] if raw.strip() else "")))
        return last_counts

    def _pr(self, ev: Event, action: str, num, title) -> Beat | None:
        """The PR title is redacted whole and wrapped afterwards: wrapped first, a term could be split
        across two lines and match neither."""
        head = (f"PR #{num} " if num else "PR ") + ("opened" if action == "create" else "merged")
        o = self.red.clean(title or "", LINE_MAX * 3)
        if o.fatal:
            return None
        return self.beat(ev.t, "pr", head, wrap(o.text, LINE_MAX, 3) if o.text else [])

    def _lane(self, ev: Event):
        def render():
            label = " · ".join(x for x in (ev.tool, ev.model) if x)
            return self.beat(ev.t, "lane", ev.text or "sub-agent", [label] if label else [])
        return render

    def _test(self, ev: Event, runner: str, ok: bool, passed, failed_n) -> Beat | None:
        if ok:
            head = f"{passed} tests passed" if passed else "Tests passed"
        elif failed_n:
            head = f"{failed_n} failed" + (f", {passed} passed" if passed else "")
        else:
            head = "Tests failed"
        return self.beat(ev.t, "test", head, [runner])

    def _edit(self, ev: Event, added: int, removed: int):
        def render():
            path = self.red.clean(ev.path)
            if path.fatal:
                return None
            diff = telling_hunk(ev.hunks, ev.new_file)
            return self.beat(ev.t, "edit", shorten_path(path.text, HEADLINE_MAX), [f"+{added} {MINUS}{removed}"], diff)
        return render

    def _commits(self, edits_added: int, edits_removed: int, edit_files: set[str]) -> None:
        t = self.totals
        by_sha: dict[str, tuple[str, float, int | None, int | None, int]] = {}
        start = parse_ts(self.info.started)
        for sha, subject in self.sha_seen.items():
            by_sha[sha] = (subject, self.commit_t.get(sha, 0.0), None, None, 0)
        files: set[str] = set()
        added = removed = 0
        for c in self.git_commits or []:
            when = max(0.0, c.at - start.timestamp()) if start else 0.0
            by_sha[c.sha] = (c.subject, when, c.added, c.removed, len(c.files))
            files.update(c.files)
            added += c.added
            removed += c.removed
        t.commits = len(by_sha)
        if self.git_commits is not None:
            t.files_changed, t.lines_added, t.lines_removed = len(files), added, removed
        else:
            t.files_changed, t.lines_added, t.lines_removed = len(edit_files), edits_added, edits_removed
        for sha, (subject, when, a, r, nfiles) in by_sha.items():
            self.tick_events.append((when, "commit", 1))

            def render(sha=sha, subject=subject, when=when, a=a, r=r, nfiles=nfiles):
                extra = [f"+{a} {MINUS}{r} · {nfiles} file" + ("s" if nfiles != 1 else "")] if a is not None else []
                return self.beat(when, "commit", subject, [sha] + extra)
            self.cands.append(Cand("commit", when, 1, render=render))


def make_ticks(tick_events: list[tuple[float, str, int]], totals: Totals) -> list[list[int]]:
    """Cumulative [t, commits, tests passed, PRs opened] after each event, thinned to TICKS_MAX rows and
    closed with the totals. Numbers only: nothing here can carry a string out of the transcript."""
    commits = tests = prs = 0
    rows = []
    for t, kind, value in sorted(tick_events):
        if kind == "commit":
            commits += 1
        elif kind == "pr":
            prs += 1
        else:
            tests = value
        rows.append([int(t), commits, tests, prs])
    if len(rows) > TICKS_MAX - 1:
        step = len(rows) / (TICKS_MAX - 1)
        rows = [rows[min(len(rows) - 1, int(i * step))] for i in range(TICKS_MAX - 1)]
    rows.append([totals.wall_clock, totals.commits, totals.tests_passed, totals.prs_opened])
    return rows


def find_repo(info: SessionInfo, events: list[Event]) -> str | None:
    """The working tree the session worked in: its cwd's, else the one its edits mostly landed in."""
    top = gitlog.toplevel(info.cwd) if info.cwd else None
    if top:
        return top
    seen = collections.Counter()
    cache: dict[str, str | None] = {}
    for ev in events:
        if ev.kind == "edit" and ev.path:
            d = os.path.dirname(ev.path)
            if d not in cache:
                cache[d] = gitlog.toplevel(ev.path)
            if cache[d]:
                seen[cache[d]] += 1
    return seen.most_common(1)[0][0] if seen else None


def roots_of(info: SessionInfo, events: list[Event], top: str | None) -> list[str]:
    roots = [r for r in (top, info.cwd) if r]
    dirs: dict[str, str | None] = {}
    for ev in events:
        if ev.kind == "edit" and ev.path:
            d = os.path.dirname(ev.path)
            if d not in dirs:
                dirs[d] = gitlog.toplevel(ev.path)
            if dirs[d]:
                roots.append(dirs[d])
            if len(dirs) > 40:
                break
    return roots


def build(info: SessionInfo, events: list[Event], *, ask: str | None = None, seconds: float = 45, git: bool = True,
          allow_repo: bool = False, red: Redactor | None = None, top: str | None = None) -> Story:
    """The Story for one session. Raises PrivateRepo when the repo's name is a private term."""
    top = top if top is not None else (find_repo(info, events) if git else None)
    red = red or Redactor(roots_of(info, events, top) if git else [info.cwd] if info.cwd else [])
    name = gitlog.repo_name(top) if top else (os.path.basename((info.cwd or "").rstrip("/")) or "session")
    if red.check_repo(name):
        if not allow_repo:
            raise PrivateRepo
        red.allow(name)
    start, end = parse_ts(info.started), parse_ts(info.ended)
    commits = gitlog.commits(top, start, end) if (git and top and start and end) else None
    b = _Build(info, events, red, commits, name, ask)
    b.collect()
    ask_beat, ask_text = b.ask_beat()
    cands = b.cands
    n = max_beats(seconds)
    ask_cand = Cand("ask", 0, render=lambda: ask_beat)
    pool = [ask_cand] + cands
    rendered: dict[int, Beat | None] = {}
    excluded: set[int] = set()
    while True:
        chosen = pick(pool, n, excluded)
        bad = False
        seen_keys: set = set()
        for c in chosen:
            if id(c) not in rendered:
                rendered[id(c)] = c.render()
            beat = rendered[id(c)]
            key = (beat.kind, beat.headline, tuple(beat.lines)) if beat else None
            if beat is None or key in seen_keys:
                excluded.add(id(c))
                bad = True
            else:
                seen_keys.add(key)
        if not bad:
            break
    beats = [rendered[id(c)] for c in chosen]
    title_src = info.title or _sentence(ask_text) or f"{name} session"
    title = red.clean(title_src, HEADLINE_MAX)
    title_text = title.text if (title.text and not title.fatal and not title.skip) else f"{name} session"
    repo_out = red.clean(name, REPO_MAX)
    dropped = {r: int(red.dropped.get(r, 0)) for r in REASONS}
    totals = b.totals
    totals.wall_clock = int((end - start).total_seconds()) if start and end else 0
    totals.cost_usd = info.cost_usd
    ticks = make_ticks(b.tick_events, totals)
    return Story(id=info.sid, harness=info.harness, repo=repo_out.text or "repo", started=info.started, ended=info.ended,
                 ask=ask_text, title=title_text, beats=beats, totals=totals, dropped=dropped, ticks=ticks)
