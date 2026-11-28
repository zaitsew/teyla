"""The playbook: best-practice cards, filled in stages (docs/decisions/2026-11-28-playbook.md, P1-P7; docs/PLAYBOOK.md).

    teyla playbook add --domain D --job J --surface S --mechanism M --refuse R --evidence-product P --evidence-url U --evidence-what W
    teyla playbook list [--domain D] [--status S] [--product P] [--kind K] [--json]
    teyla playbook show <id>
    teyla playbook set <id> [status=S] [--from FILE]     stage fields from a YAML or JSON file; the stage is checked
    teyla playbook expire [--apply]                      seen after 90 days, candidate after 30
    teyla playbook brief --product P --surface S [--domain D] [--job J] [--max 5] [--tokens 1500] [--json]
    teyla playbook check [PATH]                          every card against templates/playbook/card.schema.json

A card is `<root>/cards/<domain>/<id>.md`: YAML front matter, then a body of at most 150 words. The root is
`playbook_root` in the config (default ~/ops/playbook); `TEYLA_PLAYBOOK_ROOT` overrides it. The index is built in
memory on every call and never written. Nothing here touches the network. Teyla has no dependencies, so the front
matter is read by a small parser for the YAML the cards use: block maps and lists, flow lists, quoted strings.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys

DOMAINS = ("interaction", "flow", "ai", "visual", "writing", "listing", "demand")
KINDS = ("pattern", "hook")
STATUSES = ("seen", "candidate", "trial", "adopted", "rejected", "inconclusive", "parked", "expired")
CLOSED = ("adopted", "rejected", "inconclusive", "parked")
BRIEF_STATUSES = ("candidate", "trial", "adopted")
EXPIRY_DAYS = {"seen": 90, "candidate": 30}
MAX_BODY_WORDS = 150
TRANSITIONS = {
    "seen": {"candidate", "rejected", "parked"},
    "candidate": {"trial", "rejected", "parked"},
    "trial": {"adopted", "rejected", "inconclusive", "parked"},
    "expired": {"candidate"},
}
ORDER = ["id", "domain", "kind", "status", "job", "surface", "platform", "mechanism", "refuse", "evidence",
         "added_by", "created", "updated", "line", "format", "promise", "proof", "cta", "problem", "severity",
         "confidence", "trial", "verdict", "results"]
SUBORDER = {"evidence": ["product", "url", "seen", "what", "observed", "media"],
            "problem": ["product", "text", "pointer"],
            "trial": ["hypothesis", "metric", "baseline", "threshold", "direction", "window_days", "guardrails",
                      "review_by", "variants", "approved"],
            "verdict": ["result", "numbers", "date", "pr", "trigger"],
            "results": ["date", "channel", "growth_item", "denominator", "views", "saves", "named_replies",
                        "visits", "installs"]}
STOP = set("a an the of to in on for and or with by from at as is it this that be your you we our into per".split())


class CardError(ValueError):
    """A problem the owner can fix: a bad id, a bad flag, a card that does not read."""


# --- paths ------------------------------------------------------------------------------------------

def root() -> pathlib.Path:
    env = os.environ.get("TEYLA_PLAYBOOK_ROOT")
    if env:
        return pathlib.Path(env).expanduser()
    from . import config
    return pathlib.Path(config.load().get("playbook_root") or "~/ops/playbook").expanduser()


def cards_dir(base: pathlib.Path | None = None) -> pathlib.Path:
    return (base or root()) / "cards"


def schema() -> dict:
    from . import templates_dir
    return json.loads((templates_dir() / "playbook" / "card.schema.json").read_text(encoding="utf-8"))


def today() -> _dt.date:
    return _dt.date.today()


# --- the YAML the cards use ---------------------------------------------------------------------------

def _strip_comment(s: str) -> str:
    quote, skip = None, False
    for i, ch in enumerate(s):
        if skip:
            skip = False
        elif quote:
            if ch == "\\" and quote == '"':
                skip = True
            elif ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " [,:{-"):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _split_flow(s: str) -> list[str]:
    parts, cur, quote, depth, skip = [], "", None, 0, False
    for ch in s:
        if skip:
            cur += ch
            skip = False
        elif quote:
            cur += ch
            if ch == "\\" and quote == '"':
                skip = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _scalar(s: str):
    s = s.strip()
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s[0] == '"':
        try:
            return json.loads(s)
        except ValueError as e:
            raise CardError(f"bad quoted string {s[:30]}") from e
    if s[0] == "'" and s[-1] == "'" and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s[0] == "[" and s[-1] == "]":
        return [_scalar(p) for p in _split_flow(s[1:-1])]
    if s[0] == "{" and s[-1] == "}":
        out = {}
        for p in _split_flow(s[1:-1]):
            k, sep, v = p.partition(":")
            if not sep:
                raise CardError(f"bad flow map {s[:30]}")
            out[k.strip().strip("\"'")] = _scalar(v)
        return out
    if s[0] in "|>&*!":
        raise CardError(f"unsupported YAML ({s[:20]})")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def parse_yaml(text: str):
    """The YAML subset the cards use. Raises CardError on anything else."""
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise CardError("tabs in indentation")
        t = _strip_comment(raw)
        if t.strip():
            lines.append((len(t) - len(t.lstrip(" ")), t.strip()))
    if not lines:
        return {}
    val, i = _block(lines, 0, lines[0][0])
    if i != len(lines):
        raise CardError(f"unexpected indentation near `{lines[i][1][:40]}`")
    return val


def _kv(text: str):
    m = re.match(r'^("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^:\s][^:]*?)\s*:(?:\s+(.*))?$', text)
    if not m:
        return None
    return m.group(1).strip("\"'"), (m.group(2) or "")


def _block(lines, i, indent):
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        out = []
        while i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
            rest = lines[i][1][1:].strip()
            if not rest:
                if i + 1 < len(lines) and lines[i + 1][0] > indent:
                    v, i = _block(lines, i + 1, lines[i + 1][0])
                else:
                    v, i = None, i + 1
            elif _kv(rest) and not rest.startswith(("[", "{", '"', "'")) or (rest[0] in "\"'" and _kv(rest)):
                lines[i] = (indent + 2, rest)
                v, i = _block(lines, i, indent + 2)
            else:
                v, i = _scalar(rest), i + 1
            out.append(v)
        return out, i
    out = {}
    while i < len(lines) and lines[i][0] == indent:
        kv = _kv(lines[i][1])
        if kv is None:
            raise CardError(f"not a `key: value` line: `{lines[i][1][:40]}`")
        key, rest = kv
        if key in out:
            raise CardError(f"duplicate key `{key}`")
        if rest.strip():
            out[key] = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and (lines[i + 1][0] > indent or (lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "))):
            out[key], i = _block(lines, i + 1, lines[i + 1][0])
        else:
            out[key], i = None, i + 1
    return out, i


def _plain_ok(s: str) -> bool:
    if not s or s != s.strip() or s[0] in "-?:,[]{}#&*!|>'\"%@`" or "\n" in s:
        return False
    if ": " in s or " #" in s or s.endswith(":"):
        return False
    if s.lower() in ("null", "true", "false", "~", "yes", "no") or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return False
    return True


def _emit_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return s if _plain_ok(s) else json.dumps(s, ensure_ascii=False)


def _emit(v, indent: int, order: list[str] | None, out: list[str], parent: str = "") -> None:
    pad = " " * indent
    if isinstance(v, dict):
        keys = sorted(v, key=lambda k: (order.index(k) if order and k in order else len(order or []), k))
        for k in keys:
            x = v[k]
            sub = SUBORDER.get(k)
            if isinstance(x, (dict, list)) and x:
                out.append(f"{pad}{k}:")
                _emit(x, indent + 2, sub, out, k)
            else:
                out.append(f"{pad}{k}: {'[]' if x == [] else '{}' if x == {} else _emit_scalar(x)}")
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, dict) and x:
                sub: list[str] = []
                _emit(x, indent + 2, SUBORDER.get(parent), sub, parent)
                sub[0] = f"{pad}- {sub[0].lstrip()}"
                out.extend(sub)
            else:
                out.append(f"{pad}- {_emit_scalar(x)}")


def dump_card(meta: dict, body: str) -> str:
    out: list[str] = []
    _emit(meta, 0, ORDER, out)
    return "---\n" + "\n".join(out) + "\n---\n" + body.strip() + ("\n" if body.strip() else "")


def split_card(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CardError("no front matter (the file must start with `---`)")
    for j in range(1, len(lines)):
        if lines[j].strip() == "---":
            meta = parse_yaml("\n".join(lines[1:j]))
            if not isinstance(meta, dict):
                raise CardError("front matter is not a map")
            return meta, "\n".join(lines[j + 1:]).strip()
    raise CardError("front matter is not closed with `---`")


# --- the schema check (the subset the schema file uses, plus allOf / if / then / false) ----------------

_TYPES = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "null": type(None),
          "boolean": bool}


def _check(value, sch, where: str, out: list[str]) -> None:
    if sch is False:
        out.append(f"{where}: not allowed at this stage")
        return
    if sch is True:
        return
    types = sch.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        ok = any(isinstance(value, _TYPES[n]) and not (n in ("number", "integer") and isinstance(value, bool)) for n in names)
        if not ok:
            out.append(f"{where}: expected {' or '.join(names)}")
            return
    if "enum" in sch and not any(value == e and type(value) is type(e) for e in sch["enum"]):
        out.append(f"{where}: {value!r} is not one of {', '.join(map(str, sch['enum']))}")
    if isinstance(value, str):
        if "pattern" in sch and not re.search(sch["pattern"], value):
            out.append(f"{where}: {value!r} has the wrong form")
        if len(value) < sch.get("minLength", 0):
            out.append(f"{where}: empty")
        if "maxLength" in sch and len(value) > sch["maxLength"]:
            out.append(f"{where}: over {sch['maxLength']} characters")
        if "maxWords" in sch and len(value.split()) > sch["maxWords"]:
            out.append(f"{where}: over {sch['maxWords']} words")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in sch and value < sch["minimum"]:
            out.append(f"{where}: below {sch['minimum']}")
        if "maximum" in sch and value > sch["maximum"]:
            out.append(f"{where}: above {sch['maximum']}")
    if isinstance(value, dict):
        props = sch.get("properties", {})
        for key in sch.get("required", []):
            if key not in value:
                out.append(f"{where}: missing `{key}`")
        for key, v in value.items():
            if key in props:
                _check(v, props[key], f"{where}.{key}", out)
            elif sch.get("additionalProperties") is False:
                out.append(f"{where}: unknown field `{key}`")
    if isinstance(value, list):
        if len(value) < sch.get("minItems", 0):
            out.append(f"{where}: needs at least {sch['minItems']} item(s)")
        if "maxItems" in sch and len(value) > sch["maxItems"]:
            out.append(f"{where}: at most {sch['maxItems']} item(s)")
        if "items" in sch:
            for i, v in enumerate(value):
                _check(v, sch["items"], f"{where}[{i}]", out)
    for sub in sch.get("allOf", []):
        probe: list[str] = []
        _check(value, sub["if"], where, probe)
        if not probe:
            if "then" in sub:
                _check(value, sub["then"], where, out)
        elif "else" in sub:
            _check(value, sub["else"], where, out)


def validate(meta: dict) -> list[str]:
    """Problems with a card's front matter (an empty list when it is valid)."""
    out: list[str] = []
    # `if` clauses only test; report the stage rules on the whole card by checking it once.
    _check(meta, schema(), "card", out)
    if isinstance(meta, dict):
        dom, cid = meta.get("domain"), meta.get("id")
        if isinstance(cid, str) and isinstance(dom, str) and not cid.startswith(dom + "-"):
            out.append(f"card.id: {cid!r} must start with `{dom}-`")
        v = meta.get("verdict")
        if isinstance(v, dict):
            if v.get("result") in CLOSED and meta.get("status") in CLOSED and v["result"] != meta["status"]:
                out.append("card.verdict.result: must equal status")
            if meta.get("status") == "parked" and not v.get("trigger"):
                out.append("card.verdict: a parked card needs a dated `trigger`")
        evidence = meta.get("evidence")
        for i, ev in enumerate(evidence if isinstance(evidence, list) else []):
            if isinstance(ev, dict):
                m = ev.get("media")
                if isinstance(m, str):
                    problem = media_problem(m)
                    if problem:
                        out.append(f"card.evidence[{i}].media: {problem}")
    return out


