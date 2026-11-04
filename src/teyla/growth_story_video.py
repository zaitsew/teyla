"""The story vertical: a short video made from the best post the editor passed (docs/GROWTH.md, "The daily video").

A video channel (YouTube, Instagram, TikTok) never gets a text post, and the screen reel of a session often shows a test
run nobody can follow. A lesson with a number and an artifact already passed the editor as text. This module turns it into
a 15 to 30 second vertical with no voice and no stock footage:

    candidates(store, day)      passing lesson drafts of today and yesterday, the strongest first
    cards(hook, body, artifact) the on-screen lines: the hook first, then the body's own sentences, at most 8 words at once
    render(cards, dir, n)       1080x1920 frames drawn with Pillow (big captions on a plain dark card, a progress bar),
                                joined by ffmpeg into one silent H.264 file
    step(...)                   pick, render, frame-check and give the clip to the three video channels

Every word on screen comes from the approved text of the draft, so the leak scan that passed the draft passes the video,
and the frame check reads the finished frames back and scans them again. Nothing is published or sent. A filmed clip that
already covers the day is never replaced. No model is called.
"""
from __future__ import annotations

import math
import os
import pathlib
import re
import shutil
import sys

from . import growth as g
from . import growth_media as gm
from . import growth_rank as rank

W, H = gm.W, gm.H
FRAME_RATE = 10                    # frames drawn per second of video; ffmpeg repeats them up to 30 fps
OUT_FPS = 30
MAX_WORDS = 8                      # words on screen at once
MIN_SECONDS, MAX_SECONDS = 16.0, 28.0      # inside the frame check's 10 to 30, with a margin for the encoder
HOOK_SECONDS = 2.4
CARD_MIN, CARD_MAX = 1.8, 4.4
ARTIFACT_SECONDS = 2.8
MAX_STRETCH = 1.5
DAYS_BACK = 1
TRIES = 3
MARGIN_X = 96
BAR_Y, BAR_H = 1500, 12
BG, FG, ACCENT, TRACK, LINK = (14, 17, 22), (244, 241, 234), (242, 184, 75), (42, 49, 60), (120, 214, 190)
YOUTUBE_TITLE = 100
PASSING = ("review", "checked", "approved", "ready", "published")
FONTS = (("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0), ("/System/Library/Fonts/Helvetica.ttc", 1),
         ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0), ("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 0),
         ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 0))
UPGRADE = "uv tool install --force --python 3.12 'teyla[reel] @ git+https://github.com/zaitsew/teyla'"

_URL = re.compile(r"https?://\S+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(`])")
_ARTIFACT = re.compile(r"`(teyla [a-z][\w -]{1,40})`|\bhttps://github\.com/[\w.-]+/[\w.-]+(?:/pull/\d+)?")
_BREAK = (",", ";", ":", "—", "–")


# --- the text on screen ----------------------------------------------------------------------------------------------

