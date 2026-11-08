"""`teyla gtm`: the three counters, the source schema, prefixed funnels and what a missing source does (docs/GTM.md).
Every test runs in the tmp TEYLA_HOME of conftest.py, with invented sources and no real product data."""
from __future__ import annotations

import json
import time

import pytest

from teyla import cli, gtm

DAY = "2026-11-04"                       # a Wednesday in 2026-W45
WEEK = "2026-W45"
NOW = time.mktime((2026, 11, 4, 12, 0, 0, 0, 0, -1))
UPDATED = "2026-11-04T09:00:00Z"


def goals(text: str = gtm.EXAMPLE_GOALS) -> dict:
    p = gtm.home() / "goals.toml"
    gtm._write(p, text)
    return gtm.load_goals(p)


def drop(name: str, doc: dict) -> None:
    gtm._write(gtm.drop_dir() / f"{name}.json", json.dumps(doc))


def collect(g: dict, rows=(), items=None, usage=None, runner=None):
    return gtm.collect(g, DAY, NOW, runner=runner, usage=usage or {}, usage_ages={}, growth_rows=list(rows),
                       growth_items=items or {}, outreach_repos=[])


# --- the counters --------------------------------------------------------------------------------------------

def test_agent_rows_never_count_as_distribution():
    rows = [
        {"ev": "published", "day": DAY},
        {"ev": "attempt", "kind": "dm", "day": DAY, "n": 3},
        {"ev": "attempt", "kind": "email", "day": "2026-11-02"},
        {"ev": "attempt", "kind": "dm", "day": DAY, "by": "agent", "n": 5},     # claimed: 0 distribution
        {"ev": "attempt", "kind": "response", "day": DAY},
        {"ev": "attempt", "kind": "icp-meeting", "day": DAY},
        {"ev": "idea", "day": DAY}, {"ev": "draft", "day": DAY}, {"ev": "draft", "day": "2026-11-03"},
        {"ev": "published", "day": "2026-11-01"},                                  # last week
    ]
    docs, _ = collect(gtm.load_goals(gtm.home() / "none.toml"), rows)
    c = gtm.counters(docs)
    assert c["distribution"]["today"] == 4 and c["distribution"]["week"] == 5
    assert c["distribution"]["claimed_by_agents"] == 5
    assert c["outcomes"]["week"] == 2 and c["outcomes"]["by_stage"] == {"replied": 1, "conversation": 1}
    assert c["preparation"]["week"] == 3 and c["preparation"]["today"] == 2


def test_stage_class_reads_the_last_part():
    assert gtm.counter_of("network.sent") == "distribution"
    assert gtm.counter_of("investor.conversation") == "outcomes"
    assert gtm.counter_of("drafted") == "preparation"


# --- the schema ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("doc,why", [
    ({"source": "x", "updated": UPDATED}, "counts"),
    ({"source": "x", "counts": {"sent": -1}, "updated": UPDATED}, "whole number"),
    ({"source": "x", "counts": {"sent": True}, "updated": UPDATED}, "whole number"),
    ({"source": "x", "counts": {}, "updated": "yesterday"}, "updated"),
    ({"source": "x", "counts": {}, "updated": UPDATED, "week": "45"}, "week"),
    ({"source": "x", "counts": {}, "waiting": [], "updated": UPDATED}, "waiting"),
    ([1, 2], "object"),
])
def test_validate_refuses_a_bad_document(doc, why):
    out, reason = gtm.validate(doc)
    assert out is None and why in reason


def test_validate_keeps_only_http_links_and_normalises_keys():
    out, why = gtm.validate({"source": "Demo-Src", "counts": {"Signed-Up": 2}, "updated": UPDATED,
                             "links": {"approve": "https://example.com/q", "send": "file:///etc/passwd"}})
    assert why == "" and out["source"] == "demo_src" and out["counts"] == {"signed_up": 2}
    assert out["links"] == {"approve": "https://example.com/q"}


# --- sources -------------------------------------------------------------------------------------------------

