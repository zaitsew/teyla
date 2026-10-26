"""`teyla asks` grouped by product, and the muting of parked products. The asks are built by hand and
`asks.collect` is replaced, so no session file is read; the registry is a real file in the tmp
TEYLA_HOME that conftest gives every test."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import asks, cli, registry, state

pytestmark = pytest.mark.usefixtures("fake_code_root")

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()


def ask(id_, product, *, days_ago=1.0, kind="question", title="A session", question="Which font?", context=""):
    return asks.Ask(id=id_, kind=kind, product=product, title=title, question=question, context=context,
                    options=[], when=NOW - days_ago * 86400, archived=False, link=f"claude://x/{id_}", pr="",
                    harness="claude-code")


def register(**products):
    """{id: fields} -> products.toml. Fields go over registry.new_product's defaults."""
    reg = registry.load()
    for pid, fields in products.items():
        reg["product"][pid] = {**registry.new_product(pid, stage="building"), **fields}
    registry.save(reg)
    return registry.load()


@pytest.fixture
def run(monkeypatch, capsys):
    """Run `teyla asks ...` over a fixed list of asks; returns the printed text."""
    def go(items, *argv):
        monkeypatch.setattr(asks, "collect", lambda *a, **k: list(items))
        monkeypatch.setattr(asks, "_now", lambda: NOW)
        capsys.readouterr()
        assert cli.main(["asks", *argv]) == 0
        return capsys.readouterr().out
    return go


def heads(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if " waiting" in ln and not ln.startswith(" ") and "on you" not in ln]


# --- grouping -----------------------------------------------------------------------------------

def test_groups_put_focus_first_and_unassigned_last(run):
    register(atlas={"name": "Atlas"}, cellar={"name": "Cellar", "focus": True}, lens={"name": "Lens"})
    items = [ask("aaa00001", "unassigned", days_ago=9), ask("aaa00002", "lens", days_ago=7),
             ask("aaa00003", "atlas", days_ago=5), ask("aaa00004", "cellar", days_ago=1),
             ask("aaa00005", "atlas", days_ago=2)]
    out = run(items)
    assert out.splitlines()[0] == "5 waiting on you (0 in archived sessions)"
    assert heads(out) == ["Cellar  1 waiting  [building]", "Lens  1 waiting  [building]",
                          "Atlas  2 waiting  [building]", "Unassigned  1 waiting"]
    assert out.index("aaa00003") < out.index("aaa00005")        # the order inside a group is kept
    assert [g[0] for g in asks.group(items, registry.load())] == ["cellar", "lens", "atlas", "unassigned"]


def test_a_product_the_registry_does_not_know_is_listed_by_its_id_without_a_stage(run):
    out = run([ask("aaa00001", "app")])
    assert heads(out) == ["app  1 waiting"]


def test_flat_prints_the_old_list(run):
    register(atlas={"name": "Atlas", "focus": True}, lens={})
    items = [ask("aaa00001", "lens", days_ago=3, question="Ship it?"), ask("aaa00002", "atlas", days_ago=1)]
    expected = "\n".join([
        "2 waiting on you (0 in archived sessions)",
        "",
        "lens (1)",
        "  aaa00001     3d  [question]  A session",
        "      Ship it?",
        "      open: claude://x/aaa00001",
        "",
        "atlas (1)",
        "  aaa00002    24h  [question]  A session",
        "      Which font?",
        "      open: claude://x/aaa00002",
        "",
        "close one: teyla asks done <id>   hide for a while: teyla asks snooze <id> <days>",
    ])
    assert run(items, "--flat") == expected + "\n"
    assert asks.render_text(items, NOW, flat=True, reg=registry.load()) == expected


# --- muting -------------------------------------------------------------------------------------

def test_a_parked_product_is_muted_and_summed_up_in_one_line(run):
    register(atlas={}, lens={"stage": "parked"}, cellar={"stage": "parked"})
    items = [ask("aaa00001", "atlas"), ask("aaa00002", "lens"), ask("aaa00003", "cellar"), ask("aaa00004", "lens")]
    out = run(items)
    assert "aaa00001" in out and "aaa00002" not in out and "lens  " not in out
    assert out.splitlines()[0] == "1 waiting on you (0 in archived sessions)"
    assert out.splitlines()[-1] == ("3 muted in parked products (cellar, lens) — teyla asks --all, "
                                    "or teyla product wake <id>")


def test_nothing_muted_means_no_summary_line(run):
    register(atlas={})
    assert "muted" not in run([ask("aaa00001", "atlas")])


def test_a_parked_product_with_everything_muted_leaves_an_empty_list_and_the_line(run):
    register(lens={"stage": "parked"})
    out = run([ask("aaa00001", "lens")])
    assert out.splitlines()[0] == "nothing is waiting on you."
    assert out.splitlines()[-1].startswith("1 muted in parked products (lens)")