def _in_repo(p: pathlib.Path) -> bool:
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return True
    return False


def media_problem(m: str) -> str | None:
    p = pathlib.Path(m)
    if not p.is_absolute():
        return "must be an absolute path (or null)"
    if _in_repo(p.expanduser()):
        return "must be outside any git repo"
    return None


# --- cards ---------------------------------------------------------------------------------------------

class Card:
    def __init__(self, path: pathlib.Path, meta: dict, body: str):
        self.path, self.meta, self.body = path, meta, body

    @property
    def id(self) -> str:
        return str(self.meta.get("id", self.path.stem))

    @property
    def status(self) -> str:
        return str(self.meta.get("status", ""))

    def problems(self) -> list[str]:
        out = validate(self.meta)
        if self.meta.get("id") and self.path.stem != self.meta["id"]:
            out.append(f"file name `{self.path.name}` is not `{self.meta['id']}.md`")
        if self.meta.get("domain") and self.path.parent.name != self.meta["domain"]:
            out.append(f"folder `{self.path.parent.name}` is not the domain `{self.meta['domain']}`")
        n = len(self.body.split())
        if n > MAX_BODY_WORDS:
            out.append(f"body is {n} words; the limit is {MAX_BODY_WORDS}")
        return out


def read_card(path: pathlib.Path) -> Card:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CardError(f"{path}: does not read ({e.strerror or e})") from e
    try:
        meta, body = split_card(text)
    except CardError as e:
        raise CardError(f"{path}: {e}") from e
    return Card(path, meta, body)


