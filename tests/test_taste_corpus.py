"""The taste corpus (taste_corpus.py, taste_capture.py). The browser, the network and the model are replaced:
no test opens a page, calls Apple or starts a real claude. Fixtures are generic."""
from __future__ import annotations

import json
import pathlib
import struct
import zlib

import pytest

from teyla import cli, taste_capture, taste_corpus

SHOT_URL = "https://is1-ssl.mzstatic.com/image/thumb/shot1/392x696bb.png"


def png(size=8) -> bytes:
    raw = b"".join(b"\x00" + bytes((200, 30, 30)) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    d = tmp_path / "corpus"
    monkeypatch.setenv("TEYLA_TASTE_CORPUS", str(d))
    return d


def fake_browser(monkeypatch, *, fail=None):
    calls = []

    def run(url, outdir):
        calls.append(url)
        if fail:
            raise fail
        outdir.mkdir(parents=True, exist_ok=True)
        for w in (390, 1440):
            (outdir / f"page-{w}.jpg").write_bytes(png())
        return {"files": ["evidence/page-390.jpg", "evidence/page-1440.jpg"], "backend": "fake",
                "page": {"title": "Atlas", "styles": {"body": {"fontSize": "16px"}}, "copy": ["Plan the week", "Start"]}}

    monkeypatch.setattr(taste_capture, "_browser_capture", run)
    return calls


def add(args, capsys=None):
    rc = cli.main(["taste", "add", *args])
    return rc


def only_entry(corpus):
    ds = sorted(corpus.iterdir())
    assert len(ds) == 1
    return ds[0], json.loads((ds[0] / "entry.json").read_text())


def test_add_with_comment_captures_and_is_proposed(corpus, monkeypatch, capsys):
    calls = fake_browser(monkeypatch)
    assert add(["https://example.com/", "—", "great", "neutral", "design"]) == 0
    d, e = only_entry(corpus)
    assert calls == ["https://example.com/"]
    assert d.name == f"{e['created'][:4]}{e['created'][5:7]}{e['created'][8:10]}-{e['id']}"
    assert e["claim"] == "great neutral design" and e["claim_source"] == "owner"
    assert (e["verdict"], e["scope"], e["kind"], e["status"]) == ("like", "portfolio", "screen", "proposed")
    assert e["evidence"]["files"] == ["evidence/page-390.jpg", "evidence/page-1440.jpg"]
    assert e["evidence"]["measured"]["copy"] == ["Plan the week", "Start"]
    assert (d / "evidence" / "page-390.jpg").is_file()
    assert taste_corpus.validate(e) == []
    out = capsys.readouterr().out
    assert e["id"] in out and "accept" in out


def test_add_without_comment_is_raw_and_says_so(corpus, monkeypatch, capsys):
    fake_browser(monkeypatch)
    assert add(["https://example.com/"]) == 0
    _, e = only_entry(corpus)
    assert e["status"] == "raw" and e["claim"] == "" and "claim_source" not in e
    out = capsys.readouterr().out
    assert "not a style source" in out and f"teyla taste note {e['id']}" in out


def test_flags_scope_and_kind(corpus, monkeypatch):
    fake_browser(monkeypatch)
    assert add(["--dislike", "--product", "Recipes", "https://example.com/p", "too many boxes"]) == 0
    _, e = only_entry(corpus)
    assert (e["verdict"], e["scope"]) == ("dislike", "product:recipes")
    assert add(["--mixed", "--scope", "voice", "https://example.com/q", "warm", "copy,", "stiff", "layout", "--no-capture"]) == 0
    kinds = {json.loads((d / "entry.json").read_text())["verdict"]: json.loads((d / "entry.json").read_text())["kind"] for d in corpus.iterdir()}
    assert kinds["mixed"] == "copy"


def test_bad_input_is_refused(corpus, capsys):
    assert add(["not a url"]) == 1
    assert add(["--dislike", "--mixed", "https://example.com/"]) == 1
    assert add(["--scope", "everywhere", "https://example.com/"]) == 1
    assert add(["--product", "a", "--scope", "voice", "https://example.com/"]) == 1
    assert add([]) == 1
    assert not corpus.exists() or not list(corpus.iterdir())


def test_add_an_image_file_keeps_a_copy(corpus, tmp_path, capsys):
    shot = tmp_path / "shot.png"
    shot.write_bytes(png())
    assert add([str(shot), "calm", "empty", "state"]) == 0
    d, e = only_entry(corpus)
    assert e["source"] == str(shot.resolve()) and e["evidence"]["files"] == ["evidence/source.png"]
    assert (d / "evidence" / "source.png").read_bytes() == shot.read_bytes()
    bad = tmp_path / "x.png"
    bad.write_text("no")
    assert add([str(bad), "x"]) == 1


def test_safe_mode_stores_the_entry_and_skips_the_page(corpus, monkeypatch, capsys):
    calls = fake_browser(monkeypatch)
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert add(["https://example.com/", "nice"]) == 0
    assert not calls
    d, e = only_entry(corpus)
    assert "safe mode" in capsys.readouterr().err and e["evidence"]["files"] == []
    assert cli.main(["taste", "capture", e["id"], "--allow-network"]) == 0
    assert calls == ["https://example.com/"]
    assert json.loads((d / "entry.json").read_text())["evidence"]["captured"]


def test_no_browser_records_what_to_install_and_capture_retries(corpus, monkeypatch, capsys):
    fake_browser(monkeypatch, fail=taste_capture.CaptureUnavailable(taste_capture.INSTALL_HINT))
    assert add(["https://example.com/", "nice"]) == 0
    d, e = only_entry(corpus)
    assert "teyla[capture]" in e["evidence"]["error"] and e["evidence"]["files"] == []
    fake_browser(monkeypatch)
    assert cli.main(["taste", "capture", e["id"]]) == 0
    e2 = json.loads((d / "entry.json").read_text())
    assert e2["evidence"]["error"] is None and len(e2["evidence"]["files"]) == 2


def test_no_capture_flag(corpus, monkeypatch):
    calls = fake_browser(monkeypatch)
    assert add(["--no-capture", "https://example.com/", "nice"]) == 0
    assert not calls


def test_appstore_uses_the_lookup_api_not_a_browser(corpus, monkeypatch):
    def boom(*a):
        raise AssertionError("no browser for an App Store link")

    monkeypatch.setattr(taste_capture, "_browser_capture", boom)
    fetched = []

    def fetch(url, limit=0):
        fetched.append(url)
        if "lookup" in url:
            return json.dumps({"results": [{
                "trackName": "Atlas Planner", "sellerName": "Acme", "primaryGenreName": "Productivity",
                "description": "Plan every day in one place. Nothing else gets in your way.",
                "screenshotUrls": [SHOT_URL, "https://evil.example.com/steal.png"]}]}).encode()
        return png()

    monkeypatch.setattr(taste_capture, "_fetch", fetch)
    assert add(["https://apps.apple.com/es/app/atlas-planner/id123456789", "clean", "store", "page"]) == 0
    d, e = only_entry(corpus)
    assert fetched[0] == "https://itunes.apple.com/lookup?id=123456789&country=es"
    assert SHOT_URL in fetched and not any("evil" in u for u in fetched)
    assert e["kind"] == "product" and e["evidence"]["files"] == ["evidence/appstore-1.png"]
    assert e["evidence"]["backend"] == "itunes-lookup" and e["evidence"]["measured"]["copy"][0] == "Atlas Planner"
    assert (d / "evidence" / "appstore-1.png").is_file()


def test_only_http_pages(tmp_path):
    with pytest.raises(taste_capture.CaptureError):
        taste_capture._browser_capture("file:///etc/passwd", tmp_path)
    with pytest.raises(taste_capture.CaptureError):
        taste_capture._fetch("ftp://example.com/x")


def test_node_backend_arguments_and_missing_playwright(tmp_path, monkeypatch):
    monkeypatch.setattr(taste_capture.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(taste_capture.shutil, "which", lambda n: "/usr/bin/node")
    seen = {}

    def run(cmd, env):
        seen["cmd"], seen["env"] = cmd, env
        return 0, json.dumps({"files": ["evidence/page-390.jpg"], "page": {"copy": []}}) + "\n", ""

    monkeypatch.setattr(taste_capture, "_node_run", run)
    out = taste_capture._browser_capture("https://example.com/", tmp_path / "evidence")
    assert out["backend"] == "playwright-node" and seen["cmd"][3] == "https://example.com/"
    assert seen["cmd"][5] == "390,1440" and "TEYLA_PAGE_JS" in seen["env"]
    monkeypatch.setattr(taste_capture, "_node_run", lambda cmd, env: (3, "", "playwright-not-found"))
    with pytest.raises(taste_capture.CaptureUnavailable):
        taste_capture._browser_capture("https://example.com/", tmp_path / "evidence")


# --- interpret -----------------------------------------------------------------------------------------

def stream(obj, cost=0.03) -> str:
    return "\n".join([json.dumps({"type": "system"}), json.dumps({
        "type": "result", "is_error": False, "result": json.dumps(obj), "total_cost_usd": cost})]) + "\n"


PROPOSAL = {"claim": "Calm, neutral surfaces with one accent.", "kind": "screen",
            "axes": {"density": "low", "chrome": "flat, hairline borders", "color": "neutral plus one accent",
                     "type": "one sans, three sizes", "motion": None, "tone": "plain"},
            "do_not_copy": ["the logo", "the accent color"]}


def install_claude(monkeypatch, answers):
    calls = []

    def run(cmd, input_text):
        calls.append((cmd, json.loads(input_text)))
        a = answers[min(len(calls) - 1, len(answers) - 1)]
        return (a, "") if isinstance(a, int) else (0, a)

    monkeypatch.setattr(taste_capture, "_run", run)
    return calls


def seed(corpus, monkeypatch, comment="neutral"):
    fake_browser(monkeypatch)
    assert add(["https://example.com/", comment] if comment else ["https://example.com/"]) == 0
    return only_entry(corpus)


def test_interpret_dry_calls_nothing(corpus, monkeypatch, capsys):
    _, e = seed(corpus, monkeypatch)
    calls = install_claude(monkeypatch, [stream(PROPOSAL)])
    capsys.readouterr()
    assert cli.main(["taste", "interpret", e["id"], "--dry"]) == 0
    out = capsys.readouterr().out
    assert "--- system ---" in out and "page-390.jpg" in out and not calls


def test_interpret_stores_a_proposal_and_never_activates(corpus, monkeypatch, capsys):
    d, e = seed(corpus, monkeypatch, comment="")
    calls = install_claude(monkeypatch, [stream(PROPOSAL)])
    assert cli.main(["taste", "interpret", e["id"]]) == 0
    cmd, msg = calls[0]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    kinds = [b["type"] for b in msg["message"]["content"]]
    assert kinds.count("image") == 2
    e2 = json.loads((d / "entry.json").read_text())
    assert e2["status"] == "proposed" and e2["claim"] == ""
    assert e2["interpretation"]["claim"].startswith("Calm") and e2["interpretation"]["axes"]["density"] == "low"
    assert e2["axes"]["density"] is None and e2["do_not_copy"] == []
    assert taste_corpus.validate(e2) == []


def test_interpret_refusals(corpus, monkeypatch, capsys):
    d, e = seed(corpus, monkeypatch)
    monkeypatch.setenv("TEYLA_SAFE", "1")
    calls = install_claude(monkeypatch, [stream(PROPOSAL)])
    assert cli.main(["taste", "interpret", e["id"]]) == 1 and not calls
    monkeypatch.delenv("TEYLA_SAFE")
    install_claude(monkeypatch, [1])
    assert cli.main(["taste", "interpret", e["id"]]) == 1
    install_claude(monkeypatch, [stream({"claim": "x"})])
    assert cli.main(["taste", "interpret", e["id"]]) == 1
    assert json.loads((d / "entry.json").read_text())["interpretation"] is None


def test_interpret_needs_evidence(corpus, monkeypatch, capsys):
    assert add(["--no-capture", "https://example.com/", "nice"]) == 0
    _, e = only_entry(corpus)
    assert cli.main(["taste", "interpret", e["id"], "--dry"]) == 1
    assert "no evidence" in capsys.readouterr().err


# --- accept, reject, note ----------------------------------------------------------------------------------

def test_accept_adopts_the_proposal_only_where_the_owner_left_blanks(corpus, monkeypatch):
    d, e = seed(corpus, monkeypatch, comment="my own words")
    install_claude(monkeypatch, [stream(PROPOSAL)])
    assert cli.main(["taste", "interpret", e["id"]]) == 0
    p = d / "entry.json"
    mid = json.loads(p.read_text())
    mid["axes"]["density"] = "very low"
    p.write_text(json.dumps(mid))
    assert cli.main(["taste", "accept", e["id"]]) == 0
    e2 = json.loads(p.read_text())
    assert e2["status"] == "active" and e2["claim"] == "my own words" and e2["claim_source"] == "owner"
    assert e2["axes"]["density"] == "very low" and e2["axes"]["chrome"] == "flat, hairline borders"
    assert e2["do_not_copy"] == ["the logo", "the accent color"]


def test_accept_an_empty_claim_takes_the_proposal_and_says_so(corpus, monkeypatch):
    d, e = seed(corpus, monkeypatch, comment="")
    assert cli.main(["taste", "accept", e["id"]]) == 1            # raw, nothing proposed: refused
    install_claude(monkeypatch, [stream(PROPOSAL)])
    assert cli.main(["taste", "interpret", e["id"]]) == 0
    assert cli.main(["taste", "accept", e["id"]]) == 0
    e2 = json.loads((d / "entry.json").read_text())
    assert e2["claim"].startswith("Calm") and e2["claim_source"] == "accepted-proposal"


def test_note_turns_raw_into_proposed(corpus, monkeypatch):
    d, e = seed(corpus, monkeypatch, comment="")
    assert cli.main(["taste", "note", e["id"], "calm", "and", "plain"]) == 0
    e2 = json.loads((d / "entry.json").read_text())
    assert (e2["claim"], e2["status"]) == ("calm and plain", "proposed")
    assert cli.main(["taste", "note", e["id"]]) == 1


def test_supersedes_only_in_the_same_scope(corpus, monkeypatch):
    fake_browser(monkeypatch)
    for scope in ("product:atlas", "product:atlas", "voice"):
        assert add(["--scope", scope, "--no-capture", "https://example.com/", "x"]) == 0
    ents = sorted((json.loads((d / "entry.json").read_text()) for d in corpus.iterdir()), key=lambda e: e["created"] + e["id"])
    by_scope = {}
    for e in ents:
        by_scope.setdefault(e["scope"], []).append(e["id"])
    old, new = by_scope["product:atlas"]
    other = by_scope["voice"][0]
    assert cli.main(["taste", "accept", old]) == 0
    assert cli.main(["taste", "accept", other, "--supersedes", old]) == 1
    assert cli.main(["taste", "accept", new, "--supersedes", old]) == 0
    status = {e["id"]: e["status"] for _, e in taste_corpus.load_all()[0]}
    assert status[old] == "superseded" and status[new] == "active"
    assert cli.main(["taste", "note", old, "again"]) == 1


def test_reject_deletes_the_entry_and_its_evidence(corpus, monkeypatch):
    d, e = seed(corpus, monkeypatch)
    assert cli.main(["taste", "reject", e["id"]]) == 0
    assert not d.exists()
    assert cli.main(["taste", "reject", e["id"]]) == 1


def test_ids_need_a_unique_prefix(corpus, monkeypatch):
    fake_browser(monkeypatch)
    for _ in range(3):
        assert add(["--no-capture", "https://example.com/", "x"]) == 0
    assert cli.main(["taste", "accept", "zz"]) == 1
    with pytest.raises(taste_corpus.EntryError):
        taste_corpus.find("")


# --- schema, inbox, render ------------------------------------------------------------------------------------

def test_a_broken_entry_is_skipped_and_named(corpus, monkeypatch, capsys):
    d, e = seed(corpus, monkeypatch)
    bad = corpus / "20261101-aaaaaa"
    bad.mkdir()
    (bad / "entry.json").write_text(json.dumps({**e, "id": "aaaaaa", "verdict": "love"}))
    capsys.readouterr()
    assert cli.main(["taste", "inbox"]) == 0
    cap = capsys.readouterr()
    assert e["id"] in cap.out and "aaaaaa" not in cap.out
    assert "20261101-aaaaaa" in cap.err and "verdict" in cap.err
    with pytest.raises(taste_corpus.EntryError):
        taste_corpus.read_entry(bad)


def test_schema_rejects_unknown_fields_and_bad_types():
    assert taste_corpus.validate({"id": "xyz"})
    good = {"id": "abc123", "created": "2026-11-08T10:00:00", "source": "https://example.com/", "kind": "screen",
            "verdict": "like", "claim": "", "scope": "portfolio", "axes": {a: None for a in taste_corpus.AXES},
            "evidence": {"files": [], "measured": {}, "captured": None}, "do_not_copy": [], "status": "raw",
            "supersedes": None, "interpretation": None}
    assert taste_corpus.validate(good) == []
    assert taste_corpus.validate({**good, "extra": 1})
    assert taste_corpus.validate({**good, "axes": {**good["axes"], "mood": "x"}})
    assert taste_corpus.validate({**good, "do_not_copy": "no"})


def test_inbox_lists_raw_and_proposed_first(corpus, monkeypatch, capsys):
    fake_browser(monkeypatch)
    assert add(["--no-capture", "https://example.com/a", "one"]) == 0
    assert add(["--no-capture", "https://example.com/b"]) == 0
    assert add(["--no-capture", "https://example.com/c", "three"]) == 0
    ids = {e["source"][-1]: e["id"] for _, e in taste_corpus.load_all()[0]}
    assert cli.main(["taste", "accept", ids["a"]]) == 0
    capsys.readouterr()
    assert cli.main(["taste", "inbox"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [ln.split()[1] for ln in lines] == ["raw", "proposed", "active"]
    assert lines[0].startswith(ids["b"])
    assert cli.main(["taste", "inbox", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["entries"]) == 3


def make_active(corpus, source, claim, verdict="like", scope="portfolio", axes=None, dnc=None):
    argv = ["--no-capture", f"--scope={scope}", "https://example.com/" + source, claim]
    if verdict != "like":
        argv.insert(0, f"--{verdict}")
    assert add(argv) == 0
    e = next(e for _, e in taste_corpus.load_all()[0] if e["source"].endswith(source))
    d = next(d for d, e2 in taste_corpus.load_all()[0] if e2["id"] == e["id"])
    e["axes"].update(axes or {})
    e["do_not_copy"] = dnc or []
    taste_corpus.write_entry(d, e)
    assert cli.main(["taste", "accept", e["id"]]) == 0
    return e["id"]


def test_render_groups_dislikes_as_constraints_and_filters_scope(corpus, monkeypatch, capsys, tmp_path):
    a = make_active(corpus, "like-a", "calm neutral", axes={"color": "neutral"}, dnc=["the logo"])
    b = make_active(corpus, "dis-b", "too many boxes", verdict="dislike", scope="product:atlas", axes={"density": "boxed"})
    c = make_active(corpus, "like-c", "warm voice", scope="voice")
    other = make_active(corpus, "other", "other product", scope="product:recipes")
    raw = "https://example.com/pending"
    assert add(["--no-capture", raw]) == 0
    capsys.readouterr()
    out_file = tmp_path / "TASTE.md"
    assert cli.main(["taste", "corpus", "render", "--product", "atlas", "--out", str(out_file)]) == 0
    text = out_file.read_text()
    assert "## Likes" in text and "## Dislikes (constraints)" in text
    assert f"**{a}**" in text and f"**{b}**" in text and f"**{c}**" in text
    assert other not in text and "pending" not in text
    assert "constrains: density (density: boxed)" in text and "do not copy: the logo" in text
    assert text.index("## Likes") < text.index("## Dislikes")
    assert taste_corpus.select(taste_corpus.load_all()[0], "atlas")[0]["id"] == b   # the product's own entry comes first
    assert cli.main(["taste", "corpus", "render"]) == 0
    assert b not in capsys.readouterr().out
    assert cli.main(["taste", "corpus", "bogus"]) == 1


def test_render_is_capped_at_fifteen_active_entries(corpus):
    rows = []
    for i in range(20):
        make_active(corpus, f"n{i}", f"claim {i}")
    rows, _ = taste_corpus.load_all()
    text = taste_corpus.render_corpus(rows, None)
    assert text.count("- **") == taste_corpus.MAX_RENDER
    assert "5 older active entries" in text


def test_the_existing_ledger_still_lists(tmp_path, capsys):
    (tmp_path / "design" / "decisions").mkdir(parents=True)
    assert cli.main(["taste", "list", str(tmp_path)]) == 0


def test_python_playwright_navigation_errors_are_recorded_not_raised(corpus, monkeypatch, tmp_path, capsys):
    import sys
    import types

    class Boom(Exception):
        pass

    class Page:
        def goto(self, *a, **k):
            raise Boom("net::ERR_NAME_NOT_RESOLVED at https://nope.invalid/\nCall log: ...")

    class Ctx:
        def new_page(self):
            return Page()

    class Browser:
        def new_context(self, **k):
            return Ctx()

        def close(self):
            pass

    class PW:
        chromium = types.SimpleNamespace(launch=lambda **k: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    mod = types.ModuleType("playwright")
    sync = types.ModuleType("playwright.sync_api")
    sync.sync_playwright = lambda: PW()
    monkeypatch.setitem(sys.modules, "playwright", mod)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync)
    monkeypatch.setattr(taste_capture.importlib.util, "find_spec", lambda name: object())
    assert add(["https://nope.invalid/", "nice"]) == 0
    d, e = only_entry(corpus)
    assert "ERR_NAME_NOT_RESOLVED" in e["evidence"]["error"] and e["evidence"]["files"] == []
    cap = capsys.readouterr()
    assert "capture failed" in cap.err and e["id"] in cap.out