def speakable(text: str) -> str:
    """The draft's words as they should be read from a screen: no links, no markdown marks, no hashtags."""
    t = _URL.sub("", str(text or ""))
    t = re.sub(r"[`*]|(?<!\w)#(?=\w)", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    return " ".join(t.split())


def sentences(text: str) -> list[str]:
    """The sentences of a draft. They are split before the markdown marks go, so a sentence that opens with a `command`
    still starts a new one."""
    raw = _URL.sub("", str(text or ""))
    return [t for t in (speakable(s) for s in _SENTENCE.split(" ".join(raw.split()))) if t]


def _split(words: list[str]) -> list[list[str]]:
    if len(words) <= MAX_WORDS:
        return [words]
    cuts = [i for i in range(3, len(words) - 2) if words[i - 1].endswith(_BREAK)]
    if cuts:
        i = min(cuts, key=lambda k: abs(k - len(words) / 2))
        return _split(words[:i]) + _split(words[i:])
    n = math.ceil(len(words) / MAX_WORDS)
    size = math.ceil(len(words) / n)
    return [words[k:k + size] for k in range(0, len(words), size)]


def chunks(sentence: str) -> list[str]:
    """A sentence in pieces of at most eight words, cut after a comma or a colon when there is one near the middle."""
    return [" ".join(c) for c in _split(sentence.split())]


def dwell(text: str) -> float:
    return min(CARD_MAX, max(CARD_MIN, 0.7 + 0.36 * len(text.split())))


def display_artifact(raw: str) -> str:
    s = raw.strip().strip("`")
    return re.sub(r"^https://(www\.)?", "", s)


def find_artifact(item: dict) -> str:
    """The command or the GitHub address a viewer can check, from the draft or its facts. "" when there is none."""
    for text in ("\n".join(item.get("facts") or []), str(item.get("first_comment") or ""), str(item.get("body") or "")):
        m = _ARTIFACT.search(text)
        if m:
            return display_artifact(m.group(1) or m.group(0))
    return ""


def cards(hook: str, body: str, artifact: str = "") -> tuple[list[dict], str]:
    """([{text, kind, seconds}], why not). The hook is the first card and shows from the first frame. The body follows
    sentence by sentence, never cut in the middle of a sentence. The total is 16 to 28 seconds."""
    hook_s, sents = speakable(hook), sentences(body)
    core = hook_s.rstrip(".!? ").lower()
    if core and sents:                                             # the body usually opens with the hook: show it once
        first = sents[0]
        if first.rstrip(".!? ").lower() == core:
            sents = sents[1:]
        elif first.lower().startswith(core):
            rest = first[len(core):].lstrip(".!?,;: ").strip()
            sents = ([rest] if rest else []) + sents[1:]
    if not hook_s and sents:
        hook_s, sents = sents[0], sents[1:]
    if not hook_s:
        return [], "the draft has no text to show"
    out = [dict(text=t, kind="hook", seconds=max(HOOK_SECONDS if k == 0 else CARD_MIN, dwell(t))) for k, t in enumerate(chunks(hook_s))]
    budget = MAX_SECONDS - (ARTIFACT_SECONDS if artifact else 0)
    total = sum(c["seconds"] for c in out)
    if total > budget:
        return [], f"the hook alone runs {total:.0f} s"
    for sent in sents:
        unit = [dict(text=t, kind="line", seconds=dwell(t)) for t in chunks(sent)]
        need = sum(c["seconds"] for c in unit)
        if total + need > budget:
            break
        out += unit
        total += need
    if artifact:
        out.append(dict(text=artifact, kind="artifact", seconds=ARTIFACT_SECONDS))
        total += ARTIFACT_SECONDS
    if total < MIN_SECONDS:                                     # too little text: hold each line a little longer, within limits
        k = min(MAX_STRETCH, MIN_SECONDS / total)
        for c in out:
            if c["kind"] != "hook":
                c["seconds"] = min(5.0, c["seconds"] * k)
        total = sum(c["seconds"] for c in out)
    if total < MIN_SECONDS:
        return [], f"the text fills {total:.0f} s; a story video runs {MIN_SECONDS:.0f} to {MAX_SECONDS:.0f} s"
    for c in out:                                               # whole frames: the video is exactly as long as the plan says
        c["seconds"] = max(1, round(c["seconds"] * FRAME_RATE)) / FRAME_RATE
    return out, ""


# --- the draft to film -----------------------------------------------------------------------------------------------

def candidates(store: g.Store, day: str) -> list[dict]:
    """Passing lesson drafts of `day` and the day before, not filmed before: the ones with a number and an artifact first,
    then the higher editor score, then the newer."""
    seen = g.refs_seen(store)
    days = {day, _days_back(day)}
    rows = []
    for it in store.items().values():
        if (it.get("platform") == g.MASTER or it.get("kind") != "post" or it.get("format") != "lesson" or it.get("language") != "en"
                or it.get("day") not in days or it["status"] not in PASSING or it.get("hold_reason")
                or not str(it.get("body") or "").strip() or f"storyvideo:{it['id']}" in seen):
            continue
        if rank.outcome(it) is not True:
            continue
        rows.append(it)
    return sorted(rows, key=lambda i: (rank.story_class(i) == "story", float((i.get("editor") or {}).get("score") or 0),
                                       i.get("day", ""), i.get("created", "")), reverse=True)


def _days_back(day: str) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(day) - dt.timedelta(days=DAYS_BACK)).isoformat()


