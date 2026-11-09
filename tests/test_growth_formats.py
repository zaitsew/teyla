"""The owner's formats and calls to action (docs/GROWTH.md, "The formats" and "Calls to action"). Fakes only: the model and
gh come from the fixtures of test_growth; nothing is published or sent."""
from __future__ import annotations

import pytest

from teyla import growth, growth_formats as F, growth_rank as rank, notes
from test_growth import DAY, GOOD, NOW, REAL_SOURCES, env, fake_model, make, master  # noqa: F401

EARLY = "https://accounts.fabriquefutur.com/early/{}?ref={}"


def harvest_notes(store, cfg):
    skip = tuple(n for n, _ in growth.SOURCES if n not in ("notes",))
    return growth.harvest(store, cfg, NOW, allow_net=False, skip=skip)


def masters(store):
    return {i["format"]: i for i in store.items().values() if i["platform"] == growth.MASTER}


# --- tag -> format -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tag,fmt", [("spec", "spec-product"), ("tvc", "true-vibe-coding"), ("wow", "wow-use-case"),
                                     ("case", "case-study"), ("week", "week-results"), ("ainative", "ai-native"),
                                     ("predict", "prediction"), ("viral", "viral-remix"), ("inadviser", "inadviser-verdict"),
                                     ("research", "research-note"), ("content", "lesson")])
def test_a_note_tag_selects_the_format(tag, fmt):
    assert F.note_format(f"Something happened #{tag}") == fmt
    assert F.note_format(f"#{tag.upper()} Something happened") == fmt


def test_tags_are_whole_words_and_the_first_in_order_wins():
    assert F.note_format("no tag here") is None
    assert F.note_format("#cases and #specs") is None
    assert F.note_format("a #content note that is also a #wow one") == "wow-use-case"
    assert F.note_format("mail me at a#spec") is None
    assert F.strip_tags("#wow Clicky did a thing #content") == "Clicky did a thing"


def test_every_new_format_has_a_brief_a_prior_and_is_known():
    for fmt in F.NEW:
        assert fmt in F.BRIEFS and fmt in F.PRIOR and fmt in growth.FORMATS and fmt in growth.FORMAT_BRIEF
    assert "true-vibe-coding" in F.PRIOR and F.PRIOR["wow-use-case"] > F.PRIOR["viral-remix"]


def test_the_planner_prior_follows_the_format(env):
    store, _ = make()
    for fmt, p in F.PRIOR.items():
        assert rank.prior(master(store, idea=f"x {fmt}", fmt=fmt, facts=("x",))) == p


def test_notes_become_ideas_in_their_format(env):
    store, cfg = make(public=("alpha", "beta"))
    notes.add("#wow Alpha plans a whole weekend from one voice note", product="alpha")
    notes.add("#case A bakery cut ordering time from 40 to 9 minutes with Beta")
    notes.add("#predict Voice becomes the default way to start a coding agent by mid 2027")
    notes.add("#research Zorbix: how do founders collect early feedback today?")
    notes.add("A plain lesson #content")
    harvest_notes(store, cfg)
    got = masters(store)
    assert set(got) == {"wow-use-case", "case-study", "prediction", "research-note", "lesson"}
    assert got["wow-use-case"]["kind"] == "clip" and got["wow-use-case"]["product"] == "alpha" and got["wow-use-case"]["owner"]
    assert got["case-study"]["kind"] == "post" and "40 to 9" in got["case-study"]["facts"][0]
    assert got["research-note"]["product"] == ""                       # Zorbix is in no registry: it is named, not linked
    assert "#" not in got["lesson"]["idea"]


def test_a_note_about_a_product_that_is_not_public_is_blocked(env):
    store, cfg = make(public=("alpha",))
    notes.add("#wow Gammatool files your invoices on its own")
    res = harvest_notes(store, cfg)
    assert not masters(store) and res["blocked"].get("unreleased-product")


