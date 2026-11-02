"""`teyla portfolio` — where every registered product stands, per platform, and whether it is on track.

    teyla portfolio [--json] [--refresh] [--product ID] [--allow-network]

The object is `portfolio` in `teyla state --json` (version 3, `docs/APP.md`, "Version 3: the portfolio").
Building it never calls the network. It joins what Teyla already keeps:

    the registry          ~/.teyla/products.toml: title, stage, focus, primary platform, repos
    the repo manifest     `[productize]` in each repo's teyla.toml: users, target, platforms, primary, and the
                          requirement rows that give the milestone
    the snapshot          questions that wait, owner tasks, last activity (state.py)
    the GitHub backlog    ~/.teyla/state-backlog.json (open PRs, as a fallback for the counts below)
    the review ledger     ~/.cache/review-ledger.tsv, read when the object is built
    the portfolio cache   ~/.teyla/portfolio-cache.json (0600): the parts that need a network call or a slow read
    the usage cache       ~/.teyla/products-cache.json (0600): the counters `teyla products` printed last

`teyla portfolio --refresh` is the pass that fills the cache, in three independent parts:

    stores     `teyla testflight` and `teyla play` for each product in scope (the release tools, 80 s or so)
    github     merged PRs of the last 7 days per repo and the owner's open PRs (the calls of `teyla reviews`
               and the backlog), kept as compact rows so the ledger is read when the object is built
    activity   sessions and spend of the last 7 days per product, read from the local transcripts (no network)

A part that fails keeps the rows it had, with their old `as_of`; it never blanks good data. `checked.stores`
and `checked.github` move only when the whole part worked. `teyla state` starts the pass detached when the cache
is missing or older than 6 hours (not in safe mode, not without `gh`), and a lock stops a second one.

Platform state: `current` (the newest build reached the owner), `behind`, `blocked` (only the owner can clear it),
`none`, `unknown`; `live` only where the data says so: a web page whose URL the repo declares
(`[productize] url`, or `[release] web_url`; Teyla does not open it) and a Google Play production release that
is rolling out. The tool payloads carry no App Store public version or review state, so iOS and macOS are
never `live` or `in_review`.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

from . import asks, backlog, net, productize, registry, reviews, testflight
from .control import state as control

VERSION = 1
CACHE_VERSION = 1
FRESH_S = 6 * 3600                 # an older cache starts one refresh
LOCK_STALE_S = 1800                # the pass reads two stores and every repo: minutes
WEEK_DAYS = 7
BEHIND_OFF_TRACK_DAYS = 2
WAIT_AT_RISK_DAYS = 3
WAIT_OFF_TRACK_DAYS = 7
QUIET_DAYS = 14
MAX_REASONS = 3
CORE_MAX = 6
CORE_SPEND_USD = 40.0              # the rule: a product that took this much spend in 7 days is core
TOP_PRS = 3
LINE_WORDS = 12
DETAIL_CHARS = 140
TITLE_CHARS = 100
REASON_DETAIL_CHARS = 60
PLATFORMS = ("ios", "macos", "android", "web", "watch")
PLATFORM_LABEL = {"ios": "iOS", "macos": "macOS", "android": "Android", "web": "Web", "watch": "Watch"}
_PLATFORM_ALIASES = {"iphone": "ios", "mac": "macos", "osx": "macos", "garmin": "watch", "wear": "watch"}
ASC_PLATFORM = {"IOS": "ios", "MAC_OS": "macos"}
HEALTH_ORDER = {"off_track": 0, "at_risk": 1, "on_track": 2, "parked": 3}
HEALTH_WORD = {"off_track": "off track", "at_risk": "at risk", "on_track": "on track", "parked": "parked"}
STATE_ORDER = ("blocked", "behind", "none", "unknown", "in_review", "current", "live")

# A TestFlight blocker only the owner can clear: the tester never accepted, was never invited, or a review needs a change.
_TF_OWNER = re.compile(r"not accepted|never invited|revoked|not submitted for beta review|in no group|rejected", re.I)
# A Play blocker only the owner can clear: a draft to send, a halted release, a closed test to start.
_PLAY_OWNER = re.compile(r"draft|halted|no closed test|clock is not running", re.I)

EMPTY_CACHE = {"version": CACHE_VERSION, "at": 0.0, "checked": {"stores": "", "github": "", "activity": ""},
               "stores": {}, "github": {}, "open_prs": {}, "activity": {}}


# --- the cache --------------------------------------------------------------------------------

def cache_path() -> pathlib.Path:
    return control.home() / "portfolio-cache.json"


def lock_path() -> pathlib.Path:
    return control.home() / "portfolio-refresh.lock"


def load_cache() -> dict:
    """The cache with every field present; the empty cache when the file is missing or unreadable."""
    out = copy.deepcopy(EMPTY_CACHE)
    try:
        c = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return out
    if not isinstance(c, dict) or c.get("version") != CACHE_VERSION:
        return out
    for k in ("stores", "github", "open_prs", "activity"):
        if isinstance(c.get(k), dict):
            out[k] = c[k]
    if isinstance(c.get("checked"), dict):
        for k in out["checked"]:
            out["checked"][k] = str(c["checked"].get(k) or "")
    try:
        out["at"] = float(c.get("at") or 0)
    except (TypeError, ValueError):
        pass
    return out


def save_cache(cache: dict) -> None:
    asks._atomic_write(cache_path(), json.dumps(cache, indent=1))     # 0600, atomic


def usage_cache_path() -> pathlib.Path:
    return control.home() / "products-cache.json"


def load_usage_cache() -> dict:
    """{repo folder name (lowercase): {counter: value}} from the last `teyla products`; {} when there is none."""
    try:
        c = json.loads(usage_cache_path().read_text())
    except (OSError, ValueError):
        return {}
    repos = c.get("repos") if isinstance(c, dict) and c.get("version") == 1 else None
    out = {}
    for name, row in (repos or {}).items():
        if isinstance(row, dict) and row.get("status") == "ok" and isinstance(row.get("counters"), dict):
            out[str(name).lower()] = {str(k): str(v) for k, v in row["counters"].items()}
    return out


def enabled(cfg: dict | None = None) -> bool:
    """The network pass may start only outside safe mode and with `gh` on PATH, as the backlog refresh."""
    try:
        return net.allowed(cfg) and shutil.which("gh") is not None
    except Exception:  # noqa: BLE001 — an unreadable config is "nothing starts"
        return False


def spawn_refresh(now: float | None = None) -> None:
    """Start one detached `teyla portfolio --refresh --background`. The lock is created exclusively; one
    older than LOCK_STALE_S is taken over. The child removes the lock when it ends."""
    now = asks._now() if now is None else now
    lock = lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            if now - lock.stat().st_mtime < LOCK_STALE_S:
                return
            os.utime(lock, (now, now))
        subprocess.Popen([sys.executable, "-m", "teyla", "portfolio", "--refresh", "--background"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        pass


def maybe_refresh(cache: dict, now: float) -> bool:
    """Start a refresh when the cache is missing or older than 6 hours. True when one was asked for."""
    if cache["at"] and now - cache["at"] < FRESH_S:
        return False
    if not enabled():
        return False
    spawn_refresh(now)
    return True


# --- small helpers ----------------------------------------------------------------------------

def _iso(epoch: float) -> str:
    return asks._iso(epoch)


def _clip(text: str, n: int = DETAIL_CHARS) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def norm_platform(raw) -> str:
    p = str(raw or "").strip().lower()
    p = _PLATFORM_ALIASES.get(p, p)
    return p if p in PLATFORMS else ""


def product_repos(p: dict) -> list[pathlib.Path]:
    return [registry.abs_path(d) for d in p.get("repos") or []]


def parse_manifests(repos: list[pathlib.Path]) -> list[dict]:
    """The parsed teyla.toml of each repo that has one and that parses."""
    out = []
    for r in repos:
        f = r / "teyla.toml"
        if f.is_file():
            m = productize.parse(f)
            if "error" not in m:
                out.append(m)
    return out


def _slugs(repos: list[pathlib.Path], canonical: dict) -> list[str]:
    out = []
    for r in repos:
        s = backlog.remote_slug(r)
        if s:
            full = canonical.get(s.lower(), s)
            if full.lower() not in [x.lower() for x in out]:
                out.append(full)
    return out


def declared_platforms(reg_product: dict, manifests: list[dict]) -> tuple[list[str], str]:
    """(platforms, primary): from `[productize]` of the first manifest that declares them, else the registry's
    primary alone. Primary first."""
    plats: list[str] = []
    primary = ""
    for m in manifests:
        pz = m.get("productize") or {}
        for x in pz.get("platforms") or []:
            n = norm_platform(x)
            if n and n not in plats:
                plats.append(n)
        primary = primary or norm_platform(pz.get("primary"))
    primary = primary or norm_platform(reg_product.get("primary"))
    if primary and primary not in plats and not plats:
        plats = [primary]
    if not primary and plats:
        primary = plats[0]
    if primary in plats:
        plats = [primary] + [p for p in plats if p != primary]
    return plats, primary


def _distribution(manifests: list[dict], plat: str) -> str:
    for m in manifests:
        v = str(((m.get("productize") or {}).get("distribution") or {}).get(plat) or "").strip().lower()
        if v:
            return v
    return ""


def channel_of(plat: str, manifests: list[dict]) -> str:
    dist = _distribution(manifests, plat)
    if plat in ("ios", "macos"):
        return "app_store" if dist == "app-store" else "testflight" if dist.startswith("testflight") else "local"
    if plat == "android":
        return "play" if dist in ("play-internal", "play") else "local"
    return "web" if plat == "web" else "local"


def web_url(manifests: list[dict]) -> str:
    """The site URL a repo declares (`[productize] url`, or `[release] web_url`); "" when none or not http(s)."""
    for m in manifests:
        for v in ((m.get("productize") or {}).get("url"), (m.get("release") or {}).get("web_url")):
            u = str(v or "").strip()
            if urlparse(u).scheme in ("http", "https") and urlparse(u).netloc:
                return u
    return ""


# --- store rows: TestFlight and Play payloads -> platform rows ---------------------------------

def _row(plat: str, channel: str, state: str, detail: str, *, version: str = "", build: str = "",
         as_of: str = "", link: str = "", since: float | None = None, behind: int = 0,
         review_unknown: bool = False) -> dict:
    return {"platform": plat, "channel": channel, "version": str(version or ""), "build": str(build or ""),
            "state": state, "detail": _clip(detail), "as_of": as_of, "link": link,
            "review_unknown": review_unknown, "_since": since, "_behind": behind}


def _build_blocker(text: str) -> str:
    """'121: processing' -> 'Build 121: processing'."""
    m = re.match(r"^(\S+): (.*)$", text.strip())
    return f"Build {m.group(1)}: {m.group(2)}" if m else text.strip()


def tf_blocker_detail(text: str) -> str:
    t = str(text)
    if re.search(r"not accepted", t, re.I):
        return "Invited, not accepted: tap View in TestFlight in Apple's e-mail"
    if re.search(r"never invited", t, re.I):
        return "In a TestFlight group but never invited: send the invitation again"
    return _build_blocker(t)


def _epoch(ts) -> float | None:
    return asks._epoch(ts) if ts else None


def testflight_rows(row: dict, now: float, prev: dict | None = None, declared: list[str] | None = None) -> dict[str, dict]:
    """{ios|macos: platform row} from one `testflight.check_product` row that was read (verdict not `error`).
    `prev` holds the rows of the last good read, which carry the time a platform fell behind; `declared` the
    platforms the manifest ships through TestFlight, which get a row even when the tool printed none."""
    prev = prev or {}
    as_of = _iso(now)
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    raw = {ASC_PLATFORM[p.get("platform")]: p for p in payload.get("platforms") or []
           if isinstance(p, dict) and p.get("platform") in ASC_PLATFORM}
    wanted = [ASC_PLATFORM[p["platform"]] for p in row.get("platforms") or [] if p.get("platform") in ASC_PLATFORM]
    out: dict[str, dict] = {}
    if payload.get("tester_found") is False:
        for key in wanted or declared or ["ios"]:
            out[key] = _row(key, "testflight", "blocked",
                            "Your tester e-mail is not on the App Store Connect team: add it and put it in a group",
                            as_of=as_of)
        return out
    verdicts = {ASC_PLATFORM[p["platform"]]: p for p in row.get("platforms") or [] if p.get("platform") in ASC_PLATFORM}
    for key, v in verdicts.items():
        p = raw.get(key) or {}
        inst, up = p.get("newest_installable") or {}, p.get("newest_uploaded") or {}
        blockers = [str(b) for b in p.get("blockers") or []]
        try:
            behind = max(int(p.get("behind") or v.get("behind") or 0), 0)
        except (TypeError, ValueError):
            behind = 0
        owner = next((b for b in blockers if _TF_OWNER.search(b)), "")
        old = prev.get(key) or {}
        # The clock starts when the platform first fell behind; a newer upload does not reset it.
        kept = old.get("_since") if old.get("state") in ("behind", "blocked") else None
        since = kept or _epoch(up.get("uploaded")) or now
        if v["verdict"] == "current":
            out[key] = _row(key, "testflight", "current", "Installable from your tester account",
                            version=inst.get("version"), build=inst.get("build"), as_of=as_of)
        elif owner:
            out[key] = _row(key, "testflight", "blocked", tf_blocker_detail(owner), version=inst.get("version"),
                            build=inst.get("build"), as_of=as_of, since=since, behind=behind)
        elif not up:
            out[key] = _row(key, "testflight", "none", "No build uploaded yet", as_of=as_of)
        else:
            n = behind or 1
            why = f": {_build_blocker(blockers[0])}" if blockers else ""
            out[key] = _row(key, "testflight", "behind", f"{n} build{'s' if n != 1 else ''} wait{'s' if n == 1 else ''}{why}",
                            version=inst.get("version"), build=inst.get("build"), as_of=as_of, since=since, behind=n)
    for key in declared or []:
        out.setdefault(key, _row(key, "testflight", "none", "No build uploaded yet", as_of=as_of))
    return out


def play_row(row: dict, now: float, prev: dict | None = None) -> dict:
    """The android platform row from one `play.check_product` row that was read (verdict not `error`).
    The most advanced track decides: a production release at a code at or above the newest internal one means
    the owner can already get the newest build, so an older internal release is not "behind"."""
    as_of = _iso(now)
    internal = row.get("internal") or {}
    prod = row.get("production") or {}
    blockers = [str(b) for b in row.get("blockers") or []]
    verdict = row.get("verdict")
    build = internal.get("code", "")
    version = internal.get("name", "")
    old = prev or {}
    since = (old.get("_since") if old.get("state") in ("behind", "blocked") else None) or now
    ahead = bool(prod) and (not internal or _code(prod.get("code")) >= _code(internal.get("code")))
    if ahead or verdict == "current":
        src, via = (prod, "production") if ahead else (internal, "internal")
        build, version = src.get("code", ""), src.get("name", "")
        if prod.get("status") == "inProgress":
            frac = prod.get("user_fraction")
            at = f" at {frac * 100:g}%" if isinstance(frac, (int, float)) else ""
            return _row("android", "play", "live", f"Rolling out to users on Play production{at}",
                        version=version, build=build, as_of=as_of)
        detail = "Newest build is on Play production" if via == "production" else "Installable from Play's internal track"
        return _row("android", "play", "current", detail, version=version, build=build, as_of=as_of)
    if verdict == "none" or not internal:
        return _row("android", "play", "none", "Nothing on Play's internal track yet", as_of=as_of)
    first = blockers[0] if blockers else "the internal release is not live"
    owner = next((b for b in blockers if _PLAY_OWNER.search(b)), "")
    # A draft or a staged internal release may sit in Play review, which the API does not report.
    unknown = internal.get("status") in ("draft", "inProgress")
    if owner:
        detail = ("Draft on Play's internal track; Play Console may show it in review (the API cannot tell)"
                  if owner.startswith("draft") else owner[:1].upper() + owner[1:])
        return _row("android", "play", "blocked", detail, version=version, build=build, as_of=as_of, since=since,
                    review_unknown=unknown)
    return _row("android", "play", "behind", first[:1].upper() + first[1:], version=version, build=build,
                as_of=as_of, since=since, review_unknown=unknown)


def _code(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _unknown(plat: str, channel: str, why: str) -> dict:
    return _row(plat, channel, "unknown", why)


def refresh_stores(reg: dict, cache: dict, now: float, cfg: dict | None = None) -> bool:
    """Read TestFlight and Play for each product in scope into `cache["stores"]`. True when every read worked.
    A failed read keeps the rows the product had (their `as_of` stays old); with none, it stores an `unknown` row."""
    from . import platform as platform_mod
    from . import play
    cfg = platform_mod.load() if cfg is None else cfg
    ok = True
    for pid, p in reg["product"].items():
        manifests = parse_manifests(product_repos(p))
        mine = cache["stores"].setdefault(pid, {})
        for m in manifests:
            for tool, in_scope, check in (("testflight", testflight.in_scope, testflight.check_product),
                                          ("play", play.in_scope, play.check_product)):
                if not in_scope(m):
                    continue
                keys = ["android"] if tool == "play" else [ASC_PLATFORM[a] for a in testflight.declared_platforms(m)
                                                           if a in ASC_PLATFORM] or ["ios"]
                try:
                    row = check(m, cfg)
                except Exception as e:  # noqa: BLE001 — one product's failure must not stop the pass
                    row = {"verdict": "error", "error": f"{type(e).__name__}: {e}"}
                if row.get("verdict") == "error":
                    ok = False
                    why = "Could not read " + ("Google Play" if tool == "play" else "App Store Connect") \
                          + ": " + _clip(row.get("error") or "unknown error", 100)
                    for k in keys:
                        have = mine.get(k)
                        if not (isinstance(have, dict) and have.get("as_of")):     # nothing good to keep
                            mine[k] = _unknown(k, "play" if k == "android" else "testflight", why)
                    continue
                if tool == "play":
                    mine["android"] = play_row(row, now, mine.get("android"))
                else:
                    mine.update(testflight_rows(row, now, mine, keys))
        if not mine:
            cache["stores"].pop(pid, None)
    if ok:
        cache["checked"]["stores"] = _iso(now)
    return ok


# --- GitHub: merged and open PRs ---------------------------------------------------------------

def compact_pr(pr: dict) -> dict:
    """A merged PR from `reviews.merged_prs`, cut to what `reviews.classify` needs at build time."""
    files = [str(f.get("path") or "") for f in pr.get("files") or [] if isinstance(f, dict)]
    merge = pr.get("mergeCommit") if isinstance(pr.get("mergeCommit"), dict) else {}
    return {"number": pr.get("number"), "title": _clip(pr.get("title") or "", TITLE_CHARS),
            "merged_at": str(pr.get("mergedAt") or ""),
            "head": str(pr.get("headRefOid") or ""), "merge": str(merge.get("oid") or ""),
            "commits": [str(c.get("oid") or "") for c in pr.get("commits") or [] if isinstance(c, dict)],
            "changed": int(pr.get("additions") or 0) + int(pr.get("deletions") or 0),
            "docs": bool(files) and all(reviews._is_docs(f) for f in files)}


def _pr_for_classify(c: dict) -> dict:
    return {"number": c.get("number"), "headRefOid": c.get("head"), "mergeCommit": {"oid": c.get("merge")},
            "commits": [{"oid": o} for o in c.get("commits") or []], "additions": int(c.get("changed") or 0),
            "deletions": 0, "files": [{"path": "x.md"}] if c.get("docs") else []}


def refresh_github(reg: dict, cache: dict, now: float, runner=None) -> bool:
    """Merged PRs of the last 7 days per repo and the owner's open PRs, into the cache. True when all worked."""
    runner = backlog.default_runner if runner is None else runner
    canonical = backlog.load()["canonical"]
    since = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).date() - _dt.timedelta(days=WEEK_DAYS)
    slugs: list[str] = []
    for p in reg["product"].values():
        for s in _slugs(product_repos(p), canonical):
            if s.lower() not in [x.lower() for x in slugs]:
                slugs.append(s)
    ok = True
    keep = {}
    for slug in slugs:
        prs, _note = reviews.merged_prs(slug, since, runner)
        if prs is None:
            ok = False
            old = cache["github"].get(slug.lower())
            if old:
                keep[slug.lower()] = old               # the old rows, with their old as_of
            continue
        keep[slug.lower()] = {"as_of": _iso(now), "prs": [compact_pr(x) for x in prs]}
    cache["github"] = keep
    opened = backlog.fetch_prs(runner)
    if opened is None:
        ok = False
    else:
        counts: dict[str, int] = {}
        for pr in opened:
            counts[pr["repo"].lower()] = counts.get(pr["repo"].lower(), 0) + 1
        cache["open_prs"] = counts
    if ok:
        cache["checked"]["github"] = _iso(now)
    return ok


