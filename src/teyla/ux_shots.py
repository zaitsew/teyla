"""`teyla ux shots | diff | accept` — the capture matrix: does a screen still look the way the owner accepted?

    teyla ux shots  <repo> [--check-manifest] [--dry] [--runs N] [--budget-min N] [--strict]
    teyla ux diff   <repo>
    teyla ux accept <repo> --yes [--allow-unstable]

A fixed matrix, not a model's glance (docs/STUDIO.md, decision S6). The product's XCUITest tour
(templates/design/ScreenshotTour.swift) visits the routes and states listed in `design/tour.yaml`,
in light, dark and the largest accessibility text size, for every shipped language. `shots` runs it
three times and exports `design/shots/<variant>/<screen>.png` plus `design/shots/run.json`. `diff`
compares the run with `design/shots/baseline/`. `accept` makes the run the baseline. The manifest,
the app contract and the run.json schema are in docs/MATRIX.md.

The machine is a budget (decision S11). `shots` asks `teyla load --admit build` first, reuses a
booted simulator or boots exactly one, and shuts down the one it booted on every exit path. A run is
cut at nine minutes and reported as cut. Every process starts in `Runner.run`, so the orchestration
is tested with a fake runner and nothing here needs Xcode to import.

Exit status of `shots`: 0 the run completed (layout findings print and fail only with `--strict`);
1 a screen was unstable, the budget cut the run, or the tour failed; 2 the manifest, the config or
the machine guard refused; 3 the build or the simulator could not start. `diff` exits 1 when a screen changed, is new, is missing or is unstable.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import getpass
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable

MANIFEST_REL = "design/tour.yaml"
SHOTS_REL = "design/shots"
RESERVED_DIRS = ("baseline", "diff")
RUN_JSON = "run.json"
ACCEPTED_JSON = "ACCEPTED.json"
PLAN_ENV = "TEYLA_TOUR_PLAN"          # the tour reads it; xcodebuild passes TEST_RUNNER_<NAME> through

BUDGET_MIN = 9
RUNS_DEFAULT = 3
DEFAULT_THRESHOLD = 0.1               # percent of pixels that may differ
DEFAULT_TOLERANCE = 8                 # per-channel difference (0-255) below which a pixel is "the same"
MIN_TARGET_PT = 44.0
EDGE_TOLERANCE_PT = 1.0
OVERLAP_MIN_AREA_PT2 = 4.0
OVERLAP_MIN_SHARE = 0.10              # of the smaller element
MAX_ELEMENTS = 400
OUTPUT_TAIL = 6000                    # characters of a failed command's output kept in a message

STATES = ("empty", "loaded", "error", "listening")
# look -> how the tour launches the app. The sizes are UIContentSizeCategory names.
LOOKS = {
    "light": {"style": "light", "content_size": "UICTContentSizeCategoryL"},
    "dark": {"style": "dark", "content_size": "UICTContentSizeCategoryL"},
    "large": {"style": "light", "content_size": "UICTContentSizeCategoryAccessibilityXXXL"},
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")


# --- a small YAML subset -------------------------------------------------------------------------
# The manifest is YAML so a person can read and edit it, and Teyla has no dependencies. The subset:
# block maps and lists (a list item may open a map), inline lists and maps, quoted strings, numbers,
# true/false/null, `#` comments. JSON is accepted too. Anything else is an error with a line number.

class YamlError(ValueError):
    pass


def _strip_comment(s: str) -> str:
    quote = ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def _split_top(s: str) -> list[str]:
    parts, depth, quote, cur = [], 0, "", []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _find_colon(s: str) -> int:
    """Index of the `:` that ends a key (followed by a space or the end), outside quotes; -1 if none."""
    quote = ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(s) or s[i + 1] == " "):
            return i
    return -1


def _scalar(s: str, n: int):
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s[0] in "\"'":
        if len(s) < 2 or s[-1] != s[0]:
            raise YamlError(f"line {n}: unterminated quote")
        return s[1:-1]
    if s[0] == "[":
        if s[-1] != "]":
            raise YamlError(f"line {n}: unterminated [ list")
        return [_scalar(p, n) for p in _split_top(s[1:-1])]
    if s[0] == "{":
        if s[-1] != "}":
            raise YamlError(f"line {n}: unterminated {{ map")
        out = {}
        for p in _split_top(s[1:-1]):
            k = _find_colon(p)
            if k < 0:
                raise YamlError(f"line {n}: expected `key: value` inside {{ }}")
            out[p[:k].strip().strip("\"'")] = _scalar(p[k + 1:], n)
        return out
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def parse_yaml(text: str):
    """The manifest subset of YAML (or JSON) as Python values. Raises YamlError."""
    if text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise YamlError(f"not valid JSON: {e}") from None
    lines: list[tuple[int, str, int]] = []
    for n, raw in enumerate(text.lstrip("﻿").splitlines(), start=1):
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        if "\t" in body[: len(body) - len(body.lstrip())]:
            raise YamlError(f"line {n}: tabs are not allowed for indentation")
        lines.append((len(body) - len(body.lstrip(" ")), body.strip(), n))
    if not lines:
        return {}
    value, i = _block(lines, 0, lines[0][0])
    if i < len(lines):
        raise YamlError(f"line {lines[i][2]}: unexpected indentation")
    return value


def _block(lines, i: int, indent: int):
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _list(lines, i, indent)
    return _map(lines, i, indent)


def _map(lines, i: int, indent: int):
    out: dict = {}
    while i < len(lines):
        ind, body, n = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"line {n}: unexpected indentation")
        if body.startswith("- ") or body == "-":
            break
        k = _find_colon(body)
        if k < 0:
            raise YamlError(f"line {n}: expected `key: value`")
        key = body[:k].strip().strip("\"'")
        if not key:
            raise YamlError(f"line {n}: empty key")
        if key in out:
            raise YamlError(f"line {n}: duplicate key `{key}`")
        rest = body[k + 1:].strip()
        i += 1
        if rest:
            out[key] = _scalar(rest, n)
        elif i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and lines[i][1].startswith("-"))):
            out[key], i = _block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


def _list(lines, i: int, indent: int):
    out: list = []
    while i < len(lines):
        ind, body, n = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"line {n}: unexpected indentation")
        if not (body.startswith("- ") or body == "-"):
            break
        rest = body[1:].strip()
        if not rest:
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                item, i = _block(lines, i, lines[i][0])
            else:
                item = None
            out.append(item)
        elif rest[0] not in "[{\"'" and _find_colon(rest) >= 0:
            # `- key: value` opens a map whose keys line up after the dash.
            inner = indent + (len(body) - len(rest))
            sub = [(inner, rest, n)]
            j = i + 1
            while j < len(lines) and lines[j][0] > indent:
                sub.append(lines[j])
                j += 1
            item, used = _map(sub, 0, inner)
            if used < len(sub):
                raise YamlError(f"line {sub[used][2]}: unexpected indentation")
            out.append(item)
            i = j
        else:
            out.append(_scalar(rest, n))
            i += 1
    return out, i


# --- the manifest --------------------------------------------------------------------------------

class ManifestError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclasses.dataclass(frozen=True)
class Mask:
    name: str
    x: float
    y: float
    w: float
    h: float


@dataclasses.dataclass(frozen=True)
class Screen:
    id: str                      # "<route>.<state>"
    route: str
    path: str
    state: str
    threshold: float             # percent of pixels
    masks: tuple[str, ...]


@dataclasses.dataclass
class Manifest:
    fixed_date: str
    seed: int
    network_stub: bool
    languages: list[str]
    looks: list[str]
    runs: int
    device_name: str
    device_w: float
    device_h: float
    masks: dict[str, Mask]
    threshold: float
    tolerance: int
    screens: list[Screen]
    sha256: str = ""

    def screen(self, screen_id: str) -> Screen | None:
        return next((s for s in self.screens if s.id == screen_id), None)

    def variants(self) -> list[str]:
        return [f"{lang}-{look}" for lang in self.languages for look in self.looks]

    def plan(self) -> dict:
        """What the tour reads from $TEYLA_TOUR_PLAN."""
        return {
            "version": 1, "fixed_date": self.fixed_date, "seed": self.seed, "network_stub": self.network_stub,
            "languages": self.languages,
            "looks": [{"name": k, **LOOKS[k]} for k in self.looks],
            "screens": [{"id": s.id, "route": s.route, "path": s.path, "state": s.state} for s in self.screens],
        }


_TOP_KEYS = {"version", "fixed_date", "seed", "network_stub", "languages", "looks", "runs", "device", "masks",
             "defaults", "routes"}
_ROUTE_KEYS = {"id", "path", "states", "threshold", "masks"}
_STATE_KEYS = {"name", "threshold", "masks"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(data, raw_text: str = "") -> tuple[Manifest | None, list[str]]:
    """(manifest, errors). The manifest is None when there is any error."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return None, ["the manifest must be a map of keys"]
    for k in data:
        if k not in _TOP_KEYS:
            errs.append(f"unknown key `{k}` (allowed: {', '.join(sorted(_TOP_KEYS))})")
    if data.get("version", 1) != 1:
        errs.append("`version` must be 1")

    fixed = data.get("fixed_date")
    if not isinstance(fixed, str):
        errs.append("`fixed_date` is required: an ISO 8601 date and time, e.g. 2026-01-15T09:41:00Z")
        fixed = ""
    else:
        try:
            dt.datetime.fromisoformat(fixed.replace("Z", "+00:00"))
        except ValueError:
            errs.append(f"`fixed_date` {fixed!r} is not an ISO 8601 date and time")
    seed = data.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        errs.append("`seed` is required: an integer the app seeds its fixture data with")
        seed = 0
    stub = data.get("network_stub", True)
    if not isinstance(stub, bool):
        errs.append("`network_stub` must be true or false")
        stub = True

    langs = data.get("languages", ["en"])
    if not isinstance(langs, list) or not langs or not all(isinstance(x, str) and _LANG.match(x) for x in langs):
        errs.append("`languages` must be a non-empty list of language codes such as [en, es]")
        langs = ["en"]
    elif len(set(langs)) != len(langs):
        errs.append("`languages` lists a language twice")
    looks = data.get("looks", list(LOOKS))
    if not isinstance(looks, list) or not looks or any(x not in LOOKS for x in looks):
        errs.append(f"`looks` must be a non-empty list drawn from {list(LOOKS)}")
        looks = list(LOOKS)
    runs = data.get("runs", RUNS_DEFAULT)
    if not isinstance(runs, int) or isinstance(runs, bool) or not 1 <= runs <= 5:
        errs.append("`runs` must be an integer from 1 to 5")
        runs = RUNS_DEFAULT

    dev = data.get("device")
    dev_name, dw, dh = "", 0.0, 0.0
    if not isinstance(dev, dict):
        errs.append("`device` is required: {name: ..., width_pt: ..., height_pt: ...} (masks are in points)")
    else:
        for k in dev:
            if k not in ("name", "width_pt", "height_pt"):
                errs.append(f"device: unknown key `{k}`")
        dev_name = dev.get("name") or ""
        if not isinstance(dev_name, str):
            errs.append("device.name must be a string")
            dev_name = ""
        if _num(dev.get("width_pt")) and _num(dev.get("height_pt")) and dev["width_pt"] > 0 and dev["height_pt"] > 0:
            dw, dh = float(dev["width_pt"]), float(dev["height_pt"])
        else:
            errs.append("device.width_pt and device.height_pt must be positive numbers")

    masks: dict[str, Mask] = {}
    raw_masks = data.get("masks") or {}
    if not isinstance(raw_masks, dict):
        errs.append("`masks` must be a map of name -> {x, y, w, h}")
        raw_masks = {}
    for name, m in raw_masks.items():
        if not isinstance(name, str) or not _SLUG.match(name):
            errs.append(f"masks: name {name!r} must be lowercase letters, digits and dashes")
            continue
        if not isinstance(m, dict) or set(m) != {"x", "y", "w", "h"} or not all(_num(m[k]) for k in m):
            errs.append(f"masks.{name}: expected {{x, y, w, h}} in points")
            continue
        if m["x"] < 0 or m["y"] < 0 or m["w"] <= 0 or m["h"] <= 0:
            errs.append(f"masks.{name}: x and y must be 0 or more, w and h above 0")
            continue
        if dw and (m["x"] + m["w"] > dw + 0.5 or m["y"] + m["h"] > dh + 0.5):
            errs.append(f"masks.{name}: the rectangle leaves the {dw:g} x {dh:g} pt device screen")
            continue
        masks[name] = Mask(name, float(m["x"]), float(m["y"]), float(m["w"]), float(m["h"]))

    defaults = data.get("defaults") or {}
    threshold, tolerance = DEFAULT_THRESHOLD, DEFAULT_TOLERANCE
    if not isinstance(defaults, dict):
        errs.append("`defaults` must be a map")
    else:
        for k in defaults:
            if k not in ("threshold", "tolerance"):
                errs.append(f"defaults: unknown key `{k}`")
        if "threshold" in defaults:
            t = defaults["threshold"]
            if _num(t) and 0 <= t <= 100:
                threshold = float(t)
            else:
                errs.append("defaults.threshold must be a percentage from 0 to 100")
        if "tolerance" in defaults:
            t = defaults["tolerance"]
            if isinstance(t, int) and not isinstance(t, bool) and 0 <= t <= 255:
                tolerance = t
            else:
                errs.append("defaults.tolerance must be an integer from 0 to 255")

    screens: list[Screen] = []
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        errs.append("`routes` is required: a non-empty list of {id, path, states}")
        routes = []
    seen_routes: set[str] = set()
    for ri, r in enumerate(routes):
        where = f"routes[{ri}]"
        if not isinstance(r, dict):
            errs.append(f"{where}: expected a map with id, path and states")
            continue
        rid = r.get("id")
        if isinstance(rid, str):
            where = f"route `{rid}`"
        for k in r:
            if k not in _ROUTE_KEYS:
                errs.append(f"{where}: unknown key `{k}` (allowed: {', '.join(sorted(_ROUTE_KEYS))})")
        if not isinstance(rid, str) or not _SLUG.match(rid):
            errs.append(f"{where}: `id` must be lowercase letters, digits and dashes")
            continue
        if rid in seen_routes:
            errs.append(f"{where}: the id is used twice")
            continue
        seen_routes.add(rid)
        path = r.get("path")
        if not isinstance(path, str) or not path.strip():
            errs.append(f"{where}: `path` is required: the route the app opens, e.g. /today")
            path = ""
        r_threshold = r.get("threshold", threshold)
        if not (_num(r_threshold) and 0 <= r_threshold <= 100):
            errs.append(f"{where}: threshold must be a percentage from 0 to 100")
            r_threshold = threshold
        r_masks = r.get("masks") or []
        if not isinstance(r_masks, list) or any(m not in masks for m in r_masks):
            bad = [m for m in (r_masks if isinstance(r_masks, list) else []) if m not in masks]
            errs.append(f"{where}: masks must be a list of names defined under `masks`" + (f" (unknown: {bad})" if bad else ""))
            r_masks = []
        states = r.get("states")
        if not isinstance(states, list) or not states:
            errs.append(f"{where}: `states` is required: a non-empty list drawn from {list(STATES)}")
            continue
        seen_states: set[str] = set()
        for si, st in enumerate(states):
            if isinstance(st, str):
                st = {"name": st}
            if not isinstance(st, dict):
                errs.append(f"{where}: states[{si}] must be a state name or {{name, threshold, masks}}")
                continue
            for k in st:
                if k not in _STATE_KEYS:
                    errs.append(f"{where}: states[{si}]: unknown key `{k}`")
            name = st.get("name")
            if name not in STATES:
                errs.append(f"{where}: state {name!r} is not one of {list(STATES)}")
                continue
            if name in seen_states:
                errs.append(f"{where}: state `{name}` is listed twice")
                continue
            seen_states.add(name)
            s_threshold = st.get("threshold", r_threshold)
            if not (_num(s_threshold) and 0 <= s_threshold <= 100):
                errs.append(f"{where}: state `{name}`: threshold must be a percentage from 0 to 100")
                s_threshold = r_threshold
            s_masks = st.get("masks")
            if s_masks is None:
                s_masks = list(r_masks)
            elif not isinstance(s_masks, list) or any(m not in masks for m in s_masks):
                errs.append(f"{where}: state `{name}`: masks must be names defined under `masks`")
                s_masks = []
            else:
                s_masks = list(dict.fromkeys(list(r_masks) + s_masks))
            screens.append(Screen(f"{rid}.{name}", rid, path, name, float(s_threshold), tuple(s_masks)))

    if errs:
        return None, errs
    return Manifest(
        fixed_date=fixed, seed=seed, network_stub=stub, languages=list(langs), looks=list(looks), runs=runs,
        device_name=dev_name, device_w=dw, device_h=dh, masks=masks, threshold=threshold, tolerance=tolerance,
        screens=screens, sha256=hashlib.sha256(raw_text.encode()).hexdigest() if raw_text else ""), []


