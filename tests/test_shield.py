"""teyla shield — the [security] contract, its tier requirements and its expiring evidence.

Fixture repos live under tmp_path. The leak scanner and `teyla hosts` belong to other lanes, so the
tests replace the two command lookups; every other check runs for real, including `git config`."""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import tomllib

import pytest

import teyla
from teyla import config, shield

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()


def ago(days: int) -> str:
    return (TODAY - datetime.timedelta(days=days)).isoformat()


def evidence(what: str, days: int, **extra) -> str:
    row = f'\n[[security.evidence]]\nwhat = "{what}"\ncommit = "abc1234"\ndate = {ago(days)}\nhow = "ran it"\n'
    return row + "".join(f"{k} = {v}\n" for k, v in extra.items())


@pytest.fixture(autouse=True)
def _scanners(monkeypatch):
    """A scanner that finds nothing, and no `teyla hosts` (the table file is checked on its own)."""
    monkeypatch.setattr(shield, "_leak_command", lambda repo: ["true"])
    monkeypatch.setattr(shield, "_hosts_command", lambda repo: None)


def git(d: pathlib.Path, *args: str):
    subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)


def repo(tmp_path, name="thing", *, users="owner", security='data = ["account"]\n', extra_toml="",
         hooks=True, privacy=True, gitignore=".env\n", files=None) -> pathlib.Path:
    """A repo that passes the owner tier unless a keyword breaks it."""
    d = tmp_path / name
    d.mkdir()
    git(d, "init", "-q")
    if "secrets" not in security:
        security += 'secrets = "runtime-env"\n'
    body = f'[product]\nname = "{name}"\n\n[productize]\nusers = "{users}"\n\n[security]\n{security}{extra_toml}'
    (d / "teyla.toml").write_text(body)
    (d / ".gitignore").write_text(gitignore)
    if hooks:
        (d / ".githooks").mkdir()
        for h in ("pre-commit", "pre-push"):
            (d / ".githooks" / h).write_text("#!/bin/sh\nexit 0\n")
            (d / ".githooks" / h).chmod(0o755)
        git(d, "config", "core.hooksPath", ".githooks")
    if privacy:
        (d / "docs").mkdir()
        (d / "docs" / "PRIVACY.md").write_text("# Hosts\n\n| host | what |\n|---|---|\n| example.test | a call |\n")
    for rel, text in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return d


def status(rep: dict) -> dict:
    return {r["name"]: r["status"] for r in rep["requirements"]}


def detail(rep: dict, name: str) -> str:
    return next(r["detail"] for r in rep["requirements"] if r["name"] == name)


# --- owner tier ------------------------------------------------------------------------

def test_owner_tier_clean_repo_passes(tmp_path):
    rep = shield.check(repo(tmp_path))
    assert rep["tier"] == "owner" and rep["exit"] == 0
    assert set(status(rep).values()) == {"OK"}
    assert list(status(rep)) == ["contract", "leak", "hooks", "hosts", "lockfile", "secrets", "trifecta"]


def test_tier_comes_from_productize_users_and_an_explicit_value_overrides(tmp_path):
    assert shield.check(repo(tmp_path, "a", users="family"))["tier"] == "family"
    assert shield.check(repo(tmp_path, "b", users="family", security='tier = "public"\ndata = ["none"]\n'))["tier"] == "public"
    low = shield.check(repo(tmp_path, "c", users="public", security='tier = "owner"\ndata = ["none"]\n'))
    assert low["tier"] == "owner" and status(low)["tier"] == "NOTE"      # a downgrade is visible, not blocking


def test_a_fresh_scaffold_prints_the_tier_fix_list_and_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(shield, "_leak_command", lambda r: None)
    d = tmp_path / "fresh"
    d.mkdir()
    git(d, "init", "-q")
    (d / "teyla.toml").write_text(shield.template_section())
    rep = shield.check(d)
    s = status(rep)
    assert rep["exit"] == 1
    assert {n for n, v in s.items() if v == "FIX"} == {"contract", "leak", "hooks", "hosts", "secrets"}
    assert "install the leak gate" in detail(rep, "leak")


