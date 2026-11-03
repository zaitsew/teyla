"""`teyla testflight` — did the build reach a person, or only reach Apple.

POLICY §11: a build is done when it is installable from the owner's tester account, not when
the upload finished. An upload can sit in processing, fail export compliance, or land in a
build the tester's group does not include; none of that shows in the uploader's exit code.

This command asks the owner's release tool, which holds the App Store Connect key:

    <release_tool> beta reached --bundle-id ID --email EMAIL [--platform ios|macos] --json

and prints one line per product and platform: the newest build uploaded, the newest build the
tester can install, and what stands between the two. Teyla never touches the API key; it runs
the tool named in `~/.teyla/platform.toml` and reads the JSON it prints.

    # ~/.teyla/platform.toml
    [apple]
    release_tool = "/path/to/your-release-script"
    tester = "you@example.com"          # the email the TestFlight app is signed in with

    # <repo>/teyla.toml
    [release]
    apple_bundle_id = "com.example.app"

A product is in scope when its `[productize.distribution]` ios or macos value is a TestFlight
one or `app-store`, or when it sets `apple_bundle_id`. Exit 0 when every in-scope platform is
current, 1 when any is behind, has nothing installable, or could not be read: a routine can
use the exit code. It is a network command (the tool calls Apple), so safe mode refuses it
without `--allow-network`.

`--quiet` prints nothing: it writes one `key<TAB>text` line per platform that is behind, has nothing
installable or could not be read to `~/.teyla/testflight.problems` (what the session-start banner and
the digest read), and removes the file when every platform is current. The daily routine runs it; in
safe mode it does nothing and exits 0.

China mainland (POLICY §15, store review). Generative AI in the China storefront needs a Chinese permit
that none of our model providers has, and any app there needs an ICP filing, so territory `CHN` is excluded
from the first submission. `teyla testflight --china` is the read-only check: for each in-scope product
it asks the same release tool

    <release_tool> availability --bundle-id ID --json

and prints one line per product that is still available in `CHN`, with the fix; it prints nothing when no
product is. The tool prints the app's territory availability (the App Store Connect
`GET /v1/apps/{id}/appAvailabilityV2`, then `GET /v2/appAvailabilities/{id}/territoryAvailabilities
?include=territory&fields[territoryAvailabilities]=available,contentStatuses,territory`; the territory id is
under `relationships.territory.data.id` and only comes back with `include=territory`):

    {"bundle_id": "com.example.app",
     "territories": [{"territory": "CHN", "available": true}, {"territory": "USA", "available": true}]}

Only the `CHN` entry is read; the tool may list every territory or just that one. A tool that cannot answer
(no `availability` command, an app with no availability set yet) is a problem line of its own, never a pass.
Exit 1 when any product is available in CHN or could not be read. `--quiet` also runs this check and adds its
lines to `testflight.problems` (keys `testflight|<product>|CHN`).

A store build can be current in TestFlight and still weeks old. The Teyla Mac app lagged `main` by a week in
November 2026 because nothing uploaded it after the UI work, and `beta reached` compares only uploads with
installable builds. A repo declares each platform's store target in its `teyla.toml`:

    [[release.store_target]]
    platform = "macos"                        # ios | macos
    scheme = "TeylaStore"
    project = "apps/mac/Teyla.xcodeproj"      # passed to the release tool; its folder is the default for `paths`
    paths = ["apps/mac/Teyla", ":(exclude)apps/mac/Teyla/Core/TeylaCLI.swift"]   # git pathspecs: the target's sources
    grace_days = 3                            # optional; a change younger than this may still be on its way
    frozen = "2026-10-01: nobody opened it since"   # optional, see below

`teyla testflight` takes the date of the newest upload on that platform (already in the `beta reached` answer,
so no new call leaves the machine) and the date of the newest commit that landed on the default branch
(`origin/HEAD`, first parent: the merge) and touched `paths`. When the change is more than `grace_days` newer
than the upload, it prints a warning line with the release command (`--platform macos` included), the platform
counts as `stale` (exit 1, one `testflight.problems` line), and nothing is uploaded. A platform with no upload
at all and a source change warns the same way.

POLICY §14: a secondary nobody opened in 30 days is frozen and gets no parity train. `frozen = "<date>: why"`
says nobody has opened it since that date; once that date is 30 days back, the lag is not reported.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

from . import cloud, net, productize

TIMEOUT_S = 60
PLATFORM_LABEL = {"IOS": "iOS", "MAC_OS": "macOS", "TV_OS": "tvOS", "VISION_OS": "visionOS"}
TARGET_PLATFORM = {"ios": "IOS", "macos": "MAC_OS"}   # `platform` in [[release.store_target]] -> App Store Connect
# Worst first: the product's verdict is the worst of its platforms'.
ORDER = ("error", "none", "behind", "stale", "current")
GRACE_DAYS = 3    # a source change this young is not yet a lagging store build
FROZEN_DAYS = 30  # POLICY §14: a secondary nobody opened in this long is frozen
CHINA = "CHN"  # POLICY §15: App Store territory id of the China mainland storefront


def _label(p: str) -> str:
    return PLATFORM_LABEL.get(str(p), str(p))


def in_scope(manifest: dict) -> bool:
    """True when the product ships through TestFlight / the App Store, or names a bundle id."""
    rel = manifest.get("release") or {}
    if str(rel.get("apple_bundle_id") or "").strip():
        return True
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    for key in ("ios", "macos"):
        v = str(dist.get(key) or "").strip().lower()
        if v.startswith("testflight") or v == "app-store":
            return True
    return False


def declared_platforms(manifest: dict) -> list[str]:
    """App Store Connect platform names the manifest says ship through TestFlight or the store."""
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    out = []
    for key, asc in (("ios", "IOS"), ("macos", "MAC_OS")):
        v = str(dist.get(key) or "").strip().lower()
        if v.startswith("testflight") or v == "app-store":
            out.append(asc)
    return out


def _worst(verdicts: list[str]) -> str:
    return min(verdicts, key=ORDER.index) if verdicts else "error"


def _row(manifest: dict, verdict: str, *, line: str, bundle_id: str = "", error: str | None = None,
         payload: dict | None = None, platforms: list[dict] | None = None) -> dict:
    return {"product": manifest["product"], "repo": str(manifest["repo"]), "bundle_id": bundle_id,
            "verdict": verdict, "error": error, "platforms": platforms or [], "payload": payload,
            "lines": [line]}


def _error(manifest: dict, msg: str, bundle_id: str = "") -> dict:
    return _row(manifest, "error", line=f"{manifest['product']}  {msg}", bundle_id=bundle_id, error=msg)


def run_tool(tool: pathlib.Path, bundle_id: str, tester: str) -> dict:
    """The tool's JSON payload. Raises RuntimeError with a one-line reason on any failure."""
    cmd = [str(tool), "beta", "reached", "--bundle-id", bundle_id, "--email", tester, "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"the release tool did not answer within {TIMEOUT_S}s") from None
    except OSError as e:
        raise RuntimeError(f"could not run the release tool ({e.strerror or e})") from None
    if r.returncode != 0:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1][:200]
        raise RuntimeError(f"the release tool exited {r.returncode}" + (f": {tail}" if tail else ""))
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("the release tool printed something that is not JSON "
                           "(is it new enough to have `beta reached`?)") from None
    if not isinstance(data, dict) or not isinstance(data.get("platforms"), list):
        raise RuntimeError("the release tool's JSON has no `platforms` list")
    return data


