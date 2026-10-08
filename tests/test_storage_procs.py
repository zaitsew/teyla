"""`teyla storage procs` — dev processes whose worktree or temp folder is gone.

`ps`, `lsof`, `kill` and `sleep` are faked (`Machine`); nothing here signals a real process, reads
the real process table or touches the real HOME: worktrees are built under a tmp HOME.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import plistlib

import pytest

from teyla import config, routine_install as ri, storage, storage_procs

REAL_CTX = storage_procs.Ctx

UID = 501
OLD = "02:00:00"
LSTART = "Thu Oct  8 10:00:00 2026"
MB = 1024


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmpdir") + "/")
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")
    monkeypatch.setattr(config, "HOME", tmp_path / "home")


def gone_wt(tmp_path, name="a/b") -> str:
    """A path inside ~/.worktrees whose folder does not exist."""
    return str(tmp_path / "home" / ".worktrees" / name)


def live_wt(tmp_path, name="a/b") -> str:
    p = tmp_path / "home" / ".worktrees" / name
    p.mkdir(parents=True)
    return str(p)


class Machine:
    """A fake process table: ps, lsof and kill over a dict of rows."""

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.cwds: dict[int, str] = {}
        self.lsof_fails = False
        self.ps_fails = False
        self.signals: list[tuple[int, int]] = []
        self.sleeps = 0
        self.survives_term: set[int] = set()
        self.reused_after_term: set[int] = set()
        self.lsof_calls = 0

    def add(self, pid, command, cwd=None, ppid=1, uid=UID, tty="??", rss_mb=200, etime=OLD, lstart=LSTART):
        self.rows[pid] = dict(pid=pid, ppid=ppid, uid=uid, tty=tty, rss=rss_mb * MB, etime=etime, lstart=lstart, command=command)
        if cwd is not None:
            self.cwds[pid] = cwd
        return pid

    @staticmethod
    def line(r):
        return f"{r['pid']:>5} {r['ppid']:>5} {r['uid']:>5} {r['tty']:<8} {r['rss']:>8} {r['etime']:>11} {r['lstart']} {r['command']}"

    def run(self, cmd, timeout=60):
        if cmd[0] == "ps":
            if self.ps_fails:
                return 1, ""
            if "-p" in cmd:
                r = self.rows.get(int(cmd[cmd.index("-p") + 1]))
                return (0, self.line(r)) if r else (1, "")
            return 0, "\n".join(self.line(r) for r in self.rows.values())
        if cmd[0] == "lsof":
            self.lsof_calls += 1
            if self.lsof_fails:
                return 127, ""
            pids = [int(p) for p in cmd[cmd.index("-p") + 1].split(",")]
            out = []
            for p in pids:
                if p in self.cwds:
                    out += [f"p{p}", "fcwd", f"n{self.cwds[p]}"]
            return (0, "\n".join(out)) if out else (1, "")
        raise AssertionError(cmd)

    def kill(self, pid, sig):
        self.signals.append((pid, sig))
        if pid not in self.rows:
            raise ProcessLookupError
        if sig == 15 and pid in self.reused_after_term:
            self.rows[pid]["lstart"] = "Thu Oct  8 11:59:59 2026"        # the pid now belongs to someone else
            self.rows[pid]["command"] = "/usr/bin/python3 other.py"
        elif sig == 9 or (sig == 15 and pid not in self.survives_term):
            del self.rows[pid]

    def sleep(self, _):
        self.sleeps += 1

    def ctx(self, **kw):
        kw.setdefault("watch", lambda pid: None)          # no kqueue on fake pids
        return REAL_CTX(run=self.run, kill=self.kill, sleep=self.sleep, uid=UID, self_pid=kw.pop("self_pid", 99999),
                                 home=pathlib.Path.home(), tmpdir=kw.pop("tmpdir", ""), **kw)


def pids(found):
    return [r["pid"] for r in found["orphans"]]


# --- what is an orphan -------------------------------------------------------------------------

def test_a_dev_server_whose_worktree_is_gone_is_an_orphan(tmp_path):
    m = Machine()
    cwd = gone_wt(tmp_path)
    m.add(10, "node /x/node_modules/.bin/next dev", cwd=cwd, rss_mb=300)
    found = storage_procs.find({}, m.ctx())
    assert pids(found) == [10] and found["error"] is None
    row = found["orphans"][0]
    assert row["cwd"] == cwd and row["reason"] == f"cwd {cwd} is gone" and row["rss_kb"] == 300 * MB
    assert row["age_s"] == 7200 and storage_procs.total_rss(found["orphans"]) == 300 * MB * 1024


def test_the_builtin_tools_are_all_recognised(tmp_path):
    m = Machine()
    cwd = gone_wt(tmp_path)
    cmds = ["/usr/bin/xcodebuild -scheme X build", "/Applications/Xcode.app/x/XCBBuildService", "swift-build --package-path .",
            "swift-frontend -frontend -c", "/opt/bin/node server.js", "npm run dev", "pnpm dev", "bun run dev", "deno task dev",
            "/usr/bin/python3 -m http.server 8000", "supabase start", "next-server (v14.2.0)", "vite --port 5173"]
    for i, c in enumerate(cmds):
        m.add(100 + i, c, cwd=cwd)
    assert sorted(pids(storage_procs.find({}, m.ctx()))) == [100 + i for i in range(len(cmds))]


def test_a_path_argument_in_a_deleted_folder_does_not_count_when_the_cwd_exists(tmp_path):
    m = Machine()
    live = live_wt(tmp_path, "repo/main")
    root = tmp_path / "scratch"
    root.mkdir()
    m.add(11, f"/usr/bin/xcodebuild -derivedDataPath {root}/build-1/dd test", cwd=live)
    cfg = {"storage": {"orphan_roots": [str(root)]}}
    assert pids(storage_procs.find(cfg, m.ctx())) == []


def test_a_path_with_a_space_is_not_taken_for_a_deleted_folder(tmp_path):
    # ps prints `node "/x/My Project/server.js"` unquoted; `/x/My` does not exist, the project does.
    m = Machine()
    root = tmp_path / "scratch"
    (root / "My Project").mkdir(parents=True)
    m.add(12, f"node {root}/My Project/server.js", cwd=str(root / "My Project"))
    assert pids(storage_procs.find({"storage": {"orphan_roots": [str(root)]}}, m.ctx())) == []


def test_an_argument_that_names_a_tool_does_not_make_the_process_that_tool(tmp_path):
    m = Machine()
    cwd = gone_wt(tmp_path)
    m.add(13, "/bin/bash /x/backup.sh --exclude /tmp/node", cwd=cwd)
    m.add(14, "/usr/bin/rsync -a /src/xcodebuild /dst", cwd=cwd)
    m.add(15, "/usr/bin/python3 tool.py --serve -m http.server", cwd=cwd)
    assert pids(storage_procs.find({}, m.ctx())) == []


def test_program_is_the_executable_or_the_interpreted_script():
    p = storage_procs.program
    assert p("/opt/homebrew/bin/node /x/node_modules/.bin/vite --port 5173") == "node vite"
    assert p("/usr/bin/python3.12 -u -m http.server 8000") == "python3.12 -m http.server"
    assert p("/bin/bash backup.sh --exclude /tmp/node") == "bash"
    assert p("next-server (v14.2.0)") == "next-server" and p("") == ""


def test_tmp_and_tmpdir_and_claude_worktrees_are_roots(tmp_path):
    m = Machine()
    tmpdir = str(tmp_path / "tmpdir")
    m.add(1001, "node a.js", cwd=f"{tmpdir}/abc123/app")
    m.add(1002, "node b.js", cwd="/private/tmp/definitely-not-here-xyz/app")
    m.add(1003, "node c.js", cwd=f"{tmp_path}/repo/.claude/worktrees/agent-ab12/web")
    assert sorted(pids(storage_procs.find({}, m.ctx(tmpdir=tmpdir)))) == [1001, 1002, 1003]


def test_a_cwd_that_still_exists_is_kept(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=live_wt(tmp_path))
    assert pids(storage_procs.find({}, m.ctx())) == []


def test_a_folder_outside_every_root_is_never_an_orphan_even_if_gone(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=str(tmp_path / "somewhere" / "else"))
    assert pids(storage_procs.find({}, m.ctx())) == []


def test_another_users_process_is_kept(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path), uid=0)
    assert pids(storage_procs.find({}, m.ctx())) == []


def test_a_process_on_a_terminal_is_kept(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path), tty="ttys003")
    assert pids(storage_procs.find({}, m.ctx())) == []


def test_a_young_process_is_kept(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path), etime="29:59")
    m.add(11, "node other.js", cwd=gone_wt(tmp_path), etime="30:00")
    assert pids(storage_procs.find({}, m.ctx())) == [11]
    cfg = {"storage": {"orphan_min_age_min": 60}}
    assert pids(storage_procs.find(cfg, m.ctx())) == []
    assert storage_procs.parse_etime("1-02:03:04") == 93784 and storage_procs.parse_etime("nonsense") is None


def test_a_command_outside_the_pattern_list_is_kept(tmp_path):
    m = Machine()
    m.add(10, "/usr/bin/vim notes.md", cwd=gone_wt(tmp_path))
    m.add(11, "/usr/bin/python3 train.py", cwd=gone_wt(tmp_path))
    assert pids(storage_procs.find({}, m.ctx())) == []
    cfg = {"storage": {"orphan_patterns": ["train\\.py"]}}
    assert pids(storage_procs.find(cfg, m.ctx())) == [11]


def test_this_process_and_its_ancestors_are_kept(tmp_path):
    m = Machine()
    cwd = gone_wt(tmp_path)
    m.add(10, "node claude-session.js", cwd=cwd, ppid=1)
    m.add(20, "npm run test", cwd=cwd, ppid=10)
    m.add(30, "node runner.js", cwd=cwd, ppid=20)       # this process
    m.add(40, "node unrelated.js", cwd=cwd, ppid=1)
    assert pids(storage_procs.find({}, m.ctx(self_pid=30))) == [40]


def test_a_failed_lsof_means_no_orphans(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path))
    m.lsof_fails = True
    found = storage_procs.find({}, m.ctx())
    assert found["orphans"] == [] and "lsof" in found["error"]


def test_a_process_lsof_does_not_name_is_kept(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path))
    m.add(11, "node other.js")                          # lsof prints nothing for it
    assert pids(storage_procs.find({}, m.ctx())) == [10]


def test_a_failed_ps_means_no_orphans(tmp_path):
    m = Machine()
    m.add(10, "node server.js", cwd=gone_wt(tmp_path))
    m.ps_fails = True
    found = storage_procs.find({}, m.ctx())
    assert found["orphans"] == [] and "ps" in found["error"]


def test_lsof_runs_once_for_all_candidates_and_not_at_all_without_any(tmp_path):
    m = Machine()
    for i in range(5):
        m.add(10 + i, "node s.js", cwd=gone_wt(tmp_path))
    storage_procs.find({}, m.ctx())
    assert m.lsof_calls == 1
    quiet = Machine()
    quiet.add(10, "/usr/bin/vim")
    storage_procs.find({}, quiet.ctx())
    assert quiet.lsof_calls == 0


# --- killing -----------------------------------------------------------------------------------

def test_kill_sends_sigterm_and_reports_the_freed_ram(tmp_path):
    m = Machine()
    cwd = gone_wt(tmp_path)
    m.add(10, "node a.js", cwd=cwd, rss_mb=300)
    m.add(11, "npm run dev", cwd=cwd, rss_mb=100)
    res = storage_procs.reap({}, ctx=m.ctx())
    assert sorted(m.signals) == [(10, 15), (11, 15)] and sorted(res["killed"]) == [10, 11]
    assert res["freed"] == 400 * MB * 1024 and m.rows == {}
    assert all(line.startswith("terminated pid") for line in res["lines"])
    assert "procs terminated pid 10" in (tmp_path / "storage.log").read_text()


def test_a_process_that_ignores_sigterm_gets_sigkill_after_the_grace_period(tmp_path):
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path))
    m.survives_term.add(10)
    res = storage_procs.reap({}, ctx=m.ctx())
    assert m.signals == [(10, 15), (10, 9)] and m.sleeps == storage_procs.GRACE_STEPS
    assert res["killed"] == [10] and "SIGKILL" in res["lines"][0]


def test_a_reused_pid_is_not_killed(tmp_path):
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path))
    m.survives_term.add(10)
    m.reused_after_term.add(10)
    res = storage_procs.reap({}, ctx=m.ctx())
    assert m.signals == [(10, 15)], "no SIGKILL for a pid that now runs something else"
    assert 10 in m.rows and m.rows[10]["command"] == "/usr/bin/python3 other.py"
    assert res["killed"] == [10], "the original process is gone, the stranger is left alone"


def test_a_pid_that_changed_between_the_scan_and_the_kill_is_skipped(tmp_path):
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path))
    found = storage_procs.find({}, m.ctx())
    m.rows[10]["lstart"] = "Thu Oct  8 11:00:00 2026"
    res = storage_procs.reap({}, ctx=m.ctx(), found=found)
    assert m.signals == [] and res["killed"] == [] and "pid was reused" in res["lines"][0]


class FakeWatch:
    def __init__(self, exits):
        self.exits, self.closed = exits, False

    def exited(self):
        return self.exits

    def close(self):
        self.closed = True


def test_a_process_that_exits_after_the_check_is_not_signalled(tmp_path):
    # The ps check passed, but the exit watch saw the process die: its pid may already be reused.
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path))
    watches = []
    res = storage_procs.reap({}, ctx=m.ctx(watch=lambda pid: watches.append(FakeWatch(True)) or watches[-1]))
    assert m.signals == [] and res["killed"] == [] and "pid was reused" in res["lines"][0]
    assert watches and all(w.closed for w in watches)


def test_a_process_gone_before_the_watch_is_not_signalled(tmp_path):
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path))
    res = storage_procs.reap({}, ctx=m.ctx(watch=lambda pid: storage_procs.GONE))
    assert m.signals == [] and res["killed"] == []


def test_the_exit_watch_follows_a_real_process():
    import select
    import subprocess
    import sys
    if not hasattr(select, "kqueue"):
        pytest.skip("kqueue is macOS/BSD only")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        w = storage_procs.watch_exit(child.pid)
        assert w not in (None, storage_procs.GONE) and not w.exited()
        child.kill()
        child.wait()
        assert w.exited()
        w.close()
    finally:
        if child.poll() is None:
            child.kill()
    assert storage_procs.watch_exit(child.pid) is storage_procs.GONE


def test_dry_run_signals_nothing(tmp_path):
    m = Machine()
    m.add(10, "node a.js", cwd=gone_wt(tmp_path), rss_mb=300)
    res = storage_procs.reap({}, dry=True, ctx=m.ctx())
    assert m.signals == [] and m.rows and res["freed"] == 0 and res["killed"] == []
    assert res["lines"][0].startswith("would kill pid 10") and "is gone" in res["lines"][0]


# --- the CLI -----------------------------------------------------------------------------------

def args(**kw):
    base = dict(kill=False, dry=False, json=False, quiet=False)
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def machine(tmp_path, monkeypatch):
    m = Machine()
    m.add(10, "node /x/node_modules/.bin/vite", cwd=gone_wt(tmp_path), rss_mb=512)
    monkeypatch.setattr(storage_procs, "Ctx", lambda: m.ctx())
    return m


def test_the_listing_shows_pid_rss_age_command_and_reason(machine, capsys):
    assert storage_procs.cmd_procs(args(), {}) == 0
    out = capsys.readouterr().out
    assert "1 orphan process(es), 512.0M RSS" in out and "    10" in out and "2h" in out and "vite" in out and "is gone" in out
    assert machine.signals == []


def test_json_output(machine, capsys):
    storage_procs.cmd_procs(args(json=True), {})
    data = json.loads(capsys.readouterr().out)
    assert data["orphans"][0]["pid"] == 10 and data["error"] is None


def test_quiet_prints_nothing_when_there_is_nothing_to_do(tmp_path, monkeypatch, capsys):
    m = Machine()
    m.add(10, "node s.js", cwd=live_wt(tmp_path))
    monkeypatch.setattr(storage_procs, "Ctx", lambda: m.ctx())
    assert storage_procs.cmd_procs(args(kill=True, quiet=True), {}) == 0
    assert storage_procs.cmd_procs(args(quiet=True), {}) == 0
    assert capsys.readouterr().out == ""
    storage_procs.cmd_procs(args(kill=True), {})
    assert "no orphan processes" in capsys.readouterr().out


def test_quiet_kill_prints_only_what_was_done(machine, capsys):
    storage_procs.cmd_procs(args(kill=True, quiet=True), {})
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and "terminated pid 10" in out[0] and "freed" not in out[0]
    assert machine.signals == [(10, 15)]


def test_kill_dry_via_the_cli_signals_nothing(machine, capsys):
    storage_procs.cmd_procs(args(kill=True, dry=True), {})
    assert "would kill pid 10" in capsys.readouterr().out and machine.signals == []


def test_the_storage_command_dispatches_procs(machine, capsys):
    ns = argparse.Namespace(action="procs", kill=False, dry=False, json=False, quiet=False)
    assert storage.cmd_storage(ns) == 0
    assert "orphan process(es)" in capsys.readouterr().out


def test_the_storage_report_and_doctor_mention_orphans(tmp_path):
    rows = [{"pid": 1, "rss_kb": 2 * 1024 * 1024, "age_s": 7200, "command": "node", "cwd": "/x", "reason": "r", "ppid": 1, "lstart": LSTART}]
    rep = {"disk": {"free": 10 ** 11, "total": 10 ** 12, "free_fraction": 0.1}, "settings": storage.settings({}),
           "worktrees": [], "artifacts": [], "derived": []}
    text = storage.render(rep, [], [], [], None, None, rows)
    assert "orphan processes (1, 2.0G RSS" in text and "storage procs --kill" in text
    assert "orphan processes" not in storage.render(rep, [], [], [], None, None, [])


def test_doctor_gets_an_info_row_only_above_one_gib(tmp_path, monkeypatch):
    big = [{"rss_kb": 1100 * MB}]
    monkeypatch.setattr(storage_procs, "find", lambda cfg=None, ctx=None: {"orphans": big, "error": None})
    row = next(r for r in storage.doctor_checks({}) if r["name"] == "storage:orphans")
    assert row["level"] == "INFO" and "storage procs --kill" in row["fix"] and "1.1G" in row["detail"]
    monkeypatch.setattr(storage_procs, "find", lambda cfg=None, ctx=None: {"orphans": [{"rss_kb": 900 * MB}], "error": None})
    assert not any(r["name"] == "storage:orphans" for r in storage.doctor_checks({}))


# --- the sims agent ------------------------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    for name, rel in (("PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Library/Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Library/Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(ri, name, home / rel)
    monkeypatch.setattr(ri, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    monkeypatch.setattr(ri, "sys", type("S", (), {"platform": "darwin", "argv": ["teyla"]}))
    monkeypatch.setattr(ri, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(ri, "_unload", lambda plist, label: f"unloaded {label}")
    monkeypatch.setattr(ri, "loaded", lambda label: (False, None, None))
    monkeypatch.setattr(ri.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launchctl called")))
    return home


def sims_wrapper() -> str:
    return ri.optional_paths(ri.SIMS_LABEL)["wrapper"].read_text()


def test_the_sims_wrapper_has_no_procs_line_by_default(home):
    config.set_value("storage.sims_agent", "true")
    ri.install()
    text = sims_wrapper()
    assert '"$TEYLA" storage sims --reap --quiet' in text and "storage procs" not in text
    assert not ri.is_stale()


def test_orphan_kill_adds_the_procs_line_to_the_sims_wrapper(home):
    config.set_value("storage.sims_agent", "true")
    config.set_value("storage.orphan_kill", "true")
    ri.install()
    lines = sims_wrapper().splitlines()
    assert ri.PROCS_LINE == '"$TEYLA" storage procs --kill --quiet' and ri.PROCS_LINE in lines
    assert lines.index('"$TEYLA" storage sims --reap --quiet') < lines.index(ri.PROCS_LINE)
    assert plistlib.loads(ri.optional_paths(ri.SIMS_LABEL)["plist"].read_bytes())["StartInterval"] == 600
    assert not ri.is_stale()


def test_switching_orphan_kill_on_or_off_makes_the_wrapper_stale(home):
    config.set_value("storage.sims_agent", "true")
    ri.install()
    assert not ri.is_stale()
    config.set_value("storage.orphan_kill", "true")
    assert ri.is_stale() and "STALE" in "\n".join(ri.status())
    assert any(c[0] == "FIX" and c[1] == "routine:sims" for c in ri.optional_checks())
    ri.install()
    assert not ri.is_stale()
    config.set_value("storage.orphan_kill", "false")
    assert ri.is_stale()
    ri.install()
    assert "storage procs" not in sims_wrapper() and not ri.is_stale()


def test_orphan_kill_alone_installs_nothing(home):
    config.set_value("storage.orphan_kill", "true")
    ri.install()
    assert not ri.optional_paths(ri.SIMS_LABEL)["plist"].exists() and not ri.optional_paths(ri.SIMS_LABEL)["wrapper"].exists()
    assert not ri.is_stale()
