"""scripts/leak_check.py: the guard that keeps private data and non-English text out of the
public repo. Every private term here is invented; the fixtures that look like leaks are built
at run time, so this file itself is clean under the guard."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"
CYR = "Привет"          # a Russian greeting
AT = "@"


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    e = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
         "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author" + AT + "example.com",
         "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author" + AT + "example.com", **(env or {})}
    p = subprocess.run(["git", *args], cwd=cwd, env=e, capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return r


@pytest.fixture
def terms(tmp_path, monkeypatch):
    f = tmp_path / "terms.txt"
    f.write_text("# fake terms\nzebracorn\n\nallow zebracorn in docs/*\nquokka lab\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    return f


def commit_files(repo: Path, files: dict[str, str], msg: str = "add files", **kw) -> None:
    for name, body in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, **kw)


def run(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, capture_output=True, text=True,
                          input=stdin, env=os.environ.copy())


def rules(p: subprocess.CompletedProcess) -> list[str]:
    return [line.split(": ")[1] for line in p.stdout.splitlines()]


# --- private terms -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "zebracorn", "ZebraCorn rocks", "-Users-zebracorn-repos-app", "my_zebracorn_thing",
    "path/zebracorn/x", "zebracorn.example", "a zebracorn-b",
])
def test_term_matches_across_separators(repo, terms, text):
    commit_files(repo, {"a.txt": text + "\n"})
    p = run(repo)
    assert p.returncode == 1 and rules(p) == ["term"]
    assert "ze***" in p.stdout.lower() and "zebracorn" not in p.stdout.lower()


@pytest.mark.parametrize("text", ["zebracorns", "xzebracorn", "zebracorn2", "zebra corn"])
def test_term_needs_boundaries(repo, terms, text):
    commit_files(repo, {"a.txt": text + "\n"})
    assert run(repo).returncode == 0


def test_multiword_term(repo, terms):
    commit_files(repo, {"a.txt": "see the Quokka Lab page\n"})
    assert rules(run(repo)) == ["term"]


def test_allow_line_scopes_term_to_a_glob(repo, terms):
    commit_files(repo, {"docs/ok.md": "zebracorn\n", "src/bad.py": "# zebracorn\n"})
    p = run(repo)
    assert p.returncode == 1
    assert p.stdout.startswith("src/bad.py:1: term: ") and "docs/ok.md" not in p.stdout


def test_excerpt_masks_every_match_on_the_line(repo, terms):
    commit_files(repo, {"a.txt": "zebracorn and quokka lab\n"})
    out = run(repo).stdout
    assert out.count("***") == 2 and "quokka" not in out.lower()


def test_missing_term_file_notes_and_keeps_generic_rules(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "nope.txt"))
    commit_files(repo, {"a.txt": "zebracorn\n", "b.txt": CYR + "\n"})
    p = run(repo)
    assert p.stderr.count("no private term list; generic rules only") == 1
    assert rules(p) == ["cyrillic"] and p.returncode == 1


def test_default_term_file_location(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("TEYLA_PRIVATE_TERMS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".config" / "teyla").mkdir(parents=True)
    (tmp_path / ".config" / "teyla" / "private-terms.txt").write_text("zebracorn\n")
    commit_files(repo, {"a.txt": "zebracorn\n"})
    assert rules(run(repo)) == ["term"]


# --- e-mails --------------------------------------------------------------------------------

def test_real_looking_email_is_flagged_and_masked(repo, terms):
    commit_files(repo, {"a.txt": "write to jdoe" + AT + "corp-mail.io please\n"})
    p = run(repo)
    assert rules(p) == ["email"] and "jd***" in p.stdout and "corp-mail" not in p.stdout


@pytest.mark.parametrize("addr", [
    "a" + AT + "example.com", "a" + AT + "mail.example.org", "a" + AT + "example.net",
    "12345+someone" + AT + "users.noreply.github.com", "noreply" + AT + "anthropic.com",
    "git" + AT + "github.com:org/repo.git", "icon" + AT + "2x.png",
])
def test_email_exceptions(repo, terms, addr):
    commit_files(repo, {"a.txt": f"{addr}\n"})
    assert run(repo).returncode == 0


def test_email_allow_pattern(repo, terms):
    commit_files(repo, {"a.txt": "x" + AT + "fixture.test\n", ".leak-allow": "emails:\n*" + AT + "fixture.test  # test data\n"})
    assert run(repo).returncode == 0


# --- home paths -----------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/Users/me/x", "/Users/<user>/x", "/Users/$USER/x", "/home/runner/work", "/Users/Name/x",
    "/home/alice/", "/Users/username/repos", "/Users/Shared/x",
])
def test_home_placeholders_pass(repo, terms, path):
    commit_files(repo, {"a.txt": path + "\n"})
    assert run(repo).returncode == 0


def test_home_real_looking_name_flagged(repo, terms):
    commit_files(repo, {"a.txt": "cd /Users/" + "jdoe" + "/repos/app\n", "b.txt": "/home/" + "jdoe" + "/x\n"})
    p = run(repo)
    assert rules(p) == ["home", "home"] and "/Users/jd***/" in p.stdout


def test_home_allow_entry(repo, terms):
    commit_files(repo, {"a.txt": "/Users/" + "jdoe" + "/x\n", ".leak-allow": "home:\njdoe\n"})
    assert run(repo).returncode == 0


# --- secrets --------------------------------------------------------------------------------

def test_secret_shapes_and_allow_by_path(repo, terms):
    key = "sk-ant-" + "A1" * 12
    pem = "-----BEGIN " + "RSA PRIVATE KEY-----"
    commit_files(repo, {"src/a.py": f"K = '{key}'\n", "tests/t.py": f"K = '{key}'\n{pem}\n",
                        ".leak-allow": "secrets:\ntests/t.py  # fake fixture\n"})
    p = run(repo)
    assert rules(p) == ["secret"] and p.stdout.startswith("src/a.py:1:") and key not in p.stdout


def test_pem_header_flagged(repo, terms):
    commit_files(repo, {"a.txt": "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n"})
    assert rules(run(repo)) == ["secret"]


# --- non-English ----------------------------------------------------------------------------

def test_cyrillic_blocked_unless_listed(repo, terms):
    commit_files(repo, {"src/a.py": f'X = "{CYR}"\n', "src/lexicon.py": f'X = "{CYR}"\n',
                        ".leak-allow": "cyrillic:\nsrc/lexicon.py  # language data\n"})
    p = run(repo)
    assert p.returncode == 1 and rules(p) == ["cyrillic"] and p.stdout.startswith("src/a.py:1:")
    assert "Пр***" in p.stdout and CYR not in p.stdout


def test_binary_files_skipped(repo, terms):
    (repo / "img.bin").write_bytes(b"\x00\x01zebracorn")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bin")
    assert run(repo).returncode == 0


def test_paths_section_skips_file_entirely(repo, terms):
    commit_files(repo, {"gen.txt": "zebracorn " + CYR + "\n", ".leak-allow": "paths:\ngen.txt\n"})
    assert run(repo).returncode == 0


# --- --commits ------------------------------------------------------------------------------

def test_commits_catches_bad_author_email_and_term_in_message(repo, terms):
    commit_files(repo, {"a.txt": "clean\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"b.txt": "clean\n"}, msg="fix for zebracorn",
                 env={"GIT_AUTHOR_EMAIL": "jdoe" + AT + "corp-mail.io", "GIT_COMMITTER_EMAIL": "jdoe" + AT + "corp-mail.io"})
    p = run(repo, "--commits", f"{base}..HEAD")
    assert p.returncode == 1
    assert sorted(rules(p)) == ["email", "term"]
    assert ":author:" in p.stdout and ":message:" in p.stdout
    assert run(repo, "--commits", f"{base}..{base}").returncode == 0     # empty range


def test_commits_clean_and_noreply_and_author_allow(repo, terms, tmp_path):
    commit_files(repo, {"a.txt": "x\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"b.txt": "y\n"}, msg="ok\n\nCo-Authored-By: Bot <noreply" + AT + "anthropic.com>",
                 env={"GIT_AUTHOR_NAME": "Zebracorn Person", "GIT_AUTHOR_EMAIL": "1+z" + AT + "users.noreply.github.com"})
    assert rules(run(repo, "--commits", f"{base}..HEAD")) == ["term"]
    terms.write_text("zebracorn\nallow zebracorn in commit:*:author\n")
    assert run(repo, "--commits", f"{base}..HEAD").returncode == 0


def test_commits_cyrillic_message(repo, terms):
    commit_files(repo, {"a.txt": "x\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"b.txt": "y\n"}, msg=CYR)
    assert rules(run(repo, "--commits", f"{base}..HEAD")) == ["cyrillic"]


def test_commits_bad_range_is_usage_error(repo, terms):
    commit_files(repo, {"a.txt": "x\n"})
    assert run(repo, "--commits", "nope..HEAD").returncode == 2


# --- --text, --quiet, exit codes -------------------------------------------------------------

def test_text_file_and_stdin(repo, terms, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("Summary\n\nfixes the zebracorn thing\n")
    p = run(repo, "--text", str(body))
    assert p.returncode == 1 and f"{body}:3: term:" in p.stdout
    body.write_text("All clean.\n")
    assert run(repo, "--text", str(body)).returncode == 0
    assert run(repo, "--text", "-", stdin="mail jdoe" + AT + "corp-mail.io\n").stdout.startswith("<stdin>:1: email:")


def test_quiet_prints_only_the_count(repo, terms):
    commit_files(repo, {"a.txt": "zebracorn\n", "b.txt": CYR + "\n"})
    p = run(repo, "--quiet")
    assert p.stdout == "2\n" and p.returncode == 1
    commit_files(repo, {"a.txt": "fine\n", "b.txt": "fine\n"})
    p = run(repo, "--quiet")
    assert p.stdout == "0\n" and p.returncode == 0


def test_clean_tree_exits_zero_silently(repo, terms):
    commit_files(repo, {"a.txt": "hello\n"})
    p = run(repo)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_outside_a_repo_is_usage_error(tmp_path, terms):
    p = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True)
    assert p.returncode == 2 and "not inside a git repository" in p.stderr


# --- content added by commits ----------------------------------------------------------------

KEY = "sk-ant-" + "A1" * 12


def test_commits_scan_a_key_added_then_removed(repo, terms):
    commit_files(repo, {"a.txt": "ok\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"src/k.py": f"x = 1\nKEY = '{KEY}'\n"}, msg="add key")
    bad = git(repo, "rev-parse", "HEAD")[:8]
    commit_files(repo, {"src/k.py": "x = 1\n"}, msg="remove key")
    assert run(repo).returncode == 0                       # the tree is clean...
    p = run(repo, "--commits", f"{base}..HEAD")            # ...the history is not
    assert p.returncode == 1 and rules(p) == ["secret"]
    assert p.stdout.startswith(f"commit:{bad}:src/k.py:2: secret: ") and KEY not in p.stdout


def test_commits_only_added_lines_and_hunk_line_numbers(repo, terms):
    commit_files(repo, {"a.txt": "one\ntwo\nthree\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"a.txt": "one\ntwo\nthree\nzebracorn\nfive\n"}, msg="add")
    commit_files(repo, {"a.txt": "one\ntwo\nthree\nfive\n"}, msg="drop the term again")
    out = run(repo, "--commits", f"{base}..HEAD").stdout.splitlines()
    assert len(out) == 1 and ":a.txt:4: term:" in out[0]    # the removal is not a finding


def test_commits_path_globs_apply_like_the_tree_scan(repo, terms):
    commit_files(repo, {".leak-allow": "secrets:\ntests/*\ncyrillic:\ntests/*\npaths:\ngen/*\n"}, msg="allow")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"tests/t.py": f"K = '{KEY}'\n# {CYR}\n", "gen/g.txt": f"{KEY} zebracorn\n",
                        "docs/d.md": "zebracorn\n", "src/s.py": f"# {CYR}\n"}, msg="content")
    out = run(repo, "--commits", f"{base}..HEAD").stdout.splitlines()
    assert sorted((l.split(": ")[0].split(":", 2)[2], l.split(": ")[1]) for l in out) == [("src/s.py:1", "cyrillic")]


def test_commits_skip_binary_diffs(repo, terms):
    commit_files(repo, {"a.txt": "x\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "b.bin").write_bytes(b"\x00\x01zebracorn\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bin")
    assert run(repo, "--commits", f"{base}..HEAD").returncode == 0


def test_commits_content_line_starting_with_plus_signs(repo, terms):
    commit_files(repo, {"a.txt": "x\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"a.txt": "x\n++ zebracorn\n"}, msg="plus")
    assert rules(run(repo, "--commits", f"{base}..HEAD")) == ["term"]


# --- size, TLDs ------------------------------------------------------------------------------

def test_large_text_files_are_still_scanned(repo, terms):
    commit_files(repo, {"big.txt": "filler line of text\n" * 200_000 + "zebracorn\n"})
    assert (repo / "big.txt").stat().st_size > 2_000_000
    p = run(repo)
    assert p.returncode == 1 and p.stdout.startswith("big.txt:200001: term:")


def test_large_binary_is_skipped(repo, terms):
    (repo / "big.bin").write_bytes(b"\x00" + b"zebracorn\n" * 400_000)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bin")
    assert run(repo).returncode == 0


@pytest.mark.parametrize("domain", ["company.sh", "company.md", "corp.json", "corp.py", "corp.ai"])
def test_file_like_tlds_are_not_excused(repo, terms, domain):
    commit_files(repo, {"a.txt": "person" + AT + domain + "\n"})
    assert rules(run(repo)) == ["email"]


def test_retina_asset_names_are_not_addresses(repo, terms):
    commit_files(repo, {"a.txt": "icon" + AT + "2x.png logo" + AT + "3x.webp\n"})
    assert run(repo).returncode == 0


def test_retina_exception_is_only_for_image_names(repo, terms):
    commit_files(repo, {"a.txt": "person" + AT + "2x.com\n"})
    assert rules(run(repo)) == ["email"]


def test_commits_scan_lines_written_while_resolving_a_merge(repo, terms):
    commit_files(repo, {"m.txt": "base\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "side")
    commit_files(repo, {"m.txt": "side\n"}, msg="side")
    git(repo, "checkout", "-q", "-")
    commit_files(repo, {"m.txt": "main\n"}, msg="main")
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "merge", "-q", "side")                                            # conflicts
    (repo / "m.txt").write_text(f"KEY = '{KEY}'\n")
    git(repo, "add", "m.txt")
    git(repo, "commit", "-q", "--no-edit")
    commit_files(repo, {"m.txt": "resolved\n"}, msg="remove key")
    assert "secret" in rules(run(repo, "--commits", f"{base}..HEAD"))


def test_commits_scan_ignores_a_noprefix_setting(repo, terms):
    commit_files(repo, {"README": "x\n"}, msg="base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "config", "diff.noprefix", "true")
    commit_files(repo, {"src/config.py": f"KEY = '{KEY}'\n"}, msg="add key")
    commit_files(repo, {"src/config.py": "x = 1\n"}, msg="remove key")
    assert "secret" in rules(run(repo, "--commits", f"{base}..HEAD"))


# --- the pre-push hook -----------------------------------------------------------------------

ZERO = "0" * 40
HOOK = Path(__file__).resolve().parent.parent / ".githooks" / "pre-push"


def hook(repo: Path, url: str, lsha: str, rsha: str = ZERO) -> subprocess.CompletedProcess:
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "leak_check.py").write_text(SCRIPT.read_text())
    return subprocess.run(["bash", str(HOOK), "dest", url], cwd=repo, capture_output=True, text=True,
                          input=f"refs/heads/main {lsha} refs/heads/main {rsha}\n", env=os.environ.copy())


def bare(tmp: Path, repo: Path, name: str, sha: str | None = None) -> str:
    """A bare repository standing in for the push destination, holding `sha` (or nothing)."""
    dest = tmp / name
    subprocess.run(["git", "init", "-q", "--bare", str(dest)], check=True)
    if sha:
        git(repo, "push", "-q", "--no-verify", str(dest), f"{sha}:refs/heads/main")
    return str(dest)


@pytest.fixture
def history(repo):
    """main = [commit with a key, commit removing it]; the tree is clean, the history is not."""
    commit_files(repo, {"src/k.py": f"KEY = '{KEY}'\n"}, msg="add key")
    first = git(repo, "rev-parse", "HEAD")
    commit_files(repo, {"src/k.py": "x = 1\n"}, msg="remove key")
    return repo, first, git(repo, "rev-parse", "HEAD")


def test_hook_empty_destination_scans_all_history(history, terms, tmp_path):
    repo, first, last = history
    git(repo, "update-ref", "refs/remotes/origin/main", last)       # tracking refs say "has everything"...
    p = hook(repo, bare(tmp_path, repo, "public.git"), last)        # ...but the destination is empty
    assert p.returncode == 1 and "secret" in p.stdout


def test_hook_scans_only_what_the_destination_lacks(history, terms, tmp_path):
    repo, first, last = history
    url = bare(tmp_path, repo, "has-first.git", first)              # the key commit is already there
    assert hook(repo, url, last).returncode == 0                    # only the removal is new


def test_hook_new_commits_on_existing_ref(history, terms, tmp_path):
    repo, first, last = history
    url = bare(tmp_path, repo, "has-last.git", last)
    assert hook(repo, url, last, last).returncode == 0
    commit_files(repo, {"b.txt": "zebracorn\n"}, msg="term")
    p = hook(repo, url, git(repo, "rev-parse", "HEAD"), last)
    assert p.returncode == 1 and "term" in p.stdout


def test_hook_unreachable_destination_scans_all_history(history, terms, tmp_path):
    repo, first, last = history
    assert hook(repo, str(tmp_path / "missing.git"), last, "f" * 40).returncode == 1


def test_hook_ref_deletion_is_skipped(history, terms, tmp_path):
    repo, first, last = history
    assert hook(repo, str(tmp_path / "missing.git"), ZERO, last).returncode == 0
