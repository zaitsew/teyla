"""`teyla prose` — how long and how padded the agent's replies are (the policy section "Writing and reporting", register a).

For every Claude Code and Codex session in the window, the final text of each turn the human
saw: the agent's last text before a human reply, and the session's last text. Subagent and
headless (batch) sessions are skipped, as in `teyla monitor`: nobody reads their replies.

Per harness and per project it reports:

- count, median and 90th-percentile words per reply, and the share over 150 words
- the share of sentences over 25 words (the policy's limit for a description)
- ban-list hits per 1,000 words, and the five phrases hit most (`BAN_LIST`, one constant)
- the share of replies that open with a preamble ("Let me", "I'll", "Great", "Sure", "Okay")

Fenced code blocks and table rows do not count as words or sentences: the policy limits prose,
and a diff pasted into a reply is not padding. Words are counted in any script; the ban list and
the preamble list are English only. One advice line per finding above a threshold, and only for
a group with at least `MIN_REPLIES` replies.

    teyla prose [--days 7] [--project SUBSTR] [--json]
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import statistics
from collections import Counter

# The policy's ban list (templates/POLICY.md, "Writing and reporting"). English only; matched case-insensitively on
# word boundaries, so "leverage" also catches "leverages" and "leveraged".
BAN_LIST = (
    "delve", "comprehensive", "robust", "seamless", "leverage", "cutting-edge", "game-changer",
    "dive into", "it's important to note", "it is important to note", "i hope this helps",
    "great question", "in today's", "let me know if you have any", "feel free to",
)
# What a reply must not open with: a preamble delays the answer (the policy: answer first).
PREAMBLES = ("let me", "i'll", "i will", "great", "sure", "okay", "ok", "certainly", "absolutely")

REPLY_WORDS_TARGET = 150     # a reply over this is "long"; the median should stay under it
SENTENCE_WORDS_MAX = 25      # the policy's limit for a description
MIN_REPLIES = 10             # advice needs this many replies in the group
LONG_SHARE_MAX = 0.25        # advice when more than this share of replies is over the target
LONG_SENTENCE_SHARE_MAX = 0.20
BAN_PER_1000_MAX = 1.0
PREAMBLE_SHARE_MAX = 0.15
HARNESSES = ("claude-code", "codex")
TOP_PROJECTS = 12
MIN_PROJECT_REPLIES = 5

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_WORD = re.compile(r"\w+(?:['’-]\w+)*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_MARKUP_LEAD = re.compile(r"^\s*(?:[-*+>]+|\d+[.)]|#+)\s*")
_APOS = str.maketrans({"’": "'", "‘": "'"})


def _ban_pattern(phrase: str) -> re.Pattern:
    """Word-boundary match for a phrase; a one-word phrase ending in "e" also matches its -es, -ed and -ing forms."""
    if " " not in phrase and phrase.endswith("e"):
        body = re.escape(phrase[:-1]) + r"(?:e|es|ed|ing)"
    else:
        body = re.escape(phrase).replace(r"\ ", r"\s+") + r"s?"
    return re.compile(r"(?<!\w)" + body + r"(?!\w)")


_BAN_RES = [(p, _ban_pattern(p)) for p in BAN_LIST]
_PREAMBLE_RES = [re.compile(r"^" + re.escape(p).replace(r"\ ", r"\s+") + r"(?![\w'])") for p in PREAMBLES]


def _prose_lines(text: str) -> list[str]:
    """The reply minus fenced code, table rows and bare rules, as paragraphs: a wrapped line joins
    the one before it; a blank line, a bullet, a heading or a numbered item starts a new one."""
    out: list[str] = []
    joinable = False
    for line in _FENCE.sub("\n", text).splitlines():
        s = line.strip()
        if not s or s.startswith("|") or re.fullmatch(r"[-*_=]{3,}", s):
            joinable = False
            continue
        lead = _MARKUP_LEAD.match(s)
        body = _MARKUP_LEAD.sub("", s)
        if joinable and not lead:
            out[-1] += " " + body
        else:
            out.append(body)
        joinable = not s.startswith("#")
    return out


def measure(text: str) -> dict:
    """The numbers for one reply: words, sentence word counts, ban hits, whether it opens with a preamble."""
    lines = _prose_lines(text)
    body = "\n".join(lines)
    words = len(_WORD.findall(body))
    sentences = [len(_WORD.findall(s)) for s in _SENTENCE_SPLIT.split(body) if _WORD.search(s)]
    low = body.lower().translate(_APOS)
    bans = Counter()
    for phrase, rx in _BAN_RES:
        n = len(rx.findall(low))
        if n:
            bans[phrase] += n
    first = low.lstrip(" \t\"'*_`>#-")[:40]
    return dict(words=words, sentences=sentences, bans=bans,
                preamble=any(rx.match(first) for rx in _PREAMBLE_RES))


def collect(sessions, cutoff_ts: str | None = None, project: str | None = None) -> list[dict]:
    """One row per final reply: harness, project, and its `measure`. Subagent and batch sessions,
    and replies written before `cutoff_ts` (an ISO UTC timestamp), are skipped."""
    from .grokcost import project_of
    rows = []
    for s in sessions:
        if s.sidechain or s.batch or s.harness not in HARNESSES:
            continue
        proj = project_of(s.cwd or s.project)
        if project and project.lower() not in proj.lower():
            continue
        for ts, text in getattr(s, "finals", ()):
            if cutoff_ts and (ts or "")[:19] < cutoff_ts[:19]:
                continue
            m = measure(text)
            if m["words"]:
                rows.append(dict(harness=s.harness, project=proj, **m))
    return rows


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return float(v[min(len(v) - 1, int(round(q * (len(v) - 1))))])


def summarize(rows: list[dict]) -> dict:
    """Aggregate numbers for a group of replies."""
    n = len(rows)
    words = [r["words"] for r in rows]
    total_words = sum(words)
    sentences = [w for r in rows for w in r["sentences"]]
    bans = Counter()
    for r in rows:
        bans.update(r["bans"])
    return dict(
        replies=n,
        median_words=round(statistics.median(words)) if n else 0,
        p90_words=round(_pct(words, 0.9)),
        over_150=round(sum(w > REPLY_WORDS_TARGET for w in words) / n, 3) if n else 0.0,
        long_sentences=round(sum(w > SENTENCE_WORDS_MAX for w in sentences) / len(sentences), 3) if sentences else 0.0,
        ban_per_1000=round(1000 * sum(bans.values()) / total_words, 2) if total_words else 0.0,
        top_bans=bans.most_common(5),
        preamble=round(sum(r["preamble"] for r in rows) / n, 3) if n else 0.0,
    )


def advice(label: str, s: dict) -> list[str]:
    """One line per finding above its threshold. Silent for a group too small to judge."""
    if s["replies"] < MIN_REPLIES:
        return []
    out = []
    if s["median_words"] > REPLY_WORDS_TARGET or s["over_150"] > LONG_SHARE_MAX:
        out.append(f"{label} replies: median {s['median_words']} words, {s['over_150']:.0%} over {REPLY_WORDS_TARGET}"
                   f" — the policy card is 12 lines; put detail in the PR or a file")
    if s["long_sentences"] > LONG_SENTENCE_SHARE_MAX:
        out.append(f"{label} replies: {s['long_sentences']:.0%} of sentences run over {SENTENCE_WORDS_MAX} words"
                   f" — one idea per sentence")
    if s["ban_per_1000"] > BAN_PER_1000_MAX:
        top = ", ".join(f'"{p}"' for p, _ in s["top_bans"][:3])
        out.append(f"{label} replies: {s['ban_per_1000']} ban-list hits per 1,000 words ({top}) — see the ban list in the policy")
    if s["preamble"] > PREAMBLE_SHARE_MAX:
        out.append(f"{label} replies: {s['preamble']:.0%} open with a preamble — start with the answer")
    return out


def report(days: int | None = 7, project: str | None = None, sessions=None,
           now: _dt.datetime | None = None) -> dict:
    from .adapters import load_all, since_epoch
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = (now - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S") if days else None
    if sessions is None:
        sessions = load_all(since=since_epoch(days))
    rows = collect(sessions, cutoff, project)
    by_harness = {h: [r for r in rows if r["harness"] == h] for h in HARNESSES}
    harness_rows = {h: summarize(v) for h, v in by_harness.items() if v}
    projects = Counter((r["harness"], r["project"]) for r in rows)
    project_rows = []
    for (h, p), n in projects.most_common():
        if n < MIN_PROJECT_REPLIES or len(project_rows) >= TOP_PROJECTS:
            continue
        project_rows.append(dict(harness=h, project=p, **summarize([r for r in rows if (r["harness"], r["project"]) == (h, p)])))
    lines = []
    for h, s in harness_rows.items():
        lines += advice("Claude" if h == "claude-code" else "Codex", s)
    return dict(days=days, project=project, replies=len(rows), overall=summarize(rows), harnesses=harness_rows,
                projects=project_rows, advice=lines, target_words=REPLY_WORDS_TARGET)


def render(rep: dict) -> str:
    where = f" in projects matching {rep['project']!r}" if rep["project"] else ""
    L = [f"teyla prose — {rep['replies']} final replies{where}, last {rep['days']} days "
         f"(target: median <= {rep['target_words']} words)", ""]
    if not rep["replies"]:
        return "\n".join(L + ["no replies in the window"])
    head = f"{'':<24} {'replies':>7} {'median':>6} {'p90':>5} {'>150w':>6} {'sent>25':>8} {'bans/1k':>8} {'preamble':>9}"

    def row(name, s):
        return (f"{name[:24]:<24} {s['replies']:>7} {s['median_words']:>6} {s['p90_words']:>5} {s['over_150']:>6.0%} "
                f"{s['long_sentences']:>8.0%} {s['ban_per_1000']:>8.1f} {s['preamble']:>9.0%}")
    L.append(head)
    for h, s in rep["harnesses"].items():
        L.append(row(h, s))
    if rep["projects"]:
        L += ["", "by project (5+ replies):"]
        L += [row(f"{p['project']} ({'cc' if p['harness'] == 'claude-code' else 'cx'})", p) for p in rep["projects"]]
    bans = Counter()
    for s in rep["harnesses"].values():
        bans.update(dict(s["top_bans"]))
    if bans:
        L += ["", "top ban-list phrases: " + ", ".join(f'"{p}" x{n}' for p, n in bans.most_common(5))]
    L.append("")
    L += rep["advice"] or ["nothing above its threshold"]
    return "\n".join(L)


def digest_candidates(days: int = 7) -> list[dict]:
    """One digest line when the week's median reply is over the target. Reads the transcripts,
    so the weekly digest calls it once; any failure means no line."""
    try:
        rep = report(days)
    except Exception:  # noqa: BLE001 — a metric must never stop the digest being written
        return []
    if rep["replies"] < MIN_REPLIES:
        return []
    median = rep["overall"]["median_words"]
    if median <= REPLY_WORDS_TARGET:
        return []
    return [dict(rank=5, id="prose:reply-length", text=f"reply length: median {median} words (target <= {REPLY_WORDS_TARGET})",
                 step="teyla prose", cmd=True)]


def cmd_prose(args) -> int:
    rep = report(args.days, args.project)
    if args.json:
        rep = dict(rep, harnesses={h: dict(s, top_bans=dict(s["top_bans"])) for h, s in rep["harnesses"].items()},
                   projects=[dict(p, top_bans=dict(p["top_bans"])) for p in rep["projects"]])
        print(json.dumps(rep, indent=1))
    else:
        print(render(rep))
    return 0


def register(sp):
    q = sp.add_parser("prose", help="how long and how padded the agent's final replies are: words, long sentences, ban-list hits, preambles")
    q.set_defaults(fn=cmd_prose)
    q.add_argument("--days", type=int, default=7, help="window by message time (default 7)")
    q.add_argument("--project", metavar="SUBSTR", help="only projects whose name contains SUBSTR")
    q.add_argument("--json", action="store_true")
    return q
