"""`teyla reel product`: captions, timing, the ffmpeg command, the voice-over price gate. ffmpeg and ffprobe are
replaced by a recorder, the speech call by a stub; no media is decoded."""
from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import pytest

from teyla import cli, genai, kitdraw
from teyla.reel import product

from kitfix import RU_CAPTION, RealtimeFake, make_repo

pytest.importorskip("PIL")

KEY = "k-" + "x" * 12


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    terms = tmp_path / "terms.txt"
    terms.write_text("# test terms\nzebracorp\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    monkeypatch.setenv("HOME", str(tmp_path / "home" / "tester"))
    monkeypatch.setenv("LOGNAME", "tester")
    monkeypatch.setenv("USER", "tester")
    for v in ("OPENAI_API_KEY", "TEYLA_SAFE"):
        monkeypatch.delenv(v, raising=False)


class Media:
    """Stands in for subprocess.run and shutil.which: ffprobe answers a length, ffmpeg writes its output file."""

    def __init__(self, duration=10.0, audio=12.0, fail=False):
        self.duration, self.audio, self.fail = duration, audio, fail
        self.ffmpeg, self.probes = [], []

    def which(self, name):
        return f"/fake/bin/{name}"

    def run(self, cmd, **kw):
        if Path(cmd[0]).name == "ffprobe":
            self.probes.append(cmd[-1])
            d = self.audio if cmd[-1].endswith(".wav") else self.duration
            return types.SimpleNamespace(returncode=0, stdout=f"{d}\n", stderr="")
        self.ffmpeg.append(cmd)
        if self.fail:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom at the encoder")
        Path(cmd[-1]).write_bytes(b"mp4")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def media(monkeypatch):
    m = Media()
    monkeypatch.setattr(product.shutil, "which", m.which)
    monkeypatch.setattr(product.subprocess, "run", m.run)
    return m


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def copy_table(path: Path, rows=None):
    rows = rows or [
        {"key": "tour.today", "control": "caption", "state": "default", "budget": 40, "en": "Today at a glance", "es": "Hoy de un vistazo", "ru": RU_CAPTION},
        {"key": "tour.plan", "control": "caption", "state": "default", "budget": 40, "en": "Plan in one tap", "es": "Plan en un toque", "ru": "\u041f\u043b\u0430\u043d \u0432 \u043e\u0434\u0438\u043d \u0442\u0430\u043f"},
        {"key": "home.title", "control": "title", "state": "default", "budget": 20, "en": "Today", "es": "Hoy", "ru": "\u0421\u0435\u0433\u043e\u0434\u043d\u044f"},
    ]
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return path


def setup(tmp_path):
    repo = make_repo(tmp_path)
    mov = tmp_path / "demo.mov"
    mov.write_bytes(b"mov")
    return repo, mov, copy_table(tmp_path / "copy.json")


# --- captions -----------------------------------------------------------------------------------------

def test_a_copy_table_gives_the_caption_rows_per_language(tmp_path):
    caps = product.load_captions(copy_table(tmp_path / "c.json"), "caption")
    assert [c.text for c in caps["en"]] == ["Today at a glance", "Plan in one tap"] and set(caps) == {"en", "es", "ru"}
    assert caps["ru"][0].text == RU_CAPTION


def test_a_copy_table_may_be_a_list_or_a_mapping(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"control": "caption", "en": "One"}, {"control": "button", "en": "Two"}]))
    assert [c.text for c in product.load_captions(p)["en"]] == ["One"]
    p.write_text(json.dumps({"a": {"control": "caption", "en": "One", "start": 1, "end": 2.5}}))
    (c,) = product.load_captions(p)["en"]
    assert (c.text, c.start, c.end) == ("One", 1.0, 2.5)


def test_plain_captions_keep_their_times(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"en": ["One", {"text": "Two", "start": 3, "end": 5}], "es": ["Uno"]}))
    caps = product.load_captions(p)
    assert [(c.text, c.start) for c in caps["en"]] == [("One", None), ("Two", 3.0)]
    assert list(product.load_captions(p, langs=["es"])) == ["es"]


