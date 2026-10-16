"""What a reel says outside the beats: the title card, the end card, and `reel.txt`.

Shared by `teyla reel check`, `teyla reel render` and the tests, so the audit trail and the video
are built from the same function.
"""
from __future__ import annotations

from .story import MINUS, Story, fmt_span


def top_bar(story: Story) -> list[str]:
    """Strings in the top bar of every frame (the clock is session time, not a Story string)."""
    return [story.repo, story.harness]


def title_card(story: Story) -> list[str]:
    """Strings on the 2.5 s title card: the title, then the repo and the harness."""
    return [story.title, f"{story.repo} · {story.harness}"]


def end_card(story: Story) -> list[str]:
    """Strings on the 3 s end card: the totals, one per line."""
    t = story.totals
    lines = [
        f"{t.commits} commit{'s' if t.commits != 1 else ''}",
        f"+{t.lines_added} {MINUS}{t.lines_removed}",
    ]
    if t.tests_passed:
        lines.append(f"{t.tests_passed} tests passed")
    if t.tests_failed:
        lines.append(f"{t.tests_failed} tests failed")
    if t.prs_opened or t.prs_merged:
        lines.append(f"{t.prs_opened} PR{'s' if t.prs_opened != 1 else ''} opened · {t.prs_merged} merged")
    lines.append(f"{fmt_span(t.wall_clock)} wall clock")
    if t.cost_usd is not None:
        lines.append(f"${t.cost_usd:,.0f} in tokens")
    return lines


def beat_strings(beat) -> list[str]:
    out = [beat.kind.upper(), beat.headline, *beat.lines]
    if beat.diff:
        out.extend(beat.diff)
    return out


def rendered_strings(story: Story) -> list[str]:
    """Every string the renderer may draw that came from the Story, in video order: reel.txt."""
    out = top_bar(story) + title_card(story)
    for b in story.beats:
        out.extend(beat_strings(b))
    out.extend(end_card(story))
    return out
