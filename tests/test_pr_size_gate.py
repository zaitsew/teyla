"""The PR size gate (`teyla.pr_size_gate`, `plugin/hooks/pr-size-gate.sh`): a PR over the limits is refused at
`gh pr create` and `gh pr merge`; excluded files are not counted; the escapes are logged; every error allows."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from teyla import pr_size_gate as g

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "pr-size-gate.sh"


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=a@example.com", "-c", "user.name=a", *a],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "widget"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("hi\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    git(r, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(r, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(r, "checkout", "-qb", "feature")
    return r


def add(repo, files: dict[str, int]):
    for path, n in files.items():
        p = repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(f"line {i}\n" for i in range(n)))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "teyla"
    home.mkdir()
    monkeypatch.delenv("TEYLA_SIZE_OK", raising=False)
    return {"TEYLA_HOME": str(home), "HOME": str(tmp_path), "PATH": os.environ["PATH"]}


def rows(env):
    p = pathlib.Path(env["TEYLA_HOME"]) / g.LOG_NAME
    return [r.split("\t") for r in p.read_text().splitlines()] if p.exists() else []


def config(env, text):
    (pathlib.Path(env["TEYLA_HOME"]) / "config.toml").write_text(text)


def claude(repo, command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1", "cwd": str(repo),
            "transcript_path": "/x/t.jsonl", "tool_input": {"command": command}}


def codex(repo, command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "abc12345-0000", "cwd": str(repo),
            "turn_id": "t1", "model": "gpt-6.1-sol", "transcript_path": None,
            "tool_input": {"command": ["bash", "-lc", command]}}


def stub_gh(tmp_path, env, files, body=""):
    """A `gh` on PATH that answers `gh pr view ... --json` with a fixed PR and records its argv."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    data = {"files": [{"path": p, "additions": n, "deletions": 0} for p, n in files.items()],
            "additions": sum(files.values()), "deletions": 0, "body": body}
    (tmp_path / "pr.json").write_text(json.dumps(data))
    (bin_ / "gh").write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/gh.log"\ncat "{tmp_path}/pr.json"\n')
    (bin_ / "gh").chmod(0o755)
    env["PATH"] = f"{bin_}:{env['PATH']}"
    return tmp_path / "gh.log"


def decide(payload, env):
    return g.decide(payload, env)


# --- create ---------------------------------------------------------------------------------------------------

def test_a_small_pr_passes_and_logs_nothing(repo, env):
    add(repo, {"src/a.py": 100})
    assert decide(claude(repo, "gh pr create --title x --body y"), env) is None
    assert rows(env) == []


def test_an_over_the_line_limit_pr_is_refused_with_counts_dirs_and_a_hint(repo, env):
    add(repo, {"src/big/a.py": 700, "docs/design/b.md": 300, "tests/c.py": 50})
    text = decide(claude(repo, "gh pr create --title x --body y"), env)
    assert text and "1050 lines in 3 files" in text and "limits 800 lines, 20 files" in text
    assert "src/big 700" in text and "docs/design 300" in text and "one pr per logical unit" in text.lower()
    assert "Size-OK" in text and "TEYLA_SIZE_OK" in text
    [row] = rows(env)
    assert row[1:] == ["claude", "widget", "create", "1050", "3", "refused"]


def test_an_over_the_file_limit_pr_is_refused(repo, env):
    add(repo, {f"src/f{i}.py": 1 for i in range(21)})
    text = decide(claude(repo, "gh pr create --fill"), env)
    assert text and "21 files" in text


def test_exactly_at_the_limits_passes(repo, env):
    add(repo, {f"src/f{i}.py": 40 for i in range(20)})
    assert decide(claude(repo, "gh pr create --fill"), env) is None


def test_excluded_files_are_not_counted(repo, env):
    add(repo, {"uv.lock": 5000, "package-lock.json": 900, "App.xcodeproj/project.pbxproj": 900,
               "L/Localizable.xcstrings": 900, "res/values-es/strings.xml": 900, "locales/es.json": 900,
               "img/a.png": 900, "fonts/a.ttf": 900, "t/__snapshots__/a.txt": 900, "x/a.snap": 900,
               "dist/app.js": 900, "build/o.txt": 900, "App/Generated/m.swift": 900, "CHANGELOG.md": 900,
               "Podfile.lock": 900, "Package.resolved": 900, "src/real.py": 10})
    assert decide(claude(repo, "gh pr create --fill"), env) is None


