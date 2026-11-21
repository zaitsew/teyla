"""The generic leak rules against disguised input: zero-width and fullwidth characters in an address, a home path
at the end of a line, a Windows home path, a Telegram bot token, and one rule set for `teyla leak --text` and
`leak_check.py --text`. Every value is invented; the ones that look like leaks are built from parts at run time."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from teyla import leak

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"
AT, ZW, FULL_AT = "@", "\u200b", "\uff20"
USERS = "/" + "Users"
BOT = "1234567890" + ":" + "A" * 35          # a fake bot id and 35 characters
GENERIC = "token=Abc123Def456Ghi789Jkl012Mno"


@pytest.fixture(autouse=True)
def no_terms(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "no-terms.txt"))


def run_check(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    f = tmp_path / "in.txt"
    f.write_text(text + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), "--text", str(f)], cwd=tmp_path, capture_output=True,
                          text=True, env=os.environ.copy())


def check(tmp_path: Path, text: str) -> tuple[int, list[str]]:
    p = run_check(tmp_path, text)
    return p.returncode, [ln.split(": ")[1] for ln in p.stdout.splitlines()]


@pytest.mark.parametrize("text,rule", [
    ("jane" + AT + "exa" + ZW + "mple.org.net", "email"),                      # zero-width space in the domain
    ("ja" + ZW + "ne" + AT + "corp.net", "email"),                             # in the local part
    ("jane" + FULL_AT + "corp.net", "email"),                                  # fullwidth at sign
    ("jane" + AT + "corp\uff0enet", "email"),                                  # fullwidth dot
    ("\ufeffjane" + AT + "corp.net", "email"),                                 # byte-order mark
    ("cd " + USERS + "/jdoe", "home"),                                         # end of line, no trailing slash
    ("open " + USERS + "/jdoe.", "home"),
    ("\"" + USERS + "/jdoe\"", "home"),
    ("/ho" + "me/jdoe", "home"),
    ("C:\\" + "Users\\jdoe\\Documents", "home"),
    ("C:\\\\" + "Users\\\\jdoe", "home"),                                      # escaped backslashes
    ("token " + BOT, "secret"),
    ("bot=" + BOT + " end", "secret"),
])
def test_caught(tmp_path, text, rule):
    code, found = check(tmp_path, text)
    assert code == 1 and rule in found


@pytest.mark.parametrize("text", [
    "jane" + AT + "example.com", "jane" + AT + "exa" + ZW + "mple.com",       # an allowed domain stays allowed
    "jane" + FULL_AT + "example.org",
    "cd " + USERS + "/Shared", USERS + "/you", USERS + "/<name>", USERS + "/me/repos", "/home/x",
    "C:\\" + "Users\\Public", "C:\\" + "Users\\<name>\\x",
    "12345:short", "1234567890:" + "A" * 20, "id 12345678901:" + "A" * 35,    # not a bot token shape
    "plain text, no leak",
])
def test_still_allowed(tmp_path, text):
    code, found = check(tmp_path, text)
    assert code == 0 and found == []


def test_line_numbers_survive_normalization(tmp_path):
    p = run_check(tmp_path, "one\n" + ZW + "two\n" + "jane" + AT + "cor" + ZW + "p.net")
    assert p.returncode == 1 and ":3: email" in p.stdout and p.stdout.count("\n") == 1


def test_generic_token_in_text_is_listed_by_both_doors(tmp_path):
    code, found = check(tmp_path, GENERIC)
    assert code == 0 and found == ["secret-generic"]          # listed, never blocking: as `teyla leak --text`
    assert [f.rule for f in leak.scan_text(GENERIC)] == ["secret-generic"]


@pytest.mark.parametrize("text", [
    GENERIC, "jane" + AT + "cor" + ZW + "p.net", "cd " + USERS + "/jdoe",
    "C:\\" + "Users\\jdoe", BOT, "nothing here", "jane" + AT + "example.com",
])
def test_both_doors_agree(text):
    eng = leak._engine()
    mine = sorted({f.rule for f in eng.scan_text("t", text, eng.Config())})
    theirs = sorted({f.rule for f in leak.scan_text(text)})
    assert mine == theirs


def test_a_generic_finding_does_not_hide_a_blocker(tmp_path):
    code, found = check(tmp_path, GENERIC + "\njane" + AT + "corp.net")
    assert code == 1 and sorted(found) == ["email", "secret-generic"]


def test_a_private_term_is_normalized_like_the_text(tmp_path, monkeypatch):
    terms = tmp_path / "terms.txt"
    terms.write_text("Zo" + ZW + "rbak\n\uff2dorvane\n", encoding="utf-8")     # zero-width char, fullwidth letter
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    for text in ("about Zorbak here", "about Mo" + ZW + "rvane here", "about Morvane here"):
        code, found = check(tmp_path, text)
        assert code == 1 and "term" in found, text
