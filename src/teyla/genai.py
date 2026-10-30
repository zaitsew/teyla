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
    tts-1             OpenAI voice-over           $15 per 1M characters
    tts-1-hd          OpenAI voice-over           $30 per 1M characters

The API id Teyla sends for `nano-banana-2.1` is `gemini-3.1-flash-image`; if Google names it differently,
set `api_model` in the kit's `[mascot.settings]` or TEYLA_KIT_GEMINI_MODEL. No call is made in safe mode
unless the command carries `--allow-network`. The only seam tests use is `_post`.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"
OPENAI_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"

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

TTS_USD_PER_MCHAR = {"tts-1": 15.0, "tts-1-hd": 30.0}
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_VOICE = "alloy"


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
    if model not in TTS_USD_PER_MCHAR:
        raise GenError(f"unknown voice-over model {model!r} (known: {', '.join(TTS_USD_PER_MCHAR)})")
    return chars * TTS_USD_PER_MCHAR[model] / 1_000_000


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

def speak(text: str, model: str = DEFAULT_TTS_MODEL, voice: str = DEFAULT_VOICE, key: str | None = None, post=None) -> bytes:
    """MP3 bytes of `text` read aloud."""
    key = key or api_key("openai")
    if not key:
        raise GenError(f"no openai key: {key_hint('openai')}")
    raw = (post or _post)(OPENAI_SPEECH_URL, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json.dumps({"model": model, "voice": voice, "input": text, "response_format": "mp3"}).encode())
    if not raw:
        raise GenError("the OpenAI speech answer was empty")
    return raw
