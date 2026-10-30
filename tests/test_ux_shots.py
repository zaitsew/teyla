"""teyla ux shots / diff / accept: fixture repos in tmp dirs, a fake runner, tiny generated PNGs.
Nothing here starts Xcode or a simulator; the simulator path is exercised with mocks only."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

from teyla import cli, ux_shots as ux

ROOT = pathlib.Path(__file__).resolve().parents[1]

MANIFEST = """\
version: 1
fixed_date: 2026-01-15T09:41:00Z
seed: 7
network_stub: true
languages: [en, es]
looks: [light, dark, large]
runs: 3
device: {name: Example Phone, width_pt: 100, height_pt: 200}
masks:
  clock: {x: 0, y: 0, w: 100, h: 20}
  map: {x: 0, y: 100, w: 100, h: 50}
defaults:
  threshold: 0.2
  tolerance: 8
routes:
  - id: today
    path: /today
    threshold: 0.5
    masks: [clock]
    states:
      - loaded
      - empty
      - name: error
        threshold: 2
  - id: places
    path: /places
    masks: [map]
    states: [loaded, listening]
"""

TOML = """\
[ux.tour]
project = "Example.xcodeproj"
scheme = "ExampleTour"
device = "Example Phone"
"""


def make_repo(tmp_path, manifest=MANIFEST, toml=TOML, name="app"):
    repo = tmp_path / name
    (repo / "design").mkdir(parents=True)
    (repo / ".git").mkdir()
    if manifest is not None:
        (repo / "design" / "tour.yaml").write_text(manifest)
    if toml is not None:
        (repo / "teyla.toml").write_text(toml)
    return repo


def manifest_of(text=MANIFEST) -> ux.Manifest:
    m, errs = ux.validate(ux.parse_yaml(text), text)
    assert not errs, errs
    return m


def png(path, color=(255, 255, 255), size=(100, 200), patch=None):
    from PIL import Image
    im = Image.new("RGB", size, color)
    if patch:
        (x0, y0, x1, y1), c = patch
        for x in range(x0, x1):
            for y in range(y0, y1):
                im.putpixel((x, y), c)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


# --- the YAML subset and the manifest ------------------------------------------------------------

def test_yaml_subset_parses_maps_lists_and_inline_values():
    d = ux.parse_yaml("a: 1\nb: [x, 'y z', 3]\nc: {k: v, n: 2.5}\nd:\n  - id: one   # comment\n    ok: true\n  - two\ne: ~\n")
    assert d == {"a": 1, "b": ["x", "y z", 3], "c": {"k": "v", "n": 2.5}, "d": [{"id": "one", "ok": True}, "two"], "e": None}


def test_yaml_accepts_json_and_rejects_bad_input():
    assert ux.parse_yaml('{"a": [1, 2]}') == {"a": [1, 2]}
    for bad in ("a: 1\na: 2\n", "a:\n\tb: 1\n", "just words\n", "a: [1, 2\n"):
        with pytest.raises(ux.YamlError):
            ux.parse_yaml(bad)


def test_valid_manifest_builds_screens_with_inherited_threshold_and_masks():
    m = manifest_of()
    assert [s.id for s in m.screens] == ["today.loaded", "today.empty", "today.error", "places.loaded", "places.listening"]
    by = {s.id: s for s in m.screens}
    assert by["today.loaded"].threshold == 0.5 and by["today.error"].threshold == 2.0
    assert by["places.loaded"].threshold == 0.2            # the default
    assert by["today.error"].masks == ("clock",) and by["places.listening"].masks == ("map",)
    assert m.variants()[:3] == ["en-light", "en-dark", "en-large"] and len(m.variants()) == 6
    plan = m.plan()
    assert plan["seed"] == 7 and plan["network_stub"] is True and plan["screens"][0]["path"] == "/today"
    assert plan["looks"][2] == {"name": "large", "style": "light", "content_size": "UICTContentSizeCategoryAccessibilityXXXL"}


@pytest.mark.parametrize("mutate, needle", [
    (lambda t: t.replace("fixed_date: 2026-01-15T09:41:00Z\n", ""), "fixed_date"),
    (lambda t: t.replace("seed: 7\n", ""), "seed"),
    (lambda t: t.replace("seed: 7", "seed: 7\nspeed: 3"), "unknown key `speed`"),
    (lambda t: t.replace("- loaded\n      - empty", "- loaded\n      - sleeping"), "sleeping"),
    (lambda t: t.replace("masks: [clock]", "masks: [clok]"), "unknown: ['clok']"),
    (lambda t: t.replace("w: 100, h: 20", "w: 300, h: 20"), "leaves the 100 x 200 pt device screen"),
    (lambda t: t.replace("id: places", "id: today"), "used twice"),
    (lambda t: t.replace("threshold: 0.5", "threshold: 140"), "percentage"),
    (lambda t: t.replace("languages: [en, es]", "languages: [en, en]"), "twice"),
    (lambda t: t.replace("looks: [light, dark, large]", "looks: [light, sepia]"), "looks"),
    (lambda t: t.replace("device: {name: Example Phone, width_pt: 100, height_pt: 200}\n", ""), "device"),
    (lambda t: t.replace("fixed_date: 2026-01-15T09:41:00Z", "fixed_date: yesterday"), "ISO 8601"),
])
def test_manifest_errors_name_the_problem(mutate, needle):
    text = mutate(MANIFEST)
    m, errs = ux.validate(ux.parse_yaml(text), text)
    assert m is None
    assert any(needle in e for e in errs), errs


def test_check_manifest_command(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert cli.main(["ux", "shots", str(repo), "--check-manifest"]) == 0
    out = capsys.readouterr().out
    assert "5 screen(s) from 2 route(s)" in out and "6 variant(s)" in out and "30 capture(s) per run" in out
    (repo / "design" / "tour.yaml").write_text(MANIFEST.replace("seed: 7\n", ""))
    assert cli.main(["ux", "shots", str(repo), "--check-manifest"]) == 1
    assert "seed" in capsys.readouterr().err


def test_missing_manifest_is_a_one_line_error(tmp_path, capsys):
    repo = make_repo(tmp_path, manifest=None)
    assert cli.main(["ux", "shots", str(repo)]) == 2
    assert "design/tour.yaml not found" in capsys.readouterr().err


def test_the_example_in_docs_validates():
    text = (ROOT / "docs" / "MATRIX.md").read_text()
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    m, errs = ux.validate(ux.parse_yaml(block), block)
    assert not errs, errs
    assert m.screens


def test_tour_config(tmp_path):
    repo = make_repo(tmp_path)
    cfg = ux.load_tour_config(repo)
    assert (cfg.project_flag, cfg.project, cfg.scheme, cfg.device) == ("-project", "Example.xcodeproj", "ExampleTour", "Example Phone")
    (repo / "teyla.toml").write_text('[ux.tour]\nworkspace = "A.xcworkspace"\nproject = "B.xcodeproj"\nscheme = "S"\n')
    with pytest.raises(ux.ConfigError, match="exactly one"):
        ux.load_tour_config(repo)
    (repo / "teyla.toml").write_text('[ux.tour]\nworkspace = "A.xcworkspace"\nscheme = "S"\n')
    assert ux.load_tour_config(repo, manifest=manifest_of()).device == "Example Phone"
    (repo / "teyla.toml").write_text("[other]\n")
    with pytest.raises(ux.ConfigError, match=r"\[ux.tour\]"):
        ux.load_tour_config(repo)


# --- layout checks on the tour's element frames --------------------------------------------------

def el(type_, label, x, y, w, h, **kw):
    return {"type": type_, "label": label, "x": x, "y": y, "w": w, "h": h, **kw}


def kinds(doc):
    return sorted((f["kind"], tuple(f["elements"])) for f in ux.analyze_elements(doc))


def test_small_target_only_for_interactive_elements():
    doc = {"screen": {"width": 100, "height": 200}, "elements": [
        el("button", "Tiny", 10, 10, 30, 30), el("button", "Wide", 10, 60, 80, 44), el("staticText", "Caption", 10, 120, 20, 10),
        el("switch", "Flag", 10, 150, 51, 31)]}
    assert kinds(doc) == [("small-target", ("button 'Tiny'",)), ("small-target", ("switch 'Flag'",))]


def test_off_screen_ignores_scroll_content_and_window():
    doc = {"screen": {"width": 100, "height": 200}, "elements": [
        el("window", "", 0, 0, 100, 200), el("staticText", "Cut", 80, 10, 40, 20), el("staticText", "Inside", 0, 40, 100, 20),
        el("staticText", "Row", 0, 190, 100, 50, in_scroll=True)]}
    assert kinds(doc) == [("off-screen", ("statictext 'Cut'",))]


def test_truncated_by_flag_or_ellipsis():
    doc = {"screen": {"width": 100, "height": 200}, "elements": [
        el("staticText", "A long tit\u2026", 0, 0, 90, 20), el("staticText", "Cut", 0, 30, 50, 20, truncated=True),
        el("staticText", "Fine", 0, 60, 50, 20)]}
    assert kinds(doc) == [("truncated", ("statictext 'A long tit\u2026'",)), ("truncated", ("statictext 'Cut'",))]


def test_overlap_needs_a_partial_cover_not_containment_or_a_container():
    doc = {"screen": {"width": 100, "height": 200}, "elements": [
        el("staticText", "Left", 0, 0, 60, 20), el("staticText", "Right", 40, 0, 60, 20),           # partial: flagged
        el("image", "Icon", 0, 100, 50, 50), el("staticText", "On icon", 10, 110, 20, 10),          # contained: fine
        el("cell", "Row", 0, 150, 100, 40), el("staticText", "In row", 5, 155, 90, 20),             # container: fine
        el("staticText", "Edge A", 0, 60, 50, 20), el("staticText", "Edge B", 50, 60, 50, 20)]}     # touching: fine
    assert kinds(doc) == [("overlap", ("statictext 'Left'", "statictext 'Right'"))]


def test_analyze_survives_junk():
    assert ux.analyze_elements({}) == []
    assert ux.analyze_elements({"elements": [None, {"type": "button"}, {"x": "a", "y": 1, "w": 2, "h": 3}]}) == []


# --- reading the export --------------------------------------------------------------------------

UUID = "8A2B4C6D-1111-2222-3333-444455556666"


def test_classify_attachment_names():
    c = ux.classify_attachment
    assert c("en-light__today.loaded") == ("en-light", "today.loaded", "png")
    assert c(f"en-light__today.loaded_0_{UUID}.png") == ("en-light", "today.loaded", "png")
    assert c(f"es-419-dark__plan-day.error.elements_2_{UUID}.json") == ("es-419-dark", "plan-day.error", "elements")
    assert c("en-large__today.listening.audit") == ("en-large", "today.listening", "audit")
    assert c("random attachment") is None
    assert c("en-light__today.sleeping") is None


def write_export(out_dir: pathlib.Path, items: dict, elements=None, audit=None):
    """items: {(variant, screen): color}. Writes the files and a manifest.json shaped like xcresulttool's."""
    out_dir.mkdir(parents=True, exist_ok=True)
    attachments = []
    for i, ((variant, screen), color) in enumerate(items.items()):
        png(out_dir / f"{i}-shot.png", color)
        attachments.append({"exportedFileName": f"{i}-shot.png", "isAssociatedWithFailure": False,
                            "suggestedHumanReadableName": f"{variant}__{screen}_0_{UUID}.png"})
        if elements is not None:
            (out_dir / f"{i}-el.json").write_text(json.dumps(elements))
            attachments.append({"exportedFileName": f"{i}-el.json", "suggestedHumanReadableName": f"{variant}__{screen}.elements_1_{UUID}.json"})
        if audit is not None:
            (out_dir / f"{i}-au.json").write_text(json.dumps(audit))
            attachments.append({"exportedFileName": f"{i}-au.json", "suggestedHumanReadableName": f"{variant}__{screen}.audit_2_{UUID}.json"})
    (out_dir / "manifest.json").write_text(json.dumps([{"testIdentifier": "ScreenshotTour/testTour()", "attachments": attachments}]))


