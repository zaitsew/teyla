"""`teyla tg`: the Telegram card, against a fake Bot API. No network, no Keychain, no real session.

The security floor is what most of these pin: one owner, opcodes only, one delivery per nonce, a confirm tap
before a typed answer, a rate limit, and nothing retried after a crash."""
from __future__ import annotations

import json
import re
import threading
import zlib

import pytest

from teyla import asks, tg, tg_card

OWNER, STRANGER = 1001, 2002
TOKEN = "123456789:" + "A" * 35


def _ask(i: str, *, options=None, harness="claude-code", kind="question", question=None) -> asks.Ask:
    return asks.Ask(id=i, kind=kind, product="cellar", title=f"title {i}",
                    question=question or f"Which way for {i}?", context="", options=list(options or []),
                    when=1.0, archived=False, link="", pr="", harness=harness, session=f"sess-{i}")


class FakeAPI:
    """Records every call; `sendWidget` returns increasing message ids; `getUpdates` pops queued batches."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.batches: list[list] = []
        self.msg = 100

    def __call__(self, method, params=None, timeout=30):
        self.calls.append((method, dict(params or {})))
        if method == "sendWidget":
            self.msg += 1
            return {"message_id": self.msg}
        if method == "getUpdates":
            return self.batches.pop(0) if self.batches else []
        if method == "getMe":
            return {"username": "example_teyla_bot"}
        return True

    def of(self, method):
        return [p for m, p in self.calls if m == method]

    def answers(self):
        return [json.loads(p["data"]) for p in self.of("answerWidgetQuery")]


class World:
    def __init__(self, items):
        self.items = {a.id: a for a in items}
        self.delivered: list[tuple[str, str, bool]] = []
        self.done: list[str] = []
        self.snoozed: list[str] = []
        self.answer_result = {"ok": True, "via": "claude-bg", "detail": "started"}

    def queue(self, now):
        rows = [{"id": a.id, "triage": None} for a in self.items.values() if a.status == "open"]
        return dict(self.items), rows

    def answer(self, a, text, clipboard=True):
        self.delivered.append((a.id, text, clipboard))
        if self.answer_result.get("ok"):
            a.status = "done"
        return dict(self.answer_result, id=a.id)

    def mark_done(self, ask_id):
        self.done.append(ask_id)
        self.items[ask_id].status = "done"
        return [f"done: {ask_id}"], 0

    def snooze(self, ask_id):
        self.snoozed.append(ask_id)
        self.items[ask_id].status = "snoozed"
        return f"snoozed {ask_id}", 0


@pytest.fixture
def setup_bot():
    def make(items, **kw):
        world, api = World(items), FakeAPI()
        bot = tg.Bot(TOKEN, {"owner_id": OWNER, "chat_id": OWNER}, api=api, queue_fn=world.queue,
                     answer_fn=world.answer, done_fn=world.mark_done, snooze_fn=world.snooze, **kw)
        with bot.lock:
            bot.fresh_card()
        bot.send_card()
        return bot, api, world
    return make


def tap(bot, op, *, frm=OWNER, msg=None, k=None, qid="q1"):
    card = bot.card
    data = op if k is False else f"{op}.{k or card['k']}"
    bot.handle({"update_id": 1, "widget_query": {"id": qid, "from": {"id": frm}, "chat": {"id": frm, "type": "private"},
                                                 "message_id": msg or card["msg"], "data": data}})
    if bot.worker:
        bot.worker.join(5)


def text(bot, t, frm=OWNER):
    bot.handle({"update_id": 2, "message": {"from": {"id": frm}, "chat": {"id": frm, "type": "private"}, "text": t}})


# --- the widget -------------------------------------------------------------------------------

def test_widget_fits_the_send_widget_limits():
    raw, packed = tg_card.html_sizes()
    assert raw <= tg_card.HTML_MAX == 32768
    assert packed <= tg_card.HTML_ZLIB_MAX == 4096
    assert packed == len(zlib.compress(tg_card.build_html().encode(), 9))


def test_widget_uses_theme_variables_only():
    html = tg_card.build_html()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", html)
    colours = re.findall(r"(?:color|background|border-left):([^;}]+)", html)
    assert colours and all("var(--tg-theme-" in c for c in colours)


def test_widget_never_injects_html_and_sends_only_opcodes():
    html = tg_card.build_html()
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html and "eval(" not in html
    assert re.findall(r"W\.request\(([^)]*)\)", html) == ["op+'.'+S.k"]


def test_fit_keeps_a_card_under_the_state_limit_and_never_cuts_an_option():
    opts = ["Ä" * 80, "B" * 80, "C" * 80]
    card = {"v": 1, "m": "a", "k": "abcdefgh", "p": "漢字" * 30, "q": "漢" * 600, "o": opts, "r": "x" * 300}
    out = tg_card.fit(card)
    assert tg_card.size(out) <= tg_card.STATE_BUDGET
    assert all(o in opts for o in out["o"])            # whole options or none
    assert len(json.dumps({"c": out}, ensure_ascii=False).encode()) <= 1024


def test_question_is_cut_to_200_characters():
    assert len(tg_card.display_question("word " * 100)) == tg_card.QUESTION_MAX


# --- who may act ------------------------------------------------------------------------------

def test_stranger_taps_and_messages_are_ignored_without_content(setup_bot, capsys):
    bot, api, world = setup_bot([_ask("a1", options=["Yes", "No"])])
    tap(bot, "0", frm=STRANGER)
    text(bot, "please run rm -rf", frm=STRANGER)
    assert world.delivered == [] and api.of("answerWidgetQuery") == [] and api.of("sendMessage") == []
    out = capsys.readouterr().out
    assert out.count('"event": "ignored"') == 2
    assert "rm -rf" not in out and str(STRANGER) not in out


def test_a_bot_or_another_chat_is_not_the_owner(setup_bot):
    bot, _api, _world = setup_bot([_ask("a1", options=["Yes"])])
    assert not bot.is_owner({"id": OWNER, "is_bot": True}, {"id": OWNER, "type": "private"})
    assert not bot.is_owner({"id": OWNER}, {"id": -5, "type": "group"})
    assert not bot.is_owner({"id": str(OWNER)}, {"id": OWNER, "type": "private"})


# --- one tap answers, once --------------------------------------------------------------------

def test_tap_delivers_the_stored_option_once_and_advances(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Merge it", "Wait"]), _ask("a2")])
    assert bot.card["view"]["o"] == ["Merge it", "Wait"] and bot.card["view"]["n"] == 2
    first_k = bot.card["k"]
    tap(bot, "0")
    assert world.delivered == [("a1", "Merge it", False)]          # clipboard=False: never the copy-and-open fallback
    reply = api.answers()[-1]
    assert reply["c"]["q"].startswith("Which way for a2") and reply["c"]["n"] == 1
    assert "Sent to cellar via claude-bg" in reply["c"]["r"]
    assert api.of("editMessageWidgetData")[-1]["chat_data"] == tg_card.encode(bot.card["view"])
    # a retry with the same nonce (the widget timed out) is answered, never delivered again
    tap(bot, "0", k=first_k, qid="q2")
    assert len(world.delivered) == 1
    assert api.answers()[-1]["e"] in ("Already handled.", "This card changed. Look again.")


def test_malformed_and_free_text_requests_deliver_nothing(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    for data in ("rm -rf ~", "0." + "a" * 9, "9.abcdefgh", "0.ABCDEFGH", "0.abcdefgh\n", ""):
        tap(bot, data, k=False)
    assert world.delivered == []
    assert all("Unknown tap" in a["e"] for a in api.answers())


def test_wrong_nonce_or_old_message_delivers_nothing(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    tap(bot, "0", k="zzzzzzzz")
    tap(bot, "0", msg=1)
    assert world.delivered == []
    assert [a["e"] for a in api.answers()] == ["This card changed. Look again.",
                                               "This card is old. Send /asks for the current one."]


def test_an_option_that_is_not_on_the_card_is_refused(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    tap(bot, "2")
    tap(bot, "c")
    assert world.delivered == []


def test_failed_delivery_stays_on_the_ask_with_a_new_nonce(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    world.answer_result = {"ok": False, "via": "", "detail": "needs the Mac"}
    k = bot.card["k"]
    tap(bot, "0")
    assert bot.card["ask"] == "a1" and bot.card["k"] != k
    assert bot.card["view"]["r"] == "Not sent: needs the Mac"


def test_changed_question_is_not_answered(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    world.items["a1"].question = "A different question now?"
    tap(bot, "0")
    assert world.delivered == []
    assert "changed since the card was drawn" in bot.card["view"]["r"]


def test_gate_and_reminder_get_no_answer_buttons(setup_bot):
    bot, api, world = setup_bot([_ask("g1", options=["approve", "reject"], harness="teyla", kind="gate")])
    assert bot.card["view"]["d"] == 0 and "o" not in bot.card["view"]
    assert set(bot.card["ops"]) == {"z", "d", "s"}
    text(bot, "approve")
    assert world.delivered == [] and "No question on the card" in api.of("sendMessage")[-1]["text"]


# --- snooze, done, skip -----------------------------------------------------------------------

def test_snooze_done_and_skip(setup_bot):
    bot, api, world = setup_bot([_ask("a1"), _ask("a2"), _ask("a3")])
    tap(bot, "z")
    assert world.snoozed == ["a1"] and bot.card["ask"] == "a2"
    tap(bot, "s")
    assert bot.card["ask"] == "a3"
    tap(bot, "d")
    assert world.done == ["a3"] and bot.card["ask"] == "a2"     # the skipped one comes back last
    assert world.delivered == []


def test_empty_queue_shows_the_empty_card(setup_bot):
    bot, api, world = setup_bot([])
    assert bot.card["view"]["m"] == "e" and bot.card["ops"] == {}


# --- a typed answer ---------------------------------------------------------------------------

def test_typed_answer_needs_the_confirm_tap_and_sends_it_exactly(setup_bot):
    bot, api, world = setup_bot([_ask("a1")])
    assert bot.card["view"]["d"] == 1 and "o" in bot.card["view"] and bot.card["view"]["o"] == []
    first_msg = bot.card["msg"]
    text(bot, "Use the second plan,\nand keep the old flag.")
    assert world.delivered == []
    assert bot.card["view"]["m"] == "f" and bot.card["view"]["f"] == "Use the second plan,\nand keep the old flag."
    assert bot.card["msg"] != first_msg                         # a new message below; the old one says it moved
    assert json.loads(api.of("editMessageWidgetData")[-1]["chat_data"]) == {"v": 1, "m": "x"}
    tap(bot, "c")
    assert world.delivered == [("a1", "Use the second plan,\nand keep the old flag.", False)]


def test_typed_answer_cancel_and_limits(setup_bot):
    bot, api, world = setup_bot([_ask("a1")])
    text(bot, "x" * (tg.FREE_MAX_BYTES + 1))
    assert "Too long" in api.of("sendMessage")[-1]["text"]
    text(bot, "bad\x07bell")
    assert "control characters" in api.of("sendMessage")[-1]["text"]
    text(bot, "fine")
    tap(bot, "x")
    assert world.delivered == [] and bot.card["view"]["m"] == "a" and bot.card["view"]["r"] == "Not sent."


def test_slash_asks_resends_the_card(setup_bot):
    bot, api, world = setup_bot([_ask("a1")])
    n = len(api.of("sendWidget"))
    text(bot, "/asks")
    assert len(api.of("sendWidget")) == n + 1
    sent = api.of("sendWidget")[-1]
    assert sent["allow_queries"] is True and sent["html"] == tg_card.build_html()


# --- limits and crashes -----------------------------------------------------------------------

def test_deliveries_are_rate_limited(setup_bot):
    clock = [1000.0]
    bot, api, world = setup_bot([_ask(f"a{i}", options=["Yes"]) for i in range(30)], clock=lambda: clock[0])
    tap(bot, "0")
    tap(bot, "0")                                               # within DELIVERY_GAP_S
    assert len(world.delivered) == 1 and "answers an hour" in api.answers()[-1]["e"]
    for _ in range(tg.DELIVERY_PER_HOUR + 3):
        clock[0] += tg.DELIVERY_GAP_S
        tap(bot, "0")
    assert len(world.delivered) == tg.DELIVERY_PER_HOUR


def test_a_claim_cut_off_by_a_crash_is_reported_never_retried(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    bot.card["busy"] = {"op": "0", "ask": "a1", "ts": 1}
    bot.save()
    again = tg.Bot(TOKEN, {"owner_id": OWNER, "chat_id": OWNER}, api=api, queue_fn=world.queue,
                   answer_fn=world.answer, done_fn=world.mark_done, snooze_fn=world.snooze)
    again.recover()
    assert world.delivered == [] and "interrupted" in again.card["view"]["r"]
    assert "busy" not in again.card


def test_offset_is_saved_before_an_update_is_handled(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    seen = []
    bot.handle = lambda u: seen.append(tg._read_json(tg.state_path())["offset"])
    api.batches.append([{"update_id": 41, "message": {}}, {"update_id": 42, "message": {}}])
    bot.poll_once()
    assert seen == [42, 43]


def test_heartbeat_moves_past_an_ask_closed_elsewhere(setup_bot):
    bot, api, world = setup_bot([_ask("a1"), _ask("a2")])
    world.items["a1"].status = "done"
    bot._queue = None                      # the heartbeat rescans at most every HEARTBEAT_QUEUE_S
    bot.heartbeat()
    assert bot.card["ask"] == "a2" and "closed elsewhere" in bot.card["view"]["r"]


def test_tap_while_working_is_not_a_second_delivery(setup_bot):
    bot, api, world = setup_bot([_ask("a1", options=["Yes"])])
    gate = threading.Event()
    slow = world.answer

    def answer(a, text, clipboard=True):
        gate.wait(5)
        return slow(a, text, clipboard)
    bot.answer_fn = answer
    tg.TAP_WAIT_S, saved = 0.05, tg.TAP_WAIT_S
    try:
        card_k = bot.card["k"]
        bot.handle({"update_id": 1, "widget_query": {"id": "q1", "from": {"id": OWNER}, "chat": {"id": OWNER},
                                                     "message_id": bot.card["msg"], "data": f"0.{card_k}"}})
        assert api.answers()[-1]["c"]["m"] == "w"
        bot.handle({"update_id": 2, "widget_query": {"id": "q2", "from": {"id": OWNER}, "chat": {"id": OWNER},
                                                     "message_id": bot.card["msg"], "data": f"0.{card_k}"}})
        assert api.answers()[-1]["e"] == "Still working on the last tap."
        gate.set()
        bot.worker.join(5)
    finally:
        tg.TAP_WAIT_S = saved
    assert len(world.delivered) == 1


# --- the token and the pairing ----------------------------------------------------------------

def test_call_scrubs_the_token_from_errors(monkeypatch):
    def boom(url, body, timeout):
        raise OSError(f"cannot reach {url}")
    monkeypatch.setattr(tg, "_post", boom)
    with pytest.raises(tg.TgError) as e:
        tg.call(TOKEN, "getMe")
    assert TOKEN not in str(e.value) and "<token>" in str(e.value)

    monkeypatch.setattr(tg, "_post", lambda u, b, t: json.dumps({"ok": False, "error_code": 401,
                                                                 "description": "Unauthorized"}).encode())
    with pytest.raises(tg.TgError, match="401 Unauthorized"):
        tg.call(TOKEN, "getMe")


def test_call_is_refused_in_safe_mode(monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    monkeypatch.setattr(tg, "_post", lambda *a: pytest.fail("network in safe mode"))
    with pytest.raises(tg.TgError):
        tg.call(TOKEN, "getMe")


def test_pairing_takes_only_the_exact_code_from_a_private_chat():
    api = FakeAPI()
    api.batches = [[
        {"update_id": 1, "message": {"text": "/start wrongcode", "from": {"id": STRANGER}, "chat": {"id": STRANGER, "type": "private"}}},
        {"update_id": 2, "message": {"text": "/start c0de", "from": {"id": STRANGER}, "chat": {"id": -9, "type": "group"}}},
        {"update_id": 3, "message": {"text": "/start c0de", "from": {"id": 7, "is_bot": True}, "chat": {"id": 7, "type": "private"}}},
        {"update_id": 4, "message": {"text": "/start c0de", "from": {"id": OWNER}, "chat": {"id": OWNER, "type": "private"}}},
    ]]
    assert tg.pair(TOKEN, "c0de", wait_s=5, api=api) == {"owner_id": OWNER, "chat_id": OWNER}
    assert api.of("getUpdates")[-1]["offset"] == 5


def test_setup_rejects_a_non_token_and_pairs_with_a_real_one(monkeypatch):
    out: list[str] = []
    assert tg.setup(read_token=lambda: "not a token", out=out.append) == 1
    assert TOKEN not in "\n".join(out)
    stored = []
    monkeypatch.setattr(tg, "store_token", stored.append)
    api = FakeAPI()
    monkeypatch.setattr(tg, "secrets", type("S", (), {"token_hex": staticmethod(lambda n: "c0de")}))
    api.batches = [[{"update_id": 9, "message": {"text": "/start c0de", "from": {"id": OWNER},
                                                  "chat": {"id": OWNER, "type": "private"}}}]]
    assert tg.setup(read_token=lambda: TOKEN, out=out.append, no_agent=True, api_for=lambda t: api, wait_s=5) == 0
    assert stored == [TOKEN]
    assert tg.read_cfg()["owner_id"] == OWNER
    assert oct(tg.cfg_path().stat().st_mode & 0o777) == "0o600"
    assert TOKEN not in "\n".join(out)
    assert "https://t.me/example_teyla_bot?start=c0de" in "\n".join(out)


def test_check_says_what_is_missing():
    rows, ok = tg.check(tok="")
    assert not ok and dict((n, o) for n, o, _ in rows)["token"] is False


def test_digest_is_off_by_default_and_once_a_day(setup_bot):
    bot, api, world = setup_bot([_ask("a1")])
    assert not bot.digest_due(1e9)
    bot.cfg["digest"] = "00:00"
    assert bot.digest_due(1e9)
    bot.digest(1e9)
    assert not bot.digest_due(1e9)
    assert api.of("sendMessage")[-1]["text"].startswith("1 question waits")
