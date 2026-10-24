"""`teyla product`: the registry file, the resolve order, the CLI and the state fields. Synthetic repos
in tmp dirs; TEYLA_HOME is a tmp dir for every test (conftest), so the real registry is never touched."""
from __future__ import annotations

import json
import pathlib
import stat

import pytest

from teyla import asks, cli, config, registry, state

NOW = 1_790_000_000.0
HOME = pathlib.Path.home()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A code root holding three git checkouts, plus a scratch folder."""
    root = tmp_path / "repos"
    for name in ("app-a", "app-b", "tool-c"):
        (root / name / ".git").mkdir(parents=True)
    (root / "notes").mkdir()                                  # a folder, not a repo
    (tmp_path / "scratch").mkdir()
    monkeypatch.setattr(config, "code_root", lambda cfg=None: root)
    return root


def reg_with(**products) -> dict:
    return {"product": {pid: {**registry.new_product(pid), **p} for pid, p in products.items()}, "assign": {}}


# --- resolve ----------------------------------------------------------------------------------

def test_a_registered_repo_and_its_subdirectories_map_to_the_product(tree):
    reg = reg_with(**{"app-a": {"repos": [str(tree / "app-a")]}})
    assert registry.resolve(tree / "app-a", reg=reg) == "app-a"
    assert registry.resolve(tree / "app-a" / "ios" / "Sources", reg=reg) == "app-a"


def test_the_registry_beats_the_directory_name(tree):
    reg = reg_with(portal={"repos": [str(tree / "app-a")]})
    assert registry.resolve(tree / "app-a", reg=reg) == "portal"


def test_extra_paths_belong_to_the_product(tree, tmp_path):
    reg = reg_with(**{"app-b": {"repos": [str(tree / "app-b")], "paths": [str(tmp_path / "scratch")]}})
    assert registry.resolve(tmp_path / "scratch" / "x", reg=reg) == "app-b"


def test_the_longest_matching_prefix_wins(tree):
    reg = reg_with(mono={"repos": [str(tree / "app-a")]}, sub={"paths": [str(tree / "app-a" / "tools" / "sub")]})
    assert registry.resolve(tree / "app-a" / "tools" / "sub" / "x", reg=reg) == "sub"
    assert registry.resolve(tree / "app-a" / "tools", reg=reg) == "mono"


def test_assign_beats_path_beats_code_root_beats_unassigned(tree, tmp_path):
    reg = reg_with(**{"app-b": {"repos": [str(tree / "app-b")]}})
    # an unregistered git checkout under code_root keeps its directory name
    assert registry.resolve(tree / "tool-c", reg=reg) == "tool-c"
    # a registered path wins over that
    assert registry.resolve(tree / "app-b", reg=reg) == "app-b"
    # the session assignment wins over the path
    reg["assign"]["sess-1"] = "tool-c"
    assert registry.resolve(tree / "app-b", session="sess-1", reg=reg) == "tool-c"
    # the ask assignment too, and a session id in a list of two
    reg["assign"]["abcd1234"] = "app-a"
    assert registry.resolve(tree / "app-b", ask_id="abcd1234", reg=reg) == "app-a"
    assert registry.resolve(tree / "app-b", session=("nope", "sess-1"), reg=reg) == "tool-c"
    # nothing matches: unassigned
    assert registry.resolve(tmp_path / "scratch", reg=reg) == "unassigned"


def test_worktrees_map_to_their_repo(tree, tmp_path):
    reg = reg_with(**{"app-a": {"repos": [str(tree / "app-a")]}})
    assert registry.resolve(tree / "app-a" / ".claude" / "worktrees" / "calm-fox", reg=reg) == "app-a"
    other = tmp_path / "elsewhere" / "app-a"               # a registered checkout outside code_root
    reg = reg_with(portal={"repos": [str(other)]})
    wt = tmp_path / ".worktrees" / "app-a" / "feat-x"      # ~/.worktrees/<repo>/<branch> matches by repo name
    assert registry.resolve(wt, reg=reg) == "portal"
    assert registry.resolve(other / ".claude" / "worktrees" / "x", reg=reg) == "portal"
    # unregistered: the checkout under code_root; a deleted worktree still resolves
    assert registry.resolve(tmp_path / ".worktrees" / "tool-c" / "gone", reg=reg_with()) == "tool-c"
    assert registry.resolve(tree / "tool-c" / ".claude" / "worktrees" / "gone", reg=reg_with()) == "tool-c"
    assert registry.resolve(tmp_path / ".worktrees" / "unknown-repo" / "b", reg=reg_with()) == "unassigned"


@pytest.mark.parametrize("cwd", ["", None, "/", "/private/tmp/claude-501/x/scratch", str(HOME), "/nowhere/at/all"])
def test_resolve_never_returns_the_old_placeholder_names(tree, cwd):
    out = registry.resolve(cwd, reg=reg_with())
    assert out == "unassigned"
    assert out not in ("(no repo)", "(home)", "(scratch)", "unknown")


def test_the_code_root_itself_and_a_plain_folder_in_it_are_unassigned(tree):
    assert registry.resolve(tree, reg=reg_with()) == "unassigned"
    assert registry.resolve(tree / "notes", reg=reg_with()) == "unassigned"


def test_resolve_reads_the_file_and_follows_edits(tree):
    assert registry.resolve(tree / "app-a") == "app-a"
    reg = registry.load()
    reg["product"]["portal"] = registry.new_product("portal", repos=[tree / "app-a"])
    registry.save(reg)
    assert registry.resolve(tree / "app-a") == "portal"


# --- the file ---------------------------------------------------------------------------------

def test_save_and_load_round_trip_with_quoted_keys_and_unknown_fields(tree):
    reg = reg_with(**{"app-a": {"repos": ["~/repos/app-a"], "aliases": ["appa"], "focus": True, "owner": "me"}})
    reg["assign"]["019a2b3c-0000-4000-8000-000000000001"] = "app-a"
    p = registry.save(reg)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    again = registry.load()
    assert again["product"]["app-a"]["owner"] == "me"
    assert again["product"]["app-a"]["focus"] is True
    assert again["assign"] == reg["assign"]
    assert 'name = "App A"' in p.read_text()


def test_a_broken_file_reads_as_empty_but_is_never_written_over(tree):
    registry.path().write_text("[product.x\nname = ")
    assert registry.load() == {"product": {}, "assign": {}}
    with pytest.raises(registry.RegistryError):
        registry.load(strict=True)
    assert cli.main(["product", "set", "x", "stage=live"]) == 1
    assert registry.path().read_text().startswith("[product.x")


# --- init -------------------------------------------------------------------------------------

def test_init_proposes_repos_and_stages_from_the_last_commit(tree, monkeypatch):
    ages = {"app-a": NOW - 3 * 86400, "app-b": NOW - 90 * 86400, "tool-c": None}
    monkeypatch.setattr(registry, "_last_commit", lambda d: ages[d.name])
    new = registry.propose(registry.load(), now=NOW)
    assert list(new) == ["app-a", "app-b", "tool-c"]
    assert [new[k]["stage"] for k in new] == ["building", "parked", "parked"]
    assert new["app-a"]["name"] == "App A" and new["app-a"]["repos"] == [str(tree / "app-a")]


def test_init_write_adds_missing_products_and_never_overwrites_edits(tree, monkeypatch, capsys):
    monkeypatch.setattr(registry, "_last_commit", lambda d: NOW)
    monkeypatch.setattr("time.time", lambda: NOW)
    reg = reg_with(**{"app-a": {"name": "Portal", "stage": "live", "focus": True, "repos": [str(tree / "app-a")]}})
    registry.save(reg)
    assert cli.main(["product", "init"]) == 0
    assert "app-a" not in capsys.readouterr().out
    assert registry.load()["product"].keys() == {"app-a"}           # no --write: nothing written
    assert cli.main(["product", "init", "--write"]) == 0
    after = registry.load()["product"]
    assert set(after) == {"app-a", "app-b", "tool-c"}
    assert (after["app-a"]["name"], after["app-a"]["stage"], after["app-a"]["focus"]) == ("Portal", "live", True)
    assert cli.main(["product", "init", "--write"]) == 0
    assert "nothing to add" in capsys.readouterr().out


def test_init_skips_a_repo_held_by_a_product_under_another_id(tree, monkeypatch):
    monkeypatch.setattr(registry, "_last_commit", lambda d: NOW)
    reg = reg_with(portal={"repos": [str(tree / "app-a")]})
    assert "app-a" not in registry.propose(reg, now=NOW)


# --- set, add, park, wake ---------------------------------------------------------------------

def test_add_set_and_list(tree, capsys):
    assert cli.main(["product", "add", "app-a", "--repo", str(tree / "app-a")]) == 0
    assert cli.main(["product", "add", "app-a"]) == 1
    assert cli.main(["product", "add", "unassigned"]) == 2
    assert cli.main(["product", "add", "bad id"]) == 2
    assert cli.main(["product", "set", "app-a", "name=App A+", "stage=beta", "primary=ios", "focus=true",
                     "aliases=AppA, a-app", f"add-path={tree / 'notes'}"]) == 0
    p = registry.load()["product"]["app-a"]
    assert (p["name"], p["stage"], p["primary"], p["focus"]) == ("App A+", "beta", "ios", True)
    assert p["aliases"] == ["appa", "a-app"] and p["paths"] == [str(tree / "notes")]
    assert cli.main(["product", "set", "app-a", "stage=nonsense"]) == 2
    assert cli.main(["product", "set", "nope", "stage=live"]) == 1
    capsys.readouterr()
    assert cli.main(["product", "list"]) == 0
    line = capsys.readouterr().out.splitlines()[1]
    assert line.split()[:3] == ["app-a", "beta", "*"] and "ios" in line
    assert cli.main(["product", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["products"][0]["id"] == "app-a"


def test_park_remembers_the_stage_and_wake_restores_it(tree, capsys):
    cli.main(["product", "add", "app-a", "--stage", "beta"])
    assert cli.main(["product", "park", "app-a"]) == 0
    p = registry.load()["product"]["app-a"]
    assert (p["stage"], p["stage_before_park"]) == ("parked", "beta")
    assert cli.main(["product", "park", "app-a"]) == 0               # twice keeps the first memory
    assert registry.load()["product"]["app-a"]["stage_before_park"] == "beta"
    assert cli.main(["product", "wake", "app-a"]) == 0
    p = registry.load()["product"]["app-a"]
    assert p["stage"] == "beta" and "stage_before_park" not in p
    cli.main(["product", "set", "app-a", "stage=parked"])             # set stage=parked goes through park
    assert registry.load()["product"]["app-a"]["stage_before_park"] == "beta"
    capsys.readouterr()
    cli.main(["product", "wake", "app-a"])
    assert "woke app-a: stage beta" in capsys.readouterr().out


def test_products_the_usage_table_still_parses():
    ns = cli.build_parser().parse_args(["products"])
    assert ns.fn is cli.cmd_products
    assert cli.build_parser().parse_args(["product"]).fn is registry.cmd_product


# --- assign -----------------------------------------------------------------------------------

def ask(id, session, product="app-a", title="t"):
    return asks.Ask(id=id, kind="question", product=product, title=title, question="q", context="", options=[],
                    when=NOW, archived=False, link="", pr="", harness="claude-code", session=session)


def test_assign_by_ask_id_prefix_files_the_whole_session(tree, capsys):
    reg = reg_with(**{"app-a": {}, "app-b": {}})
    registry.save(reg)
    items = [ask("abcd1234", "sess-1", title="first"), ask("abce5678", "sess-1", title="second"),
             ask("ffff0000", "sess-2")]
    lines, code = registry.assign("abcd", "app-b", items=items)
    assert code == 0
    assert registry.load()["assign"] == {"sess-1": "app-b"}
    assert [l.split()[0] for l in lines[1:]] == ["abcd1234", "abce5678"]       # what moved
    assert registry.resolve(tree / "app-a", session="sess-1") == "app-b"
    assert registry.resolve(tree / "app-a", session="sess-2") == "app-a"


def test_assign_ask_only_stores_the_ask_id(tree):
    registry.save(reg_with(**{"app-a": {}, "app-b": {}}))
    items = [ask("abcd1234", "sess-1"), ask("abce5678", "sess-1")]
    lines, code = registry.assign("abcd1234", "app-b", ask_only=True, items=items)
    assert code == 0 and registry.load()["assign"] == {"abcd1234": "app-b"}
    assert len(lines) == 2


def test_assign_by_full_session_id_even_when_no_ask_uses_it(tree):
    registry.save(reg_with(**{"app-b": {}}))
    sid = "019a2b3c-0000-4000-8000-000000000001"
    lines, code = registry.assign(sid, "app-b", items=[ask("abcd1234", sid)])
    assert code == 0 and registry.load()["assign"] == {sid: "app-b"}
    other = "019a2b3c-0000-4000-8000-000000000002"
    lines, code = registry.assign(other, "app-b", items=[])
    assert code == 0 and "no current ask" in lines[0]


def test_assign_refuses_an_unknown_product_or_ask(tree):
    registry.save(reg_with(**{"app-a": {}}))
    assert registry.assign("abcd", "nope", items=[ask("abcd1234", "s")])[1] == 1
    assert registry.assign("zzzz", "app-a", items=[ask("abcd1234", "s")])[1] == 1
    assert registry.load()["assign"] == {}


def test_asks_use_the_assignment(tree, monkeypatch):
    """The collectors go through registry.resolve, so a correction moves the ask."""
    registry.save({"product": {"app-b": registry.new_product("app-b")}, "assign": {"cli-1": "app-b"}})
    session = {"sessionId": "local_cli-1", "cliSessionId": "cli-1", "cwd": str(tree / "app-a"), "isArchived": False,
               "title": "T", "createdAt": int(NOW * 1000), "lastActivityAt": int(NOW * 1000),
               "postTurnSummary": {"status_category": "blocked", "needs_action": "Which db?", "status_detail": ""}}
    a = asks._claude_ask(session, None, "cli-1", NOW - 86400)
    assert a.product == "app-b"
    b = asks._claude_ask(session, None, "cli-2", NOW - 86400)
    assert b.product == "app-a"


# --- match_text -------------------------------------------------------------------------------

def test_match_text_finds_whole_words_names_and_aliases():
    reg = reg_with(**{"app-a": {"name": "App A", "aliases": ["appa"]},
                      "tool-c": {"name": "Tool C", "aliases": ["toolbox"]},
                      "cat": {"name": "Cat"}})
    assert registry.match_text("ship APPA to testers", reg) == ["app-a"]
    assert registry.match_text("the App   A launch and a toolbox", reg) == ["app-a", "tool-c"]
    assert registry.match_text("app-a, then tool-c.", reg) == ["app-a", "tool-c"]
    assert registry.match_text("concatenate the category", reg) == []          # not whole words
    assert registry.match_text("a cat's day", reg) == ["cat"]
    assert registry.match_text("", reg) == [] and registry.match_text(None, reg) == []


# --- the state snapshot -----------------------------------------------------------------------

def test_products_view_keeps_the_old_fields_and_adds_the_registry_ones():
    reg = reg_with(**{"app-a": {"name": "App A", "stage": "parked", "primary": "web", "focus": True},
                      "app-b": {"name": "App B", "stage": "live"}})
    rows = [{"product": "unassigned", "title": "orphan", "ts": "2026-10-16T10:00:00Z"},
            {"product": "app-a", "title": "q", "ts": "2026-10-15T10:00:00Z"},
            {"product": "app-a", "title": "q2", "ts": "2026-10-14T10:00:00Z"}]
    by = state.products_view(rows, [], {}, NOW, reg=reg)
    names = [p["name"] for p in by]
    assert names == ["app-a", "app-b", "unassigned"]                      # unassigned last, even with asks waiting
    a, b, u = by
    for old in ("name", "waiting", "state", "line", "last_activity"):
        assert old in a
    assert a["waiting"] == 2 and a["state"] == "waiting"
    assert (a["id"], a["display_name"], a["stage"], a["focus"], a["primary"], a["registered"]) == (
        "app-a", "App A", "parked", True, "web", True)
    assert (b["display_name"], b["stage"], b["focus"], b["registered"]) == ("App B", "live", False, True)
    assert (u["display_name"], u["stage"], u["registered"]) == ("Unassigned", "", False)


def test_unassigned_without_asks_is_not_listed():
    assert state.products_view([], [], {}, NOW, reg=reg_with()) == []
