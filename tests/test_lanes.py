"""`teyla lanes`: subagent units by (type, model), cost from the transcripts, P1s from the review ledger.
All data is invented; the home directory is never read."""
from __future__ import annotations

import datetime as _dt
import json
import os

import pytest

from teyla import config, lanes, pricing

NOW = _dt.datetime(2026, 10, 12, 12, 0, tzinfo=_dt.timezone.utc)
SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"      # built by lane 1, reviewed with 2 P1s
SHA_B = "0123456789abcdef0123456789abcdef01234567"      # built by lane 2, reviewed clean, then a fix round
SHA_C = "fedcba9876543210fedcba9876543210fedcba98"      # reviewed BEFORE lane 4 started: not its work


@pytest.fixture(autouse=True)
def _list_prices(monkeypatch, tmp_path):
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _msg(ts, mid, model, out=0, inp=0, cread=0, cwrite=0, rid=None, text="ok"):
    return {"type": "assistant", "timestamp": ts, "requestId": rid or f"req-{mid}", "message": {
        "id": mid, "role": "assistant", "model": model,
        "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cread,
                  "cache_creation_input_tokens": cwrite},
        "content": [{"type": "text", "text": text}]}}


def _unit(root, proj, agent, kind, records, session="sess"):
    d = root / proj / session / "subagents"
    _write(str(d / f"agent-{agent}.jsonl"), records)
    if kind:
        (d / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": kind, "description": "d"}))


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "projects"
    # lane 1: Opus. The two records of message m2 share an id and request: the last one counts.
    _unit(r, "-Users-me-repos-app-a", "1", "lane", [
        _msg("2026-10-11T09:00:00Z", "m1", "claude-opus-5-5", out=10_000, inp=1_000, cread=50_000),
        _msg("2026-10-11T09:01:00Z", "m2", "claude-opus-5-5", out=1, inp=1_000, cread=80_000, rid="r2"),
        _msg("2026-10-11T09:01:01Z", "m2", "claude-opus-5-5", out=5_000, inp=1_000, cread=99_000, rid="r2",
             text=f"committed {SHA_A[:9]}"),
    ])
    # lane 2: Sonnet; its sha follows a newline, which the transcript stores as the two characters \n
    _unit(r, "-Users-me-repos-app-a", "2", "lane", [
        _msg("2026-10-11T10:00:00Z", "m1", "claude-sonnet-5-5", out=20_000, inp=500, cread=10_000, text=f"line\n{SHA_B}"),
    ])
    # lane 3: Sonnet, no sha at all
    _unit(r, "-Users-me-repos-app-b", "3", "lane", [
        _msg("2026-10-10T10:00:00Z", "m1", "claude-sonnet-5-5", out=2_000),
        _msg("2026-10-10T10:00:05Z", "m2", "claude-sonnet-5-5", out=2_000),
    ])
    # lane 4: names a commit reviewed before it began; untyped (no meta file)
    _unit(r, "-Users-me-repos-app-b", "4", None, [
        _msg("2026-10-11T11:00:00Z", "m1", "claude-sonnet-5-5", out=1_000, text=f"see {SHA_C}"),
    ])
    # lane 5: older than any window used below
    _unit(r, "-Users-me-repos-app-a", "5", "lane", [_msg("2026-09-01T09:00:00Z", "m1", "claude-opus-5-5", out=99_999)])
    # a main-session transcript is not a lane
    _write(str(r / "-Users-me-repos-app-a" / "sess.jsonl"), [_msg("2026-10-11T09:00:00Z", "x", "claude-fable-5-1", out=1_000_000)])
    return r


@pytest.fixture
def ledger(tmp_path):
    p = tmp_path / "ledger.tsv"
    rows = [
        ("2026-10-11T12:00:00Z", "app-a", SHA_A, "branch:src/", "2", "1", "codex"),
        ("2026-10-11T12:30:00Z", "app-a", SHA_B, "diff-file", "0", "2", "codex"),
        ("2026-10-11T13:00:00Z", "app-a", SHA_B, "commit", "0", "0", "codex"),
        ("2026-10-11T08:00:00Z", "app-b", SHA_C, "branch", "3", "0", "codex"),
        ("2026-10-11T14:00:00Z", "app-a", SHA_A, "skip:docs only", "-", "-", "review-gate"),
    ]
    p.write_text("\n".join("\t".join(r) for r in rows) + "\n")
    return p


def test_units_cost_turns_peak_and_dedup(root):
    units = {u["agent"]: u for u in lanes.scan(7, root=str(root), now=NOW)}
    assert set(units) == {"agent-1", "agent-2", "agent-3", "agent-4"}      # the old lane and the main session are out
    u = units["agent-1"]
    assert u["type"] == "lane" and u["model"] == "claude-opus-5-5" and u["project"] == "-Users-me-repos-app-a"
    assert u["turns"] == 2                                                   # m1 and m2: the repeated record counts once
    assert u["peak"] == 100_000                                              # 1_000 + 99_000 of the last record of m2
    expect = (1_000 * 4 + 50_000 * 0.2 + 10_000 * 20) / 1e6 + (1_000 * 4 + 99_000 * 0.2 + 5_000 * 20) / 1e6
    assert u["usd"] == pytest.approx(expect)
    assert units["agent-4"]["type"] == "(untyped)"


def test_window_is_by_message_time_and_project_filter(root):
    assert {u["agent"] for u in lanes.scan(2, root=str(root), now=NOW)} == {"agent-1", "agent-2", "agent-4"}   # lane 3 is 2 days old
    assert len(lanes.scan(None, root=str(root), now=NOW)) == 5
    assert {u["agent"] for u in lanes.scan(7, project="APP-B", root=str(root), now=NOW)} == {"agent-3", "agent-4"}
    assert lanes.scan(7, project="nothing", root=str(root), now=NOW) == []


def test_report_groups_by_type_and_model_and_reads_the_ledger(root, ledger):
    rep = lanes.report(7, root=str(root), ledger=ledger, now=NOW)
    rows = {(r["type"], r["model"]): r for r in rep["rows"]}
    assert set(rows) == {("lane", "claude-opus-5-5"), ("lane", "claude-sonnet-5-5"), ("(untyped)", "claude-sonnet-5-5")}
    opus = rows[("lane", "claude-opus-5-5")]
    assert opus["units"] == 1 and opus["median_turns"] == 2 and opus["median_peak"] == 100_000
    assert opus["matched"] == 1 and opus["p1_per_unit"] == 2.0 and opus["units_with_p1"] == 1
    sonnet = rows[("lane", "claude-sonnet-5-5")]
    assert sonnet["units"] == 2 and sonnet["median_turns"] == 1.5            # lane 2 (1 turn) and lane 3 (2)
    assert sonnet["matched"] == 1                                            # lane 2: a clean review plus a fix round
    assert sonnet["p1_per_unit"] == 0.0 and sonnet["units_with_p1"] == 0
    assert rows[("(untyped)", "claude-sonnet-5-5")]["matched"] == 0          # its commit was reviewed before it began
    assert rows[("(untyped)", "claude-sonnet-5-5")]["p1_per_unit"] is None
    assert [r["total_usd"] for r in rep["rows"]] == sorted((r["total_usd"] for r in rep["rows"]), reverse=True)
    assert rep["total_usd"] == pytest.approx(sum(r["total_usd"] for r in rep["rows"]), abs=0.02)


def test_a_missing_ledger_leaves_the_review_columns_empty(root, tmp_path):
    rep = lanes.report(7, root=str(root), ledger=tmp_path / "gone.tsv", now=NOW)
    assert rep["ledger"] is None and all(r["matched"] is None and r["p1_per_unit"] is None for r in rep["rows"])
    text = lanes.render(rep)
    assert "no review ledger" in text and lanes.CONFOUNDED in text


def test_render_has_the_columns_and_the_confounding_footer(root, ledger):
    text = lanes.render(lanes.report(7, root=str(root), ledger=ledger, now=NOW))
    for col in ("type", "model", "units", "turns", "peak ctx", "med $", "total $", "matched", "P1/unit", "with P1"):
        assert col in text
    line = next(l for l in text.splitlines() if l.startswith("lane") and "opus" in l)
    assert " 2.00 " in line and "100k" in line
    assert text.rstrip().endswith(lanes.CONFOUNDED) and "confounded by task difficulty" in text
    empty = lanes.render(dict(days=7, project="zzz", units=0, ledger=None, total_usd=0, rows=[]))
    assert "no subagent lanes" in empty and "zzz" in empty


def test_cli_wiring_json_and_flags(root, ledger, monkeypatch, capsys):
    from teyla import cli, reviews
    from teyla.adapters import claude_code
    monkeypatch.setattr(config, "apply_env", lambda *a, **k: None)
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(root))
    monkeypatch.setattr(reviews, "ledger_path", lambda cfg=None: ledger)
    assert cli.main(["lanes", "--days", "3650", "--project", "app-a", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "app-a" and data["units"] == 3 and "confounded" in data["footer"]
    assert cli.main(["lanes"]) == 0
    assert "teyla lanes" in capsys.readouterr().out
    assert "teyla lanes" in cli.__doc__


def test_family_names_models_by_what_they_are():
    f = pricing.family
    assert [f(m) for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1",
                           "claude-opus-5-20260401")] == ["opus", "sonnet", "haiku", "fable", "opus"]
    assert [f(m) for m in ("gpt-6.1-sol", "grok-4.7", "", None, "mystery")] == ["other"] * 5
    assert pricing.tier("claude-opus-5-5") == pricing.tier("claude-sonnet-5-5") == "volume"   # why a family column exists


def test_config_set_writes_the_opus_threshold_as_a_number(tmp_path):
    p = tmp_path / "config.toml"
    config.set_value("spend.opus_share_max", "0.4", p)
    assert "opus_share_max = 0.4" in p.read_text()
    assert "not a number" in config.set_value("spend.opus_share_max", "lots", p)
