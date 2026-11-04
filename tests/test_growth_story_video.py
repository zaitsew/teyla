"""The story vertical: the best lesson the editor passed becomes a silent 15 to 30 second video for the video channels
(docs/GROWTH.md, "The daily video"). Fakes only for the step: ffmpeg, ffprobe, the OCR helper and `teyla load` are the
`Machine` of test_growth_video. One test draws and encodes a real video when Pillow and ffmpeg exist. Nothing is published."""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from teyla import growth, growth_media as gm, growth_rank as rank, growth_story_video as sv, update
from test_growth import DAY, GOOD, NOW, PASS, TERM, WEAK, env, fake_model, make, master  # noqa: F401
from test_growth_media import CHANNELS, CLIP, media  # noqa: F401
from test_growth_video import Machine, clips, set_up

HOOK = "97 hand-rolled AI code reviews took 23% of my weekly Codex limit."
BODY = (f"{HOOK} Each one sent about 460k input tokens. `codex-review` sends only the diff: the median is 169k tokens. "
        "Same findings, a third of the cost. Check it yourself: `teyla review stats` https://github.com/owner/alpha/pull/7")
FACTS = ["97 reviews took 23% of the weekly limit", "Each review sent about 460k input tokens; the diff alone is 169k tokens", "Artifact: https://github.com/owner/alpha/pull/7"]


def lesson(store, hook=HOOK, body=BODY, day=DAY, score=4.0, status="review", platform="x", facts=FACTS, **kw):
    it = growth.make_item(store, NOW, kind="post", format="lesson", idea=hook, platform=platform, language="en", product="alpha", hook=hook,
                          facts=list(facts), day=day, channel=f"{platform}-en", status=status, body=body,
                          editor=dict(score=score, parts=dict(hook=4)), **kw)
    store.save(it, NOW)
    return it


def fake_render(monkeypatch):
    def render(plan, d, n=1):
        out = d / f"story-{n}.mp4"
        out.write_bytes(b"mp4")
        return out, ""
    monkeypatch.setattr(sv, "render", render)


# --- the text on screen --------------------------------------------------------------------------------------------

def test_the_hook_comes_first_and_every_card_has_at_most_eight_words():
    plan, why = sv.cards(HOOK, BODY, "github.com/owner/alpha")
    assert not why and plan[0]["kind"] == "hook" and plan[0]["text"].startswith("97 hand-rolled")
    assert all(len(c["text"].split()) <= sv.MAX_WORDS for c in plan)
    texts = [c["text"] for c in plan]
    assert sum(t.count("97 hand-rolled") for t in texts) == 1             # the body opens with the hook: shown once
    assert plan[-1] == dict(text="github.com/owner/alpha", kind="artifact", seconds=sv.ARTIFACT_SECONDS)
    assert not any(c["kind"] == "artifact" for c in plan[:-1])
    total = sum(c["seconds"] for c in plan)
    assert sv.MIN_SECONDS <= total <= sv.MAX_SECONDS and all(abs(c["seconds"] * sv.FRAME_RATE - round(c["seconds"] * sv.FRAME_RATE)) < 1e-6 for c in plan)


def test_links_and_markdown_marks_are_not_read_from_the_screen():
    text = " ".join(c["text"] for c in sv.cards(HOOK, BODY)[0])
    assert "http" not in text and "`" not in text and "codex-review sends only the diff" in text
    assert sv.speakable("**Bold** and `code` #tag https://x.example/a") == "Bold and code tag"


def test_a_sentence_that_opens_with_a_command_still_starts_a_new_card():
    plan, _ = sv.cards("Reviews cost 23% of my limit.", "Reviews cost 23% of my limit. Each one sent 460k tokens. `codex-review` sends the diff only. It cut that to 169k tokens. Findings stayed the same across 12 pull requests. That is a third of the cost for the same result.")
    texts = [c["text"] for c in plan]
    assert "codex-review sends the diff only." in texts


