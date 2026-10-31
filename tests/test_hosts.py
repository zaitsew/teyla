"""teyla hosts: synthetic repos in tmp dirs with invented hosts. Nothing here reads a real repo or the network."""
from __future__ import annotations

import json
import pathlib
import plistlib

import pytest

from teyla import cli, hosts, scaffold

ROOT = pathlib.Path(__file__).resolve().parents[1]

TABLE = """# Privacy

| # | Trigger | Host | What is sent | Default on | Turn it off |
|---|---|---|---|---|---|
{rows}
"""


def table(*hosts_: str) -> str:
    rows = "\n".join(f"| {i} | on launch | `{h}` | a version string | Yes | a setting |" for i, h in enumerate(hosts_, 1))
    return TABLE.format(rows=rows)


def repo(tmp_path, files: dict[str, str | bytes], name="proj"):
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return d


def run(capsys, *argv):
    rc = cli.main(["hosts", *argv])
    return rc, capsys.readouterr().out


def host_names(report, key="hosts"):
    return {h["host"] for h in report[key]}


def checks(report):
    return {(f["check"], f["severity"], f["host"]) for f in report["findings"]}


SWIFT = '''import Foundation
// see https://docs.acme.test/guide for the format
let api = URL(string: "https://api.acme.test/v1/items")!
let dev = URL(string: "http://127.0.0.1:8080/health")!
let user = "https://\\(region).edge.acme.test/ping"
'''

TS = '''import { serve } from "https://deno.acme.test/std@1/http/server.ts";
const cdn = "https://cdn.acme.test/lib.js";
const hook = process.env.PAYMENTS_URL;
/* https://commented.acme.test/ignored */
export async function go(ref: string) {
  await fetch(`https://${ref}.supabase.acme.test/rest/v1/items`);
  await fetch(`https://${base}/computed`);
}
'''

PY = '''"""Talks to https://docstring.acme.test only in this docstring."""
import http.client
import os

# https://comment.acme.test/never
URL = "https://pyapi.acme.test/v2"
conn = http.client.HTTPSConnection("conn.acme.test")
TOKEN_URL = os.environ["AUTH_URL"]
'''


# --- extraction --------------------------------------------------------------------------------------

def test_extracts_hosts_by_file_and_line_across_languages(tmp_path):
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT, "web/app.ts": TS, "svc/client.py": PY,
                        "docs/PRIVACY.md": table("nothing.acme.test")})
    r = hosts.check_repo(d)
    found = {h["host"]: h["refs"][0] for h in r["hosts"]}
    assert found["api.acme.test"] == {"file": "Sources/Net.swift", "line": 3, "how": "literal"}
    assert found["cdn.acme.test"]["file"] == "web/app.ts" and found["cdn.acme.test"]["line"] == 2
    assert found["pyapi.acme.test"] == {"file": "svc/client.py", "line": 6, "how": "literal"}
    assert found["conn.acme.test"]["line"] == 7
    assert found["deno.acme.test"]["file"] == "web/app.ts"
    assert "*.edge.acme.test" in found and "*.supabase.acme.test" in found       # an interpolated first label
    for ignored in ("docs.acme.test", "commented.acme.test", "docstring.acme.test", "comment.acme.test"):
        assert ignored not in found                                                # comments and docstrings


def test_computed_urls_and_env_names_are_reported_not_judged(tmp_path):
    d = repo(tmp_path, {"web/app.ts": TS, "svc/client.py": PY, "docs/PRIVACY.md": table("x.acme.test")})
    r = hosts.check_repo(d)
    assert r["coverage"]["computed_urls"] >= 1                                    # `https://${base}/computed`
    names = {e["name"] for e in r["env_provided"]}
    assert names == {"PAYMENTS_URL", "AUTH_URL"}
    assert not any(f["host"] in names for f in r["findings"])


