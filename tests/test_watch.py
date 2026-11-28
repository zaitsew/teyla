"""Frozen controlled Apple-shaped snapshots, not live captures; tests make no network request."""
import argparse
import json
import pathlib

import pytest

from teyla import config, net, routine_install, watch

FIXTURES = pathlib.Path(__file__).parent / "fixtures/watch"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / "state"
    monkeypatch.setenv("TEYLA_HOME", str(home))
    monkeypatch.setenv("TEYLA_SAFE", "0")
    monkeypatch.setattr(net, "_allow_once", False)
    monkeypatch.setattr(net, "_offline", False)
    monkeypatch.setattr(net, "_offline_threads", [])
    products = [{"name": "example", "storefronts": ["us", "gb"], "rows": [
        {"name": "Structured", "app_store_id": 1499198946, "ring": "job", "url": "https://never.invalid/"}]}]
    active = ["week-one"]
    requested = []

    def fetch(url):
        requested.append(url)
        name = "reviews" if "/rss/" in url else active[0]
        return json.loads((FIXTURES / f"{name}.json").read_text())

    monkeypatch.setattr(watch, "_fetch", fetch)
    return home / "watch", products, active, requested


def test_two_weeks_dedupe_state_and_rerun(setup):
    home, products, active, requested = setup
    first = watch.run(products, "2026-W47")
    assert len(requested) == 4
    assert (home / "state/1499198946-us.json").exists()
    assert len(first["products"][0]["changes"]) == 1
    assert first["products"][0]["changes"][0]["storefronts"] == ["gb", "us"]
    active[0] = "week-two"
    second = watch.run(products, "2026-W48")
    changes = second["products"][0]["changes"]
    assert {c["field"] for c in changes} == {"version", "releaseNotes", "description", "screenshotUrls"}
    assert all(c["storefronts"] == ["gb", "us"] for c in changes)
    screenshots = next(c for c in changes if c["field"] == "screenshotUrls")
    assert (screenshots["before_count"], screenshots["after_count"], screenshots["order_changed"]) == (2, 3, True)
    assert len(next(c for c in changes if c["field"] == "description")["diff"]) <= 20
    again = watch.run(products, "2026-W48")
    assert again["products"][0]["changes"] == changes
    assert len(again["quotes"]["1499198946"]) == 3
    assert {q["rating"] for q in again["quotes"]["1499198946"]} == {2, 3, 4}
    assert all(len(q["text"].split()) >= 12 for q in again["quotes"]["1499198946"])
    assert len((home / "2026-W48.md").read_text().splitlines()) <= 32
    assert len((home / "log.jsonl").read_text().splitlines()) == 3
    assert all(url.startswith("https://itunes.apple.com/") for url in requested)


def test_dry_fetches_and_writes_nothing(setup):
    home, products, _, requested = setup
    result = watch.run(products, "2026-W48", dry=True)
    assert len(result["requests"]) == 4
    assert not requested and not home.exists()


def test_failures_preserve_state_and_report_errors(setup, monkeypatch):
    home, products, _, _ = setup
    watch.run(products, "2026-W47")
    baseline = (home / "state/1499198946-us.json").read_bytes()
    monkeypatch.setattr(watch, "_fetch", lambda url: (_ for _ in ()).throw(ValueError("bad response")))
    report = watch.run(products, "2026-W48")
    assert len(report["products"][0]["errors"]) == 4
    assert (home / "state/1499198946-us.json").read_bytes() == baseline


def test_safe_mode_and_output_repo_guard(setup, monkeypatch):
    home, products, _, requested = setup
    monkeypatch.setenv("TEYLA_SAFE", "1")
    with pytest.raises(ValueError, match="network refused"):
        watch.run(products, "2026-W48")
    assert not requested and not home.exists()
    home.parent.mkdir()
    (home.parent / ".git").write_text("gitdir: elsewhere")
    assert len(watch.run(products, "2026-W48", dry=True)["requests"]) == 4
    with pytest.raises(ValueError, match="outside every git"):
        watch.run(products, "2026-W48")


