"""teyla.cloud — readiness per repo, cloud sessions from git trailers, A19, the inbox.

Every repo here is a real git repo in tmp_path; HOME points into tmp_path so the owner's
CLAUDE.md, config.toml and any gh or git config are the test's own, never the machine's."""
from __future__ import annotations

import datetime as dt
import json
import subprocess

import pytest

from teyla import advise as advise_mod
from teyla import cloud, config, monitor, report

OWNER_MD = """# How I want work shipped

- **Merge without asking ONLY in a repo on this list.**

  ```
  MERGE-APPROVED REPOS
    acme/ready                  # added 2026-09-01 as acme/old-name, on the owner's instruction
    acme/tool                   # added 2026-09-02
                                # acme/only-in-a-comment is not an entry
  ```
"""


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid"),
                 ("GIT_CONFIG_NOSYSTEM", "1")):
        monkeypatch.setenv(k, v)
    return home


def _git(repo, *args, env=None):
    import os
    e = dict(os.environ, **(env or {}))
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=e).stdout


def _repo(tmp_path, name="ready", slug="acme/ready", files=None):
    r = tmp_path / "code" / name
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    if slug:
        _git(r, "remote", "add", "origin", f"https://github.com/{slug}.git")
    for rel, text in (files or {}).items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return r


PREPARED_AGENTS = """# ready

<!-- teyla:cloud:start -->
## Shipping
merge-approved: yes
- One PR per logical unit.
- Merge, don't squash. Never force-push.
- Done in a cloud session: branch pushed, PR open, `needs-mac` label when a Mac step was skipped.
<!-- teyla:cloud:end -->
"""
PREPARED_SETTINGS = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "sh start.sh"}]}],
                                          "Stop": [{"hooks": [{"type": "command", "command": "sh stop.sh"}]}]}})


def _prepared(tmp_path, **kw):
    files = {"AGENTS.md": PREPARED_AGENTS, "CLAUDE.md": "@AGENTS.md\n", ".claude/settings.json": PREPARED_SETTINGS,
             "check.sh": "#!/bin/sh\nset -e\npython -m pytest -q\n"}
    files.update(kw.pop("files", {}))
    return _repo(tmp_path, files=files, **kw)


def _by(report_):
    return {i["name"]: i for i in report_["items"]}


# --- the owner's list ---------------------------------------------------------------

def test_owner_list_takes_first_token_and_ignores_comments():
    assert cloud.parse_owner_list(OWNER_MD) == {"acme/ready", "acme/tool"}


def test_owner_list_absent_block_is_none():
    assert cloud.parse_owner_list("# nothing here\n") is None


def test_origin_slug_https_and_ssh(tmp_path):
    r = _repo(tmp_path, slug="acme/ready")
    assert cloud.origin_slug(r) == "acme/ready"
    r2 = _repo(tmp_path, name="ssh", slug=None)
    _git(r2, "remote", "add", "origin", "git@github.com:acme/ssh-repo.git")
    assert cloud.origin_slug(r2) == "acme/ssh-repo"


# --- the check ----------------------------------------------------------------------

def test_empty_repo_is_blocked_on_instructions_and_done_state(tmp_path):
    rep = cloud.check_repo(_repo(tmp_path), owners=set(), net=False)
    by = _by(rep)
    assert not rep["ready"]
    assert by["instructions"]["level"] == "BLOCK"
    assert by["shipping"]["level"] == "BLOCK"
    assert by["gate"]["level"] == "WARN"


def test_prepared_repo_is_ready(tmp_path, _home):
    (_home / ".claude" / "CLAUDE.md").write_text(OWNER_MD)
    rep = cloud.check_repo(_prepared(tmp_path), net=False)
    assert rep["ready"], rep
    assert all(i["level"] in ("OK", "INFO") for i in rep["items"]), rep["items"]
    assert "visibility" not in _by(rep)  # net=False never asks gh


def test_claude_dir_ignored_wholesale_blocks(tmp_path):
    r = _prepared(tmp_path, files={".gitignore": ".claude/*\n!.claude/agents/\n"})
    by = _by(cloud.check_repo(r, owners=set(), net=False))
    assert by["gitignore"]["level"] == "BLOCK"
    assert ".claude/settings.json" in by["gitignore"]["detail"]