def test_manifests_plist_next_config_and_env_example(tmp_path):
    plist = plistlib.dumps({"NSAppTransportSecurity": {"NSExceptionDomains": {
        "legacy.acme.test": {"NSExceptionAllowsInsecureHTTPLoads": True}}}, "SUFeedURL": "https://updates.acme.test/feed.xml"})
    nxt = "module.exports = {\n  images: {\n    domains: ['img.acme.test'],\n    remotePatterns: [{ protocol: 'https', hostname: '**.photos.acme.test' }],\n  },\n};\n"
    d = repo(tmp_path, {"App/Info.plist": plist, "web/next.config.js": nxt,
                        ".env.example": "API_BASE=https://env.acme.test/v1\nEMPTY=\nNAME=plain\n",
                        "vercel.json": json.dumps({"rewrites": [{"source": "/a", "destination": "https://edge.acme.test/a"}]}),
                        "supabase/config.toml": '[auth]\nsite_url = "https://site.acme.test"\n',
                        "app/src/main/res/xml/network_security_config.xml":
                            '<network-security-config><domain-config cleartextTrafficPermitted="true"><domain>droid.acme.test</domain></domain-config></network-security-config>',
                        "docs/PRIVACY.md": table("nothing.acme.test")})
    r = hosts.check_repo(d)
    got = {h["host"]: h["refs"][0] for h in r["hosts"]}
    assert got["legacy.acme.test"]["file"] == "App/Info.plist" and got["legacy.acme.test"]["line"] > 0
    assert got["updates.acme.test"]["file"] == "App/Info.plist"
    assert got["img.acme.test"] == {"file": "web/next.config.js", "line": 3, "how": "images.domains"}
    assert got["*.photos.acme.test"]["line"] == 4
    assert got["env.acme.test"] == {"file": ".env.example", "line": 1, "how": "env-provided"}
    assert got["edge.acme.test"]["file"] == "vercel.json"
    assert got["site.acme.test"]["file"] == "supabase/config.toml" and got["site.acme.test"]["line"] == 2
    assert got["droid.acme.test"]["file"].endswith("network_security_config.xml")
    assert ("cleartext", "WARN", "legacy.acme.test") in checks(r)                  # ATS exception to plain HTTP
    assert any(f["check"] == "cleartext" and "droid.acme.test" in f["host"] for f in r["findings"])


def test_loopback_private_and_placeholder_hosts_are_never_findings(tmp_path):
    src = '''let a = "http://127.0.0.1:3000"
let b = "http://localhost:8080/x"
let c = "http://192.168.1.20/x"
let d = "http://10.0.2.2:54321"
let e = "http://[::1]:9/"
let f = "https://example.com/terms"
let g = "https://example.test/x"
let h = "http://printer.local/x"
let i = "https://cdn.example.com/lib.js"
let j = "http://www.w3.org/2000/svg"
let k = "https://real.acme.test/x"
'''
    d = repo(tmp_path, {"A.swift": src, "docs/PRIVACY.md": table("real.acme.test")})
    r = hosts.check_repo(d)
    assert host_names(r) == {"real.acme.test"}
    assert host_names(r, "local") == {"127.0.0.1", "192.168.1.20", "10.0.2.2", "[::1]"}
    assert r["findings"] == []


def test_tests_build_output_and_comments_are_skipped_and_named_in_coverage(tmp_path):
    d = repo(tmp_path, {
        "src/a.ts": "const u = 'https://live.acme.test/a';\n",
        "tests/a.test.ts": "const u = 'https://intests.acme.test/a';\n",
        "src/b.test.ts": "const u = 'https://beside.acme.test/a';\n",
        "node_modules/x/index.js": "const u = 'https://dep.acme.test/a';\n",
        "AppTests/T.swift": 'let u = "https://swifttest.acme.test"\n',
        "test_x.py": "U = 'https://pytest.acme.test'\n",
        "docs/PRIVACY.md": table("live.acme.test")})
    r = hosts.check_repo(d)
    assert host_names(r) == {"live.acme.test"}
    cov = r["coverage"]
    assert {"tests", "node_modules", "AppTests"} <= set(cov["skipped_roots"])
    assert cov["test_files_skipped"] == 2 and cov["files"] == 1


