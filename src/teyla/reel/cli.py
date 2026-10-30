"""`teyla reel list | story | check` (and `render`, see teyla.reel.render)."""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys

from . import cards
from .events import SessionInfo, discover, events_of, resolve
from .redact import REASONS, Redactor
from .story import PrivateRepo, Story, build, fmt_span


def parse_since(text: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhdw])", (text or "").strip().lower())
    if not m:
        raise ValueError(f"--since wants a number and s, m, h, d or w (24h, 7d); got {text!r}")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]


def load_story(arg: str, args) -> Story:
    """A Story from a story.json path or from a session id (prefix)."""
    import os
    if arg.endswith(".json") or os.path.isfile(arg):
        with open(arg, encoding="utf-8") as fh:
            return Story.from_dict(json.load(fh))
    info = resolve(arg)
    return build(info, events_of(info), ask=getattr(args, "ask", None), seconds=getattr(args, "seconds", 45),
                 git=not getattr(args, "no_git", False), allow_repo=getattr(args, "allow_repo", False))


def _squash(text: str) -> str:
    return " ".join(text.split())


def audit(story: Story, allow_repo: bool = False) -> int:
    """How many strings of a Story would not survive redaction as they stand: a hand-edited story.json.
    A string fails when redaction drops it or *changes* it (a URL with credentials, a home path, an
    address), and the text a viewer reads across a beat's lines is checked as well as each line."""
    red = Redactor()
    if allow_repo:
        red.allow(story.repo)
    texts = cards.rendered_strings(story) + [story.ask, story.title, story.repo, story.harness]
    for b in story.beats:
        texts.append(" ".join([b.headline, *b.lines]))
        if b.diff:
            texts.append(" ".join(x[1:].strip() for x in b.diff))
    bad = 0
    for s in texts:
        o = red.clean(s)
        if o.fatal or o.skip or _squash(o.text) != _squash(s):
            bad += 1
    return bad


