"""teyla.feedback + routines.open_issues — the two write/share paths that must never leak
a path under the home directory, a session id, or correction text, and must never touch
`gh` for a check that isn't BROKEN."""
from __future__ import annotations

from collections import Counter

from teyla.adapters import AgentCall, Session, Turn
from teyla.feedback import QUESTIONS, build
from teyla.monitor import metrics
from teyla.routines import open_issues


def _session(sid, cwd="/Users/me/repos/demo-project"):
    s = Session(harness="claude-code", project="demo-project", sid=sid, path=f"/tmp/{sid}.jsonl", size=1000)
    s.first = "2026-01-01T00:00:00Z"
    s.last = "2026-01-01T01:00:00Z"
    s.cwd = cwd
    s.models["claude-sonnet-5"] = 3
    s.usage["claude-sonnet-5"] = Counter(input_tokens=1000, output_tokens=500,
                                          cache_read_input_tokens=100, cache_creation_input_tokens=0)
    s.tools["Bash"] = 2
    s.user_turns = [
        Turn("2026-01-01T00:00:00Z", "do the thing", False),
        Turn("2026-01-01T00:30:00Z", "no, not like that, use pnpm instead of npm", True),
    ]
    s.agents.append(AgentCall(None, "general-purpose", "read some files"))
    return s


def _fake_metrics():
    # One giant session so giant_sessions carries a project + sid that redact() must strip,
    # and one correction-shaped turn so correction_samples must not survive either.
    sessions = [_session(f"sidzz{i}") for i in range(3)]
    sessions[0].size = 9_000_000  # over GIANT_BYTES -> lands in giant_sessions
    return metrics(sessions)


def test_build_contains_no_home_paths():
    m = _fake_metrics()
    out = build(m, days=30, policy_status={"policy-file": True, "claude-code": True},
                doctor_lines=["claude-code   ~/.claude/projects   found   sessions: 3"])
    assert "/Users/" not in out
    assert "alice" not in out


def test_build_contains_no_session_ids():
    m = _fake_metrics()
    out = build(m, days=30, policy_status={}, doctor_lines=[])
    for i in range(3):
        assert f"sidzz{i}" not in out


def test_build_contains_no_correction_text():
    m = _fake_metrics()
    out = build(m, days=30, policy_status={}, doctor_lines=[])
    assert "pnpm" not in out
    assert "not like that" not in out


def test_build_has_the_fixed_questionnaire_and_footer():
    m = _fake_metrics()
    out = build(m, days=30, policy_status={}, doctor_lines=[])
    for q in QUESTIONS:
        assert q in out
    assert "https://github.com/zaitsew/teyla/issues/new?template=feedback.md" in out
    assert "Teyla version" in out


def test_build_reports_redacted_project_alias_not_raw_name():
    m = _fake_metrics()
    out = build(m, days=30, policy_status={}, doctor_lines=[])
    assert "demo-project" not in out
    assert "p01" in out


# --- routines.open_issues ---------------------------------------------------------------

def _report(product="my-app", repo="/Users/me/repos/my-app", checks=None):
    return {"product": product, "repo": repo, "routines": [], "checks": checks or []}


def test_open_issues_skips_non_broken_without_calling_gh(monkeypatch):
    calls = []
    monkeypatch.setattr("teyla.routines.subprocess.run", lambda *a, **k: calls.append(a))
    report = _report(checks=[
        {"name": "photo entry logging", "status": "ok", "confirmed": "-", "age_days": "-", "verdict": "ok"},
        {"name": "sync check", "status": "untested", "confirmed": "-", "age_days": "-", "verdict": "UNTESTED"},
    ])
    lines = open_issues([report])
    assert lines == []
    assert calls == []


