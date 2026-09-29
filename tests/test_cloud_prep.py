"""teyla.cloud_prep — the files a cloud session needs, written idempotently between markers,
never over hand-written content, never with anything personal in them; and the two hook
scripts, run for real under sh in a fixture repo with a local origin."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from teyla import cloud, cloud_prep, config

OWNERS = {"acme/app", "acme/secret-project", "acme/other"}
POLICY = "- **No GitHub Actions.** Nothing on push or PR.\nOwner: Jane Roe, jane@example.com, ~/ops/bin/tool\n"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid"), ("GIT_CONFIG_NOSYSTEM", "1")):
        monkeypatch.setenv(k, v)
    return home


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _repo(tmp_path, files=None, name="app", slug="acme/app"):
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    if slug:
        _git(r, "remote", "add", "origin", f"https://github.com/{slug}.git")
    for rel, text in (files or {}).items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return r


def _prep(r, **kw):
    kw.setdefault("owners", OWNERS)
    kw.setdefault("policy_text", POLICY)
    kw.setdefault("vis", "private")
    return cloud_prep.prep(r, **kw)


def _tree(path):
    return {str(p.relative_to(path)): (p.read_text() if p.is_file() else None) for p in path.rglob("*") if ".git" not in p.parts}


GATE = "#!/bin/sh\nset -e\npython -m pytest -q\nif command -v xcodebuild >/dev/null; then xcodebuild build; else echo 'skipped here: ios'; fi\n"


# --- what gets written ---------------------------------------------------------------------

def test_fresh_repo_gets_every_file_and_becomes_cloud_ready(tmp_path, _home):
    (_home / ".claude" / "CLAUDE.md").write_text("MERGE-APPROVED REPOS\n  acme/app\n```\n")
    r = _repo(tmp_path, {"check.sh": GATE, ".env.example": "OPENAI_API_KEY=sk-x\nAPP_URL=\n"})
    rc, out = _prep(r)
    assert rc == 0, out
    for rel in ("AGENTS.md", "CLAUDE.md", ".claude/settings.json", cloud_prep.START_HOOK, cloud_prep.STOP_HOOK,
                ".claude/rules/cloud.md", "docs/cloud-setup.md"):
        assert (r / rel).is_file(), rel
    assert os.access(r / cloud_prep.STOP_HOOK, os.X_OK)
    assert (r / "CLAUDE.md").read_text().splitlines()[1] == "@AGENTS.md"
    agents = (r / "AGENTS.md").read_text()
    assert "merge-approved: yes" in agents and "No GitHub Actions" in agents
    rep = cloud.check_repo(r, net=False)
    assert rep["ready"] and all(i["level"] in ("OK", "INFO") for i in rep["items"]), rep["items"]
    rc, out = _prep(r)
    assert rc == 0 and out[-1] == "up to date: nothing to write"


def test_merge_flag_follows_the_owner_list_and_refreshes_in_place(tmp_path):
    r = _repo(tmp_path, {"AGENTS.md": "# app\n\nHand-written intro.\n", "CLAUDE.md": "@AGENTS.md\n\nMore by hand.\n"})
    _prep(r)
    (r / "AGENTS.md").write_text((r / "AGENTS.md").read_text() + "\n## Later, by hand\n\nkept\n")
    rc, out = _prep(r, owners={"acme/other"})
    agents = (r / "AGENTS.md").read_text()
    assert "merge-approved: no" in agents and "merge-approved: yes" not in agents
    assert "Hand-written intro." in agents and "## Later, by hand\n\nkept" in agents
    assert agents.count("teyla:cloud:start") == 1
    assert (r / "CLAUDE.md").read_text() == "@AGENTS.md\n\nMore by hand.\n"  # import already there: untouched


def test_unknown_owner_list_writes_the_safe_no(tmp_path):
    rc, out = _prep(_repo(tmp_path, slug=None), owners=None)
    assert "merge-approved: no" in (tmp_path / "app" / "AGENTS.md").read_text()
    assert any("safe default" in l for l in out)


def test_claude_md_gets_one_import_line_at_the_top(tmp_path):
    r = _repo(tmp_path, {"AGENTS.md": "# a\n", "CLAUDE.md": "# Claude notes\n"})
    _prep(r)
    text = (r / "CLAUDE.md").read_text()
    assert text.startswith(cloud_prep.IMPORT_START + "\n@AGENTS.md\n" + cloud_prep.IMPORT_END + "\n\n# Claude notes")
    _prep(r)
    assert (r / "CLAUDE.md").read_text().count("@AGENTS.md") == 1


@pytest.mark.parametrize("link,target", [("AGENTS.md", "CLAUDE.md"), ("CLAUDE.md", "AGENTS.md")])
def test_symlinked_pair_gets_the_section_once_and_no_import(tmp_path, link, target):
    r = _repo(tmp_path, {target: "# real\n"})
    (r / link).symlink_to(target)
    _prep(r)
    assert (r / link).is_symlink()
    text = (r / target).read_text()
    assert text.count("teyla:cloud:start") == 1 and "@AGENTS.md" not in text


def test_settings_json_is_merged_never_clobbered(tmp_path):
    existing = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh mine.sh"}]}]}}
    r = _repo(tmp_path, {".claude/settings.json": json.dumps(existing)})
    _prep(r)
    data = json.loads((r / ".claude/settings.json").read_text())
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    stops = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert stops[0] == "sh mine.sh" and cloud_prep.STOP_HOOK in stops[1]
    assert any(cloud_prep.START_HOOK in h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"])
    before = (r / ".claude/settings.json").read_text()
    _prep(r)
    assert (r / ".claude/settings.json").read_text() == before


def test_invalid_settings_json_refuses_and_writes_nothing(tmp_path):
    r = _repo(tmp_path, {".claude/settings.json": "{not json", "AGENTS.md": "# a\n"})
    before = _tree(r)
    rc, out = _prep(r)
    assert rc == 1 and out[0].startswith("refused: .claude/settings.json is not valid JSON")
    assert _tree(r) == before


def test_hand_written_hook_script_is_not_touched(tmp_path):
    r = _repo(tmp_path, {cloud_prep.STOP_HOOK: "#!/bin/sh\necho mine\n"})
    rc, out = _prep(r)
    assert (r / cloud_prep.STOP_HOOK).read_text() == "#!/bin/sh\necho mine\n"
    assert any("hand-written: not touched" in l for l in out)


def test_gitignore_is_only_printed_without_the_flag(tmp_path):
    gi = "node_modules/\n.claude/*\n!.claude/agents/\n"
    r = _repo(tmp_path, {".gitignore": gi})
    rc, out = _prep(r)
    assert (r / ".gitignore").read_text() == gi
    note = next(l for l in out if ".gitignore ignores .claude/ wholesale (line 2)" in l)
    assert ".claude/settings.local.json" in note and "--fix-gitignore" in note
    rc, out = _prep(r, fix_gitignore=True)
    assert (r / ".gitignore").read_text() == ("node_modules/\n.claude/settings.local.json\n.claude/launch.json\n"
                                              ".claude/worktrees/\n!.claude/agents/\n")
    assert cloud.claude_ignored(r) == []


def test_dry_writes_nothing_and_prints_a_diff(tmp_path, capsys):
    from teyla.cli import main
    r = _repo(tmp_path, {"AGENTS.md": "# a\nprivate context line\n", ".gitignore": ".claude/\n"})
    before = _tree(r)
    assert main(["cloud", "prep", str(r), "--dry", "--fix-gitignore"]) == 0
    out = capsys.readouterr().out
    assert _tree(r) == before
    assert "+++ b/AGENTS.md" in out and "+++ b/.claude/hooks/teyla-cloud-stop.sh" in out and "--- /dev/null" in out
    assert "-.claude/" in out and "+.claude/launch.json" in out
    assert "private context line" not in out  # no context lines: the diff quotes only what prep writes


@pytest.mark.parametrize("vis,allow,rc", [("public", False, 1), (None, False, 1), ("public", True, 0), ("private", False, 0)])
def test_public_or_unknown_visibility_is_refused_without_the_flag(tmp_path, vis, allow, rc):
    r = _repo(tmp_path)
    before = _tree(r)
    got, out = _prep(r, vis=vis, allow_public=allow)
    assert got == rc
    if rc:
        assert _tree(r) == before and "--allow-public" in out[-1]
        assert ("unknown visibility" in out[-1]) is (vis is None)
    else:
        assert (r / "AGENTS.md").exists()


def test_generated_text_carries_nothing_personal(tmp_path):
    r = _repo(tmp_path, {"check.sh": GATE, ".env.example": "ASC_KEY_ID=\nX_TOKEN=\n"})
    p = cloud_prep.plan(r, owners=OWNERS, policy_text=POLICY)
    for rel, _old, new, _ in p["changes"]:
        assert "~/" not in new and "/Users/" not in new, rel
        assert "jane" not in new.lower() and "@example.com" not in new, rel
        assert "secret-project" not in new and "acme/other" not in new, rel


def test_the_guard_catches_what_it_is_for():
    assert cloud_prep.leaks("see ~/.claude/CLAUDE.md", set(), None) == ["a home-directory path"]
    assert cloud_prep.leaks("mail jane@example.com", set(), None) == ["an email address"]
    assert cloud_prep.leaks("also acme/other", OWNERS, "acme/app") == ["1 other repo name(s) from the owner's list"]
    assert cloud_prep.leaks("this is acme/app, $HOME/.local/bin", OWNERS, "acme/app") == []


def test_no_actions_rule_only_when_the_owner_policy_says_so(tmp_path):
    a = cloud_prep.shipping_section("yes", "./check.sh", no_actions=True)
    b = cloud_prep.shipping_section("no", None, no_actions=False)
    assert "No GitHub Actions" in a and "No GitHub Actions" not in b
    assert "gh pr merge --merge`). If merging is refused" in a and "the owner merges" in b
    assert cloud._MERGE_LINE.findall(a) == ["yes"] and cloud._MERGE_LINE.findall(b) == ["no"]


@pytest.mark.parametrize("name,want", [("ASC_KEY_ID", "local only"), ("APNS_KEY_ID", "local only"),
                                       ("OPENAI_API_KEY", "host api.openai.com"), ("SUPABASE_URL", "environment variable"),
                                       ("MY_SERVICE_TOKEN", "fill in")])
def test_secret_destinations(name, want):
    assert want in cloud_prep.secret_destination(name)


def test_setup_script_is_valid_bash_and_survives_missing_files(tmp_path):
    r = _repo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n", "pnpm-lock.yaml": "", "deno.json": "{}"})
    script = "\n".join(cloud_prep.setup_script(r, ""))
    assert "pnpm install --frozen-lockfile" in script and "npm install -g deno" in script
    f = tmp_path / "setup.sh"
    f.write_text(script + "\n")
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert not any(l.startswith("[ ") and "&&" in l for l in script.splitlines())


# --- the hooks, run for real -----------------------------------------------------------------

def _landed_repo(tmp_path):
    """A clone of a local bare origin, on a session branch with one commit."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    r = _repo(tmp_path, {"check.sh": GATE}, slug=None)
    _git(r, "remote", "add", "origin", str(bare))
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "push", "-q", "-u", "origin", "main")
    _git(r, "remote", "set-head", "origin", "main")
    _prep(r)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "prep")
    _git(r, "push", "-q", "origin", "main")
    _git(r, "checkout", "-q", "-b", "claude/brave-x")
    return r