# --- activity: sessions and spend per product ---------------------------------------------------

def compute_activity(reg: dict) -> dict:
    """{product id: {sessions_7d, spend_7d_usd}} from the local transcripts. Slow; the refresh runs it."""
    from . import product_page, spend
    rows, titles = product_page.load_rows(WEEK_DAYS)
    mine: dict[str, list[dict]] = {}
    for r in rows:
        pid = registry.attribute(r.get("cwd"), session=r["sid"], texts=(titles.get(r["sid"], ""), ""), reg=reg)[0]
        if pid in reg["product"]:
            mine.setdefault(pid, []).append(r)
    out = {}
    for pid, rs in mine.items():
        days = spend.by_day(WEEK_DAYS, rs)
        out[pid] = {"sessions_7d": len(rs), "spend_7d_usd": round(sum(d["total_usd"] for d in days), 2)}
    return out


# --- the refresh pass --------------------------------------------------------------------------

def refresh(now: float | None = None, *, reg: dict | None = None, cfg: dict | None = None, runner=None,
            network: bool | None = None) -> int:
    """Run the three parts and rewrite the cache. 0 when every part worked, 1 otherwise. Without the network
    (safe mode) only the local activity part runs. The cache is stamped with this attempt either way, so a
    permanent failure is retried in 6 hours and not on every snapshot."""
    now = asks._now() if now is None else now
    reg = registry.load() if reg is None else reg
    cache = load_cache()
    allowed = net.allowed(cfg) if network is None else network
    ok = True
    try:
        if allowed:
            for part in (lambda: refresh_stores(reg, cache, now, cfg),
                         lambda: refresh_github(reg, cache, now, runner)):
                try:
                    ok = part() and ok
                except Exception:  # noqa: BLE001 — a part that crashes keeps its old rows
                    ok = False
        else:
            ok = False
        try:
            cache["activity"] = compute_activity(reg)
            cache["checked"]["activity"] = _iso(now)
        except Exception:  # noqa: BLE001
            ok = False
    finally:
        cache["at"] = now
        try:
            save_cache(cache)
        except OSError:
            ok = False
    return 0 if ok else 1