@pytest.mark.parametrize("path", ["uv.lock", "a/b/yarn.lock", "x.pbxproj", "a.xcstrings", "en.lproj/a.strings",
                                  "values-fr/strings.xml", "locales/en/x.json", "a.JPG", "a.woff2", "a.mov",
                                  "a/__snapshots__/x", "dist/x.js", "Generated/x.swift", "CHANGELOG.md"])
def test_is_excluded(path):
    assert g.is_excluded(path)


@pytest.mark.parametrize("path", ["src/a.py", "docs/guide.md", "src/builder.py", "README.md", "src/distance.py"])
def test_is_not_excluded(path):
    assert not g.is_excluded(path)


def test_base_option_is_honoured(repo, env):
    add(repo, {"src/a.py": 900})
    git(repo, "branch", "mid", "HEAD")
    add(repo, {"src/b.py": 10})
    assert decide(claude(repo, "gh pr create --base mid"), env) is None
    assert decide(claude(repo, "gh pr create --base main"), env)


def test_the_codex_payload_with_a_bash_lc_wrapper_is_understood(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(codex(repo, "cd . && gh pr create --title x --body y"), env)
    assert rows(env)[0][1] == "codex"


def test_a_nested_bash_c_in_a_claude_payload(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, "bash -lc 'gh pr create --fill'"), env)


def test_size_ok_in_the_body_overrides_and_is_logged(repo, env):
    add(repo, {"src/a.py": 900})
    cmd = "gh pr create --title x --body 'Moves the data layer.\n\nSize-OK: mechanical rename, one idea'"
    assert decide(claude(repo, cmd), env) is None
    assert rows(env)[0][-1] == "mechanical rename, one idea"


def test_size_ok_in_a_heredoc_body_and_in_a_body_file(repo, env, tmp_path):
    add(repo, {"src/a.py": 900})
    heredoc = "gh pr create --title x --body \"$(cat <<'EOF'\nsummary\nSize-OK: generated import\nEOF\n)\""
    assert decide(claude(repo, heredoc), env) is None
    (tmp_path / "body.md").write_text("summary\n\nSize-OK: vendored data\n")
    assert decide(claude(repo, f"gh pr create --title x --body-file {tmp_path}/body.md"), env) is None
    assert [r[-1] for r in rows(env)] == ["generated import", "vendored data"]


def test_a_body_without_the_line_is_still_refused(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, "gh pr create --body 'size is fine, trust me'"), env)


def test_env_override_and_leading_assignment(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, "TEYLA_SIZE_OK='one-off import' gh pr create --fill"), env) is None
    assert decide(claude(repo, "gh pr create --fill"), dict(env, TEYLA_SIZE_OK="from env")) is None
    assert [r[-1] for r in rows(env)] == ["one-off import", "from env"]


def test_warn_prints_and_allows_and_off_is_silent(repo, env, capsys):
    add(repo, {"src/a.py": 900})
    config(env, '[pr_size]\nmode = "warn"\n')
    assert decide(claude(repo, "gh pr create --fill"), env) is None
    assert "warn" in capsys.readouterr().err and rows(env)[0][-1] == "warned"
    config(env, '[pr_size]\nmode = "off"\n')
    assert decide(claude(repo, "gh pr create --fill"), env) is None
    assert len(rows(env)) == 1


def test_configured_limits(repo, env):
    add(repo, {"src/a.py": 120})
    config(env, "[pr_size]\nmax_lines = 100\n")
    assert decide(claude(repo, "gh pr create --fill"), env)
    config(env, "[pr_size]\nmax_lines = 100\nmax_files = 0\nmode = 7\n")  # bad values keep the defaults
    assert g.load_config(env) == {"max_lines": 100, "max_files": 20, "mode": "refuse"}


