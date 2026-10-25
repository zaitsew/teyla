"""The data behind `teyla web`: every route is a thin call to the function the command line calls.

This module computes no figure of its own. The diagnosis, the offers and `apply` / `undo` come from
`start`, `offers` and `changes`; the Today tab is `today.snapshot`; products come from `registry`,
`asks` and `notes`; the spend tab sums `spend.session_rows` per day (the same rows `teyla spend`
reads). What it adds is the plumbing a page needs: a cache, so the page opens at once, and a
background thread, so the 5 to 60 s a diagnosis takes never blocks a request.

    GET  /api/start  /api/today  /api/products  /api/products/<id>  /api/notes  /api/spend
    POST /api/apply  /api/undo  /api/refresh  /api/notes  /api/notes/<id>/link|drop|undrop

`Api.route(method, path, query, body)` returns `(status, json-able)`. An `ApiError` becomes
`{"error": ...}` with its status; nothing here lets a traceback reach the page.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import tempfile
import threading
import time
from urllib.parse import unquote

from .. import asks, changes, corrections, notes, registry
from .. import offers as offers_mod
from .. import start as start_mod

START_DAYS = 30
START_TTL_S = 15 * 60            # the diagnosis is counted again in the background when older than this
SPEND_TTL_S = 10 * 60
SPEND_DAYS = 14                  # this week and the week before
WEEK = 7
SESSIONS_PER_PRODUCT = 8
CACHE_VERSION = 1
UNDO_MAX = 20


class ApiError(Exception):
    """A refusal the page shows as one sentence. `extra` is merged into the JSON body."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def _now() -> float:
    return time.time()


