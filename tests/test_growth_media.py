"""`teyla growth` episodes: ride, ingest, cut, daily and the 06:30 agent. Fakes only: no real ffmpeg, whisper,
claude, gh or launchctl runs, and nothing is published or sent."""
from __future__ import annotations

import json
import os
import pathlib
import plistlib

import pytest

from teyla import cli, config, growth, growth_media as gm, net, routine_install as ri
from test_growth import DAY, GOOD, NOW, TERM, env, fake_model, make, master  # noqa: F401  (env is a fixture)

CLIP = dict(GOOD, hook="Alpha now syncs faster.", body="Alpha now syncs faster. The merged change cut the sync step.",
            segments=[dict(start=2, end=9, caption="The sync step is gone"), dict(start=20, end=26, caption="Faster on a watch")])
CHANNELS = ("youtube-en", "instagram-en", "tiktok-en")


@pytest.fixture
def media(env, monkeypatch):
    monkeypatch.setattr(gm, "load_blockers", lambda: [])
    monkeypatch.setattr(growth.time, "time", lambda: NOW)
    return env


def fake_tool(calls, writes=True):
    def run(argv, timeout):
        calls.append(list(argv))
        if writes and argv[0] == "ffmpeg":
            pathlib.Path(argv[-1]).write_bytes(b"mp4")
        return 0, ""
    return run


def episode(store, footage=True, transcript="[0.0-5.0] We merged the sync fix today.", seconds=40.0, **extra):
    it = growth.make_item(store, NOW, kind="episode", format="true-vibe-coding", idea="Can an agent fix sync in one ride?",
                          facts=["Can an agent fix sync in one ride?"], scores=dict(relevance=4, demonstrable=5, novelty=4, momentum=3),
                          ride=dict(question="Can an agent fix sync in one ride?", job="", started=growth.iso(NOW - 3600),
                                    ended=growth.iso(NOW), sessions=[]), **extra)
    if footage:
        it["footage"] = [dict(path="/x/clip.mov", ref="footage:clip.mov:1:1", seconds=seconds, transcript=transcript)]
        it["status"] = "draft"
    store.save(it, NOW)
    return it


# --- the ride ---------------------------------------------------------------------------------------------------

def test_ride_records_question_job_clock_and_active_sessions(media, monkeypatch):
    store, cfg = make(channels=("x-en",))
    monkeypatch.setattr(growth, "_sessions", lambda d: [dict(sid="s1", harness="claude", last=growth.iso(NOW - 600)),
                                                       dict(sid="s2", harness="codex", last=growth.iso(NOW - 7200))])
    it, notes = gm.ride_start(store, cfg, NOW, "  Can I   ship in a day? ", "ship the sync fix")
    got = growth.Store().get(it["id"])
    assert got["kind"] == "episode" and got["ride"]["question"] == "Can I ship in a day?" and got["ride"]["job"] == "ship the sync fix"
    assert got["ride"]["started"] == growth.iso(NOW) and got["ride"]["ended"] is None
    assert got["ride"]["sessions"] == [dict(sid="s1", harness="claude")] and notes == []
    done = gm.ride_end(growth.Store(), NOW + 1800)
    assert done["ride"]["ended"] == growth.iso(NOW + 1800) and done["ride"]["minutes"] == 30.0
    assert [r["ev"] for r in growth.Store().ledger()] == ["ride-start", "ride-end"]


def test_ride_reports_blockers_and_refuses_nothing(media, monkeypatch):
    store, cfg = make(channels=("x-en",))
    monkeypatch.setattr(gm, "load_blockers", lambda: ["machine load BUSY: swap high", "disk: 3.0 GB free, under 5 GB"])
    first, _ = gm.ride_start(store, cfg, NOW, "First?")
    second, notes = gm.ride_start(store, cfg, NOW + 60, "Second?")
    assert first["id"] != second["id"]
    assert any("BUSY" in n for n in notes) and any("disk" in n for n in notes) and any(first["id"] in n and "still open" in n for n in notes)
    assert gm.open_ride(growth.Store())["id"] == second["id"]


def test_ride_flags_a_question_the_guard_would_block(media):
    store, cfg = make(channels=("x-en",))
    _, notes = gm.ride_start(store, cfg, NOW, f"What does {TERM} do?")
    assert any("private-term" in n for n in notes)


