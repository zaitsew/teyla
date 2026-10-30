"""`teyla post` — a product's posts from its voice chart and a ship event, into a queue the owner approves.

    teyla post draft [repo] --channel x|instagram|tiktok|threads|youtube [--event "<ship event>"] [--text TEXT | --file FILE]
                     [--lang en|es|ru] [--slug S] [--dry]
    teyla post pack  [repo] [--event "<ship event>"] [--week YYYY-Www] [--channels x,instagram,threads]

`draft` writes `brand/posts/queue/<date>-<channel>-<slug>.md` (`-<lang>` is added for es and ru). The text is
`--text`, `--file`, or, in English only, a scaffold built from the event, the kit's promise and its tagline:
a starting point to rewrite, not a finished post. Every draft is checked in-process by the same code as
`teyla voice check` against `brand/voice/<lang>.md` (sentence length, banned words, emoji, hashtags,
exclamation marks, length for the format), and against the channel's own limit. A draft that fails is
printed with its findings and not written (exit 1). Video channels (tiktok, youtube) also check the first
sentence, the hook, against the chart's `video_hook_15s` limit; a YouTube title is that sentence, at most 100
characters.

`pack` writes `brand/posts/packs/<year>-W<week>.md`, the weekly flagship pack as a checklist: one reel, one
screenshot set, three posts. Items done on disk are ticked when the file is written, and a tick you made
by hand stays. Nothing here publishes anything: the owner approves and posts from the queue by hand.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from . import kit as kitmod
from . import voice

CHANNELS = ("x", "instagram", "tiktok", "threads", "youtube")
# fmt: the chart's format key for the text; limit: the channel's own limit in characters; hook: the first
# sentence is also checked as a 15 second video hook.
SPECS = {
    "x": dict(fmt="x_post", limit=280, hook=False),
    "threads": dict(fmt=None, limit=500, hook=False),
    "instagram": dict(fmt=None, limit=2200, hook=False),
    "tiktok": dict(fmt=None, limit=2200, hook=True),
    "youtube": dict(fmt=None, limit=5000, hook=True, title_limit=100),
}
QUEUE = "brand/posts/queue"
PACKS = "brand/posts/packs"
PACK_POSTS = 3

_FIRST_SENTENCE = re.compile(r"^(.+?[.!?…])(?:\s|$)", re.S)


class PostError(Exception):
    """The draft cannot be made; the message says what to fix."""


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40].strip("-")


def _sentence(s: str) -> str:
    s = " ".join(s.split())
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    return s if s[-1] in ".!?…" else s + "."


def scaffold(kit: dict, event: str, limit: int) -> str:
    """The English starting point: the event, the promise, the tagline; the tail parts go first when it is too long."""
    prod = kit.get("product") or {}
    parts = [_sentence(event), _sentence(str(prod.get("promise") or "")), _sentence(str((kit.get("tagline") or {}).get("en") or ""))]
    parts = [p for i, p in enumerate(parts) if p and p not in parts[:i]]
    while len(parts) > 1 and len(" ".join(parts)) > limit:
        parts.pop()
    return " ".join(parts)


def hook_of(text: str) -> str:
    t = " ".join(text.split())
    m = _FIRST_SENTENCE.match(t)
    return m.group(1) if m else t


def check_draft(text: str, chart: voice.Chart, channel: str, lang_warning: str | None) -> dict:
    """The voice report for the whole text, plus the channel's limit and, for video channels, the hook."""
    spec = SPECS[channel]
    rep = voice.check(text, chart, spec["fmt"], lang_warning)
    findings = list(rep["findings"])
    n = voice.post_length(text, spec["fmt"] or "")
    if n > spec["limit"]:
        findings.append(dict(level="fail", rule="length", message=f"{n} characters, {channel} allows {spec['limit']}"))
    if spec["hook"]:
        hook = hook_of(text)
        hrep = voice.check(hook, chart, "video_hook_15s")
        findings += [dict(f, rule="hook " + f["rule"], message=f["message"]) for f in hrep["findings"] if f["rule"] in ("length", "banned", "sentence")]
        if channel == "youtube" and len(hook) > spec["title_limit"]:
            findings.append(dict(level="fail", rule="title", message=f"the title (first sentence) is {len(hook)} characters, YouTube allows {spec['title_limit']}"))
    ok = not any(f["level"] == "fail" for f in findings)
    return dict(ok=ok, findings=findings, chars=n, words=rep["stats"]["words"], limit=spec["limit"], format=spec["fmt"])


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def render_post(kit: dict, channel: str, lang: str, event: str, text: str, rep: dict, chart: voice.Chart, today: str) -> str:
    spec = SPECS[channel]
    warns = [f"{f['rule']}: {f['message']}" for f in rep["findings"] if f["level"] == "warn"]
    head = ["---", f"product: {_q(str((kit.get('product') or {}).get('name') or ''))}", f"channel: {channel}", f"lang: {lang}",
            f"date: {today}", "status: draft", f"event: {_q(event)}",
            f"limit: {rep['limit']} characters" + (f", chart format {rep['format']}" if rep["format"] else ""),
            f"characters: {rep['chars']}", f"checked: pass (teyla voice check, {chart.path.name})"]
    if warns:
        head.append("warnings: [" + ", ".join(_q(w) for w in warns) + "]")
    if channel == "youtube":
        head.append(f"title: {_q(hook_of(text))}")
    head += ["---", ""]
    return "\n".join(head) + text.strip() + "\n"


