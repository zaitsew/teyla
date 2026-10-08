"""What gets read: the session-start banner shows only what changed, and a weekly digest
names the three things worth doing.

The weekly reports (monitor.md, routines.md, products.md, models.md, reviews.md under the ops runs folder)
had no reader: nothing opened them. And a session-start line such as "teyla: 1 fix(es),
2 warning(s) — run `teyla doctor`" that repeats the same items for days stops being read.

**Banner.** `teyla doctor` and `teyla routines` write `~/.teyla/banner.items`, one
`key<TAB>text` line per thing that needs a human: doctor WARN/FIX rows (key = level|name, so
a WARN turning into a FIX is news), routines not running (NOT LOADED/STALE/unknown/FAILING) and BROKEN checks from every
product, and reminders — those only on the day they fall due, the day after, and then once a
week (the key carries the overdue week). The plugin's session-start hook compares the keys
with `~/.teyla/banner.seen` (the keys it showed last time) in one awk call, prints

    teyla: new — app-a routine gate NOT LOADED; 2 known (teyla doctor)

and nothing at all when nothing is new, then records the current keys as seen. The weekly
digest is where known items come back.

**Digest.** The weekly routine runs `teyla digest --write`: `~/.teyla/digest.md`, at most
six lines — a headline, the week's spend and waste (`teyla spend`), the review debt line
(`teyla reviews`, only while PRs merged unreviewed or with an open P1), the top three actions
across monitor advice, spend waste findings, doctor FIX rows, routines not running and checks
BROKEN/UNTESTED for more than 14 days, each with its one command or fix, and a streak note when the same advice has fired three weeks running (advice ids
per ISO week are kept in `~/.teyla/digest-history.json`). The session-start hook prints the
headline once, at the first session after it was written; `teyla digest` prints the file. On
macOS a notification is posted when it is written (`teyla config set digest.notify=false`
turns that off).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from . import config

HEADLINE_MAX = 220


def _path(name: str) -> pathlib.Path:
    # Resolved at call time: config.TEYLA_DIR is what tests (and a moved home) redirect.
    return config.TEYLA_DIR / name


def banner_items_path() -> pathlib.Path:
    return _path("banner.items")


def digest_path() -> pathlib.Path:
    return _path("digest.md")


def history_path() -> pathlib.Path:
    return _path("digest-history.json")


def _clean(s) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(s)).strip()


def _short(s: str, n: int = 70) -> str:
    s = _clean(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --- banner -----------------------------------------------------------------------------------

def reminder_items(reminders: list[dict] | None = None, today: _dt.date | None = None) -> list[tuple[str, str]]:
    """Reminders for the banner: only once due. The key names the due day, then the overdue week
    (days 1–7 overdue are week 0, 8–14 week 1, …), so the hook shows it on the due day, the first
    day overdue and once a week after — not at every session start, as the doctor line did."""
    from . import remind
    today = today or _dt.date.today()
    out = []
    for r in (remind.load() if reminders is None else reminders):
        try:
            d = remind.days_until(r["due"], today)
        except ValueError:
            continue
        if d > 0:
            continue
        what = _short(r["what"], 60)
        if d == 0:
            out.append((f"remind|{what}|due", f"reminder due today: {what}"))
        else:
            out.append((f"remind|{what}|w{(-d - 1) // 7}", f"reminder {-d}d overdue: {what}"))
    return out


def doctor_items(checks: list[dict]) -> list[tuple[str, str]]:
    out = []
    for c in checks:
        if c.get("level") not in ("WARN", "FIX") or str(c.get("name", "")).startswith("remind:"):
            continue
        out.append((f"{c['level']}|{c['name']}", _short(f"{c['name']} {c['level']}: {c.get('detail', '')}")))
    return out


def routine_items(lines_dir: pathlib.Path | None = None) -> list[tuple[str, str]]:
    from . import routines
    d = lines_dir or routines.LINES_DIR
    out = []
    try:
        files = sorted(d.glob("*.problems"))
    except OSError:
        return out
    for f in files:
        try:
            for line in f.read_text().splitlines():
                if "\t" in line:
                    k, t = line.split("\t", 1)
                    out.append((k, t))
        except OSError:
            continue
    return out


def _doctor_checks_on_disk() -> list[dict]:
    from . import doctor
    try:
        return json.loads(doctor.DOCTOR_JSON.read_text()).get("checks") or []
    except (OSError, ValueError, AttributeError):
        return []


def write_banner_items(checks: list[dict] | None = None, today: _dt.date | None = None) -> pathlib.Path | None:
    """Rewrite ~/.teyla/banner.items from doctor (the given rows, else doctor.json), every
    product's problems file and the reminders. Atomic: the hook may read it at any moment."""
    items = doctor_items(_doctor_checks_on_disk() if checks is None else checks)
    items += routine_items()
    items += reminder_items(today=today)
    p = banner_items_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text("".join(f"{_clean(k)}\t{_clean(t)}\n" for k, t in items))
        os.replace(tmp, p)
    except OSError:
        return None
    return p


