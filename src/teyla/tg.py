"""`teyla tg` — your open questions as a card in a private Telegram chat (`docs/ASKS.md`, "Telegram").

    teyla tg setup [--no-agent]     paste the bot token (read hidden), pair your Telegram account, start the agent
    teyla tg check [--json]         token, pairing, agent, last poll: prints OK when all four hold
    teyla tg send                   send the current card again (the same as /asks in the chat)
    teyla tg digest HH:MM|off       one morning line with the count of waiting questions (off by default)
    teyla tg serve                  the long-poll loop the launchd agent runs
    teyla tg off                    stop the agent; the token and the pairing stay

There is no server and no webhook. The launchd agent `com.zaitsew.teyla.tg` long-polls `getUpdates` from the
laptop. When the laptop sleeps nothing answers, and the card shows "Laptop offline since HH:MM" from the time of
its last edit (the agent rewrites the card every HEARTBEAT_S seconds).

A tap here can make Teyla type into a coding session that runs with bypassed permissions, so this path does
exactly what `teyla answer`, `teyla asks done` and `teyla asks snooze` do, and nothing more:

1. **One person.** Only the Telegram user id paired by `teyla tg setup`, in its private chat with the bot, can act.
   Telegram authenticates `from`. Every other update is dropped and logged as "ignored", without its content.
   Pairing needs a one-time code that `setup` prints and that Telegram's deep link sends back.
2. **No free text from the widget.** A tap sends `<op>.<nonce>`: one opcode character and the card's 8-character
   nonce, matched in full against `OP_RE`. The opcode maps to an option stored here, on the laptop; the text sent
   to a session is that stored option, never anything the widget sent. A nonce is used once: a second tap with it
   (a retry after a timeout, a replay) gets "already handled" and the current card, and never delivers again.
3. **A typed answer needs a tap.** A text message becomes a confirm card that shows the exact text; only the Send
   tap on that card delivers it.
4. **Same delivery.** `answer.answer(ask, text, clipboard=False)`, the call the CLI and the iPhone relay make, with
   its transcript confirmation; `asks.mark_done` and `asks.snooze` for Done already and Snooze. Before delivery
   the ask must still be open and its question unchanged since the card was drawn.
5. **Rate limits.** At most DELIVERY_PER_HOUR answers an hour and one every DELIVERY_GAP_S seconds.
6. **At most once.** The update offset is saved before an update is handled, the nonce is claimed before the work
   starts, and a lock file lets one `serve` run at a time. A claim cut off by a crash is reported as
   "interrupted" on the next start and never retried.

The bot token lives in the macOS Keychain (service `teyla-telegram`), written through `security -i` on stdin, never
printed or logged. The pairing (your user and chat ids) lives in `~/.teyla/tg.json`, mode 600, never in a repo.
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import fcntl
import getpass
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from . import asks, config, net
from . import routine_install as ri
from . import tg_card

LABEL = "com.zaitsew.teyla.tg"
KEYCHAIN_SERVICE = "teyla-telegram"
KEYCHAIN_ACCOUNT = "bot"
API = "https://api.telegram.org/bot{token}/{method}"

POLL_TIMEOUT_S = 20            # long poll; also how long `teyla tg send` may wait for the agent to pick it up
HEARTBEAT_S = 300              # rewrite the card this often, so the widget can tell the laptop is offline
POLL_FRESH_S = 120             # `check`: the agent polled within this window
TAP_WAIT_S = 9.0               # answer a tap with the next card when the work is done within this; else "working"
DELIVERY_GAP_S = 5
DELIVERY_PER_HOUR = 20
QUEUE_TTL_S = 60
USED_KEEP = 64
FREE_MAX_BYTES = 600           # a typed answer must fit the confirm card whole: it is shown, never cut
PAIR_WAIT_S = 300
TOKEN_RE = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{30,64}", re.ASCII)
OP_RE = re.compile(r"([012zdscx])\.([a-z0-9]{8})", re.ASCII)
ANSWER_OPS = ("0", "1", "2", "c")
DELIVERABLE_HARNESSES = ("claude-desktop", "claude-code", "codex")


class TgError(Exception):
    """A problem the owner can fix; the message says how. Never holds the token."""


# --- paths ------------------------------------------------------------------------------------

def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def cfg_path() -> pathlib.Path:
    return home() / "tg.json"


def state_path() -> pathlib.Path:
    return home() / "tg-state.json"


def lock_path() -> pathlib.Path:
    return home() / "tg.lock"


def resend_flag() -> pathlib.Path:
    return home() / "tg-resend"


def plist_path() -> pathlib.Path:
    return ri.PLIST_PATH.parent / f"{LABEL}.plist"


def wrapper_path() -> pathlib.Path:
    return ri.WRAPPER_PATH.parent / "tg.sh"


def log_path() -> pathlib.Path:
    return ri.LOG_PATH.parent / "teyla-tg.log"


def _read_json(path: pathlib.Path) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_private(path: pathlib.Path, data: dict) -> None:
    """Owner-only, written by rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_cfg() -> dict:
    return _read_json(cfg_path())


