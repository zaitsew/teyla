"""`teyla design`: the design cycle as files and a command (templates/design/CYCLE.md).

A product keeps its redesign under `design/decisions/`:

    map.yaml                  ordered decisions: id, title, journey, needs, status
    <id>/dossier.md           five parts, each item labelled guideline | observation | hypothesis
    <id>/options.yaml         two or three options, the first recommended, with a one-line why
    <id>/pick.yaml            the owner's pick: option or none, his sentence verbatim, date, scope

Every gate is a function that returns a list of problems; the command prints the first and exits 1.
`pick` writes the record, sets the map status and opens a taste rule proposal (a file the owner
confirms with `teyla taste confirm`; nothing here ever confirms). `options` also registers a card in
`~/.teyla/design-cards.json`, which `teyla asks` shows first and `teyla answer` turns into a pick.
Nothing here leaves the machine.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import uuid

from . import taste
from .control import state

STATUSES = ("open", "researching", "options", "picked", "built")
DONE = ("picked", "built")
SCOPES = ("screen", "product", "all")
LABELS = ("guideline", "observation", "hypothesis")
MAX_OPTIONS = 3
MIN_OPTIONS = 2
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
OPTION_FIELDS = ("summary", "user_does", "removes_or_moves", "evidence", "cost")
PARTS = (
    "Owner's words and earlier picks",
    "Usage",
    "Guidelines",
    "How other products solve it",
    "Practitioner reports",
)
LABELLED_PARTS = PARTS[1:]
NONE = "none"
CARD_HARNESS = "teyla-design"
_ITEM = re.compile(r"^\s*[-*]\s*\[?(guideline|observation|hypothesis)\]?\s*[:—-]?\s+\S", re.I)
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")


class DesignError(Exception):
    """A gate refused. The message is the one line printed."""


# --- paths ----------------------------------------------------------------------------------------

def root(repo: pathlib.Path) -> pathlib.Path:
    return taste.design_dir(repo) / "decisions"


def map_path(repo: pathlib.Path) -> pathlib.Path:
    return root(repo) / "map.yaml"


def folder(repo: pathlib.Path, did: str) -> pathlib.Path:
    return root(repo) / did


# --- the map --------------------------------------------------------------------------------------

def load_map(repo: pathlib.Path) -> list[dict]:
    p = map_path(repo)
    if not p.is_file():
        raise DesignError(f"no map: run `teyla design map {repo.name}` to scaffold {_rel(repo, p)}")
    try:
        data = taste.load_file(p)
    except ValueError as e:
        raise DesignError(str(e)) from e
    rows = data.get("decisions")
    if not isinstance(rows, list) or not rows:
        raise DesignError(f"{_rel(repo, p)}: `decisions` must be a non-empty list")
    return [dict(r) if isinstance(r, dict) else {"id": r} for r in rows]


def save_map(repo: pathlib.Path, rows: list[dict]) -> None:
    ordered = [{k: r[k] for k in ("id", "title", "journey", "needs", "status") if k in r} for r in rows]
    taste._write_atomic(map_path(repo), taste.dumps({"decisions": ordered}))


def map_problems(rows: list[dict]) -> list[str]:
    """Unknown or self `needs`, duplicate ids, bad status, a cycle. Empty when the map is sound."""
    out: list[str] = []
    ids: list[str] = []
    for i, r in enumerate(rows, 1):
        did = str(r.get("id", ""))
        if not ID_RE.match(did):
            out.append(f"decision {i}: id {did!r} must be lowercase letters, digits and dashes")
            continue
        if did in ids:
            out.append(f"decision {did}: duplicate id")
        ids.append(did)
        for f in ("title", "journey"):
            if not str(r.get(f) or "").strip():
                out.append(f"decision {did}: `{f}` is empty")
        if r.get("status") not in STATUSES:
            out.append(f"decision {did}: status {r.get('status')!r} must be one of {', '.join(STATUSES)}")
        if not isinstance(r.get("needs", []), list):
            out.append(f"decision {did}: `needs` must be a list of ids")
    if out:
        return out
    known = set(ids)
    for r in rows:
        for n in r.get("needs") or []:
            if n == r["id"]:
                out.append(f"decision {r['id']}: needs itself")
            elif n not in known:
                out.append(f"decision {r['id']}: needs unknown decision {n!r}")
    if out:
        return out
    # a cycle: Kahn's algorithm leaves the members of one behind
    left = {r["id"]: set(r.get("needs") or []) for r in rows}
    while True:
        free = [k for k, v in left.items() if not v]
        if not free:
            break
        for k in free:
            del left[k]
        for v in left.values():
            v.difference_update(free)
    if left:
        out.append("cycle in `needs` among: " + ", ".join(sorted(left)))
    return out


def valid_map(repo: pathlib.Path) -> list[dict]:
    rows = load_map(repo)
    bad = map_problems(rows)
    if bad:
        raise DesignError(f"{_rel(repo, map_path(repo))}: {bad[0]}" + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""))
    return rows


def row(rows: list[dict], did: str) -> dict:
    for r in rows:
        if r["id"] == did:
            return r
    raise DesignError(f"no decision {did!r} in the map: " + ", ".join(r["id"] for r in rows))


def needs_met(rows: list[dict], r: dict) -> list[str]:
    """The `needs` of `r` that are not picked or built yet."""
    by = {x["id"]: x for x in rows}
    return [n for n in r.get("needs") or [] if by[n]["status"] not in DONE]


def next_decision(rows: list[dict]) -> dict | None:
    for r in rows:
        if r["status"] not in DONE and not needs_met(rows, r):
            return r
    return None


def scaffold_map(repo: pathlib.Path) -> list[str]:
    p = map_path(repo)
    if p.exists():
        rows = valid_map(repo)
        return [f"{_rel(repo, p)}: valid, {len(rows)} decision(s)"]
    taste._write_atomic(p, taste.dumps({"decisions": [{
        "id": "jobs", "title": "What the product is for", "journey": "the first day of a new user",
        "needs": [], "status": "open"}]}))
    return [f"wrote {_rel(repo, p)}: edit it to the product's decisions, in dependency order",
            "each decision: id, title, journey, needs: [ids], status: open | researching | options | picked | built",
            f"then: teyla design dossier {repo.name} <id>"]


# --- the dossier ----------------------------------------------------------------------------------

DOSSIER_TEMPLATE = """# Dossier: {title}

