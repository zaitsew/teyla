"""The ask gate: what `teyla asks` closes or hides on its own, and what it never does. Repeat runs of one
scheduled job, a job that is off, a status report shown as a question, a TestFlight tap the cached data
already answers, and the hard floor (`needs_owner`). Every source is a tmp dir or a hand-built `Ask`;
nothing reads this machine. Texts are generic."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import asks, cli, portfolio

pytestmark = pytest.mark.usefixtures("fake_code_root")

NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400
HOUR = 3600
HOME = "/Users/someone"
JOB = "nightly-publish"
TITLE = "Example: publish Android 1.3 (5) once the store approves"
WAIT = "Android 1.3 (5) is still in review; check the console again later"


def iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ask(id_, *, product="lens", title=TITLE, question=WAIT, kind="question", hours_ago=1.0, task="", session=None,
        options=(), harness="claude-desktop", context=""):
    return asks.Ask(id=id_, kind=kind, product=product, title=title, question=question, context=context,
                    options=list(options), when=NOW - hours_ago * HOUR, archived=False, link=f"claude://x/{id_}",
                    pr="", harness=harness, session=id_ if session is None else session, task=task)


def runs(n, *, task=JOB, kind="blocked", question=WAIT, title=TITLE, **kw):
    """n runs of one job, two hours apart; the newest is `run00`."""
    return [ask(f"run{i:02d}", kind=kind, task=task, question=question, title=title, hours_ago=1 + 2 * i, **kw)
            for i in range(n)]


def store():
    return {"done": {}, "snoozed": {}, "undone": {}}


def settle(items, *, st=None, tasks=None, stores=None, now=NOW):
    st = store() if st is None else st
    asks.settle(items, now, st=st, tasks={} if tasks is None else tasks, stores={} if stores is None else stores)
    return st


def open_ids(items):
    return sorted(a.id for a in items if a.status == "open")


# --- the world: sources, schedule records and the TestFlight cache, as `collect` would read them -------------

@pytest.fixture
def world(monkeypatch):
    class W:
        items: list = []                                    # a factory result is built anew for every collect
        tasks: dict | None = {}
    w = W()
    w.build = lambda: []
    monkeypatch.setattr(asks, "collect_claude", lambda *a, **k: w.build())
    monkeypatch.setattr(asks, "collect_codex", lambda *a, **k: [])
    monkeypatch.setattr(asks, "collect_gates", lambda: [])
    monkeypatch.setattr(asks, "collect_reminders", lambda *a, **k: [])
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(asks, "schedule_states", lambda home=None: w.tasks)
    return w


def collect():
    return asks.collect(asks.DEFAULT_DAYS, NOW)


# --- 1. repeat runs collapse by identity -------------------------------------------------------------------

def test_21_runs_of_one_enabled_job_leave_one_card_with_20_similar():
    items = runs(21)
    settle(items, tasks={JOB: "on"})
    assert open_ids(items) == ["run00"]
    kept = items[0]
    assert len(kept.dupes) == 20 and all(a.status == "duplicate" for a in items[1:])
    assert all(a.note == "auto: repeat run of run00" for a in items[1:])


def test_repeat_runs_collapse_even_when_the_question_text_changes_a_little():
    items = [ask(f"run{i:02d}", kind="blocked", task=JOB, hours_ago=1 + 2 * i,
                 question=f"{WAIT}; checked at {10 + i}:17") for i in range(4)]
    settle(items, tasks={JOB: "on"})
    assert open_ids(items) == ["run00"]


def test_runs_of_two_jobs_with_one_title_stay_apart():
    items = runs(3, task="job-a") + [ask(f"other{i}", kind="blocked", task="job-b", hours_ago=1 + i) for i in range(3)]
    settle(items, tasks={"job-a": "on", "job-b": "on"})
    assert open_ids(items) == ["other0", "run00"]


def test_same_words_with_a_different_target_version_do_not_collapse():
    v13 = [ask(f"a{i}", kind="blocked", task=JOB, hours_ago=1 + i, question=WAIT) for i in range(3)]
    v14 = [ask(f"b{i}", kind="blocked", task=JOB, hours_ago=10 + i, question=WAIT.replace("1.3 (5)", "1.4 (2)"),
               title=TITLE) for i in range(3)]
    settle(v13 + v14, tasks={JOB: "on"})
    assert open_ids(v13 + v14) == ["a0", "b0"]
    assert [a.id for a in v13 if a.status == "duplicate"] == ["a1", "a2"]


@pytest.mark.parametrize("old,new", [("build 12", "build 13"), ("v2.1.0", "v2.2.0"), ("Android 1.3 (5)", "Android 1.3 (6)")])
def test_a_different_build_or_version_token_keeps_two_asks(old, new):
    items = [ask("aaa", kind="blocked", task=JOB, hours_ago=3, title="Job", question=f"Waiting on {old} review"),
             ask("bbb", kind="blocked", task=JOB, hours_ago=1, title="Job", question=f"Waiting on {new} review")]
    settle(items, tasks={JOB: "on"})
    assert open_ids(items) == ["aaa", "bbb"]


def test_blocked_asks_never_collapse_by_similarity():
    a = ask("aaa", kind="blocked", title="Session one", question="the upload failed because the build number repeats "
            "an earlier upload of the same beta", hours_ago=3)
    b = ask("bbb", kind="blocked", title="Session two", question="the upload failed because the build number repeats "
            "an earlier upload of the same beta", hours_ago=1)
    settle([a, b])
    assert open_ids([a, b]) == ["aaa", "bbb"]


def test_without_a_task_three_sessions_with_one_title_product_and_harness_collapse():
    items = [ask(f"s{i}", kind="blocked", title="Nightly check", question=f"check {i}", hours_ago=1 + i) for i in range(3)]
    settle(items)
    assert open_ids(items) == ["s0"] and items[0].dupes == ["s1", "s2"]


def test_without_a_task_two_sessions_or_two_harnesses_do_not_collapse():
    two = [ask(f"s{i}", kind="blocked", title="Nightly check", question=f"check {i}", hours_ago=1 + i) for i in range(2)]
    mixed = [ask("m0", title="Other", harness="codex", question="zero"), ask("m1", title="Other", question="one"),
             ask("m2", title="Other", question="two")]
    settle(two + mixed)
    assert open_ids(two + mixed) == ["m0", "m1", "m2", "s0", "s1"]


def test_without_a_task_three_asks_of_one_session_are_not_a_job():
    items = [ask(f"s{i}", kind="blocked", title="Nightly check", question=f"check {i}", hours_ago=1 + i, session="one")
             for i in range(3)]
    settle(items)
    assert open_ids(items) == ["s0", "s1", "s2"]


def test_the_asks_of_different_products_never_collapse_even_with_one_task():
    items = [ask("aaa", product="lens", kind="blocked", task=JOB), ask("bbb", product="atlas", kind="blocked", task=JOB)]
    settle(items, tasks={JOB: "on"})
    assert open_ids(items) == ["aaa", "bbb"]


def test_a_hand_closed_older_run_is_left_alone():
    items = runs(3)
    st = store()
    st["done"]["run02"] = {"ts": iso(NOW), "note": "by hand"}
    asks.apply_state(items, st, NOW)
    settle(items, st=st, tasks={JOB: "on"})
    assert st["done"]["run02"]["note"] == "by hand" and items[1].status == "duplicate"


# --- 2. a job that is off closes its cards --------------------------------------------------------------

def test_21_runs_of_a_disabled_job_collapse_and_close_into_nothing_open():
    items = runs(21)
    st = settle(items, tasks={JOB: "off"})
    assert open_ids(items) == []
    assert items[0].status == "done" and items[0].note == f"auto: scheduled task off {JOB}"
    assert st["done"]["run00"]["note"] == f"auto: scheduled task off {JOB}"
    assert sum(1 for a in items if a.status == "duplicate") == 20
    assert asks.filtered_by_reason(items) == dict(resolved=0, duplicates=0, repeat_runs=20, scheduled_off=1,
                                                 testflight_current=0, reports=0)


def test_a_deleted_job_closes_its_cards_when_the_store_is_readable():
    items = runs(2)
    settle(items, tasks={"another-job": "on"})
    assert open_ids(items) == [] and items[0].note == f"auto: scheduled task off {JOB}"


def test_an_unreadable_schedule_store_closes_nothing():
    items = runs(2)
    settle(items, tasks={})                      # no record at all: the store is missing, not every job deleted
    assert open_ids(items) == ["run00"]


def test_a_one_shot_that_switched_itself_off_keeps_its_ask():
    items = runs(1)
    settle(items, tasks={JOB: "once"})
    assert open_ids(items) == ["run00"]


def test_an_ask_without_a_task_is_not_closed_by_a_job_that_is_off():
    items = [ask("aaa", kind="blocked")]
    settle(items, tasks={JOB: "off"})
    assert open_ids(items) == ["aaa"]


def test_the_schedule_store_is_read_from_local_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    rec = home / "Library" / "Application Support" / "Claude" / "claude-code-sessions" / "acct" / "work"
    rec.mkdir(parents=True)
    (rec / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [
        {"id": "daily-job", "enabled": True, "cronExpression": "30 7 * * *"},
        {"id": "paused-job", "enabled": False, "cronExpression": "17 8-22/2 * * *"},
        {"id": "single-shot", "enabled": False, "fireAt": 1790000000000}]}))
    assert asks.schedule_states(home) == {"daily-job": "on", "paused-job": "off", "single-shot": "once"}


def test_no_schedule_records_read_as_none(tmp_path, monkeypatch):
    assert asks.schedule_states(tmp_path / "empty-home") is None


def test_a_desktop_session_names_its_task_and_the_scheduled_store_decides(tmp_path, monkeypatch):
    """End to end from files: 21 session records with `scheduledTaskId`, one disabled job in the app's record."""
    root = tmp_path / "sessions"
    home = tmp_path / "home"
    (root / "acct" / "work").mkdir(parents=True)
    rec = home / "Library" / "Application Support" / "Claude" / "claude-code-sessions" / "acct" / "work"
    rec.mkdir(parents=True)
    (rec / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [
        {"id": JOB, "enabled": False, "cronExpression": "17 8-22/2 * * *"}]}))
    monkeypatch.setattr(asks, "_schedule_home", lambda: home)
    for i in range(21):
        sid = f"local_run{i:02d}"
        (root / "acct" / "work" / f"{sid}.json").write_text(json.dumps({
            "sessionId": sid, "cliSessionId": f"cli{i:02d}", "cwd": f"{HOME}/repos/lens", "isArchived": True,
            "title": TITLE, "scheduledTaskId": JOB,
            "createdAt": int((NOW - (2 * i + 2) * HOUR) * 1000), "lastActivityAt": int((NOW - (2 * i + 1) * HOUR) * 1000),
            "postTurnSummary": {"status_category": "blocked", "needs_action": WAIT, "status_detail": "", "summarizes_uuid": ""}}))
    items = asks.collect(asks.DEFAULT_DAYS, NOW, desktop=str(root), projects=str(tmp_path / "no-projects"),
                         codex_root=str(tmp_path / "no-codex"), codex_archive=str(tmp_path / "no-archive"),
                         reminders=tmp_path / "reminders.toml", st=store())
    assert len(items) == 21 and {a.task for a in items} == {JOB} and open_ids(items) == []
    assert asks.filtered_by_reason(items)["repeat_runs"] == 20 and asks.filtered_by_reason(items)["scheduled_off"] == 1


