"""`teyla prose`: reply metrics on synthetic transcripts, the policy and voice templates.
All text is invented; the home directory is never read."""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re

import pytest

from teyla import prose
from teyla.adapters import claude_code, codex

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = _dt.datetime(2026, 10, 16, 12, 0, tzinfo=_dt.timezone.utc)


@pytest.fixture(autouse=True)
def _home(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/me")        # project_of names /Users/me/repos/demo "demo"


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _words(n, word="word"):
    return " ".join([word] * n) + "."


# --- measure ---------------------------------------------------------------------------------

def test_measure_counts_words_sentences_and_skips_code():
    text = "Fixed it. The cache key was wrong.\n```\n" + "x " * 200 + "\n```\n| a | b |\n- Next step is a release."
    m = prose.measure(text)
    assert m["words"] == 2 + 5 + 5                  # code fence and table row do not count
    assert m["sentences"] == [2, 5, 5]
    assert not m["preamble"]
    assert not m["bans"]


def test_measure_long_sentence():
    m = prose.measure(_words(30) + " Short one.")
    assert m["sentences"] == [30, 2]


def test_measure_ban_hits_with_forms_and_apostrophes():
    text = "We leverage it, then leveraged it. It’s important to note this is robust and seamless. Delve deeper."
    m = prose.measure(text)
    assert m["bans"]["leverage"] == 2
    assert m["bans"]["it's important to note"] == 1
    assert m["bans"]["robust"] == 1 and m["bans"]["seamless"] == 1 and m["bans"]["delve"] == 1
    assert "comprehensively" not in m["bans"]


def test_measure_does_not_match_inside_words():
    assert not prose.measure("The lever moved. A robustness check ran. Comprehension is fine.")["bans"]


@pytest.mark.parametrize("text,expected", [
    ("Let me check the logs first.", True),
    ("I'll start with the config.", True),
    ("Great, that works.", True),
    ("Sure - here it is.", True),
    ("Okay. Done.", True),
    ("**Let me** do it.", True),
    ("Done. Let me know if you want more.", False),
    ("Greater load fixed.", False),
    ("Surely not.", False),
    ("The result: 12 files.", False),
])
def test_measure_preamble(text, expected):
    assert prose.measure(text)["preamble"] is expected


# --- adapters: which replies the human saw ---------------------------------------------------

def _claude_assistant(ts, text=None, tool=False, model="claude-sonnet-5-5", error=False):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
    o = {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": model, "content": content, "usage": {}}}
    if error:
        o["isApiErrorMessage"] = True
    return o


def _claude_user(ts, text, **extra):
    return dict({"type": "user", "timestamp": ts, "cwd": "/Users/me/repos/demo",
                 "message": {"role": "user", "content": text}}, **extra)


def test_claude_finals_are_the_text_before_a_human_turn_plus_the_last(tmp_path):
    f = tmp_path / "projects" / "-Users-me-repos-demo" / "s1.jsonl"
    _write(str(f), [
        _claude_user("2026-10-15T09:00:00Z", "fix the build"),
        _claude_assistant("2026-10-15T09:00:05Z", "I'll look at the build first.", tool=True),   # mid-turn: not final
        _claude_assistant("2026-10-15T09:00:09Z", "Build fixed. One flag was wrong."),
        _claude_user("2026-10-15T09:01:00Z", "thanks, now the tests"),
        _claude_assistant("2026-10-15T09:01:30Z", "API Error: cannot reach the server", error=True),
        _claude_user("2026-10-15T09:02:00Z", "try again"),
        _claude_assistant("2026-10-15T09:02:10Z", "Tests pass. 12 of 12."),
    ])
    s, = claude_code.load(root=str(tmp_path / "projects"))
    assert [t for _, t in s.finals] == ["Build fixed. One flag was wrong.", "Tests pass. 12 of 12."]
    assert "finals" not in s.to_dict()


def test_codex_finals_skip_commentary(tmp_path):
    f = tmp_path / "sessions" / "2026" / "10" / "15" / "rollout-2026-10-15T09-00-00-abc.jsonl"

    def msg(ts, role, text, phase=None):
        p = {"type": "message", "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}
        if phase:
            p["phase"] = phase
        return {"timestamp": ts, "type": "response_item", "payload": p}
    _write(str(f), [
        {"timestamp": "2026-10-15T09:00:00.000Z", "type": "session_meta", "payload": {"session_id": "abc", "cwd": "/Users/me/repos/demo", "originator": "codex_cli_rs", "source": "cli"}},
        msg("2026-10-15T09:00:01.000Z", "user", "fix the build"),
        msg("2026-10-15T09:00:02.000Z", "assistant", "Checking the config.", phase="commentary"),
        msg("2026-10-15T09:00:09.000Z", "assistant", "Build fixed.", phase="final_answer"),
        msg("2026-10-15T09:01:00.000Z", "user", "and the tests"),
        msg("2026-10-15T09:01:30.000Z", "assistant", "Tests pass."),
    ])
    s, = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "x"), index_path=str(tmp_path / "x.jsonl"))
    assert [t for _, t in s.finals] == ["Build fixed.", "Tests pass."]


# --- report ----------------------------------------------------------------------------------

@pytest.fixture
def sessions(tmp_path):
    p = tmp_path / "projects"
    long_reply = "Let me explain. " + _words(300) + " It is robust and seamless."
    # 12 interactive turns: each ends with a long reply, so advice fires.
    recs = []
    for i in range(12):
        recs.append(_claude_user(f"2026-10-15T09:{i:02d}:00Z", f"question {i}"))
        recs.append(_claude_assistant(f"2026-10-15T09:{i:02d}:30Z", long_reply))
    _write(str(p / "-Users-me-repos-demo" / "interactive.jsonl"), recs)
    # a headless run (claude -p): the same long replies, never counted
    _write(str(p / "-Users-me-repos-demo" / "headless.jsonl"), [
        dict(_claude_user("2026-10-15T10:00:00Z", "brief", entrypoint="sdk-cli")),
        dict(_claude_assistant("2026-10-15T10:00:30Z", long_reply), entrypoint="sdk-cli"),
    ])
    # an old session: out of the window
    _write(str(p / "-Users-me-repos-demo" / "old.jsonl"), [
        _claude_user("2026-09-01T09:00:00Z", "old question"),
        _claude_assistant("2026-09-01T09:00:30Z", long_reply),
    ])
    return claude_code.load(root=str(p))


def test_report_skips_automation_and_old_replies(sessions):
    rep = prose.report(7, sessions=sessions, now=NOW)
    assert rep["replies"] == 12
    cc = rep["harnesses"]["claude-code"]
    assert cc["replies"] == 12 and cc["median_words"] > 300 and cc["over_150"] == 1.0
    assert cc["preamble"] == 1.0
    assert dict(cc["top_bans"])["robust"] == 12
    assert [p["project"] for p in rep["projects"]] == ["demo"]


def test_report_sidechain_is_skipped(sessions):
    for s in sessions:
        s.sidechain = True
    assert prose.report(7, sessions=sessions, now=NOW)["replies"] == 0


def test_report_project_filter(sessions):
    assert prose.report(7, project="nope", sessions=sessions, now=NOW)["replies"] == 0
    assert prose.report(7, project="DEM", sessions=sessions, now=NOW)["replies"] == 12


def test_advice_lines_and_threshold(sessions):
    rep = prose.report(7, sessions=sessions, now=NOW)
    text = "\n".join(rep["advice"])
    assert text.startswith("Claude replies: median ")
    assert "100% over 150" in text and "open with a preamble" in text and "ban-list hits" in text
    assert "12 lines" in text


def test_advice_silent_for_a_small_or_clean_group():
    clean = prose.summarize([dict(prose.measure("Done. 3 files changed."), harness="codex", project="p")] * 12)
    assert prose.advice("Codex", clean) == []
    few = prose.summarize([dict(prose.measure(_words(400)), harness="codex", project="p")] * 3)
    assert prose.advice("Codex", few) == []


def test_render_and_empty(sessions):
    out = prose.render(prose.report(7, sessions=sessions, now=NOW))
    assert "teyla prose" in out and "claude-code" in out and "demo (cc)" in out and "robust" in out
    assert "no replies" in prose.render(prose.report(7, sessions=[], now=NOW))


def test_digest_candidate_only_over_target(monkeypatch):
    def fake(replies, median):
        monkeypatch.setattr(prose, "report", lambda days=7, **k: {"replies": replies, "overall": {"median_words": median}})
    fake(12, 240)
    c, = prose.digest_candidates()
    assert c["text"] == "reply length: median 240 words (target <= 150)" and c["step"] == "teyla prose"
    fake(12, 90)
    assert prose.digest_candidates() == []
    fake(3, 900)                                       # too few replies to judge
    assert prose.digest_candidates() == []


# --- templates -------------------------------------------------------------------------------

def _section(path, number):
    text = (ROOT / "templates" / path).read_text()
    m = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, re.S | re.M)
    assert m, f"{path} has no section {number}"
    return m.group(0).rstrip("\n")