def test_spec_notes_keep_the_founder_handle_for_the_first_reply(env):
    store, cfg = make()
    notes.add("#spec What if Acme was truly AI-native? @acme_founder")
    harvest_notes(store, cfg)
    it = masters(store)["spec-product"]
    assert it["tags"] == ["@acme_founder"] and "@" not in it["idea"] and it["product"] == "" and it["kind"] == "clip"


def test_viral_keeps_its_source_url_and_inadviser_needs_its_own(env):
    store, cfg = make(public=("alpha", "inadviser"))
    notes.add("#viral https://example.com/post/1 a one-sentence hook, then a turn")
    notes.add("#viral a viral post with no link")
    notes.add("#inadviser https://www.inadviser.com/verdicts/alpha costs 9 a month and has no offline mode")
    notes.add("#inadviser https://example.com/elsewhere a verdict from some other site")
    res = harvest_notes(store, cfg)
    got = masters(store)
    assert got["viral-remix"]["source_url"] == "https://example.com/post/1" and got["viral-remix"]["sources"][0]["url"] == "https://example.com/post/1"
    assert "example.com" not in got["viral-remix"]["idea"]
    assert got["inadviser-verdict"]["sources"][0]["url"] == "https://www.inadviser.com/verdicts/alpha"
    assert dict(res["rows"][0:0]) == {} and sum(1 for i in store.items().values() if i["format"] == "viral-remix") == 1
    note = [t for n, _c, t in res["rows"] if n == "notes"][0]
    assert "#viral no source URL" in note and "#inadviser no inadviser.com source URL" in note


def test_the_planned_item_keeps_tags_and_source_url(env):
    store, cfg = make(channels=("x-en",))
    master(store, idea="Take a thing", fmt="viral-remix", product="", facts=("a hook shape",), tags=["@x"], source_url="https://example.com/p")
    (row,) = growth.plan(store, cfg, DAY, NOW)
    assert row["item"]["source_url"] == "https://example.com/p" and row["item"]["tags"] == ["@x"]


# --- week results: only counts Teyla gathered --------------------------------------------------------------------

def test_last_week_is_the_last_completed_iso_week():
    assert F.last_week("2026-11-09") == ("2026-11-02", "2026-11-08", "2026-W45")
    assert F.last_week("2026-11-15") == ("2026-11-02", "2026-11-08", "2026-W45")
    assert F.last_week("2026-11-16")[2] == "2026-W46"


def test_week_facts_count_only_what_teyla_gathered(env):
    ledger = [dict(ev="published", day="2026-11-03"), dict(ev="published", day="2026-11-08"), dict(ev="published", day="2026-11-09"),
              dict(ev="attempt", kind="call", day="2026-11-04"), dict(ev="attempt", kind="meeting", day="2026-11-05", n=2),
              dict(ev="attempt", kind="call", day="2026-11-06", by="agent"), dict(ev="attempt", kind="comment", day="2026-11-06")]
    facts = F.week_facts("2026-11-09", ["2026-11-02", "2026-11-08", "2026-11-09", "2026-10-30"], ledger,
                         growth.is_claimed, growth.row_n, growth.MEETING_KINDS)
    text = " | ".join(facts)
    assert "merged pull requests in the week: 2" in text and "content items published in the week: 2" in text
    assert "calls and meetings the owner logged in the week: 3" in text            # the agent's claimed call is not counted
    assert "No other number exists" in text
    assert not any("merged pull requests in the week" in f for f in F.week_facts("2026-11-09", None, [], growth.is_claimed, growth.row_n, growth.MEETING_KINDS))


def test_a_week_idea_is_made_once_per_week_with_counts_only(env, monkeypatch):
    monkeypatch.setattr(growth, "SOURCES", REAL_SOURCES)
    store, cfg = make()
    monkeypatch.setattr(growth, "_pr_cache", lambda: {"owner/alpha": {"prs": [dict(merged_at="2026-11-03T10:00:00Z", title="x")]}})
    notes.add("#week Slow start, then 4 days of shipping, 12 percent more focus")
    skip = tuple(n for n, _ in growth.SOURCES if n not in ("notes", "week"))
    growth.harvest(store, cfg, NOW, allow_net=False, skip=skip)
    growth.harvest(store, cfg, NOW, allow_net=False, skip=skip)
    weeks = [i for i in store.items().values() if i["format"] == "week-results"]
    assert len(weeks) == 2                                              # one automatic, one from the note
    for w in weeks:
        assert "No other number exists" in w["facts"][0] and not any("12" in f for f in w["facts"])
        assert "12" not in w["idea"] and "4 days" not in w["idea"]


