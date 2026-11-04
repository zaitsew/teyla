"""The daily video: a video channel never gets a text post, and on a day with no clip one vertical screen video is
rendered from a real session and checked frame by frame. Fakes only: no real ffmpeg, ffprobe, OCR helper, claude or
teyla load runs, and nothing is published or sent."""
from __future__ import annotations

import pathlib
import sys

import pytest

from teyla import cli, growth, growth_media as gm, net
from teyla.reel.story import Beat, Story, Totals
from test_growth import DAY, GOOD, NOW, TERM, env, fake_model, make, master  # noqa: F401  (env is a fixture)
from test_growth_media import CHANNELS, CLIP, media  # noqa: F401  (media is a fixture)


def story(repo="alpha", commits=2, tests=14, beats=4, **tot):
    return Story(id="s1", harness="claude", repo=repo, started="2026-11-03T10:00:00Z", ended="2026-11-03T10:30:00Z", ask="Fix the sync step",
                 title="Fix the sync step", beats=[Beat(t=i * 60, kind="step", headline=f"Step {i}", lines=["ran a thing"]) for i in range(beats)],
                 totals=Totals(commits=commits, tests_passed=tests, **tot))


class Machine:
    """Stands in for ffmpeg, ffprobe, the OCR helper and `teyla load --wait`; records every argv."""

    def __init__(self, seconds=24.0, size="1080x1920", ocr_text="Step 1  ran a thing", wait=0, frames=5, ocr=True):
        self.calls, self.seconds, self.size, self.ocr_text, self.wait, self.frames, self.ocr = [], seconds, size, ocr_text, wait, frames, ocr

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if argv[0] == "ffprobe":
            return (0, f"{self.seconds}") if "format=duration" in argv else (0, self.size)
        if argv[0] == "ffmpeg":
            out = pathlib.Path(argv[-1])
            if "%02d" in out.name:
                for k in range(1, self.frames + 1):
                    (out.parent / f"f{k:02d}.png").write_bytes(b"png")
            else:
                out.write_bytes(b"mp4")
            return 0, ""
        if argv[:3] == [sys.executable, "-m", "teyla"]:
            return self.wait, ""
        if argv[0].endswith("/ocr"):
            return (0, "\n".join(f"{i}\t{self.ocr_text}" for i in range(len(argv) - 1))) if self.ocr else (1, "")
        return 0, ""


def set_up(monkeypatch, tmp_path, machine=None, sessions=None, st=None, ocr_helper=True):
    machine = machine or Machine()
    monkeypatch.setattr(gm, "run_tool", machine)
    monkeypatch.setattr(gm, "probe_seconds", lambda p: machine.seconds)
    helper = tmp_path / "ocr"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    monkeypatch.setattr(gm, "ocr_helper", lambda: helper if ocr_helper else None)
    monkeypatch.setattr(growth, "_sessions", lambda days: sessions if sessions is not None else [dict(sid="sess-1", harness="claude", project="alpha",
                                                                                                       last=growth.iso(NOW - 3600), prs=[])])
    monkeypatch.setattr(gm, "session_story", lambda sid, seconds=45: (st or story(), ""))
    monkeypatch.setattr(gm, "story_strings", lambda s: ["Fixed the sync step", "14 tests passed"])

    def render(s, d, n=1, seconds=45):
        mp4 = d / f"reel-{n}" / "reel.mp4"
        mp4.parent.mkdir(parents=True, exist_ok=True)
        mp4.write_bytes(b"mp4")
        return mp4, ""
    monkeypatch.setattr(gm, "render_session", render)
    monkeypatch.setattr(growth, "call_model", fake_model([dict(CLIP, segments=[])]))
    return machine


def clips(store, day=DAY):
    return [i for i in store.items().values() if i["kind"] == "clip" and i.get("day") == day]


# --- plan: a video channel is never a text post ---------------------------------------------------------------------

def test_a_video_channel_without_a_clip_is_a_gap_with_the_reason_not_a_text_post(media):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    master(store)
    rows = growth.plan(store, cfg, DAY, NOW)
    by = {r["channel"]: r for r in rows}
    assert by["x-en"]["item"] and all(by[c]["item"] is None for c in CHANNELS)
    assert "no video yet" in by["youtube-en"]["gap"]
    assert not [i for i in growth.Store().items().values() if i["platform"] in ("youtube", "instagram", "tiktok")]
    text = growth.render_plan(rows, DAY, None)
    assert "youtube-en     gap: no video yet" in text and "no idea left" not in text