Journey: {journey}

Fill each part. Parts 2 to 5 take one item per line, labelled `guideline`, `observation` or
`hypothesis`, for example `- guideline: five or fewer tabs by default (source, link)`.
A popular app or a post is never evidence by itself.

## {p1}

<!-- The owner's own sentences on this subject (`teyla intent`) and his earlier picks (`teyla taste`). -->

## {p2}

<!-- Which screens and actions people open, time per job, dead ends. With no data, say so: `- observation: no usage data yet`. -->

## {p3}

<!-- Apple HIG first, then NN/g and Material where they add a number. -->

## {p4}

<!-- 6 to 10 products: the closest competitors and the apps he uses daily. A link and the one pattern worth taking. -->

## {p5}

<!-- What practitioners report (X, blogs). Mark each item verified or not. -->
"""


def dossier_sections(text: str) -> dict[str, list[str]]:
    """Heading -> its lines, for the five known parts (HTML comments dropped)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1) if m.group(1) in PARTS else None
            if cur:
                out[cur] = []
            continue
        if cur is not None:
            out[cur].append(line)
    return out


def dossier_problems(text: str) -> list[str]:
    secs = dossier_sections(text)
    out = []
    for part in PARTS:
        lines = secs.get(part)
        if lines is None:
            out.append(f"the dossier lacks the part \"{part}\"")
        elif part in LABELLED_PARTS:
            items = [l for l in lines if _BULLET.match(l)]
            if not items:
                out.append(f"the dossier part \"{part}\" has no items")
            elif any(not _ITEM.match(l) for l in items):
                out.append(f"the dossier part \"{part}\" has an item with no label (guideline | observation | hypothesis)")
        elif not any(l.strip() for l in lines):
            out.append(f"the dossier part \"{part}\" is empty")
    return out


