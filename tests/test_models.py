"""teyla.models — fixture catalogues stand in for models.dev / Grok / Codex / POLICY.md so these
tests never depend on what happens to be installed on the machine running them."""
from __future__ import annotations

import json

import pytest

from teyla import models, pricing

CATALOGUE = {
    "anthropic": {"env": ["ANTHROPIC_API_KEY"], "models": {
        "claude-fable-5": {"name": "Claude Fable 5", "family": "claude-fable", "release_date": "2026-06-07",
                            "cost": {"input": 10, "output": 50, "cache_read": 1, "cache_write": 12.5}},
        "claude-fable-5-1": {"name": "Claude Fable 5.1", "family": "claude-fable", "release_date": "2026-09-01",
                              "cost": {"input": 10, "output": 50, "cache_read": 0.25, "cache_write": 12.5}},
        "claude-opus-5": {"name": "Claude Opus 5", "family": "claude-opus", "release_date": "2026-07-24",
                           "cost": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 6.25}},
        "claude-sonnet-5": {"name": "Claude Sonnet 5", "family": "claude-sonnet", "release_date": "2026-06-29",
                             "cost": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 2.5}},
        "claude-haiku-4-5": {"name": "Claude Haiku 4.5", "family": "claude-haiku", "release_date": "2025-10-15",
                              "cost": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 1.25}},
    }},
    "openai": {"env": ["OPENAI_API_KEY"], "models": {
        "gpt-5.6-sol": {"name": "GPT-5.6 Sol", "family": "gpt-sol", "release_date": "2026-07-09",
                         "cost": {"input": 4, "output": 20, "cache_read": 0.4, "cache_write": 5}},
        "gpt-5.6-terra": {"name": "GPT-5.6 Terra", "family": "gpt-terra", "release_date": "2026-07-09",
                           "cost": {"input": 2, "output": 12, "cache_read": 0.2, "cache_write": 2.5}},
        "gpt-5.6-luna": {"name": "GPT-5.6 Luna", "family": "gpt-luna", "release_date": "2026-07-09",
                          "cost": {"input": 0.2, "output": 1.2, "cache_read": 0.02, "cache_write": 0.25}},
        "gpt-5.5": {"name": "GPT-5.5", "family": "gpt", "release_date": "2025-11-13",
                     "cost": {"input": 1.25, "output": 10, "cache_read": 0.125}},
    }},
    "xai": {"env": ["XAI_API_KEY"], "models": {
        "grok-4.5": {"name": "Grok 4.5", "family": "grok", "release_date": "2026-07-08",
                      "cost": {"input": 2, "output": 6, "cache_read": 0.3}},
        "grok-4.6": {"name": "Grok 4.6", "family": "grok", "release_date": "2026-08-12",
                      "cost": {"input": 2, "output": 6, "cache_read": 0.5}},
    }},
}