def test_a_missing_scanner_is_a_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(shield, "_leak_command", lambda r: None)
    rep = shield.check(repo(tmp_path))
    assert status(rep)["leak"] == "FIX" and "install the leak gate" in detail(rep, "leak")


def test_a_scanner_that_finds_something_is_a_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(shield, "_leak_command", lambda r: ["sh", "-c", "echo 3; exit 1"])
    rep = shield.check(repo(tmp_path))
    assert status(rep)["leak"] == "FIX" and "3" in detail(rep, "leak")


def test_hooks_need_both_files_executable_and_the_hooks_path(tmp_path):
    assert status(shield.check(repo(tmp_path, "a", hooks=False)))["hooks"] == "FIX"
    d = repo(tmp_path, "b")
    git(d, "config", "--unset", "core.hooksPath")
    assert "core.hooksPath" in detail(shield.check(d), "hooks")
    (d / ".githooks" / "pre-push").chmod(0o644)
    assert "chmod" in detail(shield.check(d), "hooks")


def test_hosts_needs_a_table(tmp_path):
    assert status(shield.check(repo(tmp_path, "a", privacy=False)))["hosts"] == "FIX"
    d = repo(tmp_path, "b", files={"docs/PRIVACY.md": "no table here\n"})
    assert status(shield.check(d))["hosts"] == "FIX"


def test_hosts_runs_teyla_hosts_when_the_command_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(shield, "_hosts_command", lambda r: ["sh", "-c", "echo 'undocumented api.example.test'; exit 1"])
    rep = shield.check(repo(tmp_path))
    assert status(rep)["hosts"] == "FIX" and "undocumented" in detail(rep, "hosts")