def test_a_stale_slim_cache_without_the_task_id_is_not_trusted(tmp_path):
    root = tmp_path / "sessions"
    p = root / "acct" / "work" / "local_x.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"sessionId": "local_x", "cliSessionId": "cx", "scheduledTaskId": JOB}))
    st = p.stat()
    asks._slim_cache_path().write_text(json.dumps({"version": 1, "files": {str(p): [st.st_mtime_ns, st.st_size, {"sessionId": "local_x", "cliSessionId": "cx"}]}}))
    assert asks._desktop_sessions(str(root))[0]["scheduledTaskId"] == JOB


# --- 3. reports are not questions ------------------------------------------------------------------------

REPORTS = [
    "Not verified: the iPad layout.",
    "**Result:** the upload finished.",
    "## Status\nThe nightly job ran and nothing else changed.",
    "Done — lens\nResult: the build is uploaded.",
    "Checked three things:\n- the build number is new\n- the beta group exists\n- the notes are filled in",
]
STAYS_AN_ASK = [
    "Sign in to Example Console",
    "Run the migration on staging",
    "Please review the pull request and merge it.",
    "Not verified: the iPad layout. Reply with the device you want me to use.",
    "Pick one of the layouts:\n- narrow\n- wide\n- compact",
    "**Decision needed:** approve the release?",
    "Which layout do you want?\n- narrow\n- wide\n- compact",
    "Needs you: the store login.",
]