def test_captions_errors_say_what_to_fix(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"rows": [{"control": "title", "en": "T"}]}))
    with pytest.raises(product.ProductError, match=r"control 'caption'.*controls found: title.*--control"):
        product.load_captions(p)
    assert [c.text for c in product.load_captions(p, "title")["en"]] == ["T"]
    p.write_text(json.dumps({"en": ["One"]}))
    with pytest.raises(product.ProductError, match="no captions in es"):
        product.load_captions(p, langs=["es"])
    p.write_text("not json")
    with pytest.raises(product.ProductError, match="cannot read"):
        product.load_captions(p)
    p.write_text(json.dumps({"en": [{"text": "x", "start": -1}]}))
    with pytest.raises(product.ProductError, match="seconds"):
        product.load_captions(p)
    p.write_text(json.dumps({"en": [3]}))
    with pytest.raises(product.ProductError, match="string or an object"):
        product.load_captions(p)


def test_vet_rejects_a_private_term_a_path_and_an_address(tmp_path):
    repo = make_repo(tmp_path)
    caps = {"en": [product.Caption("Made at ZebraCorp"), product.Caption("Fine line"), product.Caption("Mail me at a.b@example.org"),
                   product.Caption(f"See {repo}/brand")]}
    bad = product.vet(caps, repo)
    assert len(bad) == 3 and all(b.startswith("en caption") for b in bad) and not any("caption 2" in b for b in bad)
    assert product.vet({"en": [product.Caption("Plan your day")]}, repo) == []


def test_vet_allows_the_product_names_and_nothing_else(tmp_path):
    repo = make_repo(tmp_path)
    caps = {"en": [product.Caption("Made at ZebraCorp"), product.Caption("Mail me at a.b@example.org")]}
    bad = product.vet(caps, repo, allow=("ZebraCorp",))
    assert bad == ["en caption 2 holds a secret, a private term, an address or a path"]
    assert product.vet_texts({"en": "Made at ZebraCorp"}, repo, allow=["zebracorp"]) == []
    # The name is allowed whole; a private term that is only part of it is still refused on its own.
    caps = {"en": [product.Caption("ZebraCorp Planner plans"), product.Caption("Made at ZebraCorp")]}
    assert product.vet(caps, repo, allow=("ZebraCorp Planner",)) == ["en caption 2 holds a secret, a private term, an address or a path"]


def test_a_longer_private_term_that_contains_the_product_name_is_still_refused(tmp_path, monkeypatch):
    terms = tmp_path / "terms2.txt"
    terms.write_text("zebracorp\nzebracorp planner internal\nplanner internal\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    repo = make_repo(tmp_path)
    caps = {"en": [product.Caption("ZebraCorp Planner plans"), product.Caption("ZebraCorp Planner Internal only"),
                   product.Caption("ZebraCorp Planner  Internal"), product.Caption("The Planner Internal of ZebraCorp Planner")]}
    assert product.vet(caps, repo, allow=("ZebraCorp Planner",)) == [f"en caption {i} holds a secret, a private term, an address or a path" for i in (2, 3, 4)]


def test_product_names_come_from_the_kit_the_toml_and_the_directory(tmp_path):
    repo = make_repo(tmp_path, name="zebracorp")
    (repo / "teyla.toml").write_text('[product]\nname = "zebra"\n', encoding="utf-8")
    assert product.product_names(repo, {"name": "Zebra Corp"}) == ["Zebra Corp", "zebra", "zebracorp"]
    assert product.product_names(repo, {}) == ["zebra", "zebracorp"]


def test_vet_texts_checks_a_voice_script_like_a_caption(tmp_path):
    repo = make_repo(tmp_path)
    assert product.vet_texts({"en": "Plan your day"}, repo) == []
    bad = product.vet_texts({"en": "Made at ZebraCorp", "es": "Bien"}, repo)
    assert bad == ["the en voice-over script holds a secret, a private term, an address or a path"]


def test_an_empty_caption_is_refused_at_load(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"en": ["Fine", ""]}))
    with pytest.raises(product.ProductError, match="must not be empty"):
        product.load_captions(path)


# --- timing -----------------------------------------------------------------------------------------------

