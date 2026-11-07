"""`teyla growth connect` and `teyla growth publish`: approved items only, one post per item and network, tokens in the
Keychain (a dict here, see conftest), every HTTP call a fake. No test reaches LinkedIn, Meta or Google."""
from __future__ import annotations

import base64
import json
import urllib.parse

import pytest

from teyla import cli, growth, growth_publish as gp, net
from test_growth import NOW, drafted, env  # noqa: F401

REAL_HTTP = gp.http                                       # taken at import, before any fixture replaces it


class Fake:
    """A scripted network: each call takes the first matching (method, url fragment) answer."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def __call__(self, method, url, *, headers=None, data=None, timeout=60):
        self.calls.append((method, url, headers or {}, data))
        for i, (m, frag, resp) in enumerate(self.answers):
            if m == method and frag in url:
                self.answers.pop(i)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected {method} {url}")


def R(status=200, body=None, headers=None):
    return gp.Response(status, {k.lower(): v for k, v in (headers or {}).items()}, json.dumps(body or {}).encode())


def connect_linkedin(expires=NOW + 50 * 86400):
    gp.save_creds("linkedin", dict(network="linkedin", client_id="cid", client_secret="csecret-123456",
                                   access_token="tok-abcdef-123", expires_at=expires, user="urn:li:person:abc"))


def approved(env, monkeypatch, channels=("linkedin-en",)):
    store, cfg, items = drafted(env, monkeypatch, channels=channels)
    for it in items:
        growth.approve(store, it["id"], NOW)
    return growth.Store(), growth.load_config(growth.Store()), [growth.Store().get(i["id"]) for i in items]


def test_creds_round_trip_through_the_keychain_as_base64(_no_real_keychain_or_network_for_growth):
    connect_linkedin()
    raw = _no_real_keychain_or_network_for_growth["teyla-growth-linkedin"]
    assert all(c.isalnum() or c in "+/=" for c in raw)
    assert json.loads(base64.b64decode(raw))["access_token"] == "tok-abcdef-123"
    assert gp.load_creds("linkedin")["user"] == "urn:li:person:abc" and gp.is_connected("linkedin")
    assert gp.forget("linkedin") and gp.load_creds("linkedin") is None and not gp.is_connected("linkedin")


def test_publish_posts_an_approved_linkedin_item_once(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    fake = Fake(("POST", "api.linkedin.com/rest/posts", R(201, headers={"x-restli-id": "urn:li:share:777"})))
    row = gp.publish_one(store, cfg, it, NOW, h=fake)
    assert row["status"] == "published" and row["url"] == "https://www.linkedin.com/feed/update/urn:li:share:777/"
    method, url, headers, data = fake.calls[0]
    body = json.loads(data)
    assert body["author"] == "urn:li:person:abc" and body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"
    assert headers["Authorization"] == "Bearer tok-abcdef-123" and headers["LinkedIn-Version"] == gp.LINKEDIN_VERSION
    got = growth.Store().get(it["id"])
    assert got["status"] == "published" and got["published_via"] == "api" and got["published_by"] == "linkedin"
    pub = [r for r in growth.Store().ledger() if r["ev"] == "published"][-1]
    assert pub["by"] == "owner-approved" and pub["idem"] == gp.idem_key(it["id"], "linkedin") and pub["url"] == row["url"]
    # the second run is a no-op: no call, the same URL
    again = gp.publish_one(growth.Store(), cfg, growth.Store().get(it["id"]), NOW, h=Fake())
    assert again["status"] == "already" and again["url"] == row["url"]


def test_the_ledger_idem_key_stops_a_second_post_even_if_the_item_file_says_approved(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    store.log("published", NOW, id=it["id"], platform="linkedin", url="https://www.linkedin.com/feed/update/x/",
              idem=gp.idem_key(it["id"], "linkedin"))
    row = gp.publish_one(growth.Store(), cfg, it, NOW, h=Fake())
    assert row["status"] == "already" and row["url"].endswith("/x/")


def test_a_start_with_no_end_blocks_a_blind_repost_until_retry(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    fake = Fake(("POST", "rest/posts", gp.PublishError("cannot reach api.linkedin.com: TimeoutError", posted=None)))
    row = gp.publish_one(store, cfg, it, NOW, h=fake)
    assert row["status"] == "unknown" and "may be live" in row["message"]
    assert [r["ev"] for r in growth.Store().ledger()][-2:] == ["publish-start", "publish-unknown"]
    blocked = gp.publish_one(growth.Store(), cfg, growth.Store().get(it["id"]), NOW, h=Fake())
    assert blocked["status"] == "unknown" and "--retry" in blocked["message"]
    ok = Fake(("POST", "rest/posts", R(201, headers={"x-restli-id": "urn:li:share:8"})))
    done = gp.publish_one(growth.Store(), cfg, growth.Store().get(it["id"]), NOW, h=ok, retry=True)
    assert done["status"] == "published"


def test_a_refusal_means_nothing_went_live_and_a_5xx_may_have(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    row = gp.publish_one(store, cfg, it, NOW, h=Fake(("POST", "rest/posts", R(422, {"message": "bad text"}))))
    assert row["status"] == "failed" and "bad text" in row["message"]
    assert gp._idem_state(growth.Store(), gp.idem_key(it["id"], "linkedin"))[0] == "failed"
    row = gp.publish_one(growth.Store(), cfg, growth.Store().get(it["id"]), NOW,
                         h=Fake(("POST", "rest/posts", R(503, {"message": "busy"}))))
    assert row["status"] == "unknown"
    assert gp._idem_state(growth.Store(), gp.idem_key(it["id"], "linkedin"))[0] == "open"


def test_only_an_approved_item_is_published(env, monkeypatch):
    store, cfg, (it,) = drafted(env, monkeypatch, channels=("linkedin-en",))
    connect_linkedin()
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "refused" and "only an approved item" in row["message"]


def test_no_credentials_falls_back_to_the_packet(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "packet" and "not connected" in row["message"] and "teyla growth connect linkedin" in row["message"]
    assert growth.Store().get(it["id"])["status"] == "ready"


def test_safe_mode_falls_back_to_the_packet(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    monkeypatch.setattr(net, "allowed", lambda cfg=None: False)
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "packet" and "safe mode" in row["message"]


def test_x_stays_manual_without_and_with_x_paid(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch, channels=("x-en",))
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "packet" and "POLICY section 11" in row["message"]
    with pytest.raises(gp.PublishRefused, match="no X adapter"):
        gp.XStub().check({"x_paid": True})
    with pytest.raises(gp.PublishRefused, match="two yeses"):
        gp.connect("x", {"publish": {"x_paid": False}})


def test_an_expired_linkedin_token_says_connect_again(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin(expires=NOW - 10)
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "packet" and "connect linkedin" in row["message"]


def test_a_401_names_the_connect_command_and_never_the_token(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    fake = Fake(("POST", "rest/posts", R(401, {"message": "token tok-abcdef-123 is revoked"})))
    row = gp.publish_one(store, cfg, it, NOW, h=fake)
    assert "tok-abcdef-123" not in json.dumps(row) and "[secret]" in row["message"]
    assert "connect" in row["message"]
    assert "tok-abcdef-123" not in growth.Store().ledger_path.read_text()


def test_linkedin_reserved_characters_are_escaped():
    assert gp.linkedin_text("a (b) #c @d_e*") == "a \\(b\\) \\#c \\@d\\_e\\*"


def test_threads_two_calls_and_a_permalink(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch, channels=("threads-en",))
    gp.save_creds("threads", dict(network="threads", access_token="ttok-123456", expires_at=NOW + 50 * 86400,
                                  connected_at=NOW, user="42"))
    fake = Fake(("POST", "/42/threads_publish", R(200, {"id": "m9"})),
                ("POST", "/42/threads", R(200, {"id": "c1"})),
                ("GET", "/v1.0/m9", R(200, {"permalink": "https://www.threads.com/@me/post/abc"})))
    row = gp.publish_one(store, cfg, it, NOW, h=fake)
    assert row["status"] == "published" and row["url"] == "https://www.threads.com/@me/post/abc"
    first = urllib.parse.parse_qs(fake.calls[0][3].decode())
    assert first["media_type"] == ["TEXT"] and len(first["text"][0]) <= 500


def test_instagram_resumable_reel(env, monkeypatch, tmp_path):
    store, cfg, (it,) = approved(env, monkeypatch, channels=("threads-en",))
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00" * 64)
    it = dict(it, platform="instagram", media=[str(vid)])
    creds = dict(network="instagram", access_token="itok-123456", expires_at=NOW + 50 * 86400, user="17")
    fake = Fake(("POST", "/17/media_publish", R(200, {"id": "p5"})),
                ("POST", "/17/media", R(200, {"id": "c7", "uri": "https://rupload.facebook.com/ig-api-upload/v23.0/c7"})),
                ("POST", "rupload.facebook.com", R(200, {"success": True})),
                ("GET", "/c7?", R(200, {"status_code": "IN_PROGRESS"})),
                ("GET", "/c7?", R(200, {"status_code": "FINISHED"})),
                ("GET", "/p5?", R(200, {"permalink": "https://www.instagram.com/reel/xyz/"})))
    res = gp.publish_instagram(it, creds, fake, {}, sleep=lambda s: None)
    assert res.url == "https://www.instagram.com/reel/xyz/"
    up = next(c for c in fake.calls if "rupload" in c[1])
    assert up[2]["Authorization"] == "OAuth itok-123456" and up[2]["file_size"] == "64" and up[3] == b"\x00" * 64


def test_instagram_refuses_an_upload_host_it_does_not_know(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"1")
    fake = Fake(("POST", "/17/media", R(200, {"id": "c7", "uri": "https://evil.example/upload"})))
    with pytest.raises(gp.PublishError, match="upload host"):
        gp.publish_instagram({"id": "g1104-abcd", "media": [str(vid)]}, dict(access_token="t-123456", user="17"), fake, {})


def test_youtube_resumable_upload_warns_when_privacy_is_forced(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"v" * 10)
    item = {"id": "g1104-abcd", "hook": "Six bugs three agents missed", "body": "body text", "media": [str(vid)], "language": "en"}
    fake = Fake(("POST", "upload/youtube/v3/videos", R(200, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=u1"})),
                ("PUT", "upload_id=u1", R(200, {"id": "vid1", "status": {"privacyStatus": "private"}})))
    res = gp.publish_youtube(item, dict(access_token="ytok-123456"), fake, {"youtube_privacy": "public"})
    assert res.url == "https://www.youtube.com/shorts/vid1" and "private" in res.warning
    meta = json.loads(fake.calls[0][3])
    assert meta["snippet"]["title"] == "Six bugs three agents missed" and meta["status"]["privacyStatus"] == "public"
    assert fake.calls[0][2]["X-Upload-Content-Length"] == "10"


def test_a_clip_without_a_video_is_not_published(tmp_path):
    with pytest.raises(gp.PublishError, match="no video"):
        gp.publish_youtube({"id": "g1104-abcd", "media": []}, dict(access_token="t-123456"), Fake(), {})


def test_youtube_refreshes_an_expired_token():
    creds = dict(network="youtube", access_token="old", refresh_token="r-123456", client_id="c", client_secret="s-123456",
                 expires_at=NOW - 1)
    fake = Fake(("POST", "oauth2.googleapis.com/token", R(200, {"access_token": "new", "expires_in": 3600})))
    got, changed = gp.refresh(creds, NOW, fake)
    assert changed and got["access_token"] == "new" and got["expires_at"] == NOW + 3600
    assert urllib.parse.parse_qs(fake.calls[0][3].decode())["grant_type"] == ["refresh_token"]


def test_connect_linkedin_stores_the_member_and_never_prints_the_secret(capsys):
    seen = {}

    def wait(redirect, state):
        seen["state"] = state
        return "code-1"
    fake = Fake(("POST", "linkedin.com/oauth/v2/accessToken", R(200, {"access_token": "at-999999", "expires_in": 5184000})),
                ("GET", "/v2/userinfo", R(200, {"sub": "m1"})))
    opened = []
    got = gp.connect("linkedin", {"publish": {}}, now=NOW, ask=lambda p: "client-1", ask_secret=lambda p: "very-secret-1",
                     opener=opened.append, wait=wait, h=fake)
    assert got["user"] == "urn:li:person:m1"
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0]).query)
    assert q["state"] == [seen["state"]] and q["redirect_uri"] == ["http://127.0.0.1:8765/callback"]
    assert "w_member_social" in q["scope"][0]
    creds = gp.load_creds("linkedin")
    assert creds["access_token"] == "at-999999" and creds["client_secret"] == "very-secret-1"
    out = capsys.readouterr().out
    assert "very-secret-1" not in out and "at-999999" not in out


def test_connect_threads_needs_an_https_redirect_and_takes_a_pasted_address():
    with pytest.raises(gp.NotConnected, match="redirect"):
        gp.connect("threads", {"publish": {}}, ask=lambda p: "x", ask_secret=lambda p: "y", opener=lambda u: None)
    state = {}

    def opener(url):
        state["s"] = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    answers = iter(["client-2"])

    def ask(prompt):
        if prompt.startswith("Paste"):
            return f"https://example.com/oauth?code=abc&state={state['s']}#_"
        return next(answers)
    fake = Fake(("POST", "graph.threads.net/oauth/access_token", R(200, {"access_token": "short-1234", "user_id": 77})),
                ("GET", "graph.threads.net/access_token", R(200, {"access_token": "long-12345", "expires_in": 5184000})))
    got = gp.connect("threads", {"publish": {"redirect": {"threads": "https://example.com/oauth"}}}, now=NOW, ask=ask,
                     ask_secret=lambda p: "sec-123456", opener=opener, h=fake)
    assert got["user"] == "77" and gp.load_creds("threads")["access_token"] == "long-12345"


def test_a_wrong_state_is_refused():
    with pytest.raises(gp.NotConnected, match="state"):
        gp.parse_redirect("https://example.com/cb?code=1&state=other", "mine")


def test_publish_targets_a_master_and_a_day(env, monkeypatch):
    store, cfg, items = approved(env, monkeypatch, channels=("linkedin-en", "x-en"))
    parent = items[0]["parent"]
    got = gp.targets(store, [parent], None)
    assert {i["id"] for i in got} == {i["id"] for i in items if i["parent"] == parent}
    day = gp.targets(store, [], items[0]["day"])
    assert {i["id"] for i in day} == {i["id"] for i in items}


def test_cli_publish_json_and_connect_status(env, monkeypatch, capsys):
    store, cfg, (it,) = approved(env, monkeypatch)
    rc = cli.main(["growth", "publish", it["id"], "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["version"] == 1 and doc["packets"] == 1 and doc["results"][0]["network"] == "linkedin"
    rc = cli.main(["growth", "connect", "--status", "--json"])
    rows = json.loads(capsys.readouterr().out)["networks"]
    assert rc == 0 and [r["network"] for r in rows] == ["linkedin", "threads", "instagram", "youtube", "x"]
    assert not any(r["connected"] for r in rows)


def test_cli_connect_refuses_without_a_terminal(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["growth", "connect", "linkedin"]) == 2
    assert "your own terminal" in capsys.readouterr().err


def test_the_section_reports_a_connected_channel(env, monkeypatch):
    approved(env, monkeypatch)
    connect_linkedin()
    sec = growth.section(NOW)
    assert next(c for c in sec["channels"] if c["platform"] == "linkedin")["connected"] is True


# --- review round 1 -----------------------------------------------------------------------------------------------

def test_a_dropped_connection_on_an_upload_put_may_have_gone_live(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    fresh = REAL_HTTP                                      # the conftest fake replaces gp.http in every test
    with pytest.raises(gp.PublishError) as e:
        fresh("PUT", "https://www.googleapis.com/upload/x", data=b"chunk")
    assert e.value.posted is None
    with pytest.raises(gp.PublishError) as e:
        fresh("GET", "https://graph.threads.net/x")
    assert e.value.posted is False


def test_a_second_publish_while_the_first_holds_the_lock_posts_nothing(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    with gp._idem_lock(store, gp.idem_key(it["id"], "linkedin")) as held:
        assert held
        row = gp.publish_one(growth.Store(), cfg, it, NOW, h=Fake())
    assert row["status"] == "unknown" and "running now" in row["message"]
    assert not [r for r in growth.Store().ledger() if r["ev"] == "publish-start"]


def test_media_on_a_text_only_network_goes_to_the_packet(env, monkeypatch, tmp_path):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    pic = tmp_path / "slide.png"
    pic.write_bytes(b"png")
    it["media"] = [str(pic)]
    row = gp.publish_one(store, cfg, it, NOW, h=Fake())
    assert row["status"] == "packet" and "text only" in row["message"]


def test_a_token_refresh_that_fails_does_not_stop_the_batch(env, monkeypatch):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()

    def refresh(creds, now, h):
        raise gp.PublishError("token endpoint busy", posted=False)
    monkeypatch.setattr(gp, "refresh", refresh)
    doc = gp.publish_many(store, cfg, [it], NOW, h=Fake())
    assert doc["results"][0]["status"] == "failed" and "refresh" in doc["results"][0]["message"] and doc["failed"] == 1


def test_cli_publish_json_exits_0_with_the_failure_in_the_report(env, monkeypatch, capsys):
    store, cfg, (it,) = approved(env, monkeypatch)
    connect_linkedin()
    monkeypatch.setattr(gp, "http", Fake(("POST", "rest/posts", R(422, {"message": "bad text"}))))
    monkeypatch.setattr(net, "allowed", lambda cfg=None: True)
    rc = cli.main(["growth", "publish", it["id"], "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["failed"] == 1 and doc["results"][0]["status"] == "failed"