def test_ride_end_without_a_ride_and_empty_question_are_usage_errors(media):
    store, cfg = make(channels=("x-en",))
    with pytest.raises(growth.GrowthError, match="no open ride"):
        gm.ride_end(store, NOW)
    with pytest.raises(growth.GrowthError, match="stakes question"):
        gm.ride_start(store, cfg, NOW, "   ")


def test_load_blockers_names_a_busy_machine_and_low_disk(env, monkeypatch):
    import types
    from teyla import load
    snap = types.SimpleNamespace(disk_free_bytes=2 * 1024 ** 3)
    monkeypatch.setattr(load, "safe_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(load, "assess", lambda *a, **k: types.SimpleNamespace(level=load.BUSY, reasons=["swap 9 GB"]))
    monkeypatch.setattr(load, "current_trend", lambda *a, **k: None)
    out = gm.load_blockers()
    assert any("BUSY" in x for x in out) and any("disk: 2.0 GB" in x for x in out)


def test_episodes_never_become_masters_or_review_rows(media, capsys):
    store, cfg = make(channels=("x-en",))
    ep = episode(store, footage=False)
    ep["status"] = "idea"
    ep["platform"] = growth.MASTER
    store.save(ep, NOW)
    assert growth.available_masters(store, cfg) == []
    ep["status"] = "checked"
    store.save(ep, NOW)
    assert cli.main(["growth", "review"]) == 0 and "nothing waits" in capsys.readouterr().out


# --- ingest -----------------------------------------------------------------------------------------------------

def footage_dir(tmp_path, files):
    d = tmp_path / "icloud"
    d.mkdir()
    for name, mtime in files:
        f = d / name
        f.write_bytes(b"x" + name.encode())
        os.utime(f, (mtime, mtime))
    (d / "notes.txt").write_text("not video")
    (d / ".hidden.mov").write_bytes(b"h")
    return d


def test_ingest_joins_the_ride_window_dedupes_and_names_the_whisper_line(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("youtube-en",))
    monkeypatch.setattr(gm, "probe_seconds", lambda p: 31.5)
    monkeypatch.setattr(gm, "whisper_bin", lambda: None)
    monkeypatch.setattr(gm, "run_tool", lambda argv, timeout: (_ for _ in ()).throw(AssertionError("nothing may run without whisper")))
    ride, _ = gm.ride_start(store, cfg, NOW, "Can I film a ride?")
    d = footage_dir(tmp_path, [("IMG_1.MOV", NOW + 120), ("IMG_2.mp4", NOW - 86400 * 3)])
    res = gm.ingest(growth.Store(), cfg, NOW + 300, d)
    assert res["files"] == 2 and len(res["episodes"]) == 2 and ride["id"] in res["episodes"]
    assert any("brew install whisper-cpp" in n for n in res["notes"])
    inside = growth.Store().get(ride["id"])
    assert inside["status"] == "draft" and inside["footage"][0]["seconds"] == 31.5 and inside["footage"][0]["path"].endswith("IMG_1.MOV")
    again = gm.ingest(growth.Store(), cfg, NOW + 400, d)
    assert again["files"] == 0 and again["episodes"] == []


def test_ingest_transcribes_only_when_whisper_and_a_model_exist(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("youtube-en",))
    model = tmp_path / "ggml.bin"
    model.write_bytes(b"m")
    cfg["whisper_model"] = str(model)
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        if argv[0].endswith("whisper-cli"):
            pathlib.Path(argv[argv.index("-of") + 1] + ".srt").write_text("1\n00:00:01,000 --> 00:00:04,000\nWe merged the sync fix.\n")
        return 0, ""
    monkeypatch.setattr(gm, "run_tool", run)
    monkeypatch.setattr(gm, "whisper_bin", lambda: "/opt/bin/whisper-cli")
    monkeypatch.setattr(gm, "probe_seconds", lambda p: 12.0)
    res = gm.ingest(store, cfg, NOW, footage_dir(tmp_path, [("a.mov", NOW)]))
    ep = growth.Store().get(res["episodes"][0])
    assert "We merged the sync fix." in ep["footage"][0]["transcript"] and res["notes"] == []
    assert [c[0] for c in calls] == ["ffmpeg", "/opt/bin/whisper-cli"]
    assert not list((growth.Store().root / "episodes" / ep["id"]).glob("audio.wav"))


def test_ingest_without_a_folder_or_with_a_bad_one_says_what_to_set(media, tmp_path):
    store, cfg = make(channels=("youtube-en",))
    with pytest.raises(growth.GrowthError, match="footage_folder"):
        gm.ingest(store, cfg, NOW, gm.footage_folder(cfg))
    with pytest.raises(growth.GrowthError, match="not a folder"):
        gm.ingest(store, cfg, NOW, tmp_path / "nope")


def test_the_srt_parser_and_the_segment_validator():
    rows = gm.parse_srt("1\n00:00:01,000 --> 00:00:04,500\nHello there\n\n2\n00:01:00,000 --> 00:01:02,000\nLine one\nLine two\n")
    assert rows == [(1.0, 4.5, "Hello there"), (60.0, 62.0, "Line one Line two")]
    raw = [dict(start=0, end=40, caption="x" * 90), dict(start=50, end=50.4), dict(start="a", end=3), dict(start=-1, end=5),
           dict(start=41, end=60), dict(start=3, end=9, caption="ok")]
    segs = gm.valid_segments(raw, 45.0)
    assert [(x["start"], x["end"]) for x in segs] == [(0, 15), (41, 45), (3, 9)] and len(segs[0]["caption"]) <= 60
    assert sum(x["end"] - x["start"] for x in segs) <= 60
    many = [dict(start=i * 10, end=i * 10 + 5, caption="c") for i in range(20)]
    assert len(gm.valid_segments(many, None)) == 8
    assert gm.valid_segments("junk", 10) == [] and gm.valid_segments(None, 10) == []


# --- the cut ----------------------------------------------------------------------------------------------------

def test_cut_with_footage_renders_and_lands_every_clip_in_review(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store)
    calls = []
    fm = fake_model([CLIP])
    monkeypatch.setattr(growth, "call_model", fm)
    monkeypatch.setattr(gm, "run_tool", fake_tool(calls))
    monkeypatch.setattr(gm, "has_audio", lambda p: True)
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"png") or True)
    row = gm.cut(store, cfg, ep["id"], NOW)
    assert fm.calls[0]["system"] == gm.CUT_SYSTEM and "We merged the sync fix" in fm.calls[0]["payload"]["transcript"]
    assert fm.calls[0]["payload"]["footage_seconds"] == 40.0 and fm.calls[0]["model"] == cfg["model_script"]
    ff = calls[-1]
    assert ff[0] == "ffmpeg" and ff[2:4] == ["-v", "error"] and "/x/clip.mov" in ff and ff[-1].endswith("cut-1.part.mp4")
    graph = ff[ff.index("-filter_complex") + 1]
    assert "trim=start=2.0:end=9.0" in graph and "concat=n=2:v=1:a=1" in graph and "overlay=0:H-h-300:enable='between(t,0.00,7.00)'" in graph
    assert "between(t,7.00,13.00)" in graph and "1080:1920" in graph
    assert len(row["items"]) == 3 and {i["status"] for i in row["items"]} == {"review"}
    s2 = growth.Store()
    for i in row["items"]:
        it = s2.get(i["id"])
        assert it["status"] == "review" and it["media"] == [row["video"]] and it["parent"] == ep["id"] and it["language"] == "en"
        assert it["voice_check"]["ok"] and it["leak_check"]["ok"] and it["day"] == DAY
    done = s2.get(ep["id"])
    assert done["status"] == "checked" and done["cut"]["footage"] is True and done["cut"]["segments"] == 2
    assert not any(i["status"] in ("approved", "ready", "published") for i in s2.items().values())
    assert pathlib.Path(row["video"]).stat().st_mode & 0o077 == 0 and (s2.root / "episodes" / ep["id"] / "cut-1.srt").is_file()
    assert row["video"].endswith("cut-1.mp4") and not list((s2.root / "episodes" / ep["id"]).glob("*.part.mp4"))
    d = s2.root / "episodes" / ep["id"]
    assert gm.next_cut_number(d) == 2 and gm.next_cut_number(d) == 3, "a number is reserved the moment it is handed out"
    assert not list((s2.root / "episodes" / ep["id"]).glob("cap*.png"))


