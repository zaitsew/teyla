"""`teyla asks` resolves an ask whose PR is merged or closed, and collapses an ask asked twice. GitHub is
never reached: every test hands `gh` to the code as a fake runner (or, through the CLI, patches
`backlog.default_runner`); the asks are built by hand. Texts are generic."""
from __future__ import annotations

import datetime as dt
import json
import re

import pytest

from teyla import asks, backlog, cli, state

pytestmark = pytest.mark.usefixtures("fake_code_root")

NOW = dt.datetime(2026, 10, 20, 12, 0, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400
PR1 = "https://github.com/example/lens/pull/14"
PR2 = "https://github.com/example/lens/pull/15"
PR3 = "https://github.com/example/atlas/pull/3"

BASE = "which database migration should run first before the nightly backup job starts tonight"
NEAR = "which database migration should run first before the nightly backup job starts today"
FAR = "which database migration should run first before the nightly restore job starts today"


def iso(days_ago: float) -> str:
    return dt.datetime.fromtimestamp(NOW - days_ago * DAY, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ask(id_, product="lens", *, days_ago=3.0, question="Which font?", pr="", session="", kind="question"):
    return asks.Ask(id=id_, kind=kind, product=product, title="A session", question=question, context="",
                    options=[], when=NOW - days_ago * DAY, archived=False, link=f"claude://x/{id_}", pr=pr,
                    harness="claude-code", session=session)


class FakeGh:
    """`gh api graphql` over a table {pr url: (state, days ago it was merged or closed)}."""

    def __init__(self, table, rc=0):
        self.table, self.rc, self.calls = table, rc, []

    def __call__(self, argv):
        self.calls.append(argv)
        query = next(a for a in argv if a.startswith("query="))
        data = {}
        for m in re.finditer(r'(p\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ pullRequest\(number: (\d+)\)', query):
            alias, o, n, num = m.groups()
            hit = self.table.get(f"https://github.com/{o}/{n}/pull/{num}")
            if hit is None:
                data[alias] = None
                continue
            st, ago = hit
            data[alias] = {"pullRequest": {"state": st, "mergedAt": iso(ago) if st == "MERGED" else None,
                                           "closedAt": iso(ago) if st != "OPEN" else None}}
        return self.rc, json.dumps({"data": data}), ""


def fresh_store():
    return {"done": {}, "snoozed": {}, "undone": {}}


def settle(items, gh, *, st=None, now=NOW, fetch=True):
    st = fresh_store() if st is None else st
    asks.settle(items, now, st=st, fetch=fetch, runner=gh)
    return st


# --- resolve by PR state -------------------------------------------------------------------------

def test_a_merged_pr_and_a_closed_pr_resolve_their_asks_and_an_open_one_does_not():
    gh = FakeGh({PR1: ("MERGED", 1), PR2: ("CLOSED", 1), PR3: ("OPEN", 0)})
    items = [ask("aaa00001", pr=PR1), ask("aaa00002", pr=PR2), ask("aaa00003", "atlas", pr=PR3), ask("aaa00004")]
    st = settle(items, gh)
    assert [a.status for a in items] == ["done", "done", "open", "open"]
    assert items[0].note == f"auto: PR merged {PR1}" and items[1].note == f"auto: PR closed {PR2}"
    assert st["done"]["aaa00001"]["note"] == f"auto: PR merged {PR1}" and set(st["done"]) == {"aaa00001", "aaa00002"}
    assert len(gh.calls) == 1                                  # one batched query for all three PRs
    assert asks.filtered_counts(items) == (2, 0)


def test_a_pr_merged_before_the_ask_was_written_does_not_resolve_it():
    items = [ask("aaa00001", pr=PR1, days_ago=1)]                # the ask is 1 day old, the merge 5 days old
    st = settle(items, FakeGh({PR1: ("MERGED", 5)}))
    assert items[0].status == "open" and st["done"] == {}


def test_a_snoozed_ask_is_resolved_too():
    a = ask("aaa00001", pr=PR1)
    a.status = "snoozed"
    st = settle([a], FakeGh({PR1: ("MERGED", 1)}))
    assert a.status == "done" and "aaa00001" in st["done"]


def test_no_gh_a_failing_gh_and_a_bad_answer_resolve_nothing_and_fail_nothing(monkeypatch):
    monkeypatch.setattr(backlog.shutil, "which", lambda name: None)
    items = [ask("aaa00001", pr=PR1)]
    assert settle(items, None)["done"] == {} and items[0].status == "open"        # no gh, no injected runner

    def raises(argv):
        raise OSError("no network")
    for runner in (raises, lambda argv: (1, "", "boom"), lambda argv: (0, "not json", ""),
                   lambda argv: (0, json.dumps({"data": []}), ""), lambda argv: (0, json.dumps({"errors": []}), "")):
        backlog.pr_state_path().unlink(missing_ok=True)
        items = [ask("aaa00001", pr=PR1)]
        assert settle(items, runner)["done"] == {} and items[0].status == "open"


def test_a_failed_query_backs_off_for_five_minutes():
    calls = []

    def gh(argv):
        calls.append(argv)
        return 1, "oops", ""
    settle([ask("aaa00001", pr=PR1)], gh)
    settle([ask("aaa00001", pr=PR1)], gh, now=NOW + 60)
    assert len(calls) == 1
    settle([ask("aaa00001", pr=PR1)], gh, now=NOW + 400)
    assert len(calls) == 2


def test_pr_state_is_cached_for_thirty_minutes():
    gh = FakeGh({PR1: ("OPEN", 0)})
    assert backlog.pr_states([PR1], NOW, runner=gh)[PR1.lower()]["state"] == "OPEN"
    assert backlog.pr_state_path().exists() and len(gh.calls) == 1
    backlog.pr_states([PR1], NOW + 29 * 60, runner=gh)
    assert len(gh.calls) == 1                                  # still fresh
    backlog.pr_states([PR1], NOW + 31 * 60, runner=gh)
    assert len(gh.calls) == 2                                  # stale: asked again
    backlog.pr_states([PR1], NOW + 31 * 60, runner=gh, fetch=False)
    assert len(gh.calls) == 2                                  # `teyla state` never asks


def test_a_pr_open_in_the_backlog_cache_is_not_asked_about():
    backlog.cache_path().write_text(json.dumps({"version": 1, "at": NOW - 60, "issues": [], "counts": {},
                                                "canonical": {}, "prs": [{"url": PR1, "repo": "example/lens"}]}))
    gh = FakeGh({PR1: ("MERGED", 1), PR2: ("MERGED", 1)})
    got = backlog.pr_states([PR1, PR2], NOW, runner=gh)
    assert got[PR1.lower()]["state"] == "OPEN" and got[PR2.lower()]["state"] == "MERGED"
    assert len(gh.calls) == 1 and "number: 14" not in gh.calls[0][-1] and "number: 15" in gh.calls[0][-1]
    # an old backlog cache is not trusted: the PR is asked about
    backlog.cache_path().write_text(json.dumps({"version": 1, "at": NOW - 5000, "issues": [], "counts": {},
                                                "canonical": {}, "prs": [{"url": PR1}]}))
    backlog.pr_state_path().unlink()
    assert backlog.pr_states([PR1], NOW, runner=gh)[PR1.lower()]["state"] == "MERGED"


def test_safe_mode_closes_the_network_for_the_pr_check(monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    gh = FakeGh({PR1: ("MERGED", 1)})
    assert backlog.pr_states([PR1], NOW, runner=gh) == {} and gh.calls == []


def test_a_link_that_is_not_a_github_pr_is_ignored():
    gh = FakeGh({})
    assert backlog.pr_states(["", "https://example.com/pull/1", "https://github.com/a/b/issues/2"], NOW, runner=gh) == {}
    assert gh.calls == []
    assert backlog.canonical_pr_url("https://github.com/Example/Lens/pull/14/files") == PR1.lower()


def test_undo_reopens_an_auto_resolved_ask_and_it_is_not_resolved_again(monkeypatch, capsys):
    gh = FakeGh({PR1: ("MERGED", 1)})
    first = ask("aaa00001", pr=PR1)
    st = settle([first], gh)
    asks.save_state(st, now=NOW)
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [first])
    assert cli.main(["asks", "undo", "aaa"]) == 0
    assert "reopened: aaa00001" in capsys.readouterr().out
    saved = asks.load_state()
    assert saved["done"] == {} and "aaa00001" in saved["undone"]
    again = ask("aaa00001", pr=PR1)
    settle([again], gh, st=saved)
    assert again.status == "open"
    # and the next full run, which reads the store itself, leaves it open too
    asks.apply_state([again], asks.load_state(), NOW)
    asks.settle([again], NOW, fetch=True, runner=gh)
    assert again.status == "open"


def test_undo_of_something_not_done_says_so(monkeypatch, capsys):
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [ask("aaa00001")])
    assert cli.main(["asks", "undo", "aaa00001"]) == 1
    assert "not done: aaa00001" in capsys.readouterr().err
    assert cli.main(["asks", "undo"]) == 64


# --- dedupe --------------------------------------------------------------------------------------

def test_the_same_session_and_question_collapse_into_the_newest_ignoring_case_markdown_and_spacing():
    old = ask("aaa00001", days_ago=5, question="Ship **it** to  the `beta`?", session="s1")
    new = ask("aaa00002", days_ago=1, question="ship it to the beta?", session="s1")
    settle([old, new], None)
    assert (old.status, new.status) == ("duplicate", "open")
    assert new.dupes == ["aaa00001"] and old.note == "auto: duplicate of aaa00002"
    assert "dupes" in new.to_dict(NOW) and new.to_dict(NOW)["dupes"] == ["aaa00001"]
    assert "dupes" not in old.to_dict(NOW) and "note" not in new.to_dict(NOW)


def test_the_same_question_in_another_session_is_not_a_dupe_when_it_is_short():
    a, b = ask("aaa00001", question="Ship it now?", session="s1"), ask("aaa00002", question="Ship it now?", session="s2")
    settle([a, b], None)
    assert (a.status, b.status) == ("open", "open") and not b.dupes


def test_a_jaccard_of_point_eight_collapses_and_a_near_miss_stays_separate():
    def jaccard(x, y):
        wx, wy = asks.question_words(x), asks.question_words(y)
        return len(wx & wy) / len(wx | wy)
    assert jaccard(BASE, NEAR) >= 0.8 > jaccard(BASE, FAR)
    old, new = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    settle([old, new], None)
    assert (old.status, new.status) == ("duplicate", "open") and new.dupes == ["aaa00001"]
    old, miss = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00003", days_ago=1, question=FAR)
    settle([old, miss], None)
    assert (old.status, miss.status) == ("open", "open") and miss.dupes == []


def test_a_question_with_fewer_than_six_words_never_matches_by_jaccard():
    a = ask("aaa00001", question="Should the exporter use retries or not?")        # 6 words incl. 'the', 'use', 'not'
    b = ask("aaa00002", question="Should the exporter use retries or not??", days_ago=1)
    c = ask("aaa00003", question="Which plan now", days_ago=5)
    d = ask("aaa00004", question="Which plan now!", days_ago=2)
    settle([a, b, c, d], None)
    assert (a.status, c.status) == ("duplicate", "open") and d.dupes == []


def test_dupes_in_different_products_do_not_collapse():
    a, b = ask("aaa00001", "lens", days_ago=4, question=BASE), ask("aaa00002", "atlas", days_ago=1, question=BASE)
    settle([a, b], None)
    assert (a.status, b.status) == ("open", "open") and b.dupes == []


def test_only_questions_collapse():
    a = ask("aaa00001", days_ago=4, question=BASE, kind="blocked")
    b = ask("aaa00002", days_ago=1, question=BASE, kind="blocked")
    settle([a, b], None)
    assert (a.status, b.status) == ("open", "open")


def test_a_repeat_of_a_done_ask_is_done_too_and_the_store_says_why():
    old, new = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    new.status = "done"
    st = settle([old, new], None)
    assert old.status == "done" and st["done"]["aaa00001"]["note"] == "auto: duplicate of aaa00002"
    assert asks.filtered_counts([old, new]) == (0, 1)


def test_a_manually_done_older_ask_is_left_alone_and_does_not_count():
    old, new = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    old.status = "done"
    settle([old, new], None)
    assert new.status == "open" and new.dupes == [] and asks.filtered_counts([old, new]) == (0, 0)


def test_undoing_the_kept_ask_puts_its_auto_closed_repeats_back_under_it(monkeypatch):
    old, new = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    new.status = "done"
    st = settle([old, new], None)
    st["done"]["aaa00002"] = {"ts": iso(0), "note": "manual"}
    asks.save_state(st, now=NOW)
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [old, new])
    assert asks.undo(["aaa00002"], NOW)[1] == 0
    saved = asks.load_state()
    assert saved["done"] == {} and "aaa00002" in saved["undone"]
    a, b = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    asks.settle([a, b], NOW, st=saved)
    assert (a.status, b.status) == ("duplicate", "open")


