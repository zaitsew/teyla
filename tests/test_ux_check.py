"""teyla ux check: synthetic repos in tmp dirs. Nothing here reads a real repo or ~/.teyla."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import cli, config, ux_check


def make(tmp_path, files, name="app", design=True):
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if design:
        (d / "DESIGN.md").write_text("# Design\n\nTokens live in Theme.swift.\n")
    return d


def swift_view(body: str, name="HomeView") -> str:
    return f"import SwiftUI\n\nstruct {name}: View {{\n    var body: some View {{\n{body}\n    }}\n}}\n"


def counts(tmp_path, files, **kw):
    return ux_check.audit(make(tmp_path, files, **kw))["counts"]


# --- SwiftUI ------------------------------------------------------------------------------------

def test_swift_literals_are_counted(tmp_path):
    body = """
        Text("Hi").font(.system(size: 17))
        Text("Hi").font(.custom("Serif", size: 20))
        Rectangle().fill(Color(red: 0.1, green: 0.2, blue: 0.3))
        Rectangle().fill(Color(hex: 0xFF8800))
        Rectangle().fill(Color(#colorLiteral(red: 1, green: 0, blue: 0, alpha: 1)))
        VStack {}.padding(16)
        VStack {}.padding(.horizontal, 12)
        VStack {}.padding([.top, .bottom], 8.5)
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert (c["font"], c["colour"], c["spacing"]) == (2, 3, 3)


def test_swift_tokens_zero_and_expressions_are_not_literals(tmp_path):
    body = """
        Text("Hi").font(Tokens.body)
        VStack {}.padding(Space.m)
        VStack {}.padding(.horizontal, Space.l)
        VStack {}.padding(.top, 2 * Space.s)
        VStack {}.padding(0)
        VStack {}.padding()
        VStack {}.padding(.bottom)
        Rectangle().fill(Palette.accent)
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert (c["font"], c["colour"], c["spacing"]) == (0, 0, 0)


def test_swift_comments_and_previews_are_not_read(tmp_path):
    src = swift_view("""
        // VStack {}.padding(16)
        /* Text("x").font(.system(size: 9)) */
        Text("ok")
    """) + """
#Preview {
    HomeView().padding(24).font(.system(size: 30))
}

struct HomeView_Previews: PreviewProvider {
    static var previews: some View { HomeView().padding(8) }
}
"""
    c = counts(tmp_path, {"Sources/HomeView.swift": src})
    assert (c["font"], c["colour"], c["spacing"]) == (0, 0, 0)


def test_crowded_screen_needs_more_than_four_taps(tmp_path):
    four = swift_view("\n".join('Button("Go") { }' for _ in range(4)), name="Four")
    five = swift_view("\n".join(['Button("Go") { }'] * 3 + ['NavigationLink("More") { Text("x") }', 'Text("a").onTapGesture { }']), name="Five")
    a = ux_check.audit(make(tmp_path, {"Sources/Four.swift": four, "Sources/Five.swift": five}))
    assert [(x["view"], x["taps"]) for x in a["crowded"]] == [("Five", 5)]
    assert a["crowded"][0]["file"] == "Sources/Five.swift"


def test_only_view_structs_are_screens(tmp_path):
    src = "import SwiftUI\n\nstruct Model: Hashable {\n" + "\n".join('    let a = Button("x") { }' for _ in range(6)) + "\n}\n"
    assert ux_check.audit(make(tmp_path, {"Sources/Model.swift": src}))["crowded"] == []


def test_swift_copy_rules(tmp_path):
    body = """
        Text("Please sign in")
        Text("Welcome back!")
        Text("3 items")
        Button("Add a new item to list") { }
        Button("Add item") { }
        Label("Settings", systemImage: "gear")
        Text("a != b")
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert (c["please"], c["bang"], c["long_button"]) == (1, 1, 1)


# --- Jetpack Compose ----------------------------------------------------------------------------

COMPOSE = """package app

import androidx.compose.runtime.Composable

@Composable
fun Home() {
    Text("Welcome!", fontSize = 18.sp)
    Box(Modifier.padding(16.dp).background(Color(0xFF112233)))
    Box(Modifier.padding(horizontal = 12.dp, vertical = 0.dp))
    Box(Modifier.padding(0.dp))
    Box(Modifier.padding(Spacing.m))
    Text("Please wait")
    val c = Color.parseColor("#abcdef")
}

@Preview
@Composable
fun HomePreview() {
    Text("x", fontSize = 40.sp)
}
"""


def test_compose_literals_and_copy(tmp_path):
    a = ux_check.audit(make(tmp_path, {"app/src/main/Home.kt": COMPOSE}))
    c = a["counts"]
    assert (c["font"], c["colour"], c["spacing"]) == (1, 2, 2)
    assert (c["please"], c["bang"]) == (1, 1)
    assert a["platforms"] == ["compose"]


def test_kotlin_without_composables_is_not_ui(tmp_path):
    a = ux_check.audit(make(tmp_path, {"app/Model.kt": "class A { val s = 12.sp; val p = Modifier.padding(4.dp) }\n"}))
    assert a["ui_files"] == 0


def test_android_string_resources(tmp_path):
    xml = """<resources>
    <string name="title">Please log in</string>
    <string name="btn_add_item_now">Add a new item</string>
    <string name="btn_save">Save note</string>
    <string name="done">Done!</string>
    <string name="skip" translatable="false">Please!</string>
</resources>"""
    ru = '<resources><string name="title">Please!</string></resources>'
    c = counts(tmp_path, {
        "app/src/main/res/values/strings.xml": xml,
        "app/src/main/res/values-ru/strings.xml": ru,
        "app/src/main/Home.kt": COMPOSE,
    })
    assert (c["please"], c["bang"], c["long_button"]) == (2, 2, 1)  # the Compose file adds 1 + 1


# --- web ----------------------------------------------------------------------------------------

def test_web_literals(tmp_path):
    css = """:root { --text-md: 14px; --brand: #ff0000; }
/* .old { font-size: 30px; color: #123456; } */
.a { font-size: 14px; color: #fff; background: rgb(10, 20, 30); }
.b { font-size: var(--text-md); color: var(--brand); }
#hero { margin: 0 }
a[href="#top"] { color: inherit }
"""
    tsx = """export const A = () => <p style={{ fontSize: 13, color: "#abcdef" }}>hi</p>;
export const B = () => <a href="#abc123">x</a>;
"""
    c = counts(tmp_path, {"web/src/app.css": css, "web/src/A.tsx": tsx})
    assert c["font"] == 2
    assert c["colour"] == 3  # #fff, rgb(), "#abcdef"


def test_web_token_files_and_output_dirs_are_skipped(tmp_path):
    bad = ".a { font-size: 14px; color: #fff; }\n"
    files = {
        "web/src/theme.css": bad, "web/src/tokens.scss": bad, "web/src/colors.css": bad,
        "web/src/theme/base.css": bad, "web/node_modules/x/a.css": bad, "web/dist/a.css": bad,
        "web/src/a.test.tsx": "const s = { fontSize: 12 };\n", "web/src/__tests__/a.tsx": "const s = { fontSize: 12 };\n",
        "web/src/gen.generated.css": bad, "web/src/b.css": "/* @generated */\n" + bad,
    }
    a = ux_check.audit(make(tmp_path, files))
    assert a["ui_files"] == 0
    assert a["literals"] == 0


# --- skips --------------------------------------------------------------------------------------

def test_swift_skips_build_pods_tests_and_token_files(tmp_path):
    bad = swift_view("VStack {}.padding(16)\nText(\"x\").font(.system(size: 12))")
    files = {
        "Sources/Theme.swift": bad, "Sources/AppTokens.swift": bad, "Sources/DesignSystem.swift": bad,
        "Pods/Lib/V.swift": bad, "build/V.swift": bad, ".build/V.swift": bad, "DerivedData/V.swift": bad,
        "AppTests/V.swift": bad, "Sources/VTests.swift": bad, "Sources/VPreview.swift": bad,
        "Sources/Gen.swift": "// swiftgen\n" + bad, "Sources/Auto.swift": "// Generated by tool. DO NOT EDIT.\n" + bad,
        "Sources/Real.swift": bad,
    }
    a = ux_check.audit(make(tmp_path, files))
    assert a["ui_files"] == 1
    assert a["literals"] == 2
    assert [w["file"] for w in a["worst_files"]] == ["Sources/Real.swift"]


def test_worst_files_are_the_five_largest(tmp_path):
    files = {f"S/V{i}.swift": swift_view("\n".join(["VStack {}.padding(8)"] * i), name=f"V{i}") for i in range(1, 8)}
    a = ux_check.audit(make(tmp_path, files))
    assert [w["file"] for w in a["worst_files"]] == [f"S/V{i}.swift" for i in (7, 6, 5, 4, 3)]
    assert a["worst_files"][0]["total"] == 7


# --- strings catalogs ---------------------------------------------------------------------------

def test_strings_files_and_xcstrings(tmp_path):
    strings = '"a" = "Please try again";\n"b" = "Done!";\n'
    cat = json.dumps({"sourceLanguage": "en", "strings": {
        "Hello there!": {}, "k": {"localizations": {"en": {"stringUnit": {"value": "Please wait"}}}}}})
    es = json.dumps({"sourceLanguage": "es", "strings": {"Hola!": {}}})
    c = counts(tmp_path, {"A/en.lproj/Localizable.strings": strings, "A/es.lproj/Localizable.strings": strings,
                          "A/Localizable.xcstrings": cat, "B/Localizable.xcstrings": es})
    assert (c["please"], c["bang"]) == (2, 2)


# --- verdicts -----------------------------------------------------------------------------------

def test_clean_repo_is_ok(tmp_path):
    r = ux_check.check_repo(make(tmp_path, {"S/V.swift": swift_view('Text("Add item")')}))
    assert r["verdict"] == "OK" and r["findings"] == []


def test_repo_without_ui_code_is_ok_and_needs_no_design_doc(tmp_path):
    r = ux_check.check_repo(make(tmp_path, {"a.py": "print(1)\n"}, design=False))
    assert r["verdict"] == "OK" and r["platforms"] == [] and r["findings"] == []


def test_missing_and_unfilled_design_doc_warn(tmp_path):
    files = {"S/V.swift": swift_view('Text("Add item")')}
    r = ux_check.check_repo(make(tmp_path, files, design=False))
    assert r["verdict"] == "WARN" and [f["check"] for f in r["findings"]] == ["design-doc"]
    d = make(tmp_path, files, name="b")
    (d / "DESIGN.md").write_text("# {{product}}\n")
    assert ux_check.check_repo(d)["findings"][0]["message"].startswith("DESIGN.md still holds")
    docs = make(tmp_path, files, name="c", design=False)
    (docs / "docs").mkdir()
    (docs / "docs" / "Design.md").write_text("# Design\n")
    assert ux_check.check_repo(docs)["findings"] == []


def test_token_thresholds(tmp_path):
    def rep(n_literals, extra_lines=0, name="r"):
        body = "\n".join(["VStack {}.padding(8)"] * n_literals + ["Text(\"x\")"] * extra_lines)
        return ux_check.check_repo(make(tmp_path, {"S/V.swift": swift_view(body)}, name=name))
    assert rep(9)["verdict"] == "OK"                        # under the minimum count
    assert rep(10, extra_lines=2500, name="a")["verdict"] == "OK"   # under 5 per 1,000 lines
    warn = rep(10, name="b")
    assert warn["verdict"] == "WARN" and warn["findings"][0]["check"] == "tokens"
    assert rep(99, name="c")["verdict"] == "WARN"
    assert rep(100, name="d")["verdict"] == "FIX"
    assert rep(100, extra_lines=100000, name="e")["verdict"] == "OK"  # the same count, a sparse repo


def test_crowded_is_a_warning_never_a_fix(tmp_path):
    def view(i, taps):
        return swift_view("\n".join(['Button("Go") { }'] * taps), name=f"V{i}")
    one = ux_check.check_repo(make(tmp_path, {"S/A.swift": view(1, 5)}, name="one"))
    assert one["verdict"] == "WARN" and one["findings"][0]["check"] == "crowded"
    for name, n, taps in (("ten", 10, 5), ("severe", 3, 10), ("many", 12, 14)):
        r = ux_check.check_repo(make(tmp_path, {f"S/V{i}.swift": view(i, taps) for i in range(n)}, name=name))
        assert r["verdict"] == "WARN", name
        assert [f["severity"] for f in r["findings"]] == ["WARN"]


def test_copy_thresholds(tmp_path):
    def rep(n, name):
        body = "\n".join(['Text("Please wait")'] * n)
        return ux_check.check_repo(make(tmp_path, {"S/V.swift": swift_view(body)}, name=name))
    assert rep(1, "a")["verdict"] == "WARN"
    assert rep(24, "b")["verdict"] == "WARN"
    r = rep(25, "c")
    assert r["verdict"] == "FIX" and any(f["check"] == "copy" for f in r["findings"])


# --- the Apple writing rules and the per-control budgets ---------------------------------------

def test_oops_and_uh_oh_are_counted(tmp_path):
    body = """
        Text("Oops, that did not work")
        Text("Uh-oh")
        Text("Whoops")
        Text("Could not save")
        Text("Group chat")
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert c["oops"] == 3


def test_your_before_a_noun_in_a_label_is_counted_but_a_sentence_is_not(tmp_path):
    body = """
        Text("Your Favorites")
        Text("Your trips")
        Label("Your account", systemImage: "person")
        Text("Your trip is saved")
        Text("Your order shipped.")
        Text("Yours truly")
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert c["your_label"] == 3


def test_we_in_an_error_string_is_counted_only_where_the_code_shows_an_error(tmp_path):
    body = """
        Text("We could not save your note").foregroundStyle(errorColor)
        Text("We could not reach the server") // in a view model: errorMessage
        if let error { Text("We're offline, try again") }
        case .failed: Text("We lost the connection")
        Text("We missed you")
        Text("Sign in with a link").opacity(error == nil ? 1 : 0)
        Text("We love this").font(Tokens.body)
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    # line 1 (errorColor), line 3 (error), line 4 (.failed): three. The comment line is stripped,
    # so it has no identifier; plain lines have no context and are not guessed.
    assert c["we_error"] == 3


def test_a_line_that_names_both_an_error_and_an_empty_state_has_no_context(tmp_path):
    body = 'Text("We could not load. Try again. Or check later.") // x\n        if emptyState { Text("We found nothing. Add one. Then share it.") } else if error != nil { Text("a") }'
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert (c["we_error"], c["long_error"], c["long_empty"]) == (0, 0, 0)


def test_an_error_over_two_sentences_is_counted(tmp_path):
    body = """
        Text("Could not save. Check your connection and try again.").foregroundStyle(errorColor)
        Text("Could not save. Check your connection. Try again later.").foregroundStyle(errorColor)
        Text("Saved. Synced. Shared.")
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert c["long_error"] == 1


def test_an_empty_state_over_two_sentences_is_counted(tmp_path):
    body = """
        ContentUnavailableView("No notes yet", systemImage: "note", description: Text("Notes you add show up here. Tap Add note to start. Or import some."))
        ContentUnavailableView("No notes yet", systemImage: "note")
        Text("Nothing here. Add a note. Then share it.").opacity(emptyStateOpacity)
        EmptyView()
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    # the first line holds a two-string call whose strings are both read as empty-state text; only
    # the description has three sentences. The third line is an empty-state context by name.
    assert c["long_empty"] == 2


def test_a_navigation_title_over_five_words_is_counted(tmp_path):
    body = """
        List {}.navigationTitle("Notes")
        List {}.navigationTitle("Notes from the last trip")
        List {}.navigationTitle("Notes from the whole last trip")
        List {}.navigationBarTitle("A very long title for this screen")
        List {}.navigationTitle(title)
    """
    c = counts(tmp_path, {"Sources/HomeView.swift": swift_view(body)})
    assert c["long_title"] == 2


def test_compose_error_context(tmp_path):
    kt = """package app

import androidx.compose.runtime.Composable

@Composable
fun Home(error: String?) {
    if (error != null) Text("We could not save")
    Text("We are glad you are here")
}
"""
    assert counts(tmp_path, {"app/src/main/Home.kt": kt})["we_error"] == 1


def test_android_and_catalog_strings_use_their_names_as_context(tmp_path):
    xml = """<resources>
    <string name="error_save">We could not save</string>
    <string name="save_failed">We lost the connection. Check it. Retry.</string>
    <string name="empty_notes">Nothing here. Add a note. Share it.</string>
    <string name="welcome">We are glad you are here</string>
    <string name="Your_Favorites">Your Favorites</string>
</resources>"""
    strings = '"error.save" = "We could not save";\n"home.title" = "We are glad";\n"We failed" = "We tried";\n'
    cat = json.dumps({"sourceLanguage": "en", "strings": {
        "saveFailed": {"localizations": {"en": {"stringUnit": {"value": "We could not save"}}}},
        "We failed to load": {}}})
    c = counts(tmp_path, {
        "app/src/main/res/values/strings.xml": xml,
        "A/en.lproj/Localizable.strings": strings,
        "A/Localizable.xcstrings": cat,
    })
    assert c["we_error"] == 4   # error_save, save_failed, error.save, saveFailed
    assert c["long_error"] == 1  # save_failed
    assert c["long_empty"] == 1
    assert c["your_label"] == 1


def test_copy_finding_names_each_new_kind(tmp_path):
    body = 'Text("Oops").font(Tokens.body)\nText("Your Favorites")\nList {}.navigationTitle("One two three four five six")'
    r = ux_check.check_repo(make(tmp_path, {"S/V.swift": swift_view(body)}))
    copy = [f for f in r["findings"] if f["check"] == "copy"][0]
    assert copy["severity"] == "WARN"
    for needle in ("with \"oops\"", "starting with \"Your\"", "title(s) over 5 words"):
        assert needle in copy["message"]
    assert ux_check.copy_total(r["counts"]) == 3


# --- DESIGN.md and the standard -----------------------------------------------------------------

def test_a_long_design_doc_is_a_fix(tmp_path):
    files = {"S/V.swift": swift_view('Text("Add item")')}
    ok = make(tmp_path, files, name="ok")
    (ok / "DESIGN.md").write_text("# Design\n" + "line\n" * 99)  # 100 lines
    assert ux_check.check_repo(ok)["findings"] == []
    long = make(tmp_path, files, name="long")
    (long / "DESIGN.md").write_text("# Design\n" + "line\n" * 100)  # 101 lines
    r = ux_check.check_repo(long)
    assert r["verdict"] == "FIX"
    f = r["findings"][0]
    assert (f["check"], f["severity"], f["file"]) == ("design-doc", "FIX", "DESIGN.md")
    assert f["message"] == "DESIGN.md is 101 lines; keep it under 100, move history to docs/decisions/"


def test_a_long_design_doc_in_docs_is_found(tmp_path):
    d = make(tmp_path, {"S/V.swift": swift_view('Text("Add item")')}, design=False)
    (d / "docs").mkdir()
    (d / "docs" / "DESIGN.md").write_text("x\n" * 150)
    r = ux_check.check_repo(d)
    assert r["findings"][0]["file"] == "docs/DESIGN.md" and "150 lines" in r["findings"][0]["message"]


def rule(n, dated=True):
    meta = "Since 2026-10-16 · Scope: every screen · Check: review\n\n" if dated else "\n"
    return f"### R{n}. A rule number {n}\n{meta}Body.\n\n"


def standard(n, dated=True, tail=""):
    return "# Standard\n\n```\n### R99. an example inside a fence\n```\n\n" + "".join(rule(i, dated) for i in range(1, n + 1)) + tail


def test_standard_with_more_than_twenty_active_rules_is_a_fix(tmp_path):
    ok = make(tmp_path, {"a.py": "print(1)\n"}, name="ok", design=False)
    (ok / "docs").mkdir()
    (ok / "docs" / "STANDARD.md").write_text(standard(20))
    assert ux_check.check_repo(ok)["findings"] == []
    over = make(tmp_path, {"a.py": "print(1)\n"}, name="over", design=False)
    (over / "docs").mkdir()
    (over / "docs" / "STANDARD.md").write_text(standard(21))
    r = ux_check.check_repo(over)
    assert r["verdict"] == "FIX"
    f = r["findings"][0]
    assert (f["check"], f["severity"], f["file"]) == ("standard", "FIX", "docs/STANDARD.md")
    assert "21 active rules" in f["message"] and "20" in f["message"]


def test_retired_rules_do_not_count_toward_the_twenty(tmp_path):
    d = make(tmp_path, {"a.py": "print(1)\n"}, design=False)
    tail = "## Retired or advisory\n\n" + "".join(rule(i) for i in range(30, 50))
    (d / "STANDARD.md").write_text(standard(20, tail=tail))
    assert ux_check.check_repo(d)["findings"] == []
    assert len(ux_check.standard_rules(standard(20, tail=tail))) == 20


def test_a_rule_without_a_date_and_scope_line_is_a_warning(tmp_path):
    d = make(tmp_path, {"a.py": "print(1)\n"}, design=False)
    (d / "STANDARD.md").write_text(standard(3, dated=False))
    r = ux_check.check_repo(d)
    assert r["verdict"] == "WARN"
    f = r["findings"][0]
    assert f["check"] == "standard" and "3 rule(s)" in f["message"] and "R1, R2, R3" in f["message"]
    (d / "STANDARD.md").write_text(standard(3).replace("Since 2026-10-16 · Scope: every screen", "Since 2026-10-16", 1))
    assert "1 rule(s)" in ux_check.check_repo(d)["findings"][0]["message"]


def test_teylas_own_standard_is_found_under_templates_and_passes(tmp_path):
    d = make(tmp_path, {"a.py": "print(1)\n"}, design=False)
    (d / "templates" / "design").mkdir(parents=True)
    (d / "templates" / "design" / "STANDARD.md").write_text(standard(21))
    assert ux_check.check_repo(d)["findings"][0]["file"] == "templates/design/STANDARD.md"
    real = pathlib.Path(ux_check.__file__).resolve().parents[2] / "templates" / "design"
    rules = ux_check.standard_rules((real / "STANDARD.md").read_text())
    assert 1 <= len(rules) <= ux_check.STANDARD_MAX_RULES
    assert all(r["dated"] for r in rules)


def test_the_design_template_is_executable_and_short():
    real = pathlib.Path(ux_check.__file__).resolve().parents[2] / "templates" / "design" / "DESIGN.md"
    text = real.read_text()
    assert len(text.splitlines()) <= ux_check.DESIGN_MAX_LINES
    for marker in ("teyla:rules", "teyla:screens"):
        assert f"<!-- {marker} -->" in text and f"<!-- /{marker} -->" in text
    assert "design/screens/*.yaml" in text
    assert "| Concept | en | es | ru |" in text


# --- CLI ----------------------------------------------------------------------------------------

@pytest.fixture
def code(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "TEYLA_DIR", h / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", h / ".teyla" / "config.toml")
    root = tmp_path / "code"
    root.mkdir()
    (h / ".teyla" / "config.toml").write_text(f'code_root = "{root}"\n')
    return root


def test_cli_json_all_and_strict(code, capsys):
    make(code, {"S/V.swift": swift_view('Text("Add item")')}, name="good")
    make(code, {"S/V.swift": swift_view("\n".join(['Text("Please wait")'] * 25))}, name="bad")
    assert cli.main(["ux", "check", "--all", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {r["repo"]: r["verdict"] for r in out["repos"]} == {"good": "OK", "bad": "FIX"}
    assert out["totals"] == {"FIX": 1, "WARN": 0, "OK": 1}

    assert cli.main(["ux", "check", "good", "--strict"]) == 0
    capsys.readouterr()
    assert cli.main(["ux", "check", "bad", "--strict"]) == 1
    text = capsys.readouterr().out
    assert "copy" in text and "fix:" in text and "1 repo(s): 1 FIX" in text


def test_cli_defaults_to_the_current_git_repo(code, monkeypatch, capsys):
    d = make(code, {"S/V.swift": swift_view('Text("Add item")')}, name="here")
    monkeypatch.chdir(d)
    assert cli.main(["ux", "check"]) == 0
    assert "here" in capsys.readouterr().out


def test_cli_unknown_path(code, capsys):
    assert cli.main(["ux", "check", "/nonexistent/dir"]) == 2
