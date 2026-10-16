"""Pacing and layout of a reel as pure functions: no Pillow, no ffmpeg, no files.

`plan` turns a Story into the list of segments (title card, one per beat, end card) with their
frame counts and the session clock each one covers. `card_layout` says where each row of a card
goes. `captions` builds `reel.srt`. `render.py` only draws what these functions describe, so the
timing and the placement are testable without a video.
"""
from __future__ import annotations

import dataclasses
import re

from .story import Story

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 160, 320
MARGIN = 40
ADVANCE = 0.602            # advance width / font size of Menlo and DejaVu Sans Mono
TITLE_S, END_S = 2.5, 3.0
SLIDE_FRAMES = 6
BEAT_MIN_S, BEAT_MAX_S = 2.0, 4.0

# Vertical bands, top to bottom (all inside the safe area).
BAR_Y = SAFE_TOP + 10               # top bar baseline box
CARD_TOP = SAFE_TOP + 120           # kind label
CARD_BOTTOM = H - SAFE_BOTTOM - 170  # lowest pixel a card row may reach
PROGRESS_Y = H - SAFE_BOTTOM - 120
COUNTERS_Y = H - SAFE_BOTTOM - 80

LINE_PT, HEAD_BIG_PT, HEAD_PT, LABEL_PT = 48, 72, 64, 40
LINE_PT_SMALL = 40


def cols(pt: int) -> int:
    """How many monospace characters fit between the margins at this font size."""
    return int((W - 2 * MARGIN) / (pt * ADVANCE))


def beat_seconds(lines: int, has_diff: bool) -> float:
    """Reading time of a beat before it is scaled to the reel length."""
    return min(BEAT_MAX_S, max(BEAT_MIN_S, 2.0 + 0.3 * min(lines, 6) + (1.2 if has_diff else 0.0)))


# --- text fitting ---------------------------------------------------------------------------

def _split_token(token: str, width: int) -> list[str]:
    """A token longer than `width`, broken after `/` where it can be, else after `_ -`, else after `.`,
    else at the width. The break must leave a head longer than a third of the line."""
    out = []
    while len(token) > width:
        window = token[:width]
        cut = width
        for seps in ("/", "_-", "."):
            ends = [m.end() for m in re.finditer("[" + re.escape(seps) + "]", window)]
            if ends and ends[-1] > width // 3:
                cut = ends[-1]
                break
        out.append(token[:cut])
        token = token[cut:]
    return out + [token]


def wrap_text(text: str, width: int) -> list[str]:
    """Greedy word wrap; tokens wider than the line are broken (never cut: every character is drawn)."""
    lines, cur = [], ""
    for word in text.split():
        for part in _split_token(word, width):
            if cur and len(cur) + 1 + len(part) > width:
                lines.append(cur)
                cur = part
            else:
                cur = f"{cur} {part}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_headline(text: str) -> tuple[int, list[str]]:
    """(font size, wrapped lines): 72 px when the headline fits one line, else 64 px over up to 3."""
    if len(text) <= cols(HEAD_BIG_PT):
        return HEAD_BIG_PT, [text]
    return HEAD_PT, wrap_text(text, cols(HEAD_PT))


@dataclasses.dataclass
class Row:
    text: str
    y: int
    pt: int
    role: str                 # label | headline | line | diff
    tint: str | None = None   # diff rows: "add" | "del" | None


def body_pt(lines: list[str], diff: bool) -> int:
    """Font size of the body rows: 48 px, or up to 60 px when the lines are short enough to take it."""
    if diff or not lines or len(lines) > 6:
        return LINE_PT
    longest = max(len(x) for x in lines)
    return max(LINE_PT, min(60, int((W - 2 * MARGIN) / (ADVANCE * max(longest, 1)))))