def test_parse_export_pairs_png_elements_and_audit(tmp_path):
    pytest.importorskip("PIL")
    write_export(tmp_path / "x", {("en-light", "today.loaded"): (1, 2, 3)}, elements={"elements": []}, audit={"ran": True, "issues": []})
    caps = ux.parse_export(tmp_path / "x")
    cap = caps[("en-light", "today.loaded")]
    assert cap.png.name == "0-shot.png" and cap.elements.name == "0-el.json" and cap.audit.name == "0-au.json"


def test_parse_export_without_manifest_uses_file_names(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "en-dark__places.empty.png").write_bytes(b"x")
    assert ("en-dark", "places.empty") in ux.parse_export(d)
    assert ux.parse_export(tmp_path / "x") and not ux.parse_export(tmp_path / "x").get(("zz", "a.loaded"))


# --- stability -----------------------------------------------------------------------------------

def test_stability_logic():
    assert ux.stability(["a", "a", "a"]) is True
    assert ux.stability(["a", "a", "b"]) is False
    assert ux.stability(["a"]) is None and ux.stability([]) is None


def test_aggregate_reports_unstable_findings_and_audit(tmp_path):
    pytest.importorskip("PIL")
    m = manifest_of()
    key = ("en-light", "today.loaded")
    steady = ("en-light", "today.empty")
    els = {"screen": {"width": 100, "height": 200}, "elements": [el("button", "Tiny", 0, 0, 20, 20)]}
    audit = {"ran": True, "issues": [{"type": 1, "description": "Contrast failed"}]}
    runs = []
    for n, color in enumerate([(10, 10, 10), (10, 10, 10), (200, 10, 10)], start=1):
        write_export(tmp_path / f"r{n}", {key: color, steady: (5, 5, 5)}, elements=els, audit=audit)
        runs.append(ux.parse_export(tmp_path / f"r{n}"))
    screens = ux.aggregate(m, runs, 3)
    a, b = screens["en-light/today.loaded"], screens["en-light/today.empty"]
    assert a["stable"] is False and len(set(a["hashes"])) == 2
    assert b["stable"] is True
    assert [f["kind"] for f in a["findings"]] == ["small-target"]          # deduplicated across runs
    assert a["audit"]["issue_count"] == 1
    assert screens["es-dark/places.listening"]["captured"] == 0
    doc = ux.run_json(m, screens, status="complete", started="s", finished="f", duration_s=1.0, budget_s=540, runs_requested=3,
                      runs_completed=3, device="Example Phone", commit="abc", errors=[])
    assert doc["unstable"] == ["en-light/today.loaded"]
    assert "es-dark/places.listening" in doc["uncaptured"]
    assert doc["counts"]["unstable"] == 1