def test_a_week_note_that_states_mrr_is_blocked(env):
    store, cfg = make()
    notes.add("#week Slow start, then MRR up 12%")
    res = growth.harvest(store, cfg, NOW, allow_net=False, skip=tuple(n for n, _ in growth.SOURCES if n != "notes"))
    assert not masters(store) and res["blocked"] == {"revenue-or-runway": 1}


def test_week_results_still_refuse_revenue_mrr_conversion_and_users(env):
    g = growth.Guard(make()[1])
    for bad in ("MRR hit a new high this week.", "Revenue doubled.", "Conversion rate rose to a new high.",
                "We have 1,200 users now.", "A 12% conversion on the landing page."):
        assert g.check(bad), bad
    assert not g.check("Merged pull requests this week: 7. Published items: 5.")


# --- the call to action --------------------------------------------------------------------------------------------

def item(fmt, product="alpha", platform="x"):
    return dict(format=fmt, product=product, platform=platform, tags=[])


def test_the_cta_follows_the_format(env):
    cfg = make(public=("alpha",))[1] | dict(research_form="https://forms.example.com/research")
    kinds = {fmt: F.resolve(item(fmt), cfg)["kind"] for fmt in growth.FORMATS}
    assert kinds["spec-product"] == "founder-question"
    assert kinds["true-vibe-coding"] == kinds["wow-use-case"] == "none"          # alpha has no early-access form: see below
    assert kinds["case-study"] == kinds["ai-native"] == "talk"
    assert kinds["week-results"] == "follow" and kinds["research-note"] == "research"
    assert kinds["worklog"] == kinds["lesson"] == kinds["product-spotlight"] == kinds["viral-remix"] == "none"


def test_the_early_access_link_is_built_by_code(env):
    cfg = make(public=("alpha", "beta", "gamma"))[1] | dict(early_products=["alpha", "beta"])
    c = F.resolve(item("wow-use-case", "alpha", "linkedin"), cfg)
    assert c["kind"] == "early-access" and c["link"] == EARLY.format("alpha", "linkedin")
    assert F.resolve(item("true-vibe-coding", "beta", "x"), cfg)["link"] == EARLY.format("beta", "x")
    nope = F.resolve(item("wow-use-case", "gamma", "x"), cfg)                       # public, but the hub has no form for it
    assert nope["kind"] == "none" and nope["link"] == "" and "no early-access form" in nope["note"]
    cfg["public_products"] = ["alpha"]
    private = F.resolve(item("wow-use-case", "beta", "x"), cfg)                     # a form, but the product is not public
    assert private["kind"] == "none" and private["link"] == ""
    assert F.resolve(item("wow-use-case", "", "x"), cfg)["kind"] == "none"


def test_forms_come_from_the_hubs_cockpit_source_unless_the_config_says_otherwise(env, tmp_path, monkeypatch):
    drop = tmp_path / "gtm" / "sources"
    drop.mkdir(parents=True)
    monkeypatch.setenv("TEYLA_GTM_DIR", str(tmp_path / "gtm"))
    cfg = make(public=("alpha", "beta"))[1]
    assert F.early_forms(cfg) == set() and F.resolve(item("wow-use-case", "alpha"), cfg)["kind"] == "none"   # nothing known
    (drop / F.EARLY_SOURCE).write_text('{"source": "accounts-early-access", "products": {"alpha": {}, "some-app": {}}}')
    assert F.early_forms(cfg) == {"alpha", "someapp"}
    assert F.resolve(item("wow-use-case", "alpha"), cfg)["link"] == EARLY.format("alpha", "x")
    assert F.resolve(item("wow-use-case", "beta"), cfg)["link"] == ""
    assert F.early_forms(dict(cfg, early_products=["beta"])) == {"beta"}                  # the config wins
    assert F.early_forms(dict(cfg, early_products=[])) == set()
    (drop / F.EARLY_SOURCE).write_text("not json")
    assert F.early_forms(cfg) == set()


