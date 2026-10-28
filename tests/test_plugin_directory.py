"""The plugin as a stranger gets it from a directory: no Teyla CLI, no private names, a true privacy
section, and the checks Anthropic's directory (claude.com/docs/plugins/pre-submission-checklist) runs.

`docs/DIRECTORY.md` is the listing pack; these tests keep it and the plugin from drifting apart.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"
INSTALL_LINE = "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"
MARKETPLACE_LINE = "/plugin install teyla --marketplace zaitsew/teyla"
SHIPPED = [p for p in sorted(PLUGIN.rglob("*")) if p.is_file()]
ICON = PLUGIN / ".claude-plugin" / "icon.png"
TEXT = [p for p in SHIPPED if p != ICON]  # the icon is the one binary file the plugin ships
SKILLS = sorted(PLUGIN.glob("skills/*/SKILL.md"))
COMMANDS = sorted(PLUGIN.glob("commands/*.md"))
# Components that run the separately installed CLI, and the ones that must not need it.
NEEDS_CLI = {"adoption-review", "tidy", "wiki-pass", "harvest", "correct"}
NO_CLI = {"review", "rule"}


def name_of(path: pathlib.Path) -> str:
    return path.parent.name if path.name == "SKILL.md" else path.stem


def front_matter(path: pathlib.Path) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path}: no front matter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


# --- the manifest, the README, the license, the folder ----------------------------------------

def test_manifest_has_what_the_directory_reads():
    m = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert m["name"] == "teyla"
    for key in ("version", "description", "author", "license", "homepage", "repository",
                "documentationUrl", "supportUrl", "privacyPolicyUrl"):
        assert m.get(key), key
    assert m["license"] == "Apache-2.0"
    assert m["author"]["name"]
    for key in ("homepage", "repository", "documentationUrl", "supportUrl", "privacyPolicyUrl"):
        assert m[key].startswith("https://"), key
    assert "hooks" not in m, "hooks/hooks.json loads by itself; naming it again is a warning"


def test_license_file_in_the_plugin_folder_is_the_repo_license():
    """Same Apache-2.0 text. The copyright line in the plugin copy names "The Teyla authors": the author
    is in plugin.json, and a personal name would trip the private-terms guard in a second file."""
    strip = lambda s: re.sub(r"(?m)^(\s+Copyright 2026 ).*$", r"\1<holder>", s)  # noqa: E731
    assert strip((PLUGIN / "LICENSE").read_text()) == strip((ROOT / "LICENSE").read_text())


def test_readme_meets_the_directory_checks():
    text = (PLUGIN / "README.md").read_text()
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    assert len(prose.split()) >= 40
    assert MARKETPLACE_LINE in text, "claude plugin validate asks for this line"
    assert INSTALL_LINE in text, "the CLI install line the skills print"
    assert "\n## Privacy\n" in text and "### Network" in text and "### What it writes" in text
    # privacyPolicyUrl points at this anchor
    assert json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["privacyPolicyUrl"].endswith(
        "plugin/README.md#privacy")


def test_marketplace_lists_the_plugin_folder():
    mp = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert [(p["name"], p["source"]) for p in mp["plugins"]] == [("teyla", "./plugin")]


def test_plugin_folder_passes_the_file_checks():
    assert len(SHIPPED) <= 512
    for p in SHIPPED:
        rel = p.relative_to(PLUGIN)
        assert not p.is_symlink(), rel
        assert p.name not in {".DS_Store", "Thumbs.db", "desktop.ini"} and "__MACOSX" not in rel.parts, rel
        assert p.stat().st_size < 256 * 1024, rel
        assert p == ICON or b"\0" not in p.read_bytes(), f"{rel} is binary: the directory holds binary files for a reviewer"
        assert not re.search(r'[:<>"|?*]|[. ]$', p.name), f"{rel}: name invalid on Windows"
    assert not (PLUGIN / "bin").exists()
    lower = [str(p.relative_to(PLUGIN)).lower() for p in SHIPPED]
    assert len(lower) == len(set(lower)), "two names differ only by case"


def test_mcp_config_registers_only_the_local_stdio_server():
    cfg = json.loads((PLUGIN / ".mcp.json").read_text())
    assert cfg == {"mcpServers": {"teyla": {"command": "teyla", "args": ["mcp"]}}}


def test_icon_is_a_square_png_under_2_mb():
    data = ICON.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    assert width == height >= 512
    assert len(data) < 2 * 1024 * 1024


@pytest.mark.parametrize("path", SKILLS + COMMANDS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_front_matter_is_plain_yaml(path):
    """A description with ': ' or an argument-hint that starts with '[' does not parse as YAML, and
    the directory blocks front matter that does not parse."""
    fm = front_matter(path)
    assert fm.get("description"), path
    for key, value in fm.items():
        if value.startswith(('"', "'")):
            continue
        assert ": " not in value, f"{path}: unquoted {key} contains ': '"
        assert not re.match(r"[\[\]{}*&!|>%@`#,]", value), f"{path}: unquoted {key} starts with a YAML indicator"
        assert " #" not in value, f"{path}: unquoted {key} contains ' #'"
    if path.name == "SKILL.md":
        assert fm["name"] == path.parent.name


# --- nothing private ships ----------------------------------------------------------------------

# Generic patterns only. Product and person names live in the private-terms file outside the repo
# (see scripts/leak_check.py); the test below runs that list too when the file exists.
PRIVATE_PATHS = re.compile(r"~/ops\b|/ops/|/Users/|/home/[a-z]")


def test_no_private_name_or_path_ships_in_the_plugin_folder():
    hits = [f"{p.relative_to(ROOT)}:{n}: {line.strip()[:80]}"
            for p in TEXT for n, line in enumerate(p.read_text().splitlines(), 1) if PRIVATE_PATHS.search(line)]
    assert hits == []


def test_the_private_term_list_finds_nothing_in_the_plugin_folder():
    sys.path.insert(0, str(ROOT / "scripts"))
    import leak_check as lc
    cfg = lc.Config()
    lc.load_terms(cfg)
    lc.load_allow(cfg, ROOT)
    if not cfg.terms:
        pytest.skip("no private term list on this machine")
    found = []
    for p in TEXT + [ROOT / "docs" / "DIRECTORY.md"]:
        found += lc.scan_lines(str(p.relative_to(ROOT)), str(p.relative_to(ROOT)),
                               enumerate(p.read_text().splitlines(), 1), cfg)
    assert [f for f in found if "LICENSE" not in f.path] == []


# --- no CLI: every skill and command says so and stops ------------------------------------------

def preflight_block(text: str) -> str:
    m = re.search(r"```sh\n(\{ command -v teyla.*?)\n```", text, re.S)
    assert m, "no CLI check block"
    return m.group(1)


def first_cli_use(text: str):
    """The first `teyla <word>` in the body, outside the front matter and the check block (both blanked
    out so offsets still match the original text)."""
    blank = lambda m: " " * len(m.group(0))  # noqa: E731
    body = re.sub(r"\A---\n.*?\n---\n", blank, text, flags=re.S)
    body = re.sub(r"```sh\n\{ command -v teyla.*?```", blank, body, flags=re.S)
    return re.search(r"(?<![\w/.])teyla [a-z]", body)


@pytest.mark.parametrize("path", SKILLS + COMMANDS, ids=lambda p: name_of(p))
def test_cli_dependence_is_checked_first(path):
    text = path.read_text()
    name = name_of(path)
    use = first_cli_use(text)
    if name in NO_CLI:
        assert use is None and "command -v teyla" not in text, f"{name} must not need the CLI"
        return
    assert name in NEEDS_CLI and use
    assert INSTALL_LINE in text
    assert text.index("command -v teyla") < use.start(), "check the CLI before using it"
    assert "teyla: MISSING" in text and "~/.local/bin/teyla" in text


def run_sh(script: str, path: str, home: pathlib.Path) -> str:
    env = {"PATH": path, "HOME": str(home)}
    return subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, env=env, timeout=10).stdout.strip()


@pytest.mark.parametrize("path", [p for p in SKILLS + COMMANDS if name_of(p) in NEEDS_CLI], ids=lambda p: name_of(p))
def test_the_cli_check_reports_missing_with_a_stripped_path_and_found_with_one(path, tmp_path):
    block = preflight_block(path.read_text())
    home = tmp_path / "home"; home.mkdir()
    assert run_sh(block, str(tmp_path / "nothing"), home) == "teyla: MISSING"
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "teyla").write_text("#!/bin/sh\n"); (bindir / "teyla").chmod(0o755)
    assert run_sh(block, str(bindir), home) == "teyla: found"
    # a uv tool install that is not on a GUI app's PATH
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "teyla").write_text("#!/bin/sh\n")
    ls_dir = tmp_path / "lsbin"; ls_dir.mkdir()
    (ls_dir / "ls").symlink_to(shutil.which("ls"))
    assert run_sh(block, str(ls_dir), home) == "teyla: found"


# --- no CLI: hooks stay silent and exit 0 --------------------------------------------------------

def hook_sandbox(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """The plugin as Claude Code caches it: only the plugin folder, no src/ beside it, HOME empty, no teyla."""
    cache = tmp_path / "cache" / "teyla" / "teyla" / "0.29.0"
    shutil.copytree(PLUGIN, cache)
    home = tmp_path / "home"; home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(cache), "TMPDIR": str(tmp_path / "tmp")}
    (tmp_path / "tmp").mkdir()
    assert not any(pathlib.Path(d, "teyla").exists() for d in ("/usr/bin", "/bin"))
    return cache, env


PAYLOADS = {
    "session-start.sh": {"hook_event_name": "SessionStart", "source": "startup"},
    "capture-correction.sh": {"hook_event_name": "UserPromptSubmit", "prompt": "no, that's wrong, redo it"},
    "capture-intent.sh": {"hook_event_name": "UserPromptSubmit", "prompt": "I want " + "a long plan " * 60},
    "pre-tool-use.sh": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
    "machine-guard.sh": {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                         "tool_input": {"command": "xcodebuild -scheme App build"}},
    "land-check.sh": {"hook_event_name": "Stop", "session_id": "s1"},
    "context-budget.sh": {"hook_event_name": "PostToolUse", "session_id": "s1"},
}


def test_every_hook_script_has_a_payload_here():
    assert sorted(PAYLOADS) == sorted(p.name for p in (PLUGIN / "hooks").glob("*.sh"))


@pytest.mark.parametrize("script", sorted(PAYLOADS))
def test_without_the_cli_a_hook_exits_zero_and_says_nothing(script, tmp_path):
    cache, env = hook_sandbox(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    payload = dict(PAYLOADS[script], cwd=str(work), transcript_path=str(work / "none.jsonl"))
    proc = subprocess.run(["sh", str(cache / "hooks" / script)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=work, env=env, timeout=20)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert not (pathlib.Path(env["HOME"]) / ".teyla").exists(), "nothing is written without the CLI"


def test_every_command_in_hooks_json_is_one_of_the_scripts_above():
    cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    cmds = {h["command"] for groups in cfg["hooks"].values() for g in groups for h in g["hooks"]}
    assert cmds and all(re.fullmatch(r'sh "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/[a-z-]+\.sh"', c) for c in cmds)
    assert {re.search(r"hooks/([a-z-]+\.sh)", c).group(1) for c in cmds} == set(PAYLOADS)


def test_hook_scripts_name_no_path_above_the_plugin_and_run_no_inline_python():
    """The directory validator blocks `..` in a command's path (COMMAND_PATH_ABOVE_PLUGIN) and a path the shell
    computes (COMMAND_PATH_COMPUTED, `dirname "$0"`, an inline `python3 -c` program). The code the hooks run
    is the installed package's, reached with `python -m`."""
    bad = re.compile(r"\.\./|\bpython3? +-c\b|\"\$py\" +-c\b|dirname \"\$0\"|\$\{0%|\bperl +-e\b|\bnode +-e\b")
    hits = [f"{p.name}:{n}: {line.strip()[:80]}" for p in sorted((PLUGIN / "hooks").glob("*.sh"))
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if not line.lstrip().startswith("#") and bad.search(line)]
    assert hits == []


