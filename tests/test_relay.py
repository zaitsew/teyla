"""`teyla relay`: the signing vector, every refusal, at-most-once delivery, the lock, the atomic write.
Everything runs in tmp dirs with injected runners and answer functions: no launchctl, no `claude`,
no `codex`, no iCloud. The fixture key is a test key; nothing here touches the real ~/.teyla."""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import json
import os
import pathlib
import plistlib
import stat
import sys
import uuid

import pytest

from teyla import answer, asks, cli, relay

FIX = pathlib.Path(__file__).parent / "fixtures"
VEC = json.loads((FIX / "relay-vector.json").read_text())
SNAP = json.loads((FIX / "state.v2.json").read_text())
KEY = bytes.fromhex(VEC["key_hex"])
QUESTION = VEC["question"]
NOW = dt.datetime(2026, 10, 17, 21, 46, tzinfo=dt.timezone.utc).timestamp()
RUNNING_ID, RUNNING_TITLE = "local_00000000-0000-0000-0000-000000000004", "Agent connector P2"
CRASH_MSG = "simulated power cut"


class Crash(BaseException):
    """Not an Exception: nothing in the relay may swallow it, like a power cut."""


def iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(text: str) -> str:
    return relay.sha256_hex(text)


def make_ask() -> asks.Ask:
    return asks.Ask(id="7c222b3d", kind="question", product="cellar", title="Cellar app store rejection",
                    question=QUESTION, context="", options=[], when=NOW - 3600, archived=False,
                    link="claude://claude.ai/epitaxy/local_x", pr="", harness="claude-desktop", session="")


