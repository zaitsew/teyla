"""teyla docs check: synthetic repos in tmp dirs. Nothing here reads a real repo or ~/.teyla."""
from __future__ import annotations

import json

import pytest

from teyla import cli, config, docs_check

GOOD = """# Widget

Widget turns a folder of receipts into a monthly expense sheet. It is for freelancers who keep
paper receipts and want the sheet without typing.

```
git clone https://example.invalid/widget
cd widget
./check.sh
```

## Usage

Run `widget scan`.
"""


def repo(tmp_path, readme=GOOD, docs=None, name="proj", pyproject=None):
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    if readme is not None:
        (d / "README.md").write_text(readme)
    for rel, text in (docs or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if pyproject:
        (d / "pyproject.toml").write_text(pyproject)
    return d


def checks(report):
    return {(f["check"], f["severity"]) for f in report["findings"]}


def test_good_readme_has_no_findings(tmp_path):
    assert docs_check.check_repo(repo(tmp_path))["findings"] == []


def test_placeholder_opening_is_a_fix(tmp_path):
    text = """# widget

One line: what widget does, for the person opening this repo cold.

## Quick start

```
./check.sh
```

- Does: (fill in — the one or two things this is actually for)
"""
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    assert ("opening", "FIX") in checks(r)
    assert ("placeholder", "WARN") in checks(r)


def test_scaffold_output_is_flagged(tmp_path):
    from teyla import scaffold
    dest = tmp_path / "fresh"
    scaffold.scaffold(str(dest), name="fresh", kind="cli", license="none", owner="Ada")
    (dest / ".git").mkdir(exist_ok=True)
    r = docs_check.check_repo(dest)
    assert ("opening", "FIX") in checks(r)


def test_missing_readme_is_a_fix(tmp_path):
    r = docs_check.check_repo(repo(tmp_path, readme=None))
    assert checks(r) == {("opening", "FIX")}


def test_opening_skips_badges_images_and_comments(tmp_path):
    text = """# Widget

<!-- generated -->
[![ci](https://example.invalid/b.svg)](https://example.invalid)
![logo](logo.png)
<p align="center"></p>

Widget sorts receipts.

```sh
widget scan
```
"""
    assert docs_check.check_repo(repo(tmp_path, readme=text))["findings"] == []


def test_heading_before_prose_is_a_fix(tmp_path):
    text = "# Widget\n\n## Install\n\n```\nmake\n```\n"
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    assert ("opening", "FIX") in checks(r)


def test_long_opening_is_a_warn(tmp_path):
    text = "# Widget\n\n" + " ".join(["word"] * 70) + "\n\n```\nmake\n```\n"
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    assert ("opening", "WARN") in checks(r)
    assert ("opening", "FIX") not in checks(r)


def test_no_quick_start_in_first_80_lines(tmp_path):
    filler = "\n".join(f"Line {i} of plain prose." for i in range(90))
    text = f"# Widget\n\nWidget sorts receipts.\n\n{filler}\n\n```\nmake\n```\n"
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    assert ("quick-start", "WARN") in checks(r)


def test_non_shell_fence_is_not_a_quick_start(tmp_path):
    text = "# Widget\n\nWidget sorts receipts.\n\n```json\n{}\n```\n"
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    assert ("quick-start", "WARN") in checks(r)


def test_long_readme_names_the_largest_section(tmp_path):
    big = " ".join(["filler"] * 2600)
    text = GOOD + f"\n## Reference\n\n{big}\n"
    r = docs_check.check_repo(repo(tmp_path, readme=text))
    f = [x for x in r["findings"] if x["check"] == "length"][0]
    assert f["severity"] == "WARN"
    assert '"Reference" (2,6' in f["message"]
    assert "docs/" in f["fix"]


def test_dead_command_only_in_teyla_repos(tmp_path):
    text = GOOD + "\nRun `teyla nonesuch` or `teyla monitor`.\n\n```\nteyla reel bogus\nteyla load\n```\n"
    generic = repo(tmp_path, readme=text, name="generic")
    assert not any(f["check"] == "dead-command" for f in docs_check.check_repo(generic)["findings"])

    own = repo(tmp_path, readme=text, name="own", pyproject='[project]\nname = "x"\n[project.scripts]\nteyla = "teyla.cli:main"\n')
    msgs = [f["message"] for f in docs_check.check_repo(own)["findings"] if f["check"] == "dead-command"]
    assert any("teyla nonesuch" in m for m in msgs)
    assert any("teyla reel bogus" in m for m in msgs)
    assert not any("monitor" in m or "teyla load" in m for m in msgs)


def test_dead_command_ignores_prose_and_paths(tmp_path):
    text = GOOD + "\nSee ~/.teyla/config.toml and teyla.toml; teyla is local-first. The `teyla.toml` file.\n"
    own = repo(tmp_path, readme=text, name="own", pyproject='[project.scripts]\nteyla = "x:main"\n')
    assert not any(f["check"] == "dead-command" for f in docs_check.check_repo(own)["findings"])


def test_roadmap_may_name_commands_that_do_not_exist_yet(tmp_path):
    own = repo(tmp_path, name="own", pyproject='[project.scripts]\nteyla = "x:main"\n',
               docs={"docs/ROADMAP.md": "# Roadmap\n\nNext: `teyla futurecmd`.\n"})
    assert not any(f["check"] == "dead-command" for f in docs_check.check_repo(own)["findings"])


NARRATIVE_DOC = """# Sync

How sync works.

On 2026-09-30 we decided to batch uploads.
The cache used to hold a week of data (2026-10-02).
Previously the sync ran hourly.
As of rev. 3 it runs daily.
The queue was changed to FIFO.
Sync reads the config file.
"""

STATE_DOC = "# Sync\n\nSync reads the config file.\nIt uploads in batches.\nIt runs daily.\nIt retries three times.\n"


def test_decision_history_is_flagged(tmp_path):
    r = docs_check.check_repo(repo(tmp_path, docs={"docs/SYNC.md": NARRATIVE_DOC, "docs/STATE.md": STATE_DOC}))
    hist = [f for f in r["findings"] if f["check"] == "history"]
    assert [f["file"] for f in hist] == ["docs/SYNC.md"]
    assert "docs/decisions/" in hist[0]["fix"]


def test_history_dirs_and_changelog_are_not_read(tmp_path):
    r = docs_check.check_repo(repo(tmp_path, docs={
        "docs/decisions/0001.md": NARRATIVE_DOC, "docs/reviews/r.md": NARRATIVE_DOC,
        "docs/case-studies/c.md": NARRATIVE_DOC, "docs/CHANGELOG.md": NARRATIVE_DOC}))
    assert r["findings"] == []


def test_status_drift_between_doc_and_readme(tmp_path):
    readme = GOOD + "\nSee [the reel docs](docs/reel.md) for video output.\n"
    doc = "# Reel\n\nTurns a session into a video.\n\nStatus: v0 spec, 2026-10-16.\n"
    r = docs_check.check_repo(repo(tmp_path, readme=readme, docs={"docs/reel.md": doc}))
    assert ("status-drift", "WARN") in checks(r)

    labelled = GOOD + "\nSee [the reel spec](docs/reel.md) (draft).\n"
    assert ("status-drift", "WARN") not in checks(docs_check.check_repo(repo(tmp_path, readme=labelled, docs={"docs/reel.md": doc}, name="p2")))

    shipped = "# Reel\n\nTurns a session into a video.\n\nStatus: shipped in 0.25.0.\n"
    assert ("status-drift", "WARN") not in checks(docs_check.check_repo(repo(tmp_path, readme=readme, docs={"docs/reel.md": shipped}, name="p3")))


def test_status_drift_through_the_commands_page(tmp_path):
    doc = "# Reel\n\nTurns a session into a video.\n\nStatus: draft.\n"
    cmds = "# Commands\n\nSee [`docs/reel.md`](reel.md).\n"
    r = docs_check.check_repo(repo(tmp_path, docs={"docs/reel.md": doc, "docs/COMMANDS.md": cmds}))
    assert ("status-drift", "WARN") in checks(r)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "TEYLA_DIR", h / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", h / ".teyla" / "config.toml")
    code = tmp_path / "code"
    code.mkdir()
    (h / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\n')
    return code


def test_cli_json_strict_and_all(home, capsys):
    repo(home, name="good")
    repo(home, readme="# Bad\n\n## Install\n", name="bad")
    assert cli.main(["docs", "check", "--all", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["FIX"] == 1
    assert {r["repo"] for r in out["repos"]} == {"good", "bad"}

    assert cli.main(["docs", "check", "good", "--strict"]) == 0
    capsys.readouterr()
    assert cli.main(["docs", "check", "bad", "--strict"]) == 1
    text = capsys.readouterr().out
    assert "FIX" in text and "fix:" in text and "1 repo(s): 1 FIX" in text


def test_cli_defaults_to_the_current_git_repo(home, monkeypatch, capsys):
    d = repo(home, name="here")
    monkeypatch.chdir(d)
    assert cli.main(["docs", "check"]) == 0
    assert "here: ok" in capsys.readouterr().out


def test_cli_unknown_path(home, capsys):
    assert cli.main(["docs", "check", "/nonexistent/dir"]) == 2


def test_teyla_readme_command_links(capsys):
    """This repo's own docs name only commands the parser has."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        pytest.skip("not a source checkout")
    r = docs_check.check_repo(root)
    assert [f for f in r["findings"] if f["check"] in ("dead-command", "status-drift")] == []


def test_four_backtick_fence_holds_inner_triple_backticks():
    from teyla.docs_check import fence_state
    lines = ["````md", "```bash", "teyla nope", "```", "````", "prose"]
    st = fence_state(lines)
    assert st[2] == "md" and st[3] == "md"
    assert st[4] == "<marker>" and st[5] is None