def card_layout(kind: str, headline: str, lines: list[str], diff: list[str] | None) -> list[Row]:
    """Every row of a beat card with its top y. The block sits in the card band, a little above its
    middle; body rows shrink to 40 px when 48 px would run past the band."""
    pt, head_lines = fit_headline(headline)
    pitch = int(pt * 1.22)
    body = [(x, "line") for x in lines] + [(x, "diff") for x in diff or []]
    size = body_pt(lines, bool(diff))
    step = int(size * 1.33)
    top_h = 90 + len(head_lines) * pitch + 36
    band = CARD_BOTTOM - CARD_TOP
    if body and top_h + len(body) * step > band:
        size, step = LINE_PT_SMALL, 54
        if top_h + len(body) * step > band:
            step = max(40, (band - top_h) // len(body))
    height = top_h + len(body) * step
    y0 = CARD_TOP + max(0, int((band - height) * 0.35))
    rows = [Row(kind.upper(), y0, LABEL_PT, "label")]
    y = y0 + 90
    for h in head_lines:
        rows.append(Row(h, y, pt, "headline"))
        y += pitch
    y += 36
    for text, role in body:
        tint = None
        if role == "diff":
            tint = "add" if text.startswith("+") else "del" if text.startswith(("-", "\u2212")) else None
        rows.append(Row(text, y, size, role, tint))
        y += step
    return rows


def center_rows(texts: list[str], pt: int, pitch: int, top: int, bottom: int) -> list[tuple[str, int]]:
    """(text, y) for rows centred vertically in a band."""
    total = len(texts) * pitch
    y = top + max(0, (bottom - top - total) // 2)
    return [(t, y + i * pitch) for i, t in enumerate(texts)]


# --- pacing ---------------------------------------------------------------------------------

@dataclasses.dataclass
class Segment:
    kind: str            # title | beat | end
    index: int           # beat index (beats only)
    start: int           # first frame
    frames: int
    clock_from: float    # session seconds shown at the first frame
    clock_to: float      # session seconds shown after the last frame


def plan(story: Story, seconds: float = 45) -> list[Segment]:
    """The reel's segments. Title and end cards keep their length; the beats share what is left of
    `seconds`, each in proportion to its reading time, and the clock between two beats runs linearly."""
    wall = max(1, story.totals.wall_clock)
    n = len(story.beats)
    avail = max(1.0, seconds - TITLE_S - END_S)
    want = [beat_seconds(len(b.lines), bool(b.diff)) for b in story.beats]
    scale = avail / sum(want) if want else 1.0
    # Beats are never stretched past their own reading time, only squeezed to fit.
    scale = min(scale, 1.0)
    durations = [max(1.0, w * scale) for w in want]

    segs: list[Segment] = []
    cursor = 0.0

    def add(kind: str, index: int, dur: float, c0: float, c1: float) -> None:
        nonlocal cursor
        start = round(cursor * FPS)
        cursor += dur
        end = round(cursor * FPS)
        segs.append(Segment(kind, index, start, max(1, end - start), c0, c1))

    add("title", -1, TITLE_S, 0, 0)
    for i, b in enumerate(story.beats):
        nxt = story.beats[i + 1].t if i + 1 < n else wall
        add("beat", i, durations[i], min(b.t, wall), min(max(nxt, b.t), wall))
    add("end", -1, END_S, wall, wall)
    return segs


def total_frames(segs: list[Segment]) -> int:
    return segs[-1].start + segs[-1].frames if segs else 0


def clock_at(seg: Segment, frame: int) -> float:
    """Session time at `frame` (counted from the segment's first frame)."""
    if seg.frames <= 1:
        return seg.clock_from
    return seg.clock_from + (seg.clock_to - seg.clock_from) * min(1.0, frame / (seg.frames - 1))


def effective_ticks(story: Story) -> list[list[int]]:
    """Story.ticks, or, for a story.json made before ticks existed, counted from the beats."""
    if story.ticks:
        return story.ticks
    rows, commits, tests, prs = [], 0, 0, 0
    for b in story.beats:
        if b.kind == "commit":
            commits += 1
        elif b.kind == "pr" and "opened" in b.headline:
            prs += 1
        elif b.kind == "test":
            m = re.match(r"(\d+) tests passed", b.headline)
            tests = int(m.group(1)) if m else tests
        else:
            continue
        rows.append([b.t, commits, tests, prs])
    t = story.totals
    return rows + [[t.wall_clock, t.commits, t.tests_passed, t.prs_opened]]


def counters_at(story: Story, t: float) -> tuple[int, int, int]:
    """(commits, tests passed, PRs opened) as of session time `t`, from Story.ticks."""
    best = (0, 0, 0)
    for row in effective_ticks(story):
        if row[0] <= t:
            best = (row[1], row[2], row[3])
        else:
            break
    return best


def progress(story: Story, t: float) -> float:
    return max(0.0, min(1.0, t / max(1, story.totals.wall_clock)))


def slide(frame: int) -> tuple[float, int]:
    """(alpha 0..1, dy px) of a card `frame` frames after it appeared: eased over SLIDE_FRAMES."""
    if frame >= SLIDE_FRAMES:
        return 1.0, 0
    p = (frame + 1) / (SLIDE_FRAMES + 1)
    e = 1 - (1 - p) ** 3
    return e, int(round(60 * (1 - e)))


def keyframes(segs: list[Segment], count: int = 9) -> list[tuple[int, int]]:
    """(segment index, frame within it) for the contact sheet: the title, the end and beats spread
    between them, each a moment after its card has settled."""
    if not segs:
        return []
    beats = [i for i, s in enumerate(segs) if s.kind == "beat"]
    picks = [0]
    middle = count - 2
    if beats:
        if len(beats) <= middle:
            chosen = beats
        else:
            chosen = [beats[round(k * (len(beats) - 1) / (middle - 1))] for k in range(middle)]
        picks += chosen
    picks.append(len(segs) - 1)
    out = []
    for i in picks[:count]:
        s = segs[i]
        out.append((i, min(s.frames - 1, SLIDE_FRAMES + 12 if s.kind == "beat" else s.frames // 2)))
    return out


# --- captions -------------------------------------------------------------------------------

def timecode(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def captions(story: Story, segs: list[Segment]) -> str:
    """reel.srt: one caption per beat, video time, the beat's label, headline and lines."""
    out, n = [], 0
    for s in segs:
        if s.kind != "beat":
            continue
        b = story.beats[s.index]
        n += 1
        text = "\n".join([f"{b.kind.upper()}: {b.headline}", *b.lines])
        out.append(f"{n}\n{timecode(s.start / FPS)} --> {timecode((s.start + s.frames) / FPS)}\n{text}\n")
    return "\n".join(out)

