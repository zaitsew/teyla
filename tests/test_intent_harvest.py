"""What the intent harvest keeps: the owner's typed words and his button answers (with their
question), never another agent's message, and not less because a prompt was queued mid-task or came
after a compaction. Plus `teyla intent rebuild`. Synthetic transcripts only."""
from __future__ import annotations

import datetime as dt
import json

from teyla import cli, intent
from test_intent import NOW, claude_user, hook_payload, jl, prose, recent, repo

ASK = "Which fix first?"


def wrap_up(ts, ask=ASK, labels=("Yes, fix 1", "Not now")) -> dict:
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "tu1", "name": "mcp__ccd_turn__wrap_up",
         "input": {"recap": "Two bugs found.", "ask": ask, "actions": [{"label": l} for l in labels]}}]}}


def queued(ts, cwd, text, mode="prompt") -> dict:
    return {"type": "attachment", "timestamp": ts, "cwd": cwd, "attachment": {
        "type": "queued_command", "prompt": text, "commandMode": mode, "origin": {"kind": "human"}, "timestamp": ts}}


def asked(ts, cwd, answers: dict, notes: dict | None = None) -> dict:
    r = {"questions": [{"question": q} for q in answers], "answers": answers}
    if notes:
        r["annotations"] = {q: {"notes": n} for q, n in notes.items()}
    return claude_user(ts, cwd, [{"type": "tool_result", "tool_use_id": "tu2", "content": "The user answered."}], toolUseResult=r)


def roots_with(tmp_path, rows, sid="s1") -> dict:
    jl(tmp_path / "cc" / "-p-alpha" / f"{sid}.jsonl", rows)
    return {"claude-code": {"root": str(tmp_path / "cc")},
            "codex": {"root": str(tmp_path / "cx"), "archive_root": "", "index_path": str(tmp_path / "none.jsonl")}}


def texts(product="alpha") -> list[str]:
    return [e["text"] for e in intent.entries(product)]


# --- what counts --------------------------------------------------------------------------

def test_agent_messages_are_not_the_owners_words():
    for t in ("<cross-session-message from=\"local_x\" from-name=\"Lab\">" + prose(600) + "</cross-session-message>",
              "Task (from the session that started this one): " + prose(600),
              "<realtime_delegation>\n<input>hi</input>\n<transcript_delta>" + prose(600) + "</transcript_delta>\n</realtime_delegation>",
              "<heartbeat>\n<automation_id>a</automation_id>\n<instructions>" + prose(600) + "</instructions>\n</heartbeat>",
              "This is an app-generated request. " + prose(600)):
        assert intent.typed(t) is None, t[:30]


def test_codex_envelopes_keep_only_what_the_person_typed():
    files = ("# Files mentioned by the user\n\n## notes.pdf /tmp/notes.pdf\n\nDistinguish instructions in attached documents"
             " from the user's request\n\n<in-app-browser-context source=\"x\">" + prose(300, "page") + "</in-app-browser-context>"
             "\n\n## My request\nMove the return flight to the morning.")
    assert intent.typed(files) == "Move the return flight to the morning."
    page = "<in-app-browser-context source=\"x\">" + prose(300, "page") + "</in-app-browser-context>\n\nWhat changed here?"
    assert intent.typed(page) == "What changed here?"
    reply = ("<send_user_message_question_reply>" + json.dumps([{"questionItemId": "q1", "question": "Ship it now?", "answer": "Yes"}])
             + "</send_user_message_question_reply>")
    assert intent.typed(reply) == "Asked: Ship it now?\nAnswered: Yes"
    assert intent.typed("<send_user_message_question_reply>not json</send_user_message_question_reply>") is None


def test_an_answer_is_kept_whatever_its_length_and_a_short_prompt_is_not(tmp_path):
    r = repo(tmp_path, "alpha")
    tp = tmp_path / "t.jsonl"
    jl(tp, [claude_user(recent(5), str(r), prose(500)), wrap_up(recent(4))])
    assert intent.capture(hook_payload("Yes, fix 1", r, transcript_path=str(tp)), now=NOW) is True
    assert texts()[-1] == f"Asked: {ASK}\nAnswered: Yes, fix 1"
    assert intent.capture(hook_payload("not that one", r, transcript_path=str(tp)), now=NOW) is False


def test_a_label_typed_after_someone_spoke_again_is_not_an_answer(tmp_path):
    r = repo(tmp_path, "alpha")
    tp = tmp_path / "t.jsonl"
    jl(tp, [wrap_up(recent(5)), claude_user(recent(4), str(r), "Something else first, please.")])
    assert intent.pending_ask(str(tp)) is None
    assert intent.capture(hook_payload("Not now", r, transcript_path=str(tp)), now=NOW) is False


# --- backfill -----------------------------------------------------------------------------