def banner(items_text: str, seen_text: str | None) -> str:
    """What the session-start hook prints, in Python — the hook does the same in awk; this is the
    reference the tests hold the hook to."""
    seen = set((seen_text or "").split())
    new, known = [], 0
    for line in items_text.splitlines():
        if "\t" not in line:
            continue
        k, t = line.split("\t", 1)
        if k in seen:
            known += 1
        else:
            new.append(t)
    if not new:
        return ""
    s = "teyla: new — " + "; ".join(new[:3])
    if len(new) > 3:
        s += f" (+{len(new) - 3} more)"
    if known:
        s += f"; {known} known"
    return s + " (teyla doctor)"


# --- digest -----------------------------------------------------------------------------------

_COMMAND_RE = re.compile(r"^(?:teyla|git|gh|uv|pipx|brew|chmod|bash|sh|launchctl|claude|codex|grok|~/|/|\./)(?:\s|$|/)")


# A command that acknowledges or accepts something is never pasteable on its own: the advice
# says when (after the diff shows the edit is yours), and a digest line drops the "when".
_ACK_RE = re.compile(r"^teyla\s+policy\s+ack\b")
_CONDITION_RE = re.compile(r"\b(?:if|unless|when|whenever|once|after|only|provided)\b", re.I)


def _step_of_advice(action: str) -> tuple[str, bool]:
    """(step, is_command): the first `backticked` span of an advice action that is a command
    (A16's `on:` is a YAML key, not one); without one the action is prose — its first sentence,
    backticks dropped, never dressed up as something to paste.

    A span is skipped when the words before it, in its sentence, set a condition ("if the edit
    is yours, run `teyla policy ack`") or when it is an ack: the line would say "run this" and
    lose the "if" (caught in review, P1 — A10 became an unconditional `teyla policy ack`)."""
    text = action or ""
    for m in re.finditer(r"`([^`]+)`", text):
        span = m.group(1)
        if not _COMMAND_RE.match(span) or _ACK_RE.match(span):
            continue
        before = re.split(r"(?<=[.;])\s", text[:m.start()])[-1]
        if _CONDITION_RE.search(before):
            continue
        return span, True
    first = re.split(r"(?<=[.;])\s", text)[0].rstrip(".").replace("`", "")
    return _short(first, 90), False


def _step_of_fix(fix: str | None) -> tuple[str, bool]:
    # doctor fixes often carry an alternative in parentheses after spaces: keep the first command.
    # Not truncated: a step is copied into a shell, and a command cut with "…" does not run.
    step = _clean(re.split(r"\s{2,}\(", fix or "")[0]) or "teyla doctor"
    if _ACK_RE.match(step):  # its parenthesis says "if you made or accepted the edit" (caught in review, P1)
        return "diff the global CLAUDE.md, then acknowledge it only if the edit is yours", False
    return step, bool(_COMMAND_RE.match(step))


