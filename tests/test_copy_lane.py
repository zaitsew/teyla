"""`teyla copy`: brief, write (the model replaced), judge, apply, and the round trip into an xcstrings catalog.
The repo is a tmp dir with generic recipe-app content. No model starts: `copy_lane._run` and `copy_lane._run_lane`
are replaced wherever a call would happen, and `_git`/`_gh` for `--pr`. Russian is \\u escapes."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import cli, config, copy_lane as cl, net

RU_ADD = "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0440\u0435\u0446\u0435\u043f\u0442"               # Add recipe
RU_TITLE = "\u0420\u0435\u0446\u0435\u043f\u0442\u044b"                                                      # Recipes
RU_EMPTY = ("\u0417\u0434\u0435\u0441\u044c \u043f\u043e\u043a\u0430 \u043f\u0443\u0441\u0442\u043e. "
            "\u0414\u043e\u0431\u0430\u0432\u044c\u0442\u0435 \u043f\u0435\u0440\u0432\u044b\u0439 \u0440\u0435\u0446\u0435\u043f\u0442.")
RU_ERROR = ("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c. "
            "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u0435\u0442\u044c \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435.")
RU_OOPS = "\u0423\u043f\u0441, \u043e\u0448\u0438\u0431\u043a\u0430"                                               # Oops, an error
RU_WE = "\u041c\u044b \u043d\u0435 \u0441\u043c\u043e\u0433\u043b\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c"   # We could not save
RU_YOUR = "\u0412\u0430\u0448\u0438 \u0440\u0435\u0446\u0435\u043f\u0442\u044b"                                  # Your recipes
RU_HINT = "\u0420\u0435\u0446\u0435\u043f\u0442 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d"                   # Recipe saved

DESIGN = """# Design: Recipes

## Glossary
| Concept | en | es | ru |
|---|---|---|---|
| recipe | recipe | receta | RU-recipe-term |
| {{trip}} | {{en word}} | {{es word}} | {{ru word}} |

## Voice
UI copy only. The product sounds warm, plain and brief.
Address: you.

## Screens
"""

SCREEN = """job: Browse saved recipes and start a new one.
primary_action: Add recipe
states:
  - empty
  - loaded
  - error
string_keys:
  - recipe.list.title
  - recipe.list.add
  - recipe.list.empty
  - recipe.list.error
  - recipe.list.saved
  - recipe.list.missing
"""

VOICE_SCREEN = """job: Talk to the assistant.
primary_action: Hold to talk
kind: voice
string_keys:
  - assistant.ready
state_notes:
  listening:
    hears: a soft tone
    reads: Listening
