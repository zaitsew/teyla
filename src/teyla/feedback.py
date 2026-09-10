"""`teyla feedback` — one file a stranger can send back.

Built for the setup this has to work on: an account that can install Teyla from the
GitHub link, cannot push to GitHub, and can only get feedback out by copying one file
somewhere (a chat, an email, a pasted GitHub issue). `teyla feedback` writes exactly
that file: what Teyla can see on this machine, the same redacted report `monitor
--share` would produce, and a fixed questionnaire to fill in by hand.

Nothing in the output should identify the machine or the work: no session ids, no
path under the home directory (home is rewritten to `~`, and `monitor.redact()`
already turns project keys into p01..pNN and drops correction text and cwd paths).
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib
import platform

from . import __version__

ISSUE_URL = "https://github.com/zaitsew/teyla/issues/new?template=feedback.md"

QUESTIONS = [
    "What did you expect Teyla to tell you that it didn't?",
    "Which advice was wrong for your context, and why?",
    "What could not be installed or run (paste the error)?",
    "What does your harness/setup have that Teyla does not read (connectors, plugins, logs)?",
    "One thing to add, one to remove",
]


def _redact_home(text: str) -> str:
    """Replace every occurrence of the home directory with `~`, absolute or already-expanded."""
    home = str(pathlib.Path.home())
    if not home or home == "/":
        return text
    return text.replace(home, "~")


def _doctor_lines() -> list[str]:
    """Same shape as `teyla doctor`'s harness table, with the store path home-redacted."""
    from .adapters import claude_code, codex, grok, hermes
    lines = []
    for mod in (claude_code, codex, grok, hermes):
        root = getattr(mod, "DEFAULT_ROOT", None)
        ok = bool(root) and os.path.exists(os.path.expanduser(root))
        try:
            n = len(mod.load()) if ok else 0
        except Exception as e:  # noqa: BLE001
            n = f"error: {type(e).__name__}"
        shown_root = _redact_home(os.path.expanduser(root)) if root else "-"
        lines.append(f"{mod.NAME:12} {shown_root:40} {'found' if ok else 'absent':7} sessions: {n}")
    # The doctor checklist itself (levels, names, home-redacted detail; the fix column is
    # left out — it can name a repo path). This is what tells the maintainer whether the
    # install is actually wired on the reporting machine.
    try:
        from . import doctor
        lines.append("")
        for c in doctor.checks(refresh_update=False, scan_repos=False):
            lines.append(f"{c['level']:4} {c['name']:22} {_redact_home(str(c['detail']))}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"doctor: error: {type(e).__name__}")
    return lines


def _policy_lines(policy_status: dict) -> list[str]:
    """Same shape as `teyla policy status`. No paths — the dict is booleans/None only."""
    return [f"{k:14} {'ok' if v else ('not installed' if v is None else 'MISSING')}" for k, v in policy_status.items()]


def _routines_summary(cwd: str | None = None) -> str | None:
    """The one-line routines summary, if a teyla.toml exists under cwd or under ~/repos."""
    from .routines import ManifestError, evaluate, find_manifests, parse_manifest, summarize

    cwd = cwd or os.getcwd()
    manifests = {p.resolve() for p in find_manifests([cwd])} | {p.resolve() for p in find_manifests(None)}
    if not manifests:
        return None
    reports = []
    for m in sorted(manifests):
        try:
            reports.append(evaluate(parse_manifest(m)))
        except ManifestError:
            continue
    if not reports:
        return None
    n, m_, k = summarize(reports)
    return f"{n} routines not running, {m_} checks broken, {k} untested/re-test — {len(reports)} product(s) checked"


def build(metrics_raw: dict, *, days: int, policy_status: dict, doctor_lines: list[str],
          routines_summary: str | None = None) -> str:
    """Assemble the feedback file from already-gathered pieces. Redacts the metrics and
    scrubs the home directory from the whole document before returning it — this is the
    function to call from a test with a hand-built metrics dict."""
    from .advise import advise
    from .monitor import redact
    from .report import markdown

    m = redact(metrics_raw)
    findings = advise(m, policy_status)
    report_md = markdown(m, findings, title="Teyla adoption report", include_samples=False)

    L = [f"# Teyla feedback — {_dt.date.today().isoformat()}", ""]
    L += ["## Setup", "",
          f"- Teyla version: {__version__}",
          f"- Python: {platform.python_version()}",
          f"- OS: {platform.platform()}", ""]
    L += ["### Harnesses (doctor)", "", "```"] + doctor_lines + ["```", ""]
    L += ["### Policy", "", "```"] + _policy_lines(policy_status) + ["```", ""]
    if routines_summary:
        L += ["### Routines", "", routines_summary, ""]
    L += [f"## Adoption report — last {days} days, redacted", "", report_md]
    L += ["## Questionnaire", ""]
    for q in QUESTIONS:
        L += [f"**{q}**", "", "_(answer here)_", ""]
    L += ["---", "", f"Send this file to the maintainer or paste it into a GitHub issue: {ISSUE_URL}", ""]
    return _redact_home("\n".join(L))


def render(days: int = 30) -> str:
    """Gather everything live from this machine and build the feedback document."""
    from . import policy
    from .adapters import load_all
    from .monitor import metrics

    sessions = [s for s in load_all() if not s.sidechain]
    m = metrics(sessions, days)
    return build(m, days=days, policy_status=policy.status(), doctor_lines=_doctor_lines(),
                 routines_summary=_routines_summary())


def write_feedback(days: int = 30, out: str | None = None) -> str:
    """Render and write the feedback file, returning the path written."""
    content = render(days)
    out_path = out or f"teyla-feedback-{_dt.date.today().isoformat()}.md"
    pathlib.Path(out_path).write_text(content)
    return out_path


def cmd_feedback(args):
    days = getattr(args, "days", None) or 30
    path = write_feedback(days=days, out=getattr(args, "out", None))
    print(f"wrote {path}")


def register(sp):
    """Add `teyla feedback` to an argparse subparsers object. Not wired from cli.py yet —
    call `feedback.register(sp)` next to the other `sp.add_parser(...)` calls in main()."""
    q = sp.add_parser("feedback", help="one shareable file: setup + redacted report + questionnaire")
    q.set_defaults(fn=cmd_feedback)
    q.add_argument("--days", type=int, default=30, help="report window (default: 30)")
    q.add_argument("--out", help="output path (default: teyla-feedback-<date>.md)")
    return q
