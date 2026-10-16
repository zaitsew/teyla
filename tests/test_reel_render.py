"""teyla reel render: pacing and layout as pure functions, the drawn-strings audit, and a smoke render.

The layout tests need nothing installed. The drawing tests need Pillow and a monospace font, the
video test also ffmpeg; each skips cleanly when its piece is missing.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from teyla import cli
from teyla.reel import cards, layout, render
from teyla.reel.story import DIFF_MAX, LINE_MAX, LINES_MAX, MINUS, Beat, Story, Totals, make_ticks


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No look at the owner's term list or home directory."""
    terms = tmp_path / "terms.txt"
    terms.write_text("# test terms\nzebracorp\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    monkeypatch.setenv("HOME", str(tmp_path / "home" / "tester"))
    monkeypatch.setenv("LOGNAME", "tester")
    monkeypatch.setenv("USER", "tester")


DIFF = ["+def fetch(url, retries=3):", "+    for n in range(retries):", "+        try:", "+            return get(url)",
        " ", "-    return get(url)"]


def make_story(n_beats: int = 8, wall: int = 5400) -> Story:
    beats = [Beat(0, "ask", "The ask", ["Add a retry wrapper to the", "fetch helper."])]
    kinds = [
        Beat(300, "lane", "Survey the fetch helper", ["scout · haiku"]),
        Beat(700, "edit", "src/app/fetch.py", ["+4 " + MINUS + "1"], DIFF),
        Beat(1500, "test", "21 tests passed", ["pytest"]),
        Beat(2200, "test", "2 failed, 19 passed", ["pytest"]),
        Beat(2600, "commit", "Add a retry wrapper to the fetch helper", ["a1b2c3d", "+40 " + MINUS + "2 · 2 files"]),
        Beat(3100, "review", "codex-review: 0 P1, 1 P2", ["no blockers"]),
        Beat(3800, "pr", "PR #12 opened", ["Retry wrapper"]),
        Beat(4300, "command", "git push origin feat/retry"),
        Beat(4700, "pr", "PR #12 merged", ["Retry wrapper"]),
    ]
    beats += kinds[: max(0, n_beats - 1)]
    totals = Totals(wall_clock=wall, commits=1, lines_added=40, lines_removed=2, tests_passed=21, tests_failed=0,
                    test_runs=2, prs_opened=1, prs_merged=1)
    ticks = [[2600, 1, 0, 0], [3800, 1, 21, 1], [wall, 1, 21, 1]]
    return Story(id="5e55a0f1-0000", harness="claude", repo="demo", started="2026-01-01T12:00:00Z",
                 ended="2026-01-01T13:30:00Z", ask="Add a retry wrapper to the fetch helper.", title="demo session",
                 beats=beats, totals=totals, ticks=ticks)


# --- pacing -----------------------------------------------------------------------------------

def test_beat_seconds_grows_with_lines_and_diff_and_stays_clamped():
    assert layout.beat_seconds(0, False) == 2.0
    assert layout.beat_seconds(3, False) == pytest.approx(2.9)
    assert layout.beat_seconds(3, True) > layout.beat_seconds(3, False)
    assert layout.beat_seconds(8, True) == 4.0


@pytest.mark.parametrize("seconds", [20, 30, 45, 60])
def test_plan_fits_the_requested_length(seconds):
    st = make_story()
    segs = layout.plan(st, seconds)
    total = layout.total_frames(segs) / layout.FPS
    assert total <= seconds + 0.1
    assert segs[0].kind == "title" and segs[0].frames == round(layout.TITLE_S * layout.FPS)
    assert segs[-1].kind == "end" and segs[-1].frames == round(layout.END_S * layout.FPS)
    assert [s.index for s in segs if s.kind == "beat"] == list(range(len(st.beats)))


def test_plan_is_contiguous_and_squeezes_rather_than_stretches():
    st = make_story()
    segs = layout.plan(st, 45)
    for a, b in zip(segs, segs[1:]):
        assert b.start == a.start + a.frames
    short = layout.plan(make_story(3), 60)       # few beats: the reel is shorter than asked, not padded
    assert layout.total_frames(short) / layout.FPS < 20
    tight = layout.plan(st, 18)                  # many beats in little time: every beat still gets a second
    assert all(s.frames >= layout.FPS for s in tight if s.kind == "beat")


def test_session_clock_runs_forward_and_ends_at_the_wall_clock():
    st = make_story()
    segs = layout.plan(st, 45)
    clocks = [layout.clock_at(s, f) for s in segs for f in range(s.frames)]
    assert clocks == sorted(clocks)
    assert clocks[0] == 0 and clocks[-1] == st.totals.wall_clock
    beat = segs[2]
    assert layout.clock_at(beat, 0) == st.beats[1].t
    assert layout.clock_at(beat, beat.frames - 1) == st.beats[2].t


def test_progress_and_counters_follow_the_session_clock():
    st = make_story()
    assert layout.progress(st, 0) == 0 and layout.progress(st, st.totals.wall_clock) == 1
    assert layout.progress(st, st.totals.wall_clock * 2) == 1
    assert layout.counters_at(st, 0) == (0, 0, 0)
    assert layout.counters_at(st, 2600) == (1, 0, 0)
    assert layout.counters_at(st, 4000) == (1, 21, 1)


def test_counters_fall_back_to_the_beats_for_a_story_without_ticks():
    st = make_story()
    st.ticks = []
    assert layout.counters_at(st, 0) == (0, 0, 0)
    assert layout.counters_at(st, 4000)[0] == 1 and layout.counters_at(st, 4000)[2] == 1
    assert layout.counters_at(st, st.totals.wall_clock) == (1, 21, 1)


def test_ticks_are_numbers_thinned_and_closed_with_the_totals():
    totals = Totals(wall_clock=999, commits=70, tests_passed=5, prs_opened=3)
    events = [(float(i), "commit", 1) for i in range(70)] + [(30.0, "test", 5), (40.0, "pr", 1)]
    rows = make_ticks(events, totals)
    assert len(rows) <= 48 and rows[-1] == [999, 70, 5, 3]
    assert all(len(r) == 4 and all(isinstance(x, int) for x in r) for r in rows)
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    assert make_ticks([], Totals(wall_clock=5)) == [[5, 0, 0, 0]]


def test_slide_in_is_six_frames_and_eased():
    assert layout.slide(layout.SLIDE_FRAMES) == (1.0, 0)
    alphas = [layout.slide(f)[0] for f in range(layout.SLIDE_FRAMES)]
    offsets = [layout.slide(f)[1] for f in range(layout.SLIDE_FRAMES)]
    assert alphas == sorted(alphas) and 0 < alphas[0] < alphas[-1] < 1
    assert offsets == sorted(offsets, reverse=True) and offsets[-1] >= 0


def test_keyframes_are_nine_spread_and_include_the_title_and_the_end():
    st = make_story()
    segs = layout.plan(st, 45)
    keys = layout.keyframes(segs, 9)
    assert len(keys) == 9
    assert keys[0][0] == 0 and keys[-1][0] == len(segs) - 1
    assert [k[0] for k in keys] == sorted(set(k[0] for k in keys))
    assert all(0 <= f < segs[i].frames for i, f in keys)
    few = layout.keyframes(layout.plan(make_story(3), 45), 9)
    assert len(few) == 5      # title, three beats, end


# --- layout ------------------------------------------------------------------------------------

def test_columns_follow_the_font_size():
    assert layout.cols(48) >= LINE_MAX            # a full-width story line fits at 48 px
    assert layout.cols(72) < layout.cols(64) < layout.cols(48)


def test_headline_is_big_when_short_and_wraps_when_long():
    pt, rows = layout.fit_headline("21 tests passed")
    assert pt == layout.HEAD_BIG_PT and rows == ["21 tests passed"]
    pt, rows = layout.fit_headline("Add a retry wrapper to the fetch helper for flaky networks")
    assert pt == layout.HEAD_PT and len(rows) <= 3 and all(len(r) <= layout.cols(pt) for r in rows)


def test_wrap_keeps_every_character_and_breaks_long_paths_at_separators():
    text = "…/supabase/functions/tests/tts_realtime_test.ts"
    rows = layout.wrap_text(text, 25)
    assert "".join(rows) == text and all(len(r) <= 25 for r in rows)
    assert rows[0].endswith("/")                   # broken after a slash, not through a word
    blob = "x" * 70
    assert "".join(layout.wrap_text(blob, 25)) == blob


def test_a_beat_card_stays_inside_the_card_band():
    worst = layout.card_layout("edit", "a" * 48, ["l" * LINE_MAX] * LINES_MAX, ["+" + "d" * (LINE_MAX - 1)] * DIFF_MAX)
    for r in worst:
        assert layout.CARD_TOP <= r.y and r.y + r.pt <= layout.CARD_BOTTOM + 4, r
    assert [r.y for r in worst] == sorted(r.y for r in worst)
    ys = [r.y for r in worst]
    assert len(set(ys)) == len(ys)                 # no two rows on the same line


def test_a_small_card_is_set_below_the_top_of_the_band():
    rows = layout.card_layout("test", "21 tests passed", ["pytest"], None)
    assert rows[0].role == "label" and rows[0].y > layout.CARD_TOP
    assert layout.body_pt(["short"], False) > layout.LINE_PT
    assert layout.body_pt(["x" * LINE_MAX], False) == layout.LINE_PT
    assert layout.body_pt(["+" + "x" * 20], True) == layout.LINE_PT


def test_diff_rows_are_tinted_by_their_first_character():
    rows = layout.card_layout("edit", "f.py", [], ["+new", "-old", " same"])
    assert [r.tint for r in rows if r.role == "diff"] == ["add", "del", None]


def test_captions_are_one_srt_cue_per_beat():
    st = make_story()
    segs = layout.plan(st, 45)
    srt = layout.captions(st, segs)
    cues = [c for c in srt.strip().split("\n\n")]
    assert len(cues) == len(st.beats)
    first = cues[0].splitlines()
    assert first[0] == "1" and re.fullmatch(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", first[1])
    assert first[2] == "ASK: The ask" and first[3] == "Add a retry wrapper to the"
    assert layout.timecode(3725.5) == "01:02:05,500"


def test_reel_txt_lists_the_top_bar_then_the_title_then_every_beat():
    st = make_story()
    txt = cards.rendered_strings(st)
    assert txt[:3] == ["demo", "claude", "demo session"]
    assert all(s in txt for b in st.beats for s in cards.beat_strings(b))


# --- drawing -----------------------------------------------------------------------------------

def need_pillow():
    if not render.available()["pillow"]:
        pytest.skip("Pillow is not installed")
    try:
        return render.Fonts.find()
    except render.Missing as e:
        pytest.skip(str(e))


def test_everything_drawn_is_in_reel_txt():
    fonts = need_pillow()
    st = make_story()
    reel = render.Reel(st, 45, fonts)
    for i, seg in enumerate(reel.segs):
        for f in (0, 2, layout.SLIDE_FRAMES, seg.frames - 1):
            reel.frame(i, f)
    allowed = set(cards.rendered_strings(st))
    squash = lambda s: re.sub(r"\s+", "", s)                         # noqa: E731
    assert reel.ledger.content
    for src, drawn in reel.ledger.content:
        assert src in allowed, f"drawn but not in reel.txt: {src!r}"
        assert squash(drawn) == squash(src), f"{src!r} was drawn as {drawn!r}"
    for s in reel.ledger.chrome:
        assert any(rx.fullmatch(s) for rx in render.CHROME_OK), f"unexpected chrome text {s!r}"


def test_drawn_strings_cover_every_beat_string():
    fonts = need_pillow()
    st = make_story()
    reel = render.Reel(st, 45, fonts)
    for i, seg in enumerate(reel.segs):
        reel.frame(i, seg.frames - 1)
    drawn = {src for src, _ in reel.ledger.content}
    for b in st.beats:
        for s in cards.beat_strings(b):
            assert s in drawn, f"never drawn: {s!r}"


def test_a_long_headline_is_drawn_whole():
    fonts = need_pillow()
    st = make_story(2)
    st.beats[1].headline = "…/supabase/functions/tests/tts_realtime_test.ts"
    reel = render.Reel(st, 45, fonts)
    reel.frame(2, reel.segs[2].frames - 1)
    assert any(src == st.beats[1].headline and drawn.replace(" ", "") == src for src, drawn in reel.ledger.content)


def test_contact_sheet_is_a_three_by_three_png(tmp_path):
    fonts = need_pillow()
    reel = render.Reel(make_story(), 45, fonts)
    out = tmp_path / "contact.png"
    reel.contact(out)
    from PIL import Image
    with Image.open(out) as im:
        assert im.size == (3 * 360 + 4 * 12, 3 * 640 + 4 * 12)


def test_frames_are_1080_by_1920_rgb():
    fonts = need_pillow()
    reel = render.Reel(make_story(), 45, fonts)
    assert len(reel.frame_bytes(1, 20)) == 1080 * 1920 * 3
    assert reel.frame(0, 0).size == (1080, 1920)


def test_the_default_output_dir_names_the_day_the_repo_and_the_id():
    d = render.default_dir(make_story())
    assert d.parts[-2] == "teyla-reel" and d.parts[-3] == "Movies"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d-demo-5e55a0f1", d.name)


def test_a_hand_edited_story_cannot_steer_the_output_directory():
    st = make_story()
    st.id, st.repo = "../../etc/cron", "../x/y"
    d = render.default_dir(st)
    assert d.parent.name == "teyla-reel" and ".." not in d.name and "/" not in d.name


# --- the command -------------------------------------------------------------------------------

def write_story(tmp_path, st=None) -> str:
    path = tmp_path / "in.json"
    path.write_text(json.dumps((st or make_story()).to_dict()))
    return str(path)


def test_render_without_pillow_or_ffmpeg_still_writes_the_text_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "available", lambda: {"pillow": False, "ffmpeg": None})
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path), "-o", str(out)])
    err = capsys.readouterr().err
    assert rc == 1 and "Pillow" in err and "ffmpeg" in err
    assert sorted(p.name for p in out.iterdir()) == ["reel.srt", "reel.txt", "story.json"]
    assert (out / "reel.txt").read_text().splitlines()[2] == "demo session"
    assert json.loads((out / "story.json").read_text())["repo"] == "demo"


