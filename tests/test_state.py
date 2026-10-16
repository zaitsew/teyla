"""`teyla state` and `teyla answer`: synthetic items and session stores in tmp dirs. No test starts a
real `claude` or `codex`: `answer.run` is replaced."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pytest

from teyla import answer, asks, cli, state
from teyla.adapters import codex

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
                 title=None):
    p = root / "acct" / "work" / f"{sid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"sessionId": sid, "cliSessionId": sid[6:], "cwd": cwd, "isArchived": archived,
                             "title": title or f"Title of {sid}", "model": "claude-sonnet-5-5",
                             "createdAt": int((NOW - 7200) * 1000),
                             "lastActivityAt": int((NOW - minutes_ago * 60) * 1000)}))
    return p


def rollout(root: pathlib.Path, sid: str, *, minutes_ago: float, cwd="/Users/someone/.worktrees/cellar/feat", source="vscode",
            originator="Codex Desktop"):
    d = root / "2026" / "10" / "16"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"rollout-2026-10-16T10-00-00-{sid}.jsonl"
    recs = [{"type": "session_meta", "timestamp": "2026-10-16T10:00:00.000Z",
             "payload": {"id": sid, "session_id": sid, "cwd": cwd, "source": source,
                         "originator": originator}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}]
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
    fixture = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state.json").read_text())
    assert set(st) == set(fixture)
    assert set(st["totals"]) == set(fixture["totals"])
    assert set(st["asks"][0]) == set(fixture["asks"][0])
    assert set(st["products"][0]) == set(fixture["products"][0])
    assert st["totals"] == {"questions": 1, "running": 0, "spent_today_usd": 4.1}
    assert st["version"] == 1 and st["generated"] == asks._iso(NOW)


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
    assert world.calls.calls[1]["cmd"] == ["codex", "queue", "--thread", CODEX_SID, "--message", "yes"]


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