def card_files(base: pathlib.Path) -> list[pathlib.Path]:
    if base.is_file():
        return [base]
    d = base / "cards" if (base / "cards").is_dir() else base
    return sorted(p for p in d.rglob("*.md") if p.is_file())


def load_all(base: pathlib.Path | None = None) -> tuple[list[Card], list[str]]:
    cards, errors = [], []
    for p in card_files(base or root()):
        try:
            cards.append(read_card(p))
        except CardError as e:
            errors.append(str(e))
    return cards, errors


def find(cid: str, cards: list[Card]) -> Card:
    hits = [c for c in cards if c.id == cid] or [c for c in cards if c.id.startswith(cid)]
    if not hits:
        raise CardError(f"no card `{cid}`")
    if len(hits) > 1:
        raise CardError(f"`{cid}` matches {', '.join(c.id for c in hits[:5])}; give more of the id")
    return hits[0]


def write_card(card: Card) -> None:
    problems = validate(card.meta)
    if problems:
        raise CardError(f"{card.id}: {'; '.join(problems[:3])}")
    card.path.parent.mkdir(parents=True, exist_ok=True)
    card.path.write_text(dump_card(card.meta, card.body), encoding="utf-8")


def _date(s) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(s))
    except ValueError:
        return None


def age_days(meta: dict, on: _dt.date) -> int | None:
    d = _date(meta.get("updated") or meta.get("created"))
    return None if d is None else (on - d).days


