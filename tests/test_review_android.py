"""packages/review-android (docs/REVIEW.md, "Android"): the real module and the no-op module expose one
public API, the no-op holds no `ReviewOverlay`, and the golden capture the JVM tests pin matches the schema.

None of it needs a JDK or the Android SDK: the API check reads the Kotlin sources. The build of a real
fixture app in both variants is in tests/test_review_android_build.py, which skips without the SDK."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from teyla import review_gate as gate
from test_review_capture import SCHEMA, validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "review-android"
REAL = PKG / "teyla-review" / "src" / "main" / "kotlin"
NOOP = PKG / "teyla-review-noop" / "src" / "main" / "kotlin"
GOLDEN = ROOT / "tests" / "fixtures" / "review-android-capture.json"

# ---- a reader for the public declarations of a Kotlin source tree ------------------------------------------
# It reads the style these two modules are written in, not all of Kotlin: one declaration per line start,
# modifiers before the keyword, braces balanced, no raw strings. The self-tests below pin that.

_HEAD = re.compile(
    r"(?:^|(?<=[{;]))[ \t]*((?:@\w+(?:\([^)\n]*\))?[ \t]*\n?[ \t]*)*)((?:(?:public|private|internal|protected|override|open|abstract|data|enum|sealed|inline|const|lateinit|suspend|operator|infix|final)[ \t]+)*)(class|object|interface|fun|val|var|typealias)\b",
    re.M,
)
_HIDDEN = {"private", "internal", "protected"}


def _blank_strings_and_comments(src: str) -> str:
    """Comments go; each string literal becomes a short fingerprint so braces in it cannot confuse the scan."""
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            depth = 0
            while i < n:
                if src.startswith("/*", i):
                    depth += 1
                    i += 2
                elif src.startswith("*/", i):
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                else:
                    i += 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append('"' + hashlib.md5(src[i + 1 : j].encode()).hexdigest()[:8] + '"')
            i = j + 1
        elif c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            out.append("'c'")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _match_brace(s: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced braces")


def _signature_end(s: str, start: int) -> int:
    """The end of a declaration's head: a `{`, an `=` or ` get()` outside parentheses, or the line's end once they close."""
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0:
            if c == "{":
                return i
            if c == "=" and s[i - 1] in " \t" and s[i + 1] not in "=":
                return i
            if s.startswith(" get()", i) or s.startswith(" set(", i):
                return i
            if c == "\n":
                rest = s[i + 1 :].lstrip(" \t")
                if not rest.startswith((":", "=", "{", "get(", ".", ",")) and not s[:i].rstrip(" \t").endswith((":", ",", "=")):
                    return i
        i += 1
    return len(s)


def _normal(sig: str) -> str:
    sig = re.sub(r"\s+", " ", sig).strip()
    sig = re.sub(r",\s*\)", ")", sig)
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", sig))


def _enum_entries(body: str) -> list[str]:
    head = body.split(";", 1)[0] if ";" in body else body
    out, depth, cur = [], 0, ""
    for ch in head:
        depth += ch in "(["
        depth -= ch in ")]"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [_normal(e) for e in out if e]


def declarations(src: str, path: str = "") -> set[str]:
    """Every public declaration, as `path|signature`, including enum entries."""
    s = _blank_strings_and_comments(src)
    found: set[str] = set()

    def scan(lo: int, hi: int, scope: str) -> None:
        pos = lo
        while True:
            m = _HEAD.search(s, pos, hi)
            if not m:
                return
            mods = set(m.group(2).split())
            kind = m.group(3)
            end = _signature_end(s, m.end())
            sig = _normal(s[m.start(1) if m.group(1) else m.start(2) : end])
            body_open = end if end < hi and s[end] == "{" else None
            body_close = _match_brace(s, body_open) if body_open is not None else None
            hidden = bool(mods & _HIDDEN)
            if not hidden and not (scope == "" and mods & {"override"}):
                found.add(f"{scope}|{sig}")
            if kind in ("class", "object", "interface") and body_open is not None:
                name = re.search(r"(?:class|object|interface)\s+(\w+)", sig).group(1)  # type: ignore[union-attr]
                if "enum" in mods and not hidden:
                    for e in _enum_entries(s[body_open + 1 : body_close]):
                        found.add(f"{scope + '.' if scope else ''}{name}|entry {e}")
                if not hidden:
                    scan(body_open + 1, body_close, f"{scope}.{name}" if scope else name)
            pos = (body_close + 1) if body_close is not None else max(end, m.end())

    scan(0, len(s), "")
    return found


def tree_declarations(root: pathlib.Path) -> set[str]:
    out: set[str] = set()
    for p in sorted(root.rglob("*.kt")):
        out |= declarations(p.read_text(), str(p))
    return out


# ---- the reader itself --------------------------------------------------------------------------------------

def test_the_reader_sees_public_declarations_and_skips_the_rest():
    src = '''
package x
/** doc { with a brace */
class Open(val a: String = "{", val b: Int = 1,) {
    val shown: Boolean get() = hidden
    private val hidden = true
    internal fun nope() {}
    fun yes(x: Int): String { return "}" }
}
internal class Closed { fun inside() {} }
object Single { val flag: Boolean = false }
fun Modifier.ext(id: String, r: Role = Role.Other): Modifier = this
@Composable
fun Row(modifier: Modifier = Modifier) {
    val local = 1
    fun nested() {}
}
enum class Role(val wire: String) { A("a"), B("b"); fun more() {} }
'''
    got = declarations(src)
    assert "|class Open(val a: String = \"%s\", val b: Int = 1)" % __import__("hashlib").md5(b"{").hexdigest()[:8] in got
    assert "Open|val shown: Boolean" in got
    assert "Open|fun yes(x: Int): String" in got
    assert not any("hidden" in d or "nope" in d or "Closed" in d or "inside" in d or "local" in d or "nested" in d for d in got)
    assert "Single|val flag: Boolean" in got
    wrapped = declarations("private class Node(var a: Int) :\n    Base(), Other {\n    fun inner() {}\n}\nfun outer() {}")
    assert wrapped == {"|fun outer()"}
    assert "|fun Modifier.ext(id: String, r: Role = Role.Other): Modifier" in got
    assert "|@Composable fun Row(modifier: Modifier = Modifier)" in got
    assert {"Role|entry A(\"%s\")" % __import__("hashlib").md5(b"a").hexdigest()[:8], "Role|fun more()"} <= got


def test_the_reader_notices_a_drifting_signature():
    a = declarations("object T { fun install(app: Application, config: ReviewConfig) {} }")
    assert a != declarations("object T { fun install(app: Application) {} }")
    assert a != declarations("object T { fun install(app: Application, config: ReviewConfig = X()) {} }")
    assert a != declarations("object T { fun present(app: Application, config: ReviewConfig) {} }")
    assert a == declarations("object T {\n fun install(\n app: Application,\n config: ReviewConfig,\n ) {\n } }")


# ---- the two modules ----------------------------------------------------------------------------------------

def test_the_real_module_and_the_noop_module_have_one_public_api():
    real, noop = tree_declarations(REAL), tree_declarations(NOOP)
    assert real, "no public declarations found in the real module"
    assert real == noop, f"only in the real module: {sorted(real - noop)}; only in the no-op: {sorted(noop - real)}"


def test_the_public_api_is_the_one_a_product_uses():
    api = tree_declarations(REAL)
    for needle in (
        "|object TeylaReview",
        "TeylaReview|val isEnabled: Boolean",
        "TeylaReview|fun install(application: Application, config: ReviewConfig)",
        "TeylaReview|fun present(activity: Activity)",
        "|fun Modifier.reviewPrivate(): Modifier",
        "|@Composable fun ReviewSettingsRow(modifier: Modifier = Modifier)",
    ):
        assert needle in api, needle
    assert not any("ReviewOverlay" in d or "ReviewActivity" in d for d in api), "the marker class is never public API"


def test_the_noop_module_holds_no_review_overlay():
    assert not list(NOOP.rglob("*Overlay*")), "no file named after the overlay"
    for p in NOOP.rglob("*.kt"):
        code = _blank_strings_and_comments(p.read_text())
        assert "ReviewOverlay" not in code and "ReviewActivity" not in code, p
    manifest = PKG / "teyla-review-noop" / "src" / "main" / "AndroidManifest.xml"
    assert not manifest.exists() or "<activity" not in manifest.read_text()
    assert not list((PKG / "teyla-review-noop").glob("*.pro")), "no rules that keep the marker"


def test_the_real_module_has_the_marker_class_and_keeps_its_name_under_r8():
    marker = gate.MARKER_ANDROID.decode()
    pkg, name = marker.rsplit("/", 1)[0].replace("/", "."), marker.rsplit("/", 1)[1]
    src = (REAL / "teyla" / "review" / f"{name}.kt").read_text()
    assert f"package {pkg}\n" in src
    assert re.search(rf"^internal object {name}\b", src, re.M)
    rules = (PKG / "teyla-review" / "consumer-rules.pro").read_text()
    assert f"-keep class {pkg}.{name}" in rules
    gradle = (PKG / "teyla-review" / "build.gradle.kts").read_text()
    assert 'consumerProguardFiles("consumer-rules.pro")' in gradle


def test_the_real_module_asks_for_no_microphone_and_the_noop_for_nothing():
    manifest = (PKG / "teyla-review" / "src" / "main" / "AndroidManifest.xml").read_text()
    uses = re.findall(r'uses-permission android:name="([^"]+)"', manifest)
    assert sorted(uses) == ["android.permission.ACCESS_NETWORK_STATE", "android.permission.INTERNET"]
    assert "RECORD_AUDIO" not in re.sub(r"<!--.*?-->", "", manifest, flags=re.S)


def test_no_variant_changes_the_application_id():
    for build in sorted(PKG.glob("*/build.gradle.kts")) + [PKG / "build.gradle.kts"]:
        code = "\n".join(line.split("//", 1)[0] for line in build.read_text().splitlines())
        assert "applicationIdSuffix" not in code, build


# ---- the capture the JVM tests pin ---------------------------------------------------------------------------

def test_the_golden_capture_matches_the_schema():
    doc = json.loads(GOLDEN.read_text())
    schema = json.loads(SCHEMA.read_text())
    assert validate(doc, schema, schema) == []
    assert doc["device"] == "Android"
    assert doc["app"]["configuration"] == "play_internal"
    assert doc["app"]["product"] == "sample-app"
    assert doc["element"]["id"] == "sample.list.addButton" and doc["element"]["matched_by"] == "anchor"
    assert doc["microphone"] == {"host_audio_in_use": False}


def test_the_golden_capture_breaks_the_schema_when_a_field_is_wrong():
    doc = json.loads(GOLDEN.read_text())
    schema = json.loads(SCHEMA.read_text())
    doc["app"]["configuration"] = "release"
    assert validate(doc, schema, schema) != []
