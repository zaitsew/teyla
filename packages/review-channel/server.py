#!/usr/bin/env python3
"""The shared review channel: a write-only drop box for test-build feedback captures.

A tester's build PUTs `capture.json` and `capture.png` here. The owner's Mac moves them out
(`teyla review pull --channel`). Nothing can be read, listed or deleted over HTTP.

    PUT /v1/captures/<uuid>/capture.png    Authorization: Bearer <key>
    PUT /v1/captures/<uuid>/capture.json   Authorization: Bearer <key>
    OPTIONS (the same paths)               CORS for web builds
    GET /healthz                           200

A key belongs to one product. The key decides the product, and `app.product` in the JSON must equal it.
Files land in `incoming/<product>/<id>/` under temporary names. When both are there and the picture
matches `screenshot.sha256`, the folder is renamed to `ready/<product>/<id>/`, which is what the Mac reads.

Environment: RC_DATA (default /data), RC_KEYS (default /keys/keys.txt), RC_PORT (8080), RC_BIND (0.0.0.0).
The keys file holds one `<sha256 hex of the key> <product slug>` per line; it is read again when it changes.

Python 3 standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

MIB = 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PUT_PATH = re.compile(rf"^/v1/captures/({UUID})/(capture\.png|capture\.json)$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA_FIELD = re.compile(r"^[0-9a-fA-F]{64}$")
DRAIN_MAX = MIB          # a refused request this small has its body read and dropped, so the client sees the answer


@dataclass
class Config:
    data: str
    keys: str
    max_png: int = 10 * MIB
    max_json: int = 1 * MIB
    per_product_day: int = 20
    total_day: int = 100
    max_bytes: int = 500 * MIB
    max_concurrent: int = 8
    timeout: float = 30.0
    body_deadline: float = 120.0
    incoming_ttl: float = 24 * 3600
    sweep_every: float = 600.0
    clock: Callable[[], float] = field(default=time.time, repr=False)


class Keys:
    """sha256(key) hex -> product slug, from a file that is read again when its mtime changes."""

    def __init__(self, path: str):
        self.path = path
        self._sig: tuple | None = None
        self._map: dict[str, str] = {}
        self._lock = threading.Lock()

    def lookup(self, digest: str) -> str | None:
        try:
            st = os.stat(self.path)
            sig: tuple | None = (st.st_mtime_ns, st.st_ino, st.st_size)
        except OSError:
            sig = None
        with self._lock:
            if sig != self._sig:
                self._map = self._read() if sig is not None else {}
                self._sig = sig
            return self._map.get(digest)

    def _read(self) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2 and HEX64.match(parts[0]) and SLUG.match(parts[1]):
                        out[parts[0]] = parts[1]
        except (OSError, UnicodeDecodeError):
            return {}
        return out


def _mkdir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _tree_bytes(root: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


class Store:
    """Where captures live, and the caps. One lock reserves a capture before its body is read."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.incoming = os.path.join(cfg.data, "incoming")
        self.ready = os.path.join(cfg.data, "ready")
        self.state = os.path.join(cfg.data, "state")
        for d in (cfg.data, self.incoming, self.ready, self.state):
            _mkdir(d)
        self.lock = threading.Lock()          # counters and the byte budget
        self.commit_lock = threading.Lock()   # writing a file and moving a folder to ready
        self.inflight = 0
        self.counts: dict = {}
        self._load()

    # --- the daily counters, kept across restarts ---
    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.cfg.clock()))

    def _fresh(self) -> dict:
        return {"day": self._day(), "total": 0, "products": {}, "ids": []}

    def _load(self) -> None:
        try:
            with open(os.path.join(self.state, "counters.json"), encoding="utf-8") as f:
                c = json.load(f)
            ok = (isinstance(c, dict) and isinstance(c.get("day"), str) and isinstance(c.get("total"), int)
                  and isinstance(c.get("products"), dict) and isinstance(c.get("ids"), list))
            self.counts = c if ok else self._fresh()
        except (OSError, ValueError):
            self.counts = self._fresh()

    def _save(self) -> None:
        path = os.path.join(self.state, "counters.json")
        tmp = f"{path}.{secrets.token_hex(4)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.counts, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def usage(self) -> int:
        return _tree_bytes(self.ready) + _tree_bytes(self.incoming)

    def ready_dir(self, product: str, cid: str) -> str:
        return os.path.join(self.ready, product, cid)

    def incoming_dir(self, product: str, cid: str) -> str:
        return os.path.join(self.incoming, product, cid)

    def reserve(self, product: str, cid: str, length: int) -> str:
        """"ready" (already delivered, count nothing), "rate" (429), "full" (507) or "ok"."""
        with self.lock:
            if os.path.isdir(self.ready_dir(product, cid)):
                return "ready"
            if self.counts.get("day") != self._day():
                self.counts = self._fresh()
            key = f"{product}/{cid}"
            new = key not in self.counts["ids"] and not os.path.isdir(self.incoming_dir(product, cid))
            if new and (self.counts["products"].get(product, 0) >= self.cfg.per_product_day
                        or self.counts["total"] >= self.cfg.total_day):
                return "rate"
            if self.usage() + self.inflight + length > self.cfg.max_bytes:
                return "full"
            if new:
                self.counts["ids"].append(key)
                self.counts["products"][product] = self.counts["products"].get(product, 0) + 1
                self.counts["total"] += 1
                self._save()
            self.inflight += length
            return "ok"

    def release(self, length: int) -> None:
        with self.lock:
            self.inflight = max(0, self.inflight - length)

    def put(self, product: str, cid: str, name: str, body: bytes) -> str:
        """"stored", "complete" (the capture moved to ready), "ready" (it was there already) or "mismatch"."""
        d_in, d_ready = self.incoming_dir(product, cid), self.ready_dir(product, cid)
        with self.commit_lock:
            if os.path.isdir(d_ready):
                return "ready"
            _mkdir(os.path.join(self.incoming, product))
            _mkdir(d_in)
            tmp = os.path.join(d_in, f".{name}.{secrets.token_hex(6)}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(body)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, os.path.join(d_in, name))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            png, js = os.path.join(d_in, "capture.png"), os.path.join(d_in, "capture.json")
            if not (os.path.isfile(png) and os.path.isfile(js)):
                return "stored"
            with open(js, "rb") as f:
                want = json.loads(f.read().decode("utf-8")).get("screenshot", {}).get("sha256", "").lower()
            h = hashlib.sha256()
            with open(png, "rb") as f:
                for block in iter(lambda: f.read(MIB), b""):
                    h.update(block)
            if h.hexdigest() != want:
                shutil.rmtree(d_in, ignore_errors=True)
                return "mismatch"
            _mkdir(os.path.join(self.ready, product))
            os.rename(d_in, d_ready)
            return "complete"

    def sweep(self) -> int:
        """Remove incoming folders nothing has touched for the TTL. Returns how many."""
        now, gone = self.cfg.clock(), 0
        try:
            products = os.listdir(self.incoming)
        except OSError:
            return 0
        for p in products:
            pdir = os.path.join(self.incoming, p)
            try:
                ids = os.listdir(pdir)
            except OSError:
                continue
            for cid in ids:
                d = os.path.join(pdir, cid)
                try:
                    newest = max([os.lstat(d).st_mtime] + [os.lstat(os.path.join(d, n)).st_mtime for n in os.listdir(d)])
                except OSError:
                    continue
                if now - newest > self.cfg.incoming_ttl:
                    with self.commit_lock:
                        shutil.rmtree(d, ignore_errors=True)
                    gone += 1
        return gone


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg)
        self.keys = Keys(cfg.keys)
        self.slots = threading.BoundedSemaphore(cfg.max_concurrent)
        self._stop = threading.Event()
        super().__init__(addr, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n"
                                b"Connection: close\r\nRetry-After: 5\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            print("- - - 503", file=sys.stderr, flush=True)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def start_sweeper(self) -> None:
        def loop() -> None:
            while True:
                try:
                    self.store.sweep()
                except Exception as e:  # noqa: BLE001 - the sweep must never end
                    print(f"sweep failed: {type(e).__name__}", file=sys.stderr, flush=True)
                if self._stop.wait(self.cfg.sweep_every):
                    return
        threading.Thread(target=loop, daemon=True, name="sweep").start()

    def server_close(self) -> None:
        self._stop.set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "review-channel"
    sys_version = ""
    protocol_version = "HTTP/1.0"          # one request per connection

    def setup(self) -> None:
        self.timeout = self.server.cfg.timeout
        super().setup()

    def log_message(self, *args) -> None:  # the access log is ours, below: no path, no header, no comment
        pass

    def handle_expect_100(self) -> bool:
        return True                         # 100 Continue goes out only after the request passed its checks

    # --- answers ---
    def reply(self, status: int, text: str = "", **headers) -> None:
        body = text.encode("ascii")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.send_header("Content-Type", "text/plain; charset=us-ascii")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
        self._log(status)

    def _log(self, status: int) -> None:
        print(f"{self.command} {getattr(self, 'cid8', '-')} {getattr(self, 'product', '-')} {status}",
              file=sys.stderr, flush=True)

    def _drain(self, length: int) -> None:
        if 0 < length <= DRAIN_MAX:
            try:
                self._read_body(length)
            except (OSError, ConnectionError):
                pass

    def _read_body(self, n: int) -> bytes:
        buf, deadline = bytearray(), time.monotonic() + self.server.cfg.body_deadline
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError("body too slow")
            chunk = self.rfile.read1(min(65536, n - len(buf)))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return bytes(buf)

    # --- methods ---
    def _no(self) -> None:
        self.reply(405, "method not allowed", Allow="PUT, OPTIONS")

    do_HEAD = do_POST = do_DELETE = do_PATCH = do_TRACE = do_CONNECT = _no

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.reply(200, "ok")
        else:
            self._no()

    def do_OPTIONS(self) -> None:
        if not PUT_PATH.match(self.path):
            return self._no()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "PUT")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self._log(204)

    def _auth(self) -> str | None:
        head = self.headers.get("Authorization", "")
        if len(head) > 300 or not head.startswith("Bearer ") or not head[7:].strip():
            return None
        return self.server.keys.lookup(hashlib.sha256(head[7:].strip().encode("utf-8", "replace")).hexdigest())

    def do_PUT(self) -> None:
        m = PUT_PATH.match(self.path)
        if not m:
            return self._no()
        cid, name = m.groups()
        self.cid8 = cid[:8]
        cfg, store = self.server.cfg, self.server.store
        raw_len = self.headers.get("Content-Length")
        try:
            length = int(raw_len) if raw_len is not None and raw_len.isascii() and raw_len.isdigit() else -1
        except ValueError:
            length = -1
        product = self._auth()
        if product is None:
            self.reply(401, "unauthorized")
            return self._drain(length)
        self.product = product
        if self.headers.get("Transfer-Encoding") or raw_len is None:
            return self.reply(411, "content-length required")
        if length < 0:
            return self.reply(400, "bad content-length")
        limit = cfg.max_png if name == "capture.png" else cfg.max_json
        if length > limit:
            return self.reply(413, "too large")
        verdict = store.reserve(product, cid, length)
        if verdict == "ready":
            self.reply(200, "ok")
            return self._drain(length)
        if verdict != "ok":
            self.reply(429 if verdict == "rate" else 507, "daily limit reached" if verdict == "rate" else "storage full")
            return self._drain(length)
        try:
            if (self.headers.get("Expect") or "").lower() == "100-continue":
                self.send_response_only(100)
                self.end_headers()
            try:
                body = self._read_body(length)
            except (OSError, ConnectionError):
                self.close_connection = True
                return self._log(408)
            status, text = self._accept(product, cid, name, body)
            self.reply(status, text)
        finally:
            store.release(length)

    def _accept(self, product: str, cid: str, name: str, body: bytes) -> tuple[int, str]:
        if name == "capture.png":
            if not body.startswith(PNG_MAGIC):
                return 400, "not a png"
        else:
            try:
                obj = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return 400, "not json"
            if not isinstance(obj, dict) or obj.get("v") != 1 or isinstance(obj.get("v"), bool):
                return 400, "v must be 1"
            if obj.get("id") != cid:
                return 400, "id must equal the path"
            app = obj.get("app")
            if not isinstance(app, dict) or app.get("product") != product:
                return 403, "product mismatch"
            shot = obj.get("screenshot")
            if not isinstance(shot, dict) or not isinstance(shot.get("sha256"), str) or not SHA_FIELD.match(shot["sha256"]):
                return 400, "screenshot.sha256 missing"
        try:
            result = self.server.store.put(product, cid, name, body)
        except OSError:
            return 500, "could not store"
        if result == "mismatch":
            return 422, "picture does not match screenshot.sha256"
        return 200, "ok"


def make_server(cfg: Config, host: str = "127.0.0.1", port: int = 0) -> Server:
    return Server((host, port), cfg)


def main() -> int:
    cfg = Config(data=os.environ.get("RC_DATA", "/data"), keys=os.environ.get("RC_KEYS", "/keys/keys.txt"))
    srv = make_server(cfg, os.environ.get("RC_BIND", "0.0.0.0"), int(os.environ.get("RC_PORT", "8080")))
    srv.start_sweeper()
    print(f"review-channel listening on {srv.server_address[1]}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
