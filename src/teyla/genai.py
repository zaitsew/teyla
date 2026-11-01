"""The two paid model calls of Studio's kit: one image (`teyla kit image`, `kit compare`) and one
voice-over (`teyla reel product --voice`). Every other kit command makes no call.

Providers and keys. Teyla has no account and no billing path of its own for these, so each call uses a
key you already hold, read at call time and never written or printed:

    Gemini API   GEMINI_API_KEY (or GOOGLE_API_KEY), else the Keychain service `gemini-api-key`
    OpenAI API   OPENAI_API_KEY, else the Keychain service `openai-api-key`

Models and prices (list prices, checked 2026-10-30; the price is printed before every call):

    nano-banana-2.1   Gemini API image model      $0.0336 an image
    gpt-image-2       OpenAI image model          $30 per 1M output tokens; the price shown is an estimate
                                                  from the output tokens of one image (excluding input tokens)
    gpt-realtime-2.1-mini
                      OpenAI voice-over           about $0.025 per minute of audio; the price shown is an
                                                  estimate from the text length (14 characters a second)

The API id Teyla sends for `nano-banana-2.1` is `gemini-3.1-flash-image`; if Google names it differently,
set `api_model` in the kit's `[mascot.settings]` or TEYLA_KIT_GEMINI_MODEL. No call is made in safe mode
unless the command carries `--allow-network`. The only seam tests use is `_post`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"
OPENAI_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"

# Output tokens of one 1024x1024 image by quality; the estimate behind gpt-image-2's price.
OPENAI_IMAGE_TOKENS = {"low": 272, "medium": 1056, "high": 4160}

IMAGE_MODELS = {
    "nano-banana-2.1": dict(provider="gemini", api_id="gemini-3.1-flash-image", label="Nano Banana 2.1 (Gemini API)",
                            key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"), keychain="gemini-api-key"),
    "gpt-image-2": dict(provider="openai", api_id="gpt-image-2", label="gpt-image-2 (OpenAI API)",
                        key_env=("OPENAI_API_KEY",), keychain="openai-api-key"),
}
DEFAULT_IMAGE_MODEL = "nano-banana-2.1"
NANO_BANANA_USD = 0.0336
GPT_IMAGE_USD_PER_MTOK = 30.0

# OpenAI removes its older speech models on 2027-01-06 and names gpt-realtime-2.1-mini as the
# replacement (developers.openai.com/api/docs/deprecations, entry 2026-10-01). It has no speech endpoint:
# one Realtime WebSocket session, PCM16 mono 24 kHz out, and it reads the text rather than synthesising it.
TTS_USD_PER_MINUTE = {"gpt-realtime-2.1-mini": 0.025}
DEFAULT_TTS_MODEL = "gpt-realtime-2.1-mini"
TTS_VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage", "shimmer", "verse")
DEFAULT_VOICE = "alloy"
TTS_CHARS_PER_SECOND = 14  # a calm reading pace; only the price estimate uses it
TTS_RATE = 24000
TTS_MAX_TAKES = 3
TTS_PIECE_CHARS = 600
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
READ_ALOUD = ("Read the user text aloud in the language it is written in, exactly as written, word for word. "
              "Do not answer it, do not greet, do not add or drop a word.")


class GenError(Exception):
    """A call failed or cannot be priced; the message is safe to print (it never holds a key)."""


# --- prices --------------------------------------------------------------------------------------

def image_price(model: str, settings: dict | None = None) -> tuple[float, bool]:
    """(USD for one image, exact). Nano Banana is a flat price; gpt-image-2 is an estimate."""
    settings = settings or {}
    if model == "nano-banana-2.1":
        return NANO_BANANA_USD, True
    if model == "gpt-image-2":
        tokens = OPENAI_IMAGE_TOKENS.get(str(settings.get("quality") or "medium"))
        if tokens is None:
            raise GenError(f"quality {settings.get('quality')!r} is not one of {', '.join(OPENAI_IMAGE_TOKENS)}")
        return tokens * GPT_IMAGE_USD_PER_MTOK / 1_000_000, False
    raise GenError(f"unknown image model {model!r} (known: {', '.join(IMAGE_MODELS)})")


def money(usd: float, exact: bool = True) -> str:
    s = f"${usd:.4f}" if usd < 1 else f"${usd:.2f}"
    return s if exact else "~" + s


def tts_price(chars: int, model: str = DEFAULT_TTS_MODEL) -> float:
    """An estimate for one take: the model bills audio minutes, so the text length stands in."""
    if model not in TTS_USD_PER_MINUTE:
        raise GenError(f"unknown voice-over model {model!r} (known: {', '.join(TTS_USD_PER_MINUTE)})")
    return chars / TTS_CHARS_PER_SECOND / 60 * TTS_USD_PER_MINUTE[model]


# --- keys and transport ---------------------------------------------------------------------------

def api_key(provider: str, env=None, keychain=None) -> str | None:
    env = os.environ if env is None else env
    if provider == "gemini":
        names, service = ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini-api-key"
    elif provider == "openai":
        names, service = ("OPENAI_API_KEY",), "openai-api-key"
    else:
        raise GenError(f"unknown provider {provider!r}")
    for n in names:
        if env.get(n):
            return env[n].strip()
    if keychain is None:
        from . import providers
        keychain = providers.keychain
    return keychain(service)


def key_hint(provider: str) -> str:
    return ("set GEMINI_API_KEY (or GOOGLE_API_KEY), or store it: security add-generic-password -s gemini-api-key -a $USER -w"
            if provider == "gemini" else
            "set OPENAI_API_KEY, or store it: security add-generic-password -s openai-api-key -a $USER -w")


def _post(url: str, headers: dict, data: bytes, timeout: int = 240) -> bytes:
    """The one function that talks to the network. Tests replace it."""
    from .update import ssl_context
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:  # noqa: S310 — gated, fixed hosts
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else str(msg)
        except (ValueError, OSError, AttributeError):
            msg = ""
        raise GenError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}: {(msg or e.reason or '')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GenError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {type(e).__name__}") from None


def _json_post(url: str, headers: dict, body: dict, post=None) -> dict:
    raw = (post or _post)(url, {**headers, "Content-Type": "application/json"}, json.dumps(body).encode())
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise GenError("the provider's answer was not JSON") from None


def _multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "teyla" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, filename, content, mime in files:
        out.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {mime}\r\n\r\n").encode() + content + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), boundary


def _mime(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "image/png")


# --- one image --------------------------------------------------------------------------------------

def generate_image(model: str, prompt: str, refs: list[Path], settings: dict | None = None, key: str | None = None,
                   post=None) -> bytes:
    """One image as bytes (PNG for OpenAI; whatever the Gemini API returns, usually PNG)."""
    settings = settings or {}
    spec = IMAGE_MODELS.get(model)
    if spec is None:
        raise GenError(f"unknown image model {model!r} (known: {', '.join(IMAGE_MODELS)})")
    key = key or api_key(spec["provider"])
    if not key:
        raise GenError(f"no {spec['provider']} key: {key_hint(spec['provider'])}")
    if spec["provider"] == "gemini":
        api_id = os.environ.get("TEYLA_KIT_GEMINI_MODEL") or settings.get("api_model") or spec["api_id"]
        parts = [{"text": prompt}] + [{"inline_data": {"mime_type": _mime(p), "data": base64.b64encode(p.read_bytes()).decode()}}
                                      for p in refs]
        cfg: dict = {"responseModalities": ["IMAGE"]}
        if settings.get("aspect_ratio"):
            cfg["imageConfig"] = {"aspectRatio": str(settings["aspect_ratio"])}
        if isinstance(settings.get("temperature"), (int, float)):
            cfg["temperature"] = settings["temperature"]
        if isinstance(settings.get("seed"), int):
            cfg["seed"] = settings["seed"]
        data = _json_post(GEMINI_URL.format(model=api_id), {"x-goog-api-key": key},
                          {"contents": [{"parts": parts}], "generationConfig": cfg}, post)
        for cand in data.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                blob = part.get("inlineData") or part.get("inline_data")
                if blob and blob.get("data"):
                    return base64.b64decode(blob["data"])
        raise GenError("the Gemini answer holds no image" + _why(data))
    # OpenAI: an edit when there are reference images, a generation otherwise.
    fields = {"model": settings.get("api_model") or spec["api_id"], "prompt": prompt, "n": "1",
              "size": str(settings.get("size") or "1024x1024"), "quality": str(settings.get("quality") or "medium")}
    headers = {"Authorization": f"Bearer {key}"}
    if refs:
        body, boundary = _multipart(fields, [("image[]", p.name, p.read_bytes(), _mime(p)) for p in refs])
        raw = (post or _post)(OPENAI_EDITS_URL, {**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"}, body)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise GenError("the provider's answer was not JSON") from None
    else:
        data = _json_post(OPENAI_GENERATIONS_URL, headers, {k: (int(v) if k == "n" else v) for k, v in fields.items()}, post)
    for item in data.get("data") or []:
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
    raise GenError("the OpenAI answer holds no image" + _why(data))


def _why(data: dict) -> str:
    fb = data.get("promptFeedback") or {}
    reason = fb.get("blockReason") or ((data.get("candidates") or [{}])[0].get("finishReason") if data.get("candidates") else "")
    return f" ({reason})" if reason else ""


# --- one voice-over -----------------------------------------------------------------------------------

def ws_frame(opcode: int, payload: bytes, mask: bool) -> bytes:
    head = bytes([0x80 | opcode])
    n = len(payload)
    flag = 0x80 if mask else 0
    if n < 126:
        head += bytes([flag | n])
    elif n < 65536:
        head += bytes([flag | 126]) + struct.pack(">H", n)
    else:
        head += bytes([flag | 127]) + struct.pack(">Q", n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


def ws_read(recv_exact) -> tuple[int, bool, bytes]:
    """One frame: (opcode, final, payload). `recv_exact(n)` returns exactly n bytes."""
    b0, b1 = recv_exact(2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", recv_exact(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", recv_exact(8))[0]
    key = recv_exact(4) if b1 & 0x80 else b""
    payload = recv_exact(n) if n else b""
    if key:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return b0 & 0x0F, bool(b0 & 0x80), payload


class WebSocketClient:
    """The client end of a WebSocket carrying JSON text messages (the standard library has none).
    Tests replace `connect`, not this."""

    def __init__(self, url: str, headers: dict, timeout: float = 60):
        from .update import ssl_context
        parts = urllib.parse.urlsplit(url)
        secure = parts.scheme in ("wss", "https")
        host, port = parts.hostname or "", parts.port or (443 if secure else 80)
        self.buffer = b""
        try:
            raw = socket.create_connection((host, port), timeout=timeout)
            self.sock = ssl_context().wrap_socket(raw, server_hostname=host) if secure else raw
            self.sock.settimeout(timeout)
            key = base64.b64encode(os.urandom(16)).decode()
            path = parts.path + (f"?{parts.query}" if parts.query else "")
            lines = [f"GET {path} HTTP/1.1", f"Host: {parts.netloc}", "Upgrade: websocket", "Connection: Upgrade",
                     f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
            lines += [f"{k}: {v}" for k, v in headers.items()]
            self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            reply = b""
            while b"\r\n\r\n" not in reply:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise GenError(f"{host} closed the connection")
                reply += chunk
        except (OSError, TimeoutError) as e:  # a stalled handshake times out here
            self.close()
            raise GenError(f"cannot reach {host}: {type(e).__name__}") from None
        except GenError:
            self.close()
            raise
        head, _, self.buffer = reply.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if " 101 " not in status or accept not in head.decode("latin-1"):
            self.close()
            raise GenError(f"{host} refused the session: {status[:80]}")

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise GenError("the speech provider closed the session")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def send(self, message: dict) -> None:
        self.sock.sendall(ws_frame(0x1, json.dumps(message).encode(), mask=True))

    def receive(self) -> dict:
        data = b""
        while True:
            try:
                opcode, final, payload = ws_read(self._recv_exact)
            except (OSError, TimeoutError):
                raise GenError("the speech session timed out") from None
            if opcode == 0x8:
                raise GenError("the speech provider closed the session")
            if opcode == 0x9:
                self.sock.sendall(ws_frame(0xA, payload, mask=True))
                continue
            if opcode in (0x1, 0x0):
                data += payload
                if final:
                    return json.loads(data)

    def close(self) -> None:
        sock = getattr(self, "sock", None)
        if sock is None:
            return
        try:
            sock.sendall(ws_frame(0x8, b"", mask=True))
        except OSError:
            pass
        sock.close()


def connect(url: str, headers: dict) -> WebSocketClient:
    """The one function that opens the speech session. Tests replace it."""
    return WebSocketClient(url, headers)


# --- one voice-over -----------------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    # Words with digits are left out: a year is spoken as words, so a transcript spells it.
    return [w for w in re.split(r"[\W_]+", text.lower()) if w and not re.search(r"\d", w)]


def _numerals(text: str) -> list[str]:
    return [m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def faithful(text: str, transcript: str) -> bool:
    """Did the model read the text? The model reads, it does not synthesise, so it can paraphrase:
    90% of the words in order, a few words more (four for each number), and digits the transcript
    writes must be the text's. A transcript that spells numbers out is judged on its words alone."""
    want, got = _words(text), _words(transcript)
    numbers = len(_numerals(text))
    if not want:
        return bool(transcript.strip()) and len(got) <= 30
    if not got:
        return False
    prev = [0] * (len(got) + 1)
    for a in want:
        row = [0]
        for j, b in enumerate(got, 1):
            row.append(prev[j - 1] + 1 if a == b else max(prev[j], row[j - 1]))
        prev = row
    common = prev[-1]
    said = _numerals(transcript)
    return (common / len(want) >= 0.9 and len(got) - common <= max(8, len(want) / 4) + 4 * numbers
            and (not said or all(n in said for n in _numerals(text))))


