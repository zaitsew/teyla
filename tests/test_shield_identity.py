"""teyla shield check --identity: can the active gh identity both push and merge on the repo?

`gh` is a fake script on PATH that answers from files in a temp directory, so nothing here reaches
GitHub and no real token exists. The fake logs every call, which lets a test prove that only read-only
`gh api` GETs ran, and that safe mode ran none."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess

import pytest

from teyla import shield
from teyla.cli import main

FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_DIR/calls.log"
if [ -n "$FAKE_GH_UNAUTH" ]; then
  echo "To get started with GitHub CLI, please run:  gh auth login" >&2
  exit 4
fi
[ "$1" = api ] || exit 2
key=$(printf '%s' "$2" | tr '/?=&' '____')
f="$FAKE_GH_DIR/$key.json"
if [ ! -f "$f" ]; then
  echo '{"message":"Not Found"}'
  echo "gh: Not Found (HTTP 404)" >&2
  exit 1
fi
code=$(cat "$FAKE_GH_DIR/$key.code" 2>/dev/null || echo 200)
cat "$f"
if [ "$code" != 200 ]; then
  echo "gh: request failed (HTTP $code) $FAKE_GH_LEAK" >&2
  exit 1
fi
"""

SLUG = "acme/widget"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.test"}


def fake_token() -> str:
    """Shaped like a GitHub token, built at run time so no scanner sees a literal."""
    return "gh" + "p_" + "A1b2C3d4" * 5


class Gh:
    """The fake gh's answers, one file per endpoint."""

    def __init__(self, tmp_path: pathlib.Path, monkeypatch):
        self.dir = tmp_path / "fakegh"
        self.dir.mkdir()
        binary = self.dir / "gh"
        binary.write_text(FAKE_GH)
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{self.dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_GH_DIR", str(self.dir))
        monkeypatch.delenv("FAKE_GH_UNAUTH", raising=False)
        monkeypatch.delenv("TEYLA_SAFE", raising=False)
        self.answer("user", {"login": "worker-bot"})

    def answer(self, endpoint: str, body, code: int = 200):
        key = endpoint.replace("/", "_").replace("?", "_").replace("=", "_").replace("&", "_")
        (self.dir / f"{key}.json").write_text(json.dumps(body))
        (self.dir / f"{key}.code").write_text(str(code))

    def repo_info(self, *, push: bool, admin: bool = False, private: bool = False, branch: str = "main"):
        self.answer(f"repos/{SLUG}", {"default_branch": branch, "private": private,
                                      "permissions": {"admin": admin, "maintain": False, "push": push, "pull": True}})

    def ruleset(self, rules: list[dict], *, bypass: str = "never", enforcement: str = "active",
                include: list[str] | None = None, rid: int = 7):
        rs = {"id": rid, "name": "publisher-only", "target": "branch", "enforcement": enforcement,
              "conditions": {"ref_name": {"include": include or ["~DEFAULT_BRANCH"], "exclude": []}},
              "rules": rules, "current_user_can_bypass": bypass}
        self.answer(f"repos/{SLUG}/rulesets", [{"id": rid, "name": rs["name"], "target": "branch",
                                                "enforcement": enforcement}])
        self.answer(f"repos/{SLUG}/rulesets/{rid}", rs)

    def calls(self) -> list[str]:
        log = self.dir / "calls.log"
        return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def gh(tmp_path, monkeypatch):
    return Gh(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _scanners(monkeypatch):
    monkeypatch.setattr(shield, "_leak_command", lambda repo: (["true"], None))
    monkeypatch.setattr(shield, "_hosts_command", lambda repo: None)


def git(d: pathlib.Path, *args: str):
    subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV})


def product(tmp_path, *, remote: str | None = f"https://github.com/{SLUG}.git", name="thing") -> pathlib.Path:
    d = tmp_path / name
    d.mkdir()
    git(d, "init", "-q")
    git(d, "commit", "-q", "--allow-empty", "-m", "init")
    (d / "teyla.toml").write_text(f'[product]\nname = "{name}"\n\n[productize]\nusers = "owner"\n\n'
                                  '[security]\ndata = ["account"]\nsecrets = "runtime-env"\n')
    (d / ".gitignore").write_text(".env\n")
    (d / ".githooks").mkdir()
    for h in ("pre-commit", "pre-push"):
        (d / ".githooks" / h).write_text("#!/bin/sh\nexit 0\n")
        (d / ".githooks" / h).chmod(0o755)
    git(d, "config", "core.hooksPath", ".githooks")
    (d / "docs").mkdir()
    (d / "docs" / "PRIVACY.md").write_text("# Hosts\n\n| host | what |\n|---|---|\n| example.test | a call |\n")
    if remote:
        git(d, "remote", "add", "origin", remote)
    return d


def row(rep: dict) -> dict:
    return next(r for r in rep["requirements"] if r["name"] == "credential-separation")