def test_lockfile_for_the_detected_ecosystem(tmp_path):
    d = repo(tmp_path, files={"package.json": "{}\n"})
    assert status(shield.check(d))["lockfile"] == "FIX"
    (d / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    assert status(shield.check(d))["lockfile"] == "OK"
    py = repo(tmp_path, "py", files={"pyproject.toml": '[project]\nname = "x"\ndependencies = []\n'})
    assert "n/a" in detail(shield.check(py), "lockfile")             # nothing to pin
    py2 = repo(tmp_path, "py2", files={"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n'})
    assert status(shield.check(py2))["lockfile"] == "FIX"


def test_secrets_location_gitignore_and_tracked_key_files(tmp_path):
    assert status(shield.check(repo(tmp_path, "a", security='data = ["none"]\nsecrets = "client"\n')))["secrets"] == "FIX"
    assert status(shield.check(repo(tmp_path, "b", security='data = ["none"]\nsecrets = "repo"\n')))["secrets"] == "FIX"
    open_env = repo(tmp_path, "c", security='data = ["none"]\nsecrets = "keychain"\n', gitignore="")
    assert "add .env to .gitignore" in detail(shield.check(open_env), "secrets")
    ok = repo(tmp_path, "d", security='data = ["none"]\nsecrets = "hub"\n')
    assert status(shield.check(ok))["secrets"] == "OK"
    (ok / "AuthKey.p8").write_text("not a key\n")
    git(ok, "add", "AuthKey.p8")
    assert "AuthKey.p8" in detail(shield.check(ok), "secrets")


def test_rls_flags_tables_without_row_level_security(tmp_path):
    sql1 = """
    -- create table commented_out (id int);
    create table public.notes (id uuid primary key);
    create table if not exists "Photos" (id int);
    create table audit_log (id int);
    alter table public.notes enable row level security;
    alter table audit_log enable row level security;
    create table scratch (id int);
    drop table if exists scratch;
    create table private.internal (id int);
    """
    d = repo(tmp_path, files={"supabase/migrations/001_init.sql": sql1})
    rep = shield.check(d)
    assert status(rep)["rls"] == "FIX"
    assert detail(rep, "rls") == "enable row level security on: photos"
    (d / "supabase/migrations/002_more.sql").write_text('alter table "Photos" enable row level security;\n')
    rep = shield.check(d)
    assert status(rep)["rls"] == "OK" and "3 table" in detail(rep, "rls")


def test_rls_declared_without_migrations_is_a_fix(tmp_path):
    rep = shield.check(repo(tmp_path, security='data = ["account"]\nrls = "migrations"\n'))
    assert status(rep)["rls"] == "FIX" and "no supabase/migrations" in detail(rep, "rls")


def test_trifecta_all_three_legs_is_a_fix_unless_the_split_is_documented(tmp_path):
    legs = 'data = ["messages"]\ntrifecta = ["private-data", "untrusted-content", "outbound"]\n'
    rep = shield.check(repo(tmp_path, "a", security=legs))
    assert status(rep)["trifecta"] == "FIX" and "cut a leg or document the executor split" in detail(rep, "trifecta")
    rep = shield.check(repo(tmp_path, "b", security=legs, extra_toml=evidence("executor-split", 3)))
    assert status(rep)["trifecta"] == "OK" and "executor split" in detail(rep, "trifecta")
    two = shield.check(repo(tmp_path, "c", security='data = ["messages"]\ntrifecta = ["private-data", "outbound"]\n'))
    assert status(two)["trifecta"] == "OK"


def test_mcp_url_key_is_a_fix_at_every_tier(tmp_path):
    mcp = 'data = ["account"]\nmcp = { auth = "bearer", url_key = true, rate_limit = true, static_tools = true }\n'
    rep = shield.check(repo(tmp_path, security=mcp))
    assert status(rep)["mcp"] == "FIX" and "the URL is the secret" in detail(rep, "mcp")


def test_mcp_without_auth_fails_above_owner_only(tmp_path):
    mcp = 'data = ["account"]\nmcp = { auth = "none", url_key = false, rate_limit = true, static_tools = true }\n'
    assert status(shield.check(repo(tmp_path, "a", security=mcp)))["mcp"] == "OK"
    assert status(shield.check(repo(tmp_path, "b", users="family", security=mcp)))["mcp"] == "FIX"
    pub = 'data = ["account"]\nmcp = { auth = "bearer", url_key = false, rate_limit = false, static_tools = true }\n'
    assert status(shield.check(repo(tmp_path, "c", users="public", security=pub)))["mcp"] == "FIX"


# --- family and testers ------------------------------------------------------------------

def test_family_tier_adds_the_platform_checks(tmp_path):
    rep = shield.check(repo(tmp_path, users="family"))
    assert list(status(rep)) == ["contract", "leak", "hooks", "hosts", "lockfile", "secrets", "trifecta",
                                 "rls-test", "privacy-manifest", "no-token-in-defaults", "mcp"]
    assert rep["exit"] == 0                          # no database, no Xcode project, no MCP: all n/a


def test_rls_test_evidence_is_required_with_migrations(tmp_path):
    files = {"supabase/migrations/001.sql": "create table t (id int);\nalter table t enable row level security;\n"}
    d = repo(tmp_path, users="family", files=files)
    rep = shield.check(d)
    assert status(rep)["rls-test"] == "FIX" and "what = \"rls-test\"" in detail(rep, "rls-test")
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text() + evidence("rls-test", 4))
    rep = shield.check(d)
    assert status(rep)["rls-test"] == "OK" and "4d old" in detail(rep, "rls-test")


def test_probe_is_required_when_an_mcp_section_exists(tmp_path):
    mcp = 'data = ["account"]\nmcp = { auth = "bearer", url_key = false, rate_limit = true, static_tools = true }\n'
    d = repo(tmp_path, users="testers", security=mcp)
    rep = shield.check(d)
    assert status(rep)["probe"] == "FIX"
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text() + evidence("mcp-probe", 2))
    assert status(shield.check(d))["probe"] == "OK"


def test_privacy_manifest_is_required_for_an_xcode_project(tmp_path):
    d = repo(tmp_path, users="family", files={"project.yml": "name: App\ntargets:\n  App:\n    type: application\n"})
    assert status(shield.check(d))["privacy-manifest"] == "FIX"
    (d / "App").mkdir()
    (d / "App" / "PrivacyInfo.xcprivacy").write_text("<plist/>\n")
    assert status(shield.check(d))["privacy-manifest"] == "OK"


def test_a_token_key_in_user_defaults_is_a_fix(tmp_path):
    bad = ('import Foundation\nfunc save(_ t: String) {\n'
           '    UserDefaults.standard.set(t, forKey: "authToken")\n}\n'
           '@AppStorage("apiKey") var key = ""\n')
    d = repo(tmp_path, users="family", files={"App/Store.swift": bad})
    rep = shield.check(d)
    assert status(rep)["no-token-in-defaults"] == "FIX" and "App/Store.swift:3" in detail(rep, "no-token-in-defaults")
    good = ('UserDefaults.standard.set(true, forKey: "onboarded")\n'
            'keychain.set(token, forKey: "authToken")\n'
            '// UserDefaults.standard.set(t, forKey: "oldToken")\n')
    d2 = repo(tmp_path, "ok", users="family", files={"App/Store.swift": good})
    assert status(shield.check(d2))["no-token-in-defaults"] == "OK"
    kt = repo(tmp_path, "kt", users="family", files={"app/Prefs.kt": 'prefs.edit().putString("session_token", t).apply()\n'})
    assert status(shield.check(kt))["no-token-in-defaults"] == "FIX"


# --- public tier, evidence and release -------------------------------------------------

PUBLIC = 'data = ["account"]\n'


def test_public_tier_with_stale_evidence_is_stale_and_blocks_only_a_release(tmp_path):
    d = repo(tmp_path, users="public", security=PUBLIC, extra_toml=evidence("deps", 45) + evidence("credential-separation", 2),
             files={"docs/APP-STORE.md": "# Review notes\n\n## DATA\n\nWhat is collected.\n"})
    rep = shield.check(d)
    assert status(rep)["deps"] == "STALE" and "45d old, limit 30d" in detail(rep, "deps")
    assert rep["exit"] == 0 and rep["not_enforced"] == []
    rel = shield.check(d, release=True)
    assert status(rel)["release-notes"] == "OK" and rel["exit"] == 1 and not rel["ok"]
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text() + evidence("deps", 1))
    assert shield.check(d, release=True)["exit"] == 0                 # the newest row counts