def test_a_form_is_named_without_hyphens():
    assert F.early_slug("some-app") == "someapp" and F.early_link("some-app", "x") == EARLY.format("someapp", "x")


def test_links_never_carry_a_bad_ref():
    assert F.early_link("alpha", "x") == EARLY.format("alpha", "x")
    assert F.early_link("../etc", "x") == "" and F.early_link("alpha", "x&y=1") == ""
    assert F.with_ref("https://f.example.com/r?a=1&ref=old", "tiktok") == "https://f.example.com/r?a=1&ref=tiktok"
    assert F.research_link({"research_form": "http://insecure.example.com/f"}, "x") == ""
    assert F.research_link({"research_form": ""}, "x") == ""


def test_a_research_post_without_a_form_is_held_before_any_model_call(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store, idea="How do founders collect early feedback?", product="", fmt="research-note", facts=("a question",))
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    fm = fake_model([GOOD])
    monkeypatch.setattr(growth, "call_model", fm)
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "draft" and "research_form" in got["hold_reason"] and not fm.calls
    rows = growth.doctor_rows(store, cfg, NOW)
    assert any(n == "research form" and s == "note" for s, n, _ in rows)


def test_apply_cta_puts_the_link_only_in_the_first_comment():
    it = dict(format="wow-use-case", first_comment="Early access is open. https://evil.example.com/x",
              cta=dict(kind="early-access", link=EARLY.format("alpha", "x"), handles=[]))
    F.apply_cta(it)
    assert it["first_comment"] == "Early access is open. " + EARLY.format("alpha", "x")
    it["first_comment"] = ""
    F.apply_cta(it)
    assert it["first_comment"] == EARLY.format("alpha", "x")


def test_a_founder_is_tagged_only_in_the_first_reply():
    it = dict(format="spec-product", first_comment="@someone_else Would Acme ship this? https://x.example.com",
              cta=dict(kind="founder-question", link="", handles=["@acme_founder"]))
    F.apply_cta(it)
    assert it["first_comment"] == "@acme_founder Would Acme ship this?"


def test_no_other_format_has_its_first_comment_touched():
    it = dict(format="worklog", first_comment="See https://example.com/pr", cta=dict(kind="none", link="", handles=[]))
    F.apply_cta(it)
    assert it["first_comment"] == "See https://example.com/pr"


def test_cta_findings():
    link = dict(kind="early-access", link=EARLY.format("alpha", "x"), handles=[])
    assert [f["rule"] for f in F.findings(dict(cta=link), f"Try it {link['link']}")] == ["cta-link"]
    assert not F.findings(dict(cta=link), "Early access is open.")
    spec = dict(format="spec-product", cta=dict(kind="founder-question", link="", handles=["@a"]), first_comment="@a Would you ship it?")
    assert not F.findings(spec, "What if Acme was AI-native? The prototype does it in 9 seconds.")
    assert [f["rule"] for f in F.findings(spec, "Let's meet and talk about it.")] == ["cta-meet"]
    assert [f["rule"] for f in F.findings(spec, "@acme look at this")] == ["cta-tag"]
    assert [f["rule"] for f in F.findings(dict(spec, first_comment="@a"), "Fine body.")] == ["cta-question"]
    talk = dict(cta=dict(kind="talk", link="", handles=[]))
    assert not F.findings(talk, "Tell me about your team, let's talk.")


def test_a_research_note_about_a_product_that_does_not_exist_never_claims_it_does():
    it = dict(format="research-note", product="", cta=dict(kind="research", link="https://f.example.com/r?ref=x", handles=[]))
    assert not F.findings(it, "I am researching how founders collect feedback before they build anything.")
    for claim in ("Zorbix launched today.", "Zorbix is live: sign up now.", "Download Zorbix.", "Try it, we built it."):
        assert [f["rule"] for f in F.findings(it, claim)] == ["research-claim"], claim


