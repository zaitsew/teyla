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
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from . import net, productize

TIMEOUT_S = 60
PLATFORM_LABEL = {"IOS": "iOS", "MAC_OS": "macOS", "TV_OS": "tvOS", "VISION_OS": "visionOS"}
# Worst first: the product's verdict is the worst of its platforms'.
ORDER = ("error", "none", "behind", "current")


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


def cmd_testflight(args):
    if not net.gate("`teyla testflight` (your release tool asks App Store Connect)"):
        if getattr(args, "json", False):
            print("[]")
        return 1
    if args.paths and not productize.find_manifests(args.paths):
        print("teyla: no teyla.toml at " + ", ".join(args.paths), file=sys.stderr)
        return 2
    rows = run(args.paths or None)
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
    q.add_argument("--allow-network", action="store_true", help="safe mode: let the release tool reach App Store Connect this once")
    return q