def expiring(cards: list[Card], on: _dt.date) -> list[tuple[Card, int]]:
    out = []
    for c in cards:
        limit = EXPIRY_DAYS.get(c.status)
        a = age_days(c.meta, on)
        if limit is not None and a is not None and a > limit:
            out.append((c, a))
    return out


# --- brief ---------------------------------------------------------------------------------------------

def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP}


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def score(card: Card, product: str, surface: str, job: str) -> int:
    m = card.meta
    prob = m.get("problem") or {}
    s = 0
    if product and _norm(prob.get("product")) == _norm(product):
        s += 2
    if surface and _norm(m.get("surface")) == _norm(surface):
        s += 4
    if job and _norm(m.get("job")) == _norm(job):
        s += 3
    query = _words(surface) | _words(job)
    have = _words(f"{m.get('surface', '')} {m.get('job', '')} {m.get('mechanism', '')} {card.body}")
    s += min(len(query & have), 3)
    return s


MIN_SCORE = 3


def render_brief_card(c: Card) -> str:
    m = c.meta
    ev = ", ".join(f"{e.get('product')} {e.get('url')}" for e in (m.get("evidence") or [])[:2] if isinstance(e, dict))
    lines = [f"[{c.id}] {m.get('status')} · {m.get('domain')} · {m.get('surface')}",
             f"  job: {m.get('job')}", f"  mechanism: {m.get('mechanism')}", f"  refuse: {m.get('refuse')}"]
    prob = m.get("problem")
    if isinstance(prob, dict):
        lines.append(f"  problem ({prob.get('product')}): {prob.get('text')}")
    if m.get("line"):
        lines.append(f"  line: {m['line']}")
    lines.append(f"  evidence: {ev}")
    return "\n".join(lines)


