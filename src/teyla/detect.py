"""Policy detectors: the rules in POLICY.md a machine can check, checked.

A rule written down and never measured is followed until the first busy week. In September
2026 the no-Actions rule (POLICY §10) was broken three times by agents — workflow files
created in `accounts` twice on 09-11 and in `loco` on 09-20 — and nothing noticed until the
Actions quota hit 100% on 09-23; afterwards nine checkouts under ~/repos still declared
push / pull_request / schedule triggers. The rule was in every harness's context the whole
time. What was missing was a detector.

Which detectors run is declared by the policy itself, so a user whose POLICY.md does not
carry a rule is never nagged about it:

    <!-- teyla:detect no-actions -->        anywhere in ~/.agents/POLICY.md

switches the detector `no-actions` on. A few rules are also recognised by their wording,
so a policy written before the markers existed works unchanged (IMPLICIT below). An id
that names no built-in detector is reported by `teyla doctor`, not silently ignored.

Built-in detectors (DETECTORS):

- `no-actions` — every `.github/workflows/*.yml|yaml` in each git repo under `code_root`
  and `ops_root`, in the working tree and on the default branch (`origin/HEAD`), whose
  `on:` names push, pull_request, pull_request_target or schedule. `teyla doctor` WARNs
  per repo with the file and the fix; `teyla monitor`/`advise` raise A16.
- `ask-permission` — turns that ended with the agent asking permission to do the obvious
  next step ("Want me to push them?") and the human answering only "yes". Measured from
  Claude Code and Codex transcripts; `teyla monitor`/`advise` raise A15.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import re
import subprocess

from . import config

MARKER_RE = re.compile(r"<!--\s*teyla:detect\s+([A-Za-z0-9][A-Za-z0-9_-]*)(?![\w-])[^>]*-->")

# Wording that switches a detector on without a marker: the heading of Ivan's §10 ("GitHub
# Actions are off — the laptop is the gate") and the template's §4 ("Ask about product
# decisions, not about permission" / "Never ask "shall I proceed?"").
IMPLICIT = {
    "no-actions": re.compile(r"^#{1,6}\s.*\bGitHub Actions\b.*\b(off|never|not|no)\b", re.I | re.M),
    "ask-permission": re.compile(r"^#{1,6}\s.*\bnot about permission\b|never ask\W+shall i proceed", re.I | re.M),
}

DETECTORS = {
    "no-actions": dict(rule="GitHub Actions only on workflow_dispatch (Ivan's POLICY §10)",
                       reported="teyla doctor (actions:<repo>), advice A16"),
    "ask-permission": dict(rule="ask about product decisions, never for permission to proceed (POLICY §4)",
                           reported="advice A15"),
}


def policy_text(path: pathlib.Path | None = None) -> str:
    from . import policy
    try:
        return (path or policy.POLICY).read_text(errors="replace")
    except OSError:
        return ""


def declared(text: str | None = None) -> tuple[list[str], list[str]]:
    """(active built-in detector ids, unknown marker ids) for a POLICY.md text."""
    text = policy_text() if text is None else text
    ids = set(MARKER_RE.findall(text))
    for did, rx in IMPLICIT.items():
        if rx.search(text):
            ids.add(did)
    return sorted(i for i in ids if i in DETECTORS), sorted(i for i in ids if i not in DETECTORS)


# --- no-actions: `on:` triggers of GitHub workflows -------------------------------------

FORBIDDEN_TRIGGERS = ("push", "pull_request", "pull_request_target", "schedule")
_ON_KEY = re.compile(r"""^(?:on|"on"|'on')\s*:(.*)$""")


def _strip_comment(s: str) -> str:
    """Drop a YAML ` # comment`; a `#` inside quotes is rare enough in an `on:` block to ignore."""
    i = s.find(" #")
    s = s if i < 0 else s[:i]
    return "" if s.lstrip().startswith("#") else s.rstrip()


def _unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"" else s


def _flow_items(s: str) -> list[str]:
    """Top-level items of a YAML flow list `[a, b]` or the keys of a flow map `{a: {...}, b: x}`."""
    s = s.strip()
    is_map = s.startswith("{")
    body = s[1:-1] if s[:1] in "[{" and s[-1:] in "]}" else s
    items, depth, cur = [], 0, ""
    for ch in body:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(cur); cur = ""
        else:
            cur += ch
    items.append(cur)
    out = []
    for it in items:
        it = it.strip()
        if not it:
            continue
        if is_map:
            it = it.split(":", 1)[0]
        out.append(_unquote(it))
    return out


def workflow_triggers(text: str) -> list[str]:
    """The events a workflow's top-level `on:` names, in the three YAML shapes GitHub accepts:

        on: push                    on: [push, pull_request]       on:
                                                                     push:
                                                                       branches: [main]
                                                                     workflow_dispatch:
    plus a block list (`on:` then `- push`) and a flow map (`on: {push: {}}`). A small line
    parser, not YAML: the only question asked is which keys sit directly under `on`."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        m = _ON_KEY.match(raw)
        if not m:
            continue
        rest = _strip_comment(m.group(1)).strip()
        if rest:
            if rest[0] in "[{":
                # A flow collection may span lines; join until the brackets balance.
                j = i
                while rest.count("[") + rest.count("{") > rest.count("]") + rest.count("}") and j + 1 < len(lines):
                    j += 1
                    rest += " " + _strip_comment(lines[j]).strip()
                return _flow_items(rest)
            return [_unquote(rest)]
        out, indent = [], None
        for raw2 in lines[i + 1:]:
            s = _strip_comment(raw2)
            if not s.strip():
                continue
            ind = len(s) - len(s.lstrip())
            if ind == 0 and not s.startswith("-"):
                # Next top-level key ends the block. A sequence at the key's own indentation
                # (`on:` then `- push`) is valid YAML and stays in (caught in review, P2).
                break
            if indent is None:
                indent = ind
            if ind != indent:
                continue
            item = s.strip()
            if item.startswith("- "):
                out.append(_unquote(item[2:]))
            elif ":" in item:
                out.append(_unquote(item.split(":", 1)[0]))
        return out
    return []


