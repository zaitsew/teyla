"""teyla models watch — fixture catalogue, fixture POLICY.md, fake repos under a tmp code_root, a tmp
HOME. Nothing here reads the real caches, the real ~/.teyla or the network."""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess

import pytest

from teyla import cli, config, digest, models, models_watch, pricing, routine_install

from test_models import CATALOGUE, POLICY_FIXTURE


def _model(family, date, name, cin=1.0, cout=5.0):
    return {"name": name, "family": family, "release_date": date, "cost": {"input": cin, "output": cout}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    code = tmp_path / "code"
    code.mkdir()
    (home / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\n')

    cache = tmp_path / "models_dev_cache.json"
    cache.write_text(json.dumps(CATALOGUE))
    monkeypatch.setattr(models, "MODELS_DEV_CACHE", cache)
    monkeypatch.setattr(models, "MODELS_DEV_FALLBACK", tmp_path / "models_dev_fallback.json")
    for name in ("GROK_CACHE", "GROK_AUTH", "CODEX_CACHE", "CODEX_AUTH", "HERMES_AUTH"):
        monkeypatch.setattr(models, name, tmp_path / f"missing-{name}.json")
    monkeypatch.setattr(models, "CODEX_CONFIG", tmp_path / "missing-codex.toml")
    prices = tmp_path / "prices.json"
    monkeypatch.setattr(models, "PRICES_OUT", prices)
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", prices)
    policy_path = tmp_path / "POLICY.md"
    policy_path.write_text(POLICY_FIXTURE)
    monkeypatch.setattr("teyla.policy.POLICY", policy_path)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    class E:
        pass
    e = E()
    e.home, e.code, e.cache, e.policy = home, code, cache, policy_path
    e.known = home / ".teyla" / "models-known.json"

    def publish(extra: dict):
        cat = copy.deepcopy(CATALOGUE)
        for provider, mods in extra.items():
            cat[provider]["models"].update(mods)
        cache.write_text(json.dumps(cat))
    e.publish = publish
    return e


def git_repo(root: pathlib.Path, name: str, files: dict[str, str]) -> pathlib.Path:
    repo = root / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for rel, text in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


NEW_OPUS = {"anthropic": {"claude-opus-5-1": _model("claude-opus", "2026-09-20", "Claude Opus 5.1", 5, 25)}}


def run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


# --- the known list ---------------------------------------------------------------------------

def test_first_run_seeds_the_known_list_and_reports_nothing_new(env, capsys):
    code, out = run(["models", "watch"], capsys)
    assert code == 0
    assert "first run: seeded" in out and "new models: none" in out
    known = json.loads(env.known.read_text())
    assert set(known["known"]) == {"anthropic", "openai", "xai"}
    assert "claude-opus-5" in known["known"]["anthropic"] and known["acked"]


def test_second_run_without_changes_does_not_rewrite_or_report(env, capsys):
    run(["models", "watch"], capsys)
    before = env.known.read_text()
    code, out = run(["models", "watch"], capsys)
    assert code == 0 and "first run" not in out
    assert env.known.read_text() == before


def test_new_model_is_detected_with_price_date_and_the_entry_it_replaces(env, capsys):
    run(["models", "watch"], capsys)
    env.publish(NEW_OPUS)
    code, out = run(["models", "watch"], capsys)
    assert code == 1
    assert "anthropic:claude-opus-5-1" in out and "2026-09-20" in out and "$5/$25 per 1M" in out
    assert "replaces Opus 5 (volume, claude-opus-5)" in out
    rep = models_watch.watch()
    (n,) = rep["new"]
    assert n["replaces"] == {"entry": "Opus 5", "id": "claude-opus-5", "tier": "volume"}


def test_new_family_and_non_text_models(env, capsys):
    run(["models", "watch"], capsys)
    env.publish({"openai": {"gpt-7-nova": _model("gpt-nova", "2026-09-25", "GPT-7 Nova"),
                             "text-embed-9": {**_model("embed", "2026-09-25", "Embed 9"),
                                              "modalities": {"output": ["embedding"]}}}})
    code, out = run(["models", "watch", "--json"], capsys)
    rep = json.loads(out)
    assert code == 1
    assert [(n["id"], n["replaces"]) for n in rep["new"]] == [("gpt-7-nova", None)]  # embeddings are not text models
    code, out = run(["models", "watch"], capsys)
    assert "openai:gpt-7-nova" in out and "new family" in out


def test_same_family_variant_picks_the_closest_ladder_entry(env):
    models_watch.watch()
    env.publish({"xai": {"grok-4.7": _model("grok", "2026-09-30", "Grok 4.7"),
                          "grok-4.7-build-fast": _model("grok", "2026-09-30", "Grok 4.7 Build Fast")}})
    rep = models_watch.watch()
    by_id = {n["id"]: n for n in rep["new"]}
    assert by_id["grok-4.7"]["replaces"]["id"] == "grok-4.6"
    # no ladder entry is a "build-fast" variant, so the plain model is the closest in both cases
    assert by_id["grok-4.7-build-fast"]["replaces"]["id"] == "grok-4.6"


def test_a_provider_that_joins_the_ladder_later_is_seeded_not_reported(env):
    env.policy.write_text(POLICY_FIXTURE.replace("| xAI | Grok 4.6 | Grok 4.6, Grok 4.5 | — | xai note |\n", ""))
    models_watch.watch()
    assert "xai" not in json.loads(env.known.read_text())["known"]
    env.policy.write_text(POLICY_FIXTURE)
    rep = models_watch.watch()
    assert rep["new"] == [] and "xai" in json.loads(env.known.read_text())["known"]


# --- superseded ids in repos -------------------------------------------------------------------

def test_superseded_id_found_in_a_repo_file_and_exact_token_match(env, capsys):
    git_repo(env.code, "alpha", {
        "src/app.py": 'MODEL = "claude-sonnet-4"\nOTHER = "claude-opus-5"\nx = 1\n',
        "package-lock.json": '"claude-opus-5"',
        "config/models.toml": "gpt-5.5-turbo is not gpt-5.5, but gpt-5.5 is.\n",
    })
    git_repo(env.code, "beta", {"README.md": "nothing here\n"})
    (env.code / "not-a-repo").mkdir()
    (env.code / "not-a-repo" / "x.py").write_text("claude-opus-5")
    cat = copy.deepcopy(CATALOGUE)
    cat["anthropic"]["models"]["claude-sonnet-4"] = _model("claude-sonnet", "2025-05-01", "Claude Sonnet 4")
    cat["anthropic"]["models"]["claude-sonnet-5"]["release_date"] = "2026-06-29"
    cat["openai"]["models"]["gpt-5.5"]["family"] = "gpt-sol"
    env.cache.write_text(json.dumps(cat))
    models_watch.watch()  # seed: nothing is new, the superseded scan still runs
    code, out = run(["models", "watch"], capsys)
    rows = {(r["repo"], r["file"]): r for r in models_watch.watch()["superseded"]}
    assert ("alpha", "src/app.py") in rows and "claude-sonnet-4" in rows[("alpha", "src/app.py")]["ids"]
    assert rows[("alpha", "src/app.py")]["lines"] == 1  # claude-opus-5 is a current ladder entry, not superseded
    assert not any(k[1] == "package-lock.json" for k in rows)  # lockfiles are skipped
    assert ("alpha", "config/models.toml") in rows and rows[("alpha", "config/models.toml")]["ids"] == ["gpt-5.5"]  # not gpt-5.5-turbo
    assert not any(k[0] in ("beta", "not-a-repo") for k in rows)
    assert "alpha/src/app.py  1 line(s)  claude-sonnet-4" in out


def test_replaced_ladder_entry_is_searched_and_big_files_skipped(env):
    models_watch.watch()
    git_repo(env.code, "alpha", {"a.py": 'M = "claude-opus-5"\n'})
    big = env.code / "alpha" / "big.txt"
    big.write_text("claude-opus-5 " * 200_000)
    subprocess.run(["git", "-C", str(env.code / "alpha"), "add", "-A"], check=True)
    env.publish(NEW_OPUS)
    rep = models_watch.watch()
    files = [(r["file"], r["why"]) for r in rep["superseded"]]
    assert files == [("a.py", {"claude-opus-5": "replaced by claude-opus-5-1"})]


LIVE_AND_HISTORY = {
    "src/router.py": 'DEFAULT_MODEL = "claude-opus-5"\n',            # live
    ".env.example": "MODEL=claude-opus-5\n",                        # live
    "src/limits.py": '"claude-opus-5": (15, 75),\nFALLBACK = "claude-opus-5"\n',  # one price row, one live line
    "tests/test_router.py": 'assert MODEL == "claude-opus-5"\n',     # tests, in four shapes
    "web/app.test.ts": 'expect(m).toBe("claude-opus-5")\n',
    "pkg/router_test.go": 'const m = "claude-opus-5"\n',
    "lib/router_spec.rb": 'MODEL = "claude-opus-5"\n',
    "src/pricing.py": 'TABLE = {"claude-opus-5": None}\n',          # price table by path
    "src/rates.py": 'RATES = {"claude-opus-5": {"input": 15, "output": 75}}\n',   # price rows alone
    "docs/models.md": "We used claude-opus-5 here.\n",              # docs and changelogs
    "CHANGELOG.md": "- moved off claude-opus-5\n",
    "db/migrations/001_seed.sql": "insert into m values ('claude-opus-5');\n",
}


def test_only_live_code_and_config_are_action_items_the_rest_is_one_count(env, capsys):
    models_watch.watch()
    git_repo(env.code, "alpha", LIVE_AND_HISTORY)
    env.publish(NEW_OPUS)
    rep = models_watch.watch()
    assert sorted(r["file"] for r in rep["superseded"]) == [".env.example", "src/limits.py", "src/router.py"]
    assert {r["file"]: r["lines"] for r in rep["superseded"]}["src/limits.py"] == 1  # the price row is not usage
    assert rep["superseded_history"] == {"test": 4, "price": 2, "doc": 2, "migration": 1}
    code, out = run(["models", "watch"], capsys)
    assert "superseded ids in use (3 file(s)" in out
    assert out.count("alpha/") == 3 and "tests/test_router.py" not in out and "CHANGELOG.md" not in out
    assert "+9 file(s) in tests, price tables, docs, migrations — historical, not usage" in out
    code, out = run(["models", "watch", "--json"], capsys)
    assert json.loads(out)["superseded_history"]["test"] == 4


def test_history_alone_is_not_reported_as_usage(env, capsys):
    models_watch.watch()
    git_repo(env.code, "alpha", {k: v for k, v in LIVE_AND_HISTORY.items()
                                 if k not in ("src/router.py", ".env.example", "src/limits.py")})
    env.publish(NEW_OPUS)
    rep = models_watch.watch()
    assert rep["superseded"] == [] and sum(rep["superseded_history"].values()) == 9
    code, out = run(["models", "watch"], capsys)
    assert "superseded ids in use: none in live code or config" in out
    assert "+9 file(s) in tests, price tables, docs, migrations — historical, not usage" in out


def test_a_nothing_found_run_has_no_history_line(env, capsys):
    models_watch.watch()
    git_repo(env.code, "alpha", {"src/app.py": "x = 1\n"})
    code, out = run(["models", "watch"], capsys)
    assert "none in live code or config" in out and "historical" not in out


@pytest.mark.parametrize("line", [
    '"claude-opus-5": (15, 75),', "| claude-opus-5 | 15 | 75 |", "claude-opus-5: 15.00 / 75.00",
    '"claude-opus-5": {"input": 15, "output": 75},', "claude-opus-5 -> input_per_mtok: 15, out: 75"])
def test_price_rows_are_recognised(line):
    rx = models_watch._id_regex(["claude-opus-5"])
    assert models_watch.is_price_line(line, rx), line


@pytest.mark.parametrize("line", [
    'MODEL = "claude-opus-5"  # since 2025, v2', 'MODEL = "claude-opus-5"', "retries = 3, 5 and claude-opus-5",
    'pick("claude-opus-5", 3)', 'MODEL = "claude-opus-5"  # replaces 4.1 in 2026'])
def test_a_version_or_a_year_beside_an_id_is_not_a_price_row(line):
    rx = models_watch._id_regex(["claude-opus-5"])
    assert not models_watch.is_price_line(line, rx), line


@pytest.mark.parametrize("path,kind", [
    ("src/router.py", "live"), (".env.example", "live"), ("config/models.yaml", "live"), ("scripts/costume.py", "live"), ("lib/modelPricing.ts", "price"),
    ("tests/a.py", "test"), ("test/a.js", "test"), ("a_test.go", "test"), ("a.test.ts", "test"), ("a_spec.rb", "test"),
    ("src/__tests__/a.ts", "test"), ("AppTests/Router.swift", "test"),
    ("src/pricing.ts", "price"), ("data/prices.json", "price"), ("billing/cost_table.py", "price"),
    ("docs/a.txt", "doc"), ("README.md", "doc"), ("CHANGELOG", "doc"), ("db/migrations/001.sql", "migration"),
    ("tests/pricing.py", "test")])
def test_paths_are_classified(path, kind):
    assert models_watch.classify_path(path) == kind


def test_output_is_capped_at_twenty_rows(env, capsys):
    models_watch.watch()
    for i in range(25):
        git_repo(env.code, f"r{i:02d}", {"a.py": 'M = "claude-opus-5"\n'})
    env.publish(NEW_OPUS)
    code, out = run(["models", "watch"], capsys)
    assert out.count("line(s)") == models_watch.MAX_ROWS and "25 file(s)" in out


# --- the ladder edit ---------------------------------------------------------------------------

CURRENT_POLICY = POLICY_FIXTURE.replace("GPT-6 Astra", "GPT-5.6 Sol")


def test_ladder_current_and_proposed_edit(env, capsys):
    env.policy.write_text(CURRENT_POLICY)
    code, out = run(["models", "watch"], capsys)
    assert "ladder current" in out  # a rewrite that only stamps the review date is not an edit
    env.policy.write_text(CURRENT_POLICY.replace("Haiku 4.5", "Haiku 9"))
    code, out = run(["models", "watch"], capsys)
    assert "proposed ladder edit" in out and "ladder current" not in out
    assert "-| Anthropic" in out and "Claude Haiku 4.5" in out
    assert env.policy.read_text() == CURRENT_POLICY.replace("Haiku 4.5", "Haiku 9")  # a dry diff, never a write


# --- --ack -------------------------------------------------------------------------------------

def test_ack_all_marks_every_new_model_known_and_exits_zero(env, capsys):
    run(["models", "watch"], capsys)
    env.publish({**NEW_OPUS, "openai": {"gpt-7-nova": _model("gpt-nova", "2026-09-25", "GPT-7 Nova")}})
    code, out = run(["models", "watch", "--ack"], capsys)
    assert code == 0 and "acknowledged 2" in out and "new models: none" in out
    known = json.loads(env.known.read_text())["known"]
    assert "claude-opus-5-1" in known["anthropic"] and "gpt-7-nova" in known["openai"]
    assert run(["models", "watch"], capsys)[0] == 0


def test_ack_one_leaves_the_rest_and_exits_one(env, capsys):
    run(["models", "watch"], capsys)
    env.publish({**NEW_OPUS, "openai": {"gpt-7-nova": _model("gpt-nova", "2026-09-25", "GPT-7 Nova")}})
    code, out = run(["models", "watch", "--ack", "openai:gpt-7-nova"], capsys)
    assert code == 1 and "claude-opus-5-1" in out and "gpt-7-nova  " not in out.split("new models")[1]
    code, out = run(["models", "watch", "--ack", "claude-opus-5-1", "no-such-model"], capsys)
    assert code == 0 and "not in the catalogue" in out and "no-such-model" in out


def test_ack_flags_are_refused_outside_watch(env, capsys):
    assert run(["models", "--ack"], capsys)[0] == 2


# --- --seed ------------------------------------------------------------------------------------

def test_seed_with_list_and_dict_shapes(env, tmp_path, capsys):
    seed = tmp_path / "other.json"
    seed.write_text(json.dumps({"known": {
        "anthropic": ["claude-fable-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
        "openai": {"gpt-5.6-sol": {"seen": "x"}, "gpt-5.6-terra": 1, "gpt-5.6-luna": 1, "gpt-5.5": 1},
        "xai": [{"id": "grok-4.6"}]}}))
    code, out = run(["models", "watch", "--seed", str(seed)], capsys)
    assert "imported 10 known model(s)" in out and "first run" not in out
    assert [n["id"] for n in json.loads(run(["models", "watch", "--json"], capsys)[1])["new"]] == ["grok-4.5"]
    known = json.loads(env.known.read_text())["known"]
    assert known["openai"] == ["gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"]


def test_seed_errors_exit_two_and_write_nothing(env, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    assert run(["models", "watch", "--seed", str(bad)], capsys)[0] == 2
    assert run(["models", "watch", "--seed", str(tmp_path / "missing.json")], capsys)[0] == 2
    assert not env.known.exists()


# --- network -----------------------------------------------------------------------------------

def test_no_network_without_refresh_and_safe_mode_refuses_refresh(env, monkeypatch, capsys):
    import urllib.request
    def boom(*a, **k):
        raise AssertionError("network call")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert run(["models", "watch"], capsys)[0] == 0
    # stale cache + --refresh in safe mode: refused, the local copy is used
    import os, time
    old = time.time() - 30 * 86400
    os.utime(env.cache, (old, old))
    monkeypatch.setenv("TEYLA_SAFE", "1")
    code = cli.main(["models", "watch", "--refresh"])
    cap = capsys.readouterr()
    assert code == 0 and "safe mode is on" in cap.err


# --- digest ------------------------------------------------------------------------------------

def test_digest_line_only_when_unacked_new_models_exist(env, capsys):
    assert models_watch.digest_candidates() == []  # no known list yet: never seeds from the digest
    assert not env.known.exists()
    run(["models", "watch"], capsys)
    assert models_watch.digest_candidates() == []
    env.publish({**NEW_OPUS, "openai": {"gpt-7-nova": _model("gpt-nova", "2026-09-25", "GPT-7 Nova")}})
    (c,) = models_watch.digest_candidates()
    assert c["text"] == "models: 2 new (openai:gpt-7-nova, anthropic:claude-opus-5-1)" and c["step"] == "teyla models watch"
    lines, _ = digest.build([], [], [], {}, extra=[c])
    assert any("models: 2 new" in line and "`teyla models watch`" in line for line in lines)
    run(["models", "watch", "--ack"], capsys)
    assert models_watch.digest_candidates() == []


def test_digest_line_names_at_most_three(env, capsys):
    run(["models", "watch"], capsys)
    env.publish({"openai": {f"gpt-7-n{i}": _model("gpt-nova", f"2026-09-2{i}", f"N{i}") for i in range(5)}})
    (c,) = models_watch.digest_candidates()
    assert c["text"].startswith("models: 5 new (") and c["text"].endswith(", +2)")


# --- the weekly wrapper ------------------------------------------------------------------------

def _wrapper(watch_line):
    return routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=watch_line)


def test_wrapper_has_the_watch_line_and_safe_mode_drops_refresh(env, monkeypatch):
    assert routine_install._watch_line() == '"$TEYLA" models watch --refresh'
    text = _wrapper(routine_install._watch_line())
    assert '"$TEYLA" models watch --refresh > "$OUT_DIR/models-watch.md" 2>&1' in text
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert routine_install._watch_line() == '"$TEYLA" models watch'
    safe = _wrapper(routine_install._watch_line())
    assert 'models watch > "$OUT_DIR/models-watch.md"' in safe and "--refresh" not in safe


def test_old_wrapper_is_stale_until_rewritten(env, monkeypatch):
    w = env.home / ".teyla" / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(_wrapper(routine_install._watch_line()))
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(_wrapper(routine_install._watch_line()).replace('"$TEYLA" models watch --refresh > "$OUT_DIR/models-watch.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")  # written before `models watch`
    w.write_text(_wrapper(routine_install._watch_line()))
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert routine_install._wrapper_stale(w, "/x/teyla")  # safe mode on since: must lose --refresh


def test_provider_qualified_ids_count_as_the_same_model():
    from teyla import models_watch
    rx = models_watch._id_regex(["claude-sonnet-4"])
    assert rx.search('model = "anthropic/claude-sonnet-4"')
    assert not rx.search("claude-sonnet-4.5") and not rx.search("my-claude-sonnet-4")


def test_catalogue_prefers_a_fresher_fetched_copy(tmp_path, monkeypatch):
    import json, os
    from teyla import models
    cache, fallback = tmp_path / "cache.json", tmp_path / "fallback.json"
    cache.write_text(json.dumps({"old": {}}))
    fallback.write_text(json.dumps({"new": {}}))
    os.utime(cache, (1, 1))
    monkeypatch.setattr(models, "MODELS_DEV_CACHE", cache)
    monkeypatch.setattr(models, "MODELS_DEV_FALLBACK", fallback)
    assert models.load_models_dev_catalogue(refresh=False)[0] == {"new": {}}
    os.utime(fallback, (0, 0))
    assert models.load_models_dev_catalogue(refresh=False)[0] == {"old": {}}
