"""`teyla state` and `teyla answer`: synthetic items and session stores in tmp dirs. No test starts a
real `claude` or `codex`: `answer.run` is replaced."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pytest

from teyla import answer, asks, backlog, cli, reviews, state
from teyla.adapters import codex

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()
TODAY = dt.datetime.fromtimestamp(NOW).date()
CODEX_SID = "01a14630-4c3f-7921-91ca-b89037bced86"
CLAUDE_SID = "0bbe62f8-fca8-4e9b-b708-8362976fb8ac"


def ask(id="aaaa1111", kind="question", product="atlas", title="t", question="q", context="", hours=48.0,
        harness="claude-desktop", session=CLAUDE_SID, link="claude://claude.ai/epitaxy/local_x", **kw):
    return asks.Ask(id=id, kind=kind, product=product, title=title, question=question, context=context,
                    options=[], when=NOW - hours * 3600, archived=False, link=link, pr="", harness=harness,
                    session=session, **kw)


# --- ranking -----------------------------------------------------------------------------------

def test_kind_weight_release_signal_and_freshness_order_the_list():
    items = [ask("reminder1", "reminder", product="reminders", question="Renew the domain", harness="teyla",
                 session="", due="2026-10-16"),
             ask("plain111", question="Which color?"),
             ask("fresh111", question="Which font?", hours=2),
             ask("block111", "blocked", question="Needs your key"),
             ask("review11", question="Swap the iPhone review?", context="Mac 1.1 is in App Review.", hours=30)]
    out = state.ranked(items, NOW)
    # release question 2+3; blocked 3 and fresh question 2+1 tie, the newer first; plain question 2; reminder 0
    assert [a["id"] for a in out] == ["review11", "fresh111", "block111", "plain111", "reminder1"]
    assert [a["rank"] for a in out] == [1, 2, 3, 4, 5]


def test_ties_go_to_the_newer_item():
    out = state.ranked([ask("older111", hours=30), ask("newer111", hours=26)], NOW)
    assert [a["id"] for a in out] == ["newer111", "older111"]


def test_reminders_show_only_once_due_and_done_items_are_dropped():
    soon = ask("soon1111", "reminder", harness="teyla", session="", due=(TODAY + dt.timedelta(days=3)).isoformat())
    late = ask("late1111", "reminder", harness="teyla", session="", due=(TODAY - dt.timedelta(days=1)).isoformat())
    done = ask("done1111", status="done")
    assert [a["id"] for a in state.ranked([soon, late, done], NOW)] == ["late1111"]


@pytest.mark.parametrize("text,phrase", [
    ("Mac 1.1 is back in App Review", "a release"),
    ("The TestFlight build is processing", "a release"),
    ("Ship the release today?", "a release"),
    ("Finish the Google sign-in in your browser", "a sign-in only you can do"),
    ("Paste the credential into the config", "a sign-in only you can do"),
    ("Merge the open PR?", "a merge"),
    ("Which color do you prefer?", ""),
])
def test_unblocks_phrases(text, phrase):
    assert state.unblocks(ask(question=text)) == phrase


def test_release_beats_sign_in_in_the_phrase():
    assert state.unblocks(ask(question="Sign in so I can submit to App Review")) == "a release"


def test_delivery_choice():
    assert state.delivery(ask(harness="codex", session=CODEX_SID)) == "codex"
    assert state.delivery(ask(harness="claude-desktop")) == "claude"
    assert state.delivery(ask(harness="claude-code")) == "claude"
    assert state.delivery(ask(harness="claude-desktop", session="")) == "open"
    assert state.delivery(ask(harness="teyla", session="")) == "open"


def test_the_ask_json_schema_of_teyla_asks_is_unchanged(monkeypatch):
    d = ask().to_dict(NOW)
    assert "session" not in d
    assert {"unblocks", "rank", "delivery"} <= set(state.ranked([ask()], NOW)[0])


# --- running sessions --------------------------------------------------------------------------

def desktop_file(root: pathlib.Path, sid: str, *, minutes_ago: float, archived=False, cwd="/Users/someone/repos/atlas",
                 title=None, summary=None, prs=None):
    p = root / "acct" / "work" / f"{sid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"sessionId": sid, "cliSessionId": sid[6:], "cwd": cwd, "isArchived": archived,
            "title": title or f"Title of {sid}", "model": "claude-sonnet-5-5",
            "createdAt": int((NOW - 7200) * 1000), "lastActivityAt": int((NOW - minutes_ago * 60) * 1000)}
    if summary is not None:
        meta["postTurnSummary"] = summary
    if prs:
        meta["prs"] = [{"url": u} for u in prs]
    p.write_text(json.dumps(meta))
    return p


def rollout(root: pathlib.Path, sid: str, *, minutes_ago: float, cwd="/Users/someone/.worktrees/cellar/feat", source="vscode",
            originator="Codex Desktop", day="2026/10/16", message=None, unfinished=False):
    """A rollout whose file time is `minutes_ago`. `message` adds a finished turn ending in it, `unfinished`
    a turn that has started and not completed."""
    d = root.joinpath(*day.split("/"))
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"rollout-{day.replace('/', '-')}T10-00-00-{sid}.jsonl"
    recs = [{"type": "session_meta", "timestamp": "2026-10-16T10:00:00.000Z",
             "payload": {"id": sid, "session_id": sid, "cwd": cwd, "source": source,
                         "originator": originator}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}]
    end = dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if message is not None:
        recs += [{"type": "event_msg", "timestamp": end, "payload": {"type": "task_started"}},
                 {"type": "event_msg", "timestamp": end, "payload": {"type": "task_complete", "last_agent_message": message}}]
    if unfinished:
        recs.append({"type": "event_msg", "timestamp": end, "payload": {"type": "task_started"}})
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    t = NOW - minutes_ago * 60
    os.utime(p, (t, t))
    return p


def test_running_desktop_sessions_are_the_unarchived_ones_active_in_ten_minutes(tmp_path):
    root = tmp_path / "sessions"
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000001", minutes_ago=3)
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000002", minutes_ago=30)
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000003", minutes_ago=2, archived=True)
    rows = state.running_desktop(NOW, str(root))
    assert [r["link"] for r in rows] == ["claude://claude.ai/epitaxy/local_aaaa1111-0000-0000-0000-000000000001"]
    r = rows[0]
    assert (r["product"], r["harness"], r["model"]) == ("atlas", "claude-desktop", "claude-sonnet-5-5")
    assert r["since"] == asks._iso(NOW - 7200)


def test_running_codex_rollouts_are_the_ones_written_in_ten_minutes(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    rollout(root, "11111111-0000-0000-0000-000000000001", minutes_ago=4)
    rollout(root, "11111111-0000-0000-0000-000000000002", minutes_ago=45)
    rollout(root, "11111111-0000-0000-0000-000000000003", minutes_ago=1, source={"subagent": {"x": 1}})
    rows = state.running_codex(NOW, str(root))
    assert len(rows) == 1
    assert (rows[0]["product"], rows[0]["harness"], rows[0]["model"]) == ("cellar", "codex", "gpt-6.1-sol")
    assert rows[0]["link"] == "codex://threads/11111111-0000-0000-0000-000000000001"


def test_headless_codex_runs_and_review_sessions_are_not_running_sessions(tmp_path, monkeypatch):
    # on a real machine: headless `codex exec` rollouts carry originator "codex_exec" and source "exec";
    # the desktop app writes originator "Codex Desktop" and source "vscode"
    root = tmp_path / "codex"
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    rollout(root, "11111111-0000-0000-0000-00000000000a", minutes_ago=1)
    rollout(root, "11111111-0000-0000-0000-00000000000b", minutes_ago=1, source="exec", originator="codex_exec")
    rollout(root, "11111111-0000-0000-0000-00000000000c", minutes_ago=1, source="vscode", originator="codex_exec")
    rows = state.running_codex(NOW, str(root))
    assert [r["link"] for r in rows] == ["codex://threads/11111111-0000-0000-0000-00000000000a"]
    desktop = tmp_path / "sessions"
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000004", minutes_ago=1, title="You are reviewing a diff")
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000005", minutes_ago=1, title="Fix the build")
    assert [r["title"] for r in state.running_desktop(NOW, str(desktop))] == ["Fix the build"]


def test_running_override_env_is_honoured_by_the_desktop_root(tmp_path, monkeypatch):
    desktop_file(tmp_path / "s", "local_aaaa1111-0000-0000-0000-000000000009", minutes_ago=1)
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(tmp_path / "s"))
    assert len(state.running_desktop(NOW)) == 1


# --- products, brief, snapshot -----------------------------------------------------------------

def test_products_state_rules(tmp_path):
    def repo(name, days_ago, tag_today=False):
        p = tmp_path / "repos" / name
        (p / ".git" / "logs").mkdir(parents=True)
        h = p / ".git" / "logs" / "HEAD"
        h.write_text("x")
        t = NOW - days_ago * 86400
        os.utime(h, (t, t))
        if tag_today:
            tag = p / ".git" / "refs" / "tags"
            tag.mkdir(parents=True)
            (tag / "v1").write_text("x")
            os.utime(tag / "v1", (NOW, NOW))
        return p
    repos = {"lens": repo("lens", 5), "forge": repo("forge", 0.1, tag_today=True), "plain": repo("plain", 0.5),
             "ancient": repo("ancient", 90)}
    rows = state.ranked([ask("aaaa0001", product="atlas")], NOW)
    run = [{"product": "cellar", "title": "Doing a thing", "_last": NOW - 60}]
    by = {p["name"]: p for p in state.products_view(rows, run, repos, NOW)}
    assert by["atlas"]["state"] == "waiting" and by["atlas"]["waiting"] == 1 and by["atlas"]["line"] == "t"
    assert by["cellar"]["state"] == "active" and by["cellar"]["line"] == "Doing a thing"
    assert by["lens"]["state"] == "quiet" and by["lens"]["line"] == "no activity for 5 days"
    assert by["forge"]["state"] == "shipped"
    assert by["plain"]["state"] == "active"
    assert "ancient" not in by
    assert list(by)[0] == "atlas"                      # waiting first


def test_brief_names_the_product_whose_release_answers_wait():
    rows = state.ranked([ask("aaaa0001", product="cellar", question="Swap the App Review build?"),
                         ask("aaaa0002", product="cellar", question="TestFlight or release?"),
                         ask("aaaa0003", product="atlas", question="Which font?")], NOW)
    b = state.brief_line({"asks": rows})
    assert b["source"] == "rules"
    assert b["line"].startswith("2 answers unblock cellar's release today.")
    assert len(b["line"].split()) <= 25


def test_brief_without_release_and_without_questions():
    one = state.ranked([ask(product="atlas", question="Which font?")], NOW)
    assert state.brief_line({"asks": one})["line"] == "1 question waits for you, the first one in atlas."
    assert state.brief_line({"asks": []}) == {"line": "Nothing waits on you.", "source": "rules"}


def test_build_snapshot_matches_the_contract_fields(tmp_path):
    desktop = tmp_path / "sessions"
    desktop.mkdir()
    st = state.build(NOW, items=[ask("aaaa0001", question="Ship it to App Review?")], repos={}, spent=4.1,
                     desktop=str(desktop), codex_root=str(tmp_path / "nocodex"))
    fixture = json.loads((FIXTURES / "state.v2.json").read_text())
    assert set(st) == set(fixture)
    assert set(st["totals"]) == set(fixture["totals"])
    assert set(st["asks"][0]) == set(fixture["asks"][0])
    assert set(st["products"][0]) == set(fixture["products"][0])
    assert set(st["relay"]) == set(fixture["relay"])
    assert st["totals"] == {"questions": 1, "running": 0, "spent_today_usd": 4.1, "tasks": 0, "done": 0}
    assert st["version"] == 2 and st["generated"] == asks._iso(NOW)
    assert st["relay"] == {"on": False, "paired": False, "folder": "", "synced": ""}


def test_every_list_of_the_snapshot_has_the_keys_of_the_v2_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    desktop, cx = tmp_path / "sessions", tmp_path / "codex"
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000001", minutes_ago=3)
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000002", minutes_ago=120,
                 summary={"status_category": "completed", "status_detail": "Merged PR 5"})
    rollout(cx, "11111111-0000-0000-0000-000000000001", minutes_ago=2)
    rollout(cx, "11111111-0000-0000-0000-000000000002", minutes_ago=90, message="Done")
    bl = backlog_data(prs=[pr_row("example/lens", 14, "ab" * 20)], issues=[issue_row("example/cellar", 88)])
    st = state.build(NOW, items=[ask("aaaa0001")], repos={}, spent=None, desktop=str(desktop), codex_root=str(cx),
                     backlog_data=bl, approved=set(), ledger=None, runs=[])
    fixture = json.loads((FIXTURES / "state.v2.json").read_text())
    assert {t["kind"] for t in st["tasks"]} == {"merge", "task"}
    for t in st["tasks"]:
        assert set(t) == set(fixture["tasks"][0])
    assert len(st["done"]) == 2 and all(set(d) == set(fixture["done"][0]) for d in st["done"])
    assert {r["harness"] for r in st["running"]} == {"claude-desktop", "codex"}
    assert all(set(r) == set(fixture["running"][0]) for r in st["running"])
    assert st["totals"]["tasks"] == 2 and st["totals"]["done"] == 2 and st["totals"]["running"] == 2


def test_spend_comes_from_a_fresh_cache_and_a_stale_one_starts_a_refresh(monkeypatch):
    spawned = []
    monkeypatch.setattr(state, "_spawn_refresh", lambda: spawned.append(1))
    assert state.spent_today(NOW) is None and spawned == [1]
    state._spend_cache().write_text(json.dumps({"day": state._local_day(NOW), "usd": 3.5, "at": NOW - 60}))
    assert state.spent_today(NOW) == 3.5 and spawned == [1]
    state._spend_cache().write_text(json.dumps({"day": state._local_day(NOW), "usd": 3.5, "at": NOW - 4000}))
    assert state.spent_today(NOW) == 3.5 and spawned == [1, 1]
    state._spend_cache().write_text(json.dumps({"day": "2020-01-01", "usd": 9.0, "at": NOW}))
    assert state.spent_today(NOW) is None


def test_state_command_prints_json_and_short_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [ask("aaaa0001", question="Ship to App Review?")])
    monkeypatch.setattr(state, "repo_index", lambda: {})
    monkeypatch.setattr(state, "spent_today", lambda now: None)
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(tmp_path / "none"))
    assert cli.main(["state", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["asks"][0]["delivery"] == "claude" and d["totals"]["spent_today_usd"] is None
    assert cli.main(["state"]) == 0
    out = capsys.readouterr().out
    assert len(out.splitlines()) <= 15 and "aaaa0001" in out


# --- the model brief ---------------------------------------------------------------------------

REAL_SPAWN = state._spawn_brief_refresh        # conftest replaces the module attribute for every test


def brief_items():
    return [ask("aaaa0001", product="atlas", question="Add a read-only command?", hours=5),
            ask("aaaa0002", product="cellar", question="Ship to App Review?", hours=30),
            ask("aaaa0003", "blocked", product="cellar", question="Needs your key", hours=60)]


def brief_rows():
    return state.ranked(brief_items(), NOW)


def model_reply(**over):
    r = {"brief": "Cellar waits on a key and a review decision; Atlas can wait.",
         "items": [{"id": "aaaa0003", "rank": 1, "unblocks": "the Cellar build"},
                   {"id": "aaaa0002", "rank": 2, "unblocks": ""},
                   {"id": "aaaa0001", "rank": 3, "unblocks": "a new command"}]}
    r.update(over)
    return r


def claude_stdout(reply, **over):
    out = {"type": "result", "is_error": False, "result": reply if isinstance(reply, str) else json.dumps(reply),
           "total_cost_usd": 0.0012, "duration_ms": 2100}
    out.update(over)
    return json.dumps(out)


@pytest.fixture
def brief_env(monkeypatch):
    monkeypatch.setattr(state, "model_brief_enabled", lambda: True)
    spawned = []
    monkeypatch.setattr(state, "_spawn_brief_refresh", lambda now=None: spawned.append(1))
    return spawned


def fake_claude(monkeypatch, code, stdout, seen=None):
    def run(cmd, input_text, timeout=0):
        if seen is not None:
            seen.append((cmd, input_text))
        return code, stdout
    monkeypatch.setattr(state, "_run_claude", run)


def write_brief_cache(rows, age_s=60, **over):
    c = {"generated": asks._iso(NOW - age_s), "ask_ids_hash": state.ask_ids_hash(rows), **model_reply()}
    c.update(over)
    state._brief_cache().write_text(json.dumps(c))


def snapshot(items):
    return state.build(NOW, items=items, repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent")


def test_model_brief_replaces_rules_when_the_cache_matches_the_open_set(brief_env):
    write_brief_cache(brief_rows())
    st = snapshot(brief_items())
    assert st["brief"] == {"line": "Cellar waits on a key and a review decision; Atlas can wait.", "source": "model"}
    assert [(a["id"], a["rank"], a["unblocks"]) for a in st["asks"]] == [
        ("aaaa0003", 1, "the Cellar build"), ("aaaa0002", 2, ""), ("aaaa0001", 3, "a new command")]
    assert brief_env == []                              # fresh and matching: no refresh


def test_cache_for_another_set_means_rules_and_one_refresh(brief_env):
    rows = brief_rows()
    write_brief_cache(rows, ask_ids_hash="0" * 16)
    assert state.cached_brief(rows, NOW) is None and brief_env == [1]
    state._brief_cache().unlink()
    assert state.cached_brief(rows, NOW) is None and brief_env == [1, 1]
    assert snapshot(brief_items())["brief"]["source"] == "rules"


def test_an_old_matching_cache_is_used_and_refreshed(brief_env):
    rows = brief_rows()
    write_brief_cache(rows, age_s=3600)
    assert state.cached_brief(rows, NOW)["brief"].startswith("Cellar") and brief_env == [1]


def test_questions_the_model_did_not_rank_keep_rule_values_and_follow():
    rows = brief_rows()
    out = state.apply_model_brief(rows, model_reply(items=[{"id": "aaaa0001", "rank": 1, "unblocks": "x"}]))
    assert out[0]["id"] == "aaaa0001" and [a["rank"] for a in out] == [1, 2, 3]
    assert {a["id"]: a["unblocks"] for a in out[1:]} == {r["id"]: r["unblocks"] for r in rows if r["id"] != "aaaa0001"}


def test_model_brief_off_in_config_safe_mode_or_without_claude(monkeypatch):
    from teyla import config
    monkeypatch.setattr(state.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(config, "load", lambda path=None: dict(config.DEFAULTS))
    assert state.model_brief_enabled() is True
    for cfg in ({"state": {"model_brief": False}}, {"state": {"model_brief": "off"}}, {"safe": {"enabled": True}}):
        monkeypatch.setattr(config, "load", lambda path=None, cfg=cfg: {**config.DEFAULTS, **cfg})
        assert state.model_brief_enabled() is False
    monkeypatch.setattr(config, "load", lambda path=None: dict(config.DEFAULTS))
    monkeypatch.setattr(state.shutil, "which", lambda n: None)
    assert state.model_brief_enabled() is False


def test_validate_brief():
    ids = {"aaaa0001", "aaaa0002", "aaaa0003"}
    ok = state.validate_brief(model_reply(), ids)
    assert [i["id"] for i in ok["items"]] == ["aaaa0003", "aaaa0002", "aaaa0001"]
    long = state.validate_brief(model_reply(brief=" ".join(["word"] * 40)), ids)
    assert len(long["brief"].split()) <= 25 and long["brief"].endswith("…")
    clause = " ".join(["word"] * 12) + ", " + " ".join(["more"] * 20)
    assert state.validate_brief(model_reply(brief=clause), ids)["brief"] == " ".join(["word"] * 12) + "."
    wordy = model_reply(items=[{"id": "aaaa0001", "rank": 1, "unblocks": "one two three four five six seven"}])
    assert len(state.validate_brief(wordy, ids)["items"][0]["unblocks"].split()) <= 5
    one = {"id": "aaaa0001", "rank": 1, "unblocks": ""}
    for bad in (model_reply(items=[{"id": "zzzz9999", "rank": 1, "unblocks": ""}]),
                model_reply(items=[one, {"id": "aaaa0002", "rank": 1, "unblocks": ""}]),
                model_reply(items=[one, {"id": "aaaa0001", "rank": 2, "unblocks": ""}]),
                model_reply(items=[{"id": "aaaa0001", "rank": "1", "unblocks": ""}]),
                model_reply(items=[]), model_reply(brief="  "), "not a dict", None):
        assert state.validate_brief(bad, ids) is None


def test_the_claude_command_has_no_tools_and_takes_the_prompt_on_stdin(brief_env, monkeypatch):
    seen = []
    fake_claude(monkeypatch, 0, claude_stdout("```json\n" + json.dumps(model_reply()) + "\n```"), seen)
    rows = brief_rows()
    assert state.refresh_brief(NOW, rows=rows) == 0
    cmd, prompt = seen[0]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd
    assert not any("Ship to App Review" in a for a in cmd)          # session text is not on the command line
    assert {q["id"] for q in json.loads(prompt)["questions"]} == {"aaaa0001", "aaaa0002", "aaaa0003"}
    c = json.loads(state._brief_cache().read_text())
    assert c["ask_ids_hash"] == state.ask_ids_hash(rows) and c["brief"].startswith("Cellar")
    assert c["cost_usd"] == 0.0012 and c["latency_ms"] == 2100
    assert state._brief_cache().stat().st_mode & 0o777 == 0o600


def test_the_prompt_is_trimmed_capped_and_blocked_first():
    many = [ask(f"bbbb{n:04d}", question="q" * 900, context="c" * 900, hours=n + 1) for n in range(20)]
    many.append(ask("blocked1", "blocked", hours=500))
    cand = state.brief_candidates(state.ranked(many, NOW))
    assert len(cand) == 15 and cand[0]["id"] == "blocked1"
    assert all(len(c["question"]) <= 400 and len(c["context"]) <= 400 for c in cand)
    assert [c["id"] for c in cand[1:3]] == ["bbbb0000", "bbbb0001"]    # then the newest


@pytest.mark.parametrize("stdout", [
    claude_stdout("not json"), claude_stdout(model_reply(brief="")), claude_stdout("x", is_error=True), "garbage",
    claude_stdout(model_reply(items=[{"id": "zzzz9999", "rank": 1, "unblocks": ""}]))])
def test_a_bad_reply_keeps_the_previous_cache(brief_env, monkeypatch, stdout):
    rows = brief_rows()
    write_brief_cache(rows, age_s=7200)
    before = state._brief_cache().read_text()
    fake_claude(monkeypatch, 0, stdout)
    assert state.refresh_brief(NOW, rows=rows) == 1
    assert state._brief_cache().read_text() == before


def test_a_failing_claude_keeps_the_lock_as_a_back_off(brief_env, monkeypatch):
    state._brief_lock().write_text("")
    fake_claude(monkeypatch, 1, "")
    assert state.refresh_brief(NOW, rows=brief_rows()) == 1
    assert not state._brief_cache().exists() and state._brief_lock().exists()


def test_a_successful_refresh_releases_the_lock(brief_env, monkeypatch):
    state._brief_lock().write_text("")
    fake_claude(monkeypatch, 0, claude_stdout(model_reply()))
    assert state.refresh_brief(NOW, rows=brief_rows()) == 0 and not state._brief_lock().exists()


def test_the_lock_blocks_a_second_refresh_until_it_is_stale(monkeypatch):
    started = []
    monkeypatch.setattr(state.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    REAL_SPAWN(NOW)
    assert len(started) == 1 and started[0][-2:] == ["state", "--refresh-brief"] and state._brief_lock().exists()
    os.utime(state._brief_lock(), (NOW, NOW))
    REAL_SPAWN(NOW + 120)                                 # a refresh is running
    assert len(started) == 1
    REAL_SPAWN(NOW + 400)                                 # the lock is older than five minutes: stale
    assert len(started) == 2


def test_refresh_does_nothing_when_off_or_when_nothing_waits(monkeypatch):
    monkeypatch.setattr(state, "model_brief_enabled", lambda: False)
    assert state.refresh_brief(NOW, rows=brief_rows()) == 0 and not state._brief_cache().exists()
    monkeypatch.setattr(state, "model_brief_enabled", lambda: True)
    assert state.refresh_brief(NOW, rows=[]) == 0 and not state._brief_cache().exists()


# --- answer ------------------------------------------------------------------------------------

class Calls:
    def __init__(self, codes=None):
        self.calls, self.codes = [], list(codes or [])

    def __call__(self, cmd, cwd=None, input_text=None, timeout=30, detach=None):
        self.calls.append({"cmd": cmd, "cwd": cwd, "input": input_text, "detach": detach})
        return (self.codes.pop(0) if self.codes else 0), "out"


@pytest.fixture
def world(tmp_path, monkeypatch):
    class W:
        pass
    w = W()
    w.sessions = tmp_path / "sessions"
    w.codex = tmp_path / "codex"
    w.work = tmp_path / "work"
    w.work.mkdir()
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(w.sessions))
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(w.codex))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", "")
    w.calls = Calls()
    monkeypatch.setattr(answer, "run", w.calls)
    monkeypatch.setattr(answer, "confirm_delivery", lambda *a, **k: True)     # tests/test_answer_confirm.py covers it
    w.collect = lambda *a, **k: w.items
    monkeypatch.setattr(asks, "collect", w.collect)
    w.items = []
    return w


def claude_session(w, mode="bypassPermissions", worktree=None, cwd=None):
    p = w.sessions / "acct" / "work" / "local_x.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"sessionId": "local_x", "cliSessionId": CLAUDE_SID, "cwd": cwd or str(w.work),
            "originCwd": str(w.work), "permissionMode": mode, "lastActivityAt": 1, "createdAt": 1}
    if worktree:
        meta["worktreePath"] = worktree
    p.write_text(json.dumps(meta))


def test_claude_answer_resumes_in_the_background_in_the_session_directory(world):
    claude_session(world)
    a = ask("aaaa0001")
    r = answer.answer(a, "Keep 1.0", now=NOW)
    assert r == {"ok": True, "via": "claude-bg", "detail": "out", "id": "aaaa0001"}
    c = world.calls.calls[0]
    assert c["cmd"] == ["claude", "--bg", "--resume", CLAUDE_SID, "--permission-mode", "bypassPermissions", "Keep 1.0"]
    assert c["cwd"] == str(world.work)
    assert len(world.calls.calls) == 1


def test_claude_prefers_an_existing_worktree_and_skips_a_default_permission_mode(world, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    claude_session(world, mode="default", worktree=str(wt))
    answer.answer(ask(), "go", now=NOW)
    c = world.calls.calls[0]
    assert c["cwd"] == str(wt) and "--permission-mode" not in c["cmd"]
    world.calls.calls.clear()
    claude_session(world, worktree=str(tmp_path / "gone"))
    answer.answer(ask(), "go", now=NOW)
    assert world.calls.calls[0]["cwd"] == str(world.work)


def test_an_answer_starting_with_a_dash_is_passed_after_a_double_dash(world):
    claude_session(world)
    answer.answer(ask(), "-1 for that", now=NOW)
    assert world.calls.calls[0]["cmd"][-2:] == ["--", "-1 for that"]


def test_codex_answer_resumes_headless_in_the_session_cwd(world):
    d = world.codex / "2026" / "10" / "16"
    d.mkdir(parents=True)
    (d / f"rollout-2026-10-16T10-00-00-{CODEX_SID}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": CODEX_SID, "cwd": str(world.work)}}) + "\n")
    a = ask("aaaa0002", harness="codex", session=CODEX_SID, link=f"codex resume {CODEX_SID}")
    r = answer.answer(a, "yes do it", now=NOW)
    assert (r["ok"], r["via"]) == (True, "codex-resume")
    c = world.calls.calls[0]
    assert c["cmd"] == ["codex", "exec", "resume", CODEX_SID, "yes do it"]
    assert c["cwd"] == str(world.work) and c["detach"]
    assert len(world.calls.calls) == 1


def test_codex_falls_back_to_queue_which_says_it_waits(world):
    world.calls.codes = [1, 0]
    a = ask("aaaa0002", harness="codex", session=CODEX_SID, link=f"codex resume {CODEX_SID}")
    r = answer.answer(a, "yes", now=NOW)
    assert r["ok"] and r["via"] == "codex-queue" and r["detail"] == "waits until the session is opened"
    assert world.calls.calls[1]["cmd"] == ["codex", "queue", "--thread", CODEX_SID, "--message=yes"]


def test_falls_back_to_clipboard_and_open_when_the_session_commands_fail(world):
    claude_session(world)
    world.calls.codes = [1, 0, 0]
    r = answer.answer(ask("aaaa0001"), "text", now=NOW)
    assert (r["ok"], r["via"]) == (True, "opened")
    cmds = [c["cmd"] for c in world.calls.calls]
    assert cmds[1] == ["pbcopy"] and world.calls.calls[1]["input"] == "text"
    assert cmds[2] == ["open", "claude://claude.ai/epitaxy/local_x"]


def test_failure_reports_every_attempt_and_marks_nothing(world):
    claude_session(world)
    world.calls.codes = [1, 1]
    r = answer.answer(ask("aaaa0001"), "text", now=NOW)
    assert not r["ok"] and "claude-bg" in r["detail"]
    assert "aaaa0001" not in asks.load_state()["done"]


def test_an_item_with_no_session_and_no_link_is_not_deliverable(world):
    a = ask("aaaa0003", "reminder", harness="teyla", session="", link="teyla remind list")
    r = answer.answer(a, "ok", now=NOW)
    assert not r["ok"] and world.calls.calls == []


def test_success_marks_the_ask_done_with_a_note(world):
    claude_session(world)
    answer.answer(ask("aaaa0001"), "Keep 1.0", now=NOW)
    done = asks.load_state()["done"]["aaaa0001"]
    assert done["note"] == "answered in Teyla via claude-bg"


def test_dry_runs_and_marks_nothing(world):
    claude_session(world)
    r = answer.answer(ask("aaaa0001"), "Keep 1.0", dry=True, now=NOW)
    assert r["ok"] and r["via"] == "claude-bg" and r["detail"].startswith("would run: ")
    assert "claude --bg --resume" in r["detail"] and world.calls.calls == []
    assert "aaaa0001" not in asks.load_state()["done"]


def test_answer_command_resolves_a_prefix_and_prints_json(world, capsys):
    claude_session(world)
    world.items = [ask("aaaa0001"), ask("bbbb0002")]
    assert cli.main(["answer", "aaaa", "Keep", "1.0", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "via": "claude-bg", "detail": "out", "id": "aaaa0001"}
    assert world.calls.calls[0]["cmd"][-1] == "Keep 1.0"
    assert asks.load_state()["done"]["aaaa0001"]["note"].endswith("claude-bg")


def test_answer_command_errors(world, capsys):
    world.items = [ask("aaaa0001"), ask("aaaa0002")]
    assert cli.main(["answer", "aaaa", "text"]) == 1          # ambiguous
    assert cli.main(["answer", "zzzz", "text", "--json"]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ok"] is False
    assert cli.main(["answer", "aaaa0001"]) == 64
    assert world.calls.calls == []


def test_run_reports_missing_programs_and_timeouts(monkeypatch):
    import subprocess
    assert answer.run(["teyla-no-such-program-xyz"])[0] == 127

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert answer.run(["x"], timeout=1)[0] == 124


def test_the_answer_log_is_owner_only(tmp_path):
    from teyla import answer
    log = tmp_path / "answer.log"
    log.write_text("")
    log.chmod(0o644)
    code, _ = answer.run(["/bin/sh", "-c", "echo hi"], detach=str(log))
    assert code == 0 and oct(log.stat().st_mode & 0o777) == "0o600"


# --- version 2: done, tasks, products, relay ---------------------------------------------------

def backlog_data(prs=(), issues=(), counts=None, canonical=None):
    return {"at": NOW, "prs": list(prs), "issues": list(issues), "counts": counts or {}, "canonical": canonical or {}}


def pr_row(repo, number, head, title="Add the export", hours=24, draft=False):
    return {"repo": repo, "number": number, "title": title, "url": f"https://github.com/{repo}/pull/{number}",
            "created": NOW - hours * 3600, "head": head, "draft": draft}


def issue_row(repo, number, title="Create the record", hours=2, labels=()):
    return {"repo": repo, "number": number, "title": title, "url": f"https://github.com/{repo}/issues/{number}",
            "created": NOW - hours * 3600, "labels": list(labels)}


@pytest.mark.parametrize("summary,status", [
    ({"status_category": "completed", "status_detail": "x"}, "done"),
    ({"status_category": "review_ready", "status_detail": "x"}, "review_ready"),
    ({"status_category": "failed", "status_detail": "x"}, "failed"),
    ({"status_category": "error", "status_detail": "x"}, "failed"),
    ({"status_category": "blocked", "status_detail": "x"}, "blocked"),
    ({"status_category": "blocked", "status_detail": "x", "needs_action": "Sign in"}, "needs_you"),
    ({"status_category": "completed", "status_detail": "x", "needs_action": "Add a tester"}, "needs_you"),
    ({"status_category": "something new", "status_detail": "x"}, "done"),
])
def test_summary_status_mapping(summary, status):
    assert state.card_from_summary(summary)["status"] == status


def test_summary_detail_becomes_at_most_three_result_lines_and_needs_is_kept():
    card = state.card_from_summary({"status_category": "completed", "needs_action": "Add a tester email",
                                    "status_detail": "Android 1.0 (4) uploaded; internal track live;\n"
                                                     "review ready; one more; and another"})
    assert card["result"] == ["Android 1.0 (4) uploaded", "internal track live", "review ready"]
    assert card["needs"] == "Add a tester email"


CARD = """Done — atlas
Result:
- PDF export, one page per day ([PR 301](https://github.com/example/atlas/pull/301))
- **Merged** at 18:10
- A third line
- A fourth line
Needs you: none
Not verified: the iPad layout
"""


def test_parse_card_reads_status_result_bullets_and_needs():
    c = state.parse_card(CARD)
    assert c["status"] == "done"
    assert c["result"] == ["PDF export, one page per day (PR 301)", "Merged at 18:10", "A third line"]
    assert c["needs"] == ""


@pytest.mark.parametrize("head,status", [("Blocked — cellar", "blocked"), ("Failed — cellar", "failed"),
                                         ("Needs you — cellar", "needs_you"), ("**Done — cellar**", "done"),
                                         ("## done - cellar", "done")])
def test_parse_card_heads(head, status):
    assert state.parse_card(f"{head}\nResult: it ran")["status"] == status


def test_a_needs_line_makes_the_card_needs_you_and_inline_result_works():
    c = state.parse_card("Done — cellar\nResult: Build 4 uploaded\nNeeds you: Add a tester email in the Play Console")
    assert (c["status"], c["result"], c["needs"]) == ("needs_you", ["Build 4 uploaded"],
                                                      "Add a tester email in the Play Console")


def test_text_that_is_not_a_card_falls_back_to_its_first_line_cut_to_120_characters():
    assert state.parse_card("Donewith it — and then some") is None
    c = state.card_from_text("\n## " + "word " * 40 + "\nsecond line")
    assert c["status"] == "done" and len(c["result"][0]) <= 120 and c["result"][0].endswith("…") and c["needs"] == ""
    assert state.card_from_text("   \n") is None


def test_links_are_the_first_three_github_pr_or_issue_urls():
    t = ("https://github.com/a/b/pull/1 and https://github.com/a/b/issues/2 https://github.com/a/b/pull/1 "
         "https://github.com/a/b/tree/main https://github.com/c/d/pull/3 https://github.com/e/f/pull/4")
    assert state.links_in(t) == ["https://github.com/a/b/pull/1", "https://github.com/a/b/issues/2",
                                 "https://github.com/c/d/pull/3"]
    assert state.links_in("none", extra=["https://github.com/x/y/pull/9", "https://example.com"]) == [
        "https://github.com/x/y/pull/9"]


def test_done_comes_from_the_desktop_summary_newest_first_within_24_hours(tmp_path):
    root = tmp_path / "sessions"
    s = {"status_category": "completed", "status_detail": "Exported the PDF; merged PR 301",
         "needs_action": ""}
    desktop_file(root, "local_aaaa1111-0000-0000-0000-00000000000a", minutes_ago=60, title="Old export", summary=s,
                 prs=["https://github.com/example/atlas/pull/301"])
    desktop_file(root, "local_aaaa1111-0000-0000-0000-00000000000b", minutes_ago=30, cwd="/Users/someone/repos/cellar",
                 title="Android build", summary={"status_category": "blocked", "status_detail": "stuck",
                                                 "needs_action": "Sign in to Play"})
    desktop_file(root, "local_aaaa1111-0000-0000-0000-00000000000c", minutes_ago=25 * 60, summary=s)       # too old
    desktop_file(root, "local_aaaa1111-0000-0000-0000-00000000000d", minutes_ago=60, summary=s, archived=True)
    rows = state.done_feed(NOW, str(root), "/nonexistent", "/nonexistent", runs=[])
    assert [r["title"] for r in rows] == ["Android build", "Old export"]
    b, a = rows
    assert (b["status"], b["needs"], b["product"], b["harness"]) == ("needs_you", "Sign in to Play", "cellar", "claude-desktop")
    assert b["id"] == "local_aaaa1111-0000-0000-0000-00000000000b" and b["link"].endswith(b["id"])
    assert a["result"] == ["Exported the PDF", "merged PR 301"] and a["links"] == ["https://github.com/example/atlas/pull/301"]
    assert a["ended"] == asks._iso(NOW - 3600)


def test_a_session_without_a_summary_is_read_from_its_transcript_card(tmp_path):
    root, projects = tmp_path / "sessions", tmp_path / "projects"
    sid = "local_aaaa1111-0000-0000-0000-00000000000e"
    desktop_file(root, sid, minutes_ago=45, cwd="/Users/someone/repos/atlas")
    tdir = projects / "-Users-someone-repos-atlas"
    tdir.mkdir(parents=True)

    def rec(kind, content, **kw):
        return json.dumps({"type": kind, "timestamp": "2026-10-16T11:15:00Z", "message": {"content": content}, **kw})
    lines = [rec("user", "go"),
             rec("assistant", [{"type": "text", "text": "Done — atlas\nResult:\n- Shipped the PDF\nNeeds you: none"}])]
    (tdir / f"{sid[6:]}.jsonl").write_text("\n".join(lines) + "\n")
    rows = state.done_feed(NOW, str(root), "/nonexistent", str(projects), runs=[])
    assert [(r["status"], r["result"]) for r in rows] == [("done", ["Shipped the PDF"])]
    # a transcript that ends in a tool call or a prompt is mid-turn: not done
    lines.append(rec("assistant", [{"type": "tool_use", "name": "Bash", "input": {}}]))
    (tdir / f"{sid[6:]}.jsonl").write_text("\n".join(lines) + "\n")
    assert state.done_feed(NOW, str(root), "/nonexistent", str(projects), runs=[]) == []


def test_done_skips_review_lanes_and_sessions_still_running(tmp_path):
    root = tmp_path / "sessions"
    s = {"status_category": "completed", "status_detail": "ok"}
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000011", minutes_ago=60, summary=s,
                 title="You are reviewing a diff")
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000012", minutes_ago=60, summary=s, title="Real work")
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000013", minutes_ago=2, summary=s, title="Busy now")
    run = state.running_desktop(NOW, str(root), runs=[])
    rows = state.done_feed(NOW, str(root), "/nonexistent", "/nonexistent", runs=[], skip_ids={r["id"] for r in run})
    assert [r["title"] for r in rows] == ["Real work"]


def test_done_codex_reads_the_card_of_the_last_finished_interactive_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    root = tmp_path / "codex"
    msg = ("Needs you — cellar\nResult:\n- Build 1.0 (4) uploaded\nNeeds you: Add a tester\n"
           "See https://github.com/example/cellar/pull/7")
    rollout(root, "11111111-0000-0000-0000-000000000021", minutes_ago=120, message=msg)
    rollout(root, "11111111-0000-0000-0000-000000000022", minutes_ago=120, message="Done", source="exec",
            originator="codex_exec")
    rollout(root, "11111111-0000-0000-0000-000000000023", minutes_ago=120, unfinished=True)
    rollout(root, "11111111-0000-0000-0000-000000000024", minutes_ago=26 * 60, message="Done — old")
    rows = state.done_feed(NOW, "/nonexistent", str(root), "/nonexistent", runs=[])
    assert len(rows) == 1
    r = rows[0]
    assert (r["status"], r["product"], r["harness"], r["needs"]) == ("needs_you", "cellar", "codex", "Add a tester")
    assert r["result"] == ["Build 1.0 (4) uploaded"] and r["links"] == ["https://github.com/example/cellar/pull/7"]
    assert r["id"] == "11111111-0000-0000-0000-000000000021" and r["link"] == "codex://threads/" + r["id"]


def test_a_resumed_old_codex_session_is_running_because_the_file_time_decides(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    root = tmp_path / "codex"
    rollout(root, "11111111-0000-0000-0000-000000000031", minutes_ago=2, day="2026/08/01")
    rows = state.running_codex(NOW, str(root), runs=[])
    assert [r["id"] for r in rows] == ["11111111-0000-0000-0000-000000000031"]
    assert rows[0]["correct"] == "codex-queue"


def test_running_rows_carry_an_id_and_how_a_correction_reaches_them(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    desktop_file(tmp_path / "s", "local_aaaa1111-0000-0000-0000-000000000041", minutes_ago=1)
    rollout(tmp_path / "c", "11111111-0000-0000-0000-000000000042", minutes_ago=1)
    rows = state.running(NOW, str(tmp_path / "s"), str(tmp_path / "c"), runs=[])
    assert {(r["harness"], r["id"], r["correct"]) for r in rows} == {
        ("claude-desktop", "local_aaaa1111-0000-0000-0000-000000000041", "open"),
        ("codex", "11111111-0000-0000-0000-000000000042", "codex-queue")}


def write_dispatch(*worktrees, harness="codex"):
    state.dispatch_path().write_text("".join(json.dumps({"id": f"d{n}", "product": "atlas", "harness": harness,
                                                         "worktree": w, "branch": "b", "started": "x", "pid": 1,
                                                         "log": "l"}) + "\n" for n, w in enumerate(worktrees)))


def test_dispatched_worktrees_are_the_exception_to_the_headless_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "no-index.jsonl"))
    wt = tmp_path / "wt" / "atlas" / "feature"
    other = tmp_path / "wt" / "atlas" / "other"
    write_dispatch(str(wt))
    cx = tmp_path / "codex"
    rollout(cx, "11111111-0000-0000-0000-000000000051", minutes_ago=1, cwd=str(wt / "sub"), source="exec",
            originator="codex_exec")
    rollout(cx, "11111111-0000-0000-0000-000000000052", minutes_ago=1, cwd=str(other), source="exec",
            originator="codex_exec")
    rollout(cx, "11111111-0000-0000-0000-000000000053", minutes_ago=90, cwd=str(wt), source="exec",
            originator="codex_exec", message="Done — atlas\nResult: Ran it")
    desktop = tmp_path / "sessions"
    s = {"status_category": "completed", "status_detail": "ok"}
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000054", minutes_ago=1, cwd=str(wt),
                 title="You are reviewing the branch")
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000055", minutes_ago=1, cwd=str(other),
                 title="You are reviewing another branch")
    desktop_file(desktop, "local_aaaa1111-0000-0000-0000-000000000056", minutes_ago=90, cwd=str(wt),
                 title="You are reviewing and done", summary=s)
    run = state.running(NOW, str(desktop), str(cx))
    assert {r["id"] for r in run} == {"11111111-0000-0000-0000-000000000051", "local_aaaa1111-0000-0000-0000-000000000054"}
    assert {r["correct"] for r in run if r["harness"] == "codex"} == {"open"}      # nobody to queue for in a headless run
    done = state.done_feed(NOW, str(desktop), str(cx), "/nonexistent")
    assert {d["id"] for d in done} == {"11111111-0000-0000-0000-000000000053", "local_aaaa1111-0000-0000-0000-000000000056"}


def test_a_dispatched_claude_run_is_found_by_the_transcript_folder_of_its_worktree(tmp_path):
    wt = tmp_path / "wt" / "atlas" / "fix"
    wt.mkdir(parents=True)
    write_dispatch(str(wt), harness="claude")
    projects = tmp_path / "projects"
    tdir = projects / str(wt.resolve()).replace("/", "-").replace(".", "-")
    tdir.mkdir(parents=True)
    t = NOW - 3600
    recs = [{"type": "user", "timestamp": "2026-10-16T10:50:00Z", "message": {"content": "Fix the export bug"}},
            {"type": "assistant", "timestamp": "2026-10-16T11:00:00Z", "message": {
                "model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Done — atlas\nResult: Fixed it"}]}}]
    f = tdir / "abc-123.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in recs))
    os.utime(f, (t, t))
    done = state.done_feed(NOW, "/nonexistent", "/nonexistent", str(projects))
    assert [(d["id"], d["title"], d["result"], d["harness"]) for d in done] == [
        ("abc-123", "Fix the export bug", ["Fixed it"], "claude-code")]
    os.utime(f, (NOW - 60, NOW - 60))
    run = state.running(NOW, "/nonexistent", "/nonexistent", projects=str(projects))
    assert [(r["id"], r["model"], r["correct"]) for r in run] == [("abc-123", "claude-sonnet-5-5", "open")]


# --- tasks -------------------------------------------------------------------------------------

LEDGER = "\n".join([
    "2026-10-16T10:00:00Z\tlens\t" + "a" * 40 + "\tbranch\t0\t2\tcodex:gpt-6.1-sol",
    "2026-10-16T10:00:00Z\tcellar\t" + "b" * 40 + "\tbranch\t1\t0\tcodex:gpt-6.1-sol",
    "2026-10-16T10:30:00Z\tcellar\t" + "b" * 40 + "\tcommit\t0\t0\tcodex:gpt-6.1-sol",
    "2026-10-16T10:40:00Z\tatlas\t" + "c" * 40 + "\tbranch\t2\t0\tcodex:gpt-6.1-sol",
    "2026-10-16T11:00:00Z\thttps://github.com/example/forge/pull/9\t" + "d" * 40 + "\tskip:docs only\t-\t-\treview-gate",
])


def test_merge_tasks_say_what_the_ledger_knows_and_skip_approved_repos_and_drafts():
    ledger = reviews.parse_ledger(LEDGER)
    prs = [pr_row("example/lens", 14, "a" * 40, hours=48),
           pr_row("example/atlas", 3, "c" * 40, hours=30),
           pr_row("example/cellar", 5, "b" * 40, hours=26),
           pr_row("example/forge", 9, "e" * 40, hours=20),
           pr_row("example/forge", 10, "f" * 40, hours=10),
           pr_row("example/draft", 1, "1" * 40, draft=True),
           pr_row("Example/Approved", 2, "2" * 40)]
    out = state.tasks_view(backlog_data(prs=prs), {"example/approved"}, ledger, NOW)
    assert [t["id"] for t in out] == ["pr:example/lens#14", "pr:example/atlas#3", "pr:example/cellar#5",
                                      "pr:example/forge#9", "pr:example/forge#10"]
    by = {t["id"]: t for t in out}
    assert by["pr:example/lens#14"]["detail"].startswith("Reviewed, no open P1.")
    assert by["pr:example/atlas#3"]["detail"].startswith("Reviewed with 2 open P1.")
    assert by["pr:example/cellar#5"]["detail"].startswith("Reviewed, no open P1.")     # the fix round has no P1
    assert by["pr:example/forge#9"]["detail"].startswith("Review skipped: docs only.")
    assert by["pr:example/forge#10"]["detail"].startswith("No review of the head commit in the ledger.")
    assert all("not merge-approved" in t["detail"] for t in out)
    t = by["pr:example/lens#14"]
    assert (t["kind"], t["product"], t["title"], t["age_s"]) == ("merge", "lens", "Merge: Add the export", 48 * 3600)
    assert t["link"] == "https://github.com/example/lens/pull/14"


def test_issue_tasks_list_the_labels_and_all_tasks_are_oldest_first():
    bl = backlog_data(prs=[pr_row("example/lens", 14, "a" * 40, hours=5)],
                      issues=[issue_row("example/cellar", 88, hours=2, labels=["bug", "p1"]),
                              issue_row("example/atlas", 7, hours=90)])
    out = state.tasks_view(bl, set(), None, NOW)
    assert [t["id"] for t in out] == ["issue:example/atlas#7", "pr:example/lens#14", "issue:example/cellar#88"]
    assert out[2]["kind"] == "task" and out[2]["detail"] == "Assigned to you. Labels: bug, p1."
    assert out[0]["detail"] == "Assigned to you."


def test_build_reads_the_approved_list_and_the_ledger_when_a_pr_needs_them(tmp_path, monkeypatch):
    md = tmp_path / "CLAUDE.md"
    md.write_text("```\nMERGE-APPROVED REPOS\n  example/lens   # x\n```\n")
    monkeypatch.setattr(backlog, "claude_md_path", lambda: md)
    ledger = tmp_path / "ledger.tsv"
    ledger.write_text(LEDGER)
    monkeypatch.setattr(reviews, "ledger_path", lambda cfg=None: ledger)
    bl = backlog_data(prs=[pr_row("example/lens", 14, "a" * 40), pr_row("example/atlas", 3, "c" * 40)])
    st = state.build(NOW, items=[], repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent",
                     backlog_data=bl, runs=[])
    assert [t["id"] for t in st["tasks"]] == ["pr:example/atlas#3"]
    assert "open P1" in st["tasks"][0]["detail"]


# --- products ----------------------------------------------------------------------------------

def make_repo(tmp_path, name, remote, days_ago=1):
    p = tmp_path / "repos" / name
    (p / ".git" / "logs").mkdir(parents=True)
    cfg = '[core]\n\tbare = false\n'
    if remote:
        cfg += f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
    (p / ".git" / "config").write_text(cfg)
    h = p / ".git" / "logs" / "HEAD"
    h.write_text("x")
    t = NOW - days_ago * 86400
    os.utime(h, (t, t))
    return p


def test_two_clones_of_one_github_repo_are_one_product_named_after_the_github_repo(tmp_path):
    a = make_repo(tmp_path, "oldname", "https://github.com/example/newname.git")
    b = make_repo(tmp_path, "newname", "git@github.com:example/newname.git")
    c = make_repo(tmp_path, "renamed", "https://github.com/example/renamed-before.git")
    d = make_repo(tmp_path, "plain", "")
    repos = {"oldname": a, "newname": b, "renamed": c, "plain": d}
    alias, info = state.product_names(repos, {"example/renamed-before": "example/renamed-now"})
    assert alias == {"oldname": "newname", "newname": "newname", "renamed": "renamed-now", "plain": "plain"}
    assert info["newname"]["path"] == b and info["newname"]["slug"] == "example/newname"
    assert info["plain"]["slug"] == ""


def test_the_snapshot_merges_products_and_adds_issues_prs_next_and_repo(tmp_path):
    root = tmp_path / "sessions"
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000061", minutes_ago=60, cwd="/Users/someone/repos/oldname",
                 title="Export", summary={"status_category": "completed", "status_detail": "Shipped",
                                          "needs_action": "Add a tester"})
    desktop_file(root, "local_aaaa1111-0000-0000-0000-000000000062", minutes_ago=1, cwd="/Users/someone/repos/newname")
    repos = {"oldname": make_repo(tmp_path, "oldname", "https://github.com/example/newname.git"),
             "newname": make_repo(tmp_path, "newname", "https://github.com/example/newname.git"),
             "lens": make_repo(tmp_path, "lens", "https://github.com/example/lens", days_ago=90)}
    bl = backlog_data(prs=[pr_row("example/lens", 14, "a" * 40)], counts={"example/newname": 12, "example/lens": 1})
    st = state.build(NOW, items=[ask("aaaa0001", product="oldname")], repos=repos, spent=None, desktop=str(root),
                     codex_root="/nonexistent", backlog_data=bl, approved=set(), ledger=None, runs=[])
    by = {p["name"]: p for p in st["products"]}
    assert sorted(by) == ["lens", "newname"]
    n = by["newname"]
    assert (n["issues"], n["waiting"], n["prs_waiting"], n["state"]) == (12, 1, 0, "waiting")
    assert n["next"] == "Add a tester" and n["repo"].endswith("repos/newname")
    assert st["asks"][0]["product"] == "newname" and st["done"][0]["product"] == "newname"
    lens = by["lens"]                      # 90 days idle, but a PR waits on the owner
    assert (lens["issues"], lens["prs_waiting"], lens["next"]) == (1, 1, "")
    assert st["tasks"][0]["product"] == "lens"


def test_repo_paths_under_the_home_folder_are_written_with_a_tilde():
    home = str(pathlib.Path.home())
    assert state.home_path(pathlib.Path(home) / "repos" / "atlas") == "~/repos/atlas"
    assert state.home_path("/srv/atlas") == "/srv/atlas"


# --- relay, text, commands ---------------------------------------------------------------------

def test_relay_comes_from_relay_json_and_the_key_file():
    assert state.relay_view() == {"on": False, "paired": False, "folder": "", "synced": ""}
    home = state.control.home()
    (home / "relay.json").write_text(json.dumps({"on": True, "folder": "/x/Teyla", "synced": "2026-10-16T11:00:00Z"}))
    (home / "relay.key").write_bytes(b"k" * 32)
    assert state.relay_view() == {"on": True, "paired": True, "folder": "/x/Teyla", "synced": "2026-10-16T11:00:00Z"}
    (home / "relay.json").write_text("not json")
    assert state.relay_view()["on"] is False
    (home / "relay.json").write_text(json.dumps({"on": "yes", "folder": 3}))
    assert state.relay_view() == {"on": False, "paired": True, "folder": "3", "synced": ""}


def test_text_mode_has_short_done_and_tasks_sections_within_15_lines(tmp_path):
    root = tmp_path / "sessions"
    for n in range(4):
        desktop_file(root, f"local_aaaa1111-0000-0000-0000-00000000007{n}", minutes_ago=60 + n, title=f"Work {n}",
                     summary={"status_category": "completed", "status_detail": f"Result {n}"})
    bl = backlog_data(prs=[pr_row("example/lens", n, "a" * 40) for n in range(1, 4)])
    st = state.build(NOW, items=[ask(f"aaaa000{n}", question="Which font?") for n in range(6)], repos={}, spent=1.0,
                     desktop=str(root), codex_root="/nonexistent", backlog_data=bl, approved=set(), ledger=None,
                     runs=[])
    out = state.render_text(st, NOW)
    lines = out.splitlines()
    assert len(lines) <= 15
    assert "Tasks" in lines and "Done" in lines
    assert "6 waiting, 3 tasks, 4 done, 0 running, $1.00 today" in lines[1]
    assert any("[done]: Result 0" in ln for ln in lines) and any("lens: Merge: Add the export" in ln for ln in lines)
    assert "  + 2 more" in lines and "  + 1 more" in lines


def test_the_state_command_runs_the_backlog_refresh_when_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(state, "refresh_backlog", lambda *a, **k: seen.append(1) or 0)
    assert cli.main(["state", "--refresh-backlog"]) == 0 and seen == [1]
    monkeypatch.setattr(state, "refresh_backlog", lambda *a, **k: 1 / 0)
    assert cli.main(["state", "--refresh-backlog"]) == 1


def test_active_repos_are_the_ones_that_moved_in_30_days_and_have_a_github_remote(tmp_path):
    repos = {"new": make_repo(tmp_path, "new", "https://github.com/example/new", days_ago=2),
             "old": make_repo(tmp_path, "old", "https://github.com/example/old", days_ago=40),
             "local": make_repo(tmp_path, "local", "", days_ago=1)}
    assert state.active_slugs(repos, NOW) == ["example/new"]


def test_the_snapshot_reads_the_cache_and_never_calls_gh(monkeypatch):
    def boom(argv):
        raise AssertionError("the foreground ran " + " ".join(argv))
    monkeypatch.setattr(backlog, "default_runner", boom)
    monkeypatch.setattr(state.shutil, "which", lambda n: "/bin/" + n)
    asks._atomic_write(backlog.cache_path(), json.dumps({"version": 1, "at": NOW, "prs": [], "issues": [],
                                                         "counts": {"example/atlas": 3}, "canonical": {}}))
    spawned = []
    monkeypatch.setattr(backlog, "spawn_refresh", lambda *a, **k: spawned.append(1))
    st = state.build(NOW, items=[], repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent", runs=[])
    assert st["tasks"] == [] and spawned == []                  # fresh: no refresh either
    asks._atomic_write(backlog.cache_path(), json.dumps({"version": 1, "at": NOW - 4000}))
    state.build(NOW, items=[], repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent", runs=[])
    assert spawned == [1]


def test_no_gh_or_safe_mode_means_empty_lists_and_no_refresh(monkeypatch):
    spawned = []
    monkeypatch.setattr(backlog, "spawn_refresh", lambda *a, **k: spawned.append(1))
    monkeypatch.setattr(state.shutil, "which", lambda n: None)
    st = state.build(NOW, items=[], repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent", runs=[])
    assert (st["tasks"], st["done"], spawned) == ([], [], [])
    monkeypatch.setattr(state.shutil, "which", lambda n: "/bin/gh")
    monkeypatch.setenv("TEYLA_SAFE", "1")
    state.build(NOW, items=[], repos={}, spent=None, desktop="/nonexistent", codex_root="/nonexistent", runs=[])
    assert spawned == []


def test_two_owners_with_one_repo_name_are_two_products(tmp_path):
    a = make_repo(tmp_path, "app-a", "https://github.com/alice/app.git")
    b = make_repo(tmp_path, "app-b", "https://github.com/bob/app.git")
    c = make_repo(tmp_path, "app-c", "https://github.com/Alice/App.git")
    alias, info = state.product_names({"app-a": a, "app-b": b, "app-c": c}, {})
    assert alias == {"app-a": "alice/app", "app-b": "bob/app", "app-c": "alice/app"}
    assert sorted(info) == ["alice/app", "bob/app"]
    assert info["alice/app"]["paths"] == [a, c] and info["bob/app"]["paths"] == [b]


def test_a_product_with_two_clones_takes_the_newest_activity_and_any_tag(tmp_path):
    old = make_repo(tmp_path, "old", "https://github.com/example/lens.git", days_ago=40)
    new = make_repo(tmp_path, "new", "https://github.com/example/lens.git", days_ago=1)
    alias, info = state.product_names({"old": old, "new": new}, {})
    assert sorted(info["lens"]["paths"]) == sorted([new, old])
    by = {p["name"]: p for p in state.products_view([], [], {k: v["paths"] for k, v in info.items()}, NOW)}
    assert by["lens"]["state"] == "active"                 # the clone touched yesterday, not the 40-day one


def test_a_stale_desktop_summary_is_replaced_by_the_sessions_last_message(tmp_path):
    root, projects = tmp_path / "sessions", tmp_path / "projects"
    sid = "local_aaaa1111-0000-0000-0000-0000000000f1"
    stale = {"status_category": "blocked", "status_detail": "waiting for the key", "needs_action": "Add the key",
             "summarizes_uuid": "turn-1"}
    desktop_file(root, sid, minutes_ago=45, cwd="/Users/someone/repos/atlas", summary=stale)
    tdir = projects / "-Users-someone-repos-atlas"
    tdir.mkdir(parents=True)

    def rec(kind, content, uuid):
        return json.dumps({"type": kind, "uuid": uuid, "timestamp": "2026-10-16T11:15:00Z", "message": {"content": content}})
    card = "Done — atlas\nResult:\n- Shipped the PDF\nNeeds you: none"
    lines = [rec("assistant", [{"type": "text", "text": "Blocked"}], "turn-1"), rec("user", "key is in", "u2"),
             rec("assistant", [{"type": "text", "text": card}], "turn-2")]
    (tdir / f"{sid[6:]}.jsonl").write_text("\n".join(lines) + "\n")
    rows = state.done_feed(NOW, str(root), "/nonexistent", str(projects), runs=[])
    assert [(r["status"], r["result"], r["needs"]) for r in rows] == [("done", ["Shipped the PDF"], "")]
    # the same summary, still describing the last turn, stands
    (tdir / f"{sid[6:]}.jsonl").write_text("\n".join(lines[:1]) + "\n")
    rows = state.done_feed(NOW, str(root), "/nonexistent", str(projects), runs=[])
    assert [(r["status"], r["needs"]) for r in rows] == [("needs_you", "Add the key")]


def test_tasks_of_a_repo_whose_name_two_owners_share_carry_the_owner_qualified_product(tmp_path):
    a = make_repo(tmp_path, "app-a", "https://github.com/alice/app.git", days_ago=60)
    b = make_repo(tmp_path, "app-b", "https://github.com/bob/app.git", days_ago=60)
    bl = backlog_data(prs=[pr_row("alice/app", 3, "a" * 40)], counts={"alice/app": 4})
    st = state.build(NOW, items=[], repos={"app-a": a, "app-b": b}, spent=None, desktop="/nonexistent",
                     codex_root="/nonexistent", backlog_data=bl, approved=set(), ledger=None, runs=[])
    assert st["tasks"][0]["product"] == "alice/app"
    by = {p["name"]: p for p in st["products"]}
    assert sorted(by) == ["alice/app"]                 # 60 days idle, kept because a PR waits on the owner
    assert (by["alice/app"]["prs_waiting"], by["alice/app"]["issues"]) == (1, 4)