# --- merge ----------------------------------------------------------------------------------------------------

def test_merge_sizes_the_pr_through_gh_and_refuses(repo, env, tmp_path):
    log = stub_gh(tmp_path, env, {"src/a.py": 1000, "uv.lock": 4000, "docs/b.md": 629})
    text = decide(claude(repo, "gh pr merge 42 --merge"), env)
    assert text and "1629 lines in 2 files" in text and "src 1000" in text
    assert "pr view 42" in log.read_text() and "--json files,additions,deletions,body" in log.read_text()
    assert rows(env)[0][3:6] == ["42", "1629", "2"]


def test_merge_without_a_number_is_the_current_branch(repo, env, tmp_path):
    log = stub_gh(tmp_path, env, {"src/a.py": 900})
    assert decide(claude(repo, "gh pr merge --merge --delete-branch"), env)
    assert log.read_text().startswith("pr view --json")
    assert rows(env)[0][3] == "current"


def test_merge_passes_when_small_and_size_ok_in_the_pr_body_overrides(repo, env, tmp_path):
    stub_gh(tmp_path, env, {"src/a.py": 10})
    assert decide(claude(repo, "gh pr merge 1 --merge"), env) is None
    stub_gh(tmp_path, env, {"src/a.py": 900}, body="Rename.\n\nSize-OK: pure rename of a package\n")
    assert decide(claude(repo, "gh pr merge 1 --merge"), env) is None
    assert rows(env)[0][-1] == "pure rename of a package"


def test_merge_with_repo_flag(repo, env, tmp_path):
    log = stub_gh(tmp_path, env, {"src/a.py": 900})
    assert decide(codex(repo, "gh -R owner/app pr merge 5 --merge"), env)
    assert "-R owner/app" in log.read_text() and rows(env)[0][2] == "owner/app"


# --- untouched and fail-open ----------------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["ls -la", "git push origin feature", "gh pr view 3", "gh pr list", "gh issue create",
                                 "gh pr comment 3 --body hi", "echo gh pr create", "gh pr checks 4"])
def test_other_commands_are_untouched(repo, env, tmp_path, cmd):
    add(repo, {"src/a.py": 900})
    log = stub_gh(tmp_path, env, {"src/a.py": 900})
    assert decide(claude(repo, cmd), env) is None
    assert not log.exists() and rows(env) == []


def test_a_gh_failure_allows_logs_unsized_and_main_exits_zero(repo, env, tmp_path, monkeypatch, capsys):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text("#!/bin/sh\nexit 1\n")
    (bin_ / "gh").chmod(0o755)
    env["PATH"] = f"{bin_}:{env['PATH']}"
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import io
    monkeypatch.setattr("sys.stdin", type("S", (), {"buffer": io.BytesIO(json.dumps(claude(repo, "gh pr merge 3")).encode())})())
    assert g.main() == 0
    assert "not sized" in capsys.readouterr().err
    [row] = rows(env)
    assert row[2:4] == ["widget", "merge"] and row[-1].startswith("unsized: ") and "exited 1" in row[-1]


def test_a_repo_without_a_base_allows_and_logs_unsized(tmp_path, env):
    r = tmp_path / "bare"
    r.mkdir()
    git(r, "init", "-q", "-b", "trunk")
    assert g.decide(claude(r, "gh pr create --fill"), env) is None
    [row] = rows(env)
    assert row[2:4] == ["bare", "create"] and row[-1] == "unsized: RuntimeError: no base branch"


# --- fail-open gaps -------------------------------------------------------------------------------------------

def test_head_option_sizes_the_named_branch_not_the_current_one(repo, env):
    add(repo, {"src/small.py": 10})
    git(repo, "checkout", "-qb", "other", "main")
    add(repo, {"src/big.py": 900})
    git(repo, "checkout", "-q", "feature")  # HEAD is the small branch
    assert decide(claude(repo, "gh pr create --fill"), env) is None
    assert decide(claude(repo, "gh pr create --head other --fill"), env)
    assert decide(claude(repo, "gh pr create -H other --fill"), env)
    assert decide(claude(repo, "gh pr create --head=someone:other --fill"), env)
    git(repo, "checkout", "-q", "other")  # HEAD is the big branch, the named head is the small one
    assert decide(claude(repo, "gh pr create --head feature --fill"), env) is None