def repos(cfg: dict | None = None) -> list[pathlib.Path]:
    """Every git repo directly under code_root, plus ops_root and the git repos directly under it."""
    cfg = cfg or config.load()
    seen, out = set(), []

    def add(p: pathlib.Path):
        try:
            key = p.resolve()
        except OSError:
            return
        if key not in seen and (p / ".git").exists():
            seen.add(key); out.append(p)

    for root in (config.code_root(cfg), config.ops_root(cfg)):
        if not root.is_dir():
            continue
        add(root)
        try:
            for d in sorted(root.iterdir()):
                if d.is_dir():
                    add(d)
        except OSError:
            continue
    return out


def _git(repo: pathlib.Path, *args: str, stdin: str | None = None) -> bytes | None:
    # Bytes, not text: text mode turns CRLF into LF, and cat-file --batch declares blob sizes in
    # the original bytes, so every offset after a CRLF file drifted (caught in review, P2).
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], input=stdin.encode() if stdin is not None else None,
                           capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _default_branch_workflows(repo: pathlib.Path) -> dict[str, str] | None:
    """{".github/workflows/x.yml": text} as committed on origin/HEAD, or None when the repo has no
    origin/HEAD. Two git calls per repo — ls-tree, then one cat-file --batch for every file."""
    listing = _git(repo, "ls-tree", "--name-only", "origin/HEAD", "--", ".github/workflows/")
    if listing is None:
        return None
    paths = [p for p in listing.decode(errors="replace").splitlines() if p.endswith((".yml", ".yaml"))]
    if not paths:
        return {}
    raw = _git(repo, "cat-file", "--batch", stdin="".join(f"origin/HEAD:{p}\n" for p in paths))
    if raw is None:
        return {}
    out, pos, data = {}, 0, raw
    for p in paths:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].decode(errors="replace").split()
        pos = nl + 1
        if len(header) < 3 or header[1] != "blob":
            continue
        size = int(header[2])
        out[p] = data[pos:pos + size].decode(errors="replace")
        pos += size + 1
    return out


def scan_workflows(cfg: dict | None = None, repo_list: list[pathlib.Path] | None = None) -> dict:
    """{"repos": n scanned, "findings": [{repo, path, file, triggers, where}]}.

    `where` says which copy declares the trigger: "default branch" (origin/HEAD — the copy
    GitHub runs for schedule and for every push to main), "working tree" (local only: it takes
    effect once pushed), or both."""
    repo_list = repos(cfg) if repo_list is None else repo_list
    findings = []
    for repo in repo_list:
        local = {}
        wf = repo / ".github" / "workflows"
        if wf.is_dir():
            for f in sorted(wf.iterdir()):
                if f.suffix in (".yml", ".yaml") and f.is_file():
                    try:
                        local[f".github/workflows/{f.name}"] = f.read_text(errors="replace")
                    except OSError:
                        pass
        remote = _default_branch_workflows(repo) if (repo / ".git").exists() else None
        for rel in sorted(set(local) | set(remote or {})):
            bad_local = [t for t in workflow_triggers(local[rel]) if t in FORBIDDEN_TRIGGERS] if rel in local else []
            bad_remote = [t for t in workflow_triggers(remote[rel]) if t in FORBIDDEN_TRIGGERS] if remote and rel in remote else []
            if not bad_local and not bad_remote:
                continue
            where = ("default branch + working tree" if bad_local and bad_remote
                     else "default branch only" if bad_remote else
                     "working tree only" + ("" if remote is not None else ", no origin/HEAD to compare"))
            triggers = [t for t in FORBIDDEN_TRIGGERS if t in bad_local or t in bad_remote]
            findings.append(dict(repo=repo.name, path=str(repo), file=rel, triggers=triggers, where=where))
    return {"repos": len(repo_list), "findings": findings}


