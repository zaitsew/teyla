"""teyla taste: the YAML subset, scope matching, confirm, render and its 100-line limit.
Every repo is a tmp dir with generic content; nothing reads the real ~/.teyla or a real repo."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import cli, taste

CID = "3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11"
CID2 = "8a1d2e33-0c4f-4b6a-8e7d-5f9a0b1c2d3e"


def decision(did=CID, kind="rule", **over):
    d = {"id": did, "date": "2026-10-30", "screen": "recipe.list", "element": "recipe.list.addButton",
         "comment": "This button is too small.", "decision": kind, "reason": "Pattern, not a one-off.",
         "scope": "screen:recipe.list", "capture": did, "pr": "", "confirmed": False}
    if kind == "rule":
        d["rule"] = "Every tap target is at least 44 by 44 points."
    d.update(over)
    return d


def put(repo: pathlib.Path, d: dict) -> None:
    taste.write_json(taste.decision_path(repo, d["id"]), d)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "recipes"
    r.mkdir()
    return r


# --- the YAML subset ------------------------------------------------------------------------------

def test_yaml_round_trip_of_every_shape():
    data = {
        "wording": "Buttons say a verb and an object: \"Add recipe\".",
        "scope": "screen:recipe.list",
        "date": "2026-10-30",
        "confirmed": True,
        "n": 3,
        "nothing": None,
        "empty": [],
        "states": ["empty", "loaded", "error: offline", "yes", "123"],
        "references": [{"name": "A list app", "what_to_copy": "One add control.", "link": "https://example.com/x"},
                       {"name": "Second", "link": "https://example.com/y"}],
        "nested": {"a": "b", "deep": {"c": 1}},
        "multi": "line one\nline two",
    }
    assert taste.loads(taste.dumps(data)) == data


def test_yaml_reads_hand_written_files():
    text = """# a comment
job: Browse recipes   # trailing comment
primary_action: 'Add recipe'
states: [empty, loaded, "error"]
string_keys:
- recipe.list.title
- recipe.list.add
references:
  - name: First
    link: https://example.com/a
  -
    name: Second
