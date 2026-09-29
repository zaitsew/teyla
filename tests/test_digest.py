"""The banner that shows only what is new, the weekly digest, and `teyla check`. The hook is run
for real through `sh` with HOME pointed at tmp_path; nothing here touches the real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import time

import pytest

from teyla import cli, config, digest, doctor, remind, routine_install, routines

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "session-start.sh"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.setattr(routines, "LINES_DIR", home / ".teyla" / "routines")
    monkeypatch.setattr(remind, "REMINDERS_PATH", home / ".teyla" / "reminders.toml")
    monkeypatch.setattr(doctor, "DOCTOR_JSON", home / ".teyla" / "doctor.json")
    monkeypatch.setattr(doctor, "DOCTOR_SUMMARY", home / ".teyla" / "doctor.summary")
    monkeypatch.setattr(routines, "_launchctl_list", lambda: "")
    monkeypatch.setattr(routines, "_crontab_l", lambda: "")
    return home


def run_hook(home: pathlib.Path, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}  # no `teyla` on PATH: nothing is backgrounded
    return subprocess.run(["sh", str(HOOK)], cwd=cwd, env=env, capture_output=True, text=True, timeout=5)


# --- banner -----------------------------------------------------------------------------------

def test_banner_shows_only_new_items_and_counts_known():
    items = "FIX|version\tversion FIX: 0.13 available\nWARN|repos:agents-md\trepos:agents-md WARN: 1 differ\n"
    assert digest.banner(items, None) == ("teyla: new — version FIX: 0.13 available; repos:agents-md WARN: 1 differ (teyla doctor)")
    assert digest.banner(items, "FIX|version\nWARN|repos:agents-md\n") == ""
    more = items + "routine|frank|gate|NOT LOADED\tfrank routine gate NOT LOADED\n"
    assert digest.banner(more, "FIX|version\nWARN|repos:agents-md\n") == \
        "teyla: new — frank routine gate NOT LOADED; 2 known (teyla doctor)"
    five = "".join(f"W|{i}\titem {i}\n" for i in range(5))
    assert digest.banner(five, "") == "teyla: new — item 0; item 1; item 2 (+2 more) (teyla doctor)"


def test_hook_prints_new_then_nothing_then_only_the_change(_home, tmp_path):
    t = _home / ".teyla"
    (t / "doctor.summary").write_text("teyla: 1 fix(es), 2 warning(s) — run `teyla doctor`\n")
    items = "FIX|remind:x\treminder\nWARN|repos:agents-md\trepos:agents-md WARN: teyla-ai differs\n"
    (t / "banner.items").write_text(items)
    start = time.monotonic()
    first = run_hook(_home, tmp_path)
    assert time.monotonic() - start < 2 and first.returncode == 0
    assert first.stdout.strip() == digest.banner(items, None)
    assert "fix(es)" not in first.stdout  # the old line is not repeated next to the banner
    assert run_hook(_home, tmp_path).stdout == ""  # nothing new: nothing said
    # a WARN that becomes a FIX is news; the unchanged item collapses to a count
    items2 = "FIX|remind:x\treminder\nFIX|repos:agents-md\trepos:agents-md FIX: now broken\n"
    (t / "banner.items").write_text(items2)
    out = run_hook(_home, tmp_path).stdout.strip()
    assert out == "teyla: new — repos:agents-md FIX: now broken; 1 known (teyla doctor)"
    assert out == digest.banner(items2, "FIX|remind:x\nWARN|repos:agents-md\n")


def test_hook_falls_back_to_doctor_summary_without_banner_items(_home, tmp_path):
    (_home / ".teyla" / "doctor.summary").write_text("teyla: 1 fix(es) — run `teyla doctor`\n")
    assert run_hook(_home, tmp_path).stdout.strip() == "teyla: 1 fix(es) — run `teyla doctor`"


def test_hook_shows_the_digest_headline_once_per_digest(_home, tmp_path):
    d = _home / ".teyla" / "digest.md"
    d.write_text("teyla weekly 2026-09-28: A1 Subagents inherit → pass model:\n1. …\n")
    assert run_hook(_home, tmp_path).stdout.strip() == "teyla weekly 2026-09-28: A1 Subagents inherit → pass model:"
    assert run_hook(_home, tmp_path).stdout == ""
    later = time.time() + 60
    d.write_text("teyla weekly 2026-10-05: nothing needs you this week.\n")
    os.utime(d, (later, later))
    assert "2026-10-05" in run_hook(_home, tmp_path).stdout


def test_reminders_reach_the_banner_on_the_due_day_then_weekly():
    today = dt.date(2026, 9, 29)

    def keys(due):
        return [k for k, _ in digest.reminder_items([{"what": "Apple secret", "due": due, "how": ""}], today)]
    assert keys("2026-10-02") == []                      # not due yet: doctor's WARN, not the banner
    assert keys("2026-09-29") == ["remind|Apple secret|due"]
    assert keys("2026-09-28") == keys("2026-09-22") == ["remind|Apple secret|w0"]   # 1 and 7 days overdue
    assert keys("2026-09-21") == ["remind|Apple secret|w1"]                         # 8 days: shown again


def test_write_banner_items_merges_doctor_routines_and_reminders(_home):
    checks = [doctor._check("OK", "version", "fine"), doctor._check("WARN", "repos:agents-md", "1 differ"),
              doctor._check("FIX", "remind:Apple secret", "overdue", "x"), doctor._check("FIX", "plugin", "not installed", "y")]
    routines.write_lines([{"product": "frank", "repo": "/r/frank",
                           "routines": [{"name": "gate", "verdict": "NOT LOADED"}, {"name": "daily", "verdict": "ok"}],
                           "checks": [{"name": "send one", "verdict": "BROKEN", "age_days": 3}]}])
    remind.save([{"what": "Apple secret", "due": dt.date.today().isoformat(), "how": ""}])
    p = digest.write_banner_items(checks)
    keys = [l.split("\t")[0] for l in p.read_text().splitlines()]
    assert keys == ["WARN|repos:agents-md", "FIX|plugin", "routine|frank|gate|NOT LOADED", "check|frank|send one|BROKEN",
                    "remind|Apple secret|due"]
    # a product whose problems are gone loses its file, and with it its banner items
    routines.write_lines([{"product": "frank", "repo": "/r/frank", "routines": [], "checks": []}])
    assert not (routines.LINES_DIR / "frank.problems").exists()


def test_doctor_write_state_writes_banner_items(_home):
    doctor.write_state([doctor._check("FIX", "plugin", "not installed", "teyla plugin install zaitsew/teyla")])
    assert (_home / ".teyla" / "banner.items").read_text().startswith("FIX|plugin\tplugin FIX: not installed")


# --- the product line names the one command -----------------------------------------------------

def test_product_line_names_the_confirm_command_for_stale_checks():
    rep = {"product": "frank", "repo": "/r/frank", "routines": [],
           "checks": [{"name": "fresh", "verdict": "UNTESTED", "age_days": 3},
                      {"name": "log a photo", "verdict": "UNTESTED", "age_days": "-"},
                      {"name": "send one", "verdict": "BROKEN", "age_days": 19}]}
    line = routines.summary_line(rep)
    assert 'broken >14d: send one (+1 more); after trying it: `teyla check frank "send one" ok|broken`' in line
    assert line.endswith("`teyla routines .` for the table")
    rep["checks"] = [{"name": "fresh", "verdict": "UNTESTED", "age_days": 3}, {"name": "ok one", "verdict": "ok", "age_days": 90}]
    assert "teyla check" not in routines.summary_line(rep)
    assert routines.confirm_command("frank", "gate shows today's drafts") == 'teyla check frank "gate shows today\'s drafts" ok|broken'
    assert routines.confirm_command("frank", 'say "hi" $HOME') == "teyla check frank 'say \"hi\" $HOME' ok|broken"


# --- teyla check ---------------------------------------------------------------------------------

TOML = """# frank — the X drafting bot
[product]
name = "frank"   # shown in every report