def test_a_clip_with_its_video_fills_the_slot_and_a_held_or_videoless_one_does_not(media, tmp_path):
    store, cfg = make(channels=("youtube-en", "tiktok-en"))
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"x")
    ok = growth.make_item(store, NOW, kind="clip", format="worklog", idea="a", platform="youtube", language="en", day=DAY, channel="youtube-en",
                          media=[str(mp4)], status="review")
    held = growth.make_item(store, NOW, kind="clip", format="worklog", idea="b", platform="tiktok", language="en", day=DAY, channel="tiktok-en",
                            media=[str(mp4)], status="draft", hold_reason="a frame would leak")
    store.save(ok, NOW)
    store.save(held, NOW)
    by = {r["channel"]: r for r in growth.plan(growth.Store(), cfg, DAY, NOW)}
    assert by["youtube-en"]["item"]["id"] == ok["id"] and by["tiktok-en"]["item"] is None
    mp4.unlink()
    assert growth.plan(growth.Store(), cfg, DAY, NOW)[0]["item"] is None                # the file is gone: not a clip


def test_a_videoless_clip_is_held_with_no_model_call(media, monkeypatch):
    store, cfg = make(channels=("tiktok-en",))
    it = growth.make_item(store, NOW, kind="clip", format="worklog", idea="a", platform="tiktok", language="en", day=DAY, channel="tiktok-en")
    store.save(it, NOW)
    fm = fake_model([GOOD])
    monkeypatch.setattr(growth, "call_model", fm)
    res = growth.run_draft(store, cfg, NOW, limit=5, day=None, dry=False)
    got = growth.Store().get(it["id"])
    assert fm.calls == [] and fm.editor_calls == [] and got["status"] == "draft" and "no video to post" in got["hold_reason"]
    assert res["rows"][0]["state"] == "draft"


def test_the_slot_report_names_the_video_gap_from_the_video_step(media):
    store, cfg = make(channels=("youtube-en",))
    rep = growth.slot_report(store, cfg, DAY)
    assert rep["filled"] == 0 and "no video yet" in rep["rows"][0]["why"]
    store.log("video", NOW, state="gap", reason="no recent session to film in the last 2 days")
    assert "no recent session" in growth.slot_report(growth.Store(), cfg, DAY)["rows"][0]["why"]


# --- the frame gate -------------------------------------------------------------------------------------------------

def test_a_clean_video_passes_and_three_frames_are_kept(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    m = set_up(monkeypatch, tmp_path)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"mp4")
    assert gm.frame_gate(video, tmp_path, growth.Guard(cfg)) == "" and video.exists()
    kept = sorted((tmp_path / "frames-reel").glob("f*.png"))
    assert [f.name for f in kept] == ["f01.png", "f03.png", "f05.png"] and all(f.stat().st_mode & 0o077 == 0 for f in kept)
    assert ["ffmpeg"] == [c[0] for c in m.calls if c[0] == "ffmpeg"] and any(c[0].endswith("/ocr") for c in m.calls)


@pytest.mark.parametrize("kw,why", [(dict(seconds=45.0), "runs 45 s"), (dict(seconds=6.0), "runs 6 s"), (dict(size="1920x1080"), "1920x1080, not 1080x1920"),
                                    (dict(frames=2), "frames could not be taken"), (dict(ocr=False), "not read back")])
def test_a_video_out_of_range_or_unreadable_stays_out_of_review(media, monkeypatch, tmp_path, kw, why):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, machine=Machine(**kw))
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"mp4")
    assert why in gm.frame_gate(video, tmp_path, growth.Guard(cfg))


def test_no_ocr_helper_means_the_video_is_not_trusted(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, ocr_helper=False)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"mp4")
    assert "no OCR helper" in gm.frame_gate(video, tmp_path, growth.Guard(cfg))


@pytest.mark.parametrize("text,kind", [(f"Edited {TERM} today", "private-term"), ("mail me at someone" + "@acme-inc" + ".io", "email"),
                                       ("Gammatool tracks invoices", "unreleased-product")])