# --- health ------------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def health_of(stage: str, platforms: list[dict], primary: str, open_p1: int, last_epoch: float | None,
              now: float) -> tuple[str, list[str]]:
    """(health, reasons) by the rules of docs/APP.md: every match adds a reason, at most three reasons, worst
    first. Health measures the product: its builds, its open P1s and its silence. A question that waits, or a
    PR nobody reviewed, is a fact about the owner's queue, not a failure of the product (see `facts_of`)."""
    if stage == "parked":
        return "parked", []
    off: list[str] = []
    risk: list[str] = []
    for p in platforms:
        label = PLATFORM_LABEL.get(p["platform"], p["platform"])
        is_primary = p["platform"] == primary
        if p["state"] == "blocked":
            line = f"{label} is blocked: {_clip(p['detail'], REASON_DETAIL_CHARS)}"
            (off if is_primary else risk).append(line)
        elif p["state"] == "behind":
            n = p.get("_behind") or 0
            what = f"{label} is {n} build{'s' if n != 1 else ''} behind" if n else f"{label} is behind"
            days = (now - p["_since"]) / 86400 if p.get("_since") else 0
            if is_primary and days > BEHIND_OFF_TRACK_DAYS:
                off.append(f"{what} for {int(days)} days")
            else:
                risk.append(what)
    if open_p1:
        off.append(f"{open_p1} merged {_plural(open_p1, 'PR has', 'PRs have')} an open P1")
    if stage in ("building", "beta"):
        if last_epoch is None:
            risk.append("No session recorded")
        elif (now - last_epoch) / 86400 > QUIET_DAYS:
            risk.append(f"No session for {int((now - last_epoch) // 86400)} days")
    if off:
        return "off_track", (off + risk)[:MAX_REASONS]
    if risk:
        return "at_risk", risk[:MAX_REASONS]
    return "on_track", []


