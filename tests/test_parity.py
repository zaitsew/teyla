"""`teyla parity`, the gate in `teyla platform check`, the edit hook and the session line. Temp git repos, a
generic teyla.toml, fixed dates injected as `today`. Every name is invented."""
from __future__ import annotations

import datetime
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from teyla import cli, parity, platform_gate as pg, platform_hook as ph

AT = "@"
D = datetime.date
ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "platform-gate.sh"
START = ROOT / "plugin" / "hooks" / "session-start.sh"
TOML = """[product]
name = "widget"

[productize]
primary = "macos"
platforms = ["macos", "ios"]

[productize.triggers]
ios = "2026-10-26: the owner asked for an iOS version"

[productize.paths]
macos = ["apps/mac/**"]
ios = ["apps/ios/**", "!apps/ios/Shared.swift"]
"""
FAR, PAST = D(2999, 1, 1), D(2000, 1, 1)

pytestmark = pytest.mark.skipif(not os.path.exists("/usr/bin/git"), reason="needs /usr/bin/git")


class Repo:
    def __init__(self, tmp: Path, monkeypatch):
        self.dir = tmp / "repo"
        self.dir.mkdir()
        self.home = tmp / "teyla-home"
        env = {"TEYLA_HOME": str(self.home), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author" + AT + "example.com",
               "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author" + AT + "example.com"}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("TEYLA_PLATFORM_LABEL", raising=False)
        self.git("init", "-q", "-b", "main")
        self.commit("base", {"teyla.toml": TOML, "README.md": "x\n"})
        self.base = self.rev()

    def git(self, *a):
        p = subprocess.run(["git", "-C", str(self.dir), *a], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        return p.stdout.strip()

    def rev(self):
        return self.git("rev-parse", "HEAD")

    def commit(self, msg, files):
        for name, text in files.items():
            p = self.dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def ledger(self, **parts):
        data = {"train": {"ios": {"state": "closed", "base": self.base}}}
        data.update(parts)
        parity.save(self.dir, data)
        return data

    def run(self, capsys, *argv):
        code = cli.main(["parity", *argv, "--repo", str(self.dir)])
        out = capsys.readouterr()
        return code, out.out + out.err


@pytest.fixture
def repo(tmp_path, monkeypatch):
    return Repo(tmp_path, monkeypatch)


# --- the ledger file -------------------------------------------------------------------------

def test_the_ledger_round_trips_through_the_writer():
    data = {
        "candidate": {"build": "2.0.3 (197)", "commit": "abc", "delivered": D(2026, 11, 22), "to": "family"},
        "accepted": [{"build": "2.0.3 (197)", "commit": "abc", "date": D(2026, 11, 23), "source": "chat",
                      "ref": "intent:x@1", "summary": 'Owner: "ship it"', "features": ["a", "b"], "engine": True}],
        "train": {"android": {"state": "open", "base": "b", "tip": "abc", "opened": D(2026, 11, 26),
                              "expires": D(2026, 12, 3)}},
        "override": [{"platform": "web", "date": D(2026, 11, 23), "ref": "r", "summary": "s",
                      "expires": D(2026, 11, 24)}],
    }
    assert parity.parse(parity.dumps(data)) == data


def test_a_broken_ledger_reads_as_none(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "parity.toml").write_text("[train\n")
    assert parity.load(tmp_path) is None


# --- commands --------------------------------------------------------------------------------

def test_init_writes_a_closed_train_per_secondary(repo, capsys):
    code, out = repo.run(capsys, "init")
    assert code == 0 and "ios closed" in out
    data = parity.load(repo.dir)
    assert data["train"] == {"ios": {"state": "closed", "base": repo.base}}
    assert repo.run(capsys, "init")[0] == 1          # never overwrites


def test_init_refuses_without_a_primary(repo, capsys):
    (repo.dir / "teyla.toml").write_text('[productize]\nplatforms = ["a", "b"]\n')
    code, out = repo.run(capsys, "init")
    assert code == 1 and "primary" in out and not parity.ledger_path(repo.dir).exists()


def test_deliver_then_accept_then_open_waits_for_the_settle_time(repo, capsys):
    repo.ledger()
    assert repo.run(capsys, "deliver", "--build", "2.0.3 (197)", "--commit", "c1", "--to", "family",
                    "--date", "2026-11-22")[0] == 0
    data = parity.load(repo.dir)
    assert data["candidate"] == {"build": "2.0.3 (197)", "commit": "c1", "delivered": D(2026, 11, 22),
                                 "to": "family"}
    # no feedback yet: cannot open
    code, out = repo.run(capsys, "open", "ios", "--date", "2026-11-25")
    assert code == 1 and "waits for the owner's feedback on 2.0.3 (197), delivered 2026-11-22" in out
    assert repo.run(capsys, "accept", "--build", "2.0.3 (197)", "--commit", "c1", "--source", "chat",
                    "--ref", "intent:x@1", "--summary", "Owner: it works", "--date", "2026-11-23")[0] == 0
    code, out = repo.run(capsys, "open", "ios", "--date", "2026-11-25")      # 2 days: still settling
    assert code == 1 and "settle until 2026-11-26" in out
    code, out = repo.run(capsys, "open", "ios", "--date", "2026-11-26")      # 3 days
    assert code == 0, out
    t = parity.load(repo.dir)["train"]["ios"]
    assert (t["state"], t["tip"], t["opened"], t["expires"]) == ("open", "c1", D(2026, 11, 26), D(2026, 12, 3))


def test_an_engine_change_settles_seven_days(repo, capsys):
    repo.ledger()
    repo.run(capsys, "accept", "--build", "b", "--commit", "c1", "--source", "testflight", "--ref", "r",
             "--summary", "s", "--engine", "--date", "2026-11-23")
    assert repo.run(capsys, "open", "ios", "--date", "2026-11-29")[0] == 1
    assert repo.run(capsys, "open", "ios", "--date", "2026-11-30")[0] == 0


def test_open_uses_the_newest_eligible_accepted_commit(repo, capsys):
    repo.ledger()
    for commit, date in (("old", "2026-11-01"), ("new", "2026-11-10"), ("fresh", "2026-11-25")):
        repo.run(capsys, "accept", "--build", commit, "--commit", commit, "--source", "chat", "--ref", "r",
                 "--summary", "s", "--date", date)
    repo.run(capsys, "open", "ios", "--date", "2026-11-26")      # `fresh` is still settling
    assert parity.load(repo.dir)["train"]["ios"]["tip"] == "new"


def test_accept_needs_a_known_source_and_a_ledger(repo, capsys):
    assert repo.run(capsys, "accept", "--build", "b", "--commit", "c", "--source", "chat", "--ref", "r",
                    "--summary", "s")[0] == 1                    # no ledger yet
    repo.ledger()
    code, out = repo.run(capsys, "accept", "--build", "b", "--commit", "c", "--source", "email", "--ref", "r",
                         "--summary", "s")
    assert code == 1 and "source" in out


def test_queue_opens_nothing_and_sync_closes_the_train(repo, capsys):
    repo.ledger()
    assert repo.run(capsys, "queue", "ios", "--ref", "intent:x@2")[0] == 0
    t = parity.load(repo.dir)["train"]["ios"]
    assert t["state"] == "queued" and t["queued_ref"] == "intent:x@2"
    assert parity.gate(repo.dir, "ios", D(2026, 11, 25))[0] is False
    repo.ledger(train={"ios": {"state": "open", "base": "b", "tip": "c", "opened": PAST, "expires": FAR}})
    assert repo.run(capsys, "sync", "ios", "--to", "c9")[0] == 0
    assert parity.load(repo.dir)["train"]["ios"] == {"state": "closed", "base": "c9"}


def test_a_platform_that_is_not_secondary_is_refused(repo, capsys):
    repo.ledger()
    code, out = repo.run(capsys, "queue", "macos", "--ref", "r")
    assert code == 1 and "not a secondary" in out


# --- the gate --------------------------------------------------------------------------------

def test_gate_reasons_and_expiry(tmp_path):
    base = {"train": {"ios": {"state": "open", "base": "b", "tip": "c", "opened": D(2026, 11, 26),
                              "expires": D(2026, 12, 3)}}}
    assert parity.gate_from(base, "ios", D(2026, 12, 3)) == (True, "train open until 2026-12-03")
    ok, why = parity.gate_from(base, "ios", D(2026, 12, 4))
    assert ok is False and "expired on 2026-12-03" in why
    assert parity.gate_from(None, "ios", D(2026, 12, 4))[0] is True
    ok, why = parity.gate_from({"train": {}}, "ios", D(2026, 12, 4))
    assert ok is False and "no train entry" in why
    closed = {"train": {"ios": {"state": "closed"}}}
    assert "waits for a primary build" in parity.gate_from(closed, "ios", D(2026, 12, 4))[1]


def test_an_override_opens_one_platform_until_it_expires(repo, capsys):
    repo.ledger()
    code, out = repo.run(capsys, "override", "ios", "--ref", "intent:x@3", "--summary", "now, skip the gate",
                         "--days", "2", "--date", "2026-11-23")
    assert code == 0, out
    assert parity.gate(repo.dir, "ios", D(2026, 11, 25)) == (True, "owner override until 2026-11-25")
    assert parity.gate(repo.dir, "ios", D(2026, 11, 26))[0] is False
    assert parity.gate(repo.dir, "web", D(2026, 11, 24))[0] is False
    row = (repo.home / "platform-gate.tsv").read_text().splitlines()[-1].split("\t")
    assert row[1:4] == ["repo", "parity-override", "ios"]


def test_an_override_that_cannot_be_logged_is_refused(repo, capsys, monkeypatch):
    repo.ledger()
    blocker = repo.dir.parent / "file"
    blocker.write_text("x")
    monkeypatch.setenv("TEYLA_HOME", str(blocker / "sub"))
    code, out = repo.run(capsys, "override", "ios", "--ref", "r", "--summary", "s")
    assert code == 1 and "not on record" in out
    assert "override" not in parity.load(repo.dir)


def test_status_names_the_state_the_debt_and_the_next_step(repo, capsys):
    repo.ledger(candidate={"build": "2.0.3 (197)", "commit": "c1", "delivered": D(2026, 11, 22), "to": "family"})
    repo.commit("mac one", {"apps/mac/A.swift": "a\n"})
    repo.commit("mac two", {"apps/mac/B.swift": "b\n"})
    repo.commit("ios only", {"apps/ios/A.swift": "a\n"})
    st = parity.status(repo.dir, D.today())
    row = st["platforms"][0]
    assert (row["platform"], row["state"], row["debt_commits"]) == ("ios", "closed", 2)
    assert "waits for the owner's feedback on 2.0.3 (197), delivered 2026-11-22" in row["next"]
    code, out = repo.run(capsys, "status")
    assert code == 0 and "ios: closed  debt 2 commits" in out
    code, out = repo.run(capsys, "status", "--json")
    assert json.loads(out)["platforms"][0]["debt_commits"] == 2


def test_status_without_a_trigger_is_frozen(repo, capsys):
    repo.ledger()
    (repo.dir / "teyla.toml").write_text(TOML.replace("[productize.triggers]\nios =", "[productize.triggers]\nnone ="))
    row = parity.status(repo.dir, D.today())["platforms"][0]
    assert row["state"] == "frozen-by-trigger-missing" and row["open"] is False


def test_the_session_line_is_one_line(repo):
    repo.ledger(train={"ios": {"state": "open", "base": repo.base, "tip": "c", "opened": PAST, "expires": FAR}})
    line = parity.line(parity.status(repo.dir, D(2026, 11, 1)))
    assert line == "parity: ios open until 2999-01-01 — teyla parity status"
    repo.ledger()
    repo.commit("mac", {"apps/mac/A.swift": "a\n"})
    line = parity.line(parity.status(repo.dir, D.today()))
    assert line.startswith("parity: ios closed, 1 commits / ") and line.endswith("days behind — teyla parity status")
    assert "\n" not in line


# --- teyla platform check --------------------------------------------------------------------

def check(repo, capsys, *extra):
    code = cli.main(["platform", "check", "--repo", str(repo.dir), "--range", f"{repo.base}..{repo.rev()}", *extra])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_a_valid_trigger_with_a_closed_train_still_fails(repo, capsys):
    repo.ledger()
    repo.commit("ledger and port", {"apps/ios/A.swift": "a\n", "docs/parity.toml": (repo.dir / "docs/parity.toml").read_text()})
    code, out = check(repo, capsys)
    assert code == 1
    assert "ios:" in out and "gate closed: waits for a primary build" in out
    assert "apps/ios/A.swift" in out and "teyla parity status" in out
    assert "add to teyla.toml" not in out                    # the trigger is fine; the gate is the problem


def test_an_open_train_lets_the_port_through(repo, capsys):
    repo.ledger(train={"ios": {"state": "open", "base": repo.base, "tip": "c", "opened": PAST, "expires": FAR}})
    repo.commit("port", {"apps/ios/A.swift": "a\n"})
    code, out = check(repo, capsys)
    assert code == 0, out


def test_an_expired_train_fails(repo, capsys):
    repo.ledger(train={"ios": {"state": "open", "base": repo.base, "tip": "c", "opened": PAST, "expires": PAST}})
    repo.commit("port", {"apps/ios/A.swift": "a\n"})
    code, out = check(repo, capsys)
    assert code == 1 and "expired on 2000-01-01" in out


def test_the_ledger_counts_as_committed_not_as_edited(repo, capsys):
    repo.ledger()
    repo.commit("closed ledger", {"apps/ios/A.swift": "a\n"})
    parity.save(repo.dir, {"train": {"ios": {"state": "open", "base": "b", "tip": "c", "opened": PAST, "expires": FAR}}})
    code, _ = check(repo, capsys)                       # the open train was never committed
    assert code == 1


def test_a_label_exception_still_passes_and_is_logged(repo, capsys):
    repo.ledger()
    repo.commit("fix", {"apps/ios/A.swift": "a\n", "docs/parity.toml": (repo.dir / "docs/parity.toml").read_text()})
    code, out = check(repo, capsys, "--label", "security")
    assert code == 0 and "passed on label 'security'" in out
    assert "security" in (repo.home / "platform-gate.tsv").read_text()


def test_no_ledger_keeps_the_trigger_only_check_with_one_warning(repo, capsys):
    repo.commit("port", {"apps/ios/A.swift": "a\n"})
    code, out = check(repo, capsys)
    assert code == 0
    assert out.count("WARN") == 1 and "run `teyla parity init`" in out


def test_a_shared_file_excluded_by_a_bang_pattern_is_never_ios():
    paths = {"macos": ["apps/mac/**"], "ios": ["apps/ios/**", "!apps/ios/Shared.swift"]}
    assert pg.platforms_of("apps/ios/A.swift", paths) == ["ios"]
    assert pg.platforms_of("apps/ios/Shared.swift", paths) == []
    assert pg.platforms_of("apps/mac/A.swift", paths) == ["macos"]


# --- the edit hook ---------------------------------------------------------------------------

def payload(repo, rel, tool="Edit"):
    return {"tool_name": tool, "cwd": str(repo.dir), "tool_input": {"file_path": str(repo.dir / rel)}}


def decide(repo, rel, today=D(2026, 11, 25), **kw):
    return ph.decide(payload(repo, rel, **kw), today)


def test_the_hook_refuses_a_closed_secondary(repo):
    repo.ledger()
    code, text = decide(repo, "apps/ios/App.swift")
    assert code == 2
    assert text.startswith("platform gate: ios is closed in widget: ")
    assert "Primary first (POLICY §14). Build it on macos" in text and "`teyla parity status`" in text


@pytest.mark.parametrize("rel", ["apps/mac/A.swift", "docs/x.md", "apps/ios/Shared.swift"])
def test_the_hook_passes_primary_unmapped_and_shared_files(repo, rel):
    repo.ledger()
    assert decide(repo, rel) == (0, "")


def test_an_overlapping_primary_pattern_does_not_hide_a_closed_secondary(repo):
    repo.ledger()
    (repo.dir / "teyla.toml").write_text(TOML.replace('macos = ["apps/mac/**"]', 'macos = ["apps/**"]'))
    assert decide(repo, "apps/ios/App.swift")[0] == 2
    assert decide(repo, "apps/mac/A.swift") == (0, "")


def test_the_hook_passes_an_open_train_and_an_override(repo):
    repo.ledger(train={"ios": {"state": "open", "base": "b", "tip": "c", "opened": PAST, "expires": D(2026, 11, 30)}})
    assert decide(repo, "apps/ios/App.swift")[0] == 0
    assert decide(repo, "apps/ios/App.swift", today=D(2026, 12, 1))[0] == 2
    repo.ledger(override=[{"platform": "ios", "date": PAST, "ref": "r", "summary": "s", "expires": D(2026, 12, 2)}])
    assert decide(repo, "apps/ios/App.swift", today=D(2026, 12, 1))[0] == 0


def test_the_hook_passes_without_a_ledger_or_a_manifest(repo):
    assert decide(repo, "apps/ios/App.swift")[0] == 0
    repo.ledger()
    (repo.dir / "teyla.toml").unlink()
    assert decide(repo, "apps/ios/App.swift")[0] == 0


def test_the_hook_takes_a_notebook_path_and_a_relative_path(repo):
    repo.ledger()
    p = {"cwd": str(repo.dir), "tool_input": {"notebook_path": "apps/ios/n.ipynb"}}
    assert ph.decide(p, D(2026, 11, 25))[0] == 2


def test_a_valid_label_passes_the_hook_and_is_logged(repo, monkeypatch):
    repo.ledger()
    monkeypatch.setenv("TEYLA_PLATFORM_LABEL", "data-loss")
    assert decide(repo, "apps/ios/App.swift") == (0, "")
    row = (repo.home / "platform-gate.tsv").read_text().splitlines()[-1].split("\t")
    assert row[2:5] == ["data-loss", "ios", "edit:apps/ios/App.swift"]


def test_an_unknown_label_does_not_open_the_hook(repo, monkeypatch):
    repo.ledger()
    monkeypatch.setenv("TEYLA_PLATFORM_LABEL", "whatever")
    assert decide(repo, "apps/ios/App.swift")[0] == 2


def test_bad_json_and_odd_payloads_fail_open():
    assert ph.main(io.StringIO("{not json")) == 0
    assert ph.main(io.StringIO("")) == 0
    assert ph.main(io.StringIO("[1, 2]")) == 0
    assert ph.main(io.StringIO('{"tool_input": {"file_path": 7}}')) == 0


def run_hook(repo, rel, extra_env=None, raw=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo.dir.parent), "TEYLA_HOME": str(repo.home),
           "TEYLA_PYTHON": sys.executable, **(extra_env or {})}
    data = raw if raw is not None else json.dumps(payload(repo, rel))
    t0 = time.perf_counter()
    proc = subprocess.run(["sh", str(HOOK)], input=data, capture_output=True, text=True, env=env, timeout=20)
    return proc, (time.perf_counter() - t0) * 1000


