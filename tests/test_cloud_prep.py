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
    assert "merge-approved: yes" in agents and "- No CI on push/PR (short ubuntu deploy jobs on push to main allowed, POLICY §10); the local gate is `./check.sh`." in agents.splitlines()
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


# Only AGENTS.md/CLAUDE.md were checked; a symlinked .claude/, settings file, doc or .gitignore
# made prep write outside the repo (review of #71, P1). (.gitignore goes through the same check;
# git itself no longer reads a symlinked .gitignore, so prep never gets to rewrite one.)
@pytest.mark.parametrize("link,is_dir,fix", [(".claude", True, False), (".claude/settings.json", False, False),
                                             ("docs", True, False), ("docs/cloud-setup.md", False, False),
                                             (".claude/rules", True, False)])
def test_a_destination_symlinked_out_of_the_repo_is_refused_before_any_write(tmp_path, link, is_dir, fix):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    target = outside / ("dir" if is_dir else "file")
    if is_dir:
        target.mkdir()
    r = _repo(tmp_path, {"AGENTS.md": "# a\n"})
    (r / link).parent.mkdir(parents=True, exist_ok=True)
    (r / link).symlink_to(target)  # the file targets dangle on purpose: a link to where a write would land
    before, before_out = _tree(r), _tree(outside)
    rc, out = _prep(r, fix_gitignore=fix)
    assert rc == 1 and "resolves out of the repo" in out[0], out
    assert _tree(r) == before and _tree(outside) == before_out


def test_a_symlink_inside_the_repo_is_fine(tmp_path):
    r = _repo(tmp_path, {"AGENTS.md": "# a\n", "shared/.keep": ""})
    (r / "docs").symlink_to(r / "shared")
    rc, out = _prep(r)
    assert rc == 0, out
    assert "teyla:cloud:start" in (r / "shared" / "cloud-setup.md").read_text()


def test_apply_checks_every_destination_again_before_the_first_write(tmp_path):
    r = _repo(tmp_path, {"AGENTS.md": "# a\n"})
    p = cloud_prep.plan(r, owners=OWNERS, policy_text=POLICY)
    (tmp_path / "elsewhere").mkdir()
    (r / "docs").symlink_to(tmp_path / "elsewhere")  # moved between plan and apply
    before = _tree(r)
    with pytest.raises(cloud_prep.Refused):
        cloud_prep.apply(p)
    assert _tree(r) == before and list((tmp_path / "elsewhere").iterdir()) == []


# An unmarked `merge-approved: yes` survived prep writing `no`, and check still reported drift
# (review of #71, P2): refuse and name the lines.
def test_a_conflicting_merge_line_outside_the_section_is_refused_with_its_location(tmp_path):
    r = _repo(tmp_path, {"AGENTS.md": "# a\n\nmerge-approved: yes\n", ".claude/rules/ship.md": "x\n- merge-approved: no\n"})
    before = _tree(r)
    rc, out = _prep(r, owners={"acme/other"})
    assert rc == 1 and "AGENTS.md:3" in out[0] and "ship.md" not in out[0], out
    assert _tree(r) == before
    rc, out = _prep(r)  # the owner list says yes: AGENTS.md agrees, the rules file does not
    assert rc == 1 and ".claude/rules/ship.md:2" in out[0] and "AGENTS.md:3" not in out[0], out
    (r / ".claude/rules/ship.md").write_text("x\n")
    rc, out = _prep(r)
    assert rc == 0, out
    rc, out = _prep(r, owners={"acme/other"})  # a line inside the generated section is prep's to rewrite
    assert rc == 1 and "AGENTS.md:3" in out[0]


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


@pytest.mark.parametrize("policy,want", [("**No CI on `push` or `pull_request`.** Test workflows are dispatch only.", True),
                                         ("No CI on\n  push or PR", True), ("No CI on push/PR (deploys allowed)", True),
                                         ("Deploy on push to main.", False)])
def test_no_actions_rule_is_read_from_the_policy_wording(tmp_path, policy, want):
    # The owner's policy says "No CI on `push` or `pull_request`"; it was not recognised (review of #71, P2).
    p = cloud_prep.plan(_repo(tmp_path), owners=OWNERS, policy_text=policy)
    agents = next(new for rel, _o, new, _x in p["changes"] if rel == "AGENTS.md")
    assert ("No CI on push/PR" in agents) is want


