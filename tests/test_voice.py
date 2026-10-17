"""`teyla voice check`: charts built in tmp dirs, drafts invented here, no model call ever starts
(`voice._run` and `state._run_claude` are replaced wherever `--model` runs). Russian is written as
\\u escapes, because the repo's leak check flags literal Cyrillic outside allow-listed files.
The Spanish strings are test input for the language guess, like the Russian ones."""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from teyla import cli, config, state, voice

ROOT = pathlib.Path(__file__).resolve().parent.parent

RU_BAD = "\u0418\u043d\u043d\u043e\u0432\u0430\u0446\u0438\u043e\u043d\u043d\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u0434\u043b\u044f \u0432\u0430\u0441"
RU_OK = "\u042f \u0438\u0437\u043c\u0435\u0440\u0438\u043b \u0434\u043b\u0438\u043d\u0443 \u043e\u0442\u0432\u0435\u0442\u043e\u0432. \u041c\u0435\u0434\u0438\u0430\u043d\u0430 \u0440\u0430\u0432\u043d\u0430 150 \u0441\u043b\u043e\u0432."
ES_OK = "Cinco rechazos de tienda en cinco semanas. Cada uno costó entre uno y seis días."

EN_CHART = """---
lang: en
max_sentence_words: 10
max_post_chars:
  x_post: 100
  video_hook_15s: 60
emoji_max: 1
hashtags_max: 0
exclamations_max: 0
# a comment line
banned:
  - delve
  - robust
  - leverag*
  - game-changer
  - it's important to note
preferred: [shipped, measured]
---
# Voice chart: test

Body text the model sees.
"""

RU_CHART = """---
lang: ru
max_sentence_words: 12
banned:
  - \u0438\u043d\u043d\u043e\u0432\u0430\u0446\u0438\u043e\u043d\u043d*
  - \u0434\u0430\u0432\u0430\u0439\u0442\u0435 \u0440\u0430\u0437\u0431\u0435\u0440\u0451\u043c\u0441\u044f
---
"""


@pytest.fixture
def charts(tmp_path):
    d = tmp_path / "charts"
    d.mkdir()
    (d / "en.md").write_text(EN_CHART, encoding="utf-8")
    (d / "ru.md").write_text(RU_CHART, encoding="utf-8")
    return d


