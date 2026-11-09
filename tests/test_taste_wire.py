"""Taste drops from the iPhone's Share extension (taste_wire.py, and `teyla taste list --corpus`).
Everything runs in tmp dirs with a test key; no iCloud, no browser, no network."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pytest

from teyla import cli, relay, taste_corpus, taste_wire

FIX = pathlib.Path(__file__).parent / "fixtures"
VEC = json.loads((FIX / "taste-drop-vector.json").read_text())
KEY = bytes.fromhex(VEC["key_hex"])
NOW = 1_800_000_000.0
DID = "5b0c1d2e-3f40-4a51-8b62-73c4d5e6f708"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path / "relay"
        for sub in ("outbox", "sent"):
            (self.root / sub).mkdir(parents=True)
        monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("TEYLA_TASTE_CORPUS", str(tmp_path / "corpus"))
        (tmp_path / "home").mkdir()

    def drop(self, did=DID, *, url="https://example.com/a", image=None, image_bytes=None, sentence="",
             verdict="like", created=None, key=KEY, seen_ago=None, **extra):
        created = created or iso(NOW - 60)
        obj = {"v": 1, "id": did, "created": created, "device": "iPhone", "verdict": verdict,
               "url": None if image else url, "image": image, "sentence": sentence}
        obj.update(extra)
        raw = json.dumps(obj).encode()
        pic = JPEG if image_bytes is None else image_bytes
        d = self.root / "outbox" / "taste" / did
        d.mkdir(parents=True)
        (d / "taste.json").write_bytes(raw)
        if isinstance(image, str):
            (d / image).write_bytes(pic)
        (d / "taste.sig").write_text(taste_wire.drop_sig(key, did, created, raw, pic if isinstance(image, str) else b""))
        if seen_ago is not None:                        # this Mac first saw the drop that long ago
            seen = taste_wire._load_seen()
            seen[did] = NOW - seen_ago
            relay._write_json(taste_wire.seen_path(), seen)
        return d

    def pull(self, now=NOW):
        return self.pull_with(None, now)

    def pull_with(self, add_fn, now=NOW):
        with relay.Dirs(self.root).open() as dirs:
            return taste_wire.pull(dirs, KEY, now, add_fn)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def entries():
    rows, _ = taste_corpus.load_all()
    return [e for _, e in rows]


def test_the_vector_is_reproduced_exactly():
    raw = VEC["json"].encode()
    assert taste_wire.drop_message(VEC["id"], VEC["created"], raw, b"").decode() == VEC["message"]
    assert taste_wire.drop_sig(KEY, VEC["id"], VEC["created"], raw) == VEC["sig"]
    assert taste_wire.shape(json.loads(VEC["json"])) == ""


def test_a_link_with_a_sentence_becomes_a_proposed_entry_verbatim(env):
    sentence = "Calm, lots of air.\nThe  spacing is the point."
    env.drop(url="https://example.com/pricing", sentence=sentence, verdict="dislike")
    res = env.pull()
    assert [(r["ok"], r["kind"]) for r in res] == [(True, "taste")]
    [e] = entries()
    assert (e["status"], e["verdict"], e["source"], e["claim"], e["claim_source"]) == (
        "proposed", "dislike", "https://example.com/pricing", sentence, "owner")
    assert e["evidence"]["files"] == []                 # a sync pass never opens a page
    assert not (env.root / "outbox" / "taste" / DID).exists()


def test_a_link_without_a_sentence_stays_raw(env):
    env.drop()
    env.pull()
    [e] = entries()
    assert (e["status"], e["claim"]) == ("raw", "")


def test_a_picture_is_kept_as_evidence_and_the_source_is_not_a_temp_path(env):
    env.drop(image="image.jpg", sentence="calm empty state")
    env.pull()
    [e] = entries()
    assert e["status"] == "proposed" and e["source"] == "iphone-share-5b0c1d2e.jpg"
    assert e["evidence"]["files"] == ["evidence/source.jpg"]
    d = next(d for d, x in taste_corpus.load_all()[0] if x["id"] == e["id"])
    assert (d / "evidence" / "source.jpg").read_bytes() == JPEG


def test_a_wrong_key_is_refused_once_the_folder_is_not_young(env):
    env.drop(key=bytes(32), seen_ago=3600)
    [r] = env.pull()
    assert (r["ok"], r["detail"]) == (False, "bad signature")
    assert entries() == []


def test_a_bad_signature_on_a_young_folder_waits_for_the_rest_of_the_files(env):
    d = env.drop(key=bytes(32), seen_ago=5)
    assert env.pull() == []
    assert d.exists()


def test_a_missing_picture_waits_then_is_refused(env):
    d = env.drop(image="image.jpg")
    (d / "image.jpg").unlink()
    assert env.pull() == []
    taste_wire.seen_path().write_text(json.dumps({DID: NOW - 3600}))
    [r] = env.pull()
    assert r["ok"] is False and "missing" in r["detail"]


def test_a_changed_picture_breaks_the_signature(env):
    d = env.drop(image="image.jpg", seen_ago=3600)
    (d / "image.jpg").write_bytes(JPEG + b"x")
    [r] = env.pull()
    assert (r["ok"], r["detail"]) == (False, "bad signature")


def test_a_drop_is_imported_at_most_once(env):
    env.drop()
    env.pull()
    env.drop()                                          # the same id again, signed and valid
    [r] = env.pull()
    assert (r["ok"], r["detail"]) == (False, "replay: already handled")
    assert len(entries()) == 1


@pytest.mark.parametrize("kw,why", [
    ({"created": iso(NOW - 8 * 86400)}, "too old"),
    ({"created": iso(NOW + 3600)}, "future"),
])
def test_the_window(env, kw, why):
    env.drop(**kw)
    [r] = env.pull()
    assert r["ok"] is False and why in r["detail"]
    assert entries() == []


@pytest.mark.parametrize("change", [
    {"url": "file:///etc/passwd"}, {"url": "javascript:alert(1)"}, {"verdict": "love"}, {"sentence": "a\x00b"},
    {"sentence": "x" * 8001}, {"v": 2}, {"extra": 1}, {"image": "../image.jpg", "url": None},
    {"url": None, "image": None}, {"image": "image.jpg"},
])
def test_shape_refuses(change):
    obj = {"v": 1, "id": DID, "created": iso(NOW), "device": "iPhone", "verdict": "like",
           "url": "https://example.com", "image": None, "sentence": ""}
    obj.update(change)
    assert taste_wire.shape(obj) != ""


def test_a_picture_that_is_not_an_image_is_refused(env):
    env.drop(image="image.jpg", image_bytes=b"<html>not a picture</html>")
    [r] = env.pull()
    assert r["ok"] is False and "PNG or JPEG" in r["detail"]


def test_a_linked_picture_is_not_followed(env, tmp_path):
    d = env.drop(image="image.jpg", seen_ago=3600)
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(JPEG)
    (d / "image.jpg").unlink()
    (d / "image.jpg").symlink_to(secret)
    [r] = env.pull()
    assert r["ok"] is False and entries() == []


def test_sync_runs_the_taste_pass(env):
    relay.key_path().parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(relay.key_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(KEY)
    relay.write_cfg({"on": True, "folder": str(env.root), "synced": ""})
    env.drop(sentence="yes")
    snap = json.loads((FIX / "state.v2.json").read_text())
    res = relay.sync(now=NOW, source=lambda now: (snap, []), runner=lambda c, t: (0, "", ""), base=["teyla"])
    assert [(r["kind"], r["ok"]) for r in res["processed"]] == [("taste", True)]
    assert len(entries()) == 1


# --- teyla taste list --corpus --------------------------------------------------------------------

def test_list_corpus_counts_filters(env, capsys):
    taste_corpus.add(["https://example.com/a", "calm"], verdict="like")
    taste_corpus.add(["https://example.com/b"], verdict="dislike")
    assert cli.main(["taste", "list", "--corpus"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "corpus: 1 raw, 1 proposed"
    assert "example.com/a" in out and "example.com/b" in out
    assert cli.main(["taste", "list", "--corpus", "--status", "raw", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["counts"]["proposed"] == 1 and [e["source"] for e in got["entries"]] == ["https://example.com/b"]
    assert cli.main(["taste", "list", "--corpus", "--verdict", "like"]) == 0
    assert "example.com/b" not in capsys.readouterr().out


def test_list_without_corpus_flag_still_lists_the_ledger(env, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    taste_corpus.add(["https://example.com/a", "calm"])
    cli.main(["taste", "list", "--repo", str(tmp_path)])
    assert "example.com" not in capsys.readouterr().out


# --- review fixes (teyla#473) -----------------------------------------------------------------------

def test_a_failed_import_keeps_the_drop_and_retries_then_gives_up(env):
    d = env.drop(sentence="calm")
    calls = []

    def failing(words, **kw):
        calls.append(words)
        raise PermissionError("corpus is read-only")

    [r] = env.pull_with(failing)
    assert r["ok"] is False and "will retry (1/3)" in r["detail"]
    assert d.exists() and entries() == []
    [r] = env.pull_with(failing)
    assert "will retry (2/3)" in r["detail"] and d.exists()
    [r] = env.pull_with(failing)
    assert "after 3 tries" in r["detail"] and not d.exists()
    assert len(calls) == 3
    assert env.pull() == []


def test_a_drop_that_failed_once_is_imported_when_the_corpus_works_again(env):
    d = env.drop(sentence="calm")

    def failing(words, **kw):
        raise PermissionError("busy")

    env.pull_with(failing)
    [r] = env.pull()
    assert r["ok"] is True and not d.exists()
    assert len(entries()) == 1
    [r] = env.pull_with(failing) if env.drop() else []     # the same id again is a replay, not a second import
    assert r["detail"] == "replay: already handled" and len(entries()) == 1


def test_files_still_arriving_get_their_grace_from_when_this_mac_first_saw_the_drop(env):
    d = env.drop(image="image.jpg")
    (d / "image.jpg").unlink()
    for p in (*d.iterdir(), d):
        os.utime(p, (NOW - 7200, NOW - 7200))           # the phone wrote it two hours ago, offline
    assert env.pull() == [] and d.exists()              # first seen now: wait
    assert json.loads(taste_wire.seen_path().read_text()) == {DID: NOW}
    assert env.pull(now=NOW + 60) == [] and d.exists()
    [r] = env.pull(now=NOW + 3600)
    assert r["ok"] is False and "missing" in r["detail"] and not d.exists()


@pytest.mark.parametrize("bad", [[1, 2], {"a": 1}, 7, True])
def test_a_malformed_image_field_never_blocks_the_drops_after_it(env, bad):
    first = "0a000000-0000-4000-8000-000000000001"
    env.drop(did=first, url=None, image=bad)
    env.drop(sentence="fine")
    res = env.pull()
    by_id = {r["id"]: r for r in res}
    assert by_id[first]["ok"] is False and "image" in by_id[first]["detail"]
    assert by_id[DID]["ok"] is True
    assert len(entries()) == 1