def load_manifest(repo: pathlib.Path) -> Manifest:
    p = pathlib.Path(repo) / MANIFEST_REL
    if not p.is_file():
        raise ManifestError([f"{MANIFEST_REL} not found in {repo}: write the manifest (docs/MATRIX.md has an example)"])
    text = p.read_text()
    try:
        data = parse_yaml(text)
    except YamlError as e:
        raise ManifestError([f"{MANIFEST_REL}: {e}"]) from None
    m, errs = validate(data, text)
    if errs or m is None:
        raise ManifestError(errs)
    return m


# --- the product's tour settings (teyla.toml) -----------------------------------------------------

class ConfigError(Exception):
    pass


@dataclasses.dataclass
class TourConfig:
    project_flag: str            # "-project" or "-workspace"
    project: str
    scheme: str
    device: str
    only_testing: str = ""


def load_tour_config(repo: pathlib.Path, device_override: str = "", manifest: Manifest | None = None) -> TourConfig:
    f = pathlib.Path(repo) / "teyla.toml"
    if not f.is_file():
        raise ConfigError(f"no teyla.toml in {repo}: add a [ux.tour] table (docs/MATRIX.md)")
    try:
        d = tomllib.loads(f.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"teyla.toml does not parse: {e}") from None
    t = (d.get("ux") or {}).get("tour")
    if not isinstance(t, dict):
        raise ConfigError("teyla.toml has no [ux.tour] table: set scheme and project (docs/MATRIX.md)")
    scheme = t.get("scheme")
    if not isinstance(scheme, str) or not scheme:
        raise ConfigError("[ux.tour] scheme is required: the scheme that holds the screenshot tour")
    proj, ws = t.get("project"), t.get("workspace")
    if bool(proj) == bool(ws):
        raise ConfigError("[ux.tour] needs exactly one of project (.xcodeproj) or workspace (.xcworkspace)")
    device = device_override or t.get("device") or (manifest.device_name if manifest else "")
    if not isinstance(device, str) or not device:
        raise ConfigError("[ux.tour] device is required (a simulator name such as \"iPhone 17\"), or device.name in the manifest")
    only = t.get("only_testing") or ""
    if not isinstance(only, str):
        raise ConfigError("[ux.tour] only_testing must be a string such as \"AppUITests/ScreenshotTour\"")
    return TourConfig("-workspace" if ws else "-project", str(ws or proj), scheme, device, only)


