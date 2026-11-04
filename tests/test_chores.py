"""Chores: the classifier, and the one place `teyla asks` uses it, folding repeats of a manual chore.
Texts are generic; no source reads this machine."""
from __future__ import annotations

import datetime as dt

import pytest

from teyla import asks, chores

pytestmark = pytest.mark.usefixtures("fake_code_root")

NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc).timestamp()
HOUR = 3600


def ask(id_, question, *, product="lens", title=None, kind="blocked", hours_ago=1.0, options=(), session=None):
    return asks.Ask(id=id_, kind=kind, product=product, title=title or f"Example {id_}", question=question, context="", options=list(options),
                    when=NOW - hours_ago * HOUR, archived=False, link=f"claude://x/{id_}", pr="", harness="claude-desktop",
                    session=id_ if session is None else session)


def settle(items, st=None):
    asks.settle(items, NOW, st=st, tasks={}, stores={})


def open_ids(items):
    return sorted(a.id for a in items if a.status == "open")


@pytest.mark.parametrize("text,key", [
    ("Sign Chrome in so the agent can open the dashboard", "chrome_signin"),
    ("Please log in to Google in the Chrome profile", "chrome_signin"),
    ("Open Play Console and accept the new policy", "play_console"),
    ("Open App Store Connect and accept the agreement", "app_store_connect"),
    ("Sign in at developer.apple.com and renew the certificate", "developer_apple"),
    ("Add a CNAME record for the docs host", "dns"),
    ("Run gcloud auth login again", "gcloud_auth"),
    ("Tap View in TestFlight in the invitation e-mail", "testflight_tap"),
    ("Paste the API key into the secret store", "secret"),
    ("Disable the stale scheduled task for the nightly job", "scheduled_task_cleanup"),
    ("Open the build on your iPhone and check the camera", "device_check"),
])
def test_the_classifier_names_each_chore(text, key):
    assert chores.key_of(text) == key


def test_priority_puts_the_secret_before_the_portal_and_chrome_before_the_console():
    assert chores.key_of("Paste the API key from App Store Connect") == "secret"
    assert chores.key_of("Sign Chrome in, then open Play Console") == "chrome_signin"


def test_an_unrelated_text_is_no_chore():
    assert chores.key_of("The migration finished and the tests pass") is None


def test_a_question_that_offers_a_choice_or_a_long_report_is_not_a_request():
    assert not chores.is_request("Which Play Console track should I use for this release?")
    assert not chores.is_request("Open Play Console. " + "x" * 400)
    assert not chores.is_request("Open Play Console", options=2)
    assert chores.classify("Example", "Which Play Console track should I use?") is None


def test_every_chore_has_a_path_and_a_person():
    assert {c.key for c in chores.PATHS} == set(chores._PATTERNS)
    assert all(c.path and c.who and c.label for c in chores.PATHS)
    assert not any(chores.BY_KEY[k].collapse for k in ("secret", "testflight_tap", "device_check", "dns"))
    assert chores.key_of("Open Play Console on your phone and check the release") == "device_check"


WORDINGS = ("Sign Chrome in", "Please sign in to Chrome", "Chrome is signed out; sign in again",
            "Log in to Google in Chrome", "Sign into Chrome so I can continue")


def test_seven_wordings_of_one_chore_collapse_into_the_newest():
    items = [ask(f"c{i}", WORDINGS[i % len(WORDINGS)], hours_ago=1 + i) for i in range(7)]
    settle(items)
    assert open_ids(items) == ["c0"]
    hidden = [a for a in items if a.status == "duplicate"]
    assert len(hidden) == 6 and all(a.note == "auto: same chore c0" for a in hidden)
    assert items[0].dupes and len(items[0].dupes) == 6
    assert asks.filtered_by_reason(items)["same_chore"] == 6
    assert "6 same-chore repeats" in asks.filtered_line(0, 0, asks.filtered_by_reason(items))


def test_chores_of_two_products_or_two_keys_stay_apart():
    items = [ask("a1", "Sign Chrome in", product="lens"), ask("a2", "Sign Chrome in", product="atlas", hours_ago=2),
             ask("b1", "Open Play Console and accept the policy", product="lens", hours_ago=3)]
    settle(items)
    assert open_ids(items) == ["a1", "a2", "b1"]


def test_chores_aimed_at_different_versions_stay_apart():
    items = [ask("v1", "Open Play Console and publish 1.3 (5)"), ask("v2", "Open Play Console and publish 1.4 (2)", hours_ago=2)]
    settle(items)
    assert open_ids(items) == ["v1", "v2"]


@pytest.mark.parametrize("text", [
    "Paste the API key for the store account",                      # a secret
    "Tap View in TestFlight in the invitation e-mail",              # a TestFlight tap
    "Open the build on your iPhone and check the camera",           # a device
    "Sign Chrome in with the account of Alex Morgan",                # another person
    "Open Play Console and pay the $25 fee",                         # a price
])
def test_a_secret_a_device_a_person_or_a_price_never_collapses(text):
    items = [ask("n1", text), ask("n2", text.replace("Open", "Please open"), hours_ago=2)]
    settle(items)
    assert open_ids(items) == ["n1", "n2"]


def test_an_ask_with_options_or_a_choice_never_collapses():
    items = [ask("o1", "Sign Chrome in", options=["done", "later"]), ask("o2", "Sign Chrome in", hours_ago=2),
             ask("o3", "Which Chrome profile should I sign in?", hours_ago=3)]
    settle(items)
    assert open_ids(items) == ["o1", "o2", "o3"]


def test_a_done_chore_closes_its_older_repeats_and_undo_reverses_it():
    st = asks.load_state()
    items = [ask("d1", "Sign Chrome in", hours_ago=1), ask("d2", "Sign into Chrome", hours_ago=2)]
    st["done"]["d1"] = {"ts": "2026-11-01T11:00:00Z", "note": "signed in"}
    asks.apply_state(items, st, NOW)
    settle(items, st=st)
    assert items[1].status == "done" and items[1].note == "auto: same chore d1"
    st["done"].pop("d1")                       # `asks undo d1`: the kept ask reopens, its closed repeats go back under it
    for k in [k for k, v in st["done"].items() if v.get("note") == asks.AUTO_CHORE + "d1"]:
        del st["done"][k]
    st["undone"]["d1"] = {"ts": "2026-11-01T12:00:00Z"}
    again = [ask("d1", "Sign Chrome in", hours_ago=1), ask("d2", "Sign into Chrome", hours_ago=2)]
    asks.apply_state(again, st, NOW)
    settle(again, st=st)
    assert [a.status for a in again] == ["open", "duplicate"]      # reopened, and the repeat is hidden under it again
