"""The generic `recipes` product for the screen atlas tests: a copy of tests/fixtures/recipes plus drawn screenshots."""
from __future__ import annotations

import pathlib
import shutil
import struct
import zlib

SRC = pathlib.Path(__file__).parent / "fixtures" / "recipes"

# platform, variant, screen -> a screenshot; "baseline" captures are the accepted ones
SHOTS = [
    "en-light/home.loaded", "en-light/home.empty", "en-light/recipes.loaded", "en-light/recipe.loaded",
    "en-light/shopping.loaded", "en-dark/home.loaded", "en-dark/recipes.loaded", "en-large/home.loaded",
    "es-light/home.loaded", "macos/en-light/home.loaded",
    "baseline/en-light/settings.loaded",
]


def png(path: pathlib.Path, seed: int, size=(90, 190)) -> None:
    """A small valid PNG that looks a little like a phone screen; stdlib only."""
    w, h = size
    base = [(240, 238, 230), (30, 32, 38), (250, 250, 250)][seed % 3]
    bar = [(42, 109, 244), (76, 194, 127), (240, 138, 75)][seed % 3]
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            c = base
            if y < 14:
                c = tuple(max(0, v - 30) for v in base)
            elif 30 < y < 44 and 8 < x < w - 8:
                c = bar
            elif y > 60 and (y // 28) % 2 == 0 and 8 < x < w - 8:
                c = tuple(max(0, v - 18) for v in base)
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)


def build(dest: pathlib.Path) -> pathlib.Path:
    """Copy the fixture to `dest` and draw its screenshots. Returns `dest`."""
    shutil.copytree(SRC, dest, dirs_exist_ok=True)
    for n, rel in enumerate(SHOTS):
        parts = rel.split("/")
        png(dest / "design" / "shots" / pathlib.Path(*parts[:-1]) / f"{parts[-1]}.png", n)
    return dest


if __name__ == "__main__":
    import sys
    print(build(pathlib.Path(sys.argv[1])))