def _run(r, script, remote=True, path=None, stdin='{"stop_hook_active":false}'):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
    env["CLAUDE_PROJECT_DIR"] = str(r)
    if remote:
        env["CLAUDE_CODE_REMOTE"] = "true"
    if path:
        env["PATH"] = path
    return subprocess.run(["sh", str(r / script)], input=stdin, capture_output=True, text=True, env=env, cwd=str(r))


NO_GH = "/usr/bin:/bin"


def _fake_gh(tmp_path, body):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    (d / "gh").write_text("#!/bin/sh\n" + body)
    (d / "gh").chmod(0o755)
    return f"{d}:{NO_GH}"


def test_hooks_are_silent_outside_the_cloud(tmp_path):
    r = _landed_repo(tmp_path)
    (r / "x.txt").write_text("dirty")
    for script in (cloud_prep.START_HOOK, cloud_prep.STOP_HOOK):
        res = _run(r, script, remote=False)
        assert res.returncode == 0 and res.stdout == "" and res.stderr == ""


def test_start_hook_orients_a_cloud_session(tmp_path):
    r = _landed_repo(tmp_path)
    out = _run(r, cloud_prep.START_HOOK).stdout
    assert "branch claude/brave-x" in out and "Gate: ./check.sh" in out
    assert "Skipped here without a Mac: xcodebuild" in out and "merge-approved: no" in out  # a local origin: no GitHub slug
    assert "open the PR" in out


