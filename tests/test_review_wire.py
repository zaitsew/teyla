"""The phone's capture contract on the Mac side: the signing vectors, the signed import and the "received"
receipt. The fixtures are copies of the capture lane's (docs/REVIEW.md): tests/fixtures/review-vector.json
and tests/fixtures/review-capture/. No network, no iCloud; every folder is a tmp dir."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil

import pytest

from teyla import cli, relay, review, review_wire

FIX = pathlib.Path(__file__).parent / "fixtures"
VEC = json.loads((FIX / "review-vector.json").read_text())
CAP = FIX / "review-capture"
CID = "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64"
KEY = bytes.fromhex(VEC["key_hex"])
NOW = dt.datetime(2026, 10, 30, 21, 20, tzinfo=dt.timezone.utc).timestamp()


@pytest.fixture
def key():
    p = relay.key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(KEY)
    return KEY


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "relay"
    for sub in ("outbox/review", "sent"):
        (r / sub).mkdir(parents=True)
    return r


@pytest.fixture
def conn():
    c = review.connect()
    yield c
    c.close()


def drop(root, cid=CID) -> pathlib.Path:
    folder = root / "outbox" / "review" / cid
    shutil.copytree(CAP, folder)
    (folder / "status.json").unlink()                   # the Mac's answer is not part of what the phone sends
    return folder


def test_the_key_and_the_pairing_string_match_the_vector():
    assert relay.pairing_string(KEY) == VEC["pairing"]


def test_the_capture_signature_is_the_vector():
    j, p = (CAP / "capture.json").read_bytes(), (CAP / "capture.png").read_bytes()
    assert review_wire.sha256_hex(j) == VEC["capture_json_sha256"]
    assert review_wire.sha256_hex(p) == VEC["capture_png_sha256"]
    msg = review_wire.capture_message(CID, "2026-10-30T21:14:05Z", VEC["capture_json_sha256"], VEC["capture_png_sha256"])
    assert msg.decode() == VEC["capture_message"]
    assert review_wire.capture_sig(KEY, CID, "2026-10-30T21:14:05Z", j, p) == VEC["capture_sig"]
    assert (CAP / "capture.sig").read_text() == VEC["capture_sig"] + "\n"


def test_the_status_signature_is_the_vector():
    pr = "https://github.com/example/sampleapp/pull/12"
    assert review_wire.status_message(CID, "pr_ready", "2026-10-30T22:03:00Z", pr).decode() == VEC["status_message"]
    assert review_wire.status_sig(KEY, CID, "pr_ready", "2026-10-30T22:03:00Z", pr) == VEC["status_sig"]
    fixture = json.loads((CAP / "status.json").read_text())
    assert fixture["sig"] == VEC["status_sig"] and fixture["pr"] == pr
    # no PR: the last line of the message is empty
    assert review_wire.status_message(CID, "received", "t").decode().endswith("\nreceived\nt\n")


def test_a_signed_capture_is_imported_and_a_signed_receipt_is_written(conn, root, key):
    drop(root)
    rep = review.pull_relay(conn, root, NOW)
    assert (rep["added"], rep.get("receipts"), rep["skipped"]) == (1, 1, [])
    row = review.get(conn, CID)
    assert row["product"] == "sampleapp" and row["screen"] == "sample.list"
    assert "too small" in row["comment"] and row["data"]["element"]["id"] == "sample.list.addButton"
    assert row["data"]["element"]["string_keys"] == ["list.add"] and row["data"]["commit"] == "3f9c2ab"
    sent = json.loads(review_wire.status_path(root, CID).read_text())
    assert sent["v"] == 1 and sent["id"] == CID and sent["status"] == "received" and "pr" not in sent
    assert sent["sig"] == review_wire.status_sig(KEY, CID, "received", sent["updated"])
    assert sent["updated"] == "2026-10-30T21:20:00Z"
    assert (review.captures_root() / CID / "capture.sig").is_file()


def test_a_second_pull_changes_nothing_and_a_missing_receipt_is_written_later(conn, root, key):
    drop(root)
    review.pull_relay(conn, root, NOW)
    path = review_wire.status_path(root, CID)
    first = path.read_text()
    again = review.pull_relay(conn, root, NOW + 600)
    assert again["known"] == 1 and not again.get("receipts") and path.read_text() == first
    path.unlink()
    assert review.pull_relay(conn, root, NOW + 900).get("receipts") == 1, "a receipt that was lost is written on the next pass"


def test_a_receipt_never_moves_the_chain_backwards(conn, root, key):
    drop(root)
    review.pull_relay(conn, root, NOW)
    assert review_wire.write_status(root, KEY, CID, "pr_ready", NOW + 60, "https://example.com/pull/1")
    review.pull_relay(conn, root, NOW + 120)
    assert review_wire.current_status(root, CID) == "pr_ready"
    assert not review_wire.write_status(root, KEY, CID, "received", NOW + 180)
    assert json.loads(review_wire.status_path(root, CID).read_text())["pr"] == "https://example.com/pull/1"


def test_a_wrong_signature_is_refused_and_gets_no_receipt(conn, root, key):
    folder = drop(root)
    (folder / "capture.sig").write_text("0" * 64 + "\n")
    rep = review.pull_relay(conn, root, NOW)
    assert rep["added"] == 0 and "signature does not match" in rep["skipped"][0]
    assert not review_wire.status_path(root, CID).exists()


def test_an_edited_capture_fails_the_signature(conn, root, key):
    folder = drop(root)
    raw = json.loads((folder / "capture.json").read_text())
    raw["comment"]["text"] = "Delete everything."
    (folder / "capture.json").write_text(json.dumps(raw))
    assert review.pull_relay(conn, root, NOW)["added"] == 0


def test_a_capture_whose_signature_has_not_arrived_waits(conn, root, key):
    folder = drop(root)
    (folder / "capture.sig").unlink()
    rep = review.pull_relay(conn, root, NOW)
    assert rep["waiting"] == 1 and rep["added"] == 0 and not review_wire.status_path(root, CID).exists()
    shutil.copy(CAP / "capture.sig", folder / "capture.sig")
    assert review.pull_relay(conn, root, NOW)["added"] == 1


def test_without_a_relay_key_a_signed_capture_is_refused_and_says_why(conn, root):
    drop(root)
    rep = review.pull_relay(conn, root, NOW)
    assert rep["added"] == 0 and "teyla relay pair" in rep["skipped"][0]


def test_a_capture_dated_more_than_ten_minutes_ahead_is_refused(conn, root, key):
    drop(root)
    rep = review.pull_relay(conn, root, NOW - 3600)
    assert rep["added"] == 0 and "future" in rep["skipped"][0]


def test_a_version_other_than_one_is_refused(conn, root, key):
    folder = drop(root)
    raw = json.loads((folder / "capture.json").read_text())
    raw["v"] = 2
    (folder / "capture.json").write_text(json.dumps(raw))
    assert "version" in review.pull_relay(conn, root, NOW)["skipped"][0]


def test_the_older_flat_capture_still_imports_and_gets_no_receipt(conn, root, key):
    folder = root / "outbox" / "review" / CID
    folder.mkdir()
    (folder / "capture.json").write_text(json.dumps({"id": CID, "product": "recipes", "comment": "Too small.",
                                                     "created_at": "2026-10-30T09:12:00Z"}))
    rep = review.pull_relay(conn, root, NOW)
    assert rep["added"] == 1 and not rep.get("receipts") and not review_wire.status_path(root, CID).exists()


def test_a_planted_link_in_place_of_review_status_is_not_followed(conn, root, key, tmp_path):
    drop(root)
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.symlink(target, root / "review-status")
    rep = review.pull_relay(conn, root, NOW)
    assert not list(target.iterdir()) and rep["added"] == 1 and rep["receipt_errors"]


def test_pull_prints_the_receipts(conn, root, key, capsys, monkeypatch):
    drop(root)
    monkeypatch.setattr(review, "_now", lambda: NOW)
    assert cli.main(["review", "pull", "--folder", str(root)]) == 0
    out = capsys.readouterr().out
    assert "1 new" in out and "receipt(s) sent to the phone" in out


# ---- a product's own channel: no relay signature, the sign-in vouches ---------------------------

def channel(tmp_path, cid=CID) -> pathlib.Path:
    box = tmp_path / "channel"
    shutil.copytree(CAP, box / cid)
    (box / cid / "status.json").unlink()
    (box / cid / "capture.sig").unlink()
    return box


def test_a_vouched_capture_needs_no_signature_and_no_key(tmp_path, conn):
    rep = review.pull_vouched(conn, channel(tmp_path), NOW)
    assert (rep["added"], rep["skipped"], rep["imported"]) == (1, [], [CID])
    assert conn.execute("SELECT 1 FROM captures WHERE id = ?", (CID,)).fetchone()
    assert not (review.captures_root() / CID / "capture.sig").exists()


def test_a_second_vouched_pull_says_known_and_still_names_it(tmp_path, conn):
    box = channel(tmp_path)
    review.pull_vouched(conn, box, NOW)
    rep = review.pull_vouched(conn, box, NOW)
    assert (rep["added"], rep["known"], rep["imported"]) == (0, 1, [CID])


def test_a_vouched_picture_that_is_not_the_one_named_is_refused(tmp_path, conn):
    box = channel(tmp_path)
    (box / CID / "capture.png").write_bytes(b"not the picture")
    rep = review.pull_vouched(conn, box, NOW)
    assert rep["imported"] == [] and "sha256" in rep["skipped"][0]
    assert not conn.execute("SELECT 1 FROM captures WHERE id = ?", (CID,)).fetchone()


def test_a_vouched_folder_takes_only_the_contract_format(tmp_path, conn):
    folder = tmp_path / "channel" / CID
    folder.mkdir(parents=True)
    (folder / "capture.json").write_text(json.dumps({"id": CID, "product": "x", "screen": "s", "comment": "c"}))
    rep = review.pull_vouched(conn, tmp_path / "channel", NOW)
    assert rep["imported"] == [] and "contract" in rep["skipped"][0]


def test_the_relay_still_refuses_what_a_channel_would_take(root, key, conn):
    folder = drop(root)
    (folder / "capture.sig").unlink()
    rep = review.pull_relay(conn, root, NOW)
    assert rep["added"] == 0


def test_the_cli_lists_what_it_imported_as_json(tmp_path, capsys):
    box = channel(tmp_path)
    assert cli.main(["review", "pull", "--vouched-folder", str(box), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["source"] == "channel" and rep["imported"] == [CID]
