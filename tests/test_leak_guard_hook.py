"""The agent-boundary hook (`plugin/hooks/leak-guard.sh`, with `teyla.leak_guard` behind it), run for real
through `sh` with the hook JSON on stdin.

A fake `teyla` first on PATH delegates to the real `teyla.leak` and records its arguments; the python the hook
starts is a wrapper that insists on `-I`. HOME, TEYLA_HOME and TEYLA_PRIVATE_TERMS point into tmp_path, so
nothing here reads a real credential file or the real private-terms list. Every secret and term is invented,
and the secret is assembled at run time so this file carries no key shape of its own.

The rule under test: a command with none of the script's tokens costs nothing (no python, no scanner, and a
bug in the script lets it through); a command with one is refused whenever any part of the guard fails."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "leak-guard.sh"
SRC = ROOT / "src"

SECRET = "AKIA" + "ZXCVBNMLKJ654321"          # the shape of an AWS access key id; not a real one
TERM = "zorblax-" + "quillmere"               # an invented private term

FAKE_TEYLA = f"""#!/bin/sh
echo "$@" >> "$FAKE_CALLS"
case "${{FAKE_SCANNER:-}}" in
  broken) exit 127 ;;
  slow) sleep 5; exit 0 ;;
esac
shift
PYTHONPATH="{SRC}" exec "{sys.executable}" -c 'import sys; from teyla.leak import main; sys.exit(main(sys.argv[1:]))' "$@"
"""

# The hook starts `python3 -I -m teyla.leak_guard`. This wrapper checks the -I, then runs the checkout's source.
FAKE_PY = f"""#!/bin/sh
echo "$@" >> "$FAKE_PYCALLS"
[ "$1" = -I ] || {{ echo "the hook must start python with -I" >&2; exit 3; }}
[ "${{FAKE_PY:-}}" = crash ] && exit 1
shift
PYTHONPATH="{SRC}" exec "{sys.executable}" "$@"
"""


class Box:
    def __init__(self, tmp_path: pathlib.Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        (self.home / ".teyla").mkdir(parents=True)
        self.work = tmp_path / "work"             # the session's directory; a repo of its own, apart from HOME
        (self.work / ".git").mkdir(parents=True)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.calls = tmp_path / "calls"
        self.pycalls = tmp_path / "pycalls"
        self.calls.write_text("")
        self.pycalls.write_text("")
        self.terms = tmp_path / "secrets" / "terms.txt"
        self.terms.parent.mkdir()
        self.terms.write_text(f"# invented terms\n{TERM}\n")
        for name, body in (("teyla", FAKE_TEYLA), ("py", FAKE_PY)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)

    def spy(self, tool: str) -> pathlib.Path:
        mark = self.tmp / f"{tool}.mark"
        p = self.bin / tool
        p.write_text(f'#!/bin/sh\ntouch "{mark}"\n')
        p.chmod(0o755)
        return mark

    def payload(self, command=None, tool="Bash", path=None) -> str:
        ti = {"command": command, "description": "d"} if path is None else {"file_path": str(path)}
        return json.dumps({"session_id": "s", "cwd": str(self.work), "hook_event_name": "PreToolUse",
                           "tool_name": tool, "tool_input": ti})

    def run(self, command=None, *, tool="Bash", path=None, args=(), script=HOOK, payload=None, path_dirs=None, **env):
        if payload is None:
            payload = self.payload(command, tool, path)
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("TEYLA_", "FAKE_")) and k not in ("PYTHONPATH", "CLAUDE_PLUGIN_ROOT")}
        e.update(HOME=str(self.home), TEYLA_HOME=str(self.home / ".teyla"), TEYLA_PRIVATE_TERMS=str(self.terms),
                 TEYLA_PYTHON=str(self.bin / "py"), FAKE_CALLS=str(self.calls), FAKE_PYCALLS=str(self.pycalls),
                 PATH=path_dirs or f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin")
        e.update({k: v for k, v in env.items() if v is not None})
        for k, v in env.items():
            if v is None:
                e.pop(k, None)
        return subprocess.run(["/bin/sh", str(script), *args], input=payload, capture_output=True, text=True,
                              timeout=60, env=e, cwd=str(self.work))

    def scanner_calls(self) -> list[str]:
        return [l for l in self.calls.read_text().splitlines() if l]

    def python_calls(self) -> list[str]:
        return [l for l in self.pycalls.read_text().splitlines() if l]

    def skips(self) -> list[str]:
        log = self.home / ".teyla" / "leak-skips.log"
        return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def refused(r, *needles):
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert r.stdout == ""
    for n in needles:
        assert n in r.stderr, (n, r.stderr)
    assert SECRET not in r.stderr + r.stdout and TERM not in r.stderr + r.stdout


def allowed(r):
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), (r.returncode, r.stdout, r.stderr)


# --- a command with no token costs nothing -----------------------------------------------------------------

ORDINARY = [
    "ls -la", "git status", "git log --oneline -5", "git diff --stat", "git push origin main", "git checkout -b fix-x",
    "cat README.md", "grep -rn TODO src/", "python3 -m pytest -q", "swift build", "npm test", "xcrun simctl list",
    "ls -la ~/.config/teyla", "echo hello", "sed -n 1,5p docs/LEAK.md", "gh run list", "gh auth status",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_a_command_with_no_token_passes_and_starts_nothing(box, command):
    marks = [box.spy(t) for t in ("python3", "awk", "grep", "sed", "cat", "mkdir", "date")]
    allowed(box.run(command, TEYLA_PYTHON=None))
    assert not any(m.exists() for m in marks), command
    assert box.scanner_calls() == [] and box.python_calls() == []


def test_a_payload_without_a_tool_input_passes(box):
    for payload in ("", "{}", "not json", '{"tool_name": "Bash"}'):
        allowed(box.run(payload=payload))
    assert box.python_calls() == []


def test_a_read_of_an_ordinary_file_passes_without_python(box):
    mark = box.spy("python3")
    allowed(box.run(tool="Read", path=box.work / "src" / "app.py", TEYLA_PYTHON=None))
    assert not mark.exists()


# --- publications: the text goes through the scanner ----------------------------------------------------

def test_a_secret_in_a_pr_body_is_refused_with_the_masked_excerpt(box):
    r = box.run(f'gh pr create --title "feat: x" --body "the key is {SECRET} ok"')
    refused(r, "teyla leak-guard: refused", "gh pr create", "AK…20", "remove the value from the text")
    assert box.scanner_calls() == ["leak --text -"]
    assert box.python_calls() and box.python_calls()[0].startswith("-I -m teyla.leak_guard")


def test_a_clean_pr_passes_after_one_scan(box):
    allowed(box.run('gh pr create --title "feat: add the thing" --body "What, why, how tested."'))
    assert box.scanner_calls() == ["leak --text -"]


def test_a_private_term_in_a_heredoc_body_is_refused_and_never_printed(box):
    cmd = f"gh pr create --title t --body-file - <<'EOF'\n## Summary\nit's about {TERM} and don't forget\nEOF"
    refused(box.run(cmd), "gh pr create", "term:0")
    refused(box.run(f"gh pr comment 4 -F - <<EOF\nnote on {TERM}\nEOF"), "gh pr comment")


def test_a_command_substitution_heredoc_in_the_body_is_scanned(box):
    cmd = f'gh pr create --title t --body "$(cat <<\'EOF\'\nSummary: don\'t leak\n{TERM} is private\nEOF\n)"'
    refused(box.run(cmd), "gh pr create", "term:0")


def test_a_commit_message_with_a_term_is_refused(box):
    refused(box.run(f'git commit -m "fix: rename {TERM}"'), "git commit")
    refused(box.run(f"git commit -am 'chore: {TERM}'"), "git commit")
    refused(box.run(f"git -C /somewhere commit --message={TERM}"), "git commit")
    refused(box.run(f"git tag -a v1.0 -m 'release for {TERM}'"), "git tag")
    allowed(box.run('git commit -m "fix: the parser"'))
    allowed(box.run("git commit --amend --no-edit"))


def test_a_body_file_is_read_and_scanned(box):
    (box.work / "body.md").write_text(f"hello {TERM}\n")
    (box.work / "clean.md").write_text("hello\n")
    refused(box.run("gh pr create -t T -F body.md"), "gh pr create", "term:0")
    refused(box.run("gh issue comment 3 --body-file body.md"), "gh issue comment")
    refused(box.run('gh pr comment 5 --body "$(cat body.md)"'), "gh pr comment")
    refused(box.run("cat body.md | gh pr comment 5 -F -"), "gh pr comment")
    refused(box.run("git commit -F body.md"), "git commit")
    allowed(box.run("gh pr create -t T -F clean.md"))


def test_a_body_file_that_is_a_credential_is_refused_before_it_is_read(box):
    refused(box.run("gh gist create ~/.aws/credentials"), "credential")
    refused(box.run("gh pr create -t T --body-file ~/.ssh/id_ed25519"), "credential")
    assert box.scanner_calls() == []


def test_a_body_the_guard_cannot_read_is_refused(box):
    refused(box.run('gh pr comment 5 --body "$BODY"'), "a variable the guard cannot read", "TEYLA_LEAK_GUARD=0")
    refused(box.run("generate | gh pr comment 5 -F -"), "pipe whose source the guard cannot read")
    refused(box.run("gh pr create -t T -F missing.md"), "does not exist")
    assert box.scanner_calls() == []


def test_a_file_the_same_command_writes_is_not_a_missing_file(box):
    allowed(box.run("cat > notes.md <<'EOF'\nfine\nEOF\ngh pr create -t T -F notes.md"))


def test_other_publication_surfaces_are_scanned(box):
    refused(box.run(f"gh release create v1 --notes '{TERM}'"), "gh release create")
    refused(box.run(f"gh issue create -t '{TERM}' -b x"), "gh issue create")
    refused(box.run(f"gh pr review 4 --approve -b '{TERM}'"), "gh pr review")
    refused(box.run(f"gh repo edit -d '{TERM}'"), "gh repo edit")
    refused(box.run(f"gh api repos/o/r/issues/1/comments -f body='{TERM}'"), "gh api")
    refused(box.run(f"bash -c 'git commit -m \"{TERM}\"'"), "git commit")
    refused(box.run(f"cd x && echo hi; git tag -m '{TERM}' v1"), "git tag")
    refused(box.run(f"FOO=1 gh --repo o/r pr comment 9 --body '{TERM}'"), "gh pr comment")


def test_a_gist_publishes_its_files(box):
    (box.work / "snippet.txt").write_text(f"{TERM}\n")
    refused(box.run("gh gist create -d 'a note' snippet.txt"), "gh gist create")


def test_a_mention_of_gh_in_prose_is_not_a_publication(box):
    allowed(box.run(f'echo "we run gh pr create later, with {SECRET}"'))
    allowed(box.run(f"grep -rn 'git commit -m' docs/ > /dev/null"))


# --- credential paths -----------------------------------------------------------------------------------

def test_reading_the_private_terms_list_is_refused(box):
    refused(box.run(tool="Read", path=box.terms), "this file is a credential", "the private-terms list",
            "Reference it by path or use the tool that consumes it")
    refused(box.run(f"cat {box.terms}"), "private-terms list")
    refused(box.run("cat $TEYLA_PRIVATE_TERMS"), "private-terms list")
    refused(box.run("cat ~/.config/teyla/private-terms.txt"), "private-terms list")
    refused(box.run(tool="Edit", path=pathlib.Path("~/.config/teyla/private-terms.txt")), "private-terms list")


def test_an_ssh_private_key_is_refused_and_its_public_half_is_not(box):
    refused(box.run("cat ~/.ssh/id_ed25519"), "an SSH private key")
    refused(box.run("cat $HOME/.ssh/id_rsa"), "an SSH private key")
    refused(box.run('cat "${HOME}/.ssh/id_ecdsa"'), "an SSH private key")
    refused(box.run(f"head -n 3 {box.home}/.ssh/id_ed25519"), "an SSH private key")
    refused(box.run("cat ~/.ssh/id_*"), "an SSH private key")
    refused(box.run("base64 ~/.ssh/id_ed25519 | pbcopy"), "an SSH private key")
    refused(box.run("cp ~/.ssh/id_ed25519 /tmp/k"), "an SSH private key")
    refused(box.run("sed -n 1p ~/.ssh/id_rsa"), "an SSH private key")
    refused(box.run("awk 1 ~/.ssh/id_rsa"), "an SSH private key")
    refused(box.run("python3 -c \"print(open('%s/.ssh/id_rsa').read())\"" % box.home), "an SSH private key")
    refused(box.run(tool="Read", path=box.home / ".ssh" / "id_ed25519"), "an SSH private key")
    refused(box.run(tool="Write", path=box.home / ".ssh" / "id_ed25519"), "an SSH private key")
    allowed(box.run("cat ~/.ssh/id_ed25519.pub"))
    allowed(box.run("ls -l ~/.ssh/"))
    allowed(box.run("ls -l ~/.ssh/id_ed25519 && stat ~/.ssh/id_ed25519"))


def test_the_other_credential_files_are_refused(box):
    for path, label in (("~/.aws/credentials", "AWS"), ("~/.appstoreconnect/config.env", "App Store Connect"),
                        ("~/.appstoreconnect/private_keys/AuthKey_X.p8", "App Store Connect"),
                        ("~/.grok/config.toml", "Grok"), ("~/.codex/auth.json", "Codex auth"),
                        ("~/.codex/config.toml", "Codex config"), ("~/.claude/.credentials.json", "Claude credentials"),
                        ("~/.netrc", ".netrc"), ("~/.docker/config.json", "Docker")):
        refused(box.run(f"cat {path}"), label)
        refused(box.run(tool="Read", path=pathlib.Path(path)), label)
    allowed(box.run("ls -l ~/.appstoreconnect/"))
    allowed(box.run("stat -f %Lp ~/.aws/credentials"))


def test_a_key_file_is_a_credential_only_outside_the_repo(box):
    refused(box.run("cat /srv/keys/AuthKey_X.p8"), "key or certificate")
    refused(box.run(f"cat {box.home}/cert.pem"), "key or certificate")
    refused(box.run("cat ../elsewhere/key.pem"), "key or certificate")
    allowed(box.run("cat certs/test.pem"))
    allowed(box.run(f"cat {box.work}/certs/test.pem"))
    allowed(box.run("cat .codex/config.toml"))                    # the repo's own file, not ~/.codex
    refused(box.run("cat ~/.codex/config.toml"), "Codex config")


def test_prose_that_names_a_credential_path_is_not_a_read(box):
    allowed(box.run("echo 'never cat ~/.ssh/id_rsa'"))
    allowed(box.run("cat > docs.md <<'EOF'\nthe hook refuses ~/.ssh/id_rsa and ~/.aws/credentials\nEOF"))
    allowed(box.run("git commit -m 'docs: the hook refuses ~/.ssh/id_rsa'"))
    allowed(box.run("gh pr create --head fix-private-terms-docs --title t --body ok"))


def test_a_heredoc_fed_to_an_interpreter_is_code_and_is_checked(box):
    refused(box.run("python3 - <<'EOF'\nprint(open('%s/.aws/credentials').read())\nEOF" % box.home), "AWS")


# --- the Keychain ---------------------------------------------------------------------------------------

def test_the_keychain_is_not_read(box):
    refused(box.run("security find-generic-password -s svc -w"), "find-generic-password -w", "Keychain")
    refused(box.run("security find-generic-password -a me -s svc -g"), "find-generic-password -g")
    refused(box.run("security find-internet-password -s host -w"), "find-internet-password")
    refused(box.run("security dump-keychain -d login.keychain"), "dump-keychain")
    refused(box.run("KEY=$(security find-generic-password -s svc -w) tool"), "Keychain")
    allowed(box.run("security find-generic-password -s svc"))
    allowed(box.run("security list-keychains"))


# --- visibility -------------------------------------------------------------------------------------------

def test_making_a_repo_public_is_the_owners_call(box):
    refused(box.run("gh repo edit o/r --visibility public --accept-visibility-change-consequences"), "owner")
    refused(box.run("gh repo edit --visibility=PUBLIC"), "owner")
    refused(box.run("gh api -X PATCH repos/o/r -f visibility=public"), "owner")
    refused(box.run("gh api -X PATCH repos/o/r -F private=false"), "owner")
    allowed(box.run("gh repo edit --visibility private"))
    allowed(box.run("gh repo create new-thing --public --source ."))
    allowed(box.run("gh repo create new-thing --private"))


# --- fail-open for a bare command, fail-closed for a matched one ------------------------------------------

def test_a_broken_scanner_still_lets_a_plain_command_through_and_stops_a_publication(box):
    allowed(box.run("ls", FAKE_SCANNER="broken"))
    r = box.run('gh pr create --title t --body "hello"', FAKE_SCANNER="broken")
    refused(r, "scanner failed (exit 127)", "TEYLA_LEAK_GUARD=0 <command>", "leak-skips.log")


def test_a_slow_scanner_is_a_refusal_not_a_hang(box):
    r = box.run('gh pr create --title t --body "hello"', FAKE_SCANNER="slow", TEYLA_LEAK_GUARD_TIMEOUT="1")
    refused(r, "did not answer in time")


def test_a_scanner_that_cannot_read_everything_refuses(box):
    r = box.run('git commit -m "hello"', TEYLA_PRIVATE_TERMS=str(box.tmp / "missing-terms.txt"))
    refused(r, "could not read everything", "exit 2")


def test_no_python_is_a_refusal_for_a_matched_command_only(box):
    only = box.tmp / "only"
    only.mkdir()
    for tool in ("mkdir", "date"):
        (only / tool).symlink_to(shutil.which(tool))
    allowed(box.run("ls", TEYLA_PYTHON=None, path_dirs=str(only)))
    refused(box.run('git commit -m "x"', TEYLA_PYTHON=None, path_dirs=str(only)), "python3 is not on PATH", "TEYLA_LEAK_GUARD=0")
    refused(box.run("cat ~/.ssh/id_rsa", TEYLA_PYTHON=None, path_dirs=str(only)), "python3 is not on PATH")


def test_a_guard_that_crashes_is_a_refusal_for_a_matched_command(box):
    r = box.run('git commit -m "x"', FAKE_PY="crash")
    refused(r, "the guard failed (status 1)", "TEYLA_LEAK_GUARD=0")
    allowed(box.run("ls", FAKE_PY="crash"))
    assert len(box.python_calls()) == 1, "only the matched command started python"


def test_a_guard_that_cannot_import_its_module_is_a_refusal(box):
    broken = box.bin / "py"
    broken.write_text('#!/bin/sh\nexec "%s" -I -c "import teyla_no_such_module"\n' % sys.executable)
    refused(box.run("gh pr create -t T -b B"), "the guard failed")


def test_an_error_on_the_coarse_path_warns_and_lets_the_command_through(box, tmp_path):
    broken = tmp_path / "coarse.sh"
    broken.write_text(HOOK.read_text().replace("# leak-guard:coarse-begin", "false", 1))
    r = box.run("ls", script=broken)
    assert (r.returncode, r.stdout) == (0, "")
    assert r.stderr.count("\n") == 1 and "warning" in r.stderr and "let this command through" in r.stderr
    # the same marker is the only one before the token screen, so even a publication is untouched by it
    assert box.python_calls() == []


def test_an_error_on_the_token_path_is_a_refusal(box, tmp_path):
    broken = tmp_path / "token.sh"
    broken.write_text(HOOK.read_text().replace("# leak-guard:token-begin", "false", 1))
    r = box.run('git commit -m "x"', script=broken)
    refused(r, "the guard failed (status 1)")
    allowed(box.run("ls", script=broken))


def test_the_guard_script_carries_both_markers_once():
    text = HOOK.read_text()
    assert text.count("# leak-guard:coarse-begin") == 1 and text.count("# leak-guard:token-begin") == 1


# --- the skip -------------------------------------------------------------------------------------------

def test_the_skip_prefix_lifts_the_scan_once_and_is_logged(box):
    allowed(box.run(f'TEYLA_LEAK_GUARD=0 gh pr create --title t --body "{SECRET}"'))
    allowed(box.run(f'cd x && TEYLA_LEAK_GUARD=0 git commit -m "{TERM}"'))
    allowed(box.run('TEYLA_LEAK_GUARD=0 gh pr comment 1 --body "$BODY"', FAKE_SCANNER="broken"))
    lines = box.skips()
    assert len(lines) == 3 and all(l.split("\t")[1:3] == ["skip", "prefix"] for l in lines)
    assert SECRET not in "".join(lines) and TERM not in "".join(lines)
    assert box.scanner_calls() == [] and box.python_calls() == []


def test_the_skip_in_the_hook_environment_is_logged_too(box):
    allowed(box.run(f'git commit -m "{TERM}"', TEYLA_LEAK_GUARD="0"))
    assert [l.split("\t")[1:3] for l in box.skips()] == [["skip", "env"]]
    allowed(box.run("ls", TEYLA_LEAK_GUARD="0"))
    assert len(box.skips()) == 1, "a command with no token is not a skip"


def test_a_mention_of_the_skip_in_a_body_skips_nothing(box):
    r = box.run(f'gh pr create -t T --body "run it as TEYLA_LEAK_GUARD=0 gh pr create, and {SECRET}"')
    refused(r, "gh pr create")
    assert box.skips() == []


def test_the_skip_prefix_does_not_lift_a_credential_or_keychain_or_visibility_rule(box):
    refused(box.run("TEYLA_LEAK_GUARD=0 cat ~/.ssh/id_rsa"), "an SSH private key")
    refused(box.run("TEYLA_LEAK_GUARD=0 security find-generic-password -w"), "Keychain")
    refused(box.run("TEYLA_LEAK_GUARD=0 gh repo edit --visibility public"), "owner")
    assert box.skips() == []


# --- harness details --------------------------------------------------------------------------------------

def test_grok_gets_the_whole_refusal_as_json_on_stdout(box):
    r = box.run("cat ~/.aws/credentials", args=["--grok"])
    assert r.returncode == 2 and "credential" in r.stderr
    d = json.loads(r.stdout)
    assert d["decision"] == "deny" and "AWS credentials file" in d["reason"] and "\n" not in d["reason"]
    r = box.run('git commit -m "x"', args=["--grok"], FAKE_PY="crash")
    assert r.returncode == 2 and json.loads(r.stdout)["decision"] == "deny"


def test_codex_style_payloads_are_understood(box):
    cmd = ["bash", "-lc", f'git commit -m "{TERM}"']
    payload = json.dumps({"cwd": str(box.work), "hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": cmd}})
    refused(box.run(payload=payload), "git commit")


def test_a_matched_payload_that_is_not_json_is_a_refusal(box):
    refused(box.run(payload='{"tool_input": {"command": "git commit -m x" '), "the guard failed")


def test_the_hook_is_registered_after_the_kill_switch_and_keeps_the_others():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    cmds = [(g.get("matcher"), h["command"], h["timeout"]) for g in hooks for h in g["hooks"]]
    names = [c[1].rsplit("/", 1)[1].rstrip('"') for c in cmds]
    assert names == ["pre-tool-use.sh", "leak-guard.sh", "machine-guard.sh"]
    matcher, _cmd, timeout = cmds[1]
    assert set(matcher.split("|")) >= {"Bash", "Read", "Edit", "Write"} and timeout > 25


def test_other_hooks_are_untouched():
    for name in ("machine-guard.sh", "pre-tool-use.sh"):
        assert "leak" not in (ROOT / "plugin" / "hooks" / name).read_text().lower()


# --- the lexer behind it ------------------------------------------------------------------------------------

def test_the_lexer_splits_like_a_shell():
    from teyla.leak_guard import lex
    c = lex("a 'b c' \"d $(e f) g\" h\\ i; j | k && l")
    assert [x.words for x in c] == [["a", "b c", "d $(e f) g", "h i"], ["e", "f"], ["j"], ["k"], ["l"]]
    assert c[3].prev_pipe is c[2] and c[4].prev_pipe is None
    c = lex("cat <<'EOF' | gh pr comment 1 -F -\nit's (not) closed\nEOF\nls")
    assert c[0].heredocs == ["it's (not) closed"] and c[1].prev_pipe is c[0] and c[2].words == ["ls"]
    c = lex('git commit -m "$(cat <<\'EOF\'\nsubject\n\nbody with \'quotes\' and (parens\nEOF\n)" --amend')
    assert c[0].words[:3] == ["git", "commit", "-m"] and "body with 'quotes'" in c[0].words[3] and c[0].words[4] == "--amend"
    assert [x.words[0] for x in lex("echo `date` # tail")] == ["echo", "date"]
    assert lex("cat <<-EOF\n\tx\n\tEOF\n")[0].heredocs == ["\tx"]


def test_the_lexer_survives_garbage():
    from teyla.leak_guard import lex
    for text in ("", "'", '"', "$(", "`", "<<", "<<EOF", "a | | b", ")))", "((", "$((1+2))", "\\", "cat <<EOF\nunterminated"):
        lex(text)
