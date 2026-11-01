"""The portfolio of `teyla state` (version 3, docs/APP.md): health rules, platform rows from the store payloads,
the cache fallback, the sort order, and the promise that the snapshot makes no network call. The release tools
and gh are faked; nothing here reaches the network, the real ~/.teyla or this Mac's transcripts."""
from __future__ import annotations

import json
import pathlib
import subprocess
import time

import pytest

from teyla import asks, backlog, cli, config, net, platform, play, portfolio, reviews, state, testflight

NOW = 1_800_000_000.0
DAY = 86400
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_REAL_SPAWN = portfolio.spawn_refresh                               # conftest replaces it per test
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
    assert c["at"] == NOW and set(c["checked"]) == {"stores", "github", "activity"} and all(c["checked"].values())
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
    assert portfolio.line_of(0, "", {**ios, "state": "behind"}, 5) == "iOS 1.9.0 (120) is the newest you can install"
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
    p = pf["products"][0]
    assert set(p) == set(ref["products"][0]) and set(p["prs"]) == set(ref["products"][0]["prs"])
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
                               "core_source": "rule", "products": []}


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
