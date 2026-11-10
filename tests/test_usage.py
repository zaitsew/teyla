"""`teyla usage` and the usage batches the shared review channel carries (src/teyla/usage.py). Fixtures are
generic: a made-up product, ids and builds; no real names or paths."""
from __future__ import annotations

import json
import pathlib
import shutil
import stat

import pytest

from teyla import cli, review, review_channel, usage

DAY = 86400
T0 = 1_793_400_000                    # 2026-10-31 in UTC
INSTALL_A = "0b8f5c1e-7a2d-4e63-9d10-6c4a8e2f1b57"
INSTALL_B = "9d2e7a40-3c11-4b5f-8a66-1e0f4d7c2b93"
B1, B2, B3 = ("3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11", "8a1d2e33-0c4f-4b6a-8e7d-5f9a0b1c2d3e",
              "c2b7e9a4-1d3f-4a85-b6c0-7e8f9a0b1c2d")
DECLARED = {"screens": ["home.main", "trip.timeline", "settings.main", "legacy.screen"],
            "actions": ["trip.addButton", "plan.save"], "tasks": ["plan.day"]}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "teyla-home"))
    return tmp_path


def ev(t, k, id=None, r=None, ms=None, b="212", d=None):
    e = {"t": T0 + t, "k": k, "b": b}
    for key, val in (("id", id), ("r", r), ("ms", ms), ("d", d)):
        if val is not None:
            e[key] = val
    return e


def batch(events, cid=B1, install=INSTALL_A, product="sample", build="212", declared=DECLARED, sent="2026-10-31T10:00:00Z"):
    return {"v": 1, "kind": "usage", "id": cid, "install": install, "sent": sent,
            "app": {"bundle_id": "com.example.sample", "version": "1.4.0", "build": build, "product": product,
                    "configuration": "testflight"},
            "declared": declared, "events": events}


def folder(root: pathlib.Path, body: dict, cid: str | None = None) -> pathlib.Path:
    d = root / (cid or body["id"])
    d.mkdir(parents=True)
    (d / "usage.json").write_text(json.dumps(body))
    return d


def stored(home, product="sample"):
    d = home / "teyla-home" / "usage" / product
    return sorted(d.glob("*.json")) if d.is_dir() else []


SESSION = [ev(0, "session", r="start"), ev(1, "screen", "home.main"), ev(30, "screen", "trip.timeline"),
           ev(31, "action", "trip.addButton", "done"), ev(32, "action", "trip.addButton", "cancelled"),
           ev(40, "task", "plan.day", "start"), ev(100, "task", "plan.day", "success", ms=60_000),
           ev(120, "session", r="background")]


# --- the import ---------------------------------------------------------------------------------

def test_a_batch_is_stored_private_and_known_the_second_time(home):
    got = usage.import_folder("sample", folder(home / "in", batch(SESSION)))
    assert got["ok"] and got["events"] == len(SESSION) and got["dropped"] == 0 and not got["known"]
    [f] = stored(home)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    again = usage.import_folder("sample", folder(home / "in2", batch(SESSION)))
    assert again["ok"] and again["known"] and len(stored(home)) == 1


def test_a_batch_for_another_product_or_with_another_id_is_refused(home):
    assert not usage.import_folder("other", folder(home / "a", batch(SESSION)))["ok"]
    wrong_id = folder(home / "b", batch(SESSION, cid=B2), cid=B1)
    assert not usage.import_folder("sample", wrong_id)["ok"]
    body = batch(SESSION)
    body["kind"] = "capture"
    assert not usage.import_folder("sample", folder(home / "c", body, cid=B3))["ok"]
    assert stored(home) == []