def test_a_long_sentence_is_cut_after_a_comma_near_the_middle_and_never_beyond_eight_words():
    assert sv.chunks("one two three four five six seven eight") == ["one two three four five six seven eight"]
    parts = sv.chunks("When the cache was empty, the sync loop hung for fourteen minutes before it failed")
    assert parts[0] == "When the cache was empty," and all(len(c.split()) <= 8 for c in parts)
    long = " ".join(f"w{i}" for i in range(23))
    parts = sv.chunks(long)
    assert all(len(p.split()) <= 8 for p in parts) and " ".join(parts) == long and len(parts) == 3


def test_a_long_draft_is_cut_at_a_sentence_end_and_runs_at_most_28_seconds():
    body = HOOK + " " + " ".join(f"Step {i} took {i + 3} minutes and found {i} more problems in the sync code." for i in range(1, 12))
    plan, why = sv.cards(HOOK, body, "teyla growth plan")
    total = sum(c["seconds"] for c in plan)
    assert not why and total <= sv.MAX_SECONDS and plan[-1]["kind"] == "artifact"
    assert plan[-2]["text"].endswith("code.")                     # the body stops at a whole sentence


def test_too_little_text_is_stretched_a_little_and_then_refused():
    plan, why = sv.cards("Reviews cost 23% of my limit.", "Reviews cost 23% of my limit. I stopped hand-rolling them.")
    assert plan == [] and "a story video runs 16 to 28 s" in why
    plan, why = sv.cards("97 reviews took 23% of my limit.", "97 reviews took 23% of my limit. Each one sent about 460k tokens. The diff alone is 169k tokens. Findings stayed the same. The cost fell by a third. I checked it on 12 pull requests.")
    assert not why and sum(c["seconds"] for c in plan) >= sv.MIN_SECONDS
    assert all(c["seconds"] <= 5.0 for c in plan)
    assert sv.cards("", "")[1] == "the draft has no text to show"


def test_without_a_hook_the_first_sentence_is_the_hook():
    plan, why = sv.cards("", BODY)
    assert not why and plan[0]["kind"] == "hook" and plan[0]["text"].startswith("97 hand-rolled")


def test_the_artifact_is_read_from_the_facts_then_the_comment_then_the_body():
    assert sv.find_artifact(dict(facts=FACTS)) == "github.com/owner/alpha/pull/7"
    assert sv.find_artifact(dict(facts=[], first_comment="Source: https://github.com/owner/alpha/pull/7")) == "github.com/owner/alpha/pull/7"
    assert sv.find_artifact(dict(facts=[], body="Run `teyla review stats` yourself")) == "teyla review stats"
    assert sv.find_artifact(dict(facts=["97 reviews"], body="No link here")) == ""


def test_a_youtube_title_is_cut_at_a_word_boundary():
    long = "Ninety seven hand-rolled code reviews took a quarter of my weekly limit before I read the numbers " * 2
    t = sv.fit_title(long)
    assert len(t) <= 100 and long.startswith(t) and not t.endswith(" ")
    assert sv.fit_title("Short hook.") == "Short hook."


# --- which draft to film -------------------------------------------------------------------------------------------

def test_only_a_passing_lesson_of_today_or_yesterday_that_was_not_filmed_is_a_candidate(env):
    store, _ = make(channels=("x-en", "linkedin-en"))
    good = lesson(store, score=3.8)
    better = lesson(store, score=4.6, platform="linkedin", hook="A better lesson, 5 builds in 3 days.", body="A better lesson, 5 builds in 3 days.")
    lesson(store, day="2026-11-01")                                   # too old
    lesson(store, status="rejected")
    lesson(store, status="failed")
    lesson(store, hold_reason="the editor held it")
    lesson(store, score=2.0)                                          # the editor did not pass it
    lesson(store, body="")
    master(store, fmt="lesson", idea="a master", facts=("x",))        # a master is never filmed
    worklog = growth.make_item(store, NOW, kind="post", format="worklog", idea="w", platform="x", language="en", day=DAY, channel="x-en", status="review",
                               body="b", editor=dict(score=5, parts=dict(hook=5)))
    store.save(worklog, NOW)
    assert [i["id"] for i in sv.candidates(store, DAY)] == [better["id"], good["id"]]
    ep = growth.make_item(store, NOW, kind="episode", format="lesson", idea="e", sources=[dict(kind="story-video", ref=f"storyvideo:{good['id']}", url="")])
    store.save(ep, NOW)
    assert good["id"] not in [i["id"] for i in sv.candidates(store, DAY)]


