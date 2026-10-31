"""`teyla leak install` and `teyla leak terms --suggest`: hooks in tmp git repos, run for real through git and `sh`
with a `teyla` shim on PATH that calls this checkout's module; and the term candidates, whose output must never
carry an unmasked value. Every term, key and name here is invented; fixtures that look like leaks are built at
run time so this file is clean under the guard (scripts/leak_check.py)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from teyla import cli, leak_install as li

AT = "@"
KEY = "AKIA" + "QWERTYUIOPASDFGH"
TERM = "zorblax" + "-industries"
SRC = str(Path(__file__).resolve().parent.parent / "src")
SHIM = f"""#!/bin/sh
exec "{sys.executable}" -c 'import sys; from teyla.cli import main; sys.exit(main(sys.argv[1:]))' "$@"
"""

pytestmark = pytest.mark.skipif(not os.path.exists("/usr/bin/git") or not os.path.exists("/bin/sh"),
                                reason="needs /usr/bin/git and /bin/sh")


class Box:
    def __init__(self, tmp: Path, monkeypatch):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.bin = tmp / "bin"
        self.bin.mkdir()
        shim = self.bin / "teyla"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        self.teyla_home = tmp / "teyla-home"
        self.mark = tmp / "mark"
        self.env = {
            "HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "PYTHONPATH": SRC,
            "TEYLA_HOME": str(self.teyla_home), "MARK_FILE": str(self.mark),
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author" + AT + "example.com",
            "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author" + AT + "example.com",
        }
        for k, v in self.env.items():                 # in-process calls (cli.main) see the same world
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("TEYLA_LEAK", raising=False)
        monkeypatch.delenv("TEYLA_PRIVATE_TERMS", raising=False)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")

    def git(self, *args, env=None, cwd=None, check=True):
        p = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True,
                           env={**self.env, **(env or {})})
        if check and p.returncode:
            raise AssertionError(f"git {args}: {p.stderr}")
        return p

    def sh(self, script, *args, env=None):
        return subprocess.run(["/bin/sh", str(script), *args], cwd=self.repo, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env={**self.env, **(env or {})})

    def write(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def install(self, *extra):
        return cli.main(["leak", "install", str(self.repo), *extra])

    def hooks_path(self):
        p = self.git("config", "--local", "--get", "core.hooksPath", check=False)
        return p.stdout.strip() or None


@pytest.fixture
def box(tmp_path, monkeypatch):
    return Box(tmp_path, monkeypatch)


# --- install -----------------------------------------------------------------------------------------

def test_install_writes_executable_hooks_and_sets_hookspath(box, capsys):
    assert box.install() == 0
    out = capsys.readouterr().out
    assert "pre-commit new" in out and "pre-push new" in out and "Not committed" in out
    for hook in li.HOOKS:
        f = box.repo / ".githooks" / hook
        text = f.read_text()
        assert text.startswith("#!/bin/sh\n# teyla leak gate (")
        assert f.stat().st_mode & stat.S_IXUSR
    assert "teyla leak --staged --quiet" in (box.repo / ".githooks/pre-commit").read_text()
    assert "teyla leak --commits" in (box.repo / ".githooks/pre-push").read_text()
    assert box.hooks_path() == ".githooks"
    meta = json.loads((box.repo / ".githooks" / li.META).read_text())
    assert meta["hooks_path_set"] is True


def test_install_twice_changes_nothing(box, capsys):
    box.install()
    before = {p.name: p.read_bytes() for p in (box.repo / ".githooks").iterdir()}
    capsys.readouterr()
    assert box.install() == 0
    assert "pre-commit unchanged" in capsys.readouterr().out
    assert before == {p.name: p.read_bytes() for p in (box.repo / ".githooks").iterdir()}


def test_pre_commit_refuses_a_staged_key_and_passes_clean_files(box):
    box.install()
    box.write("a.txt", "just text\n")
    box.git("add", "a.txt")
    assert box.git("commit", "-q", "-m", "clean", check=False).returncode == 0
    box.write("b.txt", f"aws_access_key_id = {KEY}\n")
    box.git("add", "b.txt")
    p = box.git("commit", "-q", "-m", "leak", check=False)
    assert p.returncode != 0
    assert "teyla leak gate: pre-commit refused" in p.stderr
    assert KEY not in p.stdout + p.stderr                       # the scanner masks it
    assert box.git("log", "--oneline").stdout.count("\n") == 1  # nothing was committed


def test_pre_push_refuses_an_outgoing_commit_with_a_private_term(box):
    remote = box.tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    box.write("a.txt", "one\n")
    box.git("add", "a.txt")
    box.git("commit", "-q", "-m", "one")
    box.git("remote", "add", "origin", str(remote))
    box.git("push", "-q", "origin", "main")
    box.install()
    terms = box.tmp / "terms.txt"
    terms.write_text(TERM + "\n")
    env = {"TEYLA_PRIVATE_TERMS": str(terms)}
    box.write("b.txt", f"we work with {TERM} on this\n")
    box.git("add", "b.txt")
    box.git("commit", "-q", "--no-verify", "-m", "two")
    p = box.git("push", "origin", "main", env=env, check=False)
    assert p.returncode != 0
    assert "teyla leak gate: pre-push refused" in p.stderr
    assert TERM not in p.stdout + p.stderr                      # a term is never printed
    # the remote does not have the commit
    assert box.git("rev-list", "--count", "main", cwd=remote).stdout.strip() == "1"
    box.git("reset", "-q", "--hard", "HEAD~1")
    box.write("c.txt", "clean\n")
    box.git("add", "c.txt")
    box.git("commit", "-q", "--no-verify", "-m", "three")
    assert box.git("push", "origin", "main", env=env, check=False).returncode == 0


# --- chaining, hooksPath, uninstall --------------------------------------------------------------------

EXISTING = '#!/bin/sh\necho ran >> "$MARK_FILE"\nexit 0\n'


def test_chaining_adds_one_block_runs_ours_first_and_uninstall_restores(box, capsys):
    box.git("config", "--local", "core.hooksPath", ".githooks")
    f = box.write(".githooks/pre-commit", EXISTING)
    f.chmod(0o755)
    box.install()
    text = f.read_text()
    assert text.startswith("#!/bin/sh\n" + li.BEGIN) and text.count(li.BEGIN) == 1 and text.endswith(EXISTING.split("\n", 1)[1])
    box.install()
    assert f.read_text() == text                                # idempotent
    box.write("a.txt", "clean\n")
    box.git("add", "a.txt")
    assert box.git("commit", "-q", "-m", "x", check=False).returncode == 0
    assert box.mark.read_text() == "ran\n"                      # the existing hook still runs
    box.write("b.txt", KEY + "\n")
    box.git("add", "b.txt")
    assert box.git("commit", "-q", "-m", "y", check=False).returncode != 0
    assert box.mark.read_text() == "ran\n"                      # ours refused before the existing one ran
    capsys.readouterr()
    assert box.install("--uninstall") == 0
    assert f.read_text() == EXISTING and f.stat().st_mode & stat.S_IXUSR
    assert not (box.repo / ".githooks/pre-push").exists()
    assert box.hooks_path() == ".githooks"                      # we did not set it, so we do not unset it


def test_uninstall_of_a_fresh_install_removes_files_and_unsets_hookspath(box):
    box.install()
    assert box.install("--uninstall") == 0
    assert not (box.repo / ".githooks").exists() and box.hooks_path() is None


def test_an_existing_hooks_path_directory_is_used(box, capsys):
    box.git("config", "--local", "core.hooksPath", "hooks-x")
    assert box.install() == 0
    assert "already hooks-x" in capsys.readouterr().out
    assert (box.repo / "hooks-x/pre-commit").is_file() and not (box.repo / ".githooks").exists()
    assert box.hooks_path() == "hooks-x"


def test_a_hooks_path_outside_the_repo_is_refused(box, capsys):
    box.git("config", "--local", "core.hooksPath", str(box.tmp / "elsewhere"))
    assert box.install() == 2
    assert "outside the repo" in capsys.readouterr().out
    assert not (box.tmp / "elsewhere").exists()


def test_install_all_prints_a_line_per_repo(box, monkeypatch, capsys):
    other = box.tmp / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    from teyla import lang
    monkeypatch.setattr(lang, "resolve_repos", lambda args, cfg=None: [box.repo, other])
    assert cli.main(["leak", "install", "--all"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(("repo:", "other:"))]
    assert len(lines) == 2 and (other / ".githooks/pre-push").is_file()
    assert box.git("status", "--porcelain").stdout.count("githooks") == 1       # untracked, never committed


# --- a missing scanner, and the skip ------------------------------------------------------------------

def test_a_missing_teyla_is_exit_2_with_one_line(box):
    box.install()
    for hook, args in (("pre-commit", ()), ("pre-push", ("origin", "url"))):
        p = box.sh(box.repo / ".githooks" / hook, *args, env={"PATH": "/usr/bin:/bin"})
        assert p.returncode == 2
        assert p.stderr.strip() == "teyla leak gate: teyla not found; install it or set TEYLA_LEAK=0 for this command"


def test_teyla_leak_0_skips_one_command_and_logs_it(box):
    box.install()
    box.write("b.txt", KEY + "\n")
    box.git("add", "b.txt")
    p = box.git("commit", "-q", "-m", "skipped", env={"TEYLA_LEAK": "0"}, check=False)
    assert p.returncode == 0
    log = (box.teyla_home / "leak-skips.log").read_text().splitlines()
    assert len(log) == 1
    stamp, repo, hook = log[0].split("\t")
    assert stamp.startswith(date.today().isoformat()) and repo == box.repo.name and hook == "pre-commit"
    # not skipped: no new line, and the gate is back
    box.write("c.txt", KEY + "\n")
    box.git("add", "c.txt")
    assert box.git("commit", "-q", "-m", "again", check=False).returncode != 0
    assert len((box.teyla_home / "leak-skips.log").read_text().splitlines()) == 1


def test_the_hook_does_not_consume_pre_push_stdin(box):
    """A chained hook after ours still needs git's ref lines on stdin."""
    remote = box.tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    box.write("a.txt", "one\n")
    box.git("add", "a.txt")
    box.git("commit", "-q", "-m", "one")
    box.git("remote", "add", "origin", str(remote))
    box.git("push", "-q", "origin", "main")
    box.git("config", "--local", "core.hooksPath", ".githooks")
    box.write(".githooks/pre-push", '#!/bin/sh\ncat > "$MARK_FILE"\n').chmod(0o755)
    box.install()
    head = box.git("rev-parse", "HEAD").stdout.strip()
    refs = f"refs/heads/main {head} refs/heads/main {head}\n"
    p = subprocess.run(["/bin/sh", str(box.repo / ".githooks/pre-push"), "origin", str(remote)], cwd=box.repo,
                       input=refs, capture_output=True, text=True, env=box.env)
    assert p.returncode == 0, p.stderr
    assert box.mark.read_text() == refs


