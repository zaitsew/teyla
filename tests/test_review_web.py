"""packages/review-web (docs/REVIEW.md, "Web"): the build switch proved on a real Vite build, and the
capture the package writes checked against the schema and the real channel service.

The TypeScript unit tests run with `npm test` in packages/review-web (./check.sh runs them). This
file needs the package's node_modules; without them, or without node, it skips."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

import pytest

from teyla import review_gate as gate
from test_review_capture import SCHEMA, validate
from test_review_channel_server import Box, KEY_A, rc

PKG = pathlib.Path(__file__).resolve().parents[1] / "packages" / "review-web"
KEY = "fixture-write-only-key-0123456789"
URL = "http://localhost:8099"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (PKG / "node_modules" / "vite").is_dir(),
    reason="needs node and `npm ci` in packages/review-web",
)


def node(*args: str) -> str:
    r = subprocess.run(["node", *args], cwd=PKG, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.fixture(scope="module")
def dists(tmp_path_factory):
    """The same fixture app built twice. Both builds see the channel key and address in the environment,
    as a CI job would have them; only the flag differs."""
    root = tmp_path_factory.mktemp("review-web-dist")
    out = {}
    for mode in ("off", "on"):
        out[mode] = root / mode
        node("scripts/build-fixture.ts", str(out[mode]), mode, f"--key={KEY}", f"--url={URL}")
    return out


def tree(path: pathlib.Path) -> bytes:
    return b"\n".join(p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file())


def test_a_build_without_the_flag_passes_the_store_check(dists):
    _, checks = gate.run(dists["off"])
    assert checks and all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_a_build_with_the_flag_carries_the_marker_and_fails_the_store_check(dists):
    _, checks = gate.run(dists["on"])
    assert checks and not all(c.ok for c in checks)
    assert gate.MARKER_WEB in tree(dists["on"])


def test_the_channel_key_and_address_never_reach_a_build_without_the_flag(dists):
    off = tree(dists["off"])
    assert KEY.encode() not in off
    assert URL.encode() not in off
    assert b"modern-screenshot" not in off and b"foreignObject" not in off
    assert b"teyla-review" not in off and b"teyla.review" not in off, "no overlay, queue or form code at all"
    # The flag-on build does hold them: the test would pass for a broken fixture otherwise.
    on = tree(dists["on"])
    assert KEY.encode() in on and URL.encode() in on and b"teyla-review" in on


def test_the_marker_lives_only_in_the_lazily_loaded_chunk(dists):
    holders = [p for p in dists["on"].rglob("*") if p.is_file() and gate.MARKER_WEB in p.read_bytes()]
    assert [p.suffix for p in holders] == [".js"]
    entry = next(p for p in (dists["on"] / "assets").glob("*.js") if p.name.startswith("index-") and b"import(" in p.read_bytes() and gate.MARKER_WEB not in p.read_bytes())
    assert b"overlay-" in entry.read_bytes(), "the entry reaches the overlay through a dynamic import"
    assert "overlay-" in holders[0].name
    html = (dists["on"] / "index.html").read_text()
    assert "overlay-" not in html, "the overlay is not preloaded by the page"


def test_the_flag_off_build_is_small(dists):
    assert len(tree(dists["off"])) < 4000


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    out = tmp_path_factory.mktemp("review-web-capture")
    node("scripts/emit-sample-capture.ts", str(out), "alpha")
    return out


def test_the_capture_matches_the_schema_and_names_a_web_build(sample):
    doc = json.loads((sample / "capture.json").read_text())
    schema = json.loads(SCHEMA.read_text())
    assert validate(doc, schema, schema) == []
    assert doc["app"]["configuration"] == "test_host"
    assert doc["app"]["product"] == "alpha"
    assert doc["device"] == "Web"
    assert doc["element"]["id"] == "app.home.addButton" and doc["element"]["matched_by"] == "anchor"
    assert doc["screenshot"]["sha256"] == hashlib.sha256((sample / "capture.png").read_bytes()).hexdigest()


def test_the_channel_takes_the_capture_the_way_a_browser_sends_it(sample, tmp_path):
    doc = json.loads((sample / "capture.json").read_text())
    cid = doc["id"]
    box = Box(tmp_path)
    try:
        status, _, h = box.req("OPTIONS", f"/v1/captures/{cid}/capture.png", key=None, headers={
            "Origin": "https://test.example.com", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization, content-type"})
        low = {k.lower(): v for k, v in h.items()}
        assert status == 204 and low["access-control-allow-origin"] == "*"
        assert "authorization" in low["access-control-allow-headers"] and low["access-control-allow-methods"] == "PUT"
        origin = {"Origin": "https://test.example.com"}
        for name, ctype in (("capture.png", "image/png"), ("capture.json", "application/json")):
            status, _, h = box.req("PUT", f"/v1/captures/{cid}/{name}", (sample / name).read_bytes(), key=KEY_A, headers={**origin, "Content-Type": ctype})
            assert status == 200
            assert {k.lower(): v for k, v in h.items()}["access-control-allow-origin"] == "*", "the browser may read the answer"
        assert (box.ready("alpha", cid) / "capture.json").is_file()
        # The key decides the product: a web build with the wrong slug is refused, and the browser can read that too.
        other = "4c1d2e3f-6a41-4c7e-9d0a-5e2f8b7c1a65"
        doc.update(id=other, app={**doc["app"], "product": "beta"})
        status, _, h = box.req("PUT", f"/v1/captures/{other}/capture.json", json.dumps(doc).encode(), key=KEY_A, headers=origin)
        assert status == 403
        assert {k.lower(): v for k, v in h.items()}["access-control-allow-origin"] == "*"
    finally:
        box.stop()
