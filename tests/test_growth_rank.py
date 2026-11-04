"""The planner ranks by what the editor passes (docs/GROWTH.md, "The planner"). Fakes only: the model and gh are replaced
by the fixtures of test_growth; nothing is published or sent."""
from __future__ import annotations

import pytest

from teyla import growth, growth_quality as q, growth_rank as rank
from test_growth import DAY, GOOD, NOW, PASS, WEAK, env, fake_model, make, master  # noqa: F401

STORY_IDEA = "97 reviews took 23% of my weekly limit; `codex-review` sends only the diff: median 169k tokens"
THIN_CRITIQUE = "Product description only. Facts are too thin: no number, no link."


def story(store, idea=STORY_IDEA, product="alpha", **kw):
    return master(store, idea=idea, product=product, fmt="lesson", facts=(idea,), sources=[dict(kind="note", ref="note:n1", url="")], **kw)


def spotlight(store, product="alpha", **kw):
    return master(store, idea=f"Product spotlight: {product}", product=product, fmt="product-spotlight",
                  facts=(f"{product}: Counts your steps on a watch",), sources=[dict(kind="evergreen", ref=f"spotlight:{product}:1", url="")], **kw)


def test_story_class_needs_a_number_and_an_artifact(env):
    store, _ = make()
    assert rank.story_class(story(store)) == "story"
    assert rank.story_class(master(store, idea="Rules beat memory", fmt="lesson", facts=("Rules beat memory",))) == "lesson"
    assert rank.story_class(master(store, idea="23 hours lost", fmt="lesson", facts=("23 hours lost",))) == "lesson-partial"
    assert rank.story_class(master(store, idea="x", fmt="worklog")) == "worklog"
    assert rank.story_class(master(store, idea="Saved 3 calls", fmt="lesson", facts=("Saved 3 calls with `codex-review`",))) == "story"


def test_the_editors_verdict_counts_even_after_an_edit_changed_the_status(env):
    store, _ = make()
    it = growth.make_item(store, NOW, kind="post", format="lesson", idea="x", platform="x", language="en", day=DAY, channel="x-en",
                          sources=[dict(kind="note", ref="n:1", url="")], editor=dict(score=2.0, parts=dict(hook=2)))
    it["status"] = "review"                    # the owner edited an editor-held draft: hold_reason is gone, the score is not
    assert rank.outcome(it) is False
    it["editor"] = dict(score=4.0, parts=dict(hook=4))
    it["status"] = "rejected"                  # the owner rejected a draft the editor liked: still a pass for the editor
    assert rank.outcome(it) is True


def test_a_story_goes_before_a_spotlight_and_a_worklog(env):
    store, cfg = make(channels=("x-en",))
    spotlight_ = master(store, idea="Product spotlight: Alpha", fmt="product-spotlight", score=(5, 5, 5, 5),
                        facts=("Alpha: Counts steps", "Alpha ran 3 builds"), sources=[dict(kind="evergreen", ref="s:1", url="")])
    worklog = master(store, idea="Merged in Alpha: faster sync", fmt="worklog", score=(5, 5, 5, 5), product="beta")
    s = story(store, score=(2, 2, 2, 2))
    rows = growth.plan(store, cfg, DAY, NOW)
    assert rows[0]["item"]["parent"] == s["id"]
    assert spotlight_["id"] and worklog["id"]


def test_the_editors_history_moves_a_source_and_format_down_and_up(env):
    store, cfg = make(channels=("x-en",))
    for n in range(6):                                                  # six worklogs from PRs, all held
        held = growth.make_item(store, NOW, kind="post", format="worklog", idea=f"w{n}", platform="x", language="en", day="2026-11-03",
                                channel="x-en", sources=[dict(kind="pr", ref=f"pr:o/a#{n}", url="")], editor=dict(score=1.8))
        held["status"], held["hold_reason"] = "draft", "editor 1.8/5"
        held["editor"] = dict(score=1.8, parts=dict(hook=1, artifact=2, number_or_surprise=2, checkable=2))
        store.save(held, NOW)
    hist = rank.history(store)
    assert hist[("pr", "worklog")] == (0, 6)
    pr = master(store, idea="Merged in Alpha: x", fmt="worklog", sources=[dict(kind="pr", ref="pr:o/a#99", url="")])
    other = master(store, idea="Merged in Alpha: y", fmt="worklog", sources=[dict(kind="release", ref="r:1", url="")])
    assert rank.quality(pr, hist) < rank.quality(other, hist) < rank.PRIOR["lesson"] + 0.01
    passed = growth.make_item(store, NOW, kind="post", format="worklog", idea="ok", platform="x", language="en", day="2026-11-03",
                              channel="x-en", sources=[dict(kind="release", ref="r:0", url="")], editor=dict(score=4.0, parts=dict(hook=4)))
    passed["status"] = "review"
    store.save(passed, NOW)
    assert rank.quality(other, rank.history(store)) > rank.PRIOR["worklog"]