# --- review round: refs on stdin, private modes, the skip record, worktree scope, other shells ------------

def _remote(box):
    remote = box.tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    box.write("a.txt", "one\n")
    box.git("add", "a.txt")
    box.git("commit", "-q", "-m", "one")
    box.git("remote", "add", "origin", str(remote))
    box.git("push", "-q", "origin", "main")
    return remote


def test_pre_push_scans_the_refs_git_passes_not_head(box):
    remote = _remote(box)
    box.install()
    terms = box.tmp / "terms.txt"
    terms.write_text(TERM + "\n")
    env = {"TEYLA_PRIVATE_TERMS": str(terms)}
    box.git("checkout", "-q", "-b", "leaky")
    box.write("b.txt", f"we work with {TERM} on this\n")
    box.git("add", "b.txt")
    box.git("commit", "-q", "--no-verify", "-m", "two")
    box.git("checkout", "-q", "main")                            # HEAD is clean; the pushed ref is not
    new_branch = box.git("push", "origin", "leaky", env=env, check=False)
    assert new_branch.returncode != 0 and "pre-push refused" in new_branch.stderr
    update = box.git("push", "origin", "leaky:main", env=env, check=False)      # a non-zero remote sha
    assert update.returncode != 0 and "pre-push refused" in update.stderr
    assert box.git("rev-list", "--count", "--all", cwd=remote).stdout.strip() == "1"
    assert box.git("push", "origin", "main:tmpb", env=env, check=False).returncode == 0
    assert box.git("push", "origin", ":tmpb", env=env, check=False).returncode == 0     # a deletion: all-zero local sha


