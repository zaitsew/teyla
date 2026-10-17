"""`teyla intent cover`: does a plan serve the owner's own sentences?

Synthetic text only (atlas, cellar, lens). The model pass is never called: an autouse fixture makes
the one function that would start `claude` fail the test that reaches it. Russian text is written as
\\u escapes; conftest points TEYLA_HOME at a tmp dir."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from teyla import cli, intent, intent_cover as ic, state

REAL_CALL = ic._call      # the guard below replaces ic._call in every test; this is the original
WHEN = dt.datetime(2026, 10, 16, 15, 40, tzinfo=dt.timezone.utc)

RU_WANT = "\u042f \u0445\u043e\u0447\u0443 \u0432\u0438\u0434\u0435\u0442\u044c \u0432\u0441\u0435 \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u0435 \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u043d\u0430 \u043e\u0434\u043d\u043e\u043c \u044d\u043a\u0440\u0430\u043d\u0435."
RU_PLAN = "\u041e\u043a\u043d\u043e \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442 \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u0435 \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u043d\u0430 \u043e\u0434\u043d\u043e\u043c \u044d\u043a\u0440\u0430\u043d\u0435 \u0434\u043b\u044f \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0430."
RU_NOISE = "\u0414\u0430, \u0434\u0430\u0432\u0430\u0439, \u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0439 \u044d\u0442\u043e\u0442 \u0441\u043f\u0440\u0438\u043d\u0442 \u043f\u0440\u044f\u043c\u043e \u0441\u0435\u0439\u0447\u0430\u0441, \u043f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430."
RU_STATE = "\u0422\u044b \u0443\u0436\u0435 \u0437\u0430\u043a\u043e\u043d\u0447\u0438\u043b \u0441 \u044d\u0442\u0438\u043c \u0441\u043f\u0440\u0438\u043d\u0442\u043e\u043c \u0438\u043b\u0438 \u0435\u0449\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0448\u044c?"
RU_OTHER = "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f \u0434\u043e\u043b\u0436\u043d\u0430 \u043e\u043f\u0438\u0441\u044b\u0432\u0430\u0442\u044c \u0438\u0442\u043e\u0433\u043e\u0432\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043f\u0440\u043e\u0434\u0443\u043a\u0442\u0430."


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached the real claude")
    monkeypatch.setattr(ic, "_call", boom)
    monkeypatch.setattr(state, "_run_claude", boom)


def keep(product: str, text: str, minutes: int = 0, session: str = "s1abcdef", when=None, harness="claude"):
    when = when or WHEN + dt.timedelta(minutes=minutes)
    with intent.Store() as st:
        assert st.add(product, text, harness, session, when)


def entry(text: str, date: str = "2026-10-16 18:39", session: str = "s1abcdef") -> dict:
    return {"text": text, "date": date, "harness": "claude", "session": session}


def run(plan: str, *texts: str, model: bool = False) -> dict:
    return ic.run_cover(plan, [entry(t, f"2026-10-1{i} 10:00") for i, t in enumerate(texts)], use_model=model)


def by_status(res: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in res["items"]:
        out.setdefault(it["status"], []).append(it["text"])
    return out


# --- sentences ----------------------------------------------------------------------------

def test_sentences_split_on_stops_but_not_on_abbreviations_numbers_or_file_names():
    s = ic.split_sentences("Keep it short, e.g. under ten words. Version 3.5 stays in intent.py. Then ship it! Why not?")
    assert s == ["Keep it short, e.g. under ten words.", "Version 3.5 stays in intent.py.", "Then ship it!", "Why not?"]
    assert ic.split_sentences("\u041d\u0443\u0436\u043d\u043e \u043a\u0440\u0430\u0442\u043a\u043e, \u0442.\u0435. \u0431\u0435\u0437 \u0432\u043e\u0434\u044b. \u041f\u043e\u0442\u043e\u043c \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c.") == ["\u041d\u0443\u0436\u043d\u043e \u043a\u0440\u0430\u0442\u043a\u043e, \u0442.\u0435. \u0431\u0435\u0437 \u0432\u043e\u0434\u044b.", "\u041f\u043e\u0442\u043e\u043c \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c."]


def test_lines_lists_and_code_blocks():
    text = ("Goals:\n1. Every open question on one screen\n- Docs describe the end state\n\n"
            "A line without a closing stop\nthe next line.\n```\nnoise = 1\n```\n> quoted agent text here")
    lines = ic.logical_lines(text, keep_code=False)
    assert lines == ["Goals:", "Every open question on one screen", "Docs describe the end state",
                     "A line without a closing stop", "the next line."]
    assert "noise = 1" in ic.logical_lines(text, keep_code=True)


def test_short_sentences_chatter_and_status_questions_are_not_sources():
    text = ("Proceed. ok, do it\n"
            "Yes, go ahead with the sprint as we planned it.\n"
            "Are you done with the sprint yet?\n"
            "What is the status of the build right now?\n"
            "Yes, but the plan must keep every detail I wrote.\n"
            "The window should list every open question on one screen.\n"
            "Why does the sync fail after a restart?\n"
            f"{RU_NOISE}\n{RU_STATE}\n{RU_WANT}\n")
    got = [s["text"] for s in ic.source_sentences([entry(text)])]
    assert got == ["Yes, but the plan must keep every detail I wrote.",
                   "The window should list every open question on one screen.",
                   "Why does the sync fail after a restart?", RU_WANT]


def test_a_sentence_counts_once_and_markup_is_dropped():
    one = '<pasted_content id="b879"> The window should list every open question on one screen.'
    two = "The window should list every open question on one screen!"
    got = ic.source_sentences([entry(one, "2026-10-16 10:00"), entry(two, "2026-10-17 10:00")])
    assert [(g["text"], g["date"]) for g in got] == [("The window should list every open question on one screen.", "2026-10-16 10:00")]


def test_the_cut_marker_of_a_long_prompt_is_not_a_sentence():
    text = "The window should list every open question on one screen.\n[1200 more characters not kept]"
    assert [s["text"] for s in ic.source_sentences([entry(text)])] == ["The window should list every open question on one screen."]


# --- served: quote, words, out of scope ---------------------------------------------------

SRC = "The window should list every open question on one screen so that I can answer from my phone."


def test_a_quote_serves_whatever_the_case_punctuation_or_spacing():
    plan = '## Scope\n\n> "the window   SHOULD list every open question -- on one screen, so that I can answer from my phone"\n'
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "quote"


def test_a_long_run_of_the_sentence_in_the_plan_is_a_quote():
    plan = "Source: ... list every open question on one screen so that I can answer ... (cut)."
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "quote"


def test_a_plan_sentence_with_the_same_content_words_serves_the_sentence():
    plan = "| Questions | The window lists all open questions on a single screen, and the owner answers from the phone. |"
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "words" and "open questions" in it["plan"]


def test_two_plan_sentences_next_to_each_other_can_serve_one_source_sentence():
    plan = "Every open question is listed. The window shows them on one screen, answered from the phone."
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "words"


@pytest.mark.parametrize("source, plan", [
    (SRC, "Open pull requests that wait on the owner's merge are shown on one screen."),
    ("The lens should guide me on how to set up the shot and choose an angle.", "The camera app records the shot after the user picks a lens."),
    ("Cache the sessions on disk so the window opens fast after a restart.", "Sessions older than 30 days are archived to the cloud, and the window shows a count."),
    ("Agents should write short replies and put the answer first in every message.", "Every message to the owner is a card with a status line and the first answer."),
])
def test_a_plan_on_the_same_topic_that_says_something_else_does_not_serve_it(source, plan):
    (it,) = run(plan, source)["items"]
    assert it["status"] == "unserved"


@pytest.mark.parametrize("source, plan", [
    ("The lens should guide me on how to set up the shot and choose an angle.", "Shot guide: the lens tells the user how to set up the shot and pick an angle."),
    ("Documentation should describe the end state and not the process of making decisions.", "Docs describe the end state. Decisions live in the PR."),
    ("The plan must not drop the details I wrote in my prompts.", "The plan keeps the details the owner wrote in his prompts."),
])
def test_paraphrases_are_served(source, plan):
    (it,) = run(plan, source)["items"]
    assert it["status"] == "served"


def test_a_sentence_under_an_out_of_scope_heading_is_served_as_set_aside():
    plan = ("# Plan\n\nThe window lists every open question for the owner.\n\n## Out of scope\n\n"
            "- The cellar app lists every open question on one screen so that the owner can answer from a phone.\n\n"
            "## Next\n\nShip the window.\n")
    (it,) = run(plan, "The cellar app should list every open question on one screen so that I can answer from my phone.")["items"]
    assert it["status"] == "served" and it["via"] == "out of scope"


def test_the_out_of_scope_section_ends_at_the_next_heading_of_its_level():
    plan = ("## Out of scope\n\nNothing about atlas here.\n\n## Scope\n\n"
            "The window lists every open question on one screen and the owner answers from the phone.\n")
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "words"


def test_an_out_of_scope_line_covers_the_list_that_follows_it():
    plan = ("Scope is the window.\n\n**Deferred:**\n- the window lists every open question on one screen for the owner, answered from the phone\n\n"
            "Done.\n")
    (it,) = run(plan, SRC)["items"]
    assert it["status"] == "served" and it["via"] == "out of scope"


# --- Russian ------------------------------------------------------------------------------

def test_a_russian_plan_serves_a_russian_sentence_through_suffix_stripping():
    (it,) = run(RU_PLAN, RU_WANT)["items"]
    assert it["status"] == "served" and it["via"] == "words"
    assert ic.stem("\u0432\u043e\u043f\u0440\u043e\u0441\u044b") == ic.stem("\u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432") == ic.stem("\u0432\u043e\u043f\u0440\u043e\u0441\u043e\u043c")


def test_a_russian_sentence_against_an_english_plan_waits_for_the_model_instead_of_failing():
    res = run("The window lists every open question on one screen.", RU_WANT, RU_OTHER, "The camera must show a level guide before every shot.")
    got = by_status(res)
    assert got["needs_model"] == [RU_WANT, RU_OTHER]
    assert got["unserved"] == ["The camera must show a level guide before every shot."]
    assert (res["served"], res["unserved"], res["needs_model"], res["total"]) == (0, 1, 2, 3)


def test_a_russian_sentence_not_in_a_russian_plan_is_unserved():
    (it,) = run(RU_PLAN, RU_OTHER)["items"]
    assert it["status"] == "unserved"


def test_an_english_plan_that_quotes_the_russian_source_serves_it():
    (it,) = run(f'He wrote: "{RU_WANT}"', RU_WANT)["items"]
    assert it["status"] == "served" and it["via"] == "quote"


# --- the command --------------------------------------------------------------------------

def cover(capsys, *argv) -> tuple[int, str, str]:
    rc = cli.main(["intent", "cover", *argv])
    out = capsys.readouterr()
    return rc or 0, out.out, out.err


def write_plan(tmp_path, text: str, name="plan.md") -> str:
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_exit_one_and_the_unserved_sentences_grouped_by_entry(tmp_path, capsys):
    keep("atlas", "The window should list every open question on one screen so that I can answer from my phone.\n"
                  "The plan must not drop the details I wrote in my prompts.", session="aaaa1111")
    keep("atlas", "Documentation should describe the end state and not the process of making decisions.", minutes=600, session="bbbb2222")
    plan = write_plan(tmp_path, "The window lists all open questions on a single screen; the owner answers from the phone.\n")
    rc, out, _ = cover(capsys, plan, "--product", "atlas")
    lines = out.splitlines()
    assert rc == 1 and lines[0] == "served 1 of 3"
    assert "Unserved (2)" in out
    assert out.index("session aaaa1111") < out.index("The plan must not drop") < out.index("session bbbb2222") < out.index("Documentation should")
    assert "list every open question" not in out.split("Unserved")[1]


def test_exit_zero_when_everything_is_served_or_waits_for_the_model(tmp_path, capsys):
    keep("atlas", f"The window should list every open question on one screen so that I can answer from my phone.\n{RU_WANT}")
    plan = write_plan(tmp_path, "The window lists all open questions on a single screen; the owner answers from the phone.\n")
    rc, out, _ = cover(capsys, plan, "--product", "atlas")
    assert rc == 0 and out.splitlines()[0] == "served 1 of 2"
    assert "Needs --model (1)" in out and "Unserved" not in out


def test_json_carries_every_sentence_with_its_verdict(tmp_path, capsys):
    keep("atlas", f"The plan must not drop the details I wrote in my prompts.\n{RU_WANT}")
    plan = write_plan(tmp_path, "The plan keeps the details the owner wrote in his prompts.\n")
    rc, out, _ = cover(capsys, plan, "--product", "atlas", "--json")
    d = json.loads(out)
    assert rc == 0 and (d["served"], d["unserved"], d["needs_model"], d["total"]) == (1, 0, 1, 2)
    assert d["product"] == "atlas" and d["entries"] == 1 and d["model"]["calls"] == 0
    assert [(i["status"], i["via"]) for i in d["items"]] == [("served", "words"), ("needs_model", "")]


def test_since_and_last_choose_the_entries(tmp_path, capsys):
    keep("atlas", "The first entry says the window should list every open question.", when=dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.timezone.utc), session="old00000")
    keep("atlas", "The second entry says the plan must keep every detail I wrote.", when=dt.datetime(2026, 10, 10, 9, 0, tzinfo=dt.timezone.utc), session="mid00000")
    keep("atlas", "The third entry says the camera must show a level guide always.", when=dt.datetime(2026, 10, 16, 9, 0, tzinfo=dt.timezone.utc), session="new00000")
    plan = write_plan(tmp_path, "Nothing relevant here at all.\n")
    assert cover(capsys, plan, "--product", "atlas")[1].splitlines()[0] == "served 0 of 3"
    assert cover(capsys, plan, "--product", "atlas", "--since", "2026-10-05")[1].splitlines()[0] == "served 0 of 2"
    assert cover(capsys, plan, "--product", "atlas", "--last", "1")[1].splitlines()[0] == "served 0 of 1"
    assert cover(capsys, plan, "--product", "atlas", "--since", "2026-10-05", "--last", "1")[1].splitlines()[0] == "served 0 of 1"


def test_the_product_defaults_to_the_repo_of_the_plan(tmp_path, capsys):
    repo = tmp_path / "repos" / "cellar"
    (repo / ".git").mkdir(parents=True)
    (repo / "docs").mkdir()
    keep("cellar", "The window should list every open question on one screen so that I can answer from my phone.")
    keep("atlas", "The plan must not drop the details I wrote in my prompts.")
    plan = write_plan(repo / "docs", "The window lists all open questions on a single screen; the owner answers from the phone.\n")
    rc, out, _ = cover(capsys, plan)
    assert rc == 0 and out.splitlines()[0] == "served 1 of 1"


def test_errors_say_what_is_missing(tmp_path, capsys):
    plan = write_plan(tmp_path, "A plan.\n")
    rc, _, err = cover(capsys, plan, "--product", "atlas")
    assert rc == 2 and "no intent recorded for atlas" in err
    keep("atlas", "The plan must not drop the details I wrote in my prompts.")
    rc, _, err = cover(capsys, str(tmp_path / "missing.md"), "--product", "atlas")
    assert rc == 2 and "cannot read the plan" in err
    rc, _, err = cover(capsys, plan, "--product", "atlas", "--since", "yesterday")
    assert rc == 64 and "YYYY-MM-DD" in err
    rc, _, err = cover(capsys, plan, "--product", "atlas", "--last", "0")
    assert rc == 64
    rc, _, err = cover(capsys, "--product", "atlas")
    assert rc == 64 and "usage" in err
    rc, _, err = cover(capsys, plan, "--product", "atlas", "--since", "2030-01-01")
    assert rc == 2 and "no entries" in err


# --- the model pass -----------------------------------------------------------------------

def reply(results, cost=0.0021):
    return 0, json.dumps({"result": json.dumps({"results": results}), "total_cost_usd": cost, "duration_ms": 900})


def unresolved_run(monkeypatch, replies, batch=None):
    """A run with one Russian and one English unresolved sentence; `replies` answers each call in turn."""
    monkeypatch.setattr(ic, "model_unavailable", lambda: None)
    if batch:
        monkeypatch.setattr(ic, "BATCH", batch)
    sent = []

    def call(cmd, input_text):
        sent.append((cmd, json.loads(input_text)))
        return replies[len(sent) - 1]
    monkeypatch.setattr(ic, "_call", call)
    res = run("The window lists every open question on one screen.", RU_WANT, "The camera must show a level guide before every shot.", model=True)
    return res, sent


def test_the_model_pass_settles_what_words_could_not(monkeypatch):
    res, sent = unresolved_run(monkeypatch, [reply([{"id": 0, "served": True, "where": "Window lists open questions"},
                                                    {"id": 1, "served": False, "where": ""}])])
    assert [(i["status"], i["via"]) for i in res["items"]] == [("served", "model"), ("unserved", "")]
    assert res["items"][0]["plan"] == "Window lists open questions"
    assert (res["served"], res["unserved"], res["needs_model"]) == (1, 1, 0)
    assert res["model"]["calls"] == 1 and res["model"]["judged"] == 2 and res["model"]["cost_usd"] == pytest.approx(0.0021)
    (cmd, payload), = sent
    assert payload["plan"].startswith("The window lists") and [s["id"] for s in payload["sentences"]] == [0, 1]
    assert payload["sentences"][0]["text"] == RU_WANT


def test_the_call_is_the_state_brief_call_with_another_system_prompt():
    cmd, brief = ic.cover_command(), state.brief_command()
    assert cmd[0] == "claude" and "-p" in cmd and "--model" in cmd and cmd[cmd.index("--model") + 1] == state.BRIEF_MODEL
    i = cmd.index("--system-prompt")
    assert cmd[:i] == brief[:i] and cmd[i + 1] == ic.COVER_SYSTEM and cmd[i + 1] != brief[i + 1] and len(cmd) == len(brief)
    assert cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd and "--strict-mcp-config" in cmd


def test_call_goes_through_the_brief_runner(monkeypatch):
    seen = []
    monkeypatch.setattr(state, "_run_claude", lambda cmd, text, timeout=0: seen.append((cmd, text, timeout)) or (0, "{}"))
    assert REAL_CALL(["claude"], "in") == (0, "{}")
    assert seen == [(["claude"], "in", state.BRIEF_TIMEOUT_S)]


def test_the_model_runs_in_batches(monkeypatch):
    res, sent = unresolved_run(monkeypatch, [reply([{"id": 0, "served": True, "where": ""}]),
                                             reply([{"id": 0, "served": True, "where": ""}])], batch=1)
    assert len(sent) == 2 and res["model"]["calls"] == 2 and res["served"] == 2


def test_a_reply_that_does_not_validate_leaves_the_verdicts_as_they_were(monkeypatch):
    res, _ = unresolved_run(monkeypatch, [reply([{"id": 0, "served": True}, {"id": 0, "served": False}])])
    assert [i["status"] for i in res["items"]] == ["needs_model", "unserved"] and res["model"]["error"]
    res, _ = unresolved_run(monkeypatch, [(1, "")])
    assert res["model"]["error"] == "claude exited 1" and res["needs_model"] == 1
    res, _ = unresolved_run(monkeypatch, [(0, "not json")])
    assert res["model"]["error"].startswith("unusable reply") and res["needs_model"] == 1


def test_validate_cover():
    ok = ic.validate_cover({"results": [{"id": 0, "served": True, "where": "a b c"}, {"id": 1, "served": False}]}, {0, 1, 2})
    assert ok == {0: (True, "a b c"), 1: (False, "")}
    for bad in ({"results": [{"id": 3, "served": True}]}, {"results": [{"id": 0, "served": "yes"}]},
                {"results": [{"id": 0, "served": True}, {"id": 0, "served": True}]}, {"results": "x"}, [], None,
                {"results": [{"id": True, "served": True}]}):
        assert ic.validate_cover(bad, {0, 1}) is None


def test_the_model_is_off_in_safe_mode_and_without_claude(monkeypatch):
    from teyla import config
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert "safe mode" in ic.model_unavailable()
    monkeypatch.delenv("TEYLA_SAFE")
    monkeypatch.setattr(ic.shutil, "which", lambda name: None)
    assert ic.model_unavailable() == "no claude on PATH"
    monkeypatch.setattr(ic.shutil, "which", lambda name: "/usr/bin/claude")
    assert ic.model_unavailable() is None
    res = run("A plan.", "The camera must show a level guide before every shot.", model=False)
    assert res["model"]["calls"] == 0


def test_the_command_reports_the_model_pass_and_gates_on_what_is_left(tmp_path, capsys, monkeypatch):
    keep("atlas", f"{RU_WANT}\nThe camera must show a level guide before every shot.")
    plan = write_plan(tmp_path, "The window lists every open question on one screen.\n")
    monkeypatch.setattr(ic, "model_unavailable", lambda: None)
    monkeypatch.setattr(ic, "_call", lambda cmd, text: reply([{"id": 0, "served": True, "where": "w"}, {"id": 1, "served": False}]))
    rc, out, _ = cover(capsys, plan, "--product", "atlas", "--model")
    assert rc == 1 and out.splitlines()[0] == "served 1 of 2"
    assert "(1 by the model)" in out and "model pass: 1 call(s), 2 judged, $0.0021" in out and "Unserved (1)" in out
    monkeypatch.setattr(ic, "model_unavailable", lambda: "safe mode is on, and the owner's prompts stay on this machine")
    rc, out, _ = cover(capsys, plan, "--product", "atlas", "--model")
    assert "model pass skipped: safe mode" in out and "Needs --model (1)" in out
