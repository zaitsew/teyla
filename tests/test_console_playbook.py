"""The Playbook section (docs/CONSOLE.md): each part on its own, nothing from this machine, nothing from the network."""
from __future__ import annotations

import json
import subprocess

import pytest

from teyla import config, console_playbook as pb, models, models_arena, policy, you

NOW = 1_793_000_000.0      # 2026-10-26


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".teyla").mkdir(parents=True)
    code, ops = tmp_path / "code", tmp_path / "ops"
    code.mkdir()
    ops.mkdir()
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "TEYLA_DIR", h / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", h / ".teyla" / "config.toml")
    (h / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\nops_root = "{ops}"\n')
    monkeypatch.setenv("TEYLA_HOME", str(h / ".teyla"))
    monkeypatch.setattr(policy, "POLICY", h / "POLICY.md")
    (h / "POLICY.md").write_text("# Policy\n")
    for name in ("MODELS_DEV_CACHE", "MODELS_DEV_FALLBACK", "GROK_CACHE", "GROK_AUTH", "CODEX_CACHE", "CODEX_AUTH", "HERMES_AUTH"):
        monkeypatch.setattr(models, name, tmp_path / f"missing-{name}.json")
    monkeypatch.setattr(models, "CODEX_CONFIG", tmp_path / "missing-codex.toml")
    # `you` reads this machine's sessions and leak rules; a test gets neither
    monkeypatch.setattr(you, "_collect_asks", lambda: [])
    monkeypatch.setattr(you, "Screen", lambda: type("S", (), {"ok": lambda self, line: True, "terms_loaded": True})())
    return h


def test_guidelines_list_the_standards_the_policy_and_the_design_docs(home, tmp_path, monkeypatch):
    repo = tmp_path / "teyla-checkout"
    for rel in ("templates/design/STANDARD.md", "docs/WRITING.md", "templates/voice/VOICE.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n")
    monkeypatch.setattr(pb, "_repo_root", lambda: repo)
    app = tmp_path / "code" / "app-a"
    (app / ".git").mkdir(parents=True)
    (app / "DESIGN.md").write_text("# Design\n")
    rows = {r["id"]: r for r in pb._guidelines(NOW)}
    assert rows["ux"]["exists"] and rows["ux"]["path"].endswith("templates/design/STANDARD.md") and rows["ux"]["updated"]
    assert not rows["copy"]["exists"] and rows["copy"]["path"] is None          # docs/COPY.md is not in this fake checkout
    assert rows["policy"]["path"] == str(home / "POLICY.md")
    assert rows["design-md"]["count"] == 1 and "1 products" in rows["design-md"]["summary"]
    assert all(r["summary"] and r["title"] for r in rows.values())


def test_updated_prefers_the_git_date(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    f = tmp_path / "a.md"
    f.write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "m",
                    "--date=2026-01-02T00:00:00"], check=True, env={"GIT_COMMITTER_DATE": "2026-01-02T00:00:00", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
    assert pb._updated(f) == "2026-01-02"
    assert pb._updated(tmp_path / "missing.md") is None


def test_models_part_carries_the_arena_shortlist_as_candidates(home, monkeypatch):
    p = models_arena.snapshot_path()
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(dict(as_of="2026-10-20", source="pasted", entries=[dict(model="Nova 9", score=1450, cost=0.9, pareto=True)])))
    m = pb._models(NOW)
    assert m["arena"]["top"][0]["model"] == "Nova 9" and m["arena"]["top"][0]["status"] == "candidate, not a decision"
    assert m["arena"]["as_of"] == "2026-10-20" and m["arena"]["url"].endswith("/pareto")
    assert isinstance(m["drift"], list) and isinstance(m["ladder"], list) and m["new_note"]


def test_models_part_without_a_board_says_why(home):
    a = pb._models(NOW)["arena"]
    assert a["top"] == [] and "paste a snapshot" in a["note"]


def test_knowledge_reads_wiki_intent_corrections_and_taste(home, tmp_path):
    wiki = tmp_path / "ops" / "wiki"
    (wiki / "pages").mkdir(parents=True)
    k = pb._knowledge(NOW)
    assert k["wiki"]["pages"] == 0 and k["intent"]["entries"] == 0 and k["corrections"]["total"] == 0
    assert k["taste"]["total"] == 0
    d = tmp_path / "code" / "app-a" / "design" / "decisions"
    d.mkdir(parents=True)
    (d / "aaaa1111.json").write_text(json.dumps({"decision": "rule", "date": "2026-10-01"}))
    (d / "bbbb2222.json").write_text(json.dumps({"decision": "reject", "date": "2026-10-02"}))
    t = pb._taste()
    assert t["total"] == 2 and t["rule"] == 1 and t["reject"] == 1 and t["repos"] == 1


def test_no_wiki_is_a_note_not_an_error(home):
    assert pb._wiki()["pages"] is None


def test_a_failing_part_shows_its_error_and_the_rest_load(home, monkeypatch):
    def boom(now):
        raise RuntimeError("broken store")
    monkeypatch.setattr(pb, "_models", boom)
    sec = pb.section(NOW)
    assert "RuntimeError" in sec["models"]["error"] and "guidelines" in sec and "knowledge" in sec


def test_the_headline_is_a_dash_until_you_computes_it(home):
    h = pb._headline({})
    assert h["label"] == "Unresolved contradictions" and h["value"] is None
    h = pb.section(NOW)["headline"]
    assert h["label"] == "Unresolved contradictions" and h["value"] == 0 and "conflicting rules are not checked" in h["detail"]
    assert pb._headline({"you": {"contradictions": {"count": 4, "detail": "4 themes repeat after a rule"}}})["value"] == 4


def test_compact_is_small_and_keeps_you_off_the_relay_by_default(home, monkeypatch):
    sec = pb.section(NOW)
    sec["you"] = {"quote_of_the_day": {"text": "q"}, "delegation": [{"status": "open"}, {"status": "done"}]}
    c = pb.compact(sec)
    assert "you" not in c and "quote" not in json.dumps(c) and c["headline"]["label"]
    (home / ".teyla" / "config.toml").write_text('[you]\nrelay = true\n')
    c2 = pb.compact(sec)
    assert c2["you"]["chores_open"] == 1 and c2["you"]["quote"]["text"] == "q"