def test_actions_line_says_exactly_what_policy_10_says():
    # It said "No GitHub Actions on push or pull_request", which forbids the deploy-on-main jobs
    # §10 allows; the line is now §10's meaning, with the repo's own gate named.
    a = cloud_prep.shipping_section("no", "./check.sh", no_actions=True)
    assert ("- No CI on push/PR (short ubuntu deploy jobs on push to main allowed, POLICY §10); "
            "the local gate is `./check.sh`.") in a.splitlines()
    assert "No GitHub Actions" not in a
    b = cloud_prep.shipping_section("no", None, no_actions=True)
    assert "the local gate is the repo's tests." in b


def test_no_actions_rule_only_when_the_owner_policy_says_so(tmp_path):
    a = cloud_prep.shipping_section("yes", "./check.sh", no_actions=True)
    b = cloud_prep.shipping_section("no", None, no_actions=False)
    assert "No CI on push/PR" in a and "No CI on push/PR" not in b and "Actions" not in b
    assert "gh pr merge --merge`). If merging is refused" in a and "the owner merges" in b
    assert cloud._MERGE_LINE.findall(a) == ["yes"] and cloud._MERGE_LINE.findall(b) == ["no"]


@pytest.mark.parametrize("name,want", [("ASC_KEY_ID", "local only"), ("APNS_KEY_ID", "local only"),
                                       ("OPENAI_API_KEY", "host api.openai.com"), ("SUPABASE_URL", "environment variable"),
                                       ("MY_SERVICE_TOKEN", "fill in"), ("NODE_ENV", "environment variable"),
                                       ("NEXT_PUBLIC_SITE_URL", "environment variable"), ("OPENAI_MODEL", "environment variable")])
def test_secret_destinations(name, want):
    assert want in cloud_prep.secret_destination(name)


# Credential-bearing or unknown names were labelled "environment variable", which the doc says
# every user of the environment can read (review of #71, P1).
@pytest.mark.parametrize("name,want", [("DATABASE_URL", "local only"), ("REDIS_URL", "local only"), ("AMQP_URL", "local only"),
                                       ("SUPABASE_DB_URL", "local only"), ("CELERY_BROKER_URL", "local only"),
                                       ("SENTRY_DSN", "local only"), ("SUPABASE_SERVICE_ROLE", "API credentials"),
                                       ("MY_DB_PASSWORD", "local only"), ("APP_SECRET", "API credentials"),
                                       ("WEBHOOK_CREDENTIAL", "API credentials"),
                                       ("APP_URL", "decide by hand"), ("SOMETHING_ELSE", "decide by hand")])
def test_credential_shaped_and_unknown_names_are_never_plain_config(name, want):
    got = cloud_prep.secret_destination(name)
    assert want in got and "environment variable (config" not in got, got


def test_setup_script_is_valid_bash_and_survives_missing_files(tmp_path):
    r = _repo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n", "pnpm-lock.yaml": "", "deno.json": "{}"})
    script = "\n".join(cloud_prep.setup_script(r, ""))
    assert "pnpm install --frozen-lockfile" in script and "npm install -g deno" in script
    f = tmp_path / "setup.sh"
    f.write_text(script + "\n")
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert not any(l.startswith("[ ") and "&&" in l for l in script.splitlines())


