"""docs/PRIVACY.md lists every call that leaves the machine. This test is the tripwire that keeps it true.

A module under src/teyla that starts using a network library, a network tool (`gh`, `ssh`, `curl`),
a git remote operation, a model CLI, a release tool or the iCloud folder must be added to ALLOWED
below, with the PRIVACY.md rows it belongs to. A new module fails the test until someone reads the
table and decides whether it needs a row. The scan is a tripwire, not a proof: a call built from a
variable that none of these patterns sees still needs a person to add its row.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "teyla"
PRIVACY = (ROOT / "docs" / "PRIVACY.md").read_text()

_LIBS = (r"urllib\.request|urllib\s+import\s+request|http\.client|http\.server|socket|requests|httpx|aiohttp"
         r"|smtplib|ftplib|websockets?|xmlrpc\.client")
PATTERNS = {
    "network library": re.compile(rf"(?m)^\s*(?:import|from)\s+(?:{_LIBS})\b|__import__\(\s*[\"'](?:{_LIBS})[\"']"),
    "network tool": re.compile(r"""\[\s*(?:[a-z_]+\s*,\s*)?["'](?:gh|ssh|scp|curl|wget|rsync)["']"""),
    "git remote": re.compile(r"""(?:["']git["']|\bgit\()[^\n#]*?["'](?:clone|fetch|pull|push|ls-remote)["']"""),
    "model CLI": re.compile(r"""--output-format|["']--bg["']|--no-session-persistence|brief_command\(|"""
                            r"""["']exec["']\s*,\s*["']--skip-git"""),
    "release tool": re.compile(r"\brelease_tool\b"),
    "iCloud folder": re.compile(r"Mobile Documents"),
}

# module (relative to src/teyla) -> the rows of docs/PRIVACY.md it is behind.
ALLOWED = {
    "update.py": {1, 2},
    "models.py": {3},
    "plugin_install.py": {4},
    "backlog.py": {5},
    "reviews.py": {6},
    "routines.py": {7, 8},
    "schedules.py": {7},
    "cloud.py": {9},
    "spend.py": {10, 19},
    "dispatch.py": {11, 18},
    "platform.py": {12},
    "testflight.py": {13},
    "play.py": {13},
    "state.py": {14},
    "intent_cover.py": {15},
    "voice.py": {16},
    "health.py": {17},
    "control/harness.py": {18},
    "answer.py": {18},
    "providers.py": {19},
    "products.py": {20},
    "review.py": {23},
    "review_asc.py": {24},
    "ux_judge.py": {25},
    "scout_design.py": {26},
    "relay.py": {21},
    "web/server.py": {22},
}


def _found() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        text = f.read_text()
        for label, rx in PATTERNS.items():
            if rx.search(text):
                out.setdefault(str(f.relative_to(SRC)), set()).add(label)
    return out


def test_every_module_that_can_reach_the_network_is_listed():
    unlisted = {m: sorted(why) for m, why in _found().items() if m not in ALLOWED}
    assert not unlisted, (
        f"{unlisted}: add each module to ALLOWED in this test and a row to docs/PRIVACY.md "
        "(what triggers it, the host, what is sent, whether it runs by default)")


def test_the_allowlist_has_no_stale_entries():
    found = _found()
    gone = sorted(m for m in ALLOWED if not (SRC / m).exists())
    quiet = sorted(m for m in ALLOWED if (SRC / m).exists() and m not in found)
    assert not gone, f"{gone} no longer exist: remove them from ALLOWED"
    assert not quiet, f"{quiet} no longer use any network pattern: remove them from ALLOWED and check their PRIVACY.md rows"


def test_the_allowlist_mirrors_the_privacy_table():
    rows = {int(n) for n in re.findall(r"(?m)^\| (\d+) \|", PRIVACY)}
    claimed = set().union(*ALLOWED.values())
    assert rows == claimed, f"rows without a module: {sorted(rows - claimed)}; modules naming a missing row: {sorted(claimed - rows)}"


def test_every_row_says_whether_it_runs_by_default_and_what_safe_mode_does():
    for line in PRIVACY.splitlines():
        if re.match(r"\| \d+ \|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert all(cells), line
            assert len(cells) in (5, 6), line
