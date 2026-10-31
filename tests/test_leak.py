"""`teyla leak`: the surfaces, classes, severities, masking, de-duplication, exit codes and gitleaks merge.
Every private term here is invented. Fixtures that look like leaks are built at run time, so this file
is clean under the guard (scripts/leak_check.py)."""
from __future__ import annotations

import json
import os
import plistlib
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from teyla import leak

AT = "@"
KEY = "sk-ant-" + "A1" * 12
PAT = "ghp_" + "aB3dEf9hJk" * 4
CYR = "".join(chr(c) for c in (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442))        # a Russian greeting


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for k, v in {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test Author",
                 "GIT_AUTHOR_EMAIL": "author" + AT + "example.com", "GIT_COMMITTER_NAME": "Test Author",
                 "GIT_COMMITTER_EMAIL": "author" + AT + "example.com"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent")      # no global ignore file
    # gitleaks may be installed on this machine: tests choose whether it is found.
    monkeypatch.setattr(leak, "_which", lambda name: None)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    monkeypatch.chdir(r)
    return r


@pytest.fixture
def terms(tmp_path, monkeypatch):
    f = tmp_path / "terms.txt"
    f.write_text("# fake terms\nzebracorn\nquokka lab\nallow zebracorn in docs/*\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))
    return f


def commit(repo: Path, files: dict[str, str | bytes], msg: str = "add files") -> str:
    for name, body in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def scan(capsys, *args: str) -> tuple[int, dict]:
    code = leak.main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


def rules(doc: dict) -> list[tuple[str, str]]:
    return [(f["rule"], f["class"]) for f in doc["findings"]]


# --- masking and the rules -----------------------------------------------------------------

def test_private_term_prints_only_its_index(repo, terms, capsys):
    commit(repo, {"a.txt": "see the Quokka Lab page\nzebracorn\n"})
    code = leak.main([])
    out = capsys.readouterr().out
    assert code == 1
    assert "term:1" in out and "term:0" in out
    assert "quokka" not in out.lower() and "zebracorn" not in out.lower()
    assert "ze" + leak.ELLIPSIS not in out


def test_term_fingerprint_does_not_depend_on_the_term_text(repo, terms, tmp_path, capsys):
    commit(repo, {"a.txt": "zebracorn\n"})
    _, a = scan(capsys)
    terms.write_text("quokka lab\nzebracorn\n")
    _, b = scan(capsys)
    assert a["findings"][0]["masked"] == "term:0" and b["findings"][0]["masked"] == "term:1"
    assert a["findings"][0]["fingerprint"] != b["findings"][0]["fingerprint"]
    import hashlib
    assert a["findings"][0]["fingerprint"] != hashlib.sha256(b"termA.txtzebracorn").hexdigest()[:12]


def test_match_is_two_characters_an_ellipsis_and_the_length(repo, terms, capsys):
    commit(repo, {"a.txt": f"K = '{KEY}'\nmail jdoe{AT}corp-mail.io\ncd /Users/" + "jdoe" + "/repos\n"})
    code, doc = scan(capsys)
    got = {f["rule"]: f["masked"] for f in doc["findings"]}
    assert code == 1
    assert got == {"secret": f"sk{leak.ELLIPSIS}{len(KEY)}", "email": f"jd{leak.ELLIPSIS}{len('jdoe' + AT + 'corp-mail.io')}",
                   "home": f"jd{leak.ELLIPSIS}4"}
    assert KEY not in json.dumps(doc) and "corp-mail" not in json.dumps(doc)


def test_cyrillic_is_lang_and_never_blocks(repo, terms, capsys):
    commit(repo, {"a.txt": CYR + "\n"})
    code, doc = scan(capsys)
    assert code == 0
    assert [(f["rule"], f["severity"]) for f in doc["findings"]] == [("cyrillic", "lang")]


def test_generic_secret_shape_is_triage_not_a_blocker(repo, terms, capsys):
    commit(repo, {"a.py": 'password = "Ab3dEf9hJkLmNp2rStUvWx5z"\n', "b.py": 'password = "your-password-goes-here-123"\n'})
    code, doc = scan(capsys)
    assert code == 0
    assert [(f["rule"], f["severity"], f["path"]) for f in doc["findings"]] == [("secret-generic", "triage", "a.py")]


def test_clean_repo_exits_zero(repo, terms, capsys):
    commit(repo, {"a.txt": "nothing here\n"})
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == [] and doc["coverage"]["unread"] == []


def test_quiet_prints_the_number_of_blockers(repo, terms, capsys):
    commit(repo, {"a.txt": f"{KEY}\n", "b.txt": CYR + "\n"})
    assert leak.main(["--quiet"]) == 1
    assert capsys.readouterr().out.strip() == "1"


def test_one_finding_per_secret_with_every_place(repo, terms, capsys):
    commit(repo, {"a.py": f"A = '{KEY}'\nB = '{KEY}'\n"})
    commit(repo, {"a.py": "A = 1\n"}, msg="drop")
    commit(repo, {"a.py": f"A = '{KEY}'\n"}, msg="again")
    _, doc = scan(capsys, "--commits", "HEAD")
    (f,) = [f for f in doc["findings"] if f["rule"] == "secret"]
    assert len(f["places"]) >= 3 and all(p.startswith("commit:") for p in f["places"])


# --- the index ------------------------------------------------------------------------------

def test_staged_reads_the_index_not_the_working_tree(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    (repo / "a.txt").write_text(f"{KEY}\n")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("clean again in the working tree\n")
    code, doc = scan(capsys, "--staged")
    assert code == 1 and rules(doc) == [("secret", "publishable")]
    assert any("index" in r for r in doc["coverage"]["read"])


def test_staged_ignores_a_dirty_working_tree(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    (repo / "a.txt").write_text(f"{KEY}\n")
    code, doc = scan(capsys, "--staged")
    assert code == 0 and doc["findings"] == []


def test_staged_only_looks_at_staged_files(repo, terms, capsys):
    commit(repo, {"a.txt": f"{KEY}\n"})
    (repo / "b.txt").write_text("new\n")
    git(repo, "add", "b.txt")
    _, doc = scan(capsys, "--staged")
    assert doc["findings"] == []


# --- outgoing commits and tags --------------------------------------------------------------

@pytest.fixture
def remote(repo, tmp_path):
    dest = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(dest)], check=True)
    git(repo, "remote", "add", "origin", str(dest))
    return dest


def test_outgoing_scans_only_what_the_remote_lacks(repo, remote, terms, capsys):
    commit(repo, {"a.txt": f"{KEY}\n"}, msg="old key")
    git(repo, "push", "-q", "origin", "main")
    commit(repo, {"b.txt": f"mail jdoe{AT}corp-mail.io\n"}, msg="new")
    code, doc = scan(capsys, "--outgoing")
    assert code == 1 and rules(doc) == [("email", "publishable")]
    git(repo, "push", "-q", "origin", "main")
    code, doc = scan(capsys, "--outgoing")
    assert code == 0 and doc["findings"] == []


def test_outgoing_scans_commit_messages_and_authors(repo, remote, terms, capsys):
    commit(repo, {"a.txt": "x\n"}, msg="mentions zebracorn")
    _, doc = scan(capsys, "--outgoing", "origin")
    assert any(f["path"].endswith(":message") and f["rule"] == "term" for f in doc["findings"])


def test_outgoing_reads_annotated_tags_and_their_messages(repo, remote, terms, capsys):
    commit(repo, {"a.txt": "x\n"})
    git(repo, "tag", "-a", "v1", "-m", f"release notes for jdoe{AT}corp-mail.io")
    _, doc = scan(capsys, "--outgoing")
    assert ("email", "publishable") in rules(doc)
    assert any(f["path"] == "tag:v1:message" for f in doc["findings"])


def test_outgoing_in_a_shallow_clone_is_exit_two(repo, remote, terms, tmp_path, capsys, monkeypatch):
    commit(repo, {"a.txt": "1\n"})
    commit(repo, {"a.txt": "2\n"})
    git(repo, "push", "-q", "origin", "main")
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{remote}", str(clone)], check=True)
    monkeypatch.chdir(clone)
    code, doc = scan(capsys, "--outgoing")
    assert code == 2 and any("shallow" in u["why"] for u in doc["coverage"]["unread"])


def test_outgoing_without_the_remote_is_exit_two(repo, terms, capsys):
    commit(repo, {"a.txt": "1\n"})
    code, doc = scan(capsys, "--outgoing", "nowhere")
    assert code == 2 and doc["coverage"]["unread"][0]["surface"] == "outgoing to nowhere"


# --- classes --------------------------------------------------------------------------------

def test_a_key_in_pushed_history_is_historical_with_rotate_first(repo, remote, terms, capsys):
    commit(repo, {"a.py": f"K = '{KEY}'\n"}, msg="add key")
    commit(repo, {"a.py": "K = 1\n"}, msg="remove key")
    git(repo, "push", "-q", "origin", "main")
    assert leak.main(["--commits", "HEAD"]) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("rotate first")
    assert "historical" in out
    # the tree is clean; only the history holds the key
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == []


def test_a_key_in_an_unpushed_commit_is_publishable(repo, remote, terms, capsys):
    commit(repo, {"a.txt": "base\n"})
    git(repo, "push", "-q", "origin", "main")
    commit(repo, {"a.py": f"K = '{KEY}'\n"}, msg="add key")
    _, doc = scan(capsys, "--commits", "HEAD~1..HEAD")
    assert rules(doc) == [("secret", "publishable")]


def test_commits_range_with_not_inside_still_classifies(repo, remote, terms, capsys):
    base = commit(repo, {"a.txt": "base\n"})
    git(repo, "push", "-q", "origin", "main")
    commit(repo, {"a.py": f"K = '{KEY}'\n"}, msg="add key")
    _, doc = scan(capsys, "--commits", f"HEAD --not {base}")
    assert rules(doc) == [("secret", "publishable")]


# --- publication text -----------------------------------------------------------------------

def test_text_file_and_stdin(repo, terms, tmp_path, capsys, monkeypatch):
    body = tmp_path / "body.md"
    body.write_text(f"Fixes it.\nmail jdoe{AT}corp-mail.io\n")
    code, doc = scan(capsys, "--text", str(body))
    assert code == 1 and rules(doc) == [("email", "publishable")] and doc["findings"][0]["line"] == 2
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"token {KEY}\n"))
    code, doc = scan(capsys, "--text", "-")
    assert code == 1 and doc["findings"][0]["path"] == "<stdin>"