"""


def unit(value, state="translated"):
    return {"stringUnit": {"state": state, "value": value}}


def catalog_data():
    return {"sourceLanguage": "en", "version": "1.0", "strings": {
        "recipe.list.title": {"localizations": {"en": unit("Your Recipes"), "es": unit("Tus recetas")}},
        "recipe.list.add": {"localizations": {"en": unit("Add recipe"), "de": unit("Hinzufuegen")}},
        "recipe.list.empty": {"localizations": {"en": unit("No recipes yet. Tap Add recipe to start.")}},
        "recipe.list.error": {"localizations": {"en": unit("Oops! We could not save.")}},
        "recipe.list.saved": {"localizations": {"en": unit("Saved %lld recipes")}},
        "unrelated.key": {"comment": "kept", "localizations": {"fr": unit("Salut")}},
        "zeta.key": {},
    }}


def dump(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, separators=(",", " : ")) + "\n"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "recipes"
    (r / "design" / "screens").mkdir(parents=True)
    (r / "App").mkdir()
    (r / "DESIGN.md").write_text(DESIGN, encoding="utf-8")
    (r / "design" / "screens" / "recipe.list.yaml").write_text(SCREEN, encoding="utf-8")
    (r / "design" / "screens" / "assistant.yaml").write_text(VOICE_SCREEN, encoding="utf-8")
    (r / "App" / "Localizable.xcstrings").write_text(dump(catalog_data()), encoding="utf-8")
    return r


def run(argv, capsys):
    code = cli.main(["copy", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def make_brief(repo, capsys, screen="recipe.list", name="brief.md"):
    path = repo.parent / name
    code, out, err = run(["brief", str(repo), screen, "--out", str(path)], capsys)
    assert code == 0, err
    return path


# --- brief ------------------------------------------------------------------------------------------

def test_brief_holds_the_screen_states_glossary_controls_budgets_and_spanish_locale(repo, capsys):
    code, out, err = run(["brief", str(repo), "recipe.list"], capsys)
    assert code == 0, err
    assert "# Copy brief: recipes / recipe.list" in out
    assert "Job: Browse saved recipes and start a new one." in out and "Primary action: Add recipe" in out
    assert "es-ES" in out and "never translated" in out
    assert "| recipe | recipe | receta | RU-recipe-term |" in out and "{{trip}}" not in out.split("<!-- teyla:copy-spec -->")[0]
    assert "warm, plain and brief" in out
    rows = {r["key"]: r for r in cl.parse_spec(out)["rows"]}
    assert rows["recipe.list.add"]["control"] == "button" and rows["recipe.list.add"]["budget"] == "3 words"
    assert rows["recipe.list.title"]["control"] == "title" and rows["recipe.list.title"]["budget"] == "5 words"
    assert (rows["recipe.list.empty"]["control"], rows["recipe.list.empty"]["state"]) == ("empty", "empty")
    assert (rows["recipe.list.error"]["control"], rows["recipe.list.error"]["state"]) == ("error", "error")
    assert rows["recipe.list.error"]["budget"] == "2 sentences" and rows["recipe.list.saved"]["control"] == "text"
    assert rows["recipe.list.title"]["current"] == {"en": "Your Recipes", "es": "Tus recetas", "ru": ""}
    assert any("recipe.list.missing is in no catalog" in n for n in cl.parse_spec(out)["notes"])


def test_brief_infers_a_button_from_the_primary_action_and_honours_overrides(repo, capsys):
    (repo / "design" / "screens" / "recipe.list.yaml").write_text(
        SCREEN + "controls:\n  recipe.list.saved: label\nkey_states:\n  recipe.list.saved: loaded\n", encoding="utf-8")
    spec = cl.parse_spec(run(["brief", str(repo), "recipe.list"], capsys)[1])
    rows = {r["key"]: r for r in spec["rows"]}
    assert rows["recipe.list.add"]["control"] == "button"            # the key has no "button"; the text is the primary action
    assert (rows["recipe.list.saved"]["control"], rows["recipe.list.saved"]["state"]) == ("label", "loaded")


def test_a_voice_screen_gets_the_six_states_with_hears_and_reads(repo, capsys):
    code, out, err = run(["brief", str(repo), "assistant"], capsys)
    assert code == 0, err
    for s in cl.VOICE_STATES:
        assert f"| {s} |" in out
    assert "| listening | a soft tone | Listening |" in out and "| failed | (write it) | (write it) |" in out
    assert "voice screen" in out


def test_brief_errors_name_the_fix(repo, capsys):
    code, _, err = run(["brief", str(repo), "nope"], capsys)
    assert code == 2 and "no design/screens/nope.yaml" in err and "assistant, recipe.list" in err
    code, _, err = run(["brief", str(repo)], capsys)
    assert code == 2 and "usage: teyla copy brief" in err
    (repo / "design" / "screens" / "empty.yaml").write_text("job: x\n", encoding="utf-8")
    assert "no string_keys" in run(["brief", str(repo), "empty"], capsys)[2]


def test_brief_reports_the_voice_charts_and_their_gaps(repo, capsys):
    d = repo / "brand" / "voice"
    d.mkdir(parents=True)
    (d / "en.md").write_text("---\nlang: en\nbanned: [oops]\n---\n# Chart\n\n## Accepted lines\n- Add recipe\n", encoding="utf-8")
    out = run(["brief", str(repo), "recipe.list"], capsys)[1]
    assert "- en: `voice/en.md`, 1/10 accepted and 0/5 rejected example lines (incomplete); banned: oops" in out
    assert "- es: no chart" in out and "en chart is incomplete" in out


# --- write --------------------------------------------------------------------------------------------

REPLIES = {
    "en": {"recipe.list.title": "Recipes", "recipe.list.add": "Add recipe", "recipe.list.empty": "No recipes yet. Add your first one.",
           "recipe.list.error": "Could not save. Check your connection and try again.", "recipe.list.saved": "Saved %lld recipes",
           "recipe.list.missing": "Hint"},
    "es": {"recipe.list.title": "Recetas", "recipe.list.add": "A\u00f1adir receta", "recipe.list.empty": "A\u00fan no hay recetas. A\u00f1ade la primera.",
           "recipe.list.error": "No se pudo guardar. Revisa la conexi\u00f3n e int\u00e9ntalo de nuevo.", "recipe.list.saved": "%lld recetas guardadas",
           "recipe.list.missing": "Pista"},
    "ru": {"recipe.list.title": RU_TITLE, "recipe.list.add": RU_ADD, "recipe.list.empty": RU_EMPTY,
           "recipe.list.error": RU_ERROR, "recipe.list.saved": RU_HINT + " %lld", "recipe.list.missing": RU_HINT},
}


def claude_reply(rows):
    return json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.01, "duration_ms": 900,
                       "result": json.dumps({"rows": [dict(key=k, text=t) for k, t in rows.items()]})})


@pytest.fixture
def model(monkeypatch):
    seen = []

    def fake(cmd, text):
        payload = json.loads(text)
        seen.append((cmd, payload))
        return 0, claude_reply(REPLIES[payload["language"]])

    monkeypatch.setattr(cl, "_run", fake)
    return seen


def test_write_dry_prints_one_prompt_per_language_and_calls_nothing(repo, capsys, monkeypatch):
    monkeypatch.setattr(cl, "_run", lambda *a: pytest.fail("a model call started"))
    brief = make_brief(repo, capsys)
    code, out, err = run(["write", str(brief), "--dry"], capsys)
    assert code == 0, err
    assert out.count("\n--- system ---\n") == 3 and "=== en ===" in out and "=== es ===" in out and "=== ru ===" in out
    assert "model: claude-sonnet-5-5" in out and "Spanish as written in Spain (es-ES)" in out
    assert not (repo.parent / "copy.json").exists()


def test_each_language_prompt_holds_only_that_languages_text(repo, capsys):
    spec = cl.parse_spec(brief_text := run(["brief", str(repo), "recipe.list"], capsys)[1])
    en, es = cl.language_payload(spec, "en"), cl.language_payload(spec, "es")
    assert [r["current"] for r in en["rows"]][0] == "Your Recipes" and [r["current"] for r in es["rows"]][0] == "Tus recetas"
    assert "Tus recetas" not in json.dumps(en) and "Your Recipes" not in json.dumps(es)
    assert "receta" in json.dumps(es["glossary"]) and "receta" not in json.dumps(en["glossary"])
    assert "Hinzufuegen" not in json.dumps(es) and "RU-recipe-term" not in json.dumps(es)
    assert en["screen"]["job"] and "warm, plain" in en["voice_chart"]["text"]            # no chart: DESIGN.md's voice section
    assert brief_text


def test_write_makes_one_call_per_language_and_one_table(repo, capsys, model):
    brief = make_brief(repo, capsys)
    code, out, err = run(["write", str(brief)], capsys)
    assert code == 0, err
    assert [p["language"] for _, p in model] == ["en", "es", "ru"]
    cmd = model[0][0]
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5" and "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--no-session-persistence" in cmd and cl.WRITER_SYSTEM in cmd
    copy = json.loads((repo.parent / "copy.json").read_text(encoding="utf-8"))
    assert copy["written"] == ["en", "es", "ru"] and copy["screen"] == "recipe.list" and len(copy["rows"]) == 6
    row = {r["key"]: r for r in copy["rows"]}["recipe.list.title"]
    assert (row["control"], row["state"], row["budget"], row["en"], row["es"], row["ru"]) == ("title", "all", "5 words", "Recipes", "Recetas", RU_TITLE)
    assert row["was"]["en"] == "Your Recipes"
    md = (repo.parent / "copy.md").read_text(encoding="utf-8")
    assert "| key | control | state | budget | en | es | ru |" in md and "`recipe.list.add` | button | all | 3 words | Add recipe |" in md
    assert "3 calls, $0.03" in out and "next: teyla copy judge" in out


def test_write_one_language_keeps_the_others_as_they_are(repo, capsys, model):
    brief = make_brief(repo, capsys)
    assert run(["write", str(brief), "--lang", "es"], capsys)[0] == 0
    assert [p["language"] for _, p in model] == ["es"]
    row = {r["key"]: r for r in json.loads((repo.parent / "copy.json").read_text(encoding="utf-8"))["rows"]}["recipe.list.title"]
    assert row["en"] == "Your Recipes" and row["es"] == "Recetas" and row["ru"] == ""


def test_write_refuses_a_reply_with_a_missing_key_and_writes_nothing(repo, capsys, monkeypatch):
    monkeypatch.setattr(cl, "_run", lambda cmd, text: (0, claude_reply({"recipe.list.title": "Recipes"})))
    code, _, err = run(["write", str(make_brief(repo, capsys))], capsys)
    assert code == 2 and "reply was unusable" in err and "no text for 5 of 6 keys" in err
    assert not (repo.parent / "copy.json").exists()
    monkeypatch.setattr(cl, "_run", lambda cmd, text: (1, ""))
    assert "claude exited 1" in run(["write", str(repo.parent / "brief.md")], capsys)[2]
    monkeypatch.setattr(cl, "_run", lambda cmd, text: (0, "not json"))
    assert "reply was unusable" in run(["write", str(repo.parent / "brief.md")], capsys)[2]


def test_write_does_not_overwrite_kept_rows_without_force(repo, capsys, model):
    brief = make_brief(repo, capsys)
    assert run(["write", str(brief)], capsys)[0] == 0
    j = repo.parent / "copy.json"
    copy = json.loads(j.read_text(encoding="utf-8"))
    copy["rows"][0]["keep"] = True
    j.write_text(json.dumps(copy), encoding="utf-8")
    code, _, err = run(["write", str(brief)], capsys)
    assert code == 2 and "has kept rows" in err
    assert run(["write", str(brief), "--force"], capsys)[0] == 0
    assert "keep" not in json.loads(j.read_text(encoding="utf-8"))["rows"][0]


def test_write_and_judge_model_are_closed_in_safe_mode(repo, capsys, model, monkeypatch):
    brief = make_brief(repo, capsys)
    monkeypatch.setenv(config.SAFE_ENV, "1")
    code, _, err = run(["write", str(brief)], capsys)
    assert code == 2 and "safe mode" in err and not model
    assert run(["write", str(brief), "--dry"], capsys)[0] == 0                 # printing a prompt is not a call


def test_write_rejects_a_file_that_is_not_a_brief(repo, capsys):
    p = repo.parent / "x.md"
    p.write_text("# nothing\n", encoding="utf-8")
    assert "not a copy brief" in run(["write", str(p)], capsys)[2]
    assert "--lang takes en, es, ru" in run(["write", str(p), "--lang", "fr"], capsys)[2]


# --- judge: the code checks ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,lang,control,rule", [
    ("Add recipe", "en", "button", None),
    ("Save changes", "en", "button", None),
    ("Add a new recipe now", "en", "button", "budget"),
    ("OK", "en", "button", "verb"),
    ("Submit", "en", "button", "verb"),
    ("Recipes", "en", "button", "verb"),
    ("Please sign in", "en", "text", "please"),
    ("Saved!", "en", "text", "bang"),
    ("Oops, that failed. Try again.", "en", "error", "oops"),
    ("Uh-oh. Something broke.", "en", "text", "oops"),
    ("Could not save. Check your connection and try again.", "en", "error", None),
    ("We could not save. Try again.", "en", "error", "we"),
    ("We saved your recipe.", "en", "text", None),                         # "we" is only an error rule
    ("Could not save. Check the network. Try again.", "en", "error", "budget"),
    ("No recipes yet. Add your first one. It takes a minute.", "en", "empty", "budget"),
    ("Your Recipes", "en", "title", "your"),
    ("Your recipe is saved.", "en", "title", None),                       # a sentence, not a label
    ("Recipes for the week ahead and more", "en", "title", "budget"),
    ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone.", "en", "text", "budget"),
    ("Reading step " + "word " * 25, "en", "step", "budget"),
    ("A\u00f1adir receta", "es", "button", None),
    ("A\u00f1ade una receta nueva", "es", "button", "budget"),
    ("Receta", "es", "button", "verb"),
    ("Ups, algo fall\u00f3.", "es", "error", "oops"),
    ("No pudimos guardar. Int\u00e9ntalo de nuevo.", "es", "error", "we"),
    ("Tus recetas", "es", "title", "your"),
    ("Por favor, espera", "es", "text", "please"),
    (RU_ADD, "ru", "button", None),
    (RU_TITLE, "ru", "button", "verb"),
    (RU_OOPS, "ru", "error", "oops"),
    (RU_WE, "ru", "error", "we"),
    (RU_YOUR, "ru", "title", "your"),
    (RU_ERROR, "ru", "error", None),
    ("", "en", "text", "empty"),
    ("Zero\u200bwidth", "en", "text", "hidden"),
])
def test_check_text_rules(text, lang, control, rule):
    got = {f["rule"] for f in cl.check_text(text, lang, control)}
    assert got == ({rule} if rule else set()), (text, got)


def test_check_text_placeholders_must_match_english():
    assert cl.check_text("%lld recetas", "es", "text", "Saved %lld recipes") == []
    assert cl.check_text("%1$@ y %2$@", "es", "text", "%@ and %@") == []                   # position markers may reorder
    f = cl.check_text("recetas", "es", "text", "Saved %lld recipes")
    assert [x["rule"] for x in f] == ["placeholders"]
    assert [x["rule"] for x in cl.check_text("Hola {name}", "es", "text", "Hello")] == ["placeholders"]
    assert cl.count_words("Delete %@") == 2 and cl.count_words("Delete {name} now") == 3


def test_check_text_applies_the_voice_charts_banned_words_and_limit(tmp_path):
    from teyla import voice
    p = tmp_path / "en.md"
    p.write_text("---\nlang: en\nmax_sentence_words: 4\nbanned: [seamless*]\nexclamations_max: 0\n---\n", encoding="utf-8")
    chart = voice.load_chart(p)
    f = cl.check_text("A seamless experience for every recipe you save.", "en", "text", "", chart)
    assert {x["rule"] for x in f} == {"chart"} and len(f) == 2
    assert [x["rule"] for x in cl.check_text("Saved!", "en", "text", "", chart)] == ["bang"]      # counted once


# --- judge: the command -------------------------------------------------------------------------------

def table(**over):
    rows = [dict(key="recipe.list.add", control="button", state="all", budget="3 words", en="Add recipe", es="A\u00f1adir receta", ru=RU_ADD),
            dict(key="recipe.list.title", control="title", state="all", budget="5 words", en="Recipes", es="Recetas", ru=RU_TITLE),
            dict(key="recipe.list.error", control="error", state="error", budget="2 sentences", en="Oops! We could not save.",
                 es="Ups, no pudimos guardar.", ru=RU_OOPS)]
    base = dict(version=1, repo="recipes", repo_path="", screen="recipe.list", date="2026-10-30", model="m", written=["en", "es", "ru"],
                glossary=[], charts={}, catalogs=[], rows=rows)
    return {**base, **over}


def put_copy(tmp_path, copy=None, name="copy.json"):
    p = tmp_path / name
    p.write_text(json.dumps(copy or table()), encoding="utf-8")
    return p


def test_judge_marks_every_row_pass_or_fail_with_one_reason(tmp_path, capsys):
    p = put_copy(tmp_path)
    code, out, err = run(["judge", str(p)], capsys)
    assert code == 1, err
    assert "3 rows, 2 pass, 1 fail" in out and "FAIL  recipe.list.error  [error]  en: an interjection" in out and "(+" in out
    copy = json.loads(p.read_text(encoding="utf-8"))
    by = {r["key"]: r for r in copy["rows"]}
    assert by["recipe.list.add"]["verdict"] == "pass" and by["recipe.list.add"]["reason"] == "within budget; rules clear"
    assert by["recipe.list.error"]["verdict"] == "fail" and {f["rule"] for f in by["recipe.list.error"]["findings"]} >= {"oops", "bang", "we"}
    md = (tmp_path / "copy.md").read_text(encoding="utf-8")
    assert "| verdict | reason |" in md and "| pass |" in md and "| fail |" in md


def test_judge_exits_0_when_every_row_passes_and_prints_json(tmp_path, capsys):
    copy = table()
    copy["rows"] = copy["rows"][:2]
    code, out, _ = run(["judge", str(put_copy(tmp_path, copy)), "--json"], capsys)
    assert code == 0 and [r["verdict"] for r in json.loads(out)["rows"]] == ["pass", "pass"]


def test_judge_reads_the_charts_of_the_repo_named_in_the_table(repo, tmp_path, capsys):
    d = repo / "brand" / "voice"
    d.mkdir(parents=True)
    (d / "en.md").write_text("---\nlang: en\nbanned: [recipes]\n---\n", encoding="utf-8")
    copy = table(repo_path=str(repo))
    copy["rows"] = copy["rows"][1:2]
    code, out, _ = run(["judge", str(put_copy(tmp_path, copy))], capsys)
    assert code == 1 and "voice chart (en): banned" in out
    (d / "en.md").write_text("---\nlang: en\nbanned: [seamless]\n---\n", encoding="utf-8")
    assert run(["judge", str(tmp_path / "copy.json")], capsys)[0] == 0
    # --chart points elsewhere
    other = tmp_path / "charts"
    other.mkdir()
    (other / "en.md").write_text("---\nlang: en\nbanned: [recipes]\n---\n", encoding="utf-8")
    assert run(["judge", str(tmp_path / "copy.json"), "--chart", str(other)], capsys)[0] == 1


def test_judge_rejects_a_file_that_is_not_a_table(tmp_path, capsys):
    p = tmp_path / "copy.json"
    p.write_text("[]", encoding="utf-8")
    assert "not a copy table" in run(["judge", str(p)], capsys)[2]
    assert "cannot read" in run(["judge", str(tmp_path / "none.json")], capsys)[2]


# --- judge --model: the second family --------------------------------------------------------------------

def judged_ok(tmp_path, capsys):
    copy = table()
    copy["rows"] = copy["rows"][:2]
    p = put_copy(tmp_path, copy)
    return p


def test_judge_command_pins_the_lane_wrapper_read_only_and_no_skills():
    cmd = cl.judge_command("/x/out.md", "gpt-6.1-sol", "codex-lane")
    assert cmd[0] == "codex-lane" and cmd[cmd.index("-m") + 1] == "gpt-6.1-sol" and cmd[cmd.index("-s") + 1] == "read-only"
    assert "skills.include_instructions=false" in cmd and "multi_agent" in cmd and cmd[-3:] == ["-o", "/x/out.md", "-"] or cmd[-1] == "-"
    assert cmd[cmd.index("-o") + 1] == "/x/out.md"


def test_judge_model_turns_a_row_to_fail_and_never_softens_a_code_fail(tmp_path, capsys, monkeypatch):
    prompts = []

    def lane(prompt, model):
        prompts.append((prompt, model))
        return 0, "```json\n" + json.dumps({"rows": [
            {"key": "recipe.list.add", "verdict": "fail", "reason": "es: reads as a translation"},
            {"key": "recipe.list.title", "verdict": "pass", "reason": "fine"}]}) + "\n```"

    monkeypatch.setattr(cl, "_run_lane", lane)
    copy = table()
    p = put_copy(tmp_path, copy)
    code, out, _ = run(["judge", str(p), "--model"], capsys)
    assert code == 1 and len(prompts) == 1 and prompts[0][1] == "gpt-6.1-sol"
    sent = json.loads(prompts[0][0].split("--- input (JSON) ---\n", 1)[1])
    assert [r["key"] for r in sent["rows"]] == ["recipe.list.add", "recipe.list.title"]          # the code fail is not sent
    by = {r["key"]: r for r in json.loads(p.read_text(encoding="utf-8"))["rows"]}
    assert by["recipe.list.add"]["verdict"] == "fail" and by["recipe.list.add"]["reason"] == "model: es: reads as a translation"
    assert by["recipe.list.title"]["verdict"] == "pass" and by["recipe.list.title"]["model"]["verdict"] == "pass"
    assert by["recipe.list.error"]["verdict"] == "fail" and "model" not in by["recipe.list.error"]
    assert json.loads(p.read_text(encoding="utf-8"))["model_pass"] == dict(asked=2, failed=1, answered=2)


def test_judge_model_failure_keeps_the_code_verdicts_and_exits_3(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cl, "_run_lane", lambda prompt, model: (4, ""))
    p = judged_ok(tmp_path, capsys)
    code, _, err = run(["judge", str(p), "--model"], capsys)
    assert code == 3 and "the model pass failed (codex-lane exited 4)" in err
    monkeypatch.setattr(cl, "_run_lane", lambda prompt, model: (127, ""))
    assert "codex-lane not found" in run(["judge", str(p), "--model"], capsys)[2]
    monkeypatch.setattr(cl, "_run_lane", lambda prompt, model: (0, "I think it is fine"))
    assert "not the JSON asked for" in run(["judge", str(p), "--model"], capsys)[2]


def test_judge_model_is_closed_in_safe_mode_and_asks_nothing_when_all_rows_failed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cl, "_run_lane", lambda *a: pytest.fail("a model call started"))
    p = judged_ok(tmp_path, capsys)
    monkeypatch.setenv(config.SAFE_ENV, "1")
    code, _, err = run(["judge", str(p), "--model"], capsys)
    assert code == 2 and "safe mode" in err
    monkeypatch.delenv(config.SAFE_ENV)
    copy = table()
    copy["rows"] = copy["rows"][2:]
    code, out, _ = run(["judge", str(put_copy(tmp_path, copy, "c2.json")), "--model"], capsys)
    assert code == 1 and "1 rows, 0 pass, 1 fail" in out


def test_lane_binary_prefers_the_env_then_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TEYLA_CODEX_LANE", "/opt/lane")
    assert cl.lane_binary() == "/opt/lane"
    monkeypatch.delenv("TEYLA_CODEX_LANE")
    monkeypatch.setattr(cl.shutil, "which", lambda n: "/usr/bin/codex-lane")
    assert cl.lane_binary() == "/usr/bin/codex-lane"
    monkeypatch.setattr(cl.shutil, "which", lambda n: None)
    monkeypatch.setattr(cl.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    assert cl.lane_binary() is None


# --- apply: the round trip ----------------------------------------------------------------------------

@pytest.fixture
def written(repo, capsys, model):
    brief = make_brief(repo, capsys)
    assert run(["write", str(brief)], capsys)[0] == 0
    return repo.parent / "copy.json"


def cat(repo):
    return json.loads((repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8"))


def test_round_trip_keeps_every_key_and_every_other_language(repo, written, capsys):
    before = cat(repo)
    assert run(["judge", str(written)], capsys)[0] == 0
    code, out, err = run(["apply", str(written), str(repo)], capsys)
    assert code == 0, err
    after = cat(repo)
    assert list(after["strings"]) == list(before["strings"])                                    # no key added, removed or reordered
    assert after["strings"]["unrelated.key"] == before["strings"]["unrelated.key"] and after["strings"]["zeta.key"] == {}
    assert after["strings"]["recipe.list.add"]["localizations"]["de"] == before["strings"]["recipe.list.add"]["localizations"]["de"]
    loc = after["strings"]["recipe.list.title"]["localizations"]
    assert loc["en"]["stringUnit"]["value"] == "Recipes" and loc["es"]["stringUnit"]["value"] == "Recetas"
    assert loc["ru"]["stringUnit"]["value"] == RU_TITLE and loc["ru"]["stringUnit"]["state"] == "translated"
    assert "recipe.list.missing" not in after["strings"]                                          # apply never adds a key
    assert "5 keys" in out and "skipped recipe.list.missing [*]: the key is in no catalog; apply never adds a key" in out
    assert (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8").endswith("}\n")
    # a second apply changes nothing and leaves the file byte-identical
    text = (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8")
    code, out, _ = run(["apply", str(written), str(repo)], capsys)
    assert code == 0 and "0 strings changed" in out and (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8") == text


def test_apply_dry_writes_nothing(repo, written, capsys):
    text = (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8")
    run(["judge", str(written)], capsys)
    code, out, _ = run(["apply", str(written), str(repo), "--dry"], capsys)
    assert code == 0 and "(dry run)" in out and "would write App/Localizable.xcstrings" in out
    assert (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8") == text


def test_apply_keeps_only_the_chosen_rows_and_languages(repo, written, capsys):
    text = (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8")
    code, _, err = run(["apply", str(written), str(repo)], capsys)
    assert code == 2 and "no row is kept" in err                                                 # no judge, no marks, no keys
    assert (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8") == text
    assert run(["apply", str(written), str(repo), "--keys", "recipe.list.add", "--lang", "es"], capsys)[0] == 0
    after = cat(repo)["strings"]
    assert after["recipe.list.add"]["localizations"]["es"]["stringUnit"]["value"] == "A\u00f1adir receta"
    assert "en" in after["recipe.list.add"]["localizations"] and after["recipe.list.add"]["localizations"]["en"]["stringUnit"]["value"] == "Add recipe"
    assert "ru" not in after["recipe.list.add"]["localizations"]                                  # --lang es
    assert after["recipe.list.title"]["localizations"]["en"]["stringUnit"]["value"] == "Your Recipes"      # not chosen
    code, _, err = run(["apply", str(written), str(repo), "--keys", "nope"], capsys)
    assert code == 2 and "no such key in the table: nope" in err


def test_apply_uses_keep_marks_over_verdicts(repo, written, capsys):
    copy = json.loads(written.read_text(encoding="utf-8"))
    for r in copy["rows"]:
        r["verdict"] = "pass"
        r["keep"] = r["key"] == "recipe.list.title"
    written.write_text(json.dumps(copy), encoding="utf-8")
    run(["apply", str(written), str(repo)], capsys)
    after = cat(repo)["strings"]
    assert after["recipe.list.title"]["localizations"]["en"]["stringUnit"]["value"] == "Recipes"
    assert after["recipe.list.add"]["localizations"]["en"]["stringUnit"]["value"] == "Add recipe" and "es" not in after["recipe.list.add"]["localizations"]


def test_apply_never_writes_a_placeholder_that_differs_or_a_plural(repo, written, capsys):
    copy = json.loads(written.read_text(encoding="utf-8"))
    for r in copy["rows"]:
        r["verdict"] = "pass"
        if r["key"] == "recipe.list.saved":
            r["es"] = "recetas guardadas"
    written.write_text(json.dumps(copy), encoding="utf-8")
    code, out, _ = run(["apply", str(written), str(repo)], capsys)
    assert "skipped recipe.list.saved [es]: placeholders differ from English" in out
    assert "es" not in cat(repo)["strings"]["recipe.list.saved"]["localizations"]
    data = catalog_data()
    data["strings"]["recipe.list.saved"] = {"localizations": {"en": {"variations": {"plural": {"other": unit("%lld recipes")}}}}}
    (repo / "App" / "Localizable.xcstrings").write_text(dump(data), encoding="utf-8")
    code, out, _ = run(["apply", str(written), str(repo)], capsys)
    assert "recipe.list.saved [en]: the string has plural or device variations" in out


def test_apply_writes_android_and_web_catalogs_named_by_the_screen(repo, written, capsys):
    res = repo / "android" / "res"
    (res / "values").mkdir(parents=True)
    (res / "values" / "strings.xml").write_text(
        '<resources>\n    <string name="droid.only">Old</string>\n</resources>\n', encoding="utf-8")
    web = repo / "web" / "i18n.ts"
    web.parent.mkdir()
    web.write_text('export default {\n  en: { "web.only": "Old" },\n  es: {},\n};\n', encoding="utf-8")
    (repo / "design" / "screens" / "recipe.list.yaml").write_text(
        SCREEN + "catalog:\n  - App/Localizable.xcstrings\n  - android/res\ni18n: web/i18n.ts\n", encoding="utf-8")
    copy = json.loads(written.read_text(encoding="utf-8"))
    for key in ("droid.only", "web.only"):
        copy["rows"].append(dict(key=key, control="text", state="all", budget="20 words a sentence", en="Recipes", es="Recetas", ru=RU_TITLE))
    written.write_text(json.dumps(copy), encoding="utf-8")
    code, out, err = run(["apply", str(written), str(repo), "--keys", "droid.only,web.only"], capsys)
    assert code == 0, err
    assert "Recipes" in (res / "values" / "strings.xml").read_text(encoding="utf-8")
    assert "Recetas" in (res / "values-es" / "strings.xml").read_text(encoding="utf-8")
    assert RU_TITLE in (res / "values-ru" / "strings.xml").read_text(encoding="utf-8")
    assert "Recetas" in web.read_text(encoding="utf-8") and '"web.only"' in web.read_text(encoding="utf-8")


def test_apply_reports_a_catalog_it_cannot_read(repo, written, capsys):
    (repo / "design" / "screens" / "recipe.list.yaml").write_text(SCREEN + "i18n: web/i18n.ts\ncatalog: App/Localizable.xcstrings\n", encoding="utf-8")
    (repo / "web").mkdir()
    (repo / "web" / "i18n.ts").write_text("export default { en: { a: t('x') } };\n", encoding="utf-8")
    out = run(["apply", str(written), str(repo), "--keys", "recipe.list.title", "--dry"], capsys)[1]
    assert "note: web/i18n.ts: " in out and "edit this file by hand" in out


# --- apply --pr -------------------------------------------------------------------------------------

class FakeGit:
    def __init__(self, repo, tmp_path):
        self.calls, self.repo, self.tmp = [], repo, tmp_path

    def git(self, args, cwd):
        self.calls.append(("git", list(args)))
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return 0, str(self.repo)
        if args[:1] == ["symbolic-ref"]:
            return 0, "origin/main"
        if args[:2] == ["worktree", "add"]:
            import shutil
            shutil.copytree(self.repo, args[4])
            return 0, ""
        return 0, ""

    def gh(self, args, cwd):
        self.calls.append(("gh", list(args)))
        return 0, "https://github.com/example/recipes/pull/7"


def test_apply_pr_works_in_a_worktree_commits_pushes_and_opens_the_pr(repo, written, capsys, monkeypatch, tmp_path):
    fake = FakeGit(repo, tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(cl.pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cl, "_git", fake.git)
    monkeypatch.setattr(cl, "_gh", fake.gh)
    before = (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8")
    run(["judge", str(written)], capsys)
    code, out, err = run(["apply", str(written), str(repo), "--pr"], capsys)
    assert code == 0, err
    assert (repo / "App" / "Localizable.xcstrings").read_text(encoding="utf-8") == before        # the owner's checkout is untouched
    kinds = [(k, a[0] if a[0] != "worktree" else "worktree " + a[1]) for k, a in fake.calls]
    assert kinds == [("git", "rev-parse"), ("git", "symbolic-ref"), ("git", "worktree add"), ("git", "add"), ("git", "commit"),
                     ("git", "push"), ("gh", "pr"), ("git", "worktree remove")]
    wt = fake.calls[2][1]
    assert wt[:3] == ["worktree", "add", "-b"] and wt[3].startswith("copy/recipe-list-") and wt[5] == "origin/main"
    assert str(home / ".worktrees" / "recipes") in wt[4]
    assert "origin" in fake.calls[5][1] and "--force" not in fake.calls[5][1] and "-f" not in fake.calls[5][1]
    pr = fake.calls[6][1]
    assert pr[:2] == ["pr", "create"] and pr[pr.index("--title") + 1].startswith("Copy: recipe.list strings (5 keys)")
    body = pr[pr.index("--body") + 1]
    assert "## What" in body and "`recipe.list.add`" in body and "merge" not in body.lower().replace("not merged", "")
    assert "PR: https://github.com/example/recipes/pull/7" in out and "not merged" in out
    assert "--admin" not in json.dumps(fake.calls) and "merge" not in json.dumps([c for c in fake.calls if c[0] == "gh"])


def test_apply_pr_with_nothing_to_change_opens_nothing(repo, written, capsys, monkeypatch, tmp_path):
    fake = FakeGit(repo, tmp_path)
    monkeypatch.setattr(cl.pathlib.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(cl, "_git", fake.git)
    monkeypatch.setattr(cl, "_gh", fake.gh)
    run(["apply", str(written), str(repo), "--keys", "recipe.list.missing"], capsys)
    fake.calls.clear()
    code, out, _ = run(["apply", str(written), str(repo), "--keys", "recipe.list.missing", "--pr"], capsys)
    assert code == 0 and "nothing changed: no branch, no PR" in out
    assert not [c for c in fake.calls if c[0] == "gh"] and ["branch", "-D"] == fake.calls[-1][1][:2]


def test_apply_pr_stops_and_names_the_failing_step(repo, written, capsys, monkeypatch, tmp_path):
    fake = FakeGit(repo, tmp_path)
    monkeypatch.setattr(cl.pathlib.Path, "home", classmethod(lambda cls: tmp_path / "home"))

    def git(args, cwd):
        return (1, "rejected: non-fast-forward") if args[:1] == ["push"] else fake.git(args, cwd)

    monkeypatch.setattr(cl, "_git", git)
    monkeypatch.setattr(cl, "_gh", fake.gh)
    run(["judge", str(written)], capsys)
    code, _, err = run(["apply", str(written), str(repo), "--pr"], capsys)
    assert code == 2 and "git push failed: rejected: non-fast-forward" in err and "worktree is kept" in err
    assert not [c for c in fake.calls if c[0] == "gh"]


def test_apply_pr_is_closed_in_safe_mode_and_not_a_dry_run(repo, written, capsys, monkeypatch):
    monkeypatch.setattr(cl, "_git", lambda *a: pytest.fail("git started"))
    code, _, err = run(["apply", str(written), str(repo), "--pr", "--dry"], capsys)
    assert code == 2 and "do not go together" in err
    monkeypatch.setenv(config.SAFE_ENV, "1")
    code, _, err = run(["apply", str(written), str(repo), "--pr"], capsys)
    assert code == 2 and "safe mode" in err


def test_the_command_is_registered_and_documented():
    root = pathlib.Path(__file__).resolve().parents[1]
    assert "copy" in cli._commands(cli.build_parser())
    assert "teyla copy" in (root / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    assert "COPY.md" in (root / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert (root / "docs" / "COPY.md").is_file()
