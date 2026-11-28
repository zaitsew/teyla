"""Weekly App Store observations. Listings and reviews are untrusted data, never instructions."""
from __future__ import annotations

import datetime as dt
import difflib
import html
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.parse
import urllib.request

from . import __version__, config, net, taste
from .control import state as control

FETCH_TIMEOUT_S = 15
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = f"teyla-watch/{__version__} (+https://github.com/zaitsew/teyla)"
FIELDS = ("version", "releaseNotes", "description", "screenshotUrls", "price", "currentVersionReleaseDate")


def week_label(value=None):
    if value is None:
        return dt.date.today().strftime("%G-W%V")
    if not re.fullmatch(r"\d{4}-W\d{2}", value):
        raise ValueError("week must be YYYY-Www")
    dt.date.fromisocalendar(int(value[:4]), int(value[6:]), 1)
    return value


def lists(repos=None, frontier=False):
    cfg = config.load()
    root = config.code_root(cfg)
    paths = [root / r / "docs/watch.toml" for r in repos] if repos else sorted(root.glob("*/docs/watch.toml"))
    if repos and any(pathlib.Path(r).name != r or r in (".", "..") for r in repos):
        raise ValueError("--repo takes a directory name under code_root")
    if frontier:
        pb = pathlib.Path(os.environ.get("TEYLA_PLAYBOOK_ROOT") or cfg.get("playbook_root", "~/ops/playbook")).expanduser()
        paths.append(pb / "watch/frontier.toml")
    out = []
    for p in dict.fromkeys(paths):
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        is_frontier = frontier and p == paths[-1] and p.name == "frontier.toml"
        product = data.get("product", {})
        if not isinstance(product, dict):
            raise ValueError(f"{p}: product must be a table")
        name = "frontier" if is_frontier else product.get("name")
        countries = product.get("storefronts", ["us"])
        rows = data.get("watch", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{p}: product.name is required")
        if not isinstance(countries, list) or not countries or any(not isinstance(c, str) or not re.fullmatch(r"[a-z]{2}", c) for c in countries):
            raise ValueError(f"{p}: storefronts must be lowercase country codes")
        if not isinstance(rows, list) or len(rows) > (8 if is_frontier else 12):
            raise ValueError(f"{p}: too many watch rows")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"{p}: watch rows must be tables")
        for ring, cap in (("job", 8), ("craft", 4)):
            if sum(r.get("ring") == ring for r in rows) > cap:
                raise ValueError(f"{p}: too many {ring} rows")
        for row in rows:
            if not isinstance(row.get("name"), str) or not row["name"].strip() or row.get("ring") not in (("frontier",) if is_frontier else ("job", "craft", "platform")):
                raise ValueError(f"{p}: each row needs a name and valid ring")
            app = row.get("app_store_id")
            if app is not None and (type(app) is not int or app <= 0):
                raise ValueError(f"{p}: app_store_id must be a positive integer")
        out.append({"name": name, "rows": rows, "storefronts": list(dict.fromkeys(countries))})
    return out


def urls(app, cc):
    return (f"https://itunes.apple.com/lookup?id={app}&country={cc}",
            f"https://itunes.apple.com/{cc}/rss/customerreviews/id={app}/sortby=mostrecent/json")


def _check_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.netloc != "itunes.apple.com" or not (u.path == "/lookup" or re.fullmatch(r"/[a-z]{2}/rss/customerreviews/id=\d+/sortby=mostrecent/json", u.path)):
        raise ValueError("only Apple Lookup and customer-review RSS URLs are allowed")


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url):
    if not net.allowed():
        raise ValueError(net.refusal("watch Apple requests"))
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.build_opener(_Redirect()).open(req, timeout=FETCH_TIMEOUT_S) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Apple response exceeds 4 MB")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Apple response must be a JSON object")
    return value