def test_scan_text_api_needs_no_repo(terms):
    got = leak.scan_text("the zebracorn plan", None)
    assert [(f.rule, f.masked, f.cls) for f in got] == [("term", "term:0", "publishable")]


def test_text_needs_no_git_repo(tmp_path, terms, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "body.md"
    p.write_text("all fine\n")
    code, doc = scan(capsys, "--text", str(p))
    assert code == 0


# --- local-only surfaces --------------------------------------------------------------------

def test_a_key_in_an_ignored_env_is_local_only_and_not_a_blocker(repo, terms, capsys):
    commit(repo, {".gitignore": ".env\n", "a.txt": "ok\n"})
    (repo / ".env").write_text(f"TOKEN={PAT}\n")
    code, doc = scan(capsys)
    assert code == 0
    (f,) = doc["findings"]
    assert (f["rule"], f["class"], f["severity"]) == ("secret", "local-only", "triage")


def test_the_same_key_in_the_index_is_publishable(repo, terms, capsys):
    commit(repo, {".gitignore": ".env\n"})
    (repo / ".env").write_text(f"TOKEN={PAT}\n")
    git(repo, "add", "-f", ".env")
    code, doc = scan(capsys, "--staged")
    assert code == 1 and rules(doc) == [("secret", "publishable")]


def test_an_untracked_env_that_is_not_ignored_blocks(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    (repo / ".env.production").write_text(f"TOKEN={PAT}\n")
    code, doc = scan(capsys)
    assert code == 1
    (f,) = doc["findings"]
    assert f["class"] == "local-only" and f["severity"] == "blocker" and "NOT gitignored" in f["note"]


def test_local_only_files_are_not_scanned_by_staged(repo, terms, capsys):
    commit(repo, {".gitignore": ".env\n"})
    (repo / ".env").write_text(f"TOKEN={PAT}\n")
    code, doc = scan(capsys, "--staged")
    assert code == 0 and doc["findings"] == []


# --- harness configs ------------------------------------------------------------------------

@pytest.mark.parametrize("rel,text", [
    (".mcp.json", '{"mcpServers": {"x": {"url": "https://tools.example.test/mcp"}}}'),
    (".cursor/mcp.json", '{"mcpServers": {"x": {"command": "npx", "args": ["-y", "pkg", "https://tools.example.test/x"]}}}'),
    (".claude/settings.json", '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "/opt/tools/guard.sh"}]}]}}'),
    (".claude/settings.json", '{"env": {"ANTHROPIC_BASE_URL": "https://proxy.example.test/v1"}}'),
    (".claude/settings.local.json", '{"statusLine": {"type": "command", "command": "~/bin/status.sh"}}'),
    (".vscode/tasks.json", '// build\n{"tasks": [{"label": "x", "command": "bash ../outside/run.sh",}]}'),
    (".codex/config.toml", '[model_providers.p]\nbase_url = "https://llm.example.test/v1"\n'),
    (".codex/config.toml", '[mcp_servers.x]\ncommand = "/Users/example/bin/serve"\n'),
])
def test_harness_config_pointing_outside_is_a_blocker(repo, terms, capsys, rel, text):
    commit(repo, {rel: text})
    code, doc = scan(capsys)
    assert code == 1
    assert [(f["rule"], f["severity"], f["path"]) for f in doc["findings"] if f["rule"] == "harness-config"] == \
        [("harness-config", "blocker", rel)]


@pytest.mark.parametrize("rel,text", [
    (".mcp.json", '{"mcpServers": {"x": {"url": "http://localhost:8787/mcp"}, "y": {"url": "http://127.0.0.1:9/m"}}}'),
    (".claude/settings.json", '{"$schema": "https://json.schemastore.org/claude-code-settings.json", "hooks": {"PreToolUse": '
                              '[{"hooks": [{"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/guard.sh"}]}]}}'),
    (".claude/settings.json", '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh .claude/hooks/a.sh && /usr/bin/env true"}]}]}}'),
    (".vscode/tasks.json", '{"tasks": [{"label": "t", "command": "${workspaceFolder}/scripts/run.sh"}]}'),
    (".codex/config.toml", 'model = "x"\n[mcp_servers.x]\ncommand = "npx"\nargs = ["-y", "pkg"]\n'),
])
def test_harness_config_inside_the_repo_is_fine(repo, terms, capsys, rel, text):
    commit(repo, {rel: text})
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == []


def test_an_unparseable_harness_config_is_a_surface_not_read(repo, terms, capsys):
    commit(repo, {".mcp.json": "{not json"})
    code, doc = scan(capsys)
    assert code == 2 and doc["coverage"]["unread"][0]["surface"] == ".mcp.json"


def test_an_untracked_local_settings_file_is_local_only(repo, terms, capsys):
    commit(repo, {".gitignore": ".claude/settings.local.json\n", "a.txt": "ok\n"})
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.local.json").write_text('{"env": {"OPENAI_BASE_URL": "https://proxy.example.test/v1"}}')
    code, doc = scan(capsys)
    assert code == 0
    (f,) = doc["findings"]
    assert (f["rule"], f["class"], f["severity"]) == ("harness-config", "local-only", "triage")


# --- plists and string catalogs -------------------------------------------------------------

def test_binary_plist_strings_are_scanned(repo, terms, capsys):
    data = plistlib.dumps({"Contact": f"jdoe{AT}corp-mail.io", "Name": "App"}, fmt=plistlib.FMT_BINARY)
    commit(repo, {"App/Info.plist": data})
    code, doc = scan(capsys)
    assert code == 1 and [(f["rule"], f["path"]) for f in doc["findings"]] == [("email", "App/Info.plist")]


def test_entitlements_are_scanned_as_plists(repo, terms, capsys):
    data = plistlib.dumps({"com.example.group": ["group.zebracorn.shared"]})
    commit(repo, {"App/App.entitlements": data})
    code, doc = scan(capsys)
    assert code == 1 and rules(doc) == [("term", "publishable")]


def test_a_broken_binary_plist_is_not_read(repo, terms, capsys):
    commit(repo, {"App/Info.plist": b"bplist00\x01\x02garbage\x00"})
    code, doc = scan(capsys)
    assert code == 2 and "plist" in doc["coverage"]["unread"][0]["why"]


def test_xcstrings_are_parsed_and_localisation_is_not_a_finding(repo, terms, capsys):
    cat = {"sourceLanguage": "en", "strings": {"Hello": {"localizations": {"ru": {"stringUnit": {"state": "translated", "value": CYR}}}},
                                                 "Mail": {"localizations": {"en": {"stringUnit": {"value": f"write to jdoe{AT}corp-mail.io"}}}}},
           "version": "1.0"}
    commit(repo, {"App/Localizable.xcstrings": json.dumps(cat, ensure_ascii=True)})
    code, doc = scan(capsys)
    assert code == 1 and [f["rule"] for f in doc["findings"]] == ["email"]


# --- image metadata -------------------------------------------------------------------------

def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(*extra: bytes) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + b"".join(extra) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def tiff(*tags: int) -> bytes:
    entries = b"".join(struct.pack("<HHII", t, 4, 1, 26) for t in tags)
    return b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(tags)) + entries + b"\x00\x00\x00\x00"


def jpeg(exif: bytes | None = None, comment: bytes | None = None) -> bytes:
    out = b"\xff\xd8"
    if exif is not None:
        body = b"Exif\x00\x00" + exif
        out += b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    if comment is not None:
        out += b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
    return out + b"\xff\xda\x00\x02" + b"\x00" * 8 + b"\xff\xd9"


def test_a_clean_png_and_jpeg_pass(repo, terms, capsys):
    commit(repo, {"a.png": png(), "b.jpg": jpeg(exif=tiff(0x0112))})
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == []


def test_png_text_chunks_run_the_text_rules(repo, terms, capsys):
    body = b"Comment\x00" + f"made by jdoe{AT}corp-mail.io".encode()
    commit(repo, {"shot.png": png(chunk(b"tEXt", body))})
    code, doc = scan(capsys)
    assert code == 1 and [(f["rule"], f["path"]) for f in doc["findings"]] == [("email", "shot.png")]


def test_png_compressed_itxt_is_read(repo, terms, capsys):
    body = b"Description\x00\x01\x00\x00\x00" + zlib.compress(b"for zebracorn only")
    commit(repo, {"shot.png": png(chunk(b"iTXt", body))})
    code, doc = scan(capsys)
    assert code == 1 and rules(doc) == [("term", "publishable")]


def test_png_exif_gps_is_a_blocker(repo, terms, capsys):
    commit(repo, {"shot.png": png(chunk(b"eXIf", tiff(0x8825)))})
    code, doc = scan(capsys)
    assert code == 1
    (f,) = doc["findings"]
    assert (f["rule"], f["severity"], f["masked"]) == ("image-metadata", "blocker", "GPS")


@pytest.mark.parametrize("tag,name", [(0x8825, "GPS"), (0x013B, "Artist")])
def test_jpeg_exif_gps_and_artist_are_blockers(repo, terms, capsys, tag, name):
    commit(repo, {"photo.jpeg": jpeg(exif=tiff(0x0112, tag))})
    code, doc = scan(capsys)
    assert code == 1 and [(f["rule"], f["masked"]) for f in doc["findings"]] == [("image-metadata", name)]


def test_jpeg_comment_runs_the_text_rules(repo, terms, capsys):
    commit(repo, {"photo.jpg": jpeg(comment=f"by jdoe{AT}corp-mail.io".encode())})
    code, doc = scan(capsys)
    assert code == 1 and rules(doc) == [("email", "publishable")]


def test_a_truncated_jpeg_does_not_crash(repo, terms, capsys):
    commit(repo, {"photo.jpg": jpeg(exif=tiff(0x8825))[:20]})
    code, doc = scan(capsys)
    assert code in (0, 1)


def test_image_metadata_in_the_index_and_in_commits(repo, terms, capsys):
    commit(repo, {"a.txt": "base\n"})
    (repo / "p.jpg").write_bytes(jpeg(exif=tiff(0x8825)))
    git(repo, "add", "p.jpg")
    code, doc = scan(capsys, "--staged")
    assert code == 1 and rules(doc) == [("image-metadata", "publishable")]
    git(repo, "commit", "-q", "-m", "photo")
    code, doc = scan(capsys, "--commits", "HEAD~1..HEAD")
    assert code == 1 and rules(doc) == [("image-metadata", "publishable")]
    assert doc["findings"][0]["places"][0].startswith("commit:")


# --- allow-list and exceptions --------------------------------------------------------------

def test_leak_allow_sections_still_apply(repo, terms, capsys):
    commit(repo, {"docs/ok.md": "zebracorn\n", "t/fake.py": f"K = '{KEY}'\n", ".leak-allow": "secrets:\nt/fake.py\n"})
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == []


def test_exception_silences_one_rule_on_a_glob(repo, terms, capsys):
    commit(repo, {"vendor/a.txt": "zebracorn\n", "src/b.txt": "zebracorn\n",
                  ".leak-allow": "[exceptions]\nterm vendor/* vendored sample, upstream text until=2999-01-01\n"})
    code, doc = scan(capsys)
    assert code == 1 and [f["path"] for f in doc["findings"]] == ["src/b.txt"]


def test_an_expired_exception_is_ignored_and_reported(repo, terms, capsys):
    commit(repo, {"vendor/a.txt": "zebracorn\n",
                  ".leak-allow": "[exceptions]\nterm vendor/* temporary until=2000-01-01\n"})
    code, doc = scan(capsys)
    assert code == 1 and [f["path"] for f in doc["findings"]] == ["vendor/a.txt"]
    assert any(n.startswith("expired exception: term vendor/*") for n in doc["coverage"]["notes"])


@pytest.mark.parametrize("rule", ["secret", "*", "gitleaks:*"])
def test_a_match_all_exception_for_a_secret_rule_is_an_error(repo, terms, capsys, rule):
    commit(repo, {"a.txt": "x\n", ".leak-allow": f"[exceptions]\n{rule} * everything\n"})
    code, doc = scan(capsys)
    assert code == 2 and "exempts every file" in doc["errors"][0]


def test_a_secret_exception_for_named_files_and_an_exception_by_fingerprint(repo, terms, capsys):
    commit(repo, {"t/a.py": f"K = '{KEY}'\n", "t/b.py": f"K = '{KEY}x'\n"})
    _, doc = scan(capsys)
    by_path = {f["path"]: f["fingerprint"] for f in doc["findings"]}
    (repo / ".leak-allow").write_text(f"[exceptions]\nsecret t/* fake fixture fp={by_path['t/a.py']}\n")
    git(repo, "add", "-A")
    code, doc = scan(capsys)
    assert code == 1 and [f["path"] for f in doc["findings"]] == ["t/b.py"]


def test_an_exception_needs_a_reason_and_a_valid_date(repo, terms, capsys):
    commit(repo, {"a.txt": "x\n", ".leak-allow": "[exceptions]\nterm a.txt\n"})
    code, doc = scan(capsys)
    assert code == 2 and "no reason" in doc["errors"][0]
    (repo / ".leak-allow").write_text("[exceptions]\nterm a.txt why until=soon\n")
    code, doc = scan(capsys)
    assert code == 2 and "bad date" in doc["errors"][0]


def test_sections_after_exceptions_still_parse(repo, terms, capsys):
    commit(repo, {"docs/x.md": CYR + "\n", "a.txt": CYR + "\n",
                  ".leak-allow": "[exceptions]\nterm vendor/* reason until=2999-01-01\ncyrillic:\ndocs/*.md\n"})
    _, doc = scan(capsys)
    assert [f["path"] for f in doc["findings"]] == ["a.txt"]


# --- exit 2: a surface could not be read ----------------------------------------------------

def test_an_explicit_term_file_that_is_missing_is_exit_two(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "nope.txt"))
    commit(repo, {"a.txt": "zebracorn\n"})
    code, doc = scan(capsys)
    assert code == 2 and doc["coverage"]["unread"][0]["surface"] == "private terms"