# --- the orchestration with a fake runner --------------------------------------------------------

DEVICES = {"devices": {
    "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [{"udid": "OLD-UDID", "name": "Example Phone", "state": "Shutdown", "isAvailable": True}],
    "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [{"udid": "NEW-UDID", "name": "Example Phone", "state": "Shutdown", "isAvailable": True},
                                                    {"udid": "OTHER", "name": "Another Phone", "state": "Booted", "isAvailable": True}]}}


def test_pick_device_prefers_booted_then_newest_runtime():
    assert ux.pick_device(DEVICES, "Example Phone") == ("NEW-UDID", False)
    booted = json.loads(json.dumps(DEVICES))
    booted["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-17-5"][0]["state"] = "Booted"
    assert ux.pick_device(booted, "Example Phone") == ("OLD-UDID", True)
    assert ux.pick_device(DEVICES, "Missing Phone") is None


class FakeRunner(ux.Runner):
    def __init__(self, tmp_path, devices=DEVICES, guard_rc=0, build_rc=0, test_rcs=None, colors=None, timeouts=(),
                 omit=None):
        self.calls: list[list[str]] = []
        self.envs: list[dict | None] = []
        self.devices, self.guard_rc, self.build_rc = devices, guard_rc, build_rc
        self.test_rcs = test_rcs or {}
        self.colors = colors or (lambda n, key: (20, 20, 20))
        self.timeouts = set(timeouts)               # names of steps that run past the budget
        self.runs = 0
        self.tmp_path = tmp_path
        self.omit = omit or (lambda n, key: False)  # (run number, (variant, screen)) -> the tour did not capture it

    def run(self, argv, *, timeout=None, env=None, cwd=None):
        self.calls.append(list(argv))
        self.envs.append(env)
        joined = " ".join(argv)
        if "load" in argv and "--admit" in argv:
            return ux.Result(self.guard_rc, "machine busy: reuse a booted simulator" if self.guard_rc else "")
        if "load" in argv and "--wait" in argv:
            return ux.Result(0)
        if argv[:4] == ["xcrun", "simctl", "list", "devices"]:
            return ux.Result(0, json.dumps(self.devices))
        if argv[:3] == ["xcrun", "simctl", "boot"] or "bootstatus" in argv or "status_bar" in argv or "shutdown" in argv:
            return ux.Result(0)
        if argv[0] == "xcodebuild" and "build-for-testing" in argv:
            if "build" in self.timeouts:
                return ux.Result(-9, timed_out=True)
            return ux.Result(self.build_rc, "", "error: build failed" if self.build_rc else "")
        if argv[0] == "xcodebuild" and "test-without-building" in argv:
            self.runs += 1
            if f"test{self.runs}" in self.timeouts:
                return ux.Result(-9, timed_out=True)
            self.bundle = argv[argv.index("-resultBundlePath") + 1]
            pathlib.Path(self.bundle).mkdir(parents=True, exist_ok=True)
            return ux.Result(self.test_rcs.get(self.runs, 0), "", "Test failed" if self.test_rcs.get(self.runs) else "")
        if "xcresulttool" in joined:
            out_dir = pathlib.Path(argv[argv.index("--output-path") + 1])
            m = manifest_of()
            items = {(v, s.id): self.colors(self.runs, (v, s.id)) for v in m.variants() for s in m.screens
                     if not self.omit(self.runs, (v, s.id))}
            write_export(out_dir, items, elements={"screen": {"width": 100, "height": 200}, "elements": []},
                         audit={"ran": True, "issues": []})
            return ux.Result(0)
        raise AssertionError(f"unexpected command {argv}")

    def issued(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


def go(tmp_path, runner, **kw):
    repo = make_repo(tmp_path)
    cfg = ux.load_tour_config(repo)
    work = tmp_path / "work"
    return repo, ux.run_shots(repo, manifest_of(), cfg, runner, work_dir=work, derived=tmp_path / "dd", **kw)


def test_a_clean_run_exports_shots_and_run_json_and_shuts_down_the_simulator(tmp_path):
    pytest.importorskip("PIL")
    r = FakeRunner(tmp_path)
    repo, doc = go(tmp_path, r)
    assert doc["status"] == "complete" and doc["runs_completed"] == 3 and doc["unstable"] == [] and doc["errors"] == []
    # order: admission, then the build, then three test runs
    assert r.calls[0][-5:-2] == ["load", "--admit", "build"]
    builds = r.issued("xcodebuild", "build-for-testing")
    tests = r.issued("xcodebuild", "test-without-building")
    assert len(builds) == 1 and len(tests) == 3
    assert "platform=iOS Simulator,id=NEW-UDID" in builds[0]
    # the plan reaches the tour through TEST_RUNNER_<NAME>
    plan = json.loads(next(e for e in r.envs if e and "TEST_RUNNER_TEYLA_TOUR_PLAN" in e)["TEST_RUNNER_TEYLA_TOUR_PLAN"])
    assert plan["screens"][0]["id"] == "today.loaded" and plan["languages"] == ["en", "es"]
    # one simulator, booted by us, shut down after the last run
    assert len(r.issued("simctl", "boot")) == 1 and len(r.issued("simctl", "shutdown")) == 1
    assert r.calls.index(r.issued("simctl", "shutdown")[0]) > r.calls.index(tests[-1])
    shots = repo / "design" / "shots"
    assert (shots / "en-light" / "today.loaded.png").is_file() and (shots / "es-large" / "places.listening.png").is_file()
    saved = json.loads((shots / "run.json").read_text())
    assert saved["counts"]["screens"] == 30 and saved["runs_requested"] == 3


def test_an_unstable_screen_is_reported(tmp_path, capsys):
    pytest.importorskip("PIL")
    flaky = ("es-dark", "places.listening")
    r = FakeRunner(tmp_path, colors=lambda n, key: (n * 40, 0, 0) if key == flaky else (20, 20, 20))
    repo, doc = go(tmp_path, r)
    assert doc["unstable"] == ["es-dark/places.listening"]
    text = ux.render_run(doc)
    assert "UNSTABLE (1)" in text and "es-dark/places.listening" in text


def test_the_simulator_is_reused_when_booted_and_not_shut_down(tmp_path):
    pytest.importorskip("PIL")
    devices = json.loads(json.dumps(DEVICES))
    devices["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-18-2"][0]["state"] = "Booted"
    r = FakeRunner(tmp_path, devices=devices)
    go(tmp_path, r)
    assert not r.issued("simctl", "boot") and not r.issued("simctl", "shutdown")


def test_the_simulator_is_shut_down_when_the_build_fails(tmp_path):
    r = FakeRunner(tmp_path, build_rc=65)
    with pytest.raises(ux.TourFailed, match="build-for-testing failed"):
        go(tmp_path, r)
    assert len(r.issued("simctl", "shutdown")) == 1
    assert not r.issued("xcodebuild", "test-without-building")


def test_the_simulator_is_shut_down_when_the_boot_fails_halfway(tmp_path):
    class Bad(FakeRunner):
        def run(self, argv, **kw):
            if "bootstatus" in argv:
                self.calls.append(list(argv))
                return ux.Result(1, "", "never finished")
            return super().run(argv, **kw)
    r = Bad(tmp_path)
    with pytest.raises(ux.SimulatorError):
        go(tmp_path, r)
    assert len(r.issued("simctl", "shutdown")) == 1


def test_the_simulator_is_shut_down_when_the_runner_itself_raises(tmp_path):
    class Boom(FakeRunner):
        def run(self, argv, **kw):
            if argv[0] == "xcodebuild" and "test-without-building" in argv:
                self.calls.append(list(argv))
                raise RuntimeError("boom")
            return super().run(argv, **kw)
    r = Boom(tmp_path)
    with pytest.raises(RuntimeError):
        go(tmp_path, r)
    assert len(r.issued("simctl", "shutdown")) == 1


def test_a_refused_admission_starts_nothing(tmp_path):
    r = FakeRunner(tmp_path, guard_rc=2)
    with pytest.raises(ux.GuardRefused, match="machine busy"):
        go(tmp_path, r)
    assert len(r.calls) == 1


def test_the_budget_cuts_the_run_and_reports_it(tmp_path):
    pytest.importorskip("PIL")
    r = FakeRunner(tmp_path, timeouts={"test3"})
    repo, doc = go(tmp_path, r, budget_s=540)
    assert doc["status"] == "budget" and doc["runs_completed"] == 2
    assert any("budget" in e for e in doc["errors"])
    assert len(r.issued("simctl", "shutdown")) == 1
    assert "CUT" in ux.render_run(doc)
    # the timeout handed to a step never exceeds what is left of the budget
    assert doc["budget_s"] == 540


def test_budget_timeout_is_the_remaining_time(tmp_path):
    seen = []
    n = {"calls": 0}

    def clock():
        n["calls"] += 1
        return 0 if n["calls"] == 1 else 100

    class Spy(FakeRunner):
        def run(self, argv, *, timeout=None, **kw):
            if argv[0] == "xcodebuild":
                seen.append(timeout)
            return super().run(argv, timeout=timeout, **kw)
    pytest.importorskip("PIL")
    go(tmp_path, Spy(tmp_path), budget_s=540, clock=clock)
    assert seen and all(t <= 440 for t in seen)       # 540 s budget, 100 s gone


def test_nothing_exported_is_a_failed_run_and_leaves_earlier_shots(tmp_path):
    class Empty(FakeRunner):
        def run(self, argv, **kw):
            if "xcresulttool" in " ".join(argv):
                self.calls.append(list(argv))
                pathlib.Path(argv[argv.index("--output-path") + 1]).mkdir(parents=True, exist_ok=True)
                return ux.Result(0)
            return super().run(argv, **kw)
    repo = make_repo(tmp_path)
    old = repo / "design" / "shots" / "en-light"
    old.mkdir(parents=True)
    (old / "keep.png").write_bytes(b"old")
    r = Empty(tmp_path)
    doc = ux.run_shots(repo, manifest_of(), ux.load_tour_config(repo), r, work_dir=tmp_path / "w", derived=tmp_path / "d")
    assert doc["status"] == "failed" and (old / "keep.png").read_bytes() == b"old"
    assert len(r.issued("simctl", "shutdown")) == 1


def test_shots_command_prints_and_exits(tmp_path, capsys, monkeypatch):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    args = cli.build_parser().parse_args(["ux", "shots", str(repo)])
    r = FakeRunner(tmp_path)
    monkeypatch.setattr(ux, "derived_data", lambda repo: tmp_path / "dd")
    assert ux.cmd(args, runner=r) == 0
    out = capsys.readouterr().out
    assert "complete" in out and "teyla ux diff" in out
    flaky = ("en-dark", "today.empty")
    r2 = FakeRunner(tmp_path, colors=lambda n, key: (n * 50, 0, 0) if key == flaky else (9, 9, 9))
    assert ux.cmd(args, runner=r2) == 1


def test_shots_command_reports_the_guard_refusal(tmp_path, capsys):
    repo = make_repo(tmp_path)
    args = cli.build_parser().parse_args(["ux", "shots", str(repo)])
    assert ux.cmd(args, runner=FakeRunner(tmp_path, guard_rc=2)) == 2
    err = capsys.readouterr().err
    assert "machine guard" in err and "teyla load --wait --kind build" in err


def test_dry_run_prints_the_commands_and_starts_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert cli.main(["ux", "shots", str(repo), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "load --admit build" in out and "xcodebuild build-for-testing -project Example.xcodeproj -scheme ExampleTour" in out
    assert out.count("test-without-building") == 3 and "xcresulttool export attachments" in out


# --- the real Runner -----------------------------------------------------------------------------

def test_runner_kills_a_process_group_that_passes_its_timeout():
    r = ux.Runner().run([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5)
    assert r.timed_out and r.returncode != 0


def test_runner_reports_a_missing_binary_and_normal_output():
    assert ux.Runner().run(["definitely-not-a-binary-xyz"]).returncode == 127
    r = ux.Runner().run([sys.executable, "-c", "print('hi')"])
    assert (r.returncode, r.stdout.strip(), r.timed_out) == (0, "hi", False)


def test_shutdown_after_a_failure_with_subprocess_mocked(tmp_path, monkeypatch):
    """The real Runner over a fake Popen: a failed build still ends in `simctl shutdown`."""
    started = []

    class FakePopen:
        pid = 2 ** 22 + 11
        returncode = 0

        def __init__(self, argv, **kw):
            started.append(list(argv))
            self.argv = argv

        def communicate(self, timeout=None):
            a = self.argv
            if a[:4] == ["xcrun", "simctl", "list", "devices"]:
                return json.dumps(DEVICES), ""
            if "build-for-testing" in a:
                self.returncode = 65
                return "", "error: build failed"
            self.returncode = 0
            return "", ""

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(ux.subprocess, "Popen", FakePopen)
    repo = make_repo(tmp_path)
    with pytest.raises(ux.TourFailed):
        ux.run_shots(repo, manifest_of(), ux.load_tour_config(repo), ux.Runner(), work_dir=tmp_path / "w", derived=tmp_path / "d")
    assert ["xcrun", "simctl", "shutdown", "NEW-UDID"] in started
    assert started.index(["xcrun", "simctl", "shutdown", "NEW-UDID"]) > started.index(["xcrun", "simctl", "boot", "NEW-UDID"])


# --- a run that went wrong is not complete -------------------------------------------------------

def test_xctest_failures_with_partial_screenshots_make_the_run_incomplete_and_unacceptable(tmp_path, capsys):
    pytest.importorskip("PIL")
    r = FakeRunner(tmp_path, test_rcs={2: 65})            # run 2 fails but still exports its screenshots
    repo, doc = go(tmp_path, r)
    assert doc["status"] == "incomplete" and doc["runs_completed"] == 3 and any("exited 65" in e for e in doc["errors"])
    assert "INCOMPLETE" in ux.render_run(doc)
    assert json.loads((repo / "design" / "shots" / "run.json").read_text())["status"] == "incomplete"
    for extra in ([], ["--allow-unstable"]):               # no flag overrides a failed run
        assert cli.main(["ux", "accept", str(repo), "--yes", *extra]) == 2
        assert "not complete" in capsys.readouterr().err
    assert not (repo / "design" / "shots" / "baseline").exists()


def test_shots_exits_1_for_an_incomplete_run(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    args = cli.build_parser().parse_args(["ux", "shots", str(repo)])
    assert ux.cmd(args, runner=FakeRunner(tmp_path, test_rcs={1: 65})) == 1


def test_accept_refuses_errors_uncaptured_and_short_runs_even_when_the_status_says_complete(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    for extra, needle in (({"errors": ["run 2: xcodebuild test exited 65"]}, "error"),
                          ({"uncaptured": ["en-light/today.loaded"]}, "not captured"),
                          ({"runs_requested": 3, "runs_completed": 2}, "2 of 3 run")):
        finished_run(repo, full=True, **extra)
        assert cli.main(["ux", "accept", str(repo), "--yes", "--allow-unstable"]) == 2
        assert needle in capsys.readouterr().err
    assert not (repo / "design" / "shots" / "baseline").exists()


def test_a_screen_the_tour_never_captured_makes_the_run_incomplete(tmp_path):
    pytest.importorskip("PIL")
    gone = ("es-dark", "places.listening")
    repo, doc = go(tmp_path, FakeRunner(tmp_path, omit=lambda n, key: key == gone))
    assert doc["status"] == "incomplete" and doc["uncaptured"] == ["es-dark/places.listening"]
    assert "NOT CAPTURED (1)" in ux.render_run(doc)


def test_a_screen_missing_from_one_run_is_uncaptured(tmp_path, capsys):
    pytest.importorskip("PIL")
    only_run_two = ("en-light", "today.loaded")
    repo, doc = go(tmp_path, FakeRunner(tmp_path, omit=lambda n, key: key == only_run_two and n != 2))
    entry = doc["screens"]["en-light/today.loaded"]
    assert entry["captured"] == 1 and entry["missing_runs"] == 2 and entry["stable"] is None
    assert doc["status"] == "incomplete" and "en-light/today.loaded" in doc["uncaptured"]
    # its first-run PNG does not exist, and the command does not exit 0
    assert not (repo / "design" / "shots" / "en-light" / "today.loaded.png").exists()
    args = cli.build_parser().parse_args(["ux", "shots", str(repo)])
    assert ux.cmd(args, runner=FakeRunner(tmp_path, omit=lambda n, key: key == only_run_two and n != 2)) == 1


def test_a_screen_lacking_one_of_three_runs_is_uncaptured_even_when_the_others_agree(tmp_path):
    pytest.importorskip("PIL")
    repo, doc = go(tmp_path, FakeRunner(tmp_path, omit=lambda n, key: key == ("en-dark", "today.empty") and n == 3))
    e = doc["screens"]["en-dark/today.empty"]
    assert e["captured"] == 2 and e["stable"] is True
    assert doc["uncaptured"] == ["en-dark/today.empty"] and doc["status"] == "incomplete"


def test_aggregate_marks_a_screen_seen_only_in_run_two(tmp_path):
    pytest.importorskip("PIL")
    m = manifest_of()
    key = ("en-light", "today.loaded")
    runs = []
    for n, items in enumerate([{}, {key: (1, 1, 1)}, {}], start=1):
        write_export(tmp_path / f"r{n}", items)
        runs.append(ux.parse_export(tmp_path / f"r{n}"))
    screens = ux.aggregate(m, runs, 3)
    assert screens["en-light/today.loaded"]["stable"] is None
    assert "en-light/today.loaded" in ux.uncaptured_keys(screens, 3)


# --- the budget covers the export ----------------------------------------------------------------

def test_the_export_gets_what_is_left_of_the_budget_and_a_late_export_cuts_the_run(tmp_path):
    pytest.importorskip("PIL")
    now = {"t": 0.0}
    seen = {}

    class Slow(FakeRunner):
        def run(self, argv, *, timeout=None, **kw):
            if argv[0] == "xcodebuild" and "test-without-building" in argv:
                now["t"] += 99                      # run 1 leaves one second of a 100 s budget
            if "xcresulttool" in " ".join(argv):
                seen.setdefault("export_timeouts", []).append(timeout)
                now["t"] += 5                       # the export itself overruns
            return super().run(argv, timeout=timeout, **kw)
    r = Slow(tmp_path)
    repo, doc = go(tmp_path, r, budget_s=100, clock=lambda: now["t"])
    assert seen["export_timeouts"] == [1]           # one second left, so one second, not 30
    assert doc["status"] == "budget" and doc["runs_completed"] == 1
    assert any("during the export of run 1" in e for e in doc["errors"])
    assert "CUT" in ux.render_run(doc)
    assert len(r.issued("xcodebuild", "test-without-building")) == 1       # no second run after the cut
    assert len(r.issued("simctl", "shutdown")) == 1
    assert cli.main(["ux", "accept", str(repo), "--yes"]) == 2


def test_an_export_inside_the_budget_is_not_cut(tmp_path):
    pytest.importorskip("PIL")
    now = {"t": 0.0}

    class Quick(FakeRunner):
        def run(self, argv, **kw):
            if argv[0] == "xcodebuild" and "test-without-building" in argv:
                now["t"] += 10
            return super().run(argv, **kw)
    _, doc = go(tmp_path, Quick(tmp_path), budget_s=100, clock=lambda: now["t"])
    assert doc["status"] == "complete" and doc["runs_completed"] == 3


# --- temporary capture directories ---------------------------------------------------------------

def test_the_temporary_directory_is_removed_after_a_run_and_after_a_failure(tmp_path, monkeypatch):
    import tempfile
    pytest.importorskip("PIL")
    made = []

    def fake_mkdtemp(prefix=""):
        d = tmp_path / f"{prefix}{len(made)}"
        d.mkdir()
        made.append(d)
        return str(d)
    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)
    repo = make_repo(tmp_path)
    cfg = ux.load_tour_config(repo)
    r = FakeRunner(tmp_path)
    doc = ux.run_shots(repo, manifest_of(), cfg, r, derived=tmp_path / "dd")
    assert doc["status"] == "complete" and len(made) == 1 and not made[0].exists()
    assert (repo / "design" / "shots" / "en-light" / "today.loaded.png").is_file()     # the shots were copied out first
    with pytest.raises(ux.TourFailed):                                                  # a failed build cleans up too
        ux.run_shots(repo, manifest_of(), cfg, FakeRunner(tmp_path, build_rc=65), derived=tmp_path / "dd")
    assert len(made) == 2 and not made[1].exists()
    class Boom(FakeRunner):
        def run(self, argv, **kw):
            if argv[0] == "xcodebuild" and "test-without-building" in argv:
                raise RuntimeError("boom")
            return super().run(argv, **kw)
    with pytest.raises(RuntimeError):
        ux.run_shots(repo, manifest_of(), cfg, Boom(tmp_path), derived=tmp_path / "dd")
    assert len(made) == 3 and not made[2].exists()


def test_a_given_work_dir_loses_its_bundles_and_attachments_but_not_other_files(tmp_path):
    pytest.importorskip("PIL")
    work = tmp_path / "work"
    work.mkdir()
    (work / "mine.txt").write_text("keep")
    repo = make_repo(tmp_path)
    ux.run_shots(repo, manifest_of(), ux.load_tour_config(repo), FakeRunner(tmp_path), work_dir=work, derived=tmp_path / "dd")
    assert [p.name for p in work.iterdir()] == ["mine.txt"]


def test_keep_temp_keeps_the_directory_and_says_where(tmp_path, monkeypatch, capsys):
    import tempfile
    pytest.importorskip("PIL")
    kept = tmp_path / "kept"
    kept.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(kept))
    repo = make_repo(tmp_path)
    args = cli.build_parser().parse_args(["ux", "shots", str(repo), "--keep-temp"])
    assert ux.cmd(args, runner=FakeRunner(tmp_path)) == 0
    out = capsys.readouterr().out
    assert f"kept (--keep-temp): {kept}" in out
    assert (kept / "run-1.xcresult").exists() and (kept / "attachments-3").is_dir()


# --- teyla ux diff -------------------------------------------------------------------------------

def shots_dirs(repo):
    s = repo / "design" / "shots"
    return s, s / "baseline"


def test_diff_clean_changed_new_missing(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    for v in ("en-light", "en-dark"):
        png(base / v / "today.loaded.png")
        png(run / v / "today.loaded.png")
    png(base / "en-light" / "gone.loaded.png")
    png(run / "en-light" / "places.loaded.png")                      # new
    png(run / "en-dark" / "today.loaded.png", patch=((30, 60, 80, 120), (0, 0, 0)))   # 3000 of 20000 px = 15%
    assert cli.main(["ux", "diff", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "changed (1)" in out and "en-dark/today.loaded" in out and "15.000%" in out
    assert "new, no baseline (1)" in out and "en-light/places.loaded" in out
    assert "missing" in out and "en-light/gone.loaded" in out
    assert (repo / "design" / "shots" / "diff" / "en-dark" / "today.loaded.png").is_file()
    assert "drift" not in out


def write_all(root, color=(255, 255, 255)):
    """Every capture the example manifest lists: 5 screens x 6 variants."""
    m = manifest_of()
    for v in m.variants():
        for sc in m.screens:
            png(root / v / f"{sc.id}.png", color=color)


def test_diff_clean_run_says_no_diff_on_the_manifests_screens(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    assert cli.main(["ux", "diff", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "30 compared, 30 unchanged" in out
    assert "no diff on the manifest's screens (5 screens x 6 variants)" in out
    assert "drift" not in out.replace("no drift", "")


def test_diff_with_zero_screenshots_is_not_clean(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    assert cli.main(["ux", "diff", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "missing, not in the run (30)" in out
    assert "no diff on the manifest's screens" not in out


def test_diff_a_manifest_screen_absent_from_run_and_baseline_is_missing(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    (run / "es-dark" / "places.listening.png").unlink()
    (base / "es-dark" / "places.listening.png").unlink()
    report = ux.diff_repo(repo, manifest_of())
    assert report.missing == [("es-dark", "places.listening")] and not report.covers_manifest
    assert report.manifest_compared == 29 and report.manifest_total == 30
    assert cli.main(["ux", "diff", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "es-dark/places.listening" in out and "no diff on the manifest's screens" not in out


def test_diff_clean_message_needs_every_manifest_screen_compared(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    m = manifest_of()
    report = ux.diff_repo(repo, m)
    assert report.covers_manifest and "no diff on the manifest's screens" in ux.render_diff(report, m)
    report.manifest_compared -= 1                     # a verdict over fewer screens than the manifest lists
    assert "no diff on the manifest's screens" not in ux.render_diff(report, m)


def test_diff_threshold_is_per_screen(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    patch = ((0, 160, 10, 170), (0, 0, 0))          # 100 of 20000 px = 0.5%
    for sid in ("today.error", "places.loaded"):    # limits: 2% and the default 0.2%
        png(base / "en-light" / f"{sid}.png")
        png(run / "en-light" / f"{sid}.png", patch=patch)
    report = ux.diff_repo(repo, manifest_of())
    assert [d.screen for d in report.changed] == ["places.loaded"] and report.unchanged == 1


def test_diff_channel_tolerance_ignores_antialiasing_noise(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    png(base / "en-light" / "today.loaded.png", color=(100, 100, 100))
    png(run / "en-light" / "today.loaded.png", color=(104, 100, 100))     # within tolerance 8
    assert not ux.diff_repo(repo, manifest_of()).dirty
    png(run / "en-light" / "today.loaded.png", color=(130, 100, 100))
    assert ux.diff_repo(repo, manifest_of()).changed


def test_diff_masks_hide_a_changing_clock(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    png(base / "en-light" / "today.loaded.png")
    png(run / "en-light" / "today.loaded.png", patch=((20, 2, 80, 18), (0, 0, 0)))    # inside mask `clock` (0,0,100,20)
    assert not ux.diff_repo(repo, manifest_of()).dirty
    # the same change on a screen whose masks do not cover it is a diff
    png(base / "en-light" / "places.loaded.png")
    png(run / "en-light" / "places.loaded.png", patch=((20, 2, 80, 18), (0, 0, 0)))
    assert [d.screen for d in ux.diff_repo(repo, manifest_of()).changed] == ["places.loaded"]


def test_diff_masks_scale_with_the_screenshot_width(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    write_all(base)
    write_all(run)
    png(base / "en-light" / "today.loaded.png", size=(300, 600))
    png(run / "en-light" / "today.loaded.png", size=(300, 600), patch=((90, 6, 210, 54), (0, 0, 0)))   # the clock at 3x
    assert not ux.diff_repo(repo, manifest_of()).dirty


def test_diff_size_change_is_a_change(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    png(base / "en-light" / "today.loaded.png", size=(100, 200))
    png(run / "en-light" / "today.loaded.png", size=(100, 210))
    report = ux.diff_repo(repo, manifest_of())
    assert report.changed and report.changed[0].reason == "size changed"
    assert (repo / report.changed[0].image).is_file()


def test_diff_lists_unstable_screens_from_run_json(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, base = shots_dirs(repo)
    png(base / "en-light" / "today.loaded.png")
    png(run / "en-light" / "today.loaded.png")
    (run / "run.json").write_text(json.dumps({"unstable": ["en-light/today.loaded"]}))
    assert cli.main(["ux", "diff", str(repo)]) == 1
    assert "unstable" in capsys.readouterr().out


def test_diff_without_a_baseline_lists_everything_as_new(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    run, _ = shots_dirs(repo)
    png(run / "en-light" / "today.loaded.png")
    report = ux.diff_repo(repo, manifest_of())
    assert report.new == [("en-light", "today.loaded")] and report.dirty


def test_diff_removes_the_previous_side_by_sides(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    stale = repo / "design" / "shots" / "diff" / "en-light" / "old.loaded.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x")
    ux.diff_repo(repo, manifest_of())
    assert not stale.exists()


def test_diff_names_the_install_hint_without_pillow(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert cli.main(["ux", "diff", str(repo)]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "needs Pillow" in err and "--with pillow" in err


# --- teyla ux accept -----------------------------------------------------------------------------

def finished_run(repo, unstable=(), status="complete", full=False, **extra):
    run, _ = shots_dirs(repo)
    if full:
        write_all(run, color=(1, 2, 3))
    else:
        png(run / "en-light" / "today.loaded.png", color=(1, 2, 3))
        png(run / "en-dark" / "today.loaded.png", color=(4, 5, 6))
    (run / "run.json").write_text(json.dumps({"status": status, "unstable": list(unstable), "started": "2026-01-15T09:00:00Z",
                                              "commit": "abc123", "manifest_sha256": "f00", **extra}))


def test_accept_refuses_without_yes(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    finished_run(repo)
    assert cli.main(["ux", "accept", str(repo)]) == 2
    assert "--yes" in capsys.readouterr().err
    assert not (repo / "design" / "shots" / "baseline").exists()


def test_accept_copies_the_run_and_records_who_and_when(tmp_path, capsys, monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.setattr(ux, "_who", lambda: "Test Owner")
    repo = make_repo(tmp_path)
    finished_run(repo, full=True)
    base = repo / "design" / "shots" / "baseline"
    (base / "en-light").mkdir(parents=True)
    (base / "en-light" / "stale.loaded.png").write_bytes(b"old")
    assert cli.main(["ux", "accept", str(repo), "--yes"]) == 0
    assert (base / "en-light" / "today.loaded.png").is_file() and (base / "en-dark" / "today.loaded.png").is_file()
    assert not (base / "en-light" / "stale.loaded.png").exists()
    rec = json.loads((base / "ACCEPTED.json").read_text())
    assert rec["accepted_by"] == "Test Owner" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec["accepted_at"])
    assert rec["screens"] == 30 and len(rec["variants"]) == 6 and rec["run_commit"] == "abc123"
    assert not (repo / "design" / "shots" / "baseline.new").exists() and not (repo / "design" / "shots" / "baseline.old").exists()
    assert "Test Owner" in capsys.readouterr().out
    # the diff against the new baseline is clean
    assert cli.main(["ux", "diff", str(repo)]) == 0


def test_accept_refuses_unstable_partial_and_missing_runs(tmp_path, capsys):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    assert cli.main(["ux", "accept", str(repo), "--yes"]) == 2
    assert "run `teyla ux shots` first" in capsys.readouterr().err
    finished_run(repo, unstable=["en-light/today.loaded"])
    assert cli.main(["ux", "accept", str(repo), "--yes"]) == 2
    assert "unstable" in capsys.readouterr().err
    assert cli.main(["ux", "accept", str(repo), "--yes", "--allow-unstable"]) == 0
    rec = json.loads((repo / "design" / "shots" / "baseline" / "ACCEPTED.json").read_text())
    assert rec["unstable_accepted"] == ["en-light/today.loaded"]
    finished_run(repo, status="budget")
    assert cli.main(["ux", "accept", str(repo), "--yes"]) == 2
    assert "not complete" in capsys.readouterr().err


def test_one_repo_at_a_time(tmp_path, capsys):
    a, b = make_repo(tmp_path, name="a"), make_repo(tmp_path, name="b")
    assert cli.main(["ux", "diff", str(a), str(b)]) == 2
    assert "one repo at a time" in capsys.readouterr().err


# --- the template and the docs -------------------------------------------------------------------

def test_the_tour_template_matches_the_contract():
    swift = (ROOT / "templates" / "design" / "ScreenshotTour.swift").read_text()
    for needle in ("TEYLA_TOUR_PLAN", "performAccessibilityAudit", "-tour-route", "-tour-state", "-tour-date", "-tour-seed",
                   "-tour-stub-network", "tour-ready", "elements", "audit", "__"):
        assert needle in swift, needle
    # every look the module can name is one the template can launch with
    assert "UIPreferredContentSizeCategoryName" in swift and "AppleInterfaceStyle" in swift and "AppleLanguages" in swift


def test_matrix_doc_documents_every_flag_and_exit_code():
    doc = (ROOT / "docs" / "MATRIX.md").read_text()
    for needle in ("--check-manifest", "--dry", "--runs", "--budget-min", "--keep-temp", "--allow-unstable", "--yes", "design/shots/run.json",
                   "ACCEPTED.json", "xcodebuild build-for-testing", "teyla load --admit build", "no diff on the manifest's screens"):
        assert needle in doc, needle


def test_write_shots_replaces_only_variant_folders(tmp_path):
    pytest.importorskip("PIL")
    repo = make_repo(tmp_path)
    root = repo / "design" / "shots"
    for d in ("en-light", "baseline", "notes"):
        (root / d).mkdir(parents=True)
        (root / d / "keep.txt").write_text("x")
    (root / "en-light" / "stale.loaded.png").write_bytes(b"old")
    write_export(tmp_path / "x", {("en-light", "today.loaded"): (1, 1, 1)})
    caps = ux.parse_export(tmp_path / "x")
    ux.write_shots(repo, caps, manifest_of(), {"variants": []})
    assert (root / "en-light" / "today.loaded.png").is_file() and not (root / "en-light" / "stale.loaded.png").exists()
    assert (root / "baseline" / "keep.txt").is_file() and (root / "notes" / "keep.txt").is_file()


def test_a_booted_simulator_that_crash_loops_is_booted_fresh_not_reused(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    devices = json.loads(json.dumps(DEVICES))
    devices["devices"]["com.apple.CoreSimulator.SimRuntime.iOS-18-2"][0]["state"] = "Booted"
    loops = iter([5, 0])   # broken as found; healthy after our own boot
    monkeypatch.setattr(ux.storage_sims, "crash_looping", lambda udid: next(loops))
    r = FakeRunner(tmp_path, devices=devices)
    go(tmp_path, r)
    order = [c[2] for c in r.calls if c[:2] == ["xcrun", "simctl"] and c[2] in ("shutdown", "boot")]
    assert order == ["shutdown", "boot", "shutdown"], "shut down the broken boot, boot ours, shut ours down at the end"


def test_a_boot_that_crash_loops_is_tried_once_more_then_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ux.storage_sims, "crash_looping", lambda udid: 3)
    r = FakeRunner(tmp_path)
    with pytest.raises(ux.SimulatorError, match="SpringBoard crashed 3x after each of two boots"):
        go(tmp_path, r)
    assert len(r.issued("simctl", "boot")) == 2
    assert not r.issued("xcodebuild", "test-without-building")