@pytest.mark.parametrize("text", REPORTS)
def test_a_status_report_is_kind_report_and_done(text):
    a = ask("aaa", question=text)
    st = settle([a])
    assert (a.kind, a.status, a.note) == ("report", "done", "auto: report") and st["done"]["aaa"]["note"] == "auto: report"


@pytest.mark.parametrize("text", STAYS_AN_ASK)
def test_an_imperative_or_a_request_stays_an_ask(text):
    a = ask("aaa", question=text)
    settle([a])
    assert (a.kind, a.status) == ("question", "open")


def test_an_ask_with_options_keeps_its_old_behaviour():
    a = ask("aaa", question="Not verified: the iPad layout.", options=["Ship", "Wait"])
    settle([a])
    assert (a.kind, a.status) == ("question", "open")


def test_a_report_is_out_of_the_list_and_the_count_but_shown_under_all(world, capsys):
    world.build = lambda: [ask("rep00001", question="Not verified: the iPad layout.", hours_ago=2),
                           ask("ask00001", question="Sign in to Example Console", hours_ago=1)]
    assert cli.main(["asks"]) == 0
    out = capsys.readouterr().out
    assert "1 waiting on you" in out and "ask00001" in out and "rep00001" not in out
    assert out.rstrip().splitlines()[-1] == "filtered: 0 resolved (PR merged/closed), 0 duplicates, 1 reports — teyla asks --all"
    assert asks.banner_line(collect()) == "1 question waits for you — teyla asks"
    assert cli.main(["asks", "--all"]) == 0
    out = capsys.readouterr().out
    assert "rep00001" in out and "[done, report]" in out and "auto: report" in out and "filtered:" not in out


