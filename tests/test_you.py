"""`teyla you` (docs/YOU.md): quotes, insights, postcard, delegation. Fixtures are generic, nothing leaves the machine,
and the model is a fake. Cyrillic is written as escapes."""
from __future__ import annotations

import datetime as dt
import json
import stat
import subprocess
import types

import pytest

from teyla import chores, config, corrections, state, you

NOW = dt.datetime(2026, 11, 4, 12, 0).timestamp()
TODAY = dt.date(2026, 11, 4)
RU_LINE = "\u0425\u043e\u0447\u0443 \u0447\u0442\u043e\u0431\u044b \u0432\u0441\u0451 \u0431\u044b\u043b\u043e \u043f\u0440\u043e\u0441\u0442\u043e \u0438 \u0431\u044b\u0441\u0442\u0440\u043e \u0434\u043b\u044f \u0432\u0441\u0435\u0445"


class NoRules:
    """A leak-rule stand-in that finds nothing; `Hits` finds one word."""
    def hits(self, line):
        return []


class Hits:
    def __init__(self, word):
        self.word = word

    def hits(self, line):
        return [self.word] if self.word in line else []


REAL_SCREEN = you.Screen


def screen(rules=None, terms=True):
    return REAL_SCREEN(rules or NoRules(), terms_loaded=terms)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home" / ".teyla"
    h.mkdir(parents=True)
    code = tmp_path / "code"
    code.mkdir()
    monkeypatch.setattr(config, "HOME", tmp_path / "home")
    monkeypatch.setattr(config, "TEYLA_DIR", h)
    monkeypatch.setattr(config, "CONFIG_PATH", h / "config.toml")
    (h / "config.toml").write_text(f'code_root = "{code}"\n')
    monkeypatch.setenv("TEYLA_HOME", str(h))
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    return h


def write_intent(home, product, entries):
    d = home / "intent"
    d.mkdir(exist_ok=True)
    body = ""
    for date, harness, text in entries:
        body += f"## {date} · {harness} · session s1\n\n{text}\n\n"
    (d / f"{product}.md").write_text(body)


def prompt(text, day="2026-11-01", product="app-a", hour=10):
    return dict(text=text, day=day, hour=hour, product=product, harness="claude", chars=len(text))


# --- what counts as yours ---------------------------------------------------------------

@pytest.mark.parametrize("text,machine", [
    ("<realtime_delegation> do the thing", True),
    ("<cross-session-message> hello", True),
    ("Task (from the session above): fix it", True),
    ("A normal prompt\nwith an app-generated request inside", True),
    ("I want the settings screen to stay calm and obvious", False),
])
def test_machine_written(text, machine):
    assert you.machine_written(text) is machine


def test_owner_prompts_skip_machine_entries_and_the_cut_marker(home):
    long_tail = " filler" * 80
    write_intent(home, "app-a", [
        ("2026-11-01 23:15", "claude", "I want one calm settings screen" + long_tail + "\n[900 more characters not kept]"),
        ("2026-11-02 09:00", "claude", "<send_user_message_question_reply> yes" + long_tail),
    ])
    got = you.owner_prompts()
    assert len(got) == 1
    assert got[0]["product"] == "app-a" and got[0]["day"] == "2026-11-01" and got[0]["hour"] == 23
    assert "more characters not kept" not in got[0]["text"]


# --- the screen ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,ok", [
    ("Stop adding settings nobody asked for here", True),
    ("Read https://example.com/page before you start", False),
    ("Call me on +1 415 555 0100 about the plan", False),
    ("Ship it from 221 Baker Street tomorrow morning", False),
    ("Fix the `build` step so it never fails again", False),
    ("Check my passport status before we ship it", False),
    ("The salary question should never block the sprint", False),
    ("See ~/notes/plan.md for what I want here", False),
])
def test_screen_rules(line, ok):
    assert screen().ok(line) is ok


def test_screen_defers_to_the_leak_rules_first():
    assert screen(Hits("Acme")).ok("I want Acme to stop sending these mails") is False
    assert screen(Hits("Acme")).ok("I want this to stop sending these mails") is True


def test_screen_blocks_a_russian_sensitive_word():
    assert screen().ok(RU_LINE + " \u043f\u0430\u0441\u043f\u043e\u0440\u0442") is False
    assert screen().ok(RU_LINE) is True


# --- quotes ---------------------------------------------------------------------------------

def test_candidates_are_verbatim_lines_in_range_best_first():
    good = "I want every screen to do one thing and say it in few words"
    weak = "this is just an ordinary note about the weather today ok"
    text = f"{good}\n- {weak}\nshort\n{'x' * 200}\nWhy is this so slow and what should we do about it now?"
    got = you.candidates([prompt(text)], screen())
    assert [c["text"] for c in got][0] == good
    assert all(you.QUOTE_MIN <= len(c["text"]) <= you.QUOTE_MAX for c in got)
    assert not any(c["text"].endswith("?") and c["score"] > 0 for c in got[:1])
    assert you.candidates([prompt(text)], screen()) == got          # deterministic


