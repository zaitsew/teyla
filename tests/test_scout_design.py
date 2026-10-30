"""teyla scout design: sources, feed parsing, the weekly file, proposals and their caps. Feeds are fixtures; `_fetch` and the
model call are replaced, so nothing here touches the network or starts a real claude."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3

import pytest

from teyla import cli, review, routine_install, scout_design as sd, taste

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 30)          # a Friday, ISO week 2026-W44

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Example news</title>
<item><title>Tab bars lose their labels on small screens</title><link>https://news.example.com/tab-bars</link>
<pubDate>Wed, 28 Oct 2026 09:00:00 +0000</pubDate>
<description><![CDATA[<p>The tab bar now hides its labels in compact widths. Apps with a custom tab bar must retest it.</p>]]></description></item>
<item><title>Old story</title><link>https://news.example.com/old</link><pubDate>Mon, 05 Oct 2026 09:00:00 +0000</pubDate><description>Too old.</description></item>
<item><title>Insecure link</title><link>http://news.example.com/insecure</link><pubDate>Wed, 28 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>Copy rules for empty states</title><link>https://news.example.com/empty</link>
<pubDate>Thu, 29 Oct 2026 10:00:00 +0000</pubDate><description>An empty state names the next step. Keep the button label to a verb.</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Example blog</title>
<entry><title>Dynamic Type at the largest size</title>
<link rel="related" href="https://blog.example.com/related"/><link rel="alternate" href="https://blog.example.com/dynamic-type"/>
<updated>2026-10-27T08:30:00Z</updated><summary>Text must not truncate at the largest Dynamic Type size; test it on a device.</summary></entry>
</feed>"""

HIG = json.dumps({"metadata": {"title": "Buttons", "customMetadata": {"alert-date": "2026-10-29", "alert-text": "Clarified guidance on button labels."}}}).encode()

SOURCES = """# Sources

## Read every week

| Source | Kind | URL | Pages | How |
|---|---|---|---|---|
| Example News | rss | https://news.example.com/feed.xml | | news |
| Example Blog | atom | https://blog.example.com/atom.xml | | blog |
| Example HIG | hig | https://docs.example.com/hig/<slug>.json | buttons, tab-bars | pages |
| Some page | html | https://page.example.com/ | | by hand |

## Needs a priced yes (X reads cost $0.005 a post)

| Source | Kind | URL | Pages | How |
|---|---|---|---|---|
| @someone | x | https://x.com/someone | | no |
| Sneaky | rss | https://sneaky.example.com/feed.xml | | skipped: it sits in the priced section |
"""

FEEDS = {"https://news.example.com/feed.xml": RSS, "https://blog.example.com/atom.xml": ATOM,
         "https://docs.example.com/hig/buttons.json": HIG}


@pytest.fixture
def sources(tmp_path):
    p = tmp_path / "SOURCES.md"
    p.write_text(SOURCES)
    return p


