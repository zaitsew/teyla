"""teyla deps: lockfile parsers, the OSV answer (replaced, so nothing here touches the network), severity, exits,
the one-day cache, --dry, safe mode, gaps and the weekly line."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from teyla import cli, deps, routine_install

VEC_CRIT = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"           # 9.8
VEC_LOW = "CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N"            # 1.8

LOCK = {"lockfileVersion": 3, "packages": {
    "": {"name": "acme-app", "version": "1.0.0"},
    "node_modules/left-pad": {"version": "1.3.0"},
    "node_modules/@acme/widgets": {"version": "4.1.0"},
    "node_modules/a/node_modules/acme-utils": {"version": "2.0.0"},
    "node_modules/acme-link": {"resolved": "packages/acme-link", "link": True},
    "node_modules/acme-core": {"version": "0.9.0"},
    "node_modules/acme-fine": {"version": "3.0.0"}}}

VULNS = {
    "GHSA-aaaa-bbbb-cccc": {"id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2026-0001"], "summary": "Prototype pollution",
        "severity": [{"type": "CVSS_V3", "score": VEC_CRIT}],
        "affected": [{"package": {"name": "left-pad", "ecosystem": "npm"},
                      "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.3.1"}]}]}]},
    "GHSA-dddd-eeee-ffff": {"id": "GHSA-dddd-eeee-ffff", "aliases": [], "summary": "Minor leak",
        "severity": [{"type": "CVSS_V3", "score": VEC_LOW}],
        "affected": [{"package": {"name": "acme-utils", "ecosystem": "npm"},
                      "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "2.0.1"}]}]}]},
    "GHSA-gggg-hhhh-iiii": {"id": "GHSA-gggg-hhhh-iiii", "aliases": ["CVE-2026-0003"], "summary": "Denial of service",
        "database_specific": {"severity": "HIGH"},
        "affected": [{"package": {"name": "acme-core", "ecosystem": "npm"},
                      "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}]}]}]},
    # the same flaw as the first, under another id: counted once
    "PYSEC-2026-1": {"id": "PYSEC-2026-1", "aliases": ["CVE-2026-0001"],
        "affected": [{"package": {"name": "left-pad", "ecosystem": "npm"},
                      "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.3.1"}]}]}]},
}
HITS = {"left-pad": ["GHSA-aaaa-bbbb-cccc", "PYSEC-2026-1"], "acme-utils": ["GHSA-dddd-eeee-ffff"], "acme-core": ["GHSA-gggg-hhhh-iiii"]}


class FakeOsv:
    def __init__(self, hits=None, vulns=None, fail=None):
        self.hits, self.vulns, self.fail, self.calls = HITS if hits is None else hits, VULNS if vulns is None else vulns, fail, []

    def __call__(self, url, payload=None):
        self.calls.append((url, payload))
        if self.fail:
            raise self.fail
        if url.endswith("/v1/querybatch"):
            return {"results": [{"vulns": [{"id": i, "modified": "2026-10-01T00:00:00Z"} for i in self.hits.get(q["package"]["name"], [])]}
                                for q in payload["queries"]]}
        return self.vulns[url.rsplit("/", 1)[1]]


@pytest.fixture
def osv(monkeypatch):
    f = FakeOsv()
    monkeypatch.setattr(deps, "_fetch", f)
    return f


def repo(tmp_path, files, name="acme-app"):
    r = tmp_path / name
    (r / ".git").mkdir(parents=True)
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if isinstance(text, str) else json.dumps(text))
    return r


# --- parsers ------------------------------------------------------------------------------------

def test_package_lock_v3_keeps_nested_scoped_and_skips_links_and_the_root():
    pk, notes = deps.parse_package_lock(json.dumps(LOCK))
    assert ("npm", "left-pad", "1.3.0") in pk and ("npm", "@acme/widgets", "4.1.0") in pk
    assert ("npm", "acme-utils", "2.0.0") in pk and not any(p[1] in ("acme-link", "acme-app") for p in pk)
    assert notes == []


def test_package_lock_v1_and_broken_json():
    v1 = {"lockfileVersion": 1, "dependencies": {"left-pad": {"version": "1.3.0", "dependencies": {"acme-utils": {"version": "2.0.0"}}}}}
    assert deps.parse_package_lock(json.dumps(v1))[0] == [("npm", "left-pad", "1.3.0"), ("npm", "acme-utils", "2.0.0")]
    pk, notes = deps.parse_package_lock("{nope")
    assert pk == [] and "not valid JSON" in notes[0]


def test_pnpm_lock_reads_v5_v6_and_v9_keys():
    text = """lockfileVersion: '9.0'

