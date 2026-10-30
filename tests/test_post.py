"""`teyla post draft` and `teyla post pack`: voice-checked drafts into a queue, and the weekly checklist."""
from __future__ import annotations

import datetime as dt
import re

import pytest

from teyla import cli, post, voice

from kitfix import RU_TAGLINE, make_repo, png_bytes

TODAY = dt.date.today().isoformat()
EVENT = "Version 1.2 adds a weekly view"


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def queue(repo):
    return sorted(p.name for p in (repo / "brand" / "posts" / "queue").glob("*.md"))


# --- draft ---------------------------------------------------------------------------------------------

def test_a_scaffold_draft_is_checked_and_written_to_the_queue(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--event", EVENT)
    assert rc == 0, err
    (name,) = queue(repo)
    assert name == f"{TODAY}-x-version-1-2-adds-a-weekly-view.md"
    text = (repo / "brand" / "posts" / "queue" / name).read_text(encoding="utf-8")
    head, body = text.split("---\n")[1], text.split("---\n")[2]
    assert 'product: "Demo App"' in head and "channel: x" in head and "lang: en" in head and "status: draft" in head
    assert "checked: pass (teyla voice check, en.md)" in head and "limit: 280 characters, chart format x_post" in head
    assert body.strip() == "Version 1.2 adds a weekly view. Plan your day in one calm screen. A calm day plan."
    assert "publishing is by hand" in out


def test_a_text_draft_is_written_as_given(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "threads", "--text", "The week view is here. It shows seven days.", "--slug", "week")
    assert rc == 0, err
    assert queue(repo) == [f"{TODAY}-threads-week.md"]


def test_a_text_file_is_read(tmp_path, capsys):
    repo = make_repo(tmp_path)
    f = tmp_path / "post.txt"
    f.write_text("A short note about the release.\n", encoding="utf-8")
    assert run(capsys, "post", "draft", str(repo), "--channel", "instagram", "--file", str(f))[0] == 0
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "instagram", "--file", str(tmp_path / "missing.txt"))
    assert rc == 2 and "cannot read" in err


