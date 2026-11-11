"""teyla design: the map, the dossier gate, the options gate, pick, built, next, and the card in asks/answer.
Every repo is a tmp dir with generic content; TEYLA_HOME is a tmp dir (tests/conftest.py)."""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from teyla import answer, asks, cli, design_cycle as dc, taste

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "templates" / "design" / "decisions"
SENTENCE = "Three tabs, because I open Today ten times a day."


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "planner"
    shutil.copytree(SAMPLES, r / "design" / "decisions")
    (r / "design" / "decisions" / "jobs" / "pick.yaml").unlink()          # the sample's first decision, unpicked
    m = taste.load_file(dc.map_path(r))
    m["decisions"][0]["status"] = "open"
    m["decisions"][1]["status"] = "researching"
    dc.save_map(r, m["decisions"])
    return r


def write_map(repo, rows):
    dc.save_map(repo, rows)


def run(args, capsys):
    code = cli.main(["design", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def make_options_valid(repo, did="bottom-bar"):
    assert dc.do_options(repo, did)           # the sample's options are valid


def prepare_jobs(repo):
    """Give `jobs` a dossier and options so it can be picked."""
    d = dc.folder(repo, "jobs")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(dc.folder(repo, "bottom-bar") / "dossier.md", d / "dossier.md")
    shutil.copy(dc.folder(repo, "bottom-bar") / "options.yaml", d / "options.yaml")


# --- the sample is valid ---------------------------------------------------------------------------

def test_the_sample_in_templates_passes_every_gate(repo):
    assert dc.map_problems(dc.valid_map(repo)) == []
    assert dc.dossier_problems((dc.folder(repo, "bottom-bar") / "dossier.md").read_text()) == []
    assert dc.options_problems(dc.load_options(repo, "bottom-bar")) == []


# --- the map ---------------------------------------------------------------------------------------

def test_map_scaffolds_then_validates(tmp_path, capsys):
    r = tmp_path / "fresh"
    r.mkdir()
    code, out, _ = run(["map", str(r)], capsys)
    assert code == 0 and "wrote" in out and dc.map_path(r).is_file()
    code, out, _ = run(["map", str(r)], capsys)
    assert code == 0 and "valid, 1 decision" in out


def test_map_cycle_is_refused(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["needs"] = ["bottom-bar"]
    write_map(repo, rows)
    code, _, err = run(["map", str(repo)], capsys)
    assert code == 1 and "cycle" in err


def test_map_unknown_needs_is_refused(repo, capsys):
    rows = dc.load_map(repo)
    rows[1]["needs"] = ["nowhere"]
    write_map(repo, rows)
    code, _, err = run(["status", str(repo)], capsys)
    assert code == 1 and "unknown decision 'nowhere'" in err


# --- next ------------------------------------------------------------------------------------------

def test_next_names_the_first_decision_whose_needs_are_done(repo, capsys):
    code, out, _ = run(["next", str(repo)], capsys)
    assert code == 0 and out.startswith("jobs:")
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    assert run(["next", str(repo)], capsys)[1].startswith("bottom-bar:")


def test_next_skips_a_decision_whose_needs_are_open(repo):
    rows = dc.load_map(repo)
    rows.insert(0, {"id": "late", "title": "Late", "journey": "j", "needs": ["bottom-bar"], "status": "open"})
    assert dc.next_decision(rows)["id"] == "jobs"
    rows[1]["status"] = "built"
    rows[2]["status"] = "picked"
    assert dc.next_decision(rows)["id"] == "late"


# --- the dossier gate ------------------------------------------------------------------------------

def test_options_refused_without_a_dossier(repo, capsys):
    code, _, err = run(["options", str(repo), "jobs"], capsys)
    assert code == 1 and "no dossier" in err


@pytest.mark.parametrize("part", dc.PARTS)
def test_options_refused_when_any_dossier_part_is_missing(repo, capsys, part):
    p = dc.folder(repo, "bottom-bar") / "dossier.md"
    text = p.read_text().replace(f"## {part}", "## Something else")
    p.write_text(text)
    (dc.folder(repo, "bottom-bar") / "options.yaml").unlink()
    code, _, err = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 1 and part in err


def test_options_refused_for_an_unlabelled_dossier_item(repo, capsys):
    p = dc.folder(repo, "bottom-bar") / "dossier.md"
    p.write_text(p.read_text().replace("- guideline: a tab bar", "- a tab bar"))
    code, _, err = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "no label" in err


def test_a_scaffolded_dossier_is_not_enough(repo, capsys):
    assert run(["dossier", str(repo), "jobs"], capsys)[0] == 0
    code, _, err = run(["options", str(repo), "jobs"], capsys)
    assert code == 1 and "Owner's words" in err
    assert dc.load_map(repo)[0]["status"] == "researching"


# --- the options gate ------------------------------------------------------------------------------

def test_a_fourth_option_is_refused(repo, capsys):
    data = dc.load_options(repo, "bottom-bar")
    for i in ("c", "d"):
        data["options"].append({**data["options"][1], "id": i})
    (dc.folder(repo, "bottom-bar") / "options.yaml").write_text(taste.dumps(data))
    code, _, err = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "4 options" in err


def test_an_unrecommended_first_option_is_refused(repo, capsys):
    data = dc.load_options(repo, "bottom-bar")
    data["options"][0]["recommended"] = False
    (dc.folder(repo, "bottom-bar") / "options.yaml").write_text(taste.dumps(data))
    code, _, err = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "recommended" in err


def test_a_recommended_second_option_is_refused(repo):
    data = dc.load_options(repo, "bottom-bar")
    data["options"][1]["recommended"] = True
    assert any("only the first" in p for p in dc.options_problems(data))


def test_valid_options_set_the_status_and_open_a_card(repo, capsys):
    code, out, _ = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 0 and "2 options valid" in out
    assert dc.load_map(repo)[1]["status"] == "options"
    assert [c["decision"] for c in dc.open_cards()] == ["bottom-bar"]


def test_options_scaffold_when_missing(repo, capsys):
    (dc.folder(repo, "bottom-bar") / "options.yaml").unlink()
    code, out, _ = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 0 and "wrote" in out
    code, _, err = run(["options", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "`why`" in err


# --- pick ------------------------------------------------------------------------------------------

def test_pick_refused_when_needs_are_not_picked(repo, capsys):
    code, _, err = run(["pick", str(repo), "bottom-bar", "three-tabs", "--sentence", SENTENCE], capsys)
    assert code == 1 and "needs jobs" in err
    assert not (dc.folder(repo, "bottom-bar") / "pick.yaml").exists()


def test_pick_refused_without_options(repo, capsys):
    code, _, err = run(["pick", str(repo), "jobs", "a", "--sentence", SENTENCE], capsys)
    assert code == 1 and "no options" in err


def test_pick_writes_the_record_the_status_and_a_proposal(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    code, out, _ = run(["pick", str(repo), "bottom-bar", "three-tabs", "--sentence", SENTENCE, "--scope", "product"], capsys)
    assert code == 0 and "picked three-tabs" in out
    pick = taste.load_file(dc.folder(repo, "bottom-bar") / "pick.yaml")
    assert pick["option"] == "three-tabs" and pick["sentence"] == SENTENCE and pick["scope"] == "product"
    assert dc.load_map(repo)[1]["status"] == "picked"
    props = [d for d in taste.load_decisions(repo) if d.get("source") == "design-cycle"]
    assert len(props) == 1 and props[0]["confirmed"] is False and props[0]["decision"] == "rule"
    assert props[0]["scope"] == "product" and "Three tabs" in props[0]["rule"]


def test_pick_never_confirms(repo):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    dc.do_pick(repo, "bottom-bar", "none", SENTENCE)
    assert taste.load_rules(repo) == []
    assert all(d.get("confirmed") is False for d in taste.load_decisions(repo))


def test_pick_refuses_an_overwrite_unless_superseded(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    args = ["pick", str(repo), "bottom-bar", "three-tabs", "--sentence", SENTENCE]
    assert run(args, capsys)[0] == 0
    code, _, err = run(["pick", str(repo), "bottom-bar", "five-tabs", "--sentence", "Actually five."], capsys)
    assert code == 1 and "--supersede" in err
    code, _, _ = run(["pick", str(repo), "bottom-bar", "five-tabs", "--sentence", "Actually five.", "--supersede"], capsys)
    assert code == 0
    pick = taste.load_file(dc.folder(repo, "bottom-bar") / "pick.yaml")
    assert pick["option"] == "five-tabs" and pick["supersedes"]["option"] == "three-tabs"


def test_pick_refuses_an_unknown_option_and_an_empty_sentence(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    assert "no option 'zzz'" in run(["pick", str(repo), "bottom-bar", "zzz", "--sentence", "x"], capsys)[2]
    assert "owner's words" in run(["pick", str(repo), "bottom-bar", "three-tabs", "--sentence", " "], capsys)[2]


# --- built -----------------------------------------------------------------------------------------

def test_built_refused_before_the_pick(repo, capsys):
    code, _, err = run(["built", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "not picked" in err
    assert dc.load_map(repo)[1]["status"] != "built"


def test_built_after_the_pick(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    run(["pick", str(repo), "bottom-bar", "three-tabs", "--sentence", SENTENCE], capsys)
    code, out, _ = run(["built", str(repo), "bottom-bar"], capsys)
    assert code == 0 and dc.load_map(repo)[1]["status"] == "built"
    assert "built" in run(["status", str(repo)], capsys)[1]


def test_built_refuses_a_none_pick(repo, capsys):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    run(["pick", str(repo), "bottom-bar", "none", "--sentence", "Leave it as it is."], capsys)
    code, _, err = run(["built", str(repo), "bottom-bar"], capsys)
    assert code == 1 and "none" in err


# --- the card in asks, and answer ------------------------------------------------------------------

@pytest.fixture
def card(repo, monkeypatch):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    dc.do_options(repo, "bottom-bar")
    monkeypatch.setattr(asks, "collect_claude", lambda *a, **k: [])
    monkeypatch.setattr(asks, "collect_codex", lambda *a, **k: [])
    monkeypatch.setattr(asks, "collect_gates", lambda: [])
    monkeypatch.setattr(asks, "collect_reminders", lambda *a, **k: [])
    return repo


def test_the_open_card_comes_first_in_asks_with_chips(card):
    other = asks.Ask(id="zzzzzzzz", kind="question", product="other", title="t", question="q?", context="", options=[],
                     when=1.0, archived=False, link="", pr="", harness="claude-code")
    items = asks.collect(now=asks._now(), st={"done": {}, "snoozed": {}, "undone": {}})
    assert [a.harness for a in items][0] == asks.DESIGN_HARNESS
    c = items[0]
    assert c.options == ["three-tabs (recommended)", "five-tabs", "none"] and c.kind == "question"
    groups = asks.group([other, c], reg={"product": {}})
    assert groups[0][1][0] is c


def test_answering_the_card_writes_pick_yaml(card):
    c = asks.collect(now=asks._now(), st={"done": {}, "snoozed": {}, "undone": {}})[0]
    res = answer.answer(c, "three-tabs (recommended) " + SENTENCE)
    assert res["ok"] and res["via"] == "design-pick"
    pick = taste.load_file(dc.folder(card, "bottom-bar") / "pick.yaml")
    assert pick["option"] == "three-tabs" and pick["sentence"] == SENTENCE
    assert dc.load_map(card)[1]["status"] == "picked"
    assert dc.open_cards() == []                                         # the card is gone


def test_a_bad_card_answer_writes_nothing(card):
    c = asks.collect(now=asks._now(), st={"done": {}, "snoozed": {}, "undone": {}})[0]
    res = answer.answer(c, "I like the second one best")
    assert not res["ok"] and "start the answer with one of" in res["detail"]
    assert not (dc.folder(card, "bottom-bar") / "pick.yaml").exists()


def test_a_card_for_a_decision_whose_needs_are_open_is_refused_at_answer(repo, monkeypatch):
    dc.do_options(repo, "bottom-bar")                                    # jobs is still open
    c = dc.open_cards()[0]
    assert c["waiting"] == ["jobs"]
    with pytest.raises(dc.DesignError, match="needs jobs"):
        dc.answer_card(f"{repo}::bottom-bar", "three-tabs because")


def test_the_json_row_of_a_card_is_a_plain_question(card):
    c = asks.collect(now=asks._now(), st={"done": {}, "snoozed": {}, "undone": {}})[0]
    row = c.to_dict(asks._now())
    json.dumps(row)
    assert row["options"][0].endswith("(recommended)") and "session" not in row


# --- review fixes (codex P2s on #482) --------------------------------------------------------------

def test_an_unquoted_numeric_option_id_is_refused(repo):
    p = dc.folder(repo, "bottom-bar") / "options.yaml"
    data = taste.load_file(p)
    data["options"][1]["id"] = 2
    p.write_text(taste.dumps(data))
    with pytest.raises(dc.DesignError) as e:
        dc.check_options(repo, "bottom-bar")
    assert "quoted string" in str(e.value)


def test_an_unreadable_pick_is_not_overwritten_without_supersede(repo):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    (dc.folder(repo, "bottom-bar") / "pick.yaml").write_text("{{{ unclosed\n")
    with pytest.raises(dc.DesignError) as e:
        dc.do_pick(repo, "bottom-bar", "three-tabs", SENTENCE)
    assert "cannot be read" in str(e.value)
    assert "unclosed" in (dc.folder(repo, "bottom-bar") / "pick.yaml").read_text()
    dc.do_pick(repo, "bottom-bar", "three-tabs", SENTENCE, supersede=True)


def test_scope_all_keeps_its_reach_through_confirm(repo):
    rows = dc.load_map(repo)
    rows[0]["status"] = "picked"
    write_map(repo, rows)
    dc.do_pick(repo, "bottom-bar", "three-tabs", SENTENCE, scope="all")
    prop = next(d for d in taste.load_decisions(repo) if d.get("source") == "design-cycle")
    res = taste.confirm(repo, prop["id"][:8])
    rule = taste.load_file(repo / res["rule_file"])
    assert rule["reach"] == "all-products"


# --- the card's 250-word limit ---------------------------------------------------------------------

def _rendered_words(repo, did="bottom-bar"):
    rows = dc.valid_map(repo)
    r = dc.row(rows, did)
    return dc.count_words(dc.card_text(dc.card_for(repo, rows, r, dc.load_options(repo, did))))


def _size_rendered_card(repo, words, did="bottom-bar"):
    """Make the card Teyla renders for `did` exactly `words` words long, by padding the first summary."""
    p = dc.folder(repo, did) / "options.yaml"
    data = taste.load_file(p)
    data["options"][0]["summary"] = "pad"
    p.write_text(taste.dumps(data), encoding="utf-8")
    extra = words - _rendered_words(repo, did)
    assert extra >= 0
    data["options"][0]["summary"] = " ".join(["pad"] * (1 + extra))
    p.write_text(taste.dumps(data), encoding="utf-8")
    assert _rendered_words(repo, did) == words


def test_count_words_skips_syntax_only_tokens():
    assert dc.count_words("# Title\n\n- one two\n---\n* three | four\n> five\n1. six") == 8


@pytest.mark.parametrize("words,ok", [(250, True), (251, False)])
def test_a_rendered_card_over_250_words_fails_options_and_status(repo, capsys, words, ok):
    _size_rendered_card(repo, words)
    code, out, err = run(["options", str(repo), "bottom-bar"], capsys)
    if ok:
        assert code == 0, err
    else:
        assert code == 1 and f"card: {words} words, limit 250" in err
        assert dc.load_map(repo)[1]["status"] != "options"            # nothing was written
    rows = dc.load_map(repo)
    rows[1]["status"] = "options"
    dc.save_map(repo, rows)
    code, out, err = run(["status", str(repo)], capsys)
    if ok:
        assert code == 0 and "FAIL" not in out
    else:
        assert code == 1 and f"card: {words} words, limit 250" in out and f"card: {words} words, limit 250" in err


@pytest.mark.parametrize("words,ok", [(250, True), (251, False)])
def test_a_card_md_over_250_words_fails_options_and_status(repo, capsys, words, ok):
    (dc.folder(repo, "bottom-bar") / "card.md").write_text("# Card\n\n- " + " ".join(["word"] * (words - 1)) + "\n", encoding="utf-8")
    code, out, err = run(["options", str(repo), "bottom-bar"], capsys)
    if ok:
        assert code == 0, err
    else:
        assert code == 1 and f"card.md: {words} words, limit 250" in err
    rows = dc.load_map(repo)
    rows[1]["status"] = "options"
    dc.save_map(repo, rows)
    code, out, err = run(["status", str(repo)], capsys)
    assert (code == 0) is ok
    assert (f"card.md: {words} words, limit 250" in out) is (not ok)


def test_card_md_wins_over_the_rendered_card(repo, capsys):
    _size_rendered_card(repo, 300)
    (dc.folder(repo, "bottom-bar") / "card.md").write_text("Short card.\n", encoding="utf-8")
    assert run(["options", str(repo), "bottom-bar"], capsys)[0] == 0