def scaffold_dossier(repo: pathlib.Path, did: str) -> list[str]:
    rows = valid_map(repo)
    r = row(rows, did)
    p = folder(repo, did) / "dossier.md"
    if p.exists():
        bad = dossier_problems(p.read_text(encoding="utf-8"))
        return [f"{_rel(repo, p)}: " + ("complete" if not bad else bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""))]
    taste._write_atomic(p, DOSSIER_TEMPLATE.format(
        title=r["title"], journey=r["journey"], p1=PARTS[0], p2=PARTS[1], p3=PARTS[2], p4=PARTS[3], p5=PARTS[4]))
    if r["status"] == "open":
        r["status"] = "researching"
        save_map(repo, rows)
    return [f"wrote {_rel(repo, p)} with the five parts", f"then: teyla design options {repo.name} {did}"]


# --- the options ----------------------------------------------------------------------------------

def options_problems(data: dict) -> list[str]:
    opts = data.get("options")
    if not isinstance(opts, list):
        return ["options.yaml needs an `options` list"]
    if len(opts) > MAX_OPTIONS:
        return [f"{len(opts)} options: at most {MAX_OPTIONS}"]
    if len(opts) < MIN_OPTIONS:
        return [f"{len(opts)} option(s): at least {MIN_OPTIONS}"]
    out = []
    first = opts[0] if isinstance(opts[0], dict) else {}
    if first.get("recommended") is not True:
        out.append("the first option must be the recommended one (`recommended: true`)")
    if not str(first.get("why") or "").strip():
        out.append("the first option needs a one-line `why`")
    seen = set()
    for i, o in enumerate(opts, 1):
        if not isinstance(o, dict):
            out.append(f"option {i} is not a mapping")
            continue
        if not isinstance(o.get("id"), str):
            out.append(f"option {i}: id must be a quoted string, not {o.get('id')!r}")
            continue
        oid = o["id"]
        if not ID_RE.match(oid) or oid == NONE:
            out.append(f"option {i}: id {oid!r} must be lowercase letters, digits and dashes, and not `none`")
        elif oid in seen:
            out.append(f"option {i}: duplicate id {oid!r}")
        seen.add(oid)
        if i > 1 and o.get("recommended") is True:
            out.append(f"option {oid}: only the first option is recommended")
        for f in OPTION_FIELDS:
            if not str(o.get(f) or "").strip():
                out.append(f"option {oid or i}: `{f}` is empty")
    return out


def options_template(rows: list[dict], r: dict) -> dict:
    def opt(oid, rec):
        d = {"id": oid, "summary": "", "user_does": "", "removes_or_moves": "", "evidence": "", "cost": ""}
        if rec:
            d = {"id": oid, "recommended": True, "why": "", **{k: v for k, v in d.items() if k != "id"}}
        return d
    return {"options": [opt("a", True), opt("b", False)]}


def load_options(repo: pathlib.Path, did: str) -> dict:
    p = folder(repo, did) / "options.yaml"
    if not p.is_file():
        raise DesignError(f"no options for {did}: run `teyla design options {repo.name} {did}`")
    try:
        return taste.load_file(p)
    except ValueError as e:
        raise DesignError(str(e)) from e


def check_options(repo: pathlib.Path, did: str) -> dict:
    """The dossier gate, then the options gate. DesignError with one line on the first failure."""
    dp = folder(repo, did) / "dossier.md"
    if not dp.is_file():
        raise DesignError(f"no dossier for {did}: run `teyla design dossier {repo.name} {did}`")
    bad = dossier_problems(dp.read_text(encoding="utf-8"))
    if bad:
        raise DesignError(bad[0])
    data = load_options(repo, did)
    bad = options_problems(data)
    if bad:
        raise DesignError(bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""))
    return data


