"""teyla whats-new: synthetic git repos in tmp dirs. Nothing here reads a real repo or the network."""
import json
import subprocess

import pytest

from teyla import whats_new as wn
from teyla.cli import main

ENV = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo, *args):
    import os
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **ENV})


def merge(repo, n, branch, title):
    git(repo, "checkout", "-q", "-b", branch)
    (repo / f"f{n}.txt").write_text(str(n))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"work {n}")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", branch, "-m", f"Merge pull request #{n} from owner/{branch}", "-m", title)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "app"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("a")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "first")
    merge(r, 1, "old", "Old feature before the release")
    git(r, "tag", "v1.0.0")
    merge(r, 2, "share", "Share a trip as a link")
    merge(r, 3, "docs-x", "docs: explain the setup")
    merge(r, 4, "dark", "Dark mode for the map")
    merge(r, 5, "bump", "Bump the build number")
    return r


def test_draft_splits_user_facing_and_internal(repo, capsys):
    assert main(["whats-new", "draft", str(repo), "--version", "1.1"]) == 0
    out = capsys.readouterr().out
    user, internal = out.split("## Internal")
    assert "Share a trip as a link" in user and "Dark mode for the map" in user
    assert "docs: explain the setup" in internal and "Bump the build number" in internal
    assert "Old feature" not in out
    assert "since v1.0.0" in out and "Template body" in out


def test_default_since_picks_newest_version_tag(repo):
    git(repo, "tag", "android-v1.2.0")
    git(repo, "tag", "nightly")
    merge(repo, 6, "late", "Offline maps")
    assert wn.newest_version_tag(repo) == "android-v1.2.0"
    titles = [i["title"] for i in wn.merged_changes(repo, "android-v1.2.0")]
    assert titles == ["Offline maps"]


def test_no_tag_asks_for_since(tmp_path, capsys):
    r = tmp_path / "bare"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a").write_text("a")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "first")
    assert main(["whats-new", "draft", str(r), "--version", "1.0"]) == 2
    assert "--since" in capsys.readouterr().err


def test_write_placeholders_only_and_refuse_overwrite(repo, capsys):
    assert main(["whats-new", "draft", str(repo), "--version", "1.1", "--locales", "en,es", "--write"]) == 0
    for loc in ("en", "es"):
        assert (repo / "docs/whats-new/1.1" / f"{loc}.txt").read_text().strip() == wn.PLACEHOLDER
    assert "Share a trip" not in (repo / "docs/whats-new/1.1/en.txt").read_text()
    (repo / "docs/whats-new/1.1/en.txt").write_text("Share a trip as a link.\n")
    capsys.readouterr()
    assert main(["whats-new", "draft", str(repo), "--version", "1.1", "--locales", "en,es", "--write"]) == 1
    assert "not overwritten" in capsys.readouterr().out
    assert (repo / "docs/whats-new/1.1/en.txt").read_text() == "Share a trip as a link.\n"


def note(repo, name, text):
    d = repo / "docs/whats-new/1.1"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_check_passes_real_note_and_language_fallback(repo, capsys):
    note(repo, "en.txt", "You can now share a trip as a link.")
    assert main(["whats-new", "check", str(repo), "--version", "1.1", "--locales", "en,en-US"]) == 0


def test_check_fails_missing_placeholder_generic(repo, capsys):
    note(repo, "en.txt", wn.PLACEHOLDER)
    note(repo, "es.txt", "  Bug fixes and improvements!  ")
    note(repo, "fr.txt", "Corrección de errores y mejoras.")
    note(repo, "de.txt", "\n")
    rc = main(["whats-new", "check", str(repo), "--version", "1.1", "--locales", "en,es,fr,de,it"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 1 and len(out) == 5
    assert "placeholder" in out[0] and "generic" in out[1] and "generic" in out[2]
    assert "empty" in out[3] and "no file" in out[4]
    assert all("teyla whats-new draft" in line for line in out)


def test_check_json(repo, capsys):
    note(repo, "en.txt", "Minor improvements")
    assert main(["whats-new", "check", str(repo), "--version", "1.1", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["locales"]["en"]["ok"] is False


def test_generic_list_covers_other_scripts():
    assert wn.is_generic("Performance improvements")
    assert wn.is_generic("mejoras y corrección de errores")
    assert not wn.is_generic("Fixes a crash when sharing a trip")


def test_squash_merge_next_to_merge_commits_is_listed(repo):
    (repo / "s.txt").write_text("s")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Offline maps for saved trips (#6)")
    items = wn.merged_changes(repo, "v1.0.0")
    assert {"pr": 6, "title": "Offline maps for saved trips"} in items
    assert {"pr": 2, "title": "Share a trip as a link"} in items


def test_note_made_only_of_stock_lines_is_generic():
    assert wn.is_generic("- Bug fixes.\n- Performance improvements.\n")
    assert not wn.is_generic("- Bug fixes.\n- Share a trip as a link.\n")