def test_the_terms_file_is_made_private_before_the_first_byte(box, monkeypatch, capsys):
    monkeypatch.setattr(li, "collect_facts", lambda root: [("Quentin Vexley", "git user.name")])
    f = box.tmp / "terms.txt"
    f.write_text("one\n")
    f.chmod(0o644)
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    seen = {}
    real = os.fchmod

    def spy(fd, mode):
        seen["size"], seen["mode"] = os.fstat(fd).st_size, stat.S_IMODE(os.fstat(fd).st_mode)
        real(fd, mode)
    monkeypatch.setattr(os, "fchmod", spy)
    assert run_terms(capsys, "--yes")[0] == 0
    assert seen == {"size": 4, "mode": 0o644} and stat.S_IMODE(f.stat().st_mode) == 0o600   # nothing written yet
    # a failing chmod writes nothing and exits 2
    f.write_text("one\n")
    monkeypatch.setattr(os, "fchmod", lambda fd, mode: (_ for _ in ()).throw(PermissionError("no")))
    rc, out, err = run_terms(capsys, "--yes")
    assert rc == 2 and "cannot write" in err and f.read_text() == "one\n" and "Quentin" not in out + err


def test_a_skip_that_cannot_be_logged_is_refused(box):
    box.install()
    box.write("b.txt", "clean\n")
    box.git("add", "b.txt")
    blocker = box.tmp / "not-a-dir"
    blocker.write_text("x")                                       # TEYLA_HOME is a file: the log cannot be made
    p = box.git("commit", "-q", "-m", "skipped", env={"TEYLA_LEAK": "0", "TEYLA_HOME": str(blocker)}, check=False)
    assert p.returncode != 0 and "cannot record the skip" in p.stderr
    assert p.stderr.startswith("mkdir:")                                                # the reason is printed
    assert box.git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0      # no commit was made