def run_availability(tool: pathlib.Path, bundle_id: str) -> dict:
    """The tool's availability JSON. Raises RuntimeError with a one-line reason on any failure."""
    cmd = [str(tool), "availability", "--bundle-id", bundle_id, "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"the release tool did not answer within {TIMEOUT_S}s") from None
    except OSError as e:
        raise RuntimeError(f"could not run the release tool ({e.strerror or e})") from None
    if r.returncode != 0:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1][:200]
        raise RuntimeError(f"the release tool exited {r.returncode}" + (f": {tail}" if tail else ""))
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("the release tool printed something that is not JSON "
                           "(is it new enough to have `availability`?)") from None
    if not isinstance(data, dict) or not isinstance(data.get("territories"), list):
        raise RuntimeError("the release tool's JSON has no `territories` list")
    return data


def china_available(payload: dict) -> bool:
    """True when the payload lists CHN with available=true. No CHN entry means not available there."""
    for t in payload.get("territories") or []:
        if isinstance(t, dict) and str(t.get("territory") or "").upper() == CHINA and t.get("available") is True:
            return True
    return False


CHINA_FIX = ("exclude CHN in App Store Connect availability, app-wide (iOS and macOS), "
             "and note the reason in the repo's store script")


def check_china(manifest: dict, cfg: dict) -> dict | None:
    """None when the product is not available in CHN. Otherwise a row (verdict `china`, or `error`
    when the tool could not answer). Never raises."""
    name = manifest["product"]
    bundle_id = str((manifest.get("release") or {}).get("apple_bundle_id") or "").strip()
    if not bundle_id:
        return _error(manifest, f"no bundle id: add `[release] apple_bundle_id = \"com.example.app\"` "
                                f"to {manifest['repo']}/teyla.toml")
    tool_raw = str((cfg.get("apple") or {}).get("release_tool") or "").strip()
    if not tool_raw:
        return _error(manifest, f"no release tool: set `[apple] release_tool` in {_platform_path()}", bundle_id)
    tool = pathlib.Path(tool_raw).expanduser()
    if not tool.exists():
        return _error(manifest, f"the release tool named in {_platform_path()} is not at {tool}", bundle_id)
    try:
        payload = run_availability(tool, bundle_id)
    except RuntimeError as e:
        return _error(manifest, f"could not read App Store availability: {e}", bundle_id)
    if not china_available(payload):
        return None
    return _row(manifest, "china", bundle_id=bundle_id, payload=payload,
                line=f"{name}  still available in China mainland (CHN), against POLICY §15: {CHINA_FIX}")