def test_session_start_prints_only_the_rule_count_without_the_cli(tmp_path):
    cache, env = hook_sandbox(tmp_path)
    repo = tmp_path / "repo"; (repo / ".claude" / "rules").mkdir(parents=True)
    (repo / ".claude" / "rules" / "a.md").write_text("- x\n")
    proc = subprocess.run(["sh", str(cache / "hooks" / "session-start.sh")], input="", capture_output=True,
                          text=True, cwd=repo, env=env, timeout=10)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "teyla: 1 rule file(s) in .claude/rules/\n", "")


# --- the background chain starts only on a machine where Teyla was set up -----------------------

def fake_cli(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    bindir = tmp_path / "fakebin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    (bindir / "teyla").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    (bindir / "teyla").chmod(0o755)
    return bindir, log


def start_session(tmp_path, env, bindir):
    cache = pathlib.Path(env["CLAUDE_PLUGIN_ROOT"])
    env = dict(env, PATH=f"{bindir}:/usr/bin:/bin")
    return subprocess.run(["sh", str(cache / "hooks" / "session-start.sh")], input="", capture_output=True, text=True,
                          cwd=tmp_path, env=env, timeout=10)


def test_installing_the_cli_alone_starts_no_background_work(tmp_path):
    """`routine catch-up` can write launchd agents and `update --check` reaches api.github.com: neither
    may start before the owner ran `teyla policy init` or `teyla config set`."""
    _cache, env = hook_sandbox(tmp_path)
    bindir, log = fake_cli(tmp_path)
    proc = start_session(tmp_path, env, bindir)
    time.sleep(1.0)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    assert not log.exists(), log.read_text() if log.exists() else ""


def test_a_set_up_machine_still_gets_the_daily_chain(tmp_path):
    _cache, env = hook_sandbox(tmp_path)
    bindir, log = fake_cli(tmp_path)
    teyla_dir = pathlib.Path(env["HOME"]) / ".teyla"; teyla_dir.mkdir()
    (teyla_dir / "config.toml").write_text('code_root = "~/repos"\n')
    assert start_session(tmp_path, env, bindir).returncode == 0
    for _ in range(40):
        if log.exists() and "routine catch-up" in log.read_text():
            break
        time.sleep(0.25)
    assert "update --check --quiet" in log.read_text() and "routine catch-up --quiet" in log.read_text()


# --- the privacy section is true -----------------------------------------------------------------

NETWORK = re.compile(r"\b(curl|wget|socket|urllib|requests|http\.client|nc|netcat|telnet|ftp|scp|rsync|ssh)\b")


def test_no_plugin_script_or_skill_makes_a_network_call():
    files = [p for p in TEXT if p.suffix in {".sh", ".py", ".md", ".json"} and p.name not in {"README.md", "LICENSE"}]
    hits = []
    for p in files:
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if NETWORK.search(line):
                hits.append(f"{p.relative_to(PLUGIN)}:{n}: {line.strip()[:80]}")
            for url in re.findall(r"https?://[^\s)\"`>]+", line):
                if not url.startswith("https://github.com/zaitsew") and "LICENSE" not in p.name:
                    hits.append(f"{p.relative_to(PLUGIN)}:{n}: unexpected URL {url}")
    assert hits == []


def test_readme_names_every_path_the_hooks_write():
    readme = (PLUGIN / "README.md").read_text()
    hooks = "\n".join(p.read_text() for p in (PLUGIN / "hooks").iterdir() if p.suffix in {".sh", ".py"})
    assert "teyla-land-check" in hooks and "handoff" in hooks
    # corrections and intent are written by the CLI code the capture hooks import
    assert (ROOT / "src/teyla/corrections.py").read_text().count('/ "corrections"')
    assert (ROOT / "src/teyla/intent.py").read_text().count('/ "intent"')
    for written in ("~/.teyla/corrections/", "~/.teyla/intent/", "~/.teyla/handoff/", "$TMPDIR/teyla-land-check/"):
        assert written in readme, written
    for prose in ("api.github.com", "TEYLA_SAFE=1", "~/.teyla/config.toml", "cross-provider"):
        assert prose in readme


# --- the OpenAI upload archive -------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "scripts"))
import build_openai_plugin as oa  # noqa: E402


@pytest.mark.parametrize("profile", ["portable", "full"])
def test_openai_archive_is_a_skills_only_plugin(profile, tmp_path):
    import zipfile
    out = oa.build(profile, tmp_path)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        tops = {n.split("/")[0] for n in names}
        manifest = json.loads(z.read("teyla/.claude-plugin/plugin.json"))
        skills = {n.split("/")[2] for n in names if n.endswith("/SKILL.md")}
        bodies = "\n".join(z.read(n).decode() for n in names if n.endswith(".md"))
    assert tops == {"teyla"} and manifest["description"].strip()
    assert not [n for n in names if "/hooks/" in n or "/commands/" in n]
    assert not [n for n in names if "mcp" in n.lower()], "a skills-only upload carries no MCP config"
    assert skills == (set(oa.PROFILES[profile]["skills"]) | set(oa.PROFILES[profile]["commands"]))
    assert "$ARGUMENTS" not in bodies and '"$1"' not in bodies
    assert {"review", "rule"} <= skills
    assert (profile == "full") == bool(skills & NEEDS_CLI)


def test_openai_archive_is_reproducible(tmp_path):
    a = oa.build("portable", tmp_path / "a").read_bytes()
    b = oa.build("portable", tmp_path / "b").read_bytes()
    assert a == b


def test_every_skill_in_the_portable_profile_needs_no_cli():
    spec = oa.PROFILES["portable"]
    assert set(spec["skills"]) | set(spec["commands"]) == NO_CLI


# ---------- docs/DIRECTORY.md ----------

DIRECTORY = ROOT / "docs" / "DIRECTORY.md"


def test_directory_pack_matches_the_manifest():
    text = DIRECTORY.read_text()
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["description"] in text
    assert f"| Version | {manifest['version']} |" in text
    for key in ("documentationUrl", "supportUrl", "privacyPolicyUrl"):
        assert manifest[key] in text


def test_starter_prompts_fit_the_limit():
    text = DIRECTORY.read_text()
    section = text.split("## 4. Starter prompts", 1)[1].split("\n## ", 1)[0]
    prompts = re.findall(r"^\d\. `(.+)` \(\d+\)$", section, re.M)
    assert len(prompts) == 3
    assert all(len(p) <= 128 for p in prompts)
    for p, n in zip(prompts, re.findall(r"\((\d+)\)$", section, re.M)):
        assert len(p) == int(n)
