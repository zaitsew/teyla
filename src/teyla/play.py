"""`teyla play` — did the Android build reach a person, or only reach Google Play.

The Google Play twin of `teyla testflight` (POLICY §11/§14). A Play upload can sit in a draft
release, be halted, or land on a track nobody is invited to; none of that shows in the uploader's
exit code. This command asks the owner's release tool, which holds the service-account key:

    <release_tool> status --package ID --json

and prints one line per product: the newest version code on the internal track and its release
status, and whether a closed test (the `alpha` track) exists and for how many days Teyla has seen
it live. Teyla never touches the credential; it runs the tool named in `~/.teyla/platform.toml` and
reads the JSON it prints (`{"package": ID, "tracks": [{"track", "releases": [{"name", "status",
"version_codes": [int], "user_fraction"}]}]}`).

    # ~/.teyla/platform.toml
    [android]
    release_tool = "/path/to/your-play-script"

    # <repo>/teyla.toml
    [release]
    android_package = "com.example.app"

A product is in scope when its `[productize.distribution]` android value is `play-internal` or
`play`, or when it sets `android_package`.

Verdicts, worst first: `error` (the tool or the config could not answer), `none` (nothing on the
internal track), `behind` (the newest internal release is not `completed`, so testers cannot install
it; or, for a product whose distribution is `play`, there is no live closed test), `current`.

The closed-test age is Teyla's own count: the Play API says nothing about when a release went live, so
`~/.teyla/play-seen.json` records the first day Teyla saw a live release on the closed track, and the
count restarts if the track ever has none. A personal developer account needs 14 days of closed testing
before production; Play also wants a minimum number of opted-in testers, which the API does not show.
A closed test younger than 14 days is reported, not a problem. Exit 0 when every in-scope product is
current, 1 otherwise. It is a network command (the tool calls Google), so safe mode refuses it without
`--allow-network`.

`--quiet` prints nothing: it writes one `key<TAB>text` line per problem to `~/.teyla/play.problems` (what
the session-start banner and the digest read), and removes the file when every product is current. The
daily routine runs it; in safe mode it does nothing and exits 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys

from . import net, productize

TIMEOUT_S = 90
CLOSED_TRACK = "alpha"           # Play Console: "closed testing"
CLOSED_TEST_DAYS = 14            # a personal developer account, before production
LIVE = "completed"
# Worst first: the product's verdict is the worst of its checks.
ORDER = ("error", "none", "behind", "current")


def in_scope(manifest: dict) -> bool:
    rel = manifest.get("release") or {}
    if str(rel.get("android_package") or "").strip():
        return True
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    return str(dist.get("android") or "").strip().lower() in ("play-internal", "play")


def wants_closed_test(manifest: dict) -> bool:
    """Distribution `play` is the public path, which a personal account reaches only through a closed test."""
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    return str(dist.get("android") or "").strip().lower() == "play"


def _row(manifest: dict, verdict: str, *, line: str, package: str = "", error: str | None = None,
         internal: dict | None = None, closed: dict | None = None, blockers: list[str] | None = None) -> dict:
    return {"product": manifest["product"], "repo": str(manifest["repo"]), "package": package,
            "verdict": verdict, "error": error, "internal": internal, "closed": closed,
            "blockers": blockers or [], "lines": [line]}


def _error(manifest: dict, msg: str, package: str = "") -> dict:
    return _row(manifest, "error", line=f"{manifest['product']}  {msg}", package=package, error=msg)


def _platform_path() -> str:
    from . import platform as platform_mod
    return str(platform_mod.PLATFORM_PATH).replace(str(pathlib.Path.home()), "~")


def run_tool(tool: pathlib.Path, package: str) -> dict:
    """The tool's JSON payload. Raises RuntimeError with a one-line reason on any failure."""
    cmd = [str(tool), "status", "--package", package, "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"the release tool did not answer within {TIMEOUT_S}s") from None
    except OSError as e:
        raise RuntimeError(f"could not run the release tool ({e.strerror or e})") from None
    if r.returncode != 0:
        # The first line is the reason (`error: gcloud could not print an access token`); what follows is a hint.
        head = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[0].strip()[:200]
        head = head.removeprefix("error:").strip()
        raise RuntimeError(f"the release tool exited {r.returncode}" + (f": {head}" if head else ""))
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("the release tool printed something that is not JSON "
                           "(is it new enough to have `status --json`?)") from None
    if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
        raise RuntimeError("the release tool's JSON has no `tracks` list")
    return data


def _codes(release: dict) -> list[int]:
    out = []
    for v in release.get("version_codes") or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    return out


def newest(payload: dict, track: str) -> dict | None:
    """The release on `track` that holds the highest version code, as
    {"code", "name", "status", "releases"} (`releases` is how many the track has), or None."""
    best = None
    count = 0
    for t in payload.get("tracks") or []:
        if not isinstance(t, dict) or t.get("track") != track:
            continue
        for r in t.get("releases") or []:
            if not isinstance(r, dict):
                continue
            count += 1
            codes = _codes(r)
            if not codes:
                continue
            if best is None or max(codes) > best["code"]:
                best = {"code": max(codes), "name": r.get("name") or "",
                        "status": str(r.get("status") or "statusUnspecified")}
    if best is None:
        return None
    best["releases"] = count
    return best


# --- the closed-test clock ---------------------------------------------------------------------------

def seen_path() -> pathlib.Path:
    from . import config
    return config.TEYLA_DIR / "play-seen.json"  # call time: tests and a moved home redirect it


def _load_seen(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def closed_days(package: str, live: bool, today: _dt.date, path: pathlib.Path | None = None) -> int | None:
    """Days Teyla has seen a live release on the closed track (0 on the first day), or None when there is
    none. Remembers the first day in play-seen.json; forgets it when the track has no live release."""
    p = path or seen_path()
    seen = _load_seen(p)
    since = None
    raw = seen.get(package)
    if isinstance(raw, str):
        try:
            since = _dt.date.fromisoformat(raw)
        except ValueError:
            since = None
    changed = False
    if live:
        if since is None or since > today:
            since, changed = today, True
            seen[package] = today.isoformat()
    elif package in seen:
        del seen[package]
        changed = True
    if changed:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, p)
        except OSError:
            pass
    return (today - since).days if live and since else None


# --- per product -----------------------------------------------------------------------------------

def _release_label(rel: dict) -> str:
    name = f' "{rel["name"]}"' if rel.get("name") else ""
    return f"code {rel['code']}{name} {rel['status']}"


def check_product(manifest: dict, cfg: dict, today: _dt.date | None = None) -> dict:
    """One report row for one in-scope product. Never raises."""
    today = today or _dt.date.today()
    name = manifest["product"]
    package = str((manifest.get("release") or {}).get("android_package") or "").strip()
    if not package:
        return _error(manifest, f"no package: add `[release] android_package = \"com.example.app\"` "
                                f"to {manifest['repo']}/teyla.toml")
    tool_raw = str((cfg.get("android") or {}).get("release_tool") or "").strip()
    if not tool_raw:
        return _error(manifest, f"no release tool: set `[android] release_tool` in {_platform_path()}", package)
    tool = pathlib.Path(tool_raw).expanduser()
    if not tool.exists():
        return _error(manifest, f"the release tool named in {_platform_path()} is not at {tool}", package)
    try:
        payload = run_tool(tool, package)
    except RuntimeError as e:
        return _error(manifest, str(e), package)

    internal = newest(payload, "internal")
    closed = newest(payload, CLOSED_TRACK)
    live = closed is not None and closed["status"] == LIVE
    days = closed_days(package, live, today)
    blockers: list[str] = []
    if internal is None:
        verdict = "none"
        head = "nothing on the internal track"
        blockers.append("no internal release")
    elif internal["status"] != LIVE:
        verdict = "behind"
        head = f"internal {_release_label(internal)}"
        blockers.append(f"internal {internal['status']}: testers cannot install it")
    else:
        verdict = "current"
        head = f"internal {_release_label(internal)}"
    if closed is None:
        closed_txt = "no closed test"
        if wants_closed_test(manifest):
            blockers.append(f"no closed test (a personal account needs {CLOSED_TEST_DAYS} days before production)")
            verdict = _worst([verdict, "behind"])
    elif not live:
        closed_txt = f"closed test {_release_label(closed)}"
        if wants_closed_test(manifest):
            blockers.append(f"closed test {closed['status']}: the {CLOSED_TEST_DAYS}-day clock is not running")
            verdict = _worst([verdict, "behind"])
    else:
        closed_txt = (f"closed test {_release_label(closed)}, seen {days} of {CLOSED_TEST_DAYS} days"
                      if days is not None else f"closed test {_release_label(closed)}")
    tail = "current" if verdict == "current" else "; ".join(blockers)
    line = f"{name}  {head}; {closed_txt} — {tail}"
    internal_out = None if internal is None else {k: internal[k] for k in ("code", "name", "status")}
    closed_out = None if closed is None else {**{k: closed[k] for k in ("code", "name", "status")}, "days_seen": days}
    return _row(manifest, verdict, line=line, package=package, internal=internal_out, closed=closed_out,
                blockers=blockers)


def _worst(verdicts: list[str]) -> str:
    return min(verdicts, key=ORDER.index) if verdicts else "error"


def run(paths: list[str] | None = None, today: _dt.date | None = None) -> list[dict]:
    from . import platform as platform_mod
    cfg = platform_mod.load()
    rows = []
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            # A broken teyla.toml cannot say whether it ships through Play. Named on the command line it
            # is an error row, never a silent pass; in the sweep, `teyla productize` already reports it.
            if paths:
                rows.append(_error(m, f"teyla.toml does not parse: {m['error']}"))
            continue
        if not in_scope(m):
            continue
        rows.append(check_product(m, cfg, today))
    return rows


def exit_code(rows: list[dict]) -> int:
    return 0 if all(r["verdict"] == "current" for r in rows) else 1


def render_text(rows: list[dict]) -> str:
    if not rows:
        return "no product ships through Google Play (see [productize.distribution] / [release] android_package).\n"
    return "".join(f"{line}\n" for r in rows for line in r["lines"])


def problems_path() -> pathlib.Path:
    from . import config
    return config.TEYLA_DIR / "play.problems"


def problem_lines(rows: list[dict]) -> list[tuple[str, str]]:
    """(key, text) for each product that is not current, e.g.
    `app-a Play: internal draft: testers cannot install it`."""
    out = []
    for r in rows:
        if r["verdict"] == "current":
            continue
        if r["blockers"]:
            what = "; ".join(r["blockers"])
        else:
            msg = str(r.get("error") or (r["lines"][0] if r.get("lines") else ""))
            what = msg.removeprefix(r["product"]).strip() or r["verdict"]
        out.append((f"play|{r['product']}|{r['verdict']}", f"{r['product']} Play: {what}"))
    return out


def write_problems(rows: list[dict], path: pathlib.Path | None = None) -> pathlib.Path | None:
    p = path or problems_path()
    items = problem_lines(rows)
    clean = lambda s: " ".join(str(s).split())  # noqa: E731 - one line, no tabs
    try:
        if items:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text("".join(f"{clean(k)}\t{clean(t)}\n" for k, t in items))
            os.replace(tmp, p)
            return p
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def cmd_play(args):
    quiet = getattr(args, "quiet", False)
    if not net.gate("`teyla play` (your release tool asks Google Play)", quiet=quiet):
        if quiet:
            return 0  # nothing was asked, so nothing is known: leave the last answer as it was
        if getattr(args, "json", False):
            print("[]")
        return 1
    if args.paths and not productize.find_manifests(args.paths):
        print("teyla: no teyla.toml at " + ", ".join(args.paths), file=sys.stderr)
        return 2
    rows = run(args.paths or None)
    if quiet:
        write_problems(rows)
    elif getattr(args, "json", False):
        print(json.dumps([{k: v for k, v in r.items() if k != "lines"} for r in rows], indent=2))
    else:
        print(render_text(rows), end="")
    return exit_code(rows)


def register(sp):
    q = sp.add_parser("play", help="did the Android build reach a person: internal track status and closed-test age on Google Play")
    q.set_defaults(fn=cmd_play)
    q.add_argument("paths", nargs="*")
    q.add_argument("--json", action="store_true")
    q.add_argument("--quiet", action="store_true", help="print nothing; write ~/.teyla/play.problems (removed when every product is current)")
    q.add_argument("--allow-network", action="store_true", help="safe mode: let the release tool reach Google Play this once")
    return q
