"""`teyla sessions`: synthetic desktop metadata, transcripts and Codex rollouts in tmp dirs. Nothing reads the
real machine, and nothing here calls `codex`, `gh` or a real `git`: each is replaced."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import stat

import pytest

from teyla import asks, backlog, sessions_tidy as st

pytestmark = pytest.mark.usefixtures("fake_code_root")

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()
HOME = "/Users/someone"


def ts(days_ago: float = 0.0) -> str:
    return dt.datetime.fromtimestamp(NOW - days_ago * 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ms(days_ago: float = 0.0) -> int:
    return int((NOW - days_ago * 86400) * 1000)


def write_jsonl(path: pathlib.Path, recs) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    class E:
        pass
    e = E()
    e.desktop, e.projects = tmp_path / "sessions", tmp_path / "projects"
    e.codex, e.archive = tmp_path / "codex" / "sessions", tmp_path / "codex" / "archived"
    for d in (e.desktop, e.projects, e.codex):
        d.mkdir(parents=True)
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(e.desktop))
    monkeypatch.setattr(asks.claude_code, "DEFAULT_ROOT", str(e.projects))
    monkeypatch.setattr(asks.codex, "DEFAULT_ROOT", str(e.codex))
    monkeypatch.setattr(asks.codex, "DEFAULT_ARCHIVE_ROOT", str(e.archive))
    monkeypatch.setattr(asks.codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    e.git = {"status": "", "contains": "origin/main\n"}
    e.calls = []

    def git(args, cwd):
        return (0, e.git["status"]) if args[0] == "status" else (0, e.git["contains"])
    monkeypatch.setattr(st, "git_out", git)

    def codex_run(args):
        e.calls.append(args)
        return 0, ""
    monkeypatch.setattr(st, "run_codex", codex_run)

    def desktop(cli_id, *, days_ago=3.0, title="A session", archived=False, prs=(), worktree="", needs="",
                cwd=f"{HOME}/repos/app"):
        sid = f"local_{cli_id}"
        d = {"sessionId": sid, "cliSessionId": cli_id, "cwd": cwd, "isArchived": archived, "title": title,
             "createdAt": ms(days_ago + 1), "lastActivityAt": ms(days_ago), "prs": [{"url": u} for u in prs],
             "postTurnSummary": {"status_category": "blocked" if needs else "done", "needs_action": needs}}
        if worktree:
            d["worktreePath"] = worktree
        p = e.desktop / "acct" / "work" / f"{sid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d))
    e.add = desktop

    def transcript(cli_id, recs, cwd=f"{HOME}/repos/app"):
        return write_jsonl(e.projects / re.sub(r"[/.]", "-", cwd) / f"{cli_id}.jsonl", recs)
    e.transcript = transcript

    def rollout(sid, recs=(), *, source="vscode", originator="Codex Desktop", days_ago=3.0, cwd=f"{HOME}/repos/app"):
        meta = {"type": "session_meta", "timestamp": ts(days_ago + 1), "payload": {
            "id": sid, "session_id": sid, "cwd": cwd, "originator": originator, "source": source}}
        p = write_jsonl(e.codex / "2026" / "10" / "13" / f"rollout-2026-10-13T10-00-00-{sid}.jsonl", [meta, *recs])
        os.utime(p, (NOW - days_ago * 86400,) * 2)
        return p
    e.rollout = rollout

    def plan(idle=24.0):
        return {r.session: r for r in st.plan(NOW, idle, fetch=False)}
    e.plan = plan
    return e


def asked(text="Which one should I use?"):
    return [{"type": "user", "uuid": "u1", "timestamp": ts(3), "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "uuid": "a1", "timestamp": ts(3),
             "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}]


def cx_msg(role, text, days_ago):
    kind = "input_text" if role == "user" else "output_text"
    return {"type": "response_item", "timestamp": ts(days_ago),
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}}


def ns(**kw):
    base = dict(words=[], json=False, apply=False, last=False, days=None, idle_hours=None, no_fetch=True)
    return argparse.Namespace(**{**base, **kw})


# --- the candidate rule ------------------------------------------------------------------------

def test_an_idle_session_that_waits_on_nothing_is_archived(env):
    env.add("c1")
    r = env.plan()["local_c1"]
    assert (r.verdict, r.harness, r.product) == ("archive", "claude-desktop", "app")


def test_a_session_idle_less_than_the_threshold_is_kept(env):
    env.add("c1", days_ago=0.5)
    assert env.plan()["local_c1"].reason == "active recently"
    assert env.plan(idle=6.0)["local_c1"].verdict == "archive"


def test_an_archived_session_is_not_listed(env):
    env.add("c1", archived=True)
    assert env.plan() == {}


def test_a_session_with_an_open_ask_is_kept(env):
    env.add("c1", needs="Pick the colour.")
    r = env.plan()["local_c1"]
    assert (r.verdict, r.reason) == ("keep", "open ask")


def test_a_transcript_question_keeps_the_session(env):
    env.add("c1")
    env.transcript("c1", asked())
    assert env.plan()["local_c1"].reason == "open ask"


def test_a_snoozed_ask_keeps_the_session(env):
    env.add("c1", needs="Pick the colour.")
    [item] = asks.collect(30, NOW, desktop=str(env.desktop), projects=str(env.projects), codex_root=str(env.codex),
                          codex_archive=str(env.archive))
    asks.save_state({"done": {}, "snoozed": {item.id: {"until": ts(-5)}}, "undone": {}}, now=NOW)
    assert env.plan()["local_c1"].reason == "open ask"


def test_a_muted_parked_product_ask_keeps_the_session(env, monkeypatch):
    env.add("c1", needs="Pick the colour.")
    monkeypatch.setattr(asks, "is_muted", lambda a, reg: True)
    assert env.plan()["local_c1"].reason == "open ask"


def test_a_done_ask_does_not_keep_the_session(env):
    env.add("c1", needs="Pick the colour.")
    [item] = asks.collect(30, NOW, desktop=str(env.desktop), projects=str(env.projects), codex_root=str(env.codex),
                          codex_archive=str(env.archive))
    asks.save_state({"done": {item.id: {"ts": ts(1), "note": "ok"}}, "snoozed": {}, "undone": {}}, now=NOW)
    assert env.plan()["local_c1"].verdict == "archive"


def pr_state(monkeypatch, state):
    monkeypatch.setattr(backlog, "pr_states", lambda urls, now, **kw: (
        {} if state is None else {backlog.canonical_pr_url(u): {"state": state, "at": 1.0} for u in urls}))


PR = "https://github.com/acme/app/pull/7"


def test_an_open_pr_keeps_the_session(env, monkeypatch):
    env.add("c1", prs=[PR])
    pr_state(monkeypatch, "OPEN")
    assert env.plan()["local_c1"].reason == "open PR"


def test_an_unknown_pr_state_keeps_the_session(env, monkeypatch):
    env.add("c1", prs=[PR])
    pr_state(monkeypatch, None)
    assert env.plan()["local_c1"].reason == "PR state unknown"


def test_a_merged_pr_lets_the_session_go(env, monkeypatch):
    env.add("c1", prs=[PR])
    pr_state(monkeypatch, "MERGED")
    assert env.plan()["local_c1"].verdict == "archive"


def test_a_dirty_worktree_keeps_the_session(env, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    env.add("c1", worktree=str(wt))
    env.git["status"] = " M file.py\n"
    assert env.plan()["local_c1"].reason == "worktree has unpushed work"


def test_a_worktree_head_missing_from_the_remote_keeps_the_session(env, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    env.add("c1", worktree=str(wt))
    env.git["contains"] = ""
    assert env.plan()["local_c1"].reason == "worktree has unpushed work"


def test_a_clean_pushed_worktree_and_a_missing_one_do_not_keep_the_session(env, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    env.add("c1", worktree=str(wt))
    env.add("c2", worktree=str(tmp_path / "gone"))
    plan = env.plan()
    assert plan["local_c1"].verdict == plan["local_c2"].verdict == "archive"


# --- Codex ---------------------------------------------------------------------------------------

def test_codex_interactive_idle_session_is_archived_and_exec_is_skipped(env):
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    env.rollout("22222222-bbbb", [cx_msg("user", "hello", 3)], source="exec", originator="codex_exec")
    plan = env.plan()
    assert plan["11111111-aaaa"].verdict == "archive" and "22222222-bbbb" not in plan


def test_a_codex_session_ending_on_a_question_is_kept(env):
    recs = [cx_msg("user", "go", 3), {"type": "event_msg", "timestamp": ts(3), "payload": {
        "type": "task_complete", "turn_id": "t1", "last_agent_message": "Which zip code should I use?"}}]
    env.rollout("33333333-cccc", recs)
    assert env.plan()["33333333-cccc"].reason == "open ask"


# --- modes ---------------------------------------------------------------------------------------

def test_dry_mode_logs_would_archive_once_and_never_calls_codex(env, capsys):
    env.add("c1")
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    assert st.cmd_tidy(ns(), NOW) == 0
    assert st.cmd_tidy(ns(), NOW + 60) == 0
    assert st.cmd_tidy(ns(), NOW + 120) == 0
    rows = st.read_log()
    assert sorted(r["session"] for r in rows) == ["11111111-aaaa", "local_c1"]
    assert {r["action"] for r in rows} == {"would_archive"}
    assert env.calls == []
    assert st.load_cfg()["dry_until"] == "2026-10-23"
    assert stat.S_IMODE(st.log_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(st.state_path().stat().st_mode) == 0o600


def test_apply_is_refused_in_dry_and_off_modes(env, capsys):
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    assert st.cmd_tidy(ns(apply=True), NOW) == 2
    st.cmd_mode(ns(words=["off"]), NOW)
    assert st.cmd_tidy(ns(apply=True), NOW) == 2
    assert env.calls == [] and st.read_log() == []
    assert "off" in (st.cmd_tidy(ns(), NOW), capsys.readouterr().out)[1]


def test_on_mode_apply_archives_codex_with_its_uuid_and_json_names_the_mode(env, capsys):
    env.add("c1")
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    st.cmd_mode(ns(words=["on"]), NOW)
    capsys.readouterr()
    assert st.cmd_tidy(ns(apply=True, json=True), NOW) == 0
    out = json.loads(capsys.readouterr().out)
    assert env.calls == [["archive", "11111111-aaaa"]]
    assert out["mode"] == "on" and out["archived"] == ["11111111-aaaa"]
    assert {"mode", "dry_until", "idle_hours", "rows"} <= set(out)
    assert {r["session"]: r["verdict"] for r in out["rows"]} == {"local_c1": "archive", "11111111-aaaa": "archive"}
    assert [r["action"] for r in st.read_log()] == ["archived"]


def test_json_lists_the_kept_rows_too(env, capsys):
    env.add("c1")
    env.add("c2", needs="Q?")
    st.cmd_tidy(ns(json=True), NOW)
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert {r["session"]: r["reason"] for r in rows}["local_c2"] == "open ask"


def test_the_human_plan_lists_archive_rows_and_counts_the_kept_by_reason(env, capsys):
    env.add("c1", title="Finished job")
    env.add("c2", needs="Q?", title="Waiting job")
    st.cmd_tidy(ns(), NOW)
    out = capsys.readouterr().out
    assert "Finished job" in out and "Waiting job" not in out and "kept 1: 1 open ask" in out


# --- record, undo, log -------------------------------------------------------------------------------

def test_record_undo_and_log_round_trip(env, capsys):
    env.add("c1", title="Finished job")
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    assert st.cmd_record(ns(words=["local_c"]), NOW) == 0          # a prefix finds the session
    st.cmd_mode(ns(words=["on"]), NOW)
    st.cmd_tidy(ns(apply=True), NOW + 100)
    capsys.readouterr()
    assert [r["action"] for r in st.read_log()] == ["archived", "archived"]

    st.cmd_undo(ns(last=True), NOW + 200)                           # the last run: the Codex one
    out = capsys.readouterr().out
    assert ["unarchive", "11111111-aaaa"] in env.calls and "local_c1" not in out

    st.cmd_undo(ns(words=["local_c1"]), NOW + 300)
    assert "unarchive_session for local_c1" in capsys.readouterr().out
    last = st.last_actions(st.read_log())
    assert {k: v["action"] for k, v in last.items()} == {"local_c1": "unarchived", "11111111-aaaa": "unarchived"}

    st.cmd_log(ns(days=7, json=True), NOW + 400)
    assert len(json.loads(capsys.readouterr().out)) == 4


def test_a_would_archive_row_can_be_logged_again_after_an_undo(env):
    env.add("c1")
    st.cmd_tidy(ns(), NOW)
    st.cmd_record(ns(words=["local_c1"]), NOW + 10)
    st.cmd_undo(ns(words=["local_c1"]), NOW + 20)
    st.cmd_tidy(ns(), NOW + 30)
    assert [r["action"] for r in st.read_log()] == ["would_archive", "archived", "unarchived", "would_archive"]


# --- report ----------------------------------------------------------------------------------------

def test_report_with_no_mistake_recommends_mode_on(env, capsys):
    env.add("c1")
    st.cmd_tidy(ns(), NOW)
    st.cmd_report(ns(), NOW + 3600)
    out = capsys.readouterr().out
    assert "would_archive 1" in out and "mistakes: 0" in out and "recommend `teyla sessions mode on`" in out


def test_report_counts_a_session_that_got_a_human_prompt_after_it_was_logged(env, capsys):
    env.add("c1", title="Came back to life")
    env.transcript("c1", asked("Done.")[:2])
    st.cmd_tidy(ns(), NOW)
    later = NOW + 3600
    env.add("c1", title="Came back to life", days_ago=(NOW - later) / 86400)
    env.transcript("c1", asked("Done.")[:2] + [
        {"type": "user", "uuid": "u9", "timestamp": ts(-3600 / 86400), "message": {"role": "user", "content": "one more thing please"}}])
    st.cmd_report(ns(), later + 60)
    out = capsys.readouterr().out
    assert "mistakes: 1" in out and "Came back to life" in out and "keep dry" in out


def test_report_counts_a_codex_session_with_a_later_user_message(env, capsys):
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3)])
    st.cmd_tidy(ns(), NOW)
    env.rollout("11111111-aaaa", [cx_msg("user", "hello", 3), cx_msg("user", "actually, change it", -0.01)])
    st.cmd_report(ns(), NOW + 3600)
    assert "mistakes: 1" in capsys.readouterr().out


def test_mode_shows_and_sets(env, capsys):
    st.cmd_mode(ns(), NOW)
    assert "mode dry" in capsys.readouterr().out
    assert st.cmd_mode(ns(words=["bogus"]), NOW) == 64
    st.cmd_mode(ns(words=["dry"]), NOW)
    assert st.load_cfg()["dry_until"] == "2026-10-23"