# --- the one place a process starts --------------------------------------------------------------

@dataclasses.dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class Runner:
    """Starts processes. The orchestration calls only this, so tests replace it with a fake."""

    def run(self, argv: list[str], *, timeout: float | None = None, env: dict | None = None,
            cwd: str | os.PathLike | None = None) -> Result:
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                 env=env, cwd=cwd, start_new_session=True)
        except OSError as e:
            return Result(127, "", f"{argv[0]}: {e}")
        try:
            out, err = p.communicate(timeout=timeout)
            return Result(p.returncode, out or "", err or "")
        except subprocess.TimeoutExpired:
            self._kill(p)
            try:
                out, err = p.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                out = err = ""
            return Result(-signal.SIGKILL, out or "", err or "", timed_out=True)

    @staticmethod
    def _kill(p) -> None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass


# --- the simulator -------------------------------------------------------------------------------

def _runtime_key(runtime: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", runtime.rsplit(".", 1)[-1]))


def pick_device(listing: dict, name: str) -> tuple[str, bool] | None:
    """(udid, already_booted) for a simulator called `name` from `simctl list devices -j`, or None.
    A booted device wins (the policy is to reuse one); otherwise the newest runtime's available one."""
    booted, available = [], []
    for runtime, devices in (listing.get("devices") or {}).items():
        if "iOS" not in runtime:
            continue
        for d in devices or []:
            if d.get("name") != name or d.get("isAvailable") is False:
                continue
            (booted if d.get("state") == "Booted" else available).append((_runtime_key(runtime), d.get("udid", "")))
    if booted:
        return sorted(booted)[-1][1], True
    if available:
        return sorted(available)[-1][1], False
    return None


class SimulatorError(RuntimeError):
    pass


class Simulator:
    """Reuses a booted simulator or boots one, and shuts down only the one it booted."""

    def __init__(self, runner: Runner, name: str):
        self.runner = runner
        self.name = name
        self.udid = ""
        self.booted_by_us = False
        self._status_bar = False

    def acquire(self, clock: str = "9:41") -> str:
        r = self.runner.run(["xcrun", "simctl", "list", "devices", "-j"], timeout=60)
        if r.returncode != 0:
            raise SimulatorError(f"simctl list failed: {r.stderr.strip()[-300:]}")
        try:
            found = pick_device(json.loads(r.stdout), self.name)
        except json.JSONDecodeError:
            raise SimulatorError("simctl list did not print JSON") from None
        if found is None:
            raise SimulatorError(f"no available simulator named {self.name!r} (xcrun simctl list devices)")
        self.udid, booted = found
        if not booted:
            # Mark it ours before the boot: a boot that fails halfway still gets a shutdown.
            self.booted_by_us = True
            r = self.runner.run(["xcrun", "simctl", "boot", self.udid], timeout=120)
            if r.returncode != 0 and "current state: Booted" not in (r.stderr + r.stdout):
                raise SimulatorError(f"simctl boot failed: {(r.stderr or r.stdout).strip()[-300:]}")
            r = self.runner.run(["xcrun", "simctl", "bootstatus", self.udid], timeout=240)
            if r.returncode != 0:
                raise SimulatorError("the simulator did not finish booting")
        self._status_bar = True
        self.runner.run(["xcrun", "simctl", "status_bar", self.udid, "override", "--time", clock, "--batteryState",
                         "charged", "--batteryLevel", "100", "--cellularMode", "active", "--cellularBars", "4",
                         "--wifiMode", "active", "--wifiBars", "3"], timeout=30)
        return self.udid

    def release(self) -> None:
        """Never raises: it runs in a `finally`."""
        try:
            if self.udid and self._status_bar:
                self.runner.run(["xcrun", "simctl", "status_bar", self.udid, "clear"], timeout=30)
        except Exception:
            pass
        try:
            if self.udid and self.booted_by_us:
                self.runner.run(["xcrun", "simctl", "shutdown", self.udid], timeout=60)
        except Exception:
            pass
        finally:
            self.booted_by_us = False


# --- commands the run starts ---------------------------------------------------------------------

def teyla_cmd() -> list[str]:
    return [sys.executable, "-m", "teyla"]


def derived_data(repo: pathlib.Path) -> pathlib.Path:
    from .control import state as control
    return control.home() / "shots" / pathlib.Path(repo).name / "derived"


def xcodebuild_build_argv(cfg: TourConfig, udid: str, derived: str) -> list[str]:
    return ["xcodebuild", "build-for-testing", cfg.project_flag, cfg.project, "-scheme", cfg.scheme,
            "-destination", f"platform=iOS Simulator,id={udid}", "-derivedDataPath", derived, "-quiet"]


def xcodebuild_test_argv(cfg: TourConfig, udid: str, derived: str, bundle: str) -> list[str]:
    argv = ["xcodebuild", "test-without-building", cfg.project_flag, cfg.project, "-scheme", cfg.scheme,
            "-destination", f"platform=iOS Simulator,id={udid}", "-derivedDataPath", derived,
            "-resultBundlePath", bundle, "-parallel-testing-enabled", "NO", "-quiet"]
    if cfg.only_testing:
        argv += [f"-only-testing:{cfg.only_testing}"]
    return argv


def export_argv(bundle: str, out_dir: str) -> list[str]:
    return ["xcrun", "xcresulttool", "export", "attachments", "--path", bundle, "--output-path", out_dir]


# --- reading what the tour exported --------------------------------------------------------------

@dataclasses.dataclass
class Capture:
    variant: str
    screen: str
    png: pathlib.Path | None = None
    elements: pathlib.Path | None = None
    audit: pathlib.Path | None = None


_ATTACH = re.compile(
    r"^(?P<variant>[a-z0-9]+(?:-[a-z0-9]+)*)__(?P<route>[a-z0-9]+(?:-[a-z0-9]+)*)\.(?P<state>[a-z]+)"
    r"(?:\.(?P<kind>elements|audit))?(?:_\d+_[0-9A-Fa-f-]{36})?(?:\.(?:png|json))?$")


def classify_attachment(name: str) -> tuple[str, str, str] | None:
    """(variant, screen id, kind) from an attachment name such as `en-light__today.loaded` or
    `en-light__today.loaded.elements_0_<uuid>.json`; kind is png, elements or audit. None for others."""
    m = _ATTACH.match(name)
    if not m or m["state"] not in STATES:
        return None
    return m["variant"], f"{m['route']}.{m['state']}", m["kind"] or "png"


def parse_export(export_dir: pathlib.Path) -> dict[tuple[str, str], Capture]:
    """The attachments `xcresulttool export attachments` wrote, by (variant, screen id). Reads its
    manifest.json (testIdentifier -> attachments with exportedFileName and suggestedHumanReadableName)."""
    export_dir = pathlib.Path(export_dir)
    out: dict[tuple[str, str], Capture] = {}
    mf = export_dir / "manifest.json"
    entries: list[tuple[str, str]] = []
    if mf.is_file():
        try:
            data = json.loads(mf.read_text())
        except json.JSONDecodeError:
            data = []
        for test in data if isinstance(data, list) else []:
            for a in (test or {}).get("attachments") or []:
                fn, human = a.get("exportedFileName"), a.get("suggestedHumanReadableName")
                if isinstance(fn, str) and isinstance(human, str):
                    entries.append((fn, human))
    else:
        entries = [(p.name, p.name) for p in export_dir.iterdir() if p.is_file()]
    for fn, human in entries:
        c = classify_attachment(human)
        path = export_dir / fn
        if c is None or not path.is_file():
            continue
        variant, screen, kind = c
        cap = out.setdefault((variant, screen), Capture(variant, screen))
        setattr(cap, {"png": "png", "elements": "elements", "audit": "audit"}[kind], path)
    return out


# --- the layout checks ---------------------------------------------------------------------------

INTERACTIVE_TYPES = {"button", "link", "switch", "toggle", "slider", "stepper", "textfield", "securetextfield",
                     "searchfield", "segmentedcontrol", "tab", "checkbox", "radiobutton", "picker", "datepicker",
                     "menuitem", "menubutton", "textview"}
CONTAINER_TYPES = {"other", "window", "application", "scrollview", "table", "collectionview", "cell", "navigationbar",
                   "tabbar", "toolbar", "statusbar", "keyboard", "alert", "sheet", "popover", "group", "webview",
                   "layoutitem", "key", "map"}


def _ellipsis(label: str) -> bool:
    return label.rstrip().endswith(("…", "..."))


def _rect(e: dict) -> tuple[float, float, float, float] | None:
    try:
        x, y, w, h = (float(e[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y, w, h) if w > 0 and h > 0 else None


def _name(e: dict) -> str:
    return f"{str(e.get('type') or 'element').lower()} '{e.get('label') or e.get('id') or ''}'".replace("''", "(no label)")


def analyze_elements(doc: dict) -> list[dict]:
    """Findings from the tour's element frames: overlap, off-screen, truncated, small-target.
    `doc` is {"screen": {"width", "height"}, "elements": [{"type", "label", "id", "x", "y", "w", "h",
    "interactive", "container", "in_scroll", "truncated"}]} in points. Heuristics, not proof."""
    findings: list[dict] = []
    screen = doc.get("screen") or {}
    sw, sh = float(screen.get("width") or 0), float(screen.get("height") or 0)
    elements = [e for e in (doc.get("elements") or []) if isinstance(e, dict) and _rect(e)][:MAX_ELEMENTS]
    leaves = []
    for e in elements:
        t = str(e.get("type") or "").lower()
        x, y, w, h = _rect(e)  # type: ignore[misc]
        container = bool(e.get("container")) if "container" in e else t in CONTAINER_TYPES
        interactive = bool(e.get("interactive")) if "interactive" in e else t in INTERACTIVE_TYPES
        label = str(e.get("label") or "")
        if interactive and (w < MIN_TARGET_PT - 0.01 or h < MIN_TARGET_PT - 0.01):
            findings.append({"kind": "small-target", "elements": [_name(e)],
                             "detail": f"{w:g} x {h:g} pt, under {MIN_TARGET_PT:g} x {MIN_TARGET_PT:g}"})
        if sw and sh and not e.get("in_scroll") and t not in ("window", "application", "statusbar", "keyboard") and (
                x < -EDGE_TOLERANCE_PT or y < -EDGE_TOLERANCE_PT or x + w > sw + EDGE_TOLERANCE_PT or y + h > sh + EDGE_TOLERANCE_PT):
            findings.append({"kind": "off-screen", "elements": [_name(e)],
                             "detail": f"frame {x:g},{y:g} {w:g} x {h:g} leaves the {sw:g} x {sh:g} pt screen"})
        if e.get("truncated") is True or (label and _ellipsis(label) and t in ("statictext", "button", "link", "textview")):
            findings.append({"kind": "truncated", "elements": [_name(e)], "detail": "the label is cut with an ellipsis"})
        if not container:
            leaves.append((e, x, y, w, h))
    for i in range(len(leaves)):
        a, ax, ay, aw, ah = leaves[i]
        for j in range(i + 1, len(leaves)):
            b, bx, by, bw, bh = leaves[j]
            ix = min(ax + aw, bx + bw) - max(ax, bx)
            iy = min(ay + ah, by + bh) - max(ay, by)
            if ix <= EDGE_TOLERANCE_PT or iy <= EDGE_TOLERANCE_PT:
                continue
            tol = EDGE_TOLERANCE_PT
            a_in_b = ax >= bx - tol and ay >= by - tol and ax + aw <= bx + bw + tol and ay + ah <= by + bh + tol
            b_in_a = bx >= ax - tol and by >= ay - tol and bx + bw <= ax + aw + tol and by + bh <= ay + ah + tol
            if a_in_b or b_in_a:
                continue
            area = ix * iy
            if area < OVERLAP_MIN_AREA_PT2 or area / min(aw * ah, bw * bh) < OVERLAP_MIN_SHARE:
                continue
            findings.append({"kind": "overlap", "elements": [_name(a), _name(b)], "detail": f"{area:g} pt2 in common"})
    return findings


def summarize_audit(doc: dict | None) -> dict:
    """{"ran", "issue_count", "issues": [...], "error"} from the tour's audit attachment."""
    if not isinstance(doc, dict):
        return {"ran": False, "issue_count": 0, "issues": [], "error": "the tour exported no audit"}
    issues = [i for i in (doc.get("issues") or []) if isinstance(i, dict)]
    return {"ran": bool(doc.get("ran", True)), "issue_count": len(issues), "issues": issues[:20],
            "error": doc.get("error") or None}


def _read_json(path: pathlib.Path | None):
    if path is None:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# --- hashes and stability ------------------------------------------------------------------------

def png_hash(path: pathlib.Path) -> str:
    """Pixel hash when Pillow is there (metadata cannot change it), file hash otherwise."""
    try:
        from PIL import Image
    except ImportError:
        return "file:" + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:24]
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        h = hashlib.sha256(f"{rgba.width}x{rgba.height}".encode() + rgba.tobytes()).hexdigest()[:24]
    return "px:" + h


def stability(hashes: list[str]) -> bool | None:
    """True when every run agrees, False when two differ, None when there is only one run to judge by."""
    if len(hashes) < 2:
        return None
    return len(set(hashes)) == 1


# --- one tour run --------------------------------------------------------------------------------

class GuardRefused(Exception):
    pass


class TourFailed(Exception):
    pass


def aggregate(manifest: Manifest, runs: list[dict[tuple[str, str], Capture]], runs_requested: int) -> dict[str, dict]:
    """The run.json `screens` map from the captures of each completed run."""
    out: dict[str, dict] = {}
    for variant in manifest.variants():
        for s in manifest.screens:
            key = (variant, s.id)
            caps = [r[key] for r in runs if key in r and r[key].png is not None]
            entry: dict = {"variant": variant, "screen": s.id, "route": s.route, "state": s.state,
                           "hashes": [png_hash(c.png) for c in caps if c.png], "captured": len(caps)}
            entry["stable"] = stability(entry["hashes"])
            if len(caps) < len(runs):
                entry["missing_runs"] = len(runs) - len(caps)
            audits = [summarize_audit(_read_json(c.audit)) for c in caps]
            seen, issues = set(), []
            for a in audits:
                for i in a["issues"]:
                    k = json.dumps(i, sort_keys=True)
                    if k not in seen:
                        seen.add(k)
                        issues.append(i)
            entry["audit"] = {"ran": any(a["ran"] for a in audits), "issue_count": len(issues), "issues": issues[:20],
                              "error": next((a["error"] for a in audits if a["error"]), None) if audits else "not captured"}
            findings, seen_f = [], set()
            for c in caps:
                doc = _read_json(c.elements)
                if not isinstance(doc, dict):
                    continue
                for f in analyze_elements(doc):
                    k = (f["kind"], tuple(f["elements"]))
                    if k not in seen_f:
                        seen_f.add(k)
                        findings.append(f)
            entry["findings"] = findings
            out[f"{variant}/{s.id}"] = entry
    return out


def run_json(manifest: Manifest, screens: dict[str, dict], *, status: str, started: str, finished: str,
             duration_s: float, budget_s: float, runs_requested: int, runs_completed: int,
             device: str, commit: str, errors: list[str]) -> dict:
    unstable = sorted(k for k, v in screens.items() if v["stable"] is False)
    uncaptured = sorted(k for k, v in screens.items() if v["captured"] == 0)
    return {
        "version": 1, "status": status, "started": started, "finished": finished,
        "duration_s": round(duration_s, 1), "budget_s": budget_s,
        "runs_requested": runs_requested, "runs_completed": runs_completed,
        "device": device, "commit": commit, "manifest_sha256": manifest.sha256,
        "variants": manifest.variants(), "screens": screens, "unstable": unstable, "uncaptured": uncaptured,
        "counts": {
            "screens": len(screens), "unstable": len(unstable), "uncaptured": len(uncaptured),
            "findings": sum(len(v["findings"]) for v in screens.values()),
            "audit_issues": sum(v["audit"]["issue_count"] for v in screens.values()),
        },
        "errors": errors,
    }


def write_shots(repo: pathlib.Path, first_run: dict[tuple[str, str], Capture], manifest: Manifest, doc: dict) -> None:
    """design/shots/<variant>/<screen>.png from the first completed run, plus run.json. The variant
    folders of the earlier run and of this manifest go first, so a screen that left the manifest does not
    linger; `baseline`, `diff` and any other folder are never touched."""
    root = pathlib.Path(repo) / SHOTS_REL
    root.mkdir(parents=True, exist_ok=True)
    earlier = (_read_json(root / RUN_JSON) or {}).get("variants") or []
    for name in set(earlier) | set(manifest.variants()):
        if name not in RESERVED_DIRS and _SLUG.match(str(name)):
            shutil.rmtree(root / name, ignore_errors=True)
    for (variant, screen), cap in first_run.items():
        if cap.png is None:
            continue
        dest = root / variant
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cap.png, dest / f"{screen}.png")
    (root / RUN_JSON).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(repo: pathlib.Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _tail(s: str) -> str:
    s = s.strip()
    return s[-OUTPUT_TAIL:]


def run_shots(repo: pathlib.Path, manifest: Manifest, cfg: TourConfig, runner: Runner, *, runs: int | None = None,
              budget_s: float = BUDGET_MIN * 60, clock: Callable[[], float] = time.monotonic,
              work_dir: pathlib.Path | None = None, derived: pathlib.Path | None = None) -> dict:
    """Admit, build once, boot one simulator, run the tour `runs` times, export, aggregate, write.
    Returns the run.json document. Raises GuardRefused, SimulatorError or TourFailed before anything is
    written. The simulator this call booted is shut down on every path out."""
    import tempfile

    repo = pathlib.Path(repo)
    runs = runs or manifest.runs
    started_iso = _now_iso()
    guard_cwd = str(repo)
    r = runner.run(teyla_cmd() + ["load", "--admit", "build", "--cwd", guard_cwd], timeout=120)
    if r.returncode != 0:
        raise GuardRefused(_tail(r.stdout + r.stderr) or "teyla load --admit build refused")
    # A simulator is admitted separately; the guard holds the next job for its settle time, so wait for a slot.
    r = runner.run(teyla_cmd() + ["load", "--wait", "--kind", "sim", "--cwd", guard_cwd], timeout=1800)
    if r.returncode != 0:
        raise GuardRefused(_tail(r.stdout + r.stderr) or "teyla load --wait --kind sim gave no slot")

    t0 = clock()
    deadline = t0 + budget_s

    def remaining() -> float:
        return deadline - clock()

    tmp = pathlib.Path(work_dir) if work_dir else pathlib.Path(tempfile.mkdtemp(prefix="teyla-shots-"))
    tmp.mkdir(parents=True, exist_ok=True)
    derived_path = str(derived or derived_data(repo))
    sim = Simulator(runner, cfg.device)
    errors: list[str] = []
    completed: list[dict[tuple[str, str], Capture]] = []
    status = "complete"
    try:
        d = dt.datetime.fromisoformat(manifest.fixed_date.replace("Z", "+00:00"))
        udid = sim.acquire(f"{d.hour}:{d.minute:02d}")
        r = runner.run(xcodebuild_build_argv(cfg, udid, derived_path), timeout=max(remaining(), 1), cwd=str(repo))
        if r.timed_out:
            status = "budget"
            errors.append("the budget ran out during the build")
        elif r.returncode != 0:
            raise TourFailed("xcodebuild build-for-testing failed:\n" + _tail(r.stderr + "\n" + r.stdout))
        env = dict(os.environ)
        env["TEST_RUNNER_" + PLAN_ENV] = json.dumps(manifest.plan(), separators=(",", ":"))
        for n in range(1, runs + 1):
            if status != "complete":
                break
            if remaining() <= 0:
                status = "budget"
                errors.append(f"the budget ran out before run {n}")
                break
            bundle = str(tmp / f"run-{n}.xcresult")
            shutil.rmtree(bundle, ignore_errors=True)
            r = runner.run(xcodebuild_test_argv(cfg, udid, derived_path, bundle), timeout=max(remaining(), 1), env=env, cwd=str(repo))
            if r.timed_out:
                status = "budget"
                errors.append(f"the budget ran out during run {n}; the run is dropped")
                break
            out_dir = tmp / f"attachments-{n}"
            shutil.rmtree(out_dir, ignore_errors=True)
            out_dir.mkdir(parents=True)
            x = runner.run(export_argv(bundle, str(out_dir)), timeout=max(min(remaining(), 300), 30))
            caps = parse_export(out_dir) if x.returncode == 0 else {}
            if x.returncode != 0:
                errors.append(f"run {n}: attachments could not be exported: {_tail(x.stderr)[-300:]}")
            if r.returncode != 0:
                errors.append(f"run {n}: xcodebuild test exited {r.returncode}: {_tail(r.stderr + chr(10) + r.stdout)[-600:]}")
                if not caps:
                    status = "failed"
                    break
            if not caps:
                status = "failed"
                errors.append(f"run {n}: the tour exported no screenshots")
                break
            completed.append(caps)
    finally:
        sim.release()

    duration = clock() - t0
    if completed or status == "complete":
        screens = aggregate(manifest, completed, runs)
        doc = run_json(manifest, screens, status=status, started=started_iso, finished=_now_iso(), duration_s=duration,
                       budget_s=budget_s, runs_requested=runs, runs_completed=len(completed), device=cfg.device,
                       commit=_commit(repo), errors=errors)
        if completed:
            write_shots(repo, completed[0], manifest, doc)
        return doc
    # Nothing usable: say why, leave the earlier shots alone.
    doc = run_json(manifest, {}, status=status, started=started_iso, finished=_now_iso(), duration_s=duration,
                   budget_s=budget_s, runs_requested=runs, runs_completed=0, device=cfg.device, commit=_commit(repo),
                   errors=errors)
    return doc


def render_run(doc: dict) -> str:
    c = doc["counts"]
    L = [f"teyla ux shots: {doc['status']} in {doc['duration_s']:.0f} s of {doc['budget_s']:.0f} s, "
         f"{doc['runs_completed']} of {doc['runs_requested']} run(s), {c['screens']} screen(s) in "
         f"{len(doc['variants'])} variant(s)"]
    for e in doc["errors"]:
        L.append(f"  error: {e}")
    if doc["status"] == "budget":
        L.append("  CUT: the nine-minute budget ended the tour. Trim the manifest (fewer languages, looks or runs) before trusting this run.")
    if doc["unstable"]:
        L.append(f"  UNSTABLE ({len(doc['unstable'])}): the runs of one build disagree")
        for k in doc["unstable"][:30]:
            L.append(f"    {k}")
    if doc["uncaptured"]:
        L.append(f"  NOT CAPTURED ({len(doc['uncaptured'])}): in the manifest, absent from the tour")
        for k in doc["uncaptured"][:30]:
            L.append(f"    {k}")
    shown = 0
    for k, v in sorted(doc["screens"].items()):
        for f in v["findings"]:
            if shown == 0:
                L.append(f"  LAYOUT ({c['findings']}):")
            if shown < 40:
                L.append(f"    {k}  {f['kind']}: {' / '.join(f['elements'])}  ({f['detail']})")
            shown += 1
        for i in v["audit"]["issues"][:3]:
            L.append(f"    {k}  audit: {i.get('description') or i}")
    if shown > 40:
        L.append(f"    ... and {shown - 40} more in design/shots/{RUN_JSON}")
    if not (doc["unstable"] or doc["uncaptured"] or c["findings"] or c["audit_issues"] or doc["errors"]):
        L.append("  no unstable screens, no layout findings, no audit issues")
    L.append(f"  next: teyla ux diff    (run: {SHOTS_REL}/{RUN_JSON})")
    return "\n".join(L)


# --- teyla ux diff -------------------------------------------------------------------------------

class PillowMissing(Exception):
    pass


def _pillow():
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError:
        raise PillowMissing(
            "teyla ux diff needs Pillow. Fix: uv tool install --force --python 3.12 --with pillow git+https://github.com/zaitsew/teyla"
        ) from None
    return Image, ImageChops, ImageDraw


@dataclasses.dataclass
class ScreenDiff:
    variant: str
    screen: str
    percent: float = 0.0
    threshold: float = DEFAULT_THRESHOLD
    reason: str = ""
    image: str = ""


@dataclasses.dataclass
class DiffReport:
    changed: list[ScreenDiff] = dataclasses.field(default_factory=list)
    new: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    missing: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    unstable: list[str] = dataclasses.field(default_factory=list)
    unchanged: int = 0
    compared: int = 0

    @property
    def dirty(self) -> bool:
        return bool(self.changed or self.new or self.missing or self.unstable)


def _variants(root: pathlib.Path) -> dict[str, dict[str, pathlib.Path]]:
    out: dict[str, dict[str, pathlib.Path]] = {}
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name not in RESERVED_DIRS and not d.name.startswith("."):
            out[d.name] = {p.stem: p for p in sorted(d.glob("*.png"))}
    return out


def _mask_rects(manifest: Manifest, screen_id: str, width_px: int) -> list[tuple[int, int, int, int]]:
    s = manifest.screen(screen_id)
    if s is None or not s.masks or not manifest.device_w:
        return []
    k = width_px / manifest.device_w
    rects = []
    for name in s.masks:
        m = manifest.masks[name]
        rects.append((int(m.x * k), int(m.y * k), max(int((m.x + m.w) * k) - 1, int(m.x * k)), max(int((m.y + m.h) * k) - 1, int(m.y * k))))
    return rects


def compare_images(base_path: pathlib.Path, cur_path: pathlib.Path,
                   rects_for: Callable[[int], list[tuple[int, int, int, int]]], tolerance: int):
    """(percent of pixels that differ, base, current, difference-mask) after the same masks are blacked out of both.
    `rects_for(width_px)` gives the mask rectangles in pixels. A size change is 100 percent with no mask."""
    Image, ImageChops, ImageDraw = _pillow()
    with Image.open(base_path) as b0, Image.open(cur_path) as c0:
        base, cur = b0.convert("RGB"), c0.convert("RGB")
    if base.size != cur.size:
        return 100.0, base, cur, None
    rects = rects_for(cur.width)
    for im in (base, cur):
        d = ImageDraw.Draw(im)
        for r in rects:
            d.rectangle(r, fill=(0, 0, 0))
    diff = ImageChops.difference(base, cur)
    r, g, b = diff.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = mx.point(lambda v: 255 if v > tolerance else 0)
    changed = mask.histogram()[255]
    return 100.0 * changed / (cur.width * cur.height), base, cur, mask


def side_by_side(base, cur, mask, label: str, dest: pathlib.Path) -> None:
    """baseline | current | changed pixels in red over a dimmed current, written to dest."""
    Image, ImageChops, ImageDraw = _pillow()
    gap, head = 12, 18
    w, h = cur.size
    if mask is not None:
        dim = Image.blend(cur, Image.new("RGB", cur.size, (255, 255, 255)), 0.7)
        red = Image.new("RGB", cur.size, (230, 30, 30))
        third = Image.composite(red, dim, mask)
    else:
        third = Image.new("RGB", cur.size, (230, 30, 30))
    sheet = Image.new("RGB", (base.width + w + w + 2 * gap, max(base.height, h) + head), (128, 128, 128))
    sheet.paste(base, (0, head))
    sheet.paste(cur, (base.width + gap, head))
    sheet.paste(third, (base.width + w + 2 * gap, head))
    d = ImageDraw.Draw(sheet)
    d.text((2, 2), f"{label}   baseline | current | changed", fill=(255, 255, 255))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)


def diff_repo(repo: pathlib.Path, manifest: Manifest) -> DiffReport:
    _pillow()
    shots = pathlib.Path(repo) / SHOTS_REL
    cur_all, base_all = _variants(shots), _variants(shots / "baseline")
    diff_dir = shots / "diff"
    shutil.rmtree(diff_dir, ignore_errors=True)       # generated output of an earlier diff
    report = DiffReport()
    run = _read_json(shots / RUN_JSON) or {}
    report.unstable = list(run.get("unstable") or [])
    for variant in sorted(set(cur_all) | set(base_all)):
        cur, base = cur_all.get(variant, {}), base_all.get(variant, {})
        for sid in sorted(set(cur) | set(base)):
            if sid not in base:
                report.new.append((variant, sid))
                continue
            if sid not in cur:
                report.missing.append((variant, sid))
                continue
            scr = manifest.screen(sid)
            threshold = scr.threshold if scr else manifest.threshold
            pct, b, c, mask = compare_images(base[sid], cur[sid], lambda w, sid=sid: _mask_rects(manifest, sid, w),
                                             manifest.tolerance)
            report.compared += 1
            if pct > threshold:
                dest = diff_dir / variant / f"{sid}.png"
                side_by_side(b, c, mask, f"{variant}/{sid}", dest)
                report.changed.append(ScreenDiff(variant, sid, round(pct, 3), threshold,
                                                 "size changed" if mask is None else "", str(dest.relative_to(repo))))
            else:
                report.unchanged += 1
    return report


def render_diff(report: DiffReport, manifest: Manifest) -> str:
    L: list[str] = []
    if report.changed:
        L.append(f"changed ({len(report.changed)}):")
        for d in report.changed:
            extra = f"  {d.reason}" if d.reason else ""
            L.append(f"  {d.variant}/{d.screen}  {d.percent:.3f}% of pixels (limit {d.threshold:g}%){extra}  -> {d.image}")
    if report.new:
        L.append(f"new, no baseline ({len(report.new)}):")
        L.extend(f"  {v}/{s}" for v, s in report.new)
    if report.missing:
        L.append(f"missing, in the baseline but not in the run ({len(report.missing)}):")
        L.extend(f"  {v}/{s}" for v, s in report.missing)
    if report.unstable:
        L.append(f"unstable, the runs of one build disagree ({len(report.unstable)}):")
        L.extend(f"  {k}" for k in report.unstable)
    n_screens = len(manifest.screens)
    n_var = len(manifest.variants())
    L.append(f"{report.compared} compared, {report.unchanged} unchanged, {len(report.changed)} changed, "
             f"{len(report.new)} new, {len(report.missing)} missing, {len(report.unstable)} unstable")
    if report.dirty:
        L.append(f"PR text: \"diff on {len(report.changed) + len(report.new) + len(report.missing)} captures of the "
                 f"manifest's screens ({n_screens} screens x {n_var} variants); side-by-sides in {SHOTS_REL}/diff/\"")
        L.append("next: fix the code, or accept the new look with `teyla ux accept --yes` (the owner runs that)")
    else:
        L.append(f"PR text: \"no diff on the manifest's screens ({n_screens} screens x {n_var} variants)\" "
                 "(a screen the manifest does not list was not checked)")
    return "\n".join(L)


# --- teyla ux accept -----------------------------------------------------------------------------

def _who() -> str:
    try:
        r = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


class AcceptRefused(Exception):
    pass


def accept(repo: pathlib.Path, *, allow_unstable: bool = False, who: str | None = None,
           now: dt.datetime | None = None) -> dict:
    """Replace design/shots/baseline/ with the run in design/shots/<variant>/ and record who and when."""
    shots = pathlib.Path(repo) / SHOTS_REL
    run = _read_json(shots / RUN_JSON)
    if not isinstance(run, dict):
        raise AcceptRefused(f"no {SHOTS_REL}/{RUN_JSON}: run `teyla ux shots` first")
    if run.get("status") != "complete":
        raise AcceptRefused(f"the last run is {run.get('status')!r}, not complete: rerun `teyla ux shots`")
    if run.get("unstable") and not allow_unstable:
        raise AcceptRefused(f"{len(run['unstable'])} screen(s) are unstable (the runs of one build disagree), e.g. "
                            f"{run['unstable'][0]}: fix the flake, or pass --allow-unstable")
    variants = _variants(shots)
    n = sum(len(v) for v in variants.values())
    if not n:
        raise AcceptRefused(f"no screenshots in {SHOTS_REL}/<variant>/")
    new_dir, old_dir, final = shots / "baseline.new", shots / "baseline.old", shots / "baseline"
    shutil.rmtree(new_dir, ignore_errors=True)
    shutil.rmtree(old_dir, ignore_errors=True)
    for variant, screens in variants.items():
        (new_dir / variant).mkdir(parents=True)
        for sid, p in screens.items():
            shutil.copyfile(p, new_dir / variant / f"{sid}.png")
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"accepted_by": who or _who(), "accepted_at": stamp, "run_started": run.get("started"),
              "run_commit": run.get("commit"), "manifest_sha256": run.get("manifest_sha256"),
              "variants": sorted(variants), "screens": n, "unstable_accepted": list(run.get("unstable") or [])}
    (new_dir / ACCEPTED_JSON).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    if final.exists():
        final.rename(old_dir)
    new_dir.rename(final)
    shutil.rmtree(old_dir, ignore_errors=True)
    return record


