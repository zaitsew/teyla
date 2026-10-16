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
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

from . import net, productize

TIMEOUT_S = 60
PLATFORM_LABEL = {"IOS": "iOS", "MAC_OS": "macOS", "TV_OS": "tvOS", "VISION_OS": "visionOS"}
# Worst first: the product's verdict is the worst of its platforms'.
ORDER = ("error", "none", "behind", "current")
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


def check_product(manifest: dict, cfg: dict) -> dict:
    """One report row for one in-scope product. Never raises."""
    name = manifest["product"]
    bundle_id = str((manifest.get("release") or {}).get("apple_bundle_id") or "").strip()
    if not bundle_id:
        return _error(manifest, f"no bundle id: add `[release] apple_bundle_id = \"com.example.app\"` "
                                f"to {manifest['repo']}/teyla.toml")
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
    out, lines = [], []
    for p in plats:
        v = platform_verdict(p)
        out.append({"platform": p.get("platform"), "verdict": v, "behind": _behind(p)})
        lines.append(platform_line(name, p, v))
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
    if getattr(args, "china", False):
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