def test_missing_evidence_is_a_fix_not_a_stale(tmp_path):
    rep = shield.check(repo(tmp_path, users="public", security=PUBLIC))
    assert status(rep)["deps"] == "FIX" and rep["exit"] == 1


def test_an_evidence_row_sets_its_own_limit_and_a_release_entry_tightens_it(tmp_path):
    d = repo(tmp_path, users="public", security=PUBLIC + 'release = ["deps<10d"]\n',
             extra_toml=evidence("deps", 20, max_age_days=60))
    assert status(shield.check(d))["deps"] == "OK"
    rel = shield.check(d, release=True)
    assert status(rel)["deps"] == "STALE" and "limit 10d" in detail(rel, "deps")


def test_credential_separation_is_a_note_and_the_first_line_says_so(tmp_path, capsys):
    d = repo(tmp_path, users="public", security=PUBLIC, extra_toml=evidence("deps", 1))
    rep = shield.check(d)
    assert status(rep)["credential-separation"] == "NOTE"
    assert rep["not_enforced"] == ["credential separation"]
    from teyla.cli import main
    main(["shield", "check", str(d)])
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "not enforced on this machine: credential separation (see SHIELD §5.7)"
    # Never blocks by itself, even stale or with --release.
    ok = repo(tmp_path, "ok", users="public", security=PUBLIC, extra_toml=evidence("deps", 1),
              files={"docs/APP-STORE.md": "DATA: what is collected.\n"})
    assert shield.check(ok, release=True)["exit"] == 0
    fresh = repo(tmp_path, "fresh", users="public", security=PUBLIC,
                 extra_toml=evidence("deps", 1) + evidence("credential-separation", 3))
    rep = shield.check(fresh)
    assert status(rep)["credential-separation"] == "OK" and rep["not_enforced"] == []


