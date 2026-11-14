"""`teyla intent audit|mark|load`: which of the owner's requests were delivered.

Synthetic entries only; conftest points TEYLA_HOME at a tmp dir."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess

import pytest

from teyla import cli, intent, intent_status as st, you

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = ROOT / "plugin" / "hooks" / "session-start.sh"
TODAY = dt.date(2026, 11, 14)
ONE = "Build a weekly plan screen. It should show the goals for the week and nothing else.\nAlso add a dark theme to the settings."
TWO = "ok thanks, that looks right"


def seed(product="demo", bodies=((("2026-10-01 10:00"), ONE), ("2026-11-10 09:00", TWO))) -> list[str]:
    d = intent.intent_dir()
    d.mkdir(parents=True, exist_ok=True)
    text = "".join(f"## {when} · claude · session abcd1234\n{body}\n\n" for when, body in bodies)
    (d / f"{product}.md").write_text(text)
    return [st.entry_id(e) for e in intent.entries(product)]


def run(*argv) -> int:
    return cli.main(list(argv))


def test_entry_id_is_the_dedupe_hash_prefix_and_survives_an_index_rebuild():
    a, b = seed()
    assert a == intent.digest(ONE)[:8] and len(b) == 8
    (intent.intent_dir() / ".index.json").unlink(missing_ok=True)
    assert [st.entry_id(e) for e in intent.entries("demo")] == [a, b]


def test_everything_starts_not_audited():
    seed()
    a = st.audit("demo", TODAY)
    assert not a["audited"] and len(a["unaudited"]) == 2 and a["requests"] == []
    assert st.summary_line(a) == "demo: not audited (2 entries)"


def test_mark_adds_requests_numbered_by_the_cli_and_never_renumbers():
    a, _ = seed()
    assert st.mark("demo", {"ref": a, "status": "open", "quote": "add a dark theme to the settings"}) == (f"{a}.1", "new -> open")
    assert st.mark("demo", {"ref": a, "status": "open", "quote": "Build a weekly plan screen."})[0] == f"{a}.2"
    # the same quote again updates the same request: a replayed audit does not duplicate
    assert st.mark("demo", {"ref": a, "status": "done", "quote": "Build  a weekly\nplan screen.", "evidence": "https://x/pull/1"})[0] == f"{a}.2"
    recs = st.load_records("demo")
    assert sorted(recs) == [f"{a}.1", f"{a}.2"]
    assert recs[f"{a}.2"]["history"][0]["status"] == "open"


@pytest.mark.parametrize("rec,why", [
    ({"status": "done"}, "done needs --evidence"),
    ({"status": "partial", "evidence": "src/x.py"}, "partial needs --note"),
    ({"status": "superseded"}, "superseded needs --evidence or --note"),
    ({"status": "shipped"}, "unknown status"),
])
def test_statuses_that_claim_delivery_need_evidence(rec, why):
    a, _ = seed()
    with pytest.raises(st.StatusError, match=why):
        st.mark("demo", dict(rec, ref=a, quote="Build a weekly plan screen."))
    assert not st.status_path("demo").exists()


def test_a_quote_must_be_the_owners_own_text():
    a, _ = seed()
    with pytest.raises(st.StatusError, match="not in the entry"):
        st.mark("demo", {"ref": a, "status": "open", "quote": "add a light theme"})
    with pytest.raises(st.StatusError, match="not in the entry"):   # case counts
        st.mark("demo", {"ref": a, "status": "open", "quote": "build a weekly plan screen"})
    with pytest.raises(st.StatusError, match="at most"):
        st.mark("demo", {"ref": a, "status": "open", "quote": "x " * 400})


def test_one_quoted_request_leaves_the_entry_partly_audited_until_it_is_split():
    a, b = seed()
    st.mark("demo", {"ref": a, "status": "open", "quote": "add a dark theme to the settings"})
    au = st.audit("demo", TODAY)
    assert [u["entry"] for u in au["partly_audited"]] == [a] and [u["entry"] for u in au["unaudited"]] == [b]
    st.mark("demo", {"ref": a, "status": "split"})
    st.mark("demo", {"ref": b, "status": "not-a-request"})
    au = st.audit("demo", TODAY)
    assert au["partly_audited"] == [] and au["unaudited"] == []
    assert st.summary_line(au) == "demo: 1 request open, oldest 44 days"
    assert [r["id"] for r in au["requests"]] == [f"{a}.1", b]      # split itself is not a request row


def test_whole_entry_statuses_cannot_contradict_its_requests():
    a, _ = seed()
    st.mark("demo", {"ref": a, "status": "open", "quote": "add a dark theme to the settings"})
    with pytest.raises(st.StatusError, match="request"):
        st.mark("demo", {"ref": a, "status": "not-a-request"})
    with pytest.raises(st.StatusError, match="whole entry"):
        st.mark("demo", {"ref": f"{a}.1", "status": "split"})
    with pytest.raises(st.StatusError, match="no such request"):
        st.mark("demo", {"ref": f"{a}.9", "status": "open"})
    with pytest.raises(st.StatusError, match="no such entry"):
        st.mark("demo", {"ref": "00000000", "status": "open"})


def test_load_is_all_or_nothing_and_idempotent(tmp_path):
    a, b = seed()
    good = [{"entry": a, "quote": "add a dark theme to the settings", "status": "partial",
             "evidence": "https://x/pull/2", "note": "light mode only"},
            {"entry": a, "status": "split"}, {"entry": b, "status": "not-a-request"}]
    bad = good + [{"entry": a, "quote": "a request nobody typed", "status": "open"}]
    with pytest.raises(st.StatusError, match="record 4"):
        st.load("demo", bad)
    assert not st.status_path("demo").exists()
    assert [w for _, w in st.load("demo", good)] == ["new -> partial", "new -> split", "new -> not-a-request"]
    assert all("unchanged" in w for _, w in st.load("demo", good))
    f = tmp_path / "audit.json"
    f.write_text(json.dumps({"product": "demo", "records": good}))
    assert run("intent", "load", "demo", str(f), "--dry") == 0
    f.write_text(json.dumps({"product": "other", "records": good}))
    assert run("intent", "load", "demo", str(f)) == 64


def test_the_store_is_private_and_outside_the_entry_file():
    a, _ = seed()
    before = (intent.intent_dir() / "demo.md").read_bytes()
    st.mark("demo", {"ref": a, "status": "not-a-request"})
    assert (intent.intent_dir() / "demo.md").read_bytes() == before
    assert oct(st.status_path("demo").stat().st_mode & 0o777) == "0o600"
    assert oct(st.coverage_path().stat().st_mode & 0o777) == "0o600"


def test_mark_finds_the_product_from_the_entry_id(capsys):
    a, _ = seed()
    seed("other", (("2026-10-02 10:00", "A different prompt about another product entirely."),))
    assert run("intent", "mark", a, "open", "--quote", "add a dark theme to the settings") == 0
    assert capsys.readouterr().out.strip() == f"demo {a}.1: new -> open"
    assert run("intent", "mark", "deadbeef", "open") == 2


def test_audit_command_prints_owed_first_and_json_carries_everything(capsys):
    a, b = seed()
    st.load("demo", [{"entry": a, "quote": "Build a weekly plan screen.", "status": "done", "evidence": "https://x/pull/1"},
                     {"entry": a, "quote": "add a dark theme to the settings", "status": "open"}])
    assert run("intent", "audit", "demo") == 0
    out = capsys.readouterr().out
    assert out.index(f"{a}.2") < out.index(f"{a}.1") and "partly audited" in out and "not audited" in out
    assert run("intent", "audit", "demo", "--open") == 0
    assert f"{a}.1" not in capsys.readouterr().out
    assert run("intent", "audit", "demo", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["open"] == 1 and data["counts"]["done"] == 1
    assert run("intent", "audit", "nosuch") == 2


def test_entries_json_carries_the_id(capsys):
    a, b = seed()
    assert run("intent", "demo", "--json") == 0
    assert [e["id"] for e in json.loads(capsys.readouterr().out)] == [a, b]


def test_coverage_table_feeds_the_shell_hook():
    a, b = seed()
    st.load("demo", [{"entry": a, "quote": "add a dark theme to the settings", "status": "open"}, {"entry": a, "status": "split"}])
    row = st.coverage_path().read_text().split("\t")
    assert row[:4] == ["demo", "1", "1", "0"]
    assert int(row[4]) == int(dt.datetime(2026, 10, 1).timestamp())


def _start(cwd):
    home = cwd.parent.parent / "home"          # an empty HOME: only the intent line can print
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TEYLA_HOME": os.environ["TEYLA_HOME"]}
    return subprocess.run(["sh", str(START), "--codex"], input=json.dumps({"cwd": str(cwd)}), capture_output=True,
                          text=True, timeout=10, env=env).stdout


def test_session_start_appends_what_is_owed_to_the_intent_line(tmp_path):
    r = tmp_path / "repos" / "demo"
    (r / ".git").mkdir(parents=True)
    a, b = seed()
    out = _start(r)
    assert out.count("\n") == 1 and out.rstrip().endswith("None audited for delivery yet: `teyla intent audit demo`.")
    st.load("demo", [{"entry": a, "quote": "add a dark theme to the settings", "status": "open"}, {"entry": a, "status": "split"}])
    out = _start(r)
    assert "Owed requests: 1 open, oldest " in out and "entries not audited: 1 (`teyla intent audit demo --open`)." in out
    st.mark("demo", {"ref": b, "status": "not-a-request"})
    st.mark("demo", {"ref": f"{a}.1", "status": "done", "evidence": "https://x/pull/3"})
    out = _start(r)
    assert out.rstrip().endswith("quote the sentences a plan serves.")    # nothing owed: nothing said


def test_teyla_you_lists_owed_products_and_the_never_audited():
    a, b = seed()
    seed("quiet", (("2026-10-02 10:00", "A different prompt about another product entirely."),))
    st.load("demo", [{"entry": a, "quote": "add a dark theme to the settings", "status": "open"}, {"entry": a, "status": "split"}])
    o = you.owed(TODAY)
    assert [r["product"] for r in o["requests"]] == ["demo"] and o["never_audited"] == ["quiet"]
    text = "\n".join(you.render_owed(o))
    assert "demo: 1 request open, oldest 44 days; 1 entry not audited  (teyla intent audit demo)" in text
    assert "1 product with your words never audited: quiet" in text


def test_a_broken_status_file_is_reported_not_overwritten():
    a, _ = seed()
    st.status_path("demo").write_text("{not json")
    with pytest.raises(st.StatusError, match="unreadable"):
        st.mark("demo", {"ref": a, "status": "not-a-request"})
    assert st.status_path("demo").read_text() == "{not json"
    assert "unreadable" in you.owed(TODAY)["requests"][0]["line"]


def test_owed_rows_are_oldest_first_whatever_their_status():
    a, b = seed(bodies=(("2026-08-01 10:00", ONE), ("2026-11-13 09:00", "Ship the export button today, please, it is overdue.")))
    st.load("demo", [{"entry": a, "quote": "add a dark theme to the settings", "status": "partial",
                      "evidence": "https://x/pull/4", "note": "light mode only"},
                     {"entry": b, "status": "open"}])
    assert [r["id"] for r in st.audit("demo", TODAY)["requests"]] == [f"{a}.1", b]
