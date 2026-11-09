"""The owner's content formats and calls to action (docs/GROWTH.md, "The formats" and "Calls to action").

A note tag picks the format, the format picks the call to action (CTA), and the code, never the model, builds every link:

    note_format(text)          the format a note's tag selects (`#wow` -> wow-use-case); `#content` stays a lesson
    note_idea(...)             the master idea a tagged note becomes, or why it cannot become one
    week_facts(...)            counts Teyla gathered (merged PRs, published items, logged calls); the only numbers a
                               week-results post may use
    resolve(item, cfg, reg)    the CTA of one item: kind, link, handles, and a hold reason when it cannot be built
    apply_cta(item)            put the CTA on a model reply: the link and the tags are added here, never by the model
    findings(item, ...)        draft-check findings: a link in the body, "let's meet" in a spec post, a tag in the body,
                               a research post that claims a product exists

No model call, no network, no import of `growth` (it imports this module). Every function reads only what it is given.
"""
from __future__ import annotations

import re
import urllib.parse

# --- formats --------------------------------------------------------------------------------------------------------

NEW = ("wow-use-case", "case-study", "week-results", "ai-native", "prediction", "viral-remix", "inadviser-verdict", "research-note")

# A note tag selects the format. The first tag in this order wins when a note carries several.
TAGS = (("spec", "spec-product"), ("tvc", "true-vibe-coding"), ("wow", "wow-use-case"), ("case", "case-study"),
        ("week", "week-results"), ("ainative", "ai-native"), ("predict", "prediction"), ("viral", "viral-remix"),
        ("inadviser", "inadviser-verdict"), ("research", "research-note"), ("content", "lesson"))
TAG_RE = re.compile(r"(?<!\w)#(" + "|".join(t for t, _ in TAGS) + r")\b", re.I)
CLIP_FORMATS = ("spec-product", "true-vibe-coding", "wow-use-case")      # shown on screen; the rest are text first

BRIEFS = {
    "wow-use-case": "One surprising real use of an AI product or agent, shown working. Open with what it did that a reader would not expect, then the one concrete step-by-step proof (a command, a screen, a result) from the facts. If the facts show no working result, write less. Name who built the thing only if the facts do.",
    "case-study": "One case: a business, a startup or a personal-productivity setup. Before, what was done, after, with the numbers from the facts and no others. Say what it cost or what broke. Never round a number up and never add one.",
    "week-results": "The week in counts Teyla gathered, and only those: merged pull requests, items published, calls and meetings logged. Open with the biggest count, then what it produced in plain words. Never write revenue, MRR, conversion or user counts, never a count that is not in the facts, and no date: say last week.",
    "ai-native": "How to become AI-native: one practice the owner runs in his own factory, with receipts from the facts (a count, a command, a file, a failure). Open with the practice, then the receipt, then what a reader can copy today. No slogans and no theory without a receipt.",
    "prediction": "A dated prediction about where one technology goes. State it as a claim a reader can check later: what, by when, and the one reason, from the facts. Put the claim in `claim` as one sentence with its horizon, so a later post can check it. No hedging and no hype.",
    "viral-remix": "Borrow only the structure of a viral post (the shape of its hook, its pacing, its turn), never its claims, numbers, names or wording. Write the owner's own point in that structure, from the facts. Do not name the source's author and do not quote it.",
    "inadviser-verdict": "A value-for-money verdict on one product, from inadviser.com and from the facts only. Open with the verdict, then the two facts that carry it (price, what is included, what is missing). It is a judgement on value, never financial advice, never a recommendation to buy or invest.",
    "research-note": "A research note: a problem the owner is studying before he builds anything. The product may not exist yet: say you are researching the problem, never that the product exists, launched, ships or can be used. Name the problem, what the owner already learned from the facts, and the one question he still cannot answer.",
}

# The planner's prior by format (growth_rank.prior): how likely the editor passes a draft of this format on its own.
PRIOR = {"true-vibe-coding": 0.4, "wow-use-case": 0.6, "case-study": 0.55, "week-results": 0.6, "ai-native": 0.5,
         "prediction": 0.4, "viral-remix": 0.35, "inadviser-verdict": 0.5, "research-note": 0.45}


