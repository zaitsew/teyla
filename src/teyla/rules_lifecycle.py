"""Rules that are born from human corrections, counted when they are needed, and offered for
removal when they are not.

    teyla rules propose [--repo <path>] [--days 7] [--min 2] [--write]
    teyla rules stale   [--repo <path>]

The 0.12 review measured two failures. Correction capture was ~97% noise: the hook classifies
every prompt with one regex, and "no, wait" in a sentence about something else is a match. And
rules never died: a rule written once was loaded into every session forever, whether or not
anything had needed it since. This module answers both from the data already on disk.

**Human corrections only.** A correction record is *human* when a person deliberately said "this
was wrong" — not when a matcher guessed it:

    source "correct"        `teyla correct` / `/teyla:correct`: someone ran the command
    source "inbox-reject"   `teyla inbox reject --note`: someone typed why a draft was rejected
    source "hook"           the capture hook's regex guess — never human here, however it reads
    no source (pre-0.14)    the two writers differed only in key order: `teyla correct` wrote
                            {ts, text, cwd}, the hook {ts, cwd, text}; JSON keeps the order, so
                            a record whose `text` precedes its `cwd` is a `teyla correct` one

**Propose.** Human corrections in the window are matched against the repo's rule files; a match
is a *hit* (the rule exists and was not followed — sharpen it or scope it). The ones no rule
covers are clustered by shared significant words, and a cluster of `--min` or more is printed as
a new rule file, in diff form. Nothing is written without `--write`; even then the better path is
to rewrite the proposal as the constraint and run `teyla rule` — a correction's words are what
went wrong, a rule's are what to do.

**Lifecycle fields.** A rule file `teyla rule` writes carries, in its frontmatter:

    created: 2026-10-01     the day it was written
    hits: 0                 human corrections that matched it after it was written
    last_hit: never         the newest of those (an ISO timestamp — also the counting watermark)
    expires: 2026-12-30     created + 90 days, pushed to last_hit + 90 days by every hit

`hits` only moves on `--write`, and only counts corrections newer than `last_hit` (or than
`created`), so running propose any number of times never counts one correction twice. Files from
before these fields still load and match; they get `hits`/`last_hit`/`expires` on their first hit.

**Stale.** Expired rules, and rules never hit in 30 days or more, are listed as removal
candidates. Teyla never deletes a rule: whether a quiet rule is dead or is working is a
judgement the owner makes.

**Budget.** An instruction file past ~200 lines is loaded whole into every session and its rules
start to lose to each other; `teyla rule` and `teyla doctor` say so per file.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import pathlib
import re

from .rules import RULES_DIR, STOP, slug_of

TTL_DAYS = 90
NEVER_HIT_GRACE_DAYS = 30
BUDGET_LINES = 200
HUMAN_SOURCES = ("correct", "inbox-reject")
# Words a correction is phrased in, not what it is about.
CORRECTION_STOP = {"wrong", "again", "instead", "please", "should", "told", "said", "just", "only", "also",
                   "why", "what", "was", "were", "has", "have", "had", "did", "does", "but", "from", "not",
                   "never", "always", "yes", "wait", "stop", "still", "then", "there", "they", "them",
                   "не", "нет", "это", "так", "как", "что", "надо", "нужно", "опять", "снова", "уже", "тоже",
                   "для", "если", "или", "еще", "ещё", "все", "всё", "был", "была", "было", "нам", "тут"}
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


# --- what counts --------------------------------------------------------------------------

def is_human(rec: dict) -> bool:
    """See the module docstring: an explicit source decides; a pre-0.14 record without one is
    `teyla correct`'s when its `text` key comes before its `cwd` key."""
    src = rec.get("source")
    if src:
        return src in HUMAN_SOURCES
    keys = [k for k in rec if k in ("text", "cwd")]
    return keys == ["text", "cwd"]


