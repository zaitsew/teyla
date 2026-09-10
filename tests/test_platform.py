"""teyla.platform — the shared-resource manifest and its check table.

Every path is monkeypatched into tmp_path and both network probes are skipped with
--no-net, so nothing here touches the real HOME, the real network, or ssh."""
from __future__ import annotations

import pathlib

import pytest

import teyla
from teyla import platform


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(platform, "PLATFORM_PATH", home / ".teyla" / "platform.toml")
    return home


def manifest(home: pathlib.Path, body: str) -> pathlib.Path:
    p = home / ".teyla" / "platform.toml"
    p.write_text(body)
    return p


def secrets(home: pathlib.Path, names: list[str], mode: int = 0o600) -> pathlib.Path:
    p = home / ".config" / "teyla" / "platform.env"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{n}=value-not-read\n" for n in names))
    p.chmod(mode)
    return p


def row(rows: list[dict], name: str) -> dict:
    return next(r for r in rows if r["resource"] == name)


MINIMAL = """
[owner]
name = "Someone"

[secrets]
file = "~/.config/teyla/platform.env"

[server]
provider = "none"

[domain]
name = ""

[identity]
provider = "none"

[mail]
provider = "none"

[apple]
config = "~/.appstoreconnect/config.env"
release_tool = "~/bin/testflight"

[android]
play_console = false

[llm]
provider = "none"
"""


# --- the manifest ------------------------------------------------------------------

def test_init_writes_the_template_with_the_owner(_home):
    assert platform.init(owner="Someone").startswith("wrote")
    text = (_home / ".teyla" / "platform.toml").read_text()
    assert 'name = "Someone"' in text
    assert "{{owner}}" not in text
    assert platform.init(owner="Someone").startswith("exists")
    assert platform.init(owner="Other", force=True).startswith("wrote")
    assert 'name = "Other"' in (_home / ".teyla" / "platform.toml").read_text()


def test_load_is_empty_when_absent_or_broken(_home):
    assert platform.load() == {}
    manifest(_home, "this is not toml [[[")
    assert platform.load() == {}


def test_missing_manifest_is_one_row_with_the_command_to_write_it(_home):
    rows = platform.checks(no_net=True)
    assert len(rows) == 1
    assert rows[0]["state"] == platform.MISSING
    assert "teyla platform init" in rows[0]["todo"]
    assert platform.failing(rows)


def test_declared_env_names_and_env_example(_home):
    platform.init(owner="Someone")
    cfg = platform.load()
    names = platform.declared_env_names(cfg)
    assert "DIGITALOCEAN_ACCESS_TOKEN" in names
    assert "CLOUDFLARE_API_TOKEN" in names
    assert "SUPABASE_ACCESS_TOKEN" in names
    assert "RESEND_API_KEY" in names
    assert "OPENAI_API_KEY" in names
    text = platform.env_example(cfg)
    for n in names:
        assert f"{n}=" in text
    # names only: no value ever appears after the '='
    assert all(line.endswith("=") for line in text.splitlines() if "=" in line and not line.startswith("#"))


# --- secrets ------------------------------------------------------------------------

def test_secrets_missing_file(_home):
    manifest(_home, MINIMAL)
    r = row(platform.checks(no_net=True), "secrets")
    assert r["state"] == platform.MISSING
    assert "chmod 600" in r["todo"]


def test_secrets_wrong_mode_is_missing(_home):
    manifest(_home, MINIMAL)
    secrets(_home, ["OPENAI_API_KEY"], mode=0o644)
    r = row(platform.checks(no_net=True), "secrets")
    assert r["state"] == platform.MISSING
    assert "chmod 600" in r["todo"]
    assert "0644" in r["detail"]


def test_secrets_reports_names_present_never_values(_home):
    manifest(_home, MINIMAL + '\n[extra]\nfoo_env = "FOO_TOKEN"\n')
    secrets(_home, ["FOO_TOKEN"])
    r = row(platform.checks(no_net=True), "secrets")
    assert r["state"] == platform.OK
    assert "1/1 names present" in r["detail"]
    assert "value-not-read" not in r["detail"] + r["todo"]


def test_secrets_warns_about_names_still_unset(_home):
    manifest(_home, MINIMAL + '\n[extra]\na_env = "A_TOKEN"\nb_env = "B_TOKEN"\n')
    secrets(_home, ["A_TOKEN"])
    r = row(platform.checks(no_net=True), "secrets")
    assert r["state"] == platform.WARN
    assert "B_TOKEN" in r["todo"]
    assert not platform.failing([r])  # a warning is not a missing resource


def test_env_names_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "env"
    p.write_text("# comment\n\nA=1\nexport B=2\nnot-a-line\n")
    assert platform.env_names(p) == {"A", "B"}
    assert platform.env_names(tmp_path / "nope") == set()


# --- server and domain: the two probes --------------------------------------------

def test_server_none_is_not_a_failure(_home):
    manifest(_home, MINIMAL)
    assert row(platform.checks(no_net=True), "server")["state"] == platform.NA


