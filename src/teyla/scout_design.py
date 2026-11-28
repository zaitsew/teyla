"""`teyla scout design` — the weekly read of what changed in design.

    teyla scout design [--week YYYY-Www] [--dry] [--quiet] [--sources FILE] [--allow-network]

Studio's reading file (docs/STUDIO.md §5.5, decision S9). It reads the feeds in `templates/design/SOURCES.md`
(Apple Developer News and Releases, Apple Newsroom, MacStories, Daring Fireball, Nielsen Norman Group,
Smashing, uxdesign.cc, iOS Dev Weekly, SwiftLee, Swift with Majid, Sarunw, Lenny's Newsletter, and the Apple
HIG pages as JSON) with the standard library only, a timeout and a user agent, and writes
`~/.teyla/scout/design/<week>.md`: at most 20 items, each with its title, source, date, URL and one line.
X and the paid libraries are never read: the section of SOURCES.md that holds them is skipped, and no fetcher
exists for those kinds. A priced yes (docs/PRIVACY.md row 26, POLICY §11) comes before that changes.

It writes no proposal (Playbook decision P9: one weekly interrupt, not two). Cards come from `teyla playbook`.
The week is an ISO week. With no `--week` it is the current one and the items are those of the last 7 days;
with `--week` they are that week's Monday to Sunday. `--dry` lists what it would fetch and writes nothing.
The only calls that leave the machine are the HTTPS fetches (one per source row, one per HIG page).
"""
from __future__ import annotations

import datetime as _dt
import email.utils
import html
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import __version__, config, net, taste
from .control import state as control

FETCH_TIMEOUT_S = 15
MAX_FEED_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 20
WINDOW_DAYS = 7
LINE_CHARS = 160
USER_AGENT = f"teyla-scout/{__version__} (+https://github.com/zaitsew/teyla)"
FETCH_KINDS = ("rss", "atom", "hig")
HIG_HUMAN = "https://developer.apple.com/design/human-interface-guidelines/"
PRICED_HEADING = "priced yes"
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


# --- sources --------------------------------------------------------------------------------------

def default_sources() -> pathlib.Path:
    import teyla
    return teyla.templates_dir() / "design" / "SOURCES.md"


def _cell(raw: str) -> str:
    return raw.strip().strip("`").strip("<>").strip()


def parse_sources(text: str) -> list[dict]:
    """The rows the scout reads: {name, kind, url, pages}. Tables under a heading that holds "priced yes" are
    skipped, and so is every row whose kind has no fetcher here (html, x, paid)."""
    rows, skip = [], False
    for ln in text.splitlines():
        if ln.startswith("#"):
            skip = PRICED_HEADING in ln.lower()
            continue
        if skip or not ln.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name, kind, url = cells[0], _cell(cells[1]).lower(), _cell(cells[2])
        if kind not in FETCH_KINDS or not url.startswith("https://"):
            continue
        pages = [p.strip() for p in cells[3].split(",") if p.strip()] if kind == "hig" else []
        rows.append({"name": name, "kind": kind, "url": url, "pages": pages})
    return rows


def targets(sources: list[dict]) -> list[dict]:
    """One fetch per feed, one per HIG page."""
    out = []
    for s in sources:
        if s["kind"] == "hig":
            for slug in s["pages"]:
                if re.fullmatch(r"[a-z0-9-]+", slug):
                    out.append({**s, "url": s["url"].replace("<slug>", slug), "slug": slug})
        else:
            out.append(s)
    return out


# --- fetching and parsing -------------------------------------------------------------------------

