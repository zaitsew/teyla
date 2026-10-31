"""The sectioned terms file: kind A terms (`[everywhere]`, or before any header) apply in every repo, kind B
terms (`[teyla]`) only inside Teyla's own repo; and `teyla leak terms list|move`, which re-section a file without
ever printing a term. Every term here is invented, and the terms live in tmp files."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from teyla import cli, leak

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"
SECTIONED = ("# fake terms\nzebracorn\nallow zebracorn in docs/*\n\n"
             "[teyla]\n# never in Teyla's repo: product and organisation names\nmarmotly\nquokka lab\n"
             "[everywhere]\nfennec\n")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for k, v in {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test Author",
                 "GIT_AUTHOR_EMAIL": "author@example.com", "GIT_COMMITTER_NAME": "Test Author",
                 "GIT_COMMITTER_EMAIL": "author@example.com"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent")
    monkeypatch.setattr(leak, "_which", lambda name: None)


def make_repo(tmp: Path, name: str, pyproject: str | None) -> Path:
    r = tmp / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    files = {"notes.txt": "zebracorn here\nmarmotly there\nquokka lab too\nfennec as well\n"}
    if pyproject is not None:
        files["pyproject.toml"] = pyproject
    for rel, body in files.items():
        (r / rel).write_text(body)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "add files")
    return r


@pytest.fixture
def teyla_repo(tmp_path):
    return make_repo(tmp_path, "teyla-clone", '[project]\nname = "teyla"\nversion = "1"\n')


@pytest.fixture
def other_repo(tmp_path):
    return make_repo(tmp_path, "product", '[project]\nname = "someproduct"\nversion = "1"\n')


@pytest.fixture
def terms(tmp_path, monkeypatch):
    f = tmp_path / "terms.txt"
    f.write_text(SECTIONED)
    f.chmod(0o600)
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    return f


def script(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, capture_output=True, text=True,
                          input=stdin, env=os.environ.copy())


def scan(capsys, *args: str) -> tuple[int, dict]:
    code = leak.main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def term_hits(doc: dict) -> dict[str, list[int]]:
    """masked term -> the lines it was found on."""
    out: dict[str, list[int]] = {}
    for f in doc["findings"]:
        if f["rule"] == "term":
            out.setdefault(f["masked"], []).append(f["line"])
    return out


# --- scanning: the Teyla rule ------------------------------------------------------------------

def test_the_fallback_script_flags_both_kinds_inside_teyla(teyla_repo, terms):
    p = script(teyla_repo)
    assert p.returncode == 1 and p.stdout.count(": term: ") == 4         # zebracorn, marmotly, quokka lab, fennec
    assert "marmotly" not in p.stdout and "zebracorn" not in p.stdout


def test_the_fallback_script_flags_only_kind_a_in_another_repo(other_repo, terms):
    p = script(other_repo)
    assert p.returncode == 1 and p.stdout.count(": term: ") == 2         # zebracorn and fennec
    assert [ln.split(":")[1] for ln in p.stdout.splitlines()] == ["1", "4"]


def test_teyla_leak_flags_both_kinds_inside_teyla(teyla_repo, terms, capsys, monkeypatch):
    monkeypatch.chdir(teyla_repo)
    code, doc = scan(capsys)
    assert code == 1
    assert term_hits(doc) == {"term:0": [1], "term:1": [2], "term:2": [3], "term:3": [4]}


def test_teyla_leak_flags_only_kind_a_in_another_repo_and_keeps_the_indices(other_repo, terms, capsys, monkeypatch):
    monkeypatch.chdir(other_repo)
    code, doc = scan(capsys)
    assert code == 1
    assert term_hits(doc) == {"term:0": [1], "term:3": [4]}               # the index is the file position, not a rank


def test_a_repo_argument_decides_not_the_current_directory(teyla_repo, other_repo, terms, capsys, monkeypatch):
    monkeypatch.chdir(teyla_repo)
    code, doc = scan(capsys, str(other_repo))
    assert sorted(term_hits(doc)) == ["term:0", "term:3"]
    monkeypatch.chdir(other_repo)
    code, doc = scan(capsys, str(teyla_repo))
    assert sorted(term_hits(doc)) == ["term:0", "term:1", "term:2", "term:3"]


def test_a_file_without_headers_behaves_as_before(teyla_repo, other_repo, tmp_path, monkeypatch, capsys):
    f = tmp_path / "flat.txt"
    f.write_text("zebracorn\nmarmotly\nquokka lab\nfennec\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    for repo in (teyla_repo, other_repo):
        monkeypatch.chdir(repo)
        code, doc = scan(capsys)
        assert sorted(term_hits(doc)) == ["term:0", "term:1", "term:2", "term:3"]
        assert script(repo).stdout.count(": term: ") == 4


def test_allow_lines_work_in_both_sections(teyla_repo, tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.txt"
    f.write_text("zebracorn\nallow zebracorn in notes.*\n[teyla]\nmarmotly\nallow marmotly in notes.*\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    monkeypatch.chdir(teyla_repo)
    code, doc = scan(capsys)
    assert code == 0 and term_hits(doc) == {}


def test_a_term_in_both_sections_is_kind_a_and_keeps_its_first_position(other_repo, tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.txt"
    f.write_text("[teyla]\nmarmotly\nzebracorn\n[everywhere]\nMarmotly\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    monkeypatch.chdir(other_repo)
    code, doc = scan(capsys)
    assert term_hits(doc) == {"term:0": [2]}      # marmotly stands at 0 and applies here; zebracorn is [teyla] only


def test_an_unknown_section_header_is_exit_two_without_printing_it(other_repo, tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.txt"
    f.write_text("zebracorn\n[teyla-ish]\nmarmotly\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    monkeypatch.chdir(other_repo)
    code = leak.main(["--json"])
    out = capsys.readouterr().out
    assert code == 1 and "teyla-ish" not in out                           # a blocker still wins over the config error
    p = script(other_repo)
    assert p.returncode == 2 and "line 2" in p.stderr and "teyla-ish" not in p.stderr


def test_the_scrubber_masks_every_term_whatever_the_section(other_repo, terms, capsys, monkeypatch):
    (other_repo / "marmotly-plan.txt").write_text("hello\n")
    git(other_repo, "add", "-A")
    git(other_repo, "commit", "-q", "-m", "add plan")
    monkeypatch.chdir(other_repo)
    leak.main([])
    out = capsys.readouterr().out
    assert "marmotly" not in out.lower()


# --- how a repo is known to be Teyla's ---------------------------------------------------------

@pytest.mark.parametrize("pyproject,expect", [
    ('[project]\nname = "teyla"\n', True),
    ('[project]\nname = "Teyla"\n', True),
    ('[project]\nname = "teyla-tools"\n', False),
    ('[tool.x]\nname = "teyla"\n', False),
    ('[project]\nname = "teyla"\nname = "teyla"\n', True),    # does not parse: the regex fallback still finds it
    (None, False),
])
def test_is_teyla_repo_reads_the_project_name(tmp_path, pyproject, expect):
    r = make_repo(tmp_path, "r", pyproject)
    eng = leak._engine()
    assert eng.is_teyla_repo(r) is expect


def test_is_teyla_repo_from_a_subdirectory_and_a_linked_worktree(teyla_repo, tmp_path):
    eng = leak._engine()
    sub = teyla_repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert eng.is_teyla_repo(sub)
    wt = tmp_path / "wt"
    git(teyla_repo, "worktree", "add", "-q", "-b", "side", str(wt))
    assert (wt / ".git").is_file() and eng.is_teyla_repo(wt)


def test_is_teyla_repo_outside_any_repo_is_no(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "teyla"\n')      # no .git above it
    assert leak._engine().is_teyla_repo(tmp_path) is False


def test_the_nearest_repo_decides(teyla_repo):
    inner = make_repo(teyla_repo, "vendored", '[project]\nname = "other"\n')
    assert leak._engine().is_teyla_repo(inner) is False


# --- --text ------------------------------------------------------------------------------------

def test_text_inside_teyla_applies_both_kinds(teyla_repo, terms, monkeypatch, capsys):
    monkeypatch.chdir(teyla_repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO("zebracorn and marmotly\n"))
    code, doc = scan(capsys, "--text", "-")
    assert code == 1 and sorted(term_hits(doc)) == ["term:0", "term:1"]
    out = script(teyla_repo, "--text", "-", stdin="zebracorn and marmotly\n").stdout
    assert out == "<stdin>:1: term: ze*** and ma***\n"


def test_text_outside_teyla_applies_kind_a_only(other_repo, terms, monkeypatch, capsys):
    monkeypatch.chdir(other_repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO("zebracorn and marmotly\n"))
    code, doc = scan(capsys, "--text", "-")
    assert code == 1 and sorted(term_hits(doc)) == ["term:0"]
    assert script(other_repo, "--text", "-", stdin="zebracorn and marmotly\n").stdout == "<stdin>:1: term: ze*** and marmotly\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO("only marmotly\n"))
    assert scan(capsys, "--text", "-")[0] == 0


def test_text_outside_any_repo_applies_kind_a_only(tmp_path, terms, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    assert [f.masked for f in leak.scan_text("marmotly zebracorn")] == ["term:0"]
    assert script(bare, "--text", "-", stdin="marmotly\n").returncode == 0


def test_scan_text_inside_teyla_through_the_api(teyla_repo, terms, monkeypatch):
    monkeypatch.chdir(teyla_repo / "src" if (teyla_repo / "src").exists() else teyla_repo)
    assert sorted(f.masked for f in leak.scan_text("marmotly zebracorn")) == ["term:0", "term:1"]


# --- teyla leak terms list | move --------------------------------------------------------------

def terms_cmd(capsys, *args: str) -> tuple[int, str, str]:
    rc = cli.main(["leak", "terms", *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


NO_VALUES = ("zebracorn", "marmotly", "quokka", "fennec")


def test_list_prints_index_section_and_a_masked_form_only(terms, capsys):
    rc, out, err = terms_cmd(capsys, "list")
    assert rc == 0 and err == ""
    rows = [ln.split() for ln in out.splitlines()]
    assert rows == [["term:0", "everywhere", "ze…9"], ["term:1", "teyla", "ma…8"],
                    ["term:2", "teyla", "qu…10"], ["term:3", "everywhere", "fe…6"]]
    assert not any(v in out.lower() for v in NO_VALUES)


def test_list_json_has_no_values(terms, capsys):
    rc, out, _ = terms_cmd(capsys, "list", "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["terms"][1] == {"index": 1, "section": "teyla", "masked": "ma…8"}
    assert all(set(t) == {"index", "section", "masked"} for t in doc["terms"])
    assert not any(v in out.lower() for v in NO_VALUES)


def test_list_of_a_missing_file_is_empty_not_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "none.txt"))
    assert terms_cmd(capsys, "list") == (0, "no terms\n", "")


def test_move_to_teyla_rewrites_the_file_and_keeps_comments_allow_lines_and_mode(terms, capsys):
    terms.chmod(0o644)
    rc, out, err = terms_cmd(capsys, "move", "0", "term:3", "--to", "teyla")
    assert rc == 0 and err == ""
    assert not any(v in out.lower() for v in NO_VALUES)
    assert out.splitlines() == ["term:0 -> term:2  teyla", "term:3 -> term:3  teyla", "moved 2 terms to [teyla]"]
    assert stat.S_IMODE(terms.stat().st_mode) == 0o600
    text = terms.read_text()
    assert "# fake terms" in text and "allow zebracorn in docs/*" in text and "# never in Teyla's repo" in text
    assert [t for t in os.listdir(terms.parent) if t.startswith(".")] == []          # no temporary file left behind
    rc, out, _ = terms_cmd(capsys, "list")
    assert [ln.split()[:2] for ln in out.splitlines()] == [["term:0", "teyla"], ["term:1", "teyla"],
                                                           ["term:2", "teyla"], ["term:3", "teyla"]]


def test_move_to_everywhere_puts_the_term_at_the_end_of_that_section(terms, capsys):
    """The last `everywhere` block of the file is the end of that section: here the one that holds fennec."""
    rc, out, _ = terms_cmd(capsys, "move", "1", "--to", "everywhere")
    assert rc == 0 and out.splitlines()[0] == "term:1 -> term:3  everywhere"
    rc, out, _ = terms_cmd(capsys, "list")
    assert [ln.split()[:2] for ln in out.splitlines()] == [["term:0", "everywhere"], ["term:1", "teyla"],
                                                           ["term:2", "everywhere"], ["term:3", "everywhere"]]
    assert [ln.split()[2] for ln in out.splitlines()] == ["ze…9", "qu…10", "fe…6", "ma…8"]


def test_the_index_rule_after_a_move(terms, capsys):
    """Indices are file positions. A move writes each moved term once, at the end of its new section; terms that
    stay keep their relative order and close the gap. The output of `move` is the old -> new map."""
    before = [ln.split()[2] for ln in terms_cmd(capsys, "list")[1].splitlines()]          # ze, ma, qu, fe
    rc, out, _ = terms_cmd(capsys, "move", "0", "--to", "teyla")
    assert out.splitlines()[0] == "term:0 -> term:2  teyla"                                # after ma and qu
    after = [ln.split()[2] for ln in terms_cmd(capsys, "list")[1].splitlines()]
    assert after == [before[1], before[2], before[0], before[3]]
    assert after[2] == before[0]                                                           # the map told the truth
    # the scanner reads the same sections and order
    assert leak._engine().distinct_terms(terms.read_text()) == [
        ("marmotly", "teyla"), ("quokka lab", "teyla"), ("zebracorn", "teyla"), ("fennec", "everywhere")]


def test_move_creates_the_teyla_section_in_a_headerless_file(tmp_path, monkeypatch, capsys):
    f = tmp_path / "flat.txt"
    f.write_text("zebracorn\nmarmotly\n# end")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    rc, out, _ = terms_cmd(capsys, "move", "1", "--to", "teyla")
    assert rc == 0 and out.splitlines()[0] == "term:1 -> term:1  teyla"
    assert f.read_text().splitlines() == ["zebracorn", "# end", "",
                                          "[teyla]", "# never in Teyla's repo: product and organisation names",
                                          "marmotly"]
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    # and back: the headerless block is where kind A goes when no [everywhere] header exists
    rc, out, _ = terms_cmd(capsys, "move", "1", "--to", "everywhere")
    assert f.read_text().splitlines()[:3] == ["zebracorn", "# end", "marmotly"]


def test_move_to_everywhere_before_the_first_header(tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.txt"
    f.write_text("[teyla]\nmarmotly\nzebracorn\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    assert terms_cmd(capsys, "move", "0", "--to", "everywhere")[0] == 0
    assert f.read_text().splitlines() == ["marmotly", "[teyla]", "zebracorn"]


def test_moving_a_term_to_the_section_it_is_in_changes_nothing(terms, capsys):
    before = terms.read_text()
    rc, out, _ = terms_cmd(capsys, "move", "1", "--to", "teyla")
    assert rc == 0 and out == "moved 0 terms to [teyla]\n" and terms.read_text() == before


def test_move_moves_every_duplicate_line_of_the_term(tmp_path, monkeypatch, capsys):
    f = tmp_path / "t.txt"
    f.write_text("marmotly\nzebracorn\n[teyla]\nMarmotly\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    assert terms_cmd(capsys, "list")[1].splitlines()[0].split()[1] == "everywhere"       # the stronger section wins
    assert terms_cmd(capsys, "move", "0", "--to", "teyla")[0] == 0
    assert f.read_text().lower().count("marmotly") == 1


@pytest.mark.parametrize("args,msg", [
    (("move", "9", "--to", "teyla"), "no term with index 9"),
    (("move", "x", "--to", "teyla"), "not an index"),
    (("move", "--to", "teyla"), "no index given"),
    (("move", "1"), "--to teyla|everywhere is required"),
])
def test_move_errors_are_exit_two_and_touch_nothing(terms, capsys, args, msg):
    before = terms.read_text()
    rc, out, err = terms_cmd(capsys, *args)
    assert rc == 2 and msg in err and terms.read_text() == before
    assert not any(v in out + err for v in NO_VALUES)


def test_move_refuses_a_symlinked_terms_file(tmp_path, terms, monkeypatch, capsys):
    link = tmp_path / "link.txt"
    link.symlink_to(terms)
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(link))
    before = terms.read_text()
    rc, _, err = terms_cmd(capsys, "move", "0", "--to", "teyla")
    assert rc == 2 and "cannot write" in err and terms.read_text() == before and link.is_symlink()


def test_move_json_holds_numbers_only(terms, capsys):
    rc, out, _ = terms_cmd(capsys, "move", "0", "--to", "teyla", "--json")
    assert rc == 0 and json.loads(out) == {"moved": [{"from": 0, "to": 2, "section": "teyla"}], "to": "teyla"}


def test_list_and_move_do_not_combine_with_suggest(terms, capsys):
    assert terms_cmd(capsys, "list", "--suggest")[0] == 2
    assert terms_cmd(capsys, "--yes")[0] == 2


def test_alias_registers_the_subcommands():
    from teyla import leak_install
    assert leak_install.alias(["leak", "terms", "list", "--json"]) == ["leak-terms", "list", "--json"]
    assert leak_install.alias(["leak", "terms", "move", "1", "--to", "teyla"])[0] == "leak-terms"


# --- --suggest writes sections -----------------------------------------------------------------

FACTS = [("Quentin Vexley", "git user.name"), ("orgquux", "bundle id organisation"), ("quxhost.test", "hostname")]


def test_suggest_puts_organisations_under_teyla_and_the_rest_everywhere(tmp_path, monkeypatch, capsys):
    from teyla import leak_install as li
    monkeypatch.setattr(li, "collect_facts", lambda root: list(FACTS))
    f = tmp_path / "t.txt"
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    rc, out, _ = terms_cmd(capsys, "--suggest")
    assert rc == 0 and "teyla" in out and "orgquux" not in out
    rc, out, _ = terms_cmd(capsys, "--suggest", "--yes", "--json")
    assert json.loads(out)["added"] == 3 and "orgquux" not in out
    lines = [ln for ln in f.read_text().splitlines() if not ln.startswith("# added")]
    assert lines == ["Quentin Vexley", "quxhost.test", "", "[teyla]", "orgquux"]
    assert [(t, s) for t, s in leak._engine().distinct_terms(f.read_text())] == [
        ("quentin vexley", "everywhere"), ("quxhost.test", "everywhere"), ("orgquux", "teyla")]


def test_suggest_appends_under_the_section_in_force_at_the_end(tmp_path, monkeypatch, capsys):
    from teyla import leak_install as li
    monkeypatch.setattr(li, "collect_facts", lambda root: list(FACTS))
    f = tmp_path / "t.txt"
    f.write_text("zebracorn\n[teyla]\nmarmotly\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    assert terms_cmd(capsys, "--suggest", "--yes")[0] == 0
    got = dict(leak._engine().distinct_terms(f.read_text()))
    assert got == {"zebracorn": "everywhere", "marmotly": "teyla", "orgquux": "teyla",
                   "quentin vexley": "everywhere", "quxhost.test": "everywhere"}
