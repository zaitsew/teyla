"""`teyla ux check` — does a product's UI code follow the shared UX standard (templates/design/STANDARD.md)?

    teyla ux check [repo...] [--all] [--json] [--strict]

A static audit of view code. It reads files only: no network, no writes, no git history, and it
runs in a second or two on a large app. It cannot judge a design. It counts the mechanical
symptoms of one: values typed into views instead of taken from the product's tokens, screens with
too many tap targets, and copy that breaks the writing rules. Repos are chosen the same way as
`teyla docs check`: none given means the git root of the current directory, a name is looked up
under `code_root`, a path is used as it is, `--all` is every git repo under `code_root`.

What is counted (a "literal" is a value written in a view; the product's tokens are exempt):

    font      SwiftUI `.system(size: 17)`, `.custom("X", size: 17)`, `UIFont.x(ofSize: 17)`;
              Compose `fontSize = 17.sp`; web `font-size: 17px` and inline `fontSize: 17`.
    colour    SwiftUI `Color(red:`, `UIColor(red:`, `#colorLiteral(`, `hex: 0xRRGGBB`, a "#RRGGBB"
              string; Compose `Color(0xFF...)`, `Color.parseColor(`; web hex colours and
              rgb()/hsl() values (a CSS custom-property definition `--x: #fff` is a token and is not counted).
    spacing   SwiftUI `.padding(16)`, `.padding(.horizontal, 12)`; Compose `.padding(16.dp)`,
              `.padding(horizontal = 12.dp)`. Zero and expressions (`2 * Space.m`) are not counted.
    crowded   SwiftUI only: a `struct X: View` whose body holds more than 4 `Button`,
              `NavigationLink` and `.onTapGesture` together.
    copy      UI strings: `Text("...")`, `Button("...")`, `Label`, `Toggle`, `Section` in Swift;
              `Text("...")` in Compose; `<string>` values of Android `res/values/` and
              `values-en*`; `Localizable.strings` and `.xcstrings` in English. Counted: strings
              with the word "Please", strings with "!", and button labels over 3 words (Swift
              `Button("...")`, and Android strings named btn_/button_/cta_/action_).
    design    A DESIGN.md at the root or in docs/. Missing is WARN; one that still holds
              `{{` template placeholders is WARN.

Not read: build output and dependency dirs (build, Pods, node_modules, .build, DerivedData,
dist, vendor, hidden dirs, ...), tests, previews (`#Preview`, `PreviewProvider`, `@Preview`),
generated files (a "do not edit" or "@generated" header, `.generated.`, `.g.`), and token files
(any file named `*Tokens*`, `*Theme*`, `DesignSystem*`, `colors`, `palette`, `variables`, or
under a `theme`, `tokens` or `designsystem` dir). The scan is regex-based and approximate on
purpose: a count is a pointer to look, not a proof.

Verdicts, per repo (the worst finding wins; a repo with no UI code is OK):

    tokens    L = font + colour + spacing literals; D = L per 1,000 non-blank lines of UI files.
              WARN: L >= 10 and D >= 5.   FIX: L >= 100 and D >= 10.
    crowded   WARN: 1 or more screens.    FIX: 10 or more screens, or 3 or more with 10+ tap targets.
    copy      C = "Please" + "!" + long button labels.
              WARN: C >= 1.               FIX: C >= 25.
    design    WARN: no DESIGN.md in a repo with UI code, or one with template placeholders.

The cut-offs come from a first run over the owner's apps: a FIX is a repo where ignoring the
tokens or piling taps onto screens is the norm, not an exception. Exit status is 0, unless `--strict` is given
and a repo has a FIX (then 1). `--json` prints {"repos": [{"repo", "path", "platforms", "ui_files",
"ui_lines", "counts", "density", "worst_files", "crowded", "design_doc", "verdict", "findings":
[{"check", "severity", "file", "line", "message", "fix"}]}], "totals": {"FIX", "WARN", "OK"}}.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

from . import docs_check

FIX, WARN, OK = "FIX", "WARN", "OK"

# Thresholds (see the module docstring).
TOKENS_WARN_MIN, TOKENS_WARN_DENSITY = 10, 5.0
TOKENS_FIX_MIN, TOKENS_FIX_DENSITY = 100, 10.0
CROWDED_TAPS = 4          # more than this many tap targets in one View struct
CROWDED_WARN, CROWDED_FIX = 1, 10
SEVERE_TAPS, SEVERE_FIX = 10, 3   # a screen with 10+ tap targets is severe; 3 severe screens are FIX
COPY_WARN, COPY_FIX = 1, 25
BUTTON_MAX_WORDS = 3
WORST_FILES = 5
MAX_FILE_BYTES = 1_000_000

SKIP_DIRS = {
    "build", "pods", "node_modules", "deriveddata", "carthage", "dist", "out", "vendor", "target",
    "generated", "gen", "coverage", "__snapshots__", "tests", "test", "__tests__", "androidtest",
    "e2e", "previews", "_astro", "_next", "preview content", "storybook", "__pycache__", "venv",
}
TEST_DIR = re.compile(r"(Tests?|_tests?|-tests?)$")
TOKEN_DIRS = {"theme", "themes", "tokens", "designsystem", "design-system", "design_system"}
TOKEN_STEMS = {"colors", "colours", "palette", "variables", "vars", "_variables", "_vars", "_colors"}
GENERATED_HEAD = re.compile(r"do not edit|@generated|auto-?generated|generated by|swiftgen", re.I)

SWIFT, KOTLIN, WEB = "swiftui", "compose", "web"
WEB_SUFFIX = {".tsx", ".jsx", ".css", ".scss", ".vue", ".svelte"}
HTMLISH = {".vue", ".svelte"}


# --- reading source -----------------------------------------------------------------------------

def strip_comments(text: str, quotes: str = '"', line_comments: bool = True) -> str:
    """The text with comments replaced by spaces (newlines and offsets kept). Strings survive:
    their content is read by the copy check. Approximate: a quote left open ends at the newline."""
    out = []
    i, n = 0, len(text)
    q = None
    triple = False
    while i < n:
        c = text[i]
        if q:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if triple and text.startswith('"""', i):
                out.append('""')
                i += 3
                q, triple = None, False
                continue
            if not triple and c == q:
                q = None
            elif c == "\n" and not triple and q != "`":
                q = None
            i += 1
            continue
        if c in quotes:
            if c == '"' and text.startswith('"""', i):
                out.append('"""')
                i += 3
                q, triple = '"', True
                continue
            q = c
            out.append(c)
            i += 1
            continue
        if line_comments and c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def match_brace(text: str, open_idx: int) -> int:
    """Index just past the `}` that closes the `{` at open_idx (end of text when unbalanced).
    Braces inside "string" literals are skipped."""
    depth, i, n = 0, open_idx, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"' or c == "\n":
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def blank_blocks(text: str, pattern: re.Pattern) -> str:
    """Replace every brace block that follows a match of `pattern` (which must end at its `{`)
    with spaces, keeping newlines, so previews do not count."""
    out = text
    for m in list(pattern.finditer(text)):
        end = match_brace(text, m.end() - 1)
        out = out[:m.start()] + re.sub(r"[^\n]", " ", out[m.start():end]) + out[end:]
    return out