def run_china(paths: list[str] | None = None) -> list[dict]:
    from . import platform as platform_mod
    cfg = platform_mod.load()
    rows = []
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            if paths:
                rows.append(_error(m, f"teyla.toml does not parse: {m['error']}"))
            continue
        if not in_scope(m):
            continue
        row = check_china(m, cfg)
        if row is not None:
            rows.append(row)
    return rows


def china_problem_lines(rows: list[dict]) -> list[tuple[str, str]]:
    out = []
    for r in rows:
        if r["verdict"] == "china":
            out.append((f"testflight|{r['product']}|CHN", f"{r['product']}: available in China mainland (CHN); {CHINA_FIX}"))
        else:
            msg = str(r.get("error") or "").strip() or r["verdict"]
            out.append((f"testflight|{r['product']}|CHN|{r['verdict']}", f"{r['product']}: {msg}"))
    return out


def _behind(p: dict) -> int:
    try:
        return max(int(p.get("behind") or 0), 0)
    except (TypeError, ValueError):
        return 0


def platform_verdict(p: dict) -> str:
    if not p.get("newest_installable"):
        return "none"
    return "behind" if _behind(p) > 0 else "current"


def platform_line(product: str, p: dict, verdict: str) -> str:
    up = p.get("newest_uploaded") or {}
    inst = p.get("newest_installable") or {}
    if up:
        bits = f"{up.get('version', '?')} ({up.get('build', '?')})"
        uploaded = str(up.get("uploaded") or "")[:10]
        head = f"{bits} uploaded {uploaded}" if uploaded else f"{bits} uploaded"
    else:
        head = "nothing uploaded"
    can = f"you can install {inst.get('build', '?')}" if inst else "you can install nothing"
    blockers = [str(b) for b in (p.get("blockers") or [])]
    if verdict == "current":
        tail = "current"
    else:
        n = _behind(p)
        tail = (f"{n} behind" if n else "none installable") + (": " + "; ".join(blockers) if blockers else "")
    return f"{product}  {_label(p.get('platform', '?')):<6} {head}; {can} — {tail}"


def _today() -> dt.date:
    return dt.date.today()  # a function so tests can pin the day