def test_open_issues_formats_titles_for_broken_checks(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    (repo / "teyla.toml").write_text(
        '[product]\nname = "my-app"\n\n[[check]]\nname = "photo entry logging"\nhow = "app -> New -> photo"\n'
        'status = "broken"\nnote = "camera permission regressed"\n'
    )

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=None):
        class R:
            pass
        r = R()
        if cmd[:3] == ["gh", "repo", "view"]:
            r.returncode = 0; r.stdout = ""; r.stderr = ""
        elif cmd[:3] == ["gh", "issue", "list"]:
            r.returncode = 0; r.stdout = "[]"; r.stderr = ""
        elif cmd[:3] == ["gh", "issue", "create"]:
            r.returncode = 0; r.stdout = "https://github.com/alice/my-app/issues/1"; r.stderr = ""
        else:
            raise AssertionError(f"unexpected gh call: {cmd}")
        return r

    monkeypatch.setattr("teyla.routines.shutil.which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr("teyla.routines.subprocess.run", fake_run)

    report = _report(repo=str(repo), checks=[
        {"name": "photo entry logging", "status": "broken", "confirmed": "-", "age_days": "-", "verdict": "BROKEN"},
    ])
    lines = open_issues([report])
    assert len(lines) == 1
    assert "[teyla] broken check: photo entry logging" not in lines[0]  # title goes in the gh call, not necessarily the log line
    assert "photo entry logging" in lines[0]
    assert "created" in lines[0]


def test_open_issues_never_duplicates_when_issue_already_exists(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    (repo / "teyla.toml").write_text(
        '[product]\nname = "my-app"\n\n[[check]]\nname = "photo entry logging"\nhow = "x"\nstatus = "broken"\n'
    )

    created = []

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=None):
        class R:
            pass
        r = R()
        if cmd[:3] == ["gh", "repo", "view"]:
            r.returncode = 0; r.stdout = ""; r.stderr = ""
        elif cmd[:3] == ["gh", "issue", "list"]:
            r.returncode = 0; r.stdout = '[{"title": "[teyla] broken check: photo entry logging"}]'; r.stderr = ""
        elif cmd[:3] == ["gh", "issue", "create"]:
            created.append(cmd)
            r.returncode = 0; r.stdout = ""; r.stderr = ""
        else:
            raise AssertionError(f"unexpected gh call: {cmd}")
        return r

    monkeypatch.setattr("teyla.routines.shutil.which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr("teyla.routines.subprocess.run", fake_run)

    report = _report(repo=str(repo), checks=[
        {"name": "photo entry logging", "status": "broken", "confirmed": "-", "age_days": "-", "verdict": "BROKEN"},
    ])
    lines = open_issues([report])
    assert created == []
    assert "already exists" in lines[0]


# --- doctor detail in the feedback file ----------------------------------------------------

def test_shareable_check_withholds_machine_detail(monkeypatch, tmp_path):
    from teyla.feedback import shareable_check
    monkeypatch.setenv("HOME", str(tmp_path))
    c = lambda name, detail: {"level": "OK", "name": name, "detail": detail, "fix": "x"}
    assert shareable_check(c("network", "no proxy; trust: truststore")) == ("OK", "network", "(withheld)")
    assert shareable_check(c("config", "code_root=~/work")) == ("OK", "config", "(withheld)")
    assert shareable_check(c("remind:renew the acme cert", "due soon")) == ("OK", "remind", "(withheld)")
    assert shareable_check(c("platform:1password", "ok"))[2] == "(withheld)"
    assert shareable_check(c("repos:agents-md", "acme-billing differs"))[2] == "(withheld)"
    # whatever the family, a URL, an '@' or a home path is withheld
    assert shareable_check(c("version", "see https://proxy.acme"))[2] == "(withheld)"
    assert shareable_check(c("plugin", "user:pw@proxy:8080"))[2] == "(withheld)"
    assert shareable_check(c("control:hmac", f"{tmp_path}/.teyla/hmac.key mode 0o644"))[2] == "(withheld)"
    # what is about Teyla itself stays
    assert shareable_check(c("plugin", "teyla@0.11.0 in Claude Code"))[2] == "(withheld)"  # '@' is '@'
    assert shareable_check(c("policy:codex", "wired")) == ("OK", "policy:codex", "wired")
    assert shareable_check(c("routine:daily", "loaded, last started 2026-09-28 09:00"))[2].startswith("loaded")
