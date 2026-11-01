"""`teyla kit image` and `kit compare`, and the provider calls under them. The network is replaced:
every call goes through `genai._post`, which these tests swap for a recorder."""
from __future__ import annotations

import base64
import json
import re

import pytest

from teyla import cli, config, genai, kit

from kitfix import RealtimeFake, gemini_answer, make_repo, openai_answer, png_bytes

KEY = "k-" + "x" * 12            # a fake key, built here so no key-shaped literal sits in the repo


class Net:
    """Stands in for genai._post: records each call, answers with a tiny PNG in the provider's shape."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, data, timeout=240):
        self.calls.append(dict(url=url, headers=headers, data=data))
        return gemini_answer(png_bytes()) if "googleapis" in url else openai_answer(png_bytes())


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(genai, "_post", n)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    return n


@pytest.fixture(autouse=True)
def no_keys_by_default(monkeypatch):
    for v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "TEYLA_KIT_GEMINI_MODEL"):
        monkeypatch.delenv(v, raising=False)


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- prices -------------------------------------------------------------------------------------------

def test_prices():
    assert genai.image_price("nano-banana-2.1") == (0.0336, True)
    usd, exact = genai.image_price("gpt-image-2", {"quality": "medium"})
    assert not exact and usd == pytest.approx(1056 * 30 / 1e6)
    assert genai.image_price("gpt-image-2", {"quality": "high"})[0] > usd
    with pytest.raises(genai.GenError):
        genai.image_price("dream-9")
    assert genai.tts_price(840, "gpt-realtime-2.1-mini") == pytest.approx(0.025)   # 14 characters a second, one minute
    assert genai.money(0.0336) == "$0.0336" and genai.money(1.5, False) == "~$1.50"


# --- kit image ------------------------------------------------------------------------------------------

def test_image_prints_the_price_and_refuses_without_yes(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "kit", "image", str(repo), "waving at a sunrise")
    assert rc == 2 and "$0.0336" in out and "--yes" in err
    assert net.calls == [] and not (repo / "brand" / "out" / "mascot").exists()


def test_image_dry_prints_the_prompt_and_calls_nothing(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    rc, out, _ = run(capsys, "kit", "image", str(repo), "waving at a sunrise", "--dry")
    assert rc == 0 and "Pip" in out and "waving at a sunrise" in out and "2 reference image(s)" in out
    assert net.calls == []


def test_image_with_yes_calls_gemini_saves_png_txt_and_provenance(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "kit", "image", str(repo), "Waving at a sunrise!", "--yes")
    assert rc == 0, err
    (call,) = net.calls
    assert "gemini-3.1-flash-image:generateContent" in call["url"]
    assert call["headers"]["x-goog-api-key"] == KEY and KEY not in call["url"]
    body = json.loads(call["data"])
    parts = body["contents"][0]["parts"]
    assert "Waving at a sunrise!" in parts[0]["text"] and "Pip" in parts[0]["text"]
    assert [p["inline_data"]["mime_type"] for p in parts[1:]] == ["image/png", "image/png"]
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "1:1"} and body["generationConfig"]["temperature"] == 0.6
    pngs = list((repo / "brand" / "out" / "mascot").glob("*.png"))
    assert len(pngs) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}-waving-at-a-sunrise\.png", pngs[0].name)
    assert pngs[0].read_bytes() == png_bytes()
    txt = pngs[0].with_suffix(".txt").read_text()
    assert "model: nano-banana-2.1" in txt and "price_usd: 0.0336" in txt and "brand/mascot/ref-1.png" in txt and "Waving at a sunrise!" in txt
    assert KEY not in txt and KEY not in out + err
    entry = kit.load(repo)["provenance"][-1]
    assert entry["asset"] == f"brand/out/mascot/{pngs[0].name}" and entry["made_by"] == "model: nano-banana-2.1"
    assert entry["references"] == ["brand/mascot/ref-1.png", "brand/mascot/ref-2.png"] and "Waving" in entry["prompt"]
    assert kit.check(repo)["verdict"] == "OK"          # the new asset is covered


def test_a_second_image_of_the_same_scene_gets_a_new_name(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    for _ in range(2):
        assert run(capsys, "kit", "image", str(repo), "waving", "--yes")[0] == 0
    assert len(list((repo / "brand" / "out" / "mascot").glob("*.png"))) == 2
    assert kit.check(repo)["verdict"] == "OK"


def test_a_scene_in_another_script_still_gets_a_file_name(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    assert run(capsys, "kit", "image", str(repo), "\u043c\u0430\u0445\u0430\u0435\u0442 \u0440\u0443\u043a\u043e\u0439", "--yes")[0] == 0
    assert re.search(r"scene-[0-9a-f]{6}\.png$", next((repo / "brand/out/mascot").glob("*.png")).name)


def test_image_with_gpt_image_2_sends_an_edit_with_the_references(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    rc, out, _ = run(capsys, "kit", "image", str(repo), "sitting", "--model", "gpt-image-2", "--yes")
    assert rc == 0 and "~$0.0317" in out
    (call,) = net.calls
    assert call["url"] == genai.OPENAI_EDITS_URL and call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert call["data"].count(b'name="image[]"') == 2 and b'name="model"\r\n\r\ngpt-image-2' in call["data"]
    assert kit.load(repo)["provenance"][-1]["made_by"] == "model: gpt-image-2"


def test_gpt_image_2_without_references_uses_the_generations_endpoint(tmp_path, net):
    png = genai.generate_image("gpt-image-2", "a dot", [], {"quality": "low"})
    assert png == png_bytes() and net.calls[0]["url"] == genai.OPENAI_GENERATIONS_URL
    assert json.loads(net.calls[0]["data"])["quality"] == "low"


def test_no_key_says_how_to_set_one(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(genai, "_post", lambda *a, **k: pytest.fail("called without a key"))
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "kit", "image", str(repo), "waving", "--yes")
    assert rc == 1 and "GEMINI_API_KEY" in err


def test_a_provider_error_is_one_line_and_writes_nothing(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise genai.GenError("HTTP 429 from generativelanguage.googleapis.com: quota")
    monkeypatch.setattr(genai, "_post", boom)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "kit", "image", str(repo), "waving", "--yes")
    assert rc == 1 and "429" in err and not (repo / "brand" / "out" / "mascot").exists()


def test_an_answer_without_an_image_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(genai, "_post", lambda *a, **k: json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode())
    with pytest.raises(genai.GenError, match="SAFETY"):
        genai.generate_image("nano-banana-2.1", "x", [], {}, key=KEY)


def test_safe_mode_refuses_the_call(tmp_path, capsys, net, monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    repo = make_repo(tmp_path)
    rc, _, err = run(capsys, "kit", "image", str(repo), "waving", "--yes")
    assert rc == 2 and "safe mode" in err and net.calls == []
    assert run(capsys, "kit", "image", str(repo), "waving", "--yes", "--allow-network")[0] == 0


def test_the_model_id_can_be_overridden(tmp_path, net, monkeypatch):
    monkeypatch.setenv("TEYLA_KIT_GEMINI_MODEL", "gemini-test-image")
    genai.generate_image("nano-banana-2.1", "x", [], {}, key=KEY)
    assert "gemini-test-image:generateContent" in net.calls[0]["url"]


def test_image_needs_a_filled_mascot_and_references(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    (repo / "brand" / "mascot" / "ref-1.png").unlink()
    rc, _, err = run(capsys, "kit", "image", str(repo), "waving", "--yes")
    assert rc == 2 and "reference images are missing" in err
    p = repo / "brand" / "kit.toml"
    p.write_text(p.read_text().replace('name = "Pip"', 'name = "{{mascot name}}"'))
    assert run(capsys, "kit", "image", str(repo), "waving", "--yes")[0] == 2


def test_keys_come_from_the_keychain_when_the_env_has_none(monkeypatch):
    assert genai.api_key("gemini", env={}, keychain=lambda svc: KEY if svc == "gemini-api-key" else None) == KEY
    assert genai.api_key("openai", env={"OPENAI_API_KEY": " " + KEY + " "}, keychain=lambda s: None) == KEY
    assert genai.api_key("openai", env={}, keychain=lambda s: None) is None


# --- speech -----------------------------------------------------------------------------------------------

def test_speak_reads_the_text_in_a_realtime_session_and_returns_wav():
    session = RealtimeFake()
    out = genai.speak("Hello there.", voice="cedar", key=KEY, open_session=session)
    assert out[:4] == b"RIFF" and out[8:12] == b"WAVE" and out[44:] == RealtimeFake.PCM
    assert session.url == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
    assert session.headers == {"Authorization": f"Bearer {KEY}"} and session.closed
    update, create = session.sent
    assert update["session"]["audio"]["output"] == {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "cedar"}
    assert create["response"]["conversation"] == "none"
    assert create["response"]["input"][0]["content"][0] == {"type": "input_text", "text": "Hello there."}


def test_speak_takes_a_paraphrase_again_and_gives_up_after_three_takes():
    session = RealtimeFake(transcript=lambda take, text: text if take == 2 else "I would love to help with that")
    assert genai.speak("Open the door.", key=KEY, open_session=session)[:4] == b"RIFF" and session.takes == 2
    session = RealtimeFake(transcript=lambda take, text: "something else entirely")
    with pytest.raises(genai.GenError, match="did not read the text"):
        genai.speak("Open the door.", key=KEY, open_session=session)
    assert session.takes == 3 and session.closed


def test_speak_sends_a_long_text_in_pieces_and_refuses_unknown_models_and_voices():
    session = RealtimeFake()
    text = " ".join(f"Sentence number {i} has a few more words in it." for i in range(40))
    out = genai.speak(text, key=KEY, open_session=session)
    assert session.takes > 1 and len(out) - 44 == session.takes * len(RealtimeFake.PCM)
    assert all(len(m["response"]["input"][0]["content"][0]["text"]) <= genai.TTS_PIECE_CHARS for m in session.sent[1:])
    with pytest.raises(genai.GenError, match="unknown voice"):
        genai.speak("Hi", voice="onyx", key=KEY, open_session=RealtimeFake())
    with pytest.raises(genai.GenError, match="unknown voice-over model"):
        genai.speak("Hi", model="tts-1", key=KEY, open_session=RealtimeFake())


def test_a_provider_error_event_says_only_that_it_refused():
    session = RealtimeFake()
    session.queue = [{"type": "error", "error": {"message": "the text was: secret words"}}]
    with pytest.raises(genai.GenError) as caught:
        genai.speak("secret words", key=KEY, open_session=session)
    assert "secret" not in str(caught.value) and session.closed


def test_faithful_allows_spelled_numbers_but_not_a_different_digit():
    assert genai.faithful("Ten kilometres is about 6.2 miles.", "Ten kilometres is about six point two miles")
    assert genai.faithful("Ten kilometres is about 6.2 miles.", "Ten kilometres is about 6.2 miles")
    assert not genai.faithful("Ten kilometres is about 6.2 miles.", "Ten kilometres is about 9 miles")
    assert not genai.faithful("Hello", "")


# --- kit compare ----------------------------------------------------------------------------------------------

def test_compare_without_yes_prints_the_plan_and_the_price_and_calls_nothing(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    rc, out, _ = run(capsys, "kit", "compare", str(repo), "in a park")
    assert rc == 0 and net.calls == []
    assert "2 model(s) x 10 pose(s) = 20 image(s)" in out and "plan only" in out
    assert re.search(r"prices: nano-banana-2\.1 10 x \$0\.0336 = \$0\.3360; gpt-image-2 10 x ~\$0\.0317 = ~\$0\.3168; total ~\$0\.6528", out)
    assert not (repo / "brand" / "out" / "compare").exists()


def test_compare_with_yes_makes_every_image_a_contact_sheet_and_a_record(tmp_path, capsys, net):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "kit", "compare", str(repo), "in a park", "--poses", "3", "--yes")
    assert rc == 0, err
    assert len(net.calls) == 6
    (folder,) = (repo / "brand" / "out" / "compare").iterdir()
    assert len(list((folder / "nano-banana-2.1").glob("*.png"))) == 3 and len(list((folder / "gpt-image-2").glob("*.png"))) == 3
    assert (folder / "contact.png").is_file() and "prices: " in (folder / "compare.txt").read_text()
    rec = kit.load(repo)["comparison"][-1]
    assert rec["models"] == ["nano-banana-2.1", "gpt-image-2"] and rec["poses"] == 3 and rec["picked"] == ""
    assert rec["folder"] == f"brand/out/compare/{folder.name}" and rec["cost_usd"] == pytest.approx(3 * 0.0336 + 3 * 1056 * 30 / 1e6, abs=1e-4)
    assert "prices: " in out
    assert kit.check(repo)["verdict"] == "OK"          # compare output is covered by the record, not per-file provenance


def test_compare_is_bounded(tmp_path, capsys, net):
    repo = make_repo(tmp_path)
    assert run(capsys, "kit", "compare", str(repo), "x", "--poses", "11")[0] == 2
    assert run(capsys, "kit", "compare", str(repo), "x", "--poses", "0")[0] == 2
    assert run(capsys, "kit", "compare", str(repo), "x", "--models", "nano-banana-2.1,gpt-image-2,dream-9")[0] == 2
    assert run(capsys, "kit", "compare", str(repo), "x", "--models", "dream-9")[0] == 2
    rc, out, _ = run(capsys, "kit", "compare", str(repo), "x", "--models", "nano-banana-2.1", "--poses", "2")
    assert rc == 0 and "1 model(s) x 2 pose(s) = 2 image(s)" in out and net.calls == []


def test_compare_reports_a_failed_pose_and_still_charges_only_what_ran(tmp_path, capsys, monkeypatch):
    pytest.importorskip("PIL")
    n = {"i": 0}

    def flaky(url, headers, data, timeout=240):
        n["i"] += 1
        if n["i"] == 2:
            raise genai.GenError("HTTP 500 from example")
        return gemini_answer(png_bytes())
    monkeypatch.setattr(genai, "_post", flaky)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    repo = make_repo(tmp_path)
    rc, out, err = run(capsys, "kit", "compare", str(repo), "x", "--models", "nano-banana-2.1", "--poses", "3", "--yes")
    assert rc == 1 and "HTTP 500" in err
    (folder,) = (repo / "brand" / "out" / "compare").iterdir()
    assert "charged for 2 image(s)" in (folder / "compare.txt").read_text()