def facts_of(waiting: int, oldest_days: float, unreviewed: int) -> list[str]:
    """Short strings for what health no longer counts, so nothing disappears from the card."""
    out = []
    if waiting:
        out.append(f"{waiting} {_plural(waiting, 'question waits', 'questions wait')}, the oldest {int(oldest_days)} days")
    if unreviewed:
        out.append(f"{unreviewed} {_plural(unreviewed, 'PR merged', 'PRs merged')} in 7 days "
                   f"{_plural(unreviewed, 'was', 'were')} never reviewed")
    return out


# --- the object --------------------------------------------------------------------------------

def _milestone(manifests: list[dict], mail_ready) -> tuple[str, str, str]:
    """(users, target, milestone) from the first manifest that declares `[productize]`."""
    for m in manifests:
        if not m.get("productize"):
            continue
        pz = m["productize"]
        public = str(pz.get("target") or pz.get("users") or "") == "public"
        rep = productize.evaluate(m, mail_ready=mail_ready() if public else None)
        users, target = rep.get("users", ""), rep.get("target", "")
        rows = rep.get("requirements") or []
        if target in productize.SHAREABLE and target != users and rows:
            left = sum(1 for r in rows if not r["met"])
            text = f"{target}: {left} of {len(rows)} requirements left" if left else f"{target}: all requirements met"
            return users, target, text
        return users, target, ""
    return "", "", ""


