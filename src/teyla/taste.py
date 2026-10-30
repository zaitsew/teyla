"""`teyla taste` — the taste ledger of one product repo: decisions, rules, screens, references.

    teyla taste list [repo] [--all] [--json]          open rule proposals and confirmed rules (--all: every decision)
    teyla taste confirm <id> [--repo R] [--rule TEXT] [--scope S]   the owner's yes: set `confirmed`, write the rule file
    teyla taste render [repo] [--dry]                 regenerate "Rules from review" and "Screens" in DESIGN.md

The ledger is plain files in the product's own repo (formats and examples: docs/TASTE.md):

    design/decisions/<id>.json        one decision per captured comment: fix, rule or reject
    design/rules/<slug>.yaml          one active rule: wording, scope, example capture, date, confirmed
    design/screens/<screen>.yaml      the inventory entry: job, primary action, states, string keys
    design/references/<type>.yaml     the reference screens a screen type is judged against

Only the owner turns a proposal into a rule (decision S4): `confirm` is the one door, and `render` reads
confirmed rules only. A scope is `product`, `screen:<id>` or `component:<id>` and never widens on its own.
A rejection stays in the ledger so the next lane does not propose it again.

The YAML here is a small subset (scalars, lists, lists of maps, one nested map) read and written by
this module, because Teyla has no dependencies. Anything else is an error that names the file.
Nothing in this module touches the network.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys

from . import docs_check

MAX_DESIGN_LINES = 100
SCOPE_RE = re.compile(r"^(product|screen:[^\s]+|component:[^\s]+)$")
DECISIONS = ("fix", "rule", "reject")
RULES_MARK = ("<!-- teyla:rules -->", "<!-- /teyla:rules -->")
SCREENS_MARK = ("<!-- teyla:screens -->", "<!-- /teyla:screens -->")
RULES_HEADING = "## Rules from review"
SCREENS_HEADING = "## Screens"
MIN_PREFIX = 4


# --- the YAML subset ------------------------------------------------------------------------------

_PLAIN_OK = re.compile(r"^[A-Za-z0-9_./][A-Za-z0-9_./ -]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _scalar_out(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if (_PLAIN_OK.match(s) and s == s.strip() and s.lower() not in _RESERVED and not _NUMBER.match(s)
            and " #" not in s and not s.endswith(":") and ": " not in s):
        return s
    return json.dumps(s, ensure_ascii=False)


def _emit(value, indent: int, out: list[str]) -> None:
    pad = " " * indent
    for k, v in value.items():
        if isinstance(v, dict):
            if not v:
                out.append(f"{pad}{k}: {{}}")
            else:
                out.append(f"{pad}{k}:")
                _emit(v, indent + 2, out)
        elif isinstance(v, (list, tuple)):
            if not v:
                out.append(f"{pad}{k}: []")
                continue
            out.append(f"{pad}{k}:")
            for item in v:
                if isinstance(item, dict) and item:
                    sub: list[str] = []
                    _emit(item, indent + 4, sub)
                    out.append(f"{pad}  - {sub[0].lstrip()}")
                    out.extend(sub[1:])
                else:
                    out.append(f"{pad}  - {_scalar_out(item)}")
        else:
            out.append(f"{pad}{k}: {_scalar_out(v)}")


def dumps(data: dict) -> str:
    out: list[str] = []
    _emit(data, 0, out)
    return "\n".join(out) + "\n"


def _split_flow(inner: str) -> list[str]:
    items, cur, quote = [], "", ""
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        items.append(cur)
    return [i.strip() for i in items]


def _scalar_in(raw: str):
    raw = raw.strip()
    if raw == "":
        return None
    if raw[0] == '"':
        try:
            return json.loads(raw)
        except ValueError as e:
            raise ValueError(f"bad double-quoted string {raw[:40]!r}") from e
    if raw[0] == "'":
        if len(raw) < 2 or raw[-1] != "'":
            raise ValueError(f"bad single-quoted string {raw[:40]!r}")
        return raw[1:-1].replace("''", "'")
    if raw == "[]":
        return []
    if raw == "{}":
        return {}
    if raw[0] == "[" and raw[-1] == "]":
        return [_scalar_in(i) for i in _split_flow(raw[1:-1])]
    if raw[0] in "{|>&*!":
        raise ValueError(f"unsupported YAML value {raw[:40]!r}")
    raw = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _lines(text: str) -> list[tuple[int, str]]:
    out = []
    for raw in text.splitlines():
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError("a tab in the indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        out.append((len(raw) - len(raw.lstrip(" ")), stripped))
    return out


def _key_value(content: str) -> tuple[str, str]:
    m = re.match(r'^("(?:[^"\\]|\\.)*"|[^:#]+?)\s*:(?:\s+(.*))?$', content)
    if not m:
        raise ValueError(f"expected `key: value`, got {content[:40]!r}")
    key = m.group(1)
    if key.startswith('"'):
        key = json.loads(key)
    return key.strip(), (m.group(2) or "")


def _block(lines: list[tuple[int, str]], i: int, indent: int):
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _list(lines, i, indent)
    return _map(lines, i, indent)


def _map(lines, i: int, indent: int):
    out: dict = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError(f"unexpected indentation at {content[:40]!r}")
        if content.startswith("- "):
            break
        key, rest = _key_value(content)
        i += 1
        if rest.strip() == "":
            if i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and lines[i][1].startswith("- "))):
                out[key], i = _block(lines, i, lines[i][0])
            else:
                out[key] = None
        else:
            out[key] = _scalar_in(rest)
    return out, i


def _list(lines, i: int, indent: int):
    out: list = []
    while i < len(lines):
        ind, content = lines[i]
        if ind != indent or not (content.startswith("- ") or content == "-"):
            break
        body = content[1:].strip()
        if body == "":
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                item, i = _block(lines, i, lines[i][0])
                out.append(item)
            else:
                out.append(None)
        elif re.match(r'^("(?:[^"\\]|\\.)*"|[^\s:#"\'\[{][^:#]*?)\s*:(\s|$)', body):
            lines[i] = (indent + 2, body)          # a map item: its first key sits after the dash
            item, i = _map(lines, i, indent + 2)
            out.append(item)
        else:
            out.append(_scalar_in(body))
            i += 1
    return out, i


def loads(text: str) -> dict:
    lines = _lines(text)
    if not lines:
        return {}
    value, i = _block(lines, 0, lines[0][0])
    if i != len(lines):
        raise ValueError(f"cannot read the line {lines[i][1][:40]!r}")
    if not isinstance(value, dict):
        raise ValueError("a mapping was expected at the top level")
    return value


def load_file(path: pathlib.Path) -> dict:
    try:
        return loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{path}: {e}") from e


# --- the repo and its files -----------------------------------------------------------------------

def today() -> str:
    return _dt.date.today().isoformat()


def design_dir(repo: pathlib.Path) -> pathlib.Path:
    return repo / "design"


def resolve_repo(name: str | None, cfg: dict | None = None) -> pathlib.Path:
    """A name under code_root, a path, or (None) the git root of the current directory."""
    return docs_check.resolve([name] if name else [], False, cfg)[0]


def _write_atomic(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: pathlib.Path, obj: dict) -> None:
    _write_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def load_decisions(repo: pathlib.Path) -> list[dict]:
    """Every readable decision, newest first (date, then id). A broken file is skipped, never fatal."""
    out = []
    d = design_dir(repo) / "decisions"
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("decision") in DECISIONS:
            obj.setdefault("id", p.stem)
            out.append(obj)
    out.sort(key=lambda o: (str(o.get("date", "")), str(o.get("id", ""))), reverse=True)
    return out


def decision_path(repo: pathlib.Path, did: str) -> pathlib.Path:
    return design_dir(repo) / "decisions" / f"{did}.json"


def find_decision(repo: pathlib.Path, prefix: str) -> dict:
    """The one decision whose id starts with `prefix`. KeyError says why not."""
    prefix = prefix.strip().lower()
    if len(prefix) < MIN_PREFIX:
        raise KeyError(f"{prefix!r} is too short: give at least {MIN_PREFIX} characters of the id")
    hits = [d for d in load_decisions(repo) if str(d["id"]).lower().startswith(prefix)]
    if not hits:
        raise KeyError(f"no decision {prefix!r} in {design_dir(repo) / 'decisions'}")
    if len(hits) > 1:
        raise KeyError(f"{prefix!r} matches {len(hits)} decisions: " + ", ".join(str(h["id"])[:8] for h in hits[:6]))
    return hits[0]


def load_rules(repo: pathlib.Path) -> list[dict]:
    """Rule files, each with its `slug`. A file that does not read is skipped and named in `_errors`."""
    out = []
    d = design_dir(repo) / "rules"
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        try:
            obj = load_file(p)
        except ValueError:
            continue
        if obj.get("wording"):
            obj["slug"] = p.stem
            out.append(obj)
    return out


def load_screens(repo: pathlib.Path) -> list[dict]:
    out = []
    d = design_dir(repo) / "screens"
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        try:
            obj = load_file(p)
        except ValueError:
            continue
        obj["screen"] = p.stem
        out.append(obj)
    return out


def load_references(repo: pathlib.Path, screen_type: str | None = None) -> list[dict]:
    out = []
    d = design_dir(repo) / "references"
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        if screen_type and p.stem != screen_type:
            continue
        try:
            obj = load_file(p)
        except ValueError:
            continue
        obj["screen_type"] = p.stem
        out.append(obj)
    return out


def scope_matches(scope: str, screen: str, element: str = "") -> bool:
    """Does a rule or decision scope cover this screen and element? Never wider than it says."""
    scope = (scope or "").strip()
    if scope == "product":
        return True
    kind, _, name = scope.partition(":")
    if kind == "screen":
        return bool(screen) and screen == name
    if kind == "component":
        return bool(element) and (element == name or element.startswith(name + "."))
    return False


def rules_for(repo: pathlib.Path, screen: str, element: str = "", *, confirmed_only: bool = True) -> list[dict]:
    return [r for r in load_rules(repo)
            if (r.get("confirmed") is True or not confirmed_only) and scope_matches(str(r.get("scope", "")), screen, element)]


def rejections(repo: pathlib.Path) -> list[dict]:
    return [d for d in load_decisions(repo) if d.get("decision") == "reject"]


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(text).lower()).split())


def default_scope(screen: str, element: str) -> str:
    if element:
        return f"component:{element}"
    return f"screen:{screen}" if screen else "product"


# --- confirm --------------------------------------------------------------------------------------

def slugify(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()[:6]
    return "-".join(words)[:48].strip("-") or "rule"


def rule_file_for(repo: pathlib.Path, did: str) -> pathlib.Path | None:
    for r in load_rules(repo):
        if r.get("decision") == did:
            return design_dir(repo) / "rules" / f"{r['slug']}.yaml"
    return None


def confirm(repo: pathlib.Path, prefix: str, *, rule: str | None = None, scope: str | None = None,
            on: str | None = None) -> dict:
    """Set `confirmed` on a decision; for a rule, write or update design/rules/<slug>.yaml.
    Returns {id, decision, rule_file?, changed}. ValueError for what the owner must fix first."""
    d = find_decision(repo, prefix)
    did = str(d["id"])
    on = on or today()
    if scope is not None and not SCOPE_RE.match(scope):
        raise ValueError(f"scope {scope!r} must be `product`, `screen:<id>` or `component:<id>`")
    if (rule or scope) and d["decision"] != "rule":
        raise ValueError("--rule and --scope apply to a decision of kind rule only")
    wording = (rule or d.get("rule") or "").strip()
    if d["decision"] == "rule" and not wording:
        raise ValueError(f"decision {did[:8]} is a rule with no wording: pass --rule \"...\"")
    already = d.get("confirmed") is True
    changed = not already or bool(rule) or bool(scope)
    if d["decision"] == "rule":
        d["rule"] = wording
        if scope:
            d["scope"] = scope
        elif not SCOPE_RE.match(str(d.get("scope", ""))):
            d["scope"] = default_scope(str(d.get("screen", "")), str(d.get("element", "")))
    if not already:
        d["confirmed"] = True
        d["confirmed_on"] = on
    result = {"id": did, "decision": d["decision"], "changed": changed}
    if d["decision"] == "rule" and changed:
        path = rule_file_for(repo, did)
        if path is None:
            slug = slugify(wording)
            path = design_dir(repo) / "rules" / f"{slug}.yaml"
            if path.exists():
                path = design_dir(repo) / "rules" / f"{slug}-{did[:8]}.yaml"
        old = load_file(path) if path.exists() else {}
        _write_atomic(path, dumps({
            "wording": wording, "scope": d["scope"], "example_capture": d.get("capture", did),
            "date": old.get("date") or str(d.get("date") or on), "confirmed": True,
            "confirmed_on": old.get("confirmed_on") or on, "decision": did}))
        result["rule_file"] = str(path.relative_to(repo))
    elif d["decision"] == "rule":
        path = rule_file_for(repo, did)
        if path is not None:
            result["rule_file"] = str(path.relative_to(repo))
    if changed:
        write_json(decision_path(repo, did), d)
    return result


# --- render ---------------------------------------------------------------------------------------

def _one_line(text, n: int = 160) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def render_rules(repo: pathlib.Path) -> list[str]:
    rules = [r for r in load_rules(repo) if r.get("confirmed") is True]
    rules.sort(key=lambda r: (0 if r.get("scope") == "product" else 1, str(r.get("scope", "")), str(r.get("date", ""))))
    lines = []
    if not rules:
        lines.append("None confirmed yet.")
    for r in rules:
        lines.append(f"- `{r.get('scope', 'product')}` {_one_line(r['wording'])} ({r.get('date', '')})")
    return lines


def render_screens(repo: pathlib.Path) -> list[str]:
    lines = []
    screens = load_screens(repo)
    if not screens:
        lines.append("None recorded yet.")
    for s in screens:
        bits = [f"**{s['screen']}**"]
        if s.get("job"):
            bits.append(_one_line(s["job"], 100).rstrip("."))
        line = " — ".join(bits)
        if s.get("primary_action"):
            line += f". Primary: {_one_line(s['primary_action'], 60).rstrip('.')}"
        states = s.get("states")
        if isinstance(states, list) and states:
            line += ". States: " + ", ".join(str(x) for x in states)
        keys = s.get("string_keys")
        if isinstance(keys, list) and keys:
            line += f". {len(keys)} string key{'s' if len(keys) != 1 else ''}"
        lines.append("- " + line.rstrip(".") + ".")
    return lines


def design_doc(repo: pathlib.Path) -> pathlib.Path | None:
    for rel in ("DESIGN.md", "docs/DESIGN.md"):
        if (repo / rel).is_file():
            return repo / rel
    return None


def _replace_block(text: str, marks: tuple[str, str], body: list[str]) -> tuple[str, bool]:
    """Put `body` between the marks. (new text, found). Not found: the text is returned unchanged."""
    start, end = marks
    a = text.find(start)
    b = text.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        return text, False
    return text[:a] + start + "\n" + "\n".join(body) + "\n" + text[b:], True


def render_design(repo: pathlib.Path) -> dict:
    """{path, text, lines, parts, appended}: the DESIGN.md as it would be. Writes nothing.
    A missing marker pair is appended at the end of the file (with its heading), never inserted
    in the middle of text the owner wrote."""
    path = design_doc(repo) or repo / "DESIGN.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    parts = {"rules": render_rules(repo), "screens": render_screens(repo)}
    appended = []
    for name, marks in (("rules", RULES_MARK), ("screens", SCREENS_MARK)):
        text, found = _replace_block(text, marks, parts[name])
        if not found:
            heading = RULES_HEADING if name == "rules" else SCREENS_HEADING
            text = (text.rstrip("\n") + ("\n\n" if text.strip() else "") + heading + "\n\n"
                    + marks[0] + "\n" + "\n".join(parts[name]) + "\n" + marks[1] + "\n")
            appended.append(name)
    if not text.endswith("\n"):
        text += "\n"
    return {"path": path, "text": text, "lines": text.count("\n"), "parts": parts, "appended": appended}


def trim_advice(repo: pathlib.Path, rendered: dict, limit: int = MAX_DESIGN_LINES) -> list[str]:
    """What to cut so the file fits: the sizes, then the oldest rules."""
    gen = len(rendered["parts"]["rules"]) + len(rendered["parts"]["screens"]) + 4
    hand = max(rendered["lines"] - gen, 0)
    out = [f"{rendered['path'].name} would be {rendered['lines']} lines; the limit is {limit} (over by {rendered['lines'] - limit}).",
           f"  generated: rules {len(rendered['parts']['rules'])}, screens {len(rendered['parts']['screens'])} lines; "
           f"the rest of the file: {hand} lines."]
    if hand > limit - 6:
        out.append("  Trim the hand-written part first: move history to docs/decisions/ and long tables to code comments.")
    rules = sorted((r for r in load_rules(repo) if r.get("confirmed") is True), key=lambda r: str(r.get("date", "")))
    if rules:
        out.append("  Oldest rules (retire one by deleting its file in design/rules/, or narrow its scope):")
        out += [f"    {r['slug']}  {r.get('scope', '')}  {r.get('date', '')}" for r in rules[:5]]
    return out


def render(repo: pathlib.Path, *, dry: bool = False) -> tuple[int, list[str]]:
    r = render_design(repo)
    if r["lines"] > MAX_DESIGN_LINES:
        return 1, trim_advice(repo, r) + ["Nothing was written."]
    msgs = [f"{r['path'].relative_to(repo)}: {r['lines']} lines "
            f"({len(r['parts']['rules'])} rule line(s), {len(r['parts']['screens'])} screen line(s))"]
    if r["appended"]:
        msgs.append("no marker pair for " + " and ".join(r["appended"]) + ": appended at the end of the file")
    if dry:
        return 0, msgs + ["dry run: nothing written"]
    old = r["path"].read_text(encoding="utf-8") if r["path"].is_file() else None
    if old == r["text"]:
        return 0, msgs + ["already up to date"]
    _write_atomic(r["path"], r["text"])
    return 0, msgs + ["written"]


# --- list -----------------------------------------------------------------------------------------

def list_rows(repo: pathlib.Path, show_all: bool = False) -> list[dict]:
    rows = []
    for d in load_decisions(repo):
        confirmed = d.get("confirmed") is True
        if not show_all and not (d["decision"] == "rule"):
            continue
        rows.append({"id": d["id"], "date": d.get("date", ""), "decision": d["decision"], "confirmed": confirmed,
                     "scope": d.get("scope", ""), "screen": d.get("screen", ""),
                     "text": d.get("rule") or d.get("comment") or ""})
    return rows


def render_list(repo: pathlib.Path, rows: list[dict]) -> str:
    if not rows:
        return f"{repo.name}: no rule proposals yet (teyla review triage <id> writes them)"
    open_ = [r for r in rows if not r["confirmed"] and r["decision"] == "rule"]
    out = [f"{repo.name}: {len(open_)} open rule proposal(s)"]
    for r in rows:
        state = "confirmed" if r["confirmed"] else ("open" if r["decision"] == "rule" else "pending")
        out.append(f"  {str(r['id'])[:8]}  {r['decision']:<6} {state:<9} {r['scope'] or '-':<28} {_one_line(r['text'], 70)}")
    if open_:
        out.append("confirm one with: teyla taste confirm <id>")
    return "\n".join(out)


# --- the command ----------------------------------------------------------------------------------

def cmd_taste(args) -> int:
    action = args.action
    words = list(getattr(args, "words", []) or [])
    try:
        if action == "confirm":
            if len(words) != 1:
                print("teyla taste confirm: give one decision id (a prefix of at least 4 characters)", file=sys.stderr)
                return 2
            repo = resolve_repo(args.repo)
            try:
                res = confirm(repo, words[0], rule=args.rule, scope=args.scope)
            except (KeyError, ValueError) as e:
                print(f"teyla taste confirm: {e.args[0] if isinstance(e, KeyError) else e}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(res, indent=1))
                return 0
            what = "already confirmed" if not res["changed"] else "confirmed"
            line = f"{what} {res['id'][:8]} ({res['decision']})"
            if res.get("rule_file"):
                line += f": {res['rule_file']}"
            print(line)
            if res["decision"] == "rule" and res["changed"]:
                print(f"next: teyla taste render {repo.name}")
            return 0
        if len(words) > 1:
            print(f"teyla taste {action}: give at most one repo", file=sys.stderr)
            return 2
        repo = resolve_repo(words[0] if words else args.repo)
        if action == "render":
            code, msgs = render(repo, dry=args.dry)
            print("\n".join(msgs), file=sys.stderr if code else sys.stdout)
            return code
        rows = list_rows(repo, args.all)                       # list
        print(json.dumps({"repo": repo.name, "decisions": rows}, indent=1) if args.json else render_list(repo, rows))
        return 0
    except FileNotFoundError as e:
        print(f"teyla taste {action}: {e}", file=sys.stderr)
        return 2


def register(sp):
    q = sp.add_parser("taste", help="a product's taste ledger: rule proposals, confirm one, render DESIGN.md from the files")
    q.set_defaults(fn=cmd_taste)
    q.add_argument("action", nargs="?", choices=["list", "confirm", "render"], default="list")
    q.add_argument("words", nargs="*", metavar="[repo | decision-id]")
    q.add_argument("--repo", help="confirm: the product repo (name under code_root or a path; default: the current git root)")
    q.add_argument("--all", action="store_true", help="list: every decision, not only rule proposals")
    q.add_argument("--rule", help="confirm: the rule wording, replacing the proposed one")
    q.add_argument("--scope", help="confirm: product, screen:<id> or component:<id>")
    q.add_argument("--dry", action="store_true", help="render: show the result, write nothing")
    q.add_argument("--json", action="store_true")
    return q
