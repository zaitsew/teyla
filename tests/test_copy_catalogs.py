"""String catalogs for `teyla copy`: xcstrings, Android strings.xml, JSON-like i18n files.
Every catalog is built in a tmp dir; the Russian text is \\u escapes (the leak check flags literal Cyrillic)."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import copy_catalogs as cc

RU_ADD = "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c"


def xcstrings_text(extra: dict | None = None) -> str:
    strings = {
        "item.add": {"extractionState": "manual",
                     "localizations": {"de": {"stringUnit": {"state": "translated", "value": "Hinzufuegen"}},
                                       "en": {"stringUnit": {"state": "translated", "value": "Add item"}}}},
        "item.count": {"localizations": {"en": {"variations": {"plural": {
            "one": {"stringUnit": {"state": "translated", "value": "%lld item"}},
            "other": {"stringUnit": {"state": "translated", "value": "%lld items"}}}}}}},
        "Welcome back": {},
        "other.key": {"comment": "kept", "localizations": {"fr": {"stringUnit": {"state": "translated", "value": "Salut"}}}},
    }
    strings.update(extra or {})
    data = {"sourceLanguage": "en", "strings": strings, "version": "1.0"}
    return json.dumps(data, indent=2, ensure_ascii=False, separators=(",", " : ")) + "\n"


@pytest.fixture
def xc(tmp_path):
    p = tmp_path / "App" / "Localizable.xcstrings"
    p.parent.mkdir()
    p.write_text(xcstrings_text(), encoding="utf-8")
    return p


def test_xcstrings_reads_values_plural_other_and_literal_keys(xc, tmp_path):
    c = cc.XcStrings(xc, tmp_path)
    assert c.get("item.add", "en") == "Add item" and c.get("item.add", "de") == "Hinzufuegen"
    assert c.get("item.add", "es") is None
    assert c.get("item.count", "en") == "%lld items"
    assert c.get("Welcome back", "en") == "Welcome back"          # a literal-text key shows itself
    assert c.has("other.key") and not c.has("nope")


def test_xcstrings_no_op_round_trip_is_byte_identical(xc, tmp_path):
    before = xc.read_text(encoding="utf-8")
    c = cc.XcStrings(xc, tmp_path)
    assert c.set("item.add", "en", "Add item") == "same"
    assert c.save() == [] and xc.read_text(encoding="utf-8") == before
    assert c.dumps() == before                                    # Xcode's layout is reproduced exactly


def test_xcstrings_set_updates_adds_a_language_and_keeps_everything_else(xc, tmp_path):
    c = cc.XcStrings(xc, tmp_path)
    assert c.set("item.add", "en", "Add an item") == "changed"
    assert c.set("item.add", "es", "Añadir") == "changed"
    assert c.set("other.key", "es", "Hola") == "changed"
    assert c.save() == [xc]
    data = json.loads(xc.read_text(encoding="utf-8"))
    assert list(data["strings"]) == ["item.add", "item.count", "Welcome back", "other.key"]       # order kept
    assert list(data["strings"]["item.add"]["localizations"]) == ["de", "en", "es"]               # alphabetical kept
    assert data["strings"]["item.add"]["localizations"]["de"]["stringUnit"]["value"] == "Hinzufuegen"
    assert data["strings"]["item.add"]["extractionState"] == "manual"
    assert data["strings"]["other.key"]["localizations"]["fr"]["stringUnit"]["value"] == "Salut"
    assert data["strings"]["other.key"]["comment"] == "kept"
    assert data["strings"]["item.count"] == json.loads(xcstrings_text())["strings"]["item.count"]


def test_xcstrings_never_writes_variations_or_unknown_keys(xc, tmp_path):
    c = cc.XcStrings(xc, tmp_path)
    assert c.set("item.count", "en", "x").startswith("skipped: the string has plural")
    assert c.set("missing", "en", "x").startswith("skipped: the key is not in the catalog")
    assert c.save() == []


def test_xcstrings_rejects_what_is_not_a_catalog(tmp_path):
    p = tmp_path / "bad.xcstrings"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(cc.CatalogError, match="cannot read the catalog"):
        cc.XcStrings(p, tmp_path)
    p.write_text('{"version": "1.0"}', encoding="utf-8")
    with pytest.raises(cc.CatalogError, match="not a string catalog"):
        cc.XcStrings(p, tmp_path)


# --- Android ----------------------------------------------------------------------------------------

ANDROID_EN = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- a comment stays -->
    <string name="item_add">Add item</string>
    <string name="item_empty">Nothing here.\\nAdd one.</string>
    <string name="app_name" translatable="false">Demo</string>
</resources>
"""


@pytest.fixture
def android(tmp_path):
    res = tmp_path / "app" / "src" / "main" / "res"
    (res / "values").mkdir(parents=True)
    (res / "values-es").mkdir()
    (res / "values" / "strings.xml").write_text(ANDROID_EN, encoding="utf-8")
    (res / "values-es" / "strings.xml").write_text(
        '<resources>\n    <string name="item_add">Anadir</string>\n</resources>\n', encoding="utf-8")
    return res


def test_android_escape_and_unescape_round_trip():
    for text in ["Don't stop", 'Say "hi"', "a & b < c", "Line one\nLine two", "@home", "100%"]:
        assert cc.android_unescape(cc.android_escape(text)) == text
    assert cc.android_escape("It's") == "It\\'s" and cc.android_escape("a&b") == "a&amp;b"


def test_android_reads_the_default_and_language_files(android, tmp_path):
    c = cc.AndroidStrings(android, tmp_path)
    assert c.has("item_add") and c.get("item_add", "en") == "Add item" and c.get("item_add", "es") == "Anadir"
    assert c.get("item_empty", "en") == "Nothing here.\nAdd one."
    assert c.get("item_add", "ru") is None


