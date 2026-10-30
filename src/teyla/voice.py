"""`teyla voice check` — a draft against a voice chart (register (c) of the writing policy).

    teyla voice check <file|-> --chart <dir|file> [--lang en|es|ru] [--format F] [--model] [--json]

The chart is a Markdown file with a YAML front matter, one per language. A chart directory holds
`en.md`, `es.md` and `ru.md`; the draft's language (or `--lang`) picks the file. The front matter:

    lang: en | es | ru
    max_sentence_words: 18
    max_post_chars: {x_post: 280, x_thread_tweet: 270, substack_intro: 900, video_hook_15s: 220, linkedin_update: 900}
    emoji_max: 1            hashtags_max: 0            exclamations_max: 0
    banned: [phrases and words, one per list item; a trailing * matches any ending]
    preferred: [words the chart wants used; shown, not enforced]

Deterministic checks, all hard (exit 1): the longest sentence, the length for `--format`, banned
phrases (case-insensitive, whole words, any script), emoji, hashtags, exclamation marks. A draft in
another language than the chart only warns: script and stop words are a guess, not a verdict.
`--model` adds one Claude Haiku pass that rates the draft against the chart's traits and returns at
most three edits. It sends the draft and the chart to the API, so safe mode refuses it. No other
check leaves the machine. The charts themselves are the owner's and live outside the repo
(`~/.teyla/voice/<channel>/`); `templates/voice/VOICE.md` is the schema.

Exit 0 clean, 1 a hard rule failed, 2 a usage or chart error.

A chart is complete when it carries ten accepted and five rejected example lines (under `## Accepted lines`
and `## Rejected lines`, one bullet each; a line that still holds a `{{placeholder}}` does not count). `check`
adds a warning when the chart it used is short of them: a chart without examples is a style guide nobody can
calibrate against.

    teyla voice chart <repo> [--lang en|es|ru] [--out DIR] [--force] [--json]

scaffolds the product's chart, one file per language, from the `## Voice` and `## Glossary` sections of its
`DESIGN.md` and from `brand/kit.toml` when it exists; the example lines come from `design/decisions/*.json`
files that carry `copy: {lang, accepted, rejected}`. It writes `brand/voice/{en,es,ru}.md` (or the kit's
chart directory), never overwrites a chart that exists (`--force`), and prints each language's example count.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import config, state
from .prose import _prose_lines

LANGS = ("en", "es", "ru")
FORMATS = ("x_post", "x_thread_tweet", "substack_intro", "video_hook_15s", "linkedin_update")
URL_CHARS = 23            # X counts every link as 23 characters, whatever its length
MAX_EDITS = 3

_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"\w+(?:['’-]\w+)*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"'”’»)]*\s+|\n+")
_HASHTAG = re.compile(r"(?<![\w&/#])#[^\W\d_]\w*")
_ZWJ, _VS16, _KEYCAP = "‍", "️", "⃣"


class ChartError(ValueError):
    """The chart is missing, unreadable or breaks the schema; the message says what to fix."""


# --- the chart --------------------------------------------------------------------------------

def _scalar(raw: str):
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1].replace("''", "'") if s[0] == "'" else s[1:-1]      # YAML: '' inside '...' is one quote
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def _opens_quote(cur: str) -> bool:
    """A quote mark opens a quoted item only at the start of the item (`"b, c"`, or `key: "b, c"` in a map);
    inside a plain item it is an apostrophe (`don't`)."""
    head = cur.strip()
    return not head or (head.endswith(":") and ":" in head)


def _inline_list(raw: str) -> list:
    """`[a, "b, c", d]` -> ['a', 'b, c', 'd']. An apostrophe inside a plain item is text: `[don't, can't]`."""
    inner, items, cur, quote = raw.strip()[1:-1], [], "", ""
    skip = False
    for i, ch in enumerate(inner):
        if skip:                                       # the second half of a '' inside a single-quoted item
            skip = False
            cur += ch
        elif quote:
            if ch == quote and quote == "'" and inner[i + 1:i + 2] == "'":
                skip = True
            else:
                quote = "" if ch == quote else quote
            cur += ch
        elif ch in "\"'" and _opens_quote(cur):
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip() or items:
        items.append(cur)
    return [_scalar(i) for i in items if i.strip()]


def _value(raw: str):
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        return _inline_list(s)
    if s.startswith("{") and s.endswith("}"):
        out = {}
        for item in _inline_list("[" + s[1:-1] + "]"):
            k, _, v = str(item).partition(":")
            out[k.strip()] = _scalar(v)
        return out
    return _scalar(s)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """(front matter, body). The subset of YAML the schema uses: `key: value`, inline lists and maps,
    a block list (`- item`) or a block map (indented `key: value`) under a bare `key:`, full-line
    `#` comments. Anything else is a ChartError, never a silent default."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ChartError("the chart has no front matter (the file must start with a --- line)")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ChartError("the front matter is not closed (no second --- line)") from None
    data: dict = {}
    key = None
    for n, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[0] in " \t"
        s = line.strip()
        if not indented:
            k, sep, rest = s.partition(":")
            if not sep or not k.strip():
                raise ChartError(f"front matter line {n}: expected `key: value`")
            key = k.strip()
            data[key] = _value(rest) if rest.strip() else None
        elif key is None:
            raise ChartError(f"front matter line {n}: an indented line with no key above it")
        elif s.startswith("- ") or s == "-":
            if data[key] is None:
                data[key] = []
            if not isinstance(data[key], list):
                raise ChartError(f"front matter line {n}: `{key}` mixes a list with other values")
            data[key].append(_scalar(s[1:]))
        else:
            k, sep, rest = s.partition(":")
            if not sep:
                raise ChartError(f"front matter line {n}: expected `key: value`")
            if data[key] is None:
                data[key] = {}
            if not isinstance(data[key], dict):
                raise ChartError(f"front matter line {n}: `{key}` mixes a map with other values")
            data[key][k.strip()] = _scalar(rest)
    return data, "\n".join(lines[end + 1:]).lstrip("\n")


