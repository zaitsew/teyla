"""teyla scaffold: the LICENSE names the user, never the author of Teyla; the CI template obeys the shipped policy."""
import pathlib
import re
import subprocess

import pytest

from teyla import scaffold


def _no_git_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.mark.parametrize("lic", ["apache", "mit"])
def test_license_holder_is_the_given_owner(tmp_path, monkeypatch, lic):
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "repo"
    scaffold.scaffold(str(dest), name="widget", kind="cli", license=lic, owner="Ada Lovelace")
    text = (dest / "LICENSE").read_text()
    assert re.search(r"Copyright (\(c\) )?\d{4} Ada Lovelace", text)
    assert "{{" not in text


@pytest.mark.parametrize("lic", ["apache", "mit"])
def test_license_holder_falls_back_to_git_user_name(tmp_path, monkeypatch, lic):
    _no_git_identity(monkeypatch, tmp_path)
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = Grace Hopper\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    dest = tmp_path / "repo"
    scaffold.scaffold(str(dest), name="widget", kind="cli", license=lic)
    assert "Grace Hopper" in (dest / "LICENSE").read_text()


@pytest.mark.parametrize("lic", ["apache", "mit"])
def test_license_holder_without_any_name_is_neutral(tmp_path, monkeypatch, lic):
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "repo"
    scaffold.scaffold(str(dest), name="widget", kind="cli", license=lic)
    text = (dest / "LICENSE").read_text()
    assert "the authors" in text and "{{" not in text


def test_templates_do_not_hard_code_a_person():
    root = scaffold.TEMPLATE_ROOT
    for name in scaffold.LICENSE_TEMPLATES.values():
        body = (root / name).read_text()
        assert "{{owner}}" in body, name


def test_cli_passes_owner_through(tmp_path, monkeypatch):
    from teyla import cli
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "viacli"
    cli.main(["scaffold", str(dest), "--name", "widget", "--owner", "Linus T"])
    assert "Linus T" in (dest / "LICENSE").read_text()


def test_ci_template_is_manual_and_linux(tmp_path, monkeypatch):
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "repo"
    scaffold.scaffold(str(dest), name="widget", kind="cli", license="none")
    ci = (dest / ".github" / "workflows" / "ci.yml").read_text()
    on_block = ci.split("on:", 1)[1].split("jobs:", 1)[0]
    assert "workflow_dispatch" in on_block
    assert "push" not in on_block and "pull_request" not in on_block
    assert "runs-on: ubuntu-latest" in ci
    assert not re.search(r"^\s*runs-on:\s*macos", ci, re.M)


def test_productized_compose_fragment_gets_a_registry_owner(tmp_path, monkeypatch):
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "svc"
    dest.mkdir()
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", "git@github.com:AdaL/widget.git"], check=True)
    scaffold.scaffold(str(dest), name="widget", kind="service", license="none", owner="Ada Lovelace")
    frag = (dest / "deploy" / "droplet" / "docker-compose.fragment.yml").read_text()
    assert "image: ghcr.io/adal/widget:latest" in frag, "the GitHub owner, not the display name"
    assert "{{owner}}" not in frag
    assert "{{port}}" in frag  # the server's add-product.sh fills the port


def test_compose_fragment_without_any_owner_keeps_a_visible_placeholder(tmp_path, monkeypatch):
    _no_git_identity(monkeypatch, tmp_path)
    dest = tmp_path / "svc"
    scaffold.scaffold(str(dest), name="widget", kind="service", license="none", owner="Ada Lovelace")
    frag = (dest / "deploy" / "droplet" / "docker-compose.fragment.yml").read_text()
    assert "ghcr.io/your-github-owner/widget" in frag and "{{owner}}" not in frag