def note_format(text: str) -> str | None:
    """The format a note's tags select, or None when it carries none of them."""
    found = {m.group(1).lower() for m in TAG_RE.finditer(text or "")}
    return next((fmt for tag, fmt in TAGS if tag in found), None)


def strip_tags(text: str) -> str:
    return " ".join(TAG_RE.sub("", text or "").split())


_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{2,30}")


def urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in _URL.findall(text or "")]


def handles(text: str) -> list[str]:
    return list(dict.fromkeys(h.rstrip(".") for h in _HANDLE.findall(text or "")))[:4]


def _digitless(text: str) -> str:
    return " ".join(re.sub(r"[$€]?\d[\d.,]*%?", "", text or "").split())


def _public_product(text: str, note_product: str, public: set[str], reg: dict) -> str:
    """The one public product a note is about: the note's own product, else the only public product its text names."""
    if note_product in public:
        return note_product
    from . import registry
    named = [p for p in registry.match_text(text, reg) if p in public]
    return named[0] if len(named) == 1 else ""


def note_idea(fmt: str, text: str, *, note_product: str, public: set[str], reg: dict, counts: list[str]) -> tuple[dict | None, str]:
    """(fields for the master idea, "") for a tagged note, or (None, why not). `text` has its tags removed. The idea is
    the owner's own sentence; facts are the owner's sentence plus, for week-results and ai-native, Teyla's counts."""
    text = text.strip()
    if not text:
        return None, "empty"
    scores = dict(relevance=4, demonstrable=3, novelty=4, momentum=3)
    kind = "clip" if fmt in CLIP_FORMATS else "post"
    pid = _public_product(text, note_product, public, reg)
    out: dict = dict(kind=kind, format=fmt, product=pid, idea=text[:400], facts=[text[:400]], owner=True, scores=scores)
    if fmt == "lesson":
        return dict(out, product=note_product if note_product in public else ""), ""
    if fmt == "spec-product":
        tags = handles(text)
        bare = " ".join(_HANDLE.sub("", text).split())
        return dict(out, product="", idea=bare[:400], facts=[bare[:400]], tags=tags), ""   # never one of our own products
    if fmt == "week-results":
        angle = _digitless(text)
        return dict(out, idea=("Week results: " + angle)[:400], facts=list(counts), product=""), ""
    if fmt == "ai-native":
        return dict(out, facts=[text[:400], *counts]), ""
    if fmt == "viral-remix":
        src = urls(text)
        if not src:
            return None, "no source URL"
        bare = " ".join(_URL.sub("", text).split())
        return dict(out, idea=bare[:400], facts=[bare[:400]], url=src[0], source_url=src[0], product=""), ""
    if fmt == "inadviser-verdict":
        src = [u for u in urls(text) if re.match(r"https?://([\w-]+\.)*inadviser\.com(/|$|\?)", u, re.I)]
        if not src:
            return None, "no inadviser.com source URL"
        bare = " ".join(_URL.sub("", text).split())
        return dict(out, idea=bare[:400], facts=[bare[:400]], url=src[0], product="inadviser" if "inadviser" in public else ""), ""
    if fmt == "research-note":
        return dict(out, facts=[text[:400], "the product may not exist yet; this is research before building"]), ""
    return out, ""


# --- week results: counts Teyla gathered ----------------------------------------------------------------------------

def last_week(today: str) -> tuple[str, str, str]:
    """(Monday, Sunday, ref) of the last completed ISO week before `today` (YYYY-MM-DD)."""
    import datetime as dt
    t = dt.date.fromisoformat(today)
    sunday = t - dt.timedelta(days=t.isoweekday())
    monday = sunday - dt.timedelta(days=6)
    y, w, _ = monday.isocalendar()
    return monday.isoformat(), sunday.isoformat(), f"{y}-W{w:02d}"