def store_targets(manifest: dict) -> tuple[list[dict], str | None]:
    """([{platform, asc, scheme, project, paths, grace_days, frozen}], error). An entry that cannot
    be used is an error, never skipped: a typo must not turn the check off."""
    raw = (manifest.get("release") or {}).get("store_target")
    if raw is None:
        return [], None
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        return [], "`[[release.store_target]]` must be a list of tables"
    out = []
    for t in raw:
        plat = str(t.get("platform") or "").strip().lower()
        scheme = str(t.get("scheme") or "").strip()
        project = str(t.get("project") or "").strip()
        if plat not in TARGET_PLATFORM or not scheme or not project:
            return [], ("`[[release.store_target]]` needs `platform` (ios or macos), `scheme` and `project`, "
                        f"got platform={plat or 'unset'}, scheme={scheme or 'unset'}, project={project or 'unset'}")
        paths = t.get("paths")
        if paths is None:
            paths = [str(pathlib.PurePosixPath(project).parent)]
        if not isinstance(paths, list) or not paths or not all(isinstance(x, str) and x for x in paths):
            return [], "`paths` in `[[release.store_target]]` must be a list of git pathspecs"
        grace = t.get("grace_days", GRACE_DAYS)
        if isinstance(grace, bool) or not isinstance(grace, int) or grace < 0:
            return [], "`grace_days` in `[[release.store_target]]` must be a whole number of days"
        out.append({"platform": plat, "asc": TARGET_PLATFORM[plat], "scheme": scheme, "project": project,
                    "paths": paths, "grace_days": grace, "frozen": str(t.get("frozen") or "").strip()})
    return out, None


def is_frozen(target: dict, today: dt.date) -> bool:
    """POLICY §14: nobody has opened the platform since the date `frozen` starts with, and that was
    FROZEN_DAYS ago or more. An unreadable date does not freeze anything."""
    try:
        since = dt.date.fromisoformat(target["frozen"][:10])
    except ValueError:
        return False
    return (today - since).days >= FROZEN_DAYS


