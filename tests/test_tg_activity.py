"""`teyla tg activity`: the activity widget, against a fake Bot API. No network, no Keychain, no `gh`."""
from __future__ import annotations

import datetime as dt
import json
import re
import zlib

import pytest

from teyla import tg, tg_activity

OWNER, STRANGER = 1001, 2002
TOKEN = "123456789:" + "A" * 35
NOW = dt.datetime(2026, 11, 12, 14, 30).timestamp()      # a Thursday


def graph(today="2026-11-12", weeks=26, count=5, level=4, streak=9):
    t = dt.date.fromisoformat(today)
    start = t - dt.timedelta(days=t.weekday() + 7 * (weeks - 1))
    days, d = [], start
    while d <= t:
        days.append({"day": d.isoformat(), "count": count, "level": level})
        d += dt.timedelta(days=1)
    return {"start": start.isoformat(), "today": today, "days": days, "today_count": count, "streak": streak}


class FakeAPI:
    def __init__(self):
        self.calls, self.msg, self.fail = [], 200, None

    def __call__(self, method, params=None, timeout=30):
        self.calls.append((method, dict(params or {})))
        if method == "editMessageWidgetData" and self.fail:
            raise tg.TgError(self.fail)
        if method == "sendWidget":
            self.msg += 1
            return {"message_id": self.msg}
        return True

    def of(self, method):
        return [p for m, p in self.calls if m == method]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    return tmp_path


def make(home, growth=None, github=None, clock=None):
    api = FakeAPI()
    box = {"g": growth if growth is not None else graph(), "c": github, "t": NOW}
    bot = tg.Bot(TOKEN, {"owner_id": OWNER, "chat_id": OWNER}, api=api, queue_fn=lambda n: ({}, []),
                 activity_fn=lambda now: (box["g"], box["c"]), clock=clock or (lambda: box["t"]))
    return bot, api, box


def msg(bot, text, frm=OWNER):
    bot.handle({"update_id": 1, "message": {"from": {"id": frm}, "chat": {"id": frm, "type": "private"}, "text": text}})


# --- state ------------------------------------------------------------------------------------

def test_state_with_full_data_and_large_counts_fits_the_budget():
    big = graph(count=123456, streak=99999)
    raw = tg_activity.state(big, graph(count=98765), NOW)
    assert len(raw.encode()) <= tg_activity.STATE_BUDGET
    st = json.loads(raw)
    assert len(st["g"][2]) <= 182 and len(st["c"][2]) <= 182
    assert st["g"][0] == 123456 and st["d"] == "2026-11-12" and st["h"] == "14:30" and st["t"] == int(NOW)


def test_state_digits_and_start_monday():
    st = json.loads(tg_activity.state(graph(), None, NOW))
    assert dt.date.fromisoformat(st["s"]).weekday() == 0
    assert len(st["g"][2]) == 25 * 7 + 4                  # 25 full weeks and Mon..Thu
    assert set(st["g"][2]) == {"4"}


def test_state_cuts_a_longer_graph_to_whole_weeks():
    st = json.loads(tg_activity.state(graph(weeks=53), None, NOW))
    assert len(st["g"][2]) <= 182
    assert dt.date.fromisoformat(st["s"]).weekday() == 0
    end = dt.date.fromisoformat(st["s"]) + dt.timedelta(days=len(st["g"][2]) - 1)
    assert end.isoformat() == "2026-11-12"


def test_state_without_github_omits_it():
    st = json.loads(tg_activity.state(graph(), None, NOW))
    assert "c" not in st and "g" in st
    only = json.loads(tg_activity.state(None, graph(), NOW))
    assert "g" not in only and "c" in only


def test_key_ignores_the_clock():
    a = tg_activity.state(graph(), None, NOW)
    b = tg_activity.state(graph(), None, NOW + 600)
    assert a != b and tg_activity.key(a) == tg_activity.key(b)


# --- the widget -------------------------------------------------------------------------------

