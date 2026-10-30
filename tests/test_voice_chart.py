"""`teyla voice chart` (the scaffold) and the completeness finding of `teyla voice check`.
Generic recipe-app content; Russian is \\u escapes."""
from __future__ import annotations

import json

import pytest

from teyla import cli, config, voice

RU_TERM = "\u0440\u0435\u0446\u0435\u043f\u0442"

DESIGN = """# Design: Recipes

## Glossary
| Concept | en | es | ru |
|---|---|---|---|
| recipe | recipe | receta | RU-TERM |

## Voice
The product sounds warm, plain and brief.
Address: you.
"""

KIT = """product = "Recipes"

[voice]
traits = ["We are warm, not cute", "We are brief, not terse"]
banned = ["delicious journey"]
preferred = ["cook"]
"""


def decision(tmp, name, **copy):
    d = tmp / "design" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(dict(id=name, date="2026-10-30", decision="fix", copy=copy)), encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "recipes"
    r.mkdir()
    (r / "DESIGN.md").write_text(DESIGN.replace("RU-TERM", RU_TERM), encoding="utf-8")
    return r


def chart(repo, capsys, *argv):
    code = cli.main(["voice", "chart", str(repo), *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_scaffold_writes_three_charts_from_design_md(repo, capsys):
    code, out, err = chart(repo, capsys)
    assert code == 0, err
    d = repo / "brand" / "voice"
    assert sorted(p.name for p in d.iterdir()) == ["en.md", "es.md", "ru.md"]
    assert "en  written: 0/10 accepted, 0/5 rejected  INCOMPLETE" in out and "1 glossary rows" in out
    es = (d / "es.md").read_text(encoding="utf-8")
    assert "lang: es" in es and "> The product sounds warm, plain and brief." in es and "| recipe | receta |" in es
    assert "Spain (es-ES)" in es and '- "ups"' in es
    assert f"| recipe | {RU_TERM} |" in (d / "ru.md").read_text(encoding="utf-8")
    assert es.count("{{accepted line") == 10 and es.count("{{rejected line") == 5
    chart_ok = voice.load_chart(d / "en.md")                               # the scaffold is a valid chart
    assert chart_ok.lang == "en" and "oops" in chart_ok.banned


def test_the_scaffold_reads_the_brand_kit(repo, capsys):
    (repo / "brand").mkdir()
    (repo / "brand" / "kit.toml").write_text(KIT, encoding="utf-8")
    code, out, _ = chart(repo, capsys, "--lang", "en")
    assert code == 0 and "brand/kit.toml read" in out
    assert not (repo / "brand" / "voice" / "es.md").exists()               # --lang en only
    text = (repo / "brand" / "voice" / "en.md").read_text(encoding="utf-8")
    assert "# Voice chart: Recipes (English)" in text and '"delicious journey"' in text and '"cook"' in text
    assert "- We are warm, not cute" in text
    c = voice.load_chart(repo / "brand" / "voice" / "en.md")
    assert "delicious journey" in c.banned and "oops" in c.banned


def test_the_scaffold_never_overwrites_without_force(repo, capsys):
    chart(repo, capsys, "--lang", "en")
    f = repo / "brand" / "voice" / "en.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nOwner edit.\n", encoding="utf-8")
    code, out, _ = chart(repo, capsys, "--lang", "en")
    assert code == 0 and "kept (exists; --force overwrites)" in out and "Owner edit." in f.read_text(encoding="utf-8")
    chart(repo, capsys, "--lang", "en", "--force")
    assert "Owner edit." not in f.read_text(encoding="utf-8")


def test_the_scaffold_takes_example_lines_from_design_decisions(repo, capsys):
    for i in range(10):
        decision(repo, f"acc{i:02d}", lang="en", accepted=f"Add recipe {i}")
    for i in range(5):
        decision(repo, f"rej{i:02d}", lang="en", rejected=f"Oops, a recipe {i}")
    decision(repo, "dup", lang="en", accepted="Add recipe 0")
    decision(repo, "other", lang="es", accepted="Añadir receta")
    code, out, _ = chart(repo, capsys)
    assert code == 0 and "16 example lines" in out
    assert "en  written: 10/10 accepted, 5/5 rejected" in out
    en = (repo / "brand" / "voice" / "en.md").read_text(encoding="utf-8")
    assert "- Add recipe 0" in en and "- Oops, a recipe 4" in en and "{{accepted" not in en
    es = (repo / "brand" / "voice" / "es.md").read_text(encoding="utf-8")
    assert "- Añadir receta" in es and es.count("{{accepted line") == 9


def test_the_scaffold_without_design_md_still_writes_blanks(tmp_path, capsys):
    r = tmp_path / "bare"
    r.mkdir()
    code, out, _ = chart(r, capsys, "--lang", "en")
    assert code == 0 and "DESIGN.md missing" in out
    text = (r / "brand" / "voice" / "en.md").read_text(encoding="utf-8")
    assert "{{one sentence}}" in text and "{{trait 1}}" in text


def test_chart_dir_and_json_and_errors(repo, tmp_path, capsys):
    code, out, _ = chart(repo, capsys, "--out", str(tmp_path / "elsewhere"), "--json", "--lang", "es")
    rep = json.loads(out)
    assert code == 0 and rep["charts"][0]["lang"] == "es" and (tmp_path / "elsewhere" / "es.md").is_file()
    assert rep["charts"][0]["complete"] is False
    code, _, err = chart(tmp_path / "none", capsys)
    assert code == 2 and "teyla voice chart:" in err


# --- completeness -------------------------------------------------------------------------------------

def body(acc, rej, extra=""):
    return ("---\nlang: en\n---\n# C\n\n## Accepted lines\n" + "".join(f"- Line {i}\n" for i in range(acc)) +
            "\n## Rejected lines\n" + "".join(f"1. \"Bad {i}\"\n" for i in range(rej)) + extra)


def write_chart(tmp_path, text):
    f = tmp_path / "en.md"
    f.write_text(text, encoding="utf-8")
    return f


def test_example_lines_count_bullets_under_the_two_headings():
    acc, rej = voice.example_lines(body(3, 2, "\n## Notes\n- not an example\n"))
    assert len(acc) == 3 and rej == ["Bad 0", "Bad 1"]
    acc, rej = voice.example_lines("## Accepted lines\n- {{accepted line 1}}\n- Real line\n\n#### Rejected\n* Another\n")
    assert acc == ["Real line"] and rej == ["Another"]
    assert voice.example_lines("- a bullet with no heading\n") == ([], [])


def test_chart_status_needs_ten_and_five(tmp_path):
    for acc, rej, ok in ((10, 5, True), (9, 5, False), (10, 4, False), (0, 0, False)):
        st = voice.chart_status(voice.load_chart(write_chart(tmp_path, body(acc, rej))))
        assert st["complete"] is ok and (st["accepted"], st["rejected"]) == (acc, rej)


def check(tmp_path, capsys, text, *argv):
    d = tmp_path / "draft.txt"
    d.write_text("Add a recipe.\n", encoding="utf-8")
    code = cli.main(["voice", "check", str(d), "--chart", str(tmp_path / "en.md"), "--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_voice_check_warns_about_an_incomplete_chart_and_stays_green(tmp_path, capsys):
    write_chart(tmp_path, body(4, 2))
    code, rep = check(tmp_path, capsys, "")
    assert code == 0 and rep["ok"] is True
    warn = [f for f in rep["findings"] if f["rule"] == "chart"]
    assert len(warn) == 1 and warn[0]["level"] == "warn" and "4 of 10 accepted and 2 of 5 rejected" in warn[0]["message"]
    assert rep["chart_status"]["complete"] is False


def test_voice_check_is_silent_about_a_complete_chart(tmp_path, capsys):
    write_chart(tmp_path, body(10, 5))
    code, rep = check(tmp_path, capsys, "")
    assert code == 0 and not [f for f in rep["findings"] if f["rule"] == "chart"] and rep["chart_status"]["complete"] is True


def test_voice_check_still_needs_a_chart(tmp_path, capsys):
    d = tmp_path / "draft.txt"
    d.write_text("Add a recipe.\n", encoding="utf-8")
    code = cli.main(["voice", "check", str(d)])
    assert code == 2 and "check needs --chart" in capsys.readouterr().err