def run_json(d, capsys, *extra) -> tuple[int, dict]:
    rc = main(["shield", "check", str(d), "--identity", "--json", *extra])
    return rc, json.loads(capsys.readouterr().out)


# --- the two verdicts ------------------------------------------------------------------

def test_one_identity_that_can_push_and_merge_is_a_fix(tmp_path, gh, capsys):
    gh.answer("user", {"login": "the-owner"})
    gh.repo_info(push=True, admin=True)
    d = product(tmp_path)
    rc = main(["shield", "check", str(d), "--identity"])
    out = capsys.readouterr().out
    assert rc == 1
    assert ("FIX    credential-separation  the active gh identity (the-owner) can push and merge: "
            "one identity does both; see SHIELD §9.4") in out
    assert "[[security.evidence]]" not in out


def test_a_write_identity_with_no_rule_on_the_default_branch_is_a_fix(tmp_path, gh, capsys):
    gh.repo_info(push=True)                       # rulesets and protection answer 404
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 1 and row(rep)["status"] == "FIX"
    assert "worker-bot" in row(rep)["detail"] and "nothing restricts updates to main" in row(rep)["detail"]
    assert rep["identity"]["evidence"] is None


def test_a_worker_that_cannot_bypass_a_restrict_updates_rule_is_ok_and_prints_the_row(tmp_path, gh, capsys):
    gh.repo_info(push=True)
    gh.ruleset([{"type": "update"}, {"type": "deletion"}])
    d = product(tmp_path)
    rc = main(["shield", "check", str(d), "--identity"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK     credential-separation  worker identity worker-bot: push without merge rights" in out
    assert '[[security.evidence]]\nwhat = "credential-separation"' in out
    head = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert f'commit = "{head}"' in out
    # The printed row is valid evidence: pasted into teyla.toml it records the proof.
    block = out[out.index("[[security.evidence]]"):]
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text() + "\n" + block)
    rep = shield.check(d)
    assert rep["not_enforced"] == []


def test_the_ruleset_must_cover_the_default_branch_and_be_active(tmp_path, gh, capsys):
    gh.repo_info(push=True, branch="trunk")
    gh.ruleset([{"type": "update"}], include=["refs/heads/main"])
    assert run_json(product(tmp_path, name="a"), capsys)[1]["requirements"][-1]["status"] == "FIX"
    gh.ruleset([{"type": "update"}], include=["refs/heads/trunk"], enforcement="evaluate")
    assert run_json(product(tmp_path, name="b"), capsys)[1]["requirements"][-1]["status"] == "FIX"
    gh.ruleset([{"type": "update"}], include=["refs/heads/trunk"])
    assert run_json(product(tmp_path, name="c"), capsys)[1]["requirements"][-1]["status"] == "OK"


def test_a_ruleset_the_identity_can_bypass_does_not_count(tmp_path, gh, capsys):
    gh.repo_info(push=True)
    gh.ruleset([{"type": "update"}], bypass="always")
    assert run_json(product(tmp_path), capsys)[0] == 1


def test_a_pull_request_rule_without_approvals_does_not_stop_a_merge(tmp_path, gh, capsys):
    gh.repo_info(push=True)
    gh.ruleset([{"type": "pull_request", "parameters": {"required_approving_review_count": 0}}])
    assert row(run_json(product(tmp_path, name="a"), capsys)[1])["status"] == "FIX"
    gh.ruleset([{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}])
    assert row(run_json(product(tmp_path, name="b"), capsys)[1])["status"] == "OK"


def test_classic_branch_protection_counts_and_a_404_on_rulesets_is_tolerated(tmp_path, gh, capsys):
    gh.repo_info(push=True)
    gh.answer(f"repos/{SLUG}/branches/main/protection",
              {"required_pull_request_reviews": {"required_approving_review_count": 1}})
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 0 and row(rep)["status"] == "OK" and "branch protection" in row(rep)["detail"]


def test_a_403_on_rulesets_and_protection_is_tolerated_and_a_private_repo_gets_the_fork_hint(tmp_path, gh, capsys):
    gh.repo_info(push=True, private=True)
    gh.answer(f"repos/{SLUG}/rulesets", {"message": "Upgrade to GitHub Pro"}, code=403)
    gh.answer(f"repos/{SLUG}/branches/main/protection", {"message": "Upgrade"}, code=403)
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 1 and row(rep)["status"] == "FIX" and "fork route" in row(rep)["detail"]


def test_a_read_only_identity_is_ok_because_its_pushes_go_to_a_fork(tmp_path, gh, capsys):
    gh.repo_info(push=False)
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 0 and row(rep)["status"] == "OK" and "fork" in row(rep)["detail"]
    assert "has no push right" in rep["identity"]["evidence"]


def test_the_upstream_remote_is_asked_about_before_origin(tmp_path, gh, capsys):
    gh.repo_info(push=False)
    d = product(tmp_path, remote="git@github.com:worker-bot/widget.git")
    git(d, "remote", "add", "upstream", f"https://github.com/{SLUG}")
    rc, rep = run_json(d, capsys)
    assert rep["identity"]["repo"] == SLUG and rc == 0
    assert any(c == f"api repos/{SLUG}" for c in gh.calls())


def test_an_app_installation_token_cannot_read_user_and_is_judged_by_the_repo(tmp_path, gh, capsys):
    gh.answer("user", {"message": "Resource not accessible by integration"}, code=403)
    gh.repo_info(push=True)
    gh.ruleset([{"type": "update"}])
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 0 and "app-installation" in row(rep)["detail"]


# --- the cases that cannot be judged --------------------------------------------------

def test_gh_not_authenticated_is_a_note(tmp_path, gh, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_UNAUTH", "1")
    rc, rep = run_json(product(tmp_path), capsys)
    assert rc == 0 and row(rep)["status"] == "NOTE" and "gh not authenticated" in row(rep)["detail"]


def test_no_gh_on_the_path_is_a_note(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    d = product(tmp_path)
    bindir = tmp_path / "onlygit"
    bindir.mkdir()
    real_git = shutil.which("git")
    (bindir / "git").symlink_to(real_git)
    monkeypatch.setenv("PATH", str(bindir))
    rc, rep = run_json(d, capsys)
    assert row(rep)["status"] == "NOTE" and "not installed" in row(rep)["detail"]   # other rows may differ without a full PATH


def test_a_repo_without_a_github_remote_is_a_note(tmp_path, gh, capsys):
    rc, rep = run_json(product(tmp_path, remote="https://example.test/acme/widget.git"), capsys)
    assert rc == 0 and row(rep)["status"] == "NOTE" and "--github-repo" in row(rep)["detail"]
    assert gh.calls() == []


def test_a_repo_the_identity_cannot_read_is_a_note(tmp_path, gh, capsys):
    rc, rep = run_json(product(tmp_path), capsys)       # repos/acme/widget answers 404
    assert rc == 0 and row(rep)["status"] == "NOTE" and "cannot read" in row(rep)["detail"]


def test_github_repo_overrides_the_remote_and_a_bad_value_is_a_note(tmp_path, gh, capsys):
    gh.repo_info(push=False)
    d = product(tmp_path, remote=None)
    rc, rep = run_json(d, capsys, "--github-repo", SLUG)
    assert rc == 0 and row(rep)["status"] == "OK"
    rc, rep = run_json(d, capsys, "--github-repo", "not a slug")
    assert row(rep)["status"] == "NOTE"


# --- safe mode, the flag's absence, secrets -------------------------------------------

def test_safe_mode_refuses_the_network_part_and_allow_network_opens_it(tmp_path, gh, monkeypatch, capsys):
    gh.repo_info(push=False)
    monkeypatch.setenv("TEYLA_SAFE", "1")
    d = product(tmp_path)
    rc, rep = run_json(d, capsys)
    assert rc == 0 and row(rep)["status"] == "NOTE" and "safe mode" in row(rep)["detail"]
    assert gh.calls() == []
    rc, rep = run_json(d, capsys, "--allow-network")
    assert row(rep)["status"] == "OK" and gh.calls()


def test_without_the_flag_the_check_stays_file_only(tmp_path, gh, capsys):
    gh.repo_info(push=True)
    d = product(tmp_path)
    assert main(["shield", "check", str(d), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert "identity" not in rep and all(r["name"] != "credential-separation" for r in rep["requirements"])
    assert gh.calls() == []


def test_only_read_only_api_gets_run_and_no_token_is_ever_printed(tmp_path, gh, monkeypatch, capsys):
    token = fake_token()
    monkeypatch.setenv("FAKE_GH_LEAK", token)             # gh echoes a token in an error line
    gh.repo_info(push=True)
    gh.answer(f"repos/{SLUG}/rulesets", {"message": "x"}, code=403)
    d = product(tmp_path)
    rc = main(["shield", "check", str(d), "--identity"])
    cap = capsys.readouterr()
    assert token not in cap.out + cap.err
    assert all(c.startswith("api ") and "--method" not in c and "-X" not in c and "-f" not in c.split()
               for c in gh.calls()), gh.calls()
    assert shield._scrub(f"HTTP 401 {token}") == "HTTP 401 ***"
    assert rc == 1


def test_a_token_in_a_gh_error_line_is_scrubbed_from_the_note(tmp_path, gh, monkeypatch, capsys):
    token = fake_token()
    monkeypatch.setenv("FAKE_GH_LEAK", token)
    gh.answer("user", {"message": "boom"}, code=500)
    rc, rep = run_json(product(tmp_path), capsys)
    assert token not in json.dumps(rep) and "***" in row(rep)["detail"]


def test_the_default_check_still_reports_credential_separation_as_a_note_from_evidence(tmp_path, gh, capsys):
    d = product(tmp_path)
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text().replace('users = "owner"', 'users = "public"'))
    rep = shield.check(d)
    assert next(r for r in rep["requirements"] if r["name"] == "credential-separation")["status"] == "NOTE"
    assert gh.calls() == []