def test_widget_fits_the_send_widget_limits():
    raw, packed = tg_activity.html_sizes()
    assert raw <= tg_activity.HTML_MAX == 32768
    assert packed <= tg_activity.HTML_ZLIB_MAX == 4096
    assert packed == len(zlib.compress(tg_activity.build_html().encode(), 9))


def test_widget_never_injects_html_and_uses_theme_colours_only():
    html = tg_activity.build_html()
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html and "eval(" not in html
    assert "outerHTML" not in html and "document.write" not in html and "fetch(" not in html
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", html)
    colours = re.findall(r"(?:color|background|fill):([^;}]+)", html)
    assert colours and all("var(--tg-theme-" in c for c in colours)


# --- the bot ----------------------------------------------------------------------------------

def test_send_stores_the_id(home):
    bot, api, _ = make(home)
    assert bot.send_activity() == 201
    sent = api.of("sendWidget")[0]
    assert sent["height"] == 0 and sent["chat_id"] == OWNER and sent["html"] == tg_activity.build_html()
    assert len(sent["chat_data"].encode()) <= tg_activity.STATE_BUDGET
    assert tg.read_cfg()["activity_msg"] == 201 and tg.read_cfg()["activity_hash"]


def test_push_does_nothing_without_activity_msg(home):
    bot, api, _ = make(home)
    bot.push_activity()
    assert api.calls == []


def test_push_edits_only_on_change(home):
    bot, api, box = make(home)
    bot.send_activity()
    box["t"] += 300
    bot.push_activity()
    assert api.of("editMessageWidgetData") == []           # same numbers, five minutes later
    box["g"] = graph(count=6)
    bot.push_activity()
    edits = api.of("editMessageWidgetData")
    assert len(edits) == 1 and edits[0]["message_id"] == 201 and edits[0]["chat_id"] == OWNER
    assert json.loads(edits[0]["chat_data"])["g"][0] == 6
    box["t"] += 300
    bot.push_activity()
    assert len(api.of("editMessageWidgetData")) == 1


def test_push_refreshes_at_least_every_15_minutes(home):
    bot, api, box = make(home)
    bot.send_activity()
    box["t"] += tg.ACTIVITY_REFRESH_S + 1
    bot.push_activity()
    assert len(api.of("editMessageWidgetData")) == 1


def test_message_not_found_clears_the_id(home):
    bot, api, box = make(home)
    bot.send_activity()
    box["g"] = graph(count=7)
    api.fail = "editMessageWidgetData: 400 Bad Request: message to edit not found"
    bot.push_activity()
    c = tg.read_cfg()
    assert "activity_msg" not in c and "activity_hash" not in c
    api.calls.clear()
    bot.push_activity()
    assert api.calls == []


def test_other_edit_errors_keep_the_id(home):
    bot, api, box = make(home)
    bot.send_activity()
    box["g"] = graph(count=7)
    api.fail = "editMessageWidgetData: 429 Too Many Requests"
    bot.push_activity()
    assert tg.read_cfg()["activity_msg"] == 201


def test_heartbeat_pushes_the_widget(home):
    bot, api, box = make(home)
    bot.send_activity()
    box["g"] = graph(count=8)
    bot.heartbeat()
    assert len(api.of("editMessageWidgetData")) == 1


def test_activity_command_from_the_owner_sends_a_widget(home):
    bot, api, _ = make(home)
    msg(bot, "/activity")
    assert len(api.of("sendWidget")) == 1 and tg.read_cfg()["activity_msg"] == 201


def test_activity_command_from_a_stranger_is_ignored(home):
    bot, api, _ = make(home)
    msg(bot, "/activity", frm=STRANGER)
    assert api.calls == [] and "activity_msg" not in tg.read_cfg()


def test_cli_off_forgets_the_message(home, monkeypatch, capsys):
    bot, api, _ = make(home)
    bot.send_activity()
    monkeypatch.setattr(tg, "_bot_or_error", lambda: (bot, ""))
    args = type("A", (), {"action": "activity", "value": "off", "json": False, "no_agent": False})()
    assert tg.cmd_tg(args) == 0
    assert "activity_msg" not in tg.read_cfg()
    assert "no more edits" in capsys.readouterr().out