def cmd_draft(args) -> int:
    try:
        repo = kitmod.resolve_repo(args.repo)
        kit = kitmod.load(repo)
        lang = args.lang
        spec = SPECS[args.channel]
        text = args.text
        if args.file:
            try:
                text = Path(args.file).expanduser().read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                raise PostError(f"cannot read {args.file}: {e}") from None
        event = " ".join((args.event or "").split())
        if not (text or "").strip():
            if not event:
                raise PostError("give --event \"<what shipped>\" for a scaffold, or --text / --file with the post")
            if lang != "en":
                raise PostError(f"a scaffold is English only: write the {lang} post from the brief and pass it with --text or --file")
            text = scaffold(kit, event, spec["limit"])
        text = text.strip()
        chart_dir = str((kit.get("voice") or {}).get("chart") or kitmod.VOICE_DIR)
        try:
            chart, warn = voice.resolve_chart(str(repo / chart_dir), lang, text)
        except voice.ChartError as e:
            raise PostError(f"voice chart: {e}") from None
    except (kitmod.KitError, PostError) as e:
        print(f"teyla post draft: {e}", file=sys.stderr)
        return 2
    rep = check_draft(text, chart, args.channel, warn)
    print(f"post draft: {args.channel}, {lang}, {rep['chars']} of {rep['limit']} characters, chart {chart.path.relative_to(repo).as_posix()}")
    for f in rep["findings"]:
        print(f"  {'FAIL' if f['level'] == 'fail' else 'warn'}  {f['rule']}: {f['message']}")
    if not rep["ok"]:
        print("not written: edit the text (--text or --file) and run it again", file=sys.stderr)
        print("\n" + text, file=sys.stderr)
        return 1
    today = _dt.date.today().isoformat()
    slug = args.slug or slugify(event) or slugify(text) or "post"
    name = f"{today}-{args.channel}-{slug}" + ("" if lang == "en" else f"-{lang}")
    out = repo / QUEUE / f"{name}.md"
    n = 2
    while out.exists():
        out = out.with_name(f"{name}-{n}.md")
        n += 1
    body = render_post(kit, args.channel, lang, event, text, rep, chart, today)
    if args.dry:
        print("\n" + body)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"wrote {out.relative_to(repo).as_posix()}  (publishing is by hand)")
    return 0


# --- the weekly pack ----------------------------------------------------------------------------------------

