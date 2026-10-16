"""teyla ux check: synthetic repos in tmp dirs. Nothing here reads a real repo or ~/.teyla."""
from __future__ import annotations

import json

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


def test_crowded_thresholds(tmp_path):
    def view(i, taps):
        return swift_view("\n".join(['Button("Go") { }'] * taps), name=f"V{i}")
    one = ux_check.check_repo(make(tmp_path, {"S/A.swift": view(1, 5)}, name="one"))
    assert one["verdict"] == "WARN" and one["findings"][0]["check"] == "crowded"
    ten = ux_check.check_repo(make(tmp_path, {f"S/V{i}.swift": view(i, 5) for i in range(10)}, name="ten"))
    assert ten["verdict"] == "FIX"
    severe = ux_check.check_repo(make(tmp_path, {f"S/V{i}.swift": view(i, 10) for i in range(3)}, name="severe"))
    assert severe["verdict"] == "FIX"
    two_severe = ux_check.check_repo(make(tmp_path, {f"S/V{i}.swift": view(i, 10) for i in range(2)}, name="two"))
    assert two_severe["verdict"] == "WARN"


def test_copy_thresholds(tmp_path):
    def rep(n, name):
        body = "\n".join(['Text("Please wait")'] * n)
        return ux_check.check_repo(make(tmp_path, {"S/V.swift": swift_view(body)}, name=name))
    assert rep(1, "a")["verdict"] == "WARN"
    assert rep(24, "b")["verdict"] == "WARN"
    r = rep(25, "c")
    assert r["verdict"] == "FIX" and any(f["check"] == "copy" for f in r["findings"])


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
    make(code, {f"S/V{i}.swift": swift_view("\n".join(['Button("Go") { }'] * 5), name=f"V{i}") for i in range(10)}, name="bad")
    assert cli.main(["ux", "check", "--all", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {r["repo"]: r["verdict"] for r in out["repos"]} == {"good": "OK", "bad": "FIX"}
    assert out["totals"] == {"FIX": 1, "WARN": 0, "OK": 1}

    assert cli.main(["ux", "check", "good", "--strict"]) == 0
    capsys.readouterr()
    assert cli.main(["ux", "check", "bad", "--strict"]) == 1
    text = capsys.readouterr().out
    assert "crowded" in text and "fix:" in text and "1 repo(s): 1 FIX" in text


def test_cli_defaults_to_the_current_git_repo(code, monkeypatch, capsys):
    d = make(code, {"S/V.swift": swift_view('Text("Add item")')}, name="here")
    monkeypatch.chdir(d)
    assert cli.main(["ux", "check"]) == 0
    assert "here" in capsys.readouterr().out


def test_cli_unknown_path(code, capsys):
    assert cli.main(["ux", "check", "/nonexistent/dir"]) == 2
