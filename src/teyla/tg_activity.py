"""The Telegram activity widget of `teyla tg activity`: one HTML document, and the state it draws.

Two GitHub-style grids, "Growth" (the growth ledger: posts, comments, emails, meetings) and "GitHub" (the
contribution calendar), each with today's number and the streak. The widget is static; the bot keeps it current by
writing `chat_data` with `editMessageWidgetData`. It reads `window.TelegramWidget.chatData` and sends nothing.

The state, short keys to fit 1 KB (STATE_BUDGET):

    v  1                         d  the data day, YYYY-MM-DD (the day of the last row of both grids)
    s  the Monday the grids start on (column 0, row 0)
    h  time of the last edit as HH:MM on the Mac        t  epoch of that edit
    g  Growth: [today's count, streak, one digit 0-4 per day from s to d]
    c  GitHub: the same; absent when `gh` is not available, and the widget says "not connected"

At most WEEKS weeks per grid. Text is drawn with `textContent` and SVG attributes only: nothing from the state is
parsed as HTML. Colours are `--tg-theme-*` variables only.
"""
from __future__ import annotations

import datetime as _dt
import json
import zlib

WEEKS = 26
STATE_BUDGET = 1000          # bytes; chat_data stops at 1024
HTML_MAX = 32768
HTML_ZLIB_MAX = 4096
OFFLINE_S = 900              # the widget calls the laptop offline after this long without an edit

CSS = (
    "body{margin:0;padding:10px 12px;font:14px/1.3 -apple-system,system-ui,sans-serif;"
    "color:var(--tg-theme-text-color);background:var(--tg-theme-bg-color)}"
    ".r{display:flex;align-items:center;gap:12px;margin:0 0 10px}"
    ".m{flex:1;min-width:0}"
    ".l{font-size:12px;font-weight:600;color:var(--tg-theme-accent-text-color);margin:0 0 4px}"
    "svg{display:block;width:100%;height:auto}"
    ".c{fill:var(--tg-theme-secondary-bg-color)}"
    ".c1{fill:var(--tg-theme-button-color);fill-opacity:.3}"
    ".c2{fill:var(--tg-theme-button-color);fill-opacity:.5}"
    ".c3{fill:var(--tg-theme-button-color);fill-opacity:.75}"
    ".c4{fill:var(--tg-theme-button-color)}"
    ".s{width:64px;text-align:center}"
    ".b{font-size:34px;font-weight:700;line-height:1}"
    ".k{font-size:12px;color:var(--tg-theme-hint-color)}"
    ".z{font-size:12px;color:var(--tg-theme-hint-color);padding:14px 0}"
    ".f{font-size:12px;color:var(--tg-theme-hint-color)}"
    ".e{font-size:12px;color:var(--tg-theme-destructive-text-color)}"
)

JS = r"""
var W=window.TelegramWidget,S=null,NS='http://www.w3.org/2000/svg';
function el(t,c,x,p){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;(p||document.body).appendChild(e);return e}
function load(){try{S=JSON.parse(W.chatData)}catch(e){S=null}}
function today(){var n=new Date(),p=function(x){return(x<10?'0':'')+x};return n.getFullYear()+'-'+p(n.getMonth()+1)+'-'+p(n.getDate())}
function grid(p,g,s){var C=10,G=2,n=g.length,cols=Math.max(1,Math.ceil(n/7)),sv=document.createElementNS(NS,'svg');
sv.setAttribute('viewBox','0 0 '+(cols*(C+G)-G)+' '+(7*(C+G)-G));sv.setAttribute('preserveAspectRatio','xMinYMid meet');
for(var i=0;i<n;i++){var l=+g.charAt(i);if(!(l>=0&&l<=4))l=0;var r=document.createElementNS(NS,'rect');
r.setAttribute('x',Math.floor(i/7)*(C+G));r.setAttribute('y',(i%7)*(C+G));r.setAttribute('width',C);r.setAttribute('height',C);
r.setAttribute('rx',2);r.setAttribute('class',l?'c c'+l:'c');sv.appendChild(r)}
p.appendChild(sv)}
function row(name,a,live){var r=el('div','r'),m=el('div','m',null,r);el('div','l',name,m);
if(!a||!a.length){el('div','z','not connected',m);el('div','s',null,r);return}
grid(m,String(a[2]||''),S.s);var s=el('div','s',null,r);
el('div','b',live?String(a[0]):'—',s);el('div','k','today',s);el('div','k','streak '+a[1],s)}
function draw(){document.body.textContent='';
if(!S||S.v!==1){el('div','z','Waiting for the laptop.');return}
var live=S.d===today();row('GitHub',S.c,live);row('Growth',S.g,live);
if(S.t&&Date.now()/1e3-S.t>OFFLINE)el('div','e','Laptop offline since '+S.h);
else el('div','f','Updated '+S.h)}
W.onEvent('chatDataChanged',function(){load();draw()});
try{W.onEvent('themeChanged',draw)}catch(e){}
setInterval(draw,60000);
load();draw();if(W.ready)W.ready();
"""


