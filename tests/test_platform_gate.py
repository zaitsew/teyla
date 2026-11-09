"""`teyla platform check`: the §14 gate, in temp git repos with a generic teyla.toml. Every name is invented."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from teyla import cli, leak_install as li, platform_gate as pg

AT = "@"
BASE = """[productize]
primary = "ios"
platforms = ["ios", "macos", "android"]
{triggers}
[productize.paths]
ios = ["apps/ios/**"]
macos = ["apps/macos/**", "App/Mac/**"]
android = ["android/**"]
"""

pytestmark = pytest.mark.skipif(not os.path.exists("/usr/bin/git"), reason="needs /usr/bin/git")


class Repo:
    def __init__(self, tmp: Path, monkeypatch):
        self.dir = tmp / "repo"
        self.dir.mkdir()
        self.home = tmp / "teyla-home"
        self.env = {
            "TEYLA_HOME": str(self.home), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author" + AT + "example.com",
            "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author" + AT + "example.com",
        }
        for k, v in self.env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("TEYLA_PLATFORM_LABEL", raising=False)
        self.git("init", "-q", "-b", "main")
        self.toml()
        self.commit("base", {"README.md": "x\n"}, add_toml=True)
        self.base = self.rev()

    def git(self, *a):
        p = subprocess.run(["git", "-C", str(self.dir), *a], capture_output=True, text=True, env={**os.environ})
        assert p.returncode == 0, p.stderr
        return p.stdout.strip()

    def rev(self):
        return self.git("rev-parse", "HEAD")

    def toml(self, triggers=""):
        (self.dir / "teyla.toml").write_text(BASE.format(triggers=triggers))

    def commit(self, msg, files, add_toml=False):
        for name, text in files.items():
            p = self.dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def check(self, capsys, *extra):
        code = cli.main(["platform", "check", "--repo", str(self.dir), *extra])
        out = capsys.readouterr()
        return code, out.out + out.err


@pytest.fixture
def repo(tmp_path, monkeypatch):
    return Repo(tmp_path, monkeypatch)


def rng(repo):
    return f"{repo.base}..{repo.rev()}"


def test_non_primary_change_without_trigger_fails_and_names_the_platform(repo, capsys):
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1
    assert "macos: no trigger" in out
    assert "apps/macos/App.swift" in out
    assert 'macos = "YYYY-MM-DD: <who asked, why>"' in out
    assert "--label" in out


def test_a_dated_trigger_passes(repo, capsys):
    repo.toml('[productize.triggers]\nmacos = "2026-10-06: the owner asked for it"\n')
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 0, out


def test_an_undated_trigger_fails(repo, capsys):
    repo.toml('[productize.triggers]\nmacos = "the owner asked for it"\n')
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1
    assert "trigger has no date" in out


def test_an_impossible_date_and_a_missing_reason_fail(repo, capsys):
    repo.toml('[productize.triggers]\nmacos = "2026-13-45: nonsense"\nandroid = "2026-10-06"\n')
    repo.commit("both", {"apps/macos/A.swift": "a\n", "android/A.kt": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1
    assert "macos: trigger has no date" in out
    assert "android: trigger has no reason" in out


def test_a_primary_only_change_passes(repo, capsys):
    repo.commit("ios", {"apps/ios/A.swift": "a\n"})
    code, _ = repo.check(capsys, "--range", rng(repo))
    assert code == 0


def test_a_shared_file_never_fails(repo, capsys):
    repo.commit("shared", {"packages/core/a.py": "a\n", "docs/x.md": "x\n"})
    code, _ = repo.check(capsys, "--range", rng(repo))
    assert code == 0


def test_more_than_ten_files_are_cut_with_a_count(repo, capsys):
    repo.commit("many", {f"android/f{i}.kt": "a\n" for i in range(13)})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1
    assert "+3 more" in out


def test_glob_semantics():
    assert pg.glob_re("apps/ios/**").match("apps/ios/a/b.swift")
    assert pg.glob_re("**/Mac/*.swift").match("App/Mac/a.swift")
    assert pg.glob_re("**/Mac/*.swift").match("Mac/a.swift")
    assert not pg.glob_re("**/Mac/*.swift").match("Mac/sub/a.swift")
    assert pg.glob_re("a?.txt").match("ab.txt") and not pg.glob_re("a?.txt").match("a/.txt")
    assert pg.glob_re("*.kt").match("x.kt") and not pg.glob_re("*.kt").match("d/x.kt")


def test_label_security_passes_and_logs_a_row(repo, capsys):
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo), "--label", "security")
    assert code == 0, out
    rows = (repo.home / "platform-gate.tsv").read_text().splitlines()
    assert len(rows) == 1
    ts, name, label, plats, used = rows[0].split("\t")
    assert (name, label, plats, used) == ("repo", "security", "macos", rng(repo))
    assert ts.endswith("Z")


def test_the_label_from_the_environment_works(repo, capsys, monkeypatch):
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    monkeypatch.setenv("TEYLA_PLATFORM_LABEL", "data-loss")
    code, _ = repo.check(capsys, "--range", rng(repo))
    assert code == 0
    assert "\tdata-loss\t" in (repo.home / "platform-gate.tsv").read_text()


def test_an_unknown_label_is_refused_with_the_valid_ones(repo, capsys):
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo), "--label", "nope")
    assert code == 1
    assert "security" in out and "data-loss" in out and "backend-break" in out
    assert not (repo.home / "platform-gate.tsv").exists()


def test_an_unwritable_log_refuses_the_exception(repo, capsys, monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("TEYLA_HOME", str(blocker))
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo), "--label", "security")
    assert code == 1
    assert "not on record" in out


def test_no_path_map_passes_with_one_line(repo, capsys):
    (repo.dir / "teyla.toml").write_text('[productize]\nprimary = "ios"\nplatforms = ["ios", "macos"]\n')
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 0
    assert out.strip() == "platform gate: no path map in teyla.toml, nothing checked"


def test_no_teyla_toml_and_a_single_platform_pass(repo, capsys):
    repo.git("rm", "-q", "teyla.toml")
    repo.git("commit", "-q", "-m", "drop")
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 0 and "nothing checked" in out
    repo.commit("one", {"teyla.toml": '[productize]\nplatforms = ["ios"]\n[productize.paths]\nios = ["a/**"]\n'})
    code, _ = repo.check(capsys)
    assert code == 0


def test_json_output(repo, capsys):
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo), "--json")
    data = json.loads(out)
    assert code == 1 and data["ok"] is False
    assert data["violations"][0]["platform"] == "macos"


def test_default_range_is_merge_base_with_main(repo, capsys):
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    code, out = repo.check(capsys)
    assert code == 1 and "macos" in out


def _stdin(monkeypatch, text):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_pre_push_new_branch(repo, capsys, monkeypatch):
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    zeros = "0" * 40
    _stdin(monkeypatch, f"refs/heads/feature {repo.rev()} refs/heads/feature {zeros}\n")
    code, out = repo.check(capsys, "--pre-push")
    assert code == 1 and "macos" in out


def test_pre_push_new_branch_ignores_commits_a_remote_already_has(repo, capsys, monkeypatch):
    repo.commit("mac", {"apps/macos/Old.swift": "a\n"})
    repo.git("update-ref", "refs/remotes/origin/main", repo.rev())
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("ios", {"apps/ios/New.swift": "a\n"})
    zeros = "0" * 40
    _stdin(monkeypatch, f"refs/heads/feature {repo.rev()} refs/heads/feature {zeros}\n")
    code, out = repo.check(capsys, "--pre-push", "--remote", "origin")
    assert code == 0, out


def test_pre_push_update_checks_only_the_new_commits(repo, capsys, monkeypatch):
    repo.commit("mac", {"apps/macos/Old.swift": "a\n"})
    old = repo.rev()
    repo.commit("ios", {"apps/ios/New.swift": "a\n"})
    _stdin(monkeypatch, f"refs/heads/main {repo.rev()} refs/heads/main {old}\n")
    code, out = repo.check(capsys, "--pre-push")
    assert code == 0, out
    repo.commit("android", {"android/A.kt": "a\n"})
    _stdin(monkeypatch, f"refs/heads/main {repo.rev()} refs/heads/main {old}\n")
    code, out = repo.check(capsys, "--pre-push")
    assert code == 1 and "android" in out and "macos" not in out


def test_pre_push_deletion_is_skipped(repo, capsys, monkeypatch):
    zeros = "0" * 40
    _stdin(monkeypatch, f"(delete) {zeros} refs/heads/old {repo.rev()}\n")
    code, _ = repo.check(capsys, "--pre-push")
    assert code == 0


# --- review round: quoted paths, renames, the committed manifest -----------------------------------

def test_a_non_ascii_path_under_a_secondary_platform_is_caught(repo, capsys):
    repo.commit("mac", {"apps/macos/\u00e9.swift": "a\n"})
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1
    assert "macos: no trigger" in out and "\u00e9.swift" in out


def test_a_non_ascii_path_in_pre_push_is_caught(repo, capsys, monkeypatch):
    repo.commit("mac", {"apps/macos/\u00e9.swift": "a\n"})
    _stdin(monkeypatch, f"refs/heads/main {repo.rev()} refs/heads/main {repo.base}\n")
    code, out = repo.check(capsys, "--pre-push")
    assert code == 1 and "macos" in out


def test_moving_a_file_out_of_a_secondary_path_counts_the_source(repo, capsys):
    repo.toml('[productize.triggers]\nmacos = "2026-10-06: the owner asked for it"\n')
    repo.commit("mac", {"apps/macos/App.swift": "same content\n" * 20, "teyla.toml": (repo.dir / "teyla.toml").read_text()})
    base = repo.rev()
    repo.toml()                                        # trigger removed in the same push
    (repo.dir / "shared").mkdir()
    repo.git("mv", "apps/macos/App.swift", "shared/App.swift")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "move")
    code, out = repo.check(capsys, "--range", f"{base}..{repo.rev()}")
    assert code == 1
    assert "apps/macos/App.swift" in out


def test_an_uncommitted_trigger_does_not_pass_a_push(repo, capsys, monkeypatch):
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    repo.toml('[productize.triggers]\nmacos = "2026-10-06: the owner asked for it"\n')   # working tree only
    code, out = repo.check(capsys, "--range", rng(repo))
    assert code == 1 and "macos: no trigger" in out
    code, _ = repo.check(capsys)
    assert code == 1
    _stdin(monkeypatch, f"refs/heads/main {repo.rev()} refs/heads/main {repo.base}\n")
    code, _ = repo.check(capsys, "--pre-push")
    assert code == 1


def test_a_trigger_committed_in_the_pushed_revision_passes(repo, capsys, monkeypatch):
    repo.toml('[productize.triggers]\nmacos = "2026-10-06: the owner asked for it"\n')
    repo.commit("mac", {"apps/macos/App.swift": "a\n"})
    _stdin(monkeypatch, f"refs/heads/main {repo.rev()} refs/heads/main {repo.base}\n")
    code, out = repo.check(capsys, "--pre-push")
    assert code == 0, out


# --- the hook ---------------------------------------------------------------------------------------

def test_the_pre_push_block_has_the_platform_step_and_the_pre_commit_block_does_not():
    push = li.block("pre-push")
    assert 'teyla platform check --pre-push --remote "$_tlg_remote" < "$_tlg_in"' in push
    assert "TEYLA_PLATFORM" in push and "platform-gate.tsv" in push
    assert "platform check" not in li.block("pre-commit")


def test_the_standalone_hook_is_valid_sh():
    p = subprocess.run(["/bin/sh", "-n"], input=li.standalone("pre-push"), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def _hook_run(tmp_path, hook_text, refs, env_extra, shim):
    hook = tmp_path / "pre-push"
    hook.write_text(hook_text)
    hook.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "teyla").write_text(shim)
    (bin_dir / "teyla").chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin", "TEYLA_HOME": str(tmp_path / "th"),
           "TEYLA_LEAK": "0", **env_extra}
    git = subprocess.run(["git", "init", "-q", str(tmp_path / "r")], capture_output=True)
    assert git.returncode == 0
    return subprocess.run(["/bin/sh", str(hook), "origin"], cwd=tmp_path / "r", input=refs, capture_output=True,
                          text=True, env=env)


SHIM_NEW = '#!/bin/sh\nif [ "$2" = "--help" ]; then echo "check: x"; exit 0; fi\ncat >/dev/null\nexit "${GATE_EXIT:-0}"\n'
SHIM_OLD = '#!/bin/sh\nif [ "$2" = "--help" ]; then echo "init: x"; exit 0; fi\nexit 9\n'


def test_the_hook_folds_the_platform_exit_code_in(tmp_path):
    p = _hook_run(tmp_path, li.standalone("pre-push"), "refs/heads/a 1 refs/heads/a 0\n", {"GATE_EXIT": "1"}, SHIM_NEW)
    assert p.returncode == 1
    assert "platform gate: pre-push refused" in p.stderr


def test_the_hook_passes_silently_on_an_older_teyla_without_check(tmp_path):
    p = _hook_run(tmp_path, li.standalone("pre-push"), "refs/heads/a 1 refs/heads/a 0\n", {}, SHIM_OLD)
    assert p.returncode == 0 and p.stderr == ""


def test_teyla_platform_0_skips_and_is_logged(tmp_path):
    p = _hook_run(tmp_path, li.standalone("pre-push"), "refs/heads/a 1 refs/heads/a 0\n",
                  {"TEYLA_PLATFORM": "0", "GATE_EXIT": "1"}, SHIM_NEW)
    assert p.returncode == 0, p.stderr
    row = (tmp_path / "th" / "platform-gate.tsv").read_text().strip().split("\t")
    assert row[2] == "TEYLA_PLATFORM=0" and row[4] == "pre-push"


def test_a_skip_that_cannot_be_logged_is_refused(tmp_path):
    (tmp_path / "th").write_text("x")
    p = _hook_run(tmp_path, li.standalone("pre-push"), "refs/heads/a 1 refs/heads/a 0\n",
                  {"TEYLA_PLATFORM": "0"}, SHIM_NEW)
    assert p.returncode == 1 and "not on record" in p.stderr


def test_rerunning_install_updates_an_installed_block_in_place(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    hooks = repo / ".githooks"
    hooks.mkdir()
    old = li.standalone("pre-push")
    start = old.index("# platform gate")
    end = old.index("_tlg_legacy=")
    stale = old[:start] + old[end:]                    # the block as an older Teyla wrote it
    assert "platform check" not in stale
    (hooks / "pre-push").write_text(stale)
    (hooks / "pre-push").chmod(0o755)
    cli.main(["leak", "install", str(repo)])
    text = (hooks / "pre-push").read_text()
    assert "teyla platform check --pre-push" in text
    assert text.count(li.BEGIN) == 1