@dataclass
class Chart:
    path: Path
    lang: str
    max_sentence_words: int | None = None
    max_post_chars: dict = field(default_factory=dict)
    emoji_max: int | None = None
    hashtags_max: int | None = None
    exclamations_max: int | None = None
    banned: list = field(default_factory=list)
    preferred: list = field(default_factory=list)
    body: str = ""


def _count(meta: dict, key: str, minimum: int) -> int | None:
    v = meta.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ChartError(f"`{key}` must be a whole number of at least {minimum}")
    return v


def _words_list(meta: dict, key: str) -> list:
    v = meta.get(key) or []
    if not isinstance(v, list) or not all(isinstance(i, (str, int)) and str(i).strip() for i in v):
        raise ChartError(f"`{key}` must be a list of phrases")
    return [str(i).strip() for i in v]


def load_chart(path: Path) -> Chart:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ChartError(f"cannot read the chart {path}: {e}") from None
    meta, body = parse_front_matter(text)
    lang = meta.get("lang")
    if lang not in LANGS:
        raise ChartError(f"`lang` must be one of {', '.join(LANGS)}, not {lang!r}")
    limits = meta.get("max_post_chars") or {}
    if not isinstance(limits, dict):
        raise ChartError("`max_post_chars` must map a format to a number of characters")
    for fmt, n in limits.items():
        if fmt not in FORMATS:
            raise ChartError(f"`max_post_chars` names an unknown format {fmt!r} (known: {', '.join(FORMATS)})")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ChartError(f"`max_post_chars.{fmt}` must be a positive number")
    return Chart(path=path, lang=lang, max_sentence_words=_count(meta, "max_sentence_words", 1),
                 max_post_chars=dict(limits), emoji_max=_count(meta, "emoji_max", 0),
                 hashtags_max=_count(meta, "hashtags_max", 0), exclamations_max=_count(meta, "exclamations_max", 0),
                 banned=_words_list(meta, "banned"), preferred=_words_list(meta, "preferred"), body=body)