def test_release_notes_need_a_data_paragraph(tmp_path):
    d = repo(tmp_path, users="family", files={"docs/APP-STORE.md": "# Notes\n\nNothing about it.\n"})
    assert shield.check(d)["requirements"][-1]["name"] != "release-notes"          # only with --release
    rel = shield.check(d, release=True)
    assert status(rel)["release-notes"] == "FIX" and rel["exit"] == 1
    (d / "docs" / "APP-STORE.md").write_text("# Notes\n\n**DATA** what we collect\n")
    assert status(shield.check(d, release=True))["release-notes"] == "OK"


def test_owner_tier_skips_release_notes_but_a_release_entry_adds_requirements(tmp_path):
    d = repo(tmp_path, security='data = ["none"]\nrelease = ["deps", "mcp-probe"]\n')
    assert "deps" not in status(shield.check(d))
    rel = shield.check(d, release=True)
    assert status(rel)["deps"] == "FIX" and status(rel)["probe"] == "FIX" and "release-notes" not in status(rel)


# --- the contract itself ----------------------------------------------------------------

def test_contract_rejects_malformed_values_and_evidence(tmp_path):
    bad = shield.check(repo(tmp_path, "a", security='tier = "huge"\ndata = ["cats"]\ntrifecta = ["x"]\nrls = "magic"\n'))
    msg = detail(bad, "contract")
    assert status(bad)["contract"] == "FIX"
    for part in ("tier 'huge'", "unknown data class 'cats'", "trifecta takes", "rls 'magic'"):
        assert part in msg
    future = shield.check(repo(tmp_path, "b", extra_toml=f'\n[[security.evidence]]\nwhat = "deps"\ncommit = "a1"\ndate = {(TODAY + datetime.timedelta(days=5)).isoformat()}\nhow = "x"\n'))
    assert "dated in the future" in detail(future, "contract")
    short = shield.check(repo(tmp_path, "c", extra_toml='\n[[security.evidence]]\nwhat = "deps"\n'))
    assert "lacks commit, date, how" in detail(short, "contract")
    unknown = shield.check(repo(tmp_path, "d", security='data = ["none"]\nrelease = ["nonsense"]\n'))
    assert "not a requirement" in detail(unknown, "contract")


# --- the command -------------------------------------------------------------------------

def test_missing_section_exits_2_and_prints_the_template(tmp_path, capsys):
    d = tmp_path / "bare"
    d.mkdir()
    (d / "teyla.toml").write_text('[product]\nname = "bare"\n')
    from teyla.cli import main
    assert main(["shield", "check", str(d)]) == 2
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("not enforced on this machine")
    assert "[security]" in out and "no [security] section" in out
    assert main(["shield", "check", str(tmp_path / "nowhere")]) == 2


def test_the_template_section_parses_and_is_the_one_in_the_repo_template():
    section = shield.template_section()
    parsed = tomllib.loads(section)["security"]
    assert parsed["secrets"] == "runtime-env" and parsed["data"] == [] and parsed["hosts"] == "docs/PRIVACY.md"
    full = (ROOT / "templates" / "repo" / "teyla.toml").read_text().replace("{{name}}", "demo").replace("{{productize}}", "")
    assert "security" in tomllib.loads(full)


def test_cli_exit_codes_and_text_output(tmp_path, capsys):
    from teyla.cli import main
    good = repo(tmp_path, "good")
    assert main(["shield", "check", str(good)]) == 0
    out = capsys.readouterr().out
    assert "OK     leak" in out or "OK     contract" in out
    assert out.splitlines()[-1] == "7 OK, 0 FIX, 0 STALE, 0 NOTE"
    bad = repo(tmp_path, "bad", hooks=False)
    assert main(["shield", "check", str(bad)]) == 1
    assert "FIX    hooks" in capsys.readouterr().out