def test_render_without_ffmpeg_still_writes_the_contact_sheet(tmp_path, monkeypatch, capsys):
    need_pillow()
    real = render.available()
    monkeypatch.setattr(render, "available", lambda: {"pillow": real["pillow"], "ffmpeg": None})
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path), "-o", str(out)])
    assert rc == 1 and "ffmpeg" in capsys.readouterr().err
    assert (out / "contact.png").is_file() and not (out / "reel.mp4").exists()


def test_render_refuses_a_story_that_fails_redaction(tmp_path, capsys):
    st = make_story()
    st.beats[1].headline = "the zebracorp migration"
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path, st), "-o", str(out)])
    assert rc == 1 and "not rendering" in capsys.readouterr().err
    assert not out.exists()


def test_render_refuses_a_string_that_redaction_would_rewrite(tmp_path, capsys):
    st = make_story()
    st.beats[1].lines = ["clone https://user:pass" + "word@example.com/x"[:12]]
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path, st), "-o", str(out)])
    assert rc == 1 and "not rendering" in capsys.readouterr().err
    assert not out.exists()


def test_no_video_skips_the_mp4(tmp_path, capsys):
    need_pillow()
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path), "-o", str(out), "--no-video"])
    assert rc == 0
    assert sorted(p.name for p in out.iterdir()) == ["contact.png", "reel.srt", "reel.txt", "story.json"]


def test_smoke_render_writes_a_playable_mp4(tmp_path, capsys):
    need_pillow()
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not on PATH")
    out = tmp_path / "out"
    rc = cli.main(["reel", "render", write_story(tmp_path, make_story(4)), "-o", str(out), "--seconds", "12"])
    assert rc == 0, capsys.readouterr().err
    mp4 = out / "reel.mp4"
    assert mp4.stat().st_size > 10_000 and mp4.read_bytes()[4:8] == b"ftyp"
    assert sorted(p.name for p in out.iterdir()) == ["contact.png", "reel.mp4", "reel.srt", "reel.txt", "story.json"]
    if shutil.which("ffprobe"):
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,pix_fmt,r_frame_rate",
                                "-of", "default=nw=1", str(mp4)], capture_output=True, text=True).stdout
        assert "width=1080" in probe and "height=1920" in probe and "pix_fmt=yuv420p" in probe and "30/1" in probe