def build_html() -> str:
    js = "\n".join(line.strip() for line in JS.strip().splitlines()).replace("OFFLINE", str(OFFLINE_S))
    return (f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>{CSS}</style></head>"
            f"<body><script>{js}</script></body></html>")


def html_sizes(html: str | None = None) -> tuple[int, int]:
    """(raw bytes, zlib level 9 bytes): the two limits of sendWidget."""
    raw = (html or build_html()).encode("utf-8")
    return len(raw), len(zlib.compress(raw, 9))


def encode(st: dict) -> str:
    return json.dumps(st, ensure_ascii=False, separators=(",", ":"))


def size(st: dict) -> int:
    return len(encode(st).encode("utf-8"))


def _grid(a: dict, weeks: int) -> tuple[list, str]:
    """([today, streak, digits], the Monday the digits start on), cut to at most `weeks` whole weeks."""
    days = a.get("days") or []
    start = _dt.date.fromisoformat(a["start"])
    cut = max(0, len(days) - weeks * 7)
    cut += -cut % 7                                   # whole weeks only: column 0 stays a Monday
    days = days[cut:]
    start += _dt.timedelta(days=cut)
    digits = "".join(str(min(4, max(0, int(x.get("level") or 0)))) for x in days)
    return [int(a.get("today_count") or 0), int(a.get("streak") or 0), digits], start.isoformat()


def state(growth: dict | None, github: dict | None, now: float, weeks: int = WEEKS) -> str:
    """The widget's chat_data. A source that is None is left out and the widget shows "not connected"."""
    st: dict = {"v": 1}
    start = day = None
    for key, a in (("g", growth), ("c", github)):
        if not a:
            continue
        st[key], s = _grid(a, weeks)
        start, day = start or s, day or a.get("today")
    st["d"] = day or _dt.date.fromtimestamp(now).isoformat()
    if start:
        st["s"] = start
    st["h"] = _dt.datetime.fromtimestamp(now).strftime("%H:%M")
    st["t"] = int(now)
    out = {k: st[k] for k in ("v", "d", "s", "h", "t", "g", "c") if k in st}
    return encode(out)


def key(chat_data: str) -> str:
    """The state without its clock (`h`, `t`): what decides whether the widget needs an edit."""
    try:
        st = json.loads(chat_data)
    except ValueError:
        return chat_data
    st.pop("h", None)
    st.pop("t", None)
    return encode(st)


def collect(now: float, weeks: int = WEEKS) -> tuple[dict | None, dict | None]:
    """(growth graph, GitHub graph) as `teyla growth activity` makes them; GitHub is None when `gh` cannot say."""
    from . import github_activity, growth
    store, _ = growth._store_cfg()
    today = growth.day_of(now)
    g = growth.activity(store.ledger(), today, weeks)
    try:
        c = github_activity.activity(today, weeks)
    except Exception:                                  # noqa: BLE001 — a missing `gh` must not stop the growth grid
        c = None
    return g, c
