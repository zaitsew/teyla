#!/usr/bin/env python3
"""Builds Teyla/Store/sample.v3.json, the data the store build shows in sample mode.

The shared fixtures are thin (one question, no running session), and App Review sees only the sample, so
every screen needs content. This takes the made-up version 2 snapshot in tests/fixtures/state.v2.json,
moves its clock to a fixed day, adds two older questions (the "Older" fold) and a `portfolio` with four
products, one per health. Everything is invented. Run it again when the snapshot contract changes.

    python3 apps/mac/Tools/make_store_sample.py
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "state.v2.json"
OUT = ROOT / "apps" / "mac" / "Teyla" / "Store" / "sample.v3.json"

FMT = "%Y-%m-%dT%H:%M:%SZ"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def parse(text):
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc)


def shift(node, delta):
    """Moves every timestamp by `delta`."""
    if isinstance(node, dict):
        return {k: shift(v, delta) for k, v in node.items()}
    if isinstance(node, list):
        return [shift(v, delta) for v in node]
    if isinstance(node, str) and ISO.match(node):
        return (parse(node) + delta).strftime(FMT)
    return node


def platform(name, role, channel, version, build, state, detail, as_of="", link=""):
    return {"platform": name, "role": role, "channel": channel, "version": version, "build": build,
            "state": state, "detail": detail, "as_of": as_of, "link": link}


def main():
    data = json.loads(SRC.read_text())
    new_now = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)
    data = shift(data, new_now - parse(data["generated"]))
    data["version"] = 3
    data["brief"] = {
        "line": "Two answers unblock Cellar's App Store release today. Atlas is waiting on your first Claude sign-in.",
        "source": "rules",
    }
    # Two older questions fill the "Older" fold.
    for ask_id, product, question, age_days, options in (
        ("a1f09c22", "lens", "Keep the shot list export behind a setting, or ship it on for everyone?", 11,
         ["Behind a setting", "On for everyone"]),
        ("d4e87b10", "atlas", "Which map provider should the offline packs use?", 9, ["Provider A", "Provider B"]),
    ):
        data["asks"].append({
            "id": ask_id, "kind": "question", "product": product, "title": question, "question": question,
            "context": "", "options": options, "archived": False, "link": "", "pr": "", "harness": "codex",
            "status": "open", "ts": (new_now - timedelta(days=age_days)).strftime(FMT),
            "age_s": age_days * 86400, "unblocks": "", "rank": len(data["asks"]) + 1, "delivery": "codex",
            "muted": False,
        })
    data["totals"]["questions"] = len(data["asks"])
    by_product = {}
    for ask in data["asks"]:
        by_product[ask["product"]] = by_product.get(ask["product"], 0) + 1
    for product in data["products"]:
        product["waiting"] = by_product.get(product["name"], 0)

    stamp = (new_now - timedelta(hours=3)).strftime(FMT)
    github = (new_now - timedelta(minutes=40)).strftime(FMT)
    products = [
        {"id": "cellar", "title": "Cellar", "stage": "building", "focus": True, "primary": "ios", "users": "testers",
         "target": "public", "health": "off_track",
         "reasons": ["iPhone build 15 is waiting for App Review's answer", "A question has waited 2 days",
                     "Android is 1 build behind"],
         "platforms": [
             platform("ios", "primary", "testflight", "1.1.0", "18", "blocked",
                      "In App Review since Friday; only you can swap the build", stamp),
             platform("macos", "secondary", "app_store", "1.0.0", "16", "live", "Version 1.0.0 is on the Mac App Store", stamp),
             platform("android", "secondary", "play", "1.0.0", "4", "behind", "Build 4 needs a tester email", stamp)],
         "prs": {"open": 2, "waiting": 0, "merged_7d": 9, "unreviewed_7d": 0},
         "activity": {"last": (new_now - timedelta(hours=5)).strftime(FMT), "sessions_7d": 14, "spend_7d_usd": 96.4},
         "waiting": 2, "oldest_wait_days": 2.0, "tasks": 1,
         "milestone": "public: 3 of 11 requirements left", "next": "Swap the iPhone review to 1.1",
         "repo": "~/repos/cellar"},
        {"id": "atlas", "title": "Atlas", "stage": "building", "focus": False, "primary": "ios", "users": "family",
         "target": "family", "health": "at_risk",
         "reasons": ["A question has waited 9 days", "The newest build is on TestFlight, not yet with a tester"],
         "platforms": [
             platform("ios", "primary", "testflight", "1.1.5", "126", "current", "Installable from your tester account", stamp),
             platform("web", "secondary", "web", "", "", "live", "atlas.example.com", "", "https://atlas.example.com")],
         "prs": {"open": 1, "waiting": 0, "merged_7d": 6, "unreviewed_7d": 1},
         "activity": {"last": (new_now - timedelta(minutes=20)).strftime(FMT), "sessions_7d": 11, "spend_7d_usd": 71.2},
         "waiting": 2, "oldest_wait_days": 9.0, "tasks": 0,
         "milestone": "family: 2 of 9 requirements left", "next": "Ship the PDF export in the next TestFlight build",
         "repo": "~/repos/atlas"},
        {"id": "teyla", "title": "Teyla", "stage": "live", "focus": False, "primary": "macos", "users": "public",
         "target": "public", "health": "on_track", "reasons": [],
         "platforms": [
             platform("macos", "primary", "local", "0.31.0", "", "current", "Installed on this Mac", ""),
             platform("ios", "secondary", "testflight", "0.32.0", "3", "current", "Installable from your tester account", stamp)],
         "prs": {"open": 0, "waiting": 0, "merged_7d": 12, "unreviewed_7d": 0},
         "activity": {"last": (new_now - timedelta(hours=2)).strftime(FMT), "sessions_7d": 18, "spend_7d_usd": 58.0},
         "waiting": 0, "oldest_wait_days": 0, "tasks": 0, "milestone": "", "next": "", "repo": "~/repos/teyla"},
        {"id": "lens", "title": "Lens", "stage": "building", "focus": False, "primary": "ios", "users": "owner",
         "target": "owner", "health": "at_risk",
         "reasons": ["A pull request waits on your merge", "A question has waited 11 days"],
         "platforms": [platform("ios", "primary", "testflight", "0.4.0", "9", "none", "No build has reached you yet", stamp)],
         "prs": {"open": 1, "waiting": 1, "merged_7d": 2, "unreviewed_7d": 0},
         "activity": {"last": (new_now - timedelta(days=5)).strftime(FMT), "sessions_7d": 1, "spend_7d_usd": 4.3},
         "waiting": 1, "oldest_wait_days": 11.0, "tasks": 1, "milestone": "", "next": "Merge the shot list export",
         "repo": "~/repos/lens"},
    ]
    data["portfolio"] = {
        "version": 1,
        "checked": {"stores": stamp, "github": github},
        "counts": {"on_track": 1, "at_risk": 2, "off_track": 1, "parked": 0},
        "products": products,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['asks'])} questions, {len(data['running'])} running, "
          f"{len(data['tasks'])} tasks, {len(data['done'])} done, {len(products)} products")


if __name__ == "__main__":
    main()
