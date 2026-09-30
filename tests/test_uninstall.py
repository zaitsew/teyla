"""`teyla uninstall` against a machine Teyla really installed itself on.

A fake HOME gets the owner's own files first (a CLAUDE.md, Hermes config, a Cursor hook and
skill of their own, another plugin, a foreign LaunchAgent). Then the real writers run, as the
onboarding does — `policy init`, `policy sync`, `harness sync`, `plugin install`, `routine
install`, a trigger plist — in a subprocess whose HOME is the fake one, with `launchctl` and
`claude` replaced by recording stubs on PATH and sockets disabled. `teyla uninstall` must then
bring every file the owner had back byte for byte, and leave nothing of Teyla's except what it
reports and never deletes (~/.agents/POLICY.md, backups, repo-level .teyla/ and rules).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"

LAUNCHCTL = r"""#!/bin/sh
echo "$*" >> "$FAKE_LOG"
state="$FAKE_STATE"; touch "$state"
case "$1" in
  list) while read -r l; do printf -- '-\t0\t%s\n' "$l"; done < "$state" ;;
  bootstrap) basename "$3" .plist >> "$state" ;;
  bootout) grep -vx "${2##*/}" "$state" > "$state.tmp"; mv "$state.tmp" "$state" ;;
esac
exit 0
"""

CLAUDE = r"""#!/bin/sh
echo "claude $*" >> "$FAKE_LOG"
exit 0
"""

OWNER_CLAUDE_MD = "# How I work\n\nMerge only when I say so.\n"
OWNER_HERMES_CFG = "model: some-model\nterminal:\n  backend: local\n"
OWNER_SOUL = "I am Hermes.\n"
OWNER_CURSOR_HOOKS = {"version": 1, "hooks": {"sessionStart": [{"command": "/usr/local/bin/mine.sh"}]}}
TRIGGER_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Label</key><string>com.teyla.demo.nightly</string>
<key>ProgramArguments</key><array><string>/x/bin/teyla</string><string>run</string><string>demo:nightly</string></array>
</dict></plist>
"""


def snapshot(root: pathlib.Path) -> dict[str, str]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = pathlib.Path(dirpath, name)
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = "link:" + os.readlink(p)
            elif p.is_file():
                data = p.read_bytes()
                if p.suffix == ".json":
                    # the registries are rewritten sorted and indented: compare what they say
                    try:
                        data = json.dumps(json.loads(data), sort_keys=True).encode()
                    except ValueError:
                        pass
                out[rel] = hashlib.sha256(data).hexdigest()
            else:
                out[rel] = "dir"
    return out


def _env(root: pathlib.Path, with_claude: bool) -> dict:
    fakebin = root / "bin"
    fakebin.mkdir(exist_ok=True)
    (fakebin / "launchctl").write_text(LAUNCHCTL)
    (fakebin / "launchctl").chmod(0o755)
    if with_claude:
        (fakebin / "claude").write_text(CLAUDE)
        (fakebin / "claude").chmod(0o755)
    guard = root / "netguard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def _deny(self, *a, **k):\n    raise OSError('network disabled in test')\n"
        "socket.socket.connect = _deny\n")
    return {"HOME": str(root / "home"), "PATH": f"{fakebin}:/usr/bin:/bin",
            "PYTHONPATH": f"{guard}{os.pathsep}{SRC}", "LANG": "C.UTF-8", "USER": "tester",
            "FAKE_LOG": str(root / "calls.log"), "FAKE_STATE": str(root / "launchd.state"),
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def teyla(env: dict, *argv, ok=True) -> str:
    r = subprocess.run([sys.executable, "-m", "teyla", *argv], env=env, cwd=env["HOME"],
                       capture_output=True, text=True, timeout=120)
    if ok:
        assert r.returncode == 0, f"teyla {' '.join(argv)}: {r.stdout}\n{r.stderr}"
    return r.stdout


def owner_machine(home: pathlib.Path) -> None:
    """What the owner had before Teyla: none of it may change."""
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text(OWNER_CLAUDE_MD)
    (home / ".claude" / "plugins").mkdir()
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"other@elsewhere": [{"scope": "user", "installPath": "/nowhere", "version": "1.0"}]}}))
    (home / ".claude" / "plugins" / "known_marketplaces.json").write_text(json.dumps(
        {"elsewhere": {"source": {"source": "github", "repo": "someone/elsewhere"}}}))
    for h in (".codex", ".grok"):
        (home / h).mkdir()
    (home / ".codex" / "skills").mkdir()  # there before Teyla, empty: it must survive
    (home / ".hermes").mkdir()
    (home / ".hermes" / "config.yaml").write_text(OWNER_HERMES_CFG)
    (home / ".hermes" / "SOUL.md").write_text(OWNER_SOUL)
    (home / ".cursor" / "skills" / "my-skill").mkdir(parents=True)
    (home / ".cursor" / "skills" / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\n---\nmine\n")
    (home / ".cursor" / "hooks.json").write_text(json.dumps(OWNER_CURSOR_HOOKS, indent=2) + "\n")
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "com.example.mine.plist").write_text("<plist>mine</plist>\n")
    (home / "repos" / "demo").mkdir(parents=True)
    (home / "repos" / "demo" / "README.md").write_text("demo\n")