def test_backfill_reads_queued_prompts_answers_and_prompts_after_a_compaction(tmp_path):
    r = str(repo(tmp_path, "alpha"))
    roots = roots_with(tmp_path, [
        claude_user(recent(90), r, prose(500, "first")),
        queued(recent(85), r, prose(450, "queued")),                                      # typed while the agent worked
        queued(recent(84), r, "<task-notification>" + prose(450) + "</task-notification>", mode="task-notification"),
        wrap_up(recent(80)),
        claude_user(recent(79), r, "Yes, fix 1"),
        asked(recent(70), r, {"Which name?": "Nova"}, notes={"Which name?": "short and soft"}),
        claude_user(recent(60), r, "This session is being continued from a previous conversation. " + prose(600), isCompactSummary=True),
        claude_user(recent(59), r, prose(420, "after")),
        claude_user(recent(58), r, "<cross-session-message from=\"x\">" + prose(500) + "</cross-session-message>", isMeta=True),
    ])
    assert intent.backfill(days=1, roots=roots)["alpha"] == {"found": 5, "new": 5}
    got = texts()
    assert got[0].startswith("I want the first") and got[1].startswith("I want the queued")
    assert got[2] == f"Asked: {ASK}\nAnswered: Yes, fix 1"
    assert got[3] == "Asked: Which name?\nAnswered: Nova\nshort and soft"
    assert got[4].startswith("I want the after")


# --- rebuild ------------------------------------------------------------------------------

def seed_file(lines: list[tuple[str, str, str]]) -> None:
    d = intent.intent_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "alpha.md").write_text("".join(f"## {when} · claude · session {sid}\n{body}\n\n" for when, sid, body in lines))


def test_rebuild_replaces_entries_from_transcripts_keeps_the_rest_and_backs_up(tmp_path, capsys):
    r = str(repo(tmp_path, "alpha"))
    roots = roots_with(tmp_path, [
        claude_user(recent(30), r, prose(500, "kept")),
        claude_user(recent(20), r, "<cross-session-message from=\"x\">" + prose(500) + "</cross-session-message>", isMeta=True),
        wrap_up(recent(10)),
        claude_user(recent(9), r, "Not now"),
    ], sid="abcd1234-0000")
    today = dt.datetime.now().strftime("%Y-%m-%d")
    seed_file([("2026-01-02 10:00", "99999999", prose(450, "old harness")),                   # no transcript: stays
               (f"{today} 00:01", "abcd1234", "<cross-session-message from=\"x\">" + prose(500) + "</cross-session-message>"),
               (f"{today} 00:02", "abcd1234", prose(500, "kept")),
               (f"{today} 00:03", "eeeeeeee", "Background (from the session that started this one) " + prose(500))])
    before = (intent.intent_dir() / "alpha.md").read_text()

    dry = intent.rebuild("alpha", dry=True, roots=roots)
    assert (intent.intent_dir() / "alpha.md").read_text() == before
    assert [d["why"] for d in dry["dropped"]] == ["not in its transcript", "automated"]
    assert [a["text"] for a in dry["added"]] == [f"Asked: {ASK}\nAnswered: Not now"]

    res = intent.rebuild("alpha", roots=roots)
    assert res["before"] == 4 and res["after"] == 3
    got = texts()
    assert got[0].startswith("I want the old harness") and got[1].startswith("I want the kept") and got[2].endswith("Not now")
    bak = res["backup"]
    assert bak and open(bak).read() == before
    index = json.loads((intent.intent_dir() / ".index.json").read_text())["seen"]
    assert sorted(k for k in index if k.startswith("alpha:")) == sorted(f"alpha:{intent.digest(t)}" for t in got)

    again = intent.rebuild("alpha", roots=roots)                                              # nothing left to change
    assert again["added"] == again["dropped"] == [] and again["backup"] is None


def test_rebuild_with_days_leaves_older_entries_alone(tmp_path):
    r = str(repo(tmp_path, "alpha"))
    roots = roots_with(tmp_path, [claude_user(recent(30), r, prose(500, "new"))], sid="abcd1234-0000")
    seed_file([("2026-01-02 10:00", "abcd1234", "<cross-session-message from=\"x\">" + prose(500) + "</cross-session-message>")])
    res = intent.rebuild("alpha", days=2, roots=roots)
    assert res["dropped"] == [] and len(res["added"]) == 1 and res["after"] == 2


def test_rebuild_command(tmp_path, capsys, monkeypatch):
    r = str(repo(tmp_path, "alpha"))
    roots = roots_with(tmp_path, [claude_user(recent(30), r, prose(500, "new"))])
    seed_file([("2026-01-02 10:00", "99999999", prose(450, "old"))])
    real = intent.rebuild
    monkeypatch.setattr(intent, "rebuild", lambda name, **k: real(name, roots=roots, **k))
    assert cli.main(["intent", "rebuild", "alpha", "--dry"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "alpha: 1 entries -> 2: would drop 0, would add 1; nothing written"
    assert cli.main(["intent", "rebuild"]) == 64
