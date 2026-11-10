"""TestFlight screenshot feedback for `teyla review pull --testflight <app-id>`.

One read-only call family to App Store Connect:

    GET https://api.appstoreconnect.apple.com/v1/apps/{id}/betaFeedbackScreenshotSubmissions

signed with the API key the release tool already uses: `~/.appstoreconnect/config.env` holds
ASC_KEY_ID and ASC_ISSUER_ID, `~/.appstoreconnect/private_keys/AuthKey_<ASC_KEY_ID>.p8` is the secret.
The secret is read only by `openssl dgst -sign` (it is a path argument, never printed, copied or put in
an environment variable), and the token lives for 15 minutes in memory. Teyla has no crypto dependency,
so the ES256 signature comes from the `openssl` on the Mac, and `der_to_raw` turns its DER output into
the fixed 64 bytes a JWT needs.

A submission becomes a capture without element data: `source` is "testflight", the id is a UUIDv5 of
Apple's submission id (so a second pull is the same capture), and the tester's e-mail is dropped.
The screenshot is downloaded without the API token (Apple signs that URL), over https only.

Everything that touches the network goes through `Client`, which the tests replace.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.appstoreconnect.apple.com"
NAMESPACE = uuid.UUID("5b0f3a52-7c0e-4a52-9d8e-2b5f6c1a7e10")      # fixed: it makes TestFlight ids repeatable
PAGE = 50
MAX_PAGES = 5
MAX_PICTURE = 20 * 1024 * 1024
TIMEOUT_S = 60


class AscError(RuntimeError):
    """Something the owner can fix: a missing key, a refused request. The message says what to do."""


def asc_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_ASC_DIR") or "~/.appstoreconnect").expanduser()


def load_config(root: pathlib.Path | None = None) -> dict[str, str]:
    """ASC_KEY_ID, ASC_ISSUER_ID and ASC_KEY_PATH. Identifiers only; the key file is not read here."""
    root = root or asc_dir()
    cfg: dict[str, str] = {}
    f = root / "config.env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    missing = [k for k in ("ASC_KEY_ID", "ASC_ISSUER_ID") if not cfg.get(k)]
    if missing:
        raise AscError(f"missing {', '.join(missing)} in {f}: the release tool's App Store Connect setup writes them")
    key = root / "private_keys" / f"AuthKey_{cfg['ASC_KEY_ID']}.p8"
    if not key.is_file():
        raise AscError(f"no API key at {key}")
    cfg["ASC_KEY_PATH"] = str(key)
    return cfg


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_to_raw(der: bytes, size: int = 32) -> bytes:
    """An ECDSA signature as DER (SEQUENCE of two INTEGERs) to r || s, each `size` bytes."""
    def length(buf: bytes, i: int) -> tuple[int, int]:
        n = buf[i]
        if n < 0x80:
            return n, i + 1
        k = n & 0x7F
        return int.from_bytes(buf[i + 1:i + 1 + k], "big"), i + 1 + k

    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("not a DER signature")
    _, i = length(der, 1)
    parts = []
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("not a DER signature")
        n, i = length(der, i + 1)
        parts.append(int.from_bytes(der[i:i + n], "big"))
        i += n
    r, s = parts
    if r.bit_length() > size * 8 or s.bit_length() > size * 8:
        raise ValueError("signature integer too large")
    return r.to_bytes(size, "big") + s.to_bytes(size, "big")


def _sign(message: bytes, key_path: str) -> bytes:
    """ES256 over `message` with the .p8 at `key_path`, by `openssl dgst -sha256 -sign`."""
    try:
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path], input=message,
                           capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise AscError(f"cannot run openssl to sign the App Store Connect token ({type(e).__name__})") from e
    if r.returncode != 0:
        raise AscError("openssl could not sign with the API key (is the file a valid .p8?)")
    return r.stdout


def token(cfg: dict[str, str], now: float | None = None, sign=_sign) -> str:
    """A 15-minute ES256 JWT for the REST API."""
    now = int(time.time() if now is None else now)
    head = _b64(json.dumps({"alg": "ES256", "kid": cfg["ASC_KEY_ID"], "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"iss": cfg["ASC_ISSUER_ID"], "iat": now, "exp": now + 900,
                            "aud": "appstoreconnect-v1"}, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode("ascii")
    return f"{head}.{body}.{_b64(der_to_raw(sign(signing_input, cfg['ASC_KEY_PATH'])))}"


class Client:
    """The two HTTP reads. Tests pass their own object with the same two methods."""

    def __init__(self, cfg: dict[str, str]):
        self.cfg = cfg

    def get_json(self, url: str) -> dict:
        if not url.startswith(API + "/"):
            raise AscError(f"refusing to send the App Store Connect token to {url.split('?')[0]}")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token(self.cfg)})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise AscError(f"App Store Connect answered {e.code} for {url.split('?')[0].removeprefix(API)}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AscError(f"App Store Connect is unreachable ({type(e).__name__})") from e

    def get_bytes(self, url: str) -> bytes:
        """A picture from the URL Apple signed. No Authorization header, https only, size capped."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AscError("a screenshot URL that is not https was ignored")
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=TIMEOUT_S) as r:
                data = r.read(MAX_PICTURE + 1)
        except (urllib.error.URLError, OSError) as e:
            raise AscError(f"the screenshot download failed ({type(e).__name__})") from e
        if len(data) > MAX_PICTURE:
            raise AscError("a screenshot over 20 MB was ignored")
        return data