def test_cut_stops_before_the_model_when_the_transcript_leaks(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store, transcript=f"[0.0-3.0] {TERM} is the plan")
    fm = fake_model([CLIP])
    monkeypatch.setattr(growth, "call_model", fm)
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    with pytest.raises(growth.GrowthError, match="private-term"):
        gm.cut(store, cfg, ep["id"], NOW)
    assert fm.calls == []


def test_cut_stops_before_rendering_when_a_caption_leaks(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store)
    bad = dict(CLIP, segments=[dict(start=1, end=6, caption=f"Ask about {TERM}")])
    monkeypatch.setattr(growth, "call_model", fake_model([bad]))
    calls = []
    monkeypatch.setattr(gm, "run_tool", fake_tool(calls))
    with pytest.raises(growth.GrowthError, match="caption would leak"):
        gm.cut(store, cfg, ep["id"], NOW)
    assert calls == []


def test_cut_without_usable_segments_or_ffmpeg_output_fails_cleanly(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store)
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(growth, "call_model", fake_model([dict(CLIP, segments=[])]))
    with pytest.raises(growth.GrowthError, match="no usable segments"):
        gm.cut(store, cfg, ep["id"], NOW)
    monkeypatch.setattr(growth, "call_model", fake_model([CLIP]))
    monkeypatch.setattr(gm, "run_tool", fake_tool([], writes=False))
    monkeypatch.setattr(gm, "caption_png", lambda text, path: False)
    with pytest.raises(growth.GrowthError, match="ffmpeg failed"):
        gm.cut(store, cfg, ep["id"], NOW)
    assert growth.Store().get(ep["id"])["status"] == "draft"


