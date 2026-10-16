"""Drawing a Story: Pillow frames piped to ffmpeg, plus the contact sheet and the text artifacts.

Everything about *where* and *when* lives in `layout.py` (pure). This module only paints what that
module describes, and every string goes through `Painter`, which writes it to a ledger: the tests
(and `teyla reel check`) can then prove the video contains nothing that is not in `reel.txt`.

Pillow is the optional extra `teyla[reel]`; ffmpeg is read from PATH. Without either, `render_all`
still writes story.json, reel.txt and reel.srt and says what is missing.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import cards, layout
from .layout import H, W
from .story import MINUS, Story, fmt_clock

try:  # the optional extra
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover — exercised by the missing-dependency test via available()
    Image = ImageDraw = ImageFont = None

# --- theme ---------------------------------------------------------------------------------

BG = (11, 13, 16)
FG = (240, 244, 248)
FG_DIM = (201, 209, 219)
MUTED = (139, 148, 160)
GREEN = (74, 222, 128)
RED = (255, 92, 92)
ACCENT = (124, 156, 255)
TRACK = (33, 38, 45)
ADD_BG, ADD_FG = (16, 52, 31), (134, 239, 172)
DEL_BG, DEL_FG = (66, 22, 28), (255, 160, 160)
KIND_COLOR = {
    "ask": ACCENT, "lane": (192, 132, 252), "edit": (251, 191, 36), "test": GREEN,
    "command": (148, 163, 184), "commit": (45, 212, 191), "pr": (244, 114, 182), "review": (251, 146, 60),
}
DARK_ON_PILL = (11, 13, 16)

MAC_FONT = "/System/Library/Fonts/Menlo.ttc"
LINUX_FONTS = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSansMono.ttf", "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf"),
)
CHROME_OK = (re.compile(r"\d\d:\d\d:\d\d"), re.compile(r"\d+ (?:commits?|tests|PRs?)"))


class Missing(Exception):
    """Something the video needs is not there (Pillow, ffmpeg, a font)."""


def available() -> dict:
    """What can be produced here: {'pillow': bool, 'ffmpeg': path | None}."""
    return {"pillow": Image is not None, "ffmpeg": shutil.which("ffmpeg")}


# --- fonts and the painter -----------------------------------------------------------------

class Fonts:
    def __init__(self, regular: str, bold: str, reg_index: int = 0, bold_index: int = 0):
        self._spec = {False: (regular, reg_index), True: (bold, bold_index)}
        self._cache: dict = {}

    def get(self, pt: int, bold: bool = False):
        key = (pt, bold)
        if key not in self._cache:
            path, index = self._spec[bold]
            self._cache[key] = ImageFont.truetype(path, pt, index=index)
        return self._cache[key]

    @classmethod
    def find(cls, override: str | None = None) -> "Fonts":
        if override:
            if not os.path.isfile(override):
                raise Missing(f"font not found: {override}")
            bold = re.sub(r"(?i)regular", "Bold", override) if re.search(r"(?i)regular", override) else override
            return cls(override, bold if os.path.isfile(bold) else override)
        if os.path.isfile(MAC_FONT):
            return cls(MAC_FONT, MAC_FONT, 0, 1)
        for reg, bold in LINUX_FONTS:
            if os.path.isfile(reg):
                return cls(reg, bold if os.path.isfile(bold) else reg)
        raise Missing("no monospace font found (Menlo, DejaVu Sans Mono); pass --font PATH")


class Ledger:
    """Every string drawn: content (must be in reel.txt) and chrome (clock, counters)."""

    def __init__(self):
        self.content: set[tuple[str, str]] = set()   # (source string, what was drawn, whitespace aside)
        self.chrome: set[str] = set()


class Painter:
    """The only way a string reaches a frame."""

    def __init__(self, img, fonts: Fonts, ledger: Ledger):
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.fonts = fonts
        self.ledger = ledger

    def width(self, s: str, pt: int, bold: bool = False) -> float:
        return self.fonts.get(pt, bold).getlength(s)

    def text(self, xy, s: str, pt: int, fill, *, src: str | None = None, bold: bool = False,
             chrome: bool = False, anchor: str = "la") -> None:
        """Draw `s` at `xy`. `src` is the Story string it comes from (default: `s` itself)."""
        if chrome:
            self.ledger.chrome.add(s)
        else:
            self.ledger.content.add((s if src is None else src, s))
        self.d.text(xy, s, font=self.fonts.get(pt, bold), fill=fill, anchor=anchor)

    def runs(self, xy, parts: list[tuple[str, tuple]], pt: int, *, src: str, bold: bool = False) -> None:
        """One string drawn in colour runs: the runs together are `src`."""
        self.ledger.content.add((src, "".join(p for p, _c in parts)))
        x, y = xy
        font = self.fonts.get(pt, bold)
        for part, fill in parts:
            self.d.text((x, y), part, font=font, fill=fill, anchor="la")
            x += font.getlength(part)

    def wrapped(self, x: int, rows: list[tuple[str, int]], pt: int, fill, *, src: str, bold: bool = False) -> None:
        """A string already broken into rows by the layout: the rows together are `src`."""
        self.ledger.content.add((src, " ".join(t for t, _y in rows)))
        font = self.fonts.get(pt, bold)
        for t, y in rows:
            self.d.text((x, y), t, font=font, fill=fill, anchor="la")

    def rect(self, box, fill, radius: int = 0) -> None:
        if radius:
            self.d.rounded_rectangle(box, radius=radius, fill=fill)
        else:
            self.d.rectangle(box, fill=fill)


# --- the reel ------------------------------------------------------------------------------

END_COLORS = (
    (re.compile(r"tests passed"), GREEN), (re.compile(r"tests failed"), RED), (re.compile(r"\bPR"), ACCENT),
    (re.compile(r"wall clock|in tokens"), MUTED),
)


class Reel:
    """A Story's frames. `frame(i, f)` is frame `f` of segment `i`; `video` and `contact` use it."""

    def __init__(self, story: Story, seconds: float = 45, fonts: Fonts | None = None):
        if Image is None:
            raise Missing("Pillow is not installed (pip install 'teyla[reel]')")
        self.story = story
        self.fonts = fonts or Fonts.find()
        self.segs = layout.plan(story, seconds)
        self.ledger = Ledger()
        self._frame_static = self._static()
        self._settled: dict[int, "Image.Image"] = {}
        self._last: tuple | None = None
        self._last_bytes = b""

    # -- pieces --

    def _canvas(self):
        return Image.new("RGB", (W, H), BG)

    def _static(self):
        """Background plus what never changes: the repo, the harness badge, the progress track and its ticks."""
        img = self._canvas()
        p = Painter(img, self.fonts, self.ledger)
        s = self.story
        p.text((layout.MARGIN, layout.BAR_Y), s.repo, 40, FG, src=s.repo, bold=True)
        x = layout.MARGIN + p.width(s.repo, 40, True) + 24
        bw = p.width(s.harness, 30) + 28
        p.rect((x, layout.BAR_Y + 2, x + bw, layout.BAR_Y + 46), TRACK, radius=10)
        p.text((x + 14, layout.BAR_Y + 7), s.harness, 30, MUTED, src=s.harness)
        left, right = layout.MARGIN, W - layout.MARGIN
        p.rect((left, layout.PROGRESS_Y, right, layout.PROGRESS_Y + 12), TRACK, radius=6)
        wall = max(1, s.totals.wall_clock)
        for b in s.beats:
            tx = left + int((right - left) * min(1.0, b.t / wall))
            p.rect((tx - 2, layout.PROGRESS_Y - 6, tx + 2, layout.PROGRESS_Y + 18), MUTED)
        return img

    def _card(self, img, seg: layout.Segment, dy: int) -> None:
        p = Painter(img, self.fonts, self.ledger)
        s = self.story
        if seg.kind == "title":
            pt, rows = layout.fit_headline(s.title)
            pitch = int(pt * 1.22)
            top = (layout.CARD_TOP + layout.CARD_BOTTOM) // 2 - (len(rows) * pitch + 90) // 2 + dy
            p.wrapped(layout.MARGIN, [(t, top + i * pitch) for i, t in enumerate(rows)], pt, FG, src=s.title, bold=True)
            sub = cards.title_card(s)[1]
            p.text((layout.MARGIN, top + len(rows) * pitch + 30), sub, 40, MUTED, src=sub)
        elif seg.kind == "end":
            lines = cards.end_card(s)
            for text, y in layout.center_rows(lines, 64, 120, layout.CARD_TOP, layout.CARD_BOTTOM):
                y += dy
                if text.startswith("+") and MINUS in text:
                    plus, minus = text.split(" ", 1)
                    p.runs((layout.MARGIN, y), [(plus + " ", GREEN), (minus, RED)], 64, src=text, bold=True)
                    continue
                color = next((c for rx, c in END_COLORS if rx.search(text)), FG)
                p.text((layout.MARGIN, y), text, 64, color, src=text, bold=True)
        else:
            b = s.beats[seg.index]
            rows = layout.card_layout(b.kind, b.headline, b.lines, b.diff)
            color = KIND_COLOR.get(b.kind, MUTED)
            head_rows = [(r.text, r.y + dy) for r in rows if r.role == "headline"]
            for r in rows:
                y = r.y + dy
                if r.role == "label":
                    w = p.width(r.text, r.pt, True) + 40
                    p.rect((layout.MARGIN, y - 6, layout.MARGIN + w, y + r.pt + 14), color, radius=14)
                    p.text((layout.MARGIN + 20, y), r.text, r.pt, DARK_ON_PILL, src=r.text, bold=True)
                elif r.role == "line":
                    p.text((layout.MARGIN, y), r.text, r.pt, FG_DIM, src=r.text)
                elif r.role == "diff":
                    fg, bg = (ADD_FG, ADD_BG) if r.tint == "add" else (DEL_FG, DEL_BG) if r.tint == "del" else (MUTED, None)
                    if bg:
                        p.rect((0, y - 4, W, y + int(r.pt * 1.2) + 2), bg)
                    p.text((layout.MARGIN, y), r.text, r.pt, fg, src=r.text)
            if head_rows:
                pt = next(r.pt for r in rows if r.role == "headline")
                hc = RED if b.kind == "test" and "fail" in b.headline.lower() else GREEN if b.kind == "test" else FG
                p.wrapped(layout.MARGIN, head_rows, pt, hc, src=b.headline, bold=True)

    def _dynamic(self, img, t: float) -> None:
        """The clock, the progress fill and the counters: the parts that change every frame."""
        p = Painter(img, self.fonts, self.ledger)
        p.text((W - layout.MARGIN, layout.BAR_Y), fmt_clock(t), 40, FG_DIM, chrome=True, anchor="ra")
        left, right = layout.MARGIN, W - layout.MARGIN
        px = int((right - left) * layout.progress(self.story, t))
        if px > 0:
            p.rect((left, layout.PROGRESS_Y, left + max(px, 12), layout.PROGRESS_Y + 12), ACCENT, radius=6)
        commits, tests, prs = layout.counters_at(self.story, t)
        y = layout.COUNTERS_Y
        p.text((layout.MARGIN, y), f"{commits} commit" + ("" if commits == 1 else "s"), 44, FG_DIM, chrome=True)
        p.text((420, y), f"{tests} tests", 44, GREEN if tests else MUTED, chrome=True)
        p.text((720, y), f"{prs} PR" + ("" if prs == 1 else "s"), 44, FG_DIM if prs else MUTED, chrome=True)

    # -- frames --

    def _settled_base(self, i: int):
        if i not in self._settled:
            img = self._frame_static.copy()
            self._card(img, self.segs[i], 0)
            self._settled[i] = img
        return self._settled[i]

    def frame(self, i: int, f: int):
        """Frame `f` of segment `i` as an RGB image."""
        seg = self.segs[i]
        alpha, dy = layout.slide(f)
        if alpha < 1.0:
            moving = self._frame_static.copy()
            self._card(moving, seg, dy)
            img = Image.blend(self._frame_static, moving, alpha)
        else:
            img = self._settled_base(i).copy()
        self._dynamic(img, layout.clock_at(seg, f))
        return img

    def frame_bytes(self, i: int, f: int) -> bytes:
        """Raw RGB of a frame; repeats of an unchanged frame are served from the previous one."""
        seg = self.segs[i]
        alpha, _ = layout.slide(f)
        t = layout.clock_at(seg, f)
        key = (i, int(t), layout.counters_at(self.story, t), int((W - 2 * layout.MARGIN) * layout.progress(self.story, t)))
        if alpha >= 1.0 and key == self._last:
            return self._last_bytes
        data = self.frame(i, f).tobytes()
        self._last, self._last_bytes = (key, data) if alpha >= 1.0 else (None, b"")
        return data

    def forget(self, i: int) -> None:
        self._settled.pop(i, None)

    # -- outputs --

    def contact(self, path: Path) -> None:
        tw, th, gap = 360, 640, 12
        sheet = Image.new("RGB", (3 * tw + 4 * gap, 3 * th + 4 * gap), (24, 27, 32))
        for n, (i, f) in enumerate(layout.keyframes(self.segs, 9)):
            tile = self.frame(i, f).resize((tw, th), Image.LANCZOS)
            sheet.paste(tile, (gap + (n % 3) * (tw + gap), gap + (n // 3) * (th + gap)))
        sheet.save(path)

    def video(self, path: Path, ffmpeg: str, preset: str = "veryfast") -> None:
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(layout.FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", preset,
               "-crf", "18", "-movflags", "+faststart", "-an", str(path)]
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err)
            try:
                for i, seg in enumerate(self.segs):
                    for f in range(seg.frames):
                        proc.stdin.write(self.frame_bytes(i, f))
                    self.forget(i)
                proc.stdin.close()
            except BrokenPipeError:
                pass
            finally:
                code = proc.wait()
            if code != 0:
                err.seek(0)
                tail = err.read().decode("utf-8", "replace").strip().splitlines()[-3:]
                path.unlink(missing_ok=True)
                raise RuntimeError("ffmpeg failed: " + " | ".join(tail))


# --- the command -----------------------------------------------------------------------------

def default_dir(story: Story) -> Path:
    day = story.started[:10]
    try:
        from datetime import datetime
        day = datetime.fromisoformat(story.started.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        pass
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", story.repo).strip("-") or "session"
    return Path.home() / "Movies" / "teyla-reel" / f"{day}-{slug}-{story.id[:8]}"


@dataclasses.dataclass
class Result:
    out: Path
    written: list[str]
    missing: list[str]       # what stopped the video: ["Pillow", "ffmpeg", ...]
    seconds: float = 0.0


def render_all(story: Story, out: Path, seconds: float = 45, font: str | None = None, video: bool = True,
               preset: str = "veryfast") -> Result:
    """Write the reel's artifacts into `out`. The text ones always; the picture ones as far as the machine allows."""
    out.mkdir(parents=True, exist_ok=True)
    res = Result(out, [], [])
    (out / "story.json").write_text(json.dumps(story.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "reel.txt").write_text("\n".join(cards.rendered_strings(story)) + "\n", encoding="utf-8")
    segs = layout.plan(story, seconds)
    (out / "reel.srt").write_text(layout.captions(story, segs), encoding="utf-8")
    res.written += ["story.json", "reel.txt", "reel.srt"]
    res.seconds = layout.total_frames(segs) / layout.FPS

    have = available()
    if not have["pillow"]:
        res.missing.append("Pillow (pip install 'teyla[reel]')")
    if video and not have["ffmpeg"]:
        res.missing.append("ffmpeg (on PATH)")
    if not have["pillow"]:
        return res
    try:
        reel = Reel(story, seconds, Fonts.find(font))
    except Missing as e:
        res.missing.append(str(e))
        return res
    reel.contact(out / "contact.png")
    res.written.append("contact.png")
    if video and have["ffmpeg"]:
        reel.video(out / "reel.mp4", have["ffmpeg"], preset)
        res.written.append("reel.mp4")
    return res