# --- verdicts ----------------------------------------------------------------------------------------

def test_an_undocumented_host_is_a_fix_with_file_line_and_exit_1(tmp_path, capsys):
    d = repo(tmp_path, {"web/app.ts": TS, "docs/PRIVACY.md": table("cdn.acme.test")})
    rc, out = run(capsys, str(d))
    assert rc == 1
    assert "FIX  undocumented deno.acme.test  web/app.ts:1" in out
    assert "add a row to docs/PRIVACY.md: what is sent, when, how to turn it off" in out
    fixes = {f["host"] for f in hosts.check_repo(d)["findings"] if f["severity"] == "FIX"}
    assert fixes == {"deno.acme.test", "*.supabase.acme.test"}


def test_documented_hosts_by_exact_name_and_wildcard_suffix_are_clean(tmp_path, capsys):
    d = repo(tmp_path, {"web/app.ts": TS, "Sources/Net.swift": SWIFT,
                        "docs/PRIVACY.md": table("deno.acme.test", "cdn.acme.test", "*.supabase.acme.test",
                                                 "*.edge.acme.test", "api.acme.test")})
    rc, out = run(capsys, str(d))
    assert rc == 0, out
    assert "0 FIX, 0 WARN" in out


def test_a_documented_host_no_code_reaches_is_a_warn_and_exit_stays_0(tmp_path, capsys):
    d = repo(tmp_path, {"a.ts": "const u = 'https://live.acme.test';\n",
                        "docs/PRIVACY.md": table("live.acme.test", "gone.acme.test")})
    rc, out = run(capsys, str(d))
    assert rc == 0
    assert "WARN stale        gone.acme.test  docs/PRIVACY.md:6" in out


def test_a_row_marked_not_in_code_is_never_stale(tmp_path):
    text = table("live.acme.test") + "| 9 | the SDK | `sdk.acme.test` (not in code: the SDK reaches it) | crash data | No | a setting |\n"
    d = repo(tmp_path, {"a.ts": "const u = 'https://live.acme.test';\n", "docs/PRIVACY.md": text})
    assert hosts.check_repo(d)["findings"] == []


def test_config_hosts_work_alone_and_together_with_the_table(tmp_path, capsys):
    toml = '[privacy]\nhosts = ["api.acme.test", "*.edge.acme.test"]\n'
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT, "teyla.toml": toml})
    rc, out = run(capsys, str(d))
    assert rc == 0, out
    d2 = repo(tmp_path, {"Sources/Net.swift": SWIFT, "teyla.toml": '[privacy]\nhosts = ["api.acme.test"]\n',
                         "docs/PRIVACY.md": table("*.edge.acme.test")}, name="both")
    assert run(capsys, str(d2))[0] == 0


def test_no_table_and_no_config_is_a_coverage_gap_exit_2_that_still_lists_hosts(tmp_path, capsys):
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT})
    rc, out = run(capsys, str(d))
    assert rc == 2
    assert "coverage gap" in out and "api.acme.test" in out
    assert run(capsys, str(d), "--quiet")[1].count("GAP") == 1


CONSENT = """# Privacy

| # | Trigger | Host | What is sent | Default on | Consent | Turn it off |
|---|---|---|---|---|---|---|
| 1 | a chat message | `api.openai.com` | the message | No | {consent} | a setting |
| 2 | launch | `api.acme.test` | a version | Yes | - | a setting |
"""


