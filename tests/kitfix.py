"""Shared fixtures for the kit tests: a complete product repo in a tmp dir, tiny PNGs, voice charts.

Russian is written as \\u escapes because the repo's leak check flags literal Cyrillic outside allow-listed files.
Everything here is generic: a made-up product, no real names.
"""
from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

RU_TAGLINE = "\u041f\u043b\u0430\u043d \u0434\u043d\u044f \u0431\u0435\u0437 \u0441\u0443\u0435\u0442\u044b"
RU_CAPTION = "\u0414\u0435\u043d\u044c \u0432 \u043e\u0434\u0438\u043d \u0432\u0437\u0433\u043b\u044f\u0434"

SHEET = ("Pip is a small round robot with a single lantern eye, a short antenna, stubby legs and a teal body that "
         "fades to white at the belly. Its face is always calm. It carries a tiny yellow notebook in its left hand. "
         "Its proportions never change: the head is as wide as the body, the legs are short, the eye sits centred. "
         "It never wears clothes, never speaks and never appears with a second character in the scene.")

CHART = """---
lang: {lang}
max_sentence_words: 20
max_post_chars:
  x_post: 280
  video_hook_15s: 120
emoji_max: 0
hashtags_max: 0
exclamations_max: 0
banned:
  - delve
  - seamless*
---
# Voice chart ({lang})
"""

KIT = """version = 1

[product]
name = "Demo App"
promise = "Plan your day in one calm screen."

[tagline]
en = "A calm day plan."
es = "Un plan de d\\u00eda tranquilo."
ru = "{ru}"

[tokens]
path = "design/tokens"

[shots]
background = "#1F2937"
text = "#FFFFFF"
accent = "#7C9CFF"

[mascot]
name = "Pip"
sheet = "{sheet}"
refs = ["brand/mascot/ref-1.png", "brand/mascot/ref-2.png"]
model = "nano-banana-2.1"

[mascot.settings]
aspect_ratio = "1:1"
temperature = 0.6
refs_max = 6

[icon]
source = "brand/icon/icon.svg"

[voice]
chart = "brand/voice"

[channels.x]
media = "image"
ratio = "16:9"
max_chars = 280
per_week = 1

[channels.instagram]
media = "image"
ratio = "4:5"
max_chars = 2200
per_week = 1

[channels.threads]
media = "none"
ratio = "none"
max_chars = 500
per_week = 1

[banned]
words = ["delve", "seamless*"]

[[provenance]]
asset = "brand/mascot/ref-1.png"
made_by = "model: nano-banana-2.1"
prompt = "Pip, front view, neutral expression"
references = []
date = "2026-10-01"

[[provenance]]
asset = "brand/mascot/ref-2.png"
made_by = "human: A. Designer"
prompt = ""
references = []
date = "2026-10-02"

[[provenance]]
asset = "brand/icon/icon.svg"
made_by = "human: A. Designer"
prompt = ""
references = []
date = "2026-10-02"

[[comparison]]
date = "2026-10-03"
scene = "waving"
models = ["nano-banana-2.1", "gpt-image-2"]
poses = 10
cost_usd = 0.6
folder = "brand/out/compare/2026-10-03-waving"
picked = "nano-banana-2.1"
"""


def png_bytes(w: int = 4, h: int = 6, rgb=(200, 80, 80)) -> bytes:
    """A valid PNG without Pillow."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_repo(tmp_path: Path, name: str = "demo-app", kit: bool = True) -> Path:
    """A product repo with a complete, passing kit."""
    repo = tmp_path / name
    (repo / "design" / "tokens").mkdir(parents=True)
    (repo / "design" / "tokens" / "colors.json").write_text("{}", encoding="utf-8")
    (repo / ".git").mkdir()
    for d in ("brand/mascot", "brand/icon", "brand/voice", "brand/posts/queue", "brand/posts/samples"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    (repo / "brand" / "mascot" / "ref-1.png").write_bytes(png_bytes())
    (repo / "brand" / "mascot" / "ref-2.png").write_bytes(png_bytes(rgb=(80, 200, 80)))
    (repo / "brand" / "icon" / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    for lang in ("en", "es", "ru"):
        (repo / "brand" / "voice" / f"{lang}.md").write_text(CHART.format(lang=lang), encoding="utf-8")
    for i in range(3):
        (repo / "brand" / "posts" / "samples" / f"sample-{i}.md").write_text("A calm sample.\n", encoding="utf-8")
    if kit:
        (repo / "brand" / "kit.toml").write_text(KIT.format(sheet=SHEET, ru=RU_TAGLINE), encoding="utf-8")
    return repo


def gemini_answer(png: bytes) -> bytes:
    return json.dumps({"candidates": [{"content": {"parts": [
        {"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}}]}}]}).encode()


def openai_answer(png: bytes) -> bytes:
    return json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}]}).encode()


class RealtimeFake:
    """Stands in for genai.connect: a Realtime speech session that answers each `response.create` with
    audio and a transcript. `transcript(take, text)` says what the model "read" (default: the text itself)."""

    PCM = b"\x01\x00" * 24000   # one second of 24 kHz PCM16

    def __init__(self, transcript=None, status="completed"):
        self.transcript, self.status = transcript, status
        self.url = self.headers = None
        self.sent, self.takes, self.closed = [], 0, False
        self.queue = [{"type": "session.created"}]

    def __call__(self, url, headers):
        self.url, self.headers = url, headers
        return self

    def send(self, message):
        import base64
        self.sent.append(message)
        if message["type"] == "session.update":
            self.queue.append({"type": "session.updated"})
        elif message["type"] == "response.create":
            self.takes += 1
            text = message["response"]["input"][0]["content"][0]["text"]
            said = self.transcript(self.takes, text) if self.transcript else text
            self.queue += [{"type": "response.output_audio.delta", "delta": base64.b64encode(self.PCM).decode()},
                           {"type": "response.output_audio_transcript.done", "transcript": said},
                           {"type": "response.done", "response": {"status": self.status}}]

    def receive(self):
        return self.queue.pop(0)

    def close(self):
        self.closed = True