def install_everything(env: dict, home: pathlib.Path) -> None:
    """The onboarding's writes, by the real code paths."""
    teyla(env, "policy", "init", "--owner", "Tester")
    teyla(env, "policy", "sync")
    teyla(env, "harness", "sync")
    teyla(env, "plugin", "install", str(REPO))
    teyla(env, "routine", "install")
    (home / "Library" / "LaunchAgents" / "com.teyla.demo.nightly.plist").write_text(TRIGGER_PLIST)
    (home / "Library" / "Logs" / "com.teyla.demo.nightly.log").write_text("ran\n")
    # the same, installed from a checkout's `python -m teyla`: argv[0] is .../teyla/__main__.py
    (home / "Library" / "LaunchAgents" / "com.teyla.demo.hourly.plist").write_text(
        TRIGGER_PLIST.replace("com.teyla.demo.nightly", "com.teyla.demo.hourly")
                     .replace("/x/bin/teyla", "/x/teyla/src/teyla/__main__.py"))
    # what the capture hook and `teyla rule` leave in a repo
    (home / "repos" / "demo" / ".teyla").mkdir()
    (home / "repos" / "demo" / ".teyla" / "corrections.jsonl").write_text('{"text": "no"}\n')
    (home / "repos" / "demo" / ".claude" / "rules").mkdir(parents=True)
    (home / "repos" / "demo" / ".claude" / "rules" / "use-pnpm.md").write_text("---\nglobs: **\n---\n\n- Use pnpm.\n")


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    owner_machine(home)
    before = snapshot(home)
    env = _env(tmp_path, with_claude=False)
    install_everything(env, home)
    return dict(home=home, env=env, before=before, root=tmp_path)


def _installed_is_real(home: pathlib.Path) -> None:
    """Guard against a vacuous pass: the writers did write."""
    assert (home / ".teyla" / "config.toml").exists()
    assert (home / ".codex" / "AGENTS.md").is_symlink()
    assert "@~/.agents/POLICY.md" in (home / ".claude" / "CLAUDE.md").read_text()
    assert "## Operating policy" in (home / ".hermes" / "SOUL.md").read_text()
    assert "teyla-hooks begin" in (home / ".hermes" / "config.yaml").read_text()
    assert (home / ".grok" / "hooks" / "teyla.json").exists()
    assert (home / ".cursor" / "skills" / "teyla-policy" / "SKILL.md").exists()
    assert (home / ".codex" / "skills" / "teyla-harvest" / "SKILL.md").exists()
    assert "teyla@teyla" in (home / ".claude" / "plugins" / "installed_plugins.json").read_text()
    assert (home / "Library" / "LaunchAgents" / "com.zaitsew.teyla.daily.plist").exists()


def test_dry_lists_every_write_and_touches_nothing(machine):
    home, env = machine["home"], machine["env"]
    _installed_is_real(home)
    mid = snapshot(home)
    out = teyla(env, "uninstall", "--dry")
    assert snapshot(home) == mid, "--dry changed the machine"
    for needle in ("com.zaitsew.teyla.daily.plist", "com.zaitsew.teyla.weekly.plist", "com.teyla.demo.nightly.plist",
                   "com.teyla.demo.hourly.plist",
                   ".claude/CLAUDE.md", ".codex/AGENTS.md", ".grok/AGENTS.md", ".hermes/SOUL.md", ".hermes/config.yaml",
                   ".cursor/hooks.json", ".grok/hooks/teyla.json", "teyla-policy", "teyla-harvest",
                   "installed_plugins.json[teyla@teyla]", "known_marketplaces.json[teyla]", f"{home}/.teyla",
                   ".agents/POLICY.md", "repos/demo/.teyla", "repos/demo/.claude/rules"):
        assert needle in out, f"--dry does not mention {needle}"
    assert "would remove" in out and "would edit" in out
    if sys.platform == "darwin":
        assert "would unload com.zaitsew.teyla.daily" in out