def week_facts(today: str, pr_days: list[str] | None, ledger: list[dict], is_claimed, row_n, meeting_kinds) -> list[str]:
    """Facts for the last completed week: merged pull requests (None when the PR cache is empty: no line, never a zero),
    items published, calls and meetings the owner logged. A row an agent only claimed counts for nothing. These are the
    only numbers a week-results post may use."""
    start, end, _ = last_week(today)
    facts = [f"Counts gathered by Teyla for the week {start} to {end}: merged pull requests, items published and calls "
             f"or meetings logged by the owner. No other number exists."]
    if pr_days is not None:
        facts.append(f"merged pull requests in the week: {sum(1 for d in pr_days if start <= d <= end)}")
    pub = sum(row_n(r) for r in ledger if r.get("ev") == "published" and start <= str(r.get("day") or "") <= end)
    facts.append(f"content items published in the week: {pub}")
    calls = sum(row_n(r) for r in ledger if r.get("ev") == "attempt" and r.get("kind") in meeting_kinds
                and not is_claimed(r) and start <= str(r.get("day") or "") <= end)
    facts.append(f"calls and meetings the owner logged in the week: {calls}")
    return facts


# --- calls to action ------------------------------------------------------------------------------------------------

EARLY_BASE = "https://accounts.fabriquefutur.com/early/"
EARLY_SOURCE = "accounts-early-access.json"


def early_forms(cfg: dict) -> set[str]:
    """The early-access forms that exist, as slugs. `early_products` in the growth config wins (an empty list means none);
    otherwise the products the accounts hub reports in its cockpit source (`~/.teyla/gtm/sources/accounts-early-access.json`),
    so a form added at the hub is used from the next run. No file, no config: no form is known and no link is built."""
    if isinstance(cfg.get("early_products"), list):
        return {early_slug(x) for x in cfg["early_products"]}
    try:
        import json
        from . import gtm
        data = json.loads((gtm.drop_dir() / EARLY_SOURCE).read_text(encoding="utf-8"))
        prods = data.get("products")
        return {early_slug(k) for k in prods} if isinstance(prods, dict) else set()
    except (OSError, ValueError, AttributeError):
        return set()

CTA_BY_FORMAT = {"spec-product": "founder-question", "true-vibe-coding": "early-access", "wow-use-case": "early-access",
                 "case-study": "talk", "ai-native": "talk", "week-results": "follow", "prediction": "follow",
                 "inadviser-verdict": "early-access", "research-note": "research"}

CTA_BRIEF = {
    "founder-question": "CTA: none in the body. Do not write 'let's meet', 'book a call' or any invitation, and no @ tag. "
                        "first_comment is one real question to the founder of the company, about the behaviour the prototype shows, at most 25 words, ending with a question mark. No link and no @ tag: the code adds the tag.",
    "early-access": "CTA: early access. The body may end with one plain sentence that early access to the product is open. Never write 'comment X to get access' or any comment-gate, and no link in the body. "
                    "first_comment is one short line inviting the reader to early access, with no link: the code adds it.",
    "talk": "CTA: the last line of the body is one invitation: tell me about your team, let's talk. Never mention hiring, a job search, a role or an employer. No link.",
    "follow": "CTA: the last line of the body is one invitation to follow for the next one. No link, no other ask.",
    "research": "CTA: join the research. The body may end with one plain sentence inviting the reader to join the research. "
                "first_comment is one short line about what the research asks, with no link: the code adds the form link. Never write 'comment X to get access'.",
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def early_slug(pid: str) -> str:
    """The accounts hub names a form without hyphens ("petit-chef" is "petitchef")."""
    return str(pid or "").lower().replace("-", "")


def with_ref(url: str, ref: str) -> str:
    """`url` with `ref=<channel>` as its query parameter (replacing one that is there)."""
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k != "ref"]
    q.append(("ref", ref))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))


def early_link(pid: str, channel: str) -> str:
    slug = early_slug(pid)
    return with_ref(EARLY_BASE + slug, channel) if _SLUG.match(slug) and _SLUG.match(str(channel or "")) else ""


def research_link(cfg: dict, channel: str) -> str:
    url = str(cfg.get("research_form") or "").strip()
    p = urllib.parse.urlsplit(url)
    return with_ref(url, channel) if p.scheme == "https" and p.netloc and _SLUG.match(str(channel or "")) else ""