SWIFT_PREVIEW = re.compile(r"#Preview\b[^{\n]*\{|struct\s+\w+\s*:\s*[^{\n]*\bPreviewProvider\b[^{\n]*\{")
KOTLIN_PREVIEW = re.compile(r"@(?:\w+\.)?Preview\b[^\n]*\n(?:\s*@\w+[^\n]*\n)*\s*(?:private\s+|internal\s+)?fun\s+\w+\s*\([^)]*\)\s*(?::\s*\w+\s*)?\{")


# --- which files --------------------------------------------------------------------------------

def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name.lower() in SKIP_DIRS or bool(TEST_DIR.search(name)) or name.endswith((".xcodeproj", ".xcassets", ".xcworkspace"))


def _is_token_file(path: pathlib.Path, rel_parts: tuple[str, ...]) -> bool:
    stem = path.name.split(".")[0].lower()
    if "tokens" in stem or "theme" in stem or stem.startswith("designsystem") or stem in TOKEN_STEMS:
        return True
    if stem.startswith("tailwind"):
        return True
    return any(p.lower() in TOKEN_DIRS for p in rel_parts[:-1])


def _skip_file(path: pathlib.Path) -> bool:
    name = path.name
    low = name.lower()
    stem = name.split(".")[0]
    if re.search(r"(Tests?|Spec)$", stem) or re.search(r"\.(test|spec|stories)\.", low):
        return True
    if "preview" in stem.lower() and path.suffix in (".swift", ".kt"):
        return True
    if re.search(r"\.(generated|g|gen)\.", low) or "generated" in stem.lower() or low.endswith((".pb.swift", ".min.css", ".min.js")):
        return True
    return False