def test_all_and_product_show_the_muted_asks(run):
    register(atlas={}, lens={"stage": "parked"})
    items = [ask("aaa00001", "atlas"), ask("aaa00002", "lens")]
    every = run(items, "--all")
    assert "aaa00002" in every and "muted" not in every
    assert heads(every) == ["Atlas  1 waiting  [building]", "Lens  1 waiting  [parked]"]
    assert "[parked, question]" in every
    one = run(items, "--product", "lens")
    assert "aaa00002" in one and "aaa00001" not in one and "muted" not in one
    other = run(items, "--product", "atlas")                   # another product: the parked one is not mentioned
    assert "aaa00001" in other and "muted" not in other
    assert "aaa00002" not in run(items)


def test_waking_a_product_ends_the_muting(run):
    reg = register(lens={"stage": "parked"})
    assert "aaa00001" not in run([ask("aaa00001", "lens")])
    registry.wake(reg, "lens")
    registry.save(reg)
    assert "aaa00001" in run([ask("aaa00001", "lens")])


# --- what is never muted ------------------------------------------------------------------------

CRITICAL = [
    pytest.param(dict(kind="blocked"), id="blocked kind"),
    pytest.param(dict(question="Is this a security hole?"), id="security"),
    pytest.param(dict(title="Found a Vulnerability in login"), id="vulnerab*"),
    pytest.param(dict(context="The key leaked into a log."), id="leak*"),
    pytest.param(dict(question="Rotate the secrets?"), id="secret*"),
    pytest.param(dict(question="Which credentials do I use?"), id="credential*"),
    pytest.param(dict(question="The token expired. Sign in again?"), id="token expired"),
    pytest.param(dict(question="Why was I charged twice?"), id="charge*"),
    pytest.param(dict(title="Billing page"), id="billing"),
    pytest.param(dict(question="Pay the invoice?"), id="invoice"),
    pytest.param(dict(question="PAYMENT failed in checkout"), id="payment"),
    pytest.param(dict(question="Change the price to 4.99?"), id="price"),
    pytest.param(dict(question="Apple rejected the build."), id="rejected"),
    pytest.param(dict(title="Rejection from review"), id="rejection"),
    pytest.param(dict(question="Crashes on launch. Roll back?"), id="crash*"),
    pytest.param(dict(question="The  build failed on CI"), id="build failed"),
    pytest.param(dict(question="release failed at the last step"), id="release failed"),
    pytest.param(dict(context="Upload failed with a 409."), id="upload failed"),
]


@pytest.mark.parametrize("fields", CRITICAL)
def test_a_critical_ask_is_not_muted_in_a_parked_product(run, fields):
    register(lens={"name": "Lens", "stage": "parked"})
    item = ask("aaa00001", "lens", **fields)
    assert asks.is_critical(item) and not asks.is_muted(item, registry.load())
    out = run([item])
    assert heads(out) == ["Lens  1 waiting  [parked]"] and "aaa00001" in out and "muted" not in out
    assert "[parked, " in out


@pytest.mark.parametrize("text", ["Which font?", "Is the cost fine?", "A discharge of the battery", "overpriced", "leakproof is a word",
                                  "The tokens are fine", "Ship on Friday?"])
def test_ordinary_text_is_not_critical(text):
    # "leakproof" is the one near miss: `leak*` lets a word go on, so it counts; the rest must not.
    expected = text == "leakproof is a word"
    assert asks.is_critical(ask("aaa00001", "lens", question=text)) is expected


def test_a_critical_ask_shows_next_to_a_muted_one(run):
    register(lens={"stage": "parked"})
    out = run([ask("aaa00001", "lens", question="Pay the invoice?"), ask("aaa00002", "lens", days_ago=2)])
    assert "aaa00001" in out and "aaa00002" not in out
    assert out.splitlines()[-1].startswith("1 muted in parked products (lens)")


def test_flat_marks_a_critical_ask_in_a_parked_product(run):
    register(lens={"stage": "parked"})
    out = run([ask("aaa00001", "lens", kind="blocked")], "--flat")
    assert "lens (1)" in out and "[parked, blocked]" in out


# --- the count ----------------------------------------------------------------------------------

def test_the_count_file_matches_the_visible_listing(run):
    register(atlas={}, lens={"stage": "parked"})
    items = [ask("aaa00001", "atlas"), ask("aaa00002", "lens"), ask("aaa00003", "lens", question="Pay the invoice?")]
    out = run(items)
    assert out.splitlines()[0].startswith("2 waiting")
    assert asks.count_path().read_text() == "2 questions wait for you — teyla asks\n"
    run(items, "--quiet")
    assert asks.count_path().read_text() == "2 questions wait for you — teyla asks\n"
    run(items, "--all")                                     # a flag that widens the list does not rewrite the count
    assert asks.count_path().read_text() == "2 questions wait for you — teyla asks\n"


def test_the_count_is_gone_when_only_muted_asks_wait(run):
    register(lens={"stage": "parked"})
    items = [ask("aaa00001", "lens")]
    run(items, "--quiet")
    assert not asks.count_path().exists()
    reg = registry.load()
    registry.wake(reg, "lens")
    registry.save(reg)
    run(items, "--quiet")
    assert asks.count_path().read_text() == "1 question waits for you — teyla asks\n"


