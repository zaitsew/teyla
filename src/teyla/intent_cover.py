"""`teyla intent cover <plan.md>` — does a plan serve what the owner wrote?

    teyla intent cover <plan.md> [--product P] [--since YYYY-MM-DD] [--last N] [--model] [--json]

The source is the owner's own entries for the product (`teyla intent`), cut into sentences and list
items in Russian and English. Sentences under six words and chatter ("proceed", "ok, do it", a
question about the agent's own state) are dropped; requirements, goals, constraints, complaints and
examples stay. A sentence is served when the plan

    quotes it         the plan holds all of it, or a run of at least 60% of its words, normalised
                      (case, punctuation, whitespace)
    covers its words  one plan sentence, or two next to each other, shares at least 55% of its content
                      words, and at least three of them (a simple suffix strip stands in for stemming)
    puts it aside     the match sits under an "Out of scope" or "Deferred" heading, or in a line that
                      opens with such a phrase and a colon

A Russian sentence cannot match an English plan by words. Without `--model` those are listed apart as
"needs --model", not as unserved. `--model` sends the unresolved sentences and the plan to one Claude
Haiku call (batched, JSON in and out, the same `claude -p` the state brief uses) and takes its answer
as the verdict. It is off by default and in safe mode, because the owner's prompts leave the machine.

Exit 0: every sentence is served or still waits for `--model`. Exit 1: something is unserved. Exit 2:
no plan, or no intent recorded for the product. Exit 64: bad arguments.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import pathlib
import re
import shutil
import sys

from . import intent, lexicon

MIN_WORDS = 6          # a source sentence shorter than this is not a requirement
OVERLAP = 0.55         # share of a source sentence's content words one plan unit must hold
MIN_HITS = 3           # ...and at least this many (fewer if the sentence has fewer)
RUN_SHARE = 0.6        # a quote: this share of the sentence's words in a row in the plan...
RUN_MIN = 6            # ...and at least this many words
RU_PLAN_SHARE = 0.2    # a plan with less Cyrillic than this is an English plan
BATCH = 80             # sentences per model call
PLAN_CHARS = 60_000    # the plan text a model call carries
SENTENCE_CHARS = 600   # a source sentence clipped to this in a model call
SHOW_CHARS = 170

_WORD_RE = re.compile(r"[^\W_]+")
_CYR_RE = re.compile("[\u0400-\u04ff]")
_LETTER_RE = re.compile(r"[^\W\d_]")
_LIST_MARK_RE = re.compile(r"^\s*(?:[-*+•–—]|\d{1,2}[.)]|\(\d{1,2}\)|[A-Za-z][.)])\s+")
_BOUNDARY_RE = re.compile("([.!?…]+[\"')\\]»”]*)\\s+(?=[\"'(\\[«“]*[A-Z\u0410-\u042f\u0401\\d])")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_OOS_RE = re.compile("|".join(lexicon.COVER_OUT_OF_SCOPE), re.I)
_OOS_LINE_RE = re.compile(r"^\W*(?:" + "|".join(lexicon.COVER_OUT_OF_SCOPE) + r")\b[^:：\n]{0,40}[:：]", re.I)
_STATE_RE = re.compile("|".join(lexicon.COVER_AGENT_STATE), re.I)
_TAG_RE = re.compile(r"</?[A-Za-z_][\w:-]*(?:\s[^<>]*)?>")     # <pasted_content id="..."> and the like
_URL_RE = re.compile(r"https?://\S+|(?:~|\.{0,2})/[\w./-]+")


# --- words ---------------------------------------------------------------------------------

def words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower().replace("\u0451", "\u0435"))


def norm(text: str) -> str:
    return " ".join(words(text))


def cyr_share(text: str) -> float:
    letters = _LETTER_RE.findall(text or "")
    return len(_CYR_RE.findall(text or "")) / len(letters) if letters else 0.0


def stem(w: str) -> str:
    """A crude stem: enough to match "plans" with "planned" and a Russian word with its other forms."""
    if _CYR_RE.search(w):
        for suf in lexicon.COVER_RU_SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                return w[:-len(suf)]
        return w
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("ly", ""), ("s", "")):
        if w.endswith(suf) and not w.endswith("ss") and len(w) - len(suf) >= 3:
            w = w[:-len(suf)] + rep
            break
    if len(w) > 3 and w.endswith("e"):          # make, makes, making -> mak
        w = w[:-1]
    return w[:-1] if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou" else w


def stems(text: str) -> frozenset[str]:
    out = set()
    for w in words(text):
        if w in lexicon.COVER_STOP_EN or w in lexicon.COVER_STOP_RU:
            continue
        if len(w) < 3 and not (len(w) == 2 and w.isdigit()):
            continue
        out.add(stem(w))
    return frozenset(out)


# --- sentences -----------------------------------------------------------------------------

def _plain(line: str) -> str:
    """A markdown line as prose: links as their text, no emphasis marks or code ticks."""
    line = _LINK_RE.sub(r"\1", line)
    return re.sub(r"[*_`]{1,3}", "", line).strip()


def logical_lines(text: str, keep_code: bool) -> list[str]:
    """Lines of prose, list marks removed. A fenced block is dropped (pasted code and logs are not
    requirements) unless `keep_code`. A line is never joined to the next: people type one thought a
    line, often without a closing stop."""
    out: list[str] = []
    fenced = False
    for raw in (text or "").splitlines():
        if _FENCE_RE.match(raw):
            fenced = not fenced
            continue
        if fenced and not keep_code:
            continue
        line = raw.strip()
        if not line or _TABLE_SEP_RE.match(line) and "-" in line:
            continue
        if not keep_code and line.startswith(">"):
            continue
        out.append(_LIST_MARK_RE.sub("", line))
    return out


def split_sentences(line: str) -> list[str]:
    out, start = [], 0
    for m in _BOUNDARY_RE.finditer(line):
        last = line[start:m.start(1)].split()
        tail = last[-1].lower().rstrip(".") if last else ""
        if m.group(1).startswith(".") and tail in lexicon.COVER_ABBREV:
            continue
        out.append(line[start:m.end(1)].strip())
        start = m.end()
    out.append(line[start:].strip())
    return [s for s in out if s]


def chatter(sentence: str) -> bool:
    w = words(sentence)
    if not w:
        return True
    if sentence.rstrip().endswith("?") and _STATE_RE.search(sentence):
        return True
    cues = set(words(re.sub("['\u2019]", "", sentence)))      # "don't" -> "dont"
    return w[0] in lexicon.COVER_CHATTER_LEAD and len(w) <= 12 and not (cues & lexicon.COVER_CUE)


def _worth_keeping(s: str) -> bool:
    if len(words(s)) < MIN_WORDS or chatter(s):
        return False
    stripped = _URL_RE.sub("", s)
    return len(words(stripped)) >= MIN_WORDS


def source_sentences(entries: list[dict]) -> list[dict]:
    """The sentences worth checking, oldest entry first. A sentence repeated in a later entry counts once."""
    out, seen = [], set()
    for idx, e in enumerate(entries):
        text, _ = intent.kept_text(e["text"])
        text = _TAG_RE.sub(" ", text)
        for line in logical_lines(text, keep_code=False):
            for s in split_sentences(line):
                s = s.rstrip(' "') if s.count('"') % 2 else s       # a quote mark left behind by a stripped tag
                key = norm(s)
                if key in seen or not _worth_keeping(s):
                    continue
                seen.add(key)
                out.append({"text": s, "entry": idx, "date": e["date"], "harness": e.get("harness", ""),
                            "session": e.get("session", ""), "lang": "ru" if cyr_share(s) >= 0.3 else "en"})
    return out


# --- the plan ------------------------------------------------------------------------------

def plan_units(text: str) -> list[dict]:
    """Pieces of the plan a source sentence can match: every sentence, every two next to each other
    and, for a short block, the whole block. Each carries its content words and whether it sits under
    an out-of-scope heading or line."""
    units: list[dict] = []
    oos_level = None      # heading level of the open out-of-scope section
    oos_block = False     # an out-of-scope line, until the next blank line or heading
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            oos_block = False
            continue
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            if oos_level is not None and level <= oos_level:
                oos_level = None
            if oos_level is None and _OOS_RE.search(h.group(2)):
                oos_level = level
            oos_block = False
            line = h.group(2)
        elif _OOS_LINE_RE.match(_plain(line)):
            oos_block = True
        if _FENCE_RE.match(line) or (_TABLE_SEP_RE.match(line) and "-" in line):
            continue
        in_oos = oos_level is not None or oos_block
        cells = [c for c in line.split("|")] if line.startswith("|") else [line]
        for cell in cells:
            block = [s for s in split_sentences(_plain(_LIST_MARK_RE.sub("", cell))) if s]
            if not block:
                continue
            pieces = list(block)
            pieces += [" ".join(block[i:i + 2]) for i in range(len(block) - 1)]
            if 2 < len(block) <= 6:
                pieces.append(" ".join(block))
            for p in pieces:
                st = stems(p)
                if st:
                    units.append({"text": p, "stems": st, "oos": in_oos})
    return units


class Plan:
    def __init__(self, text: str):
        self.text = text
        self.units = plan_units(text)
        self.words = words(text)
        self.joined = " " + " ".join(self.words) + " "
        self.cyr = cyr_share(text)
        self.english = self.cyr < RU_PLAN_SHARE
        self._grams: dict[int, set] = {}
        # the words that sit under an out-of-scope heading or line, to tell a quote there from one elsewhere
        self.oos_joined = " " + " ".join(norm(u["text"]) for u in self.units if u["oos"]) + " "

    def _gram_set(self, k: int) -> set:
        if k not in self._grams:
            w = self.words
            self._grams[k] = {tuple(w[i:i + k]) for i in range(len(w) - k + 1)}
        return self._grams[k]

    def quotes(self, sentence: str) -> bool:
        w = words(sentence)
        if not w:
            return False
        if " " + " ".join(w) + " " in self.joined:
            return True
        k = max(RUN_MIN, math.ceil(RUN_SHARE * len(w)))
        if k > len(w):
            return False
        grams = self._gram_set(k)
        return any(tuple(w[i:i + k]) in grams for i in range(len(w) - k + 1))

    def best_unit(self, sentence: str) -> tuple[dict | None, int, int]:
        """(the plan unit sharing most content words with the sentence, hits, the sentence's word count)."""
        a = stems(sentence)
        best, hits = None, 0
        for u in self.units:
            n = len(a & u["stems"])
            if n > hits or (n == hits and n and best is not None and best["oos"] and not u["oos"]):
                best, hits = u, n
        return best, hits, len(a)


def judge(sentence: dict, plan: Plan) -> dict:
    """The sentence with `status` (served, unserved, needs_model), `via` and `plan` (the plan text matched)."""
    s = sentence["text"]
    unit, hits, n = plan.best_unit(s)
    if plan.quotes(s):
        oos = " " + norm(s) + " " in plan.oos_joined
        return {**sentence, "status": "served", "via": "out of scope" if oos else "quote", "plan": ""}
    if unit is not None and n >= 2 and hits >= min(MIN_HITS, n) and hits / n >= OVERLAP:
        return {**sentence, "status": "served", "via": "out of scope" if unit["oos"] else "words",
                "plan": unit["text"]}
    if sentence["lang"] == "ru" and plan.english:
        return {**sentence, "status": "needs_model", "via": "", "plan": ""}
    return {**sentence, "status": "unserved", "via": "", "plan": ""}


# --- the model pass ------------------------------------------------------------------------

COVER_SYSTEM = (
    "You check whether a plan serves what its owner asked for. You get the plan and a list of the owner's "
    "sentences as JSON and reply with strict JSON only, no prose and no code fence:\n"
    '{"results": [{"id": 1, "served": true, "where": "<at most 12 words naming the part of the plan, or empty>"}]}\n'
    "A sentence is served when the plan holds a step, requirement, decision or target that addresses that "
    "specific point, in any language, or lists the point as out of scope or deferred. A passing mention of the "
    "topic does not serve it. Every id appears once. Never invent plan content."
)


def cover_command() -> list[str]:
    """The brief call of state.py with this system prompt: `claude -p`, no tools, no skills, no MCP
    servers, no settings files, no saved session; the prompt goes in on stdin."""
    from . import state
    cmd = state.brief_command()
    cmd[cmd.index("--system-prompt") + 1] = COVER_SYSTEM
    return cmd


def model_unavailable() -> str | None:
    """Why the model pass cannot run, or None."""
    from . import config
    try:
        if config.safe_mode(config.load()):
            return "safe mode is on, and the owner's prompts stay on this machine"
    except Exception:  # noqa: BLE001 — an unreadable config means no model call
        return "the config is unreadable"
    return None if shutil.which("claude") else "no claude on PATH"


def _call(cmd: list[str], input_text: str) -> tuple[int, str]:
    """Tests replace this one function; none starts a real claude."""
    from . import state
    return state._run_claude(cmd, input_text, timeout=state.BRIEF_TIMEOUT_S)


def validate_cover(reply, ids: set[int]) -> dict[int, tuple[bool, str]] | None:
    """{id: (served, where)} from the model's reply, or None when it cannot be trusted: an unknown or
    repeated id, or a verdict that is not a boolean, rejects the whole reply."""
    raw = reply.get("results") if isinstance(reply, dict) else None
    if not isinstance(raw, list):
        return None
    out: dict[int, tuple[bool, str]] = {}
    for r in raw:
        if not isinstance(r, dict):
            return None
        i, v = r.get("id"), r.get("served")
        if isinstance(i, bool) or i not in ids or i in out or not isinstance(v, bool):
            return None
        w = r.get("where")
        out[i] = (v, " ".join(w.split()[:12]) if isinstance(w, str) else "")
    return out


def model_pass(items: list[dict], plan_text: str) -> tuple[list[dict], dict]:
    """Ask the model about every unresolved item (status unserved or needs_model), BATCH at a time.
    Returns (items with the verdicts applied, {calls, judged, cost_usd, error}). A failed batch leaves
    its items as they were."""
    from . import state
    todo = [i for i, it in enumerate(items) if it["status"] != "served"]
    info = {"calls": 0, "judged": 0, "cost_usd": 0.0, "error": ""}
    out = [dict(it) for it in items]
    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        payload = {"plan": plan_text[:PLAN_CHARS],
                   "sentences": [{"id": n, "text": items[i]["text"][:SENTENCE_CHARS]} for n, i in enumerate(chunk)]}
        info["calls"] += 1
        try:
            code, raw = _call(cover_command(), json.dumps(payload, ensure_ascii=False))
            if code != 0:
                info["error"] = f"claude exited {code}"
                break
            reply, usage = state._parse_reply(raw)
        except (ValueError, OSError) as e:
            info["error"] = f"unusable reply ({type(e).__name__})"
            break
        verdicts = validate_cover(reply, set(range(len(chunk))))
        if verdicts is None:
            info["error"] = "the reply did not validate"
            break
        info["cost_usd"] += float(usage.get("cost_usd") or 0)
        for n, (served, where) in verdicts.items():
            it = out[chunk[n]]
            it["status"] = "served" if served else "unserved"
            it["via"] = "model" if served else ""
            it["plan"] = where
            info["judged"] += 1
    return out, info


# --- the command ---------------------------------------------------------------------------

def select_entries(es: list[dict], since: str | None, last: int | None) -> list[dict]:
    if since:
        es = [e for e in es if e["date"][:10] >= since]
    return es[-last:] if last else es


def run_cover(plan_text: str, entries: list[dict], use_model: bool = False) -> dict:
    """The whole check, with no printing: {total, served, unserved, needs_model, via, items, model}."""
    plan = Plan(plan_text)
    items = [judge(s, plan) for s in source_sentences(entries)]
    model = {"calls": 0, "judged": 0, "cost_usd": 0.0, "error": "", "skipped": ""}
    if use_model and any(it["status"] != "served" for it in items):
        why = model_unavailable()
        if why:
            model["skipped"] = why
        else:
            items, info = model_pass(items, plan_text)
            model.update(info)
    count = lambda st: sum(1 for it in items if it["status"] == st)  # noqa: E731
    via: dict[str, int] = {}
    for it in items:
        if it["status"] == "served":
            via[it["via"]] = via.get(it["via"], 0) + 1
    return {"total": len(items), "served": count("served"), "unserved": count("unserved"),
            "needs_model": count("needs_model"), "via": via, "items": items, "model": model}


def _clip(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= SHOW_CHARS else s[:SHOW_CHARS - 1].rstrip() + "…"


def _group(items: list[dict]) -> list[str]:
    lines, last = [], None
    for it in items:
        key = (it["entry"], it["date"], it["session"])
        if key != last:
            lines.append(f"{it['date']} · {it['harness'] or 'unknown'} · session {it['session'] or '?'}")
            last = key
        lines.append(f"  - {_clip(it['text'])}")
    return lines


def render(res: dict) -> str:
    out = [f"served {res['served']} of {res['total']}"]
    extra = []
    if res["via"].get("out of scope"):
        extra.append(f"{res['via']['out of scope']} listed as out of scope")
    if res["via"].get("model"):
        extra.append(f"{res['via']['model']} by the model")
    if extra:
        out.append("  (" + ", ".join(extra) + ")")
    m = res["model"]
    if m["calls"]:
        out.append(f"model pass: {m['calls']} call(s), {m['judged']} judged, ${m['cost_usd']:.4f}"
                   + (f"; stopped: {m['error']}" if m["error"] else ""))
    elif m["skipped"]:
        out.append(f"model pass skipped: {m['skipped']}")
    bad = [it for it in res["items"] if it["status"] == "unserved"]
    wait = [it for it in res["items"] if it["status"] == "needs_model"]
    if bad:
        out += ["", f"Unserved ({len(bad)}): the plan neither quotes, covers nor sets these aside"] + _group(bad)
    if wait:
        out += ["", f"Needs --model ({len(wait)}): Russian sentences, English plan; words cannot decide these"] + _group(wait)
    return "\n".join(out)


def cmd_cover(args, words_: list[str]) -> int:
    if len(words_) != 2:
        print("usage: teyla intent cover <plan.md> [--product P] [--since YYYY-MM-DD] [--last N] [--model] [--json]",
              file=sys.stderr)
        return 64
    since = getattr(args, "since", None)
    last = getattr(args, "last", None)
    if since:
        try:
            _dt.date.fromisoformat(since)
        except ValueError:
            print("teyla: --since takes a date, YYYY-MM-DD", file=sys.stderr)
            return 64
    if last is not None and last < 1:
        print("teyla: --last takes a positive number", file=sys.stderr)
        return 64
    plan_path = pathlib.Path(words_[1]).expanduser()
    try:
        plan_text = plan_path.read_text(errors="replace")
    except OSError as e:
        print(f"teyla: cannot read the plan: {e.strerror or e}", file=sys.stderr)
        return 2
    wanted = getattr(args, "product", None) or intent.product_for(plan_path.resolve().parent)
    name = intent.resolve(wanted)
    if name is None:
        print(f"teyla: no intent recorded for {wanted}; teyla intent backfill --days 30 fills it", file=sys.stderr)
        return 2
    es = select_entries(intent.entries(name), since, last)
    if not es:
        print(f"teyla: no entries for {name} match that window", file=sys.stderr)
        return 2
    res = run_cover(plan_text, es, use_model=bool(getattr(args, "model", False)))
    if args.json:
        print(json.dumps({"plan": str(plan_path), "product": name, "entries": len(es), **res},
                         ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 1 if res["unserved"] else 0