confirmed: yes
"""
    got = taste.loads(text)
    assert got["job"] == "Browse recipes"
    assert got["primary_action"] == "Add recipe"
    assert got["states"] == ["empty", "loaded", "error"]
    assert got["string_keys"] == ["recipe.list.title", "recipe.list.add"]
    assert got["references"] == [{"name": "First", "link": "https://example.com/a"}, {"name": "Second"}]
    assert got["confirmed"] is True


@pytest.mark.parametrize("bad", ["a: |\n  block\n", "a: &x 1\n", "a: {b: 1}\n", "a:\n\tb: 1\n", "just a line\n"])
def test_yaml_outside_the_subset_is_an_error(bad):
    with pytest.raises(ValueError):
        taste.loads(bad)


def test_a_broken_rule_file_is_skipped_not_fatal(repo):
    rules = repo / "design" / "rules"
    rules.mkdir(parents=True)
    (rules / "good.yaml").write_text("wording: Keep it short.\nscope: product\nconfirmed: true\n")
    (rules / "bad.yaml").write_text("wording: |\n  block\n")
    assert [r["slug"] for r in taste.load_rules(repo)] == ["good"]


# --- scope ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope,screen,element,expect", [
    ("product", "any", "", True),
    ("screen:recipe.list", "recipe.list", "", True),
    ("screen:recipe.list", "recipe.detail", "", False),
    ("screen:recipe", "recipe.list", "", False),                      # a prefix is not the screen
    ("component:recipe.list.addButton", "recipe.list", "recipe.list.addButton", True),
    ("component:recipe.list.addButton", "recipe.list", "recipe.list.addButton.icon", True),
    ("component:recipe.list.add", "recipe.list", "recipe.list.addButton", False),
    ("component:recipe.list.addButton", "recipe.list", "", False),
    ("nonsense", "recipe.list", "x", False),
])
def test_scope_matches(scope, screen, element, expect):
    assert taste.scope_matches(scope, screen, element) is expect


# --- confirm --------------------------------------------------------------------------------------

def test_a_rule_file_exists_only_after_confirm(repo):
    put(repo, decision())
    assert not (repo / "design" / "rules").exists()
    res = taste.confirm(repo, CID[:8], on="2026-10-31")
    assert res["decision"] == "rule" and res["changed"]
    path = repo / res["rule_file"]
    rule = taste.load_file(path)
    assert rule["wording"] == "Every tap target is at least 44 by 44 points."
    assert rule["scope"] == "screen:recipe.list"
    assert rule["example_capture"] == CID
    assert rule["confirmed"] is True and rule["confirmed_on"] == "2026-10-31" and rule["date"] == "2026-10-30"
    d = json.loads(taste.decision_path(repo, CID).read_text())
    assert d["confirmed"] is True and d["confirmed_on"] == "2026-10-31"


def test_confirm_twice_changes_nothing_and_a_new_wording_updates_the_same_file(repo):
    put(repo, decision())
    first = taste.confirm(repo, CID[:6], on="2026-10-31")
    again = taste.confirm(repo, CID[:6], on="2026-11-02")
    assert not again["changed"] and again["rule_file"] == first["rule_file"]
    upd = taste.confirm(repo, CID[:6], rule="Tap targets are 48 points or more.", scope="product", on="2026-11-03")
    assert upd["rule_file"] == first["rule_file"]
    assert len(list((repo / "design" / "rules").glob("*.yaml"))) == 1
    rule = taste.load_file(repo / upd["rule_file"])
    assert rule["wording"] == "Tap targets are 48 points or more." and rule["scope"] == "product"
    assert rule["confirmed_on"] == "2026-10-31", "the first confirmation date is kept"


def test_two_rules_with_the_same_first_words_get_two_files(repo):
    put(repo, decision())
    put(repo, decision(CID2, rule="Every tap target is at least 44 by 44 points, no exceptions."))
    a = taste.confirm(repo, CID[:6])
    b = taste.confirm(repo, CID2[:6])
    assert a["rule_file"] != b["rule_file"]


def test_confirm_refuses_what_the_owner_must_fix_first(repo):
    put(repo, decision(CID, rule=""))
    with pytest.raises(ValueError, match="no wording"):
        taste.confirm(repo, CID[:6])
    with pytest.raises(ValueError, match="scope"):
        taste.confirm(repo, CID[:6], rule="x", scope="everywhere")
    put(repo, decision(CID2, kind="fix"))
    with pytest.raises(ValueError, match="rule only"):
        taste.confirm(repo, CID2[:6], rule="x")
    with pytest.raises(KeyError, match="too short"):
        taste.confirm(repo, "3f9")
    with pytest.raises(KeyError, match="no decision"):
        taste.confirm(repo, "ffff0000")


def test_confirming_a_fix_or_a_reject_writes_no_rule_file(repo):
    put(repo, decision(CID, kind="fix"))
    put(repo, decision(CID2, kind="reject"))
    assert "rule_file" not in taste.confirm(repo, CID[:6])
    assert "rule_file" not in taste.confirm(repo, CID2[:6])
    assert not (repo / "design" / "rules").exists()
    assert json.loads(taste.decision_path(repo, CID2).read_text())["confirmed"] is True


def test_an_ambiguous_prefix_names_the_candidates(repo):
    put(repo, decision("3f9a1c20-0000-4000-8000-000000000001"))
    put(repo, decision("3f9a1c20-0000-4000-8000-000000000002"))
    with pytest.raises(KeyError, match="matches 2"):
        taste.find_decision(repo, "3f9a1c20")


# --- render ---------------------------------------------------------------------------------------

def write_screen(repo, name="recipe.list"):
    d = repo / "design" / "screens"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(taste.dumps({"job": "Browse saved recipes.", "primary_action": "Add recipe",
                                                  "states": ["empty", "loaded"], "string_keys": ["a", "b", "c"]}))


HAND = "# Design: recipes\n\nHand-written text that stays.\n\n## Tokens\nNames only.\n"


def test_render_fills_the_marker_blocks_and_keeps_the_rest(repo):
    (repo / "DESIGN.md").write_text(
        HAND + "\n## Rules from review\n<!-- teyla:rules -->\nold\n<!-- /teyla:rules -->\n\n## Voice\nCalm.\n\n"
        "## Screens\n<!-- teyla:screens -->\nold\n<!-- /teyla:screens -->\n\nTail.\n")
    put(repo, decision())
    taste.confirm(repo, CID[:6], on="2026-10-31")
    write_screen(repo)
    code, msgs = taste.render(repo)
    assert code == 0, msgs
    text = (repo / "DESIGN.md").read_text()
    assert text.startswith(HAND)
    assert "## Voice\nCalm.\n" in text and text.endswith("Tail.\n")
    assert "## Rules from review" in text and "`screen:recipe.list` Every tap target is at least 44 by 44 points. (2026-10-30)" in text
    assert "**recipe.list** — Browse saved recipes. Primary: Add recipe. States: empty, loaded. 3 string keys." in text
    assert "old" not in text
    assert text.count("## Rules from review") == 1 and text.count("## Screens") == 1, "headings are not duplicated"
    assert taste.render(repo)[1][-1] == "already up to date"


def test_render_does_not_show_an_unconfirmed_proposal(repo):
    (repo / "DESIGN.md").write_text(HAND)
    put(repo, decision())
    code, _ = taste.render(repo)
    text = (repo / "DESIGN.md").read_text()
    assert code == 0 and "tap target" not in text and "None confirmed yet." in text


def test_render_appends_missing_markers_after_the_hand_written_text(repo):
    (repo / "DESIGN.md").write_text(HAND)
    code, msgs = taste.render(repo)
    text = (repo / "DESIGN.md").read_text()
    assert code == 0 and text.startswith(HAND)
    assert text.index("<!-- teyla:rules -->") < text.index("<!-- teyla:screens -->")
    assert "## Rules from review\n\n<!-- teyla:rules -->" in text and "<!-- /teyla:screens -->" in text
    assert any("appended" in m for m in msgs)


def test_render_finds_docs_design_md(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "DESIGN.md").write_text(HAND)
    taste.render(repo)
    assert "<!-- teyla:rules -->" in (repo / "docs" / "DESIGN.md").read_text()
    assert not (repo / "DESIGN.md").exists()


def test_render_refuses_past_100_lines_and_writes_nothing(repo, capsys):
    hand = "# Design\n" + "".join(f"line {i}\n" for i in range(95))
    (repo / "DESIGN.md").write_text(hand)
    put(repo, decision())
    taste.confirm(repo, CID[:6])
    code, msgs = taste.render(repo)
    assert code == 1
    assert (repo / "DESIGN.md").read_text() == hand, "a refused render leaves the file as it was"
    out = "\n".join(msgs)
    assert "limit is 100" in out and "hand-written" in out and "Nothing was written" in out
    assert "Oldest rules" in out


def test_render_dry_writes_nothing(repo):
    (repo / "DESIGN.md").write_text(HAND)
    code, msgs = taste.render(repo, dry=True)
    assert code == 0 and (repo / "DESIGN.md").read_text() == HAND and "dry run" in msgs[-1]


# --- the rejection memory and the command ---------------------------------------------------------

def test_rejections_and_recent_decisions_come_from_the_files(repo):
    put(repo, decision(CID, kind="reject", date="2026-10-01"))
    put(repo, decision(CID2, kind="fix", date="2026-10-02"))
    assert [d["id"] for d in taste.load_decisions(repo)] == [CID2, CID], "newest first"
    assert [d["id"] for d in taste.rejections(repo)] == [CID]


def test_cli_list_confirm_render(repo, capsys, monkeypatch):
    (repo / "DESIGN.md").write_text(HAND)
    put(repo, decision())
    assert cli.main(["taste", "list", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "1 open rule proposal" in out and CID[:8] in out and "teyla taste confirm" in out
    assert cli.main(["taste", "confirm", CID[:8], "--repo", str(repo)]) == 0
    assert "design/rules/" in capsys.readouterr().out
    assert cli.main(["taste", "list", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["decisions"][0]["confirmed"] is True
    assert cli.main(["taste", "render", str(repo)]) == 0
    assert "tap target" in (repo / "DESIGN.md").read_text()
    assert cli.main(["taste", "confirm", "zzzz", "--repo", str(repo)]) == 1
    assert cli.main(["taste", "confirm", "--repo", str(repo)]) == 2
    assert cli.main(["taste", "list", str(repo / "missing")]) == 2
    monkeypatch.chdir(repo)
    assert cli.main(["taste"]) == 0, "the default action is list, in the current repo"


def test_render_on_the_shipped_template_stays_short_and_does_not_duplicate(repo):
    template = pathlib.Path(taste.__file__).resolve().parents[2] / "templates" / "design" / "DESIGN.md"
    (repo / "DESIGN.md").write_text(template.read_text())
    put(repo, decision())
    taste.confirm(repo, CID[:6], on="2026-10-31")
    write_screen(repo)
    code, msgs = taste.render(repo)
    assert code == 0, msgs
    text = (repo / "DESIGN.md").read_text()
    assert len(text.splitlines()) < 100
    assert text.count("## Screens") == 1 and text.count("## Rules from review") == 1
    assert "{{home}}" not in text and "{{rule:" not in text, "the placeholder rows were replaced"
    assert "**recipe.list**" in text and "Every tap target" in text
    assert not any("appended" in m for m in msgs)