# --- json and html ------------------------------------------------------------------------------

def test_json_adds_groups_and_the_muted_fields_beside_the_old_keys(run):
    register(atlas={"name": "Atlas", "focus": True}, lens={"stage": "parked"}, cellar={"name": "Cellar"})
    items = [ask("aaa00001", "cellar", days_ago=4), ask("aaa00002", "atlas", days_ago=1),
             ask("aaa00003", "lens"), ask("aaa00004", "lens", kind="blocked")]
    d = json.loads(run(items, "--json"))
    assert {"waiting", "archived", "generated", "items"} <= set(d)
    assert d["waiting"] == 3 and [i["id"] for i in d["items"]] == ["aaa00001", "aaa00002", "aaa00004"]
    assert d["groups"] == [
        {"product": "atlas", "display_name": "Atlas", "stage": "building", "focus": True, "count": 1, "ids": ["aaa00002"]},
        {"product": "cellar", "display_name": "Cellar", "stage": "building", "focus": False, "count": 1, "ids": ["aaa00001"]},
        {"product": "lens", "display_name": "Lens", "stage": "parked", "focus": False, "count": 1, "ids": ["aaa00004"]},
    ]
    assert d["muted"] == 1 and d["muted_products"] == ["lens"]
    d = json.loads(run(items, "--json", "--all"))
    assert d["waiting"] == 4 and d["muted"] == 0 and d["muted_products"] == []


def test_html_has_the_same_groups_and_the_muted_line(run, tmp_path):
    register(atlas={"name": "Atlas", "focus": True}, lens={"stage": "parked"})
    items = [ask("aaa00001", "lens"), ask("aaa00002", "atlas"), ask("aaa00003", "lens", kind="blocked")]
    out_file = tmp_path / "page.html"
    run(items, "--html", "-o", str(out_file))
    page = out_file.read_text()
    assert "<h2>Atlas  1 waiting  [building]</h2>" in page and "<h2>Lens  1 waiting  [parked]</h2>" in page
    assert page.index("Atlas  1 waiting") < page.index("Lens  1 waiting")
    assert "aaa00001" not in page and "1 muted in parked products (lens)" in page
    assert page.count("<style>") == 1                       # no new styling system
    run(items, "--html", "--flat", "-o", str(out_file))
    assert "<h2>atlas &middot; 1</h2>" in out_file.read_text()


# --- the state snapshot -------------------------------------------------------------------------

def snapshot(items, tmp_path):
    desktop = tmp_path / "sessions"
    desktop.mkdir(exist_ok=True)
    return state.build(NOW, items=items, repos={}, spent=None, desktop=str(desktop), codex_root=str(tmp_path / "nocodex"),
                       model_brief=False, runs=[])


def test_state_marks_muted_asks_and_counts_them_per_product(tmp_path):
    register(atlas={"name": "Atlas"}, lens={"name": "Lens", "stage": "parked"}, cellar={"name": "Cellar", "stage": "parked"})
    items = [ask("aaa00001", "atlas", days_ago=3), ask("aaa00002", "lens", days_ago=1), ask("aaa00003", "lens", days_ago=2),
             ask("aaa00004", "cellar", days_ago=1, question="Why was I charged?")]
    st = snapshot(items, tmp_path)
    by_id = {a["id"]: a for a in st["asks"]}
    assert {i: a["muted"] for i, a in by_id.items()} == {"aaa00001": False, "aaa00002": True, "aaa00003": True,
                                                         "aaa00004": False}
    assert [a["id"] for a in st["asks"]][-2:] == ["aaa00002", "aaa00003"]       # muted last, ranks stay 1..n
    assert [a["rank"] for a in st["asks"]] == [1, 2, 3, 4]
    rows = {p["id"]: p for p in st["products"]}
    assert (rows["atlas"]["waiting"], rows["atlas"]["muted"]) == (1, 0)
    assert (rows["lens"]["waiting"], rows["lens"]["muted"]) == (0, 2)
    assert (rows["cellar"]["waiting"], rows["cellar"]["muted"]) == (1, 0)
    assert st["totals"]["questions"] == 2
    assert st["version"] == 3


def test_state_brief_ignores_muted_asks(tmp_path):
    register(lens={"stage": "parked"})
    st = snapshot([ask("aaa00001", "lens")], tmp_path)
    assert st["asks"][0]["muted"] is True
    assert st["brief"]["line"] == "Nothing waits on you." and st["totals"]["questions"] == 0
    assert state.render_text(st, NOW).splitlines()[1].startswith("0 waiting,")
    assert "aaa00001" not in state.render_text(st, NOW)
    st = snapshot([ask("aaa00001", "lens"), ask("aaa00002", "atlas")], tmp_path)
    assert st["brief"]["line"] == "1 question waits for you, the first one in atlas."