def test_a_remote_only_head_uses_origin(repo, env):
    add(repo, {"src/big.py": 900})
    git(repo, "update-ref", "refs/remotes/origin/pushed", "HEAD")
    git(repo, "checkout", "-q", "main")
    assert decide(claude(repo, "gh pr create --head pushed --fill"), env)
    assert decide(claude(repo, "gh pr create --head fork:pushed --fill"), env)


def test_a_missing_head_allows_and_logs_unsized(repo, env):
    add(repo, {"src/big.py": 900})
    assert decide(claude(repo, "gh pr create --head nowhere --fill"), env) is None
    assert rows(env)[0][-1] == "unsized: RuntimeError: head nowhere not found locally or on origin"


def test_a_base_with_a_slash_resolves_to_the_remote_ref(repo, env):
    add(repo, {"src/a.py": 900})
    git(repo, "update-ref", "refs/remotes/origin/release/v1", "main")
    assert decide(claude(repo, "gh pr create --base release/v1 --fill"), env)
    assert decide(claude(repo, "gh pr create -B origin/main --fill"), env)
    git(repo, "branch", "hotfix/x", "HEAD")  # a local ref with a slash
    assert decide(claude(repo, "gh pr create --base hotfix/x --fill"), env) is None
    assert [r[-1] for r in rows(env)] == ["refused", "refused"]


def test_an_unknown_base_allows_and_logs_unsized(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, "gh pr create --base release/none --fill"), env) is None
    assert rows(env)[0][-1] == "unsized: RuntimeError: base release/none not found"


@pytest.mark.parametrize("cmd, reason", [
    ("gh pr create --title x --body 'Moves it.\n\nSize-OK: one idea'", "one idea"),
    ('gh pr create --title x --body "Size-OK: one idea"', "one idea"),
    ("gh pr create --title x --body='Size-OK: one idea'", "one idea"),
    ("gh pr create --title x --body \"$(cat <<'EOF'\nsummary\n\nSize-OK: one idea\nEOF\n)\"", "one idea"),
    ("gh pr create --title x --body-file - <<'EOF'\nsummary\n\nSize-OK: one idea\nEOF\n", "one idea"),
])
def test_size_ok_is_read_from_the_body_value_without_quotes(repo, env, cmd, reason):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, cmd), env) is None
    assert rows(env)[-1][-1] == reason


def test_size_ok_in_a_body_file_loses_its_quotes(repo, env, tmp_path):
    add(repo, {"src/a.py": 900})
    (tmp_path / "b.md").write_text("summary\nSize-OK: vendored data'\n")
    assert decide(claude(repo, f"gh pr create --body-file {tmp_path}/b.md"), env) is None
    assert rows(env)[-1][-1] == "vendored data"


def test_size_ok_outside_the_body_does_not_override(repo, env):
    add(repo, {"src/a.py": 900})
    assert decide(claude(repo, "echo 'Size-OK: sneaky' && gh pr create --title t --body plain"), env)
    assert decide(claude(repo, "gh pr create --title 'Size-OK: sneaky' --body plain"), env)


def test_merge_by_url_outside_a_checkout(tmp_path, env):
    nowhere = tmp_path / "plain"
    nowhere.mkdir()
    log = stub_gh(tmp_path, env, {"src/a.py": 900})
    url = "https://github.com/owner/app/pull/7"
    assert decide(claude(nowhere, f"gh pr merge {url} --merge"), env)
    assert f"pr view {url} --json" in log.read_text() and "-R" not in log.read_text()
    assert rows(env)[0][2:4] == ["owner/app", url] and rows(env)[0][-1] == "refused"