def test_a_story_with_a_number_and_an_artifact_goes_before_a_higher_scoring_bare_lesson(env):
    store, _ = make()
    bare = lesson(store, score=4.9, hook="Rules beat memory every time.", body="Rules beat memory every time. I write them down now.", facts=["Rules beat memory"])
    story = lesson(store, score=3.6)
    assert rank.story_class(story) == "story" and rank.story_class(bare) != "story"
    assert [i["id"] for i in sv.candidates(store, DAY)] == [story["id"], bare["id"]]


# --- the step ------------------------------------------------------------------------------------------------------

def test_a_passing_lesson_becomes_one_video_shared_by_the_three_channels(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    src = lesson(store)
    machine = set_up(monkeypatch, tmp_path)
    fake_render(monkeypatch)
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, gm.registry.load()), reg=gm.registry.load())
    assert res["state"] == "ok" and f"made from the lesson {src['id']}" in res["reason"] and "3 clips share story-1.mp4" in res["reason"]
    s2 = growth.Store()
    got = clips(s2)
    assert {i["channel"] for i in got} == set(CHANNELS) and {i["status"] for i in got} == {"review"}
    assert all(i["story_video_of"] == src["id"] and i["body"] == BODY and i["media"][0].endswith("story-1.mp4") for i in got)
    assert all(i["script"].startswith("97 hand-rolled AI code reviews took") for i in got)
    yt = next(i for i in got if i["platform"] == "youtube")
    assert yt["hook"] == HOOK and len(yt["hook"]) <= 100
    ep = s2.get(got[0]["parent"])
    assert ep["status"] == "checked" and ep["cut"]["story"] == src["id"] and ep["cut"]["footage"] is False
    assert [r for r in s2.ledger() if r["ev"] == "video"][-1]["state"] == "ok"
    assert any(c[0] == "ffprobe" for c in machine.calls) and any(c[0].endswith("/ocr") for c in machine.calls)      # the frame gate ran
    # the lesson is not filmed twice, and the day is covered
    again = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, gm.registry.load()), reg=gm.registry.load())
    assert again["state"] == "skipped"
    assert sv.candidates(s2, DAY) == []


def test_the_story_beats_the_screen_of_a_session_and_no_model_is_called(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    lesson(store)
    set_up(monkeypatch, tmp_path)
    fake_render(monkeypatch)
    fm = fake_model([GOOD])
    monkeypatch.setattr(growth, "call_model", fm)
    rendered = []
    monkeypatch.setattr(gm, "render_session", lambda *a, **k: rendered.append(1) or (None, "must not run"))
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, gm.registry.load()), reg=gm.registry.load())
    assert res["state"] == "ok" and not rendered and not fm.calls and not fm.editor_calls


def test_a_day_with_no_passing_lesson_falls_back_to_the_session_and_says_why_when_both_fail(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    set_up(monkeypatch, tmp_path)
    fake_render(monkeypatch)
    reg = gm.registry.load()
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg)
    assert res["state"] == "ok" and "3 clips share reel.mp4" in res["reason"]          # the session reel, as before
    set_up(monkeypatch, tmp_path, sessions=[])
    monkeypatch.setattr(growth, "_sessions", lambda days: [])
    res = gm.video_step(store, cfg, NOW + 86400 * 3, guard=growth.Guard(cfg, reg), reg=reg)
    assert res["state"] == "gap" and "no passing lesson draft from today or yesterday to film" in res["reason"] and "no recent session" in res["reason"]


def test_a_leak_in_a_frame_holds_the_story_video_and_deletes_it(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    lesson(store)
    set_up(monkeypatch, tmp_path, machine=Machine(ocr_text=f"a line with {TERM} in it"))
    fake_render(monkeypatch)
    reg = gm.registry.load()
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg)
    assert res["state"] == "held" and "would leak (private-term)" in res["reason"]
    got = clips(growth.Store())
    assert got and {i["status"] for i in got} == {"draft"} and all(i["video_hold"] for i in got)
    assert not list(growth.Store().root.glob("episodes/*/story-1.mp4"))


