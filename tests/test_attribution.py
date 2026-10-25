"""`registry.attribute`, `teyla asks --why` and whole questions. Synthetic repos in tmp dirs; the
product names are generic (app-a, app-b, tool-c) and no real session text appears here."""
from __future__ import annotations

import json

import pytest

from teyla import asks, cli, config, registry

NOW = 1_790_000_000.0
PR_B = "https://github.com/example/app-b/pull/7"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A code root with three git checkouts (app-a, app-b registered by the tests, tool-c never registered)."""
    root = tmp_path / "repos"
    for name in ("app-a", "app-b", "tool-c", "app-d"):
        (root / name / ".git").mkdir(parents=True)
    (tmp_path / "scratch").mkdir()
    monkeypatch.setattr(config, "code_root", lambda cfg=None: root)
    return root


def reg_with(tree, **extra) -> dict:
    prods = {"app-a": {"name": "App A", "repos": [str(tree / "app-a")]},
             "app-b": {"name": "Bee Hive", "repos": [str(tree / "app-b")], "aliases": ["bee"]},
             "shop-e": {"name": "Shop E"}, **extra}
    return {"product": {pid: {**registry.new_product(pid), **p} for pid, p in prods.items()}, "assign": {}}


def attr(tree, cwd, **kw):
    return registry.attribute(cwd, reg=kw.pop("reg", None) or reg_with(tree), **kw)


# --- the order ---------------------------------------------------------------------------------

def test_each_rule_names_itself(tree, tmp_path):
    reg = reg_with(tree)
    reg["assign"]["sess-1"] = "shop-e"
    assert attr(tree, tree / "app-a", reg=reg, session="sess-1") == ("shop-e", "assign")
    assert attr(tree, tree / "app-a", reg=reg, pr=PR_B) == ("app-b", "pr")
    assert attr(tree, tree / "app-a", reg=reg) == ("app-a", "path")
    assert attr(tree, tmp_path / "scratch", reg=reg, texts=("plan the Bee Hive launch", "")) == ("app-b", "text")
    assert attr(tree, tree / "tool-c", reg=reg) == ("tool-c", "checkout")
    assert attr(tree, tmp_path / "scratch", reg=reg) == ("unassigned", "unassigned")
    assert attr(tree, None, reg=reg) == ("unassigned", "unassigned")


def test_assign_beats_pr_and_the_ask_beats_the_session(tree):
    reg = reg_with(tree)
    reg["assign"]["sess-1"] = "app-a"
    reg["assign"]["abcd1234"] = "shop-e"
    assert attr(tree, tree / "app-b", reg=reg, session="sess-1", pr=PR_B) == ("app-a", "assign")
    assert attr(tree, tree / "app-b", reg=reg, session="sess-1", ask_id="abcd1234", pr=PR_B) == ("shop-e", "assign")


def test_pr_beats_path_and_text(tree):
    reg = reg_with(tree)
    assert attr(tree, tree / "app-a", reg=reg, pr=PR_B, texts=("App A review", "")) == ("app-b", "pr")


def test_pr_repo_matches_a_repo_directory_an_id_or_an_alias(tree):
    reg = reg_with(tree, portal={"repos": [str(tree / "tool-c")]})
    pr = lambda repo: f"https://github.com/example/{repo}/pull/1"   # noqa: E731
    assert attr(tree, None, reg=reg, pr=pr("tool-c")) == ("portal", "pr")        # a repos entry's directory name
    assert attr(tree, None, reg=reg, pr=pr("Shop-E")) == ("shop-e", "pr")  # an id, any case
    assert attr(tree, None, reg=reg, pr=pr("bee")) == ("app-b", "pr")            # an alias
    assert attr(tree, tree / "app-a", reg=reg, pr=pr("unknown-repo")) == ("app-a", "path")
    assert attr(tree, tree / "app-a", reg=reg, pr="not a link") == ("app-a", "path")


def test_a_repo_name_held_by_two_products_makes_no_pr_match(tree):
    reg = reg_with(tree, twin={"repos": [str(tree / "app-b")]})
    assert attr(tree, tree / "app-a", reg=reg, pr=PR_B) == ("app-a", "path")


# --- text --------------------------------------------------------------------------------------

def test_the_title_overrides_the_cwd_product(tree):
    assert attr(tree, tree / "app-a", texts=("Bee Hive checkout flow", "any question")) == ("app-b", "text")


def test_the_title_does_not_override_when_it_also_names_the_cwd_product(tree):
    assert attr(tree, tree / "app-a", texts=("App A and Bee Hive", "")) == ("app-a", "path")


def test_the_title_naming_the_cwd_product_keeps_it(tree):
    assert attr(tree, tree / "app-a", texts=("App A polish", "ask about Bee Hive")) == ("app-a", "path")


def test_question_text_alone_never_overrides_a_registered_cwd(tree):
    assert attr(tree, tree / "app-a", texts=("A session", "should Bee Hive get a dark mode?")) == ("app-a", "path")


def test_text_fills_in_when_the_cwd_gave_no_registered_product(tree):
    """Title first, then the question; an unregistered checkout is below text."""
    assert attr(tree, tree / "tool-c", texts=("A session", "should Bee Hive get a dark mode?")) == ("app-b", "text")
    assert attr(tree, tree / "tool-c", texts=("Shop E labels", "Bee Hive?")) == ("shop-e", "text")


def test_two_products_named_make_no_text_match(tree, tmp_path):
    assert attr(tree, tmp_path / "scratch", texts=("Bee Hive and Shop E", "")) == ("unassigned", "unassigned")
    assert attr(tree, tmp_path / "scratch", texts=("A session", "Bee Hive or Shop E?")) == ("unassigned", "unassigned")
    assert attr(tree, tree / "app-a", texts=("Bee Hive and Shop E", "")) == ("app-a", "path")


def test_match_text_takes_the_display_name_and_hyphens_as_spaces():
    reg = {"product": {"shop-e": {**registry.new_product("shop-e"), "name": "The Cellar"},
                       "lab_k": {**registry.new_product("lab_k"), "name": "Lab"}}, "assign": {}}
    assert registry.match_text("add a note to shop e", reg) == ["shop-e"]
    assert registry.match_text("SHOP-E and the cellar", reg) == ["shop-e"]
    assert registry.match_text("the cellar tab", reg) == ["shop-e"]
    assert registry.match_text("Shop  E", reg) == ["shop-e"]
    assert registry.match_text("lab k notes", reg) == ["lab_k"]
    assert registry.match_text("shop es and toolc", reg) == []              # whole words only
    reg["product"]["shop-e"]["display_name"] = "Vault"
    assert registry.match_text("open the vault", reg) == ["shop-e"]


def test_resolve_is_the_path_rule_alone(tree, tmp_path):
    reg = reg_with(tree)
    assert registry.resolve(tree / "app-a", reg=reg) == "app-a"
    assert registry.resolve(tree / "tool-c", reg=reg) == "tool-c"
    assert registry.resolve(tmp_path / "scratch", reg=reg) == "unassigned"
    assert registry.resolve("", reg=reg) == "unassigned"


# --- asks: attributed_by, --why ----------------------------------------------------------------

def session(tree, **kw):
    d = {"sessionId": "local_cli-1", "cliSessionId": "cli-1", "cwd": str(tree / "app-a"), "isArchived": False,
         "title": "A session", "createdAt": int(NOW * 1000), "lastActivityAt": int(NOW * 1000), "prs": [],
         "postTurnSummary": {"status_category": "blocked", "needs_action": "Which database?", "status_detail": ""}}
    d.update(kw)
    return d


@pytest.fixture
def saved(tree):
    reg = reg_with(tree)
    registry.save(reg)
    return reg


def test_an_ask_records_how_it_was_attributed(tree, saved):
    a = asks._claude_ask(session(tree), None, "cli-1", NOW - 86400)
    assert (a.product, a.attributed_by) == ("app-a", "path")
    b = asks._claude_ask(session(tree, prs=[{"url": PR_B}]), None, "cli-1", NOW - 86400)
    assert (b.product, b.attributed_by, b.pr) == ("app-b", "pr", PR_B)
    c = asks._claude_ask(session(tree, title="Bee Hive pricing"), None, "cli-1", NOW - 86400)
    assert (c.product, c.attributed_by) == ("app-b", "text")


def test_json_has_attributed_by_and_not_the_evidence(tree, saved):
    a = asks._claude_ask(session(tree), None, "cli-1", NOW - 86400)
    d = a.to_dict(NOW, attribution=True)
    assert d["attributed_by"] == "path" and "evidence" not in d
    assert "attributed_by" not in a.to_dict(NOW)            # the state snapshot keeps its v2 keys


def test_why_prints_one_line_with_the_evidence(tree, saved, monkeypatch, capsys):
    a = asks._claude_ask(session(tree, title="Bee Hive pricing"), None, "cli-1", NOW - 86400)
    b = asks._claude_ask(session(tree, cliSessionId="cli-2", sessionId="local_cli-2", prs=[{"url": PR_B}]),
                         None, "cli-2", NOW - 86400)
    monkeypatch.setattr(asks, "collect", lambda *a_, **k: [a, b])
    assert cli.main(["asks", "--why", a.id[:4]]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == [f"{a.id} → app-b (by text: title names app-b, not app-a (cwd))"]
    assert cli.main(["asks", "--why", b.id]) == 0
    assert capsys.readouterr().out.strip() == f"{b.id} → app-b (by pr: PR example/app-b)"
    assert cli.main(["asks", "--why", "zzz999"]) == 1
    assert cli.main(["asks", "--why", a.id, "done"]) == 64


def test_why_for_a_path_names_the_directory(tree, saved):
    a = asks._claude_ask(session(tree), None, "cli-1", NOW - 86400)
    line, code = asks.why_line(a.id, [a])
    assert code == 0 and line.startswith(f"{a.id} → app-a (by path: ") and line.endswith("app-a)")


# --- whole questions ---------------------------------------------------------------------------

def test_a_clipped_tail_is_backed_up_to_the_start_of_its_sentence():
    sentence = "Checks passed: " + "item " * 70 + "and reviews."
    text = "Intro line. " + "Filler words here. " * 12 + sentence + " Needs you: which layout should lead?"
    cut = len(text) - asks.TRAILING_MAX
    assert text.index(sentence) < cut < text.index(sentence) + len(sentence)      # the 400-character cut is mid-sentence
    q = asks.trailing_question(text)
    assert q.startswith("Checks passed") and q.endswith("lead?") and len(q) <= asks.QUESTION_MAX


def test_a_clipped_tail_that_cannot_back_up_moves_on_to_the_next_sentence():
    long_sentence = "word " * 140 + "ends here."
    text = long_sentence + " Which layout should lead? Say A or B."
    q = asks.trailing_question(text + " Or C?")
    assert not asks.is_fragment(q) and q.startswith("Which layout") and len(q) <= asks.TRAILING_MAX


def test_a_question_with_no_sentence_start_keeps_the_ellipsis_cut():
    q = asks.trailing_question("word " * 200 + "do you agree?")
    assert q.startswith("…") and q.endswith("do you agree?") and len(q) <= 400


def test_a_short_question_that_starts_lowercase_backs_up_across_paragraphs():
    text = "The migration is ready, and\n\nthe rollback is tested. which db first?"
    q = asks.trailing_question(text)
    assert q.startswith("The migration") and q.endswith("which db first?")


def test_a_question_that_starts_a_sentence_is_left_alone():
    assert asks.trailing_question("Done.\n\nWhich of the two layouts do you want?") == "Which of the two layouts do you want?"


@pytest.mark.parametrize("q,lead", [
    ("say to start the second wave", True),
    ("Approve the checksum change", True),
    ("go ahead", True),
    ("Which layout should lead?", False),                  # a question
    ("say to start the second wave when the build is green", False),   # long enough to stand alone
    ("Branch looks fine today", False),                    # not an imperative
    ("", False),
])
def test_a_bare_imperative_gets_the_session_title_as_its_lead(q, lead):
    out = asks.with_title_lead("Release plan", q)
    assert (out == f"Release plan: {q}") is lead


def test_the_lead_is_skipped_without_a_title_or_when_the_title_has_it():
    assert asks.with_title_lead("", "go ahead") == "go ahead"
    assert asks.with_title_lead("Please go ahead now", "go ahead") == "go ahead"


def test_the_collector_puts_the_lead_in_the_question(tree, saved):
    s = session(tree, title="Second wave", postTurnSummary={"status_category": "blocked", "status_detail": "",
                                                           "needs_action": "say to start the second wave"})
    a = asks._claude_ask(s, None, "cli-1", NOW - 86400)
    assert a.question == "Second wave: say to start the second wave"
    assert len(a.question) <= asks.QUESTION_MAX


def test_the_question_limit_is_unchanged():
    assert asks.QUESTION_MAX == 600