def test_a_session_only_cut_fills_the_slots_without_footage(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store, footage=False)
    ep["ride"]["sessions"] = [dict(sid="s1", harness="claude")]
    store.save(ep, NOW)
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"mp4")
    fm = fake_model([dict(CLIP, segments=[])])
    monkeypatch.setattr(growth, "call_model", fm)
    seen = {}
    monkeypatch.setattr(gm, "session_story", lambda sid: seen.setdefault("sid", sid) and (object(), ""))
    monkeypatch.setattr(gm, "story_strings", lambda story: ["Agent fixed the sync step", "Tests passed"])
    monkeypatch.setattr(gm, "render_session", lambda story, d, n=1: (mp4, ""))
    row = gm.cut(store, cfg, ep["id"], NOW)
    assert seen["sid"] == "s1" and fm.calls[0]["payload"]["session_outline"] == ["Agent fixed the sync step", "Tests passed"]
    assert fm.calls[0]["payload"]["transcript"] == "" and {i["status"] for i in row["items"]} == {"review"}
    assert growth.Store().get(ep["id"])["cut"]["footage"] is False


def test_a_session_only_cut_needs_a_session_and_refuses_a_leaking_story(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store, footage=False)
    monkeypatch.setattr(growth, "call_model", fake_model([CLIP]))
    with pytest.raises(growth.GrowthError, match="no footage and no session"):
        gm.cut(store, cfg, ep["id"], NOW)
    fm = fake_model([CLIP])
    monkeypatch.setattr(growth, "call_model", fm)
    monkeypatch.setattr(gm, "session_story", lambda sid: (object(), ""))
    monkeypatch.setattr(gm, "story_strings", lambda story: [f"Edited {TERM}"])
    with pytest.raises(growth.GrowthError, match="session story would leak"):
        gm.cut(store, cfg, ep["id"], NOW, session="s9")
    assert fm.calls == []


def test_cut_marks_a_blocked_clip_failed_and_keeps_the_rest(media, monkeypatch):
    store, cfg = make(channels=("youtube-en", "tiktok-en"))
    ep = episode(store)
    long_hook = dict(CLIP, hook="x" * 140, body="x" * 140 + " Alpha.")
    monkeypatch.setattr(growth, "call_model", fake_model([long_hook]))
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"p") or True)
    row = gm.cut(store, cfg, ep["id"], NOW)
    by = {i["channel"]: i for i in row["items"]}
    assert by["youtube-en"]["status"] == "failed" and "title" in by["youtube-en"]["reason"]
    assert by["tiktok-en"]["status"] == "review"
    assert growth.Store().get(ep["id"])["status"] == "checked"


