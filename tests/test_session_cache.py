"""The parsed-transcript cache (`teyla.adapters.cache`): synthetic transcripts in tmp dirs only."""
from __future__ import annotations

import json
import os
import stat

import pytest

from teyla.adapters import cache, claude_code, codex


def _write(path, lines, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _asst(ts, mid, out):
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": "claude-sonnet-5", "usage": {"input_tokens": 1, "output_tokens": out},
                        "content": [{"type": "text", "text": "ok"}]}}


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "projects"
    f = root / "slug" / "s1.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "add a login button"}},
        _asst("2026-01-01T00:00:05Z", "m1", 50),
    ])
    sub = root / "slug" / "s1" / "subagents" / "agent-a.jsonl"
    _write(str(sub), [_asst("2026-01-01T00:00:06Z", "x1", 7)])
    return root, f, sub


def _parse_calls(monkeypatch):
    calls = []
    real = claude_code.parse
    monkeypatch.setattr(claude_code, "parse", lambda f, r=None: calls.append(f) or real(f, r))
    return calls


def test_second_load_hits_cache_and_matches(tree, monkeypatch):
    root, f, _ = tree
    first = claude_code.load(root=str(root))
    calls = _parse_calls(monkeypatch)
    second = claude_code.load(root=str(root))
    assert calls == []
    assert second == first
    assert second[0].usage["claude-sonnet-5"]["output_tokens"] == 57
    assert second[0].day_usage["2026-01-01"]["claude-sonnet-5"]["output_tokens"] == 57
    second[0].usage["new-model"]["output_tokens"] += 1  # defaultdict behaviour survives the round trip


def test_appending_to_transcript_invalidates(tree, monkeypatch):
    root, f, _ = tree
    claude_code.load(root=str(root))
    _write(str(f), [_asst("2026-01-01T00:00:09Z", "m2", 5)], mode="a")
    calls = _parse_calls(monkeypatch)
    s = claude_code.load(root=str(root))
    assert calls == [str(f)]
    assert s[0].usage["claude-sonnet-5"]["output_tokens"] == 62


def test_appending_to_subagent_file_invalidates(tree, monkeypatch):
    root, f, sub = tree
    claude_code.load(root=str(root))
    _write(str(sub), [_asst("2026-01-01T00:00:07Z", "x2", 3)], mode="a")
    calls = _parse_calls(monkeypatch)
    s = claude_code.load(root=str(root))
    assert calls == [str(f)]
    assert s[0].usage["claude-sonnet-5"]["output_tokens"] == 60


def test_new_subagent_file_invalidates(tree, monkeypatch):
    root, f, sub = tree
    claude_code.load(root=str(root))
    _write(str(sub.with_name("agent-b.jsonl")), [_asst("2026-01-01T00:00:08Z", "y1", 4)])
    calls = _parse_calls(monkeypatch)
    claude_code.load(root=str(root))
    assert calls == [str(f)]


def test_different_repo_names_miss(tree, monkeypatch):
    root, f, _ = tree
    claude_code.load(root=str(root), repo_names=["demo"])
    calls = _parse_calls(monkeypatch)
    claude_code.load(root=str(root), repo_names=["demo"])
    assert calls == []
    claude_code.load(root=str(root), repo_names=["other"])
    assert calls == [str(f)]


def test_bumped_parser_version_misses(tree, monkeypatch):
    root, f, _ = tree
    claude_code.load(root=str(root))
    monkeypatch.setattr(claude_code, "PARSER_VERSION", claude_code.PARSER_VERSION + 1)
    calls = _parse_calls(monkeypatch)
    claude_code.load(root=str(root))
    assert calls == [str(f)]


def test_corrupt_entry_is_ignored_and_rewritten(tree, monkeypatch):
    root, f, _ = tree
    claude_code.load(root=str(root))
    entries = list(cache.cache_dir().glob("*.pkl"))
    assert len(entries) == 1
    entries[0].write_bytes(b"not a pickle")
    calls = _parse_calls(monkeypatch)
    assert claude_code.load(root=str(root))[0].sid == "s1"
    assert calls == [str(f)]
    calls.clear()
    claude_code.load(root=str(root))
    assert calls == []  # rewritten


def test_files_are_private(tree):
    root, _, _ = tree
    claude_code.load(root=str(root))
    d = cache.cache_dir()
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    for p in d.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert not list(d.glob("*.tmp"))


def test_no_cache_env_bypasses(tree, monkeypatch):
    root, f, _ = tree
    monkeypatch.setenv("TEYLA_NO_CACHE", "1")
    claude_code.load(root=str(root))
    assert not cache.cache_dir().exists()
    calls = _parse_calls(monkeypatch)
    claude_code.load(root=str(root))
    assert calls == [str(f)]