[[routine]]
name = "daily"
kind = "launchd"
label = "com.x.frank"
every = "1d"

[[check]]
name = "gate shows drafts"
how = "open the gate page"
status = "untested"                 # ok | broken | untested

[[check]]
name = 'send "one"'
how = "approve one draft"
status = "broken"
confirmed = 2026-09-10
note = "times out"

# trailing comment kept
"""


def test_set_check_edits_only_that_block(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text(TOML)
    msg = routines.set_check(p, "gate shows drafts", "ok", today=dt.date(2026, 9, 29))
    assert msg.startswith("gate shows drafts: untested -> ok, confirmed 2026-09-29")
    new = p.read_text()
    assert 'status = "ok"                 # ok | broken | untested\nconfirmed = 2026-09-29\n' in new
    assert new.replace('status = "ok"                 # ok | broken | untested\nconfirmed = 2026-09-29\n',
                       'status = "untested"                 # ok | broken | untested\n') == TOML
    routines.set_check(p, 'send "one"', "ok", note="works on 5G", today=dt.date(2026, 9, 29))
    new2 = p.read_text()
    assert 'status = "ok"\nconfirmed = 2026-09-29\nnote = "works on 5G"\n\n# trailing comment kept\n' in new2
    parsed = routines.parse_manifest(p)
    assert [c["status"] for c in parsed["checks"]] == ["ok", "ok"]
    assert new2.startswith("# frank — the X drafting bot\n[product]\nname = \"frank\"   # shown in every report\n")


def test_set_check_unknown_name_and_file_without_newline(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname = "a"\n\n[[check]]\nname = "x"\nhow = "y"\nstatus = "ok"')
    with pytest.raises(routines.ManifestError, match="no \\[\\[check\\]\\] named 'nope'; there are: 'x'"):
        routines.set_check(p, "nope", "ok")
    routines.set_check(p, "x", "broken", today=dt.date(2026, 9, 1))
    assert p.read_text().endswith('status = "broken"\nconfirmed = 2026-09-01\n')


def test_find_product_by_name_dir_path_and_cwd(tmp_path, monkeypatch):
    code = tmp_path / "repos"
    (code / "frank-repo").mkdir(parents=True)
    (code / "frank-repo" / "teyla.toml").write_text('[product]\nname = "frank"\n')
    monkeypatch.setattr(config, "load", lambda path=None: {**config.DEFAULTS, "code_root": str(code)})
    m = code / "frank-repo" / "teyla.toml"
    assert routines.find_product("frank", cwd=tmp_path) == m
    assert routines.find_product("frank-repo", cwd=tmp_path) == m
    assert routines.find_product(str(code / "frank-repo")) == m
    assert routines.find_product("nothing", cwd=tmp_path) is None
    (tmp_path / "here").mkdir()
    (tmp_path / "here" / "teyla.toml").write_text('[product]\nname = "frank"\n')
    assert routines.find_product("frank", cwd=tmp_path / "here") == tmp_path / "here" / "teyla.toml"


def test_teyla_check_cli_updates_file_line_and_banner(_home, tmp_path, capsys):
    repo = tmp_path / "frank"
    repo.mkdir()
    (repo / "teyla.toml").write_text(TOML)
    assert cli.main(["check", str(repo), 'send "one"', "ok"]) == 0
    assert "broken -> ok" in capsys.readouterr().out
    assert "BROKEN" not in (routines.LINES_DIR / "frank.line").read_text()
    assert "send" not in (_home / ".teyla" / "banner.items").read_text()
    assert cli.main(["check", str(repo), "missing", "ok"]) == 1


# --- the weekly digest ------------------------------------------------------------------------------

FINDINGS = [dict(id="A1", severity="high", title="Subagents inherit the parent model", evidence="x",
                 action="Pass model: sonnet (or haiku) on every Agent call that reads."),
            dict(id="A3", severity="medium", title="3 giant sessions", evidence="x", action="Split work; run `teyla sessions`.")]
DOCTOR = [doctor._check("FIX", "plugin", "not installed", "teyla plugin install zaitsew/teyla   (or: claude plugin …)"),
          doctor._check("WARN", "repos:agents-md", "1 differ", "x")]
REPORTS = [{"product": "frank", "repo": "/r/frank",
            "routines": [{"name": "gate", "verdict": "NOT LOADED"}],
            "checks": [{"name": "send one", "verdict": "BROKEN", "age_days": 19},
                       {"name": "new one", "verdict": "UNTESTED", "age_days": 2}]}]


def test_digest_top_three_across_sources_with_commands():
    lines, _ = digest.build(FINDINGS, DOCTOR, REPORTS, {}, today=dt.date(2026, 9, 28))
    assert lines[0] == "teyla weekly 2026-09-28: plugin: not installed → teyla plugin install zaitsew/teyla (+2 more: teyla digest)"
    assert lines[1:] == ["1. plugin: not installed → `teyla plugin install zaitsew/teyla`",
                         "2. A1 Subagents inherit the parent model → Pass model: sonnet (or haiku) on every Agent call that reads",
                         "3. frank routine gate NOT LOADED → `teyla routines /r/frank`"]
    cands = digest.candidates(FINDINGS, DOCTOR, REPORTS)
    assert [c["id"] for c in cands] == ["doctor:plugin", "A1", "routine:frank:gate", "check:frank:send one", "A3"]
    assert cands[3]["step"] == 'teyla check frank "send one" ok|broken' and cands[4]["step"] == "teyla sessions"


def test_digest_nothing_to_do_is_one_line():
    lines, hist = digest.build([], [], [], {}, today=dt.date(2026, 9, 28))
    assert lines == ["teyla weekly 2026-09-28: nothing needs you this week."]
    assert hist == {"weeks": {"2026-W40": []}}


def test_digest_streak_after_three_weeks_running():
    hist = {}
    for d in (dt.date(2026, 9, 14), dt.date(2026, 9, 21)):
        _, hist = digest.build(FINDINGS[:1], [], [], hist, today=d)
    lines, hist = digest.build(FINDINGS[:1], [], [], hist, today=dt.date(2026, 9, 21))  # rerun, same week
    assert not any(l.startswith("streak") for l in lines)
    lines, hist = digest.build(FINDINGS, [], [], hist, today=dt.date(2026, 9, 28))
    assert lines[-1].startswith("streak: A1 (3 weeks) running") and len(lines) <= 5
    # a gap breaks the streak
    assert digest.streaks({"weeks": {"2026-W38": ["A1"], "2026-W40": ["A1"]}}, dt.date(2026, 9, 28)) == {"A1": 1}
    many = {"weeks": {f"2026-W{w:02d}": ["A1"] for w in range(20, 40)}}
    assert len(digest.update_history(many, ["A1"], dt.date(2026, 9, 28))["weeks"]) == 12


def test_digest_write_notifies_unless_configured_off(_home, monkeypatch):
    calls = []
    monkeypatch.setattr(digest.sys, "platform", "darwin")
    monkeypatch.setattr(digest.shutil, "which", lambda n: "/usr/bin/osascript")
    monkeypatch.setattr(digest.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0))[1])
    lines = digest.write(FINDINGS, DOCTOR, REPORTS, today=dt.date(2026, 9, 28))
    assert (_home / ".teyla" / "digest.md").read_text().splitlines() == lines
    assert json.loads((_home / ".teyla" / "digest-history.json").read_text())["weeks"]["2026-W40"] == ["A1", "A3"]
    assert calls and calls[0][0] == "osascript" and calls[0][2].startswith('display notification "teyla weekly 2026-09-28')
    print(config.set_value("digest.notify", "false"))
    calls.clear()
    digest.write(FINDINGS, DOCTOR, REPORTS, today=dt.date(2026, 9, 28))
    assert calls == []


def test_teyla_digest_prints_the_file(_home, capsys):
    assert cli.main(["digest"]) == 1
    assert "no digest yet" in capsys.readouterr().out
    (_home / ".teyla" / "digest.md").write_text("teyla weekly 2026-09-28: nothing needs you this week.\n")
    assert cli.main(["digest"]) == 0
    assert capsys.readouterr().out == "teyla weekly 2026-09-28: nothing needs you this week.\n"


def test_weekly_wrapper_writes_the_digest_and_an_old_one_is_stale(_home, monkeypatch):
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", _home / ".teyla" / "weekly.sh")
    assert '"$TEYLA" digest --write' in routine_install.WRAPPER_TEMPLATE
    w = routine_install.WRAPPER_PATH
    w.write_text(routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l")
                 .replace('"$TEYLA" digest --write\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l"))
    assert not routine_install._wrapper_stale(w, "/x/teyla")


def test_unknown_routines_count_as_not_running_in_banner_and_digest():
    rep = {"product": "loco", "repo": "/r/loco", "checks": [],
           "routines": [{"name": "health", "verdict": "unknown"}, {"name": "sync", "verdict": "ok"}]}
    assert routines.problem_items(rep) == [("routine|loco|health|unknown", "loco routine health unknown")]
    assert [c["id"] for c in digest.candidates([], [], [rep])] == ["routine:loco:health"]


def test_prose_stays_prose_and_commands_get_backticks():
    fs = [dict(id="A1", severity="high", title="t1", action="Pass model: sonnet on every Agent call."),
          dict(id="A9", severity="high", title="t9", action="Add it with `teyla rule` and it stops.")]
    checks = [doctor._check("FIX", "repos:x", "differ", "merge by hand, or teyla policy sync-repo <path>"),
              doctor._check("FIX", "plugin", "missing", "teyla plugin install zaitsew/teyla   (or: …)")]
    lines, _ = digest.build(fs, checks, [], {}, today=dt.date(2026, 9, 28))
    assert lines[1] == "1. repos:x: differ → merge by hand, or teyla policy sync-repo <path>"
    assert lines[2] == "2. plugin: missing → `teyla plugin install zaitsew/teyla`"
    assert lines[3] == "3. A1 t1 → Pass model: sonnet on every Agent call"
    assert [c["cmd"] for c in digest.candidates(fs, [], [])] == [False, True]
    yaml_key = dict(id="A16", severity="high", title="t", action="Set `on:` to `workflow_dispatch:` only, commit and push.")
    assert digest._step_of_advice(yaml_key["action"]) == ("Set on: to workflow_dispatch: only, commit and push", False)


def test_manifests_are_discovered_under_config_code_root(tmp_path, monkeypatch):
    code = tmp_path / "work" / "code"
    for name in ("a", "b"):
        (code / name / ".git").mkdir(parents=True)
    (code / "a" / "teyla.toml").write_text('[product]\nname = "a"\n')
    monkeypatch.setattr(config, "load", lambda path=None: {**config.DEFAULTS, "code_root": str(code)})
    assert routines.find_manifests() == [code / "a" / "teyla.toml"]
