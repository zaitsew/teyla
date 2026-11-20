#!/usr/bin/env python3
"""Move everything under "## Unreleased" in CHANGELOG.md into a dated version heading.

    python3 scripts/changelog_release.py CHANGELOG.md 0.58.2 2026-11-20

scripts/release.sh runs this before it bumps the version strings. The notes of a release must
say what changed (POLICY: What's New says what changed), so an empty Unreleased section is
refused. The heading style is the file's own: `## <version> — <date>`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

UNRELEASED = "## Unreleased"


class ChangelogError(ValueError):
    pass


def release(text: str, version: str, date: str) -> str:
    """Return `text` with the Unreleased body under a new `## <version> — <date>` heading."""
    lines = text.split("\n")
    try:
        start = lines.index(UNRELEASED)
    except ValueError:
        raise ChangelogError(f'CHANGELOG.md has no "{UNRELEASED}" heading') from None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = lines[start + 1 : end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        raise ChangelogError(f'"{UNRELEASED}" is empty: write the release notes first')
    if re.search(rf"^## {re.escape(version)}( |$)", text, re.M):
        raise ChangelogError(f"CHANGELOG.md already has a heading for {version}")
    new = lines[: start + 1] + ["", f"## {version} — {date}", ""] + body + [""] + lines[end:]
    return "\n".join(new)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: changelog_release.py CHANGELOG.md VERSION YYYY-MM-DD", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        out = release(path.read_text(), argv[2], argv[3])
    except ChangelogError as e:
        print(f"changelog: {e}", file=sys.stderr)
        return 1
    path.write_text(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
