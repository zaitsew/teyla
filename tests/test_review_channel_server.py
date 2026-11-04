"""packages/review-channel/server.py against a real server on a local port: auth, the product rule, size limits,
the picture hash, duplicates, every cap, counts across a restart, the sweep, and nothing readable over HTTP."""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import os
import pathlib
import socket
import stat
import threading
import time

import pytest
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_channel_server", ROOT / "packages" / "review-channel" / "server.py")
rc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rc
spec.loader.exec_module(rc)

PNG = rc.PNG_MAGIC + b"fake picture bytes " * 8
SHA = hashlib.sha256(PNG).hexdigest()
KEY_A, KEY_B = "key-for-alpha-0123456789", "key-for-beta-0123456789"
COMMENT = "A tester wrote this private sentence."


def uid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def capture(cid: str, product: str = "alpha", sha: str = SHA, **over) -> bytes:
    d = {"v": 1, "id": cid, "created": "2026-11-04T10:00:00Z",
         "app": {"bundle_id": f"com.example.{product}", "product": product, "name": "Sample", "version": "1.0", "build": "3"},
         "screen": "sample.list", "comment": {"text": COMMENT, "input": "text", "language": "en"},
         "screenshot": {"file": "capture.png", "width": 10, "height": 10, "scale": 1, "sha256": sha}}
    d.update(over)
    return json.dumps(d).encode()