def candidates(findings: list[dict], doctor_checks: list[dict], reports: list[dict]) -> list[dict]:
    """Every action worth a line, ranked: doctor FIX, high advice, routines not running, broken
    checks, medium advice, long-untested checks, low advice. Each: {id, text, step, cmd, rank} —
    `cmd` says whether `step` is a command to paste or a sentence to act on."""
    from . import routines
    out = []
    for c in doctor_checks:
        if c.get("level") == "FIX":
            step, cmd = _step_of_fix(c.get("fix"))
            out.append(dict(rank=0, id=f"doctor:{c['name']}", text=_short(f"{c['name']}: {c.get('detail', '')}"),
                            step=step, cmd=cmd))
    sev_rank = {"high": 1, "medium": 4, "low": 6}
    for f in findings:
        step, cmd = _step_of_advice(f.get("action", ""))
        out.append(dict(rank=sev_rank.get(f.get("severity"), 6), id=f["id"], text=_short(f"{f['id']} {f['title']}"),
                        step=step, cmd=cmd))
    for r in reports:
        if r.get("error"):
            out.append(dict(rank=2, id=f"toml:{r['product']}", text=f"{r['product']}: teyla.toml has an error",
                            step=f"teyla routines {routines._sh(r.get('repo') or '.')}", cmd=True))
            continue
        for row in r.get("routines") or []:
            if row.get("verdict") in routines.NOT_RUNNING_VERDICTS:  # `unknown` counts, as in `teyla routines`
                out.append(dict(rank=2, id=f"routine:{r['product']}:{row['name']}",
                                text=_short(f"{r['product']} routine {row['name']} {row['verdict']}"
                                            + (f" ({row['detail']})" if row.get("detail") else "")),
                                step=f"teyla routines {routines._sh(r.get('repo') or '.')}", cmd=True))
        for c in routines.stale_checks(r):
            age = c.get("age_days")
            since = f"{age}d" if isinstance(age, int) else "never confirmed"
            out.append(dict(rank=3 if c["verdict"] == "BROKEN" else 5, id=f"check:{r['product']}:{c['name']}",
                            text=_short(f"{r['product']} check {c['name']} {c['verdict']} ({since})"),
                            step=routines.confirm_step(r["product"], c["name"]), cmd=False,
                            brief="try it, then record the result (teyla digest has the commands)"))
    return sorted(out, key=lambda c: c["rank"])  # stable: ties keep input order