def test_a_worktree_level_hooks_path_is_the_effective_one(box, capsys):
    box.write("a.txt", "one\n")
    box.git("add", "a.txt")
    box.git("commit", "-q", "-m", "one")
    box.git("config", "extensions.worktreeConfig", "true")
    wt = box.tmp / "wt"
    box.git("worktree", "add", "-q", "-b", "wtb", str(wt))
    box.git("config", "--worktree", "core.hooksPath", "hooks-wt", cwd=wt)
    assert cli.main(["leak", "install", str(wt)]) == 0
    assert "(worktree scope)" in capsys.readouterr().out
    assert (wt / "hooks-wt/pre-commit").is_file() and not (wt / ".githooks").exists()
    # the main worktree has no value of its own: the repo's scope is set, and the line says which
    assert box.install() == 0
    assert "(local scope)" in capsys.readouterr().out
    assert box.install("--uninstall") == 0
    assert "unset (local scope)" in capsys.readouterr().out and box.hooks_path() is None


def test_a_non_sh_hook_is_renamed_and_runs_after_the_gate(box):
    box.git("config", "--local", "core.hooksPath", ".githooks")
    py = '#!/usr/bin/env python3\nimport os\nopen(os.environ["MARK_FILE"], "a").write("py\\n")\n'
    f = box.write(".githooks/pre-commit", py)
    f.chmod(0o755)
    box.install()
    assert (box.repo / ".githooks/pre-commit.chain").read_text() == py
    assert f.read_text().startswith("#!/bin/sh\n# teyla leak gate (pre-commit)") and "pre-commit.chain" in f.read_text()
    before = f.read_bytes()
    box.install()
    assert f.read_bytes() == before                              # idempotent
    box.write("a.txt", "clean\n")
    box.git("add", "a.txt")
    assert box.git("commit", "-q", "-m", "x", check=False).returncode == 0
    assert box.mark.read_text() == "py\n"                        # the old hook ran after the gate
    box.write("b.txt", KEY + "\n")
    box.git("add", "b.txt")
    assert box.git("commit", "-q", "-m", "y", check=False).returncode != 0
    assert box.mark.read_text() == "py\n"                        # and not when the gate refused
    box.install("--uninstall")
    assert f.read_text() == py and not (box.repo / ".githooks/pre-commit.chain").exists()


def test_a_hook_left_in_git_hooks_still_runs_with_args_and_stdin(box):
    remote = _remote(box)
    legacy = box.repo / ".git/hooks/pre-push"
    legacy.write_text('#!/bin/sh\necho "$@" > "$MARK_FILE"\ncat >> "$MARK_FILE"\n')
    legacy.chmod(0o755)
    box.install()
    box.write("c.txt", "clean\n")
    box.git("add", "c.txt")
    box.git("commit", "-q", "-m", "three")
    assert box.git("push", "origin", "main", check=False).returncode == 0
    lines = box.mark.read_text().splitlines()
    assert lines[0] == f"origin {remote}" and lines[1].startswith("refs/heads/main ")
    legacy.write_text("#!/bin/sh\nexit 3\n")                     # a failing legacy hook still blocks
    box.write("d.txt", "clean\n")
    box.git("add", "d.txt")
    box.git("commit", "-q", "-m", "four")
    assert box.git("push", "origin", "main", check=False).returncode != 0