def do_options(repo: pathlib.Path, did: str) -> list[str]:
    rows = valid_map(repo)
    r = row(rows, did)
    p = folder(repo, did) / "options.yaml"
    if not p.exists():
        dp = folder(repo, did) / "dossier.md"
        if not dp.is_file():
            raise DesignError(f"no dossier for {did}: run `teyla design dossier {repo.name} {did}`")
        bad = dossier_problems(dp.read_text(encoding="utf-8"))
        if bad:
            raise DesignError(bad[0])
        taste._write_atomic(p, taste.dumps(options_template(rows, r)))
        return [f"wrote {_rel(repo, p)}: fill it (two or three options, the recommended one first), then run this again"]
    data = check_options(repo, did)
    if (folder(repo, did) / "pick.yaml").exists() and r["status"] in DONE:
        return [f"{did} is already {r['status']}; options are closed (`teyla design pick --supersede` replaces the pick)"]
    r["status"] = "options"
    save_map(repo, rows)
    register_card(repo, rows, r, data)
    return [f"{did}: {len(data['options'])} options valid, status options",
            "the card is in `teyla asks`; the owner answers with `teyla answer <id> <option> <his words>`"]


# --- the pick -------------------------------------------------------------------------------------

def load_pick(repo: pathlib.Path, did: str) -> dict | None:
    p = folder(repo, did) / "pick.yaml"
    if not p.is_file():
        return None
    try:
        return taste.load_file(p)
    except ValueError:
        return None


def rule_wording(r: dict, option: dict | None) -> str:
    if option is None:
        return f"{r['title']}: keep the current behaviour."
    return f"{r['title']}: {str(option['summary']).strip()}"


def open_proposal(repo: pathlib.Path, r: dict, option: dict | None, scope: str, sentence: str, on: str) -> str:
    """A rule proposal in the taste ledger, `confirmed: false`. The owner confirms it with `teyla taste confirm`."""
    did = str(uuid.uuid4())
    rec = {"id": did, "date": on, "screen": r["id"], "element": "", "comment": sentence, "decision": "rule",
           "reason": "Picked in the design cycle.", "scope": f"screen:{r['id']}" if scope == "screen" else "product",
           "rule": rule_wording(r, option), "capture": did, "pr": "", "confirmed": False,
           "source": "design-cycle"}
    if scope == "all":
        rec["reach"] = "all-products"
    taste.write_json(taste.decision_path(repo, did), rec)
    return did


def do_pick(repo: pathlib.Path, did: str, choice: str, sentence: str, scope: str = "screen",
            supersede: bool = False, on: str | None = None) -> dict:
    rows = valid_map(repo)
    r = row(rows, did)
    sentence = (sentence or "").strip()
    if not sentence:
        raise DesignError("a pick needs the owner's words: pass --sentence \"...\"")
    if scope not in SCOPES:
        raise DesignError(f"scope {scope!r} must be one of {', '.join(SCOPES)}")
    if not (folder(repo, did) / "options.yaml").is_file():
        raise DesignError(f"no options for {did}: run `teyla design options {repo.name} {did}` first")
    data = check_options(repo, did)
    waiting = needs_met(rows, r)
    if waiting:
        raise DesignError(f"{did} needs {', '.join(waiting)}, which is not picked yet")
    by = {o["id"]: o for o in data["options"]}
    choice = choice.strip().lower()
    if choice != NONE and choice not in by:
        raise DesignError(f"no option {choice!r} for {did}: " + ", ".join([*by, NONE]))
    old = load_pick(repo, did)
    if old is None and (folder(repo, did) / "pick.yaml").is_file() and not supersede:
        raise DesignError(f"{did}/pick.yaml exists but cannot be read; fix it, or pass --supersede to replace it")
    if old is not None and not supersede:
        raise DesignError(f"{did} already has a pick ({old.get('option')}); pass --supersede to replace it")
    on = on or taste.today()
    rec: dict = {"option": choice, "sentence": sentence, "date": on, "scope": scope}
    if old is not None:
        rec["supersedes"] = {"option": old.get("option"), "date": old.get("date")}
    taste._write_atomic(folder(repo, did) / "pick.yaml", taste.dumps(rec))
    r["status"] = "picked"
    save_map(repo, rows)
    drop_card(repo, did)
    proposal = open_proposal(repo, r, by.get(choice), scope, sentence, on)
    return {"id": did, "option": choice, "scope": scope, "proposal": proposal,
            "superseded": old is not None}


