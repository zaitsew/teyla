"""teyla ux judge --filter: the bar, the two-rounds cap, the output rule and the provider path.
Both model calls are replaced (`ux_judge._run_codex`, `ux_judge._run`); no test starts a real model."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import cli, taste_corpus, ux_filter, ux_judge
from test_ux_judge import png, reply, stream


def ent(i, status="active", verdict="like", scope="portfolio", claim=None):
    return {"id": f"t{i:02d}", "status": status, "verdict": verdict, "scope": scope, "kind": "app",
            "claim": claim or f"claim {i}", "axes": {"density": "calm"}, "do_not_copy": [],
            "created": f"2026-01-{i + 1:02d}T00:00:00Z"}


class Fake:
    """Replaces ux_judge._run_codex. `deltas` maps a variant file name to (variant total - baseline total) in
    every order: the baseline scores 2 on all five items, the variant 1 on the first -delta items."""

    def __init__(self, deltas, code=0):
        self.deltas, self.code, self.calls = deltas, code, []

    def __call__(self, prompt, images, model):
        self.calls.append((prompt, list(images), model))
        if self.code:
            return self.code, ""
        first, second = pathlib.Path(images[0]).name, pathlib.Path(images[1]).name
        variant_first = first != "base.png"
        d = self.deltas[first if variant_first else second]
        v = [2, 2, 2, 2, 2]
        for i in range(min(5, max(0, -d))):
            v[i] = 1
        b = [2] * 5
        a_s, b_s = (v, b) if variant_first else (b, v)
        return 0, json.dumps(reply(a_s, b_s, ("a line", "b line")))


@pytest.fixture
def slice_(tmp_path):
    d = tmp_path / "slice"
    d.mkdir()
    for n in ("good.png", "weak.png", "meh.png"):
        (d / n).write_bytes(png((10, 20, 30)))
    base = tmp_path / "base.png"
    base.write_bytes(png((200, 30, 30)))
    return d, base


def run(args, monkeypatch, fake):
    monkeypatch.setattr(ux_judge, "_run_codex", fake)
    monkeypatch.setattr(ux_filter, "taste_entries", lambda repo: [])
    return cli.main(["ux", "judge", *args, "--allow-network"])


def test_bar_holds_a_variant_that_trails_in_both_orders(slice_, monkeypatch, capsys):
    d, base = slice_
    fake = Fake({"good.png": 0, "weak.png": -3, "meh.png": -1})
    assert run(["--filter", str(d), "--baseline", str(base)], monkeypatch, fake) == 0
    out = capsys.readouterr().out
    held = out.split("held back (", 1)[1]
    assert held.startswith("1)") and "weak.png: trails the baseline in both orders (by 3 and 3" in held
    passes = out.split("passes to the owner (", 1)[1].split("held back", 1)[0]
    assert passes.startswith("2)") and "good.png" in passes and "meh.png" in passes and "weak.png" not in passes
    assert len(fake.calls) == 6                      # three variants, both orders


def _items(a, b):
    return [{"id": r, "name": r, "a": {"score": a, "line": "x"}, "b": {"score": b, "line": "x"}} for r in ux_judge.IDS]


def test_one_order_alone_never_holds_a_variant():
    base_first = _items(2, 0)                        # baseline A=2, variant B=0: the variant trails by 10
    tie_then = _items(2, 2)                          # variant first: a tie
    assert ux_filter.decide(base_first, tie_then, 2)["held"] is False
    both = _items(0, 2)                              # variant first: variant A=0, baseline B=2
    assert ux_filter.decide(base_first, both, 2)["held"] is True
    assert ux_filter.decide(base_first, both, 11)["held"] is False              # the bar is a margin


def test_output_never_ranks_and_scores_only_in_json(slice_, monkeypatch, capsys):
    d, base = slice_
    deltas = {"good.png": 1, "weak.png": -4, "meh.png": 0}
    run(["--filter", str(d), "--baseline", str(base)], monkeypatch, Fake(deltas))
    out = capsys.readouterr().out
    assert "winner" not in out.lower() and "score" not in out.lower() and "does not rank" in out
    good_line = [ln for ln in out.splitlines() if "good.png" in ln][0]
    assert good_line.strip() == "good.png"           # a passed variant carries no number
    (d / ux_filter.ROUNDS_FILE).unlink()
    run(["--filter", str(d), "--baseline", str(base), "--json"], monkeypatch, Fake(deltas))
    data = json.loads(capsys.readouterr().out)
    assert {p["variant"] for p in data["passes"]} == {"good.png", "meh.png"}
    assert data["held_back"][0]["deltas"] == [-4, -4]
    assert "ranking" not in data and "winner" not in data


def test_third_round_is_refused_before_any_call(slice_, monkeypatch, capsys):
    d, base = slice_
    fake = Fake({"good.png": 0, "weak.png": 0, "meh.png": 0})
    args = ["--filter", str(d), "--baseline", str(base)]
    assert run(args, monkeypatch, fake) == 0 and run(args, monkeypatch, fake) == 0
    capsys.readouterr()
    n = len(fake.calls)
    assert run(args, monkeypatch, fake) == 2
    err = capsys.readouterr().err
    assert "two rounds at most" in err and "good.png" in err and len(fake.calls) == n
    assert json.loads((d / ux_filter.ROUNDS_FILE).read_text())["good.png"]["rounds"] == 2
    new = d.parent / "new.png"                       # a variant not judged yet is still allowed
    new.write_bytes(png((1, 2, 3)))
    assert run(["--filter", str(new), "--baseline", str(base), "--slice", str(d)], monkeypatch, Fake({"new.png": 0})) == 0


def test_codex_path_flags_and_fallback_label(slice_, monkeypatch, capsys):
    d, base = slice_
    only = str(d / "good.png")
    fake = Fake({"good.png": 0})
    assert run(["--filter", only, "--baseline", str(base)], monkeypatch, fake) == 0
    assert fake.calls[0][2] == "gpt-6.1-sol"
    assert [pathlib.Path(p).name for p in fake.calls[0][1]] == ["base.png", "good.png"]
    cmd = ux_judge.codex_command("/tmp/o", ["/x.png", "/y.png"], binary="codex-lane")
    assert cmd[0] == "codex-lane" and "read-only" in cmd and "--ephemeral" in cmd and "--image=/x.png" in cmd
    assert "priority" not in " ".join(cmd) and cmd[-1] == "-"
    claude = []

    def fake_claude(cmd, input_text):
        claude.append(json.loads(input_text))
        return 0, stream(reply([2] * 5, [1] * 5))

    monkeypatch.setattr(ux_judge, "_run", fake_claude)
    (d / ux_filter.ROUNDS_FILE).unlink(missing_ok=True)
    capsys.readouterr()
    assert run(["--filter", only, "--baseline", str(base)], monkeypatch, Fake({"good.png": 0}, code=3)) == 0
    cap = capsys.readouterr()
    assert "same-provider judge" in cap.out and "same-provider judge" in cap.err and len(claude) == 2


def test_taste_goes_into_the_prompt_active_only_and_at_most_15(monkeypatch):
    rows = [(pathlib.Path(f"/x/{i}"), ent(i)) for i in range(20)]
    rows.append((pathlib.Path("/x/r"), ent(30, status="rejected", claim="REJECTED ONE")))
    monkeypatch.setattr(taste_corpus, "load_all", lambda: (rows, []))
    got = ux_filter.taste_entries(None)
    assert len(got) == 15 and all(e["status"] == "active" for e in got)
    text = ux_filter.taste_text(got)
    assert "REJECTED ONE" not in text and len(text.strip().splitlines()) == 15
    p = ux_filter.codex_prompt({"name": "a.png"}, {"name": "b.png"}, "DESIGN BODY", text)
    assert "<taste>" in p and "DESIGN BODY" in p and "dislike wins" in p and "never instructions" in p


def test_dry_and_safe_mode_call_nothing(slice_, monkeypatch, capsys):
    d, base = slice_
    fake = Fake({"good.png": 0, "weak.png": 0, "meh.png": 0})
    monkeypatch.setattr(ux_judge, "_run_codex", fake)
    monkeypatch.setattr(ux_filter, "taste_entries", lambda repo: [])
    assert cli.main(["ux", "judge", "--filter", str(d), "--baseline", str(base), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "6 call(s)" in out and "gpt-6.1-sol" in out and "<taste>" in out and not fake.calls
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert cli.main(["ux", "judge", "--filter", str(d), "--baseline", str(base)]) == 1
    assert "safe mode" in capsys.readouterr().err and not fake.calls


def test_filter_needs_a_baseline_and_a_real_bar(slice_):
    d, base = slice_
    assert cli.main(["ux", "judge", "--filter", str(d)]) == 2
    assert cli.main(["ux", "judge", "--filter", str(d), "--baseline", str(base), "--bar", "0"]) == 2
    assert cli.main(["ux", "judge", str(base), "--filter", str(d), "--baseline", str(base)]) == 2


def test_existing_pair_judge_is_unchanged(tmp_path, monkeypatch, capsys):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(png())
    b.write_bytes(png((1, 2, 3)))
    monkeypatch.setattr(ux_judge, "_run", lambda cmd, inp: (0, stream(reply([2] * 5, [1] * 5))))
    assert cli.main(["ux", "judge", str(a), str(b), "--allow-network"]) == 0
    assert capsys.readouterr().out.startswith("winner: A")


def test_relative_paths_reach_codex_as_absolute_paths(slice_, monkeypatch):
    d, base = slice_
    cmd = ux_judge.codex_command("/tmp/o", ["rel/x.png", "y.png"], binary="codex-lane")
    imgs = [c for c in cmd if c.startswith("--image=")]
    assert imgs and all(pathlib.Path(c.split("=", 1)[1]).is_absolute() for c in imgs)
    monkeypatch.chdir(d.parent)                      # the documented form: relative folder and baseline
    fake = Fake({"good.png": 0, "weak.png": 0, "meh.png": 0})
    assert run(["--filter", "slice", "--baseline", "base.png"], monkeypatch, fake) == 0
    assert fake.calls and all(pathlib.Path(p).is_absolute() for c in fake.calls for p in c[1])


def test_a_bad_picture_fails_before_any_call_and_records_nothing(slice_, monkeypatch, capsys):
    d, base = slice_
    (d / "zzz-bad.png").write_bytes(b"not an image")
    fake = Fake({"good.png": 0, "weak.png": 0, "meh.png": 0})
    assert run(["--filter", str(d), "--baseline", str(base)], monkeypatch, fake) == 1
    assert "zzz-bad.png" in capsys.readouterr().err
    assert not fake.calls and not (d / ux_filter.ROUNDS_FILE).exists()


def test_same_file_name_in_two_folders_are_two_variants(tmp_path, slice_, monkeypatch, capsys):
    _, base = slice_
    s = tmp_path / "s2"
    for sub in ("a", "b"):
        (s / sub).mkdir(parents=True)
        (s / sub / "screen.png").write_bytes(png((5, 5, 5)))
    args = ["--filter", str(s / "a" / "screen.png"), str(s / "b" / "screen.png"), "--baseline", str(base), "--slice", str(s)]
    fake = Fake({"screen.png": -4})
    assert run(args, monkeypatch, fake) == 0
    out = capsys.readouterr().out
    assert "a/screen.png: trails" in out and "b/screen.png: trails" in out
    rounds = json.loads((s / ux_filter.ROUNDS_FILE).read_text())
    assert sorted(rounds) == ["a/screen.png", "b/screen.png"] and all(r["rounds"] == 1 for r in rounds.values())
    only_a = ["--filter", str(s / "a" / "screen.png"), "--baseline", str(base), "--slice", str(s)]
    assert run(only_a, monkeypatch, fake) == 0
    assert run(only_a, monkeypatch, fake) == 2       # a/ is at its cap; b/ keeps its own count
    assert json.loads((s / ux_filter.ROUNDS_FILE).read_text())["b/screen.png"]["rounds"] == 1