def test_undoing_a_hidden_duplicate_shows_it_again(monkeypatch):
    old, new = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    settle([old, new], None)
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [old, new])
    assert asks.undo(["aaa00001"], NOW)[1] == 0
    a, b = ask("aaa00001", days_ago=4, question=BASE), ask("aaa00002", days_ago=1, question=NEAR)
    asks.settle([a, b], NOW, st=asks.load_state())
    assert (a.status, b.status) == ("open", "open")


# --- the report ----------------------------------------------------------------------------------

@pytest.fixture
def machine(monkeypatch, tmp_path):
    """Four asks in two products as the sources would yield them, and a fake gh behind backlog.default_runner."""
    items = [ask("aaa00001", pr=PR1, days_ago=6),                                   # PR merged -> resolved
             ask("aaa00002", days_ago=5, question=BASE), ask("aaa00003", days_ago=2, question=NEAR),   # a pair
             ask("aaa00004", "atlas", days_ago=1, question="Connect the first client and try a question?")]
    monkeypatch.setattr(asks, "collect_claude", lambda *a, **k: items)
    monkeypatch.setattr(asks, "collect_codex", lambda *a, **k: [])
    monkeypatch.setattr(asks, "collect_gates", lambda: [])
    monkeypatch.setattr(asks, "collect_reminders", lambda *a, **k: [])
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(backlog.shutil, "which", lambda name: "/usr/bin/gh")
    gh = FakeGh({PR1: ("MERGED", 1)})
    monkeypatch.setattr(backlog, "default_runner", gh)
    return gh