def test_merge_with_repo_flag_outside_a_checkout(tmp_path, env):
    nowhere = tmp_path / "plain"
    nowhere.mkdir()
    log = stub_gh(tmp_path, env, {"src/a.py": 900})
    assert decide(claude(nowhere, "gh pr merge 9 -R owner/app --merge"), env)
    assert "pr view 9 -R owner/app" in log.read_text() and rows(env)[0][2] == "owner/app"
    assert decide(claude(nowhere, "gh pr merge --repo owner/other 9"), env)
    assert rows(env)[1][2] == "owner/other"


def test_merge_outside_a_checkout_without_a_repo_still_sizes_and_labels_unknown(tmp_path, env):
    nowhere = tmp_path / "plain"
    nowhere.mkdir()
    stub_gh(tmp_path, env, {"src/a.py": 900})
    assert decide(claude(nowhere, "gh pr merge 9"), env)
    assert rows(env)[0][2] == "unknown"


def test_monitor_line_counts_unsized(env):
    g.log_row("codex", "r", "create", 0, 0, "unsized: RuntimeError: no base branch", env)
    assert g.monitor_line(environ=env) == "PR size gate, last 7 days: 1 unsized.\n"


def test_monitor_line_counts_each_kind(env):
    assert g.monitor_line(environ=env) == ""
    g.log_row("codex", "r", "create", 900, 3, "refused", env)
    g.log_row("codex", "r", "create", 900, 3, "refused", env)
    g.log_row("claude", "r", "7", 900, 3, "reason", env)
    g.log_row("claude", "r", "7", 900, 3, "warned", env)
    assert g.monitor_line(environ=env) == "PR size gate, last 7 days: 2 refused, 1 warned, 1 overridden.\n"


# --- the hook script ------------------------------------------------------------------------------------------

def run_hook(payload, env, cwd, python=True):
    wrap = pathlib.Path(env["HOME"]) / "py"
    # the hook runs `python -I -m teyla.pr_size_gate`; -I drops PYTHONPATH, and an installed teyla may predate
    # this module, so the wrapper puts this tree's src first
    code = f"import sys, runpy; sys.path.insert(0, {str(ROOT / 'src')!r}); runpy.run_module('teyla.pr_size_gate', run_name='__main__')"
    wrap.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c "{code}"\n')
    wrap.chmod(0o755)
    e = dict(env)
    if python:
        e["TEYLA_PYTHON"] = str(wrap)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["sh", str(HOOK)], input=raw, capture_output=True, text=True, cwd=cwd, env=e, timeout=30)


def test_the_hook_refuses_with_exit_2_and_allows_the_rest(repo, env):
    add(repo, {"src/a.py": 900})
    p = run_hook(claude(repo, "gh pr create --fill"), env, repo)
    assert p.returncode == 2 and "PR size gate" in p.stderr
    p = run_hook(claude(repo, "ls"), env, repo)
    assert (p.returncode, p.stderr) == (0, "")
    p = run_hook(claude(repo, "gh pr create --fill"), dict(env, TEYLA_PR_SIZE_GATE="0"), repo)
    assert p.returncode == 0
    p = run_hook(claude(repo, "gh pr create --fill"), env, repo, python=False)
    assert p.returncode in (0, 2)  # no TEYLA_PYTHON: whatever python3 is installed; the point is it never crashes


def test_the_hook_fails_open_on_garbage_and_a_missing_package(repo, env):
    assert run_hook("gh pr create {not json", env, repo).returncode == 0
    e = dict(env, TEYLA_PYTHON="/nonexistent/python", PATH="/usr/bin:/bin")
    p = subprocess.run(["sh", str(HOOK)], input=json.dumps(claude(repo, "gh pr create")), capture_output=True,
                       text=True, cwd=repo, env=e, timeout=30)
    assert p.returncode == 0


def test_the_hook_is_registered_in_the_plugin_and_for_codex():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    ours = [g_ for g_ in hooks if any("pr-size-gate.sh" in h["command"] for h in g_["hooks"])]
    assert len(ours) == 1 and ours[0]["matcher"] == "Bash"
    from teyla import harness
    cdx = harness._codex_hooks(None)["hooks"]["PreToolUse"]
    assert any(g_.get("matcher") == "Bash" and g_["hooks"][0]["command"].endswith("pr-size-gate.sh") for g_ in cdx)