def test_a_leak_in_a_frame_deletes_the_video(media, monkeypatch, tmp_path, text, kind):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, machine=Machine(ocr_text=text))
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"mp4")
    why = gm.frame_gate(video, tmp_path, growth.Guard(cfg))
    assert "would leak" in why and "deleted" in why and not video.exists() and text not in why


def test_ocr_frames_reads_the_helper_in_batches_of_twenty(media, monkeypatch, tmp_path):
    seen = []

    def run(argv, timeout):
        seen.append(len(argv) - 1)
        return 0, "\n".join(f"{i}\tt{i}" for i in range(len(argv) - 1))
    helper = tmp_path / "ocr"
    helper.write_text("x")
    helper.chmod(0o755)
    monkeypatch.setattr(gm, "run_tool", run)
    monkeypatch.setattr(gm, "ocr_helper", lambda: helper)
    out = gm.ocr_frames([tmp_path / f"{i}.png" for i in range(25)])
    assert seen == [20, 5] and len(out) == 25 and out[20].strip() == "t0"
    monkeypatch.setattr(gm, "run_tool", lambda argv, timeout: (1, ""))
    assert gm.ocr_frames([tmp_path / "a.png"]) is None


# --- the video step -------------------------------------------------------------------------------------------------

def run_step(store, cfg, allow=True):
    return gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg), reg=gm.registry.load(), allow=allow)


