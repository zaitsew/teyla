"""teyla.toml parser + routine/check verdict logic, built from tmp fixtures."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pytest

from teyla.routines import (
    ManifestError,
    check_age_days,
    check_verdict,
    evaluate,
    counts_line,
    exit_code,
    loaded_state,
    parse_manifest,
    render_text,
    routine_verdict,
    summarize,
)

GOOD_TOML = """
[product]
name = "my-app"
usage = "./check.sh usage"

[[routine]]
name = "nightly-sync"
kind = "launchd"
label = "com.example.sync"
every = "1d"
log = "~/Library/Logs/app-sync.log"

[[check]]
name = "log an entry from a photo"
how = "app -> New -> photo -> caption"
status = "broken"
confirmed = 2026-09-09
"""


def write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "teyla.toml"
    p.write_text(text)
    return p


def test_parse_manifest_ok(tmp_path):
    p = write(tmp_path, GOOD_TOML)
    m = parse_manifest(p)
    assert m["product"]["name"] == "my-app"
    assert len(m["routines"]) == 1
    assert m["routines"][0]["kind"] == "launchd"
    assert len(m["checks"]) == 1
    assert m["checks"][0]["status"] == "broken"


def test_parse_manifest_missing_product_name(tmp_path):
    p = write(tmp_path, "[product]\n")
    with pytest.raises(ManifestError):
        parse_manifest(p)


def test_parse_manifest_bad_routine_kind(tmp_path):
    p = write(tmp_path, """
[product]
name = "x"
[[routine]]
name = "r"
kind = "carrier-pigeon"
label = "x"
every = "1d"
""")
    with pytest.raises(ManifestError):
        parse_manifest(p)


def test_parse_manifest_bad_cadence(tmp_path):
    p = write(tmp_path, """
[product]
name = "x"
[[routine]]
name = "r"
kind = "script"
label = "x"
every = "monthly"
""")
    with pytest.raises(ManifestError):
        parse_manifest(p)


def test_parse_manifest_bad_check_status(tmp_path):
    p = write(tmp_path, """
[product]
name = "x"
[[check]]
name = "c"
how = "do a thing"
status = "kinda"
""")
    with pytest.raises(ManifestError):
        parse_manifest(p)


def test_parse_manifest_bad_check_status_names_the_allowed_values(tmp_path):
    p = write(tmp_path, """
[product]
name = "x"
[[check]]
name = "c"
how = "do a thing"
status = "partially verified — link-opening confirmed on both platforms, but on the old address"
""")
    with pytest.raises(ManifestError) as e:
        parse_manifest(p)
    msg = str(e.value)
    assert "ok, broken, untested" in msg and "note =" in msg and "…" in msg


def test_any_n_m_h_d_cadence_is_accepted(tmp_path):
    from teyla.routines import cadence
    assert cadence("5m") == dt.timedelta(minutes=5) and cadence("12h") == dt.timedelta(hours=12)
    assert cadence("7d") == dt.timedelta(days=7) and cadence("unscheduled") is None and cadence("weekly") is None
    r = {"name": "agent", "kind": "launchd", "label": "x", "every": "5m"}
    now = dt.datetime.now(dt.timezone.utc)
    assert routine_verdict(r, "loaded", now - dt.timedelta(minutes=9), now=now) == "ok"
    assert routine_verdict(r, "loaded", now - dt.timedelta(minutes=11), now=now) == "STALE"
    p = write(tmp_path, """
[product]
name = "x"
[[routine]]
name = "agent"
kind = "launchd"
label = "com.x.agent"
every = "5m"
""")
    assert parse_manifest(p)["routines"][0]["every"] == "5m"


def test_script_routine_needs_only_a_name(tmp_path):
    """guiri's backend is a container with restart: unless-stopped and a health URL — no
    scheduler label, no cadence. The row is shown as unknown rather than the product refused."""
    p = write(tmp_path, """