def test_candidates_split_a_long_line_into_sentences_and_screen_them():
    text = ("Nothing to say here at all, really, just context. I never want a settings screen with ten toggles. "
            "Also read https://example.com/a for the details of the thing we need.")
    got = [c["text"] for c in you.candidates([prompt(text)], screen())]
    assert got == ["I never want a settings screen with ten toggles."]


def test_candidates_skip_lead_ins_and_the_same_line_with_other_punctuation():
    a = "I want every screen to do one thing and say it in few words"
    text = f"{a}.\n\"{a}\"\nI want you to update all the strings that say this:\n"
    got = [c["text"] for c in you.candidates([prompt(text)], screen())]
    assert got == [a + "."]


def test_candidates_drop_duplicates_and_keep_the_pool_bounded():
    lines = [f"I want feature number {i} to ship before the end of the week for sure" for i in range(60)]
    got = you.candidates([prompt("\n".join(lines)), prompt(lines[0], day="2026-11-02")], screen())
    assert len(got) == you.POOL and len({c["text"] for c in got}) == you.POOL


def test_pick_is_stable_within_a_day_and_an_order_wins():
    pool = [dict(text=f"I want thing {i} to be simple and fast", day="2026-11-01", product="p", score=3) for i in range(10)]
    assert you.pick_quote(pool, "2026-11-04") == you.pick_quote(pool, "2026-11-04")
    assert you.pick_quote([], "2026-11-04") is None
    assert you.pick_quote(pool, "2026-11-04", order=[7, 2]) is pool[7]


def test_rank_is_off_by_default_and_in_safe_mode(home):
    assert you.rank_enabled() is False
    (home / "config.toml").write_text('[you]\nrank = true\n')
    assert you.rank_enabled() is True
    (home / "config.toml").write_text('[you]\nrank = true\n[safe]\nenabled = true\n')
    assert you.rank_enabled() is False


def fake_claude(monkeypatch, reply, code=0):
    seen = {}

    def run(cmd, text, timeout=0):
        seen.update(cmd=cmd, text=text)
        return code, json.dumps({"result": reply, "total_cost_usd": 0.001, "duration_ms": 5})

    monkeypatch.setattr(state, "_run_claude", run)
    return seen


def test_rank_with_model_sends_numbered_lines_and_validates_the_reply(monkeypatch):
    pool = [dict(text=f"I want thing {i} to be simple and fast", day="d", product="p", score=1) for i in range(6)]
    seen = fake_claude(monkeypatch, '{"order": [4, 1, 0]}')
    assert you.rank_with_model(pool) == [4, 1, 0]
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == you.RANK_MODEL
    assert seen["text"].splitlines()[0] == "0: " + pool[0]["text"] and len(seen["text"].splitlines()) == 6
    for bad in ('{"order": [9]}', '{"order": [1, 1]}', '{"order": []}', '{"order": ["a"]}', '{"order": [true]}', '{"x": 1}', "not json"):
        fake_claude(monkeypatch, bad)
        assert you.rank_with_model(pool) is None
    fake_claude(monkeypatch, '{"order": [1]}', code=1)
    assert you.rank_with_model(pool) is None


# --- insights -------------------------------------------------------------------------------

def test_insights_count_what_intent_kept_and_say_so():
    items = [prompt("Nothing here " * 40, day=(TODAY - dt.timedelta(days=d)).isoformat(), hour=h, product=p)
             for d, h, p in [(1, 23, "app-a"), (2, 2, "app-a"), (3, 14, "app-b"), (4, 9, "app-a")]]
    items.append(prompt(RU_LINE * 12, day="2026-11-02", hour=11, product="app-b"))
    rows = {r["id"]: r for r in you.insights(items, TODAY)}
    assert rows["per_week"]["value"] == round(5 / 8, 1) and "400" in rows["per_week"]["detail"]
    assert rows["night_share"]["value"] == 40 and "2 of 5" in rows["night_share"]["detail"]
    assert rows["language"]["value"].startswith("en 80%")
    assert rows["products"]["value"].startswith("app-a 3")
    assert rows["median_length"]["value"] > 0
    assert rows["repeats_after_rule"]["value"] is None and rows["repeats_after_rule"]["detail"] == "not computed"


def test_insights_are_empty_not_zero_without_prompts():
    rows = {r["id"]: r for r in you.insights([], TODAY)}
    assert rows["per_week"]["value"] is None and rows["night_share"]["value"] is None and rows["language"]["value"] is None


