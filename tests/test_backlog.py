"""The GitHub data behind `teyla state`: the merge-approved list, the cache and its refresh. A fake runner
stands in for `gh`; no test starts the real one."""
from __future__ import annotations

import json
import os

from teyla import asks, backlog, config

NOW = 1_800_000_000.0
REAL_SPAWN = backlog.spawn_refresh        # conftest replaces the module attribute for every test

CLAUDE_MD = """# How I want work shipped

- **Merge without asking ONLY in a repo on this list.**

  ```
  MERGE-APPROVED REPOS
    Example-Org/app-one
    example/ops                  # added 2026-08-12, on the owner's instruction
    example/tape                 # sprint kickoff, verbatim: "Create repos at
                                 # https://github.com/example/tape/pull/1 and merge"
    Example-Org/two             # added 2026-08-27
  ```

  That list is the whole permission. Other/repos stay out: not/this either.
"""


def test_merge_approved_is_the_first_token_of_each_line_in_the_fenced_block():
    assert backlog.parse_merge_approved(CLAUDE_MD) == {"example-org/app-one", "example/ops", "example/tape",
                                                       "example-org/two"}


def test_the_marker_may_sit_above_the_fence_and_a_missing_marker_means_none():
    above = "MERGE-APPROVED REPOS\n```\nexample/one\nexample/two  # c\n```\nexample/three\n"
    assert backlog.parse_merge_approved(above) == {"example/one", "example/two"}
    assert backlog.parse_merge_approved("MERGE-APPROVED REPOS\nno fence here\n") == set()
    assert backlog.parse_merge_approved("nothing") == set()


