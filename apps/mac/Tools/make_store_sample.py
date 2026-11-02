#!/usr/bin/env python3
"""Builds Teyla/Store/sample.v3.json, the data the store build shows in sample mode.

The shared fixtures are thin (one question, no running session), and App Review sees only the sample, so
every screen needs content. This takes the made-up version 2 snapshot in tests/fixtures/state.v2.json,
moves its clock to a fixed day, adds two older questions (the "Older" fold) and a `portfolio` with nine
products: the four of the first sample, one per health, and five more so that Home shows all three of its
sections (people use these, being built, quiet). Everything is invented. Run it again when the snapshot
contract changes.

    python3 apps/mac/Tools/make_store_sample.py
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from teyla.portfolio import home_view  # noqa: E402  the ranking is the CLI's; the sample never re-implements it

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


# Two invented icons (48 px JPEG, base64), so the sample shows both an icon and a monogram.
ICON_INDIGO = "/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAAAMKADAAQAAAABAAAAMAAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgAMAAwAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMABAQEBAQEBgQEBgkGBgYJDAkJCQkMDwwMDAwMDxIPDw8PDw8SEhISEhISEhUVFRUVFRkZGRkZHBwcHBwcHBwcHP/bAEMBBAUFBwcHDAcHDB0UEBQdHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHf/dAAQAA//aAAwDAQACEQMRAD8A8gApwFAFPAr9nSPKhAAKcBXV+G/A3ivxdvbw9pst3HHkNJ8scQI25XzJCqbvmB253YOcYq54g+HPjXwtai91zSpYLc9ZUKSovIHztEzhMlgBuIyemeay+sUVP2bmubtdX+47IQOKp4FAFOArsSOuED//0PJQK63wP4b/AOEu8V6b4eZ/Lju5f3jA4IijUySbTtb5tinbkEbsZ4rlAK7f4c+ILXwt410rXL4Zt4JSkp5+VJUaJn+VWJ2By2AMnGO+a/YsRzqjN0/is7ettDmhA/Q/StK07Q9Og0nSYFtrS2XZHGnQDqevJJOSSSSSSSSSTVueCC6gktbqNZoZlKSRuAysrDBVgeCCOCD1ognguoI7q1kWaGZQ8ciEMrKwyGUjggjkEdalr8fblzXe50n58/Fbwda+CvF8unafxY3MS3VuhYuyI5KlGJA6OrbeSduMknNecAV6z8Z/E+n+KfGsk+lOs1tYwJaLMjbllKMzsy8DgM5UEEg7dwJBFeUgV+xYD2jw1N1fisrnbTjof//R8pp4FAFOAr9uSKhA9J8HfFbxf4Ktf7P02WK5sRuKW90pdEZyCWQqVcdD8u7bkk4yc1peJ/jP418U6e+lTyQWNtMrJMtojIZVbHyszs7AcYIUrkEhsg4ryYCngVy/UMM6ntXTXN3sdcaaACnAUAU6vQSOyED/2Q=="
ICON_GREEN = "/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAAAMKADAAQAAAABAAAAMAAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgAMAAwAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMABAQEBAQEBgQEBgkGBgYJDAkJCQkMDwwMDAwMDxIPDw8PDw8SEhISEhISEhUVFRUVFRkZGRkZHBwcHBwcHBwcHP/bAEMBBAUFBwcHDAcHDB0UEBQdHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHf/dAAQAA//aAAwDAQACEQMRAD8A8qRKtIlCJVlEq4QPyJsESrSJXTeHfBfifxTvOhafJcpHndJ8qRgjGV8xyqbvmB25zjnGK09a8AeLvDVuLzWdMkhgPWRSsqLyB87RlgmSwA3Yyema64JXsX7Cq4e0UHy97O33nIIlWkShEq0iV3wgcjZ//9Dz1ErsPBfh3/hKfE+n6EX8tLmT942cERopeTacN82xTtyMZxniuZRK7nwBrVv4a8XaZrN4MwQyFZDz8qSo0bPwGJ2Bt2AMnGO9dyg7aH5LQ5HVgqnw3V/S+p936Zplho1hBpelwLb2tuuyONOgHXvySTySeSSSSSaszQw3MMlvcRrLFKpR0cBlZWGCCDwQRwQaIZobmGO4t5FlilUOjoQysrDIII4II5BFS1wn6wkrWWx8SfEbwpbeE/E8tjY8Wk8a3EClizIjEqVJIHRlbHJO3GSTmuLRK9K+KevWXiLxY82nMstvZwrbLKhyshUszMOBwGcqMZBxkHBrz9Er6WhFuC5j8kx3s1iKipfDd2P/0eRRKtIlCJVpEr3YQPxps73wp8RvE/hO2+w2Esc9oNxWC4UsiMxBJUqVYdDxu25JOMnNa2vfFPxZ4ism06Z4bO3lUpKtspUyKccMzM7AcYwpGQSDkV5qiVaRK6I0IN81tTo+vYhU/ZKo+X1BEq0iUIlWkSvRhA85s//Z"

NO_METRICS = {"users": {"total": None, "active": {"7d": None, "30d": None, "365d": None},
                        "new": {"7d": None, "30d": None, "365d": None}},
              "commits": {"7d": None, "30d": None, "365d": None, "weeks": []},
              "spend_usd": {"7d": None, "30d": None, "365d": None},
              "money": {"enabled": False, "mrr_usd": None, "paying": None,
                        "revenue_usd": {"7d": None, "30d": None, "365d": None}}}


def metrics(users=None, commits=None, weeks=(), spend=None):
    """`users` is (total, (active 7d, 30d, 365d), (new 7d, 30d, 365d)); `commits` and `spend` are (7d, 30d, 365d).
    Anything left out is null (not counted), never zero. Monetization is off, as it is for every product."""
    out = json.loads(json.dumps(NO_METRICS))
    if users:
        total, active, new = users
        out["users"] = {"total": total, "active": dict(zip(("7d", "30d", "365d"), active)),
                        "new": dict(zip(("7d", "30d", "365d"), new))}
    if commits:
        out["commits"].update(dict(zip(("7d", "30d", "365d"), commits)), weeks=list(weeks))
    if spend:
        out["spend_usd"] = dict(zip(("7d", "30d", "365d"), spend))
    return out


def add_home(portfolio, extra):
    """Puts `summary`, `icon_jpeg` and `metrics` on every product, then ranks them with the CLI's own rule.
    `extra` maps a product id to (summary, icon, metrics)."""
    for product in portfolio["products"]:
        summary, icon, product_metrics = extra[product["id"]]
        product["summary"] = summary
        product["icon_jpeg"] = icon
        product["metrics"] = product_metrics
    portfolio["home"] = home_view(portfolio["products"])
    return portfolio


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

    def quiet_product(pid, title, stage, primary, last, sessions, spend, next_step=""):
        """A product with nothing to report: one build, nothing waiting."""
        return {"id": pid, "title": title, "stage": stage, "focus": False, "primary": primary, "users": "owner",
                "target": "owner", "health": "parked" if stage == "parked" else "on_track", "reasons": [],
                "platforms": [], "prs": {"open": 0, "waiting": 0, "merged_7d": 0, "unreviewed_7d": 0},
                "activity": {"last": last.strftime(FMT), "sessions_7d": sessions, "spend_7d_usd": spend},
                "waiting": 0, "oldest_wait_days": 0, "tasks": 0, "milestone": "", "next": next_step,
                "repo": f"~/repos/{pid}"}

    products += [
        quiet_product("harbor", "Harbor", "building", "ios", new_now - timedelta(hours=9), 6, 22.5),
        quiet_product("quill", "Quill", "building", "web", new_now - timedelta(days=1), 4, 14.0),
        quiet_product("tidepool", "Tidepool", "building", "ios", new_now - timedelta(days=3), 2, 6.1),
        quiet_product("fernwood", "Fernwood", "parked", "ios", new_now - timedelta(days=40), 0, 0.0),
        quiet_product("ledger", "Ledger", "building", "macos", new_now - timedelta(days=12), 0, 0.0),
        quiet_product("orchard", "Orchard", "live", "web", new_now - timedelta(days=6), 1, 1.2),
    ]
    for pid, title in (("harbor", "Harbor"), ("quill", "Quill"), ("tidepool", "Tidepool"), ("fernwood", "Fernwood"),
                       ("ledger", "Ledger"), ("orchard", "Orchard")):
        row = dict(next(p for p in data["products"] if p["name"] == "lens"))
        row.update(name=pid, id=pid, display_name=title, waiting=0, issues=0, prs_waiting=0, next="", line="",
                   repo=f"~/repos/{pid}", state="idle")
        data["products"].append(row)

    # What Home shows. The week of commits ends with the 7-day count; null means not counted.
    extra = {
        "cellar": ("A pocket sommelier: tracks the bottles you own and learns what you like.", ICON_INDIGO,
                   metrics(users=(9, (3, 5, 7), (1, 3, 9)), commits=(31, 118, 760),
                           weeks=[0, 0, 0, 12, 20, 26, 18, 22, 9, 14, 17, 31], spend=(96.4, 380.0, 2100.0))),
        "atlas": ("Offline maps and packing lists for trips with family.", ICON_GREEN,
                  metrics(users=(5, (2, 3, 5), (0, 1, 5)), commits=(22, 85, 540),
                          weeks=[0, 0, 4, 9, 11, 15, 8, 12, 20, 13, 18, 22], spend=(71.2, 290.0, 1500.0))),
        "teyla": ("Keeps a short list of what needs a person across everything an AI is building.", "",
                  metrics(users=(41, (14, 22, 33), (3, 9, 41)), commits=(18, 70, 610),
                          weeks=[3, 5, 8, 12, 9, 14, 20, 17, 11, 16, 19, 18], spend=(58.0, 240.0, 1700.0))),
        "lens": ("Plans a photo outing and checks each shot against the plan.", "",
                 metrics(commits=(9, 24, 150), weeks=[0, 0, 0, 0, 2, 4, 3, 0, 1, 5, 4, 9], spend=(4.3, 18.0, 90.0))),
        "harbor": ("A tide and weather board for people who sail on weekends.", "",
                   metrics(commits=(7, 20, 90), weeks=[0, 0, 0, 0, 0, 3, 2, 4, 1, 3, 4, 7], spend=(22.5, 60.0, 130.0))),
        "quill": ("A quiet editor for long letters, with a draft that survives a crash.", "",
                  metrics(commits=(5, 31, 77), weeks=[0, 0, 0, 0, 0, 0, 6, 9, 5, 6, 5, 5], spend=(14.0, 70.0, 140.0))),
        "tidepool": ("A shared grocery list that learns which shop has what.", "",
                     metrics(commits=(3, 9, 140), weeks=[10, 12, 9, 8, 6, 4, 3, 2, 2, 1, 1, 3], spend=(6.1, 25.0, 310.0))),
        "fernwood": ("A houseplant diary with watering reminders.", "",
                     metrics(commits=(0, 0, 22), weeks=[0] * 12, spend=(0.0, 0.0, 25.0))),
        "ledger": ("", "", metrics()),
        "orchard": ("A small site that lists the orchards you can visit in autumn.", "",
                    metrics(commits=(1, 6, 40), weeks=[0, 0, 2, 4, 3, 5, 1, 4, 0, 2, 1, 1], spend=(1.2, 5.0, 35.0))),
    }
    data["portfolio"] = add_home({
        "version": 1,
        "checked": {"stores": stamp, "github": github},
        "counts": {"on_track": 6, "at_risk": 2, "off_track": 1, "parked": 1},
        "products": products,
    }, extra)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['asks'])} questions, {len(data['running'])} running, "
          f"{len(data['tasks'])} tasks, {len(data['done'])} done, {len(products)} products")


if __name__ == "__main__":
    main()
