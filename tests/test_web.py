"""`teyla web`: the security checks, every route's shape, apply and undo through the API, notes, the idle exit.
Every machine is a fake HOME with invented sessions; the real ~/.claude, ~/.codex and ~/.teyla are never read."""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading
import time

import pytest

from teyla import cli, offers, pricing, registry, routine_install
from teyla.web import api as api_mod
from teyla.web import server as server_mod

OPUS = "claude-opus-5-5"
SETTINGS = '{\n  "model": "opus",\n  "theme": "dark"\n}\n'
ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")
    # O7 writes launchd jobs; no test here may.
    monkeypatch.setattr(routine_install, "install", lambda *a, **k: ["stub: routine installed"])
    try:                                                   # a refresh of the first-screen figures starts a process
        from teyla import figures
        monkeypatch.setattr(figures, "spawn_refresh", lambda *a, **k: None, raising=False)
    except ImportError:
        pass


@pytest.fixture
def machine(fake_home):
    h = fake_home
    (h.home / ".claude").mkdir(exist_ok=True)
    h.settings.write_text(SETTINGS)
    h.session("s1aaaa", [(OPUS, h.usage(cread=320_000, out=100))] * 40)
    h.session("s2bbbb", [(OPUS, h.usage(cread=280_000, out=100))] * 40)
    reg = registry.load()
    reg["product"]["demo"] = registry.new_product("demo", paths=["/work/demo"], stage="building", name="Demo")
    registry.save(reg)
    return h


class Web:
    """A running server and a tiny client. `Host` and the headers are the caller's to break."""

    def __init__(self, srv: server_mod.Server):
        self.srv, self.cookie = srv, None

    def raw(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.srv.port}"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def login(self):
        status, headers, _ = self.raw("GET", f"/?t={self.srv.token}")
        assert status == 302 and headers["Location"] == "/"
        self.cookie = headers["Set-Cookie"].split(";")[0]

    def call(self, method, path, body=None, headers=None):
        h = {"Cookie": self.cookie, **(headers or {})}
        if method == "POST":
            h.setdefault("X-Teyla-Token", self.srv.token)
        status, hdrs, raw = self.raw(method, path, body, h)
        return status, json.loads(raw) if hdrs.get("Content-Type", "").startswith("application/json") else raw

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, {} if body is None else body)

    def settle(self, name):
        job = self.srv.api.jobs[name]
        job.ensure()
        job.join(60)
        assert job.get()["data"] is not None, job.get()["error"]


@pytest.fixture
def web(machine, tmp_path):
    srv = server_mod.Server(port=0, api=api_mod.Api(cache=tmp_path / "web-cache.json"), idle_s=3600, watch_s=0.05)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    w = Web(srv)
    w.login()
    yield w
    srv.shutdown()
    t.join(5)


# --- the security model -------------------------------------------------------------------------

def test_the_server_binds_to_loopback_only(web):
    assert web.srv.server_address[0] == "127.0.0.1"
    assert web.srv.token and len(web.srv.token) >= 43               # 32 bytes, urlsafe


def test_no_token_and_no_cookie_is_403(web):
    for path in ("/", "/app.js", "/api/start", "/api/products"):
        status, _, body = web.raw("GET", path)
        assert status == 403 and "error" in json.loads(body)


def test_a_wrong_token_is_403_and_sets_no_cookie(web):
    status, headers, _ = web.raw("GET", "/?t=wrong")
    assert status == 403 and "Set-Cookie" not in headers


def test_the_token_becomes_an_httponly_strict_cookie_and_leaves_the_address(web):
    status, headers, _ = web.raw("GET", f"/?t={web.srv.token}")
    assert status == 302 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and web.srv.token in cookie
    status, _, page = web.raw("GET", "/", headers={"Cookie": cookie.split(";")[0]})
    assert status == 200 and b"<title>" in page