importers:
  .:
    dependencies:
      left-pad:
        specifier: ^1.3.0

packages:

  left-pad@1.3.0:
    resolution: {integrity: sha512-x}

  '@acme/widgets@4.1.0':
    resolution: {integrity: sha512-y}

  /acme-utils@2.0.0(acme-core@0.9.0):
    resolution: {integrity: sha512-z}

  /acme-old/1.2.3_acme-core@0.9.0:
    resolution: {integrity: sha512-w}

  /@acme/legacy/0.4.0:
    resolution: {integrity: sha512-v}

snapshots:

  left-pad@1.3.0: {}
"""
    pk, _ = deps.parse_pnpm_lock(text)
    assert sorted(pk) == [("npm", "@acme/legacy", "0.4.0"), ("npm", "@acme/widgets", "4.1.0"), ("npm", "acme-old", "1.2.3"),
                          ("npm", "acme-utils", "2.0.0"), ("npm", "left-pad", "1.3.0")]


def test_yarn_lock_classic_and_berry():
    classic = '''# yarn lockfile v1


"@acme/widgets@^4.0.0", "@acme/widgets@^4.1.0":
  version "4.1.0"
  resolved "https://registry.example.com/x.tgz"
  dependencies:
    version "^1.0.0"

left-pad@^1.0.0:
  version "1.3.0"
'''
    assert deps.parse_yarn_lock(classic)[0] == [("npm", "@acme/widgets", "4.1.0"), ("npm", "left-pad", "1.3.0")]
    berry = '''__metadata:
  version: 8

"left-pad@npm:^1.0.0":
  version: 1.3.0
  resolution: "left-pad@npm:1.3.0"

"acme-app@workspace:.":
  version: 0.0.0-use.local
'''
    assert deps.parse_yarn_lock(berry)[0] == [("npm", "left-pad", "1.3.0")]


def test_deno_lock_reads_npm_and_notes_jsr():
    lock = {"version": "4", "npm": {"left-pad@1.3.0": {"integrity": "x"}, "@acme/widgets@4.1.0_acme-core@0.9.0": {}},
            "jsr": {"@acme/std@1.0.0": {}}}
    pk, notes = deps.parse_deno_lock(json.dumps(lock))
    assert sorted(pk) == [("npm", "@acme/widgets", "4.1.0"), ("npm", "left-pad", "1.3.0")]
    assert "1 jsr package(s) skipped" in notes[0]


def test_package_resolved_v2_v1_and_skipped_pins():
    v2 = {"version": 2, "pins": [
        {"identity": "swift-acme", "kind": "remoteSourceControl", "location": "https://example.com/acme/swift-acme.git", "state": {"revision": "ab", "version": "1.2.0"}},
        {"identity": "branchy", "location": "https://example.com/acme/branchy.git", "state": {"branch": "main", "revision": "cd"}},
        {"identity": "ssh", "location": "git@example.com:acme/ssh.git", "state": {"version": "1.0.0"}}]}
    pk, notes = deps.parse_package_resolved(json.dumps(v2))
    assert pk == [("SwiftURL", "example.com/acme/swift-acme", "1.2.0")] and "2 pin(s) skipped" in notes[0]
    v1 = {"version": 1, "object": {"pins": [{"package": "A", "repositoryURL": "https://example.com/acme/a", "state": {"version": "3.0.0"}}]}}
    assert deps.parse_package_resolved(json.dumps(v1))[0] == [("SwiftURL", "example.com/acme/a", "3.0.0")]


def test_uv_and_poetry_lock():
    uv = '''version = 1
[[package]]
name = "acme-app"
version = "0.1.0"
source = { virtual = "." }

[[package]]
name = "acme-py"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }
'''
    assert deps.parse_uv_lock(uv)[0] == [("PyPI", "acme-py", "2.3.4")]
    poetry = '''[[package]]
name = "acme-py"
version = "2.3.4"

[[package]]
name = "acme-git"
version = "1.0.0"
[package.source]
type = "git"
url = "https://example.com/acme/acme-git"
'''
    assert deps.parse_poetry_lock(poetry)[0] == [("PyPI", "acme-py", "2.3.4")]
    assert "not valid TOML" in deps.parse_uv_lock("[[package")[1][0]


def test_requirements_pins_only_and_counts_the_rest():
    text = """# pinned