def test_policy_section_is_short_and_has_the_card():
    sec = _section("POLICY.md", 13)
    assert len(sec.splitlines()) <= 45
    assert sec.splitlines()[0].startswith("## 13. Writing and reporting")
    for needle in ("Done | Blocked | Needs you | Failed", "at most 12 lines", "teyla prose", "never translated", "20 words", "25"):
        assert needle in sec
    for phrase in ("delve", "comprehensive", "robust", "seamless", "leverage", "I hope this helps", "Great question"):
        assert phrase in sec


def test_work_policy_mirrors_a_shortened_section():
    sec = _section("POLICY.work.md", 11)
    assert len(sec.splitlines()) < len(_section("POLICY.md", 13).splitlines())
    assert "Done | Blocked | Needs you | Failed" in sec and "teyla prose" in sec


def test_policy_templates_keep_their_fences_balanced():
    for name in ("POLICY.md", "POLICY.work.md"):
        assert (ROOT / "templates" / name).read_text().count("```") % 2 == 0


def test_voice_template_shape():
    text = (ROOT / "templates" / "voice" / "VOICE.md").read_text()
    assert len(text.splitlines()) <= 80
    for needle in ("## Traits", "## Tone by channel", "### English", "### Spanish", "### Russian", "## Before posting",
                   "Ilyakhov", "Glavred", "Guia panhispanica de lenguaje claro", "never translate", "X / Twitter",
                   "Instagram / TikTok", "LinkedIn", "App Store", "Email"):
        assert needle.lower() in text.lower(), needle
    assert not re.search("[\u0400-\u04ff]", text)


def test_vale_ban_list_matches_the_constant():
    yml = (ROOT / "templates" / "vale" / "styles" / "Teyla" / "Filler.yml").read_text()
    tokens = {t.strip().lower() for t in re.findall(r"^\s+- (.+)$", yml, re.M)}
    assert {p.lower() for p in prose.BAN_LIST} <= tokens
    assert (ROOT / "templates" / "vale" / ".vale.ini").read_text().count("BasedOnStyles = Teyla") == 1
    assert "untested" in (ROOT / "templates" / "vale" / "styles" / "Teyla" / "Sentences.yml").read_text().lower()


def test_writing_doc_is_short_and_names_the_templates():
    text = (ROOT / "docs" / "WRITING.md").read_text()
    assert len(text.splitlines()) <= 50
    assert "templates/voice/VOICE.md" in text and "templates/vale/" in text and "teyla prose" in text


def test_a_sentence_wrapped_over_two_lines_counts_as_one():
    from teyla.prose import measure
    line1 = " ".join(["word"] * 20)
    line2 = " ".join(["more"] * 20) + "."
    m = measure(line1 + "\n" + line2 + "\n\n- a bullet.\n- another bullet.")
    assert m["sentences"][0] == 40
    assert m["sentences"][1:] == [2, 2]
