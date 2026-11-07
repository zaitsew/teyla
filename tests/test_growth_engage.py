"""`teyla growth engage`: the targets file, one cached X scan a day, feeds, angles that stay angles, and `done` rows
in the activity ledger. grok and the feeds are fakes; no test reaches X or a feed."""
from __future__ import annotations

import json

import pytest

from teyla import cli, growth, growth_engage as ge, net
from test_growth import NOW, env  # noqa: F401

DAY = growth.day_of(NOW)

TARGETS = """
[founders]
x = ["@alice_builds", "@your_founder_1"]
rss = ["https://alice.substack.com/feed"]
[c-level]
x = ["@cto_bob"]
[investors]
x = ["@vc_carol"]
[builders]
x = ["@dev_dan", "not a handle!"]
"""

RSS = f"""<?xml version="1.0"?><rss><channel>
<item><title>Why agents need a budget</title><link>https://alice.substack.com/p/budget</link>
<pubDate>{growth.day_of(NOW)}T08:00:00Z</pubDate></item>
<item><title>Old post</title><link>https://alice.substack.com/p/old</link><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
</channel></rss>""".encode()


def setup(text=TARGETS):
    store = growth.Store()
    store.ensure()
    (store.root / "config.toml").write_text('public_products = ["alpha"]\n')
    ge.targets_path(store).write_text(text)
    return store, growth.load_config(store)


def grok_reply(posts, feeds=()):
    calls = []

    def run(prompt, model, timeout=1):
        calls.append(prompt)
        return 0, "Here you go:\n" + json.dumps({"posts": posts, "feeds": list(feeds)})
    run.calls = calls
    return run


POSTS = [
    {"url": "https://x.com/alice_builds/status/111111", "author": "alice_builds", "date": DAY, "text": "Agents cost more than people think",
     "angle": "Ask what she counts as cost: tokens, reviews or rework"},
    {"url": "https://x.com/cto_bob/status/222222", "author": "cto_bob", "date": DAY, "text": "Hiring for AI-native roles", "angle": "Share one number from your own agent fleet"},
    {"url": "https://x.com/someone_else/status/333333", "author": "someone_else", "date": DAY, "text": "not a target", "angle": "x"},
    {"url": "https://evil.example/alice_builds/status/444444", "author": "alice_builds", "date": DAY, "text": "wrong host", "angle": "x"},
    {"url": "https://twitter.com/vc_carol/status/555555", "author": "vc_carol", "date": DAY, "text": "Seed rounds",
     "angle": '"Great post! Totally agree with everything here and I would love to connect with you about all of it soon, thanks so much for sharing this wonderful insight with everyone"'},
]


def test_targets_skip_placeholders_and_bad_handles(env):
    store, _ = setup()
    t = ge.load_targets(store)
    assert t["groups"]["founders"]["x"] == ["alice_builds"] and t["placeholders"] == 1
    assert any("not an X handle" in e for e in t["errors"])


def test_the_example_file_is_all_placeholders(env):
    store, _ = setup(ge.EXAMPLE)
    t = ge.load_targets(store)
    assert all(not s["x"] and not s["rss"] for s in t["groups"].values()) and t["placeholders"] >= 7


def test_build_validates_the_scan_and_caches_the_day(env):
    store, cfg = setup()
    grok = grok_reply(POSTS, [{"url": "https://alice.substack.com/p/budget", "angle": "Add the number your own budget cap saved"}])
    doc = ge.build(store, cfg, NOW, grok=grok, fetch=lambda url, timeout=10: RSS)
    urls = [r["url"] for r in doc["rows"]]
    assert "https://x.com/alice_builds/status/111111" in urls and "https://x.com/cto_bob/status/222222" in urls
    assert not any("someone_else" in u or "evil" in u for u in urls)
    assert "https://x.com/vc_carol/status/555555" in urls        # twitter.com is normalised to x.com
    carol = next(r for r in doc["rows"] if r["author"] == "@vc_carol")
    assert carol["angle"] == ""                                  # a quoted, long reply is not an angle
    feed = next(r for r in doc["rows"] if r["source"] == "rss")
    assert feed["url"].endswith("/budget") and feed["angle"].startswith("Add the number")
    assert not any(r["url"].endswith("/old") for r in doc["rows"])
    assert [r["n"] for r in doc["rows"]] == list(range(1, len(doc["rows"]) + 1))
    assert doc["rows"][0]["group"] == "founders" and doc["rows"][1]["group"] == "c-level"     # one group at a time
    assert "@alice_builds" in grok.calls[0] and "Never write the reply itself" in grok.calls[0]
    assert "your_founder_1" not in grok.calls[0]
    # the second run of the day reads the cache: no call
    again = ge.build(store, cfg, NOW, grok=lambda *a, **k: pytest.fail("scanned twice"), fetch=lambda *a, **k: pytest.fail("fetched twice"))
    assert again["rows"] == doc["rows"]