def test_a_missing_source_is_one_doctor_line_and_never_fails():
    g = goals()
    docs, status = collect(g)
    missing = {s["id"] for s in status if s["state"] == "missing"}
    assert {"outreach", "batrack", "contacts", "accounts"} <= missing
    t = gtm.today_report(g, docs, status, DAY)
    assert sum(1 for line in t["doctor"] if line.startswith("contacts:")) == 1
    assert [x["id"] for x in t["goals"]] == ["relationships", "testers", "investors"]


def test_a_broken_command_is_reported_and_the_rest_still_reads():
    g = goals(gtm.EXAMPLE_GOALS + '\n[[source]]\nid = "outreach"\ncommand = ["exporter", "--json"]\n')
    drop("outreach", {"source": "outreach", "counts": {"network.sent": 99}, "updated": UPDATED})   # never replaces a broken entry
    docs, status = collect(g, runner=lambda cmd: (3, "", "boom\n"))
    row = next(s for s in status if s["id"] == "outreach")
    assert row["state"] == "broken" and "boom" in row["line"]
    assert "outreach" not in {d["source"] for d in docs}


def test_a_command_source_is_read():
    g = goals(gtm.EXAMPLE_GOALS + '\n[[source]]\nid = "accounts"\ncommand = ["exporter"]\n')
    out = json.dumps({"source": "whatever", "counts": {"invited": 30, "activated": 7}, "updated": UPDATED})
    docs, _ = collect(g, runner=lambda cmd: (0, out, ""))
    testers = gtm.goal_funnel(next(x for x in g["goals"] if x["id"] == "testers"), docs)
    assert {r["stage"]: r["count"] for r in testers["rows"]} == {"invited": 30, "signed_up": 0, "activated": 7, "retained": 0}
    assert testers["rows"][2]["conversion"] is None          # signed_up is 0: no ratio, not a division error


def test_prefixed_stages_feed_only_their_goal():
    g = goals()
    drop("outreach", {"source": "outreach", "updated": UPDATED, "week": WEEK,
                   "counts": {"network.sent": 20, "network.replied": 6, "network.conversation": 3, "investor.sent": 4,
                              "investor.conversation": 1},
                   "waiting": {"network.send": 5, "investor.send": 2, "reply": 3},
                   "offer_fit": {"network.hire": 1, "network.product": 2, "investor.hire": 9},
                   "links": {"send": "https://example.com/send"}})
    docs, status = collect(g)
    rel = gtm.goal_funnel(g["goals"][0], docs)
    inv = gtm.goal_funnel(g["goals"][2], docs)
    assert {r["stage"]: r["count"] for r in rel["rows"]}["approached"] == 20
    assert {r["stage"]: r["count"] for r in rel["rows"]}["conversation"] == 3
    assert rel["offer_fit"] == {"hire": 1, "consulting": 0, "product": 2}
    assert {r["stage"]: r["count"] for r in inv["rows"]} == {"identified": 0, "approached": 4, "conversation": 1, "follow_up": 0}
    t = gtm.today_report(g, docs, status, DAY)
    assert t["send"]["total"] == 7 and t["send"]["links"] == {"outreach": "https://example.com/send"}
    assert [a["kind"] for a in t["next"]][:2] == ["reply", "send"]


def test_counts_for_another_week_count_zero():
    g = goals()
    drop("contacts", {"source": "contacts", "counts": {"network.conversation": 4}, "updated": UPDATED, "week": "2026-W44",
                    "channels": {"email": {"network.replied": 2}}, "offer_fit": {"network.hire": 1}})
    docs, status = collect(g)
    assert next(s for s in status if s["id"] == "contacts")["state"] == "stale"
    assert gtm.counters(docs)["outcomes"]["week"] == 0
    w = gtm.week_report(g, docs, status, WEEK, DAY)
    assert w["channels"] == {} and w["goals"][0]["offer_fit"]["hire"] == 0


def test_today_counts_from_another_day_are_dropped():
    g = goals()
    drop("accounts", {"source": "accounts", "counts": {"invited": 3}, "today": {"invited": 3},
                      "updated": "2026-11-03T09:00:00Z"})
    docs, _ = collect(g)
    assert gtm.counters(docs)["distribution"]["today"] == 0
    assert gtm.counters(docs)["distribution"]["week"] == 3


