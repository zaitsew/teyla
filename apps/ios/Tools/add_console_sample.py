#!/usr/bin/env python3
"""Gives the iPhone sample (apps/ios/Teyla/Resources/sample-state.json) the compact console the admin tabs read.

`teyla state` carries `console` as each section's `compact()` (docs/CONSOLE.md). This writes an invented one with the
same shape, so Growth, Money, Operations and Playbook have something to show in sample mode. Nothing here is real. It
can be run again: the section is replaced, the rest of the file is left as it is.

    python3 apps/ios/Tools/add_console_sample.py
"""
import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[1] / "Teyla" / "Resources" / "sample-state.json"

CONSOLE = {
    "version": 1,
    "generated": 1793264400,
    "growth": {
        "headline": {"label": "Posts today", "value": "4/6", "detail": "target 1 a day over 6 channels"},
        "target": {"posts_per_day_per_channel": 1},
        "today": [
            {"platform": "x", "language": "en", "posted": 1, "target": 1},
            {"platform": "x", "language": "es", "posted": 1, "target": 1},
            {"platform": "linkedin", "language": "en", "posted": 1, "target": 1},
            {"platform": "threads", "language": "en", "posted": 1, "target": 1},
            {"platform": "youtube", "language": "en", "posted": 0, "target": 1},
            {"platform": "instagram", "language": "en", "posted": 0, "target": 1},
        ],
        "last_public_days": 0,
        "queue_days": 2.5,
        "gaps": 1,
        "pipeline": {"ideas": 14, "filming": 1, "cutting": 2, "review": 3, "ready": 5, "live": 9},
        "qualified_week": 2,
        "not_tried": ["pebble", "juniper", "thistle", "basalt"],
    },
    "money": {
        "headline": {"label": "Cash per month", "value": 214.0, "detail": "The subscriptions you list."},
        "monthly_usd": 214.0,
        "unpriced": 1,
        "list_usd_7d": 388.5,
        "next_renewal": {"name": "Sample Cloud", "renews": "2026-11-09", "days": 5},
    },
    "operations": {
        "headline": {"label": "Unresolved failures", "value": 2, "detail": "2 need you."},
        "machine": {"verdict": "OK", "disk_free_gb": 48.2},
        "leave_ok": True,
        "failures": [
            {"title": "The nightly backup of sample-app has not run for 3 days", "severity": "act"},
            {"title": "A scheduled check is late", "severity": "act"},
        ],
    },
    "playbook": {
        "headline": {"label": "Unresolved contradictions", "value": 1, "detail": "A rule came back as a correction."},
        "models": {"drift": 1, "new": 2, "arena_as_of": "2026-10-30"},
        "knowledge": {
            "wiki": {"pages": 12, "drafts": 2, "confirmed": 9, "stale": 1, "inbox": 0},
            "intent": {"entries": 31, "products": 14, "recent": 4},
            "corrections": {"total": 58, "last30": 17, "repos": 6},
            "taste": {"total": 22, "repos": 5, "fix": 12, "rule": 7, "reject": 3},
        },
    },
}


def main() -> None:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data["console"] = CONSOLE
    SAMPLE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