def test_narrow_claude_ignores_are_fine(tmp_path):
    r = _prepared(tmp_path, files={".gitignore": ".claude/settings.local.json\n.claude/launch.json\n.claude/worktrees/\n"})
    assert _by(cloud.check_repo(r, owners=set(), net=False))["gitignore"]["level"] == "OK"


def test_pointer_to_home_policy_blocks_without_cloud_section(tmp_path):
    r = _repo(tmp_path, files={"AGENTS.md": "# x\n\nMerge-approved per `~/.claude/CLAUDE.md`.\nlogs in ~/Library/Logs/x.log\n"})
    item = _by(cloud.check_repo(r, owners=set(), net=False))["home-refs"]
    assert item["level"] == "BLOCK"
    assert "AGENTS.md:3" in item["detail"] and "1 other line" in item["detail"]
    assert "~/" not in item["detail"]  # pasteable: the report never repeats a home path


def test_pointer_with_cloud_section_is_only_a_warning(tmp_path):
    r = _prepared(tmp_path, files={"AGENTS.md": PREPARED_AGENTS + "\nSee ~/.agents/POLICY.md locally.\n"})
    assert _by(cloud.check_repo(r, owners=set(), net=False))["home-refs"]["level"] == "WARN"


def test_symlinked_instructions_are_read_once_and_named_by_the_real_file(tmp_path):
    r = _repo(tmp_path, files={"AGENTS.md": "x\nsee ~/.claude/CLAUDE.md\n"})
    (r / "CLAUDE.md").symlink_to("AGENTS.md")
    item = _by(cloud.check_repo(r, owners=set(), net=False))["home-refs"]
    assert item["detail"].startswith("AGENTS.md:2 ")
    assert "CLAUDE.md:" not in item["detail"]


def test_symlink_out_of_the_repo_does_not_count_and_blocks(tmp_path):
    """review of #70, P1: CLAUDE.md -> a home-directory policy carries nothing in a cloud clone."""
    outside = tmp_path / "elsewhere" / "policy.md"
    outside.parent.mkdir()
    outside.write_text(PREPARED_AGENTS)
    r = _prepared(tmp_path, files={"AGENTS.md": "# app\n"})
    (r / "CLAUDE.md").unlink()
    (r / "CLAUDE.md").symlink_to(outside)
    assert cloud.instruction_files(r) == [("AGENTS.md", "# app\n")]
    rep = cloud.check_repo(r, owners=set(), net=False)
    by = _by(rep)
    assert by["instructions"]["level"] == "BLOCK" and "CLAUDE.md" in by["instructions"]["detail"]
    assert by["shipping"]["level"] == "BLOCK"  # the outside rules were not counted toward readiness
    assert not rep["ready"]


def test_only_an_external_symlink_is_not_an_instruction_file(tmp_path):
    outside = tmp_path / "policy.md"
    outside.write_text("rules\n")
    r = _repo(tmp_path)
    (r / "AGENTS.md").symlink_to(outside)
    assert _by(cloud.check_repo(r, owners=set(), net=False))["instructions"]["level"] == "BLOCK"


@pytest.mark.parametrize("line,level", [("merge-approved: yes", "OK"), ("merge-approved: no", "BLOCK"), ("", "WARN")])
def test_merge_approved_line_against_the_owner_list(tmp_path, _home, line, level):
    (_home / ".claude" / "CLAUDE.md").write_text(OWNER_MD)
    r = _prepared(tmp_path, files={"AGENTS.md": PREPARED_AGENTS.replace("merge-approved: yes", line)})
    item = _by(cloud.check_repo(r, net=False))["merge-approved"]
    assert item["level"] == level
    if level == "BLOCK":
        assert "drift" in item["detail"] and "says no" in item["detail"] and "list says yes" in item["detail"]