def test_a_provider_host_with_an_empty_consent_cell_is_a_fix(tmp_path):
    files = {"a.ts": "fetch('https://api.openai.com/v1/x'); fetch('https://api.acme.test/y');\n"}
    d = repo(tmp_path, {**files, "docs/PRIVACY.md": CONSENT.format(consent="")})
    r = hosts.check_repo(d)
    assert [(f["check"], f["host"]) for f in r["findings"] if f["severity"] == "FIX"] == [("consent", "api.openai.com")]
    d2 = repo(tmp_path, {**files, "docs/PRIVACY.md": CONSENT.format(consent="A first-run sheet names the provider")}, name="ok")
    assert hosts.check_repo(d2)["findings"] == []
    d3 = repo(tmp_path, {**files, "docs/PRIVACY.md": CONSENT.format(consent=""), "teyla.toml": "[security]\ndata = []\n"}, name="nodata")
    assert hosts.check_repo(d3)["findings"] == []


def test_cleartext_http_to_a_real_host_is_a_warn(tmp_path):
    d = repo(tmp_path, {"a.ts": "const u = 'http://plain.acme.test/x';\n", "docs/PRIVACY.md": table("plain.acme.test")})
    r = hosts.check_repo(d)
    assert ("cleartext", "WARN", "plain.acme.test") in checks(r)
    assert hosts.exit_code([r]) == 0


# --- --write -----------------------------------------------------------------------------------------

def test_write_appends_rows_for_undocumented_hosts_and_never_deletes(tmp_path, capsys):
    before = table("cdn.acme.test", "old.acme.test")
    d = repo(tmp_path, {"web/app.ts": TS, "docs/PRIVACY.md": before})
    rc, out = run(capsys, str(d), "--write")
    after = (d / "docs" / "PRIVACY.md").read_text()
    assert "wrote" in out
    for line in before.strip().splitlines():
        assert line in after                                                       # nothing deleted or edited
    assert "| 3 |" in after and "`deno.acme.test`" in after and "Found in `web/app.ts:1`" in after
    assert after.count("TODO (a person fills this)") >= 4
    assert rc == 0                                                                  # rows exist; the TODOs are a WARN
    assert any(f["check"] == "todo" for f in hosts.check_repo(d)["findings"])
    assert run(capsys, str(d), "--write")[0] == 0
    assert (d / "docs" / "PRIVACY.md").read_text() == after                         # idempotent


def test_write_creates_the_file_from_the_template_when_it_is_missing(tmp_path, capsys):
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT})
    assert run(capsys, str(d))[0] == 2
    rc, out = run(capsys, str(d), "--write")
    text = (d / "docs" / "PRIVACY.md").read_text()
    assert rc == 0, out
    assert "teyla hosts" in text and "How to keep this true" in text
    assert "`api.acme.test`" in text and "{{name}}" not in text
    assert "| 4 |" in text                              # numbering continues after the 3 examples


def test_write_with_no_hosts_still_creates_the_template(tmp_path, capsys):
    d = repo(tmp_path, {"README.md": "x\n"})
    assert run(capsys, str(d), "--write")[0] == 0
    assert (d / "docs" / "PRIVACY.md").is_file()


def test_write_adds_a_section_when_the_file_has_no_host_table(tmp_path, capsys):
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT, "docs/PRIVACY.md": "# Privacy\n\nNothing leaves.\n"})
    assert run(capsys, str(d), "--write")[0] == 0
    text = (d / "docs" / "PRIVACY.md").read_text()
    assert text.startswith("# Privacy\n\nNothing leaves.\n") and "## Hosts found by `teyla hosts`" in text


# --- output and wiring -------------------------------------------------------------------------------

def test_json_shape(tmp_path, capsys):
    d = repo(tmp_path, {"web/app.ts": TS, "docs/PRIVACY.md": table("cdn.acme.test")})
    rc, out = run(capsys, str(d), "--json")
    data = json.loads(out)
    assert rc == 1 and data["exit"] == 1 and data["totals"]["FIX"] >= 1
    rep = data["repos"][0]
    assert {"repo", "hosts", "local", "env_provided", "findings", "coverage"} <= set(rep)
    assert {"check", "severity", "host", "file", "line", "message", "fix"} <= set(rep["findings"][0])