def test_usage_probe_counters_feed_the_adapter():
    g = goals()
    usage = {"batrack": {"drafts_open": "4", "gtm_network.replied": "2", "jobs": "10", "replies": "50"}}
    docs, status = collect(g, usage=usage)
    doc = next(d for d in docs if d["source"] == "batrack")
    assert doc["waiting"] == {"approve": 4}
    assert doc["counts"] == {"network.replied": 2}           # an all-time `replies` never counts as this week
    assert next(s for s in status if s["id"] == "batrack")["state"] == "ok"


def test_a_usage_probe_from_last_week_counts_zero():
    g = goals()
    last_sunday = time.mktime((2026, 11, 1, 20, 0, 0, 0, 0, -1))
    docs, status = gtm.collect(g, DAY, NOW, usage={"batrack": {"sent_week": "20"}}, usage_ages={"batrack": last_sunday},
                               growth_rows=[], growth_items={}, outreach_repos=[])
    assert next(s for s in status if s["id"] == "batrack")["state"] == "stale"
    assert gtm.counters(docs)["distribution"]["week"] == 0


def test_review_queue_waits_for_approval():
    items = {"g1104-aaaa": {"status": "review", "kind": "post", "platform": "x"},
             "g1104-bbbb": {"status": "checked", "kind": "post", "platform": "x", "hold_reason": "weak"},
             "g1104-cccc": {"status": "review", "kind": "post", "platform": "master"}}
    g = goals()
    docs, status = collect(g, items=items)
    t = gtm.today_report(g, docs, status, DAY)
    assert t["approve"]["by_source"] == {"growth": 1}
    assert t["next"][0]["command"] == "teyla growth review"


def test_distribution_gap_and_deadline():
    g = goals()
    docs, status = collect(g, rows=[{"ev": "published", "day": DAY}])
    t = gtm.today_report(g, docs, status, DAY)
    assert t["distribution"] == {"today": 1, "target": 10, "week": 1, "claimed_by_agents": 0}
    assert t["next"][-1]["kind"] == "distribute" and t["next"][-1]["count"] == 9
    assert t["goals"][0]["days_left"] == 117


def test_week_report_lists_missed_targets_and_channels():
    g = goals()
    drop("outreach", {"source": "outreach", "updated": UPDATED, "counts": {"network.sent": 10, "network.conversation": 5},
                   "stalled": {"network.replied": 2}, "channels": {"email": {"network.replied": 2, "network.sent": 8}}})
    docs, status = collect(g)
    w = gtm.week_report(g, docs, status, WEEK, DAY)
    rel = w["goals"][0]
    assert rel["missed"]["conversation"] == 10 and rel["missed"]["approached"] == 50
    assert rel["stalled"] == {"replied": 2}
    assert w["channels"] == {"email": {"network.replied": 2}}
    assert "missed:" in gtm.render_week(w)


# --- goals and the command line ------------------------------------------------------------------------------

def test_example_goals_load_clean_with_offer_fit():
    g = goals()
    assert g["errors"] == [] and g["per_day"] == 10
    rel = g["goals"][0]
    assert rel["funnel"][-1] == "offer_fit" and rel["offer_fit"] == ["hire", "consulting", "product"]


def test_wrong_toml_types_are_errors_not_crashes():
    g = goals('distribution = 10\ngoal = "x"\n')
    assert len(g["errors"]) == 2 and g["goals"] == []
    g = goals('[[goal]]\nid = "a"\nfunnel = "x"\nweekly = 3\nmap = 1\nsources = "y"\n')
    assert len(g["errors"]) == 4 and g["goals"][0]["funnel"] == [] and g["goals"][0]["sources"] == []


def test_bad_goal_lines_are_errors_not_crashes():
    g = goals('[[goal]]\ntitle = "no id"\n[[goal]]\nid = "a"\ndeadline = "soon"\n[goal.weekly]\nx = "lots"\n')
    assert len(g["errors"]) == 3 and g["goals"][0]["deadline"] == ""


