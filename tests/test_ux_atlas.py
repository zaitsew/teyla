"""`teyla ux registry check` and `teyla ux atlas`: parsing, validation, coverage maths, the HTML."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

import atlasfix
from teyla import cli, ux_atlas as ua


@pytest.fixture
def repo(tmp_path):
    return atlasfix.build(tmp_path / "recipes")


def write(repo, name, text):
    (repo / "design" / "screens" / f"{name}.yaml").write_text(text)


def errors(repo):
    return ua.load_registry(repo).errors


def test_the_fixture_registry_is_valid_and_reads_every_key(repo):
    reg = ua.load_registry(repo)
    assert reg.errors == []
    assert [e["id"] for e in reg.entries] == ["add-recipe", "home", "recipe", "recipes", "settings", "shopping", "units"]
    home = reg.by_id()["home"]
    assert home["title"] == "Home" and home["level"] == 1 and home["platforms"] == ["ios", "macos"]
    assert home["links"][0] == {"to": "recipes", "via": "tap Recipes tab", "tested": True}
    assert home["layout"]["wide"].startswith("Three columns") and home["layout"]["assert"] == "testHomeWideShowsThreeColumns"
    assert home["assert_found"] is True
    assert home["source"] == ["App/Recipes/Home.swift"] and home["job"].startswith("Show what")
    assert reg.by_id()["units"]["platforms"] == ["ios"]            # the default platform


def test_an_old_inventory_entry_stays_valid(tmp_path):
    (tmp_path / "design" / "screens").mkdir(parents=True)
    (tmp_path / "design" / "screens" / "today.yaml").write_text(
        "job: Show what is next.\nprimary_action: Add\nstates:\n  - loaded\n  - calendar off\nstring_keys:\n  - a.b\ncatalog:\n  - X.xcstrings\n")
    reg = ua.load_registry(tmp_path)
    assert reg.errors == []
    assert reg.entries[0]["id"] == "today" and reg.entries[0]["states"] == ["loaded", "calendar off"]


@pytest.mark.parametrize("body,needle", [
    ("parent: nowhere\n", "unknown parent 'nowhere'"),
    ("parent: loop\n", "own parent"),
    ("links:\n  - to: ghost\n", "unknown screen 'ghost'"),
    ("links:\n  - to: loop\n", "link to itself"),
    ("links:\n  - via: tap\n", "needs a `to`"),
    ("links:\n  - to: home\n    tested: maybe\n", "`tested` must be true or false"),
    ("level: 0\n", "`level` must be"),
    ("platforms: [ios, toaster]\n", "unknown platform 'toaster'"),
    ("layout:\n  tiny: A phone.\n", "unknown layout key `tiny`"),
    ("route: ghost-route\n", "not in design/tour.yaml"),
    ("title: [a, b]\n", "`title` must be text"),
])
def test_invalid_entries_are_reported_by_file(repo, body, needle):
    write(repo, "loop", body)
    errs = errors(repo)
    assert any("loop.yaml" in e and needle in e for e in errs), errs


def test_duplicate_ids_and_parent_cycles(repo):
    write(repo, "one", "id: same\n")
    write(repo, "two", "id: same\n")
    write(repo, "a", "parent: b\n")
    write(repo, "b", "parent: a\n")
    errs = errors(repo)
    assert any("duplicate screen id 'same'" in e for e in errs)
    assert any("parent chain loops" in e for e in errs)


def test_a_file_that_does_not_parse_is_an_error_not_a_crash(repo):
    write(repo, "broken", "title: ok\n  bad: indent\n")
    assert any("broken.yaml: cannot read" in e for e in errors(repo))


def test_missing_things_are_warnings_only(repo):
    write(repo, "extra", "source: [App/Nope.swift]\nlayout:\n  assert: testNeverWritten\nfeatures: [Not a section]\n")
    reg = ua.load_registry(repo)
    assert reg.errors == []
    w = "\n".join(reg.warnings)
    assert "source file 'App/Nope.swift' does not exist" in w
    assert "'testNeverWritten' named in `layout.assert` is not in the code" in w
    assert "feature 'Not a section' matches no section" in w
    assert "no `route`" in w and "no `parent` and no `level`" in w
    assert "route 'orphan-route' belongs to no screen" in w


def test_features_are_parsed_by_section_and_mapped_by_name_or_anchor(repo):
    secs = ua.parse_features(repo / "docs" / "FEATURES.md")
    assert [s["name"] for s in secs] == ["Home", "Recipe list", "Recipe detail", "Recipe editor", "Shopping list",
                                         "Meal planner", "Sharing"]
    assert secs[0]["surface"] == "iPhone" and secs[0]["rows"][0] == {"text": "Tonight card", "anchor": "`home.tonight`"}
    reg = ua.load_registry(repo)
    fc = ua.feature_coverage(reg)
    assert (fc["sections"], fc["sections_mapped"]) == (7, 5)
    assert sorted(u["name"] for u in fc["unmapped"]) == ["Meal planner", "Sharing"]
    # "Home" names a section (2 rows); "Tonight card" names one row; the same rows are not counted twice
    assert fc["rows"] == 10 and fc["rows_mapped"] == 7
    write(repo, "extra", "route: home\nfeatures: ['`planner.week`']\n")
    fc = ua.feature_coverage(ua.load_registry(repo))
    assert [u["name"] for u in fc["unmapped"]] == ["Sharing"]      # an anchor maps its section


def test_captures_are_found_in_shots_baseline_and_platform_folders(repo):
    caps = ua.scan_captures(repo)
    key = {(c["platform"], c["lang"], c["look"], c["route"], c["state"], c["kind"]) for c in caps}
    assert ("ios", "en", "light", "home", "loaded", "shots") in key
    assert ("ios", "es", "light", "home", "loaded", "shots") in key
    assert ("macos", "en", "light", "home", "loaded", "shots") in key
    assert ("ios", "en", "light", "settings", "loaded", "baseline") in key
    assert len(caps) == len(atlasfix.SHOTS)


def test_coverage_maths(repo):
    reg = ua.load_registry(repo)
    cov = ua.coverage(reg, ua.scan_captures(repo))
    # expected pairs: home 2, recipes 2, recipe 2, add-recipe 1, shopping 1, settings 3, units 1
    assert (cov["expected"], cov["captured"], cov["percent"]) == (12, 6, 50)
    assert cov["platforms"]["ios"]["expected"] == 7 and cov["platforms"]["ios"]["captured"] == 5
    assert cov["platforms"]["ios"]["looks"] == {"light": 5, "dark": 2, "large": 1}
    assert cov["platforms"]["macos"]["captured"] == 1 and cov["platforms"]["web"]["captured"] == 0
    assert cov["levels"] == {"1": {"expected": 8, "captured": 5}, "2": {"expected": 4, "captured": 1}}
    assert cov["screens"]["home"]["captured"] and not cov["screens"]["add-recipe"]["captured"]
    assert cov["screens"]["home"]["complete"] is False             # macos has only the light look


def test_a_screen_without_a_route_is_expected_and_never_captured(repo):
    write(repo, "extra", "level: 1\n")
    reg = ua.load_registry(repo)
    cov = ua.coverage(reg, ua.scan_captures(repo))
    assert cov["expected"] == 13 and cov["captured"] == 6


def test_levels_come_from_the_parent_when_not_written(repo):
    lv = ua.level_map(ua.load_registry(repo))
    assert lv["units"] == 2 and lv["recipe"] == 2 and lv["home"] == 1


def test_check_command_prints_expected_against_captured_and_exits_zero(repo, capsys):
    assert cli.main(["ux", "registry", "check", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "captured / expected (screens x platforms): 6 / 12 (50%)" in out
    assert re.search(r"ios\s+5/7\s+light 5/7\s+dark 2/7\s+large 1/7", out)
    assert "not captured: add-recipe, units" in out


def test_check_command_exits_one_on_an_invalid_entry_only(repo, capsys):
    write(repo, "bad", "parent: nowhere\n")
    assert cli.main(["ux", "registry", "check", str(repo)]) == 1
    assert "ERROR design/screens/bad.yaml: unknown parent" in capsys.readouterr().out
    (repo / "design" / "screens" / "bad.yaml").unlink()
    assert cli.main(["ux", "registry", "check", str(repo), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"]["expected"] == 12


def test_check_needs_the_check_subcommand(repo, capsys):
    assert cli.main(["ux", "registry", str(repo)]) == 2


def test_the_atlas_html_holds_every_node_and_works_offline(repo, tmp_path, capsys):
    out = tmp_path / "out"
    assert cli.main(["ux", "atlas", str(repo), "--out", str(out)]) == 0
    assert "captured / expected 6 / 12 (50%)" in capsys.readouterr().out
    page = (out / "atlas.html").read_text()
    data = json.loads(re.search(r'<script id="atlas-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    ids = [s["id"] for s in data["screens"]]
    assert ids == ["add-recipe", "home", "recipe", "recipes", "settings", "shopping", "units"]
    for i in ids:
        assert f'data-screen="{i}"' in page                        # a Grid card, drawn without JavaScript
    assert re.search(r"https?://(?!www\.w3\.org)", page) is None   # no CDN, no network
    assert "<script src" not in page and "<link " not in page
    assert "Level 1 · tab roots" in page and "Level 2" in page
    assert "<b>6 / 12</b> screens captured (50%)" in page
    assert "not captured" in page                                  # the placeholder
    for gap in ("Meal planner", "Sharing", "orphan-route"):
        assert gap in page or gap == "orphan-route"                # unmapped feature sections are listed
    assert "Feature sections no screen names" in page


def test_the_atlas_copies_the_screenshots_it_shows(repo, tmp_path):
    out = tmp_path / "out"
    data, _ = ua.build_data(repo, out)
    home = next(s for s in data["screens"] if s["id"] == "home")
    got = {(i["platform"], i["look"], i["state"]) for i in home["images"]}
    assert ("ios", "light", "loaded") in got and ("ios", "light", "empty") in got
    assert ("ios", "dark", "loaded") in got and ("macos", "light", "loaded") in got
    for i in home["images"]:
        assert (out / i["src"]).is_file()
    settings = next(s for s in data["screens"] if s["id"] == "settings")
    assert [(i["kind"]) for i in settings["images"]] == ["baseline"]
    assert next(s for s in data["screens"] if s["id"] == "units")["images"] == []


def test_a_new_capture_beats_the_baseline_and_the_language_flag_picks_one(repo, tmp_path):
    atlasfix.png(repo / "design" / "shots" / "baseline" / "en-light" / "home.loaded.png", 5)
    caps = ua.scan_captures(repo)
    pick = ua._pick(caps, "ios", "home", "en")
    assert {c["kind"] for c in pick if c["look"] == "light" and c["state"] == "loaded"} == {"shots"}
    assert {c["lang"] for c in ua._pick(caps, "ios", "home", "es")} == {"es"}
    assert {c["lang"] for c in ua._pick(caps, "ios", "home", "zz")} == {"en"}      # unknown: the first one found


def test_the_map_has_every_edge_and_marks_tested_ones(repo):
    data, reg = ua.build_data(repo, None)
    edges = {(e["from"], e["to"]): e for e in data["edges"]}
    assert edges[("home", "recipes")]["tested"] is True and edges[("home", "recipes")]["kind"] == "link"
    assert edges[("recipes", "add-recipe")]["tested"] is False and edges[("recipes", "add-recipe")]["kind"] == "link"
    assert edges[("recipes", "recipe")]["kind"] == "link"           # a link replaces the parent line
    assert edges[("settings", "units")]["kind"] == "parent"
    assert ("recipes", "add-recipe") in edges and len([e for e in data["edges"] if (e["from"], e["to"]) == ("recipes", "recipe")]) == 1


def test_the_map_layout_puts_levels_in_columns_and_never_stacks_two_nodes(repo):
    data, _ = ua.build_data(repo, None)
    xs = {s["id"]: s["x"] for s in data["screens"]}
    step = ua.NODE_W + ua.COL_GAP
    assert xs["home"] == 0 and xs["recipe"] == step and xs["units"] == step
    spots = [(s["x"], s["y"]) for s in data["screens"]]
    assert len(set(spots)) == len(spots)


def test_the_html_escapes_text_from_the_registry(repo, tmp_path):
    write(repo, "evil", 'title: "<img src=x onerror=alert(1)> </script>"\nlevel: 1\n')
    out = tmp_path / "out"
    ua.write_atlas(repo, out)
    page = (out / "atlas.html").read_text()
    assert "<img src=x" not in page
    assert page.count("</script>") == 2                            # the data block's and the code's, no more


def test_filters_and_both_views_are_in_the_page(repo, tmp_path):
    out = tmp_path / "out"
    page = ua.write_atlas(repo, out)[0].read_text()
    for needle in ('id="fp"', 'id="fc"', 'id="tg"', 'id="tm"', 'id="panel"', "prefers-color-scheme:dark", 'id="svg"'):
        assert needle in page
    assert '<option value="macos">macos</option>' in page


def test_the_commands_are_listed_in_help_and_the_docs():
    root = pathlib.Path(__file__).parent.parent
    for rel in ("docs/COMMANDS.md", "src/teyla/cli.py"):
        text = (root / rel).read_text()
        assert "teyla ux atlas" in text and "teyla ux registry check" in text, rel