def test_untimed_captions_share_the_length_equally():
    t = product.schedule([product.Caption("a"), product.Caption("b"), product.Caption("c"), product.Caption("d")], 8.0)
    assert t == [(0.0, 2.0, "a"), (2.0, 4.0, "b"), (4.0, 6.0, "c"), (6.0, 8.0, "d")]


def test_timed_captions_run_to_the_next_start_or_the_end():
    t = product.schedule([product.Caption("a", 1.0), product.Caption("b", 4.0, 5.0)], 9.0)
    assert t == [(1.0, 4.0, "a"), (4.0, 5.0, "b")]
    assert product.schedule([product.Caption("a", 8.0)], 9.0)[0][1] == 9.0
    assert product.schedule([product.Caption("a", 8.95)], 9.0)[0][1] == 9.0       # never past the end
    with pytest.raises(product.ProductError, match="every caption a start time"):
        product.schedule([product.Caption("a", 1.0), product.Caption("b")], 9.0)


def test_srt_format():
    assert product.srt_time(3723.456) == "01:02:03,456"
    assert product.srt([(0.0, 1.5, "Hello"), (1.5, 3.0, "World")]) == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n2\n00:00:01,500 --> 00:00:03,000\nWorld\n\n")


# --- the drawing and the command ------------------------------------------------------------------------------

def test_overlay_png_is_a_transparent_canvas_of_the_format_size(tmp_path):
    from PIL import Image
    for fmt, size in product.FORMATS.items():
        p = tmp_path / f"{fmt}.png"
        product.overlay_png("Plan your day in one calm screen", fmt, p)
        im = Image.open(p)
        assert im.size == size and im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
        assert im.getbbox() is not None                                          # something was drawn
        assert im.getchannel("A").crop((0, size[1] - product.SAFE_BOTTOM[fmt] + 1, size[0], size[1])).getbbox() is None   # clear bottom margin
    product.overlay_png(RU_CAPTION, "vertical", tmp_path / "ru.png")           # the default font must not raise on Cyrillic


def test_ffmpeg_command_shape():
    cmd = product.ffmpeg_cmd("ffmpeg", Path("in.mov"), "square", [(Path("a.png"), 0.0, 2.0), (Path("b.png"), 2.0, 4.0)],
                             Path("v.mp3"), Path("out.mp4"), extra=2.5, background="112233")
    s = " ".join(cmd)
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.mp4" and cmd.count("-i") == 4
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=1080:1080" in fc and "0x112233" in fc and "tpad=stop_mode=clone:stop_duration=2.50" in fc
    assert "[1:v]overlay=0:0:enable='between(t,0.000,2.000)'" in fc and "[2:v]overlay=0:0:enable='between(t,2.000,4.000)'" in fc
    assert "-map [v2]" in s and "-map 3:a" in s and "libx264" in s and "yuv420p" in s
    silent = product.ffmpeg_cmd("ffmpeg", Path("in.mov"), "vertical", [(Path("a.png"), 0, 1)], None, Path("o.mp4"))
    assert "-map" in silent and "aac" not in silent and "tpad" not in " ".join(silent) and "scale=1080:1920" in " ".join(silent)


def test_product_renders_both_formats_per_language(tmp_path, capsys, media):
    repo, mov, copy = setup(tmp_path)
    rc, out, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy))
    assert rc == 0, err
    assert len(media.ffmpeg) == 6                                                # 3 languages x 2 formats
    for lang in ("en", "es", "ru"):
        d = repo / "brand" / "out" / "reel" / lang
        assert (d / "product-vertical.mp4").is_file() and (d / "product-square.mp4").is_file()
        assert not list(d.glob(".caption-*"))                                    # temporary PNGs are removed
        assert "-->" in (d / "captions.srt").read_text(encoding="utf-8")
    assert RU_CAPTION in (repo / "brand/out/reel/ru/captions.srt").read_text(encoding="utf-8")
    assert "00:00:05,000" in (repo / "brand/out/reel/en/captions.srt").read_text()    # 10 s shared by two captions
    assert "no voice-over" in out and not (repo / "brand/out/reel/en/voice.wav").exists()


