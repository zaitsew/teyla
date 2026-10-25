"""`teyla start`: the diagnosis, the seven offers with their savings, and the apply / undo commands.
Every machine here is a fake HOME with invented sessions; the real ~/.claude and ~/.codex are never read."""
from __future__ import annotations

import builtins
import json
import pathlib

import pytest

from teyla import asks, changes, cli, diagnose, offers, pricing, start


@pytest.fixture(autouse=True)
def _list_prices(monkeypatch, tmp_path):
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")


@pytest.fixture(autouse=True)
def _no_real_routine(monkeypatch):
    """O7 writes launchd jobs; no test here may. Tests that apply it see this stub."""
    from teyla import routine_install
    calls = []
    monkeypatch.setattr(routine_install, "install", lambda *a, **k: calls.append(1) or ["stub: routine installed"])
    return calls


OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SETTINGS = '{\n  "model": "opus",\n  "theme": "dark"\n}\n'


@pytest.fixture
def machine(fake_home):
    """A Claude Code machine: a 320k-context session, a 280k one, and five subagent calls."""
    h = fake_home
    (h.home / ".claude").mkdir(exist_ok=True)
    h.settings.write_text(SETTINGS)
    h.session("s1aaaa", [(OPUS, h.usage(cread=320_000, out=100))] * 40)            # past the compaction point
    h.session("s2bbbb", [(OPUS, h.usage(cread=280_000, out=100))] * 40)            # past 250k, under 300k
    big = h.usage(cread=50_000, out=1_000_000)                                      # peak context 50k
    h.subagent("s1aaaa", "a1", OPUS, big, tools=("Edit",))                          # default model, edits files
    h.subagent("s1aaaa", "a2", OPUS, big, explicit="opus")                          # named its model, read-only
    h.subagent("s1aaaa", "a3", SONNET, big, kind="Explore")                         # default, read-only, Sonnet
    (h.home / ".claude" / "agents").mkdir()
    (h.home / ".claude" / "agents" / "pinned.md").write_text("---\nname: pinned\nmodel: opus\n---\nbody\n")
    h.subagent("s1aaaa", "a4", OPUS, big, kind="pinned", tools=("Write",))          # its definition pins Opus
    return h


def _offers(h, days=30, **kw):
    inp = diagnose.collect(days)
    return {o.id: o for o in offers.build(days, inp, home=h.home, **kw)}, inp


# --- the diagnosis -------------------------------------------------------------------------------

def test_cost_parts_add_up_to_cost_usd():
    u = {"input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 300_000,
         "cache_creation_input_tokens": 50_000, "cache_creation_1h_input_tokens": 20_000}
    for model in (OPUS, SONNET, "claude-haiku-5-5", "gpt-6.1-sol"):
        assert sum(pricing.cost_parts(model, u).values()) == pytest.approx(pricing.cost_usd(model, u))
    assert pricing.cost_parts("no-such-model", u) is None


def test_the_diagnosis_numbers(machine):
    d = diagnose.diagnose(30, with_asks=False)
    big = 50_000 * 0.2 / 1e6 + 1_000_000 * 20 / 1e6                 # an Opus subagent: cache read plus output
    main = 40 * (320_000 * 0.2 + 100 * 20) / 1e6 + 40 * (280_000 * 0.2 + 100 * 20) / 1e6
    sub_opus, sub_sonnet = 3 * big, 50_000 * 0.2 / 1e6 + 1_000_000 * 10 / 1e6
    assert d["empty"] is False and d["sessions"] == 2 and d["days"] == 30
    assert d["total_usd"] == pytest.approx(main + sub_opus + sub_sonnet, abs=0.01)
    assert d["by_harness"] == {"claude-code": d["total_usd"]}
    assert set(d["by_model"]) == {OPUS, SONNET}
    cache_read = 40 * 320_000 * 0.2 / 1e6 + 40 * 280_000 * 0.2 / 1e6 + 4 * 50_000 * 0.2 / 1e6
    assert d["cache_read_usd"] == pytest.approx(cache_read, abs=0.01)
    assert d["context_share"] == pytest.approx(cache_read / d["total_usd"], abs=0.001)
    assert d["long_sessions"] == 2 and d["long_context_tokens"] == 250_000      # 280k counts here, not for O1
    assert d["subagent_usd"] == pytest.approx(sub_opus + sub_sonnet, abs=0.01)
    assert d["subagent_opus_share"] == pytest.approx(sub_opus / (sub_opus + sub_sonnet), abs=0.001)
    assert d["active_days"] >= 1 and "subscription" in d["note"]


