#!/usr/bin/env python3
"""Writes the invented activity graph the Mac preview and the tests read: apps/mac/TeylaTests/Fixtures/activity.v1.json.

It has the shape `teyla growth activity --json` prints (version 1): every day from the Monday 52 weeks before the week of
`today`, oldest first, with a count, a level 0 to 4 and the kinds of the day. Everything is invented and deterministic, so the
file does not change between runs.

    python3 apps/mac/Tools/make_activity_fixture.py
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "apps" / "mac" / "TeylaTests" / "Fixtures" / "activity.v1.json"
TODAY = dt.date(2026, 11, 6)           # a Friday
KINDS = ["post", "comment", "reply", "email", "dm", "call", "meeting", "icp-meeting", "ad", "outreach", "response"]
# What a busy week looks like, by weekday (Monday first): comments and posts on weekdays, little on the weekend.
WEIGHTS = [4, 5, 5, 4, 4, 1, 0]
MIX = ["comment", "post", "comment", "reply", "email", "dm", "comment", "post", "meeting", "response", "outreach", "icp-meeting", "call", "ad"]


def level(n: int) -> int:
    return 0 if n == 0 else 1 if n == 1 else 2 if n <= 3 else 3 if n <= 5 else 4


def build(today: dt.date = TODAY, weeks: int = 53) -> dict:
    start = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks - 1)
    days = []
    d = start
    index = 0
    while d <= today:
        # A slow start that gathers pace, with quiet days from a hash of the day's index: the graph has every level in it.
        week = (d - start).days // 7
        noise = (index * 37 + 11) % 7
        base = round(WEIGHTS[d.weekday()] * week / 40)
        count = max(0, base + (noise % 3) - 1) if base else (1 if noise == 0 and week > 6 else 0)
        kinds: dict[str, int] = {}
        for i in range(count):
            kind = MIX[(index + i * 3) % len(MIX)]
            kinds[kind] = kinds.get(kind, 0) + 1
        days.append({"day": d.isoformat(), "count": count, "level": level(count), "kinds": kinds})
        d += dt.timedelta(days=1)
        index += 1
    streak = 0
    for item in reversed(days):
        if item["count"] == 0:
            if item["day"] == today.isoformat():
                continue              # today is not over yet
            break
        streak += 1
    longest = run = 0
    for item in days:
        run = run + 1 if item["count"] else 0
        longest = max(longest, run)
    by_kind: dict[str, int] = {}
    for item in days:
        for k, n in item["kinds"].items():
            by_kind[k] = by_kind.get(k, 0) + n
    week_start = (today - dt.timedelta(days=today.weekday())).isoformat()
    return {"version": 1, "today": today.isoformat(), "weeks": weeks, "start": start.isoformat(), "days": days,
            "total": sum(i["count"] for i in days), "today_count": days[-1]["count"],
            "week_count": sum(i["count"] for i in days if i["day"] >= week_start), "streak": streak, "longest": longest,
            "by_kind": by_kind, "outcomes": {"meetings": by_kind.get("meeting", 0) + by_kind.get("icp-meeting", 0),
                                              "responses": by_kind.get("response", 0)},
            "claimed": 2, "kinds": KINDS}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