def test_uninstall_restores_the_owners_files_and_leaves_only_what_it_reports(machine):
    home, env, before = machine["home"], machine["env"], machine["before"]
    out = teyla(env, "uninstall")
    after = snapshot(home)
    changed = {k for k in before if after.get(k) != before[k]}
    assert changed == set(), f"owner's files changed or removed: {sorted(changed)}"
    left = {k for k in after if k not in before}
    allowed_prefixes = (".agents", "repos/demo/.teyla", "repos/demo/.claude", "Library/Logs")
    unexpected = {k for k in left if not k.startswith(allowed_prefixes) and ".bak-" not in k and after[k] != "dir"}
    assert unexpected == set(), f"Teyla files left behind: {sorted(unexpected)}\n{out}"
    # what stays is reported, and never deleted
    assert (home / ".agents" / "POLICY.md").exists() and "keep    " + str(home / ".agents" / "POLICY.md") in out
    assert (home / "repos" / "demo" / ".teyla" / "corrections.jsonl").exists()
    assert (home / "repos" / "demo" / ".claude" / "rules" / "use-pnpm.md").exists()
    # the plugin's marketplace here is a directory source — somebody's checkout, never deleted
    assert (REPO / "plugin").is_dir()
    calls = pathlib.Path(env["FAKE_LOG"]).read_text() if pathlib.Path(env["FAKE_LOG"]).exists() else ""
    if sys.platform == "darwin":
        assert "bootout gui/" in calls and "com.zaitsew.teyla.daily" in calls
        assert pathlib.Path(env["FAKE_STATE"]).read_text().strip() == "", "a Teyla agent is still loaded"


def test_uninstall_is_idempotent(machine):
    env = machine["env"]
    teyla(env, "uninstall")
    mid = snapshot(machine["home"])
    out = teyla(env, "uninstall")
    assert out.startswith("nothing of Teyla's left to remove")
    assert snapshot(machine["home"]) == mid


def test_keep_data_keeps_the_state_but_unwires_everything(machine):
    home, env = machine["home"], machine["env"]
    teyla(env, "uninstall", "--keep-data")
    assert (home / ".teyla" / "config.toml").exists()
    assert not (home / ".teyla" / "hooks").exists() and not (home / ".teyla" / "daily.sh").exists()
    assert not (home / "Library" / "LaunchAgents" / "com.zaitsew.teyla.daily.plist").exists()
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert (home / ".claude" / "CLAUDE.md").read_text() == OWNER_CLAUDE_MD