def _platform_rows(plats: list[str], primary: str, manifests: list[dict], stored: dict,
                   stores_checked: bool = True) -> list[dict]:
    """The platform rows. Until a whole store pass has worked (`checked.stores` is empty), a stored `behind`
    is not trusted: a half-read store says `unknown`, never `behind`."""
    out = []
    url = web_url(manifests)
    for plat in plats:
        channel = channel_of(plat, manifests)
        have = stored.get(plat) if isinstance(stored.get(plat), dict) else None
        if plat == "web" and url:
            row = _row("web", "web", "live", urlparse(url).netloc, link=url)
        elif have:
            row = {**_row(plat, have.get("channel") or channel, "unknown", ""), **have}
            if row["state"] == "behind" and not stores_checked:
                row.update(state="unknown", detail="Not fully checked yet", _behind=0, _since=None)
        elif channel == "local":
            row = _row(plat, "local", "unknown", "No store build is tracked")
        else:
            row = _row(plat, channel, "unknown", "Not checked yet")
        row["platform"] = plat
        row["role"] = "primary" if plat == primary else "secondary"
        out.append(row)
    return out


def _public(row: dict) -> dict:
    keys = ("platform", "role", "channel", "version", "build", "state", "detail", "as_of", "link")
    out = {k: row.get(k, "") if k != "state" else (row.get(k) or "unknown") for k in keys}
    out["review_unknown"] = bool(row.get("review_unknown"))
    return out


