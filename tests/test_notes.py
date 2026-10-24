"""`teyla note` / `teyla notes`: the store, the product suggestion, the intent hand-off and the state counts.
TEYLA_HOME is a tmp dir for every test (conftest), so the real notes, registry and intent files are never touched."""
from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from teyla import cli, intent, notes, registry, state

pytestmark = pytest.mark.usefixtures("fake_code_root")


def register(**products) -> dict:
    reg = {"product": {pid: {**registry.new_product(pid), **p} for pid, p in products.items()}, "assign": {}}
    registry.save(reg)
    return reg


@pytest.fixture
def two_products(tmp_path, monkeypatch):
    """app-a (alias "alpha") owns tmp/a; tool-b owns tmp/b. The cwd is neither."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    return register(**{"app-a": {"aliases": ["alpha"], "paths": [str(tmp_path / "a")]},
                       "tool-b": {"paths": [str(tmp_path / "b")]}})


def run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- the round trip ---------------------------------------------------------------------------

def test_a_note_round_trips_through_the_cli(two_products, capsys):
    rc, out, _ = run(capsys, "note", "Try a dark icon", "--product", "app-a")
    assert rc == 0
    nid, product, how, text = [p.strip() for p in out.strip().split("  ", 3)]
    assert nid.startswith("n") and len(nid) == 7 and product == "app-a" and how == "(you chose it)"
    assert text == "Try a dark icon"
    rc, out, _ = run(capsys, "notes", "--json")
    (n,) = json.loads(out)
    assert rc == 0
    assert n["id"] == nid and n["text"] == "Try a dark icon" and n["product"] == "app-a"
    assert n["source"] == "owner" and n["linked_by"] == "owner" and n["dropped"] is False
    assert n["created"] == n["updated"] and n["created"].endswith("Z")
    assert set(n) == {"id", "text", "product", "source", "created", "updated", "linked_by", "dropped"}


def test_the_line_clips_a_long_text_to_60_characters(two_products, capsys):
    rc, out, _ = run(capsys, "note", "word " * 40, "--product", "alpha")
    assert rc == 0
    shown = out.strip().split("  ", 3)[3]
    assert len(shown) == 60 and shown.endswith("…")
    assert notes.listing()[0]["text"] == ("word " * 40).strip()


def test_the_list_is_newest_first_and_filters_by_product(two_products, capsys):
    a = notes.add("first", "app-a")
    b = notes.add("second", "tool-b")
    c = notes.add("third")
    assert [n["id"] for n in notes.listing()] == [c["id"], b["id"], a["id"]]
    rc, out, _ = run(capsys, "notes", "--product", "alpha")           # an alias works for filtering too
    assert rc == 0 and a["id"] in out and b["id"] not in out and c["id"] not in out
    rc, out, _ = run(capsys, "notes", "--inbox")
    assert c["id"] in out and a["id"] not in out
    assert run(capsys, "notes", "--inbox", "--product", "app-a")[0] == 2


def test_note_dash_reads_stdin(two_products, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("  from stdin\nsecond line  \n"))
    rc, out, _ = run(capsys, "note", "-", "--product", "tool-b")
    assert rc == 0
    assert notes.listing()[0]["text"] == "from stdin\nsecond line"


def test_an_empty_note_is_refused_and_nothing_is_written(two_products, capsys):
    rc, _, err = run(capsys, "note", "   ")
    assert rc == 1 and "empty" in err
    assert not notes.store_path().exists()
    assert run(capsys, "note")[0] == 2


# --- verbatim ---------------------------------------------------------------------------------

def test_text_is_kept_verbatim_with_newlines_and_accents(two_products):
    text = "Idée: café à la crème,\n  indented line\n\nœuvre — naïve façade ñ ü"
    n = notes.add("\n" + text + "  \n", "app-a")
    assert n["text"] == text
    assert notes.load()[n["id"]]["text"] == text
    line = notes.store_path().read_text(encoding="utf-8").splitlines()[0]
    assert "café" in line and "\\n" in line          # one JSON line, accents not escaped


def test_an_unquoted_note_joins_its_words(two_products, capsys):
    assert run(capsys, "note", "call", "the", "plumber")[0] == 0
    assert notes.listing()[0]["text"] == "call the plumber"


# --- which product ----------------------------------------------------------------------------

def test_the_text_names_the_product_first(two_products, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "b")                              # the cwd says tool-b; the text says app-a
    n = notes.add("Alpha needs a settings page")
    assert (n["product"], n["linked_by"]) == ("app-a", "text")


def test_the_directory_is_the_second_guess(two_products, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "b")
    n = notes.add("something with no product word in it")
    assert (n["product"], n["linked_by"]) == ("tool-b", "cwd")


def test_no_match_and_an_unregistered_directory_go_to_the_inbox(two_products, capsys):
    n = notes.add("an idea for nobody in particular")
    assert (n["product"], n["linked_by"]) == ("inbox", "")
    rc, out, _ = run(capsys, "note", "another one")
    assert rc == 0 and "inbox" in out and "no product matched" in out


def test_an_unregistered_checkout_under_code_root_is_not_a_product(two_products, monkeypatch, fake_code_root):
    # registry.resolve names an unregistered checkout by its directory; a note must not adopt that name
    here = fake_code_root / "some-repo" / "src"
    assert registry.resolve(here) == "some-repo"
    n = notes.add("nothing registered here", cwd=here)
    assert (n["product"], n["linked_by"]) == ("inbox", "")


def test_a_text_naming_two_products_falls_through_to_the_directory(two_products, tmp_path, monkeypatch):
    text = "share the icon between app-a and tool-b"
    assert notes.add(text)["product"] == "inbox"                    # cwd is registered to nobody
    monkeypatch.chdir(tmp_path / "b")
    n = notes.add(text)
    assert (n["product"], n["linked_by"]) == ("tool-b", "cwd")


def test_an_explicit_product_must_be_registered(two_products, capsys):
    rc, _, err = run(capsys, "note", "x", "--product", "app-aa")
    assert rc == 1 and "no product 'app-aa'" in err and "Close: app-a" in err
    rc, _, err = run(capsys, "note", "x", "--product", "zzz-nothing")
    assert rc == 1 and "Registered: app-a, tool-b" in err
    assert not notes.store_path().exists()
    assert notes.add("x", "ALPHA")["product"] == "app-a"           # alias, any case
    assert notes.add("y", "inbox")["product"] == "inbox"


def test_without_a_registry_only_the_inbox_exists(capsys):
    assert run(capsys, "note", "idea", "--product", "anything")[0] == 1
    assert run(capsys, "note", "idea")[0] == 0
    assert notes.listing()[0]["product"] == "inbox"


# --- link and drop ----------------------------------------------------------------------------

def test_link_and_drop_fold_into_the_note(two_products, capsys):
    n = notes.add("an idea")
    assert n["product"] == "inbox"
    rc, out, _ = run(capsys, "note", "link", n["id"], "alpha")
    assert rc == 0 and out.startswith("moved ") and "app-a" in out
    (cur,) = notes.listing()
    assert cur["product"] == "app-a" and cur["linked_by"] == "owner" and cur["updated"] >= cur["created"]
    assert run(capsys, "note", "drop", n["id"])[0] == 0
    assert notes.listing() == [] and notes.listing(include_dropped=True)[0]["dropped"] is True
    rc, out, _ = run(capsys, "notes")
    assert "no notes" in out
    rc, out, _ = run(capsys, "notes", "--all")
    assert "[dropped]" in out and n["id"] in out
    assert run(capsys, "note", "link", n["id"], "tool-b")[0] == 1       # a dropped note is not moved
    assert run(capsys, "note", "undrop", n["id"])[0] == 0
    assert notes.listing()[0]["dropped"] is False
    events = [json.loads(l) for l in notes.store_path().read_text().splitlines()]
    assert [e["ev"] for e in events] == ["add", "link", "drop", "undrop"]


def test_an_id_prefix_works_and_a_wrong_id_is_refused(two_products, capsys):
    n = notes.add("keep me")
    assert run(capsys, "note", "drop", n["id"][:4])[0] == 0
    rc, _, err = run(capsys, "note", "drop", "nzzzzzz")
    assert rc == 1 and "no note" in err
    assert run(capsys, "note", "link", n["id"], "no-such-product")[0] == 1


def test_link_to_inbox_and_repeat_link(two_products, capsys):
    n = notes.add("x", "app-a")
    assert notes.link(n["id"], "app-a")[1] is False                 # already there, chosen by the owner
    note, changed = notes.link(n["id"], "inbox")
    assert changed and note["product"] == "inbox"


def test_events_for_an_unknown_id_and_torn_lines_are_ignored(two_products):
    n = notes.add("real")
    with open(notes.store_path(), "a", encoding="utf-8") as f:
        f.write('{"ev": "drop", "id": "nghost00"}\nnot json at all\n{"ev": "add", "id": "n12345')   # a torn last line
    assert [x["id"] for x in notes.listing(include_dropped=True)] == [n["id"]]
    again = notes.add("after the torn line", "tool-b")                  # the writer starts a fresh line
    assert {x["id"] for x in notes.listing()} == {n["id"], again["id"]}


# --- the owner's words ------------------------------------------------------------------------

def texts(product):
    return [e["text"] for e in intent.entries(product)]


def test_a_linked_note_is_added_to_intent_even_when_short(two_products):
    n = notes.add("Dark icon", "app-a")
    assert n["intent"] is True
    (e,) = intent.entries("app-a")
    assert e["text"] == "Dark icon" and e["harness"] == "note" and e["session"] == n["id"]


def test_an_inbox_note_stays_out_of_intent_until_it_is_linked(two_products):
    n = notes.add("floating idea")
    assert intent.products() == []
    notes.link(n["id"], "tool-b")
    assert texts("tool-b") == ["floating idea"]


def test_each_link_adds_exactly_one_intent_entry_and_the_old_one_stays(two_products):
    n = notes.add("floating idea")
    notes.link(n["id"], "app-a")
    assert texts("app-a") == ["floating idea"] and texts("tool-b") == []
    notes.link(n["id"], "tool-b")
    assert texts("app-a") == ["floating idea"] and texts("tool-b") == ["floating idea"]
    notes.link(n["id"], "tool-b")                                      # no change, no new entry
    assert len(texts("tool-b")) == 1
    notes.set_dropped(n["id"], True)
    assert texts("app-a") == ["floating idea"]                          # a drop never rewrites the intent store


def test_the_intent_store_being_busy_does_not_lose_the_note(two_products, monkeypatch):
    def busy(*a, **k):
        raise TimeoutError("intent store is locked")
    monkeypatch.setattr(intent.Store, "__enter__", busy)
    n = notes.add("still saved", "app-a")
    assert n["intent"] is False and notes.listing()[0]["id"] == n["id"]


# --- files ------------------------------------------------------------------------------------

def test_the_store_is_private(two_products):
    notes.add("secret-ish idea", "app-a")
    assert stat.S_IMODE(notes.store_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(notes.notes_dir().stat().st_mode) == 0o700
    os.chmod(notes.store_path(), 0o644)                                # an older or hand-made file is tightened on write
    notes.add("again", "app-a")
    assert stat.S_IMODE(notes.store_path().stat().st_mode) == 0o600


def test_concurrent_appends_stay_valid_jsonl(two_products):
    def work(i):
        n = notes.add(f"idea {i} " + "x" * 3000, ("app-a", "tool-b", "inbox")[i % 3])
        if i % 4 == 0:
            notes.set_dropped(n["id"], True)
        return n["id"]
    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(work, range(48)))
    assert len(set(ids)) == 48
    lines = notes.store_path().read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(l) for l in lines]                            # every line is whole
    assert len(parsed) == 48 + 12 and sum(e["ev"] == "add" for e in parsed) == 48
    assert len(notes.load()) == 48 and len(notes.listing()) == 36


# --- the snapshot -----------------------------------------------------------------------------

def test_state_counts_open_notes_by_product(two_products, tmp_path):
    assert state.notes_view() == {"inbox": 0, "by_product": {}}
    notes.add("one", "app-a")
    notes.add("two", "app-a")
    notes.add("three", "tool-b")
    notes.add("four")
    gone = notes.add("five", "tool-b")
    notes.set_dropped(gone["id"], True)
    expect = {"inbox": 1, "by_product": {"app-a": 2, "tool-b": 1}}
    assert notes.counts() == expect
    st = state.build(1_790_000_000.0, items=[], repos={}, spent=None, desktop=str(tmp_path / "sessions"),
                     codex_root=str(tmp_path / "nocodex"))
    assert st["notes"] == expect
    fixture = json.loads((state.pathlib.Path(__file__).parent / "fixtures" / "state.v2.json").read_text())
    assert set(st["notes"]) == set(fixture["notes"])