def test_lists_contract_and_frontier(tmp_path, monkeypatch):
    repo = tmp_path / "example/docs"
    repo.mkdir(parents=True)
    text = '[product]\nname="example"\nstorefronts=["us","es"]\n[[watch]]\nname="App"\nring="job"\napp_store_id=123\nurl="https://never.invalid"\n'
    (repo / "watch.toml").write_text(text)
    pb = tmp_path / "playbook/watch"
    pb.mkdir(parents=True)
    (pb / "frontier.toml").write_text('[[watch]]\nname="AI"\nring="frontier"\n')
    monkeypatch.setattr(config, "load", lambda: {"code_root": str(tmp_path)})
    monkeypatch.setenv("TEYLA_PLAYBOOK_ROOT", str(pb.parent))
    rows = watch.lists(["example"], True)
    assert [p["name"] for p in rows] == ["example", "frontier"]
    assert rows[1]["storefronts"] == ["us"]
    with pytest.raises(ValueError, match="directory name"):
        watch.lists(["../example"])
    (repo / "watch.toml").write_text(text.replace('ring="job"', 'ring="frontier"'))
    with pytest.raises(ValueError, match="valid ring"):
        watch.lists(["example"])


def test_transport_bounds_and_redirects(monkeypatch):
    with pytest.raises(ValueError):
        watch._check_url("https://evil.invalid/lookup?id=1")
    with pytest.raises(ValueError):
        watch._Redirect().redirect_request(None, None, 302, "", {}, "http://itunes.apple.com/lookup?id=1")
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count):
            assert count == watch.MAX_BYTES + 1
            return b"x" * count

    class Opener:
        def open(self, req, timeout):
            calls.append((req.get_header("User-agent"), timeout))
            return Response()

    monkeypatch.setattr(net, "allowed", lambda: True)
    monkeypatch.setattr(watch.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError, match="4 MB"):
        watch._fetch("https://itunes.apple.com/lookup?id=1&country=us")
    assert calls == [(watch.USER_AGENT, 15)]


def test_registration_week_and_routine():
    sp = argparse.ArgumentParser().add_subparsers()
    parser = watch.register(sp)
    assert parser.parse_args(["--repo", "example", "--dry", "--json"]).dry
    for week in ("../../outside", "2026-W99", "2026-W1"):
        with pytest.raises(ValueError):
            watch.week_label(week)
    assert '"$TEYLA" watch > "$OUT_DIR/watch.md" 2>&1' in routine_install.WRAPPER_TEMPLATE


def test_subset_keeps_other_products_and_invalid_responses(setup):
    _, products, _, _ = setup
    other = [{**products[0], "name": "another"}]
    watch.run(products + other, "2026-W48")
    report = watch.run(products, "2026-W48")
    assert {p["name"] for p in report["products"]} == {"example", "another"}
    with pytest.raises(ValueError, match="matching app"):
        watch.lookup({"results": [None]}, 123)
    with pytest.raises(ValueError, match="review feed"):
        watch.reviews({"feed": None}, "us")
    with pytest.raises(ValueError, match="review entries"):
        watch.reviews({"feed": {"entry": None}}, "us")


def test_quote_sample_spans_ratings_before_repeating_one(setup, monkeypatch):
    _, products, _, _ = setup
    feed = {"feed": {"entry": [
        {"im:rating": {"label": str(rating)}, "content": {"label":
         f"The timeline helps me plan each day and keep every task in order: sample {index}."}}
        for index, rating in enumerate((3, 3, 3, 5))
    ]}}
    listing = json.loads((FIXTURES / "week-one.json").read_text())
    monkeypatch.setattr(watch, "_fetch", lambda url: feed if "/rss/" in url else listing)
    report = watch.run(products, "2026-W48")
    quotes = report["quotes"]["1499198946"]
    assert len(quotes) == 3
    assert [q["rating"] for q in quotes] == [3, 5, 3]


def test_later_product_and_frontier_replay_weekly_changes(setup):
    _, products, active, _ = setup
    a = {**products[0], "name": "a"}
    b = {**products[0], "name": "b", "storefronts": ["us"]}
    frontier = {**products[0], "name": "frontier", "storefronts": ["us"]}
    watch.run([a, b, frontier], "2026-W47")
    active[0] = "week-two"
    first = watch.run([a], "2026-W48")
    expected = {c["field"] for c in first["products"][0]["changes"]}
    assert expected == {"version", "releaseNotes", "description", "screenshotUrls"}
    for later in (b, frontier):
        report = watch.run([later], "2026-W48")
        result = next(p for p in report["products"] if p["name"] == later["name"])
        assert {c["field"] for c in result["changes"]} == expected
        assert len(result["changes"]) == 4
        assert all(c["storefronts"] == ["us"] for c in result["changes"])
        assert len(report["quotes"]["1499198946"]) == 3
