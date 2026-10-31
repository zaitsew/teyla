"""A repo recorded as private (`git config teyla.visibility private`): terms and e-mails are triage, everything else
still blocks; an unset or garbled value means public. `teyla leak install` records the value from `gh`, and
`teyla shield check` reports the leak row as OK with a triage count. Every term, key and name here is invented."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from teyla import cli, leak, leak_install as li, net, shield

AT = "@"
EMAIL = "family" + AT + "mailbox.test"
KEY = "sk-ant-" + "A1" * 12


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for k, v in {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test Author",
                 "GIT_AUTHOR_EMAIL": "author" + AT + "example.com", "GIT_COMMITTER_NAME": "Test Author",
                 "GIT_COMMITTER_EMAIL": "author" + AT + "example.com", "XDG_CONFIG_HOME": "/nonexistent"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(leak, "_which", lambda name: None)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    terms = tmp_path / "terms.txt"
    terms.write_text("zebracorn\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    (r / "notes.txt").write_text(f"contact {EMAIL}\nthe zebracorn project\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "notes")
    monkeypatch.chdir(r)
    return r


def scan(capsys, *args):
    code = leak.main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def sev(doc):
    return {(f["rule"], f["severity"]) for f in doc["findings"]}


# --- the scanner -----------------------------------------------------------------------------

def test_unset_is_public_and_blocks_with_no_visibility_note(repo, capsys):
    code, doc = scan(capsys)
    assert code == 1 and sev(doc) == {("term", "blocker"), ("email", "blocker")}
    assert not any("visibility" in n for n in doc["coverage"]["notes"])


def test_private_makes_terms_and_emails_triage(repo, capsys):
    git(repo, "config", "teyla.visibility", "private")
    code, doc = scan(capsys)
    assert code == 0 and sev(doc) == {("term", "triage"), ("email", "triage")}
    assert leak.PRIVATE_NOTE in doc["coverage"]["notes"]


def test_public_value_blocks_and_says_so(repo, capsys):
    git(repo, "config", "teyla.visibility", "public")
    code, doc = scan(capsys)
    assert code == 1 and ("term", "blocker") in sev(doc)
    assert any(n.startswith("visibility: public") for n in doc["coverage"]["notes"])


@pytest.mark.parametrize("value", ["Private", "PRIVATE", "internal", "yes", "true", "private-ish"])
def test_any_other_value_is_public(repo, capsys, value):
    git(repo, "config", "teyla.visibility", value)
    code, doc = scan(capsys)
    assert code == 1 and ("term", "blocker") in sev(doc)
    assert not any("visibility" in n for n in doc["coverage"]["notes"])


def test_private_still_blocks_secrets_and_home_paths(repo, capsys):
    git(repo, "config", "teyla.visibility", "private")
    home = "/Users/" + "jdoe" + "/notes"
    (repo / "keys.txt").write_text(f"{KEY}\nsee {home}\n")
    git(repo, "add", "-A")
    code, doc = scan(capsys)
    assert code == 1
    s = sev(doc)
    assert ("secret", "blocker") in s and ("home", "blocker") in s and ("term", "triage") in s


def test_private_staged_and_outgoing_surfaces_follow_the_same_rule(repo, capsys):
    git(repo, "config", "teyla.visibility", "private")
    (repo / "more.txt").write_text(f"mail {EMAIL}\n")
    git(repo, "add", "more.txt")
    code, doc = scan(capsys, "--staged")
    assert code == 0 and ("email", "triage") in sev(doc)
    git(repo, "commit", "-q", "-m", f"notify {EMAIL}")
    code, doc = scan(capsys, "--commits", "HEAD~1..HEAD")
    assert code == 0 and ("email", "triage") in sev(doc)


def test_text_is_public_whatever_the_repo_is(repo, capsys, tmp_path):
    git(repo, "config", "teyla.visibility", "private")
    body = tmp_path / "body.md"
    body.write_text(f"ask {EMAIL} about zebracorn\n")
    code, doc = scan(capsys, "--text", str(body))
    assert code == 1 and sev(doc) == {("term", "blocker"), ("email", "blocker")}
    assert not any("visibility" in n for n in doc["coverage"]["notes"])
    assert {f.severity for f in leak.scan_text(body.read_text())} == {"blocker"}


def test_all_reads_each_repos_own_visibility(repo, tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    (other / "n.txt").write_text(f"{EMAIL}\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "n")
    git(repo, "config", "teyla.visibility", "private")
    from teyla import config
    monkeypatch.setattr(config, "code_root", lambda: tmp_path)
    code, doc = scan(capsys, "--all")
    by_repo = {(f["repo"], f["rule"]): f["severity"] for f in doc["findings"]}
    assert by_repo[("repo", "email")] == "triage" and by_repo[("other", "email")] == "blocker"
    assert code == 1


# --- install ---------------------------------------------------------------------------------

def fake_gh(tmp_path, monkeypatch, body: str) -> Path:
    b = tmp_path / "fakebin"
    b.mkdir(exist_ok=True)
    gh = b / "gh"
    gh.write_text("#!/bin/sh\n" + body)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    return gh


def with_remote(repo):
    git(repo, "remote", "add", "origin", "https://github.com/acme/widget.git")


def run_install(repo, capsys):
    code = cli.main(["leak", "install", str(repo)])
    return code, capsys.readouterr().out


def test_install_records_private_from_gh(repo, tmp_path, monkeypatch, capsys):
    with_remote(repo)
    log = tmp_path / "gh.log"
    fake_gh(tmp_path, monkeypatch, f'echo "$@" >> {log}\necho PRIVATE\n')
    code, out = run_install(repo, capsys)
    assert code == 0 and "visibility: private" in out
    assert git(repo, "config", "--get", "teyla.visibility") == "private"
    assert "repo view acme/widget --json visibility -q .visibility" in log.read_text()


def test_install_records_public_and_updates_a_later_flip(repo, tmp_path, monkeypatch, capsys):
    with_remote(repo)
    git(repo, "config", "teyla.visibility", "private")
    fake_gh(tmp_path, monkeypatch, "echo PUBLIC\n")
    run_install(repo, capsys)
    assert git(repo, "config", "--get", "teyla.visibility") == "public"


@pytest.mark.parametrize("body", ["exit 1\n", "echo INTERNAL\n", "echo\n", "echo 'rm -rf /'\n"])
def test_install_stores_nothing_when_gh_fails_or_answers_oddly(repo, tmp_path, monkeypatch, capsys, body):
    with_remote(repo)
    fake_gh(tmp_path, monkeypatch, body)
    code, out = run_install(repo, capsys)
    assert code == 0 and "not recorded" in out and "treated as public" in out
    assert "git config teyla.visibility private" in out
    p = subprocess.run(["git", "config", "--get", "teyla.visibility"], cwd=repo, capture_output=True, text=True)
    assert p.returncode != 0


def test_install_without_gh_leaves_it_unset(repo, tmp_path, monkeypatch, capsys):
    with_remote(repo)
    only_git = tmp_path / "onlygit"                               # a PATH that has git and no gh
    only_git.mkdir()
    (only_git / "git").symlink_to(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    monkeypatch.setenv("PATH", str(only_git))
    code, out = run_install(repo, capsys)
    assert code == 0 and "not recorded" in out and "gh is not installed" in out


def test_install_without_a_remote_leaves_it_unset_and_never_calls_gh(repo, tmp_path, monkeypatch, capsys):
    called = tmp_path / "called"
    fake_gh(tmp_path, monkeypatch, f"touch {called}\necho PRIVATE\n")
    code, out = run_install(repo, capsys)
    assert code == 0 and "no GitHub remote" in out and not called.exists()


def test_install_asks_the_network_gate_and_obeys_a_refusal(repo, tmp_path, monkeypatch, capsys):
    with_remote(repo)
    called = tmp_path / "called"
    fake_gh(tmp_path, monkeypatch, f"touch {called}\necho PRIVATE\n")
    asked = []
    monkeypatch.setattr(net, "gate", lambda what, cfg=None, *, quiet=False: asked.append((what, quiet)) or False)
    code, out = run_install(repo, capsys)
    assert asked == [("the repo visibility lookup (gh repo view)", True)]
    assert code == 0 and "safe mode is on" in out and not called.exists()


def test_a_failed_lookup_keeps_a_value_set_by_hand(repo, tmp_path, monkeypatch, capsys):
    with_remote(repo)
    git(repo, "config", "teyla.visibility", "private")
    fake_gh(tmp_path, monkeypatch, "exit 1\n")
    code, out = run_install(repo, capsys)
    assert "visibility: private kept" in out
    assert git(repo, "config", "--get", "teyla.visibility") == "private"


# --- shield ----------------------------------------------------------------------------------

def shield_repo(tmp_path):
    d = tmp_path / "prod"
    d.mkdir()
    git(d, "init", "-q")
    return d


def fake_scanner(findings: list[dict], exit_code: int):
    doc = json.dumps({"findings": findings, "coverage": {}, "errors": [], "exit": exit_code})
    return [sys.executable, "-c", f"import sys; print({doc!r}); sys.exit({exit_code})", "--quiet"]


def leak_row(tmp_path, monkeypatch, findings, exit_code, visibility="private"):
    d = shield_repo(tmp_path)
    if visibility:
        git(d, "config", "teyla.visibility", visibility)
    monkeypatch.setattr(shield, "_leak_command", lambda r: (fake_scanner(findings, exit_code), None))
    c = type("C", (), {"repo": d})()
    return shield.check_leak(c)


F_TRIAGE = {"rule": "term", "severity": "triage"}
F_BLOCK = {"rule": "secret", "severity": "blocker"}


def test_shield_private_repo_with_triage_only_is_ok(tmp_path, monkeypatch):
    status, text = leak_row(tmp_path, monkeypatch, [F_TRIAGE, F_TRIAGE, {"rule": "email", "severity": "triage"}], 0)
    assert status == "OK" and text == "3 triage (private repo: terms and e-mails listed, not blocking)"


def test_shield_private_repo_with_a_blocker_is_fix(tmp_path, monkeypatch):
    status, text = leak_row(tmp_path, monkeypatch, [F_BLOCK, F_TRIAGE], 1)
    assert status == "FIX" and "found 1" in text


def test_shield_private_repo_without_findings_is_plain_ok(tmp_path, monkeypatch):
    assert leak_row(tmp_path, monkeypatch, [], 0) == ("OK", "no findings")


def test_shield_private_repo_whose_scanner_failed_is_fix(tmp_path, monkeypatch):
    status, text = leak_row(tmp_path, monkeypatch, [], 2)
    assert status == "FIX" and "exit 2" in text


@pytest.mark.parametrize("visibility", [None, "public", "garbage"])
def test_shield_unrecorded_or_public_repo_keeps_the_old_row(tmp_path, monkeypatch, visibility):
    d = shield_repo(tmp_path)
    if visibility:
        git(d, "config", "teyla.visibility", visibility)
    monkeypatch.setattr(shield, "_leak_command", lambda r: (["sh", "-c", "echo 4; exit 1", "x", "--quiet"], None))
    status, text = shield.check_leak(type("C", (), {"repo": d})())
    assert status == "FIX" and "found 4" in text


def test_a_global_visibility_value_does_not_count(tmp_path, monkeypatch):
    """Only the repo's own (local) config records its visibility: a global `teyla.visibility private` would
    downgrade every repo that has no local value."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text("[teyla]\n\tvisibility = private\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gcfg))
    assert leak.repo_visibility(repo) is None
    subprocess.run(["git", "-C", str(repo), "config", "teyla.visibility", "private"], check=True)
    assert leak.repo_visibility(repo) == "private"