class Box:
    def __init__(self, tmp: pathlib.Path, **over):
        self.tmp = tmp
        self.keys = tmp / "keys" / "keys.txt"
        self.keys.parent.mkdir(exist_ok=True)
        self.keys.write_text(f"{digest(KEY_A)} alpha\n{digest(KEY_B)} beta\n")
        self.now = [1_793_000_000.0]
        self.over = over
        self.start()

    def start(self):
        cfg = rc.Config(data=str(self.tmp / "data"), keys=str(self.keys), clock=lambda: self.now[0], **self.over)
        self.srv = rc.make_server(cfg)
        self.port = self.srv.server_address[1]
        threading.Thread(target=lambda: self.srv.serve_forever(poll_interval=0.02), daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, body=b"", key=KEY_A, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if key:
            h["Authorization"] = f"Bearer {key}"
        c.request(method, path, body=body if method in ("PUT", "POST") else None, headers=h)
        r = c.getresponse()
        out = r.status, r.read().decode(), dict(r.getheaders())
        c.close()
        return out

    def put(self, cid, name, body, key=KEY_A):
        return self.req("PUT", f"/v1/captures/{cid}/{name}", body, key)

    def send_both(self, cid, product="alpha", key=KEY_A):
        s1 = self.put(cid, "capture.json", capture(cid, product), key)[0]
        s2 = self.put(cid, "capture.png", PNG, key)[0]
        return s1, s2

    def ready(self, product, cid):
        return pathlib.Path(self.tmp / "data" / "ready" / product / cid)

    def incoming(self, product, cid):
        return pathlib.Path(self.tmp / "data" / "incoming" / product / cid)

    def header_only(self, method, path, length, key=KEY_A):
        """A request that promises a body and never sends it: the server must answer without reading."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        lines = [f"{method} {path} HTTP/1.1", "Host: x", f"Authorization: Bearer {key}"]
        if length is not None:
            lines.append(f"Content-Length: {length}")
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = s.recv(4096).decode()
        s.close()
        return int(data.split()[1])


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path)
    yield b
    b.stop()


def test_healthz(box):
    assert box.req("GET", "/healthz", key=None)[0] == 200


def test_an_unknown_key_gets_one_fixed_answer(box):
    a = box.put(uid(1), "capture.png", PNG, key="not-a-key")
    b = box.req("PUT", f"/v1/captures/{uid(1)}/capture.png", PNG, key=None)
    assert box.put(uid(1), "capture.png", PNG, key="")[0] == 401
    assert a[0] == b[0] == 401 and a[1] == b[1] == "unauthorized"
    assert not box.incoming("alpha", uid(1)).exists()


def test_a_capture_lands_in_ready_with_private_modes(box):
    cid = uid(1)
    assert box.send_both(cid) == (200, 200)
    d = box.ready("alpha", cid)
    assert sorted(p.name for p in d.iterdir()) == ["capture.json", "capture.png"]
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in d.iterdir())
    assert not box.incoming("alpha", cid).exists()


def test_either_file_may_come_first(box):
    cid = uid(2)
    assert box.put(cid, "capture.png", PNG)[0] == 200
    assert not box.ready("alpha", cid).exists()
    assert box.put(cid, "capture.json", capture(cid))[0] == 200
    assert box.ready("alpha", cid).is_dir()


def test_the_key_decides_the_product(box):
    cid = uid(3)
    assert box.put(cid, "capture.json", capture(cid, "beta"))[0] == 403          # alpha's key, beta's capture
    assert box.put(cid, "capture.json", capture(cid, "alpha", app={"bundle_id": "x"}))[0] == 403   # no app.product
    assert box.put(cid, "capture.json", capture(cid, "alpha"), key=KEY_B)[0] == 403
    assert not box.incoming("alpha", cid).exists() and not box.incoming("beta", cid).exists()


def test_bad_bodies_are_refused(box):
    cid = uid(4)
    assert box.put(cid, "capture.png", b"GIF89a....")[0] == 400
    assert box.put(cid, "capture.json", b"{not json")[0] == 400
    assert box.put(cid, "capture.json", capture(uid(5)))[0] == 400                 # id differs from the path
    assert box.put(cid, "capture.json", capture(cid, v=2))[0] == 400
    assert box.put(cid, "capture.json", capture(cid, v=True))[0] == 400
    assert box.put(cid, "capture.json", capture(cid, screenshot={"file": "capture.png"}))[0] == 400
    assert not box.incoming("alpha", cid).exists()


def test_size_limits_are_checked_before_the_body_is_read(box):
    cid = uid(6)
    assert box.header_only("PUT", f"/v1/captures/{cid}/capture.png", 10 * rc.MIB + 1) == 413
    assert box.header_only("PUT", f"/v1/captures/{cid}/capture.json", 256 * 1024 + 1) == 413
    assert box.header_only("PUT", f"/v1/captures/{cid}/capture.png", None) == 411
    assert box.header_only("PUT", f"/v1/captures/{cid}/capture.png", 5, key="nope") == 401


def test_a_picture_at_the_limit_is_accepted(box):
    cid = uid(7)
    big = rc.PNG_MAGIC + b"\0" * (10 * rc.MIB - 8)
    assert box.put(cid, "capture.json", capture(cid, sha=hashlib.sha256(big).hexdigest()))[0] == 200
    assert box.put(cid, "capture.png", big)[0] == 200
    assert box.ready("alpha", cid).is_dir()


def test_a_picture_that_is_not_the_one_named_drops_both(box):
    cid = uid(8)
    assert box.put(cid, "capture.json", capture(cid, sha="0" * 64))[0] == 200
    status, text, _ = box.put(cid, "capture.png", PNG)
    assert status == 422
    assert not box.incoming("alpha", cid).exists() and not box.ready("alpha", cid).exists()


def test_a_second_put_of_a_delivered_capture_is_a_200_that_counts_nothing(tmp_path):
    b = Box(tmp_path, per_product_day=1)
    try:
        assert b.send_both(uid(1)) == (200, 200)
        for _ in range(3):
            assert b.send_both(uid(1)) == (200, 200)
        assert b.put(uid(2), "capture.json", capture(uid(2)))[0] == 429       # the one slot is used
        assert json.loads((tmp_path / "data" / "state" / "counters.json").read_text())["total"] == 1
    finally:
        b.stop()


def test_a_retry_of_a_half_capture_is_not_a_new_capture(tmp_path):
    b = Box(tmp_path, per_product_day=1)
    try:
        assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
        assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
        assert b.put(uid(1), "capture.png", PNG)[0] == 200
        assert b.ready("alpha", uid(1)).is_dir()
    finally:
        b.stop()


def test_per_product_and_total_daily_caps(tmp_path):
    b = Box(tmp_path, per_product_day=2, total_day=3)
    try:
        assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
        assert b.put(uid(2), "capture.json", capture(uid(2)))[0] == 200
        assert b.put(uid(3), "capture.json", capture(uid(3)))[0] == 429                 # alpha is at 2
        assert b.put(uid(4), "capture.json", capture(uid(4), "beta"), KEY_B)[0] == 200  # beta has its own 2
        assert b.put(uid(5), "capture.json", capture(uid(5), "beta"), KEY_B)[0] == 429  # 3 in total
        assert b.put(uid(1), "capture.png", PNG)[0] == 200                              # a known id still finishes
    finally:
        b.stop()


def test_the_caps_reset_on_the_next_utc_day(tmp_path):
    b = Box(tmp_path, per_product_day=1)
    try:
        assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
        assert b.put(uid(2), "capture.json", capture(uid(2)))[0] == 429
        b.now[0] += 86400
        assert b.put(uid(2), "capture.json", capture(uid(2)))[0] == 200
    finally:
        b.stop()


def test_counts_survive_a_restart(tmp_path):
    b = Box(tmp_path, per_product_day=1, total_day=5)
    assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
    b.stop()
    b.start()
    try:
        assert b.put(uid(2), "capture.json", capture(uid(2)))[0] == 429
        assert b.put(uid(1), "capture.png", PNG)[0] == 200
    finally:
        b.stop()


def test_a_full_disk_budget_is_a_507(tmp_path):
    b = Box(tmp_path, max_bytes=2000)
    try:
        assert b.put(uid(1), "capture.json", capture(uid(1)))[0] == 200
        assert b.put(uid(2), "capture.png", PNG)[0] == 200
        status = b.header_only("PUT", f"/v1/captures/{uid(3)}/capture.png", 1900)
        assert status == 507
    finally:
        b.stop()


def test_a_half_capture_is_swept_after_a_day(box):
    cid = uid(9)
    assert box.put(cid, "capture.png", PNG)[0] == 200
    assert box.srv.store.sweep() == 0 and box.incoming("alpha", cid).is_dir()
    box.now[0] += 25 * 3600
    old = box.now[0] - 25 * 3600
    for p in [box.incoming("alpha", cid), *box.incoming("alpha", cid).iterdir()]:
        os.utime(p, (old, old))
    assert box.srv.store.sweep() == 1
    assert not box.incoming("alpha", cid).exists()


def test_a_finished_capture_is_never_swept(box):
    cid = uid(10)
    box.send_both(cid)
    old = time.time() - 3 * 86400
    box.now[0] = time.time() + 3 * 86400
    os.utime(box.ready("alpha", cid), (old, old))
    assert box.srv.store.sweep() == 0 and box.ready("alpha", cid).is_dir()


def test_nothing_is_readable_over_http(box):
    cid = uid(11)
    box.send_both(cid)
    for method, path in [("GET", f"/v1/captures/{cid}/capture.json"), ("GET", f"/v1/captures/{cid}/capture.png"),
                         ("GET", "/v1/captures/"), ("GET", "/v1/captures"), ("GET", "/"), ("GET", "/ready/alpha"),
                         ("HEAD", f"/v1/captures/{cid}/capture.png"), ("DELETE", f"/v1/captures/{cid}/capture.png"),
                         ("POST", f"/v1/captures/{cid}/capture.png"), ("PATCH", f"/v1/captures/{cid}/capture.json")]:
        status, text, _ = box.req(method, path)
        assert status == 405, (method, path)
        assert COMMENT not in text and "sample.list" not in text
    assert box.ready("alpha", cid).is_dir()


def test_only_a_lowercase_uuid_is_a_capture_path(box):
    assert box.put(uid(12).upper(), "capture.png", PNG)[0] == 405
    assert box.req("PUT", f"/v1/captures/{uid(12)}/other.png", PNG)[0] == 405
    assert box.req("PUT", f"/v1/captures/{uid(12)}/capture.png?x=1", PNG)[0] == 405


def test_cors_for_web_builds(box):
    status, _, h = box.req("OPTIONS", f"/v1/captures/{uid(13)}/capture.json", key=None,
                           headers={"Origin": "https://tester.example", "Access-Control-Request-Method": "PUT"})
    h = {k.lower(): v for k, v in h.items()}
    assert status == 204
    assert h["access-control-allow-origin"] == "*"
    assert h["access-control-allow-methods"] == "PUT"
    assert "authorization" in h["access-control-allow-headers"] and "content-type" in h["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in h
    _, _, h2 = box.put(uid(13), "capture.png", PNG)
    assert {k.lower(): v for k, v in h2.items()}["access-control-allow-origin"] == "*"


def test_the_keys_file_is_read_again_when_it_changes(box):
    assert box.put(uid(14), "capture.png", PNG, key="late-key-0123456789")[0] == 401
    box.keys.write_text(f"{digest(KEY_A)} alpha\n{digest('late-key-0123456789')} alpha\n")
    os.utime(box.keys, (time.time() + 5, time.time() + 5))
    assert box.put(uid(14), "capture.png", PNG, key="late-key-0123456789")[0] == 200
    box.keys.write_text(f"{digest(KEY_B)} beta\n")
    os.utime(box.keys, (time.time() + 10, time.time() + 10))
    assert box.put(uid(15), "capture.png", PNG)[0] == 401


def test_a_missing_keys_file_refuses_everything(box):
    box.keys.unlink()
    assert box.put(uid(16), "capture.png", PNG)[0] == 401


def test_more_than_the_concurrency_limit_gets_503(tmp_path):
    b = Box(tmp_path, max_concurrent=2)
    held = []
    try:
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", b.port), timeout=5)
            held.append(s)
        time.sleep(0.3)
        s = socket.create_connection(("127.0.0.1", b.port), timeout=5)
        s.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        assert s.recv(200).startswith(b"HTTP/1.1 503")
        s.close()
        for h in held:
            h.close()
        time.sleep(0.3)
        assert b.req("GET", "/healthz", key=None)[0] == 200
    finally:
        for h in held:
            h.close()
        b.stop()


def test_the_log_has_no_key_and_no_comment(tmp_path, capsys):
    b = Box(tmp_path)
    try:
        b.send_both(uid(17))
        b.put(uid(18), "capture.png", PNG, key="wrong-key-0123456789")
        b.req("GET", "/healthz", key=None)
    finally:
        b.stop()
    err = capsys.readouterr().err
    assert "PUT 00000011 alpha 200" in err and "PUT 00000012 - 401" in err
    for secret in (KEY_A, KEY_B, "wrong-key", COMMENT, "sample.list", "Bearer"):
        assert secret not in err


def test_the_package_uses_only_the_standard_library():
    text = (ROOT / "packages" / "review-channel" / "server.py").read_text()
    imports = {line.split()[1].split(".")[0] for line in text.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "hashlib", "json", "os", "re", "secrets", "shutil", "sys", "threading", "time",
                       "dataclasses", "http", "typing"}


def test_no_private_host_or_address_in_the_package():
    import re
    for f in (ROOT / "packages" / "review-channel").iterdir():
        text = f.read_text()
        assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text.replace("127.0.0.1", "").replace("0.0.0.0", "")), f.name


def test_expect_continue_is_answered_only_after_the_request_passed(box):
    cid = uid(19)
    for key, expect in ((KEY_A, b"HTTP/1.0 100"), ("wrong-key-0123456789", b"HTTP/1.0 401")):
        s = socket.create_connection(("127.0.0.1", box.port), timeout=10)
        s.sendall(f"PUT /v1/captures/{cid}/capture.png HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {key}\r\n"
                  f"Expect: 100-continue\r\nContent-Length: {len(PNG)}\r\n\r\n".encode())
        first = s.recv(200)
        assert first.startswith(expect), first
        if expect.endswith(b"100"):
            s.sendall(PNG)
            rest = b""
            while chunk := s.recv(4096):
                rest += chunk
            assert b"200 OK" in rest
        s.close()


def test_a_third_big_body_is_turned_away_and_spends_nothing(tmp_path):
    # Two 10 MiB bodies fit the container's 64 MiB; eight would not.
    b = Box(tmp_path)
    try:
        held = [b.srv.big_bodies.acquire(blocking=False) for _ in range(2)]
        assert all(held)
        cid = uid(90)
        assert b.header_only("PUT", f"/v1/captures/{cid}/capture.png", rc.MIB + 1) == 503
        for _ in held:
            b.srv.big_bodies.release()
        assert b.put(cid, "capture.png", rc.PNG_MAGIC + b"\0" * (rc.MIB + 1))[0] == 200
    finally:
        b.stop()
