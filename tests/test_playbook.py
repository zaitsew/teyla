"""teyla playbook: the card schema by stage, the front-matter reader, expiry, brief and the commands.
Everything is a fixture under a tmp root; nothing touches the network."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib

import pytest

from teyla import cli, playbook as pb

TODAY = dt.date(2026, 11, 28)

CONTRACT_CARD = """---
id: ai-preview-before-save
domain: ai            # interaction | flow | ai
kind: pattern         # pattern | hook
status: seen
job: turn a messy booking into a plan
surface: import sheet
platform: ios
mechanism: Show the parsed result as an editable preview and save only after the person confirms.
refuse: Example app's colour, icons and wording.
evidence:
  - product: Example
    url: https://example.com/updates
    seen: 2026-11-28
    what: Release notes describe a review step before imported reservations are saved.
    observed: true          # seen in the source
    media: null
added_by: codex
created: 2026-11-28
---
A preview lets the person fix a wrong parse before it costs anything. Do not use it when the import is exact.
"""

SEEN = {
    "id": "flow-empty-state-next-step", "domain": "flow", "kind": "pattern", "status": "seen",
    "job": "start a first plan", "surface": "empty state", "platform": "ios",
    "mechanism": "An empty state names the one next step as a verb button.",
    "refuse": "The illustration style.",
    "evidence": [{"product": "Example", "url": "https://example.com/a", "seen": "2026-11-20",
                  "what": "The empty list shows one button.", "observed": True, "media": None}],
    "added_by": "claude", "created": "2026-11-20",
}
PROBLEM = {"product": "myapp", "text": "New users see a blank list.", "pointer": "intent myapp 2026-11-25"}
TRIAL = {"hypothesis": "A next-step button lifts first plans.", "metric": "first plan rate", "baseline": "31%",
         "threshold": "35%", "direction": "up", "window_days": 14, "guardrails": "crash rate flat",
         "review_by": "2026-12-20", "variants": ["design/a.png", "design/b.png"], "approved": "2026-11-28"}
VERDICT = {"result": "adopted", "numbers": "31% to 38%", "date": "2026-12-20", "pr": "https://example.com/pr/1"}


def card(**over) -> dict:
    m = copy.deepcopy(SEEN)
    m.update(over)
    return m


def candidate(**over):
    return card(**{**dict(status="candidate", problem=PROBLEM, severity=2, confidence="medium"), **over})


def trial(**over):
    return candidate(**{**dict(status="trial", trial=TRIAL), **over})


def closed(**over):
    return trial(**{**dict(status="adopted", verdict=VERDICT), **over})


def put(root: pathlib.Path, meta: dict, body: str = "Why it works.") -> pathlib.Path:
    p = root / "cards" / meta["domain"] / f"{meta['id']}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pb.dump_card(meta, body), encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "playbook"
    monkeypatch.setenv("TEYLA_PLAYBOOK_ROOT", str(r))
    monkeypatch.setattr(pb, "today", lambda: TODAY)
    return r


def run(capsys, *argv) -> tuple[int, str, str]:
    code = cli.main(["playbook", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# --- the reader and the writer ---------------------------------------------------------------------------

def test_the_contract_card_reads_and_validates(tmp_path):
    p = tmp_path / "cards" / "ai" / "ai-preview-before-save.md"
    p.parent.mkdir(parents=True)
    p.write_text(CONTRACT_CARD)
    c = pb.read_card(p)
    assert c.meta["evidence"][0]["observed"] is True and c.meta["evidence"][0]["media"] is None
    assert c.meta["created"] == "2026-11-28"
    assert c.problems() == []


def test_dump_and_parse_round_trip_every_stage():
    for meta in (card(), candidate(), trial(), closed()):
        text = pb.dump_card(meta, "Body.")
        back, body = pb.split_card(text)
        assert back == meta and body == "Body."


def test_awkward_strings_survive_a_round_trip():
    meta = card(mechanism='Say "yes": then # go, [now]', refuse="null", job="2026")
    back, _ = pb.split_card(pb.dump_card(meta, ""))
    assert back["mechanism"] == meta["mechanism"] and back["refuse"] == "null" and back["job"] == "2026"


def test_flow_lists_and_json_parse():
    assert pb.parse_yaml("a: [x, 'y z', 3]\nb: {k: v}\n") == {"a": ["x", "y z", 3], "b": {"k": "v"}}
    with pytest.raises(pb.CardError):
        pb.parse_yaml("a: |\n  text\n")


# --- stages --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("meta", [card(), candidate(), trial(), closed(), closed(status="rejected", verdict={**VERDICT, "result": "rejected"})])
def test_a_card_of_every_stage_is_valid(meta):
    assert pb.validate(meta) == []


def test_a_parked_card_needs_a_trigger():
    meta = closed(status="parked", verdict={**VERDICT, "result": "parked"})
    assert any("trigger" in p for p in pb.validate(meta))
    meta["verdict"]["trigger"] = "2027-02-01: when the paywall ships"
    assert pb.validate(meta) == []


@pytest.mark.parametrize("field,value", [("trial", TRIAL), ("verdict", VERDICT), ("problem", PROBLEM), ("severity", 2)])
def test_a_seen_card_refuses_later_stage_fields(field, value):
    problems = pb.validate(card(**{field: value}))
    assert any(field in p and "not allowed" in p for p in problems), problems


def test_a_seen_card_with_a_baseline_fails_check(root, capsys):
    put(root, card(trial=TRIAL))
    code, out, _ = run(capsys, "check")
    assert code == 1 and "trial" in out and "not allowed at this stage" in out


def test_a_candidate_needs_its_problem_and_may_not_carry_a_trial():
    m = candidate()
    del m["problem"]
    assert any("missing `problem`" in p for p in pb.validate(m))
    assert any("trial" in p for p in pb.validate(candidate(trial=TRIAL)))


def test_a_trial_needs_two_variants_and_all_fields():
    bad = copy.deepcopy(TRIAL)
    bad["variants"] = ["only-one.png"]
    del bad["baseline"]
    problems = pb.validate(trial(trial=bad))
    assert any("variants" in p for p in problems) and any("baseline" in p for p in problems)


def test_a_pattern_has_no_hook_fields_and_a_hook_needs_them():
    assert any("line" in p for p in pb.validate(card(line="x")))
    assert any("missing `line`" in p for p in pb.validate(card(kind="hook")))
    hook = card(kind="hook", line="Plan the trip in one paste", format="reel-7s", promise="a plan", proof="demo", cta="Try it")
    assert pb.validate(hook) == []


def test_evidence_media_must_be_absolute_and_outside_a_repo(tmp_path):
    ev = lambda m: [{**SEEN["evidence"][0], "media": m}]
    assert any("absolute" in p for p in pb.validate(card(evidence=ev("shots/a.png"))))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert any("outside any git repo" in p for p in pb.validate(card(evidence=ev(str(repo / "a.png")))))
    assert pb.validate(card(evidence=ev(str(tmp_path / "media" / "a.png")))) == []


def test_unknown_observation_is_valid_and_a_guess_is_not():
    ev = lambda o: [{**SEEN["evidence"][0], "observed": o}]
    assert pb.validate(card(evidence=ev("unknown"))) == []
    assert pb.validate(card(evidence=ev("maybe")))


# --- check ---------------------------------------------------------------------------------------------

def test_check_passes_a_clean_root_and_catches_duplicates_and_long_bodies(root, capsys):
    put(root, card())
    put(root, candidate(id="flow-second", surface="list"))
    assert run(capsys, "check")[0] == 0
    dup = put(root, card())
    other = root / "cards" / "flow" / "flow-copy.md"
    other.write_text(dup.read_text())
    code, out, _ = run(capsys, "check")
    assert code == 1 and "file name `flow-copy.md`" in out and "also in" in out
    other.unlink()
    put(root, card(id="flow-wordy", surface="x"), body="word " * 151)
    code, out, _ = run(capsys, "check")
    assert code == 1 and "151 words" in out


def test_check_names_an_unreadable_card(root, capsys):
    p = root / "cards" / "flow" / "flow-broken.md"
    p.parent.mkdir(parents=True)
    p.write_text("no front matter")
    code, out, _ = run(capsys, "check")
    assert code == 1 and "no front matter" in out


# --- expiry --------------------------------------------------------------------------------------------

def test_expiry_flips_a_31_day_candidate_and_leaves_a_30_day_one(root, capsys):
    put(root, candidate(id="flow-old", created=(TODAY - dt.timedelta(days=31)).isoformat()))
    put(root, candidate(id="flow-fresh", created=(TODAY - dt.timedelta(days=30)).isoformat()))
    put(root, card(id="flow-stale-seen", created=(TODAY - dt.timedelta(days=91)).isoformat()))
    put(root, card(id="flow-young-seen", created=(TODAY - dt.timedelta(days=89)).isoformat()))
    code, out, _ = run(capsys, "expire")
    assert code == 0 and "flow-old" in out and "flow-stale-seen" in out and "flow-fresh" not in out
    assert pb.read_card(root / "cards/flow/flow-old.md").status == "candidate"        # dry: nothing written
    run(capsys, "expire", "--apply")
    assert pb.read_card(root / "cards/flow/flow-old.md").status == "expired"
    assert pb.read_card(root / "cards/flow/flow-stale-seen.md").status == "expired"
    assert pb.read_card(root / "cards/flow/flow-fresh.md").status == "candidate"
    assert run(capsys, "check")[0] == 0                                                 # an expired card is still valid


# --- brief ---------------------------------------------------------------------------------------------

def test_brief_returns_only_live_stages_and_says_none_fit(root, capsys):
    put(root, card(id="flow-only-seen", surface="import sheet"))
    code, out, _ = run(capsys, "brief", "--product", "myapp", "--surface", "import sheet")
    assert code == 0 and out.strip() == "none fit"
    put(root, candidate(id="flow-live", surface="import sheet"))
    out = run(capsys, "brief", "--product", "myapp", "--surface", "import sheet")[1]
    assert "flow-live" in out and "flow-only-seen" not in out
    assert run(capsys, "brief", "--product", "myapp", "--surface", "paywall screen")[1].strip() == "none fit"


def test_brief_on_a_missing_root_says_none_fit(root, capsys):
    assert run(capsys, "brief", "--product", "p", "--surface", "s")[1].strip() == "none fit"


def test_brief_caps_at_five_cards(root, capsys):
    for i in range(8):
        put(root, candidate(id=f"flow-card-{i}", surface="import sheet"))
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--json")[1])
    assert len(out["ids"]) == 5 and not out["none_fit"]
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--max", "50", "--json")[1])
    assert len(out["ids"]) == 5


def test_brief_caps_at_the_token_budget(root, capsys):
    for i in range(5):
        put(root, candidate(id=f"flow-long-{i}", surface="import sheet", mechanism="Show the preview. " * 80))
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--json")[1])
    assert 0 < len(out["ids"]) < 5 and out["tokens"] <= 1500
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--tokens", "40", "--json")[1])
    assert out["none_fit"]


def test_brief_ranks_exact_tags_first_and_filters_by_domain(root, capsys):
    put(root, candidate(id="flow-exact", surface="import sheet"))
    put(root, candidate(id="visual-near", domain="visual", surface="import preview sheet layout"))
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--json")[1])
    assert out["ids"][0] == "flow-exact" and "visual-near" in out["ids"]
    out = json.loads(run(capsys, "brief", "--product", "myapp", "--surface", "import sheet", "--domain", "visual", "--json")[1])
    assert out["ids"] == ["visual-near"]


# --- add, list, show, set ------------------------------------------------------------------------------

ADD = ["add", "--domain", "flow", "--job", "start a first plan", "--surface", "empty state",
       "--mechanism", "An empty state names one next step.", "--refuse", "The artwork.",
       "--evidence-product", "Example", "--evidence-url", "https://example.com/a", "--evidence-what", "One button shown."]


def test_add_scaffolds_a_valid_seen_card_and_refuses_a_second(root, capsys):
    code, out, _ = run(capsys, *ADD)
    assert code == 0
    path = pathlib.Path(out.strip())
    assert path == root / "cards/flow/flow-start-a-first-plan.md"
    c = pb.read_card(path)
    assert c.status == "seen" and c.problems() == [] and c.meta["created"] == "2026-11-28"
    assert run(capsys, *ADD)[0] == 1
    assert not list(root.glob("*.json")) and not list(root.glob("index*"))


def test_add_refuses_a_card_that_fails_check(root, capsys):
    code, _, err = run(capsys, *ADD, "--job", "one two three four five six seven eight nine")
    assert code == 1 and "words" in err and not (root / "cards").exists()


def test_list_filters_and_json(root, capsys):
    put(root, card())
    put(root, candidate(id="ai-voice-turn", domain="ai", surface="voice"))
    assert "flow-empty-state-next-step" in run(capsys, "list")[1] and "ai-voice-turn" in run(capsys, "list")[1]
    out = run(capsys, "list", "--status", "candidate")[1]
    assert "ai-voice-turn" in out and "flow-empty" not in out
    rows = json.loads(run(capsys, "list", "--product", "myapp", "--json")[1])["cards"]
    assert [r["id"] for r in rows] == ["ai-voice-turn"]
    assert [r["id"] for r in json.loads(run(capsys, "list", "--domain", "flow", "--kind", "pattern", "--json")[1])["cards"]] == ["flow-empty-state-next-step"]
    assert "no cards" in run(capsys, "list", "--domain", "demand")[1]


def test_show_prints_the_file_by_prefix(root, capsys):
    put(root, card())
    code, out, _ = run(capsys, "show", "flow-empty")
    assert code == 0 and "id: flow-empty-state-next-step" in out
    assert run(capsys, "show", "nope")[0] == 1


def test_set_walks_the_stages_and_checks_each(root, capsys, tmp_path):
    put(root, card())
    cid = "flow-empty-state-next-step"
    code, _, err = run(capsys, "set", cid, "status=candidate")
    assert code == 1 and "problem" in err                                 # no problem yet
    f = tmp_path / "cand.yaml"
    f.write_text("problem:\n  product: myapp\n  text: New users see a blank list.\n  pointer: intent myapp 2026-11-25\nseverity: 2\nconfidence: medium\n")
    assert run(capsys, "set", cid, "status=candidate", "--from", str(f))[0] == 0
    assert pb.read_card(root / f"cards/flow/{cid}.md").meta["updated"] == "2026-11-28"
    assert run(capsys, "set", cid, "status=adopted")[0] == 1               # skips the trial
    t = tmp_path / "trial.json"
    t.write_text(json.dumps({"trial": TRIAL}))
    assert run(capsys, "set", cid, "status=trial", "--from", str(t))[0] == 0
    v = tmp_path / "verdict.yaml"
    v.write_text("verdict:\n  result: adopted\n  numbers: 31% to 38%\n  date: 2026-12-20\n  pr: null\n")
    assert run(capsys, "set", cid, "status=adopted", "--from", str(v))[0] == 0
    assert pb.read_card(root / f"cards/flow/{cid}.md").problems() == []
    assert run(capsys, "check")[0] == 0


def test_set_refuses_a_baseline_on_a_seen_card_and_a_changed_id(root, capsys, tmp_path):
    put(root, card())
    t = tmp_path / "t.json"
    t.write_text(json.dumps({"trial": TRIAL}))
    code, _, err = run(capsys, "set", "flow-empty-state-next-step", "--from", str(t))
    assert code == 1 and "not allowed" in err
    t.write_text(json.dumps({"id": "flow-other"}))
    assert run(capsys, "set", "flow-empty-state-next-step", "--from", str(t))[0] == 1
    assert run(capsys, "set", "flow-empty-state-next-step", "severity=2")[0] == 1


def test_the_default_root_is_the_config_value(monkeypatch, tmp_path):
    monkeypatch.delenv("TEYLA_PLAYBOOK_ROOT", raising=False)
    assert str(pb.root()).endswith("ops/playbook")