def test_with_claude_on_path_the_plugin_goes_through_the_claude_cli(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    owner_machine(home)
    env = _env(tmp_path, with_claude=True)
    teyla(env, "plugin", "install", str(REPO))
    out = teyla(env, "uninstall")
    calls = pathlib.Path(env["FAKE_LOG"]).read_text()
    assert "claude plugin uninstall teyla@teyla" in calls
    assert "claude plugin marketplace remove teyla" in calls
    assert "run claude plugin uninstall teyla@teyla" in out


def test_refuses_what_is_not_recognisably_teylas(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(tmp_path, with_claude=False)
    (home / ".codex").mkdir()
    (home / ".codex" / "AGENTS.md").write_text("my own codex instructions\n")
    (home / ".grok").mkdir()
    (home / ".grok" / "AGENTS.md").symlink_to(home / ".codex" / "AGENTS.md")
    (home / ".grok" / "hooks").mkdir()
    (home / ".grok" / "hooks" / "teyla.json").write_text(json.dumps(
        {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "/usr/local/bin/other.sh"}]}]}}))
    (home / ".cursor" / "skills" / "teyla-custom").mkdir(parents=True)
    (home / ".cursor" / "skills" / "teyla-custom" / "SKILL.md").write_text("---\nname: teyla-custom\n---\nmine\n")
    (home / ".hermes").mkdir()
    (home / ".hermes" / "SOUL.md").write_text("I am Hermes.\n\n## Operating policy\nMy own words now.\n")
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "com.teyla.lookalike.plist").write_text("<plist>not a teyla run</plist>\n")
    # a label and a `run` argument are not enough: the program must be teyla (Codex review P2)
    (home / "Library" / "LaunchAgents" / "com.teyla.other.plist").write_text(
        TRIGGER_PLIST.replace("com.teyla.demo.nightly", "com.teyla.other").replace("/x/bin/teyla", "/usr/bin/foo"))
    # ... and its log is not Teyla's either
    (home / "Library" / "Logs").mkdir(parents=True)
    (home / "Library" / "Logs" / "com.teyla.other.log").write_text("foo ran\n")
    # a user's skill that quotes the generated-by marker in its body is still the user's
    (home / ".cursor" / "skills" / "my-notes").mkdir(parents=True)
    (home / ".cursor" / "skills" / "my-notes" / "SKILL.md").write_text(
        "---\nname: my-notes\n---\n\n# Notes\n\n" + "\n".join(f"line {i}" for i in range(12))
        + "\n\nTeyla stamps its copies with `<!-- generated by `teyla harness sync` ... -->`.\n")
    # a teyla@ registry row whose installPath points outside ~/.claude/plugins/cache
    ext = tmp_path / "ext" / "mine"
    ext.mkdir(parents=True)
    (ext / "PRECIOUS").write_text("keep me\n")
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"scope": "user", "installPath": str(ext), "version": "0.1"}]}}))
    before = snapshot(home)
    out = teyla(env, "uninstall")
    after = snapshot(home)
    # the one expected change: the teyla@ row itself goes (and a same-day registry backup appears)
    reg = ".claude/plugins/installed_plugins.json"
    assert json.loads((home / reg).read_text())["plugins"] == {}
    assert {k for k in before.keys() | after.keys() if after.get(k) != before.get(k)} - {reg} == {f"{reg}.bak-{__import__('datetime').date.today()}"}, out
    assert (ext / "PRECIOUS").read_text() == "keep me\n", "an installPath outside the plugin cache was deleted"
    assert "log of a com.teyla.* job that is not Teyla's" in out
    for needle in ("not a symlink to ~/.agents/POLICY.md", "no generated-by marker", "not the text Teyla writes",
                   "does not only run ~/.teyla/hooks", "does not run `teyla run`"):
        assert needle in out


def test_claude_md_import_line_the_owner_placed_is_removed_alone(tmp_path, monkeypatch):
    from teyla import uninstall
    # in-process: never read this machine's launchd or find its `claude`
    monkeypatch.setattr(uninstall, "_launchctl_list", lambda: "")
    monkeypatch.setattr(uninstall, "_claude_bin", lambda: None)
    monkeypatch.setattr(uninstall, "_run", lambda cmd: (_ for _ in ()).throw(AssertionError(cmd)))
    home = tmp_path
    (home / ".claude").mkdir()
    p = home / ".claude" / "CLAUDE.md"
    p.write_text("# Mine\n\n@~/.agents/POLICY.md\n\nMore of mine.\n")
    steps = [s for s in uninstall.plan(home) if s.fn]
    assert [s.verb for s in steps] == ["edit"]
    steps[0].fn()
    assert p.read_text() == "# Mine\n\n\nMore of mine.\n"
    assert list((home / ".claude").glob("CLAUDE.md.bak-*"))