# --- the CLI -------------------------------------------------------------------------------------

def add_arguments(q) -> None:
    """The flags of shots, diff and accept, on the `ux` subparser."""
    q.add_argument("--check-manifest", action="store_true", help="shots: validate design/tour.yaml and stop")
    q.add_argument("--dry", action="store_true", help="shots: print the commands a run would start, run nothing")
    q.add_argument("--runs", type=int, default=0, help="shots: runs of the tour (default: the manifest's, 3)")
    q.add_argument("--budget-min", type=float, default=BUDGET_MIN, help="shots: minutes before the run is cut (default 9)")
    q.add_argument("--yes", action="store_true", help="accept: make the run the baseline (without it nothing changes)")
    q.add_argument("--allow-unstable", action="store_true", help="accept: take a run that has unstable screens")


def _repo(args) -> pathlib.Path | None:
    from . import docs_check
    if args.all:
        print(f"teyla ux {args.action}: --all is for `ux check`; name one repo", file=sys.stderr)
        return None
    if len(args.repos) > 1:
        print(f"teyla ux {args.action}: one repo at a time", file=sys.stderr)
        return None
    try:
        return docs_check.resolve(args.repos, False)[0]
    except FileNotFoundError as e:
        print(f"teyla ux {args.action}: {e}", file=sys.stderr)
        return None