def fetch_submissions(app_id: str, client) -> list[dict]:
    """The raw `data` items, newest first, at most MAX_PAGES pages. Follows `links.next` only inside API."""
    if not app_id.isdigit():
        raise AscError(f"{app_id!r} is not an App Store Connect app id (digits only; the Apple ID in App Information)")
    url = f"{API}/v1/apps/{app_id}/betaFeedbackScreenshotSubmissions?limit={PAGE}&sort=-createdDate"
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        page = client.get_json(url)
        out += [d for d in page.get("data") or [] if isinstance(d, dict)]
        url = ((page.get("links") or {}).get("next")) or ""
        if not url:
            break
    return out


def to_capture(item: dict, product: str = "") -> dict | None:
    """One submission as a capture dict (the shape of `docs/REVIEW.md` without element data), or None."""
    sid = str(item.get("id") or "")
    a = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    if not sid:
        return None
    bundle = str(a.get("buildBundleId") or "")
    shots = a.get("screenshots") if isinstance(a.get("screenshots"), list) else []
    url = next((s.get("url") for s in shots if isinstance(s, dict) and isinstance(s.get("url"), str)), "")
    device = " ".join(x for x in (str(a.get("deviceModel") or ""), str(a.get("osVersion") or "")) if x)
    return {
        "id": str(uuid.uuid5(NAMESPACE, "testflight:" + sid)),
        "product": product or (bundle.rsplit(".", 1)[-1] if bundle else "unknown"),
        "screen": "",
        "element": None,
        "tap": None,
        "comment": str(a.get("comment") or "").strip(),
        "build": "",
        "commit": "",
        "locale": str(a.get("locale") or ""),
        "dynamic_type": "",
        "appearance": "",
        "created_at": str(a.get("createdDate") or ""),
        "source": "testflight",
        "device": device,
        "_picture_url": url,
    }


# --- device crashes (`teyla crash --pull`, docs/PRIVACY.md row 56) -------------------------------------------
# Same key, same Client, same read-only GETs. Nothing here writes to Apple.

LOG_CAP = 64 * 1024


def _app_id(app_id: str) -> str:
    if not app_id.isdigit():
        raise AscError(f"{app_id!r} is not an App Store Connect app id (digits only)")
    return app_id


def lookup_app_id(bundle_id: str, client) -> str:
    """The numeric app id of a bundle id, or "" when the key's team has no such app."""
    q = urllib.parse.quote(bundle_id, safe="")
    page = client.get_json(f"{API}/v1/apps?filter[bundleId]={q}&limit=1&fields[apps]=bundleId")
    for d in page.get("data") or []:
        if isinstance(d, dict) and str(d.get("id") or "").isdigit():
            return str(d["id"])
    return ""


def fetch_crash_submissions(app_id: str, client) -> list[dict]:
    """betaFeedbackCrashSubmissions of one app, newest first, at most MAX_PAGES pages."""
    url = f"{API}/v1/apps/{_app_id(app_id)}/betaFeedbackCrashSubmissions?limit={PAGE}&sort=-createdDate"
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        page = client.get_json(url)
        out += [d for d in page.get("data") or [] if isinstance(d, dict)]
        url = ((page.get("links") or {}).get("next")) or ""
        if not url:
            break
    return out


def fetch_crash_log(submission_id: str, client) -> str:
    """The crash log text of one submission (its `crashLog` relationship), capped. "" when there is none."""
    if not submission_id or "/" in submission_id or "?" in submission_id:
        return ""
    page = client.get_json(f"{API}/v1/betaFeedbackCrashSubmissions/{urllib.parse.quote(submission_id, safe='')}/crashLog")
    d = page.get("data")
    a = d.get("attributes") if isinstance(d, dict) and isinstance(d.get("attributes"), dict) else {}
    return str(a.get("logText") or "")[:LOG_CAP]


def newest_upload(app_id: str, client) -> str:
    """The uploadedDate (ISO text) of the app's newest build, or ""."""
    page = client.get_json(f"{API}/v1/builds?filter[app]={_app_id(app_id)}&sort=-uploadedDate&limit=1&fields[builds]=uploadedDate")
    for d in page.get("data") or []:
        a = d.get("attributes") if isinstance(d, dict) and isinstance(d.get("attributes"), dict) else {}
        if a.get("uploadedDate"):
            return str(a["uploadedDate"])
    return ""


def crash_summary(log: str) -> dict:
    """Exception type, termination reason and the first frames of the crashed thread, from a crash log's text."""
    lines = log.splitlines()
    pick = lambda key: next((ln.split(":", 1)[1].strip()[:160] for ln in lines if ln.startswith(key + ":")), "")  # noqa: E731
    frames: list[str] = []
    on = False
    for ln in lines:
        if ln.startswith("Thread ") and "Crashed" in ln:
            on = True
            continue
        if on:
            if not ln.strip():
                break
            frames.append(" ".join(ln.split())[:140])
            if len(frames) >= 6:
                break
    return {"exception": pick("Exception Type"), "termination": pick("Termination Reason"), "frames": frames}


def crash_record(item: dict, product: str = "") -> dict | None:
    """One crash submission as a stored record. The tester's e-mail is never copied."""
    sid = str(item.get("id") or "")
    a = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    if not sid:
        return None
    bundle = str(a.get("buildBundleId") or "")
    return {
        "id": str(uuid.uuid5(NAMESPACE, "testflight-crash:" + sid)),
        "product": product or (bundle.rsplit(".", 1)[-1] if bundle else "unknown"),
        "created_at": str(a.get("createdDate") or ""),
        "device": " ".join(x for x in (str(a.get("deviceModel") or ""), str(a.get("osVersion") or "")) if x),
        "build": str(a.get("buildNumber") or ""),
        "platform": str(a.get("appPlatform") or ""),
        "comment": str(a.get("comment") or "").strip()[:500],
        "_apple_id": sid,
    }
