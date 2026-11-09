"""teyla brief: the sprint contract, its budget hook and the per-session list-price cost."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys

import pytest

from teyla import brief, cli, config, session_cost
from teyla.adapters import claude_code

MODEL = "claude-sonnet-5-5"  # $10 per 1M output tokens at list price
SID = "11111111-aaaa-bbbb-cccc-000000000001"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / "teyla")
    root = tmp_path / "projects"
    (root / "slug").mkdir(parents=True)
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(root))
    repo = tmp_path / "widget"
    repo.mkdir()
    return tmp_path, root, repo


def _msg(i, out_tokens):
    return json.dumps({"type": "assistant", "timestamp": "2026-11-09T10:00:00Z",
                       "message": {"id": f"m{i}", "model": MODEL, "usage": {"output_tokens": out_tokens}}})


def transcript(root, sid, out_tokens, sub_out=0):
    f = root / "slug" / f"{sid}.jsonl"
    f.write_text(_msg(1, out_tokens) + "\n")
    if sub_out:
        d = root / "slug" / sid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        (d / "agent-1.jsonl").write_text(_msg(1, sub_out) + "\n")
    return f


def start(repo, usd=100, hours=10):
    return brief.create("widget", goal="g", slice_="s", platform="ios", usd=usd, hours=hours, gates=["./check.sh"],
                        repo=str(repo))


def call(repo, sid=SID, tool="Agent"):
    return brief.hook(json.dumps({"tool_name": tool, "session_id": sid, "cwd": str(repo)}))


def test_contract_written_with_all_fields_and_sentence(env, capsys):
    _tmp, _root, repo = env
    rc = cli.main(["brief", "widget", "--goal", "ship it", "--slice", "login", "--platform", "ios", "--usd", "50",
                   "--hours", "4", "--gate", "a", "--gate", "b", "--repo", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Budget = Teyla's list-price estimate (API list price) for this session plus all its subagents. " \
           "Subscription use and billed spend differ." in out
    path, c = brief.load_active("widget")
    assert path.parent == config.TEYLA_DIR / "briefs" / "widget"
    assert c["goal"] == "ship it" and c["slice"] == "login" and c["platform"] == "ios"
    assert c["usd"] == 50 and c["hours"] == 4 and c["gates"] == ["a", "b"]
    assert c["repo"] == str(repo.resolve()) and c["sessions"] == [] and c["started"].endswith("Z")
    assert cli.main(["brief", "widget", "--repo", str(repo)]) == 0  # no flags: prints the active one
    assert "ship it" in capsys.readouterr().out


def test_product_from_worktree_cwd(tmp_path):
    main = tmp_path / "gadget"
    main.mkdir()
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*g, "init", "-q"], cwd=main, check=True)
    subprocess.run([*g, "commit", "-q", "--allow-empty", "-m", "x"], cwd=main, check=True)
    wt = main / ".claude" / "worktrees" / "lane-1"
    subprocess.run([*g, "worktree", "add", "-q", "-b", "lane", str(wt)], cwd=main, check=True)
    assert brief.product_of(str(wt)) == "gadget"
    (main / "teyla.toml").write_text('[product]\nname = "gizmo"\n')
    assert brief.product_of(str(wt)) == "gizmo"
    assert brief.product_of(str(main)) == "gizmo"


def test_hook_no_contract_exits_0(env):
    assert call(env[2]) == (0, "")


def test_hook_ignores_other_tools(env):
    _t, root, repo = env
    start(repo, usd=1)
    transcript(root, SID, 1_000_000)  # $10 against $1
    call(repo)  # binds the session
    assert call(repo, tool="Bash") == (0, "")
    assert call(repo, tool="Task")[0] == 2


def test_hook_under_80_percent_allows(env):
    _t, root, repo = env
    start(repo, usd=100)
    transcript(root, SID, 5_000_000)  # $50
    assert call(repo) == (0, "")


def test_hook_85_percent_by_dollars_refuses_new_lane(env):
    _t, root, repo = env
    start(repo, usd=100)
    transcript(root, SID, 8_500_000)  # $85
    code, err = call(repo)
    assert code == 2 and "start no new lane" in err and "85%" in err and "$85.00 of $100" in err
    assert "checkpoint" not in err
    rows = (config.TEYLA_DIR / "briefs" / "refusals.tsv").read_text().splitlines()
    assert len(rows) == 1 and rows[0].split("\t")[1] == "widget"


def test_hook_85_percent_by_hours_refuses(env):
    _t, root, repo = env
    path, c = start(repo, usd=1000, hours=10)
    c["started"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8.5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    brief._write(path, c)
    transcript(root, SID, 1000)
    code, err = call(repo)
    assert code == 2 and "start no new lane" in err and "85%" in err


def test_hook_120_percent_says_checkpoint(env):
    _t, root, repo = env
    start(repo, usd=100)
    transcript(root, SID, 12_000_000)  # $120
    code, err = call(repo)
    assert code == 2 and "checkpoint now" in err and "120%" in err and "one question" in err


def test_session_bound_on_first_call(env):
    _t, root, repo = env
    start(repo)
    transcript(root, SID, 1000)
    assert brief.load_active("widget")[1]["sessions"] == []
    call(repo)
    call(repo)
    assert brief.load_active("widget")[1]["sessions"] == [SID]


def test_expired_contract_does_not_block_a_new_session(env):
    _t, root, repo = env
    path, c = start(repo, usd=1, hours=1)
    c["started"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    brief._write(path, c)
    transcript(root, SID, 5_000_000)
    code, err = call(repo)
    assert code == 0 and "expired" in err and "--close" in err
    assert call(repo) == (0, "")  # the note comes once per session
    assert brief.load_active("widget")[1]["sessions"] == []


def test_concurrent_binds_both_land(env):
    import threading
    _t, _root, repo = env
    path, _c = start(repo)
    sids = [f"sess-{i}" for i in range(12)]
    ts = [threading.Thread(target=brief.bind, args=(path, s)) for s in sids]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(brief.load_active("widget")[1]["sessions"]) == sorted(sids)


def test_session_not_bound_when_contract_is_old(env):
    _t, root, repo = env
    path, c = start(repo, hours=1)
    c["started"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    brief._write(path, c)
    call(repo)
    assert brief.load_active("widget")[1]["sessions"] == []


def test_raise_usd_lifts_a_refusal(env, capsys):
    _t, root, repo = env
    start(repo, usd=100)
    transcript(root, SID, 9_000_000)  # $90
    assert call(repo)[0] == 2
    rc = cli.main(["brief", "widget", "--raise-usd", "100", "--reason", "owner agreed", "--repo", str(repo)])
    assert rc == 0
    assert call(repo) == (0, "")
    c = brief.load_active("widget")[1]
    assert c["usd"] == 200 and c["raises"][0]["reason"] == "owner agreed" and c["raises"][0]["by"]


def test_raise_needs_reason(env):
    start(env[2])
    assert cli.main(["brief", "widget", "--raise-usd", "10"]) == 2


def test_corrupt_contract_fails_open(env):
    _t, root, repo = env
    path, _c = start(repo, usd=1)
    transcript(root, SID, 5_000_000)
    path.write_text("this is [not toml")
    assert call(repo) == (0, "")
    assert brief.hook("not json") == (0, "")


def test_hook_via_cli_stdin(env, monkeypatch, capsys):
    _t, root, repo = env
    start(repo, usd=100)
    transcript(root, SID, 12_000_000)
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Agent", "session_id": SID, "cwd": str(repo)})))
    assert cli.main(["brief", "--hook"]) == 2
    assert "checkpoint now" in capsys.readouterr().err


def test_close_ends_the_contract(env):
    _t, _root, repo = env
    start(repo, usd=0.01)
    assert cli.main(["brief", "widget", "--close"]) == 0
    assert brief.load_active("widget") is None


def test_session_cost_counts_subagents_and_caches(env, monkeypatch):
    _t, root, _repo = env
    transcript(root, SID, 1_000_000, sub_out=2_000_000)
    cost = session_cost.session_cost(SID)
    assert cost["usd"] == pytest.approx(30.0) and cost["sub_usd"] == pytest.approx(20.0)
    assert session_cost.session_cost("no-such-session") == {"usd": 0.0, "sub_usd": 0.0}
    monkeypatch.setattr(session_cost, "compute", lambda files: pytest.fail("unchanged session must hit the cache"))
    assert session_cost.session_cost(SID)["usd"] == pytest.approx(30.0)


def test_session_cost_ignores_other_sessions(env):
    _t, root, _repo = env
    transcript(root, SID, 1_000_000)
    transcript(root, "22222222-aaaa-bbbb-cccc-000000000002", 5_000_000)
    assert session_cost.session_cost(SID)["usd"] == pytest.approx(10.0)