def _load(repo: pathlib.Path, action: str) -> Manifest | None:
    try:
        return load_manifest(repo)
    except ManifestError as e:
        print(f"teyla ux {action}: the manifest is not valid ({len(e.errors)} problem(s)):", file=sys.stderr)
        for m in e.errors:
            print(f"  - {m}", file=sys.stderr)
        return None


def summary(m: Manifest) -> str:
    return (f"{MANIFEST_REL}: ok\n  {len(m.screens)} screen(s) from {len({s.route for s in m.screens})} route(s); "
            f"{len(m.languages)} language(s) x {len(m.looks)} look(s) = {len(m.variants())} variant(s); "
            f"{len(m.screens) * len(m.variants())} capture(s) per run, {m.runs} run(s)\n"
            f"  fixed date {m.fixed_date}, seed {m.seed}, network {'stubbed' if m.network_stub else 'live'}, "
            f"{len(m.masks)} mask(s), default threshold {m.threshold:g}%")


def cmd(args, runner: Runner | None = None) -> int:
    repo = _repo(args)
    if repo is None:
        return 2
    action = args.action
    manifest = _load(repo, action)
    if manifest is None:
        return 1 if (action == "shots" and args.check_manifest) else 2

    if action == "accept":
        if not args.yes:
            print("teyla ux accept: this replaces the baseline with the current run. It is the owner's call: "
                  "review `teyla ux diff` first, then run it again with --yes.", file=sys.stderr)
            return 2
        try:
            rec = accept(repo, allow_unstable=args.allow_unstable)
        except AcceptRefused as e:
            print(f"teyla ux accept: {e}", file=sys.stderr)
            return 2
        print(f"baseline accepted: {rec['screens']} screen(s) in {len(rec['variants'])} variant(s) by {rec['accepted_by']} "
              f"at {rec['accepted_at']} ({SHOTS_REL}/baseline/{ACCEPTED_JSON}). Commit it.")
        return 0

    if action == "diff":
        try:
            report = diff_repo(repo, manifest)
        except PillowMissing as e:
            print(f"teyla ux diff: {e}", file=sys.stderr)
            return 2
        print(render_diff(report, manifest))
        return 1 if report.dirty else 0

    # shots
    if args.check_manifest:
        print(summary(manifest))
        return 0
    try:
        cfg = load_tour_config(repo, manifest=manifest)
    except ConfigError as e:
        print(f"teyla ux shots: {e}", file=sys.stderr)
        return 2
    runs = args.runs or manifest.runs
    if args.dry:
        d = "<derived-data>"
        print(summary(manifest))
        print("would start, in order:")
        print("  " + " ".join(teyla_cmd() + ["load", "--admit", "build", "--cwd", str(repo)]))
        print("  " + " ".join(teyla_cmd() + ["load", "--wait", "--kind", "sim", "--cwd", str(repo)]))
        print("  xcrun simctl boot <udid>      (only when no simulator named %r is booted; shut down at the end)" % cfg.device)
        print("  " + " ".join(xcodebuild_build_argv(cfg, "<udid>", d)))
        for n in range(1, runs + 1):
            print("  " + " ".join(f"{a}" if " " not in a else f"'{a}'" for a in xcodebuild_test_argv(cfg, "<udid>", d, f"<tmp>/run-{n}.xcresult")))
            print("  " + " ".join(export_argv(f"<tmp>/run-{n}.xcresult", f"<tmp>/attachments-{n}")))
        return 0
    runner = runner or Runner()
    try:
        doc = run_shots(repo, manifest, cfg, runner, runs=runs, budget_s=args.budget_min * 60)
    except GuardRefused as e:
        print(f"teyla ux shots: the machine guard did not let the run start.\n{e}\n"
              f"Wait for a slot with: teyla load --wait --kind build && teyla ux shots {repo.name}", file=sys.stderr)
        return 2
    except (SimulatorError, TourFailed) as e:
        print(f"teyla ux shots: {e}", file=sys.stderr)
        return 3
    print(render_run(doc))
    bad = doc["status"] != "complete" or doc["unstable"] or doc["uncaptured"] or doc["errors"]
    if args.strict and (doc["counts"]["findings"] or doc["counts"]["audit_issues"]):
        bad = True
    return 1 if bad else 0