def test_themes_need_three_distinct_prompts():
    items = [prompt(f"the onboarding flow needs work number {i}") for i in range(3)] + [prompt("the pricing page is fine")]
    got = you.themes(items)
    assert {t["theme"] for t in got} >= {"onboarding"} and all(t["prompts"] >= 3 for t in got)
    assert not any(t["theme"] == "pricing" for t in got)


# --- repeats after a rule -------------------------------------------------------------------

def make_repo(root, name, rule_text, created):
    repo = root / name
    (repo / ".git").mkdir(parents=True)
    d = repo / ".claude" / "rules"
    d.mkdir(parents=True)
    (d / "style.md").write_text(f"---\ncreated: {created}\n---\n\n- {rule_text}\n")
    return repo


def test_contradictions_count_corrections_after_the_rule(tmp_path, monkeypatch):
    root = tmp_path / "code"
    repo = make_repo(root, "app-a", "Never merge a pull request without a review", "2026-10-01")
    recs = [dict(ts="2026-09-20T10:00:00", text="never merge a pull request without a review", source="correct"),   # before the rule
            dict(ts="2026-10-05T10:00:00", text="you merged a pull request without a review again", source="correct"),
            dict(ts="2026-10-09T10:00:00", text="stop, merge a pull request only after a review", source="hook"),
            dict(ts="2026-10-10T10:00:00", text="the colour of the button is wrong", source="correct")]
    monkeypatch.setattr(corrections, "records", lambda r, cfg=None: recs if r == repo else [])
    got = you.contradictions(root)
    assert got["count"] == 1 and got["repeats"] == 2 and got["by_hand"] == 1
    assert got["rules"][0]["written"] == "2026-10-01" and got["rules"][0]["last"] == "2026-10-09"
    assert "conflicting rules are not checked" in got["detail"]


def test_one_repeat_is_not_a_contradiction(tmp_path, monkeypatch):
    root = tmp_path / "code"
    repo = make_repo(root, "app-a", "Never merge a pull request without a review", "2026-10-01")
    monkeypatch.setattr(corrections, "records", lambda r, cfg=None: [dict(ts="2026-10-05T10:00:00", text="merged a pull request without a review")])
    got = you.contradictions(root)
    assert got["count"] == 0 and got["rules"] == [] and "no rule has two" in got["detail"]


# --- the postcard ---------------------------------------------------------------------------

