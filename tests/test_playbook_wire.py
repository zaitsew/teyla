"""Playbook cards wired into the lanes that write: `copy brief` and `growth draft` (PLAN P7)."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import cli, growth, playbook as pb
import test_copy_lane as tcl
import test_growth as tg
from test_copy_lane import repo  # noqa: F401  (fixture)
from test_growth import env  # noqa: F401  (fixture)

PROBLEM = {"product": "recipes", "text": "New users see a blank list.", "pointer": "intent recipes 2026-11-25"}
EVIDENCE = [{"product": "Example", "url": "https://example.com/a", "seen": "2026-11-20",
             "what": "The empty list shows one button.", "observed": True, "media": None}]


def live(card_id, domain, surface, **over):
    m = {"id": card_id, "domain": domain, "kind": "pattern", "status": "candidate", "job": "start a first plan",
         "surface": surface, "platform": "ios", "mechanism": "An empty state names the one next step as a verb button.",
         "refuse": "The illustration style.", "evidence": EVIDENCE, "added_by": "claude", "created": "2026-11-20",
         "problem": PROBLEM, "severity": 2, "confidence": "medium"}
    m.update(over)
    return m


def put(root: pathlib.Path, meta: dict) -> None:
    p = root / "cards" / meta["domain"] / f"{meta['id']}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pb.dump_card(meta, "Why it works."), encoding="utf-8")


@pytest.fixture
def library(tmp_path, monkeypatch):
    r = tmp_path / "library"
    monkeypatch.setenv("TEYLA_PLAYBOOK_ROOT", str(r))
    return r


def hook(card_id="demand-before-after-hook", surface="worklog"):
    return live(card_id, "demand", surface, kind="hook", line="Before: five tabs. After: one.", format="x-post",
                promise="one screen instead of five", proof="a screen recording", cta="try it")


# --- copy brief ----------------------------------------------------------------------------------------

def test_copy_brief_has_a_patterns_section_with_the_matching_cards(repo, library, capsys):
    put(library, live("flow-empty-next-step", "flow", "recipe.list"))
    put(library, live("visual-unrelated", "visual", "recipe.list"))          # not a copy domain
    code, out, err = tcl.run(["brief", str(repo), "recipe.list"], capsys)
    assert code == 0, err
    section = out.split("## Patterns", 1)[1].split("## Rules and budgets", 1)[0]
    assert "[flow-empty-next-step]" in section and "visual-unrelated" not in section
    assert "name the card ids you used" in section and "none fit" in section
    assert tcl.cl.parse_spec(out)["patterns"]["ids"] == ["flow-empty-next-step"]


def test_copy_brief_says_none_fit_with_an_empty_library(repo, library, capsys):
    out = tcl.run(["brief", str(repo), "recipe.list"], capsys)[1]
    assert "## Patterns\nPatterns: none fit\n" in out
    assert tcl.cl.parse_spec(out)["patterns"]["ids"] == []


def test_copy_brief_caps_the_patterns_at_five_cards(repo, library, capsys):
    for n in range(8):
        put(library, live(f"writing-card-{n}", "writing", "recipe.list"))
    assert len(tcl.cl.parse_spec(tcl.run(["brief", str(repo), "recipe.list"], capsys)[1])["patterns"]["ids"]) == 5


# --- growth draft --------------------------------------------------------------------------------------

def draft(env, monkeypatch, reply):
    store, cfg = tg.make(channels=("x-en",))
    (it,) = tg.planned(store, cfg)
    fm = tg.fake_model([reply])
    monkeypatch.setattr(growth, "call_model", fm)
    growth.run_draft(store, cfg, tg.NOW, limit=5, day=None, dry=False)
    return growth.Store().get(it["id"]), fm


def test_a_draft_gets_the_demand_cards_and_stores_the_ids_it_cites(env, library, monkeypatch):
    put(library, hook())
    put(library, live("flow-not-demand", "flow", "worklog"))
    got, fm = draft(env, monkeypatch, dict(tg.GOOD, cards_used=["demand-before-after-hook", "invented-card"]))
    pb_payload = fm.calls[0]["payload"]["playbook"]
    assert pb_payload["ids"] == ["demand-before-after-hook"] and "Before: five tabs" in pb_payload["cards"]
    assert got["status"] == "review" and got["playbook_cards"] == ["demand-before-after-hook"]


def test_a_draft_without_a_fitting_card_stores_none_fit(env, library, monkeypatch):
    got, fm = draft(env, monkeypatch, dict(tg.GOOD, cards_used="none fit"))
    assert fm.calls[0]["payload"]["playbook"] == {"ids": [], "cards": "none fit"}
    assert got["playbook_cards"] == ["none fit"]


def test_a_model_that_cites_nothing_is_stored_as_none_fit(env, library, monkeypatch):
    put(library, hook())
    got, _ = draft(env, monkeypatch, tg.GOOD)
    assert got["playbook_cards"] == ["none fit"]


def test_an_old_item_without_the_field_still_loads(env):
    store, cfg = tg.make(channels=("x-en",))
    it = tg.master(store)
    assert "playbook_cards" not in growth.Store().get(it["id"])
    assert growth.render_item(growth.Store().get(it["id"]), full=True)


def test_copy_write_payload_carries_the_patterns(repo, library, capsys):
    put(library, live("flow-empty-next-step", "flow", "recipe.list"))
    spec = tcl.cl.parse_spec(tcl.run(["brief", str(repo), "recipe.list"], capsys)[1])
    payload = tcl.cl.language_payload(spec, "en")
    assert "[flow-empty-next-step]" in payload["patterns"]["cards"] and "refuse" in payload["patterns"]["note"]
    spec["patterns"] = {"ids": [], "text": ""}
    assert "patterns" not in tcl.cl.language_payload(spec, "en")