def test_repo_not_on_the_list_expects_no(tmp_path, _home):
    (_home / ".claude" / "CLAUDE.md").write_text(OWNER_MD)
    r = _prepared(tmp_path, name="other", slug="acme/only-in-a-comment")
    item = _by(cloud.check_repo(r, net=False))["merge-approved"]
    assert item["level"] == "BLOCK" and "list says no" in item["detail"]
    assert "acme/ready" not in json.dumps(cloud.check_repo(r, net=False))  # the list itself never leaks


def test_no_owner_list_is_info_not_a_failure(tmp_path):
    rep = cloud.check_repo(_prepared(tmp_path), net=False)
    assert _by(rep)["merge-approved"]["level"] == "INFO"


def test_missing_hooks_warn(tmp_path):
    r = _prepared(tmp_path, files={".claude/settings.json": json.dumps({"permissions": {}})})
    item = _by(cloud.check_repo(r, owners=set(), net=False))["hooks"]
    assert item["level"] == "WARN" and "SessionStart" in item["detail"] and "Stop" in item["detail"]


GATE = """#!/bin/sh
set -e
python -m pytest -q
if command -v xcodebuild >/dev/null 2>&1; then
  xcodebuild -scheme App build
else
  echo "skipped here: ios (no Xcode)"
fi
echo "no swift build here"
swift test
"""


def test_mac_steps_guarded_unguarded_and_quoted():
    steps = cloud.mac_steps(GATE)
    assert {(s["tool"], s["guarded"]) for s in steps} == {("xcodebuild", True), ("swift", False)}
    assert [s["line"] for s in steps if not s["guarded"]] == [10]


def test_gate_warns_on_unguarded_mac_step(tmp_path):
    r = _prepared(tmp_path, files={"check.sh": GATE})
    item = _by(cloud.check_repo(r, owners=set(), net=False))["gate"]
    assert item["level"] == "WARN" and "swift (line 10)" in item["detail"]


def test_gate_guarded_but_silent_warns(tmp_path):
    silent = "#!/bin/sh\nif command -v xcodebuild >/dev/null; then\n  xcodebuild build\nfi\n"
    item = _by(cloud.check_repo(_prepared(tmp_path, files={"check.sh": silent}), owners=set(), net=False))["gate"]
    assert item["level"] == "WARN" and "no skip is printed" in item["detail"]


def test_step_after_a_completed_guarded_block_is_not_guarded():
    """review of #70, P2: the guard search must not cross `fi`."""
    gate = ("if command -v xcodebuild >/dev/null; then\n  xcodebuild build\nelse\n  echo skipped here: ios\nfi\n"
            "xcodebuild test\n")
    assert [(s["line"], s["guarded"]) for s in cloud.mac_steps(gate) if s["line"] > 1] == [(2, True), (6, False)]


def test_else_of_a_positive_guard_is_unguarded_but_else_of_a_negated_one_is_guarded():
    pos = "if command -v xcodebuild; then\n  echo have\nelse\n  xcodebuild test\nfi\n"
    neg = "if ! command -v xcodebuild; then\n  echo skipped here: ios\nelse\n  xcodebuild test\nfi\n"
    step = lambda text: [s for s in cloud.mac_steps(text) if s["line"] == 4][0]["guarded"]  # noqa: E731
    assert step(pos) is False
    assert step(neg) is True


def test_secret_names_need_a_manifest_and_values_never_show(tmp_path):
    env = "OPENAI_API_KEY=sk-live-should-never-appear\n# comment\nAPP_URL=https://x\n"
    r = _prepared(tmp_path, files={".env.example": env})
    item = _by(cloud.check_repo(r, owners=set(), net=False))["secrets"]
    assert item["level"] == "WARN" and "OPENAI_API_KEY" in item["detail"]
    assert "sk-live" not in json.dumps(item)
    (r / "docs").mkdir()
    (r / "docs" / "cloud-setup.md").write_text("| OPENAI_API_KEY | API credentials |\n| APP_URL | env |\n")
    assert _by(cloud.check_repo(r, owners=set(), net=False))["secrets"]["level"] == "OK"