def test_waiting_asks_counts_only_open_items(machine, monkeypatch):
    items = [asks.Ask(id=str(n), kind="question", product="demo", title="t", question="q?", context="", options=[],
                      when=1.0, archived=False, link="", pr="", harness="claude-code", status=st)
             for n, st in enumerate(["open", "open", "done", "snoozed"])]
    monkeypatch.setattr(asks, "collect", lambda **kw: items)
    assert diagnose.diagnose(30)["waiting_asks"] == 2


def test_a_machine_with_no_sessions_is_empty(fake_home):
    d = diagnose.diagnose(30)
    assert d["empty"] is True and d["total_usd"] == 0 and d["waiting_asks"] == 0


def test_long_message_runs_split_where_the_context_drops(fake_home):
    msgs = [(OPUS, fake_home.usage(cread=c, out=1)) for c in (320_000, 330_000, 100_000, 340_000)]
    fake_home.session("runs00", msgs)
    from teyla.adapters import claude_code
    s = claude_code.parse(str(fake_home.projects / "-work-demo" / "runs00.jsonl"))
    assert [ctx for _m, ctx, _r, _d in s.long_msgs] == [320_000, 330_000, 340_000]
    runs = [r for _m, _c, r, _d in s.long_msgs]
    assert runs[0] == runs[1] != runs[2]


# --- the savings -----------------------------------------------------------------------------------

def test_o1_prices_only_turns_past_the_compaction_point(machine):
    o, inp = _offers(machine)
    # 40 turns at 320k: each would re-read 250k fewer cached tokens ($0.20 per million); one compaction costs
    # 300k read + 10k summary + 50k one-hour write = $0.66 on Opus 5.5. The 280k session adds nothing.
    net = 40 * 250_000 * 0.2 / 1e6 - (300_000 * 0.2 + 10_000 * 20 + 50_000 * 8) / 1e6
    assert net == pytest.approx(1.34)
    assert o["O1"].saving_usd_month == {"low": round(net * 0.5, 2), "high": round(net, 2)}
    assert "40 turns in 1 sessions" in o["O1"].basis and o["O1"].benefit is None
    only_280k = [s for s in inp.sessions if s.sid == "s2bbbb"]
    assert offers.o1_net(only_280k) == (0.0, 0, 0)


def test_o1_scales_to_a_month_for_other_windows(machine):
    o30, _ = _offers(machine, 30)
    o15, _ = _offers(machine, 15)
    assert o15["O1"].saving_usd_month["high"] == pytest.approx(o30["O1"].saving_usd_month["high"] * 2, abs=0.01)
    o60, _ = _offers(machine, 60)                                    # $0.67 a month: under the $1 floor, so no figure
    assert o60["O1"].saving_usd_month is None


def test_o1_without_a_saving_says_what_it_brings(fake_home):
    (fake_home.home / ".claude").mkdir(exist_ok=True)
    fake_home.session("short0", [(OPUS, fake_home.usage(cread=100_000, out=10))] * 5)
    o, _ = _offers(fake_home)
    assert o["O1"].applies and o["O1"].saving_usd_month is None and o["O1"].benefit
    assert "saves nothing today" in o["O1"].basis


def test_o2_counts_default_opus_calls_only(machine):
    o, _ = _offers(machine)
    # a1 ran on Opus and named no model: the same tokens at Sonnet are $10 cheaper. a2 named "opus", a3 ran on
    # Sonnet already, a4's definition pins Opus: the default changes none of them.
    saving = (50_000 * 0.2 + 1_000_000 * 20 - 50_000 * 0.2 - 1_000_000 * 10) / 1e6
    assert saving == pytest.approx(10.0)
    assert o["O2"].saving_usd_month == {"low": 7.0, "high": 10.0}
    assert "1 of 4 subagent calls" in o["O2"].basis
    assert o["O2"].change["key_path"] == ["env", "CLAUDE_CODE_SUBAGENT_MODEL"] and o["O2"].change["new"] == "sonnet"


def test_o2_leaves_out_a_call_whose_meta_file_is_missing(machine):
    (machine.projects / "-work-demo" / "s1aaaa" / "subagents" / "agent-a1.meta.json").unlink()
    o, _ = _offers(machine)
    assert o["O2"].saving_usd_month is None


