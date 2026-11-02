#!/usr/bin/env python3
"""Gives the iPhone sample (apps/ios/Teyla/Resources/sample-state.json) what the new Home needs.

Home shows three sections (people use these, being built, quiet), a "Show all N" button under the last two, and a
number or a dash for every metric. The sample has to exercise all of that, so this adds invented products to
`portfolio.products`, puts `summary`, `icon_jpeg` and `metrics` on every one, and ranks them with the CLI's own
`home_view`. Everything is invented. It can be run again: products it already added are left as they are.

    python3 apps/ios/Tools/add_home_sample.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "mac" / "Tools"))
# The invented icons and the metrics helpers are the Mac sample's; the ranking is the CLI's. Nothing is copied.
from make_store_sample import ICON_GREEN, ICON_INDIGO, add_home, metrics  # noqa: E402

SAMPLE = ROOT / "apps" / "ios" / "Teyla" / "Resources" / "sample-state.json"
ANCHOR = "2026-11-02T09:00:00Z"   # the sample's own clock; the app moves every timestamp to "now"


def quiet_product(pid, title, stage, primary, last, sessions, spend):
    """A product with one build and nothing waiting."""
    return {"id": pid, "title": title, "stage": stage, "focus": False, "primary": primary, "users": "owner",
            "target": "owner", "health": "parked" if stage == "parked" else "on_track", "reasons": [],
            "platforms": [], "prs": {"open": 0, "waiting": 0, "merged_7d": 0, "unreviewed_7d": 0},
            "activity": {"last": last, "sessions_7d": sessions, "spend_7d_usd": spend},
            "waiting": 0, "oldest_wait_days": 0, "tasks": 0, "milestone": "", "next": "", "repo": f"~/code/{pid}"}


# id -> (title, stage, primary platform) for the products this adds.
NEW = {
    "pebble": ("Pebble", "building", "ios"), "juniper": ("Juniper", "building", "web"),
    "marlin": ("Marlin", "building", "ios"), "cobalt": ("Cobalt", "building", "macos"),
    "saffron": ("Saffron", "building", "web"), "tundra": ("Tundra", "building", "ios"),
    "willow": ("Willow", "building", "ios"),
    "lantern": ("Lantern", "live", "web"), "quartz": ("Quartz", "building", "macos"),
    "ember": ("Ember", "building", "ios"), "nimbus": ("Nimbus", "building", "web"),
    "thistle": ("Thistle", "building", "ios"), "basalt": ("Basalt", "idea", "ios"),
}

# id -> (summary, icon, metrics). Weeks end with the 7-day count; null (None) means "not counted", never zero.
EXTRA = {
    "sample-app": ("Keeps the family's shared lists and plans in one place.", ICON_INDIGO,
                   metrics(users=(12, (4, 6, 9), (1, 3, 8)), commits=(14, 52, 310),
                           weeks=[0, 3, 5, 9, 12, 8, 11, 7, 15, 10, 12, 14], spend=(860.5, 3400.0, 9800.0))),
    "sample-tool": ("A menu bar helper that tidies downloads.", ICON_GREEN,
                    metrics(users=(6, (2, 3, 5), (0, 1, 3)), commits=(6, 22, 140),
                            weeks=[1, 2, 0, 4, 3, 5, 2, 6, 4, 3, 2, 6], spend=(18.0, 70.0, 400.0))),
    "sample-web": ("A booking page for small studios.", "",
                   metrics(users=(3, (1, 1, 3), (None, None, None)), commits=(9, 31, 120),
                           weeks=[0, 0, 2, 4, 6, 3, 5, 8, 4, 7, 6, 9], spend=(240.0, 900.0, 2000.0))),
    "sample-watch": ("A watch face for the quiet hours.", "",
                     metrics(commits=(0, 0, 18), weeks=[0] * 12, spend=(0.0, 0.0, 12.0))),
    "sample-lab": ("A sandbox for trying small ideas before they get a name.", "",
                   metrics(commits=(14, 40, 95), weeks=[0, 0, 0, 3, 5, 4, 8, 6, 9, 7, 11, 14], spend=(12.0, 44.0, 120.0))),
    "pebble": ("Counts steps to a goal you set for a trip.", ICON_INDIGO,
               metrics(commits=(22, 61, 61), weeks=[0, 0, 0, 0, 0, 4, 7, 9, 12, 8, 15, 22], spend=(31.0, 90.0, 90.0))),
    "juniper": ("A recipe box that scales a recipe to the guests.", ICON_GREEN,
                metrics(commits=(17, 48, 120), weeks=[0, 0, 2, 5, 6, 8, 7, 9, 11, 13, 12, 17], spend=(26.5, 80.0, 190.0))),
    "marlin": ("A tide table for people who fish from the shore.", "",
               metrics(commits=(12, 33, 33), weeks=[0] * 6 + [3, 4, 6, 5, 8, 12], spend=(15.2, 40.0, 40.0))),
    "cobalt": ("Turns a folder of notes into a short weekly letter.", "",
               metrics(commits=(9, 28, 80), weeks=[1, 0, 2, 3, 4, 3, 6, 5, 7, 4, 6, 9], spend=(11.0, 35.0, 90.0))),
    "saffron": ("A pantry list that warns before things expire.", "",
                metrics(commits=(8, 19, 19), weeks=[0] * 7 + [2, 3, 4, 2, 8], spend=(9.4, 22.0, 22.0))),
    "tundra": ("Offline maps for a few walking routes.", "",
               metrics(commits=(6, 24, 70), weeks=[2, 0, 3, 4, 2, 5, 4, 6, 3, 5, 5, 6], spend=(7.0, 28.0, 70.0))),
    "willow": ("A habit tracker that never shows a streak.", "",
               metrics(commits=(5, 17, 40), weeks=[0, 0, 1, 2, 3, 2, 4, 3, 2, 4, 3, 5], spend=(5.5, 20.0, 45.0))),
    "lantern": ("A reading list that remembers where you stopped.", ICON_GREEN,
                metrics(commits=(4, 12, 55), weeks=[1, 2, 3, 0, 4, 2, 5, 3, 2, 4, 3, 4], spend=(4.0, 14.0, 60.0))),
    "quartz": ("A clipboard history that forgets on purpose.", "",
               metrics(commits=(3, 15, 30), weeks=[0, 0, 2, 1, 3, 2, 4, 2, 1, 3, 2, 3], spend=(3.2, 16.0, 33.0))),
    "ember": ("A timer for the last hour before bed.", "",
              metrics(commits=(2, 9, 22), weeks=[0, 1, 1, 2, 3, 1, 2, 1, 0, 2, 3, 2], spend=(2.1, 9.0, 24.0))),
    "nimbus": ("A weather page with only the next six hours.", "",
               metrics(commits=(1, 6, 16), weeks=[0, 0, 1, 2, 1, 0, 3, 2, 1, 2, 1, 1], spend=(1.0, 5.0, 17.0))),
    "thistle": ("A garden journal with photos by date.", "",
                metrics(commits=(0, 0, 9), weeks=[0] * 12, spend=(0.0, 0.0, 8.0))),
    "basalt": ("", "", metrics()),
}


def main():
    text = SAMPLE.read_text()
    data = json.loads(text)
    portfolio = data["portfolio"]
    known = {p["id"] for p in portfolio["products"]}
    spend = {pid: extra[2]["spend_usd"]["7d"] for pid, extra in EXTRA.items()}
    for pid, (title, stage, primary) in NEW.items():
        if pid not in known:
            portfolio["products"].append(quiet_product(pid, title, stage, primary, ANCHOR, 1, spend[pid] or 0.0))
    # A product's 7-day spend on the product page is the same number Home shows.
    for product in portfolio["products"]:
        if product["id"] in spend and spend[product["id"]] is not None:
            product["activity"]["spend_7d_usd"] = spend[product["id"]]
    portfolio["counts"] = {key: sum(1 for p in portfolio["products"] if p["health"] == key)
                           for key in ("on_track", "at_risk", "off_track", "parked")}
    add_home(portfolio, EXTRA)
    out = json.dumps(data, indent=2, ensure_ascii=False)
    SAMPLE.write_text(out)
    sections = {s["id"]: len(s["ids"]) for s in portfolio["home"]["sections"]}
    print(f"wrote {SAMPLE.relative_to(ROOT)}: {len(portfolio['products'])} products, sections {sections}")


if __name__ == "__main__":
    main()