def test_a_line_that_would_leak_is_never_drawn(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    lesson(store, body=BODY + f" It also cost {TERM} a lot of time and money in the end.")
    set_up(monkeypatch, tmp_path)
    drawn = []
    monkeypatch.setattr(sv, "render", lambda plan, d, n=1: drawn.append(plan) or (None, "not drawn"))
    reg = gm.registry.load()
    gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg, sessions=False)
    assert all(TERM not in c["text"] for plan in drawn for c in plan) or not drawn


def test_a_failed_render_tries_the_next_lesson_then_gives_up_with_the_reason(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    lesson(store, score=4.5)
    lesson(store, score=4.0, hook="A second lesson, 5 builds in 3 days.", body=HOOK + " Another sentence with 4 more figures and 7 details. Then a third one with 9 steps and 2 results. And a fourth with 6 items.")
    set_up(monkeypatch, tmp_path)
    monkeypatch.setattr(sv, "render", lambda plan, d, n=1: (None, "ffmpeg failed: no encoder"))
    reg = gm.registry.load()
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg, sessions=False)
    assert res["state"] == "gap" and "no encoder" in res["reason"]
    assert all(i["status"] == "rejected" for i in growth.Store().items().values() if i["kind"] == "episode")


def test_pillow_missing_is_a_gap_that_names_the_upgrade_command(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    lesson(store)
    monkeypatch.setattr(gm, "run_tool", gm._REAL_RUN_TOOL)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    from teyla.reel import render as reel_render
    monkeypatch.setattr(reel_render, "available", lambda: {"pillow": False, "ffmpeg": "/usr/bin/ffmpeg"})
    reg = gm.registry.load()
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg)
    assert res["state"] == "gap" and res["reason"].startswith("the reel extra (Pillow) is missing")
    assert "uv tool install --force --python 3.12 'teyla[reel] @ git+https://github.com/zaitsew/teyla'" in res["reason"]
    assert growth.video_gap(growth.Store(), DAY).startswith("the reel extra (Pillow) is missing")      # the slot report shows it
    monkeypatch.setattr(reel_render, "available", lambda: {"pillow": True, "ffmpeg": None})
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    assert gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg)["reason"] == "ffmpeg is missing: `brew install ffmpeg`"


def test_safe_mode_and_a_busy_machine_leave_the_lesson_alone(media, monkeypatch, tmp_path):
    store, cfg = make(channels=CHANNELS)
    lesson(store)
    set_up(monkeypatch, tmp_path, machine=Machine(wait=1))
    fake_render(monkeypatch)
    reg = gm.registry.load()
    assert gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg, allow=False)["reason"] == "safe mode"
    res = gm.video_step(store, cfg, NOW, guard=growth.Guard(cfg, reg), reg=reg, sessions=False)
    assert res["state"] == "gap" and "machine is busy" in res["reason"] and not [i for i in growth.Store().items().values() if i["kind"] == "episode"]


