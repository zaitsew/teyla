"""Publishing for `teyla growth` (docs/GROWTH.md, "Publishing"): approved items only, through official APIs.

    teyla growth connect <network>        the OAuth flow the owner completes himself; tokens go to the macOS Keychain
    teyla growth connect --status         which networks are connected, never a token
    teyla growth publish ID.. | --day D   post approved items; the URL lands in the ledger as `published`

Four networks have an adapter: LinkedIn (Posts API, the member's own feed), Threads, Instagram (a professional account,
Reels through the Instagram API) and YouTube (a Short through the Data API). X stays manual: its paid API needs the
owner's two yeses (POLICY section 11), so its adapter refuses unless the config says `x_paid = true`, and even then it
only says that no adapter is built. TikTok has no adapter.

The rules every adapter keeps:
- Nothing publishes unless the item's status is `approved` or `ready`: the owner approved it.
- An item publishes once. The idem key is the item id and the network; a `publish-start` row without an end blocks a
  blind repost until the owner checks the network (`--retry`).
- Without credentials, in safe mode, or for a network with no adapter, the item falls back to today's packet and says so.
- A token lives in the Keychain (service `teyla-growth-<network>`), written through `security -i` on stdin so it never
  appears in a process list. It is never printed, logged or written to a file. An error message carries the host,
  the status and the provider's message with every known secret replaced.

`ManualPublisher` stays: the owner posts by hand and pastes the URL (`teyla growth published ID URL`).
"""
from __future__ import annotations

import base64
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol

PUBLISHABLE = ("approved", "ready")
# Adapters that post text only: an item with media attached goes out from its packet instead.
TEXT_ONLY = ("linkedin", "threads")

# platform -> the host names a post URL on it may have. A mismatch is a warning (a short link is legitimate),
# never a refusal.
HOSTS = {
    "x": ("x.com", "twitter.com", "t.co"),
    "linkedin": ("linkedin.com", "lnkd.in"),
    "threads": ("threads.com", "threads.net"),
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
}

NETWORKS = ("linkedin", "threads", "instagram", "youtube")
HTTP_TIMEOUT_S = 60
UPLOAD_TIMEOUT_S = 600
CALLBACK_TIMEOUT_S = 300
DEFAULT_PORT = 8765
LINKEDIN_VERSION = "202510"
GRAPH_VERSION = "v23.0"
POLL_TRIES = 30
POLL_SLEEP_S = 4.0


class PublishRefused(Exception):
    """The item may not go live; the message says why."""


class PublishError(Exception):
    """The network call failed. `posted` is False when nothing went live, None when it may have."""

    def __init__(self, msg: str, posted: bool | None = False):
        super().__init__(msg)
        self.posted = posted


class NotConnected(Exception):
    """No usable credentials for the network; the message names the command that fixes it."""


@dataclasses.dataclass
class PublishResult:
    ok: bool
    url: str = ""
    warning: str = ""


class Publisher(Protocol):
    name: str

    def publish(self, item: dict, url: str | None = None) -> PublishResult:
        """Make the item public, or record that the owner did. Raises PublishRefused."""
        ...


def _host_ok(platform: str, host: str) -> bool:
    hosts = HOSTS.get(platform)
    if not hosts:
        return True
    host = host.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in hosts)


class ManualPublisher:
    """The owner posted by hand; Teyla records the URL. It never contacts a platform."""

    name = "manual"

    def publish(self, item: dict, url: str | None = None) -> PublishResult:
        if item.get("status") not in PUBLISHABLE:
            raise PublishRefused(f"{item.get('id')} is {item.get('status')}: only an approved item can be published")
        raw = (url or "").strip()
        parts = urllib.parse.urlparse(raw)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise PublishRefused("paste the post's URL (https://...) from the platform")
        warning = ""
        if not _host_ok(str(item.get("platform") or ""), parts.hostname or ""):
            warning = f"{parts.hostname} is not a usual {item.get('platform')} host; recorded as given"
        return PublishResult(True, raw, warning)


PUBLISHERS: dict[str, Publisher] = {"manual": ManualPublisher()}


def get(name: str = "manual") -> Publisher:
    try:
        return PUBLISHERS[name]
    except KeyError:
        raise PublishRefused(f"no publisher named {name}; only {', '.join(PUBLISHERS)} exist") from None


# --- the Keychain ----------------------------------------------------------------------------------------------
# Tests replace the four `_kc_*` functions (tests/conftest.py); none reaches the real Keychain.

ACCOUNT = "teyla"