# --- 4. live checks with a reason -------------------------------------------------------------------------

TAP = "Tap View in TestFlight in Apple's e-mail once so build 12 is installable on your phone."


def tf(state_="current", *, hours_ago=0.5, channel="testflight", plat="ios"):
    return {plat: {"platform": plat, "channel": channel, "state": state_, "as_of": iso(NOW - hours_ago * HOUR)}}


def tap_ask(**kw):
    return ask("tap00001", question=TAP, hours_ago=kw.pop("hours_ago", 5.0), **kw)


def test_a_testflight_tap_closes_when_the_cache_says_the_tester_can_install():
    a = tap_ask()
    st = settle([a], stores={"lens": tf()})
    assert (a.status, a.note) == ("done", "auto: testflight current lens") and st["done"]["tap00001"]["note"] == a.note


@pytest.mark.parametrize("stores", [
    {},                                                         # no cache
    {"atlas": tf()},                                            # another product
    {"lens": tf("blocked")},                                    # still waiting on the tap
    {"lens": tf("behind")},
    {"lens": tf("unknown")},
    {"lens": tf(hours_ago=9.0)},                                # read before the ask was written
    {"lens": tf(hours_ago=60.0)},                               # read too long ago to trust... and before the ask
    {"lens": {"ios": {"channel": "testflight", "state": "current"}}},          # no timestamp
    {"lens": {**tf(), **tf("blocked", plat="macos")}},          # one platform is still blocked
    {"lens": tf(channel="play")},                               # not a TestFlight row
    {"lens": {}},
])
def test_a_testflight_tap_stays_open_when_the_data_is_missing_or_unclear(stores):
    a = tap_ask()
    settle([a], stores=stores)
    assert a.status == "open"


def test_a_stale_cache_does_not_close_a_new_ask():
    a = tap_ask(hours_ago=1.0)
    settle([a], stores={"lens": tf(hours_ago=60.0)})
    assert a.status == "open"