def git_repo(path, day):
    path.mkdir(parents=True)
    env = {"GIT_COMMITTER_DATE": f"{day}T12:00:00", "GIT_AUTHOR_DATE": f"{day}T12:00:00", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "m"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@example.com", "tag", "v1.0.0"], check=True, env=env)


def test_postcard_pairs_an_old_line_with_git_facts(tmp_path):
    root = tmp_path / "code"
    git_repo(root / "app-a", "2026-10-20")
    old = prompt("I want the first screen to do one thing and say it in few words", day="2026-10-01", product="app-a")
    card = you.postcard([old], TODAY, screen(), root)
    assert card["then"]["text"].startswith("I want the first screen") and card["then"]["day"] == "2026-10-01"
    assert card["now"]["commits"] == 1 and card["now"]["tags"] == 1 and card["now"]["latest_tag"] == "v1.0.0"
    assert card["now"]["source"] == "git" and card["week"] == "2026-W45"


def test_postcard_is_skipped_without_checkable_facts(tmp_path):
    root = tmp_path / "code"
    git_repo(root / "app-a", "2026-09-01")                       # no commit after the prompt
    old = prompt("I want the first screen to do one thing and say it in few words", day="2026-10-01", product="app-a")
    recent = prompt("I want the first screen to do one thing and say it in few words", day="2026-11-01", product="app-a")
    other = prompt("I want the first screen to do one thing and say it in few words", day="2026-10-01", product="no-repo")
    assert you.postcard([old, recent, other], TODAY, screen(), root) is None


# --- delegation -----------------------------------------------------------------------------

def ask(title, question, product="app-a", day="2026-10-30"):
    when = dt.datetime.fromisoformat(day + "T10:00:00").timestamp()
    return types.SimpleNamespace(title=title, question=question, product=product, when=when)


def test_delegation_counts_chores_and_names_the_honest_path():
    items = [ask("Sign in", "Please open developer.apple.com and sign in"),
             ask("Sign in", "Please open developer.apple.com and sign in again", product="app-b", day="2026-11-02"),
             ask("Pick", "Which option do you want?")]
    corr = [dict(text="Add the DNS record for the new domain", day="2026-10-15", product="app-a")]
    rows = {r["chore"]: r for r in you.delegation(items, corr, TODAY)}
    assert set(rows) == {"developer_apple", "dns"}
    dev = rows["developer_apple"]
    assert dev["count"] == 2 and dev["last"] == "2026-11-02" and dev["products"] == ["app-a", "app-b"] and dev["asks"] == 2
    assert "Account Holder" in dev["path"] and "2FA" in dev["who"]
    assert dev["status"] == "open" and dev["verified"] == "not verified on this machine"
    assert rows["dns"]["corrections"] == 1


def test_chore_marks_set_status_and_the_tried_date(home):
    assert you.mark_chore("dns", "done") == "dns: done"
    you.mark_chore("dns", "tried", today=dt.date(2026, 11, 3))
    row = you.delegation([], [dict(text="Add the DNS record", day="2026-11-01", product="p")], TODAY)[0]
    assert row["status"] == "done" and row["verified"] == "tried on this machine 2026-11-03"
    you.mark_chore("dns", "untried")
    assert "tried" not in you.load_chore_marks()["dns"]
    assert stat.S_IMODE((home / "you-chores.json").stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        you.mark_chore("nope", "done")
    with pytest.raises(ValueError):
        you.mark_chore("dns", "later")


def test_every_chore_row_has_a_path_and_a_human_part():
    assert all(c.path and c.who for c in chores.PATHS)


# --- build, store, command ------------------------------------------------------------------

def seed(home):
    long_tail = " filler words to pass the length bar" * 14
    write_intent(home, "app-a", [
        ("2026-10-01 23:15", "claude", "I want every screen to do one thing and say it in few words." + long_tail),
        ("2026-10-02 10:00", "claude", "<cross-session-message> I want a secret machine line here to leak" + long_tail),
    ])


def test_build_stores_a_private_file_and_keeps_the_day_stable(home, tmp_path):
    seed(home)
    rep = you.build(NOW, screen=screen(), ask_items=[], root=tmp_path / "code")
    you.save(rep)
    assert stat.S_IMODE((home / "you.json").stat().st_mode) == 0o600
    q = rep["quote_of_the_day"]
    assert q["text"] == "I want every screen to do one thing and say it in few words." and q["for"] == "2026-11-04"
    assert not any("secret machine" in c["text"] for c in rep["quotes"])
    assert rep["counts"]["prompts"] == 1 and rep["notes"] == []
    again = you.build(NOW + 60, screen=screen(), ask_items=[], root=tmp_path / "code", prev=json.loads((home / "you.json").read_text()))
    assert again["quote_of_the_day"] == q


def test_build_says_when_no_private_terms_were_loaded(home, tmp_path):
    seed(home)
    rep = you.build(NOW, screen=screen(terms=False), ask_items=[], root=tmp_path / "code")
    assert rep["notes"] and "private-terms" in rep["notes"][0]


def test_get_reads_the_cache_within_the_day_and_refresh_rebuilds(home, tmp_path, monkeypatch):
    seed(home)
    monkeypatch.setattr(you, "Screen", lambda: screen())
    monkeypatch.setattr(you, "_collect_asks", lambda: [])
    first = you.get(NOW)
    (home / "intent" / "app-a.md").unlink()
    assert you.get(NOW + 600)["generated"] == first["generated"]
    assert you.get(NOW + 600, refresh=True)["counts"]["prompts"] == 0


def test_the_part_for_the_console_carries_every_section(home, tmp_path, monkeypatch):
    seed(home)
    monkeypatch.setattr(you, "Screen", lambda: screen())
    monkeypatch.setattr(you, "_collect_asks", lambda: [])
    part = you.console_part(NOW)
    assert part["local_only"] is True
    assert {"quote_of_the_day", "quotes", "insights", "postcard", "delegation", "contradictions", "counts", "notes"} <= set(part)
    assert part["contradictions"]["count"] is not None


def test_render_and_command(home, tmp_path, monkeypatch, capsys):
    seed(home)
    monkeypatch.setattr(you, "Screen", lambda: screen())
    monkeypatch.setattr(you, "_collect_asks", lambda: [])
    args = types.SimpleNamespace(words=[], json=False, refresh=True)
    assert you.cmd_you(args) == 0
    out = capsys.readouterr().out
    assert "Quote of the day" in out and "Delegation" in out and "conflicting rules are not checked" in out
    args.json = True
    assert you.cmd_you(args) == 0
    assert json.loads(capsys.readouterr().out)["version"] == you.VERSION
    assert you.cmd_you(types.SimpleNamespace(words=["chore", "dns", "done"], json=False, refresh=False)) == 0
    assert "dns: done" in capsys.readouterr().out
    assert you.cmd_you(types.SimpleNamespace(words=["chore", "dns"], json=False, refresh=False)) == 2
    assert you.cmd_you(types.SimpleNamespace(words=["chore", "nope", "done"], json=False, refresh=False)) == 2
    assert you.cmd_you(types.SimpleNamespace(words=["other"], json=False, refresh=False)) == 2