def test_a_generated_hook_regains_its_exec_bit(box):
    box.install()
    for hook in li.HOOKS:
        (box.repo / ".githooks" / hook).chmod(0o644)
    box.install()
    assert all((box.repo / ".githooks" / h).stat().st_mode & stat.S_IXUSR for h in li.HOOKS)


# --- round 2: annotated tags, partial stdin, a non-executable hook, recursion --------------------------------

def test_pre_push_scans_an_annotated_tags_message(box):
    _remote(box)
    box.install()
    terms = box.tmp / "terms.txt"
    terms.write_text(TERM + "\n")
    env = {"TEYLA_PRIVATE_TERMS": str(terms)}
    box.git("tag", "-a", "v1", "-m", f"release for {TERM}")
    p = box.git("push", "origin", "v1", env=env, check=False)
    assert p.returncode != 0 and "annotated tag refs/tags/v1" in p.stderr and TERM not in p.stdout + p.stderr
    assert box.git("ls-remote", "--tags", "origin").stdout == ""
    box.git("tag", "-a", "v2", "-m", "a clean message")
    box.git("tag", "v3")                                          # lightweight: no object of its own
    assert box.git("push", "origin", "v2", "v3", env=env, check=False).returncode == 0


def test_a_partial_copy_of_the_pushed_refs_is_never_scanned(box):
    box.install()
    tee = box.bin / "tee"                                         # a tee that loses data, as a full disk would
    tee.write_text('#!/bin/sh\nin=$(cat)\nprintf "%s" "$in" | head -c 3 > "$1"\nprintf "%s" "$in"\n')
    tee.chmod(0o755)
    refs = "refs/heads/main " + "a" * 40 + " refs/heads/main " + "b" * 40 + "\n"
    p = subprocess.run(["/bin/sh", str(box.repo / ".githooks/pre-push"), "origin", "url"], cwd=box.repo, input=refs,
                       capture_output=True, text=True, env=box.env, timeout=60)
    assert p.returncode == 2
    assert p.stderr.strip() == "teyla leak gate: could not read the pushed refs; not scanning a partial list"


def test_an_existing_non_executable_sh_hook_is_made_executable(box):
    box.git("config", "--local", "core.hooksPath", ".githooks")
    f = box.write(".githooks/pre-commit", EXISTING)
    f.chmod(0o644)
    box.install()
    assert f.stat().st_mode & stat.S_IXUSR
    box.write("a.txt", "clean\n")
    box.git("add", "a.txt")
    assert box.git("commit", "-q", "-m", "x", check=False).returncode == 0
    assert box.mark.read_text() == "ran\n"                       # git ran it; before the fix it skipped it