def test_setup_script_installs_subdirectories_with_their_own_lockfile(tmp_path):
    # Only the root was installed; a web/ or worker/ with its own lockfile left the gate failing.
    r = _repo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n",
                         "web/package-lock.json": "{}", "web/yarn.lock": "",  # one Node install, the first lockfile
                         "services/api/uv.lock": "", "services/api/requirements.txt": "",
                         "apps/site/pnpm-lock.yaml": "",
                         "ios/Package.resolved": "{}",
                         "a/b/c/package-lock.json": "{}",  # depth 3: out of bounds
                         "web/node_modules/dep/package-lock.json": "{}", "vendor/lib/package-lock.json": "{}",
                         ".github/x/package-lock.json": "{}", "my app/package-lock.json": "{}"})
    (r / "linked").symlink_to(r / "web")
    lines = cloud_prep.setup_script(r, "")
    script = "\n".join(lines)
    assert "if [ -f web/package-lock.json ]; then (cd web && npm ci); fi" in lines
    assert "yarn" not in script
    assert "if [ -f services/api/uv.lock ]; then (cd services/api && uv sync --frozen); fi" in lines
    assert ("if [ -f services/api/requirements.txt ]; then uv pip install -q --system -r services/api/requirements.txt; fi"
            in lines)
    assert "if [ -f apps/site/pnpm-lock.yaml ]; then (cd apps/site && pnpm install --frozen-lockfile); fi" in lines
    assert lines.index("if ! command -v pnpm >/dev/null 2>&1; then npm install -g pnpm; fi") < \
        next(i for i, l in enumerate(lines) if "apps/site" in l)
    assert "if [ -f 'my app/package-lock.json' ]; then (cd 'my app' && npm ci); fi" in lines
    assert "# skipped on Linux: ios (Swift packages, Package.resolved only; a Mac resolves them)" in lines
    for gone in ("a/b/c", "node_modules", "vendor", ".github", "linked"):
        assert gone not in script, gone

    # Run it: every install line under set -euo pipefail, with stub tools that log their cwd.
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("uv", "npm", "pnpm", "corepack", "yarn", "curl"):
        (stubs / tool).write_text(f'#!/bin/sh\necho "{tool} $(basename "$PWD") $*" >> "{log}"\n')
        (stubs / tool).chmod(0o755)
    f = tmp_path / "setup.sh"
    f.write_text(script + "\n")
    env = dict(os.environ, PATH=f"{stubs}:/usr/bin:/bin", CLAUDE_PROJECT_DIR=str(r))
    res = subprocess.run(["bash", str(f)], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    calls = log.read_text().splitlines()
    assert "npm web ci" in calls and "uv api sync --frozen" in calls and "pnpm site install --frozen-lockfile" in calls
    assert "npm my app ci" in calls


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


def _gh_prs(tmp_path, open_=0, merged=(), closed=0):
    """A gh that answers `gh pr list --head <b> --state <s> --json … --jq …` the way the real one
    does after --jq: a count for open/closed, one head sha per line for merged."""
    heads = " ".join(merged)
    return _fake_gh(tmp_path, f"""case "$*" in
  "auth status"*) exit 0 ;;
  *"--state open"*) echo {open_} ;;
  *"--state merged"*) printf '%s\\n' {heads} ;;
  *"--state closed"*) echo {closed} ;;
  *) exit 1 ;;
esac
""")


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

    none = _gh_prs(tmp_path)
    res = _run(r, cloud_prep.STOP_HOOK, path=none)
    assert res.returncode == 2 and "No open PR for claude/brave-x" in res.stderr

    broken = _fake_gh(tmp_path, 'case "$1" in auth) exit 0;; esac\necho "HTTP 502" >&2\nexit 1\n')
    res = _run(r, cloud_prep.STOP_HOOK, path=broken)
    assert res.returncode == 2 and "gh pr list failed" in res.stderr

    unauth = tmp_path / "unauth"
    unauth.mkdir()
    (unauth / "gh").write_text("#!/bin/sh\nexit 1\n")
    (unauth / "gh").chmod(0o755)
    res = _run(r, cloud_prep.STOP_HOOK, path=f"{unauth}:{NO_GH}")
    assert res.returncode == 2 and "gh is not signed in" in res.stderr

    assert _run(r, cloud_prep.STOP_HOOK, path=_gh_prs(tmp_path, open_=1)).returncode == 0

    # told once, never trapped: the second stop in a row goes through whatever the state
    (r / "y.txt").write_text("more")
    assert _run(r, cloud_prep.STOP_HOOK, path=NO_GH, stdin='{"stop_hook_active": true}').returncode == 0


def test_stop_hook_fails_closed_without_a_base_ref(tmp_path):
    # No origin/HEAD and no origin/main: `rev-list` failed, `|| echo 0` read that as "no work",
    # and committed work was allowed to stop (review of #71, P1).
    r = _landed_repo(tmp_path)
    _git(r, "update-ref", "-d", "refs/remotes/origin/HEAD")
    _git(r, "update-ref", "-d", "refs/remotes/origin/main")
    (r / "x.txt").write_text("work")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "work")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "not on the remote" in res.stderr, res.stderr

    _git(r, "push", "-q", "-u", "origin", "claude/brave-x")
    _git(r, "update-ref", "-d", "refs/remotes/origin/main")  # the push fetched nothing back, but be sure
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "Could not compare claude/brave-x with origin/main" in res.stderr, res.stderr