@pytest.mark.parametrize("text", [
    "Tap View in TestFlight in Apple's e-mail. Should I submit the build for beta review?",
    "Submit build 12 for beta review, then tap View in TestFlight.",
    "Open the console and pick the release notes.",
])
def test_only_a_request_to_tap_view_in_testflight_is_closed_by_it(text):
    a = ask("aaa", question=text, options=())
    settle([a], stores={"lens": tf()})
    assert a.status == "open"


def test_the_portfolio_cache_is_read_from_local_files_only(monkeypatch):
    cache = portfolio.load_cache()
    cache["stores"] = {"lens": tf()}
    portfolio.save_cache(cache)
    a = tap_ask()
    st = store()
    monkeypatch.setattr(portfolio.testflight, "run_tool", lambda *a, **k: pytest.fail("reached App Store Connect"))
    asks.settle([a], NOW, st=st, tasks={})
    assert a.status == "done" and a.note == "auto: testflight current lens"


# --- 5. the hard floor ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,owner", [
    ("Approve the $9.99 price for the monthly plan", True),
    ("Set the price to 4,99 € before launch", True),
    ("The subscription costs 10 USD per month", True),
    ("Paste the API key for the build service", True),
    ("The signing password expired", True),
    ("Ask Maria Lopez to approve the invite", True),
    ("Ask Maria to approve the invite", True),
    ("Maria's review is still pending", True),
    ("Send the draft to @dev-friend for a look", True),
    ("Tap View in TestFlight in Apple's e-mail once", False),
    ("Android 1.3 (5) is still in review; check the console again later", False),
    ("Check the App Store Connect page and the Google Play Console", False),
    ("Not verified: the iPad layout on iOS 17", False),
])
def test_needs_owner_names_a_price_a_secret_or_a_person(text, owner):
    assert asks.needs_owner(ask("aaa", question=text)) is owner


def test_needs_owner_reads_the_context_and_a_known_product_name_is_not_a_person():
    assert asks.needs_owner(ask("aaa", question="Wait", context="Billing failed on the card"))
    pair = ask("aaa", question="Wine Cave build 12 is processing")
    assert asks.needs_owner(pair) and not asks.needs_owner(pair, frozenset({"wine", "cave"}))


@pytest.mark.parametrize("text", [
    "Android 1.3 (5): the price is still not set in the console",
    "Android 1.3 (5): the signing key expired",
    "Android 1.3 (5): ask Maria Lopez for the access",
])
def test_an_ask_that_needs_the_owner_is_not_closed_by_a_job_that_is_off(text):
    items = [ask("aaa", kind="blocked", task=JOB, question=text)]
    settle(items, tasks={JOB: "off"})
    assert open_ids(items) == ["aaa"]


def test_an_ask_that_needs_the_owner_is_not_closed_by_the_testflight_cache():
    a = tap_ask(context="the invite goes to a tester, Maria Lopez")
    settle([a], stores={"lens": tf()})
    assert a.status == "open"
    b = ask("bbb", question="Tap View in TestFlight; then paste the API key", hours_ago=5)
    settle([b], stores={"lens": tf()})
    assert b.status == "open"


def test_asks_that_need_the_owner_collapse_only_when_their_text_is_identical():
    texts = ["Android 1.3 (5): the price is not set", "Android 1.3 (5): the price is not set", "Android 1.3 (5): the price is set to 5"]
    items = [ask(f"r{i}", kind="blocked", task=JOB, hours_ago=1 + i, question=t) for i, t in enumerate(texts)]
    settle(items, tasks={JOB: "on"})
    assert open_ids(items) == ["r0", "r2"] and items[0].dupes == ["r1"]


def test_similar_questions_that_need_the_owner_do_not_collapse_by_similarity():
    base = "which database migration should run first before the nightly backup job starts tonight and who is the owner"
    a = ask("aaa", title="One", question=base + ", price included", hours_ago=3, session="s1")
    b = ask("bbb", title="Two", question=base + ", price excluded", hours_ago=1, session="s2")
    settle([a, b])
    assert open_ids([a, b]) == ["aaa", "bbb"]
    c = ask("ccc", title="One", question=base + ", plan a", hours_ago=3, session="s3")
    d = ask("ddd", title="Two", question=base + ", plan b", hours_ago=1, session="s4")
    settle([c, d])
    assert open_ids([c, d]) == ["ddd"]