def test_chaining_never_recurses_into_the_hook_being_run(box):
    box.git("config", "--local", "core.hooksPath", ".git/hooks")  # the hooks directory IS .git/hooks
    box.install()
    hook = box.repo / ".git/hooks/pre-commit"
    assert li.BEGIN in hook.read_text()
    p = subprocess.run(["/bin/sh", str(hook)], cwd=box.repo, capture_output=True, text=True, env=box.env,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert p.returncode == 0, p.stderr
    # and a chained hook never chains again
    box.git("config", "--local", "core.hooksPath", ".githooks")
    box.install()
    legacy = box.repo / ".git/hooks/pre-commit"
    legacy.write_text('#!/bin/sh\necho legacy >> "$MARK_FILE"\n')
    legacy.chmod(0o755)
    hook = box.repo / ".githooks/pre-commit"
    assert box.sh(hook).returncode == 0 and box.mark.read_text() == "legacy\n"
    assert box.sh(hook, env={"TEYLA_LEAK_CHAIN": "1"}).returncode == 0 and box.mark.read_text() == "legacy\n"


# --- terms --suggest ----------------------------------------------------------------------------------

FACTS = [("Quentin Vexley", "git user.name"), ("qvexley" + AT + "mail.test", "git user.email"),
         ("qvexley", "login name"), ("abc", "short"), ("Quentin Vexley", "git user.name"),
         ("alreadyknown", "hostname"), ("ALREADYKNOWN2", "computer name")]


def run_terms(capsys, *extra):
    rc = cli.main(["leak", "terms", "--suggest", *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def facts(box, monkeypatch):
    monkeypatch.setattr(li, "collect_facts", lambda root: list(FACTS))
    terms = box.tmp / "cfg" / "teyla" / "private-terms.txt"
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    return terms


def test_suggest_prints_only_masked_values_and_writes_nothing(box, facts, capsys):
    facts.parent.mkdir(parents=True)
    facts.write_text("# mine\nalreadyknown\nallow x in docs/*\n")
    before = facts.read_text()
    for extra in ((), ("--json",)):
        rc, out, err = run_terms(capsys, *extra)
        assert rc == 0
        for full in ("Quentin Vexley", "qvexley", "mail.test", "alreadyknown", "ALREADYKNOWN2"):
            assert full not in out + err, full
        assert "Qu…14" in out and "git user.name" in out
        assert "al…12" not in out and "ab…3" not in out             # known and short entries are skipped
        assert out.count("Qu…14") == 1                              # duplicates collapse
    assert facts.read_text() == before


def test_suggest_yes_appends_with_private_permissions_and_no_duplicates(box, facts, capsys):
    rc, out, _ = run_terms(capsys, "--yes")
    assert rc == 0 and out.strip() == "added 5 terms"
    assert stat.S_IMODE(facts.stat().st_mode) == 0o600 and stat.S_IMODE(facts.parent.stat().st_mode) == 0o700
    lines = [ln for ln in facts.read_text().splitlines() if not ln.startswith("#")]
    assert lines == ["Quentin Vexley", "qvexley" + AT + "mail.test", "qvexley", "alreadyknown", "ALREADYKNOWN2"]
    rc, out, _ = run_terms(capsys, "--yes")
    assert out.strip() == "added 0 terms" and facts.read_text().count("Quentin Vexley") == 1
    rc, out, _ = run_terms(capsys, "--json")
    assert json.loads(out) == {"candidates": [], "added": 0}


def test_suggest_yes_fixes_loose_permissions_on_the_default_location(box, monkeypatch, capsys):
    monkeypatch.setattr(li, "collect_facts", lambda root: [("Quentin Vexley", "git user.name")])
    d = box.home / ".config" / "teyla"
    d.mkdir(parents=True)
    d.chmod(0o755)
    f = d / "private-terms.txt"
    f.write_text("one\n")
    f.chmod(0o644)
    rc, out, _ = run_terms(capsys, "--yes")
    assert rc == 0 and "added 1 term" in out
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert "Quentin Vexley" in f.read_text() and "Quentin Vexley" not in out


def test_json_output_never_carries_a_value(box, facts, capsys):
    rc, out, _ = run_terms(capsys, "--yes", "--json")
    data = json.loads(out)
    assert data["added"] == 5 and all(set(c) == {"masked", "source"} for c in data["candidates"])
    assert "Quentin" not in out and "mail.test" not in out


def test_collect_facts_reads_only_machine_facts_and_this_repos_manifest(box, monkeypatch):
    gcfg = box.tmp / "gitconfig"
    gcfg.write_text(f"[user]\n\tname = Zed Quillon\n\temail = zq{AT}global.test\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gcfg))
    monkeypatch.setenv("USER", "zquillon")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(li.stdlib_platform, "node", lambda: "zq-workstation")
    box.git("config", "--local", "user.email", "zq" + AT + "repo.test")
    box.write("teyla.toml", f'[productize]\ntesters = ["pal{AT}friends.test"]\n[release]\napple_bundle_id = "com.orgquux.app"\n')
    box.teyla_home.mkdir()
    (box.teyla_home / "platform.toml").write_text('[server]\nhost = "apps.quux-hosting.test"\n[domain]\nname = "quux-sites.test"\n')
    facts = dict((v, s) for v, s in li.collect_facts(box.repo))
    assert facts["Zed Quillon"] == "git user.name"
    assert facts["zq" + AT + "repo.test"] == "git user.email" and facts["zq" + AT + "global.test"] == "git user.email"
    assert facts["zquillon"] == "login name" and facts["zq-workstation"] == "hostname" and facts["home"] == "home directory"
    assert facts["pal" + AT + "friends.test"] == "teyla.toml tester e-mail" and facts["orgquux"] == "bundle id organisation"
    assert facts["apps.quux-hosting.test"].startswith("platform.toml") and facts["quux-sites.test"].startswith("platform.toml")
    cands = [v for v, _ in li.candidates(box.repo, set())]
    assert "home" not in cands and "orgquux" in cands            # generic names and short values are dropped
