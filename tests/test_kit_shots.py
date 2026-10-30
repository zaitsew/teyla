"""`teyla kit shots`: store screenshots framed from tiny fixture captures. Needs Pillow (skipped without it)."""
from __future__ import annotations

import json

import pytest

from teyla import cli, kit, kitdraw

from kitfix import RU_CAPTION, make_repo, png_bytes

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

# The per-screen shape: {"<route>.<state>": {"en": ..., "es": ..., "ru": ...}}
CAPTIONS = {
    "today.loaded": {"en": "Your day at a glance", "es": "Tu día de un vistazo", "ru": RU_CAPTION},
    "trip.loaded": {"en": "Every stop in order", "es": "Cada parada en orden", "ru": RU_CAPTION},
}


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def captures(repo, langs=("en", "es", "ru"), look="light", screens=("today.loaded", "trip.loaded")):
    for lang in langs:
        d = repo / "design" / "shots" / f"{lang}-{look}"
        d.mkdir(parents=True, exist_ok=True)
        for s in screens:
            (d / f"{s}.png").write_bytes(png_bytes(40, 86))


def put_captions(repo, data=CAPTIONS):
    p = repo / "docs" / "store" / "captions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_both_caption_shapes_load_in_file_order(tmp_path):
    put_captions(make_repo(tmp_path))
    by_screen = kit.load_captions(tmp_path / "demo-app" / "docs" / "store" / "captions.json")
    assert [s for s, _ in by_screen["en"]] == ["today.loaded", "trip.loaded"] and set(by_screen) == {"en", "es", "ru"}
    per_lang = tmp_path / "per-lang.json"
    per_lang.write_text(json.dumps({"_note": "x", "en": {"b.loaded": "Second", "a.loaded": "First"}}))
    assert kit.load_captions(per_lang) == {"en": [("b.loaded", "Second"), ("a.loaded", "First")]}


def test_a_broken_captions_file_is_an_error(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "docs" / "store").mkdir(parents=True)
    (repo / "docs" / "store" / "captions.json").write_text("[1, 2]")
    rc, _, err = run(capsys, "kit", "shots", str(repo))
    assert rc == 2 and "expected a JSON object" in err


def test_three_languages_in_three_sizes_from_fixture_captures(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo)
    rc, out, err = run(capsys, "kit", "shots", str(repo))
    assert rc == 0, err
    for lang in ("en", "es", "ru"):
        for size, dims in kit.STORE_SIZES.items():
            files = sorted((repo / "brand" / "out" / "store" / lang / size).glob("*.png"))
            assert [f.name for f in files] == ["01-today-loaded.png", "02-trip-loaded.png"]
            with Image.open(files[0]) as im:
                assert im.size == dims and im.mode == "RGB"
    assert "wrote 18 file(s)" in out
    # derived files need no provenance entry
    assert kit.check(repo)["verdict"] == "OK"


def test_the_frame_has_the_background_a_caption_band_and_the_capture(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(png_bytes(40, 86, rgb=(255, 0, 0)))
    img = kit.render_store_shot(shot, "Hello there", (330, 717), {"background": "#102030", "text": "#FFFFFF", "accent": "#7C9CFF"})
    assert img.getpixel((2, 2)) == (16, 32, 48)
    # the capture is red and sits in the middle of the lower part
    assert img.getpixel((165, 450)) == (255, 0, 0)
    # the band above the capture holds some caption pixels (white-ish)
    band = [img.getpixel((x, y)) for x in range(0, 330, 3) for y in range(0, 120, 3)]
    assert any(p[0] > 200 and p[1] > 200 for p in band)


def test_a_long_caption_still_fits_in_three_lines(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(png_bytes(40, 86))
    img = kit.render_store_shot(shot, "word " * 40, (660, 1434), {})
    assert img.size == (660, 1434)


def test_one_language_and_one_size(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo)
    rc, _, _ = run(capsys, "kit", "shots", str(repo), "--lang", "es", "--sizes", "iphone-6.5")
    assert rc == 0
    store = repo / "brand" / "out" / "store"
    assert [p.name for p in store.iterdir()] == ["es"] and [p.name for p in (store / "es").iterdir()] == ["iphone-6.5"]


def test_a_language_without_captures_is_skipped_whole_and_fails(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo, langs=("en", "es"))
    captures(repo, langs=("ru",), screens=("today.loaded",))
    rc, out, err = run(capsys, "kit", "shots", str(repo))
    assert rc == 1 and "ru: no capture" in err and "trip.loaded" in err
    assert (repo / "brand/out/store/en").is_dir() and not (repo / "brand/out/store/ru").exists()


def test_the_look_picks_the_capture_folder(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo, look="dark")
    assert run(capsys, "kit", "shots", str(repo))[0] == 1          # no light captures
    assert run(capsys, "kit", "shots", str(repo), "--look", "dark", "--lang", "en", "--sizes", "ipad-13")[0] == 0


def test_dry_lists_the_plan_and_writes_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo)
    rc, out, _ = run(capsys, "kit", "shots", str(repo), "--dry")
    assert rc == 0 and "Every stop in order" in out and not (repo / "brand" / "out" / "store").exists()


def test_unknown_size_and_language_are_usage_errors(tmp_path, capsys):
    repo = make_repo(tmp_path)
    put_captions(repo)
    assert run(capsys, "kit", "shots", str(repo), "--sizes", "iphone-1")[0] == 2
    assert run(capsys, "kit", "shots", str(repo), "--lang", "fr")[0] == 2


def test_without_pillow_one_line_says_how_to_install_it(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path)
    put_captions(repo)
    captures(repo)

    def gone():
        raise kitdraw.Missing(kitdraw.INSTALL_HINT)
    monkeypatch.setattr(kitdraw, "pillow", gone)
    rc, _, err = run(capsys, "kit", "shots", str(repo))
    assert rc == 1 and err.count("\n") == 1 and "--with pillow" in err
