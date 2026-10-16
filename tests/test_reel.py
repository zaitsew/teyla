"""teyla reel: extraction, redaction, the Story, selection, and list/story/check.

Every transcript here is synthetic and tiny. Secret-shaped strings are built at run time (a
literal would trip scripts/leak_check.py and, worse, look like a real key), and private terms
come from a temp file named by $TEYLA_PRIVATE_TERMS, never from the owner's real list.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess

import pytest

from teyla import cli
from teyla.reel import cli as cli_mod
from teyla.adapters import claude_code, codex
from teyla.reel import cards, commands, events as E, gitlog, redact, select, story as S

BASE = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
SID = "5e55a0f1-0000-4000-8000-000000000001"


def iso(t: float) -> str:
    return (BASE + dt.timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# secret-shaped strings, assembled at run time
ANT_KEY = "sk" + "-ant-" + "a1b2c3d4e5f6g7h8i9j0k1l2"
GH_TOKEN = "gh" + "p_" + "Q" * 30
HEX_RUN = "9f" * 20
NAME_VAL = "STRIPE" + "_SECRET" + "_KEY=" + "abc123def456"
USER = "jd" + "oe"
HOME_PATH = f"/Users/{USER}/Documents/notes.txt"


@pytest.fixture(autouse=True)
def private_terms(tmp_path, monkeypatch):
    """A term list of our own, a login name of our own, and no look at the real ones."""
    terms = tmp_path / "terms.txt"
    terms.write_text("# test terms\nzebracorp\nsecret-project\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    monkeypatch.setenv("HOME", str(tmp_path / "home" / USER))
    monkeypatch.setenv("LOGNAME", USER)
    monkeypatch.setenv("USER", USER)
    return terms


def red(*roots, terms=True):
    return redact.Redactor(list(roots), home=os.path.expanduser("~"), terms=terms)


# --- redaction ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    f"key is {ANT_KEY}",
    f"token {GH_TOKEN} here",
    f"checksum {HEX_RUN}",
    NAME_VAL,
    "api_key=abcdefgh",
    "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0In0" + ".c2lnbmF0dXJl",
    "Aa1" + "Bb2" * 12,                                  # a long mixed-class run
])
def test_secret_shapes_drop_the_beat(text):
    r = red()
    out = r.clean(text)
    assert out.fatal and out.text == ""
    assert r.dropped["secret"] == 1


def test_private_term_drops_the_beat_and_case_does_not_matter():
    r = red()
    assert r.clean("deploy ZebraCorp billing").fatal
    assert r.clean("the secret-project plan").fatal
    assert r.dropped["private-term"] == 2
    assert not r.clean("zebracorporation is not the term").fatal   # whole-word match only


def test_login_and_home_name_are_private_even_without_a_term_list():
    r = red(terms=False)
    assert r.clean(f"hello {USER}").fatal


def test_email_and_phone_drop_the_line_not_the_beat():
    r = red()
    for s in ("mail someone@example.com about it", "call +34 600 123 456 now", "call 600-123-4567"):
        o = r.clean(s)
        assert o.skip and not o.fatal and o.text == ""
    assert r.dropped["email"] == 3


def test_paths_inside_the_repo_become_relative_others_become_basename(tmp_path):
    repo = str(tmp_path / "work" / "demo")
    r = red(repo)
    assert r.clean(f"edit {repo}/src/app.py now").text == "edit src/app.py now"
    out = r.clean(f"open {HOME_PATH}").text
    assert out == "open …/notes.txt"
    assert USER not in out and "/Users" not in out
    assert r.clean("see ~/ops/bin/tool").text == "see …/tool"
    assert r.clean(f"cd /Users/{USER}").text == "cd …/~"          # the home directory itself
    assert r.dropped["path"] == 4


def test_worktree_and_checkout_paths_are_made_relative():
    home = os.path.expanduser("~")
    r = red()
    assert r.path(f"{home}/.worktrees/demo/feat-x/src/a.py") == "src/a.py"
    assert r.path(f"{home}/repos/other/lib/b.py") == "lib/b.py"
    assert r.path(f"{home}/.codex/worktrees/abc/demo/c.swift") == "c.swift"


def test_urls_reduce_to_the_host_and_pull_requests_to_a_number():
    r = red()
    assert r.clean("docs at https://docs.example.org/guide/start?x=1 ok").text == "docs at docs.example.org ok"
    assert r.clean("merged https://github.com/acme/demo/pull/42").text == "merged #42"
    assert r.clean("https://user:pw@host.example.net:8080/p").text == "host.example.net"


def test_length_is_cut_at_a_word_boundary_with_an_ellipsis():
    r = red()
    out = r.clean("alpha beta gamma delta epsilon", 15)
    assert out.text == "alpha beta…" and len(out.text) <= 15
    assert r.dropped["too-long"] == 1
    assert redact.cut("short", 10) == "short"
    assert redact.cut("x" * 30, 10) == "x" * 9 + "…"             # one token longer than the slot
    assert redact.shorten_path("src/teyla/reel/select.py", 16) == "…/reel/select.py"


def test_control_and_bidi_characters_are_removed():
    assert red().clean("a‮b\x07c​d").text == "a b c d"


def test_repo_name_that_is_a_private_term():
    assert red().check_repo("zebracorp") and not red().check_repo("demo")
    r = red()
    r.allow("zebracorp")
    assert not r.check_repo("zebracorp")


# --- command reading ------------------------------------------------------------------------

@pytest.mark.parametrize("cmd, runner", [
    ("python -m pytest -q", "pytest"),
    ("PYTHONPATH=src .venv/bin/python -m pytest -q 2>&1 | tail -5", "pytest"),
    ("cd repo && ./check.sh", "check.sh"),
    ("uv run pytest tests/", "pytest"),
    ("swift test --parallel", "swift test"),
    ("xcodebuild -scheme App -destination 'x' test", "xcodebuild test"),
    ("npm run test", "npm test"),
    ("bun test", "bun test"),
    ("cargo test --all", "cargo test"),
    ("go test ./...", "go test"),
    ("bash -c 'cd x && pytest -q'", "pytest"),
])
def test_test_runs_are_recognised(cmd, runner):
    assert commands.test_runner(cmd) == runner


@pytest.mark.parametrize("cmd", [
    'git commit -m "pytest passes now"',
    "grep -rn pytest src",
    "echo check.sh",
    "cat <<'EOF'\npytest\nEOF",
    "ls tests",
])
def test_a_mention_is_not_a_test_run(cmd):
    assert commands.test_runner(cmd) is None


def test_commit_pr_and_review_detection():
    assert commands.is_commit('git commit -m "x"') and commands.is_commit("cd r && git -C r commit -am y")
    assert not commands.is_commit("git commit --dry-run") and not commands.is_commit("echo git commit")
    assert commands.pr_action("gh pr create --title t") == "create"
    assert commands.pr_action("gh pr merge 7 --merge") == "merge"
    assert commands.review_tool("~/ops/bin/codex-review --high") == "codex-review"
    assert commands.review_tool("cat codex-review") is None


def test_reading_what_commands_printed():
    out = "[feat/x 1a2b3c4] Add the thing\n 2 files changed\n[main (root-commit) 9999999] first"
    assert commands.commits_in(out) == [("1a2b3c4", "Add the thing"), ("9999999", "first")]
    assert commands.pr_title('gh pr create --title "Add the thing" --body x') == "Add the thing"
    assert commands.pr_title("gh pr create -t 'Quick fix'") == "Quick fix"
    assert commands.pr_number("gh pr create", "https://github.com/a/b/pull/12\n") == 12
    assert commands.pr_number("gh pr merge 13 --merge", "") == 13
    assert commands.pr_merge_title("✓ Merged pull request a/b#13 (Add the thing)") == "Add the thing"
    assert commands.review_counts("codex-review: P1=1 P2=3 tokens=9") == (1, 3)
    assert commands.review_counts("P1 a.py:3 — bug\nP2 b.py:4 — meh\n") == (1, 1)
    assert commands.review_counts("nothing here") is None


def test_test_outcomes():
    assert commands.test_outcome("pytest", "===== 3 failed, 139 passed in 2s =====", 1, True) == (False, 139, 3)
    assert commands.test_outcome("pytest", "142 passed in 12.30s", 0, False) == (True, 142, None)
    assert commands.test_outcome("pytest", "1 passed, 2 errors in 1s", 1, True)[0] is False
    assert commands.test_outcome("swift test", "Executed 12 tests, with 0 failures (0 unexpected)", 0, False) == (True, 12, 0)
    assert commands.test_outcome("xcodebuild test", "** TEST FAILED **", 65, True)[0] is False
    assert commands.test_outcome("xcodebuild test", "** TEST SUCCEEDED **", 0, False)[0] is True
    assert commands.test_outcome("cargo test", "test result: ok. 5 passed; 0 failed;\ntest result: ok. 2 passed; 0 failed;", 0, False) == (True, 7, 0)
    assert commands.test_outcome("npm test", "Tests:       1 failed, 5 passed, 6 total", 1, True) == (False, 5, 1)
    assert commands.test_outcome("check.sh", "leak_check: 2 findings", 1, True) == (False, None, None)
    assert commands.test_outcome("go test", "ok  \tpkg\t0.1s", None, False)[0] is True


# --- synthetic transcripts ------------------------------------------------------------------

class Log:
    """Builds a Claude Code transcript."""

    def __init__(self, cwd):
        self.cwd, self.rows, self.n = str(cwd), [], 0

    def _row(self, t, type_, message, **kw):
        self.rows.append({"type": type_, "timestamp": iso(t), "cwd": self.cwd, "sessionId": SID, "message": message, **kw})

    def user(self, t, text):
        self._row(t, "user", {"role": "user", "content": text})

    def tool(self, t, name, inp, result="", error=False):
        self.n += 1
        tid = f"tu{self.n}"
        self._row(t, "assistant", {"role": "assistant", "model": "claude-sonnet-5-5", "id": f"m{self.n}",
                                   "usage": {"input_tokens": 10, "output_tokens": 5},
                                   "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]})
        self._row(t + 1, "user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result,
                                                               "is_error": error}]})

    def write(self, root, slug="-tmp-demo", sid=SID):
        f = root / slug / f"{sid}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n")
        return f


def git(cwd, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_COMMITTER_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_EMAIL="t@example.com")
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = iso(when)
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repos" / "demo"
    d.mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.com")
    (d / "README.md").write_text("demo\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init", when=-86400)
    return d


def shipping_log(repo) -> Log:
    """A session that asks, spawns a lane, edits, fails a test, fixes, passes, commits, opens and merges a PR."""
    log = Log(repo)
    src = f"{repo}/src/http.py"
    log.user(0, "Add a retry wrapper to the fetch helper. Then ship it.")
    log.tool(10, "Agent", {"description": "Survey the HTTP helpers", "subagent_type": "scout", "model": "haiku", "prompt": "read"}, "ok")
    log.tool(20, "Edit", {"file_path": src, "old_string": "def fetch(url):\n    return get(url)\n",
                          "new_string": "def fetch(url, retries=3):\n    for _ in range(retries):\n        try:\n            return get(url)\n        except Timeout:\n            continue\n"},
             "updated")
    log.tool(30, "Write", {"file_path": f"{repo}/tests/test_http.py",
                           "content": "import pytest\n\n\ndef test_retry():\n    assert fetch('x', retries=2)\n"}, "created")
    log.tool(40, "Bash", {"command": "python -m pytest -q"}, "FAILED tests/test_http.py::test_retry\n1 failed, 4 passed in 0.30s", error=True)
    log.tool(50, "Edit", {"file_path": src, "old_string": "continue\n", "new_string": "continue\n    raise Timeout\n"}, "updated")
    log.tool(60, "Bash", {"command": ".venv/bin/python -m pytest -q"}, "5 passed in 0.40s")
    log.tool(70, "Bash", {"command": 'git commit -am "Add retry to fetch"'}, "[feat/retry abc1234] Add retry to fetch\n 2 files changed")
    log.tool(80, "Bash", {"command": 'gh pr create --title "Add retry to fetch" --body x'}, "https://github.com/acme/demo/pull/7\n")
    log.tool(90, "Bash", {"command": "~/ops/bin/codex-review"}, "codex-review: P1=0 P2=1 tokens=1,000 effort=medium 20s")
    log.tool(100, "Bash", {"command": "gh pr merge 7 --merge"}, "✓ Merged pull request acme/demo#7 (Add retry to fetch)")
    return log


@pytest.fixture
def claude_root(tmp_path, monkeypatch):
    root = tmp_path / "claude" / "projects"
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(root))
    return root


# --- events ---------------------------------------------------------------------------------

def test_claude_events(repo, claude_root):
    f = shipping_log(repo).write(claude_root)
    ev = E.finish(E.read_claude(str(f)), iso(0))
    kinds = [e.kind for e in ev]
    assert kinds == ["ask", "agent", "edit", "edit", "command", "edit", "command", "command", "command", "command", "command"]
    assert ev[0].text.startswith("Add a retry wrapper")
    assert (ev[1].text, ev[1].tool, ev[1].model) == ("Survey the HTTP helpers", "scout", "haiku")
    assert ev[3].new_file and ev[3].path.endswith("test_http.py")
    fail = ev[4]
    assert fail.failed and fail.exit_code == 1 and "1 failed" in fail.output
    assert [round(e.t) for e in ev][:3] == [0, 10, 20]


def test_claude_ask_skips_system_reminders_and_retries(tmp_path):
    log = Log(tmp_path)
    log.user(0, "<system-reminder>ignore me</system-reminder>")
    log.user(5, "continue")
    log.user(9, "Real ask<system-reminder>and a reminder</system-reminder>")
    log.user(12, "A later message")
    f = log.write(tmp_path)
    asks = [e for e in E.read_claude(str(f)) if e.kind == "ask"]
    assert [a.text for a in asks] == ["Real ask"]


def codex_rollout(tmp_path, cwd, lines):
    f = tmp_path / "codex" / "sessions" / "2026" / "01" / "01" / f"rollout-2026-01-01T12-00-00-{SID}.jsonl"
    f.parent.mkdir(parents=True)
    rows = [{"type": "session_meta", "timestamp": iso(0), "payload": {"id": SID, "cwd": str(cwd), "source": "vscode"}}] + lines
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


def item(t, payload):
    return {"type": "response_item", "timestamp": iso(t), "payload": payload}


def test_codex_events_all_three_tool_shapes(tmp_path):
    patch = "*** Begin Patch\n*** Update File: /w/demo/a.py\n@@\n keep\n-old line\n+new line\n*** Add File: /w/demo/b.py\n+one\n+two\n*** End Patch"
    js = ('const r = await tools.exec_command({cmd:"cd /w/demo && python -m pytest -q",max_output_tokens:5000});\n'
          'tools.apply_patch("*** Begin Patch\\n*** Update File: /w/demo/c.py\\n@@\\n-x\\n+y\\n*** End Patch");')
    f = codex_rollout(tmp_path, "/w/demo", [
        item(1, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]}),
        item(2, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /w/demo\n<INSTRUCTIONS>be nice</INSTRUCTIONS>"}]}),
        item(3, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the parser"}]}),
        item(4, {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": json.dumps({"command": ["bash", "-lc", "pytest -q"]})}),
        item(5, {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": "3 passed in 1s", "metadata": {"exit_code": 0}})}),
        item(6, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c2", "input": patch}),
        item(7, {"type": "custom_tool_call", "name": "exec", "call_id": "c3", "input": js}),
        item(8, {"type": "custom_tool_call_output", "call_id": "c3",
                 "output": [{"type": "input_text", "text": "Script completed\nOutput:\n"},
                            {"type": "input_text", "text": json.dumps({"chunk_id": "x", "exit_code": 1, "output": "2 failed, 1 passed in 1s"})}]}),
        item(9, {"type": "function_call", "name": "spawn_agent", "call_id": "c4", "arguments": json.dumps({"task_name": "ux_audit", "agent_type": "scout"})}),
    ])
    ev = E.finish(E.read_codex(str(f)), iso(0))
    assert [e.kind for e in ev] == ["ask", "command", "edit", "edit", "command", "edit", "agent"]
    assert ev[0].text == "Fix the parser"
    assert ev[1].text == "pytest -q" and ev[1].exit_code == 0 and "3 passed" in ev[1].output
    a, b = ev[2], ev[3]
    assert a.path == "/w/demo/a.py" and a.hunks == [("keep\nold line", "keep\nnew line")]
    assert b.new_file and b.hunks == [("", "one\ntwo")]
    assert ev[5].path == "/w/demo/c.py"
    assert ev[4].text == "cd /w/demo && python -m pytest -q" and ev[4].exit_code == 1 and ev[4].failed
    assert ev[6].text == "ux audit" and ev[6].tool == "scout"


# --- the Story ------------------------------------------------------------------------------

def story_of(f, **kw):
    info = E.info_of(claude_code.parse(str(f)), "claude")
    return S.build(info, E.events_of(info), **kw)


def test_story_beats_and_totals_from_a_transcript(repo, claude_root):
    f = shipping_log(repo).write(claude_root)
    st = story_of(f, git=False)
    assert st.harness == "claude" and st.repo == "demo" and st.id == SID
    kinds = [b.kind for b in st.beats]
    assert kinds[0] == "ask" and st.beats[0].headline == "The ask"
    assert " ".join(st.beats[0].lines).startswith("Add a retry wrapper to the fetch helper.")
    for k in ("lane", "edit", "test", "commit", "pr", "review"):
        assert k in kinds
    by = {b.kind: b for b in st.beats}
    assert by["lane"].headline == "Survey the HTTP helpers" and by["lane"].lines == ["scout · haiku"]
    assert by["commit"].headline == "Add retry to fetch" and by["commit"].lines == ["abc1234"]
    assert by["review"].headline == "codex-review: 0 P1, 1 P2"
    tests = [b for b in st.beats if b.kind == "test"]
    assert [b.headline for b in tests] == ["1 failed, 4 passed", "5 tests passed"]
    prs = [b.headline for b in st.beats if b.kind == "pr"]
    assert prs == ["PR #7 opened", "PR #7 merged"]
    t = st.totals
    assert (t.commits, t.prs_opened, t.prs_merged, t.lanes, t.test_runs) == (1, 1, 1, 1, 2)
    assert (t.tests_passed, t.tests_failed) == (5, 0)
    assert t.files_changed == 2 and t.lines_added > 0 and t.wall_clock == 101
    assert [b.t for b in st.beats] == sorted(b.t for b in st.beats)


def test_edit_beat_shows_a_repo_relative_path_counts_and_a_dedented_diff(repo, claude_root):
    f = shipping_log(repo).write(claude_root)
    st = story_of(f, git=False)
    edit = next(b for b in st.beats if b.kind == "edit" and b.headline == "src/http.py")
    assert edit.lines[0].startswith("+") and "−" in edit.lines[0]
    assert all(ln[0] in "+- " for ln in edit.diff) and len(edit.diff) <= S.DIFF_MAX
    assert "+def fetch(url, retries=3):" in edit.diff       # dedented: no leading indent left
    assert all(len(ln) <= S.LINE_MAX for ln in edit.diff)


def test_every_limit_of_the_spec_holds(repo, claude_root):
    log = shipping_log(repo)
    log.tool(110, "Edit", {"file_path": f"{repo}/src/long.py", "old_string": "a\n",
                           "new_string": "\n".join("x" * 80 + str(i) for i in range(30)) + "\n"}, "ok")
    log.tool(120, "Bash", {"command": 'git commit -m "' + "word " * 40 + '"'}, "[main fedcba9] " + "word " * 40)
    st = story_of(log.write(claude_root), git=False, seconds=60)
    assert st.problems() == []
    for b in st.beats:
        assert len(b.headline) <= 48 and len(b.lines) <= 8 and all(len(x) <= 34 for x in b.lines)
        assert b.diff is None or (len(b.diff) <= 10 and all(len(x) <= 34 for x in b.diff))


def test_story_json_round_trips(repo, claude_root):
    st = story_of(shipping_log(repo).write(claude_root), git=False)
    again = S.Story.from_dict(json.loads(json.dumps(st.to_dict())))
    assert again.to_dict() == st.to_dict()
    assert set(st.to_dict()) >= {"id", "harness", "repo", "started", "ended", "ask", "title", "beats", "totals"}


def test_ask_override_is_used_after_redaction(repo, claude_root):
    f = shipping_log(repo).write(claude_root)
    st = story_of(f, git=False, ask="Make the fetch helper retry. Ping someone@example.com when done.")
    assert st.ask == "Make the fetch helper retry."
    assert st.dropped["email"] == 1


def test_ask_drops_a_sentence_whole_and_never_strands_half_of_one(repo, claude_root):
    f = shipping_log(repo).write(claude_root)
    st = story_of(f, git=False, ask="Make the fetch helper retry.\nNobody\nlikes zebracorp billing. Keep tests green.")
    assert st.ask == "Make the fetch helper retry. Keep tests green."
    long = "Make the fetch helper retry. " + "Then check the cache layer carefully. " * 12 + "Nobody"
    st = story_of(f, git=False, ask=long)
    assert "Nobody" not in st.ask and st.ask.endswith(("…", "."))


def test_planted_private_data_never_reaches_the_story_or_reel_txt(repo, claude_root):
    log = Log(repo)
    log.user(0, f"Ship zebracorp billing. Use {ANT_KEY} for the call. Also fix the fetch helper.")
    log.tool(10, "Edit", {"file_path": f"{repo}/src/keys.py", "old_string": "x = 1\n", "new_string": f"KEY = '{GH_TOKEN}'\n"}, "ok")
    log.tool(20, "Edit", {"file_path": HOME_PATH, "old_string": "a\n", "new_string": "b\n"}, "ok")
    log.tool(30, "Edit", {"file_path": f"{repo}/src/ok.py", "old_string": "a\n", "new_string": "b = 2\n"}, "ok")
    log.tool(40, "Edit", {"file_path": f"{repo}/src/mail.py", "old_string": "a\n", "new_string": "to = 'someone@example.com'\nb = 1\n"}, "ok")
    log.tool(50, "Bash", {"command": 'git commit -m "zebracorp invoices"'}, "[main aaaaaaa] zebracorp invoices")
    log.tool(60, "Bash", {"command": 'git commit -m "Fix fetch"'}, f"[main bbbbbbb] Fix fetch {HEX_RUN}")
    log.tool(70, "Bash", {"command": 'git commit -m "Tidy"'}, "[main ccccccc] Tidy")
    log.tool(80, "Bash", {"command": "make build"}, "ok")
    log.tool(90, "Agent", {"description": f"look at {HOME_PATH} and https://secret-project.internal/x", "subagent_type": "scout"}, "ok")
    st = story_of(log.write(claude_root), git=False, seconds=90)
    blob = json.dumps(st.to_dict()) + "\n".join(cards.rendered_strings(st))
    for planted in (ANT_KEY, GH_TOKEN, HEX_RUN, "zebracorp", "secret-project", "someone@example.com", USER, "/Users", "/home/"):
        assert planted not in blob, planted
    heads = [b.headline for b in st.beats]
    assert "Tidy" in heads and "zebracorp invoices" not in heads and not any("Fix fetch" in h for h in heads)
    assert not any(b.headline == "src/keys.py" for b in st.beats)           # a secret in the diff drops the edit
    mail = next(b for b in st.beats if b.headline == "src/mail.py")         # an e-mail drops only its line
    assert "+b = 1" in mail.diff and not any("example.com" in ln for ln in mail.diff)
    assert st.dropped["secret"] >= 2 and st.dropped["private-term"] >= 2 and st.dropped["email"] >= 1
    assert st.dropped["path"] >= 1
    assert "Ship" not in st.ask and "fetch helper" in st.ask                 # the sentences with a term or a key are gone


def test_private_repo_is_refused_unless_allowed(tmp_path, claude_root):
    d = tmp_path / "repos" / "zebracorp"
    d.mkdir(parents=True)
    git(d, "init", "-q")
    log = Log(d)
    log.user(0, "Do a thing")
    log.tool(5, "Bash", {"command": "make"}, "ok")
    f = log.write(claude_root)
    with pytest.raises(S.PrivateRepo):
        story_of(f)
    st = story_of(f, allow_repo=True)
    assert st.repo == "zebracorp"


def test_edits_outside_a_checkout_and_in_harness_dirs_are_not_shown(repo, claude_root):
    log = Log(repo)
    log.user(0, "Notes")
    log.tool(5, "Write", {"file_path": f"{os.path.expanduser('~')}/.claude/projects/x/memory/note.md", "content": "private memory\n"}, "ok")
    log.tool(6, "Write", {"file_path": "/private/tmp/scratch/brief.md", "content": "a brief\n"}, "ok")
    log.tool(7, "Write", {"file_path": f"{repo}/docs/note.md", "content": "public note\n"}, "ok")
    st = story_of(log.write(claude_root), git=False)
    assert [b.headline for b in st.beats if b.kind == "edit"] == ["docs/note.md"]


def test_git_history_supplies_commits_and_line_counts(repo, claude_root):
    log = Log(repo)
    log.user(0, "Add things")
    log.tool(5, "Bash", {"command": "make"}, "ok")
    log.tool(3000, "Bash", {"command": "make"}, "ok")
    (repo / "a.txt").write_text("1\n2\n3\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Add a.txt", when=600)
    (repo / "a.txt").write_text("1\n2\n")
    (repo / "b.txt").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Trim a, add b", when=1200)
    git(repo, "commit", "-q", "--allow-empty", "-m", "Outside the window", when=999999)
    st = story_of(log.write(claude_root))
    t = st.totals
    assert (t.commits, t.files_changed, t.lines_added, t.lines_removed) == (2, 2, 4, 1)
    commits = [b for b in st.beats if b.kind == "commit"]
    assert [b.headline for b in commits] == ["Add a.txt", "Trim a, add b"]
    assert commits[0].lines[1] == "+3 −0 · 1 file"
    assert round(commits[0].t) == 600
    info = gitlog.commits(str(repo), dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
                          dt.datetime(2026, 1, 1, 13, 0, tzinfo=dt.timezone.utc))
    assert [c.subject for c in info] == ["Add a.txt", "Trim a, add b"]


def test_a_session_outside_a_repository_has_no_git_numbers(tmp_path, claude_root):
    plain = tmp_path / "plain"
    plain.mkdir()
    log = Log(plain)
    log.user(0, "Hello")
    log.tool(5, "Edit", {"file_path": f"{plain}/x.py", "old_string": "a\n", "new_string": "b\nc\n"}, "ok")
    st = story_of(log.write(claude_root))
    assert st.repo == "plain" and st.totals.commits == 0
    assert (st.totals.lines_added, st.totals.files_changed) == (2, 1)       # from the transcript instead


def test_codex_story(tmp_path, monkeypatch):
    cwd = tmp_path / "repos" / "demo"
    cwd.mkdir(parents=True)
    git(cwd, "init", "-q")
    f = codex_rollout(tmp_path, cwd, [
        item(1, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the parser"}]}),
        item(2, {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": json.dumps({"command": ["bash", "-lc", "swift test"]})}),
        item(3, {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": "Executed 12 tests, with 0 failures", "metadata": {"exit_code": 0}})}),
        item(4, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c2",
                 "input": f"*** Begin Patch\n*** Update File: {cwd}/Parser.swift\n@@\n-let a = 1\n+let a = 2\n*** End Patch"}),
        item(5, {"type": "function_call", "name": "shell", "call_id": "c3", "arguments": json.dumps({"command": ["bash", "-lc", 'git commit -am "Fix parser"']})}),
        item(6, {"type": "function_call_output", "call_id": "c3", "output": json.dumps({"output": "[main 1234567] Fix parser", "metadata": {"exit_code": 0}})}),
    ])
    s = codex.parse(str(f))
    info = E.info_of(s, "codex")
    st = S.build(info, E.events_of(info), git=False)
    assert st.harness == "codex" and st.ask == "Fix the parser"
    assert [b.kind for b in st.beats] == ["ask", "test", "edit", "commit"]
    assert st.beats[1].headline == "12 tests passed" and st.beats[2].headline == "Parser.swift"
    assert st.beats[2].diff == ["-let a = 1", "+let a = 2"]


# --- selection ------------------------------------------------------------------------------

def cand(group, t, score=1.0, key=""):
    return select.Cand(group, t, score, key, render=lambda: None)


def test_pacing_numbers():
    assert select.max_beats(45) == 12 and select.max_beats(30) == 7 and select.max_beats(5) == 3


def test_bisect_order_spreads_every_prefix():
    assert select.bisect_order(5) == [0, 4, 2, 1, 3]
    assert select.bisect_order(1) == [0] and select.bisect_order(0) == []
    for m in range(1, 30):
        assert sorted(select.bisect_order(m)) == list(range(m))


def test_pick_keeps_the_ask_and_the_last_commit_or_pr_and_orders_by_time():
    cs = [cand("ask", 0)] + [cand("edit", t, score=t, key=f"f{t}") for t in range(1, 30)]
    cs += [cand("commit", 40), cand("commit", 50), cand("pr", 60), cand("test_fail", 20), cand("test_pass", 70), cand("lane", 5)]
    chosen = select.pick(cs, 8)
    assert len(chosen) == 8
    assert chosen[0].group == "ask"
    assert any(c.group == "pr" and c.t == 60 for c in chosen)               # the last commit/PR
    assert [c.t for c in chosen[1:]] == sorted(c.t for c in chosen[1:])
    groups = [c.group for c in chosen]
    assert "test_fail" in groups and "test_pass" in groups and "lane" in groups and "commit" in groups
    assert groups.count("edit") <= select.CAPS["edit"]


def test_pick_takes_the_largest_edit_once_per_file_and_commands_only_to_fill():
    cs = [cand("ask", 0), cand("edit", 1, 5, "a"), cand("edit", 2, 50, "a"), cand("edit", 3, 20, "b")]
    cs += [cand("command", 4, 2), cand("command", 5, 1), cand("command", 6, 1)]
    chosen = select.pick(cs, 12)
    assert [(c.group, c.t) for c in chosen if c.group == "edit"] == [("edit", 2), ("edit", 3)]
    assert sum(c.group == "command" for c in chosen) == select.MAX_COMMANDS
    assert sum(c.group == "command" for c in select.pick(cs, 3)) == 0


def test_a_beat_that_redaction_drops_is_replaced_by_the_next(repo, claude_root):
    log = Log(repo)
    log.user(0, "Edit a lot")
    for i in range(1, 30):
        body = f"x = '{GH_TOKEN}'\n" if i == 29 else f"v{i} = {i}\n" * i
        log.tool(i * 10, "Edit", {"file_path": f"{repo}/m{i}.py", "old_string": "a\n", "new_string": body}, "ok")
    st = story_of(log.write(claude_root), git=False)
    heads = [b.headline for b in st.beats if b.kind == "edit"]
    assert "m29.py" not in heads                                              # the biggest edit held a key
    assert len(st.beats) == select.max_beats(45)                              # and the slot was refilled


def test_identical_beats_are_shown_once(repo, claude_root):
    log = Log(repo)
    log.user(0, "Run tests")
    for i in range(1, 6):
        log.tool(i * 10, "Bash", {"command": "pytest -q"}, "7 passed in 1s")
    st = story_of(log.write(claude_root), git=False)
    assert [b.headline for b in st.beats if b.kind == "test"] == ["7 tests passed"]


# --- cards and the CLI ----------------------------------------------------------------------

def test_cards_are_built_from_the_story(repo, claude_root):
    st = story_of(shipping_log(repo).write(claude_root), git=False)
    txt = cards.rendered_strings(st)
    assert txt[:2] == [st.repo, st.harness] and txt[2] == st.title and "demo · claude" in txt
    end = cards.end_card(st)
    assert end[0] == "1 commit" and "5 tests passed" in end and "1 PR opened · 1 merged" in end
    assert end[-1].endswith("wall clock") or end[-1].endswith("in tokens")
    for b in st.beats:
        assert b.kind.upper() in txt and b.headline in txt


def run(capsys, *argv):
    rc = cli.main(["reel", *argv])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_cli_list_story_check(repo, claude_root, tmp_path, capsys, monkeypatch):
    f = shipping_log(repo).write(claude_root)
    os.utime(f, None)
    # the fixture's timestamps are fixed in the past; ask for a long window
    rc, out, err = run(capsys, "list", "--since", "20000d")
    assert rc == 0 and SID[:8] in out and "claude" in out and "demo" in out
    rc, out, _ = run(capsys, "list", "--since", "20000d", "--repo", "nothing-like-this")
    assert "no sessions" in out

    dest = tmp_path / "story.json"
    rc, out, _ = run(capsys, "story", SID[:6], "-o", str(dest), "--no-git")
    assert rc == 0 and "wrote" in out
    data = json.loads(dest.read_text())
    assert data["harness"] == "claude" and data["beats"][0]["kind"] == "ask"

    rc, out, _ = run(capsys, "check", SID[:6], "--no-git")
    assert rc == 0
    lines = out.splitlines()
    assert lines[-1].startswith("# dropped (counts only): secret 0 · private-term 0")
    st = S.Story.from_dict(data)
    assert lines[:-1] == cards.rendered_strings(st)

    rc, out, _ = run(capsys, "check", str(dest))                              # from story.json too
    assert rc == 0 and out.splitlines()[:-1] == cards.rendered_strings(st)


def test_cli_errors_are_one_line_and_exit_2(claude_root, capsys, repo):
    rc, out, err = run(capsys, "story", "doesnotexist")
    assert rc == 2 and "no session starts with" in err
    shipping_log(repo).write(claude_root, sid="aaaa1111-0000-4000-8000-000000000001")
    shipping_log(repo).write(claude_root, sid="aaaa2222-0000-4000-8000-000000000002")
    rc, _, err = run(capsys, "story", "aaaa")
    assert rc == 2 and "matches 2 sessions" in err
    rc, _, err = run(capsys, "list", "--since", "soon")
    assert rc == 2 and "--since" in err


def test_check_refuses_a_hand_edited_story_with_a_secret(repo, claude_root, tmp_path, capsys):
    st = story_of(shipping_log(repo).write(claude_root), git=False)
    d = st.to_dict()
    d["beats"][1]["headline"] = "oops " + ANT_KEY
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(d))
    rc, out, err = run(capsys, "check", str(p))
    assert rc == 1 and "fail redaction" in err


def test_story_problems_flags_broken_limits():
    st = S.Story("i", "claude", "r", "", "", "ask", "t", [S.Beat(0, "ask", "x" * 60, ["y" * 40] * 9, ["?bad"])], S.Totals())
    assert len(st.problems()) == 3


def test_leak_check_module_is_imported_not_copied():
    mod = redact._leak()
    assert mod.SECRET_RES and redact.Redactor()._secrets == list(mod.SECRET_RES)


# --- review fixes: the audit, split terms, Codex tool shapes, resolving rollouts -------------

def story_by_hand(**beat_kw) -> S.Story:
    beat = S.Beat(10, "command", "git push", **beat_kw)
    return S.Story(id=SID, harness="claude", repo="demo", started=iso(0), ended=iso(60), ask="Ship it", title="demo session",
                   beats=[S.Beat(0, "ask", "The ask", ["Ship it"]), beat], totals=S.Totals(wall_clock=60))


@pytest.mark.parametrize("line", [
    "clone https://user:pass" + "word@example.com/x.git",     # redaction rewrites it to the host
    "see /Users/someone/secret/notes.txt",                    # redaction rewrites it to …/notes.txt
])
def test_audit_rejects_a_string_that_redaction_would_rewrite(line):
    st = story_by_hand(lines=[line[:34]])
    assert cli_mod.audit(st) > 0


def test_audit_accepts_a_story_the_builder_made(repo, claude_root):
    st = story_of(shipping_log(repo).write(claude_root), git=False)
    assert cli_mod.audit(st) == 0
    assert cli_mod.audit(S.Story.from_dict(json.loads(json.dumps(st.to_dict())))) == 0


def test_audit_checks_what_a_viewer_reads_across_lines(private_terms):
    private_terms.write_text(private_terms.read_text() + "acme corporation\n")
    st = story_by_hand(lines=["billing for the Acme", "Corporation customers"])
    assert cli_mod.audit(st) > 0
    assert cli_mod.audit(story_by_hand(lines=["billing for the", "Acme customers"])) == 0


def test_a_term_split_across_two_lines_of_a_pr_title_drops_the_beat(repo, claude_root, private_terms):
    private_terms.write_text(private_terms.read_text() + "acme corporation\n")
    log = Log(repo)
    log.user(0, "Ship it")
    log.tool(10, "Bash", {"command": 'gh pr create --title "Add billing for the Acme Corporation customers" --body x'},
             "https://github.com/o/demo/pull/9\n")
    st = story_of(log.write(claude_root), git=False)
    text = " ".join(" ".join([b.headline, *b.lines]) for b in st.beats).lower()
    assert "acme" not in text and "corporation" not in text
    assert st.dropped.get("private-term", 0) >= 1
    assert cli_mod.audit(st) == 0


def codex_story(tmp_path, lines, **kw):
    cwd = tmp_path / "repos" / "demo"
    cwd.mkdir(parents=True, exist_ok=True)
    git(cwd, "init", "-q")
    ask = item(1, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the parser"}]})
    f = codex_rollout(tmp_path, cwd, [ask, *lines])
    info = E.info_of(codex.parse(str(f)), "codex")
    return S.build(info, E.events_of(info), **kw), E.events_of(info)


def test_a_repo_relative_patch_path_is_an_edit_beat_and_counts_without_git(tmp_path):
    st, _ = codex_story(tmp_path, [
        item(2, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1",
                 "input": "*** Begin Patch\n*** Update File: src/foo.py\n@@\n-a = 1\n+a = 2\n+b = 3\n*** End Patch"}),
    ], git=False)
    edit = [b for b in st.beats if b.kind == "edit"]
    assert [b.headline for b in edit] == ["src/foo.py"]
    assert (st.totals.lines_added, st.totals.lines_removed, st.totals.files_changed) == (2, 1, 1)


def test_a_relative_path_cannot_leave_the_checkout_or_enter_a_harness_dir(tmp_path):
    st, _ = codex_story(tmp_path, [
        item(2, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1",
                 "input": "*** Begin Patch\n*** Update File: ../other/x.py\n@@\n-a\n+b\n*** Update File: .claude/memory.md\n@@\n-a\n+b\n*** End Patch"}),
    ], git=False)
    assert not [b for b in st.beats if b.kind == "edit"]


def _poll_rollout(first_out, poll_out=None):
    lines = [
        item(2, {"type": "function_call", "name": "exec_command", "call_id": "c1", "arguments": json.dumps({"cmd": "python -m pytest -q"})}),
        item(3, {"type": "function_call_output", "call_id": "c1", "output": first_out}),
    ]
    if poll_out is not None:
        lines += [
            item(4, {"type": "function_call", "name": "write_stdin", "call_id": "c2", "arguments": json.dumps({"session_id": 77, "chars": ""})}),
            item(5, {"type": "function_call_output", "call_id": "c2", "output": poll_out}),
        ]
    return lines


RUNNING = "Chunk ID: a1\nWall time: 1.0 seconds\nProcess running with session ID 77\nOutput:\n..F.\n"


def test_a_test_run_that_finishes_after_a_poll_gets_its_exit_status(tmp_path):
    st, ev = codex_story(tmp_path, _poll_rollout(RUNNING, "Process exited with code 1\nOutput:\n2 failed, 3 passed in 1s\n"), git=False)
    cmd = [e for e in ev if e.kind == "command"][0]
    assert cmd.exit_code == 1 and cmd.failed and cmd.session is None and "2 failed" in cmd.output
    tests = [b for b in st.beats if b.kind == "test"]
    assert [b.headline for b in tests] == ["2 failed, 3 passed"]


def test_a_test_run_that_passes_after_a_poll_counts_as_passed(tmp_path):
    st, _ = codex_story(tmp_path, _poll_rollout(RUNNING, "Process exited with code 0\nOutput:\n5 passed in 1s\n"), git=False)
    assert [b.headline for b in st.beats if b.kind == "test"] == ["5 tests passed"]


def test_json_exec_results_follow_the_session_id_too(tmp_path):
    running = json.dumps({"chunk_id": "x", "session_id": 77, "output": "..F."})
    done = json.dumps({"chunk_id": "y", "exit_code": 1, "output": "1 failed, 2 passed in 1s"})
    st, _ = codex_story(tmp_path, _poll_rollout(running, done), git=False)
    assert [b.headline for b in st.beats if b.kind == "test"] == ["1 failed, 2 passed"]


def test_a_run_never_heard_from_again_is_not_reported_as_passed(tmp_path):
    st, ev = codex_story(tmp_path, _poll_rollout(RUNNING), git=False)
    assert [e for e in ev if e.kind == "command"][0].session == 77
    assert not [b for b in st.beats if b.kind == "test"]
    assert st.totals.test_runs == 0


@pytest.mark.parametrize("output", [
    "apply_patch verification failed: Failed to find expected lines in src/foo.py",
    json.dumps({"output": "patch rejected", "metadata": {"exit_code": 1}}),
    "Exit code: 1\nWall time: 0.1 seconds\nOutput:\nboom",
])
def test_a_rejected_apply_patch_is_not_an_edit(tmp_path, output):
    st, ev = codex_story(tmp_path, [
        item(2, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1",
                 "input": "*** Begin Patch\n*** Update File: src/foo.py\n@@\n-a\n+b\n*** End Patch"}),
        item(3, {"type": "custom_tool_call_output", "call_id": "c1", "output": output}),
    ], git=False)
    assert [e for e in ev if e.kind == "edit"][0].failed
    assert not [b for b in st.beats if b.kind == "edit"] and st.totals.lines_added == 0


def test_an_applied_patch_stays_an_edit(tmp_path):
    st, _ = codex_story(tmp_path, [
        item(2, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1",
                 "input": "*** Begin Patch\n*** Update File: src/foo.py\n@@\n-a\n+b\n*** End Patch"}),
        item(3, {"type": "custom_tool_call_output", "call_id": "c1",
                 "output": "Exit code: 0\nWall time: 0.1 seconds\nOutput:\nSuccess. Updated the following files:\nM src/foo.py"}),
    ], git=False)
    assert [b.headline for b in st.beats if b.kind == "edit"] == ["src/foo.py"]


@pytest.mark.parametrize("js, cmd", [
    ('await tools.exec_command({"cmd":"pytest -q"});', "pytest -q"),
    ("await tools.exec_command({ workdir: '/w', cmd: 'cd /w && pytest -q', yield_time_ms: 500 });", "cd /w && pytest -q"),
    ('await tools.exec_command({"workdir":"/w","env":{"A":"1,2"},"cmd":"make test"});', "make test"),
    ("await tools.exec_command({cmd: `swift test`});", "swift test"),
])
def test_js_exec_commands_are_read_wherever_cmd_stands_in_the_object(tmp_path, js, cmd):
    _st, ev = codex_story(tmp_path, [item(2, {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": js})], git=False)
    assert [e.text for e in ev if e.kind == "command"] == [cmd]


def test_a_rollout_in_the_archive_resolves(tmp_path, monkeypatch):
    live, arch = tmp_path / "sessions", tmp_path / "archived_sessions"
    name = f"rollout-2026-01-01T12-00-00-{SID}.jsonl"
    (arch / "2026" / "01").mkdir(parents=True)
    (arch / "2026" / "01" / name).write_text(json.dumps(
        {"type": "session_meta", "timestamp": iso(0), "payload": {"id": SID, "cwd": "/w/demo", "source": "vscode"}}) + "\n")
    live.mkdir()
    assert codex.locate(SID[:8], root=str(live), archive_root=str(arch)) == [str(arch / "2026" / "01" / name)]
    assert codex.locate(SID[:8], root=str(live), archive_root="") == []
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(live))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", str(arch))
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(tmp_path / "none"))
    assert E.resolve(SID[:8]).sid == SID


def test_a_rollout_id_that_starts_with_digits_is_not_eaten_by_the_timestamp(tmp_path):
    sid = "12345678-abcd-4000-8000-000000000001"
    d = tmp_path / "2026" / "01" / "01"
    d.mkdir(parents=True)
    f = d / f"rollout-2026-01-01T12-00-00-{sid}.jsonl"
    f.write_text("{}\n")
    assert codex.locate("12345678", root=str(tmp_path), archive_root="") == [str(f)]
    assert codex.locate("12345678-abcd", root=str(tmp_path), archive_root="") == [str(f)]
    assert codex.locate("abcd", root=str(tmp_path), archive_root="") == []