def test_a_day_with_no_clip_gets_one_video_shared_by_the_three_channels(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    m = set_up(monkeypatch, tmp_path)
    res = run_step(store, cfg)
    assert res["state"] == "ok" and "3 clips share reel.mp4" in res["reason"]
    s2 = growth.Store()
    items = clips(s2)
    assert {i["channel"] for i in items} == set(CHANNELS) and {i["status"] for i in items} == {"review"}
    assert len({i["media"][0] for i in items}) == 1 and pathlib.Path(items[0]["media"][0]).is_file()
    assert all(growth.video_ready(i) for i in items)
    ep = next(i for i in s2.items().values() if i["kind"] == "episode")
    assert ep["sources"] == [dict(kind="session", ref="session:sess-1", url="")] and ep["facts"][:2] == ["2 commits", "14 tests passed"]
    assert ep["cut"]["session"] and "held" not in ep["cut"]
    assert s2.ledger()[-1]["ev"] == "video" and s2.ledger()[-1]["state"] == "ok"
    assert [sys.executable, "-m", "teyla", "load", "--wait", "--kind", "build"] in m.calls          # the machine guard ran first
    assert growth.slot_report(s2, cfg, DAY)["filled"] == 3
    again = run_step(s2, cfg)
    assert again["state"] == "skipped" and "already covers today" in again["reason"]


def test_a_film_that_was_shot_today_means_no_render(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    mp4 = tmp_path / "f.mp4"
    mp4.write_bytes(b"x")
    for ch in CHANNELS:
        it = growth.make_item(store, NOW, kind="clip", format="true-vibe-coding", idea="ride", platform=ch.split("-")[0], language="en", day=DAY,
                              channel=ch, media=[str(mp4)], status="approved")
        store.save(it, NOW)
    m = set_up(monkeypatch, tmp_path)
    res = run_step(growth.Store(), cfg)
    assert res["state"] == "skipped" and m.calls == [] and clips(growth.Store()) and len(clips(growth.Store())) == 3


def test_no_session_a_busy_machine_or_safe_mode_is_a_gap_with_the_reason(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, sessions=[])
    res = run_step(store, cfg)
    assert res["state"] == "gap" and "no recent session" in res["reason"]
    assert "no recent session" in growth.render_plan(growth.plan(growth.Store(), cfg, DAY, NOW), DAY, None)
    set_up(monkeypatch, tmp_path, machine=Machine(wait=3))
    res = run_step(growth.Store(), cfg)
    assert res["state"] == "gap" and "machine is busy" in res["reason"] and not clips(growth.Store())
    assert run_step(growth.Store(), cfg, allow=False)["state"] == "skipped"
    store2, cfg2 = make(channels=("x-en",))
    assert run_step(store2, cfg2)["reason"] == "no enabled English video channel"


def test_a_dull_or_leaking_session_is_skipped_for_the_next_one(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, sessions=[dict(sid="s-dull", harness="claude", project="alpha", last=growth.iso(NOW - 3660), prs=[]),
                                            dict(sid="s-leak", harness="claude", project="alpha", last=growth.iso(NOW - 3720), prs=[]),
                                            dict(sid="s-good", harness="codex", project="alpha", last=growth.iso(NOW - 3780), prs=[])])
    stories = {"s-dull": story(commits=0, tests=0), "s-leak": story(), "s-good": story(commits=3)}
    monkeypatch.setattr(gm, "session_story", lambda sid, seconds=45: (stories[sid], ""))
    monkeypatch.setattr(gm, "story_strings", lambda s: [f"Edited {TERM}"] if s is stories["s-leak"] else ["Fixed the sync step"])
    res = run_step(store, cfg)
    assert res["state"] == "ok"
    s2 = growth.Store()
    eps = {i["sources"][0]["ref"]: i for i in s2.items().values() if i["kind"] == "episode"}
    assert set(eps) == {"session:s-leak", "session:s-good"} and eps["session:s-leak"]["status"] == "rejected"
    assert "would leak" in eps["session:s-leak"]["reject_reason"] and eps["session:s-good"]["status"] == "checked"
    assert TERM not in str(eps)


def test_a_session_that_opened_a_pr_goes_first_and_a_filmed_one_is_not_filmed_again(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, sessions=[dict(sid="newest", harness="claude-code", project="alpha", last=growth.iso(NOW - 3660), prs=[]),
                                            dict(sid="with-pr", harness="claude", project="alpha", last=growth.iso(NOW - 7200), prs=["https://x/pull/1"]),
                                            dict(sid="running", harness="claude-code", project="alpha", last=growth.iso(NOW - 120), prs=["p"]),
                                            dict(sid="grok-one", harness="grok", project="alpha", last=growth.iso(NOW - 4000), prs=["p"])])
    assert [r["sid"] for r in gm.session_candidates(store, cfg, gm.registry.load(), NOW)] == ["with-pr", "newest"]          # not grok, not still running
    ep = growth.make_item(store, NOW, kind="episode", format="worklog", idea="x", sources=[dict(kind="session", ref="session:with-pr", url="")])
    store.save(ep, NOW)
    assert [r["sid"] for r in gm.session_candidates(growth.Store(), cfg, gm.registry.load(), NOW)] == ["newest"]


def test_a_session_that_touched_a_private_repo_is_never_filmed(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)                       # public: alpha, beta; gamma ("Gammatool") is not
    set_up(monkeypatch, tmp_path, sessions=[dict(sid="mixed", harness="codex", last=growth.iso(NOW - 7200), repos=["alpha", "gamma"], prs=["p"]),
                                            dict(sid="alone", harness="codex", last=growth.iso(NOW - 7300), repos=["alpha"], prs=[]),
                                            dict(sid="ops", harness="codex", last=growth.iso(NOW - 7400), repos=["alpha", "ops"], prs=[]),
                                            dict(sid="bare", harness="codex", last=growth.iso(NOW - 7500), project="beta", prs=[]),
                                            dict(sid="odd", harness="codex", last=growth.iso(NOW - 7600), project="not-a-product", prs=[])])
    assert [r["sid"] for r in gm.session_candidates(store, cfg, gm.registry.load(), NOW)] == ["alone", "bare"]


def test_a_failed_frame_check_keeps_the_clips_out_of_review_and_off_the_slots(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, machine=Machine(ocr_text="mail me at someone" + "@acme-inc" + ".io"))
    res = run_step(store, cfg)
    assert res["state"] == "held" and "would leak" in res["reason"]
    s2 = growth.Store()
    items = clips(s2)
    assert {i["status"] for i in items} == {"draft"} and all("would leak" in i["hold_reason"] for i in items)
    assert all(not growth.video_ready(i) for i in items)                                  # the video was deleted
    assert growth.slot_report(s2, cfg, DAY)["filled"] == 0
    assert all(r["item"] is None for r in growth.plan(s2, cfg, DAY, NOW))
    assert cli.main(["growth", "review"]) == 0


def test_a_failed_model_call_for_captions_tries_the_next_session_and_then_gives_up(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, sessions=[dict(sid="a", harness="claude", project="alpha", last=growth.iso(NOW - 3601), prs=[]),
                                            dict(sid="b", harness="claude", project="alpha", last=growth.iso(NOW - 3602), prs=[])])
    monkeypatch.setattr(growth, "call_model", fake_model([growth.AgentError("claude exited 1")]))
    res = run_step(store, cfg)
    assert res["state"] == "gap" and "edit script failed" in res["reason"] and not clips(growth.Store())
    assert {i["status"] for i in growth.Store().items().values() if i["kind"] == "episode"} == {"rejected"}


def test_daily_runs_the_video_step_between_plan_and_draft(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    master(store)
    set_up(monkeypatch, tmp_path)
    monkeypatch.setattr(growth, "call_model", fake_model([GOOD, dict(CLIP, segments=[])]))
    lines = []
    res = gm.daily(store, cfg, NOW, out=lines.append)
    assert [s[0] for s in res["steps"]] == ["harvest", "trends", "plan", "video", "draft"] and res["failed"] == 0
    assert "3 clips share reel.mp4" in res["steps"][3][2]
    s2 = growth.Store()
    assert {i["channel"] for i in clips(s2)} == set(CHANNELS)
    assert not [i for i in s2.items().values() if i["platform"] in ("youtube", "instagram", "tiktok") and i["kind"] == "post"]
    assert "4 of 4 slots filled" in res["steps"][4][2] or "slots filled" in res["steps"][4][2]


def test_the_manual_cut_has_no_frame_gate_but_the_daily_one_passes_it(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(gm, "frame_gate", lambda video, d, guard: seen.append(video.name) or "")
    ep = growth.make_item(store, NOW, kind="episode", format="worklog", idea="a real session", facts=["2 commits"],
                          scores=dict(relevance=4, demonstrable=4, novelty=3, momentum=3))
    store.save(ep, NOW)
    gm.cut(store, cfg, ep["id"], NOW, session="sess-1", no_footage=True)
    assert seen == []
    store2 = growth.Store()
    gm.video_step(store2, cfg, NOW + 86400, guard=growth.Guard(cfg), reg=gm.registry.load())
    assert seen == ["reel.mp4"]


def test_a_caption_that_breaks_the_voice_chart_gets_one_repair_call_and_keeps_the_segments(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path)
    long = dict(CLIP, body="Alpha fixed the sync step and the whole pipeline now runs in one pass across every channel we have ever shipped to.",
                segments=[dict(start=0, end=5, caption="Sync fixed")])
    fm = fake_model([long, dict(CLIP, segments=[])])
    monkeypatch.setattr(growth, "call_model", fm)
    res = run_step(store, cfg)
    assert len(fm.calls) == 2 and fm.calls[1]["payload"]["fix"] and "previous_draft" in fm.calls[1]["payload"]
    assert res["state"] == "ok" and all(i["status"] == "review" for i in clips(growth.Store()))


def test_a_blank_read_is_an_unread_frame_and_holds_the_clips(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, machine=Machine(ocr_text=""))            # the helper exits 0 and reads nothing
    res = run_step(store, cfg)
    assert res["state"] == "held" and "did not read every frame" in res["reason"]
    assert all(i["status"] == "draft" for i in clips(growth.Store()))


def test_an_edit_or_a_retry_cannot_clear_a_frame_check_hold(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    set_up(monkeypatch, tmp_path, ocr_helper=False)
    run_step(store, cfg)
    s2 = growth.Store()
    it = clips(s2)[0]
    assert it["status"] == "draft" and it["video_hold"]
    got = growth.edit(s2, cfg, it["id"], "Alpha now syncs faster.", None, NOW)
    assert got["status"] == "draft" and got["hold_reason"] and got["video_hold"]
    with pytest.raises(growth.GrowthError, match="frame check"):
        growth.retry(growth.Store(), it["id"], NOW)
    with pytest.raises(growth.GrowthError):
        growth.approve(growth.Store(), it["id"], NOW)


def test_a_session_with_a_full_repo_list_is_not_filmed(media, monkeypatch):
    store, cfg = make()
    monkeypatch.setattr(growth, "_sessions", lambda days: [
        dict(sid="five", harness="codex", last=growth.iso(NOW - 7200), repos=["alpha", "beta", "alpha", "beta", "alpha"], prs=[]),
        dict(sid="two", harness="codex", last=growth.iso(NOW - 7300), repos=["alpha", "beta"], prs=[])])
    assert [r["sid"] for r in gm.session_candidates(store, cfg, gm.registry.load(), NOW)] == ["two"]
