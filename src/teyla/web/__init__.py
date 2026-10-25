"""`teyla web` — the local dashboard: the diagnosis and its offers, today, products, notes and spend in a browser.

    teyla web [--no-open] [--port N]

A stdlib server on 127.0.0.1 with a random port and a per-run token. It prints the address and opens it.
`docs/WEB.md` has the tabs, the security model and the API.
"""
from __future__ import annotations


def cmd_web(args) -> int:
    from . import server
    return server.run(port=args.port or 0, open_browser=not args.no_open)


def register(sp):
    q = sp.add_parser("web", help="open the dashboard in your browser: the diagnosis, today, products, notes, spend (127.0.0.1 only)")
    q.set_defaults(fn=cmd_web)
    q.add_argument("--no-open", action="store_true", help="print the address instead of opening the browser")
    q.add_argument("--port", type=int, default=0, help="listen on this port (default: a free one)")
    return q