def _walk(root: pathlib.Path):
    for cur, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not _skip_dir(d))
        for f in sorted(files):
            yield pathlib.Path(cur) / f


def _read(path: pathlib.Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(errors="replace")
    except OSError:
        return None


def _generated(text: str) -> bool:
    return bool(GENERATED_HEAD.search(text[:400]))


# --- the patterns -------------------------------------------------------------------------------

NUM = r"\d+(?:\.\d+)?"

SW_FONT = re.compile(r"\.system\(\s*size:\s*\d|\.custom\([^)\n]*\bsize:\s*\d|\bUIFont\.\w+\(\s*ofSize:\s*\d")
SW_COLOR = re.compile(
    r"\bColor\(\s*(?:\.\w+\s*,\s*)?red:|\bUIColor\(\s*red:|#colorLiteral\(|\bhex\s*:\s*0x[0-9A-Fa-f]{6,8}|[\"']#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})[\"']")
KT_FONT = re.compile(rf"\bfontSize\s*=\s*{NUM}\.sp")
KT_COLOR = re.compile(r"\bColor\(\s*0x[0-9A-Fa-f]{6,8}|\bColor\.parseColor\(|\bColor\(\s*(?:red|alpha)\s*=")
WEB_FONT = re.compile(rf"(?<![-\w])font-size\s*:\s*{NUM}px|(?<![-\w])fontSize\s*:\s*['\"]?{NUM}(?:px)?['\"]?")
WEB_HEX = re.compile(r"(?<![\w&#])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
WEB_FUNC = re.compile(r"\b(?:rgba?|hsla?)\(\s*\d")
NOT_COLOR_CONTEXT = re.compile(r"(?:\b(?:href|id|for|to|xlink:href)\s*=\s*|url\()\s*['\"]?$")
CSS_VAR_DEF = re.compile(r"(?<![\w-])--[\w-]+\s*:\s*[^;}]*")
SW_NUM = re.compile(rf"(?<![\w.]){NUM}(?![\w.])")


def _padding_literals(line: str, kotlin: bool) -> int:
    """Count `.padding(...)` calls on this line whose arguments hold a non-zero numeric literal."""
    n = 0
    for m in re.finditer(r"\.padding\(", line):
        depth, i = 1, m.end()
        while i < len(line) and depth:
            depth += {"(": 1, ")": -1}.get(line[i], 0)
            i += 1
        if depth:
            continue
        inner = line[m.end():i - 1]
        if re.search(r"[*/]|\s\+\s", inner):
            continue
        nums = re.findall(rf"(?<![\w.])({NUM})\.dp\b", inner) if kotlin else SW_NUM.findall(inner)
        if any(float(x) != 0 for x in nums):
            n += 1
    return n


def _web_colors(line: str) -> int:
    line = CSS_VAR_DEF.sub("", line)  # a custom-property definition is a token, not a literal
    n = len(WEB_FUNC.findall(line))
    for m in WEB_HEX.finditer(line):
        before = line[:m.start()]
        if NOT_COLOR_CONTEXT.search(before):
            continue
        if not re.search(r"[:=(,\[\s]['\"`]?\s*$", before) or not before.strip():
            continue
        if before.rstrip().endswith((",", "}")) and ":" not in before and "(" not in before and "'" not in before and '"' not in before:
            continue  # a selector list: `a, #fff {`
        n += 1
    return n


# --- copy ---------------------------------------------------------------------------------------

SW_TEXT = re.compile(r"\b(Text|Button|Label|Toggle|Section|NavigationLink|Link|Menu)\(\s*(?:verbatim:\s*)?\"((?:[^\"\\\n]|\\.)*)\"")
KT_TEXT = re.compile(r"\bText\(\s*(?:text\s*=\s*)?\"((?:[^\"\\\n]|\\.)*)\"")
PLEASE = re.compile(r"\bplease\b", re.I)
BANG = re.compile(r"!(?!=)")
BUTTON_NAME = re.compile(r"(?:^|_)(?:btn|button|cta|action)(?:_|$)", re.I)


def _words(s: str) -> int:
    s = re.sub(r"\\\([^)]*\)|%[@dsf]|%\d\$[@dsf]|\{[^}]*\}", "x", s)  # an interpolation counts as one word
    return len(s.split())


def _copy(strings: list[tuple[str, str, bool]]) -> dict:
    """strings: (text, ..., is_button). Counts only."""
    c = {"please": 0, "bang": 0, "long_button": 0}
    for s, _kind, is_button in strings:
        if PLEASE.search(s):
            c["please"] += 1
        if BANG.search(s):
            c["bang"] += 1
        if is_button and _words(s) > BUTTON_MAX_WORDS:
            c["long_button"] += 1
    return c


# --- one file -----------------------------------------------------------------------------------

def _new() -> dict:
    return {"font": 0, "colour": 0, "spacing": 0, "please": 0, "bang": 0, "long_button": 0}


def _add(a: dict, b: dict):
    for k, v in b.items():
        if k in a:
            a[k] += v


def scan_swift(text: str) -> tuple[dict, list[dict]]:
    code = blank_blocks(strip_comments(text), SWIFT_PREVIEW)
    c = _new()
    strings: list[tuple[str, str, bool]] = []
    for ln in code.splitlines():
        c["font"] += len(SW_FONT.findall(ln))
        c["colour"] += len(SW_COLOR.findall(ln))
        c["spacing"] += _padding_literals(ln, kotlin=False)
        for m in SW_TEXT.finditer(ln):
            strings.append((m.group(2), m.group(1), m.group(1) == "Button"))
    _add(c, _copy(strings))
    crowded = []
    for m in re.finditer(r"\bstruct\s+(\w+)\s*:\s*([^{\n]*)\{", code):
        if not re.search(r"\bView\b", m.group(2)):
            continue
        body = code[m.end() - 1:match_brace(code, m.end() - 1)]
        taps = len(re.findall(r"\bButton\s*[({]|\bNavigationLink\s*[({]|\.onTapGesture\b", body))
        if taps > CROWDED_TAPS:
            crowded.append({"view": m.group(1), "taps": taps, "line": code.count("\n", 0, m.start()) + 1})
    return c, crowded


def scan_kotlin(text: str) -> dict:
    code = blank_blocks(strip_comments(text, quotes='"\''), KOTLIN_PREVIEW)
    c = _new()
    strings = []
    for ln in code.splitlines():
        c["font"] += len(KT_FONT.findall(ln))
        c["colour"] += len(KT_COLOR.findall(ln))
        c["spacing"] += _padding_literals(ln, kotlin=True)
        for m in KT_TEXT.finditer(ln):
            strings.append((m.group(1), "Text", False))
    _add(c, _copy(strings))
    return c


def scan_web(text: str, suffix: str) -> dict:
    if suffix in HTMLISH:
        text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    code = strip_comments(text, quotes="" if suffix == ".css" else "'\"`", line_comments=suffix != ".css")
    c = _new()
    for ln in code.splitlines():
        c["font"] += len(WEB_FONT.findall(ln))
        c["colour"] += _web_colors(ln)
    return c


def scan_android_strings(text: str) -> dict:
    strings = []
    for m in re.finditer(r"<string\s+([^>]*)>(.*?)</string>", text, flags=re.S):
        attrs, val = m.group(1), m.group(2)
        if 'translatable="false"' in attrs:
            continue
        name = re.search(r'name="([^"]+)"', attrs)
        val = re.sub(r"<[^>]+>", "", val).replace("\\'", "'").replace("\\n", " ")
        strings.append((val, "string", bool(name and BUTTON_NAME.search(name.group(1)))))
    return _copy(strings)


def scan_strings_file(text: str) -> dict:
    strings = []
    for m in re.finditer(r'^\s*"(?:[^"\\]|\\.)*"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text, flags=re.M):
        strings.append((m.group(1), "string", False))
    return _copy(strings)


def scan_xcstrings(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    src = data.get("sourceLanguage", "en")
    if not str(src).startswith("en"):
        return {}
    strings = []
    for key, entry in (data.get("strings") or {}).items():
        loc = ((entry or {}).get("localizations") or {}).get(src) or {}
        val = (loc.get("stringUnit") or {}).get("value")
        strings.append((val if isinstance(val, str) else key, "string", False))
    return _copy(strings)


# --- a repo -------------------------------------------------------------------------------------

def _find_design_doc(root: pathlib.Path) -> pathlib.Path | None:
    for d in (root, root / "docs"):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.name.lower() == "design.md":
                    return p
    return None


def _finding(check, severity, file, line, message, fix):
    return {"check": check, "severity": severity, "file": file, "line": line, "message": message, "fix": fix}


def audit(root: pathlib.Path) -> dict:
    """The raw measurements for a repo, with no verdicts."""
    root = pathlib.Path(root)
    counts = _new()
    per_file: dict[str, dict] = {}
    crowded: list[dict] = []
    platforms: set[str] = set()
    ui_files = ui_lines = 0
    for path in _walk(root):
        rel_parts = path.relative_to(root).parts
        rel = "/".join(rel_parts)
        suffix = path.suffix.lower()
        parent = path.parent.name.lower()
        res_dir = suffix == ".xml" and path.name == "strings.xml" and (parent == "values" or parent.startswith("values-en")) and "res" in [p.lower() for p in rel_parts]
        strings_file = suffix == ".strings" and parent in ("en.lproj", "base.lproj")
        xcstrings = suffix == ".xcstrings"
        is_code = suffix in (".swift", ".kt") or suffix in WEB_SUFFIX
        if not (is_code or res_dir or strings_file or xcstrings):
            continue
        if is_code and _skip_file(path):
            continue
        if is_code and _is_token_file(path, rel_parts):
            continue
        text = _read(path)
        if text is None or (is_code and _generated(text)):
            continue
        fc = None
        if suffix == ".swift":
            if not re.search(r"^\s*import\s+(SwiftUI|UIKit)\b", text, re.M):
                continue
            platforms.add(SWIFT)
            fc, cr = scan_swift(text)
            crowded += [{"file": rel, **x} for x in cr]
        elif suffix == ".kt":
            if "@Composable" not in text:
                continue
            platforms.add(KOTLIN)
            fc = scan_kotlin(text)
        elif suffix in WEB_SUFFIX:
            platforms.add(WEB)
            fc = scan_web(text, suffix)
        elif res_dir:
            fc = scan_android_strings(text)
        elif strings_file:
            fc = scan_strings_file(text)
        elif xcstrings:
            fc = scan_xcstrings(text)
        if fc is None:
            continue
        if is_code:
            ui_files += 1
            ui_lines += sum(1 for ln in text.splitlines() if ln.strip())
        full = {**_new(), **fc}
        _add(counts, full)
        if any(full.values()):
            per_file[rel] = full
    literals = counts["font"] + counts["colour"] + counts["spacing"]
    worst = sorted(
        ({"file": f, "font": v["font"], "colour": v["colour"], "spacing": v["spacing"], "total": v["font"] + v["colour"] + v["spacing"]}
         for f, v in per_file.items() if v["font"] + v["colour"] + v["spacing"]),
        key=lambda x: (-x["total"], x["file"]))[:WORST_FILES]
    crowded.sort(key=lambda x: (-x["taps"], x["file"]))
    return {
        "platforms": sorted(platforms), "ui_files": ui_files, "ui_lines": ui_lines,
        "counts": counts, "literals": literals,
        "density": round(literals * 1000 / ui_lines, 1) if ui_lines else 0.0,
        "worst_files": worst, "crowded": crowded,
    }


def verdicts(root: pathlib.Path, a: dict) -> list[dict]:
    findings: list[dict] = []
    if not a["ui_files"]:
        return findings
    c = a["counts"]
    lit, dens = a["literals"], a["density"]
    sev = None
    if lit >= TOKENS_FIX_MIN and dens >= TOKENS_FIX_DENSITY:
        sev = FIX
    elif lit >= TOKENS_WARN_MIN and dens >= TOKENS_WARN_DENSITY:
        sev = WARN
    if sev:
        w = a["worst_files"][0] if a["worst_files"] else None
        worst = ", ".join(f"{x['file']} ({x['total']})" for x in a["worst_files"][:3])
        findings.append(_finding(
            "tokens", sev, w["file"] if w else "", 0,
            f"{lit} literals in views ({c['font']} font, {c['colour']} colour, {c['spacing']} spacing), {dens} per 1,000 lines; worst: {worst}",
            "replace font sizes, colours and spacing in views with the product's tokens, worst files first"))
    n = len(a["crowded"])
    if n >= CROWDED_WARN:
        severe = sum(1 for x in a["crowded"] if x["taps"] >= SEVERE_TAPS)
        sev = FIX if n >= CROWDED_FIX or severe >= SEVERE_FIX else WARN
        top = a["crowded"][0]
        names = ", ".join(f"{x['view']} ({x['taps']})" for x in a["crowded"][:3])
        findings.append(_finding(
            "crowded", sev, top["file"], top["line"],
            f"{n} screen(s) with more than {CROWDED_TAPS} tap targets in one View: {names}",
            "keep one primary action per screen; move the rest behind a menu, a detail screen or a sheet"))
    cp = c["please"] + c["bang"] + c["long_button"]
    if cp >= COPY_WARN:
        sev = FIX if cp >= COPY_FIX else WARN
        findings.append(_finding(
            "copy", sev, "", 0,
            f"{cp} UI string(s) break the copy rules: {c['please']} with \"Please\", {c['bang']} with \"!\", {c['long_button']} button label(s) over {BUTTON_MAX_WORDS} words",
            "button = verb + object in at most 3 words; no \"Please\"; no exclamation marks"))
    return findings


def check_repo(root: pathlib.Path) -> dict:
    root = pathlib.Path(root)
    a = audit(root)
    findings = verdicts(root, a)
    doc = _find_design_doc(root)
    if a["ui_files"]:
        if doc is None:
            findings.append(_finding("design-doc", WARN, "DESIGN.md", 0, "no DESIGN.md at the root or in docs/",
                                     "copy templates/design/DESIGN.md: tokens, voice, screen inventory, what is deliberately absent"))
        else:
            txt = _read(doc) or ""
            if "{{" in txt:
                findings.append(_finding("design-doc", WARN, str(doc.relative_to(root)), 1, "DESIGN.md still holds template placeholders",
                                         "fill in the tokens, the voice section and the screen inventory"))
    verdict = FIX if any(f["severity"] == FIX for f in findings) else WARN if findings else OK
    return {"repo": root.name, "path": str(root), "verdict": verdict, "design_doc": doc is not None, **a, "findings": findings}


def totals(reports: list[dict]) -> dict:
    return {s: sum(1 for r in reports if r["verdict"] == s) for s in (FIX, WARN, OK)}


# --- CLI ----------------------------------------------------------------------------------------

def render(reports: list[dict]) -> str:
    L: list[str] = []
    w = max([len(r["repo"]) for r in reports] + [4])
    L.append(f"{'repo':<{w}}  verdict  ui   files  font  colour  space  /kloc  crowded  copy  design")
    for r in reports:
        c = r["counts"]
        ui = "+".join(p[:2] for p in r["platforms"]) or "-"
        copy = c["please"] + c["bang"] + c["long_button"]
        L.append(f"{r['repo']:<{w}}  {r['verdict']:<7}  {ui:<4} {r['ui_files']:>5}  {c['font']:>4}  {c['colour']:>6}  {c['spacing']:>5}  {r['density']:>5}  {len(r['crowded']):>7}  {copy:>4}  {'yes' if r['design_doc'] else 'no' if r['ui_files'] else '-'}")
    for r in reports:
        if not r["findings"]:
            continue
        L.append("")
        L.append(f"{r['repo']}:")
        for f in r["findings"]:
            where = f["file"] + (f":{f['line']}" if f["line"] else "")
            L.append(f"  {f['severity']:<4} {f['check']:<10} {where + '  ' if where else ''}{f['message']}")
            L.append(f"       fix: {f['fix']}")
        if r["worst_files"]:
            L.append("  worst files (font/colour/spacing):")
            for x in r["worst_files"]:
                L.append(f"    {x['total']:>4}  {x['file']}  ({x['font']}/{x['colour']}/{x['spacing']})")
    t = totals(reports)
    L.append("")
    L.append(f"{len(reports)} repo(s): {t[FIX]} FIX, {t[WARN]} WARN, {t[OK]} OK")
    return "\n".join(L)


def cmd_ux(args) -> int:
    if args.action in ("shots", "diff", "accept"):
        from . import ux_shots
        return ux_shots.cmd(args)
    if args.action != "check":
        print(f"teyla ux: unknown action {args.action!r}", file=sys.stderr)
        return 2
    try:
        repos = docs_check.resolve(args.repos, args.all)
    except FileNotFoundError as e:
        print(f"teyla ux check: {e}", file=sys.stderr)
        return 2
    reports = [check_repo(r) for r in repos]
    if args.json:
        print(json.dumps({"repos": reports, "totals": totals(reports)}, indent=1))
    else:
        print(render(reports))
    return 1 if args.strict and totals(reports)[FIX] else 0


def register(sp):
    q = sp.add_parser("ux", help="does a product's UI code follow the shared UX standard: literals instead of tokens, crowded screens, copy rules, DESIGN.md")
    q.set_defaults(fn=cmd_ux)
    q.add_argument("action", choices=["check", "shots", "diff", "accept"])
    q.add_argument("repos", nargs="*", help="repo names under code_root or paths (default: the git root of the current directory)")
    q.add_argument("--all", action="store_true", help="every git repo under code_root")
    q.add_argument("--json", action="store_true")
    q.add_argument("--strict", action="store_true", help="exit 1 when any repo has a FIX")
    from . import ux_shots
    ux_shots.add_arguments(q)
    return q