def test_config_overrides_the_file_and_a_missing_file_means_none(tmp_path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(CLAUDE_MD)
    assert "example/ops" in backlog.merge_approved({}, md)
    assert backlog.merge_approved({"state": {"merge_approved": ["Example/One", "bad", "x/y"]}}, md) == {
        "example/one", "x/y"}
    assert backlog.merge_approved({"state": {"merge_approved": []}}, md) == backlog.parse_merge_approved(CLAUDE_MD)
    assert backlog.merge_approved({}, tmp_path / "missing.md") == set()
    assert config.DEFAULTS["state"]["merge_approved"] == []


def test_remote_slug_reads_the_origin_url_of_a_clone(tmp_path):
    def clone(name, text):
        (tmp_path / name / ".git").mkdir(parents=True)
        (tmp_path / name / ".git" / "config").write_text(text)
        return tmp_path / name
    origin = '[remote "upstream"]\n\turl = https://github.com/other/thing\n[remote "origin"]\n\turl = %s\n'
    assert backlog.remote_slug(clone("a", origin % "https://github.com/Example/Atlas.git")) == "Example/Atlas"
    assert backlog.remote_slug(clone("b", origin % "git@github.com:example/cellar.git")) == "example/cellar"
    assert backlog.remote_slug(clone("c", origin % "https://token" + "@github.com/example/lens")) == "example/lens"
    assert backlog.remote_slug(clone("d", origin % "https://gitlab.com/example/lens.git")) == ""
    assert backlog.remote_slug(clone("e", "[core]\n")) == ""
    assert backlog.remote_slug(tmp_path / "missing") == ""


# --- the refresh -------------------------------------------------------------------------------

PRS = {"data": {"search": {"nodes": [
    {"number": 14, "title": "Export", "url": "https://github.com/example/lens/pull/14",
     "createdAt": "2026-10-10T00:00:00Z", "isDraft": False, "headRefOid": "ABC" + "d" * 37,
     "repository": {"nameWithOwner": "example/lens"}},
    {"number": 3, "title": "Draft", "url": "https://github.com/example/atlas/pull/3",
     "createdAt": "2026-10-11T00:00:00Z", "isDraft": True, "headRefOid": "e" * 40,
     "repository": {"nameWithOwner": "example/atlas"}},
    {"title": "no number"}, {"number": 1, "repository": {"nameWithOwner": "not a slug"}}]}}}
ISSUES = [{"number": 88, "title": "Create the record", "url": "https://github.com/example/cellar/issues/88",
           "createdAt": "2026-10-15T00:00:00Z", "repository": {"nameWithOwner": "example/cellar"},
           "labels": [{"name": "bug"}, {"nope": 1}]}]
COUNTS = {"data": {"r0": {"nameWithOwner": "example/atlas", "issues": {"totalCount": 3}},
                   "r1": {"nameWithOwner": "example/cellar-now", "issues": {"totalCount": 12}},
                   "r2": None}}


class FakeGh:
    def __init__(self, prs=(0, PRS), issues=(0, ISSUES), counts=(1, COUNTS)):
        self.calls = []
        self.answers = {"prs": prs, "issues": issues, "counts": counts}

    def __call__(self, argv):
        self.calls.append(argv)
        kind = "issues" if argv[1:3] == ["search", "issues"] else "prs" if "q=" in " ".join(argv) else "counts"
        rc, body = self.answers[kind]
        return rc, json.dumps(body) if not isinstance(body, str) else body, ""


def test_refresh_makes_three_calls_and_writes_a_private_cache():
    gh = FakeGh()
    slugs = ["example/cellar", "example/atlas", "example/gone", "bad slug"]
    assert backlog.refresh(slugs, NOW, gh) == 0
    assert len(gh.calls) == 3                                  # two searches and one query, never one per repo
    pr_call, issue_call, count_call = gh.calls
    assert pr_call[:3] == ["gh", "api", "graphql"] and "is:pr is:open author:@me" in " ".join(pr_call)
    assert issue_call[:7] == ["gh", "search", "issues", "--assignee", "@me", "--state", "open"]
    assert 'owner: "example", name: "atlas"' in count_call[4] and "bad slug" not in count_call[4]
    c = json.loads(backlog.cache_path().read_text())
    assert backlog.cache_path().stat().st_mode & 0o777 == 0o600
    assert c["at"] == NOW and c["version"] == 1
    assert [(p["repo"], p["number"], p["draft"], p["head"]) for p in c["prs"]] == [
        ("example/lens", 14, False, "abc" + "d" * 37), ("example/atlas", 3, True, "e" * 40)]
    assert c["issues"][0]["labels"] == ["bug"] and c["issues"][0]["repo"] == "example/cellar"
    # a partial answer (exit 1, one repo unknown) is still read; GitHub's current name is kept
    assert c["counts"] == {"example/atlas": 3, "example/cellar-now": 12}
    assert c["canonical"] == {"example/atlas": "example/atlas", "example/cellar": "example/cellar-now"}
    assert not backlog.lock_path().exists()


def test_a_failed_call_keeps_the_old_part_stays_unstamped_and_leaves_the_lock():
    assert backlog.refresh(["example/atlas"], NOW - 5000, FakeGh()) == 0
    backlog.lock_path().write_text("")
    gh = FakeGh(prs=(1, "boom"), issues=(0, []), counts=(1, "not json"))
    assert backlog.refresh(["example/atlas"], NOW, gh) == 1
    c = backlog.load()
    assert c["at"] == NOW - 5000                              # not stamped fresh
    assert len(c["prs"]) == 2 and c["counts"] == {"example/atlas": 3}      # the failed parts keep their last value
    assert c["issues"] == []                                  # the part that worked is replaced
    assert backlog.lock_path().exists()                       # the lock backs the next attempt off


def test_refresh_without_gh_does_nothing(monkeypatch):
    monkeypatch.setattr(backlog.shutil, "which", lambda n: None)
    backlog.lock_path().write_text("")
    assert backlog.refresh(["example/atlas"], NOW) == 0
    assert not backlog.cache_path().exists() and not backlog.lock_path().exists()


def test_a_runner_that_cannot_start_is_a_failed_call_not_an_error():
    def broken(argv):
        raise OSError("no gh")
    assert backlog.refresh(["example/atlas"], NOW, broken) == 1
    assert backlog.load() == {**backlog.EMPTY, "prs": [], "issues": [], "counts": {}, "canonical": {}}


def test_counts_are_asked_in_batches_of_forty():
    gh = FakeGh(counts=(0, {"data": {}}))
    slugs = [f"example/repo{n}" for n in range(85)]
    got = backlog.fetch_counts(slugs, gh)
    assert got == ({}, {}) and len(gh.calls) == 3


# --- the cache ---------------------------------------------------------------------------------

def test_the_cache_is_read_with_every_field_and_survives_junk():
    assert backlog.load()["prs"] == []
    backlog.cache_path().write_text("[1]")
    assert backlog.load()["at"] == 0
    backlog.cache_path().write_text(json.dumps({"version": 9, "prs": [1]}))
    assert backlog.load()["prs"] == []
    backlog.cache_path().write_text(json.dumps({"version": 1, "at": "x", "prs": "no", "counts": {"a/b": 1}}))
    c = backlog.load()
    assert (c["at"], c["prs"], c["counts"]) == (0.0, [], {"a/b": 1})


def test_a_stale_or_missing_cache_starts_one_refresh_and_a_fresh_one_does_not(monkeypatch):
    spawned = []
    monkeypatch.setattr(backlog, "spawn_refresh", lambda now=None: spawned.append(1))
    backlog.view(NOW)
    assert spawned == [1]
    asks._atomic_write(backlog.cache_path(), json.dumps({"version": 1, "at": NOW - 60}))
    backlog.view(NOW)
    assert spawned == [1]
    asks._atomic_write(backlog.cache_path(), json.dumps({"version": 1, "at": NOW - backlog.FRESH_S - 1}))
    backlog.view(NOW)
    assert spawned == [1, 1]
    backlog.view(NOW, refresh=False)
    assert spawned == [1, 1]


def test_the_lock_holds_a_second_refresh_back_until_it_is_stale(monkeypatch):
    started = []
    monkeypatch.setattr(backlog.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    REAL_SPAWN(NOW)
    assert len(started) == 1 and started[0][-2:] == ["state", "--refresh-backlog"] and backlog.lock_path().exists()
    os.utime(backlog.lock_path(), (NOW, NOW))
    REAL_SPAWN(NOW + 100)                                      # a refresh is running
    assert len(started) == 1
    REAL_SPAWN(NOW + backlog.LOCK_STALE_S + 1)                 # the lock is stale: take it over
    assert len(started) == 2