def test_product_options_pick_languages_and_formats_and_output(tmp_path, capsys, media):
    repo, mov, copy = setup(tmp_path)
    out_dir = tmp_path / "elsewhere"
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "es", "--formats", "square", "-o", str(out_dir))
    assert rc == 0, err
    assert [p.name for p in (out_dir / "es").glob("*.mp4")] == ["product-square.mp4"] and not (out_dir / "en").exists()
    assert len(media.ffmpeg) == 1


def test_product_takes_the_newest_recording_and_the_default_copy(tmp_path, capsys, media):
    repo = make_repo(tmp_path)
    (repo / "brand" / "recordings").mkdir()
    (repo / "brand" / "recordings" / "demo.mov").write_bytes(b"x")
    (repo / "brand" / "reel").mkdir()
    copy_table(repo / "brand" / "reel" / "copy.json")
    rc, _, err = run(capsys, "reel", "product", str(repo), "--lang", "en", "--formats", "square")
    assert rc == 0, err
    assert media.probes[0].endswith("demo.mov")


@pytest.mark.parametrize("argv,needle", [
    ([], "no recording"),
    (["--input", "/nonexistent/x.mov"], "no recording at"),
    (["--formats", "wide"], "--formats takes"),
    (["--lang", "ru,fr"], "no captions in fr"),
])
def test_product_input_errors_exit_two_and_render_nothing(tmp_path, capsys, media, argv, needle):
    repo = make_repo(tmp_path)
    copy = copy_table(tmp_path / "copy.json")
    mov = tmp_path / "d.mov"
    mov.write_bytes(b"x")
    base = ["reel", "product", str(repo), "--copy", str(copy)]
    if not argv:
        rc, _, err = run(capsys, *base)
    elif "--input" in argv:
        rc, _, err = run(capsys, *base, *argv)
    else:
        rc, _, err = run(capsys, *base, "--input", str(mov), *argv)
    assert rc == 2 and needle in err and media.ffmpeg == []


def test_the_products_own_name_is_not_a_private_term_in_its_reel(tmp_path, capsys, media):
    repo = make_repo(tmp_path, name="zebracorp")
    mov = tmp_path / "demo.mov"
    mov.write_bytes(b"mov")
    copy = copy_table(tmp_path / "copy.json", [{"control": "caption", "en": "Ask ZebraCorp. By voice."}])
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy))
    assert rc == 0 and err == "" and media.ffmpeg


def test_a_private_term_in_a_caption_stops_the_render(tmp_path, capsys, media):
    repo, mov, copy = setup(tmp_path)
    copy_table(copy, [{"control": "caption", "en": "Built by ZebraCorp"}])
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy))
    assert rc == 2 and "private term" in err and "zebracorp" not in err.lower() and media.ffmpeg == []


def test_missing_ffmpeg_is_one_line_with_the_fix(tmp_path, capsys, monkeypatch):
    repo, mov, copy = setup(tmp_path)
    monkeypatch.setattr(product.shutil, "which", lambda name: None)
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy))
    assert rc == 1 and "brew install ffmpeg" in err


def test_a_missing_pillow_prints_the_install_hint(tmp_path, capsys, media, monkeypatch):
    repo, mov, copy = setup(tmp_path)
    def nope():
        raise kitdraw.Missing(kitdraw.INSTALL_HINT)
    monkeypatch.setattr(kitdraw, "pillow", nope)
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy))
    assert rc == 1 and "uv tool install" in err and media.ffmpeg == []


def test_an_ffmpeg_failure_is_reported_and_exits_one(tmp_path, capsys, monkeypatch):
    repo, mov, copy = setup(tmp_path)
    m = Media(fail=True)
    monkeypatch.setattr(product.shutil, "which", m.which)
    monkeypatch.setattr(product.subprocess, "run", m.run)
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--formats", "square")
    assert rc == 1 and "ffmpeg failed for en square" in err and "boom" in err


def test_dry_prints_the_plan_and_runs_nothing(tmp_path, capsys, media):
    repo, mov, copy = setup(tmp_path)
    rc, out, _ = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--dry", "--voice")
    assert rc == 0 and "Today at a glance | Plan in one tap" in out and media.ffmpeg == [] and media.probes == []
    assert not (repo / "brand" / "out" / "reel").exists()