# --- guard rules ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Comment WOW to get access.", "comment \"early\" to get the app", "Reply with ALPHA to receive the invite",
                                  "DM me ACCESS to join the beta", "Comment below to get access", "comment X and I'll send it"])
def test_comment_gating_is_refused(env, text):
    hits = growth.Guard(make()[1]).check(text)
    assert "engagement-bait" in [h["kind"] for h in hits], text


@pytest.mark.parametrize("text", ["Tell me about your team. I am open to opportunities.", "Hire me for your next build.", "We're hiring a founding engineer.",
                                  "I'm available for hire.", "Looking for new opportunities, DM me."])
def test_a_public_cta_never_mentions_hiring(env, text):
    assert "hiring" in [h["kind"] for h in growth.Guard(make()[1]).check(text)] or "job-search" in [h["kind"] for h in growth.Guard(make()[1]).check(text)], text


def test_ordinary_calls_to_action_pass_the_guard(env):
    g = growth.Guard(make()[1])
    for ok in ("Tell me about your team, let's talk.", "Early access is open for Alpha.", "Join the research: five questions about feedback.",
               "Follow for next week's counts.", "Would you ship this, Acme?"):
        assert not g.check(ok), ok


# --- drafting end to end -------------------------------------------------------------------------------------------

def test_a_draft_with_a_link_in_the_body_is_retried_and_the_link_lands_in_the_first_comment(env, monkeypatch):
    store, cfg = make(public=("alpha",), channels=("x-en",), extra='early_products = ["alpha"]')
    master(store, idea="Alpha planned a weekend", product="alpha", fmt="wow-use-case", facts=("Alpha planned a weekend trip in 9 seconds",))
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    bad = dict(GOOD, body=f"Alpha planned a weekend in 9 seconds. Try it: {EARLY.format('alpha', 'x')}", first_comment="")
    ok = dict(GOOD, body="Alpha planned a weekend trip in 9 seconds. Early access is open.", hook="Alpha planned a weekend trip in 9 seconds.",
              first_comment="Early access is open: https://evil.example.com/x")
    fm = fake_model([bad, ok])
    monkeypatch.setattr(growth, "call_model", fm)
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "review", (got.get("fail_reason"), got.get("hold_reason"))
    assert got["cta"]["kind"] == "early-access"
    assert "http" not in got["body"] and got["first_comment"].endswith(EARLY.format("alpha", "x")) and "evil" not in got["first_comment"]
    assert fm.calls[0]["payload"]["cta"]["kind"] == "early-access" and EARLY.format("alpha", "x") not in str(fm.calls[0]["payload"])
    assert any("cta-link" in str(c["payload"].get("fix")) for c in fm.calls[1:])
    assert "cta: early-access -> " + EARLY.format("alpha", "x") in growth.render_item(got, full=True)


def test_a_spec_draft_gets_its_tag_in_the_first_reply_and_no_meeting_in_the_body(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store, idea="What if Acme was truly AI-native?", product="", fmt="spec-product", facts=("Acme is another company's product",), tags=["@acme_founder"])
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    bad = dict(GOOD, body="What if Acme was truly AI-native? Let's meet and talk.", first_comment="Would you ship this?")
    ok = dict(GOOD, body="What if Acme was truly AI-native? The prototype shows it, unofficial.", first_comment="Would you ship this in Acme?")
    monkeypatch.setattr(growth, "call_model", fake_model([bad, ok]))
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "review" and got["first_comment"] == "@acme_founder Would you ship this in Acme?" and "@" not in got["body"]