@pytest.fixture
def fetched(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        if url in FEEDS:
            return FEEDS[url]
        raise OSError("404 not found")

    monkeypatch.setattr(sd, "_fetch", fake)
    return calls


class FakeModel:
    def __init__(self, rule="Every empty state names the next step in a verb.", code=0):
        self.rule, self.code, self.calls = rule, code, []

    def __call__(self, cmd, input_text):
        self.calls.append((cmd, json.loads(input_text)))
        if self.code:
            return self.code, ""
        body = json.dumps({"rule": self.rule, "why": "The item states the rule the screen broke."})
        return 0, json.dumps({"type": "result", "is_error": False, "result": body, "total_cost_usd": 0.01})


@pytest.fixture
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(sd, "_run", m)
    return m


COMMENTS = ("The empty state has no next step and the button label is long.",
            "The tab bar labels are cut off on a small screen.",
            "Text truncates at the largest Dynamic Type size.")


def product(tmp_path, comments=COMMENTS, day="2026-10-20"):
    repo = tmp_path / "atlas"
    repo.mkdir(exist_ok=True)
    (repo / "DESIGN.md").write_text("# Design: Atlas\n")
    for n, comment in enumerate(comments):
        did = f"3f9a1c2{n}-5b7e-4d0a-9c1e-2a6b8d4f0e11"
        taste.write_json(taste.decision_path(repo, did),
                         {"id": did, "date": day, "screen": "home", "element": "", "comment": comment,
                          "decision": "rule", "reason": "A pattern.", "scope": "screen:home", "rule": "A rule.",
                          "capture": "x", "pr": "", "confirmed": False})
    return repo


ORIGINAL_CHECK_PROBLEMS = sd.check_problems


@pytest.fixture(autouse=True)
def no_ux_check(monkeypatch):
    """Runs see only the decisions a test writes; the ux check problem has its own test."""
    monkeypatch.setattr(sd, "check_problems", lambda repo, today: [])


# --- the sources ----------------------------------------------------------------------------------

def test_parse_sources_reads_feeds_and_hig_pages_and_skips_the_priced_section(sources):
    rows = sd.parse_sources(sources.read_text())
    assert [(r["name"], r["kind"]) for r in rows] == [("Example News", "rss"), ("Example Blog", "atom"), ("Example HIG", "hig")]
    urls = [t["url"] for t in sd.targets(rows)]
    assert urls == ["https://news.example.com/feed.xml", "https://blog.example.com/atom.xml",
                    "https://docs.example.com/hig/buttons.json", "https://docs.example.com/hig/tab-bars.json"]


def test_the_shipped_sources_list_the_feeds_that_answered_and_keep_x_off():
    text = (ROOT / "templates" / "design" / "SOURCES.md").read_text()
    rows = sd.parse_sources(text)
    names = {r["name"] for r in rows}
    for want in ("Apple Developer News", "Apple Developer Releases", "Apple Newsroom", "MacStories", "Daring Fireball", "Nielsen Norman Group",
                 "Smashing Magazine", "UX Collective", "iOS Dev Weekly", "SwiftLee", "Swift with Majid", "Sarunw", "Lenny's Newsletter"):
        assert want in names, want
    hig = next(r for r in rows if r["kind"] == "hig")
    assert "<slug>" in hig["url"] and "writing" in hig["pages"]
    assert all(r["url"].startswith("https://") and "x.com" not in r["url"] for r in rows)
    assert "## Needs a priced yes (X reads cost $0.005 a post)" in text
    section = text.split("## Needs a priced yes", 1)[1]
    for account in ("@viticci", "@Dimillian", "@drbarnard"):
        assert account in section and account not in text.split("## Needs a priced yes", 1)[0]
    assert "Apple Design Awards" in text and "developer.apple.com/design/awards" in text


# --- parsing --------------------------------------------------------------------------------------

def test_parse_feed_reads_rss_with_cdata_and_atom_alternate_links():
    items = sd.parse_feed(RSS)
    assert [i["title"] for i in items] == ["Tab bars lose their labels on small screens", "Old story", "Copy rules for empty states"]
    assert items[0]["date"] == dt.date(2026, 10, 28) and "<p>" in items[0]["summary"]
    a = sd.parse_feed(ATOM)
    assert a[0]["url"] == "https://blog.example.com/dynamic-type" and a[0]["date"] == dt.date(2026, 10, 27)


def test_parse_feed_refuses_entities_and_garbage():
    with pytest.raises(ValueError, match="entities"):
        sd.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>')
    with pytest.raises(ValueError, match="not XML"):
        sd.parse_feed(b"<html><body>")


def test_one_line_strips_tags_and_cuts_at_the_first_sentence():
    assert sd.one_line("<p>The tab bar now hides its labels.  Apps must retest it.</p>") == "The tab bar now hides its labels."
    long = sd.one_line("word " * 100)
    assert len(long) <= sd.LINE_CHARS and long.endswith("…")


def test_parse_hig_reads_the_alert_note_and_ignores_pages_without_one():
    it = sd.parse_hig(HIG, "buttons")[0]
    assert it["title"] == "HIG: Buttons" and it["date"] == dt.date(2026, 10, 29)
    assert it["url"] == "https://developer.apple.com/design/human-interface-guidelines/buttons" and "button labels" in it["summary"]
    assert sd.parse_hig(json.dumps({"metadata": {"title": "X"}}).encode(), "x") == []
    with pytest.raises(ValueError):
        sd.parse_hig(b"[]", "x")


def test_window_labels_the_iso_week():
    assert sd.window(None, TODAY) == ("2026-W44", dt.date(2026, 10, 24), TODAY)
    assert sd.window("2026-W43", TODAY) == ("2026-W43", dt.date(2026, 10, 19), dt.date(2026, 10, 25))
    for bad in ("2026-44", "W44", "2026-W99"):
        with pytest.raises(ValueError):
            sd.window(bad, TODAY)


def test_pick_takes_turns_across_sources_dedupes_and_caps_at_20():
    items = [{"title": f"a{i}", "url": f"https://a.example.com/{i}", "date": dt.date(2026, 10, 28), "source": "A", "summary": ""} for i in range(30)]
    items += [{"title": "b0", "url": "https://b.example.com/0", "date": dt.date(2026, 10, 27), "source": "B", "summary": ""},
              {"title": "dup", "url": "https://a.example.com/1", "date": dt.date(2026, 10, 28), "source": "B", "summary": ""}]
    out = sd.pick(items)
    assert len(out) == sd.MAX_ITEMS and any(i["source"] == "B" for i in out)
    assert len({i["url"] for i in out}) == len(out)


# --- a run ----------------------------------------------------------------------------------------

def run(tmp_path, sources, **kw):
    if "repos" not in kw:
        kw["repos"] = [str(product(tmp_path))]
    return sd.run(week=kw.pop("week", None), today=TODAY, sources_file=sources, root=tmp_path / "scout", **kw)


def test_a_run_writes_the_weekly_file_with_the_items_in_the_window(tmp_path, sources, fetched, model):
    res = run(tmp_path, sources)
    text = pathlib.Path(res["file"]).read_text()
    assert res["week"] == "2026-W44" and pathlib.Path(res["file"]).name == "2026-W44.md"
    assert res["listed"] == 4 and res["found"] == 4 and res["read"] == 3 and len(res["failed"]) == 1      # tab-bars.json 404
    assert "Tab bars lose their labels on small screens" in text and "Old story" not in text and "Insecure link" not in text
    assert "(Example News, 2026-10-28) <https://news.example.com/tab-bars>" in text
    assert "The tab bar now hides its labels in compact widths." in text
    assert "## Not read" in text and "tab-bars" in text
    assert "https://sneaky.example.com/feed.xml" not in fetched and "https://x.com/someone" not in fetched and "https://page.example.com/" not in fetched


def test_proposals_need_a_product_problem_and_are_capped_at_two_a_week(tmp_path, sources, fetched, model):
    res = run(tmp_path, sources)
    assert len(res["proposals"]) == 2
    root = tmp_path / "scout" / "proposals"
    files = sorted(root.glob("*.md"))
    assert len(files) == 2 and all(f.name.startswith("2026-10-30-") for f in files)
    body = files[0].read_text() + files[1].read_text()
    assert "Week: 2026-W44" in body and "> " in body and "## Product problem it meets" in body
    assert "atlas" in body and "design/decisions/3f9a1c2" in body
    assert "Every empty state names the next step in a verb." in body and "Source: Example" in body
    assert "Nothing is applied until a person opens a PR" in body
    assert len(model.calls) >= 2
    cmd, payload = model.calls[0]
    assert cmd[cmd.index("--tools") + 1] == "" and "existing_rules" in payload and payload["problem"]["product"] == "atlas"
    # a second run in the same week adds nothing: the cap counts the proposals already written
    again = run(tmp_path, sources)
    assert again["proposals"] == [] and len(list(root.glob("*.md"))) == 2


def test_no_problem_in_the_last_30_days_means_no_proposal(tmp_path, sources, fetched, model):
    repo = product(tmp_path, day="2026-08-01")
    res = run(tmp_path, sources, repos=[str(repo)])
    assert res["proposals"] == [] and res["problems"] == 0 and not model.calls
    assert "None this run" in pathlib.Path(res["file"]).read_text()


def test_a_rejected_decision_is_not_a_problem(tmp_path):
    repo = product(tmp_path)
    for p in (repo / "design" / "decisions").glob("*.json"):
        d = json.loads(p.read_text())
        d["decision"] = "reject"
        p.write_text(json.dumps(d))
    assert sd.decision_problems(repo, TODAY) == []


def test_the_model_can_veto_a_match(tmp_path, sources, fetched, monkeypatch):
    monkeypatch.setattr(sd, "_run", FakeModel(rule=""))
    res = run(tmp_path, sources)
    assert res["proposals"] == [] and not list((tmp_path / "scout" / "proposals").glob("*.md"))


def test_no_model_writes_the_proposal_without_a_drafted_rule(tmp_path, sources, fetched, monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(sd, "_run", m)
    res = run(tmp_path, sources, use_model=False)
    assert len(res["proposals"]) == 2 and not m.calls
    assert "not drafted" in next((tmp_path / "scout" / "proposals").glob("*.md")).read_text()


def test_an_unavailable_model_is_asked_once_not_every_time(tmp_path, sources, fetched, monkeypatch):
    m = FakeModel(code=127)
    monkeypatch.setattr(sd, "_run", m)
    res = run(tmp_path, sources)
    assert len(res["proposals"]) == 2 and len(m.calls) == 1


def test_the_scout_edits_no_product_file(tmp_path, sources, fetched, model):
    repo = product(tmp_path)

    def snapshot():
        return {str(p.relative_to(repo)): p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file()}

    before = snapshot()
    run(tmp_path, sources, repos=[str(repo)])
    assert snapshot() == before


def test_proposals_older_than_30_days_are_deleted_on_the_next_run(tmp_path, sources, fetched, model):
    d = tmp_path / "scout" / "proposals"
    d.mkdir(parents=True)
    old, new, other = d / "2026-09-20-old.md", d / "2026-10-05-new.md", d / "notes.md"
    for f in (old, new, other):
        f.write_text("Week: 2026-W40\n")
    res = run(tmp_path, sources)
    assert res["pruned"] == ["2026-09-20-old.md"]
    assert not old.exists() and new.exists() and other.exists()
    assert "Deleted 1 proposal(s)" in pathlib.Path(res["file"]).read_text()


def test_an_item_is_never_proposed_twice(tmp_path, sources, fetched, model):
    run(tmp_path, sources)
    scout = tmp_path / "scout"
    first = {e["url"] for e in sd.existing_proposals(scout)}
    assert len(first) == 2
    for f in (scout / "proposals").glob("*.md"):               # pretend they were written in an earlier week
        f.write_text(f.read_text().replace("Week: 2026-W44", "Week: 2026-W43"))
    res = run(tmp_path, sources)
    second = {e["url"] for e in sd.existing_proposals(scout) if e["week"] == "2026-W44"}
    assert res["proposals"] and second and not (first & second)


def test_captures_in_the_review_queue_are_problems_and_the_queue_is_never_created(tmp_path):
    assert sd.capture_problems(TODAY) == [] and not review.queue_path().exists()
    conn = review.connect()
    conn.execute("INSERT INTO captures (id, product, screen, source, comment, status, created_at, imported_at, data, dir) "
                 "VALUES ('c1c1c1c1-0000-4000-8000-000000000001', 'atlas', 'home', 'relay', 'The tab bar labels are cut off', 'new', "
                 "'2026-10-25T10:00:00Z', '2026-10-25T10:00:00Z', '{}', '/x')")
    conn.execute("INSERT INTO captures (id, product, screen, source, comment, status, created_at, imported_at, data, dir) "
                 "VALUES ('c2c2c2c2-0000-4000-8000-000000000002', 'atlas', 'home', 'relay', 'old comment', 'new', "
                 "'2026-08-25T10:00:00Z', '2026-08-25T10:00:00Z', '{}', '/x')")
    conn.close()
    got = sd.capture_problems(TODAY)
    assert [g["text"] for g in got] == ["The tab bar labels are cut off"] and got[0]["kind"] == "capture"


def test_a_ux_check_fix_is_a_problem(tmp_path):
    repo = tmp_path / "ui"
    (repo / "App").mkdir(parents=True)
    (repo / "App" / "Home.swift").write_text('import SwiftUI\nstruct Home: View { var body: some View { Text("Hi") } }\n')
    (repo / "DESIGN.md").write_text("# Design\n" + "line\n" * 120)
    got = ORIGINAL_CHECK_PROBLEMS(repo, TODAY)
    assert [g["kind"] for g in got] == ["ux check FIX"] and "DESIGN.md" in got[0]["text"]


def test_match_needs_a_topic_word_and_one_more(tmp_path):
    item = {"title": "Tab bars lose their labels", "summary": "Retest the custom tab bar."}
    assert sd.match(item, {"text": "The tab bar labels are cut off"}) > 0
    assert sd.match(item, {"text": "The invoice total is wrong"}) == 0
    assert sd.match({"title": "A long story", "summary": "Nothing about screens."}, {"text": "Story about nothing"}) == 0


# --- the command and the routine ------------------------------------------------------------------

def test_dry_lists_the_urls_and_fetches_nothing(sources, fetched, capsys):
    assert cli.main(["scout", "design", "--sources", str(sources), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "would read 4 feed or page request(s)" in out and "https://docs.example.com/hig/tab-bars.json" in out
    assert not fetched


def test_cli_writes_the_file_and_prints_one_line(tmp_path, sources, fetched, model, monkeypatch, capsys):
    monkeypatch.setattr(sd, "scout_home", lambda: tmp_path / "scout")
    repo = product(tmp_path)
    assert cli.main(["scout", "design", "--sources", str(sources), "--repo", str(repo), "--week", "2026-W44"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("2026-W44:") and "proposal(s)" in out
    assert (tmp_path / "scout" / "2026-W44.md").is_file()


def test_safe_mode_closes_it_and_quiet_stays_silent(sources, fetched, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert cli.main(["scout", "design", "--sources", str(sources)]) == 1
    assert "safe mode" in capsys.readouterr().err
    assert cli.main(["scout", "design", "--sources", str(sources), "--quiet"]) == 0
    assert capsys.readouterr().err == "" and not fetched


def test_every_source_failing_is_exit_1(tmp_path, sources, monkeypatch, capsys):
    monkeypatch.setattr(sd, "_fetch", lambda url: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(sd, "scout_home", lambda: tmp_path / "scout")
    assert cli.main(["scout", "design", "--sources", str(sources), "--no-model", "--repo", str(tmp_path)]) == 1
    assert "no source could be read" in capsys.readouterr().err


def test_a_bad_week_is_a_usage_error(sources, capsys):
    assert cli.main(["scout", "design", "--sources", str(sources), "--week", "soon"]) == 2


def test_fetch_refuses_anything_but_https():
    with pytest.raises(ValueError):
        sd._fetch("http://example.com/feed")
    with pytest.raises(ValueError):
        sd._fetch("file:///etc/passwd")


def test_the_weekly_wrapper_runs_the_scout_and_an_old_wrapper_is_stale(tmp_path, monkeypatch):
    text = routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=routine_install._watch_line())
    assert '"$TEYLA" scout design --quiet > "$OUT_DIR/scout-design.md" 2>&1' in text
    assert text.index("reviews --quiet") < text.index("scout design") < text.index("digest --write")
    w = tmp_path / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(text)
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(text.replace('"$TEYLA" scout design --quiet > "$OUT_DIR/scout-design.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")