[product]
name = "guiri"
[[routine]]
name = "backend"
kind = "script"
how = "curl -fsS https://example.com/health"
note = "a container, not a job"
""")
    m = parse_manifest(p)
    r = m["routines"][0]
    assert r["label"] == "backend" and r["every"] == "unscheduled"
    assert routine_verdict(r, "unknown", None) == "unknown"
    assert routine_verdict(r, "unknown", dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=400)) == "ok"
    rep = evaluate(m)
    assert rep["routines"][0]["verdict"] == "unknown"


def test_parse_manifest_invalid_toml(tmp_path):
    p = write(tmp_path, "not toml [[[")
    with pytest.raises(ManifestError):
        parse_manifest(p)


# --- routine verdicts ---------------------------------------------------------

def test_loaded_state_launchd_running():
    out = loaded_state({"kind": "launchd", "label": "com.example.sync"},
                        launchctl_output="1234\t0\tcom.example.sync\n5678\t0\tother.label\n")
    assert "pid 1234" in out


def test_loaded_state_launchd_not_loaded():
    out = loaded_state({"kind": "launchd", "label": "com.example.sync"}, launchctl_output="")
    assert out == "not loaded"


def test_loaded_state_cron_found():
    out = loaded_state({"kind": "cron", "label": "app-sync"}, crontab_output="0 6 * * * /bin/app-sync\n")
    assert out == "in crontab"


def test_loaded_state_cron_missing():
    out = loaded_state({"kind": "cron", "label": "app-sync"}, crontab_output="0 6 * * * /bin/other\n")
    assert out == "not in crontab"


def test_loaded_state_pg_cron_unknown():
    assert loaded_state({"kind": "pg_cron", "label": "morning-brief"}) == "unknown"


def test_routine_verdict_not_loaded():
    r = {"every": "1d"}
    assert routine_verdict(r, "not loaded", None) == "NOT LOADED"


def test_routine_verdict_stale():
    r = {"every": "1d"}
    now = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)
    run_at = now - dt.timedelta(days=5)
    assert routine_verdict(r, "loaded (pid 1)", run_at, now=now) == "STALE"


def test_routine_verdict_ok():
    r = {"every": "1d"}
    now = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)
    run_at = now - dt.timedelta(hours=6)
    assert routine_verdict(r, "loaded (pid 1)", run_at, now=now) == "ok"


def test_routine_verdict_unknown_no_log():
    r = {"every": "1d"}
    assert routine_verdict(r, "unknown", None) == "unknown"


def test_routine_verdict_ok_when_loaded_no_log_expected():
    r = {"every": "1d"}
    assert routine_verdict(r, "in crontab", None) == "ok"


# --- check verdicts ------------------------------------------------------------

def test_check_age_days():
    c = {"confirmed": dt.date(2026, 8, 1)}
    assert check_age_days(c, today=dt.date(2026, 9, 9)) == 39


def test_check_age_days_missing():
    assert check_age_days({}, today=dt.date(2026, 9, 9)) is None


def test_check_verdict_broken():
    assert check_verdict({"status": "broken"}, None) == "BROKEN"


def test_check_verdict_untested():
    assert check_verdict({"status": "untested"}, None) == "UNTESTED"


def test_check_verdict_ok_recent():
    assert check_verdict({"status": "ok"}, 5) == "ok"


def test_check_verdict_retest():
    assert check_verdict({"status": "ok"}, 31) == "RE-TEST"


def test_check_verdict_ok_no_confirmed_date():
    assert check_verdict({"status": "ok"}, None) == "ok"


# --- end-to-end evaluate + summarize --------------------------------------------

def test_evaluate_and_summarize(tmp_path):
    p = write(tmp_path, GOOD_TOML)
    manifest = parse_manifest(p)
    now = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)
    report = evaluate(manifest, now=now)
    assert report["product"] == "my-app"
    assert report["routines"][0]["name"] == "nightly-sync"
    assert report["checks"][0]["verdict"] == "BROKEN"
    n, m, k = summarize([report])
    assert m == 1  # the broken check
    assert n in (0, 1)  # depends on whether launchd/log happen to exist on this machine


# --- unknown counts as not-running (the "built, not used" case) ----------------

def _report(routine_verdicts=(), check_verdicts=()):
    return {
        "product": "p", "repo": "/x",
        "routines": [{"name": f"r{i}", "kind": "script", "loaded": "unknown",
                      "last_run": "?", "verdict": v} for i, v in enumerate(routine_verdicts)],
        "checks": [{"name": f"c{i}", "status": "ok", "confirmed": "-",
                    "age_days": "-", "verdict": v} for i, v in enumerate(check_verdicts)],
    }


def test_summarize_counts_unknown_routine_as_not_running():
    report = _report(routine_verdicts=["unknown"])
    n, m, k = summarize([report])
    assert n == 1


def test_summarize_counts_not_loaded_and_stale_too():
    report = _report(routine_verdicts=["NOT LOADED", "STALE", "ok"])
    n, m, k = summarize([report])
    assert n == 2


def test_a_script_routine_with_no_log_evidence_resolves_to_unknown_end_to_end(tmp_path):
    p = write(tmp_path, """
