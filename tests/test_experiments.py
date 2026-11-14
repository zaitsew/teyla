"""`teyla experiments`: a verdict per feature before an experiment is retired. Synthetic names only."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import cli, experiments as ex, you

TODAY = dt.date(2026, 11, 14)


def run(*argv) -> int:
    return cli.main(list(argv))


def lab(since="2026-10-01"):
    ex.add("demo", "lab-2", "lab", title="second generation UI", where="scheme Demo 2", since=since)
    return ex.feature("demo", "lab-2", "week strip on the home screen"), ex.feature("demo", "lab-2", "voice capture button")


def test_features_get_stable_ids_and_a_repeat_is_the_same_feature():
    f1, f2 = lab()
    assert (f1, f2) == ("f1", "f2")
    assert ex.feature("demo", "lab-2", "Week strip on the  home screen") == "f1"


def test_retire_is_refused_until_every_feature_has_a_verdict():
    f1, f2 = lab()
    with pytest.raises(ex.ExperimentError, match="2 feature\\(s\\) without a verdict") as e:
        ex.retire("demo", "lab-2")
    assert "f1  week strip" in str(e.value) and "f2  voice capture" in str(e.value)
    ex.verdict("demo", "lab-2", f1, "promoted", "https://github.com/o/r/pull/7")
    with pytest.raises(ex.ExperimentError, match="1 feature"):
        ex.retire("demo", "lab-2")
    ex.verdict("demo", "lab-2", f2, "parked", "when the phone app gets a microphone permission screen")
    assert ex.retire("demo", "lab-2")["retired"] == dt.date.today().isoformat()


def test_an_experiment_with_no_features_written_down_cannot_be_retired():
    ex.add("demo", "variant-b", "variant")
    with pytest.raises(ex.ExperimentError, match="no features written down"):
        ex.retire("demo", "variant-b")


@pytest.mark.parametrize("what,because,why", [
    ("promoted", "", "promoted needs --pr"),
    ("promoted", "it went in last week", "the PR's URL"),
    ("parked", "", "parked needs --trigger"),
    ("dropped", " ", "dropped needs --reason"),
    ("kept", "x", "verdict 'kept'"),
])
def test_each_verdict_needs_its_because(what, because, why):
    f1, _ = lab()
    with pytest.raises(ex.ExperimentError, match=why):
        ex.verdict("demo", "lab-2", f1, what, because)


def test_owner_repo_number_counts_as_a_pr():
    f1, _ = lab()
    assert ex.verdict("demo", "lab-2", f1, "promoted", "o/r#12")["verdict"] == "promoted"


def test_bad_ids_kinds_and_duplicates_are_refused():
    with pytest.raises(ex.ExperimentError, match="an id is"):
        ex.add("demo", "Lab 2", "lab")
    with pytest.raises(ex.ExperimentError, match="kind"):
        ex.add("demo", "lab-3", "fork")
    lab()
    with pytest.raises(ex.ExperimentError, match="exists"):
        ex.add("demo", "lab-2", "lab")


def test_stale_means_old_with_a_feature_lacking_a_verdict_or_no_features():
    lab(since="2026-10-01")
    ex.add("demo", "fresh", "variant", since="2026-11-10")
    ex.feature("demo", "fresh", "one card layout")
    ex.add("demo", "empty", "app", since="2026-10-20")
    names = [(r["id"], ex.stale_line(r)) for r in ex.stale(TODAY)]
    assert names == [("lab-2", "demo/lab-2 (lab, 44 days): 2 of 2 features without a verdict"),
                     ("empty", "demo/empty (app, 25 days): no features written down")]


def test_parked_features_stay_listed_after_retiring():
    f1, f2 = lab()
    ex.verdict("demo", "lab-2", f1, "dropped", "the owner prefers the month view")
    ex.verdict("demo", "lab-2", f2, "parked", "after the voice provider decision")
    ex.retire("demo", "lab-2")
    assert ex.stale(TODAY) == []
    p = ex.parked()
    assert [(x["feature"], x["trigger"], bool(x["retired"])) for x in p] == [("f2", "after the voice provider decision", True)]


def test_teyla_you_shows_stale_experiments():
    lab()
    o = you.owed(TODAY)
    assert [r["line"] for r in o["experiments"]] == ["demo/lab-2 (lab, 44 days): 2 of 2 features without a verdict"]
    assert "  experiment demo/lab-2 (lab, 44 days)" in "\n".join(you.render_owed(o))


def test_the_command(capsys):
    assert run("experiments", "add", "demo", "lab-2", "--kind", "lab", "--since", "2026-10-01") == 0
    assert run("experiments", "feature", "demo", "lab-2", "week", "strip", "--request", "0123abcd.1") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "demo/lab-2 f1"
    assert run("experiments", "retire", "demo", "lab-2") == 1
    assert "f1  week strip" in capsys.readouterr().err
    assert run("experiments", "verdict", "demo", "lab-2", "f1", "promoted", "--pr", "https://github.com/o/r/pull/1") == 0
    assert run("experiments", "retire", "demo", "lab-2") == 0
    capsys.readouterr()
    assert run("experiments") == 0
    assert "no open experiments" in capsys.readouterr().out
    assert run("experiments", "--all", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["retired"] and rows[0]["verdicts"]["promoted"] == 1
    assert run("experiments", "show", "demo", "lab-2") == 0
    assert "(request 0123abcd.1)" in capsys.readouterr().out
    assert run("experiments", "add", "demo", "x") == 1          # no --kind
    assert run("experiments", "frobnicate") == 64


def test_store_is_private():
    lab()
    assert oct(ex.path("demo").stat().st_mode & 0o777) == "0o600"
    assert oct(ex.home().stat().st_mode & 0o777) == "0o700"
