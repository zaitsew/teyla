"""teyla.toml parser + routine/check verdict logic, built from tmp fixtures."""
from __future__ import annotations

import datetime as dt
import os
import pathlib

import pytest

from teyla.routines import (
    ManifestError,
    check_age_days,
    check_verdict,
    evaluate,
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
name = "garmin-sync"
kind = "launchd"
label = "com.ironu.sync"
every = "1d"
log = "~/Library/Logs/ironu-sync.log"

[[check]]
name = "meal logging from photo"
how = "app -> Log -> photo -> caption"
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


def test_parse_manifest_invalid_toml(tmp_path):
    p = write(tmp_path, "not toml [[[")
    with pytest.raises(ManifestError):
        parse_manifest(p)


# --- routine verdicts ---------------------------------------------------------

def test_loaded_state_launchd_running():
    out = loaded_state({"kind": "launchd", "label": "com.ironu.sync"},
                        launchctl_output="1234\t0\tcom.ironu.sync\n5678\t0\tother.label\n")
    assert "pid 1234" in out


def test_loaded_state_launchd_not_loaded():
    out = loaded_state({"kind": "launchd", "label": "com.ironu.sync"}, launchctl_output="")
    assert out == "not loaded"


def test_loaded_state_cron_found():
    out = loaded_state({"kind": "cron", "label": "ironu-sync"}, crontab_output="0 6 * * * /bin/ironu-sync\n")
    assert out == "in crontab"


def test_loaded_state_cron_missing():
    out = loaded_state({"kind": "cron", "label": "ironu-sync"}, crontab_output="0 6 * * * /bin/other\n")
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
    assert report["routines"][0]["name"] == "garmin-sync"
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