[product]
name = "x"
[[routine]]
name = "r"
kind = "script"
label = "x"
every = "1d"
""")
    manifest = parse_manifest(p)
    now = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)
    report = evaluate(manifest, now=now)
    assert report["routines"][0]["verdict"] == "unknown"
    n, m, k = summarize([report])
    assert n == 1  # not 0 — nothing on the machine schedules this, so it must not pass


# --- exit codes ------------------------------------------------------------------

def test_exit_code_clean():
    assert exit_code(0, 0, 0) == 0


def test_exit_code_not_running_or_broken_is_1():
    assert exit_code(1, 0, 0) == 1
    assert exit_code(0, 1, 0) == 1
    assert exit_code(1, 1, 3) == 1


def test_exit_code_only_untested_or_retest_is_2():
    assert exit_code(0, 0, 3) == 2


# --- column alignment on a long name ----------------------------------------------

def test_render_text_truncates_long_names_and_stays_aligned():
    report = {
        "product": "p", "repo": "/x",
        "routines": [
            {"name": "x" * 60, "kind": "script", "loaded": "unknown", "last_run": "?", "verdict": "unknown"},
            {"name": "short", "kind": "cron", "loaded": "in crontab", "last_run": "?", "verdict": "ok"},
        ],
        "checks": [],
    }
    out = render_text([report])
    lines = [l for l in out.splitlines() if l.strip()]
    # the long name is truncated with an ellipsis, well under the raw 60 chars
    assert any("…" in l for l in lines)
    assert not any(len(l) > 100 for l in lines)
    # every data row and the header line up: same column start for "kind"
    idx = next(i for i, l in enumerate(lines) if l.startswith("name"))
    header = lines[idx]
    kind_col = header.index("kind")
    for l in lines[idx + 1: idx + 3]:
        assert l[kind_col:kind_col + 6].strip() in ("script", "cron")


# --- the one-line summary the session-start hook shows ---------------------------------------

def test_summary_line_and_write_lines(tmp_path):
    from teyla import routines
    report = {"product": "frank", "repo": "/r/frank",
              "routines": [{"name": "daily", "verdict": "ok"}, {"name": "gate", "verdict": "NOT LOADED"}],
              "checks": [{"name": "gate shows drafts", "verdict": "UNTESTED"}, {"name": "send one", "verdict": "BROKEN"}]}
    line = routines.summary_line(report)
    assert line.startswith("frank: 1/2 routines running (not: gate) · 2 checks, broken: send one, 1 untested/re-test (as of ")
    assert line.endswith("`teyla routines .` for the table")
    err = routines.summary_line({"product": "loco", "repo": "/r/loco", "error": "bad status", "routines": [], "checks": []})
    assert "teyla.toml has an error" in err
    files = routines.write_lines([report, {"product": "a/b c", "repo": "", "routines": [], "checks": []}], tmp_path)
    assert [f.name for f in files] == ["frank.line", "a_b_c.line"]
    assert (tmp_path / "frank.line").read_text().rstrip() == line
    assert "no routines declared" in (tmp_path / "a_b_c.line").read_text()


# --- JSONL run outcomes: a routine that runs and fails is FAILING, not ok -------

NOW = dt.datetime(2026, 10, 2, 16, 0, tzinfo=dt.timezone.utc)


def _row(ok, finished, *, dry_run=False, error=None):
    r = {"dry_run": dry_run, "finished_at": finished, "items": 0, "ok": ok, "warnings": []}
    if error is not None:
        r["error"] = error
    return json.dumps(r)


def _jsonl_routine(tmp_path, lines, name="sync-runs.jsonl"):
    log = tmp_path / name
    log.write_text("\n".join(lines) + "\n")
    return {"name": "garmin-sync", "kind": "launchd", "every": "30m", "log": str(log)}


def _verdict(r):
    from teyla.routines import log_outcome
    o = log_outcome(r)
    run_at = (o or {}).get("finished_at")
    return routine_verdict(r, "loaded (pid 1)", run_at, now=NOW, outcome=o), o


def test_failing_streak_reports_since_count_and_error(tmp_path):
    err = "SyncError: Garmin refused all 19 reads (GarminAuthError): the session has expired. " + "x" * 200 + "\nsecond line"
    r = _jsonl_routine(tmp_path, [
        _row(True, "2026-10-02T09:25:00Z"),
        _row(False, "2026-10-02T09:55:00Z", error=err),
        _row(False, "2026-10-02T10:25:00Z", error=err),
        _row(False, "2026-10-02T15:25:37Z", error=err),
    ])
    v, o = _verdict(r)
    assert v == "FAILING"
    assert o["streak"] == 3 and o["since"] == dt.datetime(2026, 10, 2, 9, 55, tzinfo=dt.timezone.utc)
    assert o["finished_at"] == dt.datetime(2026, 10, 2, 15, 25, 37, tzinfo=dt.timezone.utc)
    assert o["error"].startswith("SyncError: Garmin refused all 19 reads") and len(o["error"]) <= 120
    assert "second line" not in o["error"]


def test_recovered_after_failures_is_ok(tmp_path):
    r = _jsonl_routine(tmp_path, [_row(False, "2026-10-02T14:00:00Z", error="boom"), _row(True, "2026-10-02T15:30:00Z")])
    assert _verdict(r)[0] == "ok"


def test_dry_run_rows_are_ignored(tmp_path):
    r = _jsonl_routine(tmp_path, [
        _row(True, "2026-10-02T15:00:00Z"),
        _row(False, "2026-10-02T15:10:00Z", dry_run=True, error="dry"),
    ])
    assert _verdict(r)[0] == "ok"
    r = _jsonl_routine(tmp_path, [
        _row(False, "2026-10-02T15:00:00Z", error="real"),
        _row(True, "2026-10-02T15:10:00Z", dry_run=True),
    ], name="b.jsonl")
    assert _verdict(r)[0] == "FAILING"


def test_malformed_lines_never_raise_and_fall_back_to_mtime(tmp_path):
    from teyla.routines import log_outcome
    r = _jsonl_routine(tmp_path, ["{not json", "[1, 2]", '{"ok": "yes"}'])
    assert log_outcome(r) is None
    assert routine_verdict(r, "loaded (pid 1)", NOW - dt.timedelta(minutes=10), now=NOW, outcome=None) == "ok"
    # a garbled tail after good rows is skipped, the last readable run still decides
    r = _jsonl_routine(tmp_path, [_row(False, "2026-10-02T15:00:00Z", error="e"), '{"ok": fal'], name="c.jsonl")
    assert _verdict(r)[0] == "FAILING"
    assert log_outcome({"log": str(tmp_path / "missing.jsonl")}) is None
    assert log_outcome({"log": str(tmp_path)}) is None


def test_plain_text_log_is_unchanged(tmp_path):
    from teyla.routines import log_outcome
    log = tmp_path / "sync.log"
    log.write_text("ERROR: everything failed\nok: false\n")
    assert log_outcome({"log": str(log)}) is None
    log.write_text('{"ok": false, "error": "x"}\n')  # a non-.jsonl log whose last line is a result row
    assert log_outcome({"log": str(log)})["ok"] is False


def test_large_log_reads_only_the_tail(tmp_path):
    from teyla.routines import LOG_TAIL_BYTES, log_outcome
    pad = [_row(True, "2026-10-01T00:00:00Z")] * (LOG_TAIL_BYTES // 100)
    r = _jsonl_routine(tmp_path, pad + [_row(False, "2026-10-02T15:25:37Z", error="late")])
    o = log_outcome(r)
    assert o["ok"] is False and o["streak"] == 1 and o["streak_open"] is False


def test_failing_counts_everywhere_not_running_does(tmp_path):
    from teyla.routines import problem_items
    report = _report(routine_verdicts=["FAILING", "NOT LOADED", "ok"])
    report["routines"][0]["detail"] = "3 consecutive failures since 2026-10-02 09:55Z: boom"
    assert summarize([report])[0] == 2
    assert exit_code(*summarize([report])) == 1
    assert counts_line([report]) == "1 routines not running, 1 routine failing, 0 checks broken, 0 untested/re-test"
    assert counts_line([_report(routine_verdicts=["ok"])]) == "0 routines not running, 0 checks broken, 0 untested/re-test"
    assert "3 consecutive failures" in render_text([report])
    assert "1 routine failing" in render_text([report])
    assert any("FAILING" in text and "boom" in text for _, text in problem_items(report))


def test_evaluate_marks_a_failing_jsonl_routine(tmp_path):
    log = tmp_path / "runs.jsonl"
    log.write_text(_row(False, "2026-10-02T15:25:37Z", error="SyncError: nope") + "\n")
    p = write(tmp_path, f"""
[product]
name = "iron"

[[routine]]
name = "garmin-sync"
kind = "script"
every = "30m"
log = "{log}"
""")
    rep = evaluate(parse_manifest(p), now=NOW)
    row = rep["routines"][0]
    assert row["verdict"] == "FAILING" and "SyncError: nope" in row["detail"]
    assert row["last_run"].startswith("2026-10-02T15:25:37")
    assert summarize([rep])[0] == 1