# Titles of PRs that say nothing about the product: release bumps, regenerated gates, merge commits.
MECHANICAL_TITLES = tuple(re.compile(x, re.I) for x in (
    r"^release\s+v?\d+(\.\d+)+",
    r"^(chore(\([^)]*\))?[:!]?\s*)?(bump|version bump)\b",
    r"^chore\(release\)",
    r"^v?\d+\.\d+(\.\d+)*$",
    r"^regenerate\b.*\bleak gate\b",
    r"^merge (branch|remote-tracking branch)\b",
))


def is_mechanical(title: str) -> bool:
    t = " ".join(str(title or "").split())
    return bool(t) and any(rx.search(t) for rx in MECHANICAL_TITLES)


def _github_view(slugs: list[str], names: set[str], cache: dict, bl: dict, ledger: dict | None,
                 threshold: int, now: float) -> dict:
    cut = now - WEEK_DAYS * 86400
    merged = unreviewed = p1 = shipped = 0
    titled: list[tuple[float, str]] = []
    for s in slugs:
        entry = cache["github"].get(s.lower()) or {}
        for c in entry.get("prs") or []:
            at = asks._epoch(c.get("merged_at"))
            if at is None or at < cut:
                continue
            merged += 1
            title = " ".join(str(c.get("title") or "").split())
            if not is_mechanical(title):
                shipped += 1
                if title:
                    titled.append((at, title))
            if ledger is not None:
                state = reviews.classify(_pr_for_classify(c), names | {s.lower(), s.split("/")[-1].lower()},
                                         ledger, threshold)["state"]
                unreviewed += state == "unreviewed"
                p1 += state == "open_p1"
    lower = {s.lower() for s in slugs}
    if cache["checked"]["github"]:
        opened = sum(n for slug, n in cache["open_prs"].items() if slug in lower)
    else:
        opened = sum(1 for pr in bl.get("prs") or [] if str(pr.get("repo")).lower() in lower)
    titled.sort(key=lambda x: -x[0])
    return {"open": opened, "merged_7d": merged, "unreviewed_7d": unreviewed, "open_p1": p1,
            "shipped": shipped, "top": [t for _, t in titled[:TOP_PRS]]}


# --- usage: the counters `teyla products` printed -----------------------------------------------------

_WEEKLY_KEYS = ("wau", "weekly_users", "weekly_active", "active_users_7d", "users_7d", "active_7d")
_TOTAL_KEYS = ("users_total", "total_users", "users", "user_count", "accounts")


def _int(v) -> int | None:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def usage_of(repos: list[pathlib.Path], usage: dict) -> dict | None:
    """{weekly, total, label} summed over the product's repos from the cached usage counters (the keys of
    templates/analytics/STANDARD.md: `wau=`, `users=`). None when no repo has a cached probe with a user count."""
    weekly: int | None = None
    total: int | None = None
    for r in repos:
        counters = usage.get(r.name.lower())
        if not counters:
            continue
        for keys, which in ((_WEEKLY_KEYS, "w"), (_TOTAL_KEYS, "t")):
            n = next((v for v in (_int(counters.get(k)) for k in keys) if v is not None), None)
            if n is None:
                continue
            if which == "w":
                weekly = (weekly or 0) + n
            else:
                total = (total or 0) + n
    if weekly is None and total is None:
        return None
    bits = []
    if weekly is not None:
        bits.append(f"{weekly} active this week")
    if total is not None:
        bits.append(f"{total} total")
    return {"weekly": weekly, "total": total, "label": ", ".join(bits)}


# --- the core products ----------------------------------------------------------------------------------