def _iso(at: float | None) -> str | None:
    return _dt.datetime.fromtimestamp(at, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


# --- the cache file -----------------------------------------------------------------------------

def cache_path() -> pathlib.Path:
    return corrections.teyla_home() / "web-cache.json"


def _read_cache(path: pathlib.Path) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get("version") == CACHE_VERSION else {}


def _write_cache(path: pathlib.Path, d: dict) -> None:
    """Never raises: a cache that cannot be written only means the next page load waits for the numbers."""
    from .. import config
    try:
        config.private_dir(path.parent)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(d, fh, default=str)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001
        pass


# --- a number that takes a while ------------------------------------------------------------------

class Job:
    """One slow computation. `get()` returns what is known right now; `ensure()` starts a background
    run when there is nothing yet or the number is older than `ttl`; one run at a time."""

    def __init__(self, name: str, fn, ttl: float, saved: dict | None, on_done=None):
        self.name, self.fn, self.ttl, self.on_done = name, fn, ttl, on_done
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.data = (saved or {}).get("data")
        self.at = (saved or {}).get("at")
        self.error: str | None = None

    def get(self) -> dict:
        with self.lock:
            return {"data": self.data, "at": self.at, "error": self.error,
                    "refreshing": bool(self.thread and self.thread.is_alive())}

    def stale(self) -> bool:
        return self.data is None or self.at is None or _now() - self.at > self.ttl

    def ensure(self, force: bool = False) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            if not (force or self.stale()):
                return
            self.error = None
            self.thread = threading.Thread(target=self._run, name=f"teyla-web-{self.name}", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        try:
            data = self.fn()
        except Exception as e:  # noqa: BLE001 — the page shows the sentence and keeps the old numbers
            with self.lock:
                self.error = f"could not count the {self.name}: {type(e).__name__}: {e}"
            return
        with self.lock:
            self.data, self.at, self.error = data, _now(), None
        if self.on_done:
            self.on_done()

    def patch(self, fn) -> None:
        """Change the cached data in place (`fn(data)`): what an apply does to the offers it just changed."""
        with self.lock:
            if self.data is not None:
                fn(self.data)

    def join(self, timeout: float | None = None) -> None:
        t = self.thread
        if t:
            t.join(timeout)


# --- Start --------------------------------------------------------------------------------------

def confirm_text(o: dict) -> str:
    """The sentence the Apply button asks about: the file and the key (or the command) it will change."""
    c = o["change"]
    if c["kind"] == "json":
        return f"This sets {'.'.join(c['key_path'])} to {json.dumps(c['new'])} in {c['file']}, after a backup of the file."
    if c["kind"] == "toml":
        return f"This sets {c['key_path'][0]} to {json.dumps(c['new'])} in {c['file']}, after a backup of the file."
    if c["kind"] == "file":
        return f"This creates {c['file']}. It writes nothing if the file exists."
    return f"This runs `{c['command']}`. {c['summary'][0].upper()}{c['summary'][1:]}."


def _applied_by_offer() -> dict:
    out: dict = {}
    for c in changes.changes():
        if c.get("undone") or "offer" not in c:
            continue
        out[str(c["offer"]).upper()] = {"id": c["id"], "at": c.get("at"), "kind": c.get("kind", "json"),
                                        "undoable": c.get("kind", "json") != "command"}
    return out


def _start_compute() -> dict:
    payload, _ = start_mod.payload(START_DAYS)
    return payload


# --- Spend --------------------------------------------------------------------------------------

def spend_view(rows: list[dict], reg: dict, today: _dt.date | None = None) -> dict:
    """This week against the one before, by day, by model and by product, from the session rows.
    The day totals are `spend.by_day`; the splits add the same per-day figures that function adds."""
    from .. import spend
    today = today or _dt.date.today()
    days = spend.by_day(SPEND_DAYS, rows, today)             # oldest first
    split = {d["day"]: ("last" if i < WEEK else "this") for i, d in enumerate(days)}
    this = round(sum(d["total_usd"] for d in days[WEEK:]), 2)
    last = round(sum(d["total_usd"] for d in days[:WEEK]), 2)
    by_model: dict = {}
    by_product: dict = {}
    sessions: dict = {}
    for r in rows:
        pid = registry.resolve(r.get("cwd"), session=r.get("sid"), reg=reg)
        p = by_product.setdefault(pid, {"product": pid, "name": asks.display_name(reg, pid), "this_week": 0.0, "last_week": 0.0})
        week_usd = 0.0
        for d, per in (r.get("day_model_usd") or {}).items():
            w = split.get(d)
            if not w:
                continue
            for m, usd in per.items():
                by_model.setdefault(m, {"model": m, "this_week": 0.0, "last_week": 0.0})[w + "_week"] += usd
                p[w + "_week"] += usd
                week_usd += usd
        if week_usd > 0:
            sessions.setdefault(pid, []).append({"harness": r["harness"], "sid": str(r["sid"])[:8], "last": r.get("last") or "",
                                                 "project": r.get("project") or "", "usd": round(week_usd, 2)})

    def tidy(rows_: dict) -> list[dict]:
        out = []
        for v in rows_.values():
            v["this_week"], v["last_week"] = round(v["this_week"], 2), round(v["last_week"], 2)
            if v["this_week"] or v["last_week"]:
                out.append(v)
        return sorted(out, key=lambda v: (-v["this_week"], -v["last_week"]))
    for pid in sessions:
        sessions[pid] = sorted(sessions[pid], key=lambda s: s["last"], reverse=True)[:SESSIONS_PER_PRODUCT]
    return {"days": SPEND_DAYS, "this_week": this, "last_week": last,
            "change_pct": round((this - last) / last * 100) if last else None,
            "by_day": [{"day": d["day"], "usd": d["total_usd"], "week": split[d["day"]]} for d in days],
            "by_model": tidy(by_model), "by_product": tidy(by_product), "sessions": len(rows),
            "product_sessions": sessions}


def _spend_compute() -> dict:
    from .. import spend
    return spend_view(spend.session_rows(SPEND_DAYS), registry.load())


# --- the API ------------------------------------------------------------------------------------

class Api:
    def __init__(self, cache: pathlib.Path | None = None):
        self.cache = cache or cache_path()
        saved = _read_cache(self.cache)
        self.write_lock = threading.Lock()        # one apply or undo at a time (changes.py also holds a file lock)
        self.cache_lock = threading.Lock()
        self.jobs = {
            "start": Job("diagnosis", _start_compute, START_TTL_S, saved.get("start"), lambda: self._save("start")),
            "spend": Job("spend", _spend_compute, SPEND_TTL_S, saved.get("spend"), lambda: self._save("spend")),
        }

    def _save(self, name: str) -> None:
        with self.cache_lock:
            d = _read_cache(self.cache) or {"version": CACHE_VERSION}
            g = self.jobs[name].get()
            if g["data"] is not None:
                d[name] = {"at": g["at"], "data": g["data"]}
                _write_cache(self.cache, d)

    # -- routing --

    ROUTES = [
        ("GET", r"/api/start", "get_start", 200), ("GET", r"/api/today", "get_today", 200),
        ("GET", r"/api/products", "get_products", 200), ("GET", r"/api/products/(?P<pid>.+)", "get_product", 200),
        ("GET", r"/api/notes", "get_notes", 200), ("GET", r"/api/spend", "get_spend", 200),
        ("POST", r"/api/apply", "post_apply", 200), ("POST", r"/api/undo", "post_undo", 200),
        ("POST", r"/api/refresh", "post_refresh", 202), ("POST", r"/api/notes", "post_note", 201),
        ("POST", r"/api/notes/(?P<nid>[^/]+)/(?P<verb>link|drop|undrop)", "post_note_verb", 200),
    ]

    def route(self, method: str, path: str, query: dict, body: dict) -> tuple[int, object]:
        known = False
        for m, pattern, name, ok in self.ROUTES:
            hit = re.fullmatch(pattern, path)
            if not hit:
                continue
            known = True
            if m != method:
                continue
            try:
                return ok, getattr(self, name)(query=query, body=body, **hit.groupdict())
            except ApiError as e:
                return e.status, {"error": e.message, **e.extra}
        if known:
            return 405, {"error": f"{method} is not allowed on {path}"}
        return 404, {"error": f"no such route: {path}"}

    # -- Start --

    def get_start(self, query, body, **_):
        job = self.jobs["start"]
        job.ensure()
        g = job.get()
        payload = g["data"]
        out = {"days": START_DAYS, "at": _iso(g["at"]), "age_s": int(_now() - g["at"]) if g["at"] else None,
               "refreshing": g["refreshing"], "error": g["error"], "diagnosis": None, "summary_text": None, "offers": []}
        if payload:
            applied = _applied_by_offer()
            out["diagnosis"], out["summary_text"] = payload["diagnosis"], payload["summary_text"]
            for o in payload["offers"]:
                o = dict(o)
                o["applied"] = applied.get(o["id"])
                o["confirm"] = confirm_text(o)
                out["offers"].append(o)
        out["changes"] = changes.changes()[-UNDO_MAX:]
        return out

    def post_refresh(self, query, body, **_):
        what = str(body.get("what") or "")
        if what not in self.jobs:
            raise ApiError(400, f"refresh what? one of: {', '.join(self.jobs)}")
        self.jobs[what].ensure(force=True)
        return {"refreshing": True, "what": what}

    def _patch_offer(self, offer_id: str) -> None:
        """After an apply or an undo: set `applies` from the live settings, so the page is right before the
        diagnosis is counted again."""
        try:
            live = {o.id: o for o in offers_mod.build(with_savings=False)}
        except Exception:  # noqa: BLE001
            return

        def fn(payload):
            for o in payload["offers"]:
                if o["id"] == offer_id and offer_id in live:
                    o["applies"], o["reason"] = live[offer_id].applies, live[offer_id].reason
        self.jobs["start"].patch(fn)

    def post_apply(self, query, body, **_):
        ref = str(body.get("offer") or "").strip().upper()
        if not ref:
            raise ApiError(400, "which offer? Send {\"offer\": \"O1\", \"confirm\": true}.")
        if body.get("confirm") is not True:
            raise ApiError(400, f"{ref}: a change needs a confirmation. Send \"confirm\": true after showing what it changes.")
        live = {o.id: o for o in offers_mod.build(with_savings=False)}
        o = live.get(ref)
        if o is None:
            raise ApiError(404, f"no offer {ref!r}: the offers are {', '.join(live)}")
        if not o.applies:
            raise ApiError(409, f"{o.id}: nothing to do: {o.reason}")
        with self.write_lock:
            try:
                rec, lines = offers_mod.apply(o)
            except changes.ChangeError as e:
                raise ApiError(409, str(e)) from None
            except Exception as e:  # noqa: BLE001 — a sync that fails half-way says so
                raise ApiError(500, f"{o.id} failed: {type(e).__name__}: {e}") from None
        self._patch_offer(o.id)
        self.jobs["start"].ensure(force=True)
        return {"change": rec, "lines": lines[:6], "undoable": rec.get("kind") != "command",
                "undo": o.undo}

    def post_undo(self, query, body, **_):
        ref = str(body.get("ref") or body.get("offer") or "").strip()
        if not ref:
            raise ApiError(400, "undo what? Send {\"ref\": \"O1\"} or a change id.")
        rows = changes.resolve(ref)
        if not rows:
            raise ApiError(404, f"nothing to undo for {ref!r}: Teyla has no active change with that id")
        done, lines = [], []
        with self.write_lock:
            for rec in rows:
                try:
                    lines += changes.revert(rec, force=body.get("force") is True)
                except changes.ChangeError as e:
                    msg = str(e)
                    raise ApiError(409, msg, change=rec["id"], offer=rec.get("offer"),
                                   can_force="--force" in msg, undone=done) from None
                done.append(rec["id"])
        for rec in rows:
            if rec.get("offer"):
                self._patch_offer(str(rec["offer"]).upper())
        self.jobs["start"].ensure(force=True)
        return {"undone": done, "lines": lines}

    # -- Today --

    def get_today(self, query, body, **_):
        try:
            from .. import today
        except ImportError:
            raise ApiError(503, "this version of Teyla has no `teyla today`: update Teyla and restart `teyla web`") from None
        return today.snapshot(wait=False)

    # -- Products --

    def _asks(self):
        now = asks._now()
        items = asks.collect(asks.DEFAULT_DAYS, now, fetch=False, st=asks.load_state())
        reg = registry.load()
        return [a for a in items if a.status == "open"], reg, now

    def _note_counts(self) -> dict:
        c = notes.counts()
        return {"inbox": c["inbox"], **c["by_product"]}

    def get_products(self, query, body, **_):
        items, reg, now = self._asks()
        by_note = {k: v for k, v in self._note_counts().items() if k != "inbox"}
        waiting: dict = {}
        muted: dict = {}
        for a in items:
            bucket = muted if asks.is_muted(a, reg) else waiting
            bucket[a.product] = bucket.get(a.product, 0) + 1
        ids = list(reg["product"]) + [p for p in list(waiting) + list(muted) + list(by_note) if p not in reg["product"]]
        seen, rows = set(), []
        for pid in ids:
            if pid in seen:
                continue
            seen.add(pid)
            p = reg["product"].get(pid) or {}
            rows.append({"id": pid, "name": asks.display_name(reg, pid), "registered": pid in reg["product"],
                         "stage": p.get("stage") or "", "focus": bool(p.get("focus")), "primary": p.get("primary") or "",
                         "repos": p.get("repos") or [], "waiting": waiting.get(pid, 0), "muted": muted.get(pid, 0),
                         "notes": by_note.get(pid, 0)})
        rows.sort(key=lambda r: (r["id"] == registry.UNASSIGNED, r["stage"] == "parked", not r["focus"], -r["waiting"], r["name"].lower()))
        return {"products": rows, "inbox": self._note_counts().get("inbox", 0), "registered": len(reg["product"])}

    def get_product(self, query, body, pid="", **_):
        pid = unquote(pid)
        items, reg, now = self._asks()
        mine = [a for a in items if a.product == pid]
        mine_notes = notes.listing(pid)
        p = reg["product"].get(pid)
        if p is None and not mine and not mine_notes:
            raise ApiError(404, f"no product {pid!r}. `teyla product add {pid}` registers it.")
        p = p or {}
        job = self.jobs["spend"]
        job.ensure()
        g = job.get()
        view = g["data"] or {}
        prod_spend = next((x for x in view.get("by_product", []) if x["product"] == pid), None)
        if view and prod_spend is None:
            prod_spend = {"product": pid, "name": asks.display_name(reg, pid), "this_week": 0.0, "last_week": 0.0}
        rows = []
        for a in sorted(mine, key=lambda a: (not asks.is_critical(a), a.when)):
            d = a.to_dict(now)
            d["critical"], d["muted"] = asks.is_critical(a), asks.is_muted(a, reg)
            rows.append(d)
        return {"id": pid, "name": asks.display_name(reg, pid), "registered": pid in reg["product"],
                "stage": p.get("stage") or "", "focus": bool(p.get("focus")), "primary": p.get("primary") or "",
                "aliases": p.get("aliases") or [], "repos": p.get("repos") or [], "paths": p.get("paths") or [],
                "asks": rows, "notes": mine_notes,
                "spend": prod_spend, "sessions": (view.get("product_sessions") or {}).get(pid, []),
                "spend_at": _iso(g["at"]), "spend_refreshing": g["refreshing"], "spend_error": g["error"]}

    # -- Notes --

    def get_notes(self, query, body, **_):
        include = (query.get("all") or [""])[0] in ("1", "true", "yes")
        product = (query.get("product") or [""])[0] or None
        reg = registry.load()
        rows = notes.listing(product, include_dropped=include)
        return {"notes": rows, "inbox": self._note_counts().get("inbox", 0),
                "candidates": [{"id": pid, "name": asks.display_name(reg, pid)} for pid in notes.candidates(reg)]}

    def post_note(self, query, body, **_):
        text = body.get("text")
        if not isinstance(text, str):
            raise ApiError(400, "send {\"text\": \"...\"} and, to choose the product yourself, \"product\"")
        product = body.get("product") or None
        try:
            return notes.add(text, product if isinstance(product, str) else None, cwd="")
        except notes.NoteError as e:
            raise ApiError(400, str(e)) from None

    def post_note_verb(self, query, body, nid="", verb="", **_):
        try:
            if verb == "link":
                product = body.get("product")
                if not isinstance(product, str) or not product:
                    raise ApiError(400, "link to which product? Send {\"product\": \"<id>\"} or \"inbox\".")
                note, changed = notes.link(nid, product)
            else:
                note, changed = notes.set_dropped(nid, verb == "drop")
        except notes.NoteError as e:
            msg = str(e)
            raise ApiError(404 if msg.startswith("no note") else 409 if "dropped" in msg else 400, msg) from None
        return {"note": note, "changed": changed}

    # -- Spend --

    def get_spend(self, query, body, **_):
        job = self.jobs["spend"]
        job.ensure()
        g = job.get()
        view = dict(g["data"]) if g["data"] else None
        if view:
            view.pop("product_sessions", None)
        return {"spend": view, "at": _iso(g["at"]), "age_s": int(_now() - g["at"]) if g["at"] else None,
                "refreshing": g["refreshing"], "error": g["error"]}