def do_built(repo: pathlib.Path, did: str) -> str:
    rows = valid_map(repo)
    r = row(rows, did)
    pick = load_pick(repo, did)
    if r["status"] not in DONE or pick is None:
        raise DesignError(f"{did} is not picked: nothing to build (`teyla design pick {repo.name} {did} <option>`)")
    if pick.get("option") == NONE:
        raise DesignError(f"{did} was picked as none: nothing to build")
    r["status"] = "built"
    save_map(repo, rows)
    return f"{did}: built"


# --- status ---------------------------------------------------------------------------------------

def render_status(repo: pathlib.Path, rows: list[dict]) -> str:
    nxt = next_decision(rows)
    out = [f"{repo.name}: {len(rows)} decision(s), {sum(1 for r in rows if r['status'] in DONE)} picked or built"]
    for i, r in enumerate(rows, 1):
        mark = "next " if nxt is r else "     "
        pick = load_pick(repo, r["id"]) if r["status"] in DONE else None
        tail = f"  -> {pick.get('option')}" if pick else ""
        needs = f"  needs {', '.join(r.get('needs') or [])}" if r.get("needs") else ""
        out.append(f"  {i:>2}. {mark}{r['id']:<20} {r['status']:<11}{tail}{needs}  {r['title']}")
    return "\n".join(out)


# --- the card in `teyla asks` ---------------------------------------------------------------------

def cards_path() -> pathlib.Path:
    return state.home() / "design-cards.json"