def brief(cards: list[Card], product: str, surface: str, domain: str = "", job: str = "",
          limit: int = 5, tokens: int = 1500) -> list[Card]:
    ranked = []
    for c in cards:
        if c.status not in BRIEF_STATUSES or c.problems():
            continue
        if domain and c.meta.get("domain") != domain:
            continue
        sc = score(c, product, surface, job)
        if sc >= MIN_SCORE:
            ranked.append((-sc, c.id, c))
    ranked.sort(key=lambda t: (t[0], t[1]))
    picked, used = [], 0
    for _, _, c in ranked:
        if len(picked) >= limit:
            break
        cost = (len(render_brief_card(c)) + 3) // 4
        if used + cost > tokens:
            continue
        picked.append(c)
        used += cost
    return picked


def tokens_of(text: str) -> int:
    return (len(text) + 3) // 4


# --- commands ------------------------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def cmd_add(args) -> int:
    base = root()
    domain = args.domain
    slug = _slug(args.slug or args.job)
    cid = f"{domain}-{slug}"[:60].rstrip("-")
    if not slug:
        print("teyla playbook add: give --job or --slug", file=sys.stderr)
        return 2
    media = args.media
    ev = {"product": args.evidence_product, "url": args.evidence_url, "seen": args.seen or today().isoformat(),
          "what": args.evidence_what, "observed": True if args.observed == "true" else "unknown", "media": media}
    meta = {"id": cid, "domain": domain, "kind": args.kind, "status": "seen", "job": args.job, "surface": args.surface,
            "platform": args.platform, "mechanism": args.mechanism, "refuse": args.refuse, "evidence": [ev],
            "added_by": args.added_by, "created": today().isoformat()}
    if args.kind == "hook":
        for k in ("line", "format", "promise", "proof", "cta"):
            if getattr(args, k):
                meta[k] = getattr(args, k)
    path = cards_dir(base) / domain / f"{cid}.md"
    if path.exists():
        print(f"teyla playbook add: {path} exists", file=sys.stderr)
        return 1
    existing, _ = load_all(base)
    if any(c.id == cid for c in existing):
        print(f"teyla playbook add: id {cid} is taken", file=sys.stderr)
        return 1
    card = Card(path, meta, args.body or "")
    problems = card.problems()
    if problems:
        print("teyla playbook add: the card does not pass check:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    write_card(card)
    print(path)
    return 0


def _row(c: Card) -> dict:
    m = c.meta
    return {"id": c.id, "status": m.get("status"), "domain": m.get("domain"), "kind": m.get("kind"),
            "surface": m.get("surface"), "job": m.get("job"), "product": (m.get("problem") or {}).get("product"),
            "created": m.get("created"), "path": str(c.path)}


def cmd_list(args) -> int:
    cards, errors = load_all()
    rows = []
    for c in cards:
        m = c.meta
        if args.domain and m.get("domain") != args.domain:
            continue
        if args.status and c.status != args.status:
            continue
        if args.kind and m.get("kind") != args.kind:
            continue
        if args.product:
            names = {_norm((m.get("problem") or {}).get("product"))} | {_norm(e.get("product")) for e in m.get("evidence") or [] if isinstance(e, dict)}
            if _norm(args.product) not in names:
                continue
        rows.append(_row(c))
    if args.json:
        print(json.dumps({"cards": rows, "errors": errors}, indent=2))
        return 0
    if not rows:
        print("no cards" + (f" under {root()}" if not cards else " match"))
    for r in rows:
        print(f"{r['id']:<44} {r['status']:<12} {r['kind']:<8} {r['surface']}")
    for e in errors:
        print(f"! {e}", file=sys.stderr)
    return 0


def cmd_show(args) -> int:
    cards, _ = load_all()
    try:
        c = find(args.id, cards)
    except CardError as e:
        print(f"teyla playbook show: {e}", file=sys.stderr)
        return 1
    print(f"# {c.path}")
    print(c.path.read_text(encoding="utf-8"), end="")
    return 0


def _load_fields(path: str) -> dict:
    try:
        text = pathlib.Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise CardError(f"{path}: does not read ({e.strerror or e})") from e
    try:
        data = json.loads(text)
    except ValueError:
        data = parse_yaml(text)
    if not isinstance(data, dict):
        raise CardError(f"{path}: must hold a map of fields")
    return data


def cmd_set(args) -> int:
    cards, _ = load_all()
    try:
        c = find(args.id, cards)
        changes: dict = {}
        if args.from_file:
            changes.update(_load_fields(args.from_file))
        for a in args.assign:
            k, sep, v = a.partition("=")
            if not sep or k != "status":
                raise CardError(f"`{a}`: only status=<s> goes on the command line; the other fields go in --from FILE")
            changes["status"] = v
        for k in ("id", "created", "domain"):
            if k in changes and changes[k] != c.meta.get(k):
                raise CardError(f"`{k}` cannot change")
        old = c.status
        new = changes.get("status", old)
        if new not in STATUSES:
            raise CardError(f"status `{new}` is not one of {', '.join(STATUSES)}")
        if new != old and new not in TRANSITIONS.get(old, set()):
            allowed = ", ".join(sorted(TRANSITIONS.get(old, set()))) or "none"
            raise CardError(f"{old} -> {new} is not a step; from {old} the card can go to: {allowed}")
        meta = {**c.meta, **changes}
        meta["updated"] = today().isoformat()
        draft = Card(c.path, meta, c.body)
        problems = draft.problems()
        if problems:
            raise CardError(f"{c.id} would fail check at stage {new}: " + "; ".join(problems[:4]))
        write_card(draft)
    except CardError as e:
        print(f"teyla playbook set: {e}", file=sys.stderr)
        return 1
    print(f"{c.id}: {old}" + (f" -> {new}" if new != old else " (fields updated)"))
    return 0


def cmd_expire(args) -> int:
    cards, _ = load_all()
    on = today()
    hits = expiring(cards, on)
    if not hits:
        print("nothing to expire")
        return 0
    for c, a in hits:
        print(f"{c.id}: {c.status}, {a} days old (limit {EXPIRY_DAYS[c.status]})" + ("  -> expired" if args.apply else ""))
        if args.apply:
            c.meta["status"] = "expired"
            c.meta["updated"] = on.isoformat()
            write_card(c)
    if not args.apply:
        print(f"{len(hits)} would expire; --apply writes it")
    return 0


def cmd_brief(args) -> int:
    base = root()
    cards, _ = load_all(base) if base.exists() else ([], [])
    picked = brief(cards, args.product, args.surface, args.domain or "", args.job or "", max(1, min(args.max, 5)), args.tokens)
    text = "\n\n".join(render_brief_card(c) for c in picked)
    if args.json:
        print(json.dumps({"none_fit": not picked, "ids": [c.id for c in picked], "tokens": tokens_of(text),
                          "cards": [{**_row(c), "mechanism": c.meta.get("mechanism"), "refuse": c.meta.get("refuse"),
                                     "problem": c.meta.get("problem"), "evidence": c.meta.get("evidence")} for c in picked]}, indent=2))
        return 0
    if not picked:
        print("none fit")
        return 0
    print(text)
    print(f"\ncards: {', '.join(c.id for c in picked)} (about {tokens_of(text)} tokens)")
    return 0


def cmd_check(args) -> int:
    base = pathlib.Path(args.path).expanduser() if args.path else root()
    if not base.exists():
        print(f"teyla playbook check: {base} does not exist", file=sys.stderr)
        return 2
    cards, errors = load_all(base)
    bad = list(errors)
    seen: dict[str, pathlib.Path] = {}
    for c in cards:
        for p in c.problems():
            bad.append(f"{c.path}: {p}")
        if c.id in seen:
            bad.append(f"{c.path}: id {c.id} is also in {seen[c.id]}")
        seen.setdefault(c.id, c.path)
    for b in bad:
        print(b)
    print(f"{len(cards)} card(s), {len(bad)} problem(s)")
    return 1 if bad else 0


def cmd(args) -> int:
    return {"add": cmd_add, "list": cmd_list, "show": cmd_show, "set": cmd_set, "expire": cmd_expire,
            "brief": cmd_brief, "check": cmd_check}[args.action](args)


def register(sp):
    q = sp.add_parser("playbook", help="best-practice cards filled in stages: add, list, show, set, expire, brief, check")
    q.set_defaults(fn=cmd)
    a = q.add_subparsers(dest="action", required=True)
    p = a.add_parser("add", help="scaffold a `seen` card from flags")
    p.add_argument("--domain", required=True, choices=DOMAINS)
    p.add_argument("--kind", choices=KINDS, default="pattern")
    p.add_argument("--job", required=True, help="the user's job, at most 8 words")
    p.add_argument("--slug", help="id suffix (default: from --job)")
    p.add_argument("--surface", required=True)
    p.add_argument("--platform", choices=["ios", "android", "web", "mac", "any"], default="ios")
    p.add_argument("--mechanism", required=True, help="one transferable sentence, no brand")
    p.add_argument("--refuse", required=True, help="the skin, phrase or brand we will not copy")
    p.add_argument("--evidence-product", required=True)
    p.add_argument("--evidence-url", required=True)
    p.add_argument("--evidence-what", required=True)
    p.add_argument("--seen", help="YYYY-MM-DD (default today)")
    p.add_argument("--observed", choices=["true", "unknown"], default="true")
    p.add_argument("--media", help="absolute path outside any repo")
    p.add_argument("--added-by", choices=["owner", "claude", "codex", "grok"], default="claude")
    p.add_argument("--body", help="at most 150 words")
    for k in ("line", "format", "promise", "proof", "cta"):
        p.add_argument(f"--{k}", help=f"hook field `{k}`")
    p = a.add_parser("list", help="the cards, one line each")
    p.add_argument("--domain", choices=DOMAINS)
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--product")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--json", action="store_true")
    p = a.add_parser("show", help="print one card")
    p.add_argument("id", help="a card id or a unique prefix")
    p = a.add_parser("set", help="move a card to the next stage and add that stage's fields")
    p.add_argument("id")
    p.add_argument("assign", nargs="*", metavar="status=S")
    p.add_argument("--from", dest="from_file", metavar="FILE", help="YAML or JSON map of fields to set")
    p = a.add_parser("expire", help="seen after 90 days, candidate after 30: list, or --apply")
    p.add_argument("--apply", action="store_true")
    p = a.add_parser("brief", help="at most 5 cards for a task, or `none fit`")
    p.add_argument("--product", required=True)
    p.add_argument("--surface", required=True)
    p.add_argument("--domain", choices=DOMAINS)
    p.add_argument("--job")
    p.add_argument("--max", type=int, default=5)
    p.add_argument("--tokens", type=int, default=1500)
    p.add_argument("--json", action="store_true")
    p = a.add_parser("check", help="validate every card; exit 1 on a problem")
    p.add_argument("path", nargs="?", help="a root, a folder or a card (default: the playbook root)")
    return q