def test_quiet_prints_nothing_when_clean(tmp_path, capsys):
    d = repo(tmp_path, {"a.ts": "const u = 'https://live.acme.test';\n", "docs/PRIVACY.md": table("live.acme.test", "gone.acme.test")})
    rc, out = run(capsys, str(d), "--quiet")
    assert (rc, out) == (0, "")


def test_a_missing_directory_is_exit_2(tmp_path, capsys):
    assert cli.main(["hosts", str(tmp_path / "nope")]) == 2


def test_hosts_is_registered_in_the_help_groups():
    from teyla import helpgroups
    assert helpgroups.group_of("hosts") == "Products"


def test_teylas_own_table_covers_teylas_own_code(capsys):
    r = hosts.check_repo(ROOT)
    assert [f for f in r["findings"] if f["severity"] == "FIX"] == []
    assert r["coverage"]["privacy_table"] is True


# --- the scaffold ------------------------------------------------------------------------------------

def test_scaffold_writes_the_privacy_template_and_it_passes(tmp_path, capsys):
    dest = tmp_path / "fresh"
    scaffold.scaffold(str(dest), name="fresh", kind="cli", license="none", owner="Ada")
    text = (dest / "docs" / "PRIVACY.md").read_text()
    assert text.startswith("# Privacy") and "fresh" in text and "{{name}}" not in text
    assert text.count("| 3 |") == 1 and "teyla hosts" in text
    assert hosts.check_repo(dest)["findings"] == []
    assert run(capsys, str(dest))[0] == 0


def test_check_sh_template_runs_security_steps_before_it_sources_env():
    sh = (ROOT / "templates" / "repo" / "check.sh").read_text()
    lines = sh.splitlines()
    leak = next(i for i, ln in enumerate(lines) if "teyla leak --quiet" in ln)
    hosts_ = next(i for i, ln in enumerate(lines) if "teyla hosts . --quiet" in ln)
    env = next(i for i, ln in enumerate(lines) if "source .env" in ln)
    assert leak < env and hosts_ < env
    assert "command -v teyla" in sh


# --- fix round: guarded reads and writes, wildcards, escapes, regex literals, IP rows --------------------

def test_write_refuses_a_symlinked_privacy_file_pointing_outside_the_repo(tmp_path, capsys):
    outside = tmp_path / "outside.md"
    outside.write_text("# outside\n")
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT})
    (d / "docs").mkdir()
    (d / "docs" / "PRIVACY.md").symlink_to(outside)
    rc = cli.main(["hosts", str(d), "--write"])
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and "symlink" in err
    assert outside.read_text() == "# outside\n"


