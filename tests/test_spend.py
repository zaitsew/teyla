"""`teyla spend`: the waste rules, the Actions reading, the daily alert and the digest lines."""
from __future__ import annotations

import datetime as _dt
import json
import os

from teyla import digest, spend
from teyla.adapters import claude_code


def _row(**kw):
    r = dict(harness="claude-code", sid="abcdef123456", project="demo", cwd="/nowhere", first="2026-09-28T10:00:00Z",
             last="2026-09-28T12:00:00Z", usd=0.0, by_model={}, sub_usd=0.0, top_tier_sub_saving=0.0,
             reread_usd=0.0, loop_usd=0.0, inherited_agents=0, agents=0, prs=0, batch=False, repos=[])
    r.update(kw)
    return r


def test_w1_counts_only_expensive_sessions_with_no_outcome():
    rows = [_row(sid="idle00000000", usd=40.0), _row(sid="shipped00000", usd=90.0),
            _row(sid="cheap0000000", usd=3.0), _row(sid="batch0000000", usd=60.0, batch=True),
            _row(sid="norepo000000", usd=30.0)]
    verdict = {"idle00000000": False, "shipped00000": True, "cheap0000000": False, "norepo000000": None}
    coverage = []
    F = spend.findings(rows, outcome_of=lambda r: verdict[r["sid"]], coverage=coverage)
    assert coverage == ["W1: 1 session(s) over $15 had no repo to check ($30)"]
    w1 = [f for f in F if f["id"] == "W1"]
    assert len(w1) == 1 and w1[0]["usd"] == 40.0
    assert "idle0000" in w1[0]["evidence"] and "shipped" not in w1[0]["evidence"]


def test_grok_lanes_are_w5_not_w1():
    rows = [_row(harness="grok", usd=20.0)]
    F = spend.findings(rows, outcome_of=lambda r: False)
    assert [f["id"] for f in F] == ["W5"]


def test_w2_w3_w6_sum_their_dollars_and_drop_pennies():
    rows = [_row(reread_usd=12.0, top_tier_sub_saving=30.0, loop_usd=0.4, agents=4, inherited_agents=3),
            _row(sid="other0000000", reread_usd=3.0)]
    F = {f["id"]: f for f in spend.findings(rows, outcome_of=lambda r: None)}
    assert F["W2"]["usd"] == 15.0
    assert F["W3"]["usd"] == 30.0 and "3 of 4 Agent calls" in F["W3"]["evidence"]
    assert "W6" not in F  # $0.40 is under FINDING_FLOOR_USD
    assert list(F) == ["W3", "W2"]  # largest first


def test_w8_fires_past_80_percent_or_when_paying():
    actions = [dict(account="org", plan="team", minutes=3600, included=3000, share=1.2, paid_usd=3.5,
                    top_repos=["app-a", "app-b"], macos_minutes={"app-a": 33}),
               dict(account="me", plan="free", minutes=280, included=2000, share=0.14, paid_usd=0.0,
                    top_repos=["x"], macos_minutes={})]
    F = spend.findings([], actions)
    assert len(F) == 1 and F[0]["id"] == "W8" and F[0]["usd"] is None
    assert "$3.50 paid" in F[0]["title"] and "app-a 33 min" in F[0]["evidence"]


def test_actions_usage_reads_linux_equivalent_minutes(monkeypatch):
    monkeypatch.setattr("teyla.net.gate", lambda *a, **k: True)
    usage = {"usageItems": [
        {"product": "actions", "unitType": "Minutes", "sku": "Actions Linux", "quantity": 1500,
         "grossAmount": 9.0, "discountAmount": 8.4, "netAmount": 0.6, "repositoryName": "app-b"},
        {"product": "Actions", "unitType": "minutes", "sku": "Actions macOS 3-core", "quantity": 200,
         "grossAmount": 13.0, "discountAmount": 10.8, "netAmount": 2.2, "repositoryName": "app-a"},
        {"product": "actions", "unitType": "Minutes", "sku": "Actions Linux 32-core", "quantity": 200,
         "grossAmount": 16.4, "discountAmount": 0, "netAmount": 16.4, "repositoryName": "big"},
        {"product": "actions", "unitType": "GigabyteHours", "grossAmount": 0.02, "netAmount": 0},
        {"product": "copilot", "unitType": "Minutes", "grossAmount": 100, "netAmount": 100},
    ]}
    answers = {"/user": {"login": "me", "plan": {"name": "free"}}, "/user/orgs": [{"login": "org"}],
               "/orgs/org": {"plan": {"name": "team"}},
               "/users/me/settings/billing/usage?year=2026&month=9": {"usageItems": []},
               "/organizations/org/settings/billing/usage?year=2026&month=9": usage}
    out = {a["account"]: a for a in spend.actions_usage(_dt.date(2026, 9, 30), gh=answers.get)}
    org = out["org"]
    # 19.2 discounted dollars / $0.006: the included minutes used; the 32-core runner draws none
    assert org["minutes"] == 3200 and org["included"] == 3000 and round(org["share"], 2) == 1.07
    assert org["paid_usd"] == 19.2 and org["macos_minutes"] == {"app-a": 200}
    assert org["top_repos"][0] == "big"
    assert out["me"]["minutes"] == 0


def test_actions_usage_is_none_in_safe_mode(monkeypatch):
    monkeypatch.setattr("teyla.net.gate", lambda *a, **k: False)
    assert spend.actions_usage(gh=lambda p: (_ for _ in ()).throw(AssertionError("no call in safe mode"))) is None


