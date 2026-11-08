"""teyla freshness: synthetic git repos in tmp dirs. Nothing here reads a real repo, the network or the real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess

import pytest

from teyla import config, digest, freshness, routine_install
from teyla.cli import main

ENV = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
NOW = dt.datetime.now(dt.timezone.utc)
OLD = (NOW - dt.timedelta(days=40)).isoformat()
RECENT = (NOW - dt.timedelta(days=2)).isoformat()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "code_root", lambda cfg=None: tmp_path / "repos")
    (tmp_path / "repos").mkdir()
    return home


def git(repo, *args, when=None):
    env = {**os.environ, **ENV}
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def write(repo, rel, text="x"):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(repo, files: dict, msg, when):
    for rel, text in files.items():
        write(repo, rel, text)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", msg, when=when)


def merge(repo, n, title, when):
    """A merge commit the way GitHub makes it: `Merge pull request #n`, the title in the body."""
    git(repo, "checkout", "-q", "-b", f"b{n}")
    write(repo, f"src/f{n}.txt", str(n))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"work {n}", when=when)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", f"b{n}", "-m", f"Merge pull request #{n} from owner/b{n}", "-m", title,
        when=when)


def product(tmp_path, toml="", name="app", files=None, first_when=OLD):
    r = tmp_path / "repos" / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "teyla.toml").write_text(f'[product]\nname = "{name}"\n{toml}')
    commit(r, {"README.md": "# App\n", **(files or {})}, "first", first_when)
    return r


def features(repo, n, start=1, when=RECENT, prefix="Feature"):
    for i in range(start, start + n):
        merge(repo, i, f"{prefix} {i} for users", when)


def checks(row):
    return {c["check"]: c for c in row["checks"]}


def test_a_fresh_readme_is_ok(tmp_path):
    r = product(tmp_path, first_when=RECENT)
    features(r, 12)
    row = freshness.run()[0]
    assert row["verdict"] == "ok" and checks(row)["readme"]["verdict"] == "ok"
    assert freshness.exit_code([row]) == 0
    assert freshness.render_text([row]) == "app: ok\n"


def test_a_readme_is_stale_by_count_and_age(tmp_path):
    r = product(tmp_path)
    features(r, 12)
    row = freshness.run()[0]
    c = checks(row)["readme"]
    assert row["verdict"] == "stale" and c["verdict"] == "stale" and c["changes"] == 12
    assert c["since"] == OLD[:10] and len(c["examples"]) == 2 and c["path"] == "README.md"
    assert c["text"].startswith(f"app README: 12 user-facing changes since {OLD[:10]} (e.g. \"")
    assert c["text"].endswith("Update it to what ships today.") and "#" in c["text"]
    assert freshness.exit_code([row]) == 1
    text = freshness.render_text([row])
    assert text.startswith("app: 1 stale (readme)\n  app README: 12 user-facing")


def test_below_the_count_or_younger_than_the_days_is_not_stale(tmp_path):
    r = product(tmp_path, name="few")
    features(r, 9)
    assert freshness.run([str(r)])[0]["verdict"] == "ok"
    r2 = product(tmp_path, name="young", first_when=RECENT)
    features(r2, 30)
    assert freshness.run([str(r2)])[0]["verdict"] == "ok"


def test_internal_changes_do_not_count(tmp_path):
    r = product(tmp_path)
    for i in range(1, 15):
        merge(r, i, f"{'docs' if i % 2 else 'test'}: change {i}", RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["changes"] == 0


def test_thresholds_and_skip_come_from_the_manifest(tmp_path):
    r = product(tmp_path, '[freshness]\nchanges = 3\ndays = 30\nskip = ["readme-images"]\n',
                files={"docs/a.png": "a"})
    write(r, "README.md", "# App\n![a](docs/a.png)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=OLD)
    features(r, 4)
    c = checks(freshness.run()[0])
    assert c["readme"]["verdict"] == "stale" and c["readme"]["changes"] == 4
    assert c["readme-images"]["verdict"] == "skip"


def test_the_oldest_readme_image_is_chosen_and_http_images_are_ignored(tmp_path):
    r = product(tmp_path, first_when=OLD)
    commit(r, {"docs/old.png": "o"}, "old image", (NOW - dt.timedelta(days=60)).isoformat())
    commit(r, {"docs/new.png": "n", "assets/dark.svg": "<svg/>"}, "new image", RECENT)
    write(r, "README.md", "# App\n![o](docs/old.png)\n<img src=\"docs/new.png\" width=\"10\">\n"
          "<picture><source srcset=\"assets/dark.svg 1x\"></picture>\n"
          "![remote](https://example.com/shot.png)\n![gone](docs/missing.png)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=RECENT)
    features(r, 11, when=RECENT)
    assert freshness.readme_images(r) == ["docs/old.png", "docs/new.png", "assets/dark.svg"]
    c = checks(freshness.run()[0])["readme-images"]
    assert c["verdict"] == "stale" and c["path"] == "docs/old.png"
    assert "README image docs/old.png" in c["text"]
    assert checks(freshness.run()[0])["readme"]["verdict"] == "ok"   # README itself was just touched


def test_only_http_images_means_the_check_is_skipped(tmp_path):
    r = product(tmp_path)
    write(r, "README.md", "![x](http://example.com/a.png)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=OLD)
    assert checks(freshness.run()[0])["readme-images"]["verdict"] == "skip"


def test_a_missing_readme_is_stale(tmp_path):
    r = product(tmp_path)
    git(r, "rm", "-q", "README.md")
    git(r, "commit", "-q", "-m", "drop readme", when=OLD)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "stale" and c["text"] == "app README: no README.md"


def test_whats_new_is_skipped_for_a_product_that_is_not_in_a_store(tmp_path):
    product(tmp_path)
    assert checks(freshness.run()[0])["whats-new"]["verdict"] == "skip"


def test_a_store_product_without_whats_new_is_stale(tmp_path):
    product(tmp_path, '[productize.distribution]\nios = "testflight-internal"\n')
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "stale" and "no docs/whats-new/" in c["text"]
    assert "the next store version has no What's New" in c["text"]


def test_android_play_counts_as_a_store_product(tmp_path):
    product(tmp_path, '[productize.distribution]\nandroid = "play-internal"\n')
    assert checks(freshness.run()[0])["whats-new"]["verdict"] == "stale"


def test_a_generic_newest_note_is_flagged(tmp_path):
    r = product(tmp_path, files={"docs/whats-new/1.9/en.txt": "Real change\n",
                                 "docs/whats-new/1.10/en.txt": "Bug fixes and improvements\n"},
                first_when=RECENT)
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "stale" and c["text"] == "app: docs/whats-new/1.10/en.txt is a generic line"
    commit(r, {"docs/whats-new/1.10/en.txt": "Share a trip as a link\n"}, "note", RECENT)
    assert checks(freshness.run()[0])["whats-new"]["verdict"] == "ok"


def test_old_whats_new_notes_go_stale_with_the_changes(tmp_path):
    r = product(tmp_path, files={"docs/whats-new/1.0/en.txt": "Share a trip as a link\n"})
    features(r, 11)
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "stale" and c["text"].startswith("app docs/whats-new: 11 user-facing changes since")


def test_listing_and_screenshots_skip_when_absent_and_go_stale_when_old(tmp_path):
    r = product(tmp_path)
    c = checks(freshness.run()[0])
    assert c["listing"]["verdict"] == "skip" and c["screenshots"]["verdict"] == "skip"
    commit(r, {"fastlane/metadata/en-US/description.txt": "d", "docs/screenshots/home.png": "p"}, "store", OLD)
    features(r, 11)
    c = checks(freshness.run()[0])
    assert c["listing"]["verdict"] == "stale" and c["listing"]["text"].startswith("app store listing text: 11 ")
    assert c["screenshots"]["verdict"] == "stale" and c["screenshots"]["path"] == "docs/screenshots/**/*.png"
    assert c["screenshots"]["text"].endswith("Re-capture the screenshots.")


def test_configured_globs_replace_the_defaults(tmp_path):
    r = product(tmp_path, '[freshness]\nlisting = ["store-text/*.md"]\nscreenshots = ["nothing/**"]\n',
                files={"store-text/en.md": "t", "docs/screenshots/a.png": "p"})
    features(r, 11)
    c = checks(freshness.run()[0])
    assert c["listing"]["verdict"] == "stale"
    assert c["screenshots"]["verdict"] == "skip"


def test_the_newest_touch_of_any_screenshot_counts(tmp_path):
    r = product(tmp_path, files={"docs/screenshots/a.png": "a"})
    features(r, 11)
    commit(r, {"docs/screenshots/b.png": "b"}, "new shot", RECENT)
    assert checks(freshness.run()[0])["screenshots"]["verdict"] == "ok"


def test_broken_manifest_is_an_error_row_with_a_path_and_silent_in_the_sweep(tmp_path, capsys):
    r = product(tmp_path)
    (r / "teyla.toml").write_text("[product\nname = ")
    assert freshness.run() == []
    rows = freshness.run([str(r)])
    assert rows[0]["verdict"] == "error" and "does not parse" in rows[0]["error"]
    assert freshness.exit_code(rows) == 1
    assert freshness.problem_lines(rows)[0][0] == "freshness|app|error"
    assert main(["freshness", str(r)]) == 1
    assert "does not parse" in capsys.readouterr().out


def test_exit_codes_and_json(tmp_path, capsys):
    ok = product(tmp_path, name="ok-app", first_when=RECENT)
    stale = product(tmp_path, name="stale-app")
    features(stale, 11)
    assert main(["freshness", str(ok)]) == 0
    assert capsys.readouterr().out == "ok-app: ok\n"
    assert main(["freshness", str(stale), "--json"]) == 1
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["product"] == "stale-app" and rows[0]["verdict"] == "stale"
    assert {c["check"] for c in rows[0]["checks"]} == set(freshness.CHECKS)
    assert set(rows[0]["checks"][0]) == {"check", "verdict", "since", "changes", "examples", "path", "text"}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["freshness", str(empty)]) == 2
    assert "no teyla.toml" in capsys.readouterr().err
    assert main(["freshness"]) == 1       # the sweep sees both products


def test_quiet_writes_and_removes_the_problems_file(tmp_path, capsys):
    r = product(tmp_path)
    features(r, 11)
    p = freshness.problems_path()
    assert main(["freshness", "--quiet"]) == 1
    assert capsys.readouterr().out == ""
    lines = p.read_text().splitlines()
    assert len(lines) == 1 and lines[0].startswith("freshness|app|readme\tapp README: 11 user-facing")
    commit(r, {"README.md": "# App, updated\n"}, "readme", RECENT)
    assert main(["freshness", "--quiet"]) == 0
    assert not p.exists()


def test_the_digest_and_the_banner_read_the_problems(tmp_path):
    p = freshness.problems_path()
    p.write_text("freshness|app|readme\tapp README: 11 user-facing changes since 2026-10-01 (e.g. \"A\" #1). Update it.\n"
                 "freshness|app|screenshots\tapp store screenshots: 11 user-facing changes. Re-capture.\n")
    assert len(digest.freshness_items()) == 2
    banner = digest.write_banner_items(checks=[], today=dt.date(2026, 11, 8))
    assert "freshness|app|readme" in [ln.split("\t")[0] for ln in banner.read_text().splitlines()]
    cands = {c["id"]: c for c in digest.problem_file_candidates()}
    assert cands["freshness"]["rank"] == 5 and cands["freshness"]["step"] == "teyla freshness"
    assert cands["freshness"]["text"].startswith("2 stale README or store items: app README")


def test_the_weekly_routine_runs_it_before_the_digest():
    t = routine_install.WRAPPER_TEMPLATE
    assert t.index("freshness --quiet") < t.index("digest --write")