def test_daily_tries_again_after_the_draft_step_when_a_lesson_was_drafted_this_morning(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    master(store, idea="97 reviews took 23% of my weekly limit; `codex-review` sends only the diff", fmt="lesson",
           facts=("97 reviews took 23% of my weekly limit", "Each review sent about 460k input tokens; the diff alone is 169k tokens",
                  "`codex-review` sends only the diff", "Artifact: https://github.com/owner/alpha/pull/7"), sources=[dict(kind="note", ref="note:n1", url="")])
    set_up(monkeypatch, tmp_path, sessions=[])
    fake_render(monkeypatch)
    monkeypatch.setattr(growth, "_sessions", lambda days: [])
    monkeypatch.setattr(growth, "call_model", fake_model([dict(GOOD, hook=HOOK, body=BODY)], editor=[PASS]))
    lines = []
    res = gm.daily(store, cfg, NOW, out=lines.append)

    names = [s[0] for s in res["steps"]]
    assert names == ["harvest", "trends", "plan", "video", "draft", "reel"] and res["failed"] == 0
    assert res["steps"][3][2].startswith("gap: no passing lesson draft") and "3 clips share story-1.mp4" in res["steps"][5][2]
    assert {i["channel"] for i in clips(growth.Store())} == set(CHANNELS) and len(lines) == 6


def test_daily_has_no_reel_step_when_the_video_step_made_a_clip(media, monkeypatch, tmp_path):
    store, cfg = make(channels=("x-en",) + CHANNELS)
    lesson(store)
    set_up(monkeypatch, tmp_path)
    fake_render(monkeypatch)
    monkeypatch.setattr(growth, "call_model", fake_model([GOOD]))
    res = gm.daily(store, cfg, NOW, quiet=True)
    assert [s[0] for s in res["steps"]] == ["harvest", "trends", "plan", "video", "draft"] and "story-1.mp4" in res["steps"][3][2]


# --- a real render --------------------------------------------------------------------------------------------------

def test_a_real_render_is_1080x1920_silent_and_as_long_as_planned(tmp_path):
    pytest.importorskip("PIL")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg is not installed")
    if sv.find_font() is None:
        pytest.skip("no bold sans-serif font on this machine")
    plan, why = sv.cards(HOOK, BODY, "github.com/owner/alpha")
    assert not why
    out, err = sv.render(plan, tmp_path, 1)
    assert err == "" and out == tmp_path / "story-1.mp4" and out.stat().st_mode & 0o777 == 0o600
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-show_entries", "format=duration",
                            "-of", "default=nw=1", str(out)], capture_output=True, text=True).stdout
    assert "width=1080" in probe and "height=1920" in probe and "codec_type=audio" not in probe
    seconds = float(next(ln.split("=")[1] for ln in probe.splitlines() if ln.startswith("duration=")))
    assert abs(seconds - sum(c["seconds"] for c in plan)) < 0.4
    assert not list(tmp_path.glob("story-1-frames")) and not list(tmp_path.glob("*.part.mp4"))      # no frames or partial file left behind


def test_every_card_fits_the_width_of_the_screen(tmp_path):
    pytest.importorskip("PIL")
    make_font = sv.find_font()
    if make_font is None:
        pytest.skip("no bold sans-serif font on this machine")
    plan, _ = sv.cards(HOOK, BODY, "github.com/owner/alpha")
    for c in plan:
        img = sv.draw_card(c, make_font)
        assert img.size == (sv.W, sv.H)
        px = img.load()
        assert all(px[x, y] == sv.BG for y in range(0, 300) for x in (0, sv.W - 1))      # nothing in the margins' corners
        left = min((x for x in range(sv.W) for y in range(300, 1300, 4) if px[x, y] != sv.BG), default=sv.MARGIN_X)
        right = max((x for x in range(sv.W) for y in range(300, 1300, 4) if px[x, y] != sv.BG), default=sv.W - sv.MARGIN_X)
        assert left >= sv.MARGIN_X - 12 and right <= sv.W - sv.MARGIN_X + 12


# --- the release path installs the extra ----------------------------------------------------------------------------

def test_a_mac_that_runs_the_factory_updates_with_the_reel_extra(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "truststore_available", lambda: False)
    monkeypatch.setattr(update, "pillow_available", lambda: False)
    assert update.install_source("zaitsew/teyla", "v1.0.0") == "git+https://github.com/zaitsew/teyla@v1.0.0"
    g_dir = growth.Store().root
    g_dir.mkdir(parents=True, exist_ok=True)
    (g_dir / "config.toml").write_text("posts_per_day = 1\n")
    assert update.install_source("zaitsew/teyla", "v1.0.0") == "teyla[reel] @ git+https://github.com/zaitsew/teyla@v1.0.0"
    monkeypatch.setattr(update, "truststore_available", lambda: True)
    assert update.install_source("zaitsew/teyla", "v1.0.0") == "teyla[work,reel] @ git+https://github.com/zaitsew/teyla@v1.0.0"


def test_growth_doctor_names_the_reel_extra_and_the_command(media, monkeypatch):
    store, cfg = make()
    monkeypatch.setattr(update, "pillow_available", lambda: False)
    row = next(r for r in growth.doctor_rows(store, cfg, NOW) if r[1] == "reel extra")
    assert row[0] == "missing" and sv.UPGRADE in row[2]
    monkeypatch.setattr(update, "pillow_available", lambda: True)
    assert next(r for r in growth.doctor_rows(store, cfg, NOW) if r[1] == "reel extra")[0] == "ok"
