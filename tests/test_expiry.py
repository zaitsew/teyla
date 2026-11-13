"""`teyla asks expire` (expiry.py): which old questions take a default, which are dropped, which are kept.
Asks are built by hand and `asks.collect` is replaced; the done store and the triage cache are real files in the
tmp TEYLA_HOME that conftest gives every test. The dry run must write nothing."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import asks, cli, expiry, triage

NOW = dt.datetime(2026, 11, 13, 12, 0, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400
NEUTRAL = "Is a retry limit of three enough for the sync job?"


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(asks, "is_muted", lambda a, reg: a.product == "parked")
    box = {"asks": []}
    monkeypatch.setattr(asks, "collect", lambda *a, **k: list(box["asks"]))
    return box


def ask(id_, days=20.0, question=NEUTRAL, *, title=None, context="", options=(), kind="question", product="app-a",
        harness="claude-desktop", status="open"):
    return asks.Ask(id=id_, kind=kind, product=product, title=title or f"Title of {id_}", question=question,
                    context=context, options=list(options), when=NOW - days * DAY, archived=False,
                    link=f"claude://x/{id_}", pr="", harness=harness, status=status, session=id_)


def run(capsys, *argv):
    code = cli.main(["asks", "expire", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def by_id(machine, capsys, *argv):
    code, out, _ = run(capsys, "--json", *argv)
    assert code == 0
    return {i["id"]: i for i in json.loads(out)["items"]}


def cache_default(a, default):
    row = a.to_dict(NOW)
    triage.save_cache({"version": 1, "items": {a.id: {"h": triage.text_hash(row), "at": asks._iso(NOW),
                                                       "bucket": "agent", "action": "", "default": default,
                                                       "why": "Routine."}}})


def test_triage_default_wins_over_everything(machine, capsys):
    a = ask("aaaa0001", options=["Keep it (Recommended)", "Other"], context="Default: keep it as it is.")
    cache_default(a, "Use three retries.")
    machine["asks"] = [a]
    i = by_id(machine, capsys)["aaaa0001"]
    assert (i["outcome"], i["default"], i["default_source"]) == ("default", "Use three retries.", "triage")


def test_triage_rule_permission_default(machine, capsys):
    machine["asks"] = [ask("aaaa0001", question="Want me to add the missing unit test for the export?")]
    i = by_id(machine, capsys)["aaaa0001"]
    assert (i["default"], i["default_source"]) == ("Yes, go ahead.", "triage")


def test_recommended_option_marker_is_stripped(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Tabs", "Spaces (recommended)", "Mixed"])]
    i = by_id(machine, capsys)["aaaa0001"]
    assert (i["outcome"], i["default"], i["default_source"]) == ("default", "Spaces", "recommended")


@pytest.mark.parametrize("phrase", ["Default: use spaces.", "Spaces are used by default.",
                                    "If you say nothing, spaces win.", "Unless you say otherwise, spaces win."])
def test_stated_default_sentence(machine, capsys, phrase):
    machine["asks"] = [ask("aaaa0001", context=f"Some background. {phrase} More text.")]
    i = by_id(machine, capsys)["aaaa0001"]
    assert i["default_source"] == "stated"
    assert i["default"] == phrase


def test_stated_default_is_clipped(machine, capsys):
    machine["asks"] = [ask("aaaa0001", context="Default: " + "word " * 80)]
    i = by_id(machine, capsys)["aaaa0001"]
    assert len(i["default"]) <= expiry.CLIP_DEFAULT


def test_design_card_takes_first_option(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Option A", "Option B"], harness=asks.DESIGN_HARNESS)]
    i = by_id(machine, capsys)["aaaa0001"]
    assert (i["default"], i["default_source"]) == ("Option A", "design")


def test_options_alone_are_no_default_outside_design(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Option A", "Option B"])]
    i = by_id(machine, capsys)["aaaa0001"]
    assert (i["outcome"], i["default"], i["default_source"]) == ("drop", "", "none")


def test_rule_order_recommended_beats_stated_and_design(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["A", "B (Recommended)"], context="Default: A.",
                           harness=asks.DESIGN_HARNESS)]
    assert by_id(machine, capsys)["aaaa0001"]["default_source"] == "recommended"
    machine["asks"] = [ask("aaaa0001", options=["A", "B"], context="Default: A.", harness=asks.DESIGN_HARNESS)]
    assert by_id(machine, capsys)["aaaa0001"]["default_source"] == "stated"


def test_keep_for_needs_owner_and_critical(machine, capsys):
    machine["asks"] = [
        ask("aaaa0001", question="The plan costs $9.99 per month. Keep it?", options=["Yes (Recommended)", "No"]),
        ask("aaaa0002", question="Paste the API key into the settings file."),
        ask("aaaa0003", kind="blocked", options=["Go (Recommended)"]),
        ask("aaaa0004", question="The build failed on the nightly run. Retry?", options=["Retry (Recommended)"]),
    ]
    items = by_id(machine, capsys)
    assert {k: v["outcome"] for k, v in items.items()} == {k: "keep" for k in items}
    assert items["aaaa0001"]["reason"] == "needs the owner (money, key or person)"
    assert items["aaaa0003"]["reason"] == "critical"
    assert all(v["default"] == "" for v in items.values())


def test_reminders_and_non_open_are_excluded(machine, capsys):
    machine["asks"] = [ask("aaaa0001", kind="reminder"), ask("aaaa0002", status="done"), ask("aaaa0003")]
    assert list(by_id(machine, capsys)) == ["aaaa0003"]


def test_product_filter(machine, capsys):
    machine["asks"] = [ask("aaaa0001", product="app-a"), ask("aaaa0002", product="app-b")]
    assert list(by_id(machine, capsys, "--product", "app-b")) == ["aaaa0002"]


def test_fourteen_day_boundary(machine, capsys):
    machine["asks"] = [ask("aaaa0001", days=14.0), ask("aaaa0002", days=14.01), ask("aaaa0003", days=13.9)]
    assert list(by_id(machine, capsys)) == ["aaaa0002"]


def test_older_than_30(machine, capsys):
    machine["asks"] = [ask("aaaa0001", days=20), ask("aaaa0002", days=31)]
    assert list(by_id(machine, capsys, "--older-than", "30")) == ["aaaa0002"]
    code, out, _ = run(capsys, "--older-than", "30")
    assert out.startswith("1 question is older than 30 days. Dry run: nothing changed.")


def test_muted_flagged_and_oldest_first(machine, capsys):
    machine["asks"] = [ask("aaaa0001", days=20), ask("aaaa0002", days=40, product="parked")]
    code, out, _ = run(capsys, "--json")
    items = json.loads(out)["items"]
    assert [i["id"] for i in items] == ["aaaa0002", "aaaa0001"]
    assert [i["muted"] for i in items] == [True, False]


def test_text_output(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Go (Recommended)"]), ask("aaaa0002"),
                       ask("aaaa0003", question="Paste the API key.")]
    code, out, _ = run(capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "3 questions are older than 14 days. Dry run: nothing changed."
    assert "Would take its default (1)" in out and "Would be dropped" in out and "Kept (never expired)" in out
    assert "default (recommended): Go" in out
    assert "teyla asks expire --apply" in out and "teyla asks undo <id>" in out


def test_json_shape(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Go (Recommended)"]), ask("aaaa0002"),
                       ask("aaaa0003", question="Paste the API key.")]
    code, out, _ = run(capsys, "--json")
    d = json.loads(out)
    assert d["version"] == 1 and d["older_than_days"] == 14 and d["dry_run"] is True
    assert d["counts"] == {"default": 1, "drop": 1, "keep": 1}
    assert set(d["items"][0]) == {"id", "product", "title", "age_days", "kind", "muted", "outcome", "default",
                                  "default_source", "reason"}
    assert d["items"][0]["age_days"] == 20


def test_dry_run_writes_nothing(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Go (Recommended)"]), ask("aaaa0002")]
    path = asks.state_path()
    run(capsys)
    run(capsys, "--json")
    assert not path.exists()
    asks.save_state(asks.load_state(), now=NOW)
    before = path.read_text()
    run(capsys)
    assert path.read_text() == before


def test_apply_writes_done_notes_and_undo_reopens(machine, capsys):
    machine["asks"] = [ask("aaaa0001", options=["Go (Recommended)"]), ask("aaaa0002"),
                       ask("aaaa0003", question="Paste the API key.")]
    code, out, _ = run(capsys, "--apply")
    assert code == 0
    done = asks.load_state()["done"]
    assert set(done) == {"aaaa0001", "aaaa0002"}
    assert done["aaaa0001"]["note"] == "expired: default Go (recommended)"
    assert done["aaaa0002"]["note"] == "expired: dropped"
    assert "closed 2" in out and "teyla asks undo aaaa0001 aaaa0002" in out
    assert "aaaa0003" not in out.split("closed 2")[0]
    assert cli.main(["asks", "undo", "aaaa0001", "aaaa0002"]) == 0
    capsys.readouterr()
    assert asks.load_state()["done"] == {}


def test_apply_note_prefix(machine, capsys):
    machine["asks"] = [ask("aaaa0002")]
    run(capsys, "--apply", "--note", "weekly sweep")
    assert asks.load_state()["done"]["aaaa0002"]["note"] == "weekly sweep expired: dropped"


def test_nothing_older(machine, capsys):
    machine["asks"] = [ask("aaaa0001", days=2)]
    code, out, _ = run(capsys)
    assert code == 0 and out.startswith("0 questions are older than 14 days. Dry run: nothing changed.")
    code, out, _ = run(capsys, "--apply")
    assert code == 0 and "nothing to close" in out


def test_unknown_words_still_error(machine, capsys):
    code = cli.main(["asks", "bogus"])
    assert code == 64
    assert "expire" in capsys.readouterr().err
    code, _, err = run(capsys, "extra")
    assert code == 64 and "usage: teyla asks expire" in err


def test_zero_days_is_refused(machine, capsys):
    code, _, err = run(capsys, "--older-than", "0")
    assert code == 64 and "above 0" in err