def test_a_draft_that_breaks_the_chart_is_printed_and_not_written(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--text", "We delve into a seamless week view!")
    assert rc == 1 and not queue(repo)
    assert "FAIL" in out and "delve" in out and "not written" in err and "We delve" in err


def test_the_channel_limit_is_enforced_beside_the_chart(tmp_path, capsys):
    repo = make_repo(tmp_path)
    long = " ".join(["Plan the day."] * 25)             # 25 short sentences, 349 characters
    rc, out, _ = run(capsys, "post", "draft", str(repo), "--channel", "x", "--text", long)
    assert rc == 1 and "x allows 280" in out
    assert run(capsys, "post", "draft", str(repo), "--channel", "threads", "--text", long)[0] == 0      # 500 allowed


def test_a_scaffold_is_trimmed_to_the_channel_limit():
    kit = {"product": {"promise": "Plan your day in one calm screen."}, "tagline": {"en": "A calm day plan."}}
    s = post.scaffold(kit, "Version 1.2 adds a weekly view", 60)
    assert len(s) <= 60 and s.startswith("Version 1.2")
    assert post.scaffold(kit, "A calm day plan", 280) == "A calm day plan. Plan your day in one calm screen."      # no repeats


def test_a_scaffold_needs_an_event_and_english(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "x")
    assert rc == 2 and "--event" in err
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--event", EVENT, "--lang", "es")
    assert rc == 2 and "English only" in err and not queue(repo)


def test_another_language_uses_its_own_chart_and_file_name(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--lang", "es", "--text", "La vista semanal ya está aquí.", "--slug", "semana")
    assert rc == 0, err
    assert "es.md" in out and queue(repo) == [f"{TODAY}-x-semana-es.md"]
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--lang", "ru", "--text", RU_TAGLINE + ".", "--slug", "ru")
    assert rc == 0, err
    assert RU_TAGLINE in (repo / "brand" / "posts" / "queue" / f"{TODAY}-x-ru-ru.md").read_text(encoding="utf-8")


def test_a_missing_chart_directory_is_a_clear_error(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "brand" / "voice" / "en.md").unlink()
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--text", "A line.")
    assert rc == 2 and "voice chart" in err
    rc, _, err = run(capsys, "post", "draft", str(tmp_path / "nowhere"), "--channel", "x", "--text", "A line.")
    assert rc == 2


def test_the_chart_directory_comes_from_the_kit(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "brand" / "voice").rename(repo / "brand" / "tone")
    p = repo / "brand" / "kit.toml"
    p.write_text(p.read_text().replace('chart = "brand/voice"', 'chart = "brand/tone"'))
    rc, out, err = run(capsys, "post", "draft", str(repo), "--channel", "x", "--text", "A line.")
    assert rc == 0, err
    assert "brand/tone/en.md" in out


def test_a_second_draft_of_the_same_event_gets_a_new_name(tmp_path, capsys):
    repo = make_repo(tmp_path)
    for _ in range(2):
        assert run(capsys, "post", "draft", str(repo), "--channel", "x", "--event", EVENT)[0] == 0
    assert len(queue(repo)) == 2 and any(n.endswith("-2.md") for n in queue(repo))


def test_dry_writes_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, _ = run(capsys, "post", "draft", str(repo), "--channel", "x", "--event", EVENT, "--dry")
    assert rc == 0 and "status: draft" in out and not queue(repo)


def test_a_tiktok_hook_must_fit_the_video_hook_limit(tmp_path, capsys):
    repo = make_repo(tmp_path)
    hook = "Plan " + " ".join(["every"] * 14) + " day with one calm screen and one calm list today."
    assert len(hook) > 120
    rc, out, _ = run(capsys, "post", "draft", str(repo), "--channel", "tiktok", "--text", hook + " Then open it.")
    assert rc == 1 and "hook length" in out
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "tiktok", "--text", "See the week at a glance. Then open the app.")
    assert rc == 0, err


def test_a_youtube_draft_carries_a_title_of_at_most_one_hundred_characters(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "post", "draft", str(repo), "--channel", "youtube", "--text", "The week view in sixty seconds. It shows seven days at once.")
    assert rc == 0, err
    (name,) = queue(repo)
    assert 'title: "The week view in sixty seconds."' in (repo / "brand/posts/queue" / name).read_text()
    title = post.hook_of("A " + "very " * 25 + "long title. More.")
    assert len(title) > 100
    rep = post.check_draft("A " + "very " * 25 + "long title. More.", voice.load_chart(repo / "brand/voice/en.md"), "youtube", None)
    assert any(f["rule"] == "title" for f in rep["findings"]) and not rep["ok"]


def test_the_hook_is_the_first_sentence():
    assert post.hook_of("One line. Two lines.") == "One line."
    assert post.hook_of("No stop") == "No stop"
    assert post.slugify("Version 1.2: a Weekly View!") == "version-1-2-a-weekly-view"
    assert post.slugify("\u041f\u0440\u0438\u0432\u0435\u0442") == ""


# --- pack ----------------------------------------------------------------------------------------------

def pack_text(repo, wid):
    return (repo / "brand" / "posts" / "packs" / f"{wid}.md").read_text(encoding="utf-8")


def test_the_pack_is_a_checklist_of_one_reel_one_set_and_three_posts(tmp_path, capsys):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", "2026-W44")
    assert rc == 0, err
    text = pack_text(repo, "2026-W44")
    assert text.startswith("# Flagship pack 2026-W44: Demo App") and f"Event: {EVENT}" in text
    ids = re.findall(r"<!-- ([^>]+?) -->", text)
    assert ids == ["reel", "shots", "post:x:1", "post:instagram:1", "post:threads:1", "approve"]
    assert text.count("- [ ]") == 6 and "0 of 6 done" in out
    assert "teyla reel product demo-app" in text and "teyla kit shots demo-app" in text


def test_work_on_disk_ticks_its_item_and_a_hand_tick_stays(tmp_path, capsys):
    repo = make_repo(tmp_path)
    for lang in ("en", "es", "ru"):
        (repo / "brand/out/reel" / lang).mkdir(parents=True)
        (repo / "brand/out/reel" / lang / "product-vertical.mp4").write_bytes(b"x")
    # a queued X post dated inside the week
    (repo / "brand/posts/queue" / "2026-10-27-x-launch.md").write_text("x\n")
    (repo / "brand/posts/queue" / "2026-11-20-instagram-later.md").write_text("x\n")      # another week: not counted
    assert run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", "2026-W44")[0] == 0
    text = pack_text(repo, "2026-W44")
    assert "- [x] One reel" in text and "- [x] Post 1 of 3, x" in text and "- [ ] Post 2 of 3, instagram" in text and "- [ ] One screenshot set" in text
    path = repo / "brand/posts/packs/2026-W44.md"
    path.write_text(path.read_text().replace("- [ ] One screenshot set", "- [x] One screenshot set"))
    rc, out, _ = run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", "2026-W44")
    assert rc == 0 and "- [x] One screenshot set" in pack_text(repo, "2026-W44") and "3 of 6 done" in out


def test_screenshots_on_disk_tick_the_set(tmp_path, capsys):
    repo = make_repo(tmp_path)
    for lang in ("en", "es", "ru"):
        d = repo / "brand/out/store" / lang / "iphone-6.9"
        d.mkdir(parents=True)
        (d / "01-a.png").write_bytes(png_bytes())
    assert run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", "2026-W44")[0] == 0
    assert "- [x] One screenshot set" in pack_text(repo, "2026-W44")


def test_pack_channels_cycle_and_are_checked(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", "2026-W44", "--channels", "x")[0] == 0
    assert re.findall(r"<!-- (post:[^>]+?) -->", pack_text(repo, "2026-W44")) == ["post:x:1", "post:x:2", "post:x:3"]
    rc, _, err = run(capsys, "post", "pack", str(repo), "--week", "2026-W44", "--channels", "myspace")
    assert rc == 2 and "myspace unknown" in err


@pytest.mark.parametrize("week", ["2026-44", "W44", "2026-W54", "2026-W00"])
def test_pack_rejects_a_bad_week(tmp_path, capsys, week):
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "post", "pack", str(repo), "--event", EVENT, "--week", week)
    assert rc == 2 and "week" in err


def test_pack_event_defaults_to_the_last_commit_subject(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(post, "last_event", lambda r: "Fix the empty state")
    assert run(capsys, "post", "pack", str(repo), "--week", "2026-W44")[0] == 0
    assert "Event: Fix the empty state" in pack_text(repo, "2026-W44")
    monkeypatch.setattr(post, "last_event", lambda r: "")
    assert run(capsys, "post", "pack", str(repo), "--week", "2026-W45")[0] == 0
    assert "(none given: pass --event)" in pack_text(repo, "2026-W45")


def test_week_helpers():
    assert post.week_id(dt.date(2026, 10, 30)) == "2026-W44"
    assert post.week_range("2026-W44") == (dt.date(2026, 10, 26), dt.date(2026, 11, 1))
