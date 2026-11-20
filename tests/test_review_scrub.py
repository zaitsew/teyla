"""The review scrub rules (docs/REVIEW.md, "What is scrubbed"). `packages/review-channel/test-vectors/scrub.json` is the
one list of cases that the Swift, TypeScript, Kotlin and Python test suites all read; this file runs it against the
channel's own implementation (the server-side backstop) and the backstop against a real server."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VECTORS = ROOT / "packages" / "review-channel" / "test-vectors" / "scrub.json"
spec = importlib.util.spec_from_file_location("review_channel_server_scrub", ROOT / "packages" / "review-channel" / "server.py")
rc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rc
spec.loader.exec_module(rc)

DATA = json.loads(VECTORS.read_text(encoding="utf-8"))


def ids(cases):
    return [c["name"] for c in cases]


@pytest.mark.parametrize("case", DATA["text"], ids=ids(DATA["text"]))
def test_text_vectors(case):
    assert rc.scrub(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", DATA["label"], ids=ids(DATA["label"]))
def test_label_vectors(case):
    assert rc.scrub_label(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", DATA["text"], ids=ids(DATA["text"]))
def test_scrubbing_twice_changes_nothing(case):
    assert rc.scrub(case["expected"]) == case["expected"]


def test_every_platform_suite_reads_the_shared_vectors():
    readers = [
        "packages/review-ios/Tests/TeylaReviewTests/ReviewScrubTests.swift",
        "packages/review-web/tests/scrub.test.ts",
        "packages/review-android/teyla-review/src/test/kotlin/teyla/review/ScrubTest.kt",
    ]
    for path in readers:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "scrub.json" in text and "review-channel" in text, path


def test_the_vectors_use_only_generic_data():
    text = VECTORS.read_text(encoding="utf-8")
    assert "example." in text
    assert not any(0x400 <= ord(c) < 0x500 for c in text)


def test_the_capture_scrub_covers_every_text_field():
    cap = {
        "comment": {"text": "mail jane@example.com"},
        "tap": {"x": 1, "y": 2, "accessibility_identifier": "id jane@example.com", "accessibility_label": "q" * 300},
        "screen": "s jane@example.com",
        "element": {"id": "e jane@example.com", "strings": ["jane@example.com", "ok"]},
        "anchors": [{"id": "a", "screen": "x jane@example.com", "strings": ["+34 600 123 456"]}],
    }
    out = rc.scrub_capture(cap)
    assert out["comment"]["text"] == "mail [email]"
    assert out["tap"]["accessibility_identifier"] == "id [email]"
    assert out["tap"]["accessibility_label"] == "q" * 200
    assert out["screen"] == "s [email]"
    assert out["element"] == {"id": "e [email]", "strings": ["[email]", "ok"]}
    assert out["anchors"][0] == {"id": "a", "screen": "x [email]", "strings": ["[phone]"]}
    assert "jane@example.com" not in json.dumps(out)


# ---- the server stores the scrubbed capture -----------------------------------------------------------------

sys.path.insert(0, str(ROOT / "tests"))
from test_review_channel_server import PNG, Box, capture, uid  # noqa: E402


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path)
    yield b
    b.stop()


def test_the_server_scrubs_before_it_stores(box):
    cid = uid(41)
    body = capture(cid, comment={"text": "reach me at jane@example.com or +34 600 123 456", "input": "text"},
                   tap={"x": 1, "y": 2, "accessibility_label": "z" * 250})
    assert box.put(cid, "capture.json", body)[0] == 200
    assert box.put(cid, "capture.png", PNG)[0] == 200
    path = box.ready("alpha", cid) / "capture.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["comment"]["text"] == "reach me at [email] or [phone]"
    assert stored["tap"]["accessibility_label"] == "z" * 200
    raw = path.read_text(encoding="utf-8")
    assert "jane@example.com" not in raw and "600 123" not in raw


def test_a_clean_capture_is_stored_byte_for_byte(box):
    cid = uid(42)
    body = capture(cid)
    box.put(cid, "capture.json", body)
    box.put(cid, "capture.png", PNG)
    assert (box.ready("alpha", cid) / "capture.json").read_bytes() == body