acme-py==2.3.4  # comment
acme-extra[fast]==1.0.0 ; python_version > "3.9"
acme-loose>=1.0
acme-bare
-r other.txt
--hash=sha256:abc
git+https://example.com/acme/x.git
"""
    pk, notes = deps.parse_requirements(text)
    assert pk == [("PyPI", "acme-py", "2.3.4"), ("PyPI", "acme-extra", "1.0.0")]
    assert notes == ["2 unpinned requirement(s) not checked (only `==` pins are)"]


def test_gemfile_lock_and_go_sum():
    gem = """GEM
  remote: https://rubygems.example.com/
  specs:
    acme-gem (7.0.1)
      acme-dep (>= 1.0)
    acme-dep (1.4.2-x86_64-linux)

GIT
  remote: https://example.com/acme/other.git
  specs:
    acme-git (0.1.0)

PLATFORMS
  ruby
"""
    assert deps.parse_gemfile_lock(gem)[0] == [("RubyGems", "acme-gem", "7.0.1"), ("RubyGems", "acme-dep", "1.4.2")]
    gosum = """example.com/acme/mod v1.2.3 h1:abc=
example.com/acme/mod v1.2.3/go.mod h1:def=
example.com/acme/old v0.9.0/go.mod h1:ghi=
example.com/acme/inc v2.0.0+incompatible h1:jkl=
"""
    assert deps.parse_go_sum(gosum)[0] == [("Go", "example.com/acme/mod", "1.2.3"), ("Go", "example.com/acme/inc", "2.0.0")]


# --- severity and versions ------------------------------------------------------------------------

def test_cvss3_scores_match_the_spec_and_other_versions_are_none():
    assert deps.cvss3_score(VEC_CRIT) == 9.8
    assert deps.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H") == 7.5
    assert deps.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == 10.0
    assert deps.cvss3_score(VEC_LOW) == 1.8
    assert deps.cvss3_score("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N") is None
    assert deps.cvss3_score("nonsense") is None


def test_severity_labels_and_fallback_word():
    assert deps.severity_of(VULNS["GHSA-aaaa-bbbb-cccc"]) == ("critical", 9.8)
    assert deps.severity_of(VULNS["GHSA-gggg-hhhh-iiii"]) == ("high", None)
    assert deps.severity_of({"database_specific": {"severity": "MODERATE"}})[0] == "medium"
    assert deps.severity_of({})[0] == "unknown"
    assert [deps.label(s) for s in (9.0, 7.0, 4.0, 0.1)] == ["critical", "high", "medium", "low"]


def test_fixed_version_is_the_lowest_one_above_the_installed():
    assert deps.pick_fixed("1.3.0", ["2.0.0", "1.3.1", "1.2.9"]) == "1.3.1"
    assert deps.pick_fixed("1.9.0", ["1.10.0"]) == "1.10.0"
    assert deps.pick_fixed("1.0.0-rc1", ["1.0.0"]) == "1.0.0"
    assert deps.pick_fixed("2.0.0", ["1.0.0"]) is None


# --- the command ----------------------------------------------------------------------------------

def test_a_critical_with_a_fix_is_a_fix_and_exit_1(tmp_path, osv, capsys):
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r)]) == 1
    out = capsys.readouterr().out
    assert "FIX  critical left-pad 1.3.0  GHSA-aaaa-bbbb-cccc / CVE-2026-0001  fixed in 1.3.1" in out
    assert "bump left-pad to 1.3.1 in package-lock.json" in out
    assert "(+1 more)" not in out                               # the PYSEC record is the same flaw
    assert "acme-utils 2.0.0  GHSA-dddd-eeee-ffff  fixed in 2.0.1" in out and "FIX  low" not in out
    assert "acme-core 0.9.0  GHSA-gggg-hhhh-iiii / CVE-2026-0003  no fix known" in out
    assert "5 package(s) checked in 1 lockfile(s), 3 vulnerable, 1 FIX" in out


def test_low_and_unfixed_are_listed_and_never_block(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deps, "_fetch", FakeOsv(hits={k: v for k, v in HITS.items() if k != "left-pad"}))
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r)]) == 0
    out = capsys.readouterr().out
    assert "FIX " not in out.replace("0 FIX", "") and "high     acme-core" in out


def test_json_report(tmp_path, osv, capsys):
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r), "--json"]) == 1
    d = json.loads(capsys.readouterr().out)
    rep = d["repos"][0]
    assert d["fix"] == 1 and d["exit"] == 1 and rep["checked"] == 5
    top = rep["vulnerable"][0]
    assert (top["name"], top["severity"], top["fixed"], top["fix"]) == ("left-pad", "critical", "1.3.1", True)


def test_only_names_ecosystems_and_versions_are_sent(tmp_path, osv):
    r = repo(tmp_path, {"package-lock.json": LOCK}, name="secret-product")
    cli.main(["deps", str(r)])
    sent = json.dumps(osv.calls)
    assert "secret-product" not in sent and str(tmp_path) not in sent and "package-lock" not in sent
    url, payload = osv.calls[0]
    assert url == "https://api.osv.dev/v1/querybatch"
    assert payload["queries"][0] == {"package": {"name": "@acme/widgets", "ecosystem": "npm"}, "version": "4.1.0"}
    assert all(set(q) == {"package", "version"} and set(q["package"]) == {"name", "ecosystem"} for q in payload["queries"])
    assert sorted(u for u, _ in osv.calls[1:]) == sorted(f"https://api.osv.dev/v1/vulns/{i}" for i in ("GHSA-aaaa-bbbb-cccc", "GHSA-dddd-eeee-ffff", "GHSA-gggg-hhhh-iiii", "PYSEC-2026-1"))


def test_batches_hold_at_most_a_thousand_queries(tmp_path, osv):
    pk = {("npm", f"acme-{i:04d}", "1.0.0") for i in range(2300)}
    deps.lookup(pk)
    sizes = [len(p["queries"]) for u, p in osv.calls if u.endswith("querybatch")]
    assert sizes == [1000, 1000, 300]


def test_cache_hit_miss_and_expiry(tmp_path, osv, capsys):
    r = repo(tmp_path, {"package-lock.json": LOCK})
    cli.main(["deps", str(r)])
    first = len(osv.calls)
    assert first == 5 and deps.cache_path().exists()
    assert oct(deps.cache_path().stat().st_mode & 0o777) == "0o600"
    capsys.readouterr()
    assert cli.main(["deps", str(r)]) == 1
    assert len(osv.calls) == first                                  # a hit: nothing asked
    assert "FIX  critical left-pad" in capsys.readouterr().out
    cli.main(["deps", str(r), "--no-cache"])
    assert len(osv.calls) == 2 * first                              # bypassed
    pk = {("npm", "left-pad", "1.3.0")}
    n = len(osv.calls)
    deps.lookup(pk, now=dt.datetime.now().timestamp() + deps.CACHE_TTL_S + 60)
    assert len(osv.calls) > n                                       # a day later: asked again
    n = len(osv.calls)
    deps.lookup({("npm", "left-pad", "1.3.0"), ("npm", "acme-new", "1.0.0")})
    assert [p["queries"][0]["package"]["name"] for u, p in osv.calls[n:] if u.endswith("querybatch")] == ["acme-new"]
    assert not any("/v1/vulns/" in u for u, _ in osv.calls[n:])     # known vulnerability ids are not fetched again


def test_dry_sends_and_writes_nothing(tmp_path, osv, capsys):
    r = repo(tmp_path, {"package-lock.json": LOCK, "uv.lock": '[[package]]\nname = "acme-py"\nversion = "2.3.4"\nsource = { registry = "x" }\n'})
    assert cli.main(["deps", str(r), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "would send 6 unique" in out and "PyPI 1" in out and "npm 5" in out and "nothing is sent or written" in out
    assert osv.calls == [] and not deps.cache_path().exists()


def test_safe_mode_refuses_without_allow_network(tmp_path, osv, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r)]) == 2
    assert "safe mode is on" in capsys.readouterr().err and osv.calls == []
    assert cli.main(["deps", str(r), "--quiet"]) == 0              # the unattended weekly run stays silent
    assert capsys.readouterr().out == "" and osv.calls == []
    assert cli.main(["deps", str(r), "--allow-network"]) == 1      # typed by hand: one call is allowed
    assert osv.calls


def test_a_manifest_without_a_lockfile_is_exit_2(tmp_path, osv, capsys):
    pkg = {"name": "acme-app", "dependencies": {"left-pad": "^1.0.0"}}
    r = repo(tmp_path, {"package.json": pkg})
    assert cli.main(["deps", str(r)]) == 2
    out = capsys.readouterr().out
    assert "GAP  package.json: no lockfile" in out and osv.calls == []
    # a lockfile above it covers a workspace package; a package.json with no dependencies is not a gap
    r2 = repo(tmp_path, {"package-lock.json": LOCK, "apps/web/package.json": pkg, "tools/package.json": {"name": "x"}}, name="mono")
    assert cli.main(["deps", str(r2)]) == 1
    r3 = repo(tmp_path, {"pyproject.toml": '[project]\nname = "acme-py"\ndependencies = ["acme-dep>=1"]\n'}, name="py")
    assert cli.main(["deps", str(r3)]) == 2
    assert "pyproject.toml: no lockfile (uv.lock or poetry.lock)" in capsys.readouterr().out
    r4 = repo(tmp_path, {"Package.swift": '// swift-tools\nlet p = Package(dependencies: [.package(url: "https://example.com/a/b", from: "1.0.0")])',
                         "Gemfile": 'source "x"\ngem "acme-gem"\n', "go.mod": "module example.com/acme\n\nrequire example.com/acme/mod v1.2.3\n"}, name="poly")
    assert cli.main(["deps", str(r4)]) == 2
    out = capsys.readouterr().out
    assert "Package.swift: no Package.resolved" in out and "Gemfile: no Gemfile.lock" in out and "go.mod: no go.sum" in out


def test_a_repo_with_nothing_to_check_is_exit_0(tmp_path, osv, capsys):
    r = repo(tmp_path, {"README.md": "# docs\n"})
    assert cli.main(["deps", str(r)]) == 0
    assert "no lockfile to check" in capsys.readouterr().out and osv.calls == []


def test_osv_unreachable_is_exit_2_and_says_what_was_not_covered(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deps, "_fetch", FakeOsv(fail=deps.OsvError("timed out")))
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r)]) == 2
    cap = capsys.readouterr()
    assert "OSV unreachable (timed out)" in cap.err and "NOT checked" in cap.out
    assert not deps.cache_path().exists()


def test_an_ecosystem_osv_rejects_is_not_covered_and_the_rest_is_still_checked(tmp_path, monkeypatch, capsys):
    ok = FakeOsv()

    def fake(url, payload=None):
        if payload and payload["queries"][0]["package"]["ecosystem"] == "SwiftURL":
            raise deps.OsvError("HTTP 400", 400)
        return ok(url, payload)

    monkeypatch.setattr(deps, "_fetch", fake)
    resolved = {"version": 2, "pins": [{"location": "https://example.com/acme/swift-acme.git", "state": {"version": "1.2.0"}}]}
    r = repo(tmp_path, {"package-lock.json": LOCK, "Package.resolved": resolved})
    assert cli.main(["deps", str(r)]) == 2                           # the rest was checked; the rejected one is not covered
    out = capsys.readouterr().out
    assert "OSV did not answer for 1 SwiftURL package(s): not covered" in out and "NOT COVERED  1 package(s)" in out
    assert "FIX  critical left-pad" in out


def test_all_prints_a_table_the_worst_exit_and_writes_the_summary(tmp_path, osv, monkeypatch, capsys):
    a = repo(tmp_path, {"package-lock.json": LOCK}, name="alpha")
    b = repo(tmp_path, {"package.json": {"dependencies": {"x": "1"}}}, name="beta")
    c = repo(tmp_path, {"README.md": "x"}, name="gamma")
    from teyla import lang
    monkeypatch.setattr(lang, "resolve_repos", lambda args, cfg=None: [a, b, c])
    assert cli.main(["deps", "--all"]) == 2                          # beta has a gap: 2 outranks alpha's 1
    out = capsys.readouterr().out
    assert "alpha  " in out and "1 FIX, 1 gap(s), 0 package(s) not covered; exit 2" in out and "gamma: no lockfile" not in out
    s = json.loads(deps.summary_path().read_text())
    assert s["fix"] == 1 and s["fix_repos"] == 1 and s["gaps"] == 1
    assert deps.digest_candidates()[0]["text"] == "dependency FIX: 1 vulnerable package(s) with a fixed version in 1 repo(s)"
    assert cli.main(["deps", "--all", "--quiet"]) == 2
    quiet = capsys.readouterr().out
    assert "FIX  critical left-pad" in quiet and "GAP  package.json" in quiet and "acme-utils" not in quiet and "alpha  " not in quiet


def test_digest_line_is_absent_without_a_fix_or_when_old(tmp_path):
    assert deps.digest_candidates() == []
    deps.write_summary([{"fix": 0, "gaps": [], "repo": "x"}])
    assert deps.digest_candidates() == []
    deps.write_summary([{"fix": 2, "gaps": [], "repo": "x"}])
    assert deps.digest_candidates()
    old = json.loads(deps.summary_path().read_text())
    old["at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    deps.summary_path().write_text(json.dumps(old))
    assert deps.digest_candidates() == []


def test_a_single_repo_run_does_not_write_the_weekly_summary(tmp_path, osv):
    r = repo(tmp_path, {"package-lock.json": LOCK})
    cli.main(["deps", str(r)])
    assert not deps.summary_path().exists()


def test_not_a_git_repo_is_exit_2(tmp_path, osv, capsys):
    assert cli.main(["deps", str(tmp_path)]) == 2
    assert "not a git repository" in capsys.readouterr().err


# --- the weekly routine -----------------------------------------------------------------------------

def _wrapper():
    return routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=routine_install._watch_line())


def test_the_weekly_wrapper_runs_deps_before_the_digest_and_an_old_wrapper_is_stale(tmp_path, monkeypatch):
    text = _wrapper()
    assert '"$TEYLA" deps --all --quiet > "$OUT_DIR/deps.md" 2>&1' in text
    assert text.index("scout design") < text.index("deps --all") < text.index("digest --write")
    w = tmp_path / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(text)
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(text.replace('"$TEYLA" deps --all --quiet > "$OUT_DIR/deps.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")


# --- review fixes -----------------------------------------------------------------------------------

def test_userinfo_in_a_swift_url_is_never_sent_and_is_noted_without_the_value(tmp_path, osv, capsys):
    resolved = {"version": 2, "pins": [
        {"location": "https://deploy:s3cr3t-token@example.com/acme/swift-acme.git?ref=x#frag", "state": {"version": "1.2.0"}},
        {"location": "https://onlytoken@example.com:8443/acme/other", "state": {"version": "2.0.0"}}]}
    r = repo(tmp_path, {"Package.resolved": resolved})
    cli.main(["deps", str(r)])
    cap = capsys.readouterr()
    sent = json.dumps(osv.calls)
    assert "s3cr3t-token" not in sent and "deploy" not in sent and "onlytoken" not in sent
    assert "@" not in sent and "?ref" not in sent and "frag" not in sent
    names = [q["package"]["name"] for u, p in osv.calls if p for q in p["queries"]]
    assert names == ["example.com/acme/swift-acme", "example.com:8443/acme/other"]
    assert "credential in lockfile" in cap.out and "s3cr3t-token" not in cap.out + cap.err and "onlytoken" not in cap.out + cap.err
    assert deps.clean_url("ssh://git@example.com/a/b") is None and deps.clean_url("https://example.com") is None


def test_requirements_named_like_http_are_read_and_url_lines_are_not():
    text = ("httpx==0.27.0\nhttpcore==1.0.5\nhttplib2==0.22.0\nacme @ https://example.com/acme.zip\n"
            "-e git+https://example.com/a/b.git#egg=b\n")
    pk, notes = deps.parse_requirements(text)
    assert pk == [("PyPI", "httpx", "0.27.0"), ("PyPI", "httpcore", "1.0.5"), ("PyPI", "httplib2", "0.22.0")] and notes == []


def test_deno_lock_v3_v2_and_an_unknown_shape():
    v3 = {"version": "3", "packages": {"specifiers": {"npm:left-pad@1": "npm:left-pad@1.3.0"}, "npm": {"left-pad@1.3.0": {}}, "jsr": {"@acme/std@1.0.0": {}}}}
    pk, notes = deps.parse_deno_lock(json.dumps(v3))
    assert pk == [("npm", "left-pad", "1.3.0")] and "1 jsr package(s) skipped" in notes[0]
    v2 = {"version": "2", "npm": {"specifiers": {"left-pad@1": "left-pad@1.3.0"}, "packages": {"left-pad@1.3.0": {}}}}
    assert deps.parse_deno_lock(json.dumps(v2))[0] == [("npm", "left-pad", "1.3.0")]
    pk, notes = deps.parse_deno_lock(json.dumps({"version": "9", "mystery": {}}))
    assert pk == [] and "unrecognised shape (version 9)" in notes[0]
    assert deps.parse_deno_lock(json.dumps({"version": "4"}))[1] != []


def test_yarn_aliases_resolve_to_the_real_package():
    classic = '''"alias@npm:left-pad@^1.0.0":
  version "1.3.0"

"scoped-alias@npm:@acme/widgets@^4.0.0":
  version "4.1.0"

"plain@npm:^2.0.0":
  version "2.0.1"
'''
    assert deps.parse_yarn_lock(classic)[0] == [("npm", "left-pad", "1.3.0"), ("npm", "@acme/widgets", "4.1.0"), ("npm", "plain", "2.0.1")]


def test_pagination_is_followed_before_anything_is_cached(tmp_path, monkeypatch):
    calls = []

    def fake(url, payload=None):
        calls.append((url, payload))
        if url.endswith("querybatch"):
            q = payload["queries"][0]
            tok = q.get("page_token")
            if tok is None:
                return {"results": [{"vulns": [{"id": "GHSA-aaaa-bbbb-cccc"}], "next_page_token": "t1"}]}
            return {"results": [{"vulns": [{"id": "PYSEC-2026-1"}]}]}
        return VULNS[url.rsplit("/", 1)[1]]

    monkeypatch.setattr(deps, "_fetch", fake)
    found, _ = deps.lookup({("npm", "left-pad", "1.3.0")})
    assert calls[1][1]["queries"][0]["page_token"] == "t1"
    assert len(found[("npm", "left-pad", "1.3.0")]) == 1                # both ids are one flaw
    assert json.loads(deps.cache_path().read_text())["q"]["npm\x00left-pad\x001.3.0"]["ids"] == ["GHSA-aaaa-bbbb-cccc", "PYSEC-2026-1"]


def test_pages_that_never_end_are_not_covered_and_not_cached(monkeypatch):
    def fake(url, payload=None):
        return {"results": [{"vulns": [], "next_page_token": "again"} for _ in payload["queries"]]}

    monkeypatch.setattr(deps, "_fetch", fake)
    found, _ = deps.lookup({("npm", "left-pad", "1.3.0")})
    assert found == {} and "left-pad" not in (deps.cache_path().read_text() if deps.cache_path().exists() else "")


def test_a_rejected_batch_is_split_and_only_the_bad_query_is_not_covered(tmp_path, monkeypatch, capsys):
    ok = FakeOsv()

    def fake(url, payload=None):
        if payload and any(q["package"]["name"] == "acme-bad" for q in payload["queries"]):
            raise deps.OsvError("HTTP 400", 400)
        return ok(url, payload)

    monkeypatch.setattr(deps, "_fetch", fake)
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/left-pad": {"version": "1.3.0"},
                                                 "node_modules/acme-bad": {"version": "1.0.0"}, "node_modules/acme-fine": {"version": "3.0.0"}}}
    r = repo(tmp_path, {"package-lock.json": lock})
    assert cli.main(["deps", str(r), "--json"]) == 2
    d = json.loads(capsys.readouterr().out)["repos"][0]
    assert d["checked"] == 2 and d["not_covered"] == 1 and d["fix"] == 1


def test_not_covered_exits_2_even_when_quiet_and_prints_one_line(tmp_path, monkeypatch, capsys):
    def fake(url, payload=None):
        raise deps.OsvError("HTTP 400", 400)

    monkeypatch.setattr(deps, "_fetch", fake)
    r = repo(tmp_path, {"package-lock.json": LOCK})
    assert cli.main(["deps", str(r), "--quiet"]) == 2
    out = capsys.readouterr().out
    assert "NOT COVERED  5 package(s)" in out and out.count("NOT COVERED") == 1


def test_the_split_budget_bounds_the_calls(monkeypatch):
    calls = []

    def fake(url, payload=None):
        calls.append(1)
        raise deps.OsvError("HTTP 400", 400)

    monkeypatch.setattr(deps, "_fetch", fake)
    found, notes = deps.lookup({("npm", f"acme-{i:04d}", "1.0.0") for i in range(900)})
    assert found == {} and len(calls) <= deps.MAX_SPLIT_CALLS * 2 + 2 and "900 npm package(s)" in notes[0]