def test_a_bare_product_summary_never_takes_a_slot(env):
    store, cfg = make(channels=("x-en",))
    spotlight(store)
    rows = growth.plan(store, cfg, DAY, NOW)
    assert rows[0]["item"] is None and growth.queue_days(store, cfg) == 0


def test_a_bare_summary_fails_before_a_model_call(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    m = spotlight(store)
    item = growth.make_item(store, NOW, kind="post", format="product-spotlight", idea=m["idea"], platform="x", language="en", product="alpha",
                            facts=m["facts"], sources=m["sources"], day=DAY, channel="x-en", parent=m["id"])
    store.save(item, NOW)
    fm = fake_model([GOOD])
    monkeypatch.setattr(growth, "call_model", fm)
    res = growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(item["id"])
    assert got["status"] == "failed" and got["fail_reason"].startswith("thin: a bare product summary")
    assert not fm.calls and not fm.editor_calls and res["cost"] == 0.0 and res["budget_left"] == cfg["draft_budget"]
    assert growth.Store().get(m["id"])["thin_facts"]


def test_a_spotlight_with_a_demo_fact_is_not_bare(env):
    store, _ = make()
    m = spotlight(store)
    m["facts"].append("A watch sync went from 9 steps to 3")
    assert rank.thin_reason(m) == ""


def test_thin_facts_skip_the_rewrite_and_the_next_channel(env, monkeypatch):
    store, cfg = make(channels=("x-en", "linkedin-en"))
    m = master(store, idea="Merged in Alpha: tweak", fmt="worklog")
    rows = growth.plan(store, cfg, DAY, NOW)
    fm = fake_model([GOOD], editor=[dict(WEAK, critique=THIN_CRITIQUE)])
    monkeypatch.setattr(growth, "call_model", fm)
    res = growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    states = {r["id"]: r for r in res["rows"]}
    first, second = (r["id"] for r in res["rows"])                                # drafted in channel order
    assert {first, second} == {r["item"]["id"] for r in rows}
    assert states[first]["state"] == "draft" and "too thin to rewrite" in states[first]["reason"]
    assert len(fm.calls) == 1 and len(fm.editor_calls) == 1                     # one draft, one editor call, no rewrite
    assert states[second]["state"] == "failed" and states[second]["reason"].startswith("thin:")
    assert growth.Store().get(m["id"])["thin_facts"]
    assert growth.available_masters(growth.Store(), cfg) == []


def test_a_weak_draft_that_is_not_thin_still_gets_its_rewrite(env, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store, idea="Merged in Alpha: tweak", fmt="worklog")
    growth.plan(store, cfg, DAY, NOW)
    fm = fake_model([GOOD, GOOD], editor=[dict(WEAK, critique="Lead with the diff stat."), PASS])
    monkeypatch.setattr(growth, "call_model", fm)
    growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    assert len(fm.calls) == 2 and len(fm.editor_calls) == 2


def test_retry_clears_the_thin_mark(env):
    store, cfg = make(channels=("x-en",))
    m = master(store)
    (row,) = growth.plan(store, cfg, DAY, NOW)
    it = row["item"]
    rank.mark_thin(store, it, "facts too thin", NOW)
    it["status"], it["fail_reason"] = "failed", "thin: facts too thin"
    store.save(it, NOW)
    growth.retry(store, it["id"], NOW)
    assert not store.get(it["id"]).get("thin_facts") and not store.get(m["id"]).get("thin_facts")


def test_a_product_with_no_attempts_gets_its_bonus_only_with_an_idea_that_can_pass(env):
    store, cfg = make(channels=("x-en",))
    store.log("attempt", NOW, product="alpha", kind="ad")
    a = story(store, product="alpha")
    b = master(store, idea="Merged in Beta: x", product="beta", fmt="worklog", score=(5, 5, 5, 5))
    rows = growth.plan(store, cfg, DAY, NOW)
    assert rows[0]["item"]["parent"] == a["id"]          # a story of a product with an attempt beats a weaker idea of a new one
    assert b["id"]


def test_unused_stories_are_counted_and_shown(env, capsys):
    store, cfg = make(channels=("x-en",))
    story(store)
    story(store, idea="Second: 12 sign-ins a week, `teyla you` counts them")
    master(store, idea="Merged in Alpha: x", fmt="worklog")
    assert rank.unused_stories(store, cfg) == 2
    growth.plan(store, cfg, DAY, NOW)
    assert rank.unused_stories(store, cfg) == 2          # fanout 3: a story stays available after one assignment
    text = growth.render_plan(growth.plan(store, cfg, DAY, NOW), DAY, None, 2)
    assert "2 unused stories" in text