def _ts(rec_or_s) -> _dt.datetime | None:
    s = rec_or_s.get("ts") if isinstance(rec_or_s, dict) else rec_or_s
    try:
        t = _dt.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _stem(w: str) -> str:
    """Crude on purpose: drop an English inflection, keep five characters. 'merging', 'merged'
    and 'merge' meet at 'merg'; 'мерджить' and 'мерджи' at 'мердж'. Clustering a dozen
    corrections needs nothing finer, and Teyla is stdlib-only."""
    for suf in ("ing", "ed", "es", "s", "e"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[:-len(suf)]
            break
    return w[:5]


def words(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in re.findall(r"[a-zа-яё0-9]+", (text or "").lower())
                     if len(w) >= 3 and w not in STOP and w not in CORRECTION_STOP)


def similarity(a: frozenset, b: frozenset) -> float:
    """Shared words over the shorter side's — a terse correction against a long rule still
    matches — and 0 below two shared words: one word in common is a coincidence."""
    common = len(a & b)
    if common < 2 or not a or not b:
        return 0.0
    return common / min(len(a), len(b))


MATCH = 0.5


# --- rule files ---------------------------------------------------------------------------

@dataclasses.dataclass
class Rule:
    path: pathlib.Path
    rel: str
    meta: dict
    bullets: list[str]
    created: _dt.date | None
    hits: int | None
    last_hit: _dt.datetime | None
    expires: _dt.date | None

    @property
    def tracked(self) -> bool:
        return self.hits is not None or self.expires is not None


def _date(v) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def load_rules(repo: pathlib.Path) -> list[Rule]:
    from .control.rules import _parse_frontmatter
    d = repo / RULES_DIR
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.md")):
        if f.name.upper() == "README.MD":
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        bullets = [l.strip()[2:].strip() for l in body.splitlines() if l.strip().startswith("- ")]
        bullets = bullets or [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")]
        try:
            hits = int(meta["hits"]) if "hits" in meta and not isinstance(meta["hits"], list) else None
        except ValueError:
            hits = None
        lh = meta.get("last_hit")
        out.append(Rule(f, f"{RULES_DIR}/{f.name}", meta, bullets, _date(meta.get("created")), hits,
                        _ts(lh) if isinstance(lh, str) and lh not in ("never", "") else None,
                        _date(meta.get("expires"))))
    return out


def lifecycle_fields(today: _dt.date) -> str:
    """The frontmatter lines a new rule file starts with (after `globs:`)."""
    return f"created: {today.isoformat()}\nhits: 0\nlast_hit: never\nexpires: {(today + _dt.timedelta(days=TTL_DAYS)).isoformat()}\n"


def set_fields(text: str, fields: dict) -> str:
    """`text` with each frontmatter key in `fields` replaced in place, or added before the
    closing `---`; a file without frontmatter gets one. Every other line is kept as it was."""
    m = _FRONT_RE.match(text)
    if not m:
        head = "".join(f"{k}: {v}\n" for k, v in fields.items())
        return f"---\n{head}---\n\n{text}"
    lines = m.group(1).split("\n")
    for k, v in fields.items():
        for i, l in enumerate(lines):
            if re.match(rf"^{re.escape(k)}\s*:", l):
                lines[i] = f"{k}: {v}"
                break
        else:
            lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]


def best_rule(rules: list[Rule], text: str) -> Rule | None:
    w = words(text)
    best, score = None, 0.0
    for r in rules:
        s = max((similarity(w, words(b)) for b in r.bullets), default=0.0)
        if s >= MATCH and s > score:
            best, score = r, s
    return best


# --- budget -------------------------------------------------------------------------------

def budget(repo: pathlib.Path, files: list[pathlib.Path] | None = None) -> list[tuple[str, int]]:
    """(path relative to repo, lines) for each instruction file past BUDGET_LINES. Per file, not
    per repo: each file is loaded whole, and the fix — split by scope — is per file too. A
    symlink (AGENTS.md → CLAUDE.md) is counted once, under the real file's name."""
    repo = pathlib.Path(repo)
    if files is None:
        files = [repo / "CLAUDE.md", repo / "AGENTS.md", repo / ".claude" / "CLAUDE.md"]
        d = repo / RULES_DIR
        if d.is_dir():
            files += sorted(d.glob("*.md"))
    out, seen = [], set()
    for f in files:
        try:
            real = f.resolve()
            if real in seen or not real.is_file():
                continue
            seen.add(real)
            n = len(real.read_text(errors="replace").splitlines())
        except OSError:
            continue
        if n > BUDGET_LINES:
            try:
                rel = str(real.relative_to(repo.resolve()))
            except ValueError:
                rel = str(f)
            out.append((rel, n))
    return out


def budget_lines(over: list[tuple[str, int]]) -> list[str]:
    return [f"warning: {rel} is {n} lines (budget ~{BUDGET_LINES} per instruction file) — it loads whole into "
            f"every session; split it by scope into {RULES_DIR}/<topic>.md, or drop what no correction needed"
            for rel, n in over]


# --- propose ------------------------------------------------------------------------------

def _human_records(repo: pathlib.Path) -> tuple[list[dict], int]:
    from . import corrections
    recs = corrections.records(repo)
    human = [r for r in recs if is_human(r) and str(r.get("text") or "").strip()]
    return human, len(recs) - len(human)


def cluster(recs: list[dict]) -> list[list[dict]]:
    """Greedy single-link: a record joins the first cluster holding a record it resembles."""
    out: list[list[tuple[frozenset, dict]]] = []
    for r in recs:
        w = words(r.get("text") or "")
        for c in out:
            if any(similarity(w, cw) >= MATCH for cw, _ in c):
                c.append((w, r))
                break
        else:
            out.append([(w, r)])
    return [[r for _, r in c] for c in out]


def _one_line(text: str, n: int = 200) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _effective(rule: Rule, matched: list[dict], window_start: _dt.datetime) -> dict:
    """The rule's fields after counting `matched` corrections newer than its watermark."""
    if rule.last_hit:
        floor = rule.last_hit
    elif rule.created:
        floor = _dt.datetime.combine(rule.created, _dt.time.max, tzinfo=_dt.timezone.utc)
    else:
        floor = window_start  # a pre-0.14 file: nothing says when it was written
    new = [r for r in matched if (_ts(r) or floor) > floor]
    hits = (rule.hits or 0) + len(new)
    last = max([_ts(r) for r in new] + ([rule.last_hit] if rule.last_hit else []), default=None)
    expires = rule.expires or (rule.created + _dt.timedelta(days=TTL_DAYS) if rule.created else None)
    if last:
        expires = max(filter(None, (expires, last.date() + _dt.timedelta(days=TTL_DAYS))))
    return {"new_hits": len(new), "hits": hits, "last_hit": last, "expires": expires}


def _stale_of(rule: Rule, eff: dict, today: _dt.date) -> str | None:
    if not rule.tracked and not eff["new_hits"]:
        return None
    if eff["expires"] and eff["expires"] < today:
        return f"expired {eff['expires'].isoformat()} ({eff['hits']} hit(s))"
    if eff["hits"] == 0 and rule.created and (today - rule.created).days >= NEVER_HIT_GRACE_DAYS:
        return f"never hit in {(today - rule.created).days} days"
    return None


def propose(repo, days: int = 7, min_repeats: int = 2, now: _dt.datetime | None = None) -> dict:
    """Everything the command prints, as data. Reads only; `write()` applies it."""
    repo = pathlib.Path(repo).expanduser().resolve()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    window_start = now - _dt.timedelta(days=days)
    human, automatic = _human_records(repo)
    rules = load_rules(repo)
    matched: dict[pathlib.Path, list[dict]] = {}
    loose = []
    for r in human:
        hit = best_rule(rules, r.get("text") or "")
        if hit:
            matched.setdefault(hit.path, []).append(r)
        elif (_ts(r) or now) >= window_start:
            loose.append(r)
    in_window = [r for r in human if (_ts(r) or now) >= window_start]
    new = []
    for c in cluster(loose):
        if len(c) < min_repeats:
            continue
        latest = max(c, key=lambda r: str(r.get("ts") or ""))
        text = _one_line(latest.get("text") or "")
        slug = slug_of(text)
        new.append({"text": text, "slug": slug, "rel": f"{RULES_DIR}/{slug}.md",
                    "exists": (repo / RULES_DIR / f"{slug}.md").exists(), "records": c})
    recurring, stale, untracked = [], [], []
    for rule in rules:
        m = matched.get(rule.path, [])
        eff = _effective(rule, m, window_start)
        recent = [r for r in m if (_ts(r) or now) >= window_start]
        if recent or eff["new_hits"]:
            recurring.append({"rule": rule, "recent": recent, **eff})
        why = _stale_of(rule, eff, now.date())
        if why:
            stale.append({"rule": rule, "why": why})
        if not rule.tracked and not eff["new_hits"]:
            untracked.append(rule)
    return {"repo": repo, "days": days, "human": len(in_window), "automatic": automatic, "new": new,
            "recurring": recurring, "stale": stale, "untracked": untracked, "budget": budget(repo),
            "today": now.date()}


def _new_rule_diff(p: dict, today: _dt.date) -> list[str]:
    bullet = p["text"] if p["text"].endswith((".", "!", "?", "…")) else p["text"] + "."
    if p["exists"]:
        return [f"--- {p['rel']}", f"+++ {p['rel']}  (appended)", f"+- {bullet}"]
    body = "---\nglobs: **\n" + lifecycle_fields(today) + "---\n\n" + f"- {bullet}"
    return ["--- /dev/null", f"+++ {p['rel']}"] + ["+" + l for l in body.split("\n")]


def _field_diff(rule: Rule, eff: dict) -> list[str]:
    old = {"hits": rule.meta.get("hits"), "last_hit": rule.meta.get("last_hit"), "expires": rule.meta.get("expires")}
    new = {"hits": eff["hits"], "last_hit": eff["last_hit"].isoformat() if eff["last_hit"] else "never",
           "expires": eff["expires"].isoformat() if eff["expires"] else None}
    out = [f"--- {rule.rel}", f"+++ {rule.rel}"]
    for k in ("hits", "last_hit", "expires"):
        if new[k] is None or str(old[k]) == str(new[k]):
            continue
        if old[k] not in (None, []):
            out.append(f"-{k}: {old[k]}")
        out.append(f"+{k}: {new[k]}")
    return out if len(out) > 2 else []


def render(rep: dict) -> list[str]:
    repo = rep["repo"]
    out = [f"teyla rules propose — {repo.name}, last {rep['days']} day(s): {rep['human']} human correction(s) "
           f"({rep['automatic']} automatic capture(s) ignored)"]
    for p in rep["new"]:
        ts = sorted(str(r.get("ts") or "")[:10] for r in p["records"])
        out += ["", f"new rule — {len(p['records'])} corrections no rule covers ({ts[0]}..{ts[-1]}):"]
        out += _new_rule_diff(p, rep["today"])
        out += [f"  from: \"{_one_line(r.get('text') or '', 90)}\"" for r in p["records"][-3:]]
    for r in rep["recurring"]:
        rule = r["rule"]
        out += ["", f"recurring — {rule.rel} was corrected again {len(r['recent'])} time(s) this window: "
                    "the rule exists and was not followed; sharpen it or narrow its scope"]
        out += _field_diff(rule, r) or ["  (hits already counted)"]
        out += [f"  from: \"{_one_line(x.get('text') or '', 90)}\"" for x in r["recent"][-3:]]
    if rep["stale"]:
        out += ["", "stale — removal candidates (Teyla never deletes a rule; `git rm` it if it is dead):"]
        out += [f"  {s['rule'].rel:48} {s['why']}" for s in rep["stale"]]
    if rep["untracked"]:
        out += ["", f"{len(rep['untracked'])} rule file(s) without hits/expiry (written before 0.14) — "
                    "they get them on their first hit"]
    if rep["budget"]:
        out += [""] + budget_lines(rep["budget"])
    if not (rep["new"] or rep["recurring"] or rep["stale"]):
        out += ["", "nothing to propose."]
    return out


def write(rep: dict) -> list[str]:
    """Apply a proposal: new rules through `teyla rule` (so dedupe, the invisible-character scan
    and the budget warning apply), and the hit counts into the frontmatter of matched rules."""
    from . import invisible, rules as rules_mod
    out = []
    for p in rep["new"]:
        out += rules_mod.add_rule(rep["repo"], p["text"], scope="**", today=rep["today"])
    for r in rep["recurring"]:
        if not r["new_hits"]:
            continue
        rule = r["rule"]
        fields = {"hits": r["hits"], "last_hit": r["last_hit"].isoformat()}
        if r["expires"]:
            fields["expires"] = r["expires"].isoformat()
        text = set_fields(rule.path.read_text(), fields)
        invisible.check(text, rule.rel)
        rule.path.write_text(text)
        out.append(f"{rule.rel}: hits {rule.hits or 0} → {r['hits']}")
    return out or ["nothing to write"]


def stale(repo, now: _dt.datetime | None = None) -> list[str]:
    rep = propose(repo, now=now)
    if not rep["stale"]:
        lines = [f"{rep['repo'].name}: no stale rules"]
    else:
        lines = [f"{rep['repo'].name}: {len(rep['stale'])} removal candidate(s) — Teyla never deletes a rule:"]
        lines += [f"  {s['rule'].rel:48} {s['why']}" for s in rep["stale"]]
    if rep["untracked"]:
        lines.append(f"{len(rep['untracked'])} rule file(s) without hits/expiry (written before 0.14)")
    return lines


# --- the weekly digest and doctor ---------------------------------------------------------

def _repos(root: pathlib.Path) -> list[pathlib.Path]:
    try:
        return [d for d in sorted(root.iterdir()) if (d / ".git").exists()]
    except OSError:
        return []


def digest_candidates(root: pathlib.Path | None = None, days: int = 7) -> list[dict]:
    """One digest candidate per repo under code_root with something to propose, rank 4 (with
    medium advice): a rule is worth a line in the week it is needed, not the day."""
    from . import config
    from .routines import _sh
    root = root or config.code_root(config.load())
    out = []
    for repo in _repos(root):
        if not (repo / RULES_DIR).is_dir():
            from . import corrections
            if not corrections.path_for(repo).exists():
                continue
        rep = propose(repo, days=days)
        parts = [f"{len(rep[k])} {label}" for k, label in (("new", "proposed rule(s)"), ("recurring", "recurring"),
                                                             ("stale", "stale")) if rep[k]]
        if parts:
            out.append(dict(rank=4, id=f"rules:{repo.name}", text=f"{repo.name} rules: {', '.join(parts)}",
                            step=f"teyla rules propose --repo {_sh(str(repo))}", cmd=True))
    return out


def doctor_check(root: pathlib.Path) -> dict | None:
    over = [(repo.name, rel, n) for repo in _repos(root) for rel, n in budget(repo)]
    if not over:
        return None
    names = ", ".join(f"{r}/{rel} ({n})" for r, rel, n in over[:6])
    return {"level": "WARN", "name": "repos:instr-budget",
            "detail": f"{len(over)} instruction file(s) past ~{BUDGET_LINES} lines: {names}",
            "fix": f"split each by scope into {RULES_DIR}/<topic>.md (globs:), or cut what no correction needed"}


# --- CLI ----------------------------------------------------------------------------------

def cmd_rules(args) -> int:
    repo = args.repo or "."
    if args.action == "stale":
        for line in stale(repo):
            print(line)
        return 0
    rep = propose(repo, days=args.days, min_repeats=args.min)
    for line in render(rep):
        print(line)
    if args.write:
        print()
        for line in write(rep):
            print(line)
    elif rep["new"] or any(r["new_hits"] for r in rep["recurring"]):
        print("\nnothing written. `--write` applies the diff above; better, rewrite each proposal as the "
              "constraint and run `teyla rule \"<sentence>\"`.")
    return 0


def register(sp):
    q = sp.add_parser("rules", help="rules lifecycle: propose rules from human corrections, list stale ones")
    q.set_defaults(fn=cmd_rules)
    q.add_argument("action", choices=["propose", "stale"],
                   help="propose: a diff of new/recurring rules from human corrections (writes nothing without --write); "
                        "stale: expired and never-hit rules, as removal candidates")
    q.add_argument("--repo", help="repo root (default: current directory)")
    q.add_argument("--days", type=int, default=7, help="propose: the window of corrections (default 7)")
    q.add_argument("--min", type=int, default=2, help="propose: corrections a cluster needs to become a rule (default 2)")
    q.add_argument("--write", action="store_true", help="propose: write the new rules and the hit counts")
