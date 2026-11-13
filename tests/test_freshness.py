"""teyla freshness: synthetic git repos in tmp dirs. Nothing here reads a real repo, the network or the real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
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
    assert c["text"].endswith("then run `teyla freshness --reviewed` and commit.") and "#" in c["text"]
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
          "![remote](https://example.com/shot.png)\n![gone](docs/missing.png)\n" + BODY)
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=RECENT)
    features(r, 11, when=RECENT)
    assert freshness.readme_images(r) == ["docs/old.png", "docs/new.png", "assets/dark.svg"]
    assert [x for x in freshness.readme_images(r) if not freshness.is_brand_image(x)] == ["docs/old.png", "docs/new.png"]
    c = checks(freshness.run()[0])["readme-images"]
    assert c["verdict"] == "stale" and c["path"] == "docs/old.png"
    assert "README image docs/old.png" in c["text"]
    assert checks(freshness.run()[0])["readme"]["verdict"] == "ok"   # README itself just had a real edit


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
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "skip" and c["text"] == ""


@pytest.mark.parametrize("toml", ['[productize.distribution]\nios = "testflight-internal"\n',
                                  '[productize.distribution]\nandroid = "play-internal"\n'])
def test_a_store_product_with_no_notes_yet_is_skipped_not_stale(tmp_path, toml):
    r = product(tmp_path, toml)
    features(r, 12)
    row = freshness.run()[0]
    c = checks(row)["whats-new"]
    assert c["verdict"] == "skip" and c["text"] == "no What's New file yet (a first store version has none)"
    assert row["verdict"] == "stale" and "whats-new" not in freshness.render_text([row])   # only the README


@pytest.mark.parametrize("rel", ["content/store/play/en-US/release_notes.txt", "apps/store/listing/ios/en-US/whats_new.txt",
                                 "docs/whats-new-1.2.txt", "custom/notes/en.txt"])
def test_notes_in_other_places_are_found_and_go_stale(tmp_path, rel):
    r = product(tmp_path, '[freshness]\nwhats_new = ["custom/notes/*.txt"]\n', files={rel: "Share a trip as a link\n"})
    features(r, 11)
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "stale" and c["changes"] == 11 and c["path"] != "docs/whats-new"


def test_a_generic_note_outside_docs_is_flagged(tmp_path):
    product(tmp_path, files={"content/store/app-store/en-US/release_notes.txt": "Bug fixes and improvements\n"},
            first_when=RECENT)
    c = checks(freshness.run()[0])["whats-new"]
    assert c["verdict"] == "stale" and "release_notes.txt is a generic line" in c["text"]


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
    r = product(tmp_path, '[freshness]\nlisting = ["store-text/*.txt"]\nscreenshots = ["nothing/**"]\n',
                files={"store-text/en.txt": "t", "docs/screenshots/a.png": "p"})
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
    commit(r, {"README.md": "# App, updated\n" + BODY}, "readme", RECENT)   # a real edit, not a one-line patch
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
    assert t.index("freshness --fetch --quiet") < t.index("digest --write")


def _merge_files(repo, n, title, files, when=RECENT):
    git(repo, "checkout", "-q", "-b", f"m{n}")
    for f in files:
        write(repo, f, f'# {n}\n[product]\nname = "app"\n' if f == "teyla.toml" else str(n))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"work {n}", when=when)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", f"m{n}", "-m", f"Merge pull request #{n} from owner/m{n}", "-m", title, when=when)


def test_a_change_that_touches_only_maintenance_paths_is_not_user_facing(tmp_path):
    r = product(tmp_path, files={"fastlane/screenshots/a.png": "a", "docs/whats-new/1.0/en.txt": "Share a trip\n"})
    maintenance = [["scripts/leak_check.py", ".githooks/pre-push"], ["README.md", "docs/x.md"], ["teyla.toml"],
                   ["tests/test_a.py"], ["app/Tests/AppTests/ATests.swift"], ["app/Sources/FooTest.swift"],
                   ["package-lock.json", "Cargo.lock"], ["brand/logo.svg", "design/a.fig"], [".github/w.yml"],
                   ["fastlane/screenshots/b.png"], ["check.sh", ".leak-allow"], ["docs/whats-new/1.1/en.txt"]]
    for i, files in enumerate(maintenance, 1):
        _merge_files(r, i, f"Regenerate gate {i}", files)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["changes"] == 0 and c["examples"] == []


def test_one_product_path_makes_a_change_user_facing_and_examples_come_from_the_filtered_list(tmp_path):
    r = product(tmp_path)
    _merge_files(r, 1, "Shield: leak-gate hooks and owner-data fixes", [".githooks/pre-push"])
    for i in range(2, 13):
        _merge_files(r, i, f"Share a trip as a link {i}", ["docs/a.md", f"app/Sources/Feature{i}.swift"])
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "stale" and c["changes"] == 11
    assert all("Shield" not in e for e in c["examples"]) and "Share a trip" in c["text"]


def test_a_single_parent_commit_is_judged_by_its_own_files(tmp_path):
    r = product(tmp_path)
    for i in range(11):
        commit(r, {f"app/Sources/F{i}.swift": "x"}, f"Add feature {i}", RECENT)
    for i in range(5):
        commit(r, {f"docs/n{i}.md": "x"}, f"Add notes {i}", RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "stale" and c["changes"] == 11


def test_the_listing_and_screenshot_globs_are_maintenance_too(tmp_path):
    r = product(tmp_path, '[freshness]\nlisting = ["store-text/*.txt"]\nscreenshots = ["shots/**"]\n')
    for i in range(1, 13):
        _merge_files(r, i, f"Update store art {i}", [f"store-text/{i}.txt", f"shots/{i}.jpg"])
    assert checks(freshness.run()[0])["readme"]["changes"] == 0


def test_counting_and_dating_use_the_default_branch_not_the_checked_out_one(tmp_path):
    r = product(tmp_path)
    features(r, 11)
    git(r, "checkout", "-q", "-b", "wip")
    for i in range(30):
        commit(r, {f"app/Sources/Wip{i}.swift": "x"}, f"Add wip {i}", RECENT)
    assert checks(freshness.run()[0])["readme"]["changes"] == 11   # the 30 on `wip` are not on main


def test_files_are_discovered_on_the_default_branch_even_from_a_feature_branch(tmp_path):
    r = product(tmp_path, files={"docs/screenshots/a.png": "a", "docs/shot.png": "s",
                                 "content/store/en/list.txt": "t"})
    write(r, "README.md", "# App\n![s](docs/shot.png)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=OLD)
    features(r, 11)
    git(r, "checkout", "-q", "-b", "cleanup")
    git(r, "rm", "-q", "-r", "docs/screenshots", "docs/shot.png", "content")
    write(r, "README.md", "# App without images\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "remove everything", when=RECENT)
    c = checks(freshness.run()[0])
    assert c["screenshots"]["verdict"] == "stale" and c["listing"]["verdict"] == "stale"
    assert c["readme-images"]["verdict"] == "stale" and c["readme-images"]["path"] == "docs/shot.png"
    assert c["readme"]["verdict"] == "stale"


def test_release_notes_do_not_reset_the_listing_date(tmp_path):
    r = product(tmp_path, files={"fastlane/metadata/en-US/description.txt": "d",
                                 "fastlane/metadata/en-US/release_notes.txt": "Share a trip as a link\n"})
    features(r, 11)
    commit(r, {"fastlane/metadata/en-US/release_notes.txt": "Dark mode for the map\n"}, "notes", RECENT)
    c = checks(freshness.run()[0])
    assert c["listing"]["verdict"] == "stale" and c["listing"]["since"] == OLD[:10]
    assert c["whats-new"]["verdict"] == "ok"
    r2 = product(tmp_path, name="notes-only", files={"fastlane/metadata/en-US/release_notes.txt": "A real note\n"})
    assert checks(freshness.run([str(r2)])[0])["listing"]["verdict"] == "skip"


@pytest.mark.parametrize("rel", ["brand/shot.png", "docs/Logo-dark.png", "docs/app-icon.png", "docs/lockup.png",
                                 "docs/badge.png", "docs/watermark.png", "design/logo.svg", "docs/diagram.svg"])
def test_logos_and_brand_marks_are_not_readme_screenshots(tmp_path, rel):
    r = product(tmp_path, files={rel: "x"})
    write(r, "README.md", f"# App\n![x]({rel})\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme", when=OLD)
    features(r, 11)
    assert checks(freshness.run()[0])["readme-images"]["verdict"] == "skip"
    commit(r, {"docs/home.png": "h"}, "shot", OLD)
    write(r, "README.md", f"# App\n![x]({rel})\n![h](docs/home.png)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "readme again", when=OLD)
    assert checks(freshness.run()[0])["readme-images"]["path"] == "docs/home.png"


# --- --fetch ---------------------------------------------------------------------------

def _spy_fetch(monkeypatch, result=None):
    calls = []
    monkeypatch.setattr(freshness, "fetch_origin", lambda repo: calls.append(repo.name) or result)
    return calls


def test_fetch_runs_once_per_repo_and_is_recorded(tmp_path, monkeypatch):
    product(tmp_path, name="one")
    product(tmp_path, name="two")
    calls = _spy_fetch(monkeypatch)
    rows = freshness.run(fetch=True)
    assert sorted(calls) == ["one", "two"]
    assert [r["fetch"] for r in rows] == ["ok", "ok"]


def test_no_fetch_without_the_flag(tmp_path, monkeypatch):
    product(tmp_path)
    calls = _spy_fetch(monkeypatch)
    rows = freshness.run()
    assert calls == [] and "fetch" not in rows[0]
    main(["freshness"])
    assert calls == []


def test_a_failed_fetch_is_noted_and_not_fatal(tmp_path, monkeypatch, capsys):
    r = product(tmp_path)
    features(r, 11)
    _spy_fetch(monkeypatch, "could not resolve host")
    rows = freshness.run(fetch=True)
    assert rows[0]["fetch"] == "failed: could not resolve host"
    assert rows[0]["verdict"] == "stale"               # checked against the last known refs
    assert main(["freshness", "--fetch"]) == 1
    out = capsys.readouterr().out
    assert "app: fetch failed: could not resolve host; read the last known refs" in out
    assert "app: 1 stale" in out


def test_fetch_origin_reports_failure_without_raising(tmp_path):
    r = product(tmp_path)                              # no remote named origin
    reason = freshness.fetch_origin(r)
    assert reason and "origin" in reason
    assert freshness.fetch_origin(tmp_path / "missing") is not None


def test_fetch_origin_updates_the_tracking_refs(tmp_path):
    r = product(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(r), str(bare)], check=True, capture_output=True)
    git(r, "remote", "add", "origin", str(bare))
    assert freshness.fetch_origin(r) is None
    assert subprocess.run(["git", "-C", str(r), "rev-parse", "origin/main"], capture_output=True).returncode == 0


def test_json_has_the_fetch_note_only_with_the_flag(tmp_path, monkeypatch, capsys):
    r = product(tmp_path, first_when=RECENT)
    _spy_fetch(monkeypatch, "timed out after 30 s")
    assert main(["freshness", str(r), "--json", "--fetch"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["fetch"] == "failed: timed out after 30 s"
    assert main(["freshness", str(r), "--json"]) == 0
    assert "fetch" not in json.loads(capsys.readouterr().out)[0]


def test_the_hint_shows_only_when_stale_and_not_fetched(tmp_path, monkeypatch, capsys):
    ok = product(tmp_path, name="ok-app", first_when=RECENT)
    assert main(["freshness", str(ok)]) == 0
    assert "--fetch" not in capsys.readouterr().out
    stale = product(tmp_path, name="stale-app")
    features(stale, 11)
    assert main(["freshness", str(stale)]) == 1
    assert freshness.HINT in capsys.readouterr().out
    _spy_fetch(monkeypatch)
    assert main(["freshness", str(stale), "--fetch"]) == 1
    assert freshness.HINT not in capsys.readouterr().out


def test_safe_mode_refuses_the_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    product(tmp_path, name="app")
    calls = _spy_fetch(monkeypatch)
    rows = freshness.run(fetch=True)
    assert calls == [] and "fetch" not in rows[0]
    main(["freshness", "--fetch"])
    assert "safe mode is on" in capsys.readouterr().err
    assert calls == []


# --- a touch is not an edit; the review mark; burst; surfaces ---------------------------

BODY = "".join(f"line {i}\n" for i in range(30))


def test_a_one_line_patch_does_not_make_the_readme_current(tmp_path):
    r = product(tmp_path)
    commit(r, {"README.md": "# App\n" + BODY}, "the README, written once", OLD)
    features(r, 12)
    commit(r, {"README.md": "# App\n" + BODY + "one more line\n"}, "name the new flag", RECENT)
    commit(r, {"README.md": "# App\n" + BODY + "one more line\nand another\n"}, "and its default", RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "stale" and c["since"] == OLD[:10] and c["changes"] == 12
    assert "its last real edit (2 later commits changed under 10 lines)" in c["text"]


def test_a_real_edit_resets_the_readme_date(tmp_path):
    r = product(tmp_path)
    features(r, 12)
    commit(r, {"README.md": "# App, as it is today\n" + BODY}, "rewrite the README", RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["since"] == RECENT[:10] and c["changes"] == 0


def test_a_pr_of_small_commits_is_one_edit(tmp_path):
    r = product(tmp_path)
    features(r, 12)
    git(r, "checkout", "-q", "-b", "docs")
    text = "# App\n"
    for i in range(3):
        text += "".join(f"part {i} line {j}\n" for j in range(4))
        commit(r, {"README.md": text}, f"README part {i}", RECENT)
    git(r, "checkout", "-q", "main")
    git(r, "merge", "-q", "--no-ff", "docs", "-m", "Merge pull request #90 from owner/docs", "-m", "docs: README",
        when=RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["since"] == RECENT[:10]


def test_the_review_mark_resets_the_readme_date_and_the_command_writes_it(tmp_path, capsys):
    r = product(tmp_path)
    features(r, 12)
    assert checks(freshness.run()[0])["readme"]["verdict"] == "stale"
    assert main(["freshness", "--reviewed", str(r)]) == 0
    assert "teyla:reviewed" in capsys.readouterr().out
    today = dt.date.today().isoformat()
    assert (r / "README.md").read_text() == f"# App\n\n<!-- teyla:reviewed {today} -->\n"
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "README reviewed: nothing to change", when=RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["since"] == RECENT[:10]
    # a second run replaces the mark, it does not stack them
    (r / "README.md").write_text("# App\n\n<!-- teyla:reviewed 2026-01-01 -->\n")
    assert freshness.mark_reviewed(r, dt.date(2026, 2, 2)) == "<!-- teyla:reviewed 2026-02-02 -->"
    assert (r / "README.md").read_text() == "# App\n\n<!-- teyla:reviewed 2026-02-02 -->\n"


def test_reviewed_takes_one_repo_and_needs_a_readme(tmp_path, capsys):
    a, b = product(tmp_path, name="a"), product(tmp_path, name="b")
    assert main(["freshness", "--reviewed", str(a), str(b)]) == 2
    (a / "README.md").unlink()
    assert main(["freshness", "--reviewed", str(a)]) == 2
    assert "no README.md" in capsys.readouterr().err


def test_a_burst_of_changes_makes_a_young_readme_stale(tmp_path):
    r = product(tmp_path, first_when=RECENT)
    features(r, 50)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "stale" and c["changes"] == 50
    (r / "teyla.toml").write_text('[product]\nname = "app"\n[freshness]\nburst = 0\n')
    assert checks(freshness.run()[0])["readme"]["verdict"] == "ok"


def test_the_burst_rule_leaves_the_store_checks_alone(tmp_path):
    r = product(tmp_path, first_when=RECENT, files={"fastlane/screenshots/a.png": "a"})
    features(r, 50)
    assert checks(freshness.run()[0])["screenshots"]["verdict"] == "ok"


SURFACE = '[freshness.surfaces]\n"docs/shots/*.png" = ["app/ui/**"]\n'


def test_an_image_with_a_surface_counts_only_the_changes_to_it(tmp_path):
    r = product(tmp_path, SURFACE, files={"docs/shots/home.png": "h"})
    commit(r, {"README.md": "# App\n![home](docs/shots/home.png)\n"}, "readme", OLD)
    features(r, 12)                                        # twelve changes elsewhere in the repo
    c = checks(freshness.run()[0])["readme-images"]
    assert c["verdict"] == "ok" and c["changes"] == 0
    for i in range(20, 25):
        _merge_files(r, i, f"Home screen change {i}", [f"app/ui/Home{i}.swift"])
    c = checks(freshness.run()[0])["readme-images"]
    assert c["verdict"] == "stale" and c["changes"] == 5 and c["path"] == "docs/shots/home.png"
    assert "5 user-facing changes to app/ui/** since" in c["text"] and c["text"].endswith("from the current build.")


def test_a_surface_image_goes_stale_at_any_age_and_the_count_is_configurable(tmp_path):
    r = product(tmp_path, SURFACE + "[freshness]\nsurface_changes = 2\n", first_when=RECENT,
                files={"docs/shots/home.png": "h"})
    commit(r, {"README.md": "# App\n![home](docs/shots/home.png)\n"}, "readme", RECENT)
    _merge_files(r, 1, "Home screen change 1", ["app/ui/A.swift"])
    assert checks(freshness.run()[0])["readme-images"]["verdict"] == "ok"
    _merge_files(r, 2, "Home screen change 2", ["app/ui/B.swift"])
    assert checks(freshness.run()[0])["readme-images"]["verdict"] == "stale"


def test_every_stale_image_is_named(tmp_path):
    r = product(tmp_path, files={"docs/a.png": "a", "docs/b.png": "b"})
    commit(r, {"README.md": "# App\n![a](docs/a.png)\n![b](docs/b.png)\n"}, "readme", OLD)
    features(r, 12)
    c = checks(freshness.run()[0])["readme-images"]
    assert c["verdict"] == "stale" and c["path"] in ("docs/a.png", "docs/b.png")
    assert "Also stale: docs/" in c["text"]


def test_release_and_build_number_titles_are_not_user_facing(tmp_path):
    r = product(tmp_path)
    for i, title in enumerate(["release 0.52.0", "Release v1.2", "iPhone build 11 (first upload)", "Build 4",
                               "macOS build 7"] * 3, 1):
        merge(r, i, title, RECENT)
    c = checks(freshness.run()[0])["readme"]
    assert c["verdict"] == "ok" and c["changes"] == 0
    merge(r, 99, "Build the importer for bank files", RECENT)
    assert checks(freshness.run()[0])["readme"]["changes"] == 1


def test_the_daily_routine_runs_it_before_doctor_builds_the_banner():
    t = routine_install.DAILY_WRAPPER_TEMPLATE
    assert t.index("teyla freshness --fetch --quiet") < t.index("teyla doctor --quiet")
    assert routine_install._quiet_checks_after_doctor("teyla doctor --quiet\nteyla freshness --fetch --quiet\n")


def test_session_start_names_this_repo_s_stale_items_and_no_other_repo_s(tmp_path):
    home = tmp_path / "home"
    (home / ".teyla" / "freshness.problems").write_text(
        "freshness|app|readme\tapp README: 60 user-facing changes since 2026-10-01. Read the whole README.\n"
        "freshness|other|readme\tother README: 12 user-facing changes since 2026-10-01. Read it.\n")
    cwd = tmp_path / "work"
    cwd.mkdir()
    (cwd / "teyla.toml").write_text('[product]\nname = "app"\n')
    hook = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "session-start.sh"
    out = subprocess.run(["sh", str(hook)], input="", capture_output=True, text=True, timeout=10, cwd=cwd,
                         env={"HOME": str(home), "PATH": "/usr/bin:/bin"}).stdout
    assert "teyla: stale, fix it in this session: app README: 60 user-facing changes" in out
    assert "other README" not in out