def test_prune_removes_old_untouched_entries(tree):
    root, _, _ = tree
    claude_code.load(root=str(root))
    stale = cache.cache_dir() / ("0" * 40 + ".pkl")
    stale.write_bytes(b"x")
    old = os.stat(stale).st_mtime - 40 * 24 * 3600
    os.utime(stale, (old, old))
    fresh = cache.cache_dir() / ("1" * 40 + ".pkl")
    fresh.write_bytes(b"x")
    cache._touched.clear()
    assert cache.prune() == 1
    assert not stale.exists() and fresh.exists()


def test_subagent_prefilter_keeps_first_timestamp(tmp_path):
    f = tmp_path / "slug" / "s.jsonl"
    _write(str(f), [{"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "hi"}}])
    sub = tmp_path / "slug" / "s" / "subagents" / "a.jsonl"
    _write(str(sub), [
        {"type": "user", "timestamp": "2026-01-01T00:00:01Z", "message": {"content": "task"}},
        {"type": "user", "timestamp": "2026-01-01T00:00:02Z", "message": {"content": "more"}},
        _asst("2026-01-01T00:00:03Z", "z", 9),
    ])
    per_message, calls = claude_code._subagent_usage(str(f))
    assert calls == [("2026-01-01T00:00:01Z", "claude-sonnet-5")]
    assert list(per_message.values())[0][1]["output_tokens"] == 9


def test_codex_cache_applies_title_from_index_after_the_hit(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    f = root / "2026" / "01" / "01" / "rollout-2026-01-01T00-00-00-abc123.jsonl"
    _write(str(f), [
        {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": {"id": "abc123", "cwd": "/w"}},
    ])
    index = tmp_path / "index.jsonl"
    _write(str(index), [{"id": "abc123", "thread_name": "First"}])
    kw = dict(root=str(root), archive_root="", index_path=str(index))
    a = codex.load(**kw)
    assert a and a[0].title == "First"
    _write(str(index), [{"id": "abc123", "thread_name": "Renamed"}])
    calls = []
    real = codex.parse
    monkeypatch.setattr(codex, "parse", lambda *a_, **k: calls.append(1) or real(*a_, **k))
    b = codex.load(**kw)
    assert calls == [] and b[0].title == "Renamed"


def test_torn_read_is_not_stored(tree, monkeypatch):
    root, f, _ = tree
    real = claude_code.parse

    def appending(path, repo_names=None):
        s = real(path, repo_names)
        _write(path, [_asst("2026-01-01T00:00:09Z", "late", 5)], mode="a")  # the session grew mid-read
        return s

    monkeypatch.setattr(claude_code, "parse", appending)
    claude_code.load(root=str(root))
    assert not list(cache.cache_dir().glob("*.pkl"))


def test_prune_drops_entry_whose_transcript_is_gone_but_not_for_a_missing_root(tree, tmp_path):
    root, f, _ = tree
    claude_code.load(root=str(root))
    cache._touched.clear()
    assert cache.prune() == 0  # transcript still there
    os.unlink(f)
    assert cache.prune() == 1
    claude_code.load(root=str(root))  # no transcript now: nothing parsed, nothing stored
    gone_root = tmp_path / "unmounted" / "slug" / "x.jsonl"
    key = cache.make_key(str(f), "claude-code", 1)
    assert key is None
    # an entry whose whole folder is missing is kept (unreadable root), until it is 30 days old
    _write(str(gone_root), [{"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "x"}}])
    k = cache.make_key(str(gone_root), "claude-code", 1)
    cache.put(k, claude_code.parse(str(gone_root)))
    cache._touched.clear()
    os.unlink(gone_root)
    os.rmdir(gone_root.parent)
    assert cache.prune() == 0


def test_cached_and_uncached_totals_are_identical(tree, monkeypatch):
    root, _, _ = tree

    def totals(ss):
        return {s.sid: {m: dict(c) for m, c in s.usage.items()} for s in ss}

    cold = claude_code.load(root=str(root))
    warm = claude_code.load(root=str(root))
    monkeypatch.setenv("TEYLA_NO_CACHE", "1")
    raw = claude_code.load(root=str(root))
    assert totals(cold) == totals(warm) == totals(raw)
    assert warm == raw


def test_format_or_foreign_key_is_a_miss(tree, monkeypatch):
    root, f, _ = tree
    claude_code.load(root=str(root))
    monkeypatch.setattr(cache, "_FORMAT", cache._FORMAT + 1)
    calls = _parse_calls(monkeypatch)
    claude_code.load(root=str(root))
    assert calls == [str(f)]
