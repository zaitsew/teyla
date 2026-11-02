"""`teyla products` reads the probe merged on the default branch, not the one on the checkout's branch."""
import subprocess

from teyla import products

PROBE = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
case "${1:-}" in
  usage)
    echo "where=%s"
    echo "secret_seen=$(cut -d= -f2 .env)"
    exit 0 ;;
esac
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True)


def make_repo(tmp_path):
    """A repo whose origin/main has the new probe while the checkout's branch keeps the old one."""
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".env").write_text("KEY=local\n")
    (repo / ".gitignore").write_text(".env\n")
    (repo / "check.sh").write_text(PROBE % "old")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "checkout", "-q", "main")
    (repo / "check.sh").write_text(PROBE % "merged")
    git(repo, "commit", "-qam", "two")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", "feature")
    return repo


def test_the_merged_probe_runs_on_a_feature_branch_and_sees_the_local_env(tmp_path):
    repo = make_repo(tmp_path)
    out = products.probe(repo, committed=True)
    assert out["_status"] == "ok"
    assert out["where"] == "merged"
    assert out["secret_seen"] == "local"


def test_the_checkout_is_left_alone(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / "check.sh").read_text()
    products.probe(repo, committed=True)
    assert (repo / "check.sh").read_text() == before
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_without_committed_the_checkout_runs(tmp_path):
    assert products.probe(make_repo(tmp_path))["where"] == "old"


def test_a_repo_without_a_default_branch_ref_runs_the_checkout(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert products.probe(repo, committed=True)["where"] == "old"


def test_a_stale_origin_main_is_ignored_when_origin_head_names_another_branch(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-q", "--orphan", "develop")
    git(repo, "rm", "-rfq", "--cached", ".")
    (repo / "check.sh").unlink()
    git(repo, "commit", "-q", "--allow-empty", "-m", "develop has no check.sh")
    git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    git(repo, "checkout", "-qf", "feature")
    assert products.probe(repo, committed=True)["where"] == "old"


def test_a_default_branch_without_a_probe_keeps_the_checkout_probe(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    (repo / "check.sh").write_text("#!/usr/bin/env bash\necho no modes here\n")
    git(repo, "commit", "-qam", "drop")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", "feature")
    assert products.probe(repo, committed=True)["where"] == "old"


def test_a_branch_without_check_sh_still_reports_the_merged_probe(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "check.sh").unlink()
    assert products.probe(repo, committed=True)["where"] == "merged"
    assert products.probe(repo) == {"_status": "no check.sh"}


def test_the_walk_uses_main_but_a_named_repo_and_safe_mode_use_the_checkout(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(products, "write_cache", lambda results: None)
    cfg = {"code_root": str(tmp_path)}
    monkeypatch.setattr("teyla.config.safe_mode", lambda c=None: False)
    monkeypatch.setattr("teyla.config.products_allowlist", lambda c=None: {repo.resolve()})
    monkeypatch.setattr("teyla.config.code_root", lambda c=None: tmp_path)
    assert "where=merged" in products.table(cfg=cfg)
    assert "where=old" in products.table([str(repo)], cfg=cfg)
    monkeypatch.setattr("teyla.config.safe_mode", lambda c=None: True)
    assert "where=old" in products.table(cfg=cfg)
