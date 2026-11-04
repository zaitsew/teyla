"""`teyla subs`: the owner's recurring bills, one TOML file, nothing guessed."""
from __future__ import annotations

import argparse
import json
import stat

import pytest

from teyla import subs


def args(action="list", name=None, **kw):
    base = dict(action=action, name=name, monthly=None, category=None, renews=None, credits=None, note=None, json=False)
    return argparse.Namespace(**{**base, **kw})


def test_a_missing_file_is_an_empty_list():
    assert subs.load() == []
    assert subs.forecast([]) == {"monthly_usd": None, "priced": 0, "unpriced": []}


def test_add_set_remove_round_trip_and_the_file_is_private():
    subs.add("Alpha", monthly_usd="20", category="ai", note="has a \"quote\" and a tab\there")
    subs.add("Beta", category="cloud")
    rows = subs.load()
    assert [r["name"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0]["monthly_usd"] == 20.0 and rows[0]["note"] == 'has a "quote" and a tab here'
    assert rows[1]["monthly_usd"] is None                      # unknown stays unknown
    assert stat.S_IMODE(subs.path().stat().st_mode) == 0o600
    subs.update("alpha", monthly_usd=25, renews="2026-12-01")  # names match without case
    assert subs.load()[0]["monthly_usd"] == 25.0 and subs.load()[0]["renews"] == "2026-12-01"
    subs.update("Alpha", renews=None)                          # None clears
    assert subs.load()[0]["renews"] is None
    assert subs.remove("BETA")["name"] == "Beta"
    assert [r["name"] for r in subs.load()] == ["Alpha"]


def test_a_second_row_with_the_same_name_is_refused():
    subs.add("Alpha")
    with pytest.raises(subs.SubsError, match="already listed"):
        subs.add("alpha")


@pytest.mark.parametrize("fields, message", [
    ({"monthly_usd": "-1"}, "zero or more"),
    ({"monthly_usd": "abc"}, "number of US dollars"),
    ({"monthly_usd": "nan"}, "zero or more"),
    ({"category": "gadgets"}, "category must be one of"),
    ({"renews": "next week"}, "date like"),
    ({"credits_usd": True}, "number of US dollars"),
])
def test_bad_values_are_refused_with_the_reason(fields, message):
    with pytest.raises(subs.SubsError, match=message):
        subs.add("Alpha", **fields)
    assert subs.load() == []


def test_a_broken_file_names_its_path_and_does_not_turn_into_an_empty_list():
    subs.path().parent.mkdir(parents=True, exist_ok=True)
    subs.path().write_text("[[subscription]\nname = ")
    with pytest.raises(subs.SubsError, match="not valid TOML"):
        subs.load()
    subs.path().write_text('[[subscription]]\nname = "A"\n[[subscription]]\nname = "a"\n')
    with pytest.raises(subs.SubsError, match="listed twice"):
        subs.load()
    subs.path().write_text('[[subscription]]\nmonthly_usd = 5\n')
    with pytest.raises(subs.SubsError, match="needs a name"):
        subs.load()


def test_forecast_is_a_floor_and_names_the_rows_without_a_price():
    rows = [subs.clean({"name": "A", "monthly_usd": 100}), subs.clean({"name": "B"}),
            subs.clean({"name": "C", "monthly_usd": 0.5})]
    assert subs.forecast(rows) == {"monthly_usd": 100.5, "priced": 2, "unpriced": ["B"]}
    only_unpriced = [subs.clean({"name": "B"})]
    assert subs.forecast(only_unpriced)["monthly_usd"] is None   # not $0


def test_render_shows_dashes_for_unknowns_and_names_the_unpriced(capsys):
    subs.add("Alpha", monthly_usd=20, category="ai", credits_usd=20)
    subs.add("Beta")
    out = subs.render(subs.load())
    assert "Alpha" in out and "$20" in out
    assert "cash per month: $20 across 1 priced subscription(s); no price for: Beta" in out
    assert "no subscriptions listed" in subs.render([])


def test_the_command_covers_list_add_set_remove(capsys):
    assert subs.cmd_subs(args("add", "Alpha", monthly="20", category="ai")) == 0
    assert subs.cmd_subs(args("add", "Alpha")) == 1                         # duplicate
    assert subs.cmd_subs(args("set", "Alpha", monthly="30", note="x")) == 0
    assert subs.cmd_subs(args("set", "Alpha", note="none")) == 0            # `none` clears
    capsys.readouterr()
    assert subs.cmd_subs(args("list", json=True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["subscriptions"][0]["monthly_usd"] == 30.0 and data["subscriptions"][0]["note"] is None
    assert data["forecast"]["monthly_usd"] == 30.0
    assert subs.cmd_subs(args("set", "Alpha")) == 2                          # nothing to set
    assert subs.cmd_subs(args("remove")) == 2                                # no name
    assert subs.cmd_subs(args("remove", "Nope")) == 1
    assert subs.cmd_subs(args("remove", "Alpha")) == 0
    assert subs.cmd_subs(args("list")) == 0
    assert "no subscriptions listed" in capsys.readouterr().out


def test_the_parser_accepts_the_documented_forms():
    from teyla import cli
    p = cli.build_parser() if hasattr(cli, "build_parser") else None
    if p is None:
        pytest.skip("cli has no build_parser")
    ns = p.parse_args(["subs", "add", "Alpha", "--monthly", "20", "--category", "ai", "--renews", "2026-12-01",
                       "--credits", "20", "--note", "text"])
    assert ns.fn is subs.cmd_subs and ns.monthly == "20" and ns.name == "Alpha"
    assert p.parse_args(["subs"]).action == "list"


def test_a_failed_save_leaves_the_old_list_whole(monkeypatch):
    subs.add("Alpha", monthly_usd=20)
    before = subs.path().read_text()

    def fail(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(subs.os, "replace", fail)
    with pytest.raises(OSError):
        subs.add("Beta")
    assert subs.path().read_text() == before
    assert [p.name for p in subs.path().parent.iterdir() if p.name.endswith(".tmp")] == []