def test_the_listing_hides_what_was_filtered_and_ends_with_one_line_about_it(machine, capsys):
    assert cli.main(["asks"]) == 0
    out = capsys.readouterr().out
    assert "2 waiting on you" in out
    assert "aaa00001" not in out and "aaa00002" not in out
    assert "aaa00003" in out and "(+1 similar)" in out and "aaa00004" in out
    assert out.rstrip().splitlines()[-1] == "filtered: 1 resolved (PR merged/closed), 1 duplicates — teyla asks --all"


def test_all_shows_the_filtered_asks_with_their_notes_and_no_filter_line(machine, capsys):
    assert cli.main(["asks", "--all"]) == 0
    out = capsys.readouterr().out
    assert "aaa00001" in out and "aaa00002" in out and f"auto: PR merged {PR1}" in out
    assert "[duplicate, question]" in out and "auto: duplicate of aaa00003" in out
    assert "filtered:" not in out


def test_json_carries_dupes_and_the_two_counts(machine, capsys):
    assert cli.main(["asks", "--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["waiting"] == 2 and j["resolved"] == 1 and j["duplicates"] == 1
    kept = next(i for i in j["items"] if i["id"] == "aaa00003")
    assert kept["dupes"] == ["aaa00002"]
    assert "dupes" not in next(i for i in j["items"] if i["id"] == "aaa00004")


def test_nothing_filtered_prints_no_line(monkeypatch, capsys):
    monkeypatch.setattr(asks, "collect", lambda *a, **k: [ask("aaa00001")])
    assert cli.main(["asks"]) == 0
    assert "filtered:" not in capsys.readouterr().out


def test_the_done_store_keeps_the_auto_notes_and_a_second_run_asks_gh_nothing(machine, capsys):
    assert cli.main(["asks"]) == 0
    saved = json.loads(asks.state_path().read_text())
    assert saved["done"]["aaa00001"]["note"] == f"auto: PR merged {PR1}"
    assert len(machine.calls) == 1
    assert cli.main(["asks"]) == 0
    assert len(machine.calls) == 1                              # resolved asks are not asked about; the cache is fresh


def test_the_state_snapshot_counts_resolved_and_duplicates(machine, tmp_path, capsys):
    items = asks.collect(asks.DEFAULT_DAYS, NOW)
    assert asks.filtered_counts(items) == (0, 1)               # a snapshot alone does not ask GitHub
    assert cli.main(["asks"]) == 0                             # `teyla asks` did, and left the answer in the store
    items = asks.collect(asks.DEFAULT_DAYS, NOW)
    st = state.build(NOW, items=items, repos={}, spent=None, desktop=str(tmp_path / "none"),
                     codex_root=str(tmp_path / "nocodex"), runs=[], backlog_data=dict(backlog.EMPTY, prs=[], issues=[],
                                                                                     counts={}, canonical={}))
    assert st["totals"]["resolved"] == 1 and st["totals"]["duplicates"] == 1 and st["totals"]["questions"] == 2
    assert {a["id"] for a in st["asks"]} == {"aaa00003", "aaa00004"} and st["version"] == 2


def test_collect_alone_never_reaches_gh(machine):
    asks.collect(asks.DEFAULT_DAYS, NOW)
    assert machine.calls == []