def test_android_set_edits_in_place_appends_and_creates_a_language_file(android, tmp_path):
    c = cc.AndroidStrings(android, tmp_path)
    assert c.set("item_add", "en", "Add an item") == "changed"
    assert c.set("item_add", "es", "Añadir elemento") == "changed"
    assert c.set("item_empty", "es", "Nada aquí. Añade uno.") == "changed"        # appended to values-es
    assert c.set("item_add", "ru", RU_ADD) == "changed"                                      # values-ru is created
    assert c.set("app_name", "es", "x").startswith("skipped: the string is marked translatable")
    assert sorted(p.parent.name for p in c.save()) == ["values", "values-es", "values-ru"]
    en = (android / "values" / "strings.xml").read_text(encoding="utf-8")
    assert "<!-- a comment stays -->" in en and "Add an item" in en and 'name="app_name" translatable="false">Demo' in en
    es = (android / "values-es" / "strings.xml").read_text(encoding="utf-8")
    assert es.count("<string") == 2 and es.rstrip().endswith("</resources>")
    assert RU_ADD in (android / "values-ru" / "strings.xml").read_text(encoding="utf-8")


# --- JSON-like web files ----------------------------------------------------------------------------

I18N_TS = """// strings for the demo
export const messages = {
  en: {
    "item.add": "Add item",
    nested: { title: "Items", },
  },
  es: {
    "item.add": "A\\u00f1adir",
  },
} as const;

export default messages;
"""


def test_json_like_reads_bare_keys_and_trailing_commas_and_refuses_the_rest():
    assert cc.json_like('{ a: "x", b: [1, 2,], c: {d: "y",}, }') == {"a": "x", "b": [1, 2], "c": {"d": "y"}}
    assert cc.json_like('{"a: b": "x, }"}') == {"a: b": "x, }"}                  # punctuation inside a string is text
    for bad, why in [("{ a: 'x' }", "single-quoted"), ('{ a: "x" // c\n}', "comments"), ("{ a: `x` }", "single-quoted"),
                     ("{ a: f(1) }", "not JSON-like")]:
        with pytest.raises(cc.CatalogError, match=why):
            cc.json_like(bad)


def test_i18n_file_reads_flat_and_nested_keys_and_rewrites_only_the_object(tmp_path):
    p = tmp_path / "web" / "i18n.ts"
    p.parent.mkdir()
    p.write_text(I18N_TS, encoding="utf-8")
    c = cc.I18nFile(p, tmp_path)
    assert c.has("item.add") and c.has("nested.title") and not c.has("nope")
    assert c.get("item.add", "en") == "Add item" and c.get("nested.title", "en") == "Items" and c.get("nested.title", "es") is None
    assert c.set("item.add", "es", "Añadir elemento") == "changed"
    assert c.set("item.add", "ru", RU_ADD) == "changed"                          # a new language object is created
    assert c.set("item.add", "en", "Add item") == "same"
    assert c.set("nested.title", "es", "x").startswith("skipped: the key is nested")
    c.save()
    out = p.read_text(encoding="utf-8")
    assert out.startswith("// strings for the demo\nexport const messages = {") and out.endswith("export default messages;\n")
    assert "} as const;" in out
    again = cc.I18nFile(p, tmp_path)
    assert again.get("item.add", "es") == "Añadir elemento" and again.get("item.add", "ru") == RU_ADD


def test_i18n_file_refuses_a_file_that_is_not_json_like(tmp_path):
    p = tmp_path / "i18n.ts"
    p.write_text("export default { en: { a: t('x') } };\n", encoding="utf-8")
    with pytest.raises(cc.CatalogError, match="edit this file by hand"):
        cc.I18nFile(p, tmp_path)
    p.write_text('export default { fr: { a: "x" } };\n', encoding="utf-8")
    with pytest.raises(cc.CatalogError, match="one object per language"):
        cc.I18nFile(p, tmp_path)


def test_lang_files_pattern(tmp_path):
    d = tmp_path / "locales"
    d.mkdir()
    (d / "en.json").write_text('{"a": {"b": "Hello"}, "c": "Bye"}\n', encoding="utf-8")
    (d / "es.json").write_text('{"c": "Adios"}\n', encoding="utf-8")
    c = cc.LangFiles("locales/{lang}.json", tmp_path)
    assert c.get("a.b", "en") == "Hello" and c.get("c", "es") == "Adios" and c.has("a.b")
    assert c.set("c", "es", "Chao") == "changed" and c.set("c", "ru", "x").startswith("skipped: no locales/ru.json")
    assert c.set("a.b", "es", "Hola").startswith("skipped: the key is nested")
    assert [p.name for p in c.save()] == ["es.json"]
    assert json.loads((d / "es.json").read_text(encoding="utf-8")) == {"c": "Chao"}


def test_find_catalogs_scans_the_repo_and_skips_build_output(tmp_path, xc):
    build = tmp_path / "build" / "X.xcstrings"
    build.parent.mkdir()
    build.write_text(xcstrings_text(), encoding="utf-8")
    cats, notes = cc.find_catalogs(tmp_path, {}, ["item.add"])
    assert [c.label for c in cats] == ["App/Localizable.xcstrings"] and not notes
    assert cc.lookup(cats, "item.add") is cats[0] and cc.lookup(cats, "zzz") is None
    named, notes = cc.find_catalogs(tmp_path, {"catalog": ["App/Localizable.xcstrings", "nope.xcstrings"]}, ["item.add"])
    assert len(named) == 1 and any("nope.xcstrings: not found" in n for n in notes)
