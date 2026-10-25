"""The HTTP layer of `teyla web`: a stdlib server on 127.0.0.1 that only answers the person who started it.

Five checks, in this order, on every request. A request that fails one gets a JSON `{"error"}` and a 4xx:

1. `Host` must be `127.0.0.1:<port>` or `localhost:<port>`. A web page on another site that points a DNS
   name at 127.0.0.1 (DNS rebinding) arrives with its own name in `Host` and is refused.
2. The token. `GET /?t=<token>` swaps the token for an HttpOnly, SameSite=Strict cookie and redirects, so
   the token leaves the address bar and the history. Every other request must carry that cookie.
3. A POST also needs `X-Teyla-Token: <token>`. The page reads the token from a `<meta>` tag it was served;
   another site cannot read that page (no CORS headers, SameSite=Strict cookie), so it cannot send the header.
4. A POST that names an `Origin` must name this server.
5. A POST body is JSON, at most 64 KB.

The socket is bound to 127.0.0.1 and never to 0.0.0.0. The server stops on Ctrl-C and on its own after
`IDLE_S` seconds without a request.
"""
from __future__ import annotations

import hmac
import json
import os
import pathlib
import secrets
import sys
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import api as api_mod

IDLE_S = 2 * 60 * 60
WATCH_S = 5.0
MAX_BODY = 64 * 1024
COOKIE = "teyla_web"            # the name gets the port: a cookie is shared by every port of 127.0.0.1
STATIC = pathlib.Path(__file__).parent
FILES = {"/app.js": ("app.js", "text/javascript; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0, token: str | None = None, idle_s: float = IDLE_S, watch_s: float = WATCH_S,
                 api: api_mod.Api | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token or secrets.token_urlsafe(32)
        self.port = self.server_address[1]
        self.cookie = f"{COOKIE}_{self.port}"
        self.api = api or api_mod.Api()
        self.idle_s, self.watch_s = idle_s, watch_s
        self.last_request = time.monotonic()
        self.idle_stopped = False
        self._stop = threading.Event()

    # -- the lifetime --

    def touch(self) -> None:
        self.last_request = time.monotonic()

    def url(self, with_token: bool = True) -> str:
        return f"http://127.0.0.1:{self.port}/" + (f"?t={self.token}" if with_token else "")

    def hosts(self) -> set:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _watch(self) -> None:
        while not self._stop.wait(self.watch_s):
            if time.monotonic() - self.last_request > self.idle_s:
                self.idle_stopped = True
                threading.Thread(target=self.shutdown, daemon=True).start()
                return

    def serve(self) -> None:
        """Serve until Ctrl-C (KeyboardInterrupt propagates), `shutdown()` or the idle timer."""
        threading.Thread(target=self._watch, name="teyla-web-idle", daemon=True).start()
        try:
            self.serve_forever(poll_interval=0.2)
        finally:
            self._stop.set()
            self.server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "teyla-web"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, fmt, *args):  # the terminal belongs to the person who started it
        pass

    # -- answering --

    def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj, headers: dict | None = None) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8", headers)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    # -- the checks --

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").lower() in self.server.hosts()

    def _cookie_ok(self) -> bool:
        raw = self.headers.get("Cookie") or ""
        try:
            jar = SimpleCookie(raw)
        except Exception:  # noqa: BLE001 — a malformed Cookie header is no cookie
            return False
        m = jar.get(self.server.cookie)
        return bool(m) and hmac.compare_digest(m.value.encode(), self.server.token.encode())

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.lower() in {f"http://{h}" for h in self.server.hosts()}

    def _read_body(self) -> dict | None:
        """The JSON object of a POST; None after an error has been sent."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(400, "Content-Length is not a number")
            return None
        if n > MAX_BODY:
            self._error(413, f"the body is over {MAX_BODY // 1024} KB")
            self.close_connection = True
            return None
        raw = self.rfile.read(n) if n else b""
        if not raw.strip():
            return {}
        if "json" not in (self.headers.get("Content-Type") or "").lower():
            self._error(415, "send JSON with Content-Type: application/json")
            return None
        try:
            body = json.loads(raw)
        except ValueError:
            self._error(400, "the body is not valid JSON")
            return None
        if not isinstance(body, dict):
            self._error(400, "the body must be a JSON object")
            return None
        return body

    # -- the request --

    def _handle(self) -> None:
        srv: Server = self.server
        srv.touch()
        if not self._host_ok():
            return self._error(403, f"this server answers 127.0.0.1:{srv.port} and localhost:{srv.port} only")
        url = urlsplit(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        if self.command == "GET" and url.path == "/" and "t" in query:
            if not hmac.compare_digest(query["t"][0].encode(), srv.token.encode()):
                return self._error(403, "wrong token: open the address `teyla web` printed")
            return self._send(302, b"", "text/plain", {
                "Location": "/", "Set-Cookie": f"{srv.cookie}={srv.token}; HttpOnly; SameSite=Strict; Path=/"})
        if not self._cookie_ok():
            return self._error(403, "no token: open the address `teyla web` printed, with ?t=... at the end")
        body: dict = {}
        if self.command == "POST":
            if not hmac.compare_digest((self.headers.get("X-Teyla-Token") or "").encode(), srv.token.encode()):
                return self._error(403, "a POST needs the X-Teyla-Token header")
            if not self._origin_ok():
                return self._error(403, "this Origin is not this server")
            body = self._read_body()
            if body is None:
                return
        if self.command == "GET" and url.path == "/":
            page = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", srv.token)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if self.command == "GET" and url.path in FILES:
            name, ctype = FILES[url.path]
            return self._send(200, (STATIC / name).read_bytes(), ctype)
        if url.path.startswith("/api/"):
            status, obj = srv.api.route(self.command, url.path, query, body)
            return self._json(status, obj)
        self._error(404, f"no such page: {url.path}")

    def _dispatch(self) -> None:
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:  # noqa: BLE001 — a page gets a sentence, never a traceback
            if os.environ.get("TEYLA_DEBUG"):
                traceback.print_exc()
            try:
                self._error(500, f"internal error ({type(e).__name__}). Start `teyla web` with TEYLA_DEBUG=1 to see it in this terminal.")
            except Exception:  # noqa: BLE001
                self.close_connection = True

    do_GET = do_POST = _dispatch

    def _not_allowed(self) -> None:
        self.server.touch()
        self._error(405, f"{self.command} is not supported")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _not_allowed


def _span(seconds: float) -> str:
    return f"{seconds / 3600:g} hours" if seconds >= 3600 else f"{seconds:g} seconds"


def run(port: int = 0, open_browser: bool = True, idle_s: float = IDLE_S) -> int:
    try:
        srv = Server(port=port, idle_s=idle_s)
    except OSError as e:
        if port:
            print(f"teyla: cannot listen on port {port} ({e.strerror or e}). Leave out --port to pick a free one.", file=sys.stderr)
        else:
            print(f"teyla: cannot open a local port ({e.strerror or e}).", file=sys.stderr)
        return 1
    print(f"Teyla web: {srv.url()}")
    print("It listens on 127.0.0.1 only, and nothing leaves this machine.")
    print(f"It stops on Ctrl-C, or on its own after {_span(idle_s)} with no request.")
    if open_browser:
        import webbrowser
        try:
            webbrowser.open(srv.url())
        except Exception:  # noqa: BLE001 — the address is printed above
            pass
    try:
        srv.serve()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    if srv.idle_stopped:
        print(f"Stopped: no request for {_span(idle_s)}.")
    return 0