def test_o3_prices_read_only_calls_the_default_does_not_cover(machine):
    o, _ = _offers(machine)
    haiku = (50_000 * 0.01 + 1_000_000 * 0.5) / 1e6
    a2 = (50_000 * 0.2 + 1_000_000 * 20) / 1e6 - haiku              # Opus, named its model, read-only
    a3 = (50_000 * 0.2 + 1_000_000 * 10) / 1e6 - haiku              # Sonnet, read-only
    assert o["O3"].saving_usd_month == {"low": round((a2 + a3) * 0.3, 2), "high": round((a2 + a3) * 0.6, 2)}
    assert "2 read-only subagent calls" in o["O3"].basis            # a1 and a4 write; O2 covers a1


def test_o3_leaves_out_prompts_on_haikus_dearer_card(machine):
    machine.subagent("s1aaaa", "a5", OPUS, machine.usage(cread=150_000, out=1_000_000), explicit="opus")
    o, _ = _offers(machine)
    assert "2 read-only subagent calls" in o["O3"].basis


def test_o4_has_a_benefit_not_a_dollar_figure(machine):
    (machine.home / ".codex").mkdir()
    (machine.home / ".codex" / "config.toml").write_text('model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n')
    machine.codex_session("cx01", "gpt-6.1-sol", input_tokens=5_000_000, output_tokens=1_000_000)
    o, _ = _offers(machine)
    assert o["O4"].applies and o["O4"].saving_usd_month is None
    assert "Codex output cost $10 in the window" in o["O4"].benefit
    assert o["O4"].change["new"] == "medium" and o["O4"].change["old"] == "high"


def test_o5_o6_o7_have_no_dollar_figure(machine):
    (machine.home / ".codex").mkdir()
    o, _ = _offers(machine)
    for oid in ("O5", "O6", "O7"):
        assert o[oid].saving_usd_month is None and o[oid].benefit
    assert [x for x in o] == [f"O{n}" for n in range(1, 8)]


# --- when an offer does not apply ---------------------------------------------------------------------

def test_offers_that_are_already_in_place_do_not_apply(machine):
    machine.settings.write_text('{\n  "autoCompactWindow": 500000,\n  "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}\n}\n')
    (machine.home / ".claude" / "agents" / "scout.md").write_text("mine\n")
    (machine.home / ".codex").mkdir()
    (machine.home / ".codex" / "config.toml").write_text('model_reasoning_effort = "medium"\n')
    o, _ = _offers(machine)
    assert not o["O1"].applies and "already 500000" in o["O1"].reason
    assert not o["O2"].applies and "already haiku" in o["O2"].reason
    assert not o["O3"].applies and "already exists" in o["O3"].reason
    assert not o["O4"].applies and "already medium" in o["O4"].reason


def test_offers_for_a_harness_that_is_not_installed_do_not_apply(fake_home):
    import shutil
    shutil.rmtree(fake_home.home / ".claude")
    fake_home.codex_session("cx02", "gpt-6.1-sol", 1_000_000, 100_000)
    o, _ = _offers(fake_home)
    for oid in ("O1", "O2", "O3"):
        assert not o[oid].applies and o[oid].reason == "Claude Code is not installed"
    assert not o["O4"].applies and "does not exist" in o["O4"].reason


def test_o4_needs_a_high_effort_and_a_codex_share_that_matters(machine):
    (machine.home / ".codex").mkdir()
    (machine.home / ".codex" / "config.toml").write_text('model_reasoning_effort = "high"\n')
    o, _ = _offers(machine)                                          # no Codex sessions at all
    assert not o["O4"].applies and "small part" in o["O4"].reason
    (machine.home / ".codex" / "config.toml").write_text('model = "x"\n')
    o, _ = _offers(machine)
    assert not o["O4"].applies and "no model_reasoning_effort" in o["O4"].reason


def test_a_settings_file_that_does_not_parse_blocks_o1_and_o2(machine):
    machine.settings.write_text("{not json")
    o, _ = _offers(machine)
    assert not o["O1"].applies and "not valid JSON" in o["O1"].reason and not o["O2"].applies


# --- applying and undoing --------------------------------------------------------------------------------