def test_a_research_draft_about_an_unregistered_product_carries_the_form_link(env, monkeypatch):
    store, cfg = make(channels=("x-en",), extra='research_form = "https://forms.example.com/research"')
    master(store, idea="How do founders collect early feedback?", product="", fmt="research-note",
           facts=("How do founders collect early feedback?", "the product may not exist yet; this is research before building"))
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    bad = dict(GOOD, body="Zorbix launched. Founders collect feedback in 5 ways.", hook="Zorbix launched.")
    ok = dict(GOOD, body="I am researching how founders collect early feedback. Join the research.", hook="I am researching early feedback.",
              first_comment="Five questions, two minutes.")
    monkeypatch.setattr(growth, "call_model", fake_model([bad, ok]))
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "review" and got["first_comment"] == "Five questions, two minutes. https://forms.example.com/research?ref=x"
    assert "Zorbix" not in got["body"]


def test_a_draft_that_mentions_hiring_is_blocked(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store, idea="Case: a bakery", product="", fmt="case-study", facts=("a bakery cut ordering time from 40 to 9 minutes",))
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    monkeypatch.setattr(growth, "call_model", fake_model([dict(GOOD, body="A bakery cut ordering time from 40 to 9 minutes. Tell me about your team. Hire me.")]))
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "failed" and "hiring" in got["fail_reason"]


def test_a_prediction_stores_its_dated_claim_when_published(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store, idea="Voice starts agents by 2027", product="", fmt="prediction", facts=("Voice starts agents by mid 2027",))
    (it,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    reply = dict(GOOD, body="Voice starts coding agents by mid 2027.", hook="Voice starts coding agents by mid 2027.",
                 claim="By 2027-06-30, most coding agent sessions start by voice.")
    monkeypatch.setattr(growth, "call_model", fake_model([reply]))
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert got["status"] == "review" and got["claim"].startswith("By 2027-06-30") and got["cta"]["kind"] == "follow"
    growth.approve(store, it["id"], NOW)
    growth.mark_published(store, it["id"], "https://x.com/me/status/1234567890", NOW)
    rows = [r for r in store.ledger() if r["ev"] == "prediction"]
    assert len(rows) == 1 and rows[0]["claim"].startswith("By 2027-06-30") and rows[0]["day"] == DAY and rows[0]["url"].endswith("1234567890")


def test_week_results_may_use_only_the_gathered_counts():
    facts = ["Counts gathered by Teyla for the week 2026-11-02 to 2026-11-08: ... No other number exists.",
             "merged pull requests in the week: 2", "content items published in the week: 5", "calls and meetings the owner logged in the week: 0"]
    it = dict(format="week-results", cta=dict(kind="follow"), facts=facts, first_comment="")
    assert not F.findings(it, "2 merged pull requests, 5 items published, 0 calls last week.")
    assert [f["rule"] for f in F.findings(it, "9 merged pull requests last week.")] == ["week-number"]
    assert [f["rule"] for f in F.findings(it, "Nov 2 to 8: 2 merged pull requests.")] == ["week-number"]
    assert not F.findings(it, "Week of 2026-11-02: 2 merged pull requests.")                  # an ISO date is not a count


def test_an_empty_early_products_list_means_no_early_access_link(env):
    cfg = make(public=("alpha",))[1]
    cfg["early_products"] = []
    assert F.resolve(item("wow-use-case", "alpha"), cfg)["link"] == ""


def test_the_research_claim_check_reads_the_first_comment_too():
    it = dict(format="research-note", product="", first_comment="Zorbix launched today, try it.", cta=dict(kind="research"))
    assert [f["rule"] for f in F.findings(it, "I am researching early feedback.")] == ["research-claim"]


def test_an_api_publish_also_stores_the_prediction_claim(env):
    from teyla import growth_publish
    store, _ = make(channels=("x-en",))
    it = master(store, idea="x", product="", fmt="prediction", facts=("x",))
    it.update(claim="By 2027-06-30 voice wins.", status="approved")
    growth.log_prediction(store, it, NOW, "https://example.com/p/1")
    growth.log_prediction(store, dict(it, format="worklog"), NOW, "https://example.com/p/2")
    assert [r["url"] for r in store.ledger() if r["ev"] == "prediction"] == ["https://example.com/p/1"]
    assert "log_prediction" in __import__("inspect").getsource(growth_publish)