def service(network: str) -> str:
    return f"teyla-growth-{network}"


def _kc_get(svc: str) -> str | None:
    if not shutil.which("security"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", ACCOUNT, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def _kc_exists(svc: str) -> bool:
    if not shutil.which("security"):
        return False
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", ACCOUNT],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _kc_set(svc: str, value: str) -> None:
    """`security -i` reads the command from stdin, so the value never appears in argv. The value is base64, so the
    quotes around it cannot be broken."""
    if not shutil.which("security"):
        raise NotConnected("the macOS `security` tool is missing: the Keychain is the only place a token may live")
    if not all(c.isalnum() or c in "+/=" for c in value):
        raise ValueError("a Keychain value must be base64")
    cmd = f'add-generic-password -U -s "{svc}" -a "{ACCOUNT}" -l "Teyla growth {svc}" -w "{value}"\n'
    try:
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise NotConnected(f"could not write the Keychain ({type(e).__name__})") from None
    if r.returncode != 0 or "error" in (r.stderr or "").lower():
        raise NotConnected("could not write the Keychain (security returned an error)")


def _kc_delete(svc: str) -> bool:
    if not shutil.which("security"):
        return False
    try:
        r = subprocess.run(["security", "delete-generic-password", "-s", svc, "-a", ACCOUNT],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def load_creds(network: str) -> dict | None:
    raw = _kc_get(service(network))
    if not raw:
        return None
    try:
        creds = json.loads(base64.b64decode(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return creds if isinstance(creds, dict) and creds.get("access_token") else None


def save_creds(network: str, creds: dict) -> None:
    _kc_set(service(network), base64.b64encode(json.dumps(creds, separators=(",", ":")).encode("utf-8")).decode("ascii"))


def is_connected(network: str) -> bool:
    return network in NETWORKS and _kc_exists(service(network))


def forget(network: str) -> bool:
    return _kc_delete(service(network))


# --- HTTP ------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    def json(self) -> dict:
        try:
            out = json.loads(self.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return out if isinstance(out, dict) else {"data": out}


def http(method: str, url: str, *, headers: dict | None = None, data: bytes | None = None,
         timeout: int = HTTP_TIMEOUT_S) -> Response:
    """The one function that talks to a network. Tests replace it; none reaches a real API.
    A 4xx or 5xx comes back as a Response; only an unreachable host raises."""
    from .update import ssl_context
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "teyla-growth", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:  # noqa: S310 — gated, fixed hosts
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except OSError:
            body = b""
        return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        host = urllib.parse.urlsplit(url).netloc
        # A request that carried data (POST or PUT, an upload's last chunk included) may have arrived before the
        # connection dropped: say "may be live", so the next run waits for --retry instead of posting twice.
        raise PublishError(f"cannot reach {host}: {type(e).__name__}",
                           posted=None if data is not None or method in ("POST", "PUT") else False) from None


def _scrub(text: str, *secrets_: str) -> str:
    for s in secrets_:
        if s and len(s) >= 6:
            text = text.replace(s, "[secret]")
    return text


def _provider_message(resp: Response) -> str:
    j = resp.json()
    err = j.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error_user_msg") or err.get("type") or ""
    else:
        msg = j.get("error_description") or j.get("message") or (err if isinstance(err, str) else "")
    return str(msg)[:240]


def _ok(resp: Response, url: str, what: str, creds: dict | None = None, posted: bool | None = False) -> Response:
    if 200 <= resp.status < 300:
        return resp
    c = creds or {}
    msg = _scrub(_provider_message(resp), c.get("access_token", ""), c.get("client_secret", ""), c.get("refresh_token", ""))
    host = urllib.parse.urlsplit(url).netloc
    if resp.status in (401, 403):
        raise NotConnected(f"{what}: {host} answered {resp.status} ({msg or 'not authorised'}); "
                           f"run `teyla growth connect {c.get('network') or 'the network'}` again")
    # A 4xx is a refusal: nothing went live. A 5xx on the final call may have half-worked.
    raise PublishError(f"{what}: {host} answered {resp.status}" + (f" ({msg})" if msg else ""),
                       posted=False if 400 <= resp.status < 500 else posted)


def _form(d: dict) -> bytes:
    return urllib.parse.urlencode(d).encode("ascii")


def _q(url: str, **params) -> str:
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)


# --- OAuth -----------------------------------------------------------------------------------------------------

OAUTH = {
    "linkedin": dict(auth="https://www.linkedin.com/oauth/v2/authorization",
                     token="https://www.linkedin.com/oauth/v2/accessToken",
                     scope="openid profile w_member_social", loopback=True,
                     console="https://www.linkedin.com/developers/apps (product: Share on LinkedIn, and Sign In with LinkedIn using OpenID Connect)"),
    "threads": dict(auth="https://threads.net/oauth/authorize", token="https://graph.threads.net/oauth/access_token",
                    scope="threads_basic,threads_content_publish", loopback=False,
                    console="https://developers.facebook.com/apps (use case: Access the Threads API)"),
    "instagram": dict(auth="https://www.instagram.com/oauth/authorize", token="https://api.instagram.com/oauth/access_token",
                      scope="instagram_business_basic,instagram_business_content_publish", loopback=False,
                      console="https://developers.facebook.com/apps (Instagram API with Instagram Login; a professional account)"),
    "youtube": dict(auth="https://accounts.google.com/o/oauth2/v2/auth", token="https://oauth2.googleapis.com/token",
                    scope="https://www.googleapis.com/auth/youtube.upload", loopback=True,
                    console="https://console.cloud.google.com/apis/credentials (an OAuth client of type Desktop app; YouTube Data API v3 on)"),
}


def default_redirect(network: str, cfg_publish: dict | None = None) -> str:
    given = ((cfg_publish or {}).get("redirect") or {}).get(network) or ""
    if given:
        return given
    return f"http://127.0.0.1:{DEFAULT_PORT}/callback" if OAUTH[network]["loopback"] else ""


def is_loopback(uri: str) -> bool:
    p = urllib.parse.urlsplit(uri)
    return p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost") and bool(p.port)


def auth_url(network: str, client_id: str, redirect_uri: str, state: str, verifier: str = "") -> str:
    o = OAUTH[network]
    params = dict(client_id=client_id, redirect_uri=redirect_uri, response_type="code", scope=o["scope"], state=state)
    if network == "youtube":
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params.update(access_type="offline", prompt="consent", code_challenge=challenge, code_challenge_method="S256")
    return o["auth"] + "?" + urllib.parse.urlencode(params)


def parse_redirect(url: str, state: str) -> str:
    """The `code` from the address the browser landed on, after the state check."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url.strip()).query)
    if q.get("error"):
        raise NotConnected(f"the network refused: {q.get('error_description', q['error'])[0][:200]}")
    if (q.get("state") or [""])[0] != state:
        raise NotConnected("the state in the address does not match this run: start `teyla growth connect` again")
    code = (q.get("code") or [""])[0].removesuffix("#_")
    if not code:
        raise NotConnected("no `code` in that address: copy the whole address the browser landed on")
    return code


def wait_for_code(redirect_uri: str, state: str, timeout: int = CALLBACK_TIMEOUT_S) -> str:
    """A one-request server on the loopback address of the redirect. It answers one GET to the redirect path."""
    import http.server

    p = urllib.parse.urlsplit(redirect_uri)
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            if urllib.parse.urlsplit(self.path).path != (p.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            got["url"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Teyla got the answer. You can close this tab and go back to the terminal.\n")

        def log_message(self, *a):   # nothing about the request reaches a log
            pass

    srv = http.server.HTTPServer(("127.0.0.1", p.port), Handler)
    srv.timeout = 5
    deadline = time.time() + timeout
    try:
        while "url" not in got and time.time() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()
    if "url" not in got:
        raise NotConnected(f"no answer from the browser in {timeout // 60} minutes; run `teyla growth connect` again")
    return parse_redirect(got["url"], state)


def exchange(network: str, code: str, client_id: str, client_secret: str, redirect_uri: str, verifier: str = "",
             now: float | None = None, h: Callable = None) -> dict:
    """Trade the code for a token, then for a long-lived one where the network has it. Returns the credentials."""
    h = h or http
    now = time.time() if now is None else now
    o = OAUTH[network]
    form = dict(grant_type="authorization_code", code=code, redirect_uri=redirect_uri, client_id=client_id,
                client_secret=client_secret)
    if network == "youtube":
        form["code_verifier"] = verifier
    base = dict(network=network, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    r = _ok(h("POST", o["token"], headers={"Content-Type": "application/x-www-form-urlencoded"}, data=_form(form)),
            o["token"], "token exchange", base)
    j = r.json()
    if isinstance(j.get("data"), list) and j["data"]:      # the Instagram token answer may come wrapped
        j = j["data"][0]
    token = str(j.get("access_token") or "")
    if not token:
        raise NotConnected("the token answer had no access_token")
    creds = dict(base, access_token=token, refresh_token=str(j.get("refresh_token") or ""),
                 expires_at=now + float(j.get("expires_in") or 3600), connected_at=now, user=str(j.get("user_id") or ""))
    if network == "linkedin":
        r = _ok(h("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}),
                "https://api.linkedin.com/v2/userinfo", "member lookup", creds)
        sub = str(r.json().get("sub") or "")
        if not sub:
            raise NotConnected("LinkedIn did not name the member (no `sub`); is OpenID Connect on for the app?")
        creds["user"] = f"urn:li:person:{sub}"
    elif network in ("threads", "instagram"):
        host = "https://graph.threads.net" if network == "threads" else "https://graph.instagram.com"
        grant = "th_exchange_token" if network == "threads" else "ig_exchange_token"
        url = _q(f"{host}/access_token", grant_type=grant, client_secret=client_secret, access_token=token)
        r = _ok(h("GET", url), f"{host}/access_token", "long-lived token", creds)
        lj = r.json()
        if lj.get("access_token"):
            creds["access_token"] = str(lj["access_token"])
            creds["expires_at"] = now + float(lj.get("expires_in") or 60 * 86400)
        if not creds["user"]:
            raise NotConnected(f"{network} did not name the account (no user_id)")
    return creds


def refresh(creds: dict, now: float | None = None, h: Callable = None) -> tuple[dict, bool]:
    """Fresh credentials before a publish, and whether they changed. LinkedIn has no refresh for a member app:
    an expired token means connect again."""
    h = h or http
    now = time.time() if now is None else now
    net_ = creds.get("network")
    left = float(creds.get("expires_at") or 0) - now
    if net_ == "youtube":
        if left > 300:
            return creds, False
        if not creds.get("refresh_token"):
            raise NotConnected("the YouTube token expired and has no refresh token; run `teyla growth connect youtube`")
        url = OAUTH["youtube"]["token"]
        r = _ok(h("POST", url, headers={"Content-Type": "application/x-www-form-urlencoded"},
                  data=_form(dict(grant_type="refresh_token", refresh_token=creds["refresh_token"],
                                  client_id=creds.get("client_id", ""), client_secret=creds.get("client_secret", "")))),
                url, "token refresh", creds)
        j = r.json()
        return dict(creds, access_token=str(j.get("access_token") or ""), expires_at=now + float(j.get("expires_in") or 3600)), True
    if left <= 0:
        raise NotConnected(f"the {net_} token expired; run `teyla growth connect {net_}`")
    if net_ in ("threads", "instagram") and left < 30 * 86400 and now - float(creds.get("refreshed_at") or creds.get("connected_at") or 0) > 86400:
        host = "https://graph.threads.net" if net_ == "threads" else "https://graph.instagram.com"
        grant = "th_refresh_token" if net_ == "threads" else "ig_refresh_token"
        r = h("GET", _q(f"{host}/refresh_access_token", grant_type=grant, access_token=creds["access_token"]))
        if 200 <= r.status < 300 and r.json().get("access_token"):
            j = r.json()
            return dict(creds, access_token=str(j["access_token"]), expires_at=now + float(j.get("expires_in") or 60 * 86400),
                        refreshed_at=now), True
    return creds, False


# --- the adapters ----------------------------------------------------------------------------------------------

LINKEDIN_RESERVED = set("\\|{}@[]()<>#*_~")


def linkedin_text(text: str) -> str:
    """The Posts API reads `commentary` as little text: its reserved characters need a backslash."""
    return "".join("\\" + c if c in LINKEDIN_RESERVED else c for c in text)


def _video(item: dict) -> str:
    import pathlib
    for m in item.get("media") or []:
        p = pathlib.Path(m)
        if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".m4v"):
            return str(p)
    raise PublishError(f"{item.get('id')} has no video attached: `teyla growth attach {item.get('id')} <file>`")


def caption(item: dict) -> str:
    from . import growth
    text = str(item.get("body") or "")
    if item.get("dubbed") and growth.DUB_LABEL.get(item.get("language"), "") not in text:
        text += "\n\n" + growth.DUB_LABEL.get(item.get("language"), growth.DUB_LABEL["en"])
    return text


def publish_linkedin(item: dict, creds: dict, h: Callable, cfg_publish: dict) -> PublishResult:
    url = "https://api.linkedin.com/rest/posts"
    body = dict(author=creds["user"], commentary=linkedin_text(caption(item)), visibility="PUBLIC",
                distribution=dict(feedDistribution="MAIN_FEED", targetEntities=[], thirdPartyDistributionChannels=[]),
                lifecycleState="PUBLISHED", isReshareDisabledByAuthor=False)
    r = _ok(h("POST", url, headers={"Authorization": f"Bearer {creds['access_token']}", "Content-Type": "application/json",
                                    "LinkedIn-Version": LINKEDIN_VERSION, "X-Restli-Protocol-Version": "2.0.0"},
              data=json.dumps(body).encode("utf-8")), url, "LinkedIn post", creds, posted=None)
    urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or r.json().get("id") or ""
    if not urn:
        raise PublishError("LinkedIn accepted the post but returned no id; check your feed, then "
                           f"`teyla growth published {item.get('id')} <URL>`", posted=True)
    warn = "the first comment is not posted by the API; add it by hand" if item.get("first_comment") else ""
    return PublishResult(True, f"https://www.linkedin.com/feed/update/{urn}/", warn)


def publish_threads(item: dict, creds: dict, h: Callable, cfg_publish: dict) -> PublishResult:
    base = f"https://graph.threads.net/v1.0/{creds['user']}"
    tok = creds["access_token"]
    url = f"{base}/threads"
    r = _ok(h("POST", url, data=_form(dict(media_type="TEXT", text=caption(item)[:500], access_token=tok))),
            url, "Threads container", creds)
    cid = str(r.json().get("id") or "")
    if not cid:
        raise PublishError("Threads made no container")
    url = f"{base}/threads_publish"
    r = _ok(h("POST", url, data=_form(dict(creation_id=cid, access_token=tok))), url, "Threads publish", creds, posted=None)
    mid = str(r.json().get("id") or "")
    if not mid:
        raise PublishError("Threads published no id; check your profile", posted=None)
    link = _permalink(h, f"https://graph.threads.net/v1.0/{mid}", tok) or ""
    return PublishResult(True, link or f"https://www.threads.com/ (post id {mid})",
                         "" if link else "Threads gave no permalink; the id is recorded")


def _permalink(h: Callable, url: str, tok: str) -> str:
    try:
        r = h("GET", _q(url, fields="permalink", access_token=tok))
    except PublishError:
        return ""
    link = str(r.json().get("permalink") or "") if 200 <= r.status < 300 else ""
    return link if link.startswith("https://") else ""


def publish_instagram(item: dict, creds: dict, h: Callable, cfg_publish: dict, sleep: Callable = time.sleep) -> PublishResult:
    path = _video(item)
    size = os.path.getsize(path)
    tok = creds["access_token"]
    base = f"https://graph.instagram.com/{GRAPH_VERSION}/{creds['user']}"
    url = f"{base}/media"
    r = _ok(h("POST", url, data=_form(dict(media_type="REELS", upload_type="resumable", caption=caption(item)[:2200],
                                           access_token=tok))), url, "Instagram container", creds)
    j = r.json()
    cid, upload = str(j.get("id") or ""), str(j.get("uri") or "")
    if not cid:
        raise PublishError("Instagram made no container")
    upload = upload or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{cid}"
    if urllib.parse.urlsplit(upload).hostname != "rupload.facebook.com":
        raise PublishError("Instagram named an upload host Teyla does not send video to")
    with open(path, "rb") as f:
        data = f.read()
    _ok(h("POST", upload, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, data=data,
          timeout=UPLOAD_TIMEOUT_S), upload, "Instagram upload", creds)
    status = ""
    for _ in range(POLL_TRIES):
        r = _ok(h("GET", _q(f"https://graph.instagram.com/{GRAPH_VERSION}/{cid}", fields="status_code", access_token=tok)),
                "https://graph.instagram.com/", "Instagram status", creds)
        status = str(r.json().get("status_code") or "")
        if status in ("FINISHED", "ERROR", "EXPIRED"):
            break
        sleep(POLL_SLEEP_S)
    if status != "FINISHED":
        raise PublishError(f"Instagram did not finish the video ({status or 'no status'}); nothing was published")
    url = f"{base}/media_publish"
    r = _ok(h("POST", url, data=_form(dict(creation_id=cid, access_token=tok))), url, "Instagram publish", creds, posted=None)
    mid = str(r.json().get("id") or "")
    if not mid:
        raise PublishError("Instagram published no id; check your profile", posted=None)
    link = _permalink(h, f"https://graph.instagram.com/{GRAPH_VERSION}/{mid}", tok)
    return PublishResult(True, link or f"https://www.instagram.com/ (media id {mid})",
                         "" if link else "Instagram gave no permalink; the id is recorded")


def publish_youtube(item: dict, creds: dict, h: Callable, cfg_publish: dict) -> PublishResult:
    from . import growth
    path = _video(item)
    size = os.path.getsize(path)
    tok = creds["access_token"]
    lines = [ln.strip() for ln in str(item.get("body") or "").splitlines() if ln.strip()]
    first = str(item.get("hook") or "").strip() or (lines[0] if lines else str(item.get("id")))
    title = first[: growth.PLATFORMS["youtube"].get("title_limit", 100)]
    privacy = (cfg_publish or {}).get("youtube_privacy") or "public"
    meta = dict(snippet=dict(title=title, description=caption(item)[:5000], categoryId="28"),
                status=dict(privacyStatus=privacy, selfDeclaredMadeForKids=False))
    url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    r = _ok(h("POST", url, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                                    "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
              data=json.dumps(meta).encode("utf-8")), "https://www.googleapis.com/upload/youtube/v3/videos", "YouTube upload start", creds)
    loc = r.headers.get("location") or ""
    if urllib.parse.urlsplit(loc).hostname not in ("www.googleapis.com", "youtube.googleapis.com"):
        raise PublishError("YouTube named no upload address Teyla trusts")
    with open(path, "rb") as f:
        data = f.read()
    r = _ok(h("PUT", loc, headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"}, data=data,
              timeout=UPLOAD_TIMEOUT_S), "https://www.googleapis.com/upload/youtube/v3/videos", "YouTube upload", creds, posted=None)
    j = r.json()
    vid = str(j.get("id") or "")
    if not vid:
        raise PublishError("YouTube took the upload but returned no video id; check YouTube Studio", posted=None)
    got = str((j.get("status") or {}).get("privacyStatus") or privacy)
    warn = ""
    if got != privacy:
        warn = (f"YouTube set the video to {got}, not {privacy}: an API project YouTube has not audited may only upload "
                "private videos (docs/GROWTH.md, Publishing)")
    return PublishResult(True, f"https://www.youtube.com/shorts/{vid}", warn)


class XStub:
    """X stays manual. The paid API needs the owner's two yeses (POLICY section 11). Without `x_paid = true` in the
    growth config this refuses; with it, it still refuses, because no adapter is built. It makes no call."""

    def check(self, cfg_publish: dict) -> None:
        if not (cfg_publish or {}).get("x_paid"):
            raise PublishRefused("X stays manual: its API is paid and needs your two yeses (POLICY section 11)")
        raise PublishRefused("x_paid = true is set, but no X adapter is built yet; X stays manual")


ADAPTERS: dict[str, Callable] = {"linkedin": publish_linkedin, "threads": publish_threads,
                                 "instagram": publish_instagram, "youtube": publish_youtube}


# --- the run ---------------------------------------------------------------------------------------------------

def idem_key(item_id: str, network: str) -> str:
    return hashlib.sha256(f"{item_id}|{network}".encode()).hexdigest()[:16]


def _idem_state(store, idem: str) -> tuple[str, str]:
    """What the ledger says about this idem key: ("published", url), ("open", "") after a start with no end,
    ("failed", "") or ("", "")."""
    state, url = "", ""
    for r in store.ledger():
        if r.get("idem") != idem:
            continue
        ev = r.get("ev")
        if ev == "published":
            return "published", str(r.get("url") or "")
        if ev == "publish-start":
            state = "open"
        elif ev == "publish-failed":
            state = "failed"
        elif ev == "publish-unknown":
            state = "open"
    return state, url


def targets(store, refs: list[str], day: str | None) -> list[dict]:
    """The items a publish run covers: the ids given (a master idea stands for its approved channel items) or a day's
    approved items."""
    from . import growth
    items = store.items()
    out: list[dict] = []
    if day:
        out = [i for i in items.values() if i.get("day") == day and i["status"] in PUBLISHABLE
               and i.get("platform") not in (growth.MASTER, "") and i.get("kind") != "episode"]
    for ref in refs:
        it = store.get(ref)
        if it.get("platform") == growth.MASTER or it.get("kind") == "episode":
            out += [i for i in items.values() if i.get("parent") == it["id"] and i["status"] in PUBLISHABLE]
        else:
            out.append(it)
    seen, uniq = set(), []
    for i in sorted(out, key=lambda i: (i.get("day") or "", i.get("channel") or "", i["id"])):
        if i["id"] not in seen:
            seen.add(i["id"])
            uniq.append(i)
    return uniq


def _fallback(store, cfg, it, now, row: dict, why: str) -> dict:
    from . import growth
    try:
        path = growth.packet(store, it["id"], now, cfg=cfg)
        row.update(status="packet", packet=str(path),
                   message=f"{why}. Packet: {path}. Post it by hand, then `teyla growth published {it['id']} <URL>`")
    except growth.GrowthError as e:
        row.update(status="refused", message=f"{why}; no packet either: {e}")
    return row


def publish_one(store, cfg, it: dict, now: float, *, retry: bool = False, h: Callable | None = None,
                adapters: dict | None = None) -> dict:
    from . import growth, net
    h = h or http
    adapters = adapters or ADAPTERS
    network = str(it.get("platform") or "")
    cp = cfg.get("publish") or {}
    row = dict(id=it["id"], network=network, status="", url="", message="", warning="")
    if it["status"] == "published":
        return dict(row, status="already", url=it.get("published_url", ""), message="already published")
    if it["status"] not in PUBLISHABLE:
        return dict(row, status="refused", message=f"{it['id']} is {it['status']}: only an approved item is published")
    if network == "x":
        try:
            XStub().check(cp)
        except PublishRefused as e:
            return _fallback(store, cfg, it, now, row, str(e))
    if network not in adapters:
        return _fallback(store, cfg, it, now, row, f"{network} has no API adapter; it stays manual")
    if network in TEXT_ONLY and it.get("media"):
        return _fallback(store, cfg, it, now, row, f"{network} publishing sends text only and this item has media attached; "
                                                     "post it from the packet")
    idem = idem_key(it["id"], network)
    row["idem"] = idem
    with _idem_lock(store, idem) as held:
        if not held:
            return dict(row, status="unknown", message=f"another publish of {it['id']} to {network} is running now; "
                                                        "wait for it, then check the ledger")
        return _publish_locked(store, cfg, it, now, row, network, idem, retry=retry, h=h, adapters=adapters, cp=cp)


@contextlib.contextmanager
def _idem_lock(store, idem: str):
    """One publish per item and network at a time, across processes: the ledger check and the `publish-start` row
    happen under an exclusive, non-blocking lock. A second run while the first holds it is told so and posts nothing."""
    from . import growth
    folder = store.root / "locks"
    growth._private_dir(folder)
    fd = os.open(folder / f"publish-{idem}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _publish_locked(store, cfg, it, now, row, network, idem, *, retry, h, adapters, cp) -> dict:
    from . import growth, net
    state, url = _idem_state(store, idem)
    if state == "published":
        return dict(row, status="already", url=url, message="already published (ledger)")
    if state == "open" and not retry:
        return dict(row, status="unknown", message=(
            f"an earlier publish of {it['id']} to {network} started and never finished. Check {network}: if the post is "
            f"live, `teyla growth published {it['id']} <URL>`; if not, run `teyla growth publish {it['id']} --retry`"))
    creds = load_creds(network)
    if not creds:
        return _fallback(store, cfg, it, now, row, f"{network} is not connected (`teyla growth connect {network}`)")
    if not net.allowed():
        return _fallback(store, cfg, it, now, row, "safe mode is on, so nothing leaves this Mac (`--allow-network` opens it once)")
    hits = growth.Guard(cfg).check(it.get("body", ""), it.get("hook", ""), it.get("script", ""), it.get("first_comment", ""))
    if hits:
        return dict(row, status="refused", message=f"blocked at publish time: {growth.kinds_text(hits)}")
    try:
        creds, changed = refresh(dict(creds, network=network), now, h)
        if changed:
            save_creds(network, creds)
    except NotConnected as e:
        return _fallback(store, cfg, it, now, row, str(e))
    except PublishError as e:                                # the token refresh failed; nothing was posted
        return dict(row, status="failed", message=f"could not refresh the {network} token: {e}")
    store.log("publish-start", now, id=it["id"], platform=network, idem=idem)
    try:
        res = adapters[network](it, creds, h, cp)
    except NotConnected as e:
        store.log("publish-failed", now, id=it["id"], platform=network, idem=idem, reason=str(e)[:300])
        return _fallback(store, cfg, it, now, row, str(e))
    except PublishError as e:
        ev = "publish-unknown" if e.posted is not False else "publish-failed"
        store.log(ev, now, id=it["id"], platform=network, idem=idem, reason=str(e)[:300])
        if e.posted is not False:
            return dict(row, status="unknown", message=f"{e}. It may be live: check {network} before you run it again")
        return dict(row, status="failed", message=str(e))
    growth.set_status(store, it, "published", now, published_url=res.url, published_at=growth.iso(now),
                      published_by=network, published_via="api", publish_idem=idem)
    store.log("published", now, id=it["id"], product=it.get("product"), platform=network, language=it.get("language"),
              url=res.url, by="owner-approved", via="api", idem=idem)
    return dict(row, status="published", url=res.url, warning=res.warning, message="published")


def publish_many(store, cfg, items: list[dict], now: float, **kw) -> dict:
    rows = [publish_one(store, cfg, it, now, **kw) for it in items]
    count = lambda s: sum(1 for r in rows if r["status"] == s)
    return dict(version=1, results=rows, published=count("published"), already=count("already"), packets=count("packet"),
                failed=count("failed") + count("refused") + count("unknown"))


def render(doc: dict) -> str:
    if not doc["results"]:
        return "nothing to publish: no approved item matches\n"
    out = []
    for r in doc["results"]:
        line = f"  {r['id']}  {r['network']:<10} {r['status']:<9} " + (r["url"] or r["message"])
        if r["url"] and r["message"] not in ("published", ""):
            line += f"  ({r['message']})"
        out.append(line)
        if r.get("warning"):
            out.append(f"      note: {r['warning']}")
    out.append(f"{doc['published']} published, {doc['already']} already, {doc['packets']} to post by hand, {doc['failed']} need you")
    return "\n".join(out) + "\n"


# --- connect -----------------------------------------------------------------------------------------------------

def status_rows(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    rows = []
    for n in NETWORKS:
        c = load_creds(n)
        if not c:
            rows.append(dict(network=n, connected=False, detail=f"teyla growth connect {n}"))
            continue
        days = int((float(c.get("expires_at") or 0) - now) // 86400)
        renew = n == "youtube" and c.get("refresh_token")
        rows.append(dict(network=n, connected=True,
                         detail="renews itself" if renew else (f"expires in {days} days" if days >= 0 else "expired: connect again")))
    rows.append(dict(network="x", connected=False, detail="manual: the paid API needs your two yeses (POLICY section 11)"))
    return rows


def connect(network: str, cfg: dict, *, redirect_uri: str = "", paste: bool = False, now: float | None = None,
            ask: Callable = input, ask_secret: Callable | None = None, opener: Callable | None = None,
            wait: Callable = wait_for_code, h: Callable | None = None, out=sys.stdout) -> dict:
    """The owner's OAuth flow. Asks for the app's client id and secret (the secret through getpass), opens the consent
    page, takes the answer on the loopback address or as a pasted address, and stores the credentials in the Keychain."""
    import getpass
    import webbrowser
    ask_secret = ask_secret or getpass.getpass
    opener = opener or webbrowser.open
    cp = cfg.get("publish") or {}
    if network == "x":
        XStub().check(cp)
    if network not in NETWORKS:
        raise NotConnected(f"no adapter for {network}; the networks are {', '.join(NETWORKS)}")
    o = OAUTH[network]
    redirect = redirect_uri or default_redirect(network, cp)
    if not redirect:
        raise NotConnected(f"{network} needs an https redirect address you registered in the app: pass --redirect-uri "
                           f"https://... or set [publish.redirect] {network} = \"https://...\" in ~/.teyla/growth/config.toml")
    if not redirect.startswith("https://") and not is_loopback(redirect):
        raise NotConnected("the redirect address must be https:// or a loopback http://127.0.0.1:<port>/... address")
    old = load_creds(network) or {}
    print(f"Connect {network}. The app comes from {o['console']}.", file=out)
    print(f"Its redirect address must be exactly: {redirect}", file=out)
    client_id = (ask(f"Client id{' [' + old['client_id'] + ']' if old.get('client_id') else ''}: ") or "").strip() or old.get("client_id", "")
    client_secret = (ask_secret("Client secret (hidden; Enter keeps the stored one): ") or "").strip() or old.get("client_secret", "")
    if not client_id or not client_secret:
        raise NotConnected("a client id and a client secret are needed")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48) if network == "youtube" else ""
    url = auth_url(network, client_id, redirect, state, verifier)
    print("Opening the consent page in your browser. Sign in and allow; Teyla never sees your password.", file=out)
    print(f"If it does not open: {url}", file=out)
    opener(url)
    if is_loopback(redirect) and not paste:
        code = wait(redirect, state)
    else:
        code = parse_redirect(ask("Paste the whole address the browser landed on: "), state)
    creds = exchange(network, code, client_id, client_secret, redirect, verifier, now, h)
    save_creds(network, creds)
    return dict(network=network, user=creds.get("user", ""), expires_at=creds.get("expires_at"))