def test_cli_runs_with_nothing_set_up(capsys):
    assert cli.main(["gtm", "--json"]) == 0
    t = json.loads(capsys.readouterr().out)
    assert t["version"] == 1 and t["has_goals"] is False
    assert any("teyla gtm init" in line for line in t["doctor"])
    assert cli.main(["gtm", "week"]) == 0
    assert cli.main(["gtm", "doctor"]) == 0


def test_cli_init_then_week_saves_and_rereads(capsys):
    assert cli.main(["gtm", "init"]) == 0
    assert cli.main(["gtm", "init"]) == 1
    assert cli.main(["gtm", "today"]) == 0
    saved = list(gtm.weeks_dir().glob("*.json"))
    assert len(saved) == 1
    assert cli.main(["gtm", "week", "--week", saved[0].stem, "--json"]) == 0
    assert cli.main(["gtm", "week", "--week", "2020-W01"]) == 1
    assert cli.main(["gtm", "week", "--week", "soon"]) == 2


def test_gtm_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TEYLA_GTM_DIR", str(tmp_path / "g"))
    assert gtm.goals_path() == tmp_path / "g" / "goals.toml"


# --- goal-first Today: shortfall, history, writing goals -------------------------------------------------------

def test_today_goal_carries_done_when_short_and_counter():
    g = goals()
    docs, status = collect(g, rows=[{"ev": "attempt", "kind": "call", "day": DAY, "by": "owner"}])
    t = gtm.today_report(g, docs, status, DAY)
    rel = t["goals"][0]
    assert rel["done_when"] == "A hire, a consulting deal or a product sale"
    assert rel["weeks_left"] == 17 and t["week_end"] == "2026-11-08"
    kinds = {x["stage"]: x["counter"] for x in rel["targets"]}
    assert kinds["approached"] == "distribution" and kinds["conversation"] == "outcomes"
    # Outcomes only: 14 conversations + 3 intros + 1 offer fit short. The 60 approaches never count toward a goal.
    assert rel["short"] == 14 + 3 + 1


def test_history_reads_saved_weeks_and_marks_gaps():
    g = goals()
    gtm._write(gtm.weeks_dir() / "2026-W43.json", json.dumps(
        {"week": "2026-W43", "goals": [{"id": "relationships", "funnel": [{"stage": "conversation", "count": 4}]}]}))
    docs, status = collect(g)
    t = gtm.today_report(g, docs, status, DAY)
    hist = next(x for x in t["goals"][0]["targets"] if x["stage"] == "conversation")["history"]
    assert len(hist) == 8 and hist[-1] == {"week": WEEK, "count": 0}
    assert {"week": "2026-W43", "count": 4} in hist
    assert hist[0] == {"week": "2026-W38", "count": None}