# --- the voice-over ----------------------------------------------------------------------------------------------

@pytest.fixture
def speech(monkeypatch):
    session = RealtimeFake()
    monkeypatch.setattr(genai, "connect", session)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    return session


def test_voice_prints_the_price_and_refuses_without_yes(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    rc, out, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice")
    chars = len("Today at a glance Plan in one tap")
    assert rc == 2 and f"voice-over {chars} characters" in out and genai.money(genai.tts_price(chars, "gpt-realtime-2.1-mini"), exact=False) in out and "--yes" in err
    assert speech.sent == [] and media.ffmpeg == [] and not (repo / "brand" / "out").exists()


def test_voice_with_yes_calls_speech_and_extends_a_short_recording(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    rc, out, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--formats", "vertical", "--voice", "--yes")
    assert rc == 0, err
    assert speech.url.endswith("model=gpt-realtime-2.1-mini")
    assert speech.sent[0]["session"]["audio"]["output"]["voice"] == "alloy"
    assert speech.sent[1]["response"]["input"][0]["content"][0]["text"] == "Today at a glance Plan in one tap"
    d = repo / "brand" / "out" / "reel" / "en"
    assert (d / "voice.wav").read_bytes()[:4] == b"RIFF" and "voice.wav" in out
    (cmd,) = media.ffmpeg
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "tpad=stop_mode=clone:stop_duration=2.00" in fc and "aac" in cmd          # voice 12 s over a 10 s recording
    assert "00:00:06,000" in (d / "captions.srt").read_text()                        # captions spread over the 12 s


def test_the_voice_script_file_replaces_the_captions(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"en": "A longer spoken line."}))
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes",
                     "--script", str(script), "--tts-model", "gpt-realtime-2.1-mini", "--tts-voice", "cedar")
    assert rc == 0, err
    assert speech.sent[1]["response"]["input"][0]["content"][0]["text"] == "A longer spoken line."
    assert speech.sent[0]["session"]["audio"]["output"]["voice"] == "cedar"
    script.write_text(json.dumps({"es": "x"}))
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes", "--script", str(script))
    assert rc == 2 and "no text for en" in err


def test_a_private_term_in_the_voice_script_stops_before_the_speech_call(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"en": "Built by ZebraCorp"}))
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes", "--script", str(script))
    assert rc == 2 and "voice-over script" in err and "zebracorp" not in err.lower()
    assert speech.sent == [] and media.ffmpeg == []


def test_mixed_caption_timing_is_refused_before_the_speech_call(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    copy.write_text(json.dumps({"en": [{"text": "One", "start": 0}, "Two"]}))
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes")
    assert rc == 1 and "every caption a start time" in err and speech.sent == []


def test_voice_without_a_key_fails_that_language_only(tmp_path, capsys, media, monkeypatch):
    repo, mov, copy = setup(tmp_path)
    monkeypatch.setattr(genai, "_post", lambda *a, **k: pytest.fail("called without a key"))
    monkeypatch.setattr(genai, "api_key", lambda *a, **k: None)
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes")
    assert rc == 1 and "OPENAI_API_KEY" in err and media.ffmpeg == []


def test_voice_in_safe_mode_is_refused_before_the_call(tmp_path, capsys, media, speech, monkeypatch):
    repo, mov, copy = setup(tmp_path)
    monkeypatch.setenv("TEYLA_SAFE", "1")
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes")
    assert rc == 2 and "safe mode" in err and speech.sent == [] and media.ffmpeg == []
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--formats", "square", "--voice", "--yes", "--allow-network")
    assert rc == 0, err
    assert speech.takes == 1


def test_a_voice_over_over_the_api_limit_is_refused_up_front(tmp_path, capsys, media, speech):
    repo, mov, copy = setup(tmp_path)
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"en": "x" * (product.TTS_MAX_CHARS + 1)}))
    rc, _, err = run(capsys, "reel", "product", str(repo), "--input", str(mov), "--copy", str(copy), "--lang", "en", "--voice", "--yes", "--script", str(script))
    assert rc == 2 and str(product.TTS_MAX_CHARS) in err and speech.sent == []