def cmd_list(args) -> int:
    try:
        since = parse_since(args.since)
    except ValueError as e:
        print(f"teyla reel: {e}", file=sys.stderr)
        return 2
    rows = []
    for info in discover(since):
        if (info.batch or info.sidechain) and not args.all:
            continue
        try:
            story = build(info, events_of(info), allow_repo=True)
        except Exception as e:  # noqa: BLE001 — one unreadable transcript must not hide the rest
            print(f"teyla reel: {info.sid[:8]}: {e}", file=sys.stderr)
            continue
        if args.repo and args.repo.lower() not in story.repo.lower():
            continue
        t = story.totals
        if not args.all and t.wall_clock == 0 and not t.commits and len(story.beats) <= 1:
            continue
        rows.append((info, story))
    if not rows:
        print("no sessions in that window")
        return 0
    print(f"{'id':8}  {'harness':7}  {'repo':20}  {'started':16}  {'span':>6}  {'commits':>7}  {'PRs':>3}")
    for info, story in rows:
        started = _dt.datetime.fromisoformat(info.started.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        print(f"{info.sid[:8]:8}  {info.harness:7}  {story.repo[:20]:20}  {started:16}  {fmt_span(story.totals.wall_clock):>6}  "
              f"{story.totals.commits:>7}  {story.totals.prs_opened:>3}")
    return 0


def _story_or_exit(args) -> Story | None:
    try:
        return load_story(args.session, args)
    except PrivateRepo:
        print("teyla reel: the session's repo name is a private term; pass --allow-repo to show it", file=sys.stderr)
    except (LookupError, OSError, ValueError, KeyError) as e:
        print(f"teyla reel: {e}", file=sys.stderr)
    return None


def cmd_story(args) -> int:
    story = _story_or_exit(args)
    if story is None:
        return 2
    text = json.dumps(story.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output} ({len(story.beats)} beats)")
    else:
        sys.stdout.write(text)
    return 0


def cmd_check(args) -> int:
    story = _story_or_exit(args)
    if story is None:
        return 2
    for s in cards.rendered_strings(story):
        print(s)
    print("# dropped (counts only): " + " · ".join(f"{r} {story.dropped.get(r, 0)}" for r in REASONS))
    for p in story.problems():
        print(f"teyla reel: {p}", file=sys.stderr)
    bad = audit(story, args.allow_repo)
    if bad:
        print(f"teyla reel: {bad} string(s) in this story fail redaction now; do not render it", file=sys.stderr)
    return 1 if (bad or story.problems()) else 0


def cmd_render(args) -> int:
    from pathlib import Path
    from . import render
    story = _story_or_exit(args)
    if story is None:
        return 2
    bad = audit(story, args.allow_repo)
    if bad or story.problems():
        for p in story.problems():
            print(f"teyla reel: {p}", file=sys.stderr)
        print(f"teyla reel: {bad} string(s) fail redaction or the Story breaks its limits; not rendering", file=sys.stderr)
        return 1
    out = Path(args.output).expanduser() if args.output else render.default_dir(story)
    try:
        res = render.render_all(story, out, seconds=args.seconds, font=args.font, video=not args.no_video)
    except (RuntimeError, OSError) as e:
        print(f"teyla reel: {e}", file=sys.stderr)
        return 1
    print(f"{res.out}  ({len(story.beats)} beats, {res.seconds:.0f} s)")
    for name in res.written:
        print(f"  {name}")
    if res.missing:
        print("teyla reel: no video, missing: " + "; ".join(res.missing), file=sys.stderr)
        print("            story.json, reel.txt and reel.srt are written; install the missing piece and run again", file=sys.stderr)
        return 1
    return 0


def register(sp) -> None:
    q = sp.add_parser("reel", help="a session and its git history as a vertical terminal-story video (docs/reel.md)")
    rs = q.add_subparsers(dest="reel_cmd", required=True)

    a = rs.add_parser("list", help="sessions with repo, span, commits, PRs")
    a.set_defaults(fn=cmd_list)
    a.add_argument("--since", default="24h", help="how far back (24h, 7d; default 24h)")
    a.add_argument("--repo", metavar="NAME", help="only sessions whose repo name contains NAME")
    a.add_argument("--all", action="store_true", help="include batch (claude -p, codex exec) and sub-agent sessions")

    def common(p, *, ask=True):
        p.add_argument("session", help="a session id prefix (Claude Code or Codex) or a story.json")
        if ask:
            p.add_argument("--ask", help="the ask text to show instead of the session's first message")
        p.add_argument("--seconds", type=float, default=45, help="target length; sets how many beats are kept (default 45)")
        p.add_argument("--allow-repo", action="store_true", help="show the repo name even when it is a private term")
        p.add_argument("--no-git", action="store_true", help="do not read git history; totals come from the transcript")

    b = rs.add_parser("story", help="the redacted Story of a session, as JSON")
    b.set_defaults(fn=cmd_story)
    common(b)
    b.add_argument("-o", "--output", metavar="FILE", help="write here instead of stdout")

    c = rs.add_parser("check", help="every string that would be rendered, then what redaction dropped (counts only)")
    c.set_defaults(fn=cmd_check)
    common(c)

    d = rs.add_parser("render", help="reel.mp4, reel.srt, story.json, reel.txt and contact.png (needs teyla[reel] and ffmpeg)")
    d.set_defaults(fn=cmd_render)
    common(d)
    d.add_argument("-o", "--output", metavar="DIR", help="output directory (default ~/Movies/teyla-reel/<date>-<repo>-<id>/)")
    d.add_argument("--font", metavar="PATH", help="a monospace font file instead of Menlo / DejaVu Sans Mono")
    d.add_argument("--no-video", action="store_true", help="skip reel.mp4 (contact.png and the text files only)")

    from . import product
    product.add_arguments(rs)