def test_a_foreign_host_is_403_even_with_the_cookie(web):
    for host in ("evil.example", f"evil.example:{web.srv.port}", "127.0.0.1", f"127.0.0.1:{web.srv.port + 1}"):
        status, _, body = web.raw("GET", "/api/start", headers={"Cookie": web.cookie}, host=host)
        assert status == 403, host
        assert "error" in json.loads(body)


def test_localhost_is_allowed(web):
    status, _, _ = web.raw("GET", "/api/notes", headers={"Cookie": web.cookie}, host=f"localhost:{web.srv.port}")
    assert status == 200


def test_a_post_without_the_token_header_is_403(web):
    status, _, body = web.raw("POST", "/api/notes", {"text": "x"}, headers={"Cookie": web.cookie})
    assert status == 403 and "X-Teyla-Token" in json.loads(body)["error"]
    status, _, _ = web.raw("POST", "/api/notes", {"text": "x"}, headers={"Cookie": web.cookie, "X-Teyla-Token": "nope"})
    assert status == 403
    assert web.get("/api/notes")[1]["notes"] == []


def test_a_post_from_another_origin_is_403(web):
    status, _ = web.call("POST", "/api/notes", {"text": "x"}, headers={"Origin": "https://evil.example"})
    assert status == 403
    status, _ = web.call("POST", "/api/notes", {"text": "x"}, headers={"Origin": f"http://127.0.0.1:{web.srv.port}"})
    assert status == 201


def test_a_post_body_must_be_a_small_json_object(web):
    assert web.call("POST", "/api/notes", b"not json")[0] == 400
    assert web.call("POST", "/api/notes", b"[1]")[0] == 400
    assert web.call("POST", "/api/notes", b'{"text": "x"}', headers={"Content-Type": "text/plain"})[0] == 415
    assert web.call("POST", "/api/notes", b"x" * (server_mod.MAX_BODY + 1))[0] == 413


def test_responses_carry_no_cors_and_a_strict_csp(web):
    _, headers, _ = web.raw("GET", "/", headers={"Cookie": web.cookie})
    assert not any(k.lower().startswith("access-control") for k in headers)
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "'unsafe-inline'" not in csp and "default-src 'none'" in csp
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"


def test_other_methods_and_unknown_paths(web):
    assert web.call("PUT", "/api/notes", {})[0] == 405
    assert web.call("DELETE", "/api/notes")[0] == 405
    assert web.call("GET", "/nope")[0] == 404
    status, body = web.get("/api/nope")
    assert status == 404 and "error" in body
    assert web.post("/api/start")[0] == 405


def test_the_served_page_embeds_the_token_for_posts_and_uses_no_inline_script(web):
    _, _, page = web.raw("GET", "/", headers={"Cookie": web.cookie})
    html = page.decode()
    assert f'content="{web.srv.token}"' in html and "{{TOKEN}}" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) and " style=" not in html
    for path in ("/app.js", "/app.css"):
        assert web.get(path)[0] == 200


# --- the idle exit ------------------------------------------------------------------------------

def test_the_server_stops_by_itself_after_the_idle_time(tmp_path):
    srv = server_mod.Server(port=0, api=api_mod.Api(cache=tmp_path / "c.json"), idle_s=0.3, watch_s=0.05)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive() and srv.idle_stopped


def test_a_request_resets_the_idle_timer(tmp_path):
    srv = server_mod.Server(port=0, api=api_mod.Api(cache=tmp_path / "c.json"), idle_s=0.6, watch_s=0.05)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    w = Web(srv)
    for _ in range(5):
        time.sleep(0.25)
        assert w.raw("GET", "/api/start")[0] == 403          # refused, yet it counts as a request
    assert t.is_alive() and not srv.idle_stopped
    t.join(10)
    assert not t.is_alive() and srv.idle_stopped


