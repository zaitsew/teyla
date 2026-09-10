"""A10 acknowledgement: `teyla policy ack` writes ~/.teyla/ack.json (owned by another change);
advise() only reads it, to decide whether a governance-file edit is still worth flagging.

Every test here runs with HOME pointed at a tmp dir so nothing touches the real
~/.teyla/ack.json or ~/.claude/CLAUDE.md on the machine running the suite.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from teyla.adapters import Session, Turn
from teyla.advise import advise
from teyla.monitor import metrics


def _session_with_gov_edit(sid, day):
    s = Session(harness="claude-code", project="demo", sid=sid, path=f"/tmp/{sid}.jsonl", size=1000)
    s.first = f"{day}T00:00:00Z"
    s.last = f"{day}T01:00:00Z"
    s.usage["claude-sonnet-5"] = Counter(input_tokens=100, output_tokens=50,
                                          cache_read_input_tokens=10, cache_creation_input_tokens=0)
    s.user_turns = [Turn(f"{day}T00:00:00Z", "do the thing", False)]
    s.gov_edits = 1
    return s


def _write_home_files(tmp_path, monkeypatch, claude_md_text, ack=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "CLAUDE.md").write_text(claude_md_text)
    if ack is not None:
        teyla_dir = tmp_path / ".teyla"
        teyla_dir.mkdir(parents=True, exist_ok=True)
        (teyla_dir / "ack.json").write_text(json.dumps(ack))


def test_a10_fires_normally_with_no_ack_file(tmp_path, monkeypatch):
    _write_home_files(tmp_path, monkeypatch, "policy text v1")
    m = metrics([_session_with_gov_edit("s1", "2026-09-09")])
    findings = advise(m)
    assert "A10" in [f["id"] for f in findings]


def test_a10_suppressed_for_acked_edit_on_or_before_ack_date(tmp_path, monkeypatch):
    text = "policy text v1"
    sha = hashlib.sha256(text.encode()).hexdigest()
    _write_home_files(tmp_path, monkeypatch, text, ack={"claude_md": {"sha256": sha, "date": "2026-09-09"}})
    m = metrics([_session_with_gov_edit("s1", "2026-09-09")])
    findings = advise(m)
    assert "A10" not in [f["id"] for f in findings]


def test_a10_still_fires_for_edit_after_ack_date(tmp_path, monkeypatch):
    text = "policy text v1"
    sha = hashlib.sha256(text.encode()).hexdigest()
    _write_home_files(tmp_path, monkeypatch, text, ack={"claude_md": {"sha256": sha, "date": "2026-09-01"}})
    m = metrics([_session_with_gov_edit("s1", "2026-09-09")])
    findings = advise(m)
    ids = [f["id"] for f in findings]
    assert "A10" in ids
    a10 = next(f for f in findings if f["id"] == "A10")
    assert "changed since your ack" not in a10["evidence"]


def test_a10_fires_with_changed_evidence_when_hash_no_longer_matches_ack(tmp_path, monkeypatch):
    sha_of_old_text = hashlib.sha256(b"policy text v0").hexdigest()
    _write_home_files(tmp_path, monkeypatch, "policy text v1 - edited",
                       ack={"claude_md": {"sha256": sha_of_old_text, "date": "2026-09-01"}})
    m = metrics([_session_with_gov_edit("s1", "2026-09-09")])
    findings = advise(m)
    ids = [f["id"] for f in findings]
    assert "A10" in ids
    a10 = next(f for f in findings if f["id"] == "A10")
    assert "file changed since your ack on 2026-09-01" in a10["evidence"]


def test_a10_action_text_mentions_teyla_policy_ack(tmp_path, monkeypatch):
    _write_home_files(tmp_path, monkeypatch, "policy text v1")
    m = metrics([_session_with_gov_edit("s1", "2026-09-09")])
    findings = advise(m)
    a10 = next(f for f in findings if f["id"] == "A10")
    assert "teyla policy ack" in a10["action"]