def _read_cards() -> dict:
    try:
        d = json.loads(cards_path().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_cards(cards: dict) -> None:
    taste._write_atomic(cards_path(), json.dumps(cards, indent=1, sort_keys=True) + "\n")


def register_card(repo: pathlib.Path, rows: list[dict], r: dict, data: dict) -> None:
    cards = _read_cards()
    cards[f"{repo}::{r['id']}"] = {"repo": str(repo), "decision": r["id"], "product": repo.name}
    _write_cards(cards)


def drop_card(repo: pathlib.Path, did: str) -> None:
    cards = _read_cards()
    if cards.pop(f"{repo}::{did}", None) is not None:
        _write_cards(cards)


def open_cards() -> list[dict]:
    """Registered cards that are still open: status options, valid options, no pick. A stale entry is skipped."""
    out = []
    for c in _read_cards().values():
        try:
            repo = pathlib.Path(c["repo"])
            rows = valid_map(repo)
            r = row(rows, c["decision"])
            if r["status"] != "options" or load_pick(repo, r["id"]) is not None:
                continue
            data = check_options(repo, r["id"])
        except (DesignError, KeyError, OSError):
            continue
        locked = [x["id"] for x in rows if x["status"] in DONE]
        out.append({"repo": repo, "product": repo.name, "decision": r["id"], "title": r["title"],
                    "journey": r["journey"], "options": data["options"], "locked": locked,
                    "waiting": needs_met(rows, r)})
    return out


def card_text(c: dict) -> str:
    lines = [f"{c['title']} (journey: {c['journey']}). "
             + (f"Locked: {', '.join(c['locked'])}." if c["locked"] else "Nothing locked yet.")]
    for o in c["options"]:
        lines.append(f"{o['id']}{' (recommended)' if o.get('recommended') else ''}: {str(o['summary']).strip()}")
    lines.append("Answer with an option id (or none) and your reason.")
    return "\n".join(lines)


def card_chips(c: dict) -> list[str]:
    return [o["id"] + (" (recommended)" if o.get("recommended") else "") for o in c["options"]] + [NONE]


def parse_answer(c: dict, text: str) -> tuple[str, str]:
    """(option id or none, the owner's sentence). The first word names the option; a chip's
    "(recommended)" is ignored. DesignError when it names none."""
    t = text.strip()
    first = re.split(r"\s+", t, maxsplit=1)[0].strip(".,:;").lower() if t else ""
    ids = [o["id"] for o in c["options"]]
    if first not in ids and first != NONE:
        raise DesignError(f"start the answer with one of: {', '.join([*ids, NONE])}")
    rest = re.sub(r"^\S+\s*(\(recommended\))?\s*", "", t, flags=re.I).strip()
    return first, (rest or t)


def answer_card(card_ref: str, text: str) -> dict:
    """`teyla answer` on a design card: the same pick code as `teyla design pick`. `card_ref` is `repo::decision`."""
    repo_s, _, did = card_ref.partition("::")
    repo = pathlib.Path(repo_s)
    for c in open_cards():
        if c["repo"] == repo and c["decision"] == did:
            choice, sentence = parse_answer(c, text)
            return do_pick(repo, did, choice, sentence)
    raise DesignError("this card is closed or its files changed: run `teyla asks` again")


# --- the command ----------------------------------------------------------------------------------

def _rel(repo: pathlib.Path, p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(repo))
    except ValueError:
        return str(p)


ACTIONS = ("map", "next", "dossier", "options", "pick", "status", "built")
NEEDS_ID = ("dossier", "options", "pick", "built")


def cmd_design(args) -> int:
    action = args.action
    words = list(args.words or [])
    want = 1 + (1 if action in NEEDS_ID else 0) + (1 if action == "pick" else 0)
    if len(words) != want:
        shape = {"pick": "<product> <id> <option|none> --sentence \"...\"", "dossier": "<product> <id>",
                 "options": "<product> <id>", "built": "<product> <id>"}.get(action, "<product>")
        print(f"usage: teyla design {action} {shape}", file=sys.stderr)
        return 64
    try:
        repo = taste.resolve_repo(words[0])
    except FileNotFoundError as e:
        print(f"teyla design {action}: {e}", file=sys.stderr)
        return 2
    try:
        if action == "map":
            lines = scaffold_map(repo)
        elif action == "status":
            lines = [render_status(repo, valid_map(repo))]
        elif action == "next":
            rows = valid_map(repo)
            n = next_decision(rows)
            if n is None:
                lines = ["nothing is waiting: every decision is picked or built"]
            else:
                lines = [f"{n['id']}: {n['title']} ({n['status']})",
                         f"journey: {n['journey']}",
                         {"open": f"next: teyla design dossier {repo.name} {n['id']}",
                          "researching": f"next: fill the dossier, then teyla design options {repo.name} {n['id']}",
                          "options": f"next: the owner picks (teyla asks)"}[n["status"]]]
        elif action == "dossier":
            lines = scaffold_dossier(repo, words[1])
        elif action == "options":
            lines = do_options(repo, words[1])
        elif action == "built":
            lines = [do_built(repo, words[1])]
        else:
            res = do_pick(repo, words[1], words[2], args.sentence or "", args.scope, args.supersede)
            lines = [f"{res['id']}: picked {res['option']} (scope {res['scope']})"
                     + (", replacing the earlier pick" if res["superseded"] else ""),
                     f"rule proposal {res['proposal'][:8]}: the owner confirms it with `teyla taste confirm {res['proposal'][:8]} --repo {repo.name}`"]
    except DesignError as e:
        print(f"teyla design {action}: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def register(sp):
    q = sp.add_parser("design", help="the design cycle: decision map, dossier, options, the owner's pick, build")
    q.set_defaults(fn=cmd_design)
    q.add_argument("action", choices=ACTIONS)
    q.add_argument("words", nargs="*", metavar="product [decision-id] [option]")
    q.add_argument("--sentence", help="pick: the owner's words, verbatim")
    q.add_argument("--scope", choices=SCOPES, default="screen", help="pick: how far the rule reaches (default screen)")
    q.add_argument("--supersede", action="store_true", help="pick: replace an existing pick and record it")
    return q