NO_ACTIONS_FIX = ("set `on:` to `workflow_dispatch:` only (or delete the workflow), commit, push — "
                  "the laptop's ./check.sh is the gate")


def no_actions_checks(scan: dict) -> list[dict]:
    """Doctor rows: one WARN per repo that has a violating workflow, else one OK row."""
    by_repo: dict[str, list[dict]] = {}
    for f in scan["findings"]:
        by_repo.setdefault(f["repo"], []).append(f)
    if not by_repo:
        return [dict(level="OK", name="policy:no-actions",
                     detail=f"{scan['repos']} repo(s) scanned: no workflow runs on push, pull_request or schedule", fix=None)]
    rows = []
    for repo, fs in by_repo.items():
        detail = "; ".join(f"{f['file']} on: {', '.join(f['triggers'])} ({f['where']})" for f in fs)
        rows.append(dict(level="WARN", name=f"actions:{repo}", detail=f"{detail} — POLICY: no Actions on push/PR",
                         fix=f"in {fs[0]['path']}: {NO_ACTIONS_FIX}"))
    return rows


def doctor_checks(cfg: dict | None = None, scan_repos: bool = True, text: str | None = None) -> list[dict]:
    active, unknown = declared(text)
    rows = []
    if unknown:
        rows.append(dict(level="WARN", name="policy:detect",
                         detail=f"POLICY.md names unknown detector(s): {', '.join(unknown)}; known: {', '.join(DETECTORS)}",
                         fix="fix the <!-- teyla:detect <id> --> marker, or upgrade teyla"))
    if not active:
        return rows
    rows.append(dict(level="OK", name="policy:detect", detail=f"active: {', '.join(active)}", fix=None))
    if "no-actions" in active and scan_repos:
        rows += no_actions_checks(scan_workflows(cfg))
    return rows


def enrich(m: dict, cfg: dict | None = None, text: str | None = None) -> dict:
    """Add what the policy detectors need to the monitor metrics: which detectors the policy
    declares, and the workflow scan when `no-actions` is one of them. The caller is the CLI —
    metrics() stays a pure function of the sessions it is given."""
    active, _ = declared(text)
    m["policy_detectors"] = active
    if "no-actions" in active:
        try:
            m["workflow_triggers"] = scan_workflows(cfg)["findings"]
        except Exception:  # noqa: BLE001 — a detector must never take the report down
            m["workflow_triggers"] = []
    return m


# --- ask-permission: turns that ended by asking to do the obvious next step ----------------
#
# Measured on this machine's last 30 days of Claude Code transcripts (2026-09): 403 turns
# ended with a question before the next human turn. Most were real decisions — "A or B?",
# "which do you want?", "paste the key or skip?" — and a detector that counted every trailing
# question would be noise. The shape §4 forbids is narrower and has a tell: the agent asks
# permission for one next step ("Want me to push them?", "Делать?", "Go?") and the human's
# whole decision is "yes". So a turn counts only when all three hold:
#   1. the last paragraph asks permission (PERMISSION_RE) for a single step — no " or ",
#      no "which", no numbered menu;
#   2. the step is not one the policy itself reserves for the human (BLOCKER_RE: keys,
#      payments, merges, deploys to production, deletes, downloads, the governance files);
#   3. the next human turn is a bare yes and nothing else (is_bare_yes).
# A session that ends on the question is not counted: nobody answered, so nothing is known.