def test_a_failed_step_is_reported_and_fails_the_command(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    owner_machine(home)
    env = _env(tmp_path, with_claude=True)
    teyla(env, "plugin", "install", str(REPO))
    (tmp_path / "bin" / "claude").write_text('#!/bin/sh\necho "not logged in" >&2\nexit 3\n')
    teyla(env, "harness", "sync")
    r = subprocess.run([sys.executable, "-m", "teyla", "uninstall"], env=env, cwd=env["HOME"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, r.stdout
    assert "FAILED  run claude plugin uninstall teyla@teyla: exit 3: not logged in" in r.stdout
    assert "step(s) FAILED" in r.stdout
    # the rest still ran
    assert not (home / ".codex" / "skills" / "teyla-harvest").exists()


def _in_process(monkeypatch):
    from teyla import uninstall
    monkeypatch.setattr(uninstall, "_launchctl_list", lambda: "")
    monkeypatch.setattr(uninstall, "_claude_bin", lambda: None)
    monkeypatch.setattr(uninstall, "_run", lambda cmd: (_ for _ in ()).throw(AssertionError(cmd)))
    return uninstall


def test_a_skill_that_shows_the_marker_in_a_fenced_example_is_not_teylas(tmp_path, monkeypatch):
    # review of #67, P1: the marker inside the first lines of the body, but not as the first
    # nonblank line after the frontmatter, must not get the user's whole skill directory deleted
    uninstall = _in_process(monkeypatch)
    home = tmp_path
    mine = home / ".cursor" / "skills" / "my-docs"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text(
        "---\nname: my-docs\n---\n\nTeyla writes this:\n\n```\n<!-- generated by `teyla harness sync` (teyla 1) -->\n```\n")
    (mine / "notes.txt").write_text("mine\n")
    theirs = home / ".cursor" / "skills" / "teyla-x"
    theirs.mkdir()
    (theirs / "SKILL.md").write_text(
        "---\nname: teyla-x\ndescription: d\n---\n\n<!-- generated by `teyla harness sync` (teyla 1) from p -->\n\nbody\n")
    steps = [s for s in uninstall.plan(home) if s.fn]
    assert [s.target for s in steps] == [str(theirs)]
    assert not uninstall._generated_by_teyla("<!-- generated by `teyla policy sync` -->\nno frontmatter\n")
    for s in steps:
        s.fn()
    assert (mine / "notes.txt").exists() and not theirs.exists()


def test_a_failed_cache_deletion_keeps_the_registry_row_so_a_rerun_retries(tmp_path, monkeypatch):
    # review of #67, P2: the row went first, so a cache that could not be deleted was orphaned
    uninstall = _in_process(monkeypatch)
    home = tmp_path
    plugins = home / ".claude" / "plugins"
    cache = plugins / "cache" / "teyla" / "teyla" / "1.0"
    cache.mkdir(parents=True)
    (cache / "f").write_text("x\n")
    reg = plugins / "installed_plugins.json"
    reg.write_text(json.dumps({"version": 2, "plugins": {"teyla@teyla": [
        {"scope": "user", "installPath": str(cache), "version": "1.0"}]}}))
    real = uninstall.shutil.rmtree
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    lines, failed = uninstall.run(home=home)
    assert failed == 1 and "registry row kept" in "\n".join(lines)
    assert "teyla@teyla" in json.loads(reg.read_text())["plugins"] and cache.is_dir()
    monkeypatch.setattr(uninstall.shutil, "rmtree", real)
    lines, failed = uninstall.run(home=home)
    assert failed == 0 and not cache.exists()
    assert json.loads(reg.read_text())["plugins"] == {}


def test_codex_hooks_lose_only_teylas_handlers(tmp_path):
    # #61 wires ~/.codex/hooks.json; uninstall (#67) predates it. A user's handler that shares a
    # group with Teyla's stays, with its matcher; a file with only Teyla's left goes.
    from teyla import harness, uninstall
    home = tmp_path
    ours = str(home / ".teyla" / "hooks" / "capture-correction.sh")
    cx = home / ".codex" / "hooks.json"
    cx.parent.mkdir(parents=True)
    cx.write_text(json.dumps({"description": harness.CODEX_DESCRIPTION, "hooks": {
        "UserPromptSubmit": [{"matcher": "*", "hooks": [{"type": "command", "command": ours},
                                                        {"type": "command", "command": "/usr/local/bin/mine"}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": ours + " --codex"}]}]}}))
    [step] = [s for s in uninstall._hooks(home) if s.target == str(cx)]
    step.fn()
    assert json.loads(cx.read_text())["hooks"] == {
        "UserPromptSubmit": [{"matcher": "*", "hooks": [{"type": "command", "command": "/usr/local/bin/mine"}]}]}
    cx.write_text(json.dumps({"description": harness.CODEX_DESCRIPTION, "hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": ours}]}]}}))
    [step] = [s for s in uninstall._hooks(home) if s.target == str(cx)]
    step.fn()
    assert not cx.exists()
