"""`teyla kit init` and `teyla kit check`: a kit in a tmp dir, no network, no Pillow."""
from __future__ import annotations

import json

import pytest

from teyla import cli, kit

from kitfix import KIT, SHEET, make_repo, png_bytes


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def findings(repo):
    return [(f["check"], f["severity"], f["message"]) for f in kit.check(repo)["findings"]]


def fixes(repo, check=None):
    return [m for c, s, m in findings(repo) if s == "FIX" and (check is None or c == check)]


def edit(repo, old, new):
    p = repo / "brand" / "kit.toml"
    text = p.read_text(encoding="utf-8")
    assert old in text
    p.write_text(text.replace(old, new), encoding="utf-8")


def test_the_sheet_fixture_is_about_sixty_words():
    assert 40 <= len(SHEET.split()) <= 80


def test_a_complete_kit_passes(tmp_path):
    rep = kit.check(make_repo(tmp_path))
    assert rep["verdict"] == "OK", rep["findings"]


def test_check_exit_status_and_json(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, _ = run(capsys, "kit", "check", str(repo))
    assert rc == 0 and "kit ok" in out
    (repo / "brand" / "kit.toml").unlink()
    rc, out, _ = run(capsys, "kit", "check", str(repo), "--json")
    assert rc == 1 and json.loads(out)["verdict"] == "FIX"


# --- init -----------------------------------------------------------------------------------------

def test_init_fills_what_design_md_says_and_makes_the_folders(tmp_path, capsys):
    repo = tmp_path / "widget"
    (repo / "design" / "tokens").mkdir(parents=True)
    (repo / "design" / "tokens" / "colors.json").write_text("{}")
    (repo / "brand" / "mascot").mkdir(parents=True)
    (repo / "brand" / "mascot" / "ref-front.png").write_bytes(png_bytes())
    (repo / "DESIGN.md").write_text("# Design: Widget Planner\n\nSource: `design/tokens/*.json`\n")
    rc, out, _ = run(capsys, "kit", "init", str(repo))
    assert rc == 0
    data = kit.load(repo)
    assert data["product"]["name"] == "Widget Planner"
    assert data["tokens"]["path"] == "design/tokens"
    assert data["mascot"]["refs"] == ["brand/mascot/ref-front.png"]
    for d in ("brand/icon", "brand/voice", "brand/posts/queue", "brand/posts/samples"):
        assert (repo / d).is_dir()
    assert "store/" in (repo / "brand" / "out" / ".gitignore").read_text()
    # what DESIGN.md does not say stays a placeholder, and check fails on it
    assert any("placeholder" in m for m in fixes(repo, "placeholders"))
    assert run(capsys, "kit", "check", str(repo))[0] == 1


def test_init_ignores_a_design_md_that_is_still_a_template(tmp_path):
    repo = tmp_path / "widget"
    repo.mkdir()
    (repo / "DESIGN.md").write_text("# Design: {{product}}\n\nSource: `{{design/tokens/*.json}}`\n")
    kit.init(repo)
    assert kit.load(repo)["product"]["name"] == "{{product}}"


def test_init_does_not_replace_an_existing_kit_without_force(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "kit", "init", str(repo))
    assert rc == 2 and "--force" in err
    assert "Demo App" in (repo / "brand" / "kit.toml").read_text()
    assert run(capsys, "kit", "init", str(repo), "--force")[0] == 0


def test_the_shipped_template_parses_and_has_every_section():
    from teyla import templates_dir
    import tomllib
    data = tomllib.loads((templates_dir() / "brand" / "kit.toml").read_text())
    for key in ("product", "tagline", "tokens", "mascot", "icon", "voice", "channels", "banned"):
        assert key in data
    assert set(data["tagline"]) == {"en", "es", "ru"}
    assert data["mascot"]["model"] in kit.genai.IMAGE_MODELS and data["mascot"]["settings"]


# --- check: missing pieces --------------------------------------------------------------------------

def test_missing_kit_file(tmp_path):
    repo = make_repo(tmp_path, kit=False)
    assert fixes(repo, "kit") and "kit init" in kit.check(repo)["findings"][0]["fix"]


@pytest.mark.parametrize("old,new,check,needle", [
    ('en = "A calm day plan."', 'en = ""', "tagline", "en"),
    ('promise = "Plan your day in one calm screen."', 'promise = "{{one line}}"', "placeholders", "product.promise"),
    ('path = "design/tokens"', 'path = "design/nowhere"', "tokens", "does not exist"),
    ('source = "brand/icon/icon.svg"', 'source = "brand/icon/missing.svg"', "icon", "does not exist"),
    ('model = "nano-banana-2.1"\n\n[mascot.settings]', 'model = "dream-9"\n\n[mascot.settings]', "mascot", "dream-9"),
    ('refs = ["brand/mascot/ref-1.png", "brand/mascot/ref-2.png"]', 'refs = []', "mascot", "no reference image"),
    ('refs = ["brand/mascot/ref-1.png", "brand/mascot/ref-2.png"]', 'refs = ["brand/mascot/ref-1.png", "brand/mascot/ref-9.png"]', "mascot", "ref-9"),
    ('name = "Pip"', 'name = ""', "mascot", "name is empty"),
    ('[mascot.settings]\naspect_ratio = "1:1"\ntemperature = 0.6\nrefs_max = 6\n', '', "mascot", "settings are not locked"),
    ('[channels.x]\nmedia = "image"', '[channels.myspace]\nmedia = "image"', "channels", "myspace"),
    ('words = ["delve", "seamless*"]', 'words = []', "banned", "empty"),
    ('chart = "brand/voice"', 'chart = "brand/nowhere"', "voice", "not a directory"),
])
def test_check_fails_on_a_missing_piece(tmp_path, old, new, check, needle):
    repo = make_repo(tmp_path)
    edit(repo, old, new)
    got = fixes(repo, check)
    assert any(needle in m for m in got), (needle, findings(repo))


def test_a_character_sheet_far_from_sixty_words_fails(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, SHEET, "A robot.")
    assert any("words" in m for m in fixes(repo, "mascot"))


def test_a_missing_voice_chart_language_fails(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "voice" / "ru.md").unlink()
    assert any("ru.md is missing" in m for m in fixes(repo, "voice"))
    (repo / "brand" / "voice" / "ru.md").write_text("no front matter here")
    assert any("ru.md" in m and "front matter" in m for m in fixes(repo, "voice"))


def test_a_banned_word_in_the_kits_own_text_fails(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, 'en = "A calm day plan."', 'en = "A seamless day plan."')
    assert any("tagline.en" in m and "seamless" in m for m in fixes(repo, "banned"))


def test_a_locked_model_without_a_comparison_is_a_warning(tmp_path):
    repo = make_repo(tmp_path)
    p = repo / "brand" / "kit.toml"
    text = p.read_text()
    p.write_text(text[:text.index("[[comparison]]")])
    rep = kit.check(repo)
    assert rep["verdict"] == "WARN" and any("comparison" in f["message"] for f in rep["findings"])


def test_fewer_than_three_sample_posts_is_a_warning(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "posts" / "samples" / "sample-0.md").unlink()
    assert ("samples", "WARN") in [(c, s) for c, s, _ in findings(repo)]


# --- check: two characters ----------------------------------------------------------------------------

def test_two_characters_fail_as_a_list(tmp_path):
    repo = make_repo(tmp_path)
    edit(repo, "[mascot]\n", "[[mascot]]\n")
    assert any("more than one character" in m for m in fixes(repo, "characters"))


def test_two_characters_fail_as_a_second_table(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "kit.toml").write_text((repo / "brand" / "kit.toml").read_text() + '\n[mascot_navigator]\nname = "Nav"\n')
    assert any("mascot_navigator" in m for m in fixes(repo, "characters"))
    # a [character] table counts too
    (repo / "brand" / "kit.toml").write_text((repo / "brand" / "kit.toml").read_text() + '\n[character]\nname = "Other"\n')
    assert any("character" in m for m in fixes(repo, "characters"))


def test_two_characters_fail_as_a_second_reference_folder(tmp_path):
    repo = make_repo(tmp_path)
    other = repo / "brand" / "mascot" / "navigator"
    other.mkdir()
    (other / "ref-1.png").write_bytes(png_bytes())
    assert any("navigator" in m for m in fixes(repo, "characters"))


# --- check: provenance ----------------------------------------------------------------------------------

def test_an_asset_without_provenance_fails(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "mascot" / "ref-3.png").write_bytes(png_bytes())
    (repo / "brand" / "out" / "mascot").mkdir(parents=True)
    (repo / "brand" / "out" / "mascot" / "2026-10-30-waving.png").write_bytes(png_bytes())
    got = fixes(repo, "provenance")
    assert any("ref-3.png: no provenance entry" in m for m in got)
    assert any("2026-10-30-waving.png: no provenance entry" in m for m in got)


def test_derived_files_and_posts_need_no_provenance(tmp_path):
    repo = make_repo(tmp_path)
    for d in ("brand/out/store/en/iphone-6.9", "brand/out/reel/en", "brand/out/compare/x/m", "brand/posts/queue"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    (repo / "brand/out/store/en/iphone-6.9/01-a.png").write_bytes(png_bytes())
    (repo / "brand/out/reel/en/product-vertical.mp4").write_bytes(b"x")
    (repo / "brand/out/compare/x/m/01.png").write_bytes(png_bytes())
    (repo / "brand/posts/queue/card.png").write_bytes(png_bytes())
    assert kit.check(repo)["verdict"] == "OK"


@pytest.mark.parametrize("old,new,needle", [
    ('made_by = "model: nano-banana-2.1"\nprompt = "Pip, front view, neutral expression"', 'made_by = "someone"\nprompt = "p"', "made_by"),
    ('prompt = "Pip, front view, neutral expression"', 'prompt = ""', "prompt is empty"),
    ('date = "2026-10-01"', 'date = "last week"', "date"),
])
def test_a_bad_provenance_entry_fails(tmp_path, old, new, needle):
    repo = make_repo(tmp_path)
    edit(repo, old, new)
    assert any(needle in m for m in fixes(repo, "provenance")), findings(repo)


def test_provenance_for_a_deleted_asset_is_a_warning(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "mascot" / "ref-2.png").unlink()
    edit(repo, '"brand/mascot/ref-1.png", "brand/mascot/ref-2.png"', '"brand/mascot/ref-1.png"')
    assert ("provenance", "WARN") in [(c, s) for c, s, _ in findings(repo)]


def test_append_provenance_round_trips_awkward_text(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "brand" / "icon" / "alt.png").write_bytes(png_bytes())
    kit.append_provenance(repo, "brand/icon/alt.png", "model: nano-banana-2.1", 'say "hi"\nthen\\go é', ["brand/mascot/ref-1.png"], "2026-10-30")
    entry = kit.load(repo)["provenance"][-1]
    assert entry["prompt"] == 'say "hi" then\\go é' and entry["references"] == ["brand/mascot/ref-1.png"]
    assert kit.check(repo)["verdict"] == "OK"