def fit_title(hook: str, limit: int = YOUTUBE_TITLE) -> str:
    """The hook as a YouTube title: cut at a word boundary when it is longer than the platform allows."""
    h = " ".join(str(hook or "").split())
    if len(h) <= limit:
        return h
    return h[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-—–") or h[:limit]


# --- drawing ---------------------------------------------------------------------------------------------------------

def find_font():
    from PIL import ImageFont
    for path, index in FONTS:
        if os.path.isfile(path):
            return lambda pt, _p=path, _i=index: ImageFont.truetype(_p, pt, index=_i)
    return None


def wrap_lines(text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if cur and font.getlength(trial) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return lines + [cur] if cur else lines


def draw_card(card: dict, make_font):
    """The still of one card: big centred text on the dark card, and the empty progress track."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    width = W - 2 * MARGIN_X
    pt = 104
    while True:
        font = make_font(pt)
        lines = wrap_lines(card["text"], font, width)
        widest = max((font.getlength(ln) for ln in lines), default=0)
        if (len(lines) <= 5 and widest <= width) or pt <= 56:
            break
        pt -= 6
    pitch = int(pt * 1.28)
    top = 760 - pitch * len(lines) // 2
    color = ACCENT if card["kind"] == "hook" else LINK if card["kind"] == "artifact" else FG
    for k, ln in enumerate(lines):
        d.text((W // 2, top + k * pitch), ln, font=font, fill=color, anchor="mm")
    d.rounded_rectangle((MARGIN_X, BAR_Y, W - MARGIN_X, BAR_Y + BAR_H), BAR_H // 2, fill=TRACK)
    return img


def frame_plan(plan: list[dict]) -> list[int]:
    return [max(1, round(c["seconds"] * FRAME_RATE)) for c in plan]


def render(plan: list[dict], d: pathlib.Path, n: int = 1) -> tuple[pathlib.Path | None, str]:
    """The silent video for `plan` at d/story-<n>.mp4. (path, "") or (None, why)."""
    try:
        from PIL import ImageDraw
    except ImportError:
        return None, "Pillow is missing"
    make_font = find_font()
    if make_font is None:
        return None, "no bold sans-serif font found (Arial, Helvetica or DejaVu Sans)"
    counts = frame_plan(plan)
    total = sum(counts)
    fdir = d / f"story-{n}-frames"
    shutil.rmtree(fdir, ignore_errors=True)
    fdir.mkdir(mode=0o700, parents=True)
    out, part = d / f"story-{n}.mp4", d / f"story-{n}.part.mp4"
    try:
        i = 0
        left, right = MARGIN_X, W - MARGIN_X
        for card, count in zip(plan, counts):
            base = draw_card(card, make_font)
            for _ in range(count):
                i += 1
                img = base.copy()
                x = left + round((right - left) * i / total)
                ImageDraw.Draw(img).rounded_rectangle((left, BAR_Y, max(left + BAR_H, x), BAR_Y + BAR_H), BAR_H // 2, fill=ACCENT)
                img.save(fdir / f"f{i:04d}.png", compress_level=1)
        cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FRAME_RATE), "-i", str(fdir / "f%04d.png"), "-vf", f"fps={OUT_FPS},format=yuv420p",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", "-f", "mp4", str(part)]
        code, err = gm.run_tool(cmd, gm.FFMPEG_TIMEOUT_S)
    except OSError as e:
        shutil.rmtree(fdir, ignore_errors=True)
        part.unlink(missing_ok=True)
        return None, f"render failed: {type(e).__name__}"
    shutil.rmtree(fdir, ignore_errors=True)
    if code != 0 or not part.is_file():
        part.unlink(missing_ok=True)
        return None, "ffmpeg failed: " + " ".join(err.split())[-160:]
    os.replace(part, out)
    os.chmod(out, 0o600)
    return out, ""


# --- the step --------------------------------------------------------------------------------------------------------

def reel_gap() -> str:
    """"" when this machine can draw and encode a video, else the one line that says what to install."""
    real = gm.run_tool is gm._REAL_RUN_TOOL
    if shutil.which("ffmpeg") is None and real:
        return "ffmpeg is missing: `brew install ffmpeg`"
    from .reel import render as reel_render
    if not reel_render.available()["pillow"] and real:
        return f"the reel extra (Pillow) is missing, so no video is drawn: run `{UPGRADE}`"
    return ""


def step(store: g.Store, cfg: dict, now: float, *, guard: g.Guard, reg: dict, allow: bool = True) -> dict:
    """Make today's clip from the best passing lesson. Returns {state: ok|skipped|gap|held, reason, items}, like the screen
    reel's step. The caller (`growth_media.video_step`) logs the outcome as `video`."""
    day = g.day_of(now)
    targets = gm.cut_targets(cfg)

    def end(state: str, reason: str = "", **extra) -> dict:
        return dict(state=state, reason=reason, **extra)

    if not targets:
        return end("skipped", "no enabled English video channel")
    have = [t for t in targets if any(i.get("day") == day and i.get("channel") == g.channel_key(t) and i["status"] in g.GOOD_STATES
                                      and g.video_ready(i) for i in store.items().values())]
    if len(have) == len(targets):
        return end("skipped", "a clip already covers today")
    if not allow:
        return end("skipped", "safe mode")
    rows = candidates(store, day)
    if not rows:
        return end("gap", "no passing lesson draft from today or yesterday to film")
    miss = reel_gap()
    if miss:
        return end("gap", miss)
    chart_dir = g.find_chart_dir(cfg)
    why: list[str] = []
    waited = False
    for src in rows[:TRIES]:
        master = store.items().get(src.get("parent") or "") or {}
        plan, err = cards(src.get("hook", ""), src["body"], find_artifact(dict(src, facts=src.get("facts") or master.get("facts") or [])))
        if not plan:
            why.append(err)
            continue
        hits = guard.check(*[c["text"] for c in plan])
        if hits:
            why.append(f"a line would leak ({g.kinds_text(hits)})")
            continue
        if not waited:
            code, _ = gm.run_tool([sys.executable, "-m", "teyla", "load", "--wait", "--kind", "build"], gm.LOAD_WAIT_S)
            if code != 0:
                return end("gap", "the machine is busy (teyla load --wait --kind build gave up); the render waits for tomorrow")
            waited = True
        ep = g.make_item(store, now, kind="episode", format="lesson", idea=src["idea"], facts=list(src.get("facts") or []),
                         product=src.get("product", ""), sources=[dict(kind="story-video", ref=f"storyvideo:{src['id']}", url="")], owner=True,
                         scores=dict(src.get("scores") or {}), daily_video=True, story_video_of=src["id"])
        ep["status"] = "draft"
        store.save(ep, now)
        d = gm.episode_dir(store, ep)
        video, err = render(plan, d, gm.next_cut_number(d))
        if video is None:
            ep["status"], ep["reject_reason"] = "rejected", g.clip_text(err, 200)
            store.save(ep, now)
            why.append(err)
            continue
        held = gm.frame_gate(video, d, guard)
        script = " / ".join(c["text"] for c in plan)

        def reply(ch, src=src):
            hook = fit_title(src.get("hook") or src["body"]) if ch["platform"] == "youtube" else (src.get("hook") or src["body"])
            return dict(hook=hook, body=src["body"], first_comment=src.get("first_comment", ""), script=script)
        items = gm.clip_items(store, ep, targets, reply, video, held, list(src.get("facts") or []), chart_dir, guard, now, 0.0)
        for it in items:
            row = store.items().get(it["id"])
            if row is not None:
                row["story_video_of"] = src["id"]
                store.save(row, now)
        ep["status"] = "checked"
        ep["cut"] = dict(video=str(video), at=g.iso(now), segments=len(plan), footage=False, session=False, story=src["id"],
                         seconds=round(sum(c["seconds"] for c in plan), 1), **({"held": held} if held else {}))
        store.save(ep, now)
        ids = [i["id"] for i in items]
        if held:
            return end("held", held, items=ids, episode=ep["id"], video=str(video))
        waiting = [i for i in items if i["status"] == "review"]
        if not waiting:
            return end("held", "; ".join(i["reason"] for i in items if i["reason"]) or "no clip passed its checks", items=ids, episode=ep["id"],
                       video=str(video))
        return end("ok", f"{len(waiting)} clips share {video.name}, made from the lesson {src['id']}", items=ids, episode=ep["id"], video=str(video), cost=0.0)
    return end("gap", "no lesson could be filmed: " + "; ".join(sorted(set(why)))[:300])