def _run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_apply_o1_o2_o3_and_undo_all_of_them_byte_for_byte(machine, capsys):
    before = machine.settings.read_bytes()
    code, out, err = _run(["apply", "O1", "O2", "O3", "--yes"], capsys)
    assert code == 0, err
    s = json.loads(machine.settings.read_text())
    assert s["autoCompactWindow"] == 335000 and s["env"] == {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
    scout = machine.home / ".claude" / "agents" / "scout.md"
    assert "model: haiku" in scout.read_text() and "tools: Read, Grep, Glob, Bash" in scout.read_text()
    assert "teyla undo" in out
    code, out, _ = _run(["changes"], capsys)
    assert out.count("[active]") == 3 and "autoCompactWindow" in out
    code, out, err = _run(["undo", "O2", "O1", "O3"], capsys)
    assert code == 0, err
    assert machine.settings.read_bytes() == before and not scout.exists()
    assert _run(["changes"], capsys)[1].count("[undone") == 3
    assert _run(["undo", "O1"], capsys)[0] == 1                       # nothing left to undo


def test_apply_dry_writes_nothing(machine, capsys):
    snap = machine.tree()
    code, out, _ = _run(["apply", "O1", "--dry"], capsys)
    assert code == 0 and "autoCompactWindow" in out and machine.tree() == snap


def test_apply_without_yes_and_without_a_terminal_refuses_instead_of_asking(machine, capsys, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a: pytest.fail("a prompt was shown without a terminal"))
    snap = machine.tree()
    code, _out, err = _run(["apply", "O1"], capsys)
    assert code == 1 and "--yes" in err and machine.tree() == snap


def test_apply_an_unknown_offer_is_a_usage_error(machine, capsys):
    assert _run(["apply", "O9", "--yes"], capsys)[0] == 2


def test_apply_o3_never_overwrites_a_scout_the_user_wrote(machine, capsys):
    scout = machine.home / ".claude" / "agents" / "scout.md"
    scout.write_text("my own scout\n")
    code, out, _ = _run(["apply", "O3", "--yes"], capsys)
    assert code == 0 and "already exists" in out and scout.read_text() == "my own scout\n"
    assert changes.changes() == []


def test_apply_o4_edits_one_toml_line_and_undo_restores_it(machine, capsys):
    cfg = machine.home / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('# mine\nmodel = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"  # slow\n\n[tui]\nnotify = true\n')
    machine.codex_session("cx03", "gpt-6.1-sol", 5_000_000, 1_000_000)
    code, _out, err = _run(["apply", "O4", "--yes"], capsys)
    assert code == 0, err
    assert cfg.read_text() == '# mine\nmodel = "gpt-6.1-sol"\nmodel_reasoning_effort = "medium"  # slow\n\n[tui]\nnotify = true\n'
    assert _run(["undo", "O4"], capsys)[0] == 0
    assert 'model_reasoning_effort = "high"  # slow' in cfg.read_text() and "notify = true" in cfg.read_text()


def test_undo_after_the_key_changed_stops_and_force_reverts(machine, capsys):
    _run(["apply", "O1", "--yes"], capsys)
    machine.settings.write_text(machine.settings.read_text().replace("335000", "420000"))
    code, _out, err = _run(["undo", "O1"], capsys)
    assert code == 1 and "420000" in err and "335000" in err
    assert json.loads(machine.settings.read_text())["autoCompactWindow"] == 420000
    code, _out, err = _run(["undo", "O1", "--force"], capsys)
    assert code == 0, err
    assert "autoCompactWindow" not in json.loads(machine.settings.read_text())


def test_apply_a_file_that_does_not_parse_changes_nothing(machine, capsys):
    machine.settings.write_text("{oops")
    code, _out, err = _run(["apply", "O1", "--yes"], capsys)
    assert machine.settings.read_text() == "{oops"
    assert changes.changes() == []


def test_apply_o5_and_o6_run_the_syncs_and_log_them_as_commands(machine, capsys):
    (machine.home / ".codex").mkdir()
    (machine.home / ".agents").mkdir()
    (machine.home / ".agents" / "POLICY.md").write_text("# policy\n\n## 1. rules\n\ntext\n")
    code, out, err = _run(["apply", "O5", "O6", "--yes"], capsys)
    assert code == 0, err
    assert (machine.home / ".codex" / "hooks.json").exists()
    rows = changes.changes()
    assert [(r["offer"], r["kind"], r["command"]) for r in rows] == [
        ("O5", "command", "teyla policy sync"), ("O6", "command", "teyla harness sync")]
    assert "teyla uninstall" in out and "teyla undo O5-" not in out
    assert "teyla policy sync" in _run(["changes"], capsys)[1]


def test_undo_of_a_command_prints_the_uninstall_command_and_exits_1(machine, capsys):
    (machine.home / ".codex").mkdir()
    assert _run(["apply", "O6", "--yes"], capsys)[0] == 0
    hooks = (machine.home / ".codex" / "hooks.json").read_bytes()
    code, out, err = _run(["undo", "O6"], capsys)
    assert code == 1
    assert "Teyla's sync owns these files; its uninstall removes them" in err and "teyla uninstall" in err
    assert (machine.home / ".codex" / "hooks.json").read_bytes() == hooks      # nothing was touched
    assert changes.changes()[0]["undone"] is None


def test_o6_says_the_sync_replaces_teyla_hook_files_including_edits(machine):
    o = _offers(machine)[0]["O6"]
    assert "replaces Teyla's own hook files, including any edits made to them" in o.tradeoff
    for oid in ("O5", "O6", "O7"):
        assert "teyla uninstall" in _offers(machine)[0][oid].undo


def test_apply_o7_runs_the_routine_install_and_logs_the_command(machine, capsys, _no_real_routine, monkeypatch):
    monkeypatch.setattr(offers.sys, "platform", "darwin")
    code, out, _ = _run(["apply", "O7", "--yes"], capsys)
    assert code == 0 and _no_real_routine == [1]
    assert changes.changes()[0]["command"] == "teyla routine install"


# --- the commands ----------------------------------------------------------------------------------------

def test_start_agent_writes_nothing_and_prints_the_json_shape(machine, capsys):
    snap = machine.tree()
    code, out, _ = _run(["start", "--agent"], capsys)
    assert code == 0 and machine.tree() == snap
    d = json.loads(out)
    assert set(d) == {"summary_text", "diagnosis", "offers"}
    assert len(d["summary_text"].splitlines()) <= 12
    assert [o["id"] for o in d["offers"]] == [f"O{n}" for n in range(1, 8)]
    for o in d["offers"]:
        assert {"id", "title", "change", "saving_usd_month", "basis", "benefit", "tradeoff", "undo", "applies"} <= set(o)
    assert d["diagnosis"]["total_usd"] > 0 and d["diagnosis"]["empty"] is False
    o1 = d["offers"][0]
    assert o1["change"]["file"] == "~/.claude/settings.json" and o1["change"]["key_path"] == ["autoCompactWindow"]
    assert o1["saving_usd_month"] == {"low": 0.67, "high": 1.34}


def test_start_json_is_the_same_payload(machine, capsys):
    a = json.loads(_run(["start", "--agent"], capsys)[1])
    b = json.loads(_run(["start", "--json"], capsys)[1])
    assert a["summary_text"] == b["summary_text"] and a["offers"] == b["offers"]


def test_the_summary_card_is_short_and_numbers_first(machine, capsys):
    d = json.loads(_run(["start", "--agent"], capsys)[1])
    lines = d["summary_text"].splitlines()
    assert lines[0].startswith("Last 30 days: $") and "sessions" in lines[0]
    assert any("re-reading and storing context" in l for l in lines)
    assert any(l.startswith("  O2 Run subagents on Sonnet") for l in lines)
    assert any("List price" in l for l in lines)


def test_start_without_a_terminal_never_prompts(machine, capsys, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *a: pytest.fail("a prompt was shown without a terminal"))
    snap = machine.tree()
    code, out, _ = _run(["start"], capsys)
    assert code == 0 and "teyla apply O1" in out and "Not a terminal" in out
    assert machine.tree() == snap


def test_start_on_an_empty_machine_says_what_to_do(fake_home, capsys):
    code, out, _ = _run(["start"], capsys)
    assert code == 0
    assert out.strip() == ("No agent sessions found yet in ~/.claude or ~/.codex. "
                           "Use Claude Code or Codex for a day, then run `teyla start` again.")
    d = json.loads(_run(["start", "--agent"], capsys)[1])
    assert d["diagnosis"]["empty"] is True and d["summary_text"] == out.strip()


def test_start_yes_applies_every_applicable_offer(machine, capsys, monkeypatch):
    monkeypatch.setattr(offers.sys, "platform", "linux")        # no launchd job here
    code, out, err = _run(["start", "--yes"], capsys)
    assert code == 0, err
    s = json.loads(machine.settings.read_text())
    assert s["autoCompactWindow"] == 335000 and s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "sonnet"
    assert (machine.home / ".claude" / "agents" / "scout.md").exists()
    assert "Changed:" in out and "teyla undo" in out


def _tty(monkeypatch, answers):
    monkeypatch.setattr(start, "_is_tty", lambda: True)
    asked = []
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": asked.append(prompt) or next(it))
    return asked


def test_interactive_explain_then_yes_then_no(machine, capsys, monkeypatch):
    monkeypatch.setattr(offers.sys, "platform", "linux")
    asked = _tty(monkeypatch, ["e", "y", "n", "n"] + ["n"] * 6)
    code, out, _ = _run(["start"], capsys)
    assert code == 0
    assert "[y]es / [n]o / [e]xplain / [q]uit" in asked[0]
    assert "Detail:" not in out and "Claude Code compacts a session about 35k tokens" in out      # [e] printed it once
    assert json.loads(machine.settings.read_text())["autoCompactWindow"] == 335000                  # O1 yes
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in machine.settings.read_text()                         # O2 no
    assert not (machine.home / ".claude" / "agents" / "scout.md").exists()                          # O3 no
    assert "Undo any of them: teyla undo O1-" in out


def test_interactive_quit_changes_nothing(machine, capsys, monkeypatch):
    _tty(monkeypatch, ["q"])
    snap = machine.tree()
    code, out, _ = _run(["start"], capsys)
    assert code == 0 and machine.tree() == snap and "Nothing changed." in out


def test_interactive_end_of_input_quits(machine, capsys, monkeypatch):
    monkeypatch.setattr(start, "_is_tty", lambda: True)

    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr(builtins, "input", eof)
    snap = machine.tree()
    assert _run(["start"], capsys)[0] == 0 and machine.tree() == snap


def test_changes_on_a_clean_machine(fake_home, capsys):
    assert _run(["changes"], capsys)[1].strip() == "Teyla has changed nothing on this machine yet."
    assert json.loads(_run(["changes", "--json"], capsys)[1]) == []


# --- the window counts turns, not whole resumed sessions --------------------------------------------

def _resumed(h, old_days=40):
    """One transcript: 120 turns at 320k context `old_days` ago and one turn today."""
    recs = [h._assistant(h.ts(old_days, i), f"old{i}", OPUS, h.usage(cread=320_000, out=100)) for i in range(120)]
    recs.append(h._assistant(h.ts(0, 0), "new0", OPUS, h.usage(cread=10_000, out=100_000)))
    h._write(h.projects / "-work-demo" / "resumed0.jsonl", recs)
    return 10_000 * 0.2 / 1e6 + 100_000 * 20 / 1e6


def test_a_resumed_session_counts_only_the_turns_inside_the_window(fake_home):
    today_cost = _resumed(fake_home)
    d = diagnose.diagnose(1, with_asks=False)
    assert d["total_usd"] == pytest.approx(today_cost, abs=0.01) and d["sessions"] == 1
    assert d["active_days"] == 1 and d["long_sessions"] == 0 and d["long_sessions_usd"] == 0
    assert d["by_harness"] == {"claude-code": d["total_usd"]}
    assert d["cache_read_usd"] == pytest.approx(10_000 * 0.2 / 1e6, abs=0.01)
    wide = diagnose.diagnose(60, with_asks=False)                   # the old turns are inside a 60-day window
    assert wide["total_usd"] > 7 and wide["long_sessions"] == 1 and wide["active_days"] == 2


def test_a_window_never_shows_more_active_days_than_it_has(fake_home):
    for age in range(0, 40, 2):
        fake_home.session(f"d{age:02d}", [(OPUS, fake_home.usage(cread=1_000, out=10))], age_days=age)
    d = diagnose.diagnose(30, with_asks=False)
    assert d["active_days"] <= 30 and d["window_start"] == diagnose.window_start(30)


def test_o1_leaves_out_turns_sent_before_the_window(fake_home):
    _resumed(fake_home)
    (fake_home.home / ".claude").mkdir(exist_ok=True)
    o, _ = _offers(fake_home, 1)
    assert o["O1"].saving_usd_month is None and "saves nothing" in o["O1"].basis
    o, _ = _offers(fake_home, 60)
    assert "120 turns in 1 sessions" in o["O1"].basis and o["O1"].saving_usd_month["high"] > 2


# --- speed: the same numbers, less work ----------------------------------------------------------------

def test_a_lane_scan_without_sha_tokens_keeps_every_other_field(machine):
    from teyla import lanes
    full, lean = lanes.scan(30), lanes.scan(30, want_tokens=False)
    assert len(full) == len(lean) == 4
    strip = lambda us: sorted(({k: v for k, v in u.items() if k != "tokens"} for u in us), key=lambda u: u["agent"])
    assert strip(full) == strip(lean) and all(u["tokens"] == set() for u in lean)


def test_start_collects_without_the_sha_scan(machine, monkeypatch):
    from teyla import lanes
    seen = []
    real = lanes.scan
    monkeypatch.setattr(lanes, "scan", lambda *a, **k: seen.append(k) or real(*a, **k))
    diagnose.collect(30)
    assert seen == [{"want_tokens": False}]


def test_price_overrides_are_reread_when_the_file_changes(tmp_path, monkeypatch):
    f = tmp_path / "prices.json"
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", f)
    base = pricing.lookup("claude-opus-5-5")
    f.write_text(json.dumps({"claude-opus-5-5": {"input": 1.0, "output": 2.0}}))
    assert pricing.lookup("claude-opus-5-5")[0] == 1.0
    f.write_text(json.dumps({"claude-opus-5-5": {"input": 3.5, "output": 2.0}}))
    assert pricing.lookup("claude-opus-5-5")[0] == 3.5
    f.unlink()
    assert pricing.lookup("claude-opus-5-5") == base


def test_a_swapped_price_table_is_not_cached(monkeypatch):
    pricing.lookup("acme-big")
    monkeypatch.setattr(pricing, "effective_prices", lambda: {"acme-big": (5, 5, 1, 30, "volume", False)})
    assert pricing.lookup("acme-big")[0] == 5
    monkeypatch.undo()
    assert pricing.lookup("acme-big") is None


def test_the_progress_line_goes_to_stderr_and_only_for_the_card(machine, capsys):
    code, out, err = _run(["start"], capsys)
    assert code == 0 and err.strip() == "Reading 2 sessions from the last 30 days…" and "Reading" not in out
    code, out, err = _run(["start", "--agent"], capsys)
    assert err == "" and json.loads(out)["summary_text"]
    code, out, err = _run(["start", "--json"], capsys)
    assert err == "" and json.loads(out)["offers"]


# --- the summary card -----------------------------------------------------------------------------------

def test_the_card_has_one_line_per_applicable_offer(machine, capsys):
    d = json.loads(_run(["start", "--agent"], capsys)[1])
    lines = d["summary_text"].splitlines()
    got = [l for l in lines if l.startswith("  O")]
    assert [l.split()[0] for l in got] == [o["id"] for o in d["offers"] if o["applies"]]
    assert any(l.startswith("  O2 Run subagents on Sonnet unless they say otherwise: about $7.00-$10 a month") for l in got), d["summary_text"]
    assert any(l.startswith("  O1 Compact long sessions earlier: about $0.67-$1.34") for l in got), d["summary_text"]
    assert "brings no dollar figure" not in d["summary_text"]


def test_an_offer_without_a_figure_shows_what_it_brings(machine, capsys):
    d = json.loads(_run(["start", "--agent"], capsys)[1])
    o6 = [l for l in d["summary_text"].splitlines() if l.startswith("  O6 ")]
    assert o6 == ["  O6 Keep your prompts and questions: keeps your corrections and open questions"]


def test_the_card_says_when_nothing_applies(machine):
    o, inp = _offers(machine)
    diag = diagnose.diagnose(30, inp, with_asks=False)
    for x in o.values():
        x.applies = False
    text = start.summary_text(diag, list(o.values()))
    assert text.splitlines()[-1] == "No changes to suggest: your settings already match."
    assert "  O" not in text and len(text.splitlines()) <= 12


def test_the_card_fits_twelve_lines_with_all_seven_offers(machine):
    o, inp = _offers(machine)
    diag = dict(diagnose.diagnose(30, inp, with_asks=False), waiting_asks=4)
    for x in o.values():
        x.applies = True
    lines = start.summary_text(diag, list(o.values())).splitlines()
    assert len(lines) <= 12
    assert [l.split()[0] for l in lines if l.startswith("  O")] == [f"O{n}" for n in range(1, 8)]
    diag["long_sessions"] = 0
    assert len(start.summary_text(diag, list(o.values())).splitlines()) <= 12