def resolve_chart(chart: str, lang: str | None, draft: str) -> tuple[Chart, str | None]:
    """The chart file for this draft, and a warning when the draft looks like another language.
    A directory needs the language: `--lang`, else the draft's own."""
    p = Path(chart).expanduser()
    detected = detect_lang(draft)
    if p.is_dir():
        pick = lang or detected
        if pick is None:
            raise ChartError("cannot tell the draft's language; pass --lang en|es|ru")
        f = p / f"{pick}.md"
        if not f.is_file():
            raise ChartError(f"no {pick}.md in {p}")
        c = load_chart(f)
    elif p.is_file():
        c = load_chart(p)
        if lang and lang != c.lang:
            raise ChartError(f"{p} is a {c.lang} chart; --lang says {lang}")
    else:
        raise ChartError(f"no chart at {p}")
    warn = None
    if detected and detected != c.lang:
        warn = f"the draft reads as {detected}, the chart is {c.lang}"
    return c, warn


# --- language guess ---------------------------------------------------------------------------

_STOP = {
    "en": set("the and of to is in it that for on with as was i my you are this but not be at have from we your an or "
              "so if they what when how about just do does did there will would can".split()),
    "es": set("el la de que y en los un una por para con no se es del las lo al mi pero como más esto hay cuando "
              "muy ya sin sobre también le su sus nos esta son fue he ha tengo tienes porque qué cómo "
              "dónde cada todo todos".split()),
}


