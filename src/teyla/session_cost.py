"""List-price cost of one Claude Code session, its subagents included.

`session_cost(sid)` reads only that session's transcript (`<root>/<slug>/<sid>.jsonl`) and its
`<sid>/subagents/*.jsonl` files, prices each message with `pricing.cost_usd`, and returns
`{"usd": total, "sub_usd": the subagent share}`. The sprint-contract hook (`teyla brief --hook`)
calls it on every Agent call and has a 5 second timeout, so the result is cached under the Teyla
directory, keyed by the session id and a signature of every file's path, mtime and size: an
unchanged session costs one `stat` per file. Nothing leaves the machine.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os

from . import config
from .adapters import claude_code
from .pricing import cost_usd


def _cache_path():
    return config.TEYLA_DIR / "briefs" / "session-cost-cache.json"  # call time: tests redirect TEYLA_DIR


def _files(sid: str, transcript: str | None) -> list[str]:
    if transcript and os.path.isfile(transcript):
        main = transcript
    else:
        hits = claude_code.locate(sid)
        exact = [h for h in hits if os.path.basename(h) == sid + ".jsonl"]
        main = (exact or hits or [None])[0]
    if not main:
        return []
    subs = sorted(glob.glob(os.path.join(main[:-len(".jsonl")], "subagents", "*.jsonl")))
    return [main] + subs


def _signature(files: list[str]) -> str:
    h = hashlib.sha1()
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        h.update(f"{f}|{st.st_mtime_ns}|{st.st_size};".encode())
    return h.hexdigest()


def _main_usage(f: str) -> dict:
    """message id -> (model, usage row); the last record of one message wins."""
    per: dict = {}
    try:
        fh = open(f, errors="replace")
    except OSError:
        return per
    with fh:
        for n, line in enumerate(fh):
            if '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            m = o.get("message") or {}
            per[m.get("id") or ("line", n)] = (m.get("model", "?"), claude_code._usage_row(m.get("usage") or {}))
    return per


def _price(per: dict) -> float:
    return sum(cost_usd(model, row) or 0.0 for model, row in per.values())


def compute(files: list[str]) -> dict:
    if not files:
        return {"usd": 0.0, "sub_usd": 0.0}
    main_usd = _price(_main_usage(files[0]))
    subs, _calls = claude_code._subagent_usage(files[0])
    sub_usd = _price({k: (m, row) for k, (m, row, _ts) in subs.items()})
    return {"usd": main_usd + sub_usd, "sub_usd": sub_usd}


def session_cost(sid: str, transcript_path: str | None = None) -> dict:
    """{"usd", "sub_usd"} at list price for one session and its subagents; zeros when no transcript is found."""
    files = _files(sid, transcript_path)
    if not files:
        return {"usd": 0.0, "sub_usd": 0.0}
    sig = _signature(files)
    path = _cache_path()
    try:
        cache = json.loads(path.read_text())
    except Exception:
        cache = {}
    hit = cache.get(sid)
    if isinstance(hit, dict) and hit.get("sig") == sig:
        return {"usd": float(hit["usd"]), "sub_usd": float(hit["sub_usd"])}
    out = compute(files)
    cache[sid] = {"sig": sig, **out}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, path)
    except OSError:
        pass
    return out
