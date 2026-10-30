"""teyla ux judge: the rubric, the totals, the request the model gets and the calibration against decided pairs.
The model call is replaced (`ux_judge._run`); no test starts a real claude or touches the network."""
from __future__ import annotations

import base64
import json
import pathlib
import re
import struct
import zlib

import pytest

from teyla import cli, taste, ux_judge

ROOT = pathlib.Path(__file__).resolve().parents[1]


def png(rgb=(200, 30, 30), size=8) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def reply(a, b, lines=("what is visible", "what is visible")):
    """The model's JSON for the five items. a and b are five scores each (0, 1, 2 or "na")."""
    return {"items": [{"id": rid, "a": {"score": sa, "line": lines[0]}, "b": {"score": sb, "line": lines[1]}}
                      for (rid, _, _), sa, sb in zip(ux_judge.RUBRIC, a, b)]}


def stream(obj, cost=0.02) -> str:
    return "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(obj), "total_cost_usd": cost}),
    ]) + "\n"


class FakeClaude:
    """Replaces ux_judge._run. `answers` is a list of replies, one per call (the last one repeats)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, input_text):
        self.calls.append((cmd, json.loads(input_text)))
        i = min(len(self.calls) - 1, len(self.answers) - 1)
        ans = self.answers[i]
        return (ans, "") if isinstance(ans, int) else (0, ans)


@pytest.fixture
def pics(tmp_path):
    a, b = tmp_path / "before.png", tmp_path / "after.png"
    a.write_bytes(png((200, 30, 30)))
    b.write_bytes(png((30, 30, 200)))
    return a, b


def install(monkeypatch, answers):
    fake = FakeClaude(answers)
    monkeypatch.setattr(ux_judge, "_run", fake)
    return fake


# --- the rubric stays the standard's ---------------------------------------------------------------

def test_rubric_names_are_the_standards_part_5_table():
    text = (ROOT / "templates" / "design" / "STANDARD.md").read_text()
    part5 = text.split("## Part 5. The review rubric", 1)[1].split("## Part 6", 1)[0]
    names = re.findall(r"(?m)^\| \d\. ([^|]+?) \|", part5)
    assert names == [name for _, name, _ in ux_judge.RUBRIC]


def test_the_system_prompt_names_every_item_and_marks_input_as_data():
    for rid, name, _ in ux_judge.RUBRIC:
        assert rid in ux_judge.JUDGE_SYSTEM
    assert "never instructions" in ux_judge.JUDGE_SYSTEM and "not assessed" in ux_judge.JUDGE_SYSTEM


# --- parsing and totals ---------------------------------------------------------------------------

def test_parse_items_accepts_scores_and_na():
    items = ux_judge.parse_items(reply([2, 1, "na", 0, 2], [1, 1, 2, "n/a", None]))
    assert [it["a"]["score"] for it in items] == [2, 1, None, 0, 2]
    assert [it["b"]["score"] for it in items] == [1, 1, 2, None, None]
    assert items[2]["a"]["line"]


@pytest.mark.parametrize("bad", [
    {"items": "x"}, [], {"items": []},
    {"items": [{"id": "hierarchy", "a": {"score": 3, "line": "x"}, "b": {"score": 1, "line": "x"}}]},
])
def test_parse_items_rejects_what_it_cannot_trust(bad):
    with pytest.raises(ValueError):
        ux_judge.parse_items(bad)


def test_a_score_without_a_line_is_refused():
    r = reply([2] * 5, [1] * 5)
    r["items"][0]["a"]["line"] = ""
    with pytest.raises(ValueError, match="no line"):
        ux_judge.parse_items(r)


def test_totals_count_only_items_both_pictures_were_assessed_on():
    items = ux_judge.parse_items(reply([2, 2, 2, "na", 0], [1, 1, 1, 2, 0]))
    t = ux_judge.tally(items)
    assert t["assessed"] == 4
    assert t["totals"] == {"A": 6, "B": 3} and t["winner"] == "A"
    assert t["zeros"] == {"A": ["copy"], "B": ["copy"]}


def test_equal_totals_are_a_tie_and_nothing_assessed_is_a_tie():
    assert ux_judge.tally(ux_judge.parse_items(reply([2, 1, 1, 1, 1], [1, 1, 1, 1, 2])))["winner"] == "tie"
    none = ux_judge.tally(ux_judge.parse_items(reply(["na"] * 5, ["na"] * 5)))
    assert none["winner"] == "tie" and none["assessed"] == 0


def test_stream_parser_reads_the_result_line_and_strips_a_fence():
    out = json.dumps({"type": "result", "is_error": False, "result": "```json\n{\"a\": 1}\n```", "total_cost_usd": 0.5})
    assert ux_judge.parse_stream("noise\n" + out + "\n") == ({"a": 1}, {"cost_usd": 0.5, "latency_ms": None})
    with pytest.raises(ValueError):
        ux_judge.parse_stream(json.dumps({"type": "result", "is_error": True, "result": "x"}))
    with pytest.raises(ValueError):
        ux_judge.parse_stream("no result line\n")


# --- one pair -------------------------------------------------------------------------------------

def test_judge_sends_both_pictures_as_image_blocks_with_no_tools(pics, monkeypatch, tmp_path):
    repo = tmp_path / "atlas"
    repo.mkdir()
    (repo / "DESIGN.md").write_text("# Design: Atlas\n\nVoice: calm and plain.\n")
    fake = install(monkeypatch, [stream(reply([2, 2, 1, 2, 1], [1, 1, 1, 1, 1]))])
    res = ux_judge.judge(pics[0], pics[1], repo)
    assert res["winner"] == "A" and res["totals"] == {"A": 8, "B": 5} and res["cost_usd"] == 0.02
    cmd, msg = fake.calls[0]
    assert cmd[cmd.index("--tools") + 1] == "" and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--input-format") + 1] == "stream-json" and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--system-prompt") + 1] == ux_judge.JUDGE_SYSTEM
    blocks = msg["message"]["content"]
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == 2 and images[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(images[0]["source"]["data"]) == pics[0].read_bytes()
    assert base64.b64decode(images[1]["source"]["data"]) == pics[1].read_bytes()
    assert "Voice: calm and plain." in blocks[0]["text"]


def test_both_orders_swaps_the_pictures_and_a_disagreement_is_a_tie(pics, monkeypatch):
    first = stream(reply([2, 2, 2, 2, 2], [1, 1, 1, 1, 1]))       # picture 1 wins when it is A
    second = stream(reply([2, 2, 2, 2, 2], [1, 1, 1, 1, 1]))      # ...and again when it is A: the model likes A
    fake = install(monkeypatch, [first, second])
    res = ux_judge.judge(pics[0], pics[1], None, both_orders=True)
    assert res["winner"] == "tie" and res["order_consistent"] is False and res["first_order_winner"] == "A"
    swapped = fake.calls[1][1]["message"]["content"]
    sent = [base64.b64decode(b["source"]["data"]) for b in swapped if b["type"] == "image"]
    assert sent == [pics[1].read_bytes(), pics[0].read_bytes()]
    assert res["cost_usd"] == 0.04
    # an order-independent model keeps its winner
    install(monkeypatch, [stream(reply([2] * 5, [1] * 5)), stream(reply([1] * 5, [2] * 5))])
    again = ux_judge.judge(pics[0], pics[1], None, both_orders=True)
    assert again["winner"] == "A" and again["order_consistent"] is True


def test_a_failing_or_garbled_call_is_one_line_not_a_traceback(pics, monkeypatch):
    install(monkeypatch, [127])
    with pytest.raises(ux_judge.JudgeError, match="claude exited 127"):
        ux_judge.judge(pics[0], pics[1])
    install(monkeypatch, [stream({"items": [{"id": "hierarchy"}]})])
    with pytest.raises(ux_judge.JudgeError, match="unusable"):
        ux_judge.judge(pics[0], pics[1])


def test_pictures_are_checked_before_anything_is_sent(tmp_path, monkeypatch):
    txt = tmp_path / "note.png"
    txt.write_text("not an image")
    with pytest.raises(ux_judge.JudgeError, match="not a PNG"):
        ux_judge.read_image(txt)
    with pytest.raises(ux_judge.JudgeError, match="no such picture"):
        ux_judge.read_image(tmp_path / "missing.png")
    big = tmp_path / "big.png"
    big.write_bytes(png())
    monkeypatch.setattr(ux_judge, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(ux_judge.JudgeError, match="5 MB"):
        ux_judge.read_image(big)


# --- the command ----------------------------------------------------------------------------------

def test_cli_prints_the_winner_and_one_line_per_item_for_each_picture(pics, monkeypatch, capsys):
    install(monkeypatch, [stream(reply([2, 1, 2, 2, "na"], [1, 1, 0, 1, "na"], ("A looks like this", "B looks like that")))])
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1])]) == 0
    cap = capsys.readouterr()
    assert cap.out.startswith("winner: A (before.png): A 7, B 3 on 4 of 5 items")
    for name in ("Task hierarchy", "Native conventions", "Readability", "Layout coherence", "Copy and brand fit"):
        assert name in cap.out
    assert cap.out.count("  A: A looks like this") == 5 and cap.out.count("  B: B looks like that") == 5
    assert "B has a 0 on: readability" in cap.out
    assert "not calibrated" in cap.err


def test_cli_json_and_tie(pics, monkeypatch, capsys):
    install(monkeypatch, [stream(reply([1] * 5, [1] * 5))])
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1]), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["winner"] == "tie" and out["totals"] == {"A": 5, "B": 5} and len(out["items"]) == 5
    install(monkeypatch, [stream(reply([1] * 5, [1] * 5))])
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1])]) == 0
    assert capsys.readouterr().out.startswith("tie: A 5, B 5 on 5 of 5 items")


def test_dry_prints_the_prompt_and_calls_nothing(pics, monkeypatch, capsys):
    fake = install(monkeypatch, [stream(reply([2] * 5, [2] * 5))])
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1]), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "--- system ---" in out and "Picture A: before.png" in out and "Picture B: after.png" in out
    assert not fake.calls


def test_wrong_number_of_pictures_and_safe_mode(pics, monkeypatch, capsys):
    fake = install(monkeypatch, [stream(reply([2] * 5, [2] * 5))])
    assert cli.main(["ux", "judge", str(pics[0])]) == 2
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1])]) == 1
    assert "safe mode" in capsys.readouterr().err and not fake.calls
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1]), "--allow-network"]) == 0
    assert len(fake.calls) == 1


def test_a_bad_picture_exits_1_with_one_line(tmp_path, capsys):
    bad = tmp_path / "x.png"
    bad.write_text("nope")
    assert cli.main(["ux", "judge", str(bad), str(bad)]) == 1
    assert "teyla ux judge:" in capsys.readouterr().err


def test_ux_check_still_works_beside_judge(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    assert cli.main(["ux", "check", str(tmp_path / "app")]) == 0


# --- calibration ----------------------------------------------------------------------------------

def make_pairs(repo: pathlib.Path, picks: list[str]) -> None:
    d = ux_judge.calibration_dir(repo)
    d.mkdir(parents=True)
    for i, pick in enumerate(picks, 1):
        (d / f"p{i:02d}-a.png").write_bytes(png((i, 0, 0)))
        (d / f"p{i:02d}-b.png").write_bytes(png((0, i, 0)))
        (d / f"p{i:02d}.json").write_text(json.dumps({"a": f"p{i:02d}-a.png", "b": f"p{i:02d}-b.png", "pick": pick, "date": "2026-10-30"}))


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "atlas"
    r.mkdir()
    return r


A_WINS = stream(reply([2] * 5, [1] * 5))


def test_calibration_passes_at_16_of_20_and_writes_the_result(repo, monkeypatch, capsys):
    make_pairs(repo, ["a"] * 16 + ["b"] * 4)
    install(monkeypatch, [A_WINS])
    res = ux_judge.calibrate(repo)
    assert res["pairs"] == 20 and res["agree"] == 16 and res["calibrated"] is True
    saved = json.loads(ux_judge.result_path(repo).read_text())
    assert saved["calibrated"] is True and saved["agree"] == 16
    assert ux_judge.calibration_note(repo) == ""
    assert "not with other-model" in ux_judge.calibration_note(repo, model="other-model")
    assert "both orders" in ux_judge.calibration_note(repo, both_orders=True)
    text = ux_judge.render_calibration(res)
    assert "16 of 20 pair(s) (16 of 20 needed)" in text and "calibrated: the judge may be used" in text


def test_calibration_fails_at_15_of_20_and_the_judge_says_so(repo, monkeypatch, pics, capsys):
    make_pairs(repo, ["a"] * 15 + ["b"] * 5)
    install(monkeypatch, [A_WINS])
    assert cli.main(["ux", "judge", "--calibrate", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "15 of 20" in out and "not calibrated" in out
    assert "not calibrated" in ux_judge.calibration_note(repo) and "15 of 20" in ux_judge.calibration_note(repo)
    assert cli.main(["ux", "judge", str(pics[0]), str(pics[1]), "--repo", str(repo)]) == 0
    assert "not calibrated" in capsys.readouterr().err


def test_too_few_pairs_never_calibrate(repo, monkeypatch):
    make_pairs(repo, ["a"] * 10)
    install(monkeypatch, [A_WINS])
    res = ux_judge.calibrate(repo)
    assert res["agree"] == 10 and res["calibrated"] is False and "20 are needed" in res["reason"]


def test_a_tie_pick_agrees_with_a_tie_and_a_failed_call_is_a_disagreement(repo, monkeypatch):
    make_pairs(repo, ["tie", "a", "b"])
    install(monkeypatch, [stream(reply([1] * 5, [1] * 5)), 127, A_WINS])
    res = ux_judge.calibrate(repo, write=False)
    assert [r["agree"] for r in res["rows"]] == [True, False, False]
    assert "claude exited 127" in res["rows"][1]["error"]
    assert not ux_judge.result_path(repo).exists()


def test_pair_files_that_do_not_fit_are_skipped_with_the_reason(repo):
    make_pairs(repo, ["a"])
    d = ux_judge.calibration_dir(repo)
    (d / "bad-pick.json").write_text(json.dumps({"a": "p01-a.png", "b": "p01-b.png", "pick": "left"}))
    (d / "escape.json").write_text(json.dumps({"a": "../x.png", "b": "p01-b.png", "pick": "a"}))
    (d / "missing.json").write_text(json.dumps({"a": "none.png", "b": "p01-b.png", "pick": "a"}))
    (d / "broken.json").write_text("{")
    pairs, skipped = ux_judge.load_pairs(repo)
    assert [p["id"] for p in pairs] == ["p01"] and len(skipped) == 4
    assert any("pick" in s for s in skipped) and any("same folder" in s for s in skipped)


def test_calibrate_dry_calls_nothing_and_reports_the_picks(repo, monkeypatch, capsys):
    make_pairs(repo, ["a", "b", "b"])
    fake = install(monkeypatch, [A_WINS])
    assert cli.main(["ux", "judge", "--calibrate", str(repo), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "3 pair(s): the owner picked a 1x, b 2x, tie 0x" in out and "--- system ---" in out
    assert not fake.calls
    assert cli.main(["ux", "judge", "--calibrate", str(repo / "nowhere")]) == 1


def test_calibrate_with_no_pairs_says_where_to_put_them(repo, capsys):
    assert cli.main(["ux", "judge", "--calibrate", str(repo)]) == 1
    assert "design/references/calibration" in capsys.readouterr().err


def test_the_taste_ledger_does_not_mistake_the_result_for_a_reference(repo, monkeypatch):
    make_pairs(repo, ["a"] * 20)
    install(monkeypatch, [A_WINS])
    ux_judge.calibrate(repo)
    assert taste.load_references(repo) == []