def resolve(item: dict, cfg: dict, reg: dict | None = None) -> dict:
    """The CTA of one item: {kind, link, handles, hold}. `hold` is a reason the post cannot be drafted yet (a research post
    with no form link). A link CTA whose form does not exist degrades to kind "none" and says why in `note`. Only a
    public product gets an early-access link."""
    fmt = item.get("format", "")
    kind = CTA_BY_FORMAT.get(fmt, "none")
    channel = item.get("platform", "")
    out = dict(kind=kind, link="", handles=list(item.get("tags") or []), hold="", note="")
    if kind == "early-access":
        pid = item.get("product") or ""
        slug = early_slug(pid)
        enabled = early_forms(cfg)
        if pid and pid in set(cfg.get("public_products") or []) and slug in enabled:
            out["link"] = early_link(pid, channel)
        else:
            out.update(kind="none", note=f"no early-access form for {pid or 'this post'}: the product is not public or has no form at the accounts hub")
    elif kind == "research":
        out["link"] = research_link(cfg, channel)
        if not out["link"]:
            out["hold"] = "no research form link: set `research_form = \"https://...\"` in the growth config (`teyla growth doctor`)"
    return out


def brief(cta: dict) -> str:
    return CTA_BRIEF.get(cta.get("kind", ""), "CTA: none. End the post on its last fact.")


def apply_cta(item: dict) -> None:
    """Make `first_comment` carry the CTA. The model writes a line without a URL; the link and the tags are added here,
    so a model can never invent a link or tag a stranger. Other formats keep what the model wrote."""
    cta = item.get("cta") or {}
    kind, link = cta.get("kind"), cta.get("link") or ""
    fc = str(item.get("first_comment") or "")
    if link:
        fc = " ".join(_URL.sub("", fc).split())
        item["first_comment"] = (fc + " " + link).strip()
    elif kind == "founder-question":
        fc = " ".join(_HANDLE.sub("", _URL.sub("", fc)).split())
        item["first_comment"] = " ".join([*cta.get("handles", []), fc]).strip()


# --- checks ---------------------------------------------------------------------------------------------------------

_MEET = re.compile(r"\b(let'?s (meet|talk|chat|connect|jump on)|let us (meet|talk)|meet (me|up)|book a (call|meeting|chat)|"
                   r"schedule a (call|meeting|chat)|grab a (coffee|call)|hop on a call|dm me|get in touch)\b", re.I)
_EXISTS = re.compile(r"\b(launch(ed|ing)?|now (live|available)|available (now|today)|is (live|out|here)|ships?|shipped|shipping|"
                     r"released?|download|try it|sign ?up|early access|beta|built it|we built|i built|our (app|product|tool))\b", re.I)


def _f(rule: str, message: str) -> dict:
    return dict(level="fail", rule=rule, message=message)


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _week_numbers(item: dict, text: str) -> list[dict]:
    """A week-results post may use only the counts Teyla gathered: every number in it must be one of them. A date is not
    a count, and the post says "last week" instead."""
    allowed = {m for f in item.get("facts") or [] for m in re.findall(r"in the week: (\d+)$", str(f).strip())}
    bad = [n for n in re.findall(r"\d+", _DATE.sub("", text)) if n not in allowed]
    return [_f("week-number", "a week-results post uses only the gathered counts (merged pull requests, items published, "
                              "calls and meetings), no other number and no date")] if bad else []


def findings(item: dict, text: str, hook: str = "", script: str = "") -> list[dict]:
    """Voice-style findings (rule and message, never the text) for what a CTA forbids. `item["cta"]` is the resolved CTA."""
    cta = item.get("cta") or {}
    kind = cta.get("kind", "")
    body = "\n".join(t for t in (text, hook, script) if t)
    out = []
    if item.get("format") == "week-results":
        out += _week_numbers(item, "\n".join([body, str(item.get("first_comment") or "")]))
    if kind in ("early-access", "research") and cta.get("link") and _URL.search(body):
        out.append(_f("cta-link", "the link goes in the first comment, never in the post body; remove it from the body"))
    if kind == "founder-question":
        if _MEET.search(body):
            out.append(_f("cta-meet", "a spec post never asks to meet in its body; the one question goes in the first comment"))
        if _HANDLE.search(body):
            out.append(_f("cta-tag", "no @ tag in the body; the company or founder is tagged only in the first reply"))
        if "?" not in re.sub(r"@\w+", "", str(item.get("first_comment") or "")):
            out.append(_f("cta-question", "first_comment must be one question to the founder"))
    if item.get("format") == "research-note" and not item.get("product") and _EXISTS.search(body + "\n" + str(item.get("first_comment") or "")):
        out.append(_f("research-claim", "a research note must not say the product exists, launched, ships or can be tried"))
    return out