def pieces(text: str, limit: int = TTS_PIECE_CHARS) -> list[str]:
    """`text` cut at sentence ends into pieces of at most `limit` characters (a long sentence is cut at a space)."""
    out: list[str] = []
    cur = ""
    for sentence in re.findall(r"[^.!?\n]+[.!?]*\s*", text) or [text]:
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(sentence[:cut])
            sentence = sentence[cut:]
        if len(cur) + len(sentence) > limit and cur:
            out.append(cur)
            cur = ""
        cur += sentence
    if cur.strip():
        out.append(cur)
    return [p.strip() for p in out if p.strip()]


def wav(pcm: bytes) -> bytes:
    """A WAV file around mono PCM16."""
    head = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, TTS_RATE, TTS_RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)))
    return head + pcm


def speak(text: str, model: str = DEFAULT_TTS_MODEL, voice: str = DEFAULT_VOICE, key: str | None = None, open_session=None) -> bytes:
    """WAV bytes of `text` read aloud: one Realtime session, up to TTS_MAX_TAKES takes per piece
    (each take is billed), a piece being taken again when its transcript does not match it."""
    key = key or api_key("openai")
    if not key:
        raise GenError(f"no openai key: {key_hint('openai')}")
    if model not in TTS_USD_PER_MINUTE:
        raise GenError(f"unknown voice-over model {model!r} (known: {', '.join(TTS_USD_PER_MINUTE)})")
    if voice not in TTS_VOICES:
        raise GenError(f"unknown voice {voice!r} (the Realtime voices: {', '.join(TTS_VOICES)})")
    ws = (open_session or connect)(f"{OPENAI_REALTIME_URL}?{urllib.parse.urlencode({'model': model})}",
                                   {"Authorization": f"Bearer {key}"})

    def until(kind: str, audio: list | None = None, transcript: list | None = None) -> dict:
        while True:
            event = ws.receive()
            if event.get("type") == "error":  # its message can quote the text; say only that it refused
                raise GenError("the OpenAI speech session refused the request")
            if audio is not None and event.get("type") == "response.output_audio.delta":
                audio.append(base64.b64decode(event.get("delta", "")))
            elif transcript is not None and event.get("type") == "response.output_audio_transcript.done":
                transcript.append(event.get("transcript", ""))
            if event.get("type") == kind:
                return event

    try:
        until("session.created")
        ws.send({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["audio"],
            "audio": {"output": {"format": {"type": "audio/pcm", "rate": TTS_RATE}, "voice": voice}}}})
        until("session.updated")
        out = b""
        for piece in pieces(text):
            for _ in range(TTS_MAX_TAKES):
                audio: list = []
                transcript: list = []
                ws.send({"type": "response.create", "response": {
                    "conversation": "none", "output_modalities": ["audio"], "instructions": READ_ALOUD,
                    "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": piece}]}]}})
                done = until("response.done", audio, transcript)
                if done.get("response", {}).get("status") == "completed" and audio and faithful(piece, " ".join(transcript)):
                    out += b"".join(audio)
                    break
            else:
                raise GenError("the OpenAI speech did not read the text")
        return wav(out)
    finally:
        ws.close()