def test_server_without_a_host_names_the_provision_script(_home):
    manifest(_home, MINIMAL.replace('[server]\nprovider = "none"',
                                    '[server]\nprovider = "digitalocean"\nname = "apps-1"\nhost = ""'))
    r = row(platform.checks(no_net=True), "server")
    assert r["state"] == platform.MISSING
    assert "provision-droplet.sh" in r["todo"]


def test_no_net_skips_ssh_and_dns(_home, monkeypatch):
    manifest(_home, MINIMAL.replace('[server]\nprovider = "none"',
                                    '[server]\nprovider = "digitalocean"\nhost = "10.0.0.1"')
                           .replace('[domain]\nname = ""', '[domain]\nname = "example.com"'))

    def boom(*a, **k):  # pragma: no cover - proves it is never called
        raise AssertionError("network probe ran under --no-net")

    monkeypatch.setattr(platform, "_ssh_ok", boom)
    monkeypatch.setattr(platform, "_resolves", boom)
    rows = platform.checks(no_net=True)
    assert row(rows, "server")["state"] == platform.OK
    assert row(rows, "domain")["state"] == platform.OK
    assert "--no-net" in row(rows, "server")["detail"]


def test_unreachable_server_and_domain_count_as_failures(_home, monkeypatch):
    manifest(_home, MINIMAL.replace('[server]\nprovider = "none"',
                                    '[server]\nprovider = "digitalocean"\nhost = "10.0.0.1"')
                           .replace('[domain]\nname = ""', '[domain]\nname = "example.com"'))
    monkeypatch.setattr(platform, "_ssh_ok", lambda user, host: False)
    monkeypatch.setattr(platform, "_resolves", lambda name: False)
    rows = platform.checks(no_net=False)
    assert row(rows, "server")["state"] == platform.UNREACHABLE
    assert row(rows, "domain")["state"] == platform.UNREACHABLE
    assert {r["resource"] for r in platform.failing(rows)} >= {"server", "domain"}


def test_reachable_server_is_ok(_home, monkeypatch):
    manifest(_home, MINIMAL.replace('[server]\nprovider = "none"',
                                    '[server]\nprovider = "digitalocean"\nhost = "10.0.0.1"\nssh_user = "deploy"'))
    seen = {}
    monkeypatch.setattr(platform, "_ssh_ok", lambda user, host: seen.update(user=user, host=host) or True)
    r = row(platform.checks(no_net=False), "server")
    assert r["state"] == platform.OK
    assert seen == {"user": "deploy", "host": "10.0.0.1"}


# --- identity, mail, llm -----------------------------------------------------------

def test_identity_needs_the_cli_and_an_org(_home, monkeypatch):
    manifest(_home, MINIMAL.replace('[identity]\nprovider = "none"',
                                    '[identity]\nprovider = "supabase"\norg = ""\naccess_token_env = "SUPABASE_ACCESS_TOKEN"'))
    monkeypatch.setattr(platform.shutil, "which", lambda name: None)
    r = row(platform.checks(no_net=True), "identity")
    assert r["state"] == platform.MISSING and "brew install supabase" in r["todo"]

    monkeypatch.setattr(platform.shutil, "which", lambda name: "/usr/local/bin/supabase")
    r = row(platform.checks(no_net=True), "identity")
    assert r["state"] == platform.MISSING and "org" in r["todo"]


def test_identity_ok_with_org_and_token(_home, monkeypatch):
    manifest(_home, MINIMAL.replace('[identity]\nprovider = "none"',
                                    '[identity]\nprovider = "supabase"\norg = "org-1"\naccess_token_env = "SUPABASE_ACCESS_TOKEN"'))
    secrets(_home, ["SUPABASE_ACCESS_TOKEN"])
    monkeypatch.setattr(platform.shutil, "which", lambda name: "/usr/local/bin/supabase")
    assert row(platform.checks(no_net=True), "identity")["state"] == platform.OK


def test_mail_missing_then_present(_home):
    manifest(_home, MINIMAL)
    r = row(platform.checks(no_net=True), "mail")
    assert r["state"] == platform.MISSING
    assert not platform.mail_ready(platform.load())

    manifest(_home, MINIMAL.replace('[mail]\nprovider = "none"',
                                    '[mail]\nprovider = "resend"\nkey_env = "RESEND_API_KEY"\nfrom = "hi@example.com"'))
    secrets(_home, ["RESEND_API_KEY"])
    assert row(platform.checks(no_net=True), "mail")["state"] == platform.OK
    assert platform.mail_ready(platform.load())


def test_llm_key_presence(_home):
    manifest(_home, MINIMAL.replace('[llm]\nprovider = "none"',
                                    '[llm]\nprovider = "openai"\nkey_env = "OPENAI_API_KEY"'))
    assert row(platform.checks(no_net=True), "llm")["state"] == platform.MISSING
    secrets(_home, ["OPENAI_API_KEY"])
    assert row(platform.checks(no_net=True), "llm")["state"] == platform.OK


