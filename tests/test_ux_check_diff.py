"""teyla ux check --diff: generic temp git repos, no real repo, no ~/.teyla."""
from __future__ import annotations

import json
import subprocess

import pytest

from teyla import cli, ux_check, ux_check_diff


def git(d, *a):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
                   check=True, capture_output=True)


def view(body, name="HomeView"):
    return f"import SwiftUI\n\nstruct {name}: View {{\n    var body: some View {{\n{body}\n    }}\n}}\n"


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    (d / "Sources").mkdir()
    (d / "Sources/Old.swift").write_text(view("        VStack {}.padding(16)\n        VStack {}.padding(8)", "Old"))
    (d / "DESIGN.md").write_text("# Design\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "base")
    git(d, "checkout", "-qb", "feature")
    return d


def run(d, *extra):
    return cli.main(["ux", "check", str(d), "--diff", *extra])


def test_old_debt_is_not_flagged_and_exit_0(repo, capsys):
    (repo / "Sources/Old.swift").write_text(view("        VStack {}.padding(16)\n        VStack {}.padding(8)\n        Text(\"x\")", "Old"))
    git(repo, "commit", "-qam", "touch")
    assert run(repo, "main") == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "repo debt: 2 spacing literals, unchanged by this diff" in out


def test_added_literals_block_with_file_line_rule(repo, capsys):
    (repo / "Sources/New.swift").write_text(view('        Text("a").font(.system(size: 17))\n        Rectangle().fill(Color(hex: 0xFF8800))\n        VStack {}.padding(12)'))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "new")
    assert run(repo, "main") == 1
    out = capsys.readouterr().out
    assert "Sources/New.swift:5" in out and "font" in out
    assert "Sources/New.swift:6" in out and "colour" in out
    assert "Sources/New.swift:7" in out and "spacing" in out
    assert "FAIL: 3 blocking" in out and "+3 by this diff" in out


def test_only_added_lines_in_a_changed_file(repo, capsys):
    (repo / "Sources/Old.swift").write_text(view("        VStack {}.padding(16)\n        VStack {}.padding(8)\n        VStack {}.padding(24)", "Old"))
    git(repo, "commit", "-qam", "edit")
    assert run(repo, "main") == 1
    out = capsys.readouterr().out
    assert out.count("spacing  Sources/Old.swift") == 1 and "Sources/Old.swift:7" in out


def test_removing_literals_lowers_debt(repo, capsys):
    (repo / "Sources/Old.swift").write_text(view("        VStack {}.padding(Space.m)\n        VStack {}.padding(8)", "Old"))
    git(repo, "commit", "-qam", "tokens")
    assert run(repo, "main") == 0
    assert "−1 by this diff" in capsys.readouterr().out


def test_motion_warns_but_passes(repo, capsys):
    (repo / "Sources/Anim.swift").write_text(view("        Text(\"a\").animation(.easeInOut, value: 1)"))
    git(repo, "add", "-A")
    assert run(repo, "main") == 0  # uncommitted and staged work counts too
    out = capsys.readouterr().out
    assert "WARN motion" in out and "Sources/Anim.swift:5" in out and "PASS" in out


def test_untracked_files_and_token_files(repo, capsys):
    (repo / "Sources/Theme.swift").write_text(view("        VStack {}.padding(99)", "Theme"))  # a token file
    assert run(repo, "main") == 0
    (repo / "Sources/Fresh.swift").write_text(view("        VStack {}.padding(5)", "Fresh"))  # untracked
    assert run(repo, "main") == 1
    assert "Sources/Fresh.swift:5" in capsys.readouterr().out


def test_web_file_and_json(repo, capsys):
    (repo / "web").mkdir()
    (repo / "web/App.css").write_text(".a { font-size: 14px; color: #ff8800; }\n:root { --brand: #123456; }\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "css")
    assert run(repo, "main", "--json") == 1
    data = json.loads(capsys.readouterr().out)
    got = {(f["check"], f["file"], f["line"]) for f in data["repos"][0]["findings"]}
    assert got == {("font", "web/App.css", 1), ("colour", "web/App.css", 1)}


def test_default_base_is_origin_main(repo, tmp_path, capsys):
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    (repo / "Sources/New.swift").write_text(view("        VStack {}.padding(12)"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "new")
    assert cli.main(["ux", "check", str(repo), "--diff"]) == 1


def test_bad_base_exits_2(repo, capsys):
    assert run(repo, "nope-branch") == 2
    assert "not a commit" in capsys.readouterr().out


def test_hint_on_a_branch_that_differs_only(repo, capsys):
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    assert cli.main(["ux", "check", str(repo)]) == 0
    assert "--diff" not in capsys.readouterr().out
    (repo / "Sources/New.swift").write_text(view("        VStack {}.padding(12)"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "new")
    assert cli.main(["ux", "check", str(repo)]) == 0  # the repo-wide exit code is unchanged
    assert "teyla ux check --diff" in capsys.readouterr().out


def test_help_documents_blocking_rules():
    assert "blocking" in ux_check.DIFF_HELP and "font, colour or spacing" in ux_check.DIFF_HELP


def test_non_ascii_file_name_is_scanned(repo, capsys):
    (repo / "Sources/Écran.swift").write_text(view("        VStack {}.padding(12)"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "accent")
    assert run(repo, "main") == 1
