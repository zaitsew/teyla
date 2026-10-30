"""Pillow drawing helpers shared by `teyla kit shots`, `kit compare` and `reel product`.

Pillow is the optional extra `teyla[reel]`. It is imported on first use, never at import time, so
the rest of the kit works without it. Text is drawn in a proportional bold font that covers Latin
and Cyrillic (Arial or Helvetica on a Mac, DejaVu Sans on Linux); `--font PATH` or the kit's
`[shots] font` replaces it. Without any of them Pillow's built-in font is used, which draws Latin only.
"""
from __future__ import annotations

from pathlib import Path

INSTALL_HINT = "Pillow is not installed: uv tool install --force --python 3.12 --with pillow git+https://github.com/zaitsew/teyla"

BOLD_FONTS = (
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 0),
)


class Missing(Exception):
    """Something the output needs is not there (Pillow, ffmpeg)."""


def pillow():
    """(Image, ImageDraw, ImageFont) or raise Missing with the one-line install hint."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise Missing(INSTALL_HINT) from None
    return Image, ImageDraw, ImageFont


def hex_rgb(value: str, default: tuple = (255, 255, 255)) -> tuple:
    s = (value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if len(s) == 6 else default
    except ValueError:
        return default


def find_font(path: str | None = None):
    """A function size -> font. `path` first, then the system's bold sans, then Pillow's default."""
    _, _, ImageFont = pillow()
    cands = [(path, 0)] if path else []
    cands += list(BOLD_FONTS)
    for p, index in cands:
        if p and Path(p).is_file():
            def get(size, p=p, index=index):
                try:
                    return ImageFont.truetype(p, size, index=index)
                except OSError:
                    return ImageFont.truetype(p, size)
            return get
    return lambda size: ImageFont.load_default(size)


def wrap(draw, text: str, font, width: int) -> list[str]:
    """Greedy word wrap to `width` pixels; a word wider than the line stays on its own line."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if cur and draw.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text: str, getfont, width: int, max_lines: int, size: int, min_size: int):
    """(font, lines, size): the largest size from `size` down to `min_size` whose wrap fits `max_lines`;
    at the minimum, whatever the wrap gives (the caller clips by height)."""
    s = size
    while True:
        font = getfont(s)
        lines = wrap(draw, text, font, width)
        if len(lines) <= max_lines or s <= min_size:
            return font, lines, s
        s = max(min_size, int(s * 0.92))


def rounded_screen(Image, ImageDraw, shot, size: tuple, radius: int):
    """`shot` resized to `size` with rounded corners, as an RGBA image."""
    shot = shot.convert("RGBA").resize(size, Image.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(shot, (0, 0), mask)
    return out