def test_stop_hook_counts_commits_on_no_remote_even_without_an_upstream(tmp_path):
    r = _landed_repo(tmp_path)
    _git(r, "commit", "-q", "--allow-empty", "-m", "work")
    _git(r, "push", "-q", "origin", "claude/brave-x")  # pushed, but no upstream set
    _git(r, "commit", "-q", "--allow-empty", "-m", "more")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "1 commit(s) on claude/brave-x are not on the remote" in res.stderr, res.stderr


def test_stop_hook_pushed_means_on_this_branchs_own_remote_ref(tmp_path):
    # "Pushed" was "contained in any remote branch": work pushed only under another name (or
    # contained in a sibling branch) let the session stop with nothing on its own branch.
    r = _landed_repo(tmp_path)
    _git(r, "commit", "-q", "--allow-empty", "-m", "work")
    _git(r, "push", "-q", "origin", "HEAD:refs/heads/claude/other")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "1 commit(s) on claude/brave-x are not on the remote" in res.stderr, res.stderr

    # an upstream set to another branch (git checkout -b x origin/main does that) still counts
    # origin/<branch> as pushed once the branch is there
    _git(r, "branch", "-q", "--set-upstream-to", "origin/main")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "not on the remote" in res.stderr, res.stderr
    _git(r, "push", "-q", "origin", "claude/brave-x")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert "not on the remote" not in res.stderr and "gh is not available" in res.stderr, res.stderr

    # the upstream itself counts: pushed under another name with -u, origin/claude/brave-x is behind
    _git(r, "commit", "-q", "--allow-empty", "-m", "more")
    _git(r, "push", "-q", "-u", "origin", "HEAD:refs/heads/claude/renamed")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert "not on the remote" not in res.stderr, res.stderr


def test_stop_hook_wants_a_new_pr_for_commits_after_a_merged_or_closed_one(tmp_path):
    # `gh pr view <branch>` said MERGED and the hook let the session stop, though the commits
    # pushed after that merge were in no PR at all.
    r = _landed_repo(tmp_path)
    _git(r, "commit", "-q", "--allow-empty", "-m", "first")
    _git(r, "push", "-q", "-u", "origin", "claude/brave-x")
    merged_head = _git(r, "rev-parse", "HEAD").strip()
    res = _run(r, cloud_prep.STOP_HOOK, path=_gh_prs(tmp_path, merged=[merged_head]))
    assert res.returncode == 0, res.stderr  # squash-merged as it is: nothing after it

    _git(r, "commit", "-q", "--allow-empty", "-m", "after the merge")
    _git(r, "push", "-q", "origin", "claude/brave-x")
    res = _run(r, cloud_prep.STOP_HOOK, path=_gh_prs(tmp_path, merged=[merged_head]))
    assert res.returncode == 2 and "already merged" in res.stderr and "Open a new one" in res.stderr, res.stderr
    assert _run(r, cloud_prep.STOP_HOOK, path=_gh_prs(tmp_path, open_=1, merged=[merged_head])).returncode == 0

    res = _run(r, cloud_prep.STOP_HOOK, path=_gh_prs(tmp_path, closed=1))
    assert res.returncode == 2 and "closed without merging" in res.stderr, res.stderr

    if not shutil.which("gh", path=NO_GH):  # gh missing: still a clear message, never a crash
        res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
        assert res.returncode == 2 and "gh is not available here" in res.stderr


def test_stop_hook_on_the_default_branch_does_not_stop_with_unpushed_commits(tmp_path):
    r = _landed_repo(tmp_path)
    _git(r, "checkout", "-q", "main")
    _git(r, "commit", "-q", "--allow-empty", "-m", "oops")
    res = _run(r, cloud_prep.STOP_HOOK, path=NO_GH)
    assert res.returncode == 2 and "default branch main" in res.stderr and "git switch -c" in res.stderr


@pytest.mark.parametrize("name", ["VITE_JWT", "PUBLIC_BEARER", "VITE_GITHUB_PAT", "NEXT_PUBLIC_JWT_SECRET", "GITHUB_PAT",
                                  "WEBHOOK_HMAC"])
def test_credential_words_beat_the_public_prefix(name):
    # review of #71's fix, P1: JWT/BEARER/PAT names with a browser prefix were "config, not a secret".
    assert "environment variable" not in cloud_prep.secret_destination(name)


@pytest.mark.parametrize("name", ["NEXT_PUBLIC_PATH_PREFIX", "VITE_PATTERN"])
def test_pat_is_a_word_not_a_substring(name):
    assert "environment variable" in cloud_prep.secret_destination(name)
