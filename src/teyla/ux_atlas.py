"""`teyla ux registry check` and `teyla ux atlas` — every screen of a product, with the proof that it was drawn.

    teyla ux registry check [repo] [--json]
    teyla ux atlas [repo] [--out DIR] [--lang L] [--open]

The screen registry is `design/screens/<id>.yaml` (format: docs/ATLAS.md). The tour manifest
`design/tour.yaml` says which routes the product captures; the captures are `design/shots/<variant>/<screen>.png`
and `design/shots/baseline/<variant>/<screen>.png` (docs/MATRIX.md). A screen is expected on each platform it
lists (default: ios). It is captured on a platform when a screenshot of its route exists there.

`check` validates the entries and prints expected against captured per platform and look. It exits 1 on an
invalid entry only; a missing capture, a missing layout contract or an unknown source file is a warning.
`atlas` writes one self-contained `atlas.html` (inline CSS and JS, no CDN) plus the screenshots it shows, in
`img/` next to it. Nothing here touches the network.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import pathlib
import re
import shutil
import sys
import webbrowser

from . import taste

SCREENS_REL = "design/screens"
SHOTS_REL = "design/shots"
FEATURES_REL = "docs/FEATURES.md"
PLATFORMS = ("ios", "ipados", "macos", "web", "android")
LOOKS = ("light", "dark", "large")
SIZE_CLASSES = ("compact", "regular", "wide")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
KNOWN_KEYS = {"id", "title", "parent", "links", "level", "platforms", "route", "layout", "features", "source",
              "job", "primary_action", "states", "string_keys", "catalog"}
LINK_KEYS = {"to", "via", "tested"}
LAYOUT_KEYS = set(SIZE_CLASSES) | {"assert"}
CODE_SUFFIXES = {".swift", ".kt", ".java", ".m", ".py", ".ts", ".tsx", ".js", ".jsx", ".dart"}
SKIP_DIRS = {".git", "node_modules", "build", "DerivedData", ".build", "Pods", ".venv", "dist", "shots", "atlas"}
MAX_SCAN_BYTES = 2_000_000


# --- the registry ---------------------------------------------------------------------------------

class Registry:
    def __init__(self, repo: pathlib.Path):
        self.repo = repo
        self.entries: list[dict] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.tour_routes: dict[str, list[str]] = {}      # route id -> states, from design/tour.yaml
        self.looks: list[str] = list(LOOKS)
        self.languages: list[str] = []
        self.has_tour = False
        self.features: list[dict] = []
        self.has_features = False

    def by_id(self) -> dict[str, dict]:
        return {e["id"]: e for e in self.entries}


def _str_list(v, where: str, key: str, errs: list[str]) -> list[str]:
    if v is None:
        return []
    items = v if isinstance(v, list) else [v]
    out = []
    for i in items:
        if isinstance(i, (dict, list)) or i is None or isinstance(i, bool):
            errs.append(f"{where}: `{key}` must hold plain text items")
            return out
        out.append(str(i))
    return out


def _entry(path: pathlib.Path, errs: list[str], warns: list[str]) -> dict | None:
    where = f"{SCREENS_REL}/{path.name}"
    try:
        raw = taste.load_file(path)
    except ValueError as e:
        errs.append(f"{where}: cannot read: {str(e).split(': ', 1)[-1]}")
        return None
    e: dict = {"file": path.name, "id": path.stem}
    if "id" in raw:
        if not isinstance(raw["id"], str) or not ID_RE.match(raw["id"]):
            errs.append(f"{where}: `id` must be lowercase letters, digits, dots, dashes or underscores")
        else:
            e["id"] = raw["id"]
    elif not ID_RE.match(path.stem):
        errs.append(f"{where}: the file name is not a valid screen id (lowercase letters, digits, dots, dashes, underscores); "
                    "rename the file or set `id`")
    for k in raw:
        if k not in KNOWN_KEYS:
            warns.append(f"{where}: unknown key `{k}` (ignored)")
    t = raw.get("title")
    e["title"] = str(t) if isinstance(t, (str, int)) and not isinstance(t, bool) else ""
    if t is not None and not e["title"]:
        errs.append(f"{where}: `title` must be text")
    parent = raw.get("parent")
    if parent is not None and not isinstance(parent, str):
        errs.append(f"{where}: `parent` must be a screen id")
        parent = None
    e["parent"] = parent or None
    lvl = raw.get("level")
    if lvl is not None and (isinstance(lvl, bool) or not isinstance(lvl, int) or lvl < 1):
        errs.append(f"{where}: `level` must be a whole number from 1 (1 = a tab root)")
        lvl = None
    e["level"] = lvl
    plats = _str_list(raw.get("platforms"), where, "platforms", errs)
    for p in plats:
        if p not in PLATFORMS:
            errs.append(f"{where}: unknown platform {p!r}; use one of {', '.join(PLATFORMS)}")
    e["platforms"] = [p for p in plats if p in PLATFORMS] or (["ios"] if not plats else [])
    route = raw.get("route")
    if route is not None and not isinstance(route, str):
        errs.append(f"{where}: `route` must be a tour route id")
        route = None
    e["route"] = route or None
    layout = raw.get("layout")
    e["layout"] = {}
    if layout is not None:
        if not isinstance(layout, dict):
            errs.append(f"{where}: `layout` must be a map with compact, regular, wide and optional assert")
        else:
            for k, v in layout.items():
                if k not in LAYOUT_KEYS:
                    errs.append(f"{where}: unknown layout key `{k}`; use compact, regular, wide or assert")
                elif v is None or isinstance(v, (dict, list)):
                    errs.append(f"{where}: layout `{k}` must be one sentence")
                else:
                    e["layout"][k] = str(v)
    links = raw.get("links")
    e["links"] = []
    if links is not None:
        if not isinstance(links, list):
            errs.append(f"{where}: `links` must be a list of {{to, via, tested}}")
        else:
            for n, ln in enumerate(links, 1):
                if not isinstance(ln, dict) or not isinstance(ln.get("to"), str):
                    errs.append(f"{where}: link {n} needs a `to` screen id")
                    continue
                bad = set(ln) - LINK_KEYS
                if bad:
                    errs.append(f"{where}: link {n} has unknown key(s) {', '.join(sorted(bad))}")
                tested = ln.get("tested", False)
                if not isinstance(tested, bool):
                    errs.append(f"{where}: link {n} `tested` must be true or false")
                    tested = False
                e["links"].append({"to": ln["to"], "via": str(ln.get("via") or ""), "tested": tested})
    e["features"] = _str_list(raw.get("features"), where, "features", errs)
    e["source"] = _str_list(raw.get("source"), where, "source", errs)
    e["job"] = str(raw["job"]) if isinstance(raw.get("job"), str) else ""
    e["primary_action"] = str(raw["primary_action"]) if isinstance(raw.get("primary_action"), str) else ""
    e["states"] = _str_list(raw.get("states"), where, "states", errs)
    return e


def load_registry(repo: pathlib.Path) -> Registry:
    repo = pathlib.Path(repo)
    reg = Registry(repo)
    d = repo / SCREENS_REL
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        e = _entry(p, reg.errors, reg.warnings)
        if e:
            reg.entries.append(e)
    _read_tour(reg)
    reg.features = parse_features(repo / FEATURES_REL)
    reg.has_features = (repo / FEATURES_REL).is_file()
    _validate(reg)
    return reg


def _read_tour(reg: Registry) -> None:
    from . import ux_shots
    if not (reg.repo / ux_shots.MANIFEST_REL).is_file():
        return
    try:
        m = ux_shots.load_manifest(reg.repo)
    except ux_shots.ManifestError as e:
        reg.warnings.append(f"{ux_shots.MANIFEST_REL}: not valid, so routes are not checked ({e.errors[0]})")
        return
    reg.has_tour = True
    reg.looks = list(m.looks)
    reg.languages = list(m.languages)
    for s in m.screens:
        reg.tour_routes.setdefault(s.route, []).append(s.state)


def _validate(reg: Registry) -> None:
    errs, warns = reg.errors, reg.warnings
    seen: dict[str, str] = {}
    for e in reg.entries:
        if e["id"] in seen:
            errs.append(f"{SCREENS_REL}/{e['file']}: duplicate screen id {e['id']!r} (also in {seen[e['id']]})")
        seen.setdefault(e["id"], e["file"])
    ids = reg.by_id()
    for e in reg.entries:
        where = f"{SCREENS_REL}/{e['file']}"
        p = e["parent"]
        if p is not None:
            if p == e["id"]:
                errs.append(f"{where}: a screen cannot be its own parent")
            elif p not in ids:
                errs.append(f"{where}: unknown parent {p!r}")
        for ln in e["links"]:
            if ln["to"] == e["id"]:
                errs.append(f"{where}: link to itself")
            elif ln["to"] not in ids:
                errs.append(f"{where}: link to unknown screen {ln['to']!r}")
        if e["route"] and reg.has_tour and e["route"] not in reg.tour_routes:
            errs.append(f"{where}: route {e['route']!r} is not in design/tour.yaml")
    for e in reg.entries:                                # cycles
        seen_ids, cur = {e["id"]}, e["parent"]
        while cur in ids:
            if cur in seen_ids:
                errs.append(f"{SCREENS_REL}/{e['file']}: the parent chain loops through {cur!r}")
                break
            seen_ids.add(cur)
            cur = ids[cur]["parent"]
    for e in reg.entries:
        where = f"{SCREENS_REL}/{e['file']}"
        if e["parent"] is None and e["level"] is None:
            warns.append(f"{where}: no `parent` and no `level`; it counts as level 1")
        elif e["parent"] in ids and e["level"] is not None and ids[e["parent"]]["level"] is not None \
                and e["level"] != ids[e["parent"]]["level"] + 1:
            warns.append(f"{where}: level {e['level']} under a level {ids[e['parent']]['level']} parent")
        missing = [s for s in SIZE_CLASSES if not e["layout"].get(s)]
        if missing:
            warns.append(f"{where}: no layout contract for {', '.join(missing)} (decision S18)")
        for src in e["source"]:
            if not (reg.repo / src).exists():
                warns.append(f"{where}: source file {src!r} does not exist")
        if e["route"] is None:
            warns.append(f"{where}: no `route`, so the screen cannot be captured")
        if reg.has_features:
            for ref in e["features"]:
                if not any(_match_feature(reg.features, ref)):
                    warns.append(f"{where}: feature {ref!r} matches no section or anchor in {FEATURES_REL}")
    wanted = {e["layout"]["assert"] for e in reg.entries if e["layout"].get("assert")}
    if wanted:
        found = scan_for(reg.repo, wanted)
        for e in reg.entries:
            a = e["layout"].get("assert")
            e["assert_found"] = (a in found) if a else None
            if a and a not in found:
                warns.append(f"{SCREENS_REL}/{e['file']}: the test {a!r} named in `layout.assert` is not in the code")
    for e in reg.entries:
        e.setdefault("assert_found", None)
    if reg.has_tour:
        used = {e["route"] for e in reg.entries if e["route"]}
        for r in sorted(set(reg.tour_routes) - used):
            warns.append(f"design/tour.yaml: route {r!r} belongs to no screen in the registry")


def scan_for(repo: pathlib.Path, needles: set[str]) -> set[str]:
    """Which of `needles` appear as text in the product's code (a test name, an identifier)."""
    found: set[str] = set()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if pathlib.Path(f).suffix not in CODE_SUFFIXES:
                continue
            p = pathlib.Path(root) / f
            try:
                if p.stat().st_size > MAX_SCAN_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found |= {n for n in needles if n in text}
            if found == needles:
                return found
    return found