def test_alert_only_for_the_last_day():
    now = _dt.datetime(2026, 9, 30, 7, 0, tzinfo=_dt.timezone.utc)
    rows = [_row(usd=300.0, last="2026-09-30T01:00:00Z"), _row(sid="old000000000", usd=500.0, last="2026-09-27T01:00:00Z"),
            _row(sid="small0000000", usd=60.0, last="2026-09-30T02:00:00Z")]
    out = spend.alerts(rows, [dict(account="org", share=0.85)], now=now)
    assert len(out) == 2 and "$300" in out[0] and "85%" in out[1]


def test_digest_carries_the_spend_line_and_findings():
    rep = dict(days=7, total_usd=400.0, waste_usd=100.0, findings=[
        dict(id="W2", usd=70.0, title="re-reading context", evidence="", fix="check compaction fired", cmd=False),
        dict(id="W6", usd=30.0 - 25.0, title="failed loops", evidence="", fix="stop after three", cmd=False)])
    lines, _ = digest.build([], [], [], {}, _dt.date(2026, 10, 2), rep)
    assert "W2 $70 re-reading context" in lines[0]
    assert lines[1].startswith("spend 7d: $400 API-equivalent, $100 of it waste (25%)")
    assert len(lines) <= 6
    lines, _ = digest.build([], [], [], {}, _dt.date(2026, 10, 2), dict(rep, findings=[], waste_usd=0.0))
    assert lines[0].endswith("nothing needs you this week.") and lines[1].startswith("spend 7d")


def test_banner_shows_todays_spend_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr(spend, "alerts_path", lambda: tmp_path / "spend.alerts")
    (tmp_path / "spend.alerts").write_text("2026-09-30\tsession demo abc 2026-09-30 cost $80\n"
                                           "2026-09-29\tsession old\n")
    items = digest.spend_items(_dt.date(2026, 9, 30))
    assert len(items) == 1 and items[0][1] == "spend: session demo abc 2026-09-30 cost $80"


def test_outcome_finds_a_commit_in_the_session_repo(tmp_path):
    import subprocess
    repo = tmp_path / "demo"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-28T13:00:00Z", GIT_COMMITTER_DATE="2026-09-28T13:00:00Z",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)
    assert spend.outcome(_row(cwd=str(repo))) is True
    assert spend.outcome(_row(cwd=str(repo), first="2026-09-20T10:00:00Z", last="2026-09-20T12:00:00Z")) is False
    assert spend.outcome(_row(cwd=str(tmp_path / "gone"))) is None
    assert spend.outcome(_row(prs=1)) is True


# --- adapter inputs ---------------------------------------------------------------------------

def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _msg(ts, mid, ctx_read=0, blocks=None):
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "role": "assistant", "model": "claude-fable-5-1",
                        "usage": {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": ctx_read,
                                  "cache_creation_input_tokens": 0},
                        "content": blocks or [{"type": "text", "text": "ok"}]}}


def _fail(ts, tid):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": True, "content": "boom"}]}}


def test_adapter_records_reread_loops_and_touched_repos(tmp_path):
    root = tmp_path / "projects"
    f = root / "-Users-me-repos" / "s1.jsonl"
    bash = lambda i: [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                       "input": {"command": "cd /Users/me/repos/teyla && git status"}}]
    _write(str(f), [
        {"type": "user", "timestamp": "2026-09-28T10:00:00Z", "message": {"role": "user", "content": "go"}},
        _msg("2026-09-28T10:00:01Z", "m1", ctx_read=300_000, blocks=bash(1)),
        _fail("2026-09-28T10:00:02Z", "t1"),
        _msg("2026-09-28T10:00:03Z", "m2", blocks=bash(2)), _fail("2026-09-28T10:00:04Z", "t2"),
        _msg("2026-09-28T10:00:05Z", "m3", blocks=bash(3)), _fail("2026-09-28T10:00:06Z", "t3"),
        _msg("2026-09-28T10:00:07Z", "m4"),  # the fourth message after three failures in a row
    ])
    s = claude_code.load(root=str(root))[0]
    assert s.reread_excess["claude-fable-5-1"] == 300_001 - 50_000
    assert s.loop_usage["claude-fable-5-1"]["output_tokens"] == 10
    assert s.touched_repos["teyla"] == 3


def test_waste_total_counts_a_dollar_once():
    rows = [_row(sid="idle00000000", usd=100.0, loop_usd=30.0, reread_usd=20.0),
            _row(sid="busy00000000", usd=10.0, reread_usd=8.0, loop_usd=5.0)]
    verdict = {"idle00000000": False, "busy00000000": True}
    F = spend.findings(rows, outcome_of=lambda r: verdict[r["sid"]])
    # the idle session is waste whole ($100, its loops inside); the busy one is capped at its $10
    assert spend.waste_usd(rows, F) == 110.0


def test_a_failed_git_log_is_unknown_not_idle(monkeypatch):
    monkeypatch.setattr(spend, "_repo_dirs", lambda r: ["/repo"])
    monkeypatch.setattr(spend, "_git", lambda args, cwd: None)
    assert spend.outcome(_row()) is None


def test_outcome_looks_in_touched_repos_too(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(spend.config, "code_root", lambda: tmp_path)
    for name in ("a", "b"):
        subprocess.run(["git", "init", "-q", str(tmp_path / name)], check=True)
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-28T13:00:00Z", GIT_COMMITTER_DATE="2026-09-28T13:00:00Z",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", str(tmp_path / "b"), "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)
    assert spend.outcome(_row(cwd=str(tmp_path / "a"), project="a", repos=["b"])) is True
