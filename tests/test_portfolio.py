"""The portfolio of `teyla state` (version 3, docs/APP.md): health rules, platform rows from the store payloads,
the cache fallback, the sort order, and the promise that the snapshot makes no network call. The release tools
and gh are faked; nothing here reaches the network, the real ~/.teyla or this Mac's transcripts."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import pytest

from teyla import asks, backlog, cli, config, net, platform, play, portfolio, reviews, state, testflight

NOW = 1_800_000_000.0
DAY = 86400
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_REAL_SPAWN = portfolio.spawn_refresh                               # conftest replaces it per test
_REAL_COMPUTE_ACTIVITY = portfolio.compute_activity
_REAL_COMPUTE_COMMITS = portfolio.compute_commits
_REAL_COMPUTE_ICONS = portfolio.compute_icons
SHA = "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0"


# --- a fake machine ------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(platform, "PLATFORM_PATH", home / ".teyla" / "platform.toml")
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(net, "_allow_once", False)
    monkeypatch.setattr(portfolio, "compute_activity", lambda reg: {})
    monkeypatch.setattr(portfolio, "compute_commits", lambda reg, now: {})          # real git: see the metrics tests
    monkeypatch.setattr(portfolio, "compute_icons", lambda reg, prev: {})
    tool = tmp_path / "release-tool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    platform.PLATFORM_PATH.write_text(
        f'[apple]\nrelease_tool = "{tool}"\ntester = "me@example.com"\n[android]\nrelease_tool = "{tool}"\n')


def repo(tmp_path, name="app-a", *, toml=None, slug="example/app-a"):
    d = tmp_path / "repos" / name
    (d / ".git").mkdir(parents=True)
    if slug:
        (d / ".git" / "config").write_text(f'[remote "origin"]\n\turl = https://github.com/{slug}.git\n')
    (d / "teyla.toml").write_text(toml if toml is not None else TOML)
    return d


TOML = """[product]
name = "app-a"
[productize]
users = "testers"
target = "family"
platforms = ["ios", "android", "web"]
primary = "ios"
url = "https://sample.example.com"
[productize.distribution]
ios = "testflight-internal"
android = "play-internal"
web = "pwa"
[release]
apple_bundle_id = "com.example.app"
android_package = "com.example.app"
"""


def registry_of(*rows):
    """rows: (id, repo path, stage, focus, primary)"""
    return {"product": {pid: {"name": pid.title(), "repos": [str(path)], "paths": [], "aliases": [],
                              "stage": stage, "primary": primary, "focus": focus}
                        for pid, path, stage, focus, primary in rows}, "assign": {}}


def one(tmp_path, **kw):
    d = repo(tmp_path, **kw)
    return registry_of(("app-a", d, "beta", True, "iOS")), d


def tf_plat(platform_="IOS", *, behind=0, up=("1.9.0", "120"), inst=("1.9.0", "120"), blockers=()):
    return {"platform": platform_,
            "newest_uploaded": None if up is None else {"version": up[0], "build": up[1],
                                                       "uploaded": "2027-01-14T09:30:00Z", "processing": "VALID"},
            "newest_installable": None if inst is None else {"version": inst[0], "build": inst[1], "via": ["Internal"]},
            "behind": behind, "blockers": list(blockers)}


def tf_payload(*plats, found=True):
    return {"bundle_id": "com.example.app", "tester": "me@example.com", "tester_found": found, "platforms": list(plats)}


def rel(code, status="completed", name=None, fraction=None):
    return {"name": name or f"1.9.0 ({code})", "status": status, "version_codes": [code], "user_fraction": fraction}


def play_payload(internal=(), production=()):
    return {"package": "com.example.app", "tracks": [
        {"track": "internal", "label": "internal testing", "releases": list(internal)},
        {"track": "alpha", "label": "closed testing", "releases": []},
        {"track": "beta", "label": "open testing", "releases": []},
        {"track": "production", "label": "production", "releases": list(production)}]}


def fake_tools(monkeypatch, tf=None, pl=None, *, rc=0):
    """`beta reached` answers `tf`, `status` answers `pl`; a non-zero `rc` is a tool that failed."""
    def run(cmd, **kw):
        out = tf if cmd[1] == "beta" else pl
        if out is None:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no answer")
        return subprocess.CompletedProcess(cmd, rc, stdout=json.dumps(out), stderr="tool failed" if rc else "")
    monkeypatch.setattr(testflight.subprocess, "run", run)


def stores(tmp_path, monkeypatch, tf=None, pl=None, **kw):
    reg, _ = one(tmp_path, **kw)
    fake_tools(monkeypatch, tf, pl)
    cache = portfolio.load_cache()
    ok = portfolio.refresh_stores(reg, cache, NOW)
    return reg, cache, ok


def rows_of(cache, pid="app-a"):
    return cache["stores"][pid]


def test_a_product_with_no_play_package_does_not_void_the_whole_store_pass(tmp_path, monkeypatch):
    toml = TOML.replace('android_package = "com.example.app"\n', "")
    reg, cache, ok = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), None, toml=toml)
    assert ok is True and cache["checked"]["stores"] == asks._iso(NOW)      # nothing was read, so nothing failed
    assert rows_of(cache)["android"]["state"] == "unknown"
    assert rows_of(cache)["android"]["detail"] == "No Play package in teyla.toml"
    assert rows_of(cache)["ios"]["state"] == "current"
    good = {"platform": "android", "channel": "play", "state": "current", "detail": "", "as_of": asks._iso(NOW - 60)}
    cache["stores"]["app-a"]["android"] = good                              # another repo of the product read it
    assert portfolio.refresh_stores(reg, cache, NOW) is True
    assert rows_of(cache)["android"] == good


# --- platform rows from the store payloads ----------------------------------------------------------

def test_a_build_the_tester_can_install_is_current(tmp_path, monkeypatch):
    _, cache, ok = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), play_payload(internal=[rel(14)]))
    ios, android = rows_of(cache)["ios"], rows_of(cache)["android"]
    assert ok and cache["checked"]["stores"] == asks._iso(NOW)
    assert (ios["state"], ios["version"], ios["build"], ios["channel"]) == ("current", "1.9.0", "120", "testflight")
    assert ios["detail"] == "Installable from your tester account" and ios["as_of"] == asks._iso(NOW)
    assert (android["state"], android["build"], android["channel"]) == ("current", "14", "play")
    assert android["detail"] == "Installable from Play's internal track"


def test_a_build_the_tester_cannot_install_yet_is_behind(tmp_path, monkeypatch):
    plat = tf_plat(behind=2, up=("1.9.1", "122"), inst=("1.9.0", "120"), blockers=["122: processing", "121: processing"])
    _, cache, _ = stores(tmp_path, monkeypatch, tf_payload(plat), play_payload(internal=[rel(14)]))
    ios = rows_of(cache)["ios"]
    assert (ios["state"], ios["build"], ios["_behind"]) == ("behind", "120", 2)
    assert ios["detail"] == "2 builds wait: Build 122: processing"
    assert ios["_since"] == asks._epoch("2027-01-14T09:30:00Z")        # waiting since the upload


@pytest.mark.parametrize("blocker,detail", [
    ("120: invited to Internal, not accepted — the person taps View in TestFlight in Apple's e-mail once",
     "Invited, not accepted: tap View in TestFlight in Apple's e-mail"),
    ("120: in Internal but never invited — testflight beta invite",
     "In a TestFlight group but never invited: send the invitation again"),
    ("120: not submitted for beta review in Friends", "Build 120: not submitted for beta review in Friends")])
def test_a_gap_only_the_owner_can_close_is_blocked(tmp_path, monkeypatch, blocker, detail):
    plat = tf_plat(behind=1, inst=None, blockers=[blocker])
    _, cache, _ = stores(tmp_path, monkeypatch, tf_payload(plat), play_payload(internal=[rel(14)]))
    ios = rows_of(cache)["ios"]
    assert (ios["state"], ios["detail"]) == ("blocked", detail)


def test_a_tester_who_is_not_on_the_team_blocks_the_platform(tmp_path, monkeypatch):
    _, cache, _ = stores(tmp_path, monkeypatch, tf_payload(found=False), play_payload(internal=[rel(14)]))
    assert rows_of(cache)["ios"]["state"] == "blocked"
    assert "not on the App Store Connect team" in rows_of(cache)["ios"]["detail"]


def test_a_platform_with_no_upload_has_none(tmp_path, monkeypatch):
    _, cache, _ = stores(tmp_path, monkeypatch, tf_payload(tf_plat(up=None, inst=None)), play_payload())
    assert rows_of(cache)["ios"]["state"] == "none" and rows_of(cache)["ios"]["detail"] == "No build uploaded yet"
    assert rows_of(cache)["android"]["state"] == "none"


def test_play_states(tmp_path, monkeypatch):
    draft = play_payload(internal=[rel(14, "draft")])
    _, cache, _ = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), draft)
    a = rows_of(cache)["android"]
    assert a["state"] == "blocked" and a["detail"].startswith("Draft on Play's internal track")
    assert a["review_unknown"] is True                       # the API cannot say whether review passed
    ahead = play_payload(internal=[rel(3)], production=[rel(5)])
    _, cache, _ = stores(tmp_path / "2", monkeypatch, tf_payload(tf_plat()), ahead)
    a = rows_of(cache)["android"]
    assert (a["state"], a["build"], a["review_unknown"]) == ("current", "5", False)   # production is ahead of internal
    assert a["detail"] == "Newest build is on Play production"
    stuck = play_payload(internal=[rel(8, "halted")], production=[rel(5)])
    _, cache, _ = stores(tmp_path / "4", monkeypatch, tf_payload(tf_plat()), stuck)
    assert rows_of(cache)["android"]["state"] == "blocked"   # newer than production and not live: still the owner's
    staged = play_payload(internal=[rel(6)], production=[rel(5, "inProgress", fraction=0.2)])
    _, cache, _ = stores(tmp_path / "3", monkeypatch, tf_payload(tf_plat()), staged)
    a = rows_of(cache)["android"]
    assert a["state"] == "live" and a["detail"] == "Rolling out to users on Play production at 20%"


def test_the_public_platform_rows_follow_the_manifest(tmp_path, monkeypatch):
    reg, cache, _ = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), play_payload(internal=[rel(14)]))
    pf = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache)
    p = pf["products"][0]
    assert [(x["platform"], x["role"], x["channel"], x["state"]) for x in p["platforms"]] == [
        ("ios", "primary", "testflight", "current"), ("android", "secondary", "play", "current"),
        ("web", "secondary", "web", "live")]
    assert p["platforms"][2]["link"] == "https://sample.example.com" and p["platforms"][2]["detail"] == "sample.example.com"
    assert all(set(x) == {"platform", "role", "channel", "version", "build", "state", "detail", "as_of", "link",
                          "review_unknown"} for x in p["platforms"])
    assert (p["users"], p["target"], p["primary"]) == ("testers", "family", "ios")


def test_a_platform_with_no_data_is_unknown_and_local_tools_say_so(tmp_path):
    toml = '[productize]\nusers = "owner"\nplatforms = ["macos", "ios", "web"]\nprimary = "macos"\n[productize.distribution]\nios = "testflight-internal"\n'
    reg, _ = one(tmp_path, toml=toml)
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                        cache=portfolio.load_cache())["products"][0]
    by = {x["platform"]: x for x in p["platforms"]}
    assert [x["platform"] for x in p["platforms"]] == ["macos", "ios", "web"]          # primary first
    assert (by["macos"]["channel"], by["macos"]["state"]) == ("local", "unknown")
    assert (by["ios"]["state"], by["ios"]["detail"]) == ("unknown", "Not checked yet")
    assert (by["web"]["state"], by["web"]["detail"]) == ("unknown", "Not checked yet")  # no URL declared
    assert p["milestone"] == ""                                                         # owner, no target beyond it


def test_a_product_without_a_manifest_takes_the_registry_primary(tmp_path):
    reg, _ = one(tmp_path, toml="")
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                        cache=portfolio.load_cache())["products"][0]
    assert [(x["platform"], x["role"]) for x in p["platforms"]] == [("ios", "primary")]
    assert (p["users"], p["target"]) == ("", "")


def test_the_milestone_counts_the_requirements_left(tmp_path):
    reg, _ = one(tmp_path)
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                        cache=portfolio.load_cache())["products"][0]
    assert p["milestone"].startswith("family: ") and " requirements left" in p["milestone"]


# --- the cache keeps good data ----------------------------------------------------------------------

def test_a_failed_read_keeps_the_old_rows_with_their_old_time(tmp_path, monkeypatch):
    reg, cache, ok = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), play_payload(internal=[rel(14)]))
    portfolio.save_cache(cache)
    first = asks._iso(NOW)
    fake_tools(monkeypatch, None, None)                              # both tools fail now
    cache = portfolio.load_cache()
    assert portfolio.refresh_stores(reg, cache, NOW + 3600) is False
    rows = rows_of(cache)
    assert rows["ios"]["state"] == "current" and rows["ios"]["as_of"] == first
    assert rows["android"]["state"] == "current" and rows["android"]["as_of"] == first
    assert cache["checked"]["stores"] == first                       # the part did not complete


def test_a_failed_first_read_is_unknown_with_the_reason(tmp_path, monkeypatch):
    _, cache, ok = stores(tmp_path, monkeypatch, None, None)
    assert ok is False and cache["checked"]["stores"] == ""
    ios = rows_of(cache)["ios"]
    assert ios["state"] == "unknown" and ios["as_of"] == "" and ios["detail"].startswith("Could not read App Store Connect")


def merged_node(number, *, days_ago=1, sha=SHA, changed=40, files=("src/a.py",)):
    return {"number": number, "title": f"PR {number}", "url": f"https://github.com/example/app-a/pull/{number}",
            "mergedAt": asks._iso(NOW - days_ago * DAY), "additions": changed, "deletions": 0, "headRefOid": sha,
            "mergeCommit": {"oid": "f" * 40}, "files": {"nodes": [{"path": f} for f in files]},
            "commits": {"nodes": [{"commit": {"oid": sha}}]}}


def gh(nodes, opened=(), *, fail=False):
    def runner(argv):
        if fail:
            return 1, "", "gh: network down"
        q = next(a for a in argv if a.startswith("q="))
        if "is:merged" in q:
            return 0, json.dumps({"data": {"search": {"nodes": nodes}}}), ""
        return 0, json.dumps({"data": {"search": {"nodes": [
            {"number": n, "title": "t", "url": f"https://github.com/example/app-a/pull/{n}", "createdAt": "2027-01-10T00:00:00Z",
             "isDraft": False, "headRefOid": "b" * 40, "repository": {"nameWithOwner": "example/app-a"}} for n in opened]}}}), ""
    return runner


def ledger_of(*lines):
    return reviews.parse_ledger("".join("\t".join(map(str, ln)) + "\n" for ln in lines))


def test_merged_prs_are_classified_against_the_ledger_when_the_object_is_built(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    nodes = [merged_node(1, sha="1" * 40), merged_node(2, sha="2" * 40), merged_node(3, sha="3" * 40, changed=2),
             merged_node(4, sha="4" * 40, files=("docs/x.md",)), merged_node(5, sha="5" * 40, days_ago=9)]
    assert portfolio.refresh_github(reg, cache, NOW, gh(nodes, opened=[8, 9])) is True
    assert cache["checked"]["github"] == asks._iso(NOW) and cache["open_prs"] == {"example/app-a": 2}
    ledger = ledger_of(("2027-01-14T00:00:00Z", "app-a", "1" * 40, "branch", 0, 0, "codex"),
                       ("2027-01-14T00:00:00Z", "app-a", "2" * 40, "branch", 1, 0, "codex"))
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=ledger, cache=cache)["products"][0]
    # 4 merged inside 7 days; #1 reviewed, #2 open P1, #3 and #4 exempt; none unreviewed
    assert p["prs"] == {"open": 2, "waiting": 0, "merged_7d": 4, "unreviewed_7d": 0, "open_p1": 1}
    assert p["health"] == "off_track" and p["reasons"][0] == "1 merged PR has an open P1"
    plain = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, cache=cache,
                            ledger=ledger_of(("2027-01-14T00:00:00Z", "app-a", "1" * 40, "branch", 0, 0, "codex"),
                                             ("2027-01-14T00:00:00Z", "app-a", "2" * 40, "branch", 0, 0, "codex")))
    assert plain["products"][0]["prs"]["unreviewed_7d"] == 0 and plain["products"][0]["health"] != "off_track"
    missing = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=ledger_of(), cache=cache)
    assert missing["products"][0]["prs"]["unreviewed_7d"] == 2           # #1 and #2 have no entry now
    assert any("never reviewed" in f for f in missing["products"][0]["facts"])        # a fact, no longer a reason
    assert not any("never reviewed" in r for r in missing["products"][0]["reasons"])


def test_a_failed_github_read_keeps_the_old_rows(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    portfolio.refresh_github(reg, cache, NOW, gh([merged_node(1)], opened=[8]))
    before = json.loads(json.dumps(cache["github"]))
    assert portfolio.refresh_github(reg, cache, NOW + 3600, gh([], fail=True)) is False
    assert cache["github"] == before and cache["open_prs"] == {"example/app-a": 1}
    assert cache["checked"]["github"] == asks._iso(NOW)


def test_open_prs_fall_back_to_the_backlog_cache_before_the_first_pass(tmp_path):
    reg, _ = one(tmp_path)
    bl = {"prs": [{"repo": "example/app-a", "number": 3}, {"repo": "example/other", "number": 4}], "canonical": {}}
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl=bl, ledger=None,
                        cache=portfolio.load_cache())["products"][0]
    assert p["prs"]["open"] == 1


def test_the_refresh_writes_a_private_cache_and_stamps_the_attempt(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    fake_tools(monkeypatch, tf_payload(tf_plat()), play_payload(internal=[rel(14)]))
    monkeypatch.setattr(portfolio, "compute_activity", lambda r: {"app-a": {"sessions_7d": 5, "spend_7d_usd": 12.34}})
    assert portfolio.refresh(NOW, reg=reg, runner=gh([merged_node(1)])) == 0
    path = portfolio.cache_path()
    assert path.stat().st_mode & 0o777 == 0o600
    c = portfolio.load_cache()
    assert c["at"] == NOW and set(c["checked"]) == {"stores", "github", "activity", "metrics"} and all(c["checked"].values())
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=c)["products"][0]
    assert p["activity"]["sessions_7d"] == 5 and p["activity"]["spend_7d_usd"] == 12.34


def test_safe_mode_runs_no_network_part(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)

    def boom(*a, **k):
        raise AssertionError("the network was used in safe mode")
    monkeypatch.setattr(testflight, "check_product", boom)
    monkeypatch.setattr(reviews, "merged_prs", boom)
    assert portfolio.refresh(NOW, reg=reg, runner=boom) == 1
    c = portfolio.load_cache()
    assert c["at"] == NOW and c["checked"]["stores"] == "" and c["checked"]["github"] == ""


# --- health ------------------------------------------------------------------------------------------

def plat(platform_="ios", state_="current", detail="", behind=0, since=None):
    return {"platform": platform_, "state": state_, "detail": detail, "_behind": behind, "_since": since}


def health(stage="live", platforms=(), primary="ios", p1=0, last_days=0.5):
    last = None if last_days is None else NOW - last_days * DAY
    return portfolio.health_of(stage, list(platforms), primary, p1, last, NOW)


def test_parked_wins_over_everything():
    assert health("parked", [plat(state_="blocked")], p1=2) == ("parked", [])


def test_a_blocked_primary_platform_is_off_track():
    h, why = health(platforms=[plat(state_="blocked", detail="Invited, not accepted: tap View in TestFlight")])
    assert h == "off_track" and why == ["iOS is blocked: Invited, not accepted: tap View in TestFlight"]


def test_a_primary_platform_behind_more_than_two_days_is_off_track_and_less_is_at_risk():
    h, why = health(platforms=[plat(state_="behind", behind=2, since=NOW - 3 * DAY)])
    assert (h, why) == ("off_track", ["iOS is 2 builds behind for 3 days"])
    h, why = health(platforms=[plat(state_="behind", behind=1, since=NOW - 1 * DAY)])
    assert (h, why) == ("at_risk", ["iOS is 1 build behind"])


def test_any_blocked_or_behind_platform_is_at_risk():
    assert health(platforms=[plat(), plat("android", "blocked", "Draft on Play")])[0] == "at_risk"
    assert health(platforms=[plat(), plat("android", "behind", behind=2, since=NOW - 9 * DAY)]) == (
        "at_risk", ["Android is 2 builds behind"])           # old, but not the primary platform


def test_an_open_p1_is_off_track_and_stays_a_reason():
    assert health(p1=2) == ("off_track", ["2 merged PRs have an open P1"])
    assert health(p1=1)[1] == ["1 merged PR has an open P1"]


def test_a_waiting_question_or_an_unreviewed_pr_does_not_change_health(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    portfolio.refresh_github(reg, cache, NOW, gh([merged_node(1, sha="1" * 40)]))
    ask = {"product": "app-a", "age_s": 30 * DAY, "muted": False}
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[ask], tasks=[], bl={}, ledger=ledger_of(), cache=cache,
                        usage={})["products"][0]
    assert (p["health"], p["reasons"]) != ("off_track", [])
    assert not any("question" in r or "reviewed" in r for r in p["reasons"])
    assert (p["waiting"], p["oldest_wait_days"], p["prs"]["unreviewed_7d"]) == (1, 30.0, 1)   # the raw counts stay
    assert p["facts"] == ["1 question waits, the oldest 30 days", "1 PR merged in 7 days was never reviewed"]
    d = repo(tmp_path, "calm", toml='[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
    reg2 = registry_of(("calm", d, "live", False, "ios"))
    q = portfolio.build(NOW, reg=reg2, prods=[], ask_rows=[{"product": "calm", "age_s": 30 * DAY, "muted": False}],
                        tasks=[], bl={}, ledger=None, cache=portfolio.load_cache(), usage={})["products"][0]
    assert (q["health"], q["reasons"]) == ("on_track", []) and q["waiting"] == 1


def test_facts_name_what_health_no_longer_counts():
    assert portfolio.facts_of(0, 0.0, 0) == []
    assert portfolio.facts_of(3, 9.4, 2) == ["3 questions wait, the oldest 9 days",
                                             "2 PRs merged in 7 days were never reviewed"]


def test_a_building_or_beta_product_with_no_session_for_14_days_is_at_risk():
    assert health("building", last_days=15) == ("at_risk", ["No session for 15 days"])
    assert health("beta", last_days=None) == ("at_risk", ["No session recorded"])
    assert health("beta", last_days=14)[0] == "on_track"
    assert health("live", last_days=40)[0] == "on_track"


def test_at_most_three_reasons_and_the_worst_come_first():
    h, why = health("beta", [plat(state_="blocked", detail="x"), plat("android", "behind", behind=1),
                             plat("web", "blocked", detail="y")], p1=1, last_days=30)
    assert h == "off_track" and len(why) == 3
    assert why[0].startswith("iOS is blocked") and "open P1" in why[1] and why[2].startswith("Android is 1 build")


# --- the object and its order ------------------------------------------------------------------------

def three(tmp_path):
    d = {n: repo(tmp_path, n, toml=f'[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
         for n in ("calm", "late", "stuck", "shelf", "newer")}
    reg = registry_of(("calm", d["calm"], "live", False, "ios"), ("late", d["late"], "live", True, "ios"),
                      ("stuck", d["stuck"], "live", False, "ios"), ("shelf", d["shelf"], "parked", True, "ios"),
                      ("newer", d["newer"], "live", False, "ios"))
    prods = [{"id": "calm", "last_activity": asks._iso(NOW - 3600), "display_name": "Calm", "waiting": 0},
             {"id": "late", "last_activity": asks._iso(NOW - 9 * DAY), "display_name": "Late", "waiting": 0},
             {"id": "stuck", "last_activity": asks._iso(NOW - 2 * DAY), "display_name": "Stuck", "waiting": 1},
             {"id": "shelf", "last_activity": asks._iso(NOW), "display_name": "Shelf", "waiting": 0},
             {"id": "newer", "last_activity": asks._iso(NOW - 60), "display_name": "Newer", "waiting": 0}]
    ask = {"product": "stuck", "age_s": 8 * DAY, "muted": False}
    return reg, prods, [ask]


def test_worst_health_first_then_focus_then_last_activity(tmp_path):
    reg, prods, ask = three(tmp_path)
    cache = portfolio.load_cache()
    cache["stores"]["stuck"] = {"ios": portfolio._row("ios", "testflight", "blocked", "Invited", as_of=asks._iso(NOW))}
    cache["checked"]["stores"] = asks._iso(NOW)
    pf = portfolio.build(NOW, reg=reg, prods=prods, ask_rows=ask, tasks=[], bl={}, ledger=None, cache=cache, usage={})
    assert [p["id"] for p in pf["products"]] == ["stuck", "late", "newer", "calm", "shelf"]
    assert [p["health"] for p in pf["products"]] == ["off_track", "on_track", "on_track", "on_track", "parked"]
    assert pf["counts"] == {"on_track": 3, "at_risk": 0, "off_track": 1, "parked": 1}
    stuck = pf["products"][0]
    assert (stuck["waiting"], stuck["oldest_wait_days"]) == (1, 8.0)
    assert pf["version"] == 1 and pf["checked"] == {"stores": asks._iso(NOW), "github": ""}


def test_tasks_and_the_next_step_come_from_the_snapshot_rows(tmp_path):
    reg, prods, ask = three(tmp_path)
    prods[0]["next"], prods[0]["repo"] = "Answer the sign-in question", "~/repos/calm"
    tasks = [{"product": "calm", "kind": "merge"}, {"product": "calm", "kind": "task"}, {"product": "late", "kind": "task"}]
    pf = portfolio.build(NOW, reg=reg, prods=prods, ask_rows=ask, tasks=tasks, bl={}, ledger=None, cache=portfolio.load_cache())
    calm = next(p for p in pf["products"] if p["id"] == "calm")
    assert (calm["tasks"], calm["prs"]["waiting"], calm["next"], calm["repo"]) == (2, 1, "Answer the sign-in question", "~/repos/calm")
    assert calm["title"] == "Calm" and calm["stage"] == "live"


def test_a_muted_question_does_not_wait(tmp_path):
    reg, prods, _ = three(tmp_path)
    pf = portfolio.build(NOW, reg=reg, prods=prods, tasks=[], bl={}, ledger=None, cache=portfolio.load_cache(),
                         ask_rows=[{"product": "stuck", "age_s": 30 * DAY, "muted": True}])
    assert next(p for p in pf["products"] if p["id"] == "stuck")["waiting"] == 0


# --- the core products -----------------------------------------------------------------------------------

def many(tmp_path, spec):
    """spec: (id, stage, focus, spend_7d_usd, weekly users or None). Returns (registry, cache, usage)."""
    rows, cache, usage = [], portfolio.load_cache(), {}
    for pid, stage, focus, spend, weekly in spec:
        d = repo(tmp_path, pid, toml='[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
        rows.append((pid, d, stage, focus, "ios"))
        cache["activity"][pid] = {"sessions_7d": 1, "spend_7d_usd": spend}
        if weekly is not None:
            usage[pid] = {"wau": str(weekly), "users": "50"}
    return registry_of(*rows), cache, usage


def test_core_follows_the_stars_when_any_product_is_starred(tmp_path):
    reg, cache, usage = many(tmp_path, [("a", "live", False, 500.0, 9), ("b", "live", True, 3.0, None),
                                        ("c", "beta", True, 60.0, None), ("d", "parked", True, 0.0, None)])
    ids, source, _ = portfolio.core_view(reg, cache, usage)
    assert (ids, source) == (["c", "b", "d"], "star")          # exactly the starred ones, by spend; "a" is not
    pf = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage=usage)
    assert (pf["core"], pf["core_source"]) == (["c", "b", "d"], "star")


def test_core_by_rule_takes_users_or_spend_ranked_by_spend_and_skips_parked(tmp_path):
    reg, cache, usage = many(tmp_path, [("busy", "live", False, 90.0, None), ("loved", "live", False, 5.0, 3),
                                        ("idle", "live", False, 39.9, 0), ("shelf", "parked", False, 400.0, 20),
                                        ("edge", "beta", False, 40.0, None), ("none", "live", False, 0.0, None)])
    ids, source, detail = portfolio.core_view(reg, cache, usage)
    assert (ids, source) == (["busy", "edge", "loved"], "rule")
    assert detail["loved"] == (5.0, 3)


def test_core_is_capped_at_six(tmp_path):
    reg, cache, usage = many(tmp_path, [(f"p{i}", "live", False, 100.0 + i, None) for i in range(9)])
    ids, source, _ = portfolio.core_view(reg, cache, usage)
    assert source == "rule" and ids == ["p8", "p7", "p6", "p5", "p4", "p3"]
    reg, cache, usage = many(tmp_path / "s", [(f"p{i}", "live", True, 1.0 + i, None) for i in range(8)])
    assert len(portfolio.core_view(reg, cache, usage)[0]) == 6


def test_no_core_when_nothing_qualifies(tmp_path):
    reg, cache, usage = many(tmp_path, [("a", "live", False, 1.0, None)])
    assert portfolio.core_view(reg, cache, usage)[:2] == ([], "rule")
    assert portfolio.empty()["core"] == [] and portfolio.empty()["core_source"] == "rule"


# --- progress ---------------------------------------------------------------------------------------------

def test_can_install_lists_known_builds_primary_first_and_omits_unknown_platforms(tmp_path, monkeypatch):
    reg, cache, _ = stores(tmp_path, monkeypatch, tf_payload(tf_plat()), play_payload(internal=[rel(14)]))
    cache["checked"]["stores"] = asks._iso(NOW)
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})["products"][0]
    assert p["progress"]["can_install"] == [
        {"platform": "ios", "version": "1.9.0", "build": "120", "channel": "testflight", "state": "current"},
        {"platform": "android", "version": "1.9.0 (14)", "build": "14", "channel": "play", "state": "current"},
        {"platform": "web", "version": "", "build": "", "channel": "web", "state": "live"}]
    reg2, _ = one(tmp_path / "2", toml=TOML)
    bare = portfolio.build(NOW, reg=reg2, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                           cache=portfolio.load_cache(), usage={})["products"][0]
    assert [x["platform"] for x in bare["progress"]["can_install"]] == ["web"]      # ios, android: not checked


def test_progress_without_any_cache_is_empty_but_complete(tmp_path):
    d = repo(tmp_path, "calm", toml='[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
    reg = registry_of(("calm", d, "live", False, "ios"))
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=portfolio.load_cache(),
                        usage={})["products"][0]
    assert p["progress"] == {"can_install": [], "shipped_7d": {"prs": 0, "top": []}, "users": None, "milestone": "",
                             "blocker": "", "quiet_days": None, "line": ""}


def test_shipped_7d_counts_merged_prs_and_names_up_to_three_without_the_mechanical_ones(tmp_path):
    reg, _ = one(tmp_path)
    titles = ["Add the map", "release 1.9.0", "Regenerate the leak gate for the new rules", "Fix the login loop",
              "Bump version to 1.9.1", "Show trip photos", "Speed up the feed"]
    nodes = [{**merged_node(i + 1, sha=f"{i + 1:040x}", days_ago=0.1 * (i + 1)), "title": t} for i, t in enumerate(titles)]
    nodes.append({**merged_node(20, sha="9" * 40, days_ago=9), "title": "Old work"})
    cache = portfolio.load_cache()
    portfolio.refresh_github(reg, cache, NOW, gh(nodes))
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})["products"][0]
    assert p["prs"]["merged_7d"] == 7                                    # the raw count keeps every merged PR
    assert p["progress"]["shipped_7d"] == {"prs": 4, "top": ["Add the map", "Fix the login loop", "Show trip photos"]}


def test_old_cache_rows_without_titles_give_an_empty_top(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    cache["github"]["example/app-a"] = {"as_of": asks._iso(NOW), "prs": [
        {"number": 1, "merged_at": asks._iso(NOW - DAY), "head": SHA, "merge": SHA, "commits": [SHA], "changed": 5,
         "docs": False}]}
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})["products"][0]
    assert p["progress"]["shipped_7d"] == {"prs": 1, "top": []}


@pytest.mark.parametrize("title,mechanical", [
    ("release 0.35.0", True), ("Release v1.2.3", True), ("Bump version to 2.0", True), ("chore: bump deps", True),
    ("chore(release): 1.4.0", True), ("1.2.3", True), ("Regenerate the leak gate", True),
    ("Regenerate fixtures and the leak gate", True), ("Merge branch 'main' into feature", True),
    ("Release notes page for the web app", False), ("Add a release checklist", False), ("Regenerate the map tiles", False),
    ("Fix the bump animation", False), ("", False)])
def test_the_mechanical_pr_filter(title, mechanical):
    assert portfolio.is_mechanical(title) is mechanical


def test_users_come_from_the_usage_cache_and_are_null_without_one(tmp_path):
    d = repo(tmp_path, "calm", toml='[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
    reg = registry_of(("calm", d, "live", False, "ios"))
    kw = dict(reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=portfolio.load_cache())
    assert portfolio.build(NOW, usage={}, **kw)["products"][0]["progress"]["users"] is None
    assert portfolio.build(NOW, usage={"calm": {"trips": "40"}}, **kw)["products"][0]["progress"]["users"] is None
    u = portfolio.build(NOW, usage={"calm": {"wau": "4", "users": "12"}}, **kw)["products"][0]["progress"]["users"]
    assert u == {"weekly": 4, "total": 12, "label": "4 active this week, 12 total"}
    only_total = portfolio.build(NOW, usage={"calm": {"users": "12"}}, **kw)["products"][0]["progress"]["users"]
    assert only_total == {"weekly": None, "total": 12, "label": "12 total"}


def test_teyla_products_writes_the_usage_cache_and_the_portfolio_reads_it(tmp_path):
    from teyla import products
    products.write_cache({"Calm": ("ok", {"wau": "3", "users": "9"}), "late": ("timeout", {})})
    path = products.cache_path()
    assert path == portfolio.usage_cache_path() and oct(path.stat().st_mode & 0o777) == "0o600"
    assert portfolio.load_usage_cache() == {"calm": {"wau": "3", "users": "9"}}      # only a probe that worked
    products.write_cache({"Calm": ("timeout", {}), "other": ("ok", {"wau": "1"})})    # a failed probe keeps the good row
    assert portfolio.load_usage_cache() == {"calm": {"wau": "3", "users": "9"}, "other": {"wau": "1"}}


def test_a_missing_or_broken_usage_cache_reads_as_empty():
    assert portfolio.load_usage_cache() == {}
    portfolio.usage_cache_path().write_text("not json")
    assert portfolio.load_usage_cache() == {}


def test_the_line_picks_the_first_fact_that_exists(tmp_path):
    ios = {"platform": "ios", "version": "1.9.0", "build": "120", "state": "current"}
    assert portfolio.line_of(2, "family: 2 of 9 requirements left", ios, 5) == "2 merged PRs have an open P1"
    assert portfolio.line_of(0, "family: 2 of 9 requirements left", ios, 5) == "family: 2 of 9 requirements left"
    assert portfolio.line_of(0, "", ios, 5) == "iOS 1.9.0 (120) is installable"
    assert portfolio.line_of(0, "", {**ios, "state": "behind"}, 5) == "iOS 1.9.0 (120) is behind"
    assert portfolio.line_of(0, "", {**ios, "state": "unknown"}, 5) == "Quiet for 5 days"
    assert portfolio.line_of(0, "", None, 1) == "Quiet for 1 day"
    assert portfolio.line_of(0, "", None, 0) == "" and portfolio.line_of(0, "", None, None) == ""
    long = " ".join(f"w{i}" for i in range(20))
    assert len(portfolio.line_of(0, long, None, 0).split()) == portfolio.LINE_WORDS


def test_the_blocker_key_is_empty_and_quiet_days_count_from_the_last_activity(tmp_path):
    reg, prods, _ = three(tmp_path)
    pf = portfolio.build(NOW, reg=reg, prods=prods, ask_rows=[], tasks=[], bl={}, ledger=None,
                         cache=portfolio.load_cache(), usage={})
    by = {p["id"]: p["progress"] for p in pf["products"]}
    assert by["late"]["blocker"] == "" and by["late"]["quiet_days"] == 9 and by["late"]["line"] == "Quiet for 9 days"
    assert by["calm"]["quiet_days"] == 0


# --- stores that were never fully read ------------------------------------------------------------------------

def test_an_empty_checked_stores_reads_unknown_never_behind(tmp_path, monkeypatch):
    plat_ = tf_plat(behind=2, up=("1.9.1", "122"), inst=("1.9.0", "120"), blockers=["122: processing"])
    reg, cache, _ = stores(tmp_path, monkeypatch, tf_payload(plat_), play_payload(internal=[rel(14)]))
    assert cache["stores"]["app-a"]["ios"]["state"] == "behind"
    cache["checked"]["stores"] = ""                                     # the pass never worked as a whole
    kw = dict(reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, usage={})
    p = portfolio.build(NOW, cache=cache, **kw)["products"][0]
    ios = p["platforms"][0]
    assert (ios["state"], ios["detail"]) == ("unknown", "Not fully checked yet")
    assert not any("behind" in r for r in p["reasons"])
    cache["checked"]["stores"] = asks._iso(NOW)
    assert portfolio.build(NOW, cache=cache, **kw)["products"][0]["platforms"][0]["state"] == "behind"


# --- state.brief ------------------------------------------------------------------------------------------------

def test_the_rule_brief_names_neither_a_session_title_nor_the_unassigned_bucket():
    def row(product, rank, unblocks="a release"):
        return {"product": product, "rank": rank, "unblocks": unblocks, "muted": False, "title": "Fix the flaky sign-in test"}
    line = state.brief_line({"asks": [row("unassigned", 1), row("unassigned", 2), row("known", 3)]})["line"]
    assert "unassigned" not in line.lower() and "Fix the flaky" not in line
    assert line == "2 answers unblock a release today. Known is waiting on you too."
    assert state.brief_line({"asks": [row("Unassigned", 1, "")]})["line"] == "1 question waits for you."
    assert state.brief_line({"asks": [row("Fix the flaky sign-in test", 1, "")]})["line"] == "1 question waits for you."
    assert state.brief_line({"asks": [row("Fix the flaky sign-in test", 1)]})["line"] == "1 answer unblocks a release today."
    assert state.brief_line({"asks": [row("known", 1, "")]})["line"] == "1 question waits for you, the first one in known."


# --- teyla state --------------------------------------------------------------------------------------

def snapshot(tmp_path, **kw):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    return state.build(NOW, items=[], repos={}, spent=None, desktop=str(sessions), codex_root=str(tmp_path / "nocodex"),
                       backlog_data=dict(backlog.EMPTY, prs=[], issues=[], counts={}, canonical={}),
                       approved=set(), ledger=ledger_of(), runs=[], **kw)


def test_the_snapshot_is_version_3_and_matches_the_fixture(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    monkeypatch.setattr(portfolio.registry, "load", lambda strict=False: reg)
    monkeypatch.setattr(state.registry, "load", lambda strict=False: reg)
    st = snapshot(tmp_path)
    fixture = json.loads((FIXTURES / "state.v3.json").read_text())
    assert st["version"] == 3 and set(st) == set(fixture)
    pf, ref = st["portfolio"], fixture["portfolio"]
    assert set(pf) == set(ref) and set(pf["checked"]) == set(ref["checked"]) and set(pf["counts"]) == set(ref["counts"])
    assert [(s["id"], set(s)) for s in pf["home"]["sections"]] == [(s["id"], set(s)) for s in ref["home"]["sections"]]
    p = pf["products"][0]
    assert set(p) == set(ref["products"][0]) and set(p["prs"]) == set(ref["products"][0]["prs"])
    m, rm = p["metrics"], ref["products"][0]["metrics"]
    assert set(m) == set(rm) and set(m["users"]) == set(rm["users"]) and set(m["commits"]) == set(rm["commits"])
    assert set(m["spend_usd"]) == set(rm["spend_usd"]) and set(m["money"]) == set(rm["money"])
    assert set(m["users"]["active"]) == set(rm["users"]["active"]) and set(m["users"]["new"]) == set(rm["users"]["new"])
    assert set(m["money"]["revenue_usd"]) == set(rm["money"]["revenue_usd"])
    assert set(p["activity"]) == set(ref["products"][0]["activity"])
    assert set(p["platforms"][0]) == set(ref["products"][0]["platforms"][0])
    assert [x["id"] for x in pf["products"]] == ["app-a"]
    json.dumps(st)                                                         # all of it serialises


def test_the_snapshot_makes_no_network_call(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    monkeypatch.setattr(state.registry, "load", lambda strict=False: reg)
    portfolio.save_cache({**portfolio.load_cache(), "at": NOW - 3600})     # a fresh cache: nothing is started either

    def boom(*a, **k):
        raise AssertionError("the snapshot started a process or a network call")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(backlog, "default_runner", boom)
    monkeypatch.setattr(testflight, "check_product", boom)
    monkeypatch.setattr(play, "check_product", boom)
    monkeypatch.setattr(reviews, "merged_prs", boom)
    assert snapshot(tmp_path)["portfolio"]["products"][0]["id"] == "app-a"


def test_a_missing_or_old_cache_starts_one_refresh_and_a_fresh_one_does_not(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    monkeypatch.setattr(state.registry, "load", lambda strict=False: reg)
    monkeypatch.setattr(portfolio, "enabled", lambda cfg=None: True)
    spawned = []
    monkeypatch.setattr(portfolio, "spawn_refresh", lambda now=None: spawned.append(now))
    snapshot(tmp_path)
    assert len(spawned) == 1                                               # no cache
    portfolio.save_cache({**portfolio.load_cache(), "at": NOW - 7 * 3600})
    snapshot(tmp_path)
    assert len(spawned) == 2                                               # older than 6 hours
    portfolio.save_cache({**portfolio.load_cache(), "at": NOW - 5 * 3600})
    snapshot(tmp_path)
    assert len(spawned) == 2


def test_no_refresh_starts_in_safe_mode_or_without_gh(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(portfolio, "spawn_refresh", lambda now=None: spawned.append(now))
    monkeypatch.setattr(portfolio.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    assert portfolio.maybe_refresh(portfolio.load_cache(), NOW) is False
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(portfolio.shutil, "which", lambda name: None)
    assert portfolio.maybe_refresh(portfolio.load_cache(), NOW) is False
    monkeypatch.setattr(portfolio.shutil, "which", lambda name: "/bin/gh")
    assert portfolio.maybe_refresh(portfolio.load_cache(), NOW) is True and len(spawned) == 1


def test_the_spawn_holds_a_lock_so_a_second_refresh_does_not_start(monkeypatch):
    started = []
    monkeypatch.setattr(portfolio.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    now = time.time()                                                      # the lock's mtime is real time
    _REAL_SPAWN(now)
    _REAL_SPAWN(now + 60)                                                  # the lock is fresh: nothing starts
    assert len(started) == 1 and started[0][-3:] == ["portfolio", "--refresh", "--background"]
    _REAL_SPAWN(now + portfolio.LOCK_STALE_S + 60)                          # a dead lock is taken over
    assert len(started) == 2


def test_a_snapshot_survives_a_broken_registry_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio, "build", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    st = snapshot(tmp_path)
    assert st["portfolio"] == {"version": 1, "checked": {"stores": "", "github": ""},
                               "counts": {"on_track": 0, "at_risk": 0, "off_track": 0, "parked": 0}, "core": [],
                               "core_source": "rule", "products": [],
                               "home": {"sections": [{"id": "users", "ids": []}, {"id": "building", "ids": []},
                                                     {"id": "quiet", "ids": []}]}}


# --- the command --------------------------------------------------------------------------------------

@pytest.fixture
def command(tmp_path, monkeypatch):
    reg = registry_of(("alpha", repo(tmp_path, "alpha"), "beta", True, "iOS"))
    monkeypatch.setattr(state.registry, "load", lambda strict=False: reg)
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [])
    monkeypatch.setattr(state, "repo_index", lambda: {})
    monkeypatch.setattr(state, "spent_today", lambda now: None)
    monkeypatch.setattr(state, "backlog_view", lambda now: dict(backlog.EMPTY, prs=[], issues=[], counts={}, canonical={}))
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(tmp_path / "none"))
    monkeypatch.setattr(state, "dispatched", lambda: [])
    return reg


def test_the_command_prints_json_text_and_one_product(command, capsys):
    assert cli.main(["portfolio", "--json"]) == 0
    pf = json.loads(capsys.readouterr().out)
    assert pf["version"] == 1 and [p["id"] for p in pf["products"]] == ["alpha"]
    assert cli.main(["portfolio", "--product", "alpha", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["on_track"] + json.loads(
        json.dumps(pf))["counts"]["at_risk"] >= 0
    assert cli.main(["portfolio"]) == 0
    out = capsys.readouterr().out
    first = out.splitlines()[0]
    assert "Alpha" in first and "ios current" not in first and "ios unknown" in first
    assert out.splitlines()[-1].startswith("stores checked never")
    assert cli.main(["portfolio", "--product", "nope"]) == 2
    assert "no product 'nope'" in capsys.readouterr().err


def test_refresh_through_the_command_runs_the_pass_and_removes_its_lock(command, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(portfolio, "refresh", lambda now=None, **k: ran.append(now) or 0)
    assert cli.main(["portfolio", "--refresh", "--json"]) == 0
    assert len(ran) == 1 and not portfolio.lock_path().exists()
    portfolio.lock_path().write_text("")
    assert cli.main(["portfolio", "--refresh"]) == 1
    assert "already running" in capsys.readouterr().err and len(ran) == 1


def test_refresh_in_safe_mode_says_so_and_still_exits_by_the_pass(command, monkeypatch, capsys):
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    monkeypatch.setattr(portfolio, "compute_activity", lambda reg: {})
    assert cli.main(["portfolio", "--refresh"]) == 1
    assert "safe mode is on" in capsys.readouterr().err
    assert cli.main(["portfolio", "--refresh", "--allow-network"]) in (0, 1)


# --- Home: sections, summary, icon and metrics ------------------------------------------------------------

def item(pid, *, stage="live", focus=False, active=None, new=None, c7=None, c30=None):
    nul = {"7d": None, "30d": None, "365d": None}
    return {"id": pid, "stage": stage, "focus": focus,
            "metrics": {"users": {"total": None, "active": {**nul, "7d": active}, "new": {**nul, "7d": new}},
                        "commits": {"7d": c7, "30d": c30, "365d": None, "weeks": []}}}


def sections_of(items):
    return {s["id"]: s["ids"] for s in portfolio.home_view(items)["sections"]}


def test_home_has_the_three_sections_in_order_even_when_empty():
    assert portfolio.home_view([]) == {"sections": [{"id": "users", "ids": []}, {"id": "building", "ids": []},
                                                   {"id": "quiet", "ids": []}]}


def test_home_puts_every_product_in_exactly_one_section():
    items = [item("a", active=3), item("b", new=1), item("c", c7=9), item("d", c7=1), item("e"),
             item("f", stage="parked", active=50, c7=30), item("g", active=0, new=0, c7=5), item("h", c7=4)]
    sec = sections_of(items)
    assert sec == {"users": ["a", "b"], "building": ["c", "g"], "quiet": ["f", "h", "d", "e"]}
    flat = [i for ids in sec.values() for i in ids]
    assert sorted(flat) == sorted(x["id"] for x in items) and len(flat) == len(set(flat))


def test_a_parked_product_is_always_quiet():
    sec = sections_of([item("p", stage="parked", focus=True, active=9, new=9, c7=99)])
    assert sec == {"users": [], "building": [], "quiet": ["p"]}


def test_building_starts_at_the_commit_threshold():
    sec = sections_of([item("at", c7=portfolio.BUILDING_MIN_COMMITS),
                       item("below", c7=portfolio.BUILDING_MIN_COMMITS - 1)])
    assert sec["building"] == ["at"] and sec["quiet"] == ["below"]


def test_users_are_ranked_star_then_active_then_new_then_commits_then_id():
    sec = sections_of([item("z", active=5, new=2, c7=7), item("y", active=5, new=2, c7=7),
                       item("x", active=5, new=3), item("w", active=9), item("star", focus=True, active=1),
                       item("c", active=5, new=2, c7=8), item("only-new", new=40)])
    assert sec["users"] == ["star", "w", "x", "c", "y", "z", "only-new"]


def test_null_counts_sort_after_real_ones_and_zero_active_users_still_count_as_a_count():
    sec = sections_of([item("null-new", active=2, new=None), item("zero-new", active=2, new=0),
                       item("null-commits", active=2, new=0, c7=None), item("some-commits", active=2, new=0, c7=1)])
    assert sec["users"] == ["some-commits", "null-commits", "zero-new", "null-new"]


def test_building_and_quiet_rank_starred_first_then_commits_then_the_month_then_id():
    sec = sections_of([item("b1", c7=6), item("b2", c7=9), item("b3", focus=True, c7=5), item("b0", c7=9),
                       item("q-month", c7=2, c30=40), item("q-star", focus=True), item("q-null"),
                       item("q-zero", c7=0, c30=0), item("q-two", c7=2, c30=10), item("q-3", c7=3)])
    assert sec["building"] == ["b3", "b0", "b2", "b1"]
    assert sec["quiet"] == ["q-star", "q-3", "q-month", "q-two", "q-zero", "q-null"]


def stocked(tmp_path, spec, *, usage=None):
    """spec: (id, stage, focus, commits7d or None, commits30d or None). Returns the portfolio of those products."""
    rows, cache = [], portfolio.load_cache()
    for pid, stage, focus, c7, c30 in spec:
        d = repo(tmp_path, pid, toml='[productize]\nusers = "owner"\nplatforms = ["ios"]\nprimary = "ios"\n', slug="")
        rows.append((pid, d, stage, focus, "ios"))
        cache["metrics"][pid] = {"commits": None if c7 is None else {"7d": c7, "30d": c30, "365d": c30,
                                                                    "weeks": [0] * 11 + [c7]}}
    return portfolio.build(NOW, reg=registry_of(*rows), prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                           cache=cache, usage=usage or {})


def test_build_adds_the_home_sections_and_keeps_the_old_fields(tmp_path):
    pf = stocked(tmp_path, [("busy", "building", False, 12, 40), ("loved", "live", False, 1, 3),
                            ("idle", "live", False, 0, 0), ("sleeper", "parked", True, 9, 9)],
                 usage={"loved": {"wau": "4", "new_7d": "1"}})
    assert {"core", "core_source", "counts", "checked", "products"} <= set(pf)
    assert {s["id"]: s["ids"] for s in pf["home"]["sections"]} == {
        "users": ["loved"], "building": ["busy"], "quiet": ["sleeper", "idle"]}
    assert all({"summary", "icon_jpeg", "metrics", "progress", "activity"} <= set(p) for p in pf["products"])


def test_only_cuts_the_home_sections_to_one_product(tmp_path):
    pf = stocked(tmp_path, [("a", "live", False, 9, 9), ("b", "live", False, 0, 0)])
    one_pf = portfolio.only(pf, "b")
    assert {s["id"]: s["ids"] for s in one_pf["home"]["sections"]} == {"users": [], "building": [], "quiet": ["b"]}


def test_the_period_never_changes_membership(tmp_path):
    a = stocked(tmp_path / "x", [("p", "live", False, 2, 0), ("q", "live", False, 1, 900)])
    b = stocked(tmp_path / "y", [("p", "live", False, 2, 900), ("q", "live", False, 1, 0)])
    assert a["home"] == b["home"]


# --- users, money, spend ----------------------------------------------------------------------------------

def test_users_are_summed_over_repos_and_null_when_no_repo_reports_the_key(tmp_path):
    reg, _ = one(tmp_path)
    r1, r2 = tmp_path / "repos" / "app-a", tmp_path / "repos" / "app-b"
    usage = {"app-a": {"accounts": "10", "wau": "3", "mau": "5", "new_7d": "1"},
             "app-b": {"users": "2", "active_7d": "1", "active_30d": "2", "users_new_30d": "4", "new_365d": "x"}}
    m = portfolio.users_metrics([r1, r2], usage)
    assert m == {"total": 12, "active": {"7d": 4, "30d": 7, "365d": None},
                 "new": {"7d": 1, "30d": 4, "365d": None}}
    nothing = portfolio.users_metrics([r1], {"app-a": {"rows": "9"}})
    assert nothing == {"total": None, "active": {"7d": None, "30d": None, "365d": None},
                       "new": {"7d": None, "30d": None, "365d": None}}
    assert portfolio.users_metrics([r1], {"app-a": {"users": "-1", "wau": "inf"}})["total"] is None


def test_money_is_null_while_disabled_even_when_the_probe_prints_it(tmp_path):
    d = repo(tmp_path, "shop", toml='[productize]\nusers = "public"\n', slug="")
    usage = {"shop": {"mrr_usd": "120.5", "paying_users": "9", "revenue_7d_usd": "30"}}
    reg = registry_of(("shop", d, "live", False, "ios"))
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                        cache=portfolio.load_cache(), usage=usage)["products"][0]
    assert p["metrics"]["money"] == {"enabled": False, "mrr_usd": None, "paying": None,
                                     "revenue_usd": {"7d": None, "30d": None, "365d": None}}


def test_money_is_read_from_the_usage_keys_when_the_manifest_enables_it(tmp_path):
    toml = '[productize]\nusers = "public"\n[monetization]\nenabled = true\n'
    d = repo(tmp_path, "shop", toml=toml, slug="")
    usage = {"shop": {"mrr_usd": "120.5", "paying_users": "9", "revenue_7d_usd": "30", "revenue_365d_usd": "1400.255"}}
    reg = registry_of(("shop", d, "live", False, "ios"))
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                        cache=portfolio.load_cache(), usage=usage)["products"][0]
    assert p["metrics"]["money"] == {"enabled": True, "mrr_usd": 120.5, "paying": 9,
                                     "revenue_usd": {"7d": 30.0, "30d": None, "365d": 1400.26}}
    assert productize_parse(d)["monetization"] == {"enabled": True}


def productize_parse(d):
    from teyla import productize
    return productize.parse(d / "teyla.toml")


def test_monetization_is_off_when_the_table_is_absent_or_not_true(tmp_path):
    d = repo(tmp_path, "plain", toml='[productize]\nusers = "owner"\n', slug="")
    assert productize_parse(d)["monetization"] == {}
    d2 = repo(tmp_path, "maybe", toml='[monetization]\nenabled = "yes"\n', slug="")
    assert portfolio.monetization_enabled(portfolio.parse_manifests([d, d2])) is False


def test_spend_windows_are_null_for_an_older_cache_and_real_for_a_new_one(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    cache["activity"]["app-a"] = {"sessions_7d": 2, "spend_7d_usd": 12.34}
    old = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})
    assert old["products"][0]["metrics"]["spend_usd"] == {"7d": 12.34, "30d": None, "365d": None}
    cache["activity"]["app-a"].update(spend_30d_usd=40.0, spend_365d_usd=0.0)
    new = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})
    p = new["products"][0]
    assert p["metrics"]["spend_usd"] == {"7d": 12.34, "30d": 40.0, "365d": 0.0}
    assert p["metrics"]["spend_usd"]["7d"] == p["activity"]["spend_7d_usd"]


def test_compute_activity_reports_the_three_spend_windows_for_every_product(tmp_path, monkeypatch):
    from teyla import product_page, spend
    reg, _ = one(tmp_path)
    row = {"sid": "s1", "cwd": str(tmp_path / "repos" / "app-a"), "last": "2999-01-01T00:00:00", "first": ""}
    monkeypatch.setattr(product_page, "load_rows", lambda days: ([row], {}))
    days = [{"total_usd": 0.0} for _ in range(358)] + [{"total_usd": 1.0}] * 7      # 365 days, oldest first
    days[-20] = {"total_usd": 5.0}
    monkeypatch.setattr(spend, "by_day", lambda n, rs: days if rs else [{"total_usd": 0.0}] * n)
    out = _REAL_COMPUTE_ACTIVITY({"product": {**reg["product"], "other": {"repos": [], "paths": [], "aliases": []}}, "assign": {}})
    assert out["app-a"] == {"sessions_7d": 1, "spend_7d_usd": 7.0, "spend_30d_usd": 12.0, "spend_365d_usd": 12.0}
    assert out["other"] == {"sessions_7d": 0, "spend_7d_usd": 0.0, "spend_30d_usd": 0.0, "spend_365d_usd": 0.0}


# --- commits: local git only -----------------------------------------------------------------------------

def git(d, *args, when=None):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": os.environ["PATH"],
           "HOME": str(d)}
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{int(when)} +0000"
    cmd = ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
           "-c", "init.defaultBranch=main", "-C", str(d), *args]
    subprocess.run(cmd, check=True, capture_output=True, env=env)


def commit_file(d, rel_path, days_ago, now):
    f = d / rel_path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"{rel_path} {days_ago}\n")
    git(d, "add", "-A")
    git(d, "commit", "-m", f"change {rel_path}", when=now - days_ago * DAY - 60)


def test_commit_buckets_come_from_local_git_and_skip_policy_and_docs_paths(tmp_path):
    now = time.time()
    d = tmp_path / "gitrepo"
    d.mkdir()
    git(d, "init", "-q")
    commit_file(d, "src/old.txt", 400, now)                   # out of every window
    commit_file(d, "src/c.txt", 40, now)                      # 365d; week 5
    commit_file(d, "src/b.txt", 10, now)                      # 30d, 365d; week 1
    git(d, "checkout", "-q", "-b", "feature")
    commit_file(d, "src/f.txt", 8, now)                       # on a branch, merged below; week 1
    git(d, "checkout", "-q", "main")
    commit_file(d, "src/a.txt", 2, now)                       # 7d, 30d, 365d; week 0
    for rel_path in ("docs/guide.md", "AGENTS.md", "teyla.toml", ".claude/rules/x.md", ".github/y.yml", "README.md",
                     "CHANGELOG.md", "check.sh", ".agents/z.md", ".githooks/pre-push"):
        commit_file(d, rel_path, 1, now)                      # a policy sync or a docs edit: not the product's work
    git(d, "merge", "--no-ff", "-q", "-m", "merge feature", "feature", when=now - DAY // 2)
    times = portfolio.git_commit_times(d, now)
    assert times is not None and len(times) == 4              # a, b, c, f: no merge, no old, no policy path
    b = portfolio.commit_buckets([times], now)
    assert (b["7d"], b["30d"], b["365d"]) == (1, 3, 4)
    assert len(b["weeks"]) == 12 and b["weeks"][-1] == b["7d"] and sum(b["weeks"]) == 4
    assert b["weeks"][10] == 2 and b["weeks"][6] == 1         # 10 and 8 days ago, 40 days ago
    assert portfolio.commit_buckets([times, times], now)["365d"] == 8        # summed across repos


def test_commits_use_origin_head_and_not_unpushed_work(tmp_path):
    now = time.time()
    up = tmp_path / "up"
    up.mkdir()
    git(up, "init", "-q")
    commit_file(up, "src/a.txt", 3, now)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(up), str(clone)], check=True, capture_output=True,
                   env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null"})
    commit_file(clone, "src/local.txt", 1, now)               # not on origin/HEAD
    assert len(portfolio.git_commit_times(clone, now)) == 1
    assert len(portfolio.git_commit_times(up, now)) == 1      # no remote: HEAD


def test_commits_are_null_when_git_cannot_answer(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert portfolio.git_commit_times(plain, NOW) is None
    assert portfolio.commit_buckets([None, None], NOW) is None
    assert portfolio.commit_buckets([], NOW) is None
    assert portfolio.commit_buckets([None, []], NOW) == {"7d": 0, "30d": 0, "365d": 0, "weeks": [0] * 12}
    reg = {"product": {"empty": {"repos": [], "paths": []}, "gone": {"repos": [str(tmp_path / "nope")], "paths": []}},
           "assign": {}}
    assert _REAL_COMPUTE_COMMITS(reg, NOW) == {"empty": None, "gone": None}


def test_the_cached_commits_reach_the_contract_and_missing_ones_are_null(tmp_path):
    pf = stocked(tmp_path, [("a", "live", False, 3, 8), ("b", "live", False, None, None)])
    a, b = (next(p for p in pf["products"] if p["id"] == i)["metrics"]["commits"] for i in "ab")
    assert a == {"7d": 3, "30d": 8, "365d": 8, "weeks": [0] * 11 + [3]}
    assert b == {"7d": None, "30d": None, "365d": None, "weeks": []}


def test_an_older_cache_without_metrics_still_loads(tmp_path):
    portfolio.cache_path().write_text(json.dumps({"version": 1, "at": 5.0, "checked": {"stores": "x"},
                                                  "stores": {}, "github": {}, "open_prs": {}, "activity": {}}))
    c = portfolio.load_cache()
    assert c["metrics"] == {} and c["checked"]["metrics"] == "" and c["checked"]["stores"] == "x" and c["at"] == 5.0
    reg, _ = one(tmp_path)
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=c, usage={})["products"][0]
    assert p["metrics"]["commits"]["7d"] is None and p["icon_jpeg"] == ""


def test_refresh_stores_the_metrics_without_the_network_and_keeps_old_rows_when_a_part_fails(tmp_path, monkeypatch):
    reg, _ = one(tmp_path)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))        # noqa: E731
    monkeypatch.setattr(testflight, "check_product", boom)
    monkeypatch.setattr(reviews, "merged_prs", boom)
    monkeypatch.setattr(portfolio, "compute_commits", lambda r, n: {"app-a": {"7d": 2, "30d": 3, "365d": 4,
                                                                             "weeks": [0] * 12}})
    monkeypatch.setattr(portfolio, "compute_icons", lambda r, prev: {"app-a": {"src": "s", "mtime": 1.0, "b64": "QUJD"}})
    assert portfolio.refresh(NOW, reg=reg, network=False) == 1                    # the network part is off: code 1
    c = portfolio.load_cache()
    assert c["metrics"]["app-a"]["commits"]["30d"] == 3 and c["metrics"]["app-a"]["icon"]["b64"] == "QUJD"
    assert c["checked"]["metrics"] == portfolio._iso(NOW)

    def fail(*a, **k):
        raise RuntimeError("git is broken")
    monkeypatch.setattr(portfolio, "compute_commits", fail)
    monkeypatch.setattr(portfolio, "compute_icons", lambda r, prev: {"app-a": None})
    assert portfolio.refresh(NOW + 60, reg=reg, network=False) == 1
    c = portfolio.load_cache()
    assert c["metrics"]["app-a"]["commits"]["30d"] == 3                           # the old commits stay
    assert c["metrics"]["app-a"]["icon"] is None and c["checked"]["metrics"] == portfolio._iso(NOW)


# --- summary --------------------------------------------------------------------------------------------

README = """# Sample App