def week_id(day: _dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_range(wid: str) -> tuple[_dt.date, _dt.date]:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", wid)
    if not m:
        raise PostError("--week reads YYYY-Www, for example 2026-W44")
    try:
        start = _dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        raise PostError(f"{wid} is not a week") from None
    return start, start + _dt.timedelta(days=6)


def queued(repo: Path, channel: str, start: _dt.date, end: _dt.date) -> int:
    n = 0
    for p in (repo / QUEUE).glob("*.md") if (repo / QUEUE).is_dir() else []:
        m = re.match(r"(\d{4}-\d{2}-\d{2})-([a-z]+)-", p.name)
        if m and m.group(2) == channel:
            try:
                d = _dt.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            n += start <= d <= end
    return n


def last_event(repo: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pack_items(repo: Path, kit: dict, channels: list[str], event: str, start: _dt.date, end: _dt.date) -> list[dict]:
    rel = repo.name
    langs = [l for l in voice.LANGS if str((kit.get("tagline") or {}).get(l) or "").strip()] or ["en"]
    reels = [(repo / "brand" / "out" / "reel" / l / "product-vertical.mp4") for l in langs]
    shots = [(repo / "brand" / "out" / "store" / l) for l in langs]
    ev = event.replace('"', "'")
    items = [
        dict(id="reel", done=all(p.is_file() for p in reels),
             text=f"One reel, {'/'.join(langs)}: `teyla reel product {rel} --input <recording.mov> --copy <copy.json>` -> brand/out/reel/<lang>/product-vertical.mp4 and product-square.mp4"),
        dict(id="shots", done=all(p.is_dir() and any(p.rglob("*.png")) for p in shots),
             text=f"One screenshot set, {'/'.join(langs)}: `teyla kit shots {rel}` -> brand/out/store/<lang>/"),
    ]
    for i in range(1, PACK_POSTS + 1):
        ch = channels[(i - 1) % len(channels)]
        nth = sum(1 for j in range(1, i) if channels[(j - 1) % len(channels)] == ch) + 1
        items.append(dict(id=f"post:{ch}:{nth}", done=queued(repo, ch, start, end) >= nth,
                          text=f"Post {i} of {PACK_POSTS}, {ch}: `teyla post draft {rel} --channel {ch} --event \"{ev}\"` -> {QUEUE}/"))
    items.append(dict(id="approve", done=False,
                      text=f"The owner reads the reel, the screenshots and the three queued posts, then publishes by hand from {QUEUE}/ and moves each posted file out of the queue"))
    return items


def render_pack(kit: dict, wid: str, event: str, items: list[dict], kept: set[str]) -> str:
    name = str((kit.get("product") or {}).get("name") or "")
    L = [f"# Flagship pack {wid}: {name}", "",
         f"Event: {event or '(none given: pass --event)'}",
         "One reel, one screenshot set, three posts. Nothing here publishes: the owner posts by hand.", ""]
    for it in items:
        tick = "x" if it["done"] or it["id"] in kept else " "
        L.append(f"- [{tick}] {it['text']} <!-- {it['id']} -->")
    return "\n".join(L) + "\n"


def cmd_pack(args) -> int:
    try:
        repo = kitmod.resolve_repo(args.repo)
        kit = kitmod.load(repo)
        wid = args.week or week_id(_dt.date.today())
        start, end = week_range(wid)
        have = [c for c in CHANNELS if c in (kit.get("channels") or {}) and ((kit["channels"][c] or {}).get("per_week", 1) or 0) > 0]
        channels = [c.strip() for c in args.channels.split(",")] if args.channels else have
        bad = [c for c in channels if c not in CHANNELS]
        if bad or not channels:
            raise PostError("no channels: " + (", ".join(bad) + " unknown" if bad else "the kit lists none; pass --channels"))
    except (kitmod.KitError, PostError) as e:
        print(f"teyla post pack: {e}", file=sys.stderr)
        return 2
    event = " ".join((args.event or last_event(repo)).split())
    out = repo / PACKS / f"{wid}.md"
    kept = set(re.findall(r"- \[x\].*<!-- ([^>]+?) -->", out.read_text(encoding="utf-8"))) if out.is_file() else set()
    items = pack_items(repo, kit, channels, event, start, end)
    text = render_pack(kit, wid, event, items, kept)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    done = sum(1 for it in items if it["done"] or it["id"] in kept)
    print(f"wrote {out.relative_to(repo).as_posix()}  ({done} of {len(items)} done)")
    return 0


def register(sp):
    q = sp.add_parser("post", help="posts from a product's voice chart and a ship event, into a queue you approve (docs/KIT.md)",
                      description=__doc__.split("\n\n")[0])
    ps = q.add_subparsers(dest="post_cmd", required=True)

    a = ps.add_parser("draft", help="a post for one channel, checked against the voice chart, into brand/posts/queue/")
    a.set_defaults(fn=cmd_draft)
    a.add_argument("repo", nargs="?", help="a repo name under code_root or a path (default: the git root of the current directory)")
    a.add_argument("--channel", required=True, choices=CHANNELS)
    a.add_argument("--event", metavar="TEXT", help="what shipped, in a sentence")
    a.add_argument("--text", metavar="TEXT", help="the post, written by you or an agent; checked, not rewritten")
    a.add_argument("--file", metavar="FILE", help="the post, read from a file")
    a.add_argument("--lang", choices=voice.LANGS, default="en", help="the post's language (default en)")
    a.add_argument("--slug", help="the file name's last part (default: from the event)")
    a.add_argument("--dry", action="store_true", help="check and print the file; write nothing")

    b = ps.add_parser("pack", help="the weekly flagship pack as a checklist: one reel, one screenshot set, three posts")
    b.set_defaults(fn=cmd_pack)
    b.add_argument("repo", nargs="?", help="a repo name under code_root or a path (default: the git root of the current directory)")
    b.add_argument("--event", metavar="TEXT", help="what shipped (default: the last commit subject)")
    b.add_argument("--week", metavar="YYYY-Www", help="default: this week")
    b.add_argument("--channels", metavar="C,...", help="default: the kit's channels")
    return q