def detect_lang(text: str) -> str | None:
    """`ru` by script; `es` or `en` by stop words, accents and the opening marks. None when the draft
    is too short or too even to say."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return None
    cyr = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    if cyr * 2 >= len(letters):
        return "ru"
    words = [w.lower() for w in _WORD.findall(text)]
    es = sum(w in _STOP["es"] for w in words) + 2 * len(re.findall(r"[¿¡ñ]", text))
    en = sum(w in _STOP["en"] for w in words)
    if es == en:
        return None
    return "es" if es > en else "en"


# --- the counts -------------------------------------------------------------------------------

def _fold(s: str) -> str:
    """Lower case, one apostrophe, and Cyrillic yo as ye: the matching form of a text and of a banned phrase."""
    return s.lower().replace("’", "'").replace("‘", "'").replace("\u0451", "\u0435")


def _banned_re(phrase: str) -> re.Pattern:
    """Whole-word match; spaces match any run of white space; a trailing * matches the rest of the word."""
    stem = phrase.endswith("*")
    body = re.escape(_fold(phrase.rstrip("*").strip())).replace(r"\ ", r"\s+")
    return re.compile(r"(?<!\w)" + body + (r"\w*" if stem else r"(?!\w)"))


def banned_hits(text: str, phrases: list) -> list[dict]:
    low = _fold(text)
    hits = []
    for p in phrases:
        n = len(_banned_re(p).findall(low))
        if n:
            hits.append(dict(phrase=p, count=n))
    return hits


# Symbols that render as emoji by default. Other dingbats and arrows (a check mark, a star, the Mac command
# key) are text unless a variation selector (U+FE0F) follows them.
_EMOJI_DEFAULT = {0x231A, 0x231B, 0x23E9, 0x23EA, 0x23EB, 0x23EC, 0x23F0, 0x23F3, 0x25FD, 0x25FE, 0x2614, 0x2615,
                  *range(0x2648, 0x2654), 0x267F, 0x2693, 0x26A1, 0x26AA, 0x26AB, 0x26BD, 0x26BE, 0x26C4, 0x26C5,
                  0x26CE, 0x26D4, 0x26EA, 0x26F2, 0x26F3, 0x26F5, 0x26FA, 0x26FD, 0x2705, 0x270A, 0x270B, 0x2728,
                  0x274C, 0x274E, 0x2753, 0x2754, 0x2755, 0x2757, 0x2795, 0x2796, 0x2797, 0x27B0, 0x27BF, 0x2B1B,
                  0x2B1C, 0x2B50, 0x2B55}


def _emoji_at(text: str, i: int) -> bool:
    o = ord(text[i])
    if 0x1F300 <= o <= 0x1FAFF or 0x1F000 <= o <= 0x1F2FF:
        return True
    return o in _EMOJI_DEFAULT or (0x2190 <= o <= 0x2BFF or o in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139)) \
        and text[i + 1:i + 2] == _VS16


def count_emoji(text: str) -> int:
    """Emoji as a reader sees them: a flag, a skin-tone or ZWJ sequence and a keycap are one each."""
    n, i = 0, 0
    while i < len(text):
        c = text[i]
        if "\U0001F1E6" <= c <= "\U0001F1FF":                      # a flag is two regional indicators
            n += 1
            i += 2 if i + 1 < len(text) and "\U0001F1E6" <= text[i + 1] <= "\U0001F1FF" else 1
            continue
        if c in "0123456789#*" and text[i + 1:i + 3] in (_KEYCAP, _VS16 + _KEYCAP):
            n += 1
            i += 3 if text[i + 1] == _VS16 else 2
            continue
        if _emoji_at(text, i):
            n += 1
            i += 1
            while i < len(text):
                if text[i] in (_VS16, "\U0001F3FB", "\U0001F3FC", "\U0001F3FD", "\U0001F3FE", "\U0001F3FF"):
                    i += 1
                elif text[i] == _ZWJ and i + 1 < len(text) and _emoji_at(text, i + 1):
                    i += 2
                else:
                    break
            continue
        i += 1
    return n


def count_hashtags(text: str) -> int:
    return len(_HASHTAG.findall(_URL.sub(" ", text)))


def count_exclamations(text: str) -> int:
    return text.count("!")


def post_length(text: str, fmt: str) -> int:
    """Characters as the channel counts them: an X link is 23 whatever its length."""
    t = text.strip()
    if fmt.startswith("x_"):
        t = _URL.sub("x" * URL_CHARS, t)
    return len(unicodedata.normalize("NFC", t))


def sentences(text: str) -> list[tuple[int, str]]:
    """(word count, sentence) for each sentence; bullets and wrapped lines are read as prose."""
    body = "\n".join(_prose_lines(text))
    return [(len(_WORD.findall(s)), s.strip()) for s in _SENTENCE_SPLIT.split(body) if _WORD.search(s)]


# --- the check --------------------------------------------------------------------------------

def check(text: str, chart: Chart, fmt: str | None = None, lang_warning: str | None = None) -> dict:
    """The report: stats, findings (each `level` is `fail` or `warn`), and `ok` = no fail."""
    findings: list[dict] = []

    def add(level, rule, message, **extra):
        findings.append(dict(level=level, rule=rule, message=message, **extra))

    sents = sentences(text)
    longest = max(sents, key=lambda s: s[0], default=(0, ""))
    if chart.max_sentence_words:
        for n, s in sents:
            if n > chart.max_sentence_words:
                add("fail", "sentence", f"{n} words, limit {chart.max_sentence_words}: \"{_clip(s)}\"", words=n)
    length = post_length(text, fmt) if fmt else None
    limit = chart.max_post_chars.get(fmt) if fmt else None
    if fmt and limit is None:
        add("warn", "length", f"the chart sets no limit for {fmt}")
    elif fmt and length > limit:
        add("fail", "length", f"{length} characters for {fmt}, limit {limit}", chars=length)
    for h in banned_hits(text, chart.banned):
        add("fail", "banned", f"\"{h['phrase']}\" x{h['count']}" if h["count"] > 1 else f"\"{h['phrase']}\"",
            phrase=h["phrase"])
    for rule, got, cap, what in (("emoji", count_emoji(text), chart.emoji_max, "emoji"),
                                 ("hashtags", count_hashtags(text), chart.hashtags_max, "hashtags"),
                                 ("exclamations", count_exclamations(text), chart.exclamations_max, "exclamation marks")):
        if cap is not None and got > cap:
            add("fail", rule, f"{what}: {got}, limit {cap}", count=got)
    if lang_warning:
        add("warn", "language", lang_warning)
    return dict(chart=str(chart.path), lang=chart.lang, format=fmt, ok=not any(f["level"] == "fail" for f in findings),
                stats=dict(words=len(_WORD.findall(text)), chars=length if length is not None else len(text.strip()),
                           sentences=len(sents), longest_sentence=longest[0], emoji=count_emoji(text),
                           hashtags=count_hashtags(text), exclamations=count_exclamations(text)),
                preferred_used=[p for p in chart.preferred if re.search(r"(?<!\w)" + re.escape(_fold(p)) + r"\w*", _fold(text))],
                findings=findings)


def _clip(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


# --- the model pass ---------------------------------------------------------------------------

VOICE_SYSTEM = (
    "You are an editor who checks one draft against a voice chart. The chart and the draft arrive as JSON. "
    "Reply with strict JSON only, no prose and no code fence:\n"
    '{"rating": <1 to 5, 5 = the draft already sounds like the chart>, "summary": "<one sentence>", '
    '"edits": [{"quote": "<exact words from the draft>", "fix": "<the replacement, in the draft\'s language>", '
    '"why": "<at most 12 words, the trait or rule it serves>"}]}\n'
    f"Give at most {MAX_EDITS} edits, the ones that move the draft closest to the chart's traits, and none when the "
    "draft already fits. Every quote is copied from the draft. Write the fix in the language of the draft. "
    "Judge tone and claims, not the counts: a separate check has already measured length, banned words and "
    "punctuation. Never invent facts the draft does not state."
)


def voice_command() -> list[str]:
    """The same `claude -p` call as the morning brief (no tools, no skills, no MCP, no settings, no saved
    session, Haiku), with this module's system prompt in place of the brief's."""
    cmd = state.brief_command()
    i = cmd.index("--system-prompt")
    return cmd[:i + 1] + [VOICE_SYSTEM]


def _run(cmd: list[str], input_text: str) -> tuple[int, str]:
    """Tests replace this one function; none starts a real claude."""
    return state._run_claude(cmd, input_text)


def model_review(text: str, chart: Chart, fmt: str | None) -> dict:
    """{rating, summary, edits[<=3]} from one Haiku pass, or {error: ...}. Never raises."""
    payload = json.dumps(dict(chart=chart.body[:8000], language=chart.lang, format=fmt, draft=text), ensure_ascii=False)
    try:
        code, out = _run(voice_command(), payload)
        if code != 0:
            return dict(error=f"claude exited {code}")
        reply, usage = state._parse_reply(out)
    except (ValueError, OSError) as e:
        return dict(error=f"the model reply was unusable ({e})")
    if not isinstance(reply, dict):
        return dict(error="the model reply was not an object")
    edits = []
    raw_edits = reply.get("edits")
    for e in raw_edits if isinstance(raw_edits, list) else []:
        if isinstance(e, dict) and isinstance(e.get("quote"), str) and isinstance(e.get("fix"), str):
            edits.append(dict(quote=e["quote"], fix=e["fix"], why=str(e.get("why") or "")))
    rating = reply.get("rating")
    return dict(rating=rating if isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 5 else None,
                summary=str(reply.get("summary") or ""), edits=edits[:MAX_EDITS], model=state.BRIEF_MODEL, **usage)


def model_available() -> str | None:
    """None when `--model` may run, else why not."""
    if config.safe_mode():
        return "safe mode is on: the draft would leave this machine"
    if shutil.which("claude") is None:
        return "no `claude` on PATH"
    return None


# --- completeness: the example lines --------------------------------------------------------------

ACCEPTED_MIN = 10
REJECTED_MIN = 5
_HEADING = re.compile(r"^#{2,4}\s*(.*?)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")


def example_lines(body: str) -> tuple[list[str], list[str]]:
    """(accepted, rejected) example lines of a chart body: the bullets under a heading that starts with
    "Accepted" or "Rejected". A line with a `{{placeholder}}` is a blank to fill and is not counted."""
    acc: list[str] = []
    rej: list[str] = []
    cur = None
    for line in body.splitlines():
        h = _HEADING.match(line)
        if h:
            title = h.group(1).lower()
            cur = acc if title.startswith("accepted") else rej if title.startswith("rejected") else None
            continue
        b = _BULLET.match(line)
        if b and cur is not None and "{{" not in b.group(1):
            cur.append(b.group(1).strip().strip("\"“”"))
    return acc, rej


def chart_status(chart: Chart) -> dict:
    acc, rej = example_lines(chart.body)
    return dict(lang=chart.lang, accepted=len(acc), rejected=len(rej), accepted_needed=ACCEPTED_MIN,
                rejected_needed=REJECTED_MIN, complete=len(acc) >= ACCEPTED_MIN and len(rej) >= REJECTED_MIN)


def completeness_finding(chart: Chart) -> dict | None:
    st = chart_status(chart)
    if st["complete"]:
        return None
    return dict(level="warn", rule="chart",
                message=f"the {chart.lang} chart is incomplete: {st['accepted']} of {ACCEPTED_MIN} accepted and "
                        f"{st['rejected']} of {REJECTED_MIN} rejected example lines (teyla voice chart <repo>)",
                accepted=st["accepted"], rejected=st["rejected"])


# --- the scaffold: teyla voice chart ----------------------------------------------------------------

LANG_NAMES = {"en": "English", "es": "Spanish", "ru": "Russian"}


def _decision_examples(repo: Path) -> dict[str, tuple[list[str], list[str]]]:
    """{lang: (accepted, rejected)} from `design/decisions/*.json` files with `copy: {lang, accepted, rejected}`."""
    from . import taste
    out: dict[str, tuple[list[str], list[str]]] = {l: ([], []) for l in LANGS}
    for d in reversed(taste.load_decisions(repo)):                 # oldest first
        c = d.get("copy")
        if not isinstance(c, dict):
            continue
        lang = c.get("lang") if c.get("lang") in LANGS else "en"
        for field, bucket in (("accepted", out[lang][0]), ("rejected", out[lang][1])):
            v = c.get(field)
            if isinstance(v, str) and v.strip() and v.strip() not in bucket:
                bucket.append(v.strip())
    return out


def _bullets(lines: list[str], need: int, what: str) -> list[str]:
    out = [f"- {l}" for l in lines[:need]]
    out += [f"- {{{{{what} line {i}}}}}" for i in range(len(out) + 1, need + 1)]
    return out


def scaffold_chart(repo: Path, lang: str, product: str, design: str, kit: dict,
                   examples: tuple[list[str], list[str]]) -> str:
    from . import copy_lexicon as lex, design_md
    banned = list(dict.fromkeys(lex.BANNED_DEFAULT[lang] + kit.get("banned", [])))
    preferred = kit.get("preferred", [])
    front = ["---", f"lang: {lang}", "max_sentence_words: 20", "emoji_max: 0", "hashtags_max: 0", "exclamations_max: 0",
             "banned:"] + [f"  - {json.dumps(b, ensure_ascii=False)}" for b in banned]
    front += ["preferred:"] + [f"  - {json.dumps(p, ensure_ascii=False)}" for p in preferred] if preferred else ["preferred: []"]
    front.append("---")
    voice = design_md.voice_text(design)
    gloss = design_md.glossary(design)
    traits = kit.get("traits") or []
    body = [f"# Voice chart: {product} ({LANG_NAMES[lang]})", "",
            "Written in this language, from the same brief as the other charts. Never translate one chart into another.",
            "UI strings follow `DESIGN.md`; this chart sets the voice they share with posts and store text.", "",
            "## Brief"]
    body += ([f"> {l}" if l.strip() else ">" for l in voice.splitlines()] if voice
             else ["- What the product is, in one sentence: {{one sentence}}",
                   "- Who it is for: {{reader}}", "- Address: {{you or we; formal or informal}}"])
    body += ["", "## Traits", "Each is \"We are X, not Y\", with one do and one don't from real copy.", ""]
    if traits:
        body += [f"- {t}" for t in traits]
    else:
        body += ["| We are | Not | Do | Don't |", "|---|---|---|---|"] + \
                [f"| {{{{trait {i}}}}} | {{{{opposite {i}}}}} | \"{{{{example}}}}\" | \"{{{{example}}}}\" |" for i in (1, 2, 3)]
    body += ["", "## Glossary", f"One word per concept in {LANG_NAMES[lang]}, never rotated.", ""]
    if gloss:
        body += ["| Concept | Term |", "|---|---|"] + [f"| {g['concept']} | {g.get(lang) or '{{term}}'} |" for g in gloss]
    else:
        body += ["| Concept | Term |", "|---|---|", "| {{concept}} | {{term}} |"]
    body += ["", f"## {LANG_NAMES[lang]}"] + [f"- {n}" for n in lex.LANGUAGE_NOTES[lang]]
    body += ["", "## Accepted lines", f"Ten lines the owner kept, in {LANG_NAMES[lang]}. They calibrate every judge and every writer.", ""]
    body += _bullets(examples[0], ACCEPTED_MIN, "accepted")
    body += ["", "## Rejected lines", f"Five lines the owner turned down, in {LANG_NAMES[lang]}, each with what was wrong.", ""]
    body += _bullets(examples[1], REJECTED_MIN, "rejected")
    return "\n".join(front + body) + "\n"


def scaffold(repo: Path, langs: list[str], out: Path | None = None, force: bool = False) -> dict:
    """Write the missing charts. {dir, charts: [{lang, file, written, accepted, rejected, complete}], sources}."""
    from . import design_md
    design = design_md.read(repo)
    kit = design_md.load_kit(repo)
    product = kit.get("product") or repo.name
    d = out or design_md.default_chart_dir(repo)
    examples = _decision_examples(repo)
    rows = []
    for lang in langs:
        f = d / f"{lang}.md"
        written = force or not f.exists()
        if written:
            d.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f".{f.name}.tmp")
            tmp.write_text(scaffold_chart(repo, lang, product, design, kit, examples[lang]), encoding="utf-8")
            tmp.replace(f)
        try:
            st = chart_status(load_chart(f))
        except ChartError as e:
            st = dict(accepted=0, rejected=0, complete=False, error=str(e))
        rows.append(dict(lang=lang, file=str(f), written=written, accepted=st["accepted"], rejected=st["rejected"],
                         complete=st["complete"], **({"error": st["error"]} if "error" in st else {})))
    return dict(dir=str(d), charts=rows,
                sources=dict(design_md=bool(design), voice_section=bool(design_md.voice_text(design)),
                             glossary_rows=len(design_md.glossary(design)), kit=bool(kit),
                             decision_examples=sum(len(a) + len(r) for a, r in examples.values())))


def render_scaffold(rep: dict) -> str:
    L = [f"teyla voice chart: {rep['dir']}"]
    s = rep["sources"]
    L.append(f"from: DESIGN.md {'found' if s['design_md'] else 'missing'}"
             f"{' (voice section)' if s['voice_section'] else ''}, {s['glossary_rows']} glossary rows, "
             f"brand/kit.toml {'read' if s['kit'] else 'absent'}, {s['decision_examples']} example lines from design/decisions")
    for c in rep["charts"]:
        state = "written" if c["written"] else "kept (exists; --force overwrites)"
        L.append(f"  {c['lang']}  {state}: {c['accepted']}/{ACCEPTED_MIN} accepted, {c['rejected']}/{REJECTED_MIN} rejected"
                 + ("" if c["complete"] else "  INCOMPLETE") + (f"  ({c['error']})" if c.get("error") else ""))
    if not all(c["complete"] for c in rep["charts"]):
        L.append("fill the {{placeholders}}; add accepted and rejected lines until each chart is complete")
    return "\n".join(L)


# --- the command ------------------------------------------------------------------------------

def render(rep: dict) -> str:
    s = rep["stats"]
    head = f"teyla voice check — {rep['lang']} chart" + (f", {rep['format']}" if rep["format"] else "")
    L = [head, f"{s['words']} words, {s['chars']} characters, {s['sentences']} sentences "
               f"(longest {s['longest_sentence']} words), {s['emoji']} emoji, {s['hashtags']} hashtags, "
               f"{s['exclamations']} exclamation marks"]
    if not rep["format"]:
        L.append("no --format: the length is not checked")
    for f in rep["findings"]:
        L.append(f"  {'FAIL' if f['level'] == 'fail' else 'warn'}  {f['rule']}: {f['message']}")
    if rep["preferred_used"]:
        L.append("  uses the chart's preferred words: " + ", ".join(rep["preferred_used"]))
    m = rep.get("model")
    if m:
        L.append("")
        if "error" in m:
            L.append(f"model pass: {m['error']}")
        else:
            L.append(f"model pass ({m['model']}): " + (f"{m['rating']}/5. " if m["rating"] else "") + m["summary"])
            for e in m["edits"]:
                L.append(f"  - \"{e['quote']}\" -> \"{e['fix']}\"" + (f"  ({e['why']})" if e["why"] else ""))
            if not m["edits"]:
                L.append("  no edits")
    L.append("")
    L.append("PASS" if rep["ok"] else "FAIL: " + ", ".join(sorted({f["rule"] for f in rep["findings"] if f["level"] == "fail"})))
    return "\n".join(L)


def cmd_voice(args) -> int:
    if args.action == "chart":
        return cmd_chart(args)
    try:
        if not args.chart:
            raise ChartError("check needs --chart <dir|file>")
        if args.file == "-":
            text = sys.stdin.read()
        else:
            try:
                text = Path(args.file).expanduser().read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                raise ChartError(f"cannot read the draft {args.file}: {e}") from None
        if not text.strip():
            raise ChartError("the draft is empty")
        chart, warn = resolve_chart(args.chart, args.lang, text)
        why_not = model_available() if args.model else None
        if why_not:
            raise ChartError(f"--model: {why_not}")
    except ChartError as e:
        print(f"teyla voice: {e}", file=sys.stderr)
        return 2
    rep = check(text, chart, args.format, warn)
    gap = completeness_finding(chart)
    rep["chart_status"] = chart_status(chart)
    if gap:
        rep["findings"].append(gap)
    if args.model:
        rep["model"] = model_review(text, chart, args.format)
    if args.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        print(render(rep))
    return 0 if rep["ok"] else 1


def cmd_chart(args) -> int:
    from . import taste
    try:
        repo = taste.resolve_repo(args.file)
    except FileNotFoundError as e:
        print(f"teyla voice chart: {e}", file=sys.stderr)
        return 2
    langs = [args.lang] if args.lang else list(LANGS)
    out = Path(args.out).expanduser() if args.out else None
    try:
        rep = scaffold(repo, langs, out, args.force)
    except OSError as e:
        print(f"teyla voice chart: cannot write the charts: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=1, ensure_ascii=False) if args.json else render_scaffold(rep))
    return 0


def register(sp):
    q = sp.add_parser("voice", help="check a draft against a voice chart (sentence and post length, banned phrases, emoji, hashtags, exclamation marks), or scaffold a product's chart",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_voice)
    q.add_argument("action", choices=["check", "chart"])
    q.add_argument("file", help="check: the draft, - reads stdin. chart: the product repo (a name under code_root or a path)")
    q.add_argument("--chart", metavar="DIR|FILE", help="check: a chart directory (en.md, es.md, ru.md) or one chart file (required)")
    q.add_argument("--lang", choices=LANGS, help="check: the chart language (default: the draft's own, guessed). chart: only this language")
    q.add_argument("--out", metavar="DIR", help="chart: write the charts here (default: brand/voice, or the kit's chart directory)")
    q.add_argument("--force", action="store_true", help="chart: overwrite charts that exist")
    q.add_argument("--format", choices=FORMATS, help="check the length for this format")
    q.add_argument("--model", action="store_true", help="add one Claude Haiku pass: a rating against the chart's traits and at most 3 edits (sends the draft to the API)")
    q.add_argument("--json", action="store_true")
    return q