def test_stop_hook_blocks_until_pushed_and_a_pr_exists(tmp_path):
    if shutil.which("gh", path=NO_GH):
        pytest.skip("gh lives in /usr/bin here; cannot build a PATH without it")
    r = _landed_repo(tmp_path)
    assert _run(r, cloud_prep.STOP_HOOK, path=NO_GH).returncode == 0  # nothing done yet: stopping is fine

    (r / "x.txt").write_text("work")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "Uncommitted changes on claude/brave-x" in res.stderr

    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "work")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "1 commit(s) on claude/brave-x are not on the remote" in res.stderr

    _git(r, "push", "-q", "-u", "origin", "claude/brave-x")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "gh is not available here" in res.stderr

    none = _fake_gh(tmp_path, 'case "$1" in auth) exit 0;; esac\necho "no pull requests found" >&2\nexit 1\n')
    res = _run(r, cloud_prep.STOP_HOOK, path=none)
    assert res.returncode == 2 and "No open PR for claude/brave-x" in res.stderr

    unauth = tmp_path / "unauth"
    unauth.mkdir()
    (unauth / "gh").write_text("#!/bin/sh\nexit 1\n")
    (unauth / "gh").chmod(0o755)
    res = _run(r, cloud_prep.STOP_HOOK, path=f"{unauth}:{NO_GH}")
    assert res.returncode == 2 and "gh is not signed in" in res.stderr

    (tmp_path / "fakebin" / "gh").write_text("#!/bin/sh\necho OPEN\n")
    assert _run(r, cloud_prep.STOP_HOOK, path=none).returncode == 0

    # told once, never trapped: the second stop in a row goes through whatever the state
    (r / "y.txt").write_text("more")
    assert _run(r, cloud_prep.STOP_HOOK, path=NO_GH, stdin='{"stop_hook_active": true}').returncode == 0