def test_no_default_term_file_is_a_note_not_an_error(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TEYLA_PRIVATE_TERMS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    commit(repo, {"a.txt": "ok\n"})
    code, doc = scan(capsys)
    assert code == 0 and any("no private-terms list" in n for n in doc["coverage"]["notes"])


def test_a_blocker_outranks_an_unread_surface(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "nope.txt"))
    commit(repo, {"a.txt": f"{KEY}\n"})
    code, _ = scan(capsys)
    assert code == 1


def test_outside_a_repo_is_a_usage_error(tmp_path, terms, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert leak.main([]) == 2
    assert "not inside a git repository" in capsys.readouterr().err


def test_a_missing_text_file_is_a_usage_error(repo, terms, capsys):
    assert leak.main(["--text", "nope.md"]) == 2


# --- gitleaks -------------------------------------------------------------------------------

STUB = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["protect", "--help"]:
    sys.exit(0 if os.environ.get("STUB_PROTECT", "1") == "1" else 1)
open(os.environ["STUB_LOG"], "a").write(" ".join(a) + "\\n")
path = a[a.index("--report-path") + 1]
json.dump(json.loads(os.environ.get("STUB_REPORT", "[]")), open(path, "w"))
"""


@pytest.fixture
def gitleaks(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "gitleaks"
    exe.parent.mkdir()
    exe.write_text(STUB)
    exe.chmod(0o755)
    monkeypatch.setattr(leak, "_which", lambda name: str(exe) if name == "gitleaks" else None)
    log = tmp_path / "stub.log"
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    return log


def item(**kw) -> str:
    base = {"RuleID": "generic-api-key", "File": "a.txt", "StartLine": 1, "Commit": "", "Secret": "REDACTED"}
    return json.dumps([{**base, **kw}])


def test_gitleaks_findings_merge_as_gitleaks_rules(repo, terms, gitleaks, monkeypatch, capsys):
    commit(repo, {"a.txt": "nothing Teyla sees\n"})
    monkeypatch.setenv("STUB_REPORT", item())
    code, doc = scan(capsys)
    assert code == 1
    (f,) = doc["findings"]
    assert (f["rule"], f["severity"], f["class"], f["masked"]) == ("gitleaks:generic-api-key", "blocker", "publishable", "redacted")
    args = gitleaks.read_text()
    assert "detect --no-git" in args and "--redact" in args and "--exit-code 0" in args and "--report-format json" in args
    assert "--config" in args and "--gitleaks-ignore-path" in args


def test_gitleaks_in_a_range_gets_log_opts_and_the_commit_place(repo, terms, gitleaks, monkeypatch, capsys):
    sha = commit(repo, {"a.txt": "nothing Teyla sees\n"})
    monkeypatch.setenv("STUB_REPORT", item(Commit=sha))
    code, doc = scan(capsys, "--commits", "HEAD")
    assert code == 1 and doc["findings"][0]["places"] == [f"commit:{sha[:8]}:a.txt:1"]
    assert "--log-opts HEAD" in gitleaks.read_text()


def test_gitleaks_staged_uses_protect_when_it_exists(repo, terms, gitleaks, monkeypatch, capsys):
    commit(repo, {"b.txt": "x\n"})
    (repo / "a.txt").write_text("y\n")
    git(repo, "add", "a.txt")
    monkeypatch.setenv("STUB_REPORT", item())
    code, doc = scan(capsys, "--staged")
    assert code == 1 and gitleaks.read_text().startswith("protect --staged")


def test_gitleaks_staged_without_protect_is_skipped_with_a_note(repo, terms, gitleaks, monkeypatch, capsys):
    commit(repo, {"b.txt": "x\n"})
    monkeypatch.setenv("STUB_PROTECT", "0")
    code, doc = scan(capsys, "--staged")
    assert code == 0 and any("no `protect --staged`" in n for n in doc["coverage"]["notes"])


def test_gitleaks_findings_obey_the_secrets_allow_list_and_exceptions(repo, terms, gitleaks, monkeypatch, capsys):
    commit(repo, {"a.txt": "x\n", "t/f.txt": "x\n", ".leak-allow": "secrets:\nt/f.txt\n"})
    monkeypatch.setenv("STUB_REPORT", json.dumps([
        {"RuleID": "r", "File": "t/f.txt", "StartLine": 1, "Commit": ""}]))
    code, doc = scan(capsys)
    assert code == 0 and doc["findings"] == []


def test_gitleaks_in_a_tree_scan_ignores_files_git_does_not_track(repo, terms, gitleaks, monkeypatch, capsys):
    commit(repo, {"a.txt": "x\n"})
    monkeypatch.setenv("STUB_REPORT", item(File="node_modules/p/x.js"))
    code, _ = scan(capsys)
    assert code == 0


def test_gitleaks_failure_is_a_surface_not_read(repo, terms, gitleaks, tmp_path, monkeypatch, capsys):
    commit(repo, {"a.txt": "x\n"})
    broken = tmp_path / "bin" / "gitleaks"
    broken.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
    code, doc = scan(capsys)
    assert code == 2 and doc["coverage"]["unread"][0]["surface"] == "gitleaks tree"


def test_without_gitleaks_one_note_and_no_change_to_the_exit(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    code, doc = scan(capsys, "--staged")
    notes = [n for n in doc["coverage"]["notes"] if "gitleaks is not installed" in n]
    assert code == 0 and len(notes) == 1


def test_require_gitleaks_makes_its_absence_exit_two(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    code, doc = scan(capsys, "--require-gitleaks")
    assert code == 2
    leak.main(["--require-gitleaks"])
    assert "NOT READ gitleaks" in capsys.readouterr().out


def test_require_gitleaks_passes_when_it_ran(repo, terms, gitleaks, capsys):
    commit(repo, {"a.txt": "ok\n"})
    code, _ = scan(capsys, "--require-gitleaks")
    assert code == 0


# --- --all and the output -------------------------------------------------------------------

def test_all_scans_every_repo_under_code_root(tmp_path, terms, monkeypatch, capsys):
    from teyla import config
    code_root = tmp_path / "code"
    for name, body in (("alpha", "fine\n"), ("beta", f"{KEY}\n")):
        r = code_root / name
        r.mkdir(parents=True)
        git(r, "init", "-q", "-b", "main")
        commit(r, {"a.txt": body})
    (code_root / "not-a-repo").mkdir()
    monkeypatch.setattr(config, "code_root", lambda cfg=None: code_root)
    monkeypatch.chdir(tmp_path)
    code, doc = scan(capsys, "--all")
    assert code == 1
    assert [(f["repo"], f["rule"]) for f in doc["findings"]] == [("beta", "secret")]
    assert any(r.startswith("alpha: tree") for r in doc["coverage"]["read"])


def test_all_takes_no_other_surface(repo, terms, capsys):
    assert leak.main(["--all", "--staged"]) == 2


def test_json_carries_the_documented_fields(repo, terms, capsys):
    commit(repo, {"a.txt": f"K = '{KEY}'\n"})
    code, doc = scan(capsys)
    (f,) = doc["findings"]
    assert set(f) == {"rule", "class", "severity", "path", "line", "masked", "fingerprint", "places"}
    assert len(f["fingerprint"]) == 12 and doc["exit"] == code == 1
    assert set(doc["coverage"]) == {"read", "unread", "notes"}


def test_the_fingerprint_is_the_documented_hash(repo, terms, capsys):
    import hashlib
    commit(repo, {"a.txt": f"K = '{KEY}'\n"})
    _, doc = scan(capsys)
    assert doc["findings"][0]["fingerprint"] == hashlib.sha256(("secret" + "a.txt" + KEY).encode()).hexdigest()[:12]


def test_coverage_is_printed_at_the_end_of_the_text_output(repo, terms, capsys):
    commit(repo, {"a.txt": "ok\n"})
    leak.main([])
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("coverage: read tree") or any(l.startswith("coverage:") for l in lines[-3:])


def test_repo_argument_selects_the_repo(repo, terms, tmp_path, monkeypatch, capsys):
    commit(repo, {"a.txt": f"{KEY}\n"})
    monkeypatch.chdir(tmp_path)
    code, doc = scan(capsys, str(repo))
    assert code == 1


# --- one implementation ---------------------------------------------------------------------

def test_the_rules_are_the_ones_in_scripts_leak_check():
    eng = leak._engine()
    script = Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"
    assert Path(eng.__file__).resolve() == script
    assert eng.SECRET_RES and eng.EMAIL and eng.HOME and eng.CYRILLIC


def test_the_legacy_script_and_teyla_leak_agree_on_a_repo(repo, terms, capsys):
    commit(repo, {"a.txt": f"zebracorn {KEY} jdoe{AT}corp-mail.io\n", "b.txt": CYR + "\n"})
    script = Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"
    p = subprocess.run([sys.executable, str(script)], cwd=repo, capture_output=True, text=True)
    legacy = sorted(line.split(": ")[1] for line in p.stdout.splitlines())
    _, doc = scan(capsys)
    assert legacy == sorted(f["rule"] for f in doc["findings"] if f["rule"] != "secret-generic")
