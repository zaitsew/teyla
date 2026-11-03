"""The console's Operations section (`docs/CONSOLE.md`): what failed or needs capacity.

    teyla console operations [--json]

Everything here is read from what the machine and Teyla already keep, in one pass that makes no network
call and returns in well under 20 seconds. Each part runs on its own thread with its own error: a part that
fails or is late leaves its field `null` and names the reason under `notes`; the others still load.

    machine      `load.py` snapshot and verdict, the disk from `storage.disk`, 24 h of disk and swap from `load.tsv`
    failures     `attention.collect` (offline): schedules, P1s, builds, disk, doctor, guard, offers
    schedules    the scheduled tasks as `teyla schedules` judges them, from the registry in memory
    harnesses    `harness.status` + `policy.status`, versions from `<binary> --version`
    policy_sync  `policy.drift` for the generated AGENTS.md copies, the hand-edit inbox, AGENTS.md vs CLAUDE.md per repo
    security     the last cached results of `teyla deps`, `teyla leak --published` and `teyla reviews`

Shield has no cache, so `shield_issues` is `null` until it has one. A number whose source is missing is `null`;
nothing is estimated.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import threading
import time

BUDGET_S = 15.0                 # the whole pass; the console promises 20 s
ATTENTION_TIMEOUT_S = 12.0
VERSION_TIMEOUT_S = 6.0
SERIES_HOURS = 24
SERIES_POINTS = 96
TOP_FAILURES = 3
GIB = 1024 ** 3
HARNESS_ORDER = ("claude-code", "codex", "grok", "hermes", "cursor")
POLICY_AGENTS = ("codex", "grok")           # the harnesses that read a generated ~/.<h>/AGENTS.md


def _gb(n) -> float | None:
    return None if not isinstance(n, (int, float)) or isinstance(n, bool) else round(n / GIB, 1)


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(timespec="seconds")


# --- running the parts -------------------------------------------------------------------------------------

def run_parts(parts: dict, budget_s: float = BUDGET_S) -> tuple[dict, dict]:
    """(values, notes). Every part on a daemon thread; one that raises or is not done by the deadline gives
    no value and a note. Nothing a part does can stop the others."""
    out: dict = {}
    notes: dict = {}

    def work(name, fn):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 - a broken source must become a note, not a missing section
            notes[name] = f"{type(e).__name__}: {e}"[:160]

    threads = {n: threading.Thread(target=work, args=(n, fn), daemon=True) for n, fn in parts.items()}
    for t in threads.values():
        t.start()
    deadline = time.monotonic() + budget_s
    for n, t in threads.items():
        t.join(max(0.0, deadline - time.monotonic()))
        if t.is_alive():
            notes[n] = f"no answer in {int(budget_s)} s"
    return out, notes


class Once:
    """A value computed by the first caller; a second caller waits for it instead of computing it again.
    The scheduled-task scan takes seconds (the transcripts), and two parts need its result."""

    def __init__(self, fn):
        self._fn, self._lock, self._done, self._value, self._error = fn, threading.Lock(), False, None, None

    def get(self):
        with self._lock:
            if not self._done:
                try:
                    self._value = self._fn()
                except Exception as e:  # noqa: BLE001 - kept, so the second caller fails the same way at once
                    self._error = e
                self._done = True
        if self._error is not None:
            raise self._error
        return self._value


# --- machine -----------------------------------------------------------------------------------------------

def downsample(points: list, n: int = SERIES_POINTS) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n - 1)] + [points[-1]]


def series(now: float, records: list[dict] | None = None) -> dict:
    """`{disk: [[epoch, GB free]], swap: [[epoch, GB used]]}` for the last 24 hours of `load.tsv`."""
    from . import load
    recs = load.read_records(since=now - SERIES_HOURS * 3600) if records is None else records
    disk = [[int(r["ts"]), _gb(r["disk_free_bytes"])] for r in recs if r.get("disk_free_bytes") is not None]
    swap = [[int(r["ts"]), _gb(r["swap_used_bytes"])] for r in recs if r.get("swap_used_bytes") is not None]
    return {"disk": downsample(disk), "swap": downsample(swap)}


def machine(now: float) -> dict:
    from . import load, storage
    conf = load.guard_conf()
    snap = load.safe_snapshot()
    m: dict = {"verdict": None, "reason": "the process table could not be read", "ram_gb": None, "swap_used_gb": None,
               "swap_total_gb": None, "compressor_gb": None, "pressure": None, "disk_free_gb": None,
               "disk_total_gb": None, "cpu_load": None, "cores": None, "sims": None, "builds": None,
               "agents": {"claude": None, "codex": None, "grok": None}, "lanes": None, "top": [],
               "series": {"disk": [], "swap": []}}
    try:
        d = storage.disk()
        m["disk_free_gb"], m["disk_total_gb"] = _gb(d["free"]), _gb(d["total"])
    except OSError:
        pass
    try:
        m["series"] = series(now)
    except Exception:  # noqa: BLE001 - a missing or damaged recorder file leaves the graphs empty
        pass
    if snap is None:
        return m
    verdict = load.assess(snap, conf, load.current_trend(snap, conf))
    p = snap.procs
    m.update(verdict=verdict.level, reason="; ".join(verdict.reasons[:2]), ram_gb=_gb(snap.ram_bytes),
             swap_used_gb=_gb(snap.swap_used_bytes), swap_total_gb=_gb(snap.swap_total_bytes),
             compressor_gb=_gb(snap.compressor_bytes), pressure=snap.pressure, cpu_load=snap.load1, cores=snap.ncpu,
             sims=p.sims, builds=p.builds, agents={"claude": p.claude, "codex": p.codex, "grok": p.grok},
             lanes=p.lanes, top=[{"name": n, "gb": _gb(b)} for n, b in p.top])
    if m["disk_free_gb"] is None and snap.disk_free_bytes is not None:
        m["disk_free_gb"] = _gb(snap.disk_free_bytes)
    return m


def leave(m: dict | None) -> dict:
    """Can the owner close the lid and go: the machine is not in trouble, the disk has room, no agent lane or
    build is still working. `ok` is null when the machine could not be read."""
    if not m or m.get("verdict") is None:
        return {"ok": None, "blockers": ["the machine state could not be read"]}
    from . import load
    blockers = []
    if m["verdict"] in load.BAD:
        blockers.append(f"the machine is {m['verdict']}: {m['reason']}".rstrip(": "))
    crit = load._num(load.guard_conf(), "disk_crit_gb")
    free = m.get("disk_free_gb")
    if free is not None and crit and free < crit:
        blockers.append(f"the disk has {free} GB free, under the {crit:g} GB line")
    if m.get("lanes"):
        blockers.append(f"{m['lanes']} headless agent lane(s) are still running")
    if m.get("builds"):
        blockers.append(f"{m['builds']} build(s) are still running")
    return {"ok": not blockers, "blockers": blockers}


# --- failures ----------------------------------------------------------------------------------------------

def failures(now: float, entries: Once | None = None, timeout: float = ATTENTION_TIMEOUT_S) -> list[dict]:
    """The items of `teyla attention`, offline. Two sources are swapped for the console's budget: schedules uses the
    entries read once for the Schedules list, and disk skips the sweep preview (several seconds)."""
    import functools

    from . import attention
    sources = dict(attention.SOURCES)
    sources["disk"] = functools.partial(attention.source_disk, sweep=False)
    if entries is not None:
        sources["schedules"] = lambda n, cfg: attention.source_schedules(n, cfg, full=entries.get())
    rep = attention.collect(now, sources=sources, timeout=timeout)
    out = []
    for it in rep["items"]:
        acts = it.get("actions") or []
        out.append({"title": it["title"], "detail": it["detail"], "severity": it["severity"],
                    "product": it.get("product") or "", "kind": it["kind"],
                    "action": attention.command_text(acts[0]["command"]) if acts else None})
    return out


# --- schedules ---------------------------------------------------------------------------------------------

def schedule_entries(now: float) -> list[dict]:
    from . import schedules
    return schedules.current(dt.datetime.fromtimestamp(now, dt.timezone.utc))


def schedule_rows(entries: list[dict]) -> dict:
    from . import schedules
    full = sorted(entries, key=schedules._sort_key)
    rows = [{"source": e["source"], "name": e["name"], "state": e["verdict"], "cadence": e["cadence"] or None,
             "last_run": schedules._iso(e.get("last_run")), "note": e.get("note") or None} for e in full]
    attention = sum(1 for e in full if schedules.is_problem(e))
    ok = sum(1 for e in full if e["verdict"] == "OK")
    return {"counts": {"attention": attention, "ok": ok, "other": len(full) - attention - ok}, "rows": rows}


# --- harnesses and the policy copies -----------------------------------------------------------------------

def _policy_word(value) -> str | None:
    return {True: "synced", False: "not wired"}.get(value)


def _harness_note(row: dict) -> str | None:
    if not row.get("present"):
        return None
    bits = [f"skills {row['skills']}/{row['skills_total']}"]
    hooks = row.get("hooks")
    bits.append({True: "hooks wired", False: "hooks not wired", None: "no hook mechanism"}[hooks])
    tr = row.get("trust")
    if tr and tr["total"] and tr["approved"] < tr["total"]:
        bits.append(f"hooks not approved ({tr['approved']}/{tr['total']})")
    return ", ".join(bits)


def versions(names: list[str], timeout: float = VERSION_TIMEOUT_S) -> dict:
    """`<binary> --version` for each name that has a binary, in parallel; null when it does not answer."""
    from . import health
    out: dict = {}

    def one(name):
        binary = health.find_binary(name) if name in health.BINARY else None
        out[name] = health.version(binary)[0] if binary else None

    threads = [threading.Thread(target=one, args=(n,), daemon=True) for n in names]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return {n: out.get(n) for n in names}


def harness_rows(ver=versions) -> list[dict]:
    from . import harness, policy
    pol = policy.status()
    rows = {r["harness"]: r for r in harness.status()}
    ver_of = ver(list(HARNESS_ORDER))
    out = []
    for name in HARNESS_ORDER:
        if name == "claude-code":
            present = harness.installed("claude-code")
            out.append({"name": name, "installed": present, "version": ver_of.get(name),
                        "policy": _policy_word(pol.get(name)) if present else None,
                        "note": "the plugin serves it; the global CLAUDE.md imports the policy" if present else None})
            continue
        r = rows.get(name)
        if r is None:
            continue                                  # switched off in [harness] disabled
        out.append({"name": name, "installed": bool(r.get("present")), "version": ver_of.get(name),
                    "policy": _policy_word(r.get("policy")) if r.get("present") else None, "note": _harness_note(r)})
    return out


def policy_sync(now: float) -> dict:
    from . import config, policy
    drift = []
    for h in POLICY_AGENTS:
        d = policy.drift(h)
        if d:
            drift.append({"harness": h, "why": d[0], "fix": d[1]})
    inbox = len(policy.pending_edits())
    repos = policy.repos_status(config.code_root())
    counts = {k: sum(1 for s, _ in repos if s == k) for k in ("ok", "differ", "missing", "none")}
    odd = sorted(n for s, n in repos if s in ("differ", "missing"))
    try:
        stamp = (pathlib.Path(policy.HOME) / ".teyla" / "policy-sync.stamp").stat().st_mtime
    except OSError:
        stamp = None
    if not policy.POLICY.exists():
        status = "missing"
    else:
        status = "drift" if drift or inbox else "ok"      # a repo with one of the two files is listed, not drift
    return {"status": status, "drift": drift, "inbox": inbox, "repos": {**counts, "to_fix": odd[:8]},
            "last_sync": _iso(stamp)}


# --- security: caches only ---------------------------------------------------------------------------------

def _json(path: pathlib.Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _int(d: dict | None, key: str) -> int | None:
    v = (d or {}).get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def security() -> dict:
    from . import deps, leak_published, reviews
    dp, lk, rv = _json(deps.summary_path()), _json(leak_published.summary_path()), _json(reviews.summary_path())
    notes = ["shield keeps no result between runs: run `teyla shield`"]
    for label, d, cmd in (("deps", dp, "teyla deps --all"), ("leak", lk, "teyla leak --published"),
                          ("reviews", rv, "teyla reviews")):
        if d is None:
            notes.append(f"no cached result for {label}: run `{cmd}`")
    return {"shield_issues": None, "leak_findings": _int(lk, "blockers"), "deps_vulns": _int(dp, "fix"),
            "unreviewed_prs": _int(rv, "unreviewed"),
            "as_of": {"leak": (lk or {}).get("at"), "deps": (dp or {}).get("at"), "reviews": (rv or {}).get("when")},
            "notes": notes}


# --- the section -------------------------------------------------------------------------------------------

def headline(fails: list[dict] | None, note: str | None = None) -> dict:
    label = "Unresolved failures"
    if fails is None:
        return {"label": label, "value": None, "detail": note or "failures could not be read"}
    act = [f for f in fails if f["severity"] == "act"]
    info = len(fails) - len(act)
    if not act:
        detail = "Nothing needs you here" + (f"; {info} source(s) are old or unread" if info else "")
    else:
        detail = act[0]["title"] + (f" (+{len(act) - 1} more)" if len(act) > 1 else "")
    return {"label": label, "value": len(act), "detail": detail}


def section(now: float) -> dict:
    entries = Once(lambda: schedule_entries(now))
    got, notes = run_parts({
        "machine": lambda: machine(now),
        "failures": lambda: failures(now, entries),
        "schedules": lambda: schedule_rows(entries.get()),
        "harnesses": harness_rows,
        "policy_sync": lambda: policy_sync(now),
        "security": security,
    })
    m = got.get("machine")
    return {"headline": headline(got.get("failures"), notes.get("failures")),
            "machine": m, "leave": leave(m), "failures": got.get("failures"),
            "schedules": got.get("schedules"), "harnesses": got.get("harnesses"),
            "policy_sync": got.get("policy_sync"), "security": got.get("security"), "notes": notes}


def compact(sec: dict) -> dict:
    """What the phone carries: the headline, the machine verdict and disk, the top three failures."""
    if sec.get("error"):
        return {"error": sec["error"]}
    m = sec.get("machine") or {}
    top = [{"title": f["title"], "severity": f["severity"]} for f in (sec.get("failures") or [])[:TOP_FAILURES]]
    return {"headline": sec.get("headline"),
            "machine": {"verdict": m.get("verdict"), "disk_free_gb": m.get("disk_free_gb")},
            "leave_ok": (sec.get("leave") or {}).get("ok"), "failures": top}