def test_json_shape(tmp_path, capsys):
    from teyla.cli import main
    d = repo(tmp_path, users="public", security=PUBLIC, extra_toml=evidence("deps", 45))
    assert main(["shield", "check", str(d), "--json"]) == 0           # STALE alone does not block
    rep = json.loads(capsys.readouterr().out)
    assert set(rep) == {"repo", "path", "tier", "release", "exit", "ok", "counts", "requirements",
                        "not_enforced", "evidence_oldest_days"}
    assert rep["tier"] == "public" and rep["release"] is False and rep["evidence_oldest_days"] == 45
    assert set(rep["counts"]) == {"OK", "FIX", "STALE", "NOTE"}
    assert all(set(r) == {"name", "status", "detail"} for r in rep["requirements"])
    assert main(["shield", "check", str(d), "--release", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["release"] is True


def test_the_table_lists_every_repo_with_a_section(tmp_path, monkeypatch, capsys):
    root = tmp_path / "code"
    root.mkdir()
    a = repo(root, "alpha")
    b = repo(root, "beta", users="public", security=PUBLIC, extra_toml=evidence("deps", 45))
    plain = root / "plain"
    plain.mkdir()
    (plain / ".git").mkdir()
    (plain / "teyla.toml").write_text('[product]\nname = "plain"\n')
    monkeypatch.setattr(config, "code_root", lambda cfg=None: root)
    from teyla.cli import main
    rc = main(["shield"])
    out = capsys.readouterr().out
    assert rc == 0                                           # STALE and NOTE do not fail the table
    lines = out.splitlines()
    assert lines[0].startswith("not enforced on this machine")
    assert lines[1].split()[:2] == ["repo", "tier"] and "rlst" in lines[1] and "cred" in lines[1]
    row_a = next(l for l in lines if l.startswith("alpha"))
    row_b = next(l for l in lines if l.startswith("beta"))
    assert "owner" in row_a and row_a.split()[-1] == "-"
    assert "public" in row_b and "STALE" in row_b and row_b.split()[-1] == "45d"
    assert not any(l.startswith("plain") for l in lines)
    assert main(["shield", "--json"]) == 0
    assert [p["repo"] for p in json.loads(capsys.readouterr().out)["products"]] == ["alpha", "beta"]


def test_the_table_with_no_section_anywhere(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "code_root", lambda cfg=None: tmp_path)
    from teyla.cli import main
    assert main(["shield"]) == 0
    assert "no repo under code_root has a [security] section" in capsys.readouterr().out


# --- the shipped files -------------------------------------------------------------------

def test_the_review_notes_template_has_the_three_paragraphs():
    text = (ROOT / "templates" / "store" / "REVIEW-NOTES.md").read_text()
    for head in ("## DATA", "## BUSINESS MODEL", "## CAPABILITIES"):
        assert head in text
    data = text.split("## DATA", 1)[1].split("\n## ", 1)[0]
    for word in ("collects", "providers", "delete"):
        assert word in data.lower()
    assert not any(ord(ch) > 0x400 and ord(ch) < 0x4ff for ch in text)


def test_the_contract_doc_states_its_status_and_stays_short():
    text = (ROOT / "docs" / "CONTRACT.md").read_text()
    assert "Status: shipped 2026-10-31." in text and len(text.splitlines()) <= 150
    assert "teyla shield check <repo> --release" in text


def test_the_table_exits_1_when_a_repo_has_a_fix(tmp_path, monkeypatch, capsys):
    repo(tmp_path, "broken", hooks=False)
    monkeypatch.setattr(config, "code_root", lambda cfg=None: tmp_path)
    from teyla.cli import main
    assert main(["shield"]) == 1
    assert "FIX" in capsys.readouterr().out