[![build](https://example.com/badge.svg)](https://example.com)
![logo](logo.png)
<p align="center">centered html</p>

Sample App plans **trips** with friends. See [the guide](docs/guide.md) for more.
It also keeps a shared list.

## Quick start

Run it.
"""


def test_the_readme_summary_skips_headings_badges_images_and_html(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "README.md").write_text(README)
    assert portfolio.readme_summary(d) == "Sample App plans trips with friends. See the guide for more. It also keeps a shared list."
    (d / "README.md").write_text("Title\n=====\n\n- a list\n\n```\ncode\n```\n\n" + "word " * 60 + "\n")
    out = portfolio.readme_summary(d)
    assert len(out) == portfolio.SUMMARY_CHARS and out.endswith("…") and out.startswith("word word")
    (d / "README.md").write_text("# Only a heading\n")
    assert portfolio.readme_summary(d) == ""
    assert portfolio.readme_summary(d / "missing") == ""


def test_summary_precedence_manifest_then_registry_then_readme(tmp_path):
    toml = '[productize]\nsummary = "From the manifest."\n'
    d = repo(tmp_path, "s", toml=toml, slug="")
    (d / "README.md").write_text(README)
    reg = registry_of(("s", d, "live", False, "ios"))

    def summary():
        p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                            cache=portfolio.load_cache(), usage={})["products"][0]
        return p["summary"]
    reg["product"]["s"]["summary"] = "From the registry."
    assert summary() == "From the manifest."
    (d / "teyla.toml").write_text('[productize]\nusers = "owner"\n')
    assert summary() == "From the registry."
    reg["product"]["s"]["summary"] = ""
    assert summary().startswith("Sample App plans trips")
    (d / "README.md").unlink()
    assert summary() == ""


def test_the_registry_accepts_a_summary_and_names_it_in_the_error(tmp_path):
    from teyla import registry
    reg = registry_of(("a", tmp_path, "live", False, "ios"))
    assert registry.set_field(reg, "a", "summary", "  A tool that counts.  ") == "a: summary = A tool that counts."
    assert reg["product"]["a"]["summary"] == "A tool that counts."
    with pytest.raises(ValueError, match="summary"):
        registry.set_field(reg, "a", "bogus", "1")
    again = registry._normalise(__import__("tomllib").loads(registry.dump(reg)))
    assert again["product"]["a"]["summary"] == "A tool that counts."
    assert "summary" not in registry._normalise({"product": {"b": {"name": "b"}}})["product"]["b"]


# --- icon -----------------------------------------------------------------------------------------------

def png(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG" + b"0" * size)
    return path


def test_the_icon_is_the_largest_appiconset_png_and_skips_build_dirs(tmp_path):
    d = tmp_path / "app"
    small = png(d / "ios" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-60.png", 60)
    big = png(d / "ios" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-1024.png", 900)
    png(d / "node_modules" / "pkg" / "AppIcon.appiconset" / "huge.png", 5000)
    png(d / "DerivedData" / "AppIcon.appiconset" / "huge.png", 5000)
    png(d / "public" / "icon.png", 9000)
    assert portfolio.find_icon([d]) == big and small.exists()


def test_the_icon_falls_back_to_a_web_icon_in_the_listed_order(tmp_path):
    d = tmp_path / "web"
    png(d / "icon.png", 10)
    png(d / "app" / "icon.png", 10)
    assert portfolio.find_icon([d]) == d / "app" / "icon.png"
    png(d / "public" / "logo.png", 10)
    assert portfolio.find_icon([d]) == d / "public" / "logo.png"
    assert portfolio.find_icon([tmp_path / "empty"]) is None


def fake_sips(monkeypatch, payload=b"jpegbytes", calls=None):
    monkeypatch.setattr(portfolio.shutil, "which", lambda name: "/usr/bin/sips" if name == "sips" else None)

    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        pathlib.Path(cmd[cmd.index("--out") + 1]).write_bytes(payload)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(portfolio.subprocess, "run", run)


def test_a_missing_sips_means_no_icon_and_no_error(tmp_path, monkeypatch):
    d = tmp_path / "app"
    png(d / "AppIcon.appiconset" / "i.png", 100)
    reg = {"product": {"a": {"repos": [str(d)], "paths": []}}, "assign": {}}
    monkeypatch.setattr(portfolio.shutil, "which", lambda name: None)
    assert _REAL_COMPUTE_ICONS(reg, {}) == {"a": None}
    pf = stocked(tmp_path / "x", [("a", "live", False, 1, 1)])
    assert pf["products"][0]["icon_jpeg"] == ""


def test_the_icon_is_converted_once_and_again_only_when_the_source_changes(tmp_path, monkeypatch):
    d = tmp_path / "app"
    src = png(d / "AppIcon.appiconset" / "i.png", 100)
    reg = {"product": {"a": {"repos": [str(d)], "paths": []}}, "assign": {}}
    calls = []
    fake_sips(monkeypatch, b"jpegbytes", calls)
    first = _REAL_COMPUTE_ICONS(reg, {})["a"]
    assert first["b64"] == "anBlZ2J5dGVz" and first["src"] == str(src)
    cmd = calls[0]
    assert cmd[1:9] == ["-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", "88"] and len(calls) == 1
    assert _REAL_COMPUTE_ICONS(reg, {"a": first})["a"] == first and len(calls) == 1            # unchanged: no sips
    os.utime(src, (NOW, NOW))
    again = _REAL_COMPUTE_ICONS(reg, {"a": first})["a"]
    assert len(calls) == 2 and again["mtime"] == NOW


def test_an_icon_over_8_kb_of_base64_is_dropped_and_not_converted_again(tmp_path, monkeypatch):
    d = tmp_path / "app"
    png(d / "AppIcon.appiconset" / "i.png", 100)
    reg = {"product": {"a": {"repos": [str(d)], "paths": []}}, "assign": {}}
    calls = []
    fake_sips(monkeypatch, b"x" * 7000, calls)                                    # 9336 base64 characters
    row = _REAL_COMPUTE_ICONS(reg, {})["a"]
    assert row["b64"] == "" and len(calls) == 1
    assert _REAL_COMPUTE_ICONS(reg, {"a": row})["a"] == row and len(calls) == 1


def test_the_icon_rides_in_the_portfolio_when_the_cache_has_one(tmp_path):
    reg, _ = one(tmp_path)
    cache = portfolio.load_cache()
    cache["metrics"]["app-a"] = {"icon": {"src": "s", "mtime": 1.0, "b64": "QUJD"}}
    p = portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=cache, usage={})["products"][0]
    assert p["icon_jpeg"] == "QUJD"


def test_refresh_metrics_keeps_good_commits_when_git_fails(tmp_path, monkeypatch):
    repo = tmp_path / "app"
    repo.mkdir()
    reg = {"product": {"app": {"repos": [str(repo)]}}}
    good = {"7d": 9, "30d": 9, "365d": 9, "weeks": [0] * 11 + [9]}
    cache = {"metrics": {"app": {"commits": good}}, "checked": {"metrics": "before"}}
    monkeypatch.setattr(portfolio, "compute_commits", _REAL_COMPUTE_COMMITS)
    monkeypatch.setattr(portfolio, "git_commit_times", lambda r, now: None)
    assert portfolio.refresh_metrics(reg, cache, 1000.0) is False
    assert cache["metrics"]["app"]["commits"] == good
    assert cache["checked"]["metrics"] == "before"


def test_refresh_metrics_drops_commits_of_a_repo_that_is_gone(tmp_path, monkeypatch):
    reg = {"product": {"app": {"repos": [str(tmp_path / "gone")]}}}
    good = {"7d": 9, "30d": 9, "365d": 9, "weeks": [0] * 11 + [9]}
    cache = {"metrics": {"app": {"commits": good}}, "checked": {"metrics": "before"}}
    monkeypatch.setattr(portfolio, "compute_commits", _REAL_COMPUTE_COMMITS)
    assert portfolio.refresh_metrics(reg, cache, 1000.0) is True
    assert cache["metrics"]["app"]["commits"] is None


def test_icon_keeps_the_old_one_when_conversion_fails(tmp_path, monkeypatch):
    src = tmp_path / "icon.png"
    src.write_bytes(b"x")
    reg = {"product": {"app": {"repos": [str(tmp_path)]}}}
    monkeypatch.setattr(portfolio, "compute_icons", _REAL_COMPUTE_ICONS)
    monkeypatch.setattr(portfolio, "find_icon", lambda repos: src)
    monkeypatch.setattr(portfolio, "convert_icon", lambda s: None)
    old = {"src": "elsewhere", "mtime": 1.0, "b64": "abc"}
    assert portfolio.compute_icons(reg, {"app": old})["app"] == old