def draft(tmp_path, text, name="draft.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def run(argv, capsys):
    code = cli.main(["voice", "check", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# --- front matter -----------------------------------------------------------------------------

def test_front_matter_reads_scalars_lists_and_maps():
    meta, body = voice.parse_front_matter(EN_CHART)
    assert meta["lang"] == "en" and meta["max_sentence_words"] == 10
    assert meta["max_post_chars"] == {"x_post": 100, "video_hook_15s": 60}
    assert meta["banned"][:2] == ["delve", "robust"] and "it's important to note" in meta["banned"]
    assert meta["preferred"] == ["shipped", "measured"]
    assert body.startswith("# Voice chart")


def test_front_matter_inline_list_keeps_quoted_commas_and_inline_map():
    meta, _ = voice.parse_front_matter('---\nbanned: [a, "b, c", \'d\']\nmax_post_chars: {x_post: 280, linkedin_update: 900}\n---\n')
    assert meta["banned"] == ["a", "b, c", "d"]
    assert meta["max_post_chars"] == {"x_post": 280, "linkedin_update": 900}


@pytest.mark.parametrize("text,needle", [
    ("no front matter", "no front matter"),
    ("---\nlang: en\n", "not closed"),
    ("---\nlang en\n---\n", "key: value"),
    ("---\n  - orphan\n---\n", "no key above"),
    ("---\nbanned:\n  - a\n  k: v\n---\n", "mixes a map"),
    ("---\nbanned:\n  k: v\n  - a\n---\n", "mixes a list"),
])
def test_front_matter_errors_name_the_problem(text, needle):
    with pytest.raises(voice.ChartError, match=needle):
        voice.parse_front_matter(text)


def test_load_chart_validates_the_schema(tmp_path):
    def load(front):
        p = tmp_path / "c.md"
        p.write_text(f"---\n{front}\n---\n", encoding="utf-8")
        return voice.load_chart(p)
    assert load("lang: es\nmax_sentence_words: 22").max_sentence_words == 22
    for front, needle in [("lang: fr", "`lang`"), ("lang: en\nmax_sentence_words: 0", "max_sentence_words"),
                          ("lang: en\nemoji_max: -1", "emoji_max"), ("lang: en\nmax_post_chars: 5", "max_post_chars"),
                          ("lang: en\nmax_post_chars:\n  tweet: 5", "unknown format"),
                          ("lang: en\nmax_post_chars:\n  x_post: abc", "positive number"),
                          ("lang: en\nbanned: nope", "list of phrases")]:
        with pytest.raises(voice.ChartError, match=needle):
            load(front)


# --- language guess ---------------------------------------------------------------------------

def test_detect_lang():
    assert voice.detect_lang(RU_OK) == "ru"
    assert voice.detect_lang(ES_OK) == "es"
    assert voice.detect_lang("The fix was a guard that decides for the agents, not a rule.") == "en"
    assert voice.detect_lang("¿Cómo lo mides?  Medir primero.") == "es"
    assert voice.detect_lang("ok") is None                        # too short to say
    assert voice.detect_lang("Teyla Codex TestFlight Claude Opus Sonnet Haiku") is None


# --- the counts -------------------------------------------------------------------------------

def test_banned_phrases_match_whole_words_case_insensitively():
    banned = ["delve", "robust", "leverag*", "it's important to note", "game-changer"]
    hit = lambda t: {h["phrase"] for h in voice.banned_hits(t, banned)}          # noqa: E731
    assert hit("We DELVE into it. A Robust plan.") == {"delve", "robust"}
    assert hit("robustness and delved are other words") == set()
    assert hit("leverage, leverages and leveraged") == {"leverag*"}
    assert hit("It’s  important\nto note this") == {"it's important to note"}   # curly apostrophe, wrapped line
    assert hit("a game-changer!") == {"game-changer"}
    assert hit("the bigger game changer") == set()


def test_banned_phrases_are_unicode_aware():
    banned = [voice._fold(p) for p in ("\u0438\u043d\u043d\u043e\u0432\u0430\u0446\u0438\u043e\u043d\u043d*", "\u0434\u0430\u0432\u0430\u0439\u0442\u0435 \u0440\u0430\u0437\u0431\u0435\u0440\u0451\u043c\u0441\u044f")]
    text = "\u0418\u041d\u041d\u041e\u0412\u0410\u0426\u0418\u041e\u041d\u041d\u041e\u0415 \u0440\u0435\u0448\u0435\u043d\u0438\u0435. \u0414\u0430\u0432\u0430\u0439\u0442\u0435 \u0440\u0430\u0437\u0431\u0435\u0440\u0435\u043c\u0441\u044f."   # capitals; ye for yo
    assert len(voice.banned_hits(text, banned)) == 2
    assert voice.banned_hits("\u0438\u043d\u043d\u043e\u0432\u0430\u0446\u0438\u044f", banned) == []   # the stem needs "-onn"
    assert [h["phrase"] for h in voice.banned_hits("café sinérgico", ["sinérgic*"])] == ["sinérgic*"]


def test_emoji_counts_what_a_reader_sees():
    assert voice.count_emoji("plain text, a check ✓ and ⌘ are not emoji") == 0
    assert voice.count_emoji("\U0001F680") == 1
    assert voice.count_emoji("\U0001F680\U0001F680 ship") == 2
    assert voice.count_emoji("\U0001F468‍\U0001F469‍\U0001F467") == 1             # one family
    assert voice.count_emoji("\U0001F44D\U0001F3FD") == 1                                   # skin tone
    assert voice.count_emoji("\U0001F1EA\U0001F1F8") == 1                                   # a flag
    assert voice.count_emoji("✅ ❤️ 1️⃣") == 3                       # default emoji, VS16, keycap
    assert voice.count_emoji("❤ alone") == 0                                           # text heart, no VS16


def test_hashtags_ignore_links_numbers_and_headings():
    assert voice.count_hashtags("ship it #buildinpublic #ai") == 2
    assert voice.count_hashtags("issue #12 and https://x.example/page#section and # heading") == 0
    assert voice.count_hashtags("#\u0430\u0438") == 1


def test_exclamations_and_post_length():
    assert voice.count_exclamations("Wow! Really!! ¡Si!") == 4
    link = "https://example.com/" + "a" * 100
    assert voice.post_length(f"see {link}", "x_post") == 4 + voice.URL_CHARS                # X counts a link as 23
    assert voice.post_length(f"see {link}", "substack_intro") == 4 + len(link)


def test_a_sentence_ends_after_a_closing_quote():
    assert [n for n, _ in voice.sentences('"We shipped it." We measured it.')] == [3, 3]


def test_sentences_split_on_stops_lines_and_bullets():
    got = [n for n, _ in voice.sentences("One two three. Four five!\nSix seven eight nine?\n- ten eleven\n\n```\ncode block here now\n```")]
    assert got == [3, 2, 4, 2]


# --- the check --------------------------------------------------------------------------------

def test_check_passes_a_clean_draft(charts):
    chart = voice.load_chart(charts / "en.md")
    rep = voice.check("I shipped it. I measured it.", chart, "x_post")
    assert rep["ok"] and rep["findings"] == [] and rep["preferred_used"] == ["shipped", "measured"]
    assert rep["stats"]["sentences"] == 2 and rep["stats"]["longest_sentence"] == 3


def test_check_reports_every_hard_rule(charts):
    chart = voice.load_chart(charts / "en.md")
    text = "We delve into this robust and very long sentence that has far too many words! #ai \U0001F680\U0001F680 " + "x" * 80
    rep = voice.check(text, chart, "x_post")
    rules = {f["rule"] for f in rep["findings"] if f["level"] == "fail"}
    assert rules == {"sentence", "length", "banned", "emoji", "hashtags", "exclamations"}
    assert not rep["ok"]


def test_length_needs_a_format_and_a_limit(charts):
    chart = voice.load_chart(charts / "en.md")
    long = "Word " * 40
    assert voice.check(long.strip() + ".", chart, None)["findings"][0]["rule"] == "sentence"   # no length rule without --format
    rep = voice.check("Short.", chart, "substack_intro")
    assert rep["ok"] and rep["findings"][0] == dict(level="warn", rule="length", message="the chart sets no limit for substack_intro")
    over = voice.check("x " * 40, chart, "video_hook_15s")
    assert any(f["rule"] == "length" and f["chars"] == 79 for f in over["findings"])


def test_a_missing_limit_in_the_chart_checks_nothing(charts):
    chart = voice.load_chart(charts / "ru.md")
    rep = voice.check("Fine. " * 30 + "!!! #tag \U0001F680\U0001F680\U0001F680", chart, "x_post")
    assert rep["ok"]                                                                        # no emoji, hashtag or length caps set


# --- chart resolution -------------------------------------------------------------------------

def test_directory_chart_is_picked_by_flag_or_by_the_drafts_language(charts):
    c, warn = voice.resolve_chart(str(charts), None, RU_OK)
    assert c.lang == "ru" and warn is None
    c, warn = voice.resolve_chart(str(charts), "en", "A plain sentence in English about a guard.")
    assert c.lang == "en" and warn is None
    c, warn = voice.resolve_chart(str(charts), "en", RU_OK)
    assert c.lang == "en" and "reads as ru, the chart is en" in warn


def test_chart_errors(charts, tmp_path):
    with pytest.raises(voice.ChartError, match="cannot tell"):
        voice.resolve_chart(str(charts), None, "ok")
    with pytest.raises(voice.ChartError, match="no es.md"):
        voice.resolve_chart(str(charts), "es", ES_OK)
    with pytest.raises(voice.ChartError, match="is a en chart"):
        voice.resolve_chart(str(charts / "en.md"), "ru", "x")
    with pytest.raises(voice.ChartError, match="no chart at"):
        voice.resolve_chart(str(tmp_path / "nope"), None, "x")


# --- the command ------------------------------------------------------------------------------

def test_cli_pass_and_fail_exit_codes(charts, tmp_path, capsys):
    ok = draft(tmp_path, "I shipped it. I measured it.")
    code, out, _ = run([ok, "--chart", str(charts), "--format", "x_post"], capsys)
    assert code == 0 and out.rstrip().endswith("PASS") and "en chart, x_post" in out
    bad = draft(tmp_path, "We delve into it.", "bad.txt")
    code, out, _ = run([bad, "--chart", str(charts / "en.md")], capsys)
    assert code == 1 and 'FAIL  banned: "delve"' in out and "no --format: the length is not checked" in out


def test_cli_json_and_stdin(charts, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(RU_BAD))
    code, out, _ = run(["-", "--chart", str(charts), "--json"], capsys)
    rep = json.loads(out)
    assert code == 1 and rep["lang"] == "ru" and rep["ok"] is False
    assert [f["rule"] for f in rep["findings"]] == ["banned"] and rep["findings"][0]["phrase"].endswith("*")


def test_wrong_language_only_warns(charts, tmp_path, capsys):
    code, out, _ = run([draft(tmp_path, ES_OK), "--chart", str(charts), "--lang", "en"], capsys)
    assert code == 0 and "warn  language: the draft reads as es, the chart is en" in out


def test_cli_usage_errors_exit_2(charts, tmp_path, capsys):
    code, _, err = run([str(tmp_path / "missing.txt"), "--chart", str(charts), "--lang", "en"], capsys)
    assert code == 2 and "cannot read the draft" in err
    code, _, err = run([draft(tmp_path, "  \n", "empty.txt"), "--chart", str(charts), "--lang", "en"], capsys)
    assert code == 2 and "empty" in err
    code, _, err = run([draft(tmp_path, "Hello there my friend, a plain English line."), "--chart", str(tmp_path / "x")], capsys)
    assert code == 2 and "no chart" in err
    (tmp_path / "broken.md").write_text("no front matter", encoding="utf-8")
    code, _, err = run([draft(tmp_path, "Hello"), "--chart", str(tmp_path / "broken.md")], capsys)
    assert code == 2 and "front matter" in err


# --- the model pass ---------------------------------------------------------------------------

def reply(payload, **over):
    out = {"type": "result", "is_error": False, "result": payload if isinstance(payload, str) else json.dumps(payload),
           "total_cost_usd": 0.0009, "duration_ms": 1800}
    out.update(over)
    return json.dumps(out)


@pytest.fixture
def model_on(monkeypatch):
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/claude")
    seen = []

    def install(code=0, stdout=""):
        def run(cmd, input_text):
            seen.append((cmd, input_text))
            return code, stdout
        monkeypatch.setattr(voice, "_run", run)
        return seen
    return install


def test_model_pass_returns_at_most_three_edits(charts, tmp_path, model_on, capsys):
    edits = [{"quote": f"q{i}", "fix": f"f{i}", "why": "plain"} for i in range(5)] + [{"quote": 7}]
    seen = model_on(0, reply({"rating": 4, "summary": "Close to the chart.", "edits": edits}))
    code, out, _ = run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en", "--model", "--json"], capsys)
    m = json.loads(out)["model"]
    assert code == 0 and m["rating"] == 4 and len(m["edits"]) == 3 and m["edits"][0] == {"quote": "q0", "fix": "f0", "why": "plain"}
    assert m["model"] == state.BRIEF_MODEL and m["cost_usd"] == 0.0009
    cmd, payload = seen[0]
    assert len(seen) == 1 and json.loads(payload)["draft"] == "I shipped it."
    assert "Body text the model sees." in json.loads(payload)["chart"]


def test_model_edits_that_are_not_a_list_are_ignored(charts, tmp_path, model_on, capsys):
    model_on(0, reply({"rating": 3, "summary": "ok", "edits": 1}))
    code, out, _ = run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en", "--model", "--json"], capsys)
    assert code == 0 and json.loads(out)["model"]["edits"] == []


def test_model_command_is_the_brief_call_with_the_voice_prompt():
    cmd, brief = voice.voice_command(), state.brief_command()
    assert cmd[:-1] == brief[:-1] and cmd[-1] == voice.VOICE_SYSTEM != brief[-1]
    assert cmd[cmd.index("--model") + 1] == state.BRIEF_MODEL
    assert cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd and "--strict-mcp-config" in cmd


def test_voice_run_goes_through_the_brief_runner(monkeypatch):
    seen = []
    monkeypatch.setattr(state, "_run_claude", lambda cmd, text: (seen.append((cmd, text)) or (0, "{}")))
    assert voice._run(["claude"], "in") == (0, "{}") and seen == [(["claude"], "in")]


def test_model_failures_never_break_the_check(charts, tmp_path, model_on, capsys):
    for code_, out_, needle in [(1, "", "exited 1"), (0, "not json", "unusable"), (0, reply("[1]"), "not an object"),
                                (0, reply("x", is_error=True), "unusable")]:
        model_on(code_, out_)
        code, out, _ = run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en", "--model"], capsys)
        assert code == 0 and "model pass:" in out and needle in out


def test_model_is_refused_in_safe_mode_and_without_claude(charts, tmp_path, monkeypatch, capsys):
    def boom(cmd, input_text):
        raise AssertionError("claude must not run")
    monkeypatch.setattr(voice, "_run", boom)
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    code, _, err = run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en", "--model"], capsys)
    assert code == 2 and "safe mode" in err
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(voice.shutil, "which", lambda name: None)
    code, _, err = run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en", "--model"], capsys)
    assert code == 2 and "no `claude`" in err


def test_no_model_flag_never_calls_the_model(charts, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(voice, "_run", lambda cmd, text: pytest.fail("the model ran without --model"))
    assert run([draft(tmp_path, "I shipped it."), "--chart", str(charts), "--lang", "en"], capsys)[0] == 0


# --- the template -----------------------------------------------------------------------------

def test_the_voice_template_is_a_valid_chart(tmp_path):
    chart = tmp_path / "en.md"
    shutil.copy(ROOT / "templates" / "voice" / "VOICE.md", chart)
    c = voice.load_chart(chart)
    assert c.lang == "en" and c.max_sentence_words and set(c.max_post_chars) == set(voice.FORMATS)
    assert c.emoji_max is not None and c.hashtags_max is not None and c.exclamations_max is not None
    assert "delve" in c.banned and c.body.startswith("# Voice chart")
