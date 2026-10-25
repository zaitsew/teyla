"""The shipped templates/POLICY.md is a generic starter, and a policy that is not a copy of it is never
merged with it. Every path is moved into tmp_path."""
from __future__ import annotations

import pathlib
import re

import pytest

from teyla import config, policy

ROOT = pathlib.Path(__file__).resolve().parents[1]
STARTER = ROOT / "templates" / "POLICY.md"

# The owner's name, organisation, repos and dates never ship in a default.
# Written as character classes so this file does not itself hold the private terms the leak check looks for.
DENYLIST = (r"\bi[v]an\b", r"zaits[e]v", r"fabri[q]ue", r"zaits[e]w/", r"2026-")


def test_starter_is_short_and_marked():
    text = STARTER.read_text()
    assert len(text.splitlines()) <= 80
    assert policy.template_kind(text) == "starter"
    assert "{{owner}}" in text and "<placeholder>" in text


@pytest.mark.parametrize("name", ["POLICY.md", "POLICY.work.md", "CLAUDE.global.md"])
def test_shipped_templates_name_no_person_repo_or_date(name):
    text = (ROOT / "templates" / name).read_text()
    for term in DENYLIST:
        assert not re.search(term, text, re.I), f"{name} contains {term!r}"


def test_starter_keeps_what_other_commands_read():
    from teyla import detect, models
    text = STARTER.read_text()
    assert models.LADDER_START in text and models.LADDER_END in text
    active, unknown = detect.declared(text)
    assert active == ["ask-permission"] and unknown == []


@pytest.fixture
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".agents").mkdir(parents=True)
    monkeypatch.setattr(policy, "POLICY", home / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "BASE_PATH", home / ".teyla" / "policy-base.md")
    monkeypatch.setattr(policy, "CONFLICT_PATH", home / ".teyla" / "policy-merge-conflict.md")
    monkeypatch.setattr(policy, "PROPOSED_PATH", home / ".teyla" / "policy-proposed.md")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    return home


def test_init_writes_the_starter_with_its_marker(_home):
    assert policy.init(owner="Ada").startswith("wrote")
    text = policy.POLICY.read_text()
    assert policy.template_kind(text) == "starter" and "Owner: Ada." in text
    assert not policy.is_own()


def test_a_policy_without_the_marker_is_the_persons_own_and_is_never_merged(_home):
    mine = "# My policy\n\nOwner: Ada.\n\n## 7. Merging\nMy own merge list.\n"
    policy.POLICY.write_text(mine)
    policy.BASE_PATH.parent.mkdir(parents=True)
    policy.BASE_PATH.write_text("# an older, longer template\n")
    assert policy.is_own()
    out = policy.refresh()
    assert len(out) == 1 and "your own policy" in out[0]
    assert policy.POLICY.read_text() == mine
    assert policy.BASE_PATH.read_text() == "# an older, longer template\n"
    assert not policy.PROPOSED_PATH.exists() and not policy.CONFLICT_PATH.exists()


def test_a_policy_from_the_starter_still_merges_template_changes(_home, monkeypatch):
    policy.init(owner="Ada")
    policy.BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    policy.BASE_PATH.write_text(policy.render_template("Ada"))
    assert policy.refresh() == ["template unchanged since last refresh"]
    newer = STARTER.read_text().replace("Merge, never squash.", "Merge, never squash. New line.")
    monkeypatch.setattr(policy, "TEMPLATE", _write(_home / "t.md", newer))
    out = policy.refresh()
    assert out and ("merged" in out[0] or "applied" in out[0])
    assert "New line." in policy.POLICY.read_text()


def _write(path, text):
    path.write_text(text)
    return path