def test_an_event_with_free_text_or_a_wrong_shape_is_dropped(home):
    bad = [ev(1, "screen", "A title with spaces"),
           ev(2, "action", "plan.save", "I typed this sentence"),
           ev(3, "task", "plan.day", "start", ms=-5),
           {"t": T0, "k": "comment", "b": "212", "id": "x"},
           ev(4, "screen", "home.main", d={"Nav Bar": "x"}),
           ev(5, "session", id="trip.timeline", r="start"),
           ev(6, "action", "plan.save", "done", b="a long free text build number")]
    good = ev(7, "screen", "home.main", d={"nav": "bottom-bar"})
    good["comment"] = "extra key a tester typed"
    got = usage.import_folder("sample", folder(home / "in", batch(bad + [good])))
    assert got["events"] == 1 and got["dropped"] == len(bad)
    [f] = stored(home)
    text = f.read_text()
    assert "sentence" not in text and "extra key" not in text and "spaces" not in text
    assert json.loads(text)["events"] == [{"t": T0 + 7, "k": "screen", "b": "212", "id": "home.main", "d": {"nav": "bottom-bar"}}]


def test_an_oversized_or_unreadable_batch_is_left_alone(home):
    d = home / "in" / B1
    d.mkdir(parents=True)
    (d / "usage.json").write_text("{not json")
    assert not usage.import_folder("sample", d)["ok"]
    (d / "usage.json").write_text(json.dumps(batch(SESSION)) + " " * usage.MAX_JSON)
    assert not usage.import_folder("sample", d)["ok"]


def test_prune_removes_a_batch_older_than_the_promised_retention(home):
    old = [ev(0, "screen", "home.main")]
    usage.import_folder("sample", folder(home / "a", batch(old, cid=B1)))
    usage.import_folder("sample", folder(home / "b", batch([ev(200 * DAY, "screen", "home.main")], cid=B2)))
    assert usage.prune(now=T0 + 201 * DAY) == 1
    assert [f.stem for f in stored(home)] == [B2]


# --- the pull -----------------------------------------------------------------------------------

class FakeRemote(review_channel.Remote):
    def __init__(self, ready: pathlib.Path):
        super().__init__("tester@example.com", "/srv/x")
        self.ready, self.deleted = ready, []

    def fetch(self, dest):
        shutil.copytree(self.ready, dest, dirs_exist_ok=True)

        class Done:
            returncode = 0
        return Done()

    def delete(self, items):
        self.deleted += items
        return []


def test_the_channel_pull_files_usage_apart_from_captures_and_deletes_the_server_copy(home, monkeypatch):
    monkeypatch.setattr(review_channel, "notify", lambda n: (_ for _ in ()).throw(AssertionError("no banner for usage")))
    ready = home / "server" / "ready"
    folder(ready / "sample", batch(SESSION))
    conn = review.connect()
    try:
        remote = FakeRemote(ready)
        rep = review_channel.pull_remote(conn, remote)
        assert rep["usage_batches"] == 1 and rep["usage_events"] == len(SESSION) and rep["added"] == 0
        assert rep["skipped"] == [] and remote.deleted == [("sample", B1)]
        assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0     # never in the review inbox
    finally:
        conn.close()
    assert [f.stem for f in stored(home)] == [B1]


def test_a_bad_usage_batch_stays_on_the_server_and_is_reported(home):
    ready = home / "server" / "ready"
    folder(ready / "sample", batch(SESSION, product="other"))
    conn = review.connect()
    try:
        remote = FakeRemote(ready)
        rep = review_channel.pull_remote(conn, remote)
        assert remote.deleted == [] and rep["usage_batches"] == 0 and len(rep["skipped"]) == 1
    finally:
        conn.close()
    assert stored(home) == []


def test_an_event_with_an_unhashable_field_is_dropped_and_never_stops_the_import(home):
    bad = [ev(1, "action", "plan.save", []), ev(2, "action", "plan.save", {"a": 1}),
           {"t": T0, "k": ["screen"], "b": "212", "id": "home.main"},
           {"t": T0, "k": "screen", "b": "212", "id": ["home.main"]},
           {"t": T0, "k": "screen", "b": ["212"], "id": "home.main"}]
    good = ev(7, "screen", "home.main")
    got = usage.import_folder("sample", folder(home / "in", batch(bad + [good])))
    assert got["ok"] and got["events"] == 1 and got["dropped"] == len(bad)