def test_cut_takes_over_an_unfilled_slot_and_frees_the_masters_seat(media, monkeypatch):
    store, cfg = make(channels=("youtube-en",))
    m = master(store, idea="Merged in Alpha: faster sync")
    (slot,) = [r["item"] for r in growth.plan(store, cfg, DAY, NOW) if r["item"]]
    assert growth.Store().get(m["id"])["assigned"] == ["youtube-en"]
    ep = episode(growth.Store())
    monkeypatch.setattr(growth, "call_model", fake_model([CLIP]))
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"p") or True)
    row = gm.cut(growth.Store(), cfg, ep["id"], NOW)
    s2 = growth.Store()
    assert [i["id"] for i in row["items"]] == [slot["id"]] and s2.get(slot["id"])["parent"] == ep["id"]
    assert s2.get(m["id"])["assigned"] == []
    assert sum(1 for i in s2.items().values() if i.get("channel") == "youtube-en" and i["kind"] != "episode") == 1


def test_cut_refuses_what_is_not_an_episode_or_has_no_video_channel(media):
    store, cfg = make(channels=("youtube-en",))
    m = master(store)
    with pytest.raises(growth.GrowthError, match="not an episode"):
        gm.cut(store, cfg, m["id"], NOW)
    store2, cfg2 = make(channels=("x-en",))
    ep = episode(store2)
    with pytest.raises(growth.GrowthError, match="video channel"):
        gm.cut(store2, cfg2, ep["id"], NOW)


def test_ffmpeg_command_without_audio_or_captions_has_no_overlay():
    cmd = gm.ffmpeg_command("in.mov", [dict(start=0, end=5, caption="")], [None], "out.mp4", False)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" not in graph and "a=0" in graph and "-c:a" not in cmd and cmd[-1] == "out.mp4"


def test_the_caption_png_is_a_real_transparent_picture(tmp_path):
    PIL = pytest.importorskip("PIL")
    p = tmp_path / "c.png"
    assert gm.caption_png("The sync step is gone and the watch is faster than before", p)
    img = PIL.Image.open(p)
    assert img.mode == "RGBA" and img.width == gm.W and p.stat().st_mode & 0o077 == 0


# --- daily ------------------------------------------------------------------------------------------------------

def test_daily_runs_in_order_and_each_step_fails_on_its_own(media, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store)
    order = []
    real_plan, real_trends = growth.plan, growth.run_trends
    monkeypatch.setattr(growth, "harvest", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gh is down")))
    monkeypatch.setattr(growth, "run_trends", lambda *a, **k: order.append("trends") or real_trends(*a, **k))
    monkeypatch.setattr(growth, "plan", lambda *a, **k: order.append("plan") or real_plan(*a, **k))
    monkeypatch.setattr(growth, "call_model", fake_model([GOOD]))
    res = gm.daily(store, cfg, NOW, quiet=True)
    assert [s[0] for s in res["steps"]] == ["harvest", "trends", "plan", "draft"]
    assert [s[1] for s in res["steps"]] == ["failed", "ok", "ok", "ok"] and res["failed"] == 1
    assert "gh is down" in res["steps"][0][2] and order == ["trends", "plan", "plan"]
    s2 = growth.Store()
    assert [i["status"] for i in s2.items().values() if i["platform"] == "x"] == ["review"]
    assert s2.ledger()[-1]["ev"] == "daily"


def test_daily_skips_the_model_in_safe_mode_and_prints_a_line_per_step(media, monkeypatch):
    store, cfg = make(channels=("x-en",))
    master(store)
    monkeypatch.setattr(net, "gate", lambda *a, **k: False)
    fm = fake_model([GOOD])
    monkeypatch.setattr(growth, "call_model", fm)
    lines = []
    res = gm.daily(store, cfg, NOW, out=lines.append)
    assert fm.calls == [] and res["failed"] == 0 and res["steps"][3][2] == "skipped: safe mode" and len(lines) == 4


def test_daily_cli_exit_codes(media, monkeypatch, capsys):
    assert cli.main(["growth", "daily"]) == 2 and "teyla growth init" in capsys.readouterr().err
    make(channels=("x-en",))
    monkeypatch.setattr(growth, "call_model", fake_model([GOOD]))
    assert cli.main(["growth", "daily", "--quiet"]) == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr(growth, "harvest", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert cli.main(["growth", "daily", "--quiet"]) == 1


def test_the_episode_loop_through_the_command_line(media, monkeypatch, capsys, tmp_path):
    make(channels=CHANNELS, extra=f'footage_folder = "{tmp_path / "icloud"}"')
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(gm, "probe_seconds", lambda p: 40.0)
    monkeypatch.setattr(gm, "whisper_bin", lambda: None)
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"p") or True)
    monkeypatch.setattr(growth, "call_model", fake_model([CLIP]))
    footage_dir(tmp_path, [("IMG_9.MOV", NOW + 60)])
    assert cli.main(["growth", "ride", "Can", "I", "ship", "--job", "sync fix"]) == 0
    assert "started: Can I ship (job: sync fix)" in capsys.readouterr().out
    assert cli.main(["growth", "ride", "--end"]) == 0
    assert cli.main(["growth", "ingest"]) == 0 and "1 new file(s)" in capsys.readouterr().out
    ep = next(i for i in growth.Store().items().values() if i["kind"] == "episode")
    ep["footage"][0]["transcript"] = "1\n00:00:01,000 --> 00:00:04,000\nWe merged the sync fix.\n"
    growth.Store().save(ep, NOW)
    sec = growth.section(NOW)
    assert sec["pipeline"]["cutting"] == 1 and sec["pipeline"]["filming"] == 0 and sec["episodes"][0]["stage"] == "cutting"
    assert sec["episodes"][0]["question"] == "Can I ship" and sec["episodes"][0]["footage"] == 1
    assert cli.main(["growth", "cut", ep["id"]]) == 0
    assert "nothing is published" in capsys.readouterr().out
    sec = growth.section(NOW)
    assert sec["pipeline"]["review"] == 3 and sec["episodes"][0]["stage"] == "cut" and sec["episodes"][0]["clips"] == 3
    assert sec["pipeline"]["ideas"] == 0