PERMISSION_RE = re.compile(
    r"\b(?:do you )?want me to\b|\bwould you like me to\b|\b(?:shall|should) (?:i|we)\b"
    r"|\b(?:ok|okay|ready) to (?:proceed|go|continue|start)\b|\blet me know if you(?:'d| would)? (?:like|want) me to\b"
    r"|(?:^|[.!?]\s+|\n)\s*(?:proceed|go|apply|continue|ship it|go ahead)\?"
    r"|\bхочешь\b|\bхотите\b|\bделать\?|\bделаем\?|\bпродолж(?:ить|аю|аем)\?|\bзапуска(?:ю|ем|ть)\?|\bприменить\?"
    r"|\bмне (?:продолжить|сделать|начать|запустить)\b|\bсделать\?",
    re.I,
)
CHOICE_RE = re.compile(r"\bor\b|\bwhich\b|\bили\b|\bкакой\b|\bкакую\b|\bкакое\b|\bчто (?:берём|выбираешь)\b|(?:^|\n)\s*(?:\d+[.)]|\(?[a-c]\))\s", re.I)
BLOCKER_RE = re.compile(
    r"api[ _-]?key|password|passphrase|token|credential|secret|sign[ -]?in|log[ -]?in|2fa|payment|pay\b|purchase|billing"
    r"|\bmerge\b|\bproduction\b|\bprod\b|\bdeploy|\bdelete|\bremove|\bdrop\b|force[- ]push|\bdownload|\bpublish|\bsend\b|\bemail"
    r"|CLAUDE\.md|POLICY\.md|ключ|пароль|оплат|удал|смерж|мерж|прод\b|деплой|задепло",
    re.I,
)
# The whole reply must be a yes — words from this list and punctuation, nothing else.
# "Yes, but don't push until CI is green" is a decision with a condition, not a nudge; a
# prefix match counted it (Codex review). "ok", "go" and "давай" open a redirect as
# often as a yes ("Okay, skip grok…", "Давай нагенерим больше вариантов" — both measured),
# so a reply is also rejected when anything but these words follows them.
AFFIRMATIVE_WORDS = frozenset(
    "yes yep yeah yup sure ok okay k proceed go ahead do it please agreed agree lgtm ship run continue sounds good "
    "да давай делай ок окей конечно ага продолжай согласен запускай го пожалуйста вперёд вперед".split())
FILLER_WORDS = frozenset("ahead it please good пожалуйста".split())


def is_bare_yes(reply: str | None) -> bool:
    if not reply or len(reply) > 60:
        return False
    words = re.findall(r"[^\W\d_]+", reply.lower())
    return bool(words) and all(w in AFFIRMATIVE_WORDS for w in words) and any(w not in FILLER_WORDS for w in words)


ASK_THRESHOLD_PER_WEEK = 3


def _last_paragraph(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return paras[-1] if paras else ""


def _question_sentence(par: str) -> str:
    """The sentence of `par` that holds its last question mark (or the whole paragraph when a
    "let me know if you want me to …" offer has none)."""
    q = par.rfind("?")
    if q < 0:
        return par
    start = max(par.rfind(". ", 0, q), par.rfind("! ", 0, q), par.rfind("? ", 0, q), par.rfind("\n", 0, q))
    return par[start + 1:q + 1].strip()


def is_permission_ask(ending: str, reply: str | None) -> str | None:
    """The permission question when a turn ending + the human's reply match the §4 shape, else None."""
    if not is_bare_yes(reply):
        return None
    par = _last_paragraph(ending)
    if "?" not in par and "let me know" not in par.lower():
        return None
    q = _question_sentence(par)
    if not PERMISSION_RE.search(q) or CHOICE_RE.search(q) or BLOCKER_RE.search(par):
        return None
    return q[-160:]


def permission_ask_metrics(sessions) -> dict:
    """{"by_week": {"2026-W39": n}, "total": n, "examined": turns with a candidate ending,
    "examples": [{project, sid, day, ask}]} over interactive (non-batch) sessions."""
    by_week: dict[str, int] = {}
    examples, total, examined = [], 0, 0
    for s in sessions:
        if s.batch or s.sidechain:
            continue
        for ts, ending, reply in getattr(s, "turn_ends", ()) or ():
            examined += 1
            ask = is_permission_ask(ending, reply)
            if ask is None:
                continue
            total += 1
            try:
                d = _dt.datetime.fromisoformat((ts or s.first or "").replace("Z", "+00:00"))
                y, w, _ = d.isocalendar()
                wk = f"{y}-W{w:02d}"
            except ValueError:
                wk = "?"
            by_week[wk] = by_week.get(wk, 0) + 1
            if len(examples) < 5:
                examples.append(dict(project=s.project, sid=s.sid[:8], day=(ts or s.first or "")[:10], ask=ask))
    return {"by_week": dict(sorted(by_week.items())), "total": total, "examined": examined, "examples": examples}