def test_age_alone_closes_nothing():
    items = [ask("aaa", question="Which font should the app use?", hours_ago=24 * 90),
             ask("bbb", kind="blocked", task=JOB, hours_ago=24 * 90)]
    settle(items, tasks={JOB: "on"}, stores={"lens": tf()})
    assert open_ids(items) == ["aaa", "bbb"]


# --- undo ------------------------------------------------------------------------------------------------

def test_undo_restores_a_job_that_was_off_and_it_stays_restored(world):
    world.tasks = {JOB: "off"}
    world.build = lambda: runs(21)
    assert open_ids(collect()) == [] and open_ids(collect()) == []        # stable on a second run
    lines, code = asks.undo(["run00"], NOW)
    assert code == 0 and lines[0].startswith("reopened: run00")
    for _ in range(2):
        items = collect()
        assert open_ids(items) == ["run00"]
        kept = next(a for a in items if a.id == "run00")
        assert len(kept.dupes) == 20


def test_undo_of_a_hidden_repeat_run_shows_it_as_its_own_ask(world):
    world.tasks = {JOB: "on"}
    world.build = lambda: runs(3)
    assert open_ids(collect()) == ["run00"]
    assert asks.undo(["run01"], NOW)[1] == 0
    assert open_ids(collect()) == ["run00", "run01"] and open_ids(collect()) == ["run00", "run01"]


def test_undo_restores_a_report_and_it_stays_an_ask(world):
    world.build = lambda: [ask("aaa", question="Not verified: the iPad layout.")]
    assert open_ids(collect()) == []
    assert asks.undo(["aaa"], NOW)[1] == 0
    for _ in range(2):
        items = collect()
        assert open_ids(items) == ["aaa"] and items[0].kind == "question"


def test_undo_restores_a_testflight_tap_and_it_stays_open(world):
    cache = portfolio.load_cache()
    cache["stores"] = {"lens": tf()}
    portfolio.save_cache(cache)
    world.build = lambda: [tap_ask()]
    assert open_ids(collect()) == []
    assert asks.undo(["tap00001"], NOW)[1] == 0
    for _ in range(2):
        assert open_ids(collect()) == ["tap00001"]


# --- output ----------------------------------------------------------------------------------------------

def test_json_adds_filtered_by_reason_and_keeps_every_old_key(world, capsys):
    world.tasks = {JOB: "off"}
    world.build = lambda: runs(5) + [ask("rep00001", question="Not verified: the iPad layout.", hours_ago=2),
                                     ask("ask00001", question="Sign in to Example Console", hours_ago=1)]
    assert cli.main(["asks", "--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert {"waiting", "archived", "generated", "items", "groups", "muted", "muted_products", "resolved",
            "duplicates", "filtered"} <= set(j)
    assert j["filtered"] == dict(resolved=0, duplicates=0, repeat_runs=4, scheduled_off=1, testflight_current=0, reports=1)
    assert j["duplicates"] == 4 and j["waiting"] == 1 and "task" not in j["items"][0]


def test_the_filtered_line_names_each_reason_that_happened(world, capsys):
    world.tasks = {JOB: "off"}
    world.build = lambda: runs(5) + [ask("ask00001", question="Sign in to Example Console", hours_ago=1)]
    assert cli.main(["asks"]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == (
        "filtered: 0 resolved (PR merged/closed), 4 duplicates (4 repeat runs), 1 scheduled task off — teyla asks --all")


def test_the_filtered_line_is_unchanged_without_the_new_reasons():
    assert asks.filtered_line(1, 1) == "filtered: 1 resolved (PR merged/closed), 1 duplicates — teyla asks --all"
    assert asks.filtered_line(0, 0, dict.fromkeys(asks.REASONS, 0)) == ""


def test_the_task_id_is_internal_and_the_row_keeps_its_keys():
    d = ask("aaa", task=JOB).to_dict(NOW, attribution=True)
    assert "task" not in d and {"id", "kind", "product", "title", "question", "status", "ts", "age_s", "attributed_by"} <= set(d)