def _fetch(url: str) -> bytes:
    """The one network call. Tests replace this function; none touches the network."""
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("only https URLs are fetched")
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, application/json;q=0.9, */*;q=0.5"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:      # noqa: S310 (https only, checked above)
        data = r.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError(f"more than {MAX_FEED_BYTES // 1048576} MB")
    return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _date(raw: str | None) -> _dt.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return _dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


_TAG = re.compile(r"<[^>]+>")


def one_line(raw: str | None, n: int = LINE_CHARS) -> str:
    """Plain text of a feed summary: tags dropped, entities decoded, cut at the first sentence or n characters."""
    s = " ".join(html.unescape(_TAG.sub(" ", raw or "")).split())
    m = re.match(r"(.{20,}?[.!?])(\s|$)", s)
    if m and len(m.group(1)) <= n:
        return m.group(1)
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def parse_feed(data: bytes) -> list[dict]:
    """RSS 2.0 or Atom: [{title, url, date, summary}]. ValueError for XML that does not parse or that declares entities."""
    if b"<!ENTITY" in data:
        raise ValueError("the feed declares XML entities; refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"not XML ({e})") from e
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        row = {"title": "", "url": "", "date": None, "summary": ""}
        for ch in el:
            tag = _local(ch.tag)
            text = ch.text or ""
            if tag == "title":
                row["title"] = one_line(text, 200)
            elif tag == "link":
                href = ch.get("href")
                if href:
                    if ch.get("rel", "alternate") == "alternate" or not row["url"]:
                        row["url"] = href.strip()
                elif text.strip():
                    row["url"] = text.strip()
            elif tag in ("pubdate", "published", "updated", "date") and row["date"] is None:
                row["date"] = _date(text)
            elif tag in ("description", "summary") and not row["summary"]:
                row["summary"] = text
            elif tag in ("encoded", "content") and not row["summary"]:
                row["summary"] = text
        if row["title"] and row["url"].startswith("https://"):
            items.append(row)
    return items


def parse_hig(data: bytes, slug: str) -> list[dict]:
    """The latest change note of one HIG page as an item, or []. `metadata.customMetadata` has alert-date and alert-text."""
    obj = json.loads(data.decode("utf-8", errors="replace"))
    meta = obj.get("metadata") if isinstance(obj, dict) else None
    if not isinstance(meta, dict):
        raise ValueError("no metadata")
    custom = meta.get("customMetadata") if isinstance(meta.get("customMetadata"), dict) else {}
    day = _date(str(custom.get("alert-date") or ""))
    if day is None:
        return []
    title = one_line(meta.get("title") or slug, 80)
    return [{"title": f"HIG: {title}", "url": HIG_HUMAN + slug, "date": day,
             "summary": str(custom.get("alert-text") or "Updated.")}]


def window(week: str | None, today: _dt.date) -> tuple[str, _dt.date, _dt.date]:
    """(the ISO week label, first day, last day) of the items to keep."""
    if week:
        m = _WEEK.match(week)
        if not m:
            raise ValueError(f"--week must look like 2026-W44, not {week!r}")
        try:
            first = _dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError as e:
            raise ValueError(f"--week {week!r}: {e}") from e
        return week, first, first + _dt.timedelta(days=6)
    y, w, _ = today.isocalendar()
    return f"{y}-W{w:02d}", today - _dt.timedelta(days=WINDOW_DAYS - 1), today


def collect(sources: list[dict], first: _dt.date, last: _dt.date) -> tuple[list[dict], list[dict], int]:
    """(items in the window, one row per target that failed, how many targets were read)."""
    items, failed, ok = [], [], 0
    for t in targets(sources):
        try:
            data = _fetch(t["url"])
            found = parse_hig(data, t["slug"]) if t["kind"] == "hig" else parse_feed(data)
        except (OSError, ValueError, ET.ParseError) as e:
            failed.append({"name": t["name"] + (f" ({t['slug']})" if t.get("slug") else ""), "url": t["url"], "error": one_line(str(e), 100)})
            continue
        ok += 1
        for it in found:
            if it["date"] is not None and first <= it["date"] <= last:
                items.append({**it, "source": t["name"], "summary": one_line(it["summary"])})
    return items, failed, ok


def pick(items: list[dict], limit: int = MAX_ITEMS) -> list[dict]:
    """At most `limit` items, newest first inside each source and taking turns across sources, so that one
    chatty feed cannot fill the file. An address seen twice is kept once."""
    by_source: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for it in sorted(items, key=lambda x: (x["date"], x["title"]), reverse=True):
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        by_source.setdefault(it["source"], []).append(it)
    out: list[dict] = []
    queues = list(by_source.values())
    while queues and len(out) < limit:
        for q in list(queues):
            if len(out) >= limit:
                break
            out.append(q.pop(0))
            if not q:
                queues.remove(q)
    return sorted(out, key=lambda x: (x["date"], x["source"]), reverse=True)


# --- the weekly file ------------------------------------------------------------------------------

def render_week(week: str, first: _dt.date, last: _dt.date, items: list[dict], found: int, failed: list[dict], read: int) -> str:
    L = [f"# Design scout, {week}", "",
         f"Items dated {first.isoformat()} to {last.isoformat()}: {len(items)} listed of {found} found. "
         f"Read {read} feed or page request(s); {len(failed)} failed.", ""]
    L.append("## Items")
    L.append("")
    if not items:
        L.append("Nothing in the window.")
    for i, it in enumerate(items, 1):
        L.append(f"{i}. **{it['title']}** ({it['source']}, {it['date'].isoformat()}) <{it['url']}>")
        L.append(f"   {it['summary'] or '(no summary)'}")
    if failed:
        L += ["", "## Not read", ""]
        L += [f"- {f['name']} <{f['url']}>: {f['error']}" for f in failed]
    return "\n".join(L) + "\n"


def scout_home() -> pathlib.Path:
    return control.home() / "scout" / "design"


def run(*, week: str | None, today: _dt.date | None = None, sources_file: pathlib.Path | None = None,
        root: pathlib.Path | None = None) -> dict:
    today = today or _dt.date.today()
    label, first, last = window(week, today)
    rows = parse_sources((sources_file or default_sources()).read_text(encoding="utf-8"))
    root = root or scout_home()
    config.private_dir(root)
    found, failed, read = collect(rows, first, last)
    items = pick(found)
    path = root / f"{label}.md"
    taste._write_atomic(path, render_week(label, first, last, items, len(found), failed, read))
    return {"week": label, "file": str(path), "listed": len(items), "found": len(found), "read": read, "failed": failed}


def cmd_scout(args) -> int:
    if args.action != "design":
        print(f"teyla scout: unknown action {args.action!r}", file=sys.stderr)
        return 2
    sources_file = pathlib.Path(args.sources).expanduser() if args.sources else default_sources()
    try:
        rows = parse_sources(sources_file.read_text(encoding="utf-8"))
        label, first, last = window(args.week, _dt.date.today())
    except (OSError, ValueError) as e:
        print(f"teyla scout design: {e}", file=sys.stderr)
        return 2
    if args.dry:
        ts = targets(rows)
        print(f"{label}: would read {len(ts)} feed or page request(s) for items dated {first.isoformat()} to {last.isoformat()}, "
              f"write {scout_home() / (label + '.md')}; nothing is fetched or written")
        for t in ts:
            print(f"  {t['name']}: {t['url']}")
        return 0
    if not net.gate("scout design (it fetches the feeds listed in SOURCES.md)", quiet=args.quiet):
        return 0 if args.quiet else 1
    try:
        res = run(week=args.week, sources_file=sources_file)
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"teyla scout design: {e}", file=sys.stderr)
        return 1
    if res["read"] == 0:
        print(f"teyla scout design: no source could be read ({len(res['failed'])} failed); first: {res['failed'][0]['error'] if res['failed'] else 'none listed'}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"{res['week']}: {res['listed']} item(s) of {res['found']}, {len(res['failed'])} source(s) failed -> {res['file']}")
    return 0


def register(sp):
    q = sp.add_parser("scout", help="the weekly design scout: what changed in design (a reading file, no proposals)")
    q.set_defaults(fn=cmd_scout)
    q.add_argument("action", choices=["design"])
    q.add_argument("--week", help="an ISO week such as 2026-W44 (default: this week, the last 7 days)")
    q.add_argument("--sources", help="a SOURCES.md to read instead of the one Teyla ships")
    q.add_argument("--dry", action="store_true", help="list what would be fetched; fetch and write nothing")
    q.add_argument("--quiet", action="store_true", help="print nothing unless no source could be read at all")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow the fetches for this one run")
    return q