def test_the_hook_script_refuses_a_closed_secondary_and_costs_nothing_elsewhere(repo):
    repo.ledger()
    proc, _ = run_hook(repo, "apps/ios/App.swift")
    assert proc.returncode == 2 and "ios is closed in widget" in proc.stderr
    assert run_hook(repo, "apps/mac/A.swift")[0].returncode == 0
    assert run_hook(repo, "docs/x.md")[0].returncode == 0
    assert run_hook(repo, "apps/ios/App.swift", raw="not json")[0].returncode == 0
    assert run_hook(repo, "apps/ios/App.swift", raw="")[0].returncode == 0


def test_the_hook_script_starts_no_python_without_a_ledger(repo):
    # TEYLA_PYTHON names a file that would fail loudly if it ran
    proc, ms = run_hook(repo, "apps/ios/App.swift", extra_env={"TEYLA_PYTHON": "/nonexistent"})
    assert proc.returncode == 0 and proc.stderr == ""
    assert ms < 400, ms


def test_the_hook_script_is_fast_when_it_decides(repo):
    repo.ledger()
    run_hook(repo, "apps/ios/App.swift")                            # warm the file cache
    times = [run_hook(repo, "apps/ios/App.swift")[1] for _ in range(3)]
    assert min(times) < 500, times                                  # the budget is ~200 ms on a warm machine


def test_the_hook_is_registered_for_the_four_edit_tools():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    mine = [g for g in hooks if any("platform-gate.sh" in h["command"] for h in g["hooks"])]
    assert len(mine) == 1 and mine[0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"


# --- the session line ------------------------------------------------------------------------

def test_session_start_prints_the_parity_line(repo, tmp_path):
    repo.ledger()
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "teyla"
    fake.write_text('#!/bin/sh\n[ "$1 $2 $3" = "parity status --line" ] && echo "parity: ios closed — teyla parity status"\n')
    fake.chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    proc = subprocess.run(["sh", str(START)], capture_output=True, text=True, cwd=repo.dir, env=env, timeout=10)
    assert "parity: ios closed — teyla parity status\n" in proc.stdout
    (repo.dir / "docs" / "parity.toml").unlink()
    proc = subprocess.run(["sh", str(START)], capture_output=True, text=True, cwd=repo.dir, env=env, timeout=10)
    assert "parity:" not in proc.stdout


def test_status_line_is_silent_without_a_ledger(repo, capsys):
    code, out = repo.run(capsys, "status", "--line")
    assert code == 0 and out == ""