def core_view(reg: dict, cache: dict, usage: dict) -> tuple[list[str], str, dict]:
    """(ids, source, detail): the products the home screen leads with. When the owner starred any product
    (`focus`), the core is exactly the starred ones. Otherwise the rule: not parked, and a weekly user or
    CORE_SPEND_USD of spend in 7 days. Ranked by spend, at most CORE_MAX. `detail` is {id: (spend, weekly)}."""
    rows = []
    for pid, rp in reg["product"].items():
        spend = float((cache["activity"].get(pid) or {}).get("spend_7d_usd") or 0)
        u = usage_of(product_repos(rp), usage)
        weekly = (u or {}).get("weekly") or 0
        rows.append((pid, rp, spend, weekly))
    starred = [r for r in rows if r[1].get("focus")]
    if starred:
        pool, source = starred, "star"
    else:
        pool = [r for r in rows if r[1].get("stage") != "parked" and (r[3] >= 1 or r[2] >= CORE_SPEND_USD)]
        source = "rule"
    pool.sort(key=lambda r: (-r[2], -r[3], r[0]))
    pool = pool[:CORE_MAX]
    return [r[0] for r in pool], source, {r[0]: (r[2], r[3]) for r in pool}


# --- progress: facts only --------------------------------------------------------------------------------

def _can_install(rows: list[dict]) -> list[dict]:
    """The platforms where a build is known, primary first. A platform with no known build is left out."""
    out = []
    for r in rows:
        known = r["state"] in ("current", "live", "in_review", "behind", "blocked") and (r["version"] or r["build"])
        if known or r["state"] == "live":
            out.append({"platform": r["platform"], "version": r["version"], "build": r["build"],
                        "channel": r["channel"], "state": r["state"]})
    return out


def _cut_words(text: str, n: int = LINE_WORDS) -> str:
    w = text.split()
    return text if len(w) <= n else " ".join(w[:n])


def _build_phrase(row: dict) -> str:
    label = PLATFORM_LABEL.get(row["platform"], row["platform"])
    what = " ".join(x for x in (row["version"], f"({row['build']})" if row["build"] else "") if x)
    if row["state"] == "live":
        return f"{label} {what} is live".replace("  ", " ")
    if row["state"] == "current" and what:
        return f"{label} {what} is installable"
    if row["state"] == "behind" and what:
        return f"{label} {what} is behind"
    return ""


def line_of(open_p1: int, milestone: str, primary_row: dict | None, quiet_days: int | None) -> str:
    """One sentence for a card: the first of open P1s, the milestone, the primary build, silence."""
    if open_p1:
        return _cut_words(f"{open_p1} merged {_plural(open_p1, 'PR has', 'PRs have')} an open P1")
    if milestone:
        return _cut_words(milestone)
    phrase = _build_phrase(primary_row) if primary_row else ""
    if phrase:
        return _cut_words(phrase)
    if quiet_days:
        return f"Quiet for {quiet_days} {_plural(quiet_days, 'day', 'days')}"
    return ""


def empty(cache: dict | None = None) -> dict:
    cache = cache or load_cache()
    return {"version": VERSION, "checked": {"stores": cache["checked"]["stores"], "github": cache["checked"]["github"]},
            "counts": {"on_track": 0, "at_risk": 0, "off_track": 0, "parked": 0}, "core": [], "core_source": "rule",
            "products": []}