def test_the_x_scan_is_budgeted(env):
    store, cfg = setup()
    grok = grok_reply(POSTS)
    rss = lambda url, timeout=10: RSS
    ge.build(store, cfg, NOW, grok=grok, fetch=rss)
    ge.build(store, cfg, NOW, refresh=True, grok=grok, fetch=rss)
    doc = ge.build(store, cfg, NOW, refresh=True, grok=grok, fetch=rss)
    assert len(grok.calls) == 2 and "2 X scans today" in doc["sources"]["x"]


def test_safe_mode_scans_nothing(env, monkeypatch):
    store, cfg = setup()
    monkeypatch.setattr(net, "allowed", lambda cfg=None: False)
    doc = ge.build(store, cfg, NOW, grok=lambda *a, **k: pytest.fail("scan"), fetch=lambda *a, **k: pytest.fail("feed"))
    assert doc["rows"] == [] and "safe mode" in doc["sources"]["x"] and "safe mode" in doc["sources"]["rss"]


def test_no_scan_and_no_targets(env):
    store = growth.Store()
    store.ensure()
    doc = ge.build(store, growth.load_config(store), NOW)
    assert doc["rows"] == [] and "engage init" in doc["sources"]["x"]
    doc = ge.build(store, growth.load_config(store), NOW, scan=False)
    assert "not scanned today" in doc["sources"]["x"]


def test_done_logs_one_reply_row_by_the_owner_and_is_idempotent(env):
    store, cfg = setup()
    ge.build(store, cfg, NOW, grok=grok_reply(POSTS), fetch=lambda url, timeout=10: RSS)
    doc, new = ge.mark_done(store, [1, 2], NOW)
    assert len(new) == 2 and doc["done"] == 2
    row = [r for r in store.ledger() if r["ev"] == "attempt"][-1]
    assert row["kind"] == "reply" and row["by"] == "owner" and row["n"] == 2 and len(row["engage_urls"]) == 2
    _, again = ge.mark_done(store, [1], NOW)
    assert again == [] and len([r for r in store.ledger() if r["ev"] == "attempt"]) == 1
    a = growth.activity(store.ledger(), DAY, 1)
    assert a["today_count"] == 2 and a["by_kind"]["reply"] == 2
    with pytest.raises(ge.EngageError):
        ge.mark_done(store, [99], NOW)
    assert ge.counts(store, NOW) == {"day": DAY, "scanned": True, "total": doc["total"], "done": 2, "goal": 20}


def test_done_from_an_agent_session_is_a_claim(env, monkeypatch):
    from teyla import startup
    store, cfg = setup()
    ge.build(store, cfg, NOW, grok=grok_reply(POSTS), fetch=lambda url, timeout=10: RSS)
    monkeypatch.setenv(startup.AGENT_ENV[0], "1")
    ge.mark_done(store, [1], NOW)
    row = [r for r in store.ledger() if r["ev"] == "attempt"][-1]
    assert row["by"] == "agent" and growth.is_claimed(row)


def test_a_url_replied_to_lately_does_not_come_back(env):
    store, cfg = setup()
    store.log("attempt", NOW - 86400, kind="reply", by="owner", engage_urls=["https://x.com/alice_builds/status/111111"])
    doc = ge.build(store, cfg, NOW, grok=grok_reply(POSTS), fetch=lambda url, timeout=10: RSS)
    assert "https://x.com/alice_builds/status/111111" not in [r["url"] for r in doc["rows"]]


def test_a_feed_with_a_doctype_is_not_parsed():
    with pytest.raises(ValueError):
        ge.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>', "https://a.example/feed")


def test_atom_feeds_parse():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link rel="alternate" href="https://b.example/p/1"/>
    <author><name>Eve</name></author><updated>2026-11-03T10:00:00Z</updated></entry></feed>"""
    assert ge.parse_feed(atom, "https://b.example/feed") == [{"title": "T", "url": "https://b.example/p/1", "author": "Eve", "date": "2026-11-03"}]


def test_cli_init_json_and_done(env, monkeypatch, capsys):
    store = growth.Store()
    store.ensure()
    assert cli.main(["growth", "engage", "init"]) == 0
    assert ge.targets_path(store).read_text() == ge.EXAMPLE
    capsys.readouterr()
    assert cli.main(["growth", "engage", "--json", "--no-scan"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == 1 and doc["rows"] == [] and doc["goal"] == 20
    assert cli.main(["growth", "engage", "done", "1"]) == 2
    assert "no list for today" in capsys.readouterr().err
