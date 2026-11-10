"""Device crashes from TestFlight, for `teyla crash --pull` and `teyla crash --device`.

The hourly agent (`[crash] feed_agent = true`, `teyla routine install`) runs `teyla crash --pull --quiet`.
For every product whose `teyla.toml` names `[release] apple_bundle_id` it asks App Store Connect, read-only and
with the key `review_asc.py` already uses (docs/PRIVACY.md row 56):

  - the crash submissions (betaFeedbackCrashSubmissions) and, for each new one, its crash log;
  - the screenshot feedback, through `review.pull_testflight`, so it lands in `teyla review list`;
  - the date of the newest build upload.

Crashes live in `~/.teyla/crash-feed/` (mode 0700, files 0600): `feed.json` holds the per-app freshness record
and one record per crash, `<id>.log` the capped log text. The id is a UUIDv5 of Apple's id, so a second pull
changes nothing. The tester's e-mail is never stored. Device crashes are never mixed with Mac panics: `teyla crash`
prints them under their own heading.

Freshness rule (a TestFlight feed was reported frozen in June 2026; the web UI cannot be checked from here):

  pull stale      the last successful pull of the app is older than STALE_PULL_H hours (the agent is off, or
                  every pull fails). Says nothing about Apple.
  may be frozen   a build was uploaded in the last RECENT_BUILD_DAYS days, the feed has returned submissions
                  before (so it worked once), and the newest submission is older than QUIET_DAYS days. A quiet
                  but healthy feed looks the same, so the wording is "may be", and the fix is to look at the
                  app's TestFlight page in App Store Connect once.
  never pulled    the app is known but no pull has succeeded yet.

Nothing here raises: an unreachable or refused call becomes `last_error` on the app, and the agent exits 0.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from . import config, productize, review_asc

STALE_PULL_H = 3
QUIET_DAYS = 14
RECENT_BUILD_DAYS = 7
LOG_TRIES = 3         # attempts to fetch one crash log before giving up on it
KEEP = 200            # crash records kept in feed.json, newest first


def store_dir() -> pathlib.Path:
    return config.TEYLA_DIR / "crash-feed"          # call time: tests and a moved home redirect it


def state_path() -> pathlib.Path:
    return store_dir() / "feed.json"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ts(s) -> dt.datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> dict:
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("apps"), dict):
        d["apps"] = {}
    if not isinstance(d.get("crashes"), dict):
        d["crashes"] = {}
    if not isinstance(d.get("seen"), dict):
        # crash id -> product: the dedup index, never pruned by retention (a store from before it is seeded from its crashes)
        d["seen"] = {cid: c.get("product", "") for cid, c in d["crashes"].items() if isinstance(c, dict)}
    return d


def save(d: dict) -> None:
    config.write_private(state_path(), json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def apps(paths: list[str] | None = None) -> list[dict]:
    """[{product, bundle_id, app_id}] from the teyla.toml files. `app_id` is `[release] apple_app_id` or ""
    (the pull then looks it up once, by bundle id, and remembers it). No app id or bundle id is built in."""
    out, seen = [], set()
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            continue
        rel = m.get("release") or {}
        bundle = str(rel.get("apple_bundle_id") or "").strip()
        if not bundle or bundle in seen:
            continue
        seen.add(bundle)
        out.append({"product": m["product"], "bundle_id": bundle, "app_id": str(rel.get("apple_app_id") or "").strip()})
    return out


# --- freshness --------------------------------------------------------------------------------------------------

def freshness(rec: dict, now: dt.datetime | None = None) -> tuple[str, str]:
    """(status, text): status is ok | pull-stale | may-be-frozen | never. See the module docstring for the rule."""
    now = now or _now()
    pulled = _ts(rec.get("last_pull"))
    if pulled is None:
        err = f" (last error: {rec['last_error']})" if rec.get("last_error") else ""
        return "never", f"no successful pull yet{err}"
    hours = (now - pulled).total_seconds() / 3600
    if hours > STALE_PULL_H:
        err = f"; last error: {rec['last_error']}" if rec.get("last_error") else ""
        return "pull-stale", f"last successful pull {int(hours)} h ago{err}"
    newest, upload = _ts(rec.get("newest_submission")), _ts(rec.get("newest_upload"))
    if (upload is not None and (now - upload).days <= RECENT_BUILD_DAYS
            and newest is not None and (now - newest).days > QUIET_DAYS):
        return "may-be-frozen", (f"feed may be frozen: a build was uploaded {(now - upload).days} d ago, "
                                 f"but the newest submission is {(now - newest).days} d old")
    return "ok", "fresh"


def problems(now: dt.datetime | None = None) -> list[tuple[str, str]]:
    """[(product, text)] for every app whose feed is not fresh. Empty when no pull ever ran."""
    return [(r.get("product", a), txt) for a, r in sorted(load()["apps"].items())
            for st, txt in [freshness(r, now)] if st != "ok"]


# --- the pull ---------------------------------------------------------------------------------------------------

def _pull_app(app: dict, rec: dict, client, conn, state: dict, now: dt.datetime) -> None:
    from . import review
    app_id = rec.get("app_id") or app["app_id"] or review_asc.lookup_app_id(app["bundle_id"], client)
    if not app_id:
        raise review_asc.AscError(f"no app with bundle id {app['bundle_id']} in App Store Connect for this key")
    rec["app_id"] = app_id
    items = review_asc.fetch_crash_submissions(app_id, client)
    seen = state["seen"]
    new = 0
    for item in items:
        c = review_asc.crash_record(item, app["product"])
        if c is None:
            continue
        apple_id = c.pop("_apple_id")
        old = state["crashes"].get(c["id"])
        if c["id"] in seen and (old is None or old.get("log") or old.get("log_attempts", 0) >= LOG_TRIES):
            continue            # reported before; its log is stored, given up on, or its record was pruned
        if old is not None:
            c = old             # a retry: only the log is missing
        try:
            log = review_asc.fetch_crash_log(apple_id, client)
        except review_asc.AscError:
            log = ""
        if log:
            config.write_private(store_dir() / f"{c['id']}.log", log)
            c["log"] = f"{c['id']}.log"
            c["summary"] = review_asc.crash_summary(log)
            c.pop("log_attempts", None)
        else:
            c["summary"] = c.get("summary") or {}
            c["log_attempts"] = int(c.get("log_attempts", 0)) + 1     # a bounded retry on the next pulls
        state["crashes"][c["id"]] = c
        if c["id"] not in seen:
            new += 1
        seen[c["id"]] = app["product"]
    if items:       # an empty answer never wipes the dedup index of this product
        returned = {review_asc.crash_record(i, "")["id"] for i in items if review_asc.crash_record(i, "")}
        for cid in [k for k, v in seen.items() if v == app["product"] and k not in returned]:
            del seen[cid]       # Apple no longer returns it, so it cannot come back as new
    shots = review.pull_testflight(conn, app_id, app["product"], client)
    if shots.get("error"):
        raise review_asc.AscError(str(shots.get("note") or "the screenshot pull failed"))
    upload = review_asc.newest_upload(app_id, client)
    dates = [str((i.get("attributes") or {}).get("createdDate") or "") for i in items if isinstance(i.get("attributes"), dict)]
    dates.append(str(shots.get("newest") or ""))
    mine = [c["created_at"] for c in state["crashes"].values() if c.get("product") == app["product"]]
    fresh = max([d for d in dates + mine if d], default="")
    rec.update(product=app["product"], bundle_id=app["bundle_id"], last_pull=_iso(now), last_error="",
               new_crashes=new, new_screenshots=int(shots.get("added") or 0),
               newest_upload=upload or rec.get("newest_upload", ""))
    if fresh:       # only a non-empty answer moves these; an empty one keeps the last values
        rec["newest_submission"] = max(fresh, rec.get("newest_submission", ""))
    if items:
        rec["crash_count"] = len(mine)
    if shots.get("seen"):
        rec["screenshot_count"] = int(shots["seen"])


def pull(client, conn, now: dt.datetime | None = None, paths: list[str] | None = None) -> dict:
    """One pass over every product with a bundle id. Never raises; a failed app keeps its last good numbers
    and gets `last_error`. Returns {"apps": [{product, status, text, new_crashes, ...}], "errors": n}."""
    now = now or _now()
    state = load()
    errors = 0
    for app in apps(paths):
        rec = state["apps"].setdefault(app["bundle_id"], {"product": app["product"]})
        try:
            _pull_app(app, rec, client, conn, state, now)
        except (review_asc.AscError, OSError) as e:
            rec["last_error"] = " ".join(str(e).split())[:200]
            rec["last_attempt"] = _iso(now)
            errors += 1
        except Exception as e:  # noqa: BLE001 — a malformed answer must not stop the other apps
            rec["last_error"] = f"unexpected answer ({type(e).__name__})"
            errors += 1
    keep = sorted(state["crashes"].values(), key=lambda c: c.get("created_at", ""), reverse=True)[:KEEP]
    dropped = set(state["crashes"]) - {c["id"] for c in keep}
    for cid in dropped:
        (store_dir() / f"{cid}.log").unlink(missing_ok=True)
    state["crashes"] = {c["id"]: c for c in keep}
    state["updated"] = _iso(now)
    save(state)
    out = []
    for bundle, rec in sorted(state["apps"].items()):
        st, txt = freshness(rec, now)
        out.append({"product": rec.get("product", bundle), "app_id": rec.get("app_id", ""), "status": st, "text": txt,
                    "crashes": rec.get("crash_count", 0), "new_crashes": rec.get("new_crashes", 0),
                    "screenshots": rec.get("screenshot_count", 0), "new_screenshots": rec.get("new_screenshots", 0),
                    "newest_submission": rec.get("newest_submission", ""), "newest_upload": rec.get("newest_upload", ""),
                    "last_pull": rec.get("last_pull", "")})
    return {"apps": out, "errors": errors}


# --- the report -------------------------------------------------------------------------------------------------

def report(days: int, now: dt.datetime | None = None) -> dict:
    """What `teyla crash --device` shows: crashes of the last `days`, newest first, and one freshness row per app.
    Reads the local store only."""
    now = now or _now()
    st = load()
    floor = now - dt.timedelta(days=days)
    crashes = sorted((c for c in st["crashes"].values() if (_ts(c.get("created_at")) or now) >= floor),
                     key=lambda c: c.get("created_at", ""), reverse=True)
    rows = []
    for bundle, rec in sorted(st["apps"].items()):
        status, text = freshness(rec, now)
        rows.append({"product": rec.get("product", bundle), "status": status, "text": text,
                     "last_pull": rec.get("last_pull", ""), "newest_submission": rec.get("newest_submission", ""),
                     "crash_count": rec.get("crash_count", 0), "screenshot_count": rec.get("screenshot_count", 0)})
    return {"days": days, "crashes": crashes, "apps": rows}


def render(rep: dict, header: bool = True) -> str:
    out = ["Device crashes (TestFlight, App Store Connect)"] if header else []
    if not rep["apps"]:
        out.append("  no feed yet: `teyla crash --pull` reads it once; `teyla config set crash.feed_agent=true "
                   "&& teyla routine install` keeps it hourly")
        return "\n".join(out)
    for c in rep["crashes"]:
        s = c.get("summary") or {}
        what = s.get("exception") or s.get("termination") or "crash log not available"
        top = f" at {s['frames'][0]}" if s.get("frames") else ""
        out.append(f"  {c['created_at'][:16].replace('T', ' ')}  {c['product']} {c['platform'] or ''} build {c['build'] or '?'}"
                   f"  {c['device'] or 'unknown device'}: {what}{top}")
        if c.get("comment"):
            out.append(f"      tester: {c['comment'][:120]}")
    if not rep["crashes"]:
        out.append(f"  no device crash in the last {rep['days']} days")
    for r in rep["apps"]:
        mark = "" if r["status"] == "ok" else f"  [{r['status']}]"
        out.append(f"  feed {r['product']}: {r['crash_count']} crash(es), {r['screenshot_count']} screenshot(s) on record; "
                   f"newest {r['newest_submission'][:10] or 'none'}; pulled {r['last_pull'][:16].replace('T', ' ') or 'never'}; "
                   f"{r['text']}{mark}")
    return "\n".join(out)


def doctor_row(now: dt.datetime | None = None) -> tuple[str, str, str | None] | None:
    """(level, detail, fix) for doctor's `testflight:feed`, or None when no pull ever ran (nothing to judge)."""
    st = load()
    if not st["apps"]:
        return None
    bad = problems(now)
    if bad:
        extra = f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""
        return "WARN", f"{bad[0][0]}: {bad[0][1]}{extra}", "teyla crash --pull --allow-network, then teyla crash --device"
    return "OK", f"{len(st['apps'])} app(s) pulled and fresh", None