def build(now: float, *, reg: dict, prods: list[dict], ask_rows: list[dict], tasks: list[dict], bl: dict,
          ledger: dict | None, cache: dict | None = None, threshold: int | None = None,
          mail_ready=None, usage: dict | None = None) -> dict:
    """The `portfolio` object, from the registry and the caches only. `prods` are the snapshot's product rows
    (last activity, waiting, next, repo); `ask_rows` its open questions; `tasks` the owner's tasks; `usage` the
    counters of the last `teyla products` (read from its cache when not given)."""
    cache = load_cache() if cache is None else cache
    usage = load_usage_cache() if usage is None else usage
    threshold = reviews.min_lines() if threshold is None else threshold
    mail = mail_ready if mail_ready is not None else _mail_ready
    by_prod = {p["id"]: p for p in prods}
    canonical = bl.get("canonical") or {}
    stores_checked = bool(cache["checked"]["stores"])
    items = []
    for pid, rp in reg["product"].items():
        repos = product_repos(rp)
        manifests = parse_manifests(repos)
        users, target, milestone = _milestone(manifests, mail)
        plats, primary = declared_platforms(rp, manifests)
        rows = _platform_rows(plats, primary, manifests, cache["stores"].get(pid) or {}, stores_checked)
        slugs = _slugs(repos, canonical)
        names = {r.name.lower() for r in repos}
        gh = _github_view(slugs, names, cache, bl, ledger, threshold, now)
        row = by_prod.get(pid) or {}
        mine = [a for a in ask_rows if a["product"] == pid and not a.get("muted")]
        oldest = round(max((a["age_s"] for a in mine), default=0) / 86400, 1)
        owner_tasks = [t for t in tasks if t["product"] == pid]
        last = row.get("last_activity") or ""
        last_epoch = asks._epoch(last) if last else None
        act = cache["activity"].get(pid) or {}
        stage = rp.get("stage") or ""
        health, reasons = health_of(stage, rows, primary, gh["open_p1"], last_epoch, now)
        blocked = next((r for r in rows if r["state"] == "blocked"), None)
        quiet = max(int((now - last_epoch) // 86400), 0) if last_epoch is not None else None
        primary_row = next((r for r in rows if r["platform"] == primary), None)
        progress = {"can_install": _can_install(rows),
                    "shipped_7d": {"prs": gh["shipped"], "top": gh["top"]},
                    "users": usage_of(repos, usage), "milestone": milestone, "blocker": "",
                    "quiet_days": quiet, "line": line_of(gh["open_p1"], milestone, primary_row, quiet)}
        items.append({
            "id": pid, "title": row.get("display_name") or rp.get("name") or pid, "stage": stage,
            "focus": bool(rp.get("focus")), "primary": primary or norm_platform(rp.get("primary")),
            "users": users, "target": target, "health": health, "reasons": reasons,
            "facts": facts_of(len(mine), oldest, gh["unreviewed_7d"]),
            "platforms": [_public(r) for r in rows],
            "prs": {"open": gh["open"], "waiting": sum(1 for t in owner_tasks if t["kind"] == "merge"),
                    "merged_7d": gh["merged_7d"], "unreviewed_7d": gh["unreviewed_7d"], "open_p1": gh["open_p1"]},
            "activity": {"last": last, "sessions_7d": int(act.get("sessions_7d") or 0),
                         "spend_7d_usd": float(act.get("spend_7d_usd") or 0)},
            "waiting": len(mine), "oldest_wait_days": oldest, "tasks": len(owner_tasks), "milestone": milestone,
            "progress": progress,
            "next": row.get("next") or (blocked["detail"] if blocked and health != "parked" else ""),
            "repo": row.get("repo") or "",
        })
    items.sort(key=lambda x: (HEALTH_ORDER[x["health"]], not x["focus"], -(asks._epoch(x["activity"]["last"]) or 0), x["id"]))
    counts = {k: sum(1 for x in items if x["health"] == k) for k in ("on_track", "at_risk", "off_track", "parked")}
    core, source, _ = core_view(reg, cache, usage)
    return {"version": VERSION, "checked": {"stores": cache["checked"]["stores"], "github": cache["checked"]["github"]},
            "counts": counts, "core": core, "core_source": source, "products": items}


def _mail_ready() -> bool:
    """Whether the platform can send sign-in mail: only a `public` target needs it (R8)."""
    try:
        from . import platform as platform_mod
        return platform_mod.mail_ready()
    except Exception:  # noqa: BLE001
        return False


def only(pf: dict, pid: str) -> dict | None:
    """The portfolio cut to one product (counts recomputed); None when the id is not in it."""
    rows = [p for p in pf["products"] if p["id"] == pid]
    if not rows:
        return None
    counts = {k: sum(1 for x in rows if x["health"] == k) for k in pf["counts"]}
    return {**pf, "counts": counts, "core": [c for c in pf.get("core") or [] if c == pid], "products": rows}


# --- the command -------------------------------------------------------------------------------

def render_text(pf: dict) -> str:
    if not pf["products"]:
        return "No product is registered (teyla product init --write).\n"
    lines = []
    for p in pf["products"]:
        strip = " ".join(f"{x['platform']} {x['state'].replace('_', ' ')}" for x in p["platforms"]) or "no platform"
        wait = f"{p['waiting']} waiting" if p["waiting"] else ""
        lines.append(f"{HEALTH_WORD[p['health']]:<9} {p['title'][:22]:<22} {strip}" + (f"  {wait}" if wait else ""))
        for r in p["reasons"]:
            lines.append(f"            {r}")
    c = pf["checked"]
    lines.append(f"stores checked {c['stores'] or 'never'}, github checked {c['github'] or 'never'}")
    return "\n".join(lines) + "\n"


def cmd_portfolio(args) -> int:
    from . import state
    now = asks._now()
    code = 0
    if args.refresh:
        background = getattr(args, "background", False)
        lock = lock_path()
        if not background:
            # A refused run must not delete the lock of the run that holds it.
            lock.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            except FileExistsError:
                if now - lock.stat().st_mtime < LOCK_STALE_S:
                    print("teyla: a portfolio refresh is already running", file=sys.stderr)
                    return 1
                os.utime(lock, (now, now))
        try:
            if not background and not net.allowed():
                print(net.refusal("the store and GitHub reads of `teyla portfolio --refresh`"), file=sys.stderr)
            code = refresh(now)
        finally:
            lock.unlink(missing_ok=True)
        if background:
            return code
    st = state.build(now, model_brief=False)
    pf = st["portfolio"]
    if args.product:
        pf = only(pf, args.product)
        if pf is None:
            print(f"teyla: no product '{args.product}' in the portfolio", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(pf, indent=1))
    else:
        print(render_text(pf), end="")
    return code


def register(sp):
    q = sp.add_parser("portfolio", help="where every product stands: health, platforms, PRs, spend (cache only; --refresh reads the stores and GitHub)")
    q.set_defaults(fn=cmd_portfolio)
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh", action="store_true", help="run the network pass first: TestFlight, Play, GitHub")
    q.add_argument("--product", metavar="ID", help="only this product")
    q.add_argument("--allow-network", action="store_true", help="safe mode: let the refresh reach the stores and GitHub this once")
    q.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    return q