def test_one_batch_that_raises_does_not_stop_the_pull_or_the_cleanup(home, monkeypatch):
    ready = home / "server" / "ready"
    folder(ready / "sample", batch(SESSION, cid=B1))
    folder(ready / "sample", batch(SESSION, cid=B2))
    real = usage.import_folder

    def flaky(product, d, now=None):
        if d.name == B1:
            raise TypeError("unhashable type: 'list'")
        return real(product, d, now)
    monkeypatch.setattr(usage, "import_folder", flaky)
    conn = review.connect()
    try:
        remote = FakeRemote(ready)
        rep = review_channel.pull_remote(conn, remote)
        assert rep["usage_batches"] == 1 and len(rep["skipped"]) == 1
        assert remote.deleted == [("sample", B2)]
    finally:
        conn.close()


def test_usage_retention_runs_even_when_the_pull_cannot_start(home, monkeypatch):
    usage.import_folder("sample", folder(home / "a", batch([ev(0, "screen", "home.main")], cid=B1)))
    path = stored(home)[0]
    old = T0 - 400 * DAY
    data = json.loads(path.read_text())
    data["events"][0]["t"] = old
    path.write_text(json.dumps(data))
    monkeypatch.setattr(review.time, "time", lambda: T0) if hasattr(review, "time") else None
    monkeypatch.setattr(usage.time, "time", lambda: T0)
    monkeypatch.setattr(review, "prune_channel", lambda conn: {"deleted": 0, "kept": []})

    def no_config():
        raise review_channel.ChannelError("no channel config", 2)
    monkeypatch.setattr(review_channel, "load_config", no_config)
    conn = review.connect()
    try:
        args = type("A", (), {"json": False})()
        assert review_channel.cmd_pull(conn, args) == 2
    finally:
        conn.close()
    assert stored(home) == []


# --- the report ---------------------------------------------------------------------------------

def load(home, *batches):
    for i, b in enumerate(batches):
        usage.import_folder(b["app"]["product"], folder(home / f"in{i}", b))


