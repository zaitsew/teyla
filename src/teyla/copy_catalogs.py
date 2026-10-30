"""String catalogs for `teyla copy`: read what a screen shows today, write the kept rows back.

Four kinds, each read and written without touching what it does not own:

    xcstrings   Xcode string catalogs (JSON). A key keeps its place; a language that is not named is not
                touched; a key is never added, removed or reordered. The file is written in Xcode's own
                layout (two spaces, ` : `), so a no-op round trip is byte-identical and a change is a
                small diff. A string with plural or device variations is read (the "other" form) and
                never written: the tool says so and leaves it to a person.
    strings.xml Android `res/values/strings.xml` (English), `values-es` (or `values-es-rES`), `values-ru`.
                Edited in place with the text around each string left as it was. A key that the
                language file lacks is appended before `</resources>`.
    i18n        A web file that holds a JSON-like object with one object per language, as
                `export default { en: {...}, es: {...}, ru: {...} }` in `i18n.ts`, or a `.json` of the same
                shape. "JSON-like" is strict: double-quoted strings, optional bare keys and trailing
                commas, no comments, no calls. Anything else is refused with the reason. A written file is
                rewritten as indented JSON between the unchanged text before and after the object.
    lang files  `locales/{lang}.json`: one JSON object per language, flat or nested (dotted keys).

A screen names its catalogs in `design/screens/<screen>.yaml` (`catalog:` for xcstrings and Android
paths, `i18n:` for a web file; a list is allowed). Without them the repo is scanned for `*.xcstrings` and
`res/values*/strings.xml`.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

LANGS = ("en", "es", "ru")
SKIP_DIRS = {"build", "Pods", "node_modules", ".build", "DerivedData", "dist", "vendor", "Carthage", ".git",
             ".gradle", ".idea", "__pycache__", ".venv", "venv", "out", "target"}


class CatalogError(ValueError):
    """A catalog cannot be read or written; the message says what to do by hand."""


def _write_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def walk(repo: pathlib.Path, suffix: str):
    """Files under `repo` ending in `suffix`, skipping build output, dependency and hidden directories."""
    for dirpath, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            if f.endswith(suffix):
                yield pathlib.Path(dirpath) / f


class Catalog:
    kind = ""

    def __init__(self, path: pathlib.Path, root: pathlib.Path):
        self.path = path
        self.label = _rel(path, root)
        self.touched: set[pathlib.Path] = set()

    def has(self, key: str) -> bool:                      # pragma: no cover - interface
        raise NotImplementedError

    def get(self, key: str, lang: str) -> str | None:     # pragma: no cover
        raise NotImplementedError

    def set(self, key: str, lang: str, text: str) -> str:  # pragma: no cover
        """"changed", "same", or "skipped: <why>"."""
        raise NotImplementedError

    def save(self) -> list[pathlib.Path]:                 # pragma: no cover
        raise NotImplementedError


def _rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# --- xcstrings -------------------------------------------------------------------------------------

class XcStrings(Catalog):
    kind = "xcstrings"

    def __init__(self, path: pathlib.Path, root: pathlib.Path):
        super().__init__(path, root)
        try:
            self.text = path.read_text(encoding="utf-8")
            self.data = json.loads(self.text)
        except (OSError, ValueError) as e:
            raise CatalogError(f"{self.label}: cannot read the catalog ({e})") from None
        if not isinstance(self.data, dict) or not isinstance(self.data.get("strings"), dict):
            raise CatalogError(f"{self.label}: not a string catalog (no `strings` object)")
        self.source = str(self.data.get("sourceLanguage") or "en")
        self.dirty = False

    def has(self, key: str) -> bool:
        return key in self.data["strings"]

    def get(self, key: str, lang: str) -> str | None:
        entry = self.data["strings"].get(key)
        if not isinstance(entry, dict):
            return None
        loc = (entry.get("localizations") or {}).get(lang)
        if isinstance(loc, dict):
            unit = loc.get("stringUnit")
            if isinstance(unit, dict) and isinstance(unit.get("value"), str):
                return unit["value"]
            plural = ((loc.get("variations") or {}).get("plural") or {}).get("other")
            if isinstance(plural, dict) and isinstance((plural.get("stringUnit") or {}).get("value"), str):
                return plural["stringUnit"]["value"]
            return None
        if lang == self.source and re.search(r"\s", key):      # a literal-text key shows itself
            return key
        return None

    def set(self, key: str, lang: str, text: str) -> str:
        entry = self.data["strings"].get(key)
        if not isinstance(entry, dict):
            return "skipped: the key is not in the catalog"
        if entry.get("shouldTranslate") is False:
            return "skipped: the key is marked shouldTranslate = false"
        locs = entry.get("localizations")
        loc = locs.get(lang) if isinstance(locs, dict) else None
        if isinstance(loc, dict) and ("variations" in loc or "substitutions" in loc or "stringUnit" not in loc):
            return "skipped: the string has plural or device variations; edit it by hand"
        if isinstance(loc, dict):
            unit = loc["stringUnit"]
            if unit.get("value") == text and unit.get("state", "translated") == "translated":
                return "same"
            unit["value"] = text
            unit["state"] = "translated"
        else:
            if locs is None:
                locs = entry["localizations"] = {}
            if lang == self.source and re.search(r"\s", key) and key == text:
                return "same"
            locs[lang] = {"stringUnit": {"state": "translated", "value": text}}
            if list(locs)[:-1] == sorted(list(locs)[:-1]):       # keep Xcode's alphabetical order when it was kept
                entry["localizations"] = dict(sorted(locs.items()))
        self.dirty = True
        return "changed"

    def dumps(self) -> str:
        xcode = ' : "' in self.text or '" : ' in self.text
        out = json.dumps(self.data, indent=2, ensure_ascii=False, separators=(",", " : " if xcode else ": "))
        return out + ("\n" if self.text.endswith("\n") else "")

    def save(self) -> list[pathlib.Path]:
        if not self.dirty:
            return []
        _write_atomic(self.path, self.dumps())
        self.dirty = False
        return [self.path]


# --- Android strings.xml ---------------------------------------------------------------------------

_ANDROID_STRING = re.compile(r'(<string\b(?P<attrs>[^>]*?)>)(?P<body>.*?)(</string>)', re.S)
_NAME = re.compile(r'\bname\s*=\s*"([^"]+)"')
_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}
ANDROID_DIRS = {"en": ("values-en", "values"), "es": ("values-es-rES", "values-es"), "ru": ("values-ru",)}
ANDROID_NEW_DIR = {"en": "values", "es": "values-es", "ru": "values-ru"}       # where a missing language file is created
XML_HEAD = '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n'


def android_unescape(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    s = re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), s)
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return s


def android_escape(text: str) -> str:
    s = text.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n")
    return "\\" + s if s[:1] in "@?" else s


class AndroidStrings(Catalog):
    """One `res` directory: its default strings and the language folders next to it."""
    kind = "strings.xml"

    def __init__(self, res: pathlib.Path, root: pathlib.Path):
        super().__init__(res, root)
        self.res = res
        self.files: dict[str, pathlib.Path] = {}
        for lang, names in ANDROID_DIRS.items():
            for n in names:
                if (res / n / "strings.xml").is_file():
                    self.files[lang] = res / n / "strings.xml"
                    break
        if "en" not in self.files:
            raise CatalogError(f"{self.label}: no values/strings.xml")
        self.texts = {lang: p.read_text(encoding="utf-8") for lang, p in self.files.items()}
        self.dirty: set[str] = set()

    def _find(self, lang: str, key: str):
        for m in _ANDROID_STRING.finditer(self.texts.get(lang, "")):
            nm = _NAME.search(m.group("attrs"))
            if nm and nm.group(1) == key:
                return m
        return None

    def has(self, key: str) -> bool:
        return self._find("en", key) is not None

    def get(self, key: str, lang: str) -> str | None:
        m = self._find(lang, key)
        return android_unescape(m.group("body")) if m else None

    def set(self, key: str, lang: str, text: str) -> str:
        m = self._find("en", key)
        if m and 'translatable="false"' in m.group("attrs"):
            return "skipped: the string is marked translatable = false"
        if lang not in self.texts:
            folder = self.res / ANDROID_NEW_DIR[lang]
            self.files[lang] = folder / "strings.xml"
            self.texts[lang] = XML_HEAD
        cur = self._find(lang, key)
        body = android_escape(text)
        if cur:
            if cur.group("body") == body or android_unescape(cur.group("body")) == text:
                return "same"
            t = self.texts[lang]
            self.texts[lang] = t[:cur.start("body")] + body + t[cur.end("body"):]
        else:
            t = self.texts[lang]
            i = t.rfind("</resources>")
            if i < 0:
                return "skipped: the language file has no </resources>"
            self.texts[lang] = t[:i] + f'    <string name="{key}">{body}</string>\n' + t[i:]
        self.dirty.add(lang)
        return "changed"

    def save(self) -> list[pathlib.Path]:
        out = []
        for lang in sorted(self.dirty):
            _write_atomic(self.files[lang], self.texts[lang])
            out.append(self.files[lang])
        self.dirty.clear()
        return out


# --- JSON-like web files ---------------------------------------------------------------------------

_BARE_KEY = re.compile(r"[A-Za-z_$][\w$]*")


def _object_span(text: str) -> tuple[int, int]:
    """(start, end) of the first top-level `{...}` after an `export`, `const` or `module.exports` assignment."""
    m = re.search(r"(?:export\s+default|export\s+const\s+[\w$]+(?:\s*:\s*[^=\n]+)?\s*=|const\s+[\w$]+\s*=|"
                  r"module\.exports\s*=)\s*", text)
    start = text.find("{", m.end() if m else 0)
    if start < 0 or (m and text[m.end():start].strip()):
        raise CatalogError("no object literal after `export default` or an assignment")
    depth, quote, i = 0, "", start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    raise CatalogError("the object literal is not closed")


def json_like(literal: str):
    """Parse a strict JSON-like literal: double-quoted strings, bare identifier keys, trailing commas.
    Comments, single quotes, template strings and expressions are CatalogError."""
    out, i, n = [], 0, len(literal)
    while i < n:
        c = literal[i]
        if c == '"':
            j = i + 1
            while j < n and literal[j] != '"':
                j += 2 if literal[j] == "\\" else 1
            out.append(literal[i:j + 1])
            i = j + 1
        elif c in "'`":
            raise CatalogError("the object uses single-quoted or template strings; it is not JSON-like")
        elif c == "/" and literal[i + 1:i + 2] in ("/", "*"):
            raise CatalogError("the object has comments; it is not JSON-like")
        elif c == ",":
            rest = literal[i + 1:].lstrip()
            if not rest[:1] in ("}", "]"):
                out.append(c)
            i += 1
        elif _BARE_KEY.match(literal, i) and (i == 0 or not (literal[i - 1].isalnum() or literal[i - 1] in "_$")):
            word = _BARE_KEY.match(literal, i).group(0)
            after = literal[i + len(word):].lstrip()
            out.append(json.dumps(word) if after.startswith(":") else word)
            i += len(word)
        else:
            out.append(c)
            i += 1
    try:
        return json.loads("".join(out))
    except ValueError as e:
        raise CatalogError(f"the object is not JSON-like ({e})") from None


def _dig(d: dict, key: str):
    """(container, last key) for a flat key or a dotted path, or (None, None)."""
    if key in d:
        return d, key
    cur = d
    parts = key.split(".")
    for p in parts[:-1]:
        cur = cur.get(p) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            return None, None
    return (cur, parts[-1]) if isinstance(cur, dict) and parts[-1] in cur else (None, None)


class I18nFile(Catalog):
    kind = "i18n"

    def __init__(self, path: pathlib.Path, root: pathlib.Path):
        super().__init__(path, root)
        try:
            self.text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise CatalogError(f"{self.label}: cannot read the file ({e})") from None
        if path.suffix == ".json":
            self.start, self.end = 0, len(self.text)
            try:
                self.data = json.loads(self.text)
            except ValueError as e:
                raise CatalogError(f"{self.label}: not JSON ({e})") from None
        else:
            try:
                self.start, self.end = _object_span(self.text)
                self.data = json_like(self.text[self.start:self.end])
            except CatalogError as e:
                raise CatalogError(f"{self.label}: {e}; edit this file by hand") from None
        if not isinstance(self.data, dict) or not any(isinstance(self.data.get(l), dict) for l in LANGS):
            raise CatalogError(f"{self.label}: expected one object per language (en, es, ru) at the top level")
        self.dirty = False

    def has(self, key: str) -> bool:
        return any(_dig(self.data[l], key)[0] is not None for l in LANGS if isinstance(self.data.get(l), dict))

    def get(self, key: str, lang: str) -> str | None:
        d = self.data.get(lang)
        c, k = _dig(d, key) if isinstance(d, dict) else (None, None)
        v = c[k] if c is not None else None
        return v if isinstance(v, str) else None

    def set(self, key: str, lang: str, text: str) -> str:
        d = self.data.get(lang)
        if not isinstance(d, dict):
            d = self.data[lang] = {}
        c, k = _dig(d, key)
        if c is None:
            if any(_dig(self.data[l], key)[0] is not None for l in LANGS if isinstance(self.data.get(l), dict)):
                if "." in key and not any(key in self.data[l] for l in LANGS if isinstance(self.data.get(l), dict)):
                    return "skipped: the key is nested and this language lacks the path; add it by hand"
                d[key] = text
                self.dirty = True
                return "changed"
            return "skipped: the key is not in the file"
        if not isinstance(c[k], str):
            return "skipped: the value is not a plain string"
        if c[k] == text:
            return "same"
        c[k] = text
        self.dirty = True
        return "changed"

    def save(self) -> list[pathlib.Path]:
        if not self.dirty:
            return []
        body = json.dumps(self.data, indent=2, ensure_ascii=False)
        _write_atomic(self.path, self.text[:self.start] + body + self.text[self.end:]
                      if self.path.suffix != ".json" else body + ("\n" if self.text.endswith("\n") else ""))
        self.dirty = False
        return [self.path]


class LangFiles(Catalog):
    """`locales/{lang}.json`: one file per language."""
    kind = "i18n"

    def __init__(self, pattern: str, root: pathlib.Path):
        super().__init__(root / pattern, root)
        self.label = pattern
        self.pattern, self.root = pattern, root
        self.data: dict[str, dict] = {}
        self.texts: dict[str, str] = {}
        for lang in LANGS:
            p = root / pattern.replace("{lang}", lang)
            if p.is_file():
                try:
                    self.texts[lang] = p.read_text(encoding="utf-8")
                    self.data[lang] = json.loads(self.texts[lang])
                except (OSError, ValueError) as e:
                    raise CatalogError(f"{_rel(p, root)}: cannot read as JSON ({e})") from None
                if not isinstance(self.data[lang], dict):
                    raise CatalogError(f"{_rel(p, root)}: expected a JSON object")
        if not self.data:
            raise CatalogError(f"{pattern}: no language file exists")
        self.dirty: set[str] = set()

    def has(self, key: str) -> bool:
        return any(_dig(d, key)[0] is not None for d in self.data.values())

    def get(self, key: str, lang: str) -> str | None:
        d = self.data.get(lang)
        c, k = _dig(d, key) if d is not None else (None, None)
        v = c[k] if c is not None else None
        return v if isinstance(v, str) else None

    def set(self, key: str, lang: str, text: str) -> str:
        if lang not in self.data:
            return f"skipped: no {self.pattern.replace('{lang}', lang)} file"
        c, k = _dig(self.data[lang], key)
        if c is None:
            if "." in key:
                return "skipped: the key is nested and this language lacks the path; add it by hand"
            self.data[lang][key] = text
        elif not isinstance(c[k], str):
            return "skipped: the value is not a plain string"
        elif c[k] == text:
            return "same"
        else:
            c[k] = text
        self.dirty.add(lang)
        return "changed"

    def save(self) -> list[pathlib.Path]:
        out = []
        for lang in sorted(self.dirty):
            p = self.root / self.pattern.replace("{lang}", lang)
            _write_atomic(p, json.dumps(self.data[lang], indent=2, ensure_ascii=False) + "\n")
            out.append(p)
        self.dirty.clear()
        return out


# --- finding the catalogs --------------------------------------------------------------------------

def _as_list(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v] if isinstance(v, list) else []


def find_catalogs(repo: pathlib.Path, screen: dict, keys: list[str]) -> tuple[list[Catalog], list[str]]:
    """(catalogs, notes). The ones the screen file names, else every catalog in the repo that holds at least
    one of `keys`. A named catalog that cannot be read is a note, never a silent skip."""
    named = _as_list(screen.get("catalog")) + _as_list(screen.get("catalogs")) + _as_list(screen.get("i18n"))
    notes: list[str] = []
    found: list[Catalog] = []

    def load(rel: str) -> Catalog:
        p = repo / rel
        if "{lang}" in rel:
            return LangFiles(rel, repo)
        if p.is_dir() and (p.name == "res" or (p / "values").is_dir()):
            return AndroidStrings(p, repo)
        if p.is_file() and p.name == "strings.xml":
            return AndroidStrings(p.parent.parent, repo)
        if p.suffix == ".xcstrings":
            return XcStrings(p, repo)
        if p.suffix in (".ts", ".js", ".mjs", ".json"):
            return I18nFile(p, repo)
        raise CatalogError(f"{rel}: not a string catalog I can read (xcstrings, strings.xml, i18n.ts/json)")

    for rel in named:
        try:
            if not ("{lang}" in rel or (repo / rel).exists()):
                raise CatalogError(f"{rel}: not found")
            found.append(load(rel))
        except (CatalogError, OSError) as e:
            notes.append(str(e))
    if named:
        return found, notes
    for p in walk(repo, ".xcstrings"):
        try:
            c = XcStrings(p, repo)
        except CatalogError as e:
            notes.append(str(e))
            continue
        if any(c.has(k) for k in keys):
            found.append(c)
    seen: set[pathlib.Path] = set()
    for p in walk(repo, "strings.xml"):
        if p.parent.name == "values" or p.parent.name.startswith("values-"):
            res = p.parent.parent
            if res in seen:
                continue
            seen.add(res)
            try:
                c = AndroidStrings(res, repo)
            except CatalogError:
                continue
            if any(c.has(k) for k in keys):
                found.append(c)
    return found, notes


def lookup(catalogs: list[Catalog], key: str) -> Catalog | None:
    return next((c for c in catalogs if c.has(key)), None)