def test_the_open_ride_counts_as_filming_in_the_console_section(media):
    store, cfg = make(channels=("x-en",))
    gm.ride_start(store, cfg, NOW, "Filming now?")
    sec = growth.section(NOW)
    assert sec["pipeline"]["filming"] == 1 and sec["pipeline"]["ideas"] == 0
    assert growth.compact(sec)["pipeline"]["filming"] == 1


# --- the 06:30 agent --------------------------------------------------------------------------------------------

class Home(type(pathlib.Path())):
    """A Path that also carries the recorded launchctl calls."""


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = Home(tmp_path / "home")
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    for name, rel in (("PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Library/Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Library/Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(ri, name, home / rel)
    monkeypatch.setattr(ri, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    monkeypatch.setattr(ri, "sys", type("S", (), {"platform": "darwin", "argv": ["teyla"]}))
    loads = []
    monkeypatch.setattr(ri, "_load", lambda plist, label: loads.append(label) or f"loaded {label}")
    monkeypatch.setattr(ri, "_unload", lambda plist, label: f"unloaded {label}")
    monkeypatch.setattr(ri, "loaded", lambda label: (label in loads, None, "0" if label in loads else None))
    monkeypatch.setattr(ri.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launchctl called")))
    home.loads = loads
    return home


def test_the_growth_agent_is_off_by_default_and_writes_nothing(home):
    assert not ri.optional_enabled(ri.GROWTH_LABEL)
    ri.install()
    assert not ri.optional_paths(ri.GROWTH_LABEL)["plist"].exists() and ri.GROWTH_LABEL not in home.loads
    assert not ri.is_stale()
    assert f"{ri.GROWTH_LABEL}: off ([growth] daily = false)" in ri.status()


def test_the_growth_agent_runs_at_0630_when_the_config_asks(home):
    config.set_value("growth.daily", "true")
    assert ri.optional_enabled(ri.GROWTH_LABEL) and ri.is_stale()
    ri.install()
    p = ri.optional_paths(ri.GROWTH_LABEL)
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["Label"] == "com.zaitsew.teyla.growth" and plist["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    assert "StartInterval" not in plist and plist["StandardOutPath"] == str(home / "Library/Logs/teyla-growth.log")
    text = p["wrapper"].read_text()
    assert '"$TEYLA" growth daily --quiet' in text and "because [growth] daily is on" in text and ri.GROWTH_LABEL in home.loads
    assert not ri.is_stale() and ri.every(ri.GROWTH_LABEL) == "daily at 06:30"
    assert "daily at 06:30" in "\n".join(ri.status())
    config.set_value("growth.daily", "false")
    assert ri.is_stale()
    ri.install()
    assert not p["plist"].exists() and not p["wrapper"].exists()


def test_another_tables_flag_does_not_switch_the_growth_agent_on(home):
    config.set_value("storage.sims_agent", "true")
    assert not ri.optional_enabled(ri.GROWTH_LABEL)
    assert ri.every(ri.SIMS_LABEL) == "every 10 min"


def test_a_recut_never_replaces_the_video_an_earlier_clip_points_to(media, monkeypatch):
    store, cfg = make(channels=("youtube-en",))
    ep = episode(store)
    monkeypatch.setattr(growth, "call_model", fake_model([CLIP]))
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"p") or True)
    first = gm.cut(store, cfg, ep["id"], NOW)
    growth.approve(growth.Store(), first["items"][0]["id"], NOW)
    first_video = pathlib.Path(first["video"])
    first_video.write_bytes(b"approved footage")
    second = gm.cut(growth.Store(), cfg, ep["id"], NOW)
    assert second["video"] != first["video"] and second["video"].endswith("cut-2.mp4")
    assert first_video.read_bytes() == b"approved footage"
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert growth.Store().get(first["items"][0]["id"])["status"] == "approved"
    monkeypatch.setattr(gm, "run_tool", fake_tool([], writes=False))
    with pytest.raises(growth.GrowthError, match="ffmpeg failed"):
        gm.cut(growth.Store(), cfg, ep["id"], NOW)
    assert first_video.read_bytes() == b"approved footage"


def test_footage_without_a_transcript_is_not_cut(media, monkeypatch):
    store, cfg = make(channels=CHANNELS)
    ep = episode(store, transcript="")
    fm = fake_model([CLIP])
    monkeypatch.setattr(growth, "call_model", fm)
    with pytest.raises(growth.GrowthError, match="no transcript"):
        gm.cut(store, cfg, ep["id"], NOW)
    assert fm.calls == []


def test_a_clip_may_quote_a_number_that_was_said_or_shown(media, monkeypatch):
    store, cfg = make(channels=("youtube-en",))
    ep = episode(store, transcript="1\n00:00:01,000 --> 00:00:04,000\nThe sync dropped from 40 seconds to 12 seconds.\n")
    said = dict(CLIP, hook="Sync fell from 40 to 12 seconds.", body="Sync fell from 40 to 12 seconds. One agent, one ride.")
    monkeypatch.setattr(growth, "call_model", fake_model([said]))
    monkeypatch.setattr(gm, "run_tool", fake_tool([]))
    monkeypatch.setattr(gm, "caption_png", lambda text, path: path.write_bytes(b"p") or True)
    row = gm.cut(store, cfg, ep["id"], NOW)
    assert row["items"][0]["status"] == "review"


def test_reingest_fills_the_transcript_after_whisper_is_installed(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("youtube-en",))
    monkeypatch.setattr(gm, "probe_seconds", lambda p: 12.0)
    monkeypatch.setattr(gm, "whisper_bin", lambda: None)
    d = footage_dir(tmp_path, [("a.mov", NOW)])
    first = gm.ingest(store, cfg, NOW, d)
    ep_id = first["episodes"][0]
    assert growth.Store().get(ep_id)["footage"][0]["transcript"] == ""
    model = tmp_path / "ggml.bin"
    model.write_bytes(b"m")
    cfg["whisper_model"] = str(model)

    def run(argv, timeout):
        if argv[0].endswith("whisper-cli"):
            pathlib.Path(argv[argv.index("-of") + 1] + ".srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nHello from the ride.\n")
        return 0, ""
    monkeypatch.setattr(gm, "run_tool", run)
    monkeypatch.setattr(gm, "whisper_bin", lambda: "/opt/bin/whisper-cli")
    again = gm.ingest(growth.Store(), cfg, NOW + 5, d)
    assert again["files"] == 1 and "Hello from the ride." in growth.Store().get(ep_id)["footage"][0]["transcript"]
    assert gm.ingest(growth.Store(), cfg, NOW + 9, d)["files"] == 0