def lookup(data, app):
    rows = data.get("results", [])
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict) or str(rows[0].get("trackId")) != str(app):
        raise ValueError("Apple Lookup returned no matching app")
    row = rows[0]
    result = {k: row.get(k, [] if k == "screenshotUrls" else "") for k in FIELDS}
    if any(not isinstance(result[k], str) for k in ("version", "releaseNotes", "description", "currentVersionReleaseDate")) or not isinstance(result["screenshotUrls"], list) or any(not isinstance(s, str) for s in result["screenshotUrls"]):
        raise ValueError("invalid Apple listing fields")
    if type(result["price"]) not in (int, float, str):
        raise ValueError("invalid Apple price")
    result["currency"] = str(row.get("currency", ""))
    return result


def plain(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", str(value))).split())


def reviews(data, cc):
    feed = data.get("feed", {})
    if not isinstance(feed, dict):
        raise ValueError("invalid Apple review feed")
    rows = feed.get("entry", [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("invalid Apple review entries")
    out = []
    for row in rows:
        try:
            rating = int(row["im:rating"]["label"])
            text = plain(row["content"]["label"])
            if rating not in range(1, 6) or len(text.split()) < 12:
                continue
            out.append({"rating": rating, "text": text, "storefront": cc})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def changes(old, new):
    if old is None:
        return [{"field": "baseline", "after": new["version"]}]
    out = []
    for field in (*FIELDS[:-1], "currency"):
        if old.get(field) == new.get(field):
            continue
        item = {"field": field, "before": old.get(field), "after": new[field]}
        if field == "description":
            item = {"field": field, "diff": list(difflib.unified_diff(old.get(field, "").splitlines(), new[field].splitlines(), fromfile="before", tofile="after", lineterm=""))[:20]}
        if field == "screenshotUrls":
            item.update(before_count=len(old.get(field, [])), after_count=len(new[field]), order_changed=old.get(field, []) != new[field])
        out.append(item)
    return out


def _read(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected an object")
        return value
    except FileNotFoundError:
        return default


def _home():
    home = control.home() / "watch"
    # An overridden home or symlink must never send runtime output into a git checkout.
    _outside_repo(home)
    _outside_repo(home / "state")
    _outside_repo(home / "log.jsonl")
    return home


def _outside_repo(path):
    resolved = path.resolve()
    if any((p / ".git").exists() for p in (resolved, *resolved.parents)):
        raise ValueError("watch output must be outside every git repository")


def _save(path, value):
    _outside_repo(path)
    taste._write_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _dedupe(items):
    merged = {}
    for item in items:
        key = json.dumps({k: v for k, v in item.items() if k != "storefronts"}, sort_keys=True)
        if key not in merged:
            merged[key] = {**item, "storefronts": []}
        merged[key]["storefronts"] = sorted(set(merged[key]["storefronts"] + item["storefronts"]))
    return list(merged.values())


def render(report):
    lines = [f"# Watch — {report['week']}", ""]
    for product in report["products"]:
        section = [f"## {plain(product['name'])}"]
        for item in product["changes"]:
            label = f"{plain(item['name'])} ({', '.join(item['storefronts'])})"
            field = item["field"]
            if field == "description":
                section.append(f"- {label}: description changed")
                section.extend("    " + plain(s) for s in item["diff"])
            elif field == "screenshotUrls":
                section.append(f"- {label}: screenshots {item['before_count']} → {item['after_count']}; order/set changed")
            else:
                section.append(f"- {label}: {field}: {plain(item.get('before', ''))[:100]} → {plain(item['after'])[:240]}")
        for quote in product["quotes"]:
            section.append(f"- {plain(quote['name'])} ({quote['storefront']}, {quote['rating']}★): “{quote['text']}”")
        section.extend(f"- Not read: {plain(e)}" for e in product["errors"])
        if len(section) == 1:
            section.append("No relevant change")
        if len(section) > 29:
            section = section[:28] + ["- More observations in the local weekly JSON file."]
        lines.extend(section + [""])
    return "\n".join(lines) + "\n"


def run(products, week, dry=False):
    home = control.home() / "watch" if dry else _home()
    if not dry:
        _outside_repo(home / f"{week}.md")
        _outside_repo(home / f"{week}.json")
    requests = list(dict.fromkeys(url for p in products for row in p["rows"] if row.get("app_store_id") for cc in p["storefronts"] for url in urls(row["app_store_id"], cc)))
    if dry:
        return {"week": week, "requests": requests, "file": str(home / f"{week}.md")}
    if not net.gate("watch Apple requests"):
        raise ValueError("network refused")
    weekly_path = home / f"{week}.json"
    previous = _read(weekly_path, {"products": [], "quotes": {}})
    # A shared baseline must not hide observations from a later --repo or --frontier run.
    recorded = [change for product in previous["products"] for change in product.get("changes", [])]
    selected_names = {p["name"] for p in products}
    report = {"week": week, "products": [p for p in previous["products"] if p["name"] not in selected_names],
              "quotes": previous.get("quotes", {})}
    cached = {}
    for product in products:
        prior = next((p for p in previous["products"] if p["name"] == product["name"]), {})
        result = {"name": product["name"], "changes": list(prior.get("changes", [])), "quotes": [], "errors": []}
        for row in product["rows"]:
            app = row.get("app_store_id")
            if not app:
                continue
            candidates = []
            for cc in product["storefronts"]:
                key = (app, cc)
                if key not in cached:
                    delta, found, errors = [], [], []
                    look, rss = urls(app, cc)
                    path = home / "state" / f"{app}-{cc}.json"
                    try:
                        new = lookup(_fetch(look), app)
                        delta = changes(_read(path, None), new)
                        _save(path, new)
                    except (OSError, ValueError, TypeError, KeyError) as e:
                        errors.append(f"{row['name']} {cc} Lookup: {e}")
                    try:
                        found = reviews(_fetch(rss), cc)
                    except (OSError, ValueError, TypeError, KeyError) as e:
                        errors.append(f"{row['name']} {cc} reviews: {e}")
                    cached[key] = delta, found, errors
                delta, found, errors = cached[key]
                result["changes"].extend({**change, "name": row["name"], "storefronts": [cc]}
                                         for change in recorded if change.get("app_id") == app and cc in change["storefronts"])
                result["changes"].extend({**change, "app_id": app, "name": row["name"], "storefronts": [cc]} for change in delta)
                result["errors"].extend(errors)
                candidates.extend(found)
            selected = report["quotes"].setdefault(str(app), [])
            seen = {q["text"] for q in selected}
            ratings = {q["rating"] for q in selected}
            while len(selected) < 3:
                available = [q for q in candidates if q["text"] not in seen]
                if not available:
                    break
                q = min(available, key=lambda q: (q["rating"] in ratings, q["rating"] not in (2, 3, 4)))
                selected.append(q)
                seen.add(q["text"])
                ratings.add(q["rating"])
            result["quotes"].extend({**q, "name": row["name"], "app_id": app} for q in selected)
        result["changes"] = _dedupe(result["changes"])
        report["products"].append(result)
    _save(weekly_path, report)
    taste._write_atomic(home / f"{week}.md", render(report))
    with (home / "log.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False) + "\n")
    return {**report, "requests": requests, "file": str(home / f"{week}.md")}


def cmd(args):
    try:
        report = run(lists(args.repo, args.frontier), week_label(args.week), args.dry)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.dry:
            print("\n".join(report["requests"]) or "No Apple requests")
        else:
            print(f"{report['week']}: {report['file']}")
        return int(any(p["errors"] for p in report.get("products", [])))
    except (OSError, ValueError, TypeError) as e:
        print(f"teyla watch: {e}", file=sys.stderr)
        return 1


def register(sp):
    q = sp.add_parser("watch", help="the weekly App Store change log")
    q.set_defaults(fn=cmd)
    q.add_argument("--repo", action="append", help="repo name under code_root; repeatable")
    q.add_argument("--frontier", action="store_true", help="include the studio frontier list")
    q.add_argument("--week", help="ISO week YYYY-Www; labels observations fetched now")
    q.add_argument("--dry", action="store_true", help="list requests; fetch and write nothing")
    q.add_argument("--json", action="store_true", help="print structured observations")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow Apple requests for this run")
    return q