def run(capsys, *argv):
    code = cli.main(["usage", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_report_names_top_screens_actions_task_time_and_never_opened_screens(home, capsys):
    other = [ev(0, "session", r="start"), ev(2, "screen", "home.main"), ev(60, "task", "plan.day", "start"),
             ev(180, "task", "plan.day", "success", ms=120_000), ev(200, "session", r="background")]
    load(home, batch(SESSION), batch(other, cid=B2, install=INSTALL_B))
    code, out, _ = run(capsys, "sample", "--json")
    data = json.loads(out)
    assert code == 0 and data["installs"] == 2 and data["events"] == len(SESSION) + len(other)
    assert data["top_screens"][0] == {"id": "home.main", "opens": 2, "installs": 2}
    assert data["top_actions"][0]["id"] == "trip.addButton" and data["top_actions"][0]["results"] == {"cancelled": 1, "done": 1}
    assert data["tasks"]["plan.day"] == {"started": 2, "succeeded": 2, "cancelled": 0, "median_seconds": 90.0, "timed": 2}
    assert data["never_opened"] == ["legacy.screen", "settings.main"]
    assert data["visits"] == 2 and data["active_minutes"] == 5.3        # 120 s and 200 s
    assert data["builds"] == ["212"] and INSTALL_A not in out and INSTALL_B not in out


def test_dead_ends_and_repeat_taps_are_counted(home, capsys):
    events = [ev(0, "screen", "home.main"), ev(1, "dead_end", "trip.timeline", "screen", ms=800),
              ev(2, "screen", "trip.timeline"), ev(5, "dead_end", "settings.main", "sheet"),
              ev(6, "repeat_tap", "trip.addButton"), ev(9, "repeat_tap", "trip.addButton")]
    load(home, batch(events))
    data = json.loads(run(capsys, "sample", "--json")[1])
    assert {(r["id"], r["reason"], r["count"]) for r in data["dead_ends"]} == {("trip.timeline", "screen", 1), ("settings.main", "sheet", 1)}
    assert data["repeat_taps"] == [{"id": "trip.addButton", "count": 2}]
    assert data["dead_end_rate"] == 0.5


def test_since_filters_by_utc_day(home, capsys):
    load(home, batch([ev(0, "screen", "home.main"), ev(3 * DAY, "screen", "trip.timeline")]))
    day = (T0 + 2 * DAY)
    import datetime as dt
    since = dt.datetime.fromtimestamp(day, dt.timezone.utc).strftime("%Y-%m-%d")
    data = json.loads(run(capsys, "sample", "--since", since, "--json")[1])
    assert [r["id"] for r in data["top_screens"]] == ["trip.timeline"]
    assert run(capsys, "sample", "--since", "last tuesday")[0] == 2


def test_before_and_after_a_build_compare_a_decisions_two_windows(home, capsys):
    old = [ev(0, "task", "plan.day", "start", b="9"), ev(100, "task", "plan.day", "success", ms=100_000, b="9")]
    new = [ev(0, "task", "plan.day", "start", b="10"), ev(40, "task", "plan.day", "success", ms=40_000, b="10")]
    load(home, batch(old, cid=B1, build="9"), batch(new, cid=B2, build="10"))
    data = json.loads(run(capsys, "sample", "--before", "9", "--after", "10", "--json")[1])
    assert data["before"]["tasks"]["plan.day"]["median_seconds"] == 100.0       # "9" sorts before "10"
    assert data["after"]["tasks"]["plan.day"]["median_seconds"] == 40.0
    only_after = json.loads(run(capsys, "sample", "--after", "10", "--json")[1])
    assert only_after["builds"] == ["10"]
    text = run(capsys, "sample", "--before", "9", "--after", "10")[1]
    assert "(before)" in text and "(after)" in text


def test_a_variant_filter_keeps_only_events_recorded_under_it(home, capsys):
    events = [ev(0, "screen", "home.main", d={"nav": "bottom-bar"}), ev(1, "screen", "trip.timeline", d={"nav": "sidebar"}),
              ev(2, "screen", "settings.main")]
    load(home, batch(events))
    data = json.loads(run(capsys, "sample", "--variant", "nav=bottom-bar", "--json")[1])
    assert [r["id"] for r in data["top_screens"]] == ["home.main"]
    assert run(capsys, "sample", "--variant", "Nav=x")[0] == 2


def test_no_data_and_a_bad_slug_are_told_plainly(home, capsys):
    code, out, err = run(capsys, "sample")
    assert code == 1 and "no usage events" in err
    assert run(capsys, "Not A Slug")[0] == 2


def test_the_text_report_is_readable_and_prints_no_install_id(home, capsys):
    load(home, batch(SESSION))
    code, out, _ = run(capsys, "sample")
    assert code == 0 and "top screens:" in out and "plan.day: 60.0 s over 1" in out
    assert "declared screens never opened: legacy.screen, settings.main" in out
    assert INSTALL_A not in out


def test_usage_is_in_the_help_groups():
    from teyla import helpgroups
    assert any(name == "usage" for rows in helpgroups.GROUPS.values() for name, _ in rows)


# --- a product's own backend: `teyla review pull --vouched-folder DIR` ---------------------------------

def test_the_vouched_folder_files_a_usage_batch_and_leaves_the_inbox_alone(home, capsys):
    box = home / "download"
    d = folder(box, batch(SESSION))
    assert cli.main(["review", "pull", "--vouched-folder", str(box), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert (rep["usage_batches"], rep["usage_events"], rep["usage_imported"]) == (1, len(SESSION), [B1])
    assert rep["added"] == 0 and rep["imported"] == [] and rep["skipped"] == []
    assert [f.stem for f in stored(home)] == [B1]
    assert (d / "usage.json").is_file()                     # the source folder is the caller's to delete
    conn = review.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_vouched_folder_cleans_a_batch_like_the_channel_does(home):
    messy = batch([ev(0, "screen", "home.main", d={"keep": 3, "bad": {"x": 1}, "list": [1]}), {"k": "nonsense"}])
    messy["email"] = "someone@example.invalid"
    box = home / "download"
    folder(box, messy)
    conn = review.connect()
    try:
        rep = review.pull_vouched(conn, box)
    finally:
        conn.close()
    assert rep["usage_batches"] == 1
    text = stored(home)[0].read_text()
    assert "someone@example.invalid" not in text and '"bad"' not in text


def test_a_bad_usage_batch_is_skipped_and_the_others_still_import(home):
    box = home / "download"
    folder(box, batch(SESSION, product="other-product", cid=B2))
    folder(box, batch(SESSION, product="Bad Slug!", cid=B3))
    folder(box, batch(SESSION, cid=B1))
    conn = review.connect()
    try:
        rep = review.pull_vouched(conn, box)
    finally:
        conn.close()
    assert sorted(rep["usage_imported"]) == sorted([B1, B2]) and rep["usage_batches"] == 2
    assert len(rep["skipped"]) == 1 and B3 in rep["skipped"][0]
    assert [f.stem for f in stored(home)] == [B1] and [f.stem for f in stored(home, "other-product")] == [B2]


def test_a_duplicate_usage_batch_id_is_ignored(home):
    box = home / "download"
    folder(box, batch(SESSION))
    conn = review.connect()
    try:
        review.pull_vouched(conn, box)
        rep = review.pull_vouched(conn, box)
    finally:
        conn.close()
    assert rep["usage_imported"] == [B1] and rep["usage_events"] == 0 and rep["skipped"] == []
    assert len(stored(home)) == 1


def test_a_usage_batch_does_not_stop_a_capture_in_the_same_folder(home):
    cap = pathlib.Path(__file__).parent / "fixtures" / "review-capture"
    cid = "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64"
    box = home / "download"
    folder(box, batch(SESSION))
    shutil.copytree(cap, box / cid)
    (box / cid / "status.json").unlink()
    (box / cid / "capture.sig").unlink()
    conn = review.connect()
    try:
        rep = review.pull_vouched(conn, box)
        assert rep["imported"] == [cid] and rep["usage_imported"] == [B1] and rep["skipped"] == []
        assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_vouched_pull_deletes_an_expired_batch_even_with_nothing_new(home):
    box = home / "download"
    folder(box, batch(SESSION))
    conn = review.connect()
    try:
        review.pull_vouched(conn, box, now=T0)
        assert [f.stem for f in stored(home)] == [B1]
        rep = review.pull_vouched(conn, home / "empty", now=T0 + 201 * DAY)      # not even a folder: still pruned
    finally:
        conn.close()
    assert rep["usage_pruned"] == 1 and stored(home) == []


def test_an_expired_batch_in_the_vouched_folder_is_not_stored(home):
    box = home / "download"
    folder(box, batch(SESSION))
    conn = review.connect()
    try:
        rep = review.pull_vouched(conn, box, now=T0 + 201 * DAY)
        rep2 = review.pull_vouched(conn, box, now=T0 + 201 * DAY)      # and not again on the next pull
    finally:
        conn.close()
    assert stored(home) == []
    assert rep["usage_events"] == 0 and rep2["usage_events"] == 0 and rep["skipped"] == []
    assert rep["usage_imported"] == [B1]            # read and dealt with: the product may delete its copy