def test_run_prints_the_address_and_what_it_promises(monkeypatch, capsys):
    monkeypatch.setattr(server_mod.Server, "serve", lambda self: None)
    monkeypatch.setattr("webbrowser.open", lambda url: pytest.fail("--no-open must not open a browser"))
    assert cli.main(["web", "--no-open"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"http://127\.0\.0\.1:\d+/\?t=\S{40,}", out)
    assert "127.0.0.1 only" in out and "Ctrl-C" in out and "2 hours" in out


def test_port_is_pinned_and_a_busy_port_is_a_sentence(monkeypatch, capsys):
    held = server_mod.Server(port=0)
    try:
        monkeypatch.setattr(server_mod.Server, "serve", lambda self: None)
        assert server_mod.run(port=held.port, open_browser=False) == 1
        assert "cannot listen on port" in capsys.readouterr().err
    finally:
        held.server_close()


# --- Start: the diagnosis, apply and undo -----------------------------------------------------------

def test_get_start_shape(web):
    web.settle("start")
    status, d = web.get("/api/start")
    assert status == 200 and d["refreshing"] is False and d["error"] is None and d["at"]
    assert d["diagnosis"]["sessions"] == 2 and d["diagnosis"]["total_usd"] > 0
    assert d["summary_text"]
    by_id = {o["id"]: o for o in d["offers"]}
    assert list(by_id) == [f"O{i}" for i in range(1, 8)]
    o1 = by_id["O1"]
    assert o1["applies"] is True and o1["applied"] is None and o1["saving_usd_month"]["high"] >= o1["saving_usd_month"]["low"]
    assert "autoCompactWindow" in o1["confirm"] and "settings.json" in o1["confirm"]
    assert {"title", "change", "tradeoff", "undo", "explain"} <= set(o1)


def test_the_first_load_does_not_wait_for_the_count(machine, tmp_path, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(api_mod, "_start_compute", lambda: gate.wait(10) and {"diagnosis": {}, "summary_text": "", "offers": []})
    a = api_mod.Api(cache=tmp_path / "c.json")
    t0 = time.monotonic()
    status, d = a.route("GET", "/api/start", {}, {})
    assert status == 200 and time.monotonic() - t0 < 2
    assert d["refreshing"] is True and d["diagnosis"] is None and d["offers"] == []
    gate.set()
    a.jobs["start"].join(10)


def test_a_cached_diagnosis_is_served_while_it_refreshes(web, tmp_path, monkeypatch):
    web.settle("start")
    cache = json.loads((tmp_path / "web-cache.json").read_text())
    assert cache["version"] == api_mod.CACHE_VERSION and cache["start"]["data"]["offers"]
    assert oct((tmp_path / "web-cache.json").stat().st_mode & 0o777) == "0o600"
    gate = threading.Event()
    monkeypatch.setattr(api_mod, "_start_compute", lambda: gate.wait(10) and cache["start"]["data"])
    a = api_mod.Api(cache=tmp_path / "web-cache.json")
    a.jobs["start"].at -= 10 * 3600                      # older than the time-to-live
    _, d = a.route("GET", "/api/start", {}, {})
    assert d["refreshing"] is True and d["diagnosis"] and d["offers"]      # the old numbers, marked as refreshing
    gate.set()
    a.jobs["start"].join(10)


def test_apply_then_undo_through_the_api_restores_settings_byte_for_byte(web, machine):
    web.settle("start")
    before = machine.settings.read_bytes()
    status, r = web.post("/api/apply", {"offer": "O1", "confirm": True})
    assert status == 200 and r["undoable"] is True
    s = json.loads(machine.settings.read_text())
    assert s["autoCompactWindow"] == 335000 and s["theme"] == "dark"
    _, d = web.get("/api/start")
    o1 = next(o for o in d["offers"] if o["id"] == "O1")
    assert o1["applied"]["undoable"] is True and o1["applies"] is False       # the card is right before the recount
    assert any(c["offer"] == "O1" for c in d["changes"])
    status, r = web.post("/api/undo", {"ref": "O1"})
    assert status == 200 and r["undone"]
    assert machine.settings.read_bytes() == before
    o1 = next(o for o in web.get("/api/start")[1]["offers"] if o["id"] == "O1")
    assert o1["applied"] is None and o1["applies"] is True


def test_apply_needs_the_confirmation_and_a_known_offer(web, machine):
    before = machine.settings.read_bytes()
    assert web.post("/api/apply", {"offer": "O1"})[0] == 400
    assert web.post("/api/apply", {"offer": "O1", "confirm": "yes"})[0] == 400
    assert web.post("/api/apply", {})[0] == 400
    status, body = web.post("/api/apply", {"offer": "O9", "confirm": True})
    assert status == 404 and "O9" in body["error"]
    assert machine.settings.read_bytes() == before


def test_applying_twice_is_a_409_and_changes_nothing_more(web, machine):
    assert web.post("/api/apply", {"offer": "O1", "confirm": True})[0] == 200
    after = machine.settings.read_bytes()
    status, body = web.post("/api/apply", {"offer": "O1", "confirm": True})
    assert status == 409 and "error" in body and machine.settings.read_bytes() == after


def test_a_settings_file_that_does_not_parse_is_a_409_with_a_sentence(web, machine):
    machine.settings.write_text("{oops")
    status, body = web.post("/api/apply", {"offer": "O1", "confirm": True})
    assert status in (404, 409, 500) and body["error"] and "Traceback" not in body["error"]
    assert machine.settings.read_text() == "{oops"


def test_undo_of_a_command_change_shows_the_refusal_message(web, machine):
    (machine.home / ".codex").mkdir()
    web.settle("start")
    status, r = web.post("/api/apply", {"offer": "O6", "confirm": True})
    assert status == 200 and r["undoable"] is False and "teyla uninstall" in r["undo"]
    d = web.get("/api/start")[1]
    o6 = next(o for o in d["offers"] if o["id"] == "O6")
    assert o6["applied"]["undoable"] is False
    hooks = (machine.home / ".codex" / "hooks.json").read_bytes()
    status, body = web.post("/api/undo", {"ref": "O6"})
    assert status == 409 and "teyla uninstall" in body["error"] and "owns these files" in body["error"]
    assert (machine.home / ".codex" / "hooks.json").read_bytes() == hooks


def test_undo_after_the_key_changed_offers_force_and_force_reverts(web, machine):
    web.post("/api/apply", {"offer": "O1", "confirm": True})
    machine.settings.write_text(machine.settings.read_text().replace("335000", "420000"))
    status, body = web.post("/api/undo", {"ref": "O1"})
    assert status == 409 and body["can_force"] is True and "420000" in body["error"]
    assert json.loads(machine.settings.read_text())["autoCompactWindow"] == 420000
    status, _ = web.post("/api/undo", {"ref": "O1", "force": True})
    assert status == 200 and "autoCompactWindow" not in json.loads(machine.settings.read_text())


def test_undo_of_nothing_is_a_404_and_without_a_ref_a_400(web):
    status, body = web.post("/api/undo", {"ref": "O1"})
    assert status == 404 and "error" in body
    assert web.post("/api/undo", {})[0] == 400


def test_confirm_text_restates_the_file_and_key_for_every_kind():
    j = api_mod.confirm_text({"change": {"kind": "json", "key_path": ["env", "X"], "new": "sonnet", "file": "~/.claude/settings.json"}})
    assert "env.X" in j and '"sonnet"' in j and "~/.claude/settings.json" in j and "backup" in j
    t = api_mod.confirm_text({"change": {"kind": "toml", "key_path": ["model_reasoning_effort"], "new": "medium", "file": "~/.codex/config.toml"}})
    assert "model_reasoning_effort" in t and "config.toml" in t
    f = api_mod.confirm_text({"change": {"kind": "file", "file": "~/.claude/agents/scout.md"}})
    assert "scout.md" in f and "nothing if the file exists" in f
    c = api_mod.confirm_text({"change": {"kind": "command", "command": "teyla policy sync", "summary": "one rules file"}})
    assert "`teyla policy sync`" in c


def test_refresh_starts_a_recount_and_knows_what_it_can_refresh(web):
    web.settle("start")
    status, r = web.post("/api/refresh", {"what": "start"})
    assert status == 202 and r["what"] == "start"
    web.srv.api.jobs["start"].join(60)
    assert web.post("/api/refresh", {"what": "other"})[0] == 400


# --- Today ------------------------------------------------------------------------------------

def test_today_is_the_cli_snapshot_and_shares_the_spend_count(web):
    from teyla import figures
    status, d = web.get("/api/today")
    assert status == 200 and {"version", "generated", "sessions", "questions", "notes", "spend", "suggestion"} <= set(d)
    assert d["sessions"] is True                                           # spend is null until the count is done: the page polls
    web.settle("spend")
    status, d = web.get("/api/today")
    s = web.get("/api/spend")[1]["spend"]
    assert d["spend"]["this_week"] == s["this_week"] and d["spend"]["last_week"] == s["last_week"]
    assert figures.cached("spend")[0]["this_week"] == s["this_week"]       # `teyla today` reads the same figure


def test_today_does_not_start_a_second_count_while_the_page_counts(web, monkeypatch):
    from teyla import figures
    gate = threading.Event()
    spawned = []
    monkeypatch.setattr(figures, "spawn_refresh", lambda *a, **k: spawned.append(1))
    monkeypatch.setattr(api_mod, "_spend_compute", lambda: gate.wait(10) and {"this_week": 1.0, "last_week": 0.0})
    web.srv.api.jobs["spend"].fn = api_mod._spend_compute
    assert web.get("/api/today")[0] == 200
    assert web.srv.api.jobs["spend"].get()["refreshing"] is True
    assert not figures._lock().exists()                                      # taken for the call, released after it
    gate.set()
    web.srv.api.jobs["spend"].join(10)


def test_the_diagnosis_and_an_apply_reach_the_first_screen(web):
    from teyla import figures
    web.settle("start")
    rep = figures.start_report()
    assert rep["finished"] is False and rep["total_usd"] > 0 and rep["offers"][0]["id"] == "O1"
    assert web.post("/api/apply", {"offer": "O1", "confirm": True})[0] == 200
    assert figures.start_report()["finished"] is True
    web.srv.api.jobs["start"].join(60)


# --- Products ---------------------------------------------------------------------------------

def test_get_products_shape(web):
    web.post("/api/notes", {"text": "an idea about the demo", "product": "demo"})
    web.post("/api/notes", {"text": "a loose thought"})
    status, d = web.get("/api/products")
    assert status == 200 and d["inbox"] == 1 and d["registered"] == 1
    row = next(p for p in d["products"] if p["id"] == "demo")
    assert row["name"] == "Demo" and row["stage"] == "building" and row["registered"] is True
    assert row["notes"] == 1 and row["waiting"] == 0 and {"focus", "primary", "repos", "muted"} <= set(row)


def test_get_product_shape_with_spend(web):
    web.settle("spend")
    web.post("/api/notes", {"text": "an idea about the demo", "product": "demo"})
    status, d = web.get("/api/products/demo")
    assert status == 200 and d["id"] == "demo" and d["name"] == "Demo"
    assert [n["text"] for n in d["notes"]] == ["an idea about the demo"]
    assert d["asks"] == [] and d["spend"]["this_week"] > 0 and d["sessions"]
    assert {"harness", "sid", "last", "usd"} <= set(d["sessions"][0])
    assert d["spend_refreshing"] is False and d["repos"] == [] and d["paths"] == ["/work/demo"]


def test_a_missing_product_is_a_404_json(web):
    status, body = web.get("/api/products/nope")
    assert status == 404 and "nope" in body["error"]
    assert web.get("/api/products/a%20b%2Fc")[0] == 404


# --- Notes ------------------------------------------------------------------------------------

def test_note_add_link_drop_undrop(web):
    status, n = web.post("/api/notes", {"text": "  keep this exactly  "})
    assert status == 201 and n["text"] == "keep this exactly" and n["product"] == "inbox"
    status, n2 = web.post("/api/notes", {"text": "for the demo", "product": "demo"})
    assert status == 201 and n2["product"] == "demo" and n2["linked_by"] == "owner"
    _, d = web.get("/api/notes")
    assert {x["id"] for x in d["notes"]} == {n["id"], n2["id"]} and d["inbox"] == 1
    assert {"id": "demo", "name": "Demo"} in d["candidates"]
    status, r = web.post(f"/api/notes/{n['id']}/link", {"product": "demo"})
    assert status == 200 and r["changed"] is True and r["note"]["product"] == "demo"
    assert web.get("/api/notes")[1]["inbox"] == 0
    status, r = web.post(f"/api/notes/{n['id']}/drop")
    assert status == 200 and r["note"]["dropped"] is True
    assert {x["id"] for x in web.get("/api/notes")[1]["notes"]} == {n2["id"]}
    assert {x["id"] for x in web.get("/api/notes?all=1")[1]["notes"]} == {n["id"], n2["id"]}
    assert web.post(f"/api/notes/{n['id']}/link", {"product": "inbox"})[0] == 409       # a dropped note is not moved
    status, r = web.post(f"/api/notes/{n['id']}/undrop")
    assert status == 200 and r["note"]["dropped"] is False
    assert {x["id"] for x in web.get("/api/notes?product=demo")[1]["notes"]} == {n["id"], n2["id"]}


def test_note_errors_are_json_4xx(web):
    assert web.post("/api/notes", {"text": "   "})[0] == 400
    assert web.post("/api/notes", {})[0] == 400
    status, body = web.post("/api/notes", {"text": "x", "product": "no-such-product"})
    assert status == 400 and "error" in body
    status, body = web.post("/api/notes/zzzzzz/drop")
    assert status == 404 and "error" in body
    n = web.post("/api/notes", {"text": "x"})[1]
    assert web.post(f"/api/notes/{n['id']}/link", {})[0] == 400


def test_a_note_is_stored_as_text_not_markup(web):
    text = '<img src=x onerror="alert(1)"> & "quotes"'
    n = web.post("/api/notes", {"text": text})[1]
    assert web.get("/api/notes")[1]["notes"][0]["text"] == text and n["text"] == text


# --- Spend ------------------------------------------------------------------------------------

def test_get_spend_shape(web):
    status, d = web.get("/api/spend")
    assert status == 200 and {"spend", "at", "refreshing", "error"} <= set(d)
    web.settle("spend")
    d = web.get("/api/spend")[1]
    s = d["spend"]
    assert s["days"] == 14 and len(s["by_day"]) == 14 and s["sessions"] == 2
    assert [x["week"] for x in s["by_day"]] == ["last"] * 7 + ["this"] * 7
    assert s["this_week"] > 0 and s["last_week"] == 0 and s["change_pct"] is None
    assert s["by_model"][0]["model"] == OPUS and s["by_product"][0]["product"] == "demo"
    assert "product_sessions" not in s
    assert round(sum(x["usd"] for x in s["by_day"]), 2) == round(s["this_week"] + s["last_week"], 2)
    assert round(sum(m["this_week"] for m in s["by_model"]), 2) == s["this_week"]


def test_spend_view_splits_two_weeks_without_a_machine():
    import datetime as dt
    today = dt.date(2026, 10, 20)
    rows = [{"harness": "claude-code", "sid": "abcdef123456", "cwd": "/work/demo", "project": "demo", "last": "2026-10-19T10:00:00Z",
             "day_usd": {"2026-10-19": 3.0, "2026-10-10": 3.0},
             "day_model_usd": {"2026-10-19": {"m-a": 3.0}, "2026-10-10": {"m-a": 1.0, "m-b": 2.0}}}]
    v = api_mod.spend_view(rows, registry._empty(), today)
    assert (v["this_week"], v["last_week"], v["change_pct"]) == (3.0, 3.0, 0)
    assert {m["model"]: (m["this_week"], m["last_week"]) for m in v["by_model"]} == {"m-a": (3.0, 1.0), "m-b": (0.0, 2.0)}


# --- the files stay in step with the brand ------------------------------------------------------

def _css_vars(block: str) -> dict:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", block))


def test_the_css_colours_are_the_brand_tokens():
    tokens = json.loads((ROOT / "brand" / "tokens.json").read_text())
    css = (ROOT / "src" / "teyla" / "web" / "app.css").read_text()
    light = _css_vars(css.split("@media")[0])
    dark = _css_vars(css.split("prefers-color-scheme: dark)")[1])
    for name, key in (("bg", "background"), ("surface", "surface"), ("border", "border"), ("text", "text"), ("text-2", "text-secondary"),
                      ("primary", "primary"), ("on-primary", "on-primary"), ("needs-you", "needs-you"), ("saving", "saving"),
                      ("danger", "danger")):
        assert light[name].lower() == tokens["color"]["light"][key].lower(), name
        assert dark[name].lower() == tokens["color"]["dark"][key].lower(), name


def test_the_page_has_no_external_resource_and_names_every_tab():
    html = (ROOT / "src" / "teyla" / "web" / "index.html").read_text()
    js = (ROOT / "src" / "teyla" / "web" / "app.js").read_text()
    css = (ROOT / "src" / "teyla" / "web" / "app.css").read_text()
    for text in (html, js, css):
        assert not re.search(r"(?:src|href)=\"https?://|url\(\s*['\"]?https?://|@import|fetch\(\s*['\"]https?://", text)
    for tab in ("start", "today", "products", "notes", "spend"):
        assert f'data-tab="{tab}"' in html and f"{tab}:" in js
    assert "innerHTML" not in js and "eval(" not in js


def test_the_header_lockup_has_the_brand_geometry():
    html = (ROOT / "src" / "teyla" / "web" / "index.html").read_text()
    svg = (ROOT / "brand" / "lockup.svg").read_text()
    mine = "<svg viewBox" + html.split("</svg>")[0].split("<svg viewBox", 1)[1]
    for pattern in (r' d="([^"]+)"', r'<rect ([^>]*?)(?: fill| class)', r'<circle ([^>]*?)/>', r'transform="([^"]+)"', r'viewBox="([^"]+)"'):
        assert re.findall(pattern, mine) == re.findall(pattern, svg) != [], pattern


def test_app_js_parses():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the browser is the only thing that runs app.js")
    r = subprocess.run([node, "--check", str(ROOT / "src" / "teyla" / "web" / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_two_dashboards_on_one_machine_keep_their_own_cookie(web, tmp_path):
    other = server_mod.Server(port=0, api=api_mod.Api(cache=tmp_path / "other.json"), idle_s=3600, watch_s=0.05)
    t = threading.Thread(target=other.serve, daemon=True)
    t.start()
    try:
        w2 = Web(other)
        w2.login()
        assert web.cookie.split("=")[0] != w2.cookie.split("=")[0]
        jar = web.cookie + "; " + w2.cookie                      # a browser sends both: ports do not separate cookies
        assert web.raw("GET", "/api/notes", headers={"Cookie": jar})[0] == 200
        assert w2.raw("GET", "/api/notes", headers={"Cookie": jar})[0] == 200
    finally:
        other.shutdown()
        t.join(5)
