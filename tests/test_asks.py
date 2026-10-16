"""`teyla asks`: synthetic desktop sessions, Claude Code transcripts, Codex rollouts, gated runs and
reminders. Nothing here reads the real machine: every root is a tmp dir (see conftest)."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import time

import pytest

from teyla import asks, cli, config, doctor, remind, routine_install
from teyla.control import state

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()
HOME = "/Users/someone"          # a placeholder user, as the leak check allows


def ts(days_ago: float = 0.0, minutes: float = 0.0) -> str:
    when = NOW - days_ago * 86400 + minutes * 60
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ms(days_ago: float = 0.0) -> int:
    return int((NOW - days_ago * 86400) * 1000)


# --- builders --------------------------------------------------------------------------------

def write_jsonl(path: pathlib.Path, recs) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return path


def u(uuid, text, days_ago=1.0, **kw):
    return {"type": "user", "uuid": uuid, "timestamp": ts(days_ago), "cwd": kw.pop("cwd", f"{HOME}/repos/app"),
            "message": {"role": "user", "content": text}, **kw}


def tool_result(uuid, days_ago=1.0):
    return {"type": "user", "uuid": uuid, "timestamp": ts(days_ago),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}


def a(uuid, blocks, days_ago=1.0, **kw):
    if isinstance(blocks, str):
        blocks = [{"type": "text", "text": blocks}]
    return {"type": "assistant", "uuid": uuid, "timestamp": ts(days_ago), "message": {"role": "assistant", "content": blocks}, **kw}


def wrap_up(ask="", recap="Recap.", labels=()):
    return {"type": "tool_use", "id": "w", "name": asks.WRAP_UP,
            "input": {"recap": recap, "ask": ask, "actions": [{"label": l} for l in labels]}}


def bash():
    return {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "ls"}}


def desktop(root: pathlib.Path, cli_id: str, *, cwd=f"{HOME}/repos/app", status="blocked", needs="", detail="",
            summarizes="", archived=True, days_ago=2.0, title="A session", prs=(), sid=None, deleted=False):
    sid = sid or f"local_{cli_id}"
    d = {"sessionId": sid, "cliSessionId": cli_id, "cwd": cwd, "isArchived": archived, "title": title,
         "createdAt": ms(days_ago + 1), "lastActivityAt": ms(days_ago), "prs": list(prs),
         "postTurnSummary": {"status_category": status, "status_detail": detail, "needs_action": needs,
                             "summarizes_uuid": summarizes}}
    name = ("deleted_" if deleted else "") + f"{sid}.json"
    p = root / "acct" / "work" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    return p


@pytest.fixture
def env(tmp_path):
    class E:
        pass
    e = E()
    e.desktop = tmp_path / "sessions"
    e.projects = tmp_path / "projects"
    e.codex = tmp_path / "codex" / "sessions"
    e.archive = tmp_path / "codex" / "archived"
    e.reminders = tmp_path / "reminders.toml"
    for d in (e.desktop, e.projects, e.codex):
        d.mkdir(parents=True)

    def transcript(cli_id, recs, cwd=f"{HOME}/repos/app"):
        slug = re.sub(r"[/.]", "-", cwd)
        return write_jsonl(e.projects / slug / f"{cli_id}.jsonl", recs)
    e.transcript = transcript

    real_collect = asks.collect

    def collect(days=21, **kw):
        return real_collect(days, NOW, desktop=str(e.desktop), projects=str(e.projects), codex_root=str(e.codex),
                            codex_archive=str(e.archive), reminders=e.reminders, **kw)
    e.collect = collect
    return e


# --- product from a working directory ----------------------------------------------------------

@pytest.mark.parametrize("cwd,product", [
    (f"{HOME}/repos/app", "app"),
    (f"{HOME}/repos/app/ios/Sources", "app"),
    (f"{HOME}/repos/app/.claude/worktrees/funny-name-1a2b", "app"),
    (f"{HOME}/.worktrees/app/feat-thing", "app"),
    (f"{HOME}/.worktrees/app", "app"),
    (f"{HOME}/repos", "(no repo)"),
    (f"{HOME}/ops", "ops"),
    ("/private/tmp/claude-501/x/scratch", "(scratch)"),
    ("", "unknown"),
])
def test_product_of_maps_worktrees_to_their_repo(cwd, product):
    assert asks.product_of(cwd) == product


# --- the end of a Claude Code transcript --------------------------------------------------------

def test_wrap_up_ask_is_taken_with_recap_and_option_labels(env):
    p = env.transcript("c1", [u("u1", "build it"), a("a1", [bash()]), tool_result("r1"),
                              a("a2", [wrap_up("Ship it today?", "Built and tested.", ["Ship", "Wait"])])])
    r = asks.scan_claude(str(p))
    assert (r["ask"], r["recap"], r["options"]) == ("Ship it today?", "Built and tested.", ["Ship", "Wait"])
    assert r["uuid"] == "a2" and not r["human_after"]


def test_wrap_up_without_an_ask_asks_nothing(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", [wrap_up("", "All done.")]), a("a2", "Done. Merged.")])
    r = asks.scan_claude(str(p))
    assert r["ask"] is None and r["question"] is None


def test_final_text_ending_in_a_question_is_taken_as_its_last_paragraph(env):
    text = "Long status paragraph. " * 40 + "\n\nWhich of the two layouts do you want?"
    p = env.transcript("c1", [u("u1", "go"), a("a1", text)])
    assert asks.scan_claude(str(p))["question"] == "Which of the two layouts do you want?"


def test_a_question_with_an_options_list_keeps_the_list(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Done.\n\nWhat next?\n\n- polish the UI\n- ship it")])
    assert asks.scan_claude(str(p))["question"] == "What next?\n- polish the UI\n- ship it"


def test_a_long_trailing_question_is_cut_to_400_characters_from_the_front(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "word " * 200 + "do you agree?")])
    q = asks.scan_claude(str(p))["question"]
    assert len(q) <= 400 and q.endswith("do you agree?") and q.startswith("…")


def test_status_text_without_a_question_is_not_a_question(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Done. Tests pass, the PR is up.")])
    assert asks.scan_claude(str(p))["question"] is None


def test_a_human_prompt_after_the_last_turn_answers_it(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Ready to merge?"), u("u2", "yes, merge")])
    r = asks.scan_claude(str(p))
    assert r["human_after"] and r["question"] is None and r["uuid"] == "a1"


def test_a_bare_continue_answers_a_question_too(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Ready to merge?"), u("u2", "continue")])
    assert asks.scan_claude(str(p))["human_after"]


def test_a_system_reminder_or_tool_result_after_the_turn_is_not_an_answer(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Ready to merge?"),
                              u("u2", "<system-reminder>background task done</system-reminder>"), tool_result("r1")])
    r = asks.scan_claude(str(p))
    assert not r["human_after"] and r["question"] == "Ready to merge?"


def test_a_question_followed_by_more_tool_work_is_not_the_end_of_the_turn(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", [{"type": "text", "text": "Shall I try the other way?"}, bash()])])
    assert asks.scan_claude(str(p))["question"] is None


def test_sidechain_records_and_api_errors_ask_nothing(env):
    p = env.transcript("c1", [u("u1", "go"), a("a1", "Is this fine?"),
                              a("a2", "Subagent asks: which one?", isSidechain=True),
                              a("a3", "API Error: can't reach the server?", isApiErrorMessage=True)])
    r = asks.scan_claude(str(p))
    assert r["question"] is None


def test_only_the_tail_of_a_big_transcript_is_read(env):
    filler = [a(f"f{i}", "x" * 4000) for i in range(300)]          # ~1.2 MB
    p = env.transcript("c1", [u("u1", "go")] + filler + [a("last", "Which one?")])
    assert asks.scan_claude(str(p), tail_bytes=64 * 1024)["question"] == "Which one?"


def test_find_transcript_uses_the_slug_then_falls_back_to_any_directory(env):
    p = env.transcript("c1", [u("u1", "go")])
    assert asks.find_transcript("c1", f"{HOME}/repos/app", str(env.projects)) == str(p)
    assert asks.find_transcript("c1", "/elsewhere", str(env.projects)) == str(p)
    assert asks.find_transcript("nope", f"{HOME}/repos/app", str(env.projects)) is None
    assert asks.find_transcript("../x", "/", str(env.projects)) is None


# --- desktop sessions + transcripts -------------------------------------------------------------

def test_a_blocked_desktop_session_without_a_transcript_is_a_blocked_item(env):
    desktop(env.desktop, "c1", needs="Approve the checksum change", detail="Waiting on a flag.", summarizes="a9",
            prs=[{"prNumber": 4, "repo": "o/r", "state": "open", "url": "https://github.com/o/r/pull/4"}])
    [item] = env.collect()
    assert (item.kind, item.product, item.archived, item.harness) == ("blocked", "app", True, "claude-desktop")
    assert item.question == "Approve the checksum change" and item.context == "Waiting on a flag."
    assert item.link == "claude://claude.ai/epitaxy/local_c1" and item.pr.endswith("/pull/4")
    assert item.id == asks.make_id("claude", "c1", "a9")


def test_completed_sessions_and_tombstones_are_not_items(env):
    desktop(env.desktop, "c1", status="completed")
    desktop(env.desktop, "c2", needs="x", deleted=True)
    assert env.collect() == []


def test_a_desktop_session_and_its_transcript_are_one_record_and_the_wrap_up_wins(env):
    env.transcript("c1", [u("u1", "go"), a("a1", [wrap_up("Pick the tier?", "Both built.", ["Pro", "Max"])])])
    desktop(env.desktop, "c1", needs="Decide the tier", detail="Both built.", summarizes="a1")
    [item] = env.collect()
    assert item.kind == "question" and item.question == "Pick the tier?"
    assert item.options == ["Pro", "Max"] and item.context == "Both built."
    assert item.harness == "claude-desktop" and item.id == asks.make_id("claude", "c1", "a1")


def test_needs_action_beats_a_trailing_question(env):
    env.transcript("c1", [u("u1", "go"), a("a1", "Done.\n\nWant me to also rename it?")])
    desktop(env.desktop, "c1", needs="Confirm the rename", summarizes="a1")
    [item] = env.collect()
    assert item.question == "Confirm the rename" and item.kind == "question"


def test_a_trailing_question_alone_is_found_without_a_desktop_summary(env):
    env.transcript("c1", [u("u1", "go"), a("a1", "All green.\n\nShall I push?")])
    desktop(env.desktop, "c1", status="completed", summarizes="a1")
    [item] = env.collect()
    assert item.question == "Shall I push?" and item.kind == "question"


def test_a_later_human_prompt_closes_the_item(env):
    env.transcript("c1", [u("u1", "go"), a("a1", "Shall I push?"), u("u2", "yes")])
    desktop(env.desktop, "c1", needs="Confirm the push", summarizes="a1")
    assert env.collect() == []


def test_a_summary_older_than_the_transcript_is_not_trusted(env):
    env.transcript("c1", [u("u1", "go"), a("a1", "Blocked."), u("u2", "ok"), a("a2", "Done, merged.")])
    desktop(env.desktop, "c1", needs="Approve", summarizes="a1")
    assert env.collect() == []


def test_a_transcript_without_a_desktop_session_is_a_claude_code_item(env):
    env.transcript("solo", [u("u1", "go"), a("a1", "Which database do you want?")], cwd=f"{HOME}/.worktrees/app/feat-x")
    [item] = env.collect()
    assert (item.harness, item.product, item.archived) == ("claude-code", "app", False)
    assert item.link == "claude --resume solo"


def test_scripted_claude_sessions_are_not_asked_anything(env):
    env.transcript("lane", [u("u1", "review", entrypoint="sdk-cli"), a("a1", "Anything else?", entrypoint="sdk-cli")])
    assert env.collect() == []


def test_the_window_drops_old_sessions(env):
    desktop(env.desktop, "old", needs="Old thing", days_ago=40)
    desktop(env.desktop, "new", needs="New thing", days_ago=3)
    assert [i.question for i in env.collect(21)] == ["New thing"]
    assert len(env.collect(60)) == 2


def test_items_are_oldest_first_and_grouped_by_product(env):
    desktop(env.desktop, "c1", needs="B question", days_ago=2, cwd=f"{HOME}/repos/b")
    desktop(env.desktop, "c2", needs="A old question", days_ago=9, cwd=f"{HOME}/repos/a")
    desktop(env.desktop, "c3", needs="B older question", days_ago=5, cwd=f"{HOME}/repos/b")
    items = env.collect()
    assert [i.question for i in items] == ["A old question", "B older question", "B question"]
    assert [p for p, _ in asks.group(items)] == ["a", "b"]


# --- text hygiene -----------------------------------------------------------------------------

def test_question_text_is_scrubbed_and_cut_at_600_characters(env):
    desktop(env.desktop, "c1", needs="Use token=abcd1234efgh5678 for the call. " + "long " * 200)
    [item] = env.collect()
    assert "abcd1234efgh5678" not in item.question and "[redacted]" in item.question
    assert len(item.question) == 600 and item.question.endswith("…")


def test_context_is_cut_at_300_characters(env):
    desktop(env.desktop, "c1", needs="Q", detail="detail " * 150)
    assert len(env.collect()[0].context) == 300


# --- Codex ------------------------------------------------------------------------------------

def rollout(env, sid, recs, *, originator="Codex Desktop", source="vscode", cwd=f"{HOME}/repos/app", day="2026/10/15",
            archived=False):
    meta = {"type": "session_meta", "timestamp": ts(1), "payload": {
        "id": sid, "session_id": sid, "cwd": cwd, "originator": originator, "source": source}}
    base = env.archive if archived else env.codex / day
    return write_jsonl(base / f"rollout-2026-10-15T10-00-00-{sid}.jsonl", [meta] + recs)


def cx_user(text, days_ago=1.0):
    return {"type": "response_item", "timestamp": ts(days_ago), "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}


def cx_assistant(text, days_ago=1.0):
    return {"type": "response_item", "timestamp": ts(days_ago), "payload": {
        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}}


def cx_ask_call(call_id, title="Which zip code?", options=("A", "B"), days_ago=1.0):
    args = {"questions": [{"title": title, "options": list(options)}]}
    return {"type": "response_item", "timestamp": ts(days_ago), "payload": {
        "type": "function_call", "name": "request_user_input_async", "call_id": call_id, "arguments": json.dumps(args)}}


def cx_output(call_id):
    return {"type": "response_item", "timestamp": ts(1), "payload": {"type": "function_call_output", "call_id": call_id, "output": "ok"}}


def cx_complete(text, turn="t1", days_ago=1.0):
    return {"type": "event_msg", "timestamp": ts(days_ago), "payload": {"type": "task_complete", "turn_id": turn, "last_agent_message": text}}


def test_a_codex_request_for_input_without_an_output_is_open(env):
    rollout(env, "s1", [cx_user("go"), cx_ask_call("call1", options=("Yes", "No"))])
    [item] = env.collect()
    assert (item.harness, item.kind, item.product) == ("codex", "question", "app")
    assert item.question == "Which zip code?" and item.options == ["Yes", "No"]
    assert item.link == "codex resume s1" and not item.archived


def test_an_answered_codex_request_is_not_open(env):
    rollout(env, "s1", [cx_user("go"), cx_ask_call("call1"), cx_output("call1"), cx_user("option B")])
    assert env.collect() == []


def test_an_accepted_but_unanswered_codex_request_stays_open(env):
    # request_user_input_async returns {"accepted": true} at once; the owner's answer
    # arrives later as a user message.
    rollout(env, "s1", [cx_user("go"), cx_ask_call("call1"), cx_output("call1"), cx_assistant("Waiting.")])
    [item] = env.collect()
    assert item.kind == "question"


def test_a_codex_final_message_ending_in_a_question_is_open(env):
    rollout(env, "s1", [cx_user("go"), cx_complete("All set.\n\nShould I open the PR?")])
    [item] = env.collect()
    assert item.question == "Should I open the PR?"


def test_a_later_codex_user_message_closes_it(env):
    rollout(env, "s1", [cx_user("go"), cx_complete("Should I open the PR?"), cx_user("yes please")])
    assert env.collect() == []


def test_codex_exec_review_and_spawned_agents_are_automation(env):
    rollout(env, "s1", [cx_user("go"), cx_complete("Anything else?")], originator="codex_exec", source="exec")
    rollout(env, "s2", [cx_user("go"), cx_complete("Anything else?")], source={"subagent": {"thread_spawn": {}}})
    rollout(env, "s3", [cx_user("One-pass code review of this diff"), cx_complete("Anything else?")])
    assert env.collect() == []


def test_an_archived_codex_rollout_is_flagged_archived(env):
    rollout(env, "s9", [cx_user("go"), cx_complete("Shall I continue?")], archived=True)
    [item] = env.collect()
    assert item.archived


# --- Teyla's own queue --------------------------------------------------------------------------

def test_pending_gated_runs_are_gate_items_and_decided_ones_are_not():
    state.add_inbox_item(run_id="r1", ref="app/daily", gate="A", state="drafted", summary="Draft the weekly note",
                         run_dir="/x", repo=f"{HOME}/repos/app")
    state.add_inbox_item(run_id="r2", ref="app/other", gate="A", state="drafted", summary="Second", run_dir="/x", repo="")
    state.add_inbox_decision(run_id="r2", decision="approve")
    items = asks.collect_gates()
    assert len(items) == 1
    g = items[0]
    assert (g.kind, g.product, g.question, g.link) == ("gate", "app", "Draft the weekly note", "teyla inbox show r1")
    assert g.options == ["approve", "reject"]


def test_reminders_appear_when_overdue_or_due_within_seven_days(env):
    today = dt.datetime.fromtimestamp(NOW).date()
    remind.add("Renew the cert", (today - dt.timedelta(days=2)).isoformat(), how="run renew.sh", path=env.reminders)
    remind.add("Soon", (today + dt.timedelta(days=5)).isoformat(), path=env.reminders)
    remind.add("Far away", (today + dt.timedelta(days=40)).isoformat(), path=env.reminders)
    items = asks.collect_reminders(env.reminders, today)
    assert sorted(i.question for i in items) == ["Renew the cert", "Soon"]
    cert = next(i for i in items if i.question == "Renew the cert")
    assert cert.kind == "reminder" and "overdue by 2d" in cert.context and "run renew.sh" in cert.context


# --- done and snooze --------------------------------------------------------------------------

def test_done_closes_an_item_by_id_prefix_and_records_the_note(env, monkeypatch):
    desktop(env.desktop, "c1", needs="First", summarizes="a1")
    desktop(env.desktop, "c2", needs="Second", summarizes="a2")
    first, second = env.collect()
    monkeypatch.setattr(asks, "collect", lambda days, now=None, **kw: env.collect(days))
    lines, code = asks.mark_done([first.id[:5]], "answered by phone", NOW)
    assert code == 0 and first.id in lines[0]
    st = json.loads(asks.state_path().read_text())
    assert st["done"][first.id]["note"] == "answered by phone"
    after = {i.id: i.status for i in env.collect()}
    assert after == {first.id: "done", second.id: "open"}
    assert oct(asks.state_path().stat().st_mode & 0o777) == "0o600"


def test_done_refuses_short_unknown_and_ambiguous_prefixes(env, monkeypatch):
    desktop(env.desktop, "c1", needs="First", summarizes="a1")
    [item] = env.collect()
    monkeypatch.setattr(asks, "collect", lambda days, now=None, **kw: env.collect(days))
    assert asks.mark_done(["ab"], "", NOW)[1] == 1
    assert asks.mark_done(["zzzzzz"], "", NOW)[1] == 1
    assert not asks.state_path().exists()
    # two items whose ids share a prefix
    a1 = asks.Ask(id="abc11111", kind="blocked", product="p", title="t", question="q", context="", options=[], when=NOW,
                  archived=False, link="l", pr="", harness="claude-desktop")
    a2 = asks.Ask(**{**dataclass_dict(a1), "id": "abc22222"})
    assert "matches 2 items" in asks.resolve("abc", [a1, a2])[1]


def dataclass_dict(x):
    import dataclasses
    return dataclasses.asdict(x)


def test_snooze_hides_an_item_until_the_day_passes(env, monkeypatch):
    desktop(env.desktop, "c1", needs="First", summarizes="a1")
    [item] = env.collect()
    monkeypatch.setattr(asks, "collect", lambda days, now=None, **kw: env.collect(days))
    line, code = asks.snooze(item.id, 3, NOW)
    assert code == 0 and "snoozed" in line
    assert env.collect()[0].status == "snoozed"
    st = asks.load_state()
    later = NOW + 4 * 86400
    assert asks.apply_state([asks.Ask(**{**dataclass_dict(item), "status": "open"})], st, NOW + 86400)[0].status == "snoozed"
    fresh = asks.Ask(**{**dataclass_dict(item), "status": "open"})
    assert asks.apply_state([fresh], st, later)[0].status == "open"
    assert asks.snooze(item.id, 0, NOW)[1] == 1


def test_state_writes_are_atomic_and_old_entries_are_pruned():
    st = {"done": {"old": {"ts": "2020-01-01T00:00:00Z"}, "new": {"ts": asks._iso(NOW)}}, "snoozed": {}}
    asks.save_state(st, now=NOW)
    saved = json.loads(asks.state_path().read_text())
    assert list(saved["done"]) == ["new"]
    assert not list(asks.state_path().parent.glob("asks.json.*"))


# --- output -----------------------------------------------------------------------------------

def sample(env):
    desktop(env.desktop, "c1", needs="Approve the change", detail="Context here.", days_ago=9, archived=True,
            cwd=f"{HOME}/repos/app/.claude/worktrees/x")
    env.transcript("c2", [u("u1", "go", cwd=f"{HOME}/repos/other"), a("a1", "Which one?")], cwd=f"{HOME}/repos/other")
    return env.collect()


def test_text_header_counts_archived_and_groups_by_product(env):
    items = sample(env)
    out = asks.render_text(items, NOW)
    assert out.splitlines()[0] == "2 waiting on you (1 in archived sessions)"
    assert out.index("app (1)") < out.index("other (1)")
    assert "Approve the change" in out and "claude://claude.ai/epitaxy/local_c1" in out
    assert asks.render_text([], NOW) == "nothing is waiting on you."


def test_json_output_carries_the_record_fields(env):
    d = json.loads(asks.render_json(sample(env), NOW))
    assert (d["waiting"], d["archived"]) == (2, 1)
    keys = set(d["items"][0])
    assert {"id", "kind", "product", "title", "question", "context", "options", "age_s", "archived", "link", "pr",
            "harness", "status", "ts"} <= keys
    assert d["items"][0]["age_s"] == 9 * 86400 - 0


def test_html_is_self_contained_escaped_and_themed(env):
    desktop(env.desktop, "c1", needs='<script>alert("x")</script> & "quoted" <img src=http://evil.example/x>',
            title="<b>Title</b>", detail="</div><style>*{display:none}</style>")
    page = asks.render_html(env.collect(), NOW)
    assert "<script>alert" not in page and "<img src" not in page and "<b>Title</b>" not in page
    assert "&lt;script&gt;alert" in page and "&amp; &quot;quoted&quot;" in page
    assert "prefers-color-scheme:dark" in page and 'name="viewport"' in page
    assert 'src="http' not in page and "<link" not in page and "url(" not in page and "@import" not in page
    assert page.count('href="') == 1                  # the session link; nothing is fetched from anywhere
    assert "Open session" in page and "teyla asks done " in page and "<button" in page
    assert page.count("<script>") == 1             # only the copy handler


def test_html_page_for_nothing_says_so(env):
    page = asks.render_html([], NOW)
    assert "Nothing is waiting on you." in page


def test_cli_lists_filters_and_writes_html(env, monkeypatch, capsys, tmp_path):
    sample(env)
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(env.desktop))
    monkeypatch.setattr(asks.claude_code, "DEFAULT_ROOT", str(env.projects))
    monkeypatch.setattr(asks.codex, "DEFAULT_ROOT", str(env.codex))
    monkeypatch.setattr(asks.codex, "DEFAULT_ARCHIVE_ROOT", str(env.archive))
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    assert cli.main(["asks", "--json", "--product", "other"]) == 0
    assert [i["product"] for i in json.loads(capsys.readouterr().out)["items"]] == ["other"]
    out_file = tmp_path / "page.html"
    assert cli.main(["asks", "--html", "-o", str(out_file)]) == 0
    assert out_file.read_text().startswith("<!doctype html>")
    assert cli.main(["asks"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("2 waiting on you")
    # a plain run refreshed the banner count; a filtered one does not rewrite it
    assert asks.count_path().read_text() == "2 questions wait for you — teyla asks\n"
    assert cli.main(["asks", "done"]) == 64
    assert cli.main(["asks", "snooze", "abc"]) == 64
    assert cli.main(["asks", "bogus"]) == 64


def test_done_through_the_cli_hides_the_item(env, monkeypatch, capsys):
    items = sample(env)
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(env.desktop))
    monkeypatch.setattr(asks.claude_code, "DEFAULT_ROOT", str(env.projects))
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    assert cli.main(["asks", "done", items[0].id, "--note", "ok"]) == 0
    capsys.readouterr()
    assert cli.main(["asks", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["waiting"] == 1
    assert cli.main(["asks", "--json", "--all"]) == 0
    assert json.loads(capsys.readouterr().out)["waiting"] == 2


# --- the session-start line ---------------------------------------------------------------------

def test_banner_line_counts_questions_not_reminders(env):
    a1 = asks.Ask(id="1", kind="blocked", product="p", title="t", question="q", context="", options=[], when=NOW,
                  archived=False, link="l", pr="", harness="x")
    rem = asks.Ask(**{**dataclass_dict(a1), "id": "2", "kind": "reminder"})
    assert asks.banner_line([a1]) == "1 question waits for you — teyla asks"
    assert asks.banner_line([a1, asks.Ask(**{**dataclass_dict(a1), "id": "3"}), rem]) == "2 questions wait for you — teyla asks"
    assert asks.banner_line([rem]) == ""


def test_write_count_removes_the_file_when_nothing_waits(env):
    a1 = asks.Ask(id="1", kind="blocked", product="p", title="t", question="q", context="", options=[], when=NOW,
                  archived=False, link="l", pr="", harness="x")
    asks.write_count([a1])
    assert asks.count_path().exists()
    asks.write_count([])
    assert not asks.count_path().exists() and asks.stamp_path().exists()


HOOK = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "session-start.sh"


def _hook(tmp_path, *, count=None, count_age_s=0, stamp_age_s=None, fake_teyla=False):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True, exist_ok=True)
    (home / ".teyla" / "update-check.json").write_text("{}")
    if count is not None:
        f = home / ".teyla" / "asks.count"
        f.write_text(count)
        os.utime(f, (time.time() - count_age_s,) * 2)
    if stamp_age_s is not None:
        f = home / ".teyla" / "asks.stamp"
        f.write_text("")
        os.utime(f, (time.time() - stamp_age_s,) * 2)
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    log = tmp_path / "calls"
    if fake_teyla:
        (bin_ / "teyla").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
        (bin_ / "teyla").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_}:/usr/bin:/bin"}
    proc = subprocess.run(["sh", str(HOOK)], input="", capture_output=True, text=True, timeout=10, cwd=tmp_path, env=env)
    return proc, log


def test_session_start_prints_the_questions_line_from_the_count_file(tmp_path):
    proc, _ = _hook(tmp_path, count="3 questions wait for you — teyla asks\n")
    assert "teyla: 3 questions wait for you — teyla asks\n" in proc.stdout


def test_session_start_ignores_a_stale_or_missing_count_file(tmp_path):
    assert "wait for you" not in _hook(tmp_path, count="3 questions wait for you — teyla asks\n", count_age_s=4 * 86400)[0].stdout
    assert "wait for you" not in _hook(tmp_path / "other")[0].stdout


def test_session_start_refreshes_the_count_in_the_background_once_an_hour(tmp_path):
    proc, log = _hook(tmp_path, fake_teyla=True)
    end = time.monotonic() + 5
    while time.monotonic() < end and not (log.exists() and "asks --quiet" in log.read_text()):
        time.sleep(0.05)
    assert "asks --quiet" in log.read_text()
    log.unlink()
    _hook(tmp_path, stamp_age_s=600, fake_teyla=True)           # touched ten minutes ago: not again
    time.sleep(0.4)
    assert not log.exists() or "asks --quiet" not in log.read_text()


def test_the_hook_scans_nothing_and_is_fast(tmp_path):
    t = time.monotonic()
    proc, _ = _hook(tmp_path, count="1 question waits for you — teyla asks\n")
    assert proc.returncode == 0 and time.monotonic() - t < 1.0


# --- the daily routine ------------------------------------------------------------------------

def test_the_daily_wrapper_refreshes_the_count_and_an_old_wrapper_is_stale(tmp_path, monkeypatch):
    assert "teyla asks --quiet" in routine_install.DAILY_WRAPPER_TEMPLATE
    wrapper = tmp_path / "daily.sh"
    old = routine_install.DAILY_WRAPPER_TEMPLATE.replace("teyla asks --quiet || true\n", "")
    wrapper.write_text(old.format(env_sh="", stamp=".last", label="x", teyla_bin="/bin/teyla", update_line=""))
    monkeypatch.setattr(routine_install, "DAILY_WRAPPER_PATH", wrapper)
    assert routine_install._wrapper_stale(wrapper, "/bin/teyla") is True


# --- doctor: the inbox is inbox.jsonl, not a directory ------------------------------------------

def test_doctor_counts_pending_inbox_items_from_the_jsonl_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / "elsewhere")
    state.add_inbox_item(run_id="r1", ref="app/daily", gate="A", state="drafted", summary="s", run_dir="/x", repo="")
    state.add_inbox_item(run_id="r2", ref="app/daily", gate="A", state="drafted", summary="s", run_dir="/x", repo="")
    state.add_inbox_decision(run_id="r2", decision="reject")
    rows = [c for c in doctor.checks(scan_repos=False) if c["name"] == "control:inbox"]
    assert len(rows) == 1 and "1 run(s) waiting for you" in rows[0]["detail"]


def test_done_older_than_closes_old_questions_and_keeps_new_ones_and_reminders(env, monkeypatch):
    old = asks.Ask(id="old11111", kind="blocked", product="p", title="t", question="q", context="", options=[],
                   when=NOW - 5 * 86400, archived=True, link="l", pr="", harness="claude-desktop")
    other = asks.Ask(**{**dataclass_dict(old), "id": "oth22222", "product": "q"})
    new = asks.Ask(**{**dataclass_dict(old), "id": "new33333", "when": NOW - 3600})
    rem = asks.Ask(**{**dataclass_dict(old), "id": "rem44444", "kind": "reminder"})

    def fake(days, now=None, **kw):
        st = asks.load_state()
        return asks.apply_state([asks.Ask(**dataclass_dict(a)) for a in (old, other, new, rem)], st, NOW)

    monkeypatch.setattr(asks, "collect", fake)
    lines, code = asks.mark_done_older(3, "bulk", "p", NOW)
    assert code == 0 and lines[-1] == "closed 1" and "old11111" in lines[0]
    lines, code = asks.mark_done_older(3, "bulk", "", NOW)
    assert lines[-1] == "closed 1" and "oth22222" in lines[0]
    st = json.loads(asks.state_path().read_text())
    assert set(st["done"]) == {"old11111", "oth22222"} and st["done"]["old11111"]["note"] == "bulk"
    assert asks.mark_done_older(3, "", "", NOW)[0] == ["nothing open is older than 3 day(s)"]
    assert asks.mark_done_older(0, "", "", NOW)[1] == 1


def test_ids_after_options_reach_the_command(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(asks, "mark_done", lambda ids, note, now: (seen.update(ids=ids, note=note) or ([], 0)))
    assert cli.main(["asks", "done", "--note", "why", "abc123", "def456"]) == 0
    assert seen == {"ids": ["abc123", "def456"], "note": "why"}
    with pytest.raises(SystemExit):
        cli.main(["asks", "--bogus-flag"])
    assert cli.main(["asks", "done", "abc123", "--older-than", "3"]) == 64


def test_words_after_a_double_dash_are_literal(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(asks, "mark_done", lambda ids, note, now: (seen.update(ids=ids, note=note) or ([], 0)))
    assert cli.main(["asks", "done", "--note", "why", "--", "abc123", "-def456"]) == 0
    assert seen["ids"] == ["abc123", "-def456"]