# --- apple and android -------------------------------------------------------------

def apple_config(home: pathlib.Path, names=("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_TEAM_ID"), p8=True):
    d = home / ".appstoreconnect"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.env").write_text("".join(f"{n}=x\n" for n in names))
    if p8:
        (d / "private_keys").mkdir(exist_ok=True)
        (d / "private_keys" / "AuthKey_EXAMPLE.p8").write_text("-----BEGIN PRIVATE KEY-----\n")
    return d


def test_apple_absent_config(_home):
    manifest(_home, MINIMAL)
    r = row(platform.checks(no_net=True), "apple")
    assert r["state"] == platform.MISSING
    assert "appstoreconnect.apple.com" in r["todo"]


def test_apple_config_missing_an_id(_home):
    manifest(_home, MINIMAL)
    apple_config(_home, names=("ASC_KEY_ID", "ASC_ISSUER_ID"))
    r = row(platform.checks(no_net=True), "apple")
    assert r["state"] == platform.MISSING and "ASC_TEAM_ID" in r["todo"]


def test_apple_config_without_a_key_file(_home):
    manifest(_home, MINIMAL)
    apple_config(_home, p8=False)
    r = row(platform.checks(no_net=True), "apple")
    assert r["state"] == platform.MISSING and ".p8" in r["todo"]


def test_apple_complete(_home):
    manifest(_home, MINIMAL)
    apple_config(_home)
    tool = _home / "bin" / "testflight"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    r = row(platform.checks(no_net=True), "apple")
    assert r["state"] == platform.OK
    assert "3 ids" in r["detail"]


def test_android_states(_home):
    manifest(_home, MINIMAL)
    assert row(platform.checks(no_net=True), "android")["state"] == platform.MISSING

    manifest(_home, MINIMAL.replace("play_console = false", 'play_console = true\nkeystore = ""'))
    r = row(platform.checks(no_net=True), "android")
    assert r["state"] == platform.MISSING and "keytool" in r["todo"]

    ks = _home / "upload.jks"
    ks.write_text("x")
    manifest(_home, MINIMAL.replace("play_console = false", f'play_console = true\nkeystore = "{ks}"'))
    assert row(platform.checks(no_net=True), "android")["state"] == platform.OK


# --- rendering and the command -----------------------------------------------------

def test_render_and_json_and_owner_steps(_home):
    manifest(_home, MINIMAL)
    rows = platform.checks(no_net=True)
    text = platform.render(rows)
    assert "resource" in text and "what to do" in text
    assert "resource(s) not set up" in text
    data = platform.to_json(rows)
    assert set(data) == {"resources", "missing"}
    assert "mail" in data["missing"]
    steps = platform.owner_steps(rows)
    assert any(s.startswith("platform/mail:") for s in steps)


def test_cmd_exit_codes(_home, capsys):
    from teyla.cli import main
    assert main(["platform", "init", "--owner", "Someone"]) == 0
    capsys.readouterr()
    assert main(["platform", "--no-net"]) == 1          # a fresh manifest has nothing set up
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert main(["platform", "env-example"]) == 0
    assert "OPENAI_API_KEY=" in capsys.readouterr().out


def test_cmd_json(_home, capsys):
    import json
    from teyla.cli import main
    platform.init(owner="Someone")
    capsys.readouterr()
    main(["platform", "--no-net", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["missing"]


# --- the shipped templates ---------------------------------------------------------

def test_platform_templates_exist_and_shell_scripts_parse():
    import subprocess
    root = teyla.templates_dir() / "platform"
    for name in ("platform.toml", "Caddyfile", "README.md",
                 "setup-server.sh", "add-product.sh", "provision-droplet.sh"):
        assert (root / name).exists(), name
    for sh in sorted(root.glob("*.sh")):
        r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
        assert r.returncode == 0, f"{sh}: {r.stderr}"


def test_caddyfile_imports_each_product_block():
    text = (teyla.templates_dir() / "platform" / "Caddyfile").read_text()
    assert "import /srv/*/Caddyfile" in text


def test_no_secret_value_is_ever_shipped_in_the_template():
    text = (teyla.templates_dir() / "platform" / "platform.toml").read_text()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()          # the comments explain the format
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().endswith("_env"):
            # an env var NAME, not its value
            assert value.strip().strip('"').isupper(), raw
    assert "{{owner}}" in text
    assert "sk-" not in text


def test_secrets_empty_value_counts_as_unset(_home):
    """`teyla platform env-example` writes `NAME=` lines; a pasted skeleton must not read as set up."""
    import teyla.platform as pl
    f = _home / ".config" / "teyla" / "platform.env"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("OPENAI_API_KEY=\nexport RESEND_API_KEY=\"\"\nDIGITALOCEAN_ACCESS_TOKEN=dop_v1_x\n")
    f.chmod(0o600)
    assert pl.env_names(f) == {"DIGITALOCEAN_ACCESS_TOKEN"}