# --- the feature list -----------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "")).strip().casefold()


def parse_features(path: pathlib.Path) -> list[dict]:
    """Sections of FEATURES.md that own a table of features: [{surface, name, rows: [{text, anchor}]}]."""
    if not path.is_file():
        return []
    surface, name, cols = "", "", None
    out: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^(#{2,3})\s+(.*?)\s*$", line)
        if m:
            if len(m.group(1)) == 2:
                surface = m.group(2)
            name, cols, cur = m.group(2), None, None
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cols is None:
            if cells and cells[0].casefold() == "feature":
                cols = [c.casefold() for c in cells]
                cur = {"surface": surface, "name": name or surface, "rows": []}
                out.append(cur)
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue
        if cur is None or not cells or not cells[0]:
            continue
        anchor = next((cells[i] for i, c in enumerate(cols) if c.startswith("anchor") and i < len(cells)), "")
        cur["rows"].append({"text": cells[0], "anchor": anchor})
    return [s for s in out if s["rows"]]


def _match_feature(sections: list[dict], ref: str) -> tuple[list[int], list[tuple[int, int]]]:
    """Section indexes the reference names, and (section, row) pairs when it names an anchor."""
    r = _norm(ref)
    secs, rows = [], []
    for i, s in enumerate(sections):
        if r in (_norm(s["name"]), _norm(f"{s['surface']} / {s['name']}"), _norm(f"{s['surface']}/{s['name']}")):
            secs.append(i)
    if not secs and r:
        for i, s in enumerate(sections):
            for j, row in enumerate(s["rows"]):
                if r == _norm(row["text"]) or (row["anchor"] and r in _norm(row["anchor"])):
                    rows.append((i, j))
    return secs, rows


def feature_coverage(reg: Registry) -> dict:
    """Which sections and rows of the feature list a screen names, and which sections no screen names."""
    mapped: set[tuple[int, int]] = set()
    per_screen: dict[str, list[dict]] = {}
    for e in reg.entries:
        out = []
        for ref in e["features"]:
            secs, rows = _match_feature(reg.features, ref)
            for i in secs:
                mapped |= {(i, j) for j in range(len(reg.features[i]["rows"]))}
            mapped |= set(rows)
            if secs:
                for i in secs:
                    s = reg.features[i]
                    out.append({"ref": ref, "section": s["name"], "surface": s["surface"], "rows": len(s["rows"]), "matched": True})
            elif rows:
                for i, j in rows:
                    s = reg.features[i]
                    out.append({"ref": ref, "section": s["name"], "surface": s["surface"], "rows": 1, "matched": True})
            else:
                out.append({"ref": ref, "section": "", "surface": "", "rows": 0, "matched": False})
        per_screen[e["id"]] = out
    mapped_secs = {i for i, _ in mapped}
    unmapped = [{"surface": s["surface"], "name": s["name"], "rows": len(s["rows"])}
                for i, s in enumerate(reg.features) if i not in mapped_secs]
    total_rows = sum(len(s["rows"]) for s in reg.features)
    return {"sections": len(reg.features), "sections_mapped": len(mapped_secs), "rows": total_rows,
            "rows_mapped": len(mapped), "unmapped": unmapped, "per_screen": per_screen}


# --- captures and coverage ------------------------------------------------------------------------

def scan_captures(repo: pathlib.Path) -> list[dict]:
    """Every screenshot on disk: {platform, lang, look, route, state, path, kind} (kind: shots or baseline).

    ios captures live in design/shots/<variant>/ (variant = <lang>-<look>); another platform's in
    design/shots/<platform>/<variant>/. The accepted baseline has the same shape under baseline/."""
    root = pathlib.Path(repo) / SHOTS_REL
    out: list[dict] = []

    def variant(d: pathlib.Path):
        m = re.fullmatch(r"(.+)-(light|dark|large)", d.name)
        return (m.group(1), m.group(2)) if m else None

    def walk(base: pathlib.Path, kind: str) -> None:
        if not base.is_dir():
            return
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            if variant(d):
                groups = [("ios", d)]
            elif d.name in PLATFORMS:
                groups = [(d.name, s) for s in sorted(d.iterdir()) if s.is_dir() and variant(s)]
            else:
                continue
            for plat, vd in groups:
                lang, look = variant(vd)
                for p in sorted(vd.glob("*.png")):
                    route, _, state = p.stem.partition(".")
                    out.append({"platform": plat, "lang": lang, "look": look, "route": route, "state": state,
                                "path": p, "kind": kind})

    walk(root, "shots")
    walk(root / "baseline", "baseline")
    return out


def coverage(reg: Registry, caps: list[dict]) -> dict:
    """The maths. A pair is a screen on one of its platforms; it is captured when a screenshot of its route exists."""
    have: dict[tuple[str, str], set[str]] = {}
    for c in caps:
        have.setdefault((c["platform"], c["route"]), set()).add(c["look"])
    looks = list(reg.looks)
    plat: dict[str, dict] = {}
    screens: dict[str, dict] = {}
    levels = level_map(reg)
    by_level: dict[int, list[int]] = {}
    for e in reg.entries:
        per = {}
        for p in e["platforms"]:
            got = have.get((p, e["route"]), set()) if e["route"] else set()
            per[p] = sorted(got, key=lambda x: (LOOKS.index(x) if x in LOOKS else 9))
            row = plat.setdefault(p, {"expected": 0, "captured": 0, "looks": {l: 0 for l in looks}})
            row["expected"] += 1
            row["captured"] += 1 if got else 0
            for l in looks:
                row["looks"][l] += 1 if l in got else 0
            lv = by_level.setdefault(levels[e["id"]], [0, 0])
            lv[0] += 1
            lv[1] += 1 if got else 0
        screens[e["id"]] = {"platforms": per, "captured": any(per.values()),
                            "complete": bool(per) and all(set(looks) <= set(v) for v in per.values())}
    expected = sum(r["expected"] for r in plat.values())
    captured = sum(r["captured"] for r in plat.values())
    return {"expected": expected, "captured": captured,
            "percent": round(100 * captured / expected) if expected else 0,
            "platforms": plat, "looks": looks, "screens": screens,
            "levels": {str(k): {"expected": v[0], "captured": v[1]} for k, v in sorted(by_level.items())}}


def level_map(reg: Registry) -> dict[str, int]:
    ids = reg.by_id()
    memo: dict[str, int] = {}

    def lv(i: str, trail: tuple = ()) -> int:
        if i in memo:
            return memo[i]
        e = ids[i]
        if e["level"] is not None:
            r = e["level"]
        elif e["parent"] in ids and i not in trail and e["parent"] not in trail:
            r = lv(e["parent"], trail + (i,)) + 1
        else:
            r = 1
        memo[i] = r
        return r

    return {i: lv(i) for i in ids}


# --- the check command ----------------------------------------------------------------------------

def report(repo: pathlib.Path) -> dict:
    reg = load_registry(repo)
    caps = scan_captures(repo)
    cov = coverage(reg, caps)
    return {"repo": pathlib.Path(repo).name, "screens": len(reg.entries), "errors": reg.errors,
            "warnings": reg.warnings, "coverage": {k: cov[k] for k in ("expected", "captured", "percent", "platforms", "looks", "levels")},
            "uncaptured": [i for i, s in cov["screens"].items() if not s["captured"]]}


def render_report(r: dict) -> str:
    L = [f"{r['repo']}: {r['screens']} screen(s) in {SCREENS_REL}, {len(r['errors'])} error(s), {len(r['warnings'])} warning(s)"]
    for m in r["errors"]:
        L.append(f"  ERROR {m}")
    for m in r["warnings"]:
        L.append(f"  warn  {m}")
    c = r["coverage"]
    L.append(f"captured / expected (screens x platforms): {c['captured']} / {c['expected']} ({c['percent']}%)")
    for p, row in c["platforms"].items():
        looks = "  ".join(f"{l} {row['looks'][l]}/{row['expected']}" for l in c["looks"])
        L.append(f"  {p:<8} {row['captured']}/{row['expected']}   {looks}")
    for lv, row in c["levels"].items():
        L.append(f"  level {lv}: {row['captured']}/{row['expected']}")
    if r["uncaptured"]:
        L.append("not captured: " + ", ".join(r["uncaptured"]))
    return "\n".join(L)


# --- the atlas ------------------------------------------------------------------------------------

NODE_W, NODE_H, COL_GAP, ROW_GAP = 168, 46, 70, 18


def layout_nodes(reg: Registry) -> tuple[dict[str, dict], list[dict]]:
    """A tidy tree: x by level, y by leaf rows with a parent centred over its children. Plus the edges."""
    ids = reg.by_id()
    levels = level_map(reg)
    kids: dict[str | None, list[str]] = {}
    for e in reg.entries:
        p = e["parent"] if e["parent"] in ids and e["parent"] != e["id"] else None
        kids.setdefault(p, []).append(e["id"])
    pos: dict[str, dict] = {}
    row = [0.0]
    placed: set[str] = set()

    def place(i: str) -> float:
        placed.add(i)
        ch = [c for c in kids.get(i, []) if c not in placed]
        if not ch:
            y = row[0]
            row[0] += 1
        else:
            ys = [place(c) for c in ch]
            y = (ys[0] + ys[-1]) / 2
        pos[i] = {"x": (levels[i] - 1) * (NODE_W + COL_GAP), "y": y * (NODE_H + ROW_GAP)}
        return y

    for r in kids.get(None, []):
        if r not in placed:
            place(r)
    for e in reg.entries:                                    # a parent loop leaves nodes unplaced
        if e["id"] not in placed:
            place(e["id"])
    edges, linked = [], set()
    for e in reg.entries:
        for ln in e["links"]:
            if ln["to"] in ids and ln["to"] != e["id"]:
                edges.append({"from": e["id"], "to": ln["to"], "kind": "link", "tested": ln["tested"], "via": ln["via"]})
                linked.add((e["id"], ln["to"]))
    for e in reg.entries:
        p = e["parent"]
        if p in ids and p != e["id"] and (p, e["id"]) not in linked:
            edges.append({"from": p, "to": e["id"], "kind": "parent", "tested": False, "via": ""})
    return pos, edges


def _pick(caps: list[dict], platform: str, route: str, lang: str | None) -> list[dict]:
    """The captures of a route on a platform, one per (look, state): the chosen language, current over baseline."""
    mine = [c for c in caps if c["platform"] == platform and c["route"] == route]
    langs = sorted({c["lang"] for c in mine})
    use = lang if lang in langs else (langs[0] if langs else None)
    best: dict[tuple, dict] = {}
    for c in mine:
        if c["lang"] != use:
            continue
        k = (c["look"], c["state"])
        if k not in best or (best[k]["kind"] == "baseline" and c["kind"] == "shots"):
            best[k] = c
    return sorted(best.values(), key=lambda c: (LOOKS.index(c["look"]), c["state"] != "loaded", c["state"]))


def build_data(repo: pathlib.Path, out: pathlib.Path | None, lang: str | None = None,
               today: str | None = None) -> tuple[dict, Registry]:
    """The atlas as plain data. With `out`, the screenshots it shows are copied to out/img/."""
    reg = load_registry(repo)
    caps = scan_captures(repo)
    cov = coverage(reg, caps)
    feat = feature_coverage(reg)
    lang = lang or (reg.languages[0] if reg.languages else None)
    pos, edges = layout_nodes(reg)
    levels = level_map(reg)
    ids = reg.by_id()
    copied: dict[str, str] = {}
    screens = []
    for e in reg.entries:
        imgs = []
        for p in e["platforms"]:
            for c in (_pick(caps, p, e["route"], lang) if e["route"] else []):
                rel = f"img/{p}/{c['look']}/{c['route']}.{c['state'] or 'screen'}.png"
                if out is not None and rel not in copied:
                    dest = out / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(c["path"], dest)
                    copied[rel] = c["kind"]
                imgs.append({"platform": p, "look": c["look"], "state": c["state"], "src": rel, "kind": c["kind"], "lang": c["lang"]})
        sc = cov["screens"][e["id"]]
        screens.append({
            "id": e["id"], "title": e["title"] or e["id"], "level": levels[e["id"]], "parent": e["parent"],
            "platforms": e["platforms"], "route": e["route"], "job": e["job"], "primary_action": e["primary_action"],
            "states": e["states"], "layout": {k: e["layout"].get(k, "") for k in LAYOUT_KEYS},
            "assert_found": e["assert_found"], "source": e["source"], "features": feat["per_screen"][e["id"]],
            "links": e["links"], "linked_from": sorted({o["id"] for o in reg.entries for ln in o["links"] if ln["to"] == e["id"]}),
            "captured": sc["captured"], "complete": sc["complete"], "got": sc["platforms"], "images": imgs,
            "x": pos[e["id"]]["x"], "y": pos[e["id"]]["y"]})
    registered = {e["route"] for e in reg.entries if e["route"]}
    stray = sorted({(c["platform"], c["route"]) for c in caps if c["route"] not in registered})
    data = {"repo": pathlib.Path(repo).name, "generated": today or _dt.date.today().isoformat(), "lang": lang,
            "looks": cov["looks"], "platforms": sorted({p for e in reg.entries for p in e["platforms"]}, key=PLATFORMS.index),
            "coverage": {k: cov[k] for k in ("expected", "captured", "percent", "platforms", "levels")},
            "features": {k: feat[k] for k in ("sections", "sections_mapped", "rows", "rows_mapped", "unmapped")},
            "has_features": reg.has_features, "node": {"w": NODE_W, "h": NODE_H},
            "stray": [{"platform": p, "route": r} for p, r in stray],
            "errors": reg.errors, "warnings": reg.warnings, "screens": screens, "edges": edges}
    return data, reg


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _grid(data: dict) -> str:
    by_level: dict[int, list[dict]] = {}
    ids = {s["id"]: s for s in data["screens"]}
    for s in data["screens"]:
        by_level.setdefault(s["level"], []).append(s)
    parts = []
    for lv in sorted(by_level):
        label = "Level 1 · tab roots" if lv == 1 else f"Level {lv}"
        parts.append(f'<section class="lvl"><h2>{_e(label)} <small>{len(by_level[lv])}</small></h2><div class="cards">')
        for s in sorted(by_level[lv], key=lambda x: (x["parent"] or "", x["id"])):
            parent = ids.get(s["parent"])
            rows = []
            for p in s["platforms"]:
                cells = []
                for look in data["looks"]:
                    im = next((i for i in s["images"] if i["platform"] == p and i["look"] == look), None)
                    if im:
                        cells.append(f'<figure><img loading="lazy" src="{_e(im["src"])}" alt="{_e(s["title"])} {_e(p)} {_e(look)}">'
                                     f'<figcaption>{_e(look)}</figcaption></figure>')
                    else:
                        cells.append(f'<figure class="none"><div>not captured</div><figcaption>{_e(look)}</figcaption></figure>')
                rows.append(f'<div class="plat" data-platform="{_e(p)}"><span class="pl">{_e(p)}</span>{"".join(cells)}</div>')
            state = "captured" if s["captured"] else "missing"
            sub = f'in {_e(parent["title"])}' if parent else ("no route" if not s["route"] else f'level {s["level"]}')
            parts.append(f'<article class="card {state}" data-screen="{_e(s["id"])}" data-state="{state}" '
                         f'data-platforms="{_e(" ".join(s["platforms"]))}" tabindex="0">'
                         f'<h3>{_e(s["title"])}</h3><p class="sub">{sub} · <code>{_e(s["id"])}</code></p>{"".join(rows)}</article>')
        parts.append("</div></section>")
    return "\n".join(parts)


def _banner(data: dict) -> str:
    c = data["coverage"]
    per = " · ".join(f'{_e(p)} {r["captured"]}/{r["expected"]}' for p, r in c["platforms"].items())
    feat = ""
    if data["has_features"]:
        f = data["features"]
        feat = f' · features: {f["sections_mapped"]}/{f["sections"]} sections mapped, {f["rows_mapped"]}/{f["rows"]} rows'
    return (f'<div class="banner"><b>{c["captured"]} / {c["expected"]}</b> screens captured ({c["percent"]}%)'
            f'<span class="meter"><i style="width:{c["percent"]}%"></i></span><span class="per">{per}{feat}</span></div>')


def _gaps(data: dict) -> str:
    items = []
    miss = [s for s in data["screens"] if not s["captured"]]
    if miss:
        items.append("<h3>Not captured</h3><ul>" + "".join(
            f'<li><code>{_e(s["id"])}</code> {_e(s["title"])}{"" if s["route"] else " (no route)"}</li>' for s in miss) + "</ul>")
    if data["has_features"] and data["features"]["unmapped"]:
        items.append("<h3>Feature sections no screen names</h3><ul>" + "".join(
            f'<li>{_e(u["surface"])} / {_e(u["name"])} <small>{u["rows"]} row{"" if u["rows"] == 1 else "s"}</small></li>' for u in data["features"]["unmapped"]) + "</ul>")
    if data["stray"]:
        items.append("<h3>Captures that belong to no screen</h3><ul>" + "".join(
            f'<li>{_e(s["platform"])} · <code>{_e(s["route"])}</code></li>' for s in data["stray"]) + "</ul>")
    if data["errors"]:
        items.append("<h3>Invalid entries</h3><ul>" + "".join(f"<li>{_e(m)}</li>" for m in data["errors"]) + "</ul>")
    if not items:
        return ""
    return '<details class="gaps" open><summary>Coverage gaps</summary>' + "".join(items) + "</details>"


def render_html(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    plat_opts = "".join(f'<option value="{_e(p)}">{_e(p)}</option>' for p in data["platforms"])
    return (TEMPLATE.replace("__TITLE__", _e(data["repo"])).replace("__BANNER__", _banner(data))
            .replace("__PLATFORMS__", plat_opts).replace("__GAPS__", _gaps(data)).replace("__GRID__", _grid(data))
            .replace("__GENERATED__", _e(data["generated"])).replace("__DATA__", blob))


def write_atlas(repo: pathlib.Path, out: pathlib.Path, lang: str | None = None) -> tuple[pathlib.Path, dict]:
    out = pathlib.Path(out)
    shutil.rmtree(out / "img", ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    data, _ = build_data(repo, out, lang)
    path = out / "atlas.html"
    path.write_text(render_html(data), encoding="utf-8")
    return path, data


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Screen atlas · __TITLE__</title>
<style>
:root{--bg:#f6f6f4;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#d9d9d6;--acc:#2a6df4;--ok:#2e9d5b;--bad:#c2410c;--soft:#ecebe7}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececee;--mut:#9a9aa1;--card:#202024;--line:#38383e;--acc:#6b9bff;--ok:#4cc27f;--bad:#f08a4b;--soft:#2a2a2f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px}
h1{font-size:16px;margin:0 0 6px}h2{font-size:15px;margin:18px 0 8px}h2 small,h3 small{color:var(--mut);font-weight:400}h3{font-size:13px;margin:0}
.banner{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.meter{width:140px;height:8px;background:var(--soft);border-radius:4px;overflow:hidden}.meter i{display:block;height:100%;background:var(--ok)}.per{color:var(--mut)}
.bar{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;align-items:center}
button,select{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:3px 10px}button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
main{padding:0 16px 40px}.gaps{margin:12px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px}.gaps summary{cursor:pointer;font-weight:600}.gaps ul{margin:4px 0 8px;padding-left:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;cursor:pointer}.card.missing{border-style:dashed}.card:focus,.card:hover{border-color:var(--acc)}
.sub{margin:2px 0 8px;color:var(--mut);font-size:12px}code{font:12px ui-monospace,monospace}
.plat{display:flex;gap:6px;align-items:flex-start;margin-top:6px}.pl{width:48px;font-size:11px;color:var(--mut);padding-top:2px}
figure{margin:0;width:78px;text-align:center}figure img{width:100%;border:1px solid var(--line);border-radius:6px;display:block}
figure.none div{height:100px;border:1px dashed var(--line);border-radius:6px;font-size:10px;color:var(--bad);display:flex;align-items:center;justify-content:center;padding:2px}
figcaption{font-size:10px;color:var(--mut)}
.hidden{display:none!important}
#map{height:calc(100vh - 118px);border:1px solid var(--line);border-radius:8px;background:var(--card);margin-top:12px;overflow:hidden;position:relative}
#map svg{width:100%;height:100%;cursor:grab;touch-action:none}.legend{position:absolute;left:10px;bottom:8px;font-size:11px;color:var(--mut);background:var(--card);padding:2px 6px;border-radius:4px}
.node rect{fill:var(--card);stroke:var(--line);stroke-width:1.5}.node.cap rect{stroke:var(--ok)}.node.miss rect{stroke:var(--bad);stroke-dasharray:4 3}.node.sel rect{stroke:var(--acc);stroke-width:3}
.node text{fill:var(--fg);font-size:12px;pointer-events:none}.node text.s{fill:var(--mut);font-size:10px}.node{cursor:pointer}.node.dim{opacity:.18}
.edge{fill:none;stroke:var(--mut);stroke-width:1.4}.edge.decl{stroke-dasharray:6 4}.edge.par{stroke:var(--line);stroke-width:1.2}
#panel{position:fixed;top:0;right:0;bottom:0;width:min(440px,100vw);background:var(--card);border-left:1px solid var(--line);padding:14px 16px;overflow:auto;z-index:9;transform:translateX(100%);transition:transform .15s}
#panel.open{transform:none}#panel h2{margin-top:0}#panel h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
#panel dl{margin:0;display:grid;grid-template-columns:70px 1fr;gap:4px 8px}#panel dt{color:var(--mut)}#panel dd{margin:0}
#panel .shots{display:flex;flex-wrap:wrap;gap:6px}#panel .shots img{width:96px;border:1px solid var(--line);border-radius:6px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 8px;margin:0 4px 2px 0;font-size:12px}.chip.ok{border-color:var(--ok)}.chip.bad{border-color:var(--bad);color:var(--bad)}
#panel a{color:var(--acc);cursor:pointer}#close{position:absolute;top:8px;right:10px}
</style></head><body>
<header><h1>Screen atlas · __TITLE__ <small style="color:var(--mut);font-weight:400">generated __GENERATED__</small></h1>
__BANNER__
<div class="bar"><button id="tg" class="on">Grid</button><button id="tm">Map</button>
<label>Platform <select id="fp"><option value="">all</option>__PLATFORMS__</select></label>
<label>Coverage <select id="fc"><option value="">all</option><option value="captured">captured</option><option value="missing">not captured</option></select></label></div></header>
<main><div id="grid">__GAPS__
__GRID__</div>
<div id="map" class="hidden"><svg id="svg" role="img" aria-label="Screen navigation graph"></svg>
<div class="legend">solid arrow: tested link · dashed arrow: declared link · grey line: parent · green box: captured · dashed red box: not captured</div></div></main>
<aside id="panel" aria-live="polite"><button id="close">Close</button><div id="pbody"></div></aside>
<script id="atlas-data" type="application/json">__DATA__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('atlas-data').textContent),S={},fp='',fc='',sel=null;
D.screens.forEach(function(s){S[s.id]=s});
function el(t,a,x){var n=document.createElementNS(x?'http://www.w3.org/2000/svg':'http://www.w3.org/1999/xhtml',t);for(var k in a||{})n.setAttribute(k,a[k]);return n}
function txt(t,s,x){var n=document.createElement(t);n.textContent=s;if(x)n.className=x;return n}
function shown(s){return (!fp||s.platforms.indexOf(fp)>=0)&&(!fc||(fc==='captured')===s.captured)}
function filter(){
 document.querySelectorAll('.card').forEach(function(c){c.classList.toggle('hidden',!shown(S[c.dataset.screen]));
  c.querySelectorAll('.plat').forEach(function(p){p.classList.toggle('hidden',!!fp&&p.dataset.platform!==fp)})});
 document.querySelectorAll('.lvl').forEach(function(l){l.classList.toggle('hidden',!l.querySelector('.card:not(.hidden)'))});
 document.querySelectorAll('.node').forEach(function(n){n.classList.toggle('dim',!shown(S[n.dataset.screen]))});
}
function open(id){
 var s=S[id];if(!s)return;sel=id;var b=document.getElementById('pbody');b.textContent='';
 b.appendChild(txt('h2',s.title));
 var d=el('dl');function row(k,v){if(!v)return;d.appendChild(txt('dt',k));var dd=document.createElement('dd');if(typeof v==='string')dd.textContent=v;else dd.appendChild(v);d.appendChild(dd)}
 var c=document.createElement('span');c.appendChild(txt('span',s.id,'chip'));s.platforms.forEach(function(p){c.appendChild(txt('span',p,'chip'))});
 c.appendChild(txt('span',s.captured?'captured':'not captured','chip '+(s.captured?'ok':'bad')));
 row('Screen',c);row('Level',String(s.level));row('Route',s.route||'none');row('Job',s.job);row('Action',s.primary_action);row('States',s.states.join(', '));
 b.appendChild(d);
 b.appendChild(txt('h4','Layout contract'));var ld=el('dl');
 ['compact','regular','wide'].forEach(function(k){ld.appendChild(txt('dt',k));ld.appendChild(txt('dd',s.layout[k]||'not written'))});
 b.appendChild(ld);
 if(s.layout.assert){var a=txt('p','Enforced by '+s.layout.assert+(s.assert_found===false?' (not found in the code)':''),'sub');b.appendChild(a)}
 b.appendChild(txt('h4','Screenshots'));var sh=document.createElement('div');sh.className='shots';
 s.images.forEach(function(i){var im=document.createElement('img');im.src=i.src;im.alt=i.platform+' '+i.look+' '+i.state;im.title=i.platform+' · '+i.look+' · '+(i.state||'screen')+' · '+i.kind;sh.appendChild(im)});
 if(!s.images.length)sh.appendChild(txt('span','Not captured: '+(s.route?'no screenshot of route '+s.route:'the screen has no route'),'chip bad'));
 b.appendChild(sh);
 var out=s.links.map(function(l){return [l.to,l.via,l.tested]}),inn=s.linked_from.map(function(f){return [f,'',null]});
 if(s.parent)inn.unshift([s.parent,'parent',null]);
 [['Leads to',out],['Reached from',inn]].forEach(function(g){if(!g[1].length)return;b.appendChild(txt('h4',g[0]));var u=document.createElement('div');
  g[1].forEach(function(l){var a=txt('a',(S[l[0]]?S[l[0]].title:l[0])+(l[1]?' · '+l[1]:'')+(l[2]===true?' · tested':l[2]===false?' · declared':''));a.onclick=function(){open(l[0])};u.appendChild(a);u.appendChild(document.createElement('br'))});b.appendChild(u)});
 b.appendChild(txt('h4','Features'));var f=document.createElement('div');
 s.features.forEach(function(x){f.appendChild(txt('span',x.matched?x.surface+' / '+x.section+' ('+x.rows+')':x.ref+' (no match)','chip '+(x.matched?'ok':'bad')))});
 if(!s.features.length)f.appendChild(txt('span',D.has_features?'none mapped':'none declared','chip'));
 b.appendChild(f);
 b.appendChild(txt('h4','Source'));var sf=document.createElement('div');s.source.forEach(function(x){sf.appendChild(txt('code',x));sf.appendChild(document.createElement('br'))});
 if(!s.source.length)sf.appendChild(txt('span','none declared','chip'));b.appendChild(sf);
 document.getElementById('panel').classList.add('open');
 document.querySelectorAll('.node').forEach(function(n){n.classList.toggle('sel',n.dataset.screen===id)});
}
document.getElementById('close').onclick=function(){document.getElementById('panel').classList.remove('open');sel=null;document.querySelectorAll('.node.sel').forEach(function(n){n.classList.remove('sel')})};
document.querySelectorAll('.card').forEach(function(c){c.onclick=function(){open(c.dataset.screen)};c.onkeydown=function(e){if(e.key==='Enter')open(c.dataset.screen)}});
var W=D.node.w,H=D.node.h,svg=document.getElementById('svg'),vb=null,g=null;
function build(){
 g=el('g',{},1);var ed=el('g',{},1),nd=el('g',{},1);
 var defs=el('defs',{},1),m=el('marker',{id:'arr',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'},1);
 m.appendChild(el('path',{d:'M0 0L10 5L0 10z',fill:'currentColor'},1));defs.appendChild(m);
 svg.appendChild(defs);
 D.edges.forEach(function(e){var a=S[e.from],b=S[e.to];if(!a||!b)return;
  var x1=a.x+W,y1=a.y+H/2,x2=b.x,y2=b.y+H/2;if(x2<=x1){x1=a.x+W/2;y1=a.y+H;x2=b.x+W/2;y2=b.y}
  var mx=(x1+x2)/2,p=el('path',{d:'M'+x1+' '+y1+'C'+mx+' '+y1+' '+mx+' '+y2+' '+x2+' '+y2,'class':'edge '+(e.kind==='parent'?'par':e.tested?'':'decl')},1);
  if(e.kind==='link'){p.setAttribute('marker-end','url(#arr)');p.style.color='var(--mut)'}
  if(e.via){var t=el('title',{},1);t.textContent=e.via+(e.tested?' (tested)':' (declared)');p.appendChild(t)}
  ed.appendChild(p)});
 D.screens.forEach(function(s){var n=el('g',{'class':'node '+(s.captured?'cap':'miss'),transform:'translate('+s.x+','+s.y+')'},1);n.dataset.screen=s.id;
  n.appendChild(el('rect',{width:W,height:H,rx:8},1));
  var t=el('text',{x:10,y:19},1);t.textContent=s.title.length>24?s.title.slice(0,23)+'…':s.title;n.appendChild(t);
  var u=el('text',{x:10,y:35,'class':'s'},1);u.textContent=s.id.length>28?s.id.slice(0,27)+'…':s.id;n.appendChild(u);
  n.onclick=function(ev){ev.stopPropagation();open(s.id)};nd.appendChild(n)});
 g.appendChild(ed);g.appendChild(nd);svg.appendChild(g);fit();
}
function fit(){var xs=D.screens.map(function(s){return s.x+W}),ys=D.screens.map(function(s){return s.y+H});
 var w=Math.max.apply(null,xs.concat([W]))+40,h=Math.max.apply(null,ys.concat([H]))+40;vb={x:-20,y:-20,w:w,h:h};apply()}
function apply(){svg.setAttribute('viewBox',vb.x+' '+vb.y+' '+vb.w+' '+vb.h)}
svg.addEventListener('wheel',function(e){e.preventDefault();var r=svg.getBoundingClientRect(),k=e.deltaY>0?1.12:1/1.12,
 px=vb.x+vb.w*(e.clientX-r.left)/r.width,py=vb.y+vb.h*(e.clientY-r.top)/r.height;
 vb={x:px-(px-vb.x)*k,y:py-(py-vb.y)*k,w:vb.w*k,h:vb.h*k};apply()},{passive:false});
var drag=null;
svg.addEventListener('pointerdown',function(e){drag={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y}});
window.addEventListener('pointermove',function(e){if(!drag)return;var r=svg.getBoundingClientRect();
 vb.x=drag.vx-(e.clientX-drag.x)*vb.w/r.width;vb.y=drag.vy-(e.clientY-drag.y)*vb.h/r.height;apply()});
window.addEventListener('pointerup',function(){drag=null});
function view(m){document.getElementById('grid').classList.toggle('hidden',m);document.getElementById('map').classList.toggle('hidden',!m);
 document.getElementById('tg').classList.toggle('on',!m);document.getElementById('tm').classList.toggle('on',m);if(m&&!g){build()}}
document.getElementById('tg').onclick=function(){view(false)};document.getElementById('tm').onclick=function(){view(true)};
document.getElementById('fp').onchange=function(e){fp=e.target.value;filter()};
document.getElementById('fc').onchange=function(e){fc=e.target.value;filter()};
if(location.hash==='#map')view(true);
})();
</script></body></html>
"""


# --- the CLI --------------------------------------------------------------------------------------

def add_arguments(q) -> None:
    q.add_argument("--out", metavar="DIR", help="atlas: where atlas.html and img/ go (default: <repo>/design/atlas)")
    q.add_argument("--lang", help="atlas: the language of the screenshots shown (default: the tour's first language)")
    q.add_argument("--open", action="store_true", help="atlas: open atlas.html in the browser")


def _repo(args, action: str, rest: list[str]) -> pathlib.Path | None:
    from . import docs_check
    if args.all or len(rest) > 1:
        print(f"teyla ux {action}: name one repo", file=sys.stderr)
        return None
    try:
        return docs_check.resolve(rest, False)[0]
    except FileNotFoundError as e:
        print(f"teyla ux {action}: {e}", file=sys.stderr)
        return None


def cmd(args) -> int:
    rest = list(args.repos)
    if args.action == "registry":
        if not rest or rest[0] != "check":
            print("teyla ux registry: the only subcommand is `check`: teyla ux registry check [repo]", file=sys.stderr)
            return 2
        repo = _repo(args, "registry check", rest[1:])
        if repo is None:
            return 2
        r = report(repo)
        print(json.dumps(r, indent=1) if args.json else render_report(r))
        return 1 if r["errors"] else 0
    repo = _repo(args, "atlas", rest)
    if repo is None:
        return 2
    out = pathlib.Path(args.out).expanduser() if args.out else repo / "design" / "atlas"
    path, data = write_atlas(repo, out, args.lang)
    c = data["coverage"]
    print(f"{path}\n{len(data['screens'])} screen(s), captured / expected {c['captured']} / {c['expected']} ({c['percent']}%)"
          + (f", {len(data['errors'])} invalid entr{'y' if len(data['errors']) == 1 else 'ies'} (teyla ux registry check)" if data["errors"] else ""))
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0