def test_goal_add_creates_the_file_then_appends(capsys):
    assert cli.main(["gtm", "goal", "add", "--title", "Paying customers", "--weekly", "paid=2", "--per-day", "8",
                     "--deadline", "2027-01-31", "--done-when", "Ten paying teams", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "paying_customers" and out["weekly"] == {"paid": 2} and out["sources"] == ["growth"]
    loaded = gtm.load_goals()
    assert loaded["per_day"] == 8 and not loaded["errors"]
    assert cli.main(["gtm", "goal", "add", "--title", "Paying customers"]) == 0
    assert [x["id"] for x in gtm.load_goals()["goals"]] == ["paying_customers", "paying_customers_2"]
    assert cli.main(["gtm", "goal", "add", "--title", "x", "--weekly", "paid=lots"]) == 2
    assert cli.main(["gtm", "goal", "add", "--title", "x", "--deadline", "soon"]) == 2


def test_goal_set_rewrites_only_its_block():
    goals()
    before = gtm.goals_path().read_text(encoding="utf-8")
    g = gtm.set_goal("investors", weekly={"conversation": 3, "intro": 1}, done_when="A lead investor")
    assert g["weekly"] == {"conversation": 3, "intro": 1} and g["done_when"] == "A lead investor"
    assert "intro" in g["funnel"]
    after = gtm.goals_path().read_text(encoding="utf-8")
    assert after.split("id = \"investors\"")[0].rstrip() == before.split("id = \"investors\"")[0].rstrip()
    assert "# [[source]]" in after                     # comments after the block survive
    loaded = gtm.load_goals()
    assert not loaded["errors"] and [x["id"] for x in loaded["goals"]] == ["relationships", "testers", "investors"]
    assert loaded["goals"][0]["map"] == {"sent": "approached"}
    g = gtm.set_goal("investors", weekly={"intro": 0})
    assert g["weekly"] == {"conversation": 3}
    with pytest.raises(gtm.GtmError):
        gtm.set_goal("nobody", weekly={"x": 1})


def test_goal_set_cli_needs_a_change():
    goals()
    assert cli.main(["gtm", "goal", "set", "testers"]) == 2
    assert cli.main(["gtm", "goal", "set", "testers", "--weekly", "activated=10"]) == 0
    assert next(x for x in gtm.load_goals()["goals"] if x["id"] == "testers")["weekly"]["activated"] == 10


def test_goal_set_keeps_a_dotted_map_key_one_key():
    goals(gtm.EXAMPLE_GOALS.replace('[goal.map]                 # a source\'s stage name -> this funnel\'s stage name\nsent = "approached"',
                                    '[goal.map]\n"network.sent" = "approached"', 1))
    assert gtm.load_goals()["goals"][0]["map"] == {"network.sent": "approached"}
    gtm.set_goal("relationships", weekly={"intro": 4})
    loaded = gtm.load_goals()
    assert not loaded["errors"] and loaded["goals"][0]["map"] == {"network.sent": "approached"}
    assert '"network.sent" = "approached"' in gtm.goals_path().read_text(encoding="utf-8")


# --- drafts and goals ----------------------------------------------------------------------------------------

def draft(i, **kw):
    it = {"id": f"g1104-{i}", "kind": "post", "platform": "linkedin", "product": "alpha", "status": "review"}
    it.update(kw)
    return it


def items(*its):
    return {i["id"]: i for i in its}


DRAFT_GOALS = (gtm.EXAMPLE_GOALS.replace('kinds = ["post"]', 'kinds = ["post"]\nplatforms = ["linkedin", "x"]')
               + '\n[[goal]]\nid = "alpha_fans"\ntitle = "Alpha fans"\nsources = ["growth"]\n[goal.drafts]\nproducts = ["alpha"]\n')


def test_the_example_goal_matches_posts_and_round_trips():
    g = goals()
    assert g["goals"][0]["drafts"] == {"kinds": ["post"]} and g["goals"][1]["drafts"] is None
    text = gtm.render_goal(g["goals"][0])
    assert "[goal.drafts]" in text and 'kinds = ["post"]' in text
    p = gtm.home() / "round.toml"
    gtm._write(p, text)
    assert gtm.load_goals(p)["goals"][0]["drafts"] == {"kinds": ["post"]}


def test_goal_set_keeps_the_drafts_table():
    goals(DRAFT_GOALS)
    gtm.set_goal("relationships", weekly={"intro": 4})
    g = gtm.load_goals()
    assert g["errors"] == [] and g["goals"][0]["weekly"]["intro"] == 4
    assert g["goals"][0]["drafts"] == {"platforms": ["linkedin", "x"], "kinds": ["post"]}
    assert g["goals"][3]["drafts"] == {"products": ["alpha"]}


def test_an_empty_drafts_table_matches_nothing_and_bad_ones_are_error_lines():
    g = goals('[[goal]]\nid = "a"\n[goal.drafts]\n[[goal]]\nid = "b"\ndrafts = 3\n[[goal]]\nid = "c"\n[goal.drafts]\nkinds = "post"\n')
    assert g["goals"][0]["drafts"] == {} and gtm.draft_goal(draft("a"), g) == (None, None)
    assert len(g["errors"]) == 2 and any("drafts" in e for e in g["errors"])


def test_rules_need_every_listed_field_and_the_first_goal_wins():
    g = goals(DRAFT_GOALS)
    assert gtm.draft_goal(draft("a"), g) == ("relationships", "rule")
    assert gtm.draft_goal(draft("b", platform="threads"), g) == ("alpha_fans", "rule")       # kinds+platforms fail, products match
    assert gtm.draft_goal(draft("c", platform="threads", product="beta"), g) == (None, None)
    assert gtm.draft_goal(draft("d", kind="clip", platform="x"), g) == ("alpha_fans", "rule")


def test_a_manual_tag_beats_rules_and_none_means_no_goal():
    g = goals(DRAFT_GOALS)
    assert gtm.draft_goal(draft("a", goal="alpha_fans"), g) == ("alpha_fans", "manual")
    assert gtm.draft_goal(draft("b", goal=""), g) == (None, "manual")
    assert gtm.draft_goal(draft("c", goal="gone"), g) == ("relationships", "rule")           # a stale tag is ignored


def test_today_counts_drafts_per_goal_and_untagged():
    g = goals(DRAFT_GOALS)
    its = items(draft("a"), draft("b", goal="alpha_fans"), draft("c", goal=""), draft("d", platform="tiktok", product="beta"),
                draft("e", kind="episode"), draft("f", platform="master"), draft("g", hold_reason="x", status="draft"),
                draft("h", status="published"))
    drop("outreach", {"source": "outreach", "updated": UPDATED, "week": WEEK, "counts": {},
                      "waiting": {"network.approve": 3, "investor.approve": 2, "approve": 4}})
    docs, status = collect(g, items=its)
    t = gtm.today_report(g, docs, status, DAY)
    rel, alpha = t["goals"][0], t["goals"][3]
    assert rel["drafts"] == {"total": 4, "growth": 1, "by_source": {"growth": 1, "outreach": 3}}
    assert alpha["drafts"] == {"total": 1, "growth": 1, "by_source": {"growth": 1}}
    assert t["goals"][2]["drafts"]["by_source"] == {"outreach": 2}                        # investor prefix, source listed
    assert t["goals"][1]["drafts"]["total"] == 0                                            # testers: no growth, no prefix
    assert t["untagged_drafts"] == 2 + 4                                                    # c, d + the unprefixed approve
    assert t["draft_goals"] == {"g1104-a": "relationships", "g1104-b": "alpha_fans"}
    assert t["approve"]["by_source"]["growth"] == 4                                         # same filter as the queue count
    text = gtm.render_today(t)
    assert "drafts for this goal: 4" in text and "6 drafts have no goal" in text


def test_draft_goals_is_capped():
    g = goals(DRAFT_GOALS)
    its = items(*[draft(f"{n:04d}") for n in range(gtm.MAX_DRAFT_GOALS + 20)])
    docs, status = collect(g, items=its)
    t = gtm.today_report(g, docs, status, DAY)
    assert len(t["draft_goals"]) == gtm.MAX_DRAFT_GOALS
    assert t["goals"][0]["drafts"]["growth"] == gtm.MAX_DRAFT_GOALS + 20


def test_a_source_without_the_prefix_or_not_listed_is_untagged():
    g = goals()
    drop("stranger", {"source": "stranger", "updated": UPDATED, "week": WEEK, "counts": {}, "waiting": {"network.approve": 5}})
    docs, status = collect(g)
    t = gtm.today_report(g, docs, status, DAY)
    assert t["untagged_drafts"] == 5 and t["goals"][0]["drafts"]["total"] == 0


def test_an_empty_draft_matcher_list_allows_nothing_and_survives_goal_set():
    goals(gtm.EXAMPLE_GOALS.replace('kinds = ["post"]', 'products = []\nkinds = ["post"]', 1))
    g = gtm.load_goals()
    assert g["goals"][0]["drafts"]["products"] == [] and g["goals"][0]["drafts"]["kinds"] == ["post"]
    item = {"id": "g1104-dddd", "kind": "post", "platform": "x", "product": "alpha", "status": "review"}
    assert gtm.draft_goal(item, g) == (None, None)
    gtm.set_goal("relationships", weekly={"intro": 4})
    assert gtm.load_goals()["goals"][0]["drafts"]["products"] == []