def test_write_refuses_a_symlinked_docs_directory_pointing_outside_the_repo(tmp_path, capsys):
    out_dir = tmp_path / "elsewhere"
    out_dir.mkdir()
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT})
    (d / "docs").symlink_to(out_dir)
    assert cli.main(["hosts", str(d), "--write"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert list(out_dir.iterdir()) == []


def test_a_symlinked_privacy_file_is_not_read_either(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(table("api.acme.test"))
    d = repo(tmp_path, {"Sources/Net.swift": SWIFT})
    (d / "docs").mkdir()
    (d / "docs" / "PRIVACY.md").symlink_to(outside)
    r = hosts.check_repo(d)
    assert r["coverage"]["privacy_table"] is False
    assert any("docs/PRIVACY.md" in u and "symlink" in u for u in r["coverage"]["unread"])


def test_a_plist_symlinked_to_a_device_is_skipped_not_read(tmp_path):
    d = repo(tmp_path, {"docs/PRIVACY.md": table("x.acme.test")})
    (d / "App").mkdir()
    (d / "App" / "Info.plist").symlink_to("/dev/zero")
    r = hosts.check_repo(d)                                    # must return, not read until memory runs out
    assert any("App/Info.plist" in u for u in r["coverage"]["unread"])


def test_an_oversized_plist_and_source_file_are_skipped_with_a_coverage_note(tmp_path):
    big = plistlib.dumps({"SUFeedURL": "https://big.acme.test/feed", "pad": "x" * (hosts.MAX_FILE_BYTES + 10)})
    d = repo(tmp_path, {"App/Info.plist": big, "web/huge.ts": "const u = 'https://huge.acme.test';\n" + "//" + "x" * (hosts.MAX_FILE_BYTES + 10),
                        "docs/PRIVACY.md": table("x.acme.test")})
    r = hosts.check_repo(d)
    assert "big.acme.test" not in host_names(r) and "huge.acme.test" not in host_names(r)
    unread = " ".join(r["coverage"]["unread"])
    assert "App/Info.plist" in unread and "web/huge.ts" in unread and "MB" in unread


def test_a_concrete_row_does_not_cover_a_wildcard_the_code_reaches(tmp_path):
    ts = "fetch(`https://${tenant}.pool.acme.test/rest`);\n"
    d = repo(tmp_path, {"a.ts": ts, "docs/PRIVACY.md": table("one.pool.acme.test")})
    r = hosts.check_repo(d)
    assert ("undocumented", "FIX", "*.pool.acme.test") in checks(r)
    assert not any(f["check"] == "stale" for f in r["findings"])                  # the instance is still reachable
    d2 = repo(tmp_path, {"a.ts": ts, "docs/PRIVACY.md": table("*.pool.acme.test")}, name="wild")
    assert hosts.check_repo(d2)["findings"] == []
    assert hosts.covers("*.pool.acme.test", "pool.acme.test") and not hosts.covers("one.pool.acme.test", "*.pool.acme.test")


def test_escaped_urls_are_decoded_before_extraction(tmp_path):
    src = ('const a = "https:\\/\\/slash.acme.test\\/x";\n'
           'const b = "https:\\u002f\\u002funi.acme.test/x";\n'
           'const c = "https:\\x2f\\x2fhex.acme.test/x";\n')
    d = repo(tmp_path, {"a.ts": src, "docs/PRIVACY.md": table("x.acme.test")})
    assert {"slash.acme.test", "uni.acme.test", "hex.acme.test"} <= host_names(hosts.check_repo(d))


def test_a_regex_literal_does_not_hide_the_host_after_it(tmp_path):
    src = 'const re = /"/g; fetch("https://after-regex.acme.test/a");\nconst q = /\'/; const u = "https://after-quote.acme.test";\n'
    d = repo(tmp_path, {"a.ts": src, "docs/PRIVACY.md": table("x.acme.test")})
    assert {"after-regex.acme.test", "after-quote.acme.test"} <= host_names(hosts.check_repo(d))


def test_a_documented_ip_address_is_covered_and_write_never_duplicates(tmp_path, capsys):
    src = 'const a = "https://8.8.8.8/x";\nconst b = "https://1.1.1.1/y";\nconst c = "https://9.9.9.9/z";\n'
    rows = ("| 1 | launch | `8.8.8.8` | a version | Yes | a setting |\n"
            "| 2 | launch | `https://1.1.1.1/y` | a version | Yes | a setting |")
    d = repo(tmp_path, {"a.ts": src, "docs/PRIVACY.md": TABLE.format(rows=rows)})
    r = hosts.check_repo(d)
    assert [f["host"] for f in r["findings"] if f["severity"] == "FIX"] == ["9.9.9.9"]
    assert run(capsys, str(d), "--write")[0] == 0
    once = (d / "docs" / "PRIVACY.md").read_text()
    assert once.count("8.8.8.8") == 1 and once.count("1.1.1.1") == 1 and once.count("9.9.9.9") == 1
    assert run(capsys, str(d), "--write")[0] == 0
    assert (d / "docs" / "PRIVACY.md").read_text() == once
