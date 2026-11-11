"""The Telegram widget of `teyla tg`: one HTML document, and the card state it draws.

The widget is static. Everything it shows comes from `chat_data` (at most 1 KB, written only by the bot with
`editMessageWidgetData`) or from the bot's answer to a tap (at most 1 KB). It sends nothing but
`TelegramWidget.request("<op>.<nonce>")`: one opcode character and the card's nonce. It never sends text.

The card state, short keys to fit 1 KB:

    v  1                      m  mode: a ask | f confirm a text answer | w working | e empty | x moved below
    k  nonce of this card     p  product name        q  the question, at most QUESTION_MAX characters
    o  answer options, recommended first; each is sent word for word when tapped
    d  1 when an answer can be delivered from here   s  1 when triage suggests "Done already"
    n  open questions left    t  epoch of the last edit   h  that time as HH:MM on the Mac
    f  the text answer waiting for a confirm tap      r  the result of the last tap

Text is drawn with `textContent`, never as HTML, so a question cannot inject markup into the widget. Colours are
`--tg-theme-*` variables only.
"""
from __future__ import annotations

import json
import re
import zlib

QUESTION_MAX = 200
STATE_BUDGET = 1000          # bytes; chat_data and the answer to a tap both stop at 1024, and the answer wraps the card
HTML_MAX = 32768
HTML_ZLIB_MAX = 4096
OPTIONS_MAX = 3

CSS = (
    "body{margin:0;padding:10px 12px;font:14px/1.35 -apple-system,system-ui,sans-serif;"
    "color:var(--tg-theme-text-color);background:var(--tg-theme-bg-color)}"
    ".h{display:flex;justify-content:space-between;font-size:12px;color:var(--tg-theme-hint-color)}"
    ".p{font-weight:600;color:var(--tg-theme-accent-text-color)}"
    ".q{margin:6px 0 8px;white-space:pre-wrap}"
    "button{display:block;width:100%;margin:4px 0;padding:8px 10px;border:0;border-radius:8px;font:inherit;"
    "text-align:left;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color)}"
    "button.y{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color);font-weight:600}"
    ".w{display:flex;gap:4px}.w button{text-align:center;font-size:12px;padding:6px 4px}"
    ".n{font-size:12px;color:var(--tg-theme-hint-color);margin:4px 0}"
    ".e{font-size:12px;color:var(--tg-theme-destructive-text-color);margin:4px 0}"
    ".f{border-left:3px solid var(--tg-theme-button-color);padding:4px 8px;margin:6px 0;white-space:pre-wrap}"
)

JS = r"""
var W=window.TelegramWidget,S=null,B=0,E='';
function el(t,c,x,p){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;(p||document.body).appendChild(e);return e}
function load(){try{S=JSON.parse(W.chatData)}catch(e){S=null}}
function hap(k){try{W.HapticFeedback.notificationOccurred(k)}catch(e){}}
function btn(p,c,x,op){var b=el('button',c,x,p);b.addEventListener('click',function(){go(op)});return b}
function go(op){if(B||!S||!S.k)return;B=1;E='';draw();
W.request(op+'.'+S.k).then(function(a){B=0;var r=null;try{r=JSON.parse(a.result)}catch(e){}
if(r&&r.c)S=r.c;E=r&&r.e?r.e:'';hap(E?'error':'success');draw()},
function(e){B=0;var c=e&&e.code;E=c=='TIMEOUT'?'No answer from the laptop. Tap again: an answer is never sent twice.':
(c=='RATE_LIMITED'||c=='BUSY')?'Too fast. Wait a moment, then tap again.':'Not sent ('+c+'). Tap again.';hap('error');draw()})}
function draw(){document.body.textContent='';
if(!S||!S.m){el('div','n','Waiting for the laptop.');return}
var h=el('div','h');el('span','p',S.p||'Teyla',h);el('span','',S.n!=null?S.n+' left':'',h);
if(S.t&&Date.now()/1e3-S.t>900)el('div','e','Laptop offline since '+S.h+'. Taps wait until it wakes.');
if(S.r)el('div','n',S.r);
var m=S.m,o=S.o||[];
if(m=='e')el('div','q','Nothing waits for you.');
else if(m=='x')el('div','n','This card moved below.');
else if(m=='w'||B){if(S.q)el('div','q',S.q);el('div','n','Working…')}
else if(m=='f'){el('div','q',S.q?'Send this answer to: '+S.q:'Send this answer?');el('div','f',S.f);
var w=el('div','w');btn(w,'y','Send','c');btn(w,'','Cancel','x')}
else{el('div','q',S.q);o.forEach(function(x,i){btn(0,i?'':'y',x,''+i)});
if(S.d&&!o.length)el('div','n','Answer in text: reply with a message.');
if(!S.d)el('div','n','Answer this one on the Mac.');
var w=el('div','w');btn(w,'','Snooze 1d','z');btn(w,S.s?'y':'','Done already','d');btn(w,'','Skip','s')}
if(E)el('div','e',E)}
W.onEvent('chatDataChanged',function(){load();B=0;E='';draw()});
setInterval(draw,60000);
load();draw();if(W.ready)W.ready();
"""


def build_html() -> str:
    js = "\n".join(line.strip() for line in JS.strip().splitlines())
    return f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>{CSS}</style></head><body><script>{js}</script></body></html>"


def html_sizes(html: str | None = None) -> tuple[int, int]:
    """(raw bytes, zlib level 9 bytes): the two limits of sendWidget."""
    raw = (html or build_html()).encode("utf-8")
    return len(raw), len(zlib.compress(raw, 9))


def encode(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def size(card: dict) -> int:
    return len(encode(card).encode("utf-8"))


_MD = re.compile(r"[*_`#]+")


def display_question(text: str, limit: int = QUESTION_MAX) -> str:
    """One paragraph, markdown marks removed, at most `limit` characters with an ellipsis."""
    t = re.sub(r"\s+", " ", _MD.sub("", str(text or ""))).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def fit(card: dict, budget: int = STATE_BUDGET) -> dict:
    """Shrink a card until its JSON fits `budget` bytes. Only display text shrinks: the question, the result line,
    the product. Options are sent word for word, so they are never cut; an option that does not fit is dropped from
    the end (it is then not offered). A confirm card's text `f` is never cut: the caller keeps it short enough."""
    c = dict(card)
    while size(c) > budget and len(c.get("q") or "") > 40:
        c["q"] = display_question(c["q"], max(40, int(len(c["q"]) * 0.8)))
    if size(c) > budget and c.get("r"):
        c["r"] = display_question(c["r"], 60)
    if size(c) > budget and len(c.get("p") or "") > 24:
        c["p"] = display_question(c["p"], 24)
    while size(c) > budget and c.get("o"):
        c["o"] = c["o"][:-1]
    if size(c) > budget and c.get("q"):
        c["q"] = display_question(c["q"], 40)
    return c