def _week(d: _dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def update_history(history: dict, advice_ids: list[str], today: _dt.date, keep: int = 12) -> dict:
    weeks = dict(history.get("weeks") or {})
    weeks[_week(today)] = sorted(set(advice_ids))
    return {"weeks": dict(sorted(weeks.items())[-keep:])}


def streaks(history: dict, today: _dt.date) -> dict[str, int]:
    """{advice id: consecutive ISO weeks it fired, ending this week}."""
    weeks = history.get("weeks") or {}
    out = {}
    for aid in weeks.get(_week(today), []):
        n, d = 0, today
        while aid in weeks.get(_week(d), []):
            n += 1
            d -= _dt.timedelta(days=7)
        out[aid] = n
    return out


STREAK_WEEKS = 3


def build(findings: list[dict], doctor_checks: list[dict], reports: list[dict], history: dict,
          today: _dt.date | None = None, spend_rep: dict | None = None,
          extra: list[dict] | None = None, review_line: str | None = None) -> tuple[list[str], dict]:
    """(digest lines — at most six —, the updated history). `spend_rep` is `teyla spend`'s week:
    its summary is a line of its own and its waste findings compete for the top three. `extra`
    is more ranked candidates (`teyla rules propose` per repo) competing the same way. `review_line`
    is `teyla reviews`' totals line, given only while merged PRs are unreviewed or carry an open P1."""
    from . import spend
    today = today or _dt.date.today()
    history = update_history(history, [f["id"] for f in findings], today)
    extra = (spend.digest_candidates(spend_rep) if spend_rep else []) + list(extra or [])
    top = sorted(candidates(findings, doctor_checks, reports) + extra, key=lambda c: c["rank"])[:3]
    if not top:
        lines = [f"teyla weekly {today.isoformat()}: nothing needs you this week."]
    else:
        head = f"teyla weekly {today.isoformat()}: {top[0]['text']} → {top[0].get('brief', top[0]['step'])}"
        if len(top) > 1:
            head += f" (+{len(top) - 1} more: teyla digest)"
        lines = [_short(head, HEADLINE_MAX)]
        if spend_rep:
            lines.append(spend.summary_line(spend_rep))
        lines += [f"{i}. {c['text']} → " + (f"`{c['step']}`" if c.get("cmd") else c["step"]) for i, c in enumerate(top, 1)]
    if review_line:
        lines.append(review_line)
    long_runs = sorted(((n, aid) for aid, n in streaks(history, today).items() if n >= STREAK_WEEKS), reverse=True)
    if long_runs:
        names = ", ".join(f"{aid} ({n} weeks)" for n, aid in long_runs[:3])
        lines.append(f"streak: {names} running — the advice is not landing; make it a rule, or change what it measures.")
    if not top and spend_rep:
        lines.append(spend.summary_line(spend_rep))
    return lines[:6], history


def notify(headline: str, cfg: dict | None = None) -> bool:
    """A macOS notification with the digest headline. Local only (osascript); off with
    `teyla config set digest.notify=false`. Returns whether one was posted."""
    from .storage import _truthy
    cfg = cfg or config.load()
    if not _truthy((cfg.get("digest") or {}).get("notify", True)):
        return False
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False
    def q(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        r = subprocess.run(["osascript", "-e", f"display notification {q(headline[:200])} with title {q('Teyla weekly')}"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def weekly_findings(days: int = 7) -> list[dict]:
    """The advice `teyla advise --days 7` prints — the same pass the weekly monitor report makes."""
    from . import policy
    from .adapters import load_all, since_epoch
    from .advise import advise
    from .monitor import metrics
    ss = [s for s in load_all(since=since_epoch(days)) if not s.sidechain]
    m = metrics(ss, days)
    try:
        # The policy detectors (A15/A16) need their inputs; teyla.detect ships in a sibling PR,
        # so the digest picks it up whenever it is present, in whichever order the two land.
        from .detect import enrich
        m = enrich(m)
    except ImportError:
        pass
    try:
        from .cli import _grok_week
        m["grok_week"] = _grok_week()
    except Exception:  # noqa: BLE001 — optional input, as in cmd_advise
        pass
    return advise(m, policy.status())


def write(findings: list[dict] | None = None, doctor_checks: list[dict] | None = None,
          reports: list[dict] | None = None, today: _dt.date | None = None, notify_now: bool = True,
          spend_rep: dict | None = None) -> list[str]:
    from . import routines
    findings = weekly_findings() if findings is None else findings
    doctor_checks = _doctor_checks_on_disk() if doctor_checks is None else doctor_checks
    reports = routines.evaluate_all() if reports is None else reports
    try:
        history = json.loads(history_path().read_text())
    except (OSError, ValueError):
        history = {}
    try:
        from . import rules_lifecycle
        rule_cands = rules_lifecycle.digest_candidates()
    except Exception:  # noqa: BLE001 — a proposal pass must never stop the digest being written
        rule_cands = []
    try:
        from . import models_watch
        rule_cands += models_watch.digest_candidates()
    except Exception:  # noqa: BLE001 — same: a models pass must never stop the digest being written
        pass
    try:
        from . import reviews
        review_line = reviews.digest_line()
    except Exception:  # noqa: BLE001 — same: the review pass must never stop the digest being written
        review_line = None
    lines, history = build(findings, doctor_checks, reports, history, today, spend_rep, extra=rule_cands,
                           review_line=review_line)
    p = digest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")
    history_path().write_text(json.dumps(history, indent=1) + "\n")
    if notify_now:
        notify(lines[0])
    return lines


def cmd_digest(args) -> int:
    if args.write:
        try:
            from . import spend
            spend_rep = spend.report(7)
        except Exception:  # noqa: BLE001 — the digest must still be written when spend cannot read
            spend_rep = None
        for line in write(notify_now=not args.no_notify, spend_rep=spend_rep):
            print(line)
        print(f"wrote {digest_path()}")
        return 0
    p = digest_path()
    if not p.exists():
        print("no digest yet — the weekly routine writes it; `teyla digest --write` builds one now")
        return 1
    print(p.read_text(), end="")
    return 0


def register(sp):
    q = sp.add_parser("digest", help="the weekly digest: the top three things worth doing, each with its command")
    q.set_defaults(fn=cmd_digest)
    q.add_argument("--write", action="store_true", help="build ~/.teyla/digest.md now (the weekly routine does this)")
    q.add_argument("--no-notify", action="store_true", help="--write: no macOS notification")
    return q