def test_cli_exit_code_and_json(tmp_path, capsys):
    from teyla.cli import main
    blocked = _repo(tmp_path, name="bare", slug=None)
    assert main(["cloud", "check", str(blocked), "--no-net"]) == 1
    assert "cloud-ready 0/1 repos" in capsys.readouterr().out
    ok = _prepared(tmp_path)
    assert main(["cloud", "check", str(ok), "--no-net", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["ready"] is True


def test_doctor_line_counts_ready_repos_without_network(tmp_path, monkeypatch):
    _prepared(tmp_path)
    _repo(tmp_path, name="bare", slug=None)

    def no_gh(*a, **k):
        raise AssertionError("doctor must not call gh")
    monkeypatch.setattr(cloud, "visibility", no_gh)
    c = cloud.doctor_check({"code_root": str(tmp_path / "code")})
    assert c["level"] == "INFO"
    assert c["detail"].startswith("cloud-ready 1/2 repos; not ready: bare")
    assert c["fix"] == "teyla cloud check"


def test_safe_mode_means_no_gh(monkeypatch):
    monkeypatch.setattr(cloud.shutil, "which", lambda n: "/usr/bin/gh")
    assert cloud.gh_usable()
    monkeypatch.setenv("TEYLA_SAFE", "1")
    if hasattr(config, "safe_mode"):
        monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    assert not cloud.gh_usable()


# --- cloud sessions from git -------------------------------------------------------------

def _session_repo(tmp_path):
    """origin (bare) + clone: main with one landed cloud commit, and `claude/brave-x` with two
    unlanded cloud commits pushed to origin — the shape the September runs left."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    r = _repo(tmp_path, name="app", slug=None)
    _git(r, "remote", "add", "origin", str(bare))
    old = {"GIT_COMMITTER_DATE": "2026-09-20T10:00:00+00:00", "GIT_AUTHOR_DATE": "2026-09-20T10:00:00+00:00"}
    _git(r, "commit", "-q", "--allow-empty", "-m", "base")
    _git(r, "commit", "-q", "--allow-empty", "-m", "landed\n\nClaude-Session: https://claude.ai/code/session_LANDED1", env=old)
    _git(r, "push", "-q", "origin", "main")
    _git(r, "checkout", "-q", "-b", "claude/brave-x")
    for i in range(2):
        _git(r, "commit", "-q", "--allow-empty", "-m", f"cloud {i}\n\nClaude-Session: https://claude.ai/code/session_OPEN22", env=old)
    _git(r, "push", "-q", "origin", "claude/brave-x")
    _git(r, "checkout", "-q", "main")
    _git(r, "branch", "-q", "-D", "claude/brave-x")  # only the remote-tracking ref remains, as after a fetch
    _git(r, "remote", "set-url", "--add", "origin", "https://github.com/acme/app.git")
    # origin_slug reads the first url; point it at GitHub for the PR command, keep pushes local
    cfg = (r / ".git" / "config").read_text().replace(f"url = {bare}\n", "", 1)
    (r / ".git" / "config").write_text(cfg)
    return r


NOW = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)


def test_sessions_found_from_trailers_across_remote_refs(tmp_path):
    r = _session_repo(tmp_path)
    ss = cloud.scan_sessions([r], gh=False, now=NOW)
    by = {s["session"]: s for s in ss}
    assert set(by) == {"session_LANDED1", "session_OPEN22"}
    assert by["session_OPEN22"]["branch"] == "claude/brave-x"
    assert by["session_OPEN22"]["commits"] == 2 and not by["session_OPEN22"]["landed"]
    assert by["session_OPEN22"]["pr"] == "unknown"  # gh not asked
    assert by["session_LANDED1"]["landed"] and by["session_LANDED1"]["pr"] == "landed"
    assert by["session_OPEN22"]["age_hours"] == pytest.approx(9 * 24 + 2, abs=0.1)


def test_local_main_does_not_make_a_session_landed(tmp_path):
    """review of #70, P2: merged into local main but not pushed is not landed on origin/main."""
    r = _session_repo(tmp_path)
    _git(r, "merge", "-q", "--no-ff", "-m", "local merge", "origin/claude/brave-x")
    by = {s["session"]: s for s in cloud.scan_sessions([r], gh=False, now=NOW)}
    assert not by["session_OPEN22"]["landed"] and by["session_OPEN22"]["pr"] == "unknown"
    assert by["session_LANDED1"]["landed"]


def test_days_window_excludes_old_sessions(tmp_path):
    r = _session_repo(tmp_path)
    assert cloud.scan_sessions([r], days=1, gh=False, now=NOW) == []


def test_pr_state_from_gh_and_a19(tmp_path, monkeypatch):
    r = _session_repo(tmp_path)
    calls = []

    def fake_pr(slug, branch):
        calls.append((slug, branch))
        return {"pr": "none", "pr_url": None, "labels": []}
    monkeypatch.setattr(cloud, "pr_for_branch", fake_pr)
    ss = cloud.scan_sessions([r], gh=True, now=NOW)
    assert calls == [("acme/app", "claude/brave-x")]  # landed sessions are not asked about
    F = [f for f in advise_mod.advise({"tokens": {}, "cloud_sessions": ss}) if f["id"] == "A19"]
    assert len(F) == 1
    assert "app claude/brave-x" in F[0]["evidence"]
    assert "gh pr create --repo acme/app --head claude/brave-x --fill" in F[0]["action"]


@pytest.mark.parametrize("pr,age,fires", [("none", 30, True), ("none", 5, False), ("unknown", 300, False), ("open", 300, False)])
def test_a19_needs_a_known_missing_pr_older_than_a_day(pr, age, fires):
    s = {"repo": "app", "slug": "acme/app", "branch": "claude/x", "commits": 1, "landed": False, "pr": pr, "age_hours": age}
    ids = [f["id"] for f in advise_mod.advise({"tokens": {}, "cloud_sessions": [s]})]
    assert ("A19" in ids) is fires


def test_gh_failure_is_unknown_never_none(monkeypatch):
    class R:
        returncode, stdout = 1, ""
    monkeypatch.setattr(cloud.subprocess, "run", lambda *a, **k: R())
    assert cloud.pr_for_branch("acme/app", "claude/x")["pr"] == "unknown"


def test_report_section_and_share_redaction(tmp_path):
    ss = cloud.scan_sessions([_session_repo(tmp_path)], gh=False, now=NOW)
    m = monitor.metrics([], None)
    m["cloud_sessions"] = ss
    md = report.markdown(m, [])
    assert "## Cloud sessions" in md and "claude/brave-x" in md
    red = monitor.redact(m)
    text = json.dumps(red["cloud_sessions"])
    assert "brave-x" not in text and "session_" not in text and "app" not in text
    assert red["cloud_sessions"][0]["repo"] == "r01"


def test_inbox_without_gh_lists_branches_and_says_what_was_not_asked(tmp_path):
    r = _session_repo(tmp_path)
    box = cloud.inbox(days=None, repos=[r], gh=False)
    out = cloud.render_inbox(box)
    assert "claude/brave-x" in out and "PR unknown" in out
    assert "not asked" in out
    assert "session_LANDED1" not in json.dumps(box["no_pr"])


def test_inbox_lists_needs_mac_prs(tmp_path, monkeypatch):
    r = _session_repo(tmp_path)
    monkeypatch.setattr(cloud, "pr_for_branch", lambda slug, b: {"pr": "open", "pr_url": "u", "labels": ["needs-mac"]})
    monkeypatch.setattr(cloud, "needs_mac_prs", lambda slugs: ([{"slug": s, "number": 7, "title": "voice", "url": "https://x/7",
                                                                  "headRefName": "claude/brave-x"} for s in slugs], []))
    box = cloud.inbox(days=None, repos=[r], gh=True)
    assert box["no_pr"] == []  # it has a PR now
    assert "acme/app#7" in cloud.render_inbox(box)


def test_a19_under_share_names_no_branch(tmp_path):
    s = {"repo": "app", "slug": "acme/app", "branch": "claude/x", "session": "session_X", "commits": 1, "landed": False,
         "pr": "none", "age_hours": 30, "first": "2026-09-20", "last": "2026-09-20"}
    m = monitor.redact(dict(monitor.metrics([], None), cloud_sessions=[s]))
    f = next(f for f in advise_mod.advise(m) if f["id"] == "A19")
    text = json.dumps(f)
    assert "claude/x" not in text and "acme" not in text and "teyla cloud inbox" in f["action"]