def write_cfg(c: dict) -> None:
    _write_private(cfg_path(), c)


def _now() -> float:
    return time.time()


def _hm(epoch: float) -> str:
    return _dt.datetime.fromtimestamp(epoch).strftime("%H:%M")


def log(event: str, **fields) -> None:
    """One JSON line on stdout (the agent's log). Callers pass ids, opcodes and outcomes; never message text,
    never the token, never another person's id."""
    print(json.dumps({"ts": _dt.datetime.now().isoformat(timespec="seconds"), "event": event, **fields}), flush=True)


# --- the token --------------------------------------------------------------------------------

def token() -> str | None:
    """The bot token from the Keychain, or None. Stored base64 so `security -i` can quote it safely."""
    if not shutil.which("security"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        tok = base64.b64decode(r.stdout.strip(), validate=True).decode("ascii")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return tok if TOKEN_RE.fullmatch(tok) else None


def store_token(tok: str) -> None:
    if not shutil.which("security"):
        raise TgError("the macOS `security` tool is missing: the Keychain is the only place the token may live")
    b64 = base64.b64encode(tok.encode("ascii")).decode("ascii")
    cmd = (f'add-generic-password -U -s "{KEYCHAIN_SERVICE}" -a "{KEYCHAIN_ACCOUNT}" '
           f'-l "Teyla Telegram bot" -w "{b64}"\n')
    try:
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise TgError(f"could not write the Keychain ({type(e).__name__})") from None
    if r.returncode != 0 or "error" in (r.stderr or "").lower():
        raise TgError("could not write the Keychain (security returned an error)")


# --- the Bot API ------------------------------------------------------------------------------

def _post(url: str, body: bytes, timeout: float) -> bytes:
    """The one function that talks to the network. Tests replace it with a fake Bot API."""
    from .update import ssl_context
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:  # noqa: S310 — one fixed host
            return r.read()
    except urllib.error.HTTPError as e:      # Telegram answers errors with a JSON body: hand it back
        return e.read()


def call(tok: str, method: str, params: dict | None = None, timeout: float = 30) -> dict | list | bool:
    """One Bot API call; the `result`, or TgError with Telegram's description. The token is in the URL only, and
    is scrubbed from any message."""
    if not net.allowed():
        raise TgError(net.refusal("teyla tg"))
    url = API.format(token=tok, method=method)
    try:
        raw = _post(url, json.dumps(params or {}, ensure_ascii=False).encode("utf-8"), timeout)
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as e:
        raise TgError(f"{method}: {type(e).__name__}: {str(e).replace(tok, '<token>')[:200]}") from None
    if not isinstance(data, dict) or not data.get("ok"):
        desc = str((data or {}).get("description") if isinstance(data, dict) else "no answer")
        code = (data or {}).get("error_code") if isinstance(data, dict) else None
        raise TgError(f"{method}: {code or ''} {desc.replace(tok, '<token>')[:200]}".strip())
    return data.get("result")


# --- the queue --------------------------------------------------------------------------------

def load_queue(now: float) -> tuple[dict, list[dict]]:
    """({ask id: Ask}, open rows most important first, muted ones left out): the order of `teyla asks triage`."""
    from . import triage
    items, rows, _st, _ = triage._context(now)
    return {a.id: a for a in items}, [r for r in rows if not r.get("muted")]


def question_hash(a: asks.Ask) -> str:
    return hashlib.sha256(f"{a.title}\n{a.question}".encode("utf-8")).hexdigest()[:16]


def deliverable(a: asks.Ask) -> bool:
    """Can `answer.answer(clipboard=False)` reach this ask's session from here? A gate or a reminder cannot."""
    if a.harness == asks.DESIGN_HARNESS:
        return True
    return a.kind in ("question", "blocked") and a.harness in DELIVERABLE_HARNESSES and bool(a.session)


def options_for(a: asks.Ask, row: dict) -> list[str]:
    """The answers the card offers, recommended first: the options the session attached (a `wrap_up` puts its pick
    first), else triage's proposed answer. Each is sent word for word."""
    opts = [str(o).strip() for o in a.options if str(o).strip() and str(o).strip() != "None"]
    if not opts:
        default = str(((row.get("triage") or {}).get("default")) or "").strip()
        if default:
            opts = [default]
    return opts[: tg_card.OPTIONS_MAX]


def _display(product: str) -> str:
    try:
        from . import registry
        return asks.display_name(registry.load(), product)
    except Exception:  # noqa: BLE001 — a name is cosmetic; a broken registry must not stop the card
        return product


def _new_nonce(used: list[str]) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        k = "".join(secrets.choice(alphabet) for _ in range(8))
        if k not in used:
            return k


# --- the bot ----------------------------------------------------------------------------------

class Bot:
    """The server side of the card. `api(method, params)` calls Telegram; `queue_fn(now)` returns the queue;
    `answer_fn`, `done_fn` and `snooze_fn` are the CLI's own functions (tests pass fakes)."""

    def __init__(self, tok: str, cfg: dict, *, api=None, queue_fn=None, answer_fn=None, done_fn=None,
                 snooze_fn=None, clock=None):
        self.tok, self.cfg = tok, cfg
        self.owner = int(cfg["owner_id"])
        self.chat = int(cfg["chat_id"])
        self.api = api or (lambda m, p=None, timeout=30: call(tok, m, p, timeout))
        self.queue_fn = queue_fn or load_queue
        if answer_fn is None:
            from . import answer as answer_mod
            answer_fn = answer_mod.answer
        self.answer_fn = answer_fn
        self.done_fn = done_fn or (lambda ask_id: asks.mark_done([ask_id], note="done in Telegram"))
        self.snooze_fn = snooze_fn or (lambda ask_id: asks.snooze(ask_id, 1))
        self.clock = clock or _now
        self.lock = threading.RLock()
        self.st = _read_json(state_path())
        self.st.setdefault("offset", 0)
        self.st.setdefault("used", [])
        self.st.setdefault("skipped", {})
        self.st.setdefault("sent", [])
        self._queue: tuple[float, dict, list] | None = None
        self.worker: threading.Thread | None = None

    # -- state --

    def save(self) -> None:
        with self.lock:
            _write_private(state_path(), self.st)

    @property
    def card(self) -> dict:
        return self.st.get("card") or {}

    def queue(self, fresh: bool = False) -> tuple[dict, list]:
        now = self.clock()
        if fresh or self._queue is None or now - self._queue[0] > QUEUE_TTL_S:
            items, rows = self.queue_fn(now)
            self._queue = (now, items, rows)
        return self._queue[1], self._queue[2]

    def next_row(self, items: dict, rows: list, after: str = "") -> dict | None:
        """The first open row, skipped ones last (oldest skip first). `after` is left out unless nothing else is open."""
        live = [r for r in rows if r["id"] in items]
        open_ids = {r["id"] for r in live}
        self.st["skipped"] = {k: v for k, v in self.st["skipped"].items() if k in open_ids}
        skipped = self.st["skipped"]
        order = sorted(live, key=lambda r: (r["id"] in skipped, skipped.get(r["id"], 0)))
        rest = [r for r in order if r["id"] != after]
        return (rest or order or [None])[0]

    # -- cards --

    def _base(self, n: int, result: str = "") -> dict:
        now = self.clock()
        c = {"v": 1, "n": n, "t": int(now), "h": _hm(now)}
        if result:
            c["r"] = result
        return c

    def ask_card(self, a: asks.Ask, row: dict, n: int, result: str = "") -> dict:
        """A new card for `a` with a new nonce, and the ops it allows, stored as `self.st["card"]`."""
        k = _new_nonce(self.st["used"])
        can = deliverable(a)
        view = {**self._base(n, result), "m": "a", "k": k, "p": _display(a.product),
                "q": tg_card.display_question(a.question or a.title), "d": int(can),
                "s": int(((row.get("triage") or {}).get("bucket")) == "close")}
        if can:
            view["o"] = options_for(a, row)
        view = tg_card.fit(view)
        ops = {str(i): {"kind": "answer", "text": t} for i, t in enumerate(view.get("o") or [])}
        ops.update(z={"kind": "snooze"}, d={"kind": "done"}, s={"kind": "skip"})
        self.st["card"] = {"msg": self.card.get("msg"), "k": k, "ask": a.id, "qh": question_hash(a), "ops": ops,
                           "view": view}
        return view

    def confirm_card(self, a: asks.Ask, text: str, n: int) -> dict:
        k = _new_nonce(self.st["used"])
        view = tg_card.fit({**self._base(n), "m": "f", "k": k, "p": _display(a.product), "f": text,
                            "q": tg_card.display_question(a.question or a.title, 80)})
        self.st["card"] = {"msg": self.card.get("msg"), "k": k, "ask": a.id, "qh": question_hash(a),
                           "ops": {"c": {"kind": "answer", "text": text}, "x": {"kind": "cancel"}}, "view": view}
        return view

    def empty_card(self, n: int = 0, result: str = "") -> dict:
        view = {**self._base(n, result), "m": "e"}
        self.st["card"] = {"msg": self.card.get("msg"), "k": "", "ask": "", "qh": "", "ops": {}, "view": view}
        return view

    def fresh_card(self, result: str = "", after: str = "") -> dict:
        items, rows = self.queue(fresh=True)
        row = self.next_row(items, rows, after)
        n = len([r for r in rows if r["id"] in items])
        if row is None:
            return self.empty_card(n, result)
        return self.ask_card(items[row["id"]], row, n, result)

    # -- Telegram --

    def push_view(self) -> None:
        """Write the current card into its message, silently."""
        msg = self.card.get("msg")
        if not msg:
            return
        try:
            self.api("editMessageWidgetData", {"chat_id": self.chat, "message_id": msg,
                                               "chat_data": tg_card.encode(self.card["view"])})
        except TgError as e:
            if "not modified" not in str(e):
                log("edit_failed", detail=str(e)[:120])

    def send_card(self) -> int | None:
        """Retire the old card message and send the current card as a new one."""
        old = self.card.get("msg")
        if old:
            try:
                self.api("editMessageWidgetData", {"chat_id": self.chat, "message_id": old,
                                                   "chat_data": tg_card.encode({"v": 1, "m": "x"})})
            except TgError:
                pass
        res = self.api("sendWidget", {"chat_id": self.chat, "html": tg_card.build_html(), "allow_queries": True,
                                      "chat_data": tg_card.encode(self.card["view"]), "protect_content": True})
        msg = res.get("message_id") if isinstance(res, dict) else None
        with self.lock:
            self.st["card"]["msg"] = msg
            self.save()
        log("card_sent", ask=self.card.get("ask", ""))
        return msg

    def say(self, text: str) -> None:
        try:
            self.api("sendMessage", {"chat_id": self.chat, "text": text})
        except TgError as e:
            log("say_failed", detail=str(e)[:120])

    # -- updates --

    def is_owner(self, frm, chat) -> bool:
        return (isinstance(frm, dict) and isinstance(chat, dict) and type(frm.get("id")) is int
                and frm["id"] == self.owner and chat.get("id") == self.chat
                and chat.get("type", "private") == "private" and not frm.get("is_bot"))

    def handle(self, upd: dict) -> None:
        if not isinstance(upd, dict):
            return
        if "widget_query" in upd:
            self.on_query(upd["widget_query"])
        elif "message" in upd:
            self.on_message(upd["message"])
        else:
            log("ignored", kind="other")

    def answer_query(self, qid: str, payload: dict) -> None:
        try:
            self.api("answerWidgetQuery", {"widget_query_id": qid, "data": json.dumps(payload, ensure_ascii=False,
                                                                                          separators=(",", ":"))})
        except TgError as e:
            log("answer_query_failed", detail=str(e)[:120])

    def on_query(self, q: dict) -> None:
        if not isinstance(q, dict) or not self.is_owner(q.get("from"), q.get("chat")):
            log("ignored", kind="widget_query")
            return
        qid = str(q.get("id") or "")
        data = q.get("data")
        m = OP_RE.fullmatch(data) if isinstance(data, str) else None
        if not m:
            log("refused", reason="malformed")
            self.answer_query(qid, {"e": "Unknown tap. Send /asks for a fresh card."})
            return
        op, k = m.groups()
        with self.lock:
            card = self.card
            if q.get("message_id") != card.get("msg"):
                return self.answer_query(qid, {"e": "This card is old. Send /asks for the current one."})
            if card.get("busy"):
                return self.answer_query(qid, {"c": card["view"], "e": "Still working on the last tap."})
            if k in self.st["used"]:
                return self.answer_query(qid, {"c": card["view"], "e": "Already handled."})
            if k != card.get("k"):
                return self.answer_query(qid, {"c": card["view"], "e": "This card changed. Look again."})
            spec = (card.get("ops") or {}).get(op)
            if not spec:
                return self.answer_query(qid, {"e": "That button is not on this card."})
            if spec["kind"] == "answer" and not self.rate_ok():
                log("refused", reason="rate", op=op)
                return self.answer_query(qid, {"e": f"At most {DELIVERY_PER_HOUR} answers an hour, one every "
                                                    f"{DELIVERY_GAP_S} s. Try again shortly."})
            # Claim before any work: from here the nonce never delivers again, whatever happens next.
            self.st["used"] = (self.st["used"] + [k])[-USED_KEEP:]
            if spec["kind"] == "answer":
                self.st["sent"] = [t for t in self.st["sent"] if self.clock() - t < 3600] + [self.clock()]
            card["busy"] = {"op": op, "ask": card.get("ask"), "ts": self.clock()}
            self.save()
            ask_id, qh = card.get("ask", ""), card.get("qh", "")
        log("tap", op=op, ask=ask_id)
        done = threading.Event()
        self.worker = threading.Thread(target=self._run, args=(spec, ask_id, qh, done), daemon=True)
        self.worker.start()
        if done.wait(TAP_WAIT_S):
            self.answer_query(qid, {"c": self.card["view"]})
        else:
            self.answer_query(qid, {"c": {**self.card["view"], "m": "w"}})

    def rate_ok(self) -> bool:
        now = self.clock()
        recent = [t for t in self.st["sent"] if now - t < 3600]
        return len(recent) < DELIVERY_PER_HOUR and (not recent or now - max(recent) >= DELIVERY_GAP_S)

    def _run(self, spec: dict, ask_id: str, qh: str, done: threading.Event) -> None:
        try:
            result, stay = self.perform(spec, ask_id, qh)
        except Exception as exc:  # noqa: BLE001 — the nonce is claimed: report, never retry
            result, stay = f"Failed ({type(exc).__name__}). Check the session before you answer again.", True
            log("perform_failed", error=type(exc).__name__, ask=ask_id)
        with self.lock:
            self.card.pop("busy", None)
            try:
                self._after(result, ask_id, stay, skip=spec["kind"] == "skip")
            except Exception as exc:  # noqa: BLE001 — a broken queue read must not leave the card busy
                log("queue_failed", error=type(exc).__name__)
                self.empty_card(0, result)
            self.save()
        done.set()
        self.push_view()

    def _after(self, result: str, ask_id: str, stay: bool, skip: bool) -> None:
        """The next card. `stay`: the same ask again (a failed delivery, a cancelled confirm)."""
        items, rows = self.queue(fresh=True)
        n = len([r for r in rows if r["id"] in items])
        if stay and ask_id in items and items[ask_id].status == "open":
            row = next((r for r in rows if r["id"] == ask_id), {})
            self.ask_card(items[ask_id], row, n, result)
            return
        row = self.next_row(items, rows, after=ask_id if skip else "")
        if row is None:
            self.empty_card(n, result)
        else:
            self.ask_card(items[row["id"]], row, n, result)

    def perform(self, spec: dict, ask_id: str, qh: str) -> tuple[str, bool]:
        """Do what the tap asked. Returns (result line, stay on this ask)."""
        kind = spec["kind"]
        if kind == "skip":
            self.st["skipped"][ask_id] = self.clock()
            return "Skipped; it comes back after the others.", False
        if kind == "cancel":
            return "Not sent.", True
        items, _rows = self.queue(fresh=True)
        a = items.get(ask_id)
        if a is None or a.status != "open":
            return "That question was closed elsewhere.", False
        if question_hash(a) != qh:
            return "That question changed since the card was drawn. Look again.", True
        if kind == "snooze":
            line, code = self.snooze_fn(a.id)
            log("snooze", ask=a.id, ok=code == 0)
            return ("Snoozed for 1 day." if code == 0 else "Not snoozed: " + str(line)[:80]), code != 0
        if kind == "done":
            lines, code = self.done_fn(a.id)
            log("done", ask=a.id, ok=code == 0)
            return ("Closed." if code == 0 else "Not closed: " + " ".join(lines)[:80]), code != 0
        if not deliverable(a):
            return "This one cannot be answered from Telegram. Answer it on the Mac.", True
        res = self.answer_fn(a, spec["text"], clipboard=False)
        ok, via, detail = bool(res.get("ok")), str(res.get("via") or ""), str(res.get("detail") or "")
        log("answer", ask=a.id, ok=ok, via=via)
        if not ok:
            return "Not sent: " + detail[:100], True
        name = _display(a.product)
        if "not confirmed" in detail:
            return f"Sent to {name} via {via}; not confirmed yet.", False
        return f"Sent to {name} via {via}.", False

    def on_message(self, msg: dict) -> None:
        if not isinstance(msg, dict) or not self.is_owner(msg.get("from"), msg.get("chat")):
            log("ignored", kind="message")
            return
        text = msg.get("text")
        if not isinstance(text, str) or not text.strip():
            return self.say("Send text, or /asks for the current card.")
        text = text.strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/asks", "/start"):
            with self.lock:
                if self.card.get("busy"):
                    return self.say("Still working on the last tap; the card updates when it is done.")
                self.fresh_card()
                self.save()
            self.send_card()
            return
        if cmd == "/help":
            return self.say("Tap an answer on the card, or reply with text to answer in your own words (you confirm "
                            "it first). /asks sends the current card again.")
        if cmd:
            return self.say("Unknown command. /asks sends the current card; /help says how this works.")
        self.free_text(text)

    def free_text(self, text: str) -> None:
        if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
            return self.say("That text holds control characters; send plain text.")
        if len(text.encode("utf-8")) > FREE_MAX_BYTES:
            return self.say(f"Too long for the card ({len(text)} characters). Keep it under about "
                            f"{FREE_MAX_BYTES // 2} characters, or answer on the Mac.")
        with self.lock:
            card = self.card
            if card.get("busy"):
                return self.say("Still working on the last tap. Send it again in a moment.")
            items, rows = self.queue()
            a = items.get(card.get("ask", ""))
            if a is None or a.status != "open" or not deliverable(a):
                return self.say("No question on the card can take a typed answer now. /asks sends the card.")
            self.confirm_card(a, text, len([r for r in rows if r["id"] in items]))
            self.save()
        log("confirm_card", ask=a.id)
        self.send_card()

    # -- the loop --

    def recover(self) -> None:
        """A tap cut off by a crash: say so, never retry it."""
        busy = self.card.get("busy")
        if busy:
            log("interrupted", op=busy.get("op"), ask=busy.get("ask"))
            self.card.pop("busy", None)
            self.fresh_card(result="The last tap was interrupted. Check the session before you answer again.")
            self.save()
            self.push_view()

    def heartbeat(self) -> None:
        """Rewrite the card: a new time, a new count, and the next ask when this one was closed elsewhere."""
        with self.lock:
            card = self.card
            if card.get("busy") or not card.get("msg"):
                return
            items, rows = self.queue(fresh=True)
            n = len([r for r in rows if r["id"] in items])
            a = items.get(card.get("ask", ""))
            if card.get("ask") and (a is None or a.status != "open" or question_hash(a) != card.get("qh")):
                self.fresh_card(result="The last question was closed elsewhere.")
            elif not card.get("ask") and n:
                self.fresh_card()
            else:
                card["view"].update(n=n, t=int(self.clock()), h=_hm(self.clock()))
            self.save()
        self.push_view()

    def digest_due(self, now: float) -> bool:
        at = str(self.cfg.get("digest") or "")
        if not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", at):
            return False
        d = _dt.datetime.fromtimestamp(now)
        return d.strftime("%H:%M") >= at and self.st.get("digest_day") != d.date().isoformat()

    def digest(self, now: float) -> None:
        items, rows = self.queue(fresh=True)
        n = len([r for r in rows if r["id"] in items])
        self.st["digest_day"] = _dt.datetime.fromtimestamp(now).date().isoformat()
        self.save()
        if n:
            self.say(f"{n} question{' waits' if n == 1 else 's wait'} for you. /asks shows the first one.")

    def poll_once(self) -> None:
        upds = self.api("getUpdates", {"offset": self.st["offset"], "timeout": POLL_TIMEOUT_S,
                                       "allowed_updates": ["message", "widget_query"]}, timeout=POLL_TIMEOUT_S + 15)
        self.st["polled"] = self.clock()
        for u in upds if isinstance(upds, list) else []:
            uid = u.get("update_id") if isinstance(u, dict) else None
            if type(uid) is int:
                with self.lock:          # saved before the update is handled: at most once, even after a crash
                    self.st["offset"] = max(self.st["offset"], uid + 1)
                    self.save()
            self.handle(u)
        self.save()

    def serve(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        self.recover()
        if not self.card.get("msg"):
            with self.lock:
                self.fresh_card()
            self.send_card()
        last_beat = self.clock()
        backoff = 1.0
        while not stop.is_set():
            try:
                if resend_flag().exists():
                    resend_flag().unlink(missing_ok=True)
                    self.on_message({"from": {"id": self.owner}, "chat": {"id": self.chat, "type": "private"},
                                     "text": "/asks"})
                self.poll_once()
                now = self.clock()
                if now - last_beat >= HEARTBEAT_S:
                    last_beat = now
                    self.heartbeat()
                if self.digest_due(now):
                    self.digest(now)
                backoff = 1.0
            except TgError as e:
                log("poll_failed", detail=str(e)[:160])
                stop.wait(30 if "409" in str(e) else backoff)
                backoff = min(backoff * 2, 60)


# --- setup, check, agent ----------------------------------------------------------------------

def pair(tok: str, code: str, wait_s: float = PAIR_WAIT_S, api=None, clock=None) -> dict | None:
    """Wait for `/start <code>` in a private chat; {owner_id, chat_id} of who sent it, or None. Everything else that
    arrives meanwhile is consumed and dropped."""
    api = api or (lambda m, p=None, timeout=30: call(tok, m, p, timeout))
    clock = clock or _now
    end = clock() + wait_s
    offset = 0
    while clock() < end:
        upds = api("getUpdates", {"offset": offset, "timeout": POLL_TIMEOUT_S, "allowed_updates": ["message"]},
                   timeout=POLL_TIMEOUT_S + 15)
        for u in upds if isinstance(upds, list) else []:
            if not isinstance(u, dict) or type(u.get("update_id")) is not int:
                continue
            offset = max(offset, u["update_id"] + 1)
            m = u.get("message") or {}
            frm, chat = m.get("from") or {}, m.get("chat") or {}
            if (m.get("text") == f"/start {code}" and chat.get("type") == "private" and type(frm.get("id")) is int
                    and not frm.get("is_bot") and chat.get("id") == frm["id"]):
                api("getUpdates", {"offset": offset, "timeout": 0})      # acknowledge, so serve starts after it
                return {"owner_id": frm["id"], "chat_id": chat["id"]}
    return None


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{wrapper}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
{env_plist}    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
"""

WRAPPER = """#!/usr/bin/env bash
# Written by `teyla tg setup`; `teyla tg off` removes it. The Telegram card: long-polls the Bot API from this Mac.
set -uo pipefail
{env_sh}
export TEYLA_IN_ROUTINE="{label}"
exec "{teyla_bin}" tg serve
"""


def _x(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def agent_on(load=None) -> list[str]:
    load = ri._load if load is None else load
    teyla_bin = ri._teyla_bin()
    env = ri.launchd_env(teyla_bin)
    wrapper, plist, logf = wrapper_path(), plist_path(), log_path()
    for d in (wrapper.parent, plist.parent, logf.parent):
        d.mkdir(parents=True, exist_ok=True)
    ri._write(wrapper, WRAPPER.format(env_sh=ri._env_sh(env), label=LABEL, teyla_bin=teyla_bin), 0o755)
    ri._write(plist, PLIST.format(label=LABEL, wrapper=_x(str(wrapper)), log=_x(str(logf)),
                                  env_plist=ri._env_plist(env)))
    lines = [f"wrote {wrapper}", f"wrote {plist}"]
    lines.append(load(plist, LABEL) if sys.platform == "darwin" else f"not macOS: run `teyla tg serve` yourself")
    return lines


def agent_off(unload=None) -> list[str]:
    unload = ri._unload if unload is None else unload
    lines = []
    if plist_path().exists() and sys.platform == "darwin":
        lines.append(unload(plist_path(), LABEL))
    for f in (plist_path(), wrapper_path()):
        if f.exists():
            f.unlink()
            lines.append(f"removed {f}")
    return lines or ["the agent was not installed"]


def setup(read_token=None, out=print, no_agent: bool = False, api_for=None, wait_s: float = PAIR_WAIT_S) -> int:
    read_token = read_token or (lambda: getpass.getpass("Bot token from @BotFather (hidden): "))
    if not net.allowed():
        out(net.refusal("teyla tg setup"))
        return 1
    tok = (read_token() or "").strip()
    if not TOKEN_RE.fullmatch(tok):
        out("That is not a bot token. In @BotFather send /newbot (or /token), then paste the line that looks like "
            "123456789:AA…")
        return 1
    api = api_for(tok) if api_for else (lambda m, p=None, timeout=30: call(tok, m, p, timeout))
    try:
        me = api("getMe")
        username = str((me or {}).get("username") or "")
        if plist_path().exists():
            agent_off()                     # one poller at a time: the agent would take the pairing message
        api("deleteWebhook", {"drop_pending_updates": True})
        store_token(tok)
        code = secrets.token_hex(8)
        out(f"Bot @{username} is ready. On your phone open https://t.me/{username}?start={code} and tap Start.")
        out(f"Waiting up to {int(wait_s // 60)} minutes…")
        who = pair(tok, code, wait_s, api=api)
        if who is None:
            out("No /start with the code arrived. Run `teyla tg setup` again.")
            return 1
        c = read_cfg()
        c.update(who, bot=username, paired=_dt.datetime.now().isoformat(timespec="seconds"))
        write_cfg(c)
        api("sendMessage", {"chat_id": who["chat_id"], "text": "Paired with Teyla on your Mac. Your open questions "
                            "arrive here as one card. /asks sends it again."})
    except TgError as e:
        out(f"teyla tg setup: {e}")
        return 1
    out("paired; the pairing is in " + str(cfg_path()))
    if not no_agent:
        for line in agent_on():
            out(line)
        out("The first card arrives in the chat within a minute. `teyla tg check` should print OK.")
    return 0


def check(api_for=None, tok: str | None = None) -> tuple[list[tuple[str, bool, str]], bool]:
    """[(name, ok, detail)], all ok."""
    rows: list[tuple[str, bool, str]] = []
    tok = tok if tok is not None else token()
    rows.append(("token", bool(tok), "in the Keychain" if tok else "missing: run `teyla tg setup`"))
    if tok:
        api = api_for(tok) if api_for else (lambda m, p=None, timeout=30: call(tok, m, p, timeout))
        try:
            me = api("getMe")
            rows.append(("bot", True, "@" + str((me or {}).get("username") or "?")))
        except TgError as e:
            rows.append(("bot", False, str(e)[:160]))
    c = read_cfg()
    paired = type(c.get("owner_id")) is int and type(c.get("chat_id")) is int
    rows.append(("paired", paired, "one owner" if paired else "not paired: run `teyla tg setup`"))
    agent = plist_path().exists()
    rows.append(("agent", agent, LABEL if agent else "not installed: run `teyla tg setup`"))
    polled = _read_json(state_path()).get("polled")
    fresh = isinstance(polled, (int, float)) and _now() - polled < POLL_FRESH_S
    rows.append(("polling", fresh, (f"last poll {int(_now() - polled)} s ago" if isinstance(polled, (int, float))
                                    else "never polled") + ("" if fresh else f"; log: {log_path()}")))
    return rows, all(ok for _, ok, _ in rows)


class _Lock:
    """One `serve` (or direct `send`) at a time: two pollers could hand one tap to both."""

    def __init__(self):
        self.fh = None

    def acquire(self) -> bool:
        lock_path().parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(lock_path(), "a")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False


def _bot_or_error() -> tuple[Bot | None, str]:
    if config.safe_mode() and not net.allowed():
        return None, "safe mode is on: `teyla tg` does not reach Telegram"
    tok = token()
    c = read_cfg()
    if not tok:
        return None, "no bot token: run `teyla tg setup`"
    if type(c.get("owner_id")) is not int or type(c.get("chat_id")) is not int:
        return None, "not paired: run `teyla tg setup`"
    return Bot(tok, c), ""


def cmd_tg(args) -> int:
    act = args.action
    if act == "setup":
        return setup(no_agent=args.no_agent)
    if act == "check":
        rows, ok = check()
        if args.json:
            print(json.dumps({"ok": ok, "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in rows]}))
        else:
            for n, o, d in rows:
                print(f"{'ok ' if o else 'NO '} {n:<8} {d}")
            print("OK" if ok else "not ready")
        return 0 if ok else 1
    if act == "off":
        print("\n".join(agent_off()))
        print("the token and the pairing stay; `teyla tg setup` starts again")
        return 0
    if act == "digest":
        at = (args.value or "").strip()
        if at != "off" and not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", at):
            print("usage: teyla tg digest HH:MM|off", file=sys.stderr)
            return 64
        c = read_cfg()
        c["digest"] = None if at == "off" else at
        write_cfg(c)
        print("morning digest off" if at == "off" else f"morning digest at {at}; the agent reads it within a minute")
        return 0
    bot, err = _bot_or_error()
    if bot is None:
        print(f"teyla tg: {err}", file=sys.stderr)
        return 1
    lock = _Lock()
    if act == "send":
        if not lock.acquire():
            resend_flag().parent.mkdir(parents=True, exist_ok=True)
            resend_flag().touch()
            print(f"the agent sends the card within {POLL_TIMEOUT_S} s")
            return 0
        try:
            with bot.lock:
                bot.fresh_card()
            bot.send_card()
        except TgError as e:
            print(f"teyla tg send: {e}", file=sys.stderr)
            return 1
        print("card sent")
        return 0
    if not lock.acquire():
        print("teyla tg: another `teyla tg serve` is running", file=sys.stderr)
        return 1
    log("serve_start")
    try:
        bot.serve()
    except KeyboardInterrupt:
        pass
    return 0


def register(sp):
    q = sp.add_parser("tg", help="your open questions as a card in a private Telegram chat")
    q.set_defaults(fn=cmd_tg)
    q.add_argument("action", choices=["setup", "check", "send", "digest", "serve", "off"])
    q.add_argument("value", nargs="?", help="digest: HH:MM or off")
    q.add_argument("--json", action="store_true", help="check: print JSON")
    q.add_argument("--no-agent", action="store_true", help="setup: pair only, do not install the launchd agent")
    return q