POLICY_FIXTURE = """# How to run a session

## 1. The model ladder

<!-- ladder:start — maintained by `teyla models --write-policy` -->
| provider | orchestrate / hardest tasks | volume work | throwaway / triage | note |
|---|---|---|---|---|
| Anthropic | Claude Fable 5.1 | Opus 5, Sonnet 5 | Haiku 4.5 | anthropic note |
| OpenAI | GPT-6 Astra | GPT-5.6 Sol/Terra | GPT-5.6 Luna | openai note |
| xAI | Grok 4.6 | Grok 4.6, Grok 4.5 | — | xai note |
<!-- ladder:end -->

## 2. Second opinions

unrelated text that must never change
"""


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    """Point every path teyla.models reads/writes at tmp_path, and stub out the one live
    subprocess call, so these tests never touch this machine's real caches or keychain."""
    models_dev = tmp_path / "models_dev_cache.json"
    models_dev.write_text(json.dumps(CATALOGUE))
    monkeypatch.setattr(models, "MODELS_DEV_CACHE", models_dev)
    monkeypatch.setattr(models, "MODELS_DEV_FALLBACK", tmp_path / "models_dev_fallback.json")

    grok_cache = tmp_path / "grok_models_cache.json"
    grok_cache.write_text(json.dumps({"models": {"grok-4.6": {}, "grok-4.5": {}}}))
    monkeypatch.setattr(models, "GROK_CACHE", grok_cache)
    monkeypatch.setattr(models, "GROK_AUTH", tmp_path / "grok_auth_missing.json")

    codex_cache = tmp_path / "codex_models_cache.json"
    codex_cache.write_text(json.dumps({"models": [{"slug": "gpt-6-astra"}, {"slug": "gpt-5.6-sol"},
                                                    {"slug": "gpt-5.6-terra"}, {"slug": "gpt-5.6-luna"}]}))
    monkeypatch.setattr(models, "CODEX_CACHE", codex_cache)
    codex_config = tmp_path / "codex_config.toml"
    codex_config.write_text('model = "gpt-6-astra"\nmodel_reasoning_effort = "low"\n')
    monkeypatch.setattr(models, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(models, "CODEX_AUTH", tmp_path / "codex_auth_missing.json")

    prices_out = tmp_path / "prices.json"
    monkeypatch.setattr(models, "PRICES_OUT", prices_out)
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", prices_out)

    policy_path = tmp_path / "POLICY.md"
    policy_path.write_text(POLICY_FIXTURE)
    monkeypatch.setattr("teyla.policy.POLICY", policy_path)

    # No live credentials by default; individual tests override via monkeypatch.setenv/setattr.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(models.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no security binary in tests")))

    return tmp_path


# --- parsing the ladder table -------------------------------------------------

def test_parse_ladder_splits_cells_and_expands_slash_prefix():
    ladder = models.parse_ladder(POLICY_FIXTURE)
    assert set(ladder) == {"anthropic", "openai", "xai"}
    assert ladder["anthropic"]["orchestrate"] == ["Claude Fable 5.1"]
    assert ladder["anthropic"]["volume"] == ["Opus 5", "Sonnet 5"]
    assert ladder["anthropic"]["triage"] == ["Haiku 4.5"]
    # "GPT-5.6 Sol/Terra" -> two entries, prefix shared
    assert ladder["openai"]["volume"] == ["GPT-5.6 Sol", "GPT-5.6 Terra"]
    assert ladder["xai"]["triage"] == []  # "—" is not a model
    assert ladder["anthropic"]["note"] == "anthropic note"


def test_parse_ladder_no_markers_returns_empty():
    assert models.parse_ladder("# no markers here at all") == {}


# --- resolving a ladder entry to a real id -----------------------------------

@pytest.mark.parametrize("name,provider,expect_id", [
    ("Claude Fable 5.1", "anthropic", "claude-fable-5-1"),
    ("Opus 5", "anthropic", "claude-opus-5"),
    ("Sonnet 5", "anthropic", "claude-sonnet-5"),
    ("Haiku 4.5", "anthropic", "claude-haiku-4-5"),
    ("GPT-5.6 Sol", "openai", "gpt-5.6-sol"),
    ("GPT-5.6 Terra", "openai", "gpt-5.6-terra"),
    ("GPT-5.6 Luna", "openai", "gpt-5.6-luna"),
    ("Grok 4.6", "xai", "grok-4.6"),
    ("Grok 4.5", "xai", "grok-4.5"),
])
def test_resolve_known_ladder_entries(name, provider, expect_id):
    resolved = models.resolve_ladder_entry(name, provider, CATALOGUE, [])
    assert resolved is not None
    assert resolved["id"] == expect_id


def test_resolve_via_cli_cache_when_absent_from_models_dev():
    # "GPT-6 Astra" is not in the models.dev fixture at all — only Codex's own cache knows it.
    resolved = models.resolve_ladder_entry("GPT-6 Astra", "openai", CATALOGUE, ["gpt-6-astra"])
    assert resolved is not None
    assert resolved["id"] == "gpt-6-astra"
    assert resolved["source"] == "cli-cache"


def test_resolve_unknown_model_returns_none():
    assert models.resolve_ladder_entry("Claude Zeta 9", "anthropic", CATALOGUE, []) is None


def test_resolve_descriptive_phrase_is_not_unknown():
    # No digit, no non-filler word: prose, not a model claim.
    resolved = models.resolve_ladder_entry("the hardest tasks", "anthropic", CATALOGUE, [])
    assert resolved is not None
    assert resolved["source"] == "descriptive"


# --- drift flags ---------------------------------------------------------------

def _snapshot(**kw):
    kw.setdefault("claude_used_models", [])
    return models.snapshot(**kw)


def test_drift_flags_ladder_unknown_model():
    text = POLICY_FIXTURE.replace("Claude Fable 5.1 |", "Claude Zeta 9 |", 1)
    from teyla import policy as _policy
    _policy.POLICY.write_text(text)
    snap = _snapshot()
    flags = models.drift(snap)
    unknown = [f for f in flags if f["flag"] == "LADDER-UNKNOWN"]
    assert any(f["entry"] == "Claude Zeta 9" for f in unknown)


def test_drift_newer_available_only_when_the_newer_model_is_not_listed(monkeypatch):
    from teyla import policy as _policy
    # ladder's xai volume row is "Grok 4.6, Grok 4.5": 4.6 sits beside 4.5, so 4.5 is not drift...
    snap = _snapshot()
    flags = models.drift(snap)
    assert not any(f["flag"] == "NEWER-AVAILABLE" and f["provider"] == "xai" for f in flags)
    # ...but a volume row of "Grok 4.5" alone is.
    text = _policy.POLICY.read_text().replace("| Grok 4.6, Grok 4.5 |", "| Grok 4.5 |")
    _policy.POLICY.write_text(text)
    flags = models.drift(_snapshot())
    assert any(f["flag"] == "NEWER-AVAILABLE" and f["provider"] == "xai" and f["entry"] == "Grok 4.5" for f in flags)
    # the already-newest entry in the same row must not itself be flagged


def test_drift_flags_no_credential_for_ladder_provider():
    # no env vars set (autouse fixture clears them), security lookup stubbed to fail -> no anthropic credential
    snap = _snapshot()
    flags = models.drift(snap)
    assert any(f["flag"] == "NO-CREDENTIAL" and f["provider"] == "anthropic" for f in flags)


def test_drift_flags_unlisted_provider_when_ladder_row_missing(monkeypatch):
    text = POLICY_FIXTURE.replace(
        "| xAI | Grok 4.6 | Grok 4.6, Grok 4.5 | — | xai note |\n", "")
    from teyla import policy as _policy
    _policy.POLICY.write_text(text)
    monkeypatch.setenv("XAI_API_KEY", "present-for-test-only")
    snap = _snapshot()
    flags = models.drift(snap)
    assert any(f["flag"] == "UNLISTED-PROVIDER" and f["provider"] == "xai" for f in flags)


def test_drift_flags_price_stale_over_20_percent(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "claude-opus-5", (50.0, 62.5, 5.0, 250.0, "volume", False))
    try:
        snap = _snapshot()
        flags = models.drift(snap)
        stale = [f for f in flags if f["flag"] == "PRICE-STALE" and f["entry"] == "claude-opus-5"]
        assert stale, flags
    finally:
        del pricing.PRICES["claude-opus-5"]


def test_drift_flags_price_missing_for_ladder_model_not_in_pricing(monkeypatch):
    monkeypatch.setattr(pricing, "PRICES", {})
    snap = _snapshot()
    flags = models.drift(snap)
    missing = [f for f in flags if f["flag"] == "PRICE-STALE" and f["entry"] == "Claude Fable 5.1"]
    assert missing


def test_drift_empty_for_a_fully_current_ladder_and_full_credentials(monkeypatch):
    # Bring the ladder's one stale entry (Grok 4.5) up to date and grant every credential.
    text = POLICY_FIXTURE.replace("Grok 4.6, Grok 4.5 | —", "Grok 4.6 | —")
    from teyla import policy as _policy
    _policy.POLICY.write_text(text)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("XAI_API_KEY", "x")
    # A pricing table that exactly matches the fixture catalogue (including the CLI-only
    # gpt-6-astra, which has no models.dev cost) — real pricing.PRICES has its own known-stale
    # entries (that's what the other PRICE-STALE test exercises) and would fail this one.
    clean_prices = {
        "claude-fable-5-1": (10, 12.5, 0.25, 50, "orchestrate", True),
        "claude-opus-5": (5, 6.25, 0.5, 25, "volume", True),
        "claude-sonnet-5": (2, 2.5, 0.2, 10, "volume", True),
        "claude-haiku-4-5": (1, 1.25, 0.1, 5, "triage", True),
        "gpt-6-astra": (10, 10, 2.5, 50, "orchestrate", True),
        "gpt-5.6-sol": (4, 5, 0.4, 20, "volume", True),
        "gpt-5.6-terra": (2, 2.5, 0.2, 12, "volume", True),
        "gpt-5.6-luna": (0.2, 0.25, 0.02, 1.2, "triage", True),
        "grok-4.6": (2, 2, 0.5, 6, "orchestrate", True),
    }
    monkeypatch.setattr(pricing, "PRICES", clean_prices)
    snap = _snapshot()
    flags = models.drift(snap)
    assert flags == [], flags


# --- --write-policy -------------------------------------------------------------

def test_write_policy_dry_run_does_not_write(monkeypatch):
    from teyla import policy as _policy
    before = _policy.POLICY.read_text()
    diff, changed = models.write_policy(dry=True, claude_used_models=[])
    assert _policy.POLICY.read_text() == before
    assert changed  # the review-date note is new even when every model still resolves
    assert "reviewed" in diff


def test_write_policy_only_touches_the_span_between_markers():
    from teyla import policy as _policy
    diff, changed = models.write_policy(dry=False, claude_used_models=[])
    after = _policy.POLICY.read_text()
    assert after.startswith("# How to run a session")
    assert after.rstrip().endswith("unrelated text that must never change")
    assert models.LADDER_START in after and models.LADDER_END in after


def test_write_policy_keeps_known_models_and_appends_review_note():
    diff, changed = models.write_policy(dry=False, claude_used_models=[])
    from teyla import policy as _policy
    after = _policy.POLICY.read_text()
    assert "Claude Fable 5.1" in after
    assert "Opus 5, Sonnet 5" in after
    assert "reviewed" in after and "by teyla models" in after


def test_write_policy_replaces_unknown_model_with_newest_of_guessed_family():
    text = POLICY_FIXTURE.replace("Opus 5, Sonnet 5", "Opus 3, Sonnet 5", 1)
    from teyla import policy as _policy
    _policy.POLICY.write_text(text)
    models.write_policy(dry=False, claude_used_models=[])
    after = _policy.POLICY.read_text()
    # "Opus 3" resolves to nothing; the family guess ("opus" -> claude-opus) picks the newest: Claude Opus 5
    assert "Claude Opus 5" in after
    assert "Opus 3" not in after


def test_write_policy_raises_without_markers(tmp_path):
    p = tmp_path / "no-markers.md"
    p.write_text("# nothing here")
    with pytest.raises(ValueError):
        models.write_policy(path=p, claude_used_models=[])


# --- --write-policy --drop-absent ------------------------------------------------
#
# In the fixture, anthropic has no credential and (with claude_used_models=[]) no CLI usage
# either; openai and xai both have a local CLI cache (Codex/Grok), so they count as "available"
# even without a credential and must not be treated as absent.

def test_absent_providers_flags_only_anthropic():
    cli_ids = dict(models.cli_available_models())
    cli_ids["anthropic"] = []
    assert models.absent_providers(models.credentials(), cli_ids) == ["anthropic"]


def test_write_policy_drop_absent_removes_the_absent_providers_row():
    models.write_policy(dry=False, claude_used_models=[], drop_absent=True)
    from teyla import policy as _policy
    after = _policy.POLICY.read_text()
    assert "Anthropic" not in after
    assert "OpenAI" in after
    assert "xAI" in after


def test_write_policy_without_drop_absent_keeps_every_row():
    models.write_policy(dry=False, claude_used_models=[], drop_absent=False)
    from teyla import policy as _policy
    after = _policy.POLICY.read_text()
    assert "Anthropic" in after and "OpenAI" in after and "xAI" in after


def test_cmd_models_warns_about_absent_provider_without_drop_absent(capsys, monkeypatch):
    import argparse
    monkeypatch.setattr(models, "claude_used_models_from_disk", lambda days=30: [])
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    models.register(sp)
    args = p.parse_args(["models", "--write-policy"])
    models.cmd_models(args)
    out = capsys.readouterr().out
    assert "provider Anthropic has no credential" in out
    assert "--drop-absent" in out


def test_cmd_models_no_warning_with_drop_absent(capsys, monkeypatch):
    import argparse
    monkeypatch.setattr(models, "claude_used_models_from_disk", lambda days=30: [])
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    models.register(sp)
    args = p.parse_args(["models", "--write-policy", "--drop-absent"])
    models.cmd_models(args)
    out = capsys.readouterr().out
    assert "no credential" not in out


# --- --write-prices --------------------------------------------------------------

def test_write_prices_infers_tier_from_ladder():
    path = models.write_prices(claude_used_models=[])
    data = json.loads(path.read_text())
    assert data["claude-fable-5-1"]["tier"] == "orchestrate"
    assert data["claude-opus-5"]["tier"] == "volume"
    assert data["claude-haiku-4-5"]["tier"] == "triage"
    # claude-fable-5 (the older release) is not named by the ladder -> unknown
    assert data["claude-fable-5"]["tier"] == "unknown"
    assert data["claude-fable-5-1"]["verified"] is True
    assert data["claude-fable-5-1"]["source"] == "models.dev"


def test_pricing_effective_prices_prefers_written_overrides():
    models.write_prices(claude_used_models=[])
    row = pricing.lookup("claude-fable-5-1-20260901")
    assert row is not None
    in_price, cache_write, cache_read, out_price, tier, verified = row
    assert in_price == 10
    assert out_price == 50
    assert tier == "orchestrate"


def test_pricing_falls_back_to_builtin_table_without_override_file():
    assert pricing.lookup("claude-sonnet-5-20260629") is not None  # from the built-in PRICES table


# --- credentials / CLI availability ---------------------------------------------

def test_credentials_presence_only(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-test")
    cred = models.credentials()
    assert cred["openai"] is True
    assert cred["anthropic"] is False  # env unset, security stubbed to fail
    assert cred["google"] is False


def test_cli_available_models_reads_grok_and_codex_fixtures():
    avail = models.cli_available_models()
    assert avail["xai"] == ["grok-4.5", "grok-4.6"]
    assert "gpt-6-astra" in avail["openai"]


def test_codex_config_model_reads_toml():
    assert models.codex_config_model() == "gpt-6-astra"


# --- rendering (smoke) -----------------------------------------------------------

def test_render_table_smoke():
    snap = _snapshot()
    flags = models.drift(snap)
    out = models.render_table(snap, flags)
    assert "Anthropic" in out and "OpenAI" in out and "xAI" in out
    assert "drift" in out


def test_render_json_shape():
    snap = _snapshot()
    flags = models.drift(snap)
    out = models.render_json(snap, flags)
    assert set(out) == {"snapshot", "drift"}
    assert out["snapshot"] is snap
    assert out["drift"] is flags