class Env:
    def __init__(self, tmp_path):
        self.folder = tmp_path / "relay"
        for sub in ("outbox", "sent"):
            (self.folder / sub).mkdir(parents=True)
        relay.key_path().parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(relay.key_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(KEY)
        relay.write_cfg({"on": True, "folder": str(self.folder), "synced": ""})
        self.answers: list[tuple] = []
        self.commands: list[list[str]] = []
        self.snap = copy.deepcopy(SNAP)
        self.items = [make_ask()]
        self.run_result = (0, json.dumps({"ok": True, "via": "codex-queue", "detail": "queued", "id": "x"}), "")

    def source(self, now):
        return copy.deepcopy(self.snap), list(self.items)

    def answer_fn(self, item, text, clipboard=True):
        self.answers.append((item.id, text, clipboard))
        return {"ok": True, "via": "claude-bg", "detail": "started", "id": item.id}

    def runner(self, cmd, timeout):
        self.commands.append(cmd)
        return self.run_result

    def sync(self, **kw):
        kw.setdefault("source", self.source)
        kw.setdefault("answer_fn", self.answer_fn)
        kw.setdefault("runner", self.runner)
        kw.setdefault("base", ["teyla"])
        kw.setdefault("now", NOW)
        return relay.sync(**kw)

    def entry(self, **kw) -> dict:
        e = {"v": 1, "id": str(uuid.uuid4()), "kind": "answer", "target": "7c222b3d", "about": sha(QUESTION),
             "created": iso(NOW - 60), "device": "iPhone", "text": "Swap to 1.1."}
        e.update(kw)
        if "sig" not in kw:
            e["sig"] = relay.sign(KEY, relay.entry_message(e))
        return e

    def drop(self, e: dict, name: str | None = None) -> pathlib.Path:
        p = self.folder / "outbox" / (name or f"{e['id']}.json")
        p.write_text(json.dumps(e))
        return p

    def sent(self, eid: str) -> dict:
        return json.loads((self.folder / "sent" / f"{eid}.json").read_text())

    def journal(self, eid: str) -> dict:
        return json.loads((relay.journal_dir() / f"{eid.lower()}.json").read_text())


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# --- the signing vector -----------------------------------------------------------------------

def test_the_vector_is_reproduced_exactly():
    assert relay.pairing_string(KEY) == VEC["pairing"]
    body = VEC["state_json"].encode()
    assert relay.sign(KEY, relay.STATE_PREFIX + body) == VEC["state_sig"]
    assert relay.state_file(KEY, body) == VEC["state_file"].encode()
    e = VEC["entry"]
    assert relay.entry_message(e) == VEC["entry_message"].encode()
    assert relay.sign(KEY, relay.entry_message(e)) == e["sig"]
    assert relay.entry_shape(e) == ""
    assert relay.signature_ok(KEY, e)
    assert relay.sha256_hex(VEC["question"]) == e["about"]


def test_a_changed_field_breaks_the_signature():
    for field, value in (("text", "Swap to 1.0."), ("target", "b6b78de8"), ("device", "iPad"),
                         ("kind", "say"), ("created", "2026-10-17T21:45:01Z")):
        e = dict(VEC["entry"], **{field: value})
        assert not relay.signature_ok(KEY, e), field


def test_the_state_file_is_signed_over_exactly_its_bytes(env):
    res = env.sync()
    raw = (env.folder / "state.teyla").read_bytes()
    sig, _, body = raw.partition(b"\n")
    assert relay.sign(KEY, relay.STATE_PREFIX + body) == sig.decode()
    assert json.loads(body)["version"] == 2
    assert res == {"processed": [], "recovered": []}
    assert relay.read_cfg()["synced"] == SNAP["generated"]


# --- the key ----------------------------------------------------------------------------------

def test_key_is_created_0600_exclusively_and_never_overwritten(tmp_path):
    key = relay.create_key()
    assert len(key) == 32
    assert stat.S_IMODE(os.stat(relay.key_path()).st_mode) == 0o600
    assert relay.read_key() == key
    with pytest.raises(relay.RelayError, match="already paired"):
        relay.create_key()
    assert relay.read_key() == key


def test_rotate_replaces_the_key_and_leaves_no_temp_file(tmp_path):
    first = relay.create_key()
    second = relay.create_key(rotate=True)
    assert first != second and relay.read_key() == second
    assert stat.S_IMODE(os.stat(relay.key_path()).st_mode) == 0o600
    assert not list(relay.key_path().parent.glob("relay.key.*"))


def test_a_key_others_can_read_is_not_used(env):
    os.chmod(relay.key_path(), 0o644)
    assert relay.read_key() is None
    assert env.sync() == {"skipped": "not paired (no usable key)"}
    assert not (env.folder / "state.teyla").exists()


def test_pair_command_prints_the_pairing_string(capsys):
    assert cli.main(["relay", "pair", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pairing"] == relay.pairing_string(relay.read_key()) and out["new"] is True
    # A second pair shows the same key again, for a second phone or a lost QR code.
    assert cli.main(["relay", "pair", "--json"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["pairing"] == out["pairing"] and again["new"] is False
    assert cli.main(["relay", "pair", "--rotate", "--json"]) == 0
    rotated = json.loads(capsys.readouterr().out)
    assert rotated["rotated"] is True and rotated["pairing"] != out["pairing"]


# --- the happy path ---------------------------------------------------------------------------

def test_a_signed_answer_is_delivered_once_and_reported(env):
    e = env.entry()
    path = env.drop(e)
    res = env.sync()
    assert env.answers == [("7c222b3d", "Swap to 1.1.", False)]      # never the clipboard
    assert not path.exists()
    sent = env.sent(e["id"])
    assert sent["ok"] is True and sent["via"] == "claude-bg" and sent["id"] == e["id"] and sent["done_at"]
    j = env.journal(e["id"])
    assert j["state"] == "done" and j["result"]["ok"] is True
    assert "Swap" not in json.dumps(j)                                # the journal holds no text
    assert res["processed"][0]["ok"] is True


def test_say_and_dispatch_run_the_subcommands(env):
    say = env.entry(kind="say", target=RUNNING_ID, about=sha(RUNNING_TITLE), text="--also check the iPad build")
    dis = env.entry(kind="dispatch", target="atlas", about=sha("atlas"), text="Start the offline maps work.")
    env.drop(say), env.drop(dis)
    env.sync()
    assert ["teyla", "say", RUNNING_ID, "--json", "--", "--also check the iPad build"] in env.commands
    assert ["teyla", "dispatch", "atlas", "--json", "--", "Start the offline maps work."] in env.commands
    assert env.sent(say["id"])["via"] == "codex-queue" and env.sent(dis["id"])["ok"] is True


def test_a_missing_subcommand_is_reported_not_retried(env):
    env.run_result = (2, "", "teyla: error: argument cmd: invalid choice: 'say' (choose from ...)")
    e = env.entry(kind="say", target=RUNNING_ID, about=sha(RUNNING_TITLE))
    env.drop(e)
    env.sync()
    assert env.sent(e["id"]) == {**env.sent(e["id"]), "ok": False, "detail": "this Teyla cannot do say yet"}
    assert env.journal(e["id"])["state"] == "done"


def test_a_failed_subcommand_is_reported_with_its_detail(env):
    env.run_result = (1, json.dumps({"ok": False, "via": "", "detail": "no such worktree", "id": "x"}), "")
    e = env.entry(kind="dispatch", target="atlas", about=sha("atlas"))
    env.drop(e)
    env.sync()
    assert env.sent(e["id"])["ok"] is False and "no such worktree" in env.sent(e["id"])["detail"]


def _suggest_closing(env, ask_id="7c222b3d"):
    for row in env.snap["asks"]:
        if row["id"] == ask_id:
            row["triage"] = {"bucket": "close", "action": "", "default": "", "why": "A merged PR answers it", "source": "rule"}
    env.run_result = (0, json.dumps({"closed": [{"id": ask_id, "product": "cellar", "title": "t"}], "errors": [],
                                     "undo": f"teyla asks undo {ask_id}"}), "")


def test_close_runs_accept_close_for_exactly_one_question(env):
    _suggest_closing(env)
    e = env.entry(kind="close", text="close")
    env.drop(e)
    env.sync()
    assert env.commands == [["teyla", "asks", "accept-close", "7c222b3d", "--json"]]
    assert env.answers == []
    sent = env.sent(e["id"])
    assert sent["ok"] is True and sent["via"] == "asks" and sent["detail"] == "closed"


def test_close_is_refused_for_a_question_teyla_does_not_suggest_closing(env):
    env.snap["asks"][0]["triage"] = {"bucket": "owner", "action": "decide", "default": "", "why": "", "source": "rule"}
    refused(env, env.entry(kind="close", text="close"), "no longer suggests closing")
    refused(env, env.entry(kind="close", text="close", target="deadbeef"), "no longer open")


def test_close_checks_the_question_the_owner_saw(env):
    _suggest_closing(env)
    refused(env, env.entry(kind="close", text="close", about=sha("Keep iPhone 1.0?")), "changed since you read it")


def test_a_failed_close_reports_the_reason_from_the_command(env):
    _suggest_closing(env)
    env.run_result = (1, json.dumps({"closed": [], "errors": ["7c222b3d is not in bucket close: nothing was closed"],
                                     "undo": ""}), "")
    e = env.entry(kind="close", text="close")
    env.drop(e)
    env.sync()
    sent = env.sent(e["id"])
    assert sent["ok"] is False and "not in bucket close" in sent["detail"]


def test_reopen_runs_asks_undo_and_nothing_else(env):
    env.run_result = (0, "reopened: c0000001  sample-app  Is the beta build installable?", "")
    e = env.entry(kind="reopen", target="c0000001", about=sha("c0000001"), text="reopen")
    env.drop(e)
    env.sync()
    assert env.commands == [["teyla", "asks", "undo", "c0000001"]]
    sent = env.sent(e["id"])
    assert sent["ok"] is True and sent["detail"] == "reopened"
    assert "Is the beta" not in json.dumps(sent)


def test_reopen_reports_a_question_that_is_not_closed(env):
    env.run_result = (1, "", "not done: c0000001  sample-app  Title")
    e = env.entry(kind="reopen", target="c0000001", about=sha("c0000001"), text="reopen")
    env.drop(e)
    env.sync()
    assert env.sent(e["id"])["ok"] is False and "not done" in env.sent(e["id"])["detail"]


def test_reopen_needs_the_id_it_names_in_about(env):
    refused(env, env.entry(kind="reopen", target="c0000001", about=sha("something else"), text="reopen"),
            "changed since you read it")


def test_a_target_that_looks_like_an_option_never_reaches_a_command_line(env):
    for kind in ("close", "reopen"):
        res = relay.deliver_ask_action(kind, "--all", env.runner, ["teyla"])
        assert res[0] is False
    assert env.commands == []


def test_the_phone_can_run_only_these_commands(env):
    _suggest_closing(env)
    env.drop(env.entry(kind="close", text="close"))
    env.drop(env.entry(kind="reopen", target="c0000001", about=sha("c0000001"), text="reopen"))
    env.sync()
    assert sorted(c[1:3] for c in env.commands) == [["asks", "accept-close"], ["asks", "undo"]]


def test_the_state_file_carries_core_progress_triage_and_closed_questions(env):
    # The phone's Home and Decisions read these; the relay signs the snapshot whole, so they travel with it.
    home = json.loads((pathlib.Path(__file__).parents[1] / "apps/mac/TeylaTests/Fixtures/state.sample.home.json").read_text())
    env.snap = home
    env.sync()
    raw = (env.folder / "state.teyla").read_bytes()
    head, body = raw.split(b"\n", 1)
    assert relay.sign(KEY, relay.STATE_PREFIX + body) == head.decode()
    got = json.loads(body)
    assert got["portfolio"]["core"] == home["portfolio"]["core"] and got["portfolio"]["core_source"] == "star"
    first = got["portfolio"]["products"][0]
    assert first["progress"]["line"] and first["progress"]["shipped_7d"]["top"]
    assert {a["triage"]["bucket"] for a in got["asks"] if "triage" in a} == {"owner", "agent", "close"}
    assert got["auto_closed"]["count"] == 3 and got["auto_closed"]["items"][0]["reason"]
    assert "questions" in got["totals"]


def test_the_snapshot_is_rewritten_after_a_delivery(env):
    calls = []

    def source(now):
        calls.append(now)
        return env.source(now)
    env.drop(env.entry())
    env.sync(source=source)
    assert len(calls) == 2


# --- refusals ---------------------------------------------------------------------------------

def refused(env, e, reason, name=None):
    env.drop(e, name)
    env.sync()
    assert env.answers == [] and env.commands == []
    sent = env.sent(e["id"])
    assert sent["ok"] is False and reason in sent["detail"]
    assert e["text"] not in json.dumps(sent)
    assert not (env.folder / "outbox" / f"{e['id']}.json").exists()
    return sent


def test_bad_signature_is_refused_with_the_reason_only(env):
    e = env.entry(sig="0" * 64)
    refused(env, e, "bad signature")
    assert not (relay.journal_dir() / f"{e['id']}.json").exists()      # a forgery claims nothing


def test_a_signature_from_another_key_is_refused(env):
    e = env.entry()
    e["sig"] = relay.sign(b"\x01" * 32, relay.entry_message(e))
    refused(env, e, "bad signature")


def test_a_replayed_id_is_never_delivered_twice(env):
    e = env.entry()
    env.drop(e)
    env.sync()
    first = env.sent(e["id"])
    env.drop(e)                                                         # iCloud brings the same file back
    env.sync()
    assert len(env.answers) == 1
    assert env.sent(e["id"]) == first
    (env.folder / "sent" / f"{e['id']}.json").unlink()                  # the phone cleared the result
    env.drop(e)
    env.sync()
    assert len(env.answers) == 1
    again = env.sent(e["id"])
    assert again["ok"] is True and again["via"] == "claude-bg"          # the real result, not a made-up failure


def test_a_forged_copy_of_a_real_id_does_not_overwrite_its_result(env):
    e = env.entry()
    env.drop(e)
    env.sync()
    first = env.sent(e["id"])
    env.drop(dict(e, sig="f" * 64))
    env.sync()
    assert env.sent(e["id"]) == first


def test_stale_and_future_entries_are_refused(env):
    refused(env, env.entry(created=iso(NOW - 7 * 86400 - 1)), "too old")
    refused(env, env.entry(created=iso(NOW + 601)), "future")
    ok = env.entry(created=iso(NOW + 599))
    env.drop(ok)
    env.sync()
    assert env.sent(ok["id"])["ok"] is True


@pytest.mark.parametrize("field,value", [
    ("device", "iPhone\nkind"), ("device", ""), ("device", "x" * 65), ("target", "7c222b3d\n"),
    ("target", "a b"), ("target", ""), ("about", "A" * 64), ("about", sha(QUESTION) + "\n"),
    ("created", "2026-10-17 21:45:00"), ("created", "2026-13-17T21:45:00Z"), ("created", "2026-10-17T21:45:00Z\n"),
    ("kind", "wipe"), ("kind", "answer\n"), ("v", 2), ("v", "1"), ("v", True), ("id", "not-a-uuid"),
    ("text", "   "), ("text", "a\x00b"), ("text", "lone \ud800 surrogate"), ("sig", "AB" * 32),
])
def test_every_signed_field_must_match_its_pattern(env, field, value):
    e = env.entry()
    e[field] = value
    if field != "sig":
        e["sig"] = "0" * 64
        try:
            e["sig"] = relay.sign(KEY, relay.entry_message(e))          # properly signed, still refused
        except (UnicodeEncodeError, TypeError):
            pass
    name = f"{e['id']}.json" if _is_uuid(e["id"]) else f"{uuid.uuid4()}.json"
    env.drop(e, name)
    env.sync()
    assert env.answers == []
    assert not (env.folder / "outbox" / name).exists()


def _is_uuid(s) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def test_a_newline_in_device_cannot_shift_text_into_a_signed_field(env):
    # the signature is valid over the joined lines, but the pattern refuses the line break first
    e = env.entry(device="iPhone\nSwap to 1.1.", text="x")
    refused(env, e, "malformed entry")


def test_an_extra_unsigned_field_is_refused(env):
    e = env.entry()
    e["note"] = "unsigned"
    refused(env, e, "malformed entry")


def test_an_about_that_no_longer_matches_is_refused(env):
    refused(env, env.entry(about=sha("Keep iPhone 1.0?")), "changed since you read it")
    env.snap["asks"][0]["question"] = "Something else entirely?"
    refused(env, env.entry(), "changed since you read it")


def test_an_unknown_target_is_refused_for_every_kind(env):
    refused(env, env.entry(target="deadbeef"), "no longer open")
    refused(env, env.entry(kind="say", target="local_nope", about=sha("x")), "not running")
    refused(env, env.entry(kind="dispatch", target="nosuchproduct", about=sha("nosuchproduct")), "unknown product")
    ghost = env.entry(target="b6b78de8", about=sha(env.snap["asks"][1]["question"]))     # in the snapshot, not among the items
    refused(env, ghost, "no longer open")


def test_oversize_text_and_oversize_files_are_refused(env):
    refused(env, env.entry(text="x" * 8001), "longer than 8,000")
    big = env.entry()
    big["pad"] = "z" * 70000
    refused(env, big, "larger than 64 KB")
    ok = env.entry(text="y" * 8000)
    env.drop(ok)
    env.sync()
    assert env.sent(ok["id"])["ok"] is True


def test_a_symlink_in_the_outbox_is_not_followed(env, tmp_path):
    e = env.entry()
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(e))
    link = env.folder / "outbox" / f"{e['id']}.json"
    link.symlink_to(target)
    env.sync()
    assert env.answers == []
    assert not link.exists() and target.exists()


def test_icloud_placeholders_and_strays_are_left_alone(env):
    e = env.entry()
    placeholder = env.folder / "outbox" / f".{e['id']}.json.icloud"
    placeholder.write_text("x")
    stray = env.folder / "outbox" / "notes.json"
    stray.write_text("{}")
    env.sync()
    assert placeholder.exists() and stray.exists() and env.answers == []
    assert list((env.folder / "sent").iterdir()) == []


def test_an_unfinished_download_waits_and_a_stale_one_is_refused(env):
    e = env.entry()
    p = env.folder / "outbox" / f"{e['id']}.json"
    p.write_text(json.dumps(e)[:40])
    os.utime(p, (NOW - 5, NOW - 5))
    env.sync()
    assert p.exists() and not (env.folder / "sent" / f"{e['id']}.json").exists()
    os.utime(p, (NOW - 600, NOW - 600))
    env.sync()
    assert not p.exists() and env.sent(e["id"])["ok"] is False


# --- at most once -----------------------------------------------------------------------------

def test_a_crash_between_claim_and_delivery_is_never_retried(env):
    e = env.entry()
    path = env.drop(e)

    def dies(item, text, clipboard=True):
        raise Crash(CRASH_MSG)
    with pytest.raises(Crash):
        env.sync(answer_fn=dies)
    assert env.journal(e["id"])["state"] == "claimed" and path.exists()
    assert not (env.folder / "sent" / f"{e['id']}.json").exists()
    env.sync()                                                          # the next pass
    assert env.answers == []
    sent = env.sent(e["id"])
    assert sent["ok"] is False and sent["detail"] == "interrupted; check the session, then send again"
    assert env.journal(e["id"])["state"] == "interrupted" and not path.exists()
    env.drop(e)                                                         # even the same file again
    env.sync()
    assert env.answers == []


def test_a_crash_after_the_result_is_not_repeated_either(env):
    e = env.entry()
    path = env.drop(e)
    real = relay.write_sent

    def dies(*a, **k):
        raise Crash(CRASH_MSG)
    relay.write_sent = dies
    try:
        with pytest.raises(Crash):
            env.sync()
    finally:
        relay.write_sent = real
    assert env.journal(e["id"])["state"] == "done" and path.exists()
    env.sync()
    assert len(env.answers) == 1                                        # replay: sent/ rebuilt from the journal
    assert env.sent(e["id"])["ok"] is True and not path.exists()


def test_a_delivery_that_raises_is_reported_and_not_retried(env):
    e = env.entry()
    env.drop(e)

    def boom(item, text, clipboard=True):
        raise RuntimeError("secret detail that must not leak: " + text)
    env.sync(answer_fn=boom)
    sent = env.sent(e["id"])
    assert sent["ok"] is False and "RuntimeError" in sent["detail"] and "secret" not in sent["detail"]
    assert env.journal(e["id"])["state"] == "done"


# --- no clipboard -----------------------------------------------------------------------------

@pytest.fixture
def no_real_delivery(monkeypatch):
    calls = []
    monkeypatch.setattr(answer, "run", lambda cmd, **k: calls.append(cmd) or (0, ""))
    return calls


def test_answer_without_clipboard_refuses_the_copy_and_open_fallback(no_real_delivery):
    a = make_ask()
    res = answer.answer(a, "yes", clipboard=False)
    assert res["ok"] is False and res["detail"] == "needs the Mac"
    assert no_real_delivery == []                                       # no pbcopy, no open
    res = answer.answer(a, "yes")                                       # the default is unchanged
    assert res["ok"] is True and res["via"] == "opened" and ["pbcopy"] in no_real_delivery


def test_a_relay_answer_that_needs_the_mac_leaves_the_question_open(env, no_real_delivery):
    e = env.entry()
    env.drop(e)
    env.sync(answer_fn=answer.answer)
    assert no_real_delivery == []
    sent = env.sent(e["id"])
    assert sent["ok"] is False and sent["detail"] == "needs the Mac"
    assert asks.load_state()["done"] == {}


# --- the lock, the atomic write, the guards ---------------------------------------------------

def test_a_held_lock_skips_the_pass_quietly(env):
    env.drop(env.entry())
    fd = os.open(relay.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        res = env.sync(source=lambda now: pytest.fail("the pass must not start"))
    finally:
        os.close(fd)
    assert res == {"skipped": "another pass is running"}
    assert env.answers == []
    assert env.sync()["processed"]                                      # free again


def test_the_snapshot_write_is_atomic(env, monkeypatch):
    env.sync()
    before = (env.folder / "state.teyla").read_bytes()
    env.snap["generated"] = "2026-10-17T22:00:00Z"

    def fail(dfd, src, dst):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(relay, "_rename_at", fail)
        with pytest.raises(OSError):
            env.sync()
    assert (env.folder / "state.teyla").read_bytes() == before          # the old file, whole
    assert sorted(p.name for p in env.folder.iterdir()) == ["outbox", "sent", "state.teyla"]
    env.sync()
    assert b"22:00:00Z" in (env.folder / "state.teyla").read_bytes()


def test_safe_mode_makes_sync_a_no_op(env, monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    env.drop(env.entry())
    res = env.sync(source=lambda now: pytest.fail("safe mode must not read sessions"))
    assert res == {"skipped": "safe mode"}
    assert env.answers == [] and not (env.folder / "state.teyla").exists()


def test_a_relay_that_is_off_does_nothing(env):
    cfg = relay.read_cfg()
    cfg["on"] = False
    relay.write_cfg(cfg)
    assert env.sync() == {"skipped": "relay is off"}


def test_old_journal_entries_are_pruned_and_recent_ones_kept(env):
    jd = relay.journal_dir()
    jd.mkdir(parents=True, exist_ok=True)
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    (jd / f"{old}.json").write_text(json.dumps({"id": old, "state": "done", "ts": iso(NOW - 9 * 86400)}))
    (jd / f"{new}.json").write_text(json.dumps({"id": new, "state": "done", "ts": iso(NOW - 7 * 86400)}))
    env.sync()
    assert not (jd / f"{old}.json").exists() and (jd / f"{new}.json").exists()


def test_config_and_journal_files_are_private(env):
    e = env.entry()
    env.drop(e)
    env.sync()
    for p in (relay.cfg_path(), relay.journal_dir() / f"{e['id']}.json", relay.lock_path()):
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
    assert stat.S_IMODE(os.stat(relay.journal_dir()).st_mode) == 0o700


# --- on / off / status ------------------------------------------------------------------------

def test_on_writes_the_agent_and_off_removes_it(tmp_path, monkeypatch):
    folder = tmp_path / "icloud" / "Teyla"
    monkeypatch.setattr(relay, "configured_folder", lambda: folder)
    loaded, unloaded = [], []
    lines = relay.relay_on(load=lambda plist, label: loaded.append(label) or f"loaded {label}")
    assert (folder / "outbox").is_dir() and (folder / "sent").is_dir()
    cfg = relay.read_cfg()
    assert cfg == {"on": True, "folder": str(folder), "synced": ""}
    assert stat.S_IMODE(os.stat(relay.cfg_path()).st_mode) == 0o600
    plist = plistlib.loads(relay.plist_path().read_bytes())
    assert plist["Label"] == relay.LABEL and plist["StartInterval"] == 60
    assert plist["WatchPaths"] == [str(folder / "outbox")] and "PATH" in plist["EnvironmentVariables"]
    assert relay.wrapper_path().stat().st_mode & 0o111
    assert 'relay sync --quiet' in relay.wrapper_path().read_text()
    assert (loaded == [relay.LABEL]) == (sys.platform == "darwin")
    assert any("not paired yet: run `teyla relay connect`" in l for l in lines)
    st = relay.status()
    assert st["on"] is True and st["paired"] is False and st["agent"] is True
    relay.relay_off(unload=lambda plist, label: unloaded.append(label) or "unloaded")
    assert not relay.plist_path().exists() and not relay.wrapper_path().exists()
    assert folder.is_dir()                                              # the folder is left
    assert relay.read_cfg()["on"] is False and relay.read_cfg()["folder"] == str(folder)
    assert (unloaded == [relay.LABEL]) == (sys.platform == "darwin")


def test_on_refuses_an_icloud_folder_when_icloud_drive_is_missing(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    with pytest.raises(relay.RelayError, match="iCloud Drive"):
        relay.relay_on(load=lambda *a: "")


def test_status_json_matches_the_snapshot_relay_object(env, capsys):
    assert cli.main(["relay", "status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["on"] is True and st["paired"] is True and st["folder"] == str(env.folder)
    assert set(SNAP["relay"]) <= set(st)


# --- connect ----------------------------------------------------------------------------------

@pytest.fixture
def connect_env(tmp_path, monkeypatch):
    """Everything `relay connect` touches is stubbed: no launchctl, no real sync, no `open`."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    folder = tmp_path / "icloud" / "Teyla"
    monkeypatch.setattr(relay, "configured_folder", lambda: folder)
    monkeypatch.setattr(relay.ri, "_load", lambda plist, label: f"loaded {label}")

    class C:
        pass

    c = C()
    c.home, c.folder, c.opened, c.syncs = home, folder, [], []
    c.open_ok, c.sync_result = True, {"processed": [], "recovered": []}

    def opener(url):
        c.opened.append(url)
        return c.open_ok

    def fake_sync(**kw):
        c.syncs.append(kw)
        if isinstance(c.sync_result, Exception):
            raise c.sync_result
        return c.sync_result

    monkeypatch.setattr(relay, "open_pairing", opener)
    monkeypatch.setattr(relay, "sync", fake_sync)
    return c


def test_connect_hands_the_key_over_and_does_not_print_it(connect_env, capsys):
    assert cli.main(["relay", "connect"]) == 0
    cap = capsys.readouterr()
    pairing = relay.pairing_string(relay.read_key())
    assert connect_env.opened == [pairing]
    assert pairing not in cap.out + cap.err and pairing.split(":")[-1] not in cap.out + cap.err
    assert 'click "Use this folder"' in cap.out
    assert "run `teyla relay pair` and paste the string" in cap.out
    assert "choose Connect iPhone and scan the QR code" in cap.out
    assert relay.read_cfg()["on"] is True and len(connect_env.syncs) == 1
    assert "not paired yet" not in cap.out + cap.err


def test_connect_reuses_the_existing_key_and_never_rotates(connect_env, capsys):
    key = relay.create_key()
    assert cli.main(["relay", "connect", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["new"] is False and relay.read_key() == key
    assert connect_env.opened == [relay.pairing_string(key)]
    assert cli.main(["relay", "connect", "--json"]) == 0
    assert relay.read_key() == key


def test_connect_json_when_handed_over_has_no_pairing(connect_env, capsys):
    assert cli.main(["relay", "connect", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"on": True, "folder": str(connect_env.folder), "new": True, "handed_over": True, "synced": True}


def test_connect_prints_the_pairing_string_when_the_hand_over_fails(connect_env, capsys):
    connect_env.open_ok = False
    assert cli.main(["relay", "connect"]) == 0
    cap = capsys.readouterr()
    pairing = relay.pairing_string(relay.read_key())
    assert cap.out.strip() == pairing
    assert ("Paste this into Teyla on your Mac or iPhone, or scan its QR code in Teyla on the Mac (Connect iPhone). "
            "It is the key: do not share it.") in cap.err
    assert "needs no pairing" not in cap.err
    (connect_env.home / "Applications" / "Teyla Admin.app").mkdir(parents=True)
    assert cli.main(["relay", "connect"]) == 0
    assert "needs no pairing" in capsys.readouterr().err
    assert cli.main(["relay", "connect", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["handed_over"] is False and out["pairing"] == pairing


def test_connect_survives_a_failed_or_skipped_first_sync(connect_env, capsys):
    connect_env.sync_result = RuntimeError("disk full")
    assert cli.main(["relay", "connect", "--json"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["synced"] is False and "first sync failed" in cap.err
    connect_env.sync_result = {"skipped": "safe mode"}
    assert cli.main(["relay", "connect", "--json"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["synced"] is False and "first sync skipped: safe mode" in cap.err


def test_the_default_opener_is_an_argv_list_on_macos_only(monkeypatch):
    calls = []

    class R:
        returncode = 0

    monkeypatch.setattr(relay.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or R())
    monkeypatch.setattr(relay.sys, "platform", "linux")
    assert relay.open_pairing("teyla-pair:v1:x") is False and calls == []
    monkeypatch.setattr(relay.sys, "platform", "darwin")
    assert relay.open_pairing("teyla-pair:v1:x") is True
    assert calls[0][0] == ["open", "-b", "com.zaitsew.teyla", "teyla-pair:v1:x"] and not calls[0][1].get("shell")


def test_pair_says_where_the_key_goes(capsys):
    assert cli.main(["relay", "pair"]) == 0
    assert "Paste this into Teyla on your Mac or iPhone" in capsys.readouterr().err


# --- an unsafe folder ------------------------------------------------------------------------

def test_an_outbox_linked_into_the_journal_stops_the_pass(env):
    import shutil
    shutil.rmtree(env.folder / "outbox")
    relay.journal_dir().mkdir(parents=True, exist_ok=True)
    claim = relay.journal_dir() / "kept.json"
    claim.write_text("{}")
    os.symlink(relay.journal_dir(), env.folder / "outbox")
    res = env.sync()
    assert res["skipped"].startswith("unsafe relay folder") and claim.exists()
    assert env.answers == [] and not (env.folder / "state.teyla").exists()


def test_an_outbox_swapped_for_a_journal_link_during_the_pass_changes_nothing(env):
    # The folder passes the check; then, while the snapshot is built, outbox is moved away and a link to
    # the journal takes its place. The pass keeps working on the directories it opened.
    import shutil
    relay.journal_dir().mkdir(parents=True, exist_ok=True)
    claim = relay.journal_dir() / f"{uuid.uuid4()}.json"
    claim.write_text(json.dumps({"id": claim.stem, "state": "done"}))
    e = env.entry()
    env.drop(e)
    real_source = env.source

    def swap(now):
        if not (env.folder / "outbox.old").exists():
            (env.folder / "outbox").rename(env.folder / "outbox.old")
            os.symlink(relay.journal_dir(), env.folder / "outbox")
        return real_source(now)
    res = env.sync(source=swap)
    assert claim.exists()                                               # the journal is untouched
    assert [r["id"] for r in res["processed"]] == [e["id"]] and len(env.answers) == 1
    assert not (env.folder / "outbox.old" / f"{e['id']}.json").exists()
    assert env.sent(e["id"])["ok"] is True
    assert env.sync()["skipped"].startswith("unsafe relay folder")      # the next pass sees the link
    shutil.rmtree(env.folder / "outbox.old")


def test_a_new_journal_directory_is_made_durable(env, monkeypatch):
    synced = []
    real = relay._fsync_dir
    monkeypatch.setattr(relay, "_fsync_dir", lambda path: (synced.append(pathlib.Path(path)), real(path)))
    assert not relay.journal_dir().exists()
    env.drop(env.entry())
    env.sync()
    assert synced[:2] == [relay.journal_dir().parent, relay.journal_dir()]


def test_a_folder_inside_teylas_home_is_refused(env):
    inside = relay.journal_dir().parent / "relay-inside"
    for sub in ("outbox", "sent"):
        (inside / sub).mkdir(parents=True)
    assert "overlaps" in env.sync(folder=inside)["skipped"]


def test_a_directory_named_like_an_entry_does_not_stop_the_pass(env):
    (env.folder / "outbox" / f"{uuid.uuid4()}.json").mkdir()
    e = env.entry()
    env.drop(e)
    env.sync()
    assert env.sent(e["id"])["ok"] is True


def test_the_plist_stays_valid_with_xml_characters_in_the_folder(tmp_path, monkeypatch):
    folder = tmp_path / "Tom & Jerry <docs>" / "Teyla"
    monkeypatch.setattr(relay, "configured_folder", lambda: folder)
    relay.relay_on(load=lambda *a: "")
    plist = plistlib.loads(relay.plist_path().read_bytes())
    assert plist["WatchPaths"] == [str(folder / "outbox")]


# --- activity: the phone's +1 ----------------------------------------------------------------

def test_activity_runs_growth_log_for_exactly_one_known_kind(env):
    env.run_result = (0, "logged", "")
    e = env.entry(kind="activity", target="comment", about=sha("comment"), text="+1")
    env.drop(e)
    env.sync()
    assert env.commands == [["teyla", "growth", "log", "--kind", "comment"]]
    assert env.answers == []
    sent = env.sent(e["id"])
    assert sent["ok"] is True and sent["via"] == "growth" and sent["detail"] == "logged"


@pytest.mark.parametrize("kind", relay.ACTIVITY_KINDS)
def test_every_listed_activity_kind_is_accepted(env, kind):
    e = env.entry(kind="activity", target=kind, about=sha(kind), text="+1")
    env.drop(e)
    env.sync()
    assert env.commands == [["teyla", "growth", "log", "--kind", kind]]


@pytest.mark.parametrize("target", ["--all", "unknown", "Post", "rm", "post;ls", "post/../x", "-"])
def test_activity_refuses_free_text_and_unknown_kinds(env, target):
    e = env.entry(kind="activity", target=target, about=sha(target), text="+1")
    env.drop(e)
    env.sync()
    assert env.commands == []
    assert env.sent(e["id"])["ok"] is False


def test_activity_refuses_a_wrong_about(env):
    refused(env, env.entry(kind="activity", target="post", about=sha("comment"), text="+1"), "changed since you read it")


def test_activity_text_must_be_the_fixed_plus_one(env):
    refused(env, env.entry(kind="activity", target="post", about=sha("post"), text="+50 --count 50"), "malformed entry: text")


def test_a_failed_activity_log_reports_the_command_text(env):
    env.run_result = (1, "", "teyla growth: unknown product")
    e = env.entry(kind="activity", target="post", about=sha("post"), text="+1")
    env.drop(e)
    env.sync()
    sent = env.sent(e["id"])
    assert sent["ok"] is False and "unknown product" in sent["detail"]


def test_an_older_teyla_without_growth_log_is_reported(env):
    env.run_result = (2, "", "error: argument cmd: invalid choice: 'log'")
    e = env.entry(kind="activity", target="post", about=sha("post"), text="+1")
    env.drop(e)
    env.sync()
    assert "cannot log activity" in env.sent(e["id"])["detail"]


def test_the_phone_can_still_run_only_the_listed_commands_with_activity(env):
    env.drop(env.entry(kind="activity", target="email", about=sha("email"), text="+1"))
    env.sync()
    assert [c[1:3] for c in env.commands] == [["growth", "log"]]


def _activity_json(**kw):
    days = [{"day": f"2026-10-{d:02d}", "count": d % 3, "level": d % 3, "kinds": {"note": "secret"}} for d in range(1, 31)]
    raw = {"version": 1, "today": "2026-10-30", "weeks": 17, "start": "2026-10-01", "days": days, "total": 300,
           "today_count": 2, "week_count": 5, "streak": 3, "longest": 9, "by_kind": {"post": 4}, "claimed": 1,
           "outcomes": {"meetings": 1, "responses": 2}, "kinds": ["post", "comment", "bogus"]}
    raw.update(kw)
    return json.dumps(raw)


def test_the_phone_snapshot_carries_counts_only(env):
    view = relay.activity_view(lambda cmd, t: (0, _activity_json(), ""), ["teyla"])
    assert view["today_count"] == 2 and view["streak"] == 3 and view["longest"] == 9 and view["total"] == 300
    assert view["kinds"] == ["post", "comment"]
    assert set(view["days"][0]) == {"day", "count", "level"}
    assert "secret" not in json.dumps(view) and "outcomes" not in view and "by_kind" not in view and "claimed" not in view


def test_the_phone_snapshot_has_no_activity_when_the_command_is_missing_or_broken():
    assert relay.activity_view(lambda c, t: (2, "", "invalid choice"), ["teyla"]) is None
    assert relay.activity_view(lambda c, t: (0, "not json", ""), ["teyla"]) is None
    assert relay.activity_view(lambda c, t: (0, "{}", ""), ["teyla"]) is None



def test_the_phone_gets_seventeen_whole_weeks_starting_on_a_monday():
    full = (pathlib.Path(__file__).parent.parent / "apps/mac/TeylaTests/Fixtures/activity.v1.json").read_text()
    view = relay.activity_view(lambda cmd, t: (0, full, ""), ["teyla"])
    assert view["start"] == "2026-07-13" and dt.date.fromisoformat(view["start"]).weekday() == 0
    assert view["days"][-1]["day"] == "2026-11-06" and len(view["days"]) == 117
    assert view["total"] == 719                      # the year's total, not the 17 weeks'
    assert view["streak"] == 5 and view["today_count"] == 6


def test_the_snapshot_asks_for_17_weeks():
    seen = []
    relay.activity_view(lambda cmd, t: (seen.append(cmd), (1, "", ""))[1], ["teyla"])
    assert seen == [["teyla", "growth", "activity", "--json", "--weeks", "17"]]


# --- gtm: the Today card ---------------------------------------------------------------------

def _gtm_json(**kw):
    raw = {"version": 1, "day": "2026-11-07", "week": "2026-W45", "has_goals": True,
           "approve": {"total": 6, "by_source": {"growth": 4, "src": 2}, "links": {"src": "https://example.com/q"}},
           "send": {"total": 5, "by_source": {"src": 5}, "links": {}}, "reply": {"total": 2, "by_source": {}, "links": {}},
           "follow_up": {"total": 0, "by_source": {}, "links": {}},
           "distribution": {"today": 3, "target": 10, "week": 21, "claimed_by_agents": 4},
           "preparation": {"today": 40, "week": 283}, "outcomes": {"today": 1, "week": 9},
           "goals": [{"id": "relationships", "title": "Conversations", "done_when": "A sale", "deadline": "2027-03-01",
                      "days_left": 114, "weeks_left": 16, "short": 9, "fed_by": ["src"], "unfed": ["secret-source"],
                      "targets": [{"stage": "conversation", "count": 6, "target": 15, "counter": "outcomes",
                                   "history": [{"week": "2026-W45", "count": 6}]},
                                  {"stage": "approached", "count": 21, "target": 60, "counter": "distribution"},
                                  {"stage": "odd", "count": 1, "target": 2, "counter": "rm -rf"}]}],
           "next": [{"kind": "reply", "count": 2, "label": "answer 2 replies", "sources": ["src"]},
                    {"kind": "rm -rf", "count": 1}],
           "sources": [{"id": "src", "state": "ok", "line": "secret-path"}], "doctor": ["src: missing: secret-path"]}
    raw.update(kw)
    return json.dumps(raw)


def test_the_gtm_card_carries_counts_and_goals_only():
    view = relay.gtm_view(lambda cmd, t: (0, _gtm_json(), ""), ["teyla"])
    assert view is not None and view["approve"] == 6 and view["send"] == 5 and view["reply"] == 2
    assert view["distribution"] == {"today": 3, "target": 10, "week": 21} and view["outcomes_week"] == 9
    goal = view["goals"][0]
    assert goal["targets"] == [{"stage": "conversation", "count": 6, "target": 15, "counter": "outcomes"},
                               {"stage": "approached", "count": 21, "target": 60, "counter": "distribution"},
                               {"stage": "odd", "count": 1, "target": 2, "counter": "outcomes"}]
    assert (goal["done_when"], goal["weeks_left"], goal["short"], goal["days_left"]) == ("A sale", 16, 9, 114)
    assert goal["deadline"] == "2027-03-01"
    assert view["next"] == [{"kind": "reply", "count": 2}]
    text = json.dumps(view)
    assert "secret-path" not in text and "example.com" not in text and "src" not in text and "preparation" not in text
    assert "history" not in text and "secret-source" not in text and "fed_by" not in text


def test_the_gtm_card_is_hidden_when_the_command_is_missing_or_broken():
    assert relay.gtm_view(lambda c, t: (2, "", "invalid choice"), ["teyla"]) is None
    assert relay.gtm_view(lambda c, t: (0, "nope", ""), ["teyla"]) is None
    assert relay.gtm_view(lambda c, t: (0, _gtm_json(version=2), ""), ["teyla"]) is None


def test_the_gtm_card_runs_gtm_today_json():
    seen = []
    relay.gtm_view(lambda cmd, t: (seen.append(cmd), (1, "", ""))[1], ["teyla"])
    assert seen == [["teyla", "gtm", "today", "--json"]]