def newest_change(repo: pathlib.Path, paths: list[str]) -> dict | None:
    """The newest commit on the default branch (first parent, so a merge counts when it landed) that
    touched `paths`: {when, sha, subject}. None when git cannot say. Local git only."""
    ref = cloud.default_ref(repo)
    try:
        r = subprocess.run(["git", "-C", str(repo), "log", "--first-parent", "-1",
                            "--format=%cI%x09%h%x09%s", ref, "--", *paths],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    when, _, rest = r.stdout.strip().partition("\t")
    sha, _, subject = rest.partition("\t")
    try:
        return {"when": dt.datetime.fromisoformat(when), "sha": sha, "subject": subject[:80]}
    except ValueError:
        return None


def _upload_time(p: dict) -> dt.datetime | None:
    raw = str((p.get("newest_uploaded") or {}).get("uploaded") or "")
    try:
        t = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def release_command(tool_raw: str, target: dict, bundle_id: str) -> str:
    return (f"{tool_raw} release --platform {target['platform']} --project {target['project']} "
            f"--scheme {target['scheme']} --bundle-id {bundle_id}")


def store_lag(manifest: dict, target: dict, p: dict, tool_raw: str, bundle_id: str) -> dict | None:
    """{text, release, ...} when the platform's store build is older than the target's sources by more
    than the grace period, else None (current, young, frozen, or git cannot say)."""
    if is_frozen(target, _today()):
        return None
    change = newest_change(pathlib.Path(manifest["repo"]), target["paths"])
    if change is None:
        return None
    label = _label(target["asc"])
    cmd = release_command(tool_raw, target, bundle_id)
    what = f"{target['scheme']} changed {change['when'].date()} ({change['sha']} {change['subject']})"
    uploaded = _upload_time(p)
    if p.get("newest_uploaded") and uploaded is None:
        return None   # an upload with no readable date: nothing to compare, and nothing to claim
    if uploaded is None:
        head = f"no {label} build uploaded; {what}"
    else:
        if change["when"] - uploaded <= dt.timedelta(days=target["grace_days"]):
            return None
        head = f"{label} store build uploaded {uploaded.date()} lags main; {what}"
    return {"text": head, "release": cmd, "change": change["sha"], "changed": str(change["when"].date()),
            "uploaded": str(uploaded.date()) if uploaded else None}


def lag_line(product: str, lag: dict) -> str:
    return f"{product}  WARN {lag['text']}. Release: {lag['release']}"


def check_product(manifest: dict, cfg: dict) -> dict:
    """One report row for one in-scope product. Never raises."""
    name = manifest["product"]
    bundle_id = str((manifest.get("release") or {}).get("apple_bundle_id") or "").strip()
    if not bundle_id:
        return _error(manifest, f"no bundle id: add `[release] apple_bundle_id = \"com.example.app\"` "
                                f"to {manifest['repo']}/teyla.toml")
    targets, bad = store_targets(manifest)
    if bad:
        return _error(manifest, f"{manifest['repo']}/teyla.toml: {bad}", bundle_id)
    apple = cfg.get("apple") or {}
    tool_raw = str(apple.get("release_tool") or "").strip()
    tester = str(apple.get("tester") or "").strip()
    if not tool_raw:
        return _error(manifest, f"no release tool: set `[apple] release_tool` in {_platform_path()}", bundle_id)
    tool = pathlib.Path(tool_raw).expanduser()
    if not tool.exists():
        return _error(manifest, f"the release tool named in {_platform_path()} is not at {tool}", bundle_id)
    if not tester:
        return _error(manifest, f"no tester: set `[apple] tester` in {_platform_path()} to the email "
                                f"your TestFlight app is signed in with", bundle_id)
    try:
        payload = run_tool(tool, bundle_id, tester)
    except RuntimeError as e:
        return _error(manifest, str(e), bundle_id)
    if payload.get("tester_found") is False:
        return _row(manifest, "none", bundle_id=bundle_id, payload=payload,
                    line=f"{name}  the tester is not on the team: add the tester email in App Store Connect "
                         f"(Users and Access, or TestFlight > Internal Testing) and put it in a group")
    plats = [p for p in payload["platforms"] if isinstance(p, dict)]
    # A declared platform the tool says nothing about has no build at all: that is "none",
    # not a pass (caught in review, P2).
    seen = {p.get("platform") for p in plats}
    plats += [{"platform": asc, "newest_uploaded": None, "newest_installable": None,
               "behind": 0, "blockers": []} for asc in declared_platforms(manifest) if asc not in seen]
    if not plats:
        return _row(manifest, "none", bundle_id=bundle_id, payload=payload,
                    line=f"{name}  App Store Connect has no builds for {bundle_id}")
    # A store target whose platform the tool says nothing about has no build: the lag check says so.
    seen = {p.get("platform") for p in plats}
    plats += [{"platform": t["asc"], "newest_uploaded": None, "newest_installable": None,
               "behind": 0, "blockers": [], "_no_build": True} for t in targets if t["asc"] not in seen]
    by_asc = {t["asc"]: t for t in targets}
    out, lines = [], []
    for p in plats:
        v = platform_verdict(p)
        lag = None
        if p.get("platform") in by_asc:
            lag = store_lag(manifest, by_asc[p["platform"]], p, tool_raw, bundle_id)
        if p.get("_no_build"):
            if not lag:
                continue   # a platform with no build and no source change to ship is not a finding
            v = "stale"
        elif lag and v == "current":
            v = "stale"
        entry = {"platform": p.get("platform"), "verdict": v, "behind": _behind(p)}
        if lag:
            entry["lag"] = lag
        out.append(entry)
        if not p.get("_no_build"):
            lines.append(platform_line(name, p, "current" if v == "stale" else v))
        if lag:
            lines.append(lag_line(name, lag))
    row = _row(manifest, _worst([x["verdict"] for x in out]), line="", bundle_id=bundle_id,
               payload=payload, platforms=out)
    row["lines"] = lines
    return row


def _platform_path() -> str:
    from . import platform as platform_mod
    return str(platform_mod.PLATFORM_PATH).replace(str(pathlib.Path.home()), "~")


def run(paths: list[str] | None = None) -> list[dict]:
    from . import platform as platform_mod
    cfg = platform_mod.load()
    rows = []
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            # A broken teyla.toml cannot say whether it ships through TestFlight. Named on the
            # command line, it is an error row, never a silent pass (caught in review, P2);
            # in the sweep over every repo, `teyla productize` already reports it.
            if paths:
                rows.append(_error(m, f"teyla.toml does not parse: {m['error']}"))
            continue
        if not in_scope(m):
            continue
        rows.append(check_product(m, cfg))
    return rows


def exit_code(rows: list[dict]) -> int:
    return 0 if all(r["verdict"] == "current" for r in rows) else 1


def render_text(rows: list[dict]) -> str:
    if not rows:
        return "no product ships through TestFlight or the App Store (see [productize.distribution] / [release]).\n"
    return "".join(f"{line}\n" for r in rows for line in r["lines"])


def problems_path() -> pathlib.Path:
    from . import config
    return config.TEYLA_DIR / "testflight.problems"  # call time: tests and a moved home redirect it


def problem_lines(rows: list[dict]) -> list[tuple[str, str]]:
    """(key, text) for each platform that is not current, e.g. `app-a iOS: 2 behind — 120: processing`.
    A row that has no platforms (an error, a tester not on the team) is one line of its own."""
    out = []
    for r in rows:
        if r["verdict"] == "current":
            continue
        by_platform = {p.get("platform"): p for p in (r.get("payload") or {}).get("platforms") or []
                       if isinstance(p, dict)}
        listed = [p for p in r["platforms"] if p["verdict"] != "current"]
        for p in listed:
            if p.get("lag"):
                out.append((f"testflight|{r['product']}|{p['platform']}|stale",
                            f"{r['product']} {_label(p['platform'])}: {p['lag']['text']}. Release: {p['lag']['release']}"))
            if p["verdict"] == "stale":
                continue
            raw = by_platform.get(p["platform"]) or {}
            what = f"{p['behind']} behind" if p["verdict"] == "behind" else "none installable"
            if p["verdict"] == "none" and p["behind"]:
                what = f"{p['behind']} behind, none installable"
            blockers = "; ".join(str(b) for b in raw.get("blockers") or [])
            tail = f" — {blockers}" if blockers else ""
            out.append((f"testflight|{r['product']}|{p['platform']}|{p['verdict']}",
                        f"{r['product']} {_label(p['platform'])}: {what}{tail}"))
        if not listed:
            msg = str(r.get("error") or (r["lines"][0] if r.get("lines") else ""))
            msg = msg.removeprefix(r["product"]).strip() or r["verdict"]
            out.append((f"testflight|{r['product']}|{r['verdict']}", f"{r['product']}: {msg}"))
    return out


def write_problems(rows: list[dict], path: pathlib.Path | None = None,
                   china_rows: list[dict] | None = None) -> pathlib.Path | None:
    p = path or problems_path()
    items = problem_lines(rows) + china_problem_lines(china_rows or [])
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


def cmd_testflight(args):
    quiet = getattr(args, "quiet", False)
    if not net.gate("`teyla testflight` (your release tool asks App Store Connect)", quiet=quiet):
        if quiet:
            return 0  # nothing was asked, so nothing is known: leave the last answer as it was
        if getattr(args, "json", False):
            print("[]")
        return 1
    if args.paths and not productize.find_manifests(args.paths):
        print("teyla: no teyla.toml at " + ", ".join(args.paths), file=sys.stderr)
        return 2
    if getattr(args, "china", False) and not quiet:   # --quiet always includes the check
        china = run_china(args.paths or None)
        if getattr(args, "json", False):
            print(json.dumps([{k: v for k, v in r.items() if k != "lines"} for r in china], indent=2))
        else:
            print("".join(f"{line}\n" for r in china for line in r["lines"]), end="")
        return 1 if china else 0
    rows = run(args.paths or None)
    if quiet:
        china = run_china(args.paths or None)
        write_problems(rows, china_rows=china)
        return exit_code(rows) or (1 if china else 0)
    if getattr(args, "json", False):
        print(json.dumps([{k: v for k, v in r.items() if k != "lines"} for r in rows], indent=2))
    else:
        print(render_text(rows), end="")
    return exit_code(rows)


def register(sp):
    q = sp.add_parser("testflight", help="did the build reach a person: newest upload vs newest build your tester can install")
    q.set_defaults(fn=cmd_testflight)
    q.add_argument("paths", nargs="*")
    q.add_argument("--json", action="store_true")
    q.add_argument("--quiet", action="store_true", help="print nothing; write ~/.teyla/testflight.problems (removed when every platform is current)")
    q.add_argument("--china", action="store_true", help="only check that no product is still available in China mainland (CHN), POLICY \u00a715; silent when none is")
    q.add_argument("--allow-network", action="store_true", help="safe mode: let the release tool reach App Store Connect this once")
    return q
