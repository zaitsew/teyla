"""What the providers actually billed: OpenAI's and Anthropic's cost APIs, read with admin keys.

`teyla spend` prices transcripts, which covers the harnesses on this machine. The products
you build call the APIs from servers and phones; only some of them log their calls, and none of those ledgers is reachable from a launchd
job. The providers' own cost APIs see every call, logged or not, grouped by project (OpenAI) or
workspace (Anthropic). That is W7's input: a product's daily cost jumping past twice its median.

Keys live in the macOS Keychain, read with `security find-generic-password -w` at call time and
never written anywhere:

  openai-admin-key      an OpenAI Admin key (Organization settings → Admin keys, read-only)
  anthropic-admin-key   an Anthropic Admin key (sk-ant-admin…; not available to individual orgs)

No key, no call: the report says the provider was not read. Every call goes through net.gate.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import statistics
import subprocess
import urllib.parse
import urllib.request
from collections import defaultdict

KEYCHAIN = {"openai": "openai-admin-key", "anthropic": "anthropic-admin-key"}

# W7: a day counts as a spike past this multiple of the median of the seven days before it, and
# only when the excess is worth a line.
SPIKE_FACTOR = 2.0
SPIKE_FLOOR_USD = 2.0
HISTORY_DAYS = 7
MAX_PAGES = 20


def keychain(service: str) -> str | None:
    if not shutil.which("security"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    key = r.stdout.strip()
    return key if r.returncode == 0 and key else None


def _get(url: str, headers: dict) -> dict:
    from .update import ssl_context
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "teyla-spend"})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:  # noqa: S310 — gated, explicit endpoints
        return json.loads(r.read().decode())


def _day(ts) -> str:
    if isinstance(ts, (int, float)):
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).date().isoformat()
    return str(ts)[:10]


def openai_daily(key: str, start: _dt.date, get=_get) -> dict[str, dict[str, float]]:
    """{project name: {YYYY-MM-DD: usd}} from /v1/organization/costs, grouped by project."""
    h = {"Authorization": f"Bearer {key}"}
    names = {}
    try:
        for p in get("https://api.openai.com/v1/organization/projects?limit=100", h).get("data") or []:
            names[p.get("id")] = p.get("name") or p.get("id")
    except Exception:  # noqa: BLE001 — names are a nicety; ids still group
        pass
    # Two projects with one name must not share a series: the spike rule compares each to its own median.
    seen = defaultdict(int)
    for n in names.values():
        seen[n] += 1
    names = {pid: (n if seen[n] == 1 else f"{n} ({pid})") for pid, n in names.items()}
    epoch = int(_dt.datetime.combine(start, _dt.time(), _dt.timezone.utc).timestamp())
    out: dict = defaultdict(lambda: defaultdict(float))
    page = None
    for _ in range(MAX_PAGES):
        q = {"start_time": epoch, "bucket_width": "1d", "limit": 31, "group_by": "project_id"}
        if page:
            q["page"] = page
        data = get("https://api.openai.com/v1/organization/costs?" + urllib.parse.urlencode(q), h)
        for bucket in data.get("data") or []:
            day = _day(bucket.get("start_time"))
            for res in bucket.get("results") or []:
                pid = res.get("project_id")
                out[names.get(pid, pid or "default project")][day] += float((res.get("amount") or {}).get("value") or 0)
        if not data.get("has_more"):
            break
        page = data.get("next_page")
    else:
        raise RuntimeError(f"more than {MAX_PAGES} pages")  # a partial bill must not read as a whole one
    return {k: dict(v) for k, v in out.items()}


def anthropic_daily(key: str, start: _dt.date, end: _dt.date, get=_get) -> dict[str, dict[str, float]]:
    """{workspace: {YYYY-MM-DD: usd}} from /v1/organizations/cost_report (amounts are cents)."""
    h = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    out: dict = defaultdict(lambda: defaultdict(float))
    page = None
    for _ in range(MAX_PAGES):
        q = [("starting_at", f"{start.isoformat()}T00:00:00Z"), ("ending_at", f"{end.isoformat()}T00:00:00Z"),
             ("group_by[]", "workspace_id"), ("limit", "31")]
        if page:
            q.append(("page", page))
        data = get("https://api.anthropic.com/v1/organizations/cost_report?" + urllib.parse.urlencode(q), h)
        for bucket in data.get("data") or []:
            day = _day(bucket.get("starting_at"))
            for res in bucket.get("results") or []:
                ws = res.get("workspace_id") or "default workspace"
                out[ws][day] += float(res.get("amount") or 0) / 100
        if not data.get("has_more"):
            break
        page = data.get("next_page")
    else:
        raise RuntimeError(f"more than {MAX_PAGES} pages")  # a partial bill must not read as a whole one
    return {k: dict(v) for k, v in out.items()}


def read(days: int = 7, today: _dt.date | None = None, key_of=None, get=None) -> dict:
    """{provider: {"daily": {group: {day: usd}}} | {"error": str} | {"skipped": reason}} over the
    window plus HISTORY_DAYS before it (the spike baseline)."""
    from . import net
    # Resolved here, not as defaults, so the suite's conftest can stub the Keychain module-wide.
    key_of, get = key_of or keychain, get or _get
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    start = today - _dt.timedelta(days=days + HISTORY_DAYS)
    out = {}
    for provider, service in KEYCHAIN.items():
        key = key_of(service)
        if not key:
            out[provider] = {"skipped": f"no {service} in the Keychain"}
            continue
        if not net.gate(f"{provider} cost API", quiet=True):
            out[provider] = {"skipped": "safe mode"}
            continue
        try:
            daily = (openai_daily(key, start, get) if provider == "openai"
                     else anthropic_daily(key, start, today + _dt.timedelta(days=1), get))
            out[provider] = {"daily": daily}
        except Exception as e:  # noqa: BLE001 — a provider being down must not stop the report
            out[provider] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    return out


def totals(bills: dict, days: int, today: _dt.date | None = None) -> dict[str, dict[str, float]]:
    """{provider: {group: usd over the window}}, groups with spend only. A provider that was not
    read is left out, not shown as $0: its line in the report's coverage says why."""
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    first = (today - _dt.timedelta(days=days - 1)).isoformat()
    out = {}
    for provider, b in bills.items():
        if "daily" not in b:
            continue
        groups = {g: sum(v for d, v in series.items() if d >= first) for g, series in (b.get("daily") or {}).items()}
        out[provider] = {g: v for g, v in sorted(groups.items(), key=lambda kv: -kv[1]) if v >= 0.01}
    return out


def spikes(bills: dict, days: int, today: _dt.date | None = None) -> list[dict]:
    """W7: days in the window whose cost passed SPIKE_FACTOR x the median of the HISTORY_DAYS
    before them. Each: {provider, group, day, usd, median, excess}."""
    today = today or _dt.datetime.now(_dt.timezone.utc).date()
    out = []
    for provider, b in bills.items():
        for group, series in (b.get("daily") or {}).items():
            for back in range(days):
                day = today - _dt.timedelta(days=back)
                v = series.get(day.isoformat(), 0.0)
                prior = [series.get((day - _dt.timedelta(days=i)).isoformat(), 0.0) for i in range(1, HISTORY_DAYS + 1)]
                med = statistics.median(prior)
                if v > SPIKE_FACTOR * med and v - med >= SPIKE_FLOOR_USD:
                    out.append(dict(provider=provider, group=group, day=day.isoformat(), usd=v, median=med, excess=v - med))
    return sorted(out, key=lambda s: -s["excess"])
