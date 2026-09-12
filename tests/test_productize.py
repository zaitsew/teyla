"""teyla.productize — the [productize] block, the eight requirements, and owner steps.

Fixture repos are built under tmp_path; `code_root` is monkeypatched so discovery never
looks at the real ~/repos, and the platform half is passed in rather than probed."""
from __future__ import annotations

import json
import pathlib

import pytest

import teyla
from teyla import config, productize, scaffold

BASE = """
[product]
name = "{name}"

[productize]
users = "owner"
target = "{target}"
platforms = {platforms}
identity = "{identity}"
tenancy = "{tenancy}"
backend = "{backend}"
llm = "{llm}"
onboarding_doc = "{doc}"
secrets = {secrets}
cost_cap = "{cost_cap}"

[productize.distribution]
{distribution}
"""


def repo(tmp_path, name="thing", *, target="family", platforms='["web"]', identity="supabase-auth",
         tenancy="user_id+rls", backend="supabase:abc", llm="none", doc="docs/GETTING-STARTED.md",
         secrets="[]", cost_cap="", distribution='web = "pwa"', env_example=None, blockers="",
         make_doc=True, git=True) -> pathlib.Path:
    d = tmp_path / name
    (d / "docs").mkdir(parents=True, exist_ok=True)
    if git:
        (d / ".git").mkdir(exist_ok=True)
    if make_doc and doc:
        (d / doc).parent.mkdir(parents=True, exist_ok=True)
        (d / doc).write_text("# how to start\n")
    if env_example is not None:
        (d / ".env.example").write_text("".join(f"{n}=\n" for n in env_example))
    (d / "teyla.toml").write_text(BASE.format(
        name=name, target=target, platforms=platforms, identity=identity, tenancy=tenancy,
        backend=backend, llm=llm, doc=doc, secrets=secrets, cost_cap=cost_cap,
        distribution=distribution) + blockers)
    return d


def reqs(d: pathlib.Path, **kw) -> dict:
    report = productize.evaluate(productize.parse(d / "teyla.toml"), **kw)
    return {r["id"]: r for r in report["requirements"]}


# --- parsing ------------------------------------------------------------------------

def test_parse_reads_the_block_and_the_blockers(tmp_path):
    d = repo(tmp_path, blockers='\n[[productize.blocker]]\nwhat = "a group"\nwho = "owner"\nhow = "do it"\n')
    m = productize.parse(d / "teyla.toml")
    assert m["product"] == "thing"
    assert m["productize"]["target"] == "family"
    assert m["blockers"][0]["who"] == "owner"


def test_a_repo_without_the_block_is_reported_not_raised(tmp_path):
    d = tmp_path / "bare"
    (d / ".git").mkdir(parents=True)
    (d / "teyla.toml").write_text('[product]\nname = "bare"\n')
    r = productize.evaluate(productize.parse(d / "teyla.toml"))
    assert r["declared"] is False and r["requirements"] == []
    assert "no [productize] block" in productize.render_text([r])


def test_broken_toml_is_an_error_row(tmp_path):
    d = tmp_path / "broken"
    (d / ".git").mkdir(parents=True)
    (d / "teyla.toml").write_text("[[[ not toml")
    r = productize.evaluate(productize.parse(d / "teyla.toml"))
    assert "ERROR" in productize.render_text([r])
    assert productize.unmet(r) == []


def test_owner_target_has_nothing_to_meet(tmp_path):
    d = repo(tmp_path, target="owner")
    r = productize.evaluate(productize.parse(d / "teyla.toml"))
    assert r["requirements"] == []
    assert "nothing to meet" in productize.render_text([r])


# --- R1 identity --------------------------------------------------------------------

@pytest.mark.parametrize("identity,met", [
    ("none", False), ("shared-key", False), ("", False),
    ("invite-key", True), ("supabase-auth", True), ("icloud", True),
])
def test_r1_identity(tmp_path, identity, met):
    d = repo(tmp_path, identity=identity)
    assert reqs(d)["R1"]["met"] is met


def test_r1_accounts_hub_is_the_strongest_public_identity(tmp_path):
    """`accounts-hub` (one shared Supabase-Auth project for every product) is not a lesser
    or exotic option next to a bespoke `supabase-auth` setup — it must clear the public bar
    the same way, as R1's first-listed, equally strong choice."""
    d = repo(tmp_path, target="public", identity="accounts-hub", platforms='["ios", "android"]',
             distribution='ios = "app-store"\nandroid = "play"')
    assert reqs(d, mail_ready=True)["R1"]["met"] is True


def test_r1_exempt_for_a_per_device_app(tmp_path):
    d = repo(tmp_path, identity="none", tenancy="per-device")
    r = reqs(d)["R1"]
    assert r["met"] and "per-device" in r["detail"]


def test_r1_per_device_exemption_does_not_survive_a_public_target(tmp_path):
    d = repo(tmp_path, identity="none", tenancy="per-device", target="public",
             distribution='web = "vercel"')
    assert reqs(d)["R1"]["met"] is False


# --- R2 tenancy, R3 backend ---------------------------------------------------------

@pytest.mark.parametrize("tenancy,met", [("single", False), ("", False),
                                         ("per-device", True), ("user_id", True), ("user_id+rls", True)])
def test_r2_tenancy(tmp_path, tenancy, met):
    d = repo(tmp_path, tenancy=tenancy)
    assert reqs(d)["R2"]["met"] is met


@pytest.mark.parametrize("backend,met", [("local-mac", False), ("", False),
                                         ("none", True), ("supabase:abc", True), ("droplet:apps-1", True)])
def test_r3_backend(tmp_path, backend, met):
    d = repo(tmp_path, backend=backend)
    assert reqs(d)["R3"]["met"] is met
    if not met:
        assert reqs(d)["R3"]["detail"].startswith("backend=")


# --- R4 distribution ----------------------------------------------------------------

@pytest.mark.parametrize("value,met", [("none", False), ("xcode", False),
                                       ("testflight-internal", True), ("app-store", True)])
def test_r4_ios(tmp_path, value, met):
    d = repo(tmp_path, platforms='["ios"]', distribution=f'ios = "{value}"')
    assert reqs(d)["R4"]["met"] is met


def test_r4_android_sideload_is_not_a_path_but_a_pwa_is(tmp_path):
    assert reqs(repo(tmp_path, "a", platforms='["android"]', distribution='android = "apk-sideload"'))["R4"]["met"] is False
    assert reqs(repo(tmp_path, "b", platforms='["android"]', distribution='android = "pwa"'))["R4"]["met"] is True


def test_r4_a_platform_with_no_entry_is_unmet_and_named(tmp_path):
    d = repo(tmp_path, platforms='["ios", "web"]', distribution='web = "pwa"')
    r = reqs(d)["R4"]
    assert r["met"] is False and "ios=unset" in r["detail"]


def test_r4_extension_zip_passes_for_family_and_fails_for_public(tmp_path):
    fam = repo(tmp_path, "fam", platforms='["extension"]', distribution='extension = "unpacked-zip"')
    assert reqs(fam)["R4"]["met"] is True
    pub = repo(tmp_path, "pub", target="public", platforms='["extension"]',
               distribution='extension = "unpacked-zip"')
    assert reqs(pub, mail_ready=True)["R4"]["met"] is False
    store = repo(tmp_path, "store", target="public", platforms='["extension"]',
                 distribution='extension = "chrome-web-store"')
    assert reqs(store, mail_ready=True)["R4"]["met"] is True


# --- R5 onboarding doc --------------------------------------------------------------

def test_r5_doc_must_exist(tmp_path):
    assert reqs(repo(tmp_path, "has"))["R5"]["met"] is True
    d = repo(tmp_path, "hasnt", make_doc=False)
    r = reqs(d)["R5"]
    assert r["met"] is False and "missing" in r["detail"]


def test_r5_unset(tmp_path):
    d = repo(tmp_path, doc="", make_doc=False)
    assert reqs(d)["R5"]["detail"] == "onboarding_doc unset"


# --- R6 secrets ---------------------------------------------------------------------

def test_r6_every_secret_is_in_an_env_example(tmp_path):
    d = repo(tmp_path, secrets='["OPENAI_API_KEY"]', env_example=["OPENAI_API_KEY"])
    assert reqs(d)["R6"]["met"] is True


def test_r6_a_secret_missing_from_env_example_fails_and_is_named(tmp_path):
    d = repo(tmp_path, secrets='["OPENAI_API_KEY", "DATABASE_URL"]', env_example=["OPENAI_API_KEY"])
    r = reqs(d)["R6"]
    assert r["met"] is False and "DATABASE_URL" in r["detail"]


def test_r6_no_env_example_anywhere_is_a_warning_not_a_failure(tmp_path):
    d = repo(tmp_path, secrets='["OPENAI_API_KEY"]', env_example=None)
    r = reqs(d)["R6"]
    assert r["met"] is True and r["detail"].startswith("WARN")


def test_r6_finds_a_monorepo_env_example_under_apps(tmp_path):
    d = repo(tmp_path, secrets='["OPENAI_API_KEY"]', env_example=None)
    (d / "apps" / "api").mkdir(parents=True)
    (d / "apps" / "api" / ".env.example").write_text("# OPENAI_API_KEY=\n")
    r = reqs(d)["R6"]
    assert r["met"] is True and not r["detail"].startswith("WARN")


# --- R7 cost cap --------------------------------------------------------------------

@pytest.mark.parametrize("llm,cap,met", [
    ("app-key", "", False),
    ("proxy-metered", "", False),
    ("byo-key+proxy-metered", "", False),
    ("app-key", "$5 per user", True),
    ("byo-key", "", True),
    ("none", "", True),
])
def test_r7_cost_cap(tmp_path, llm, cap, met):
    d = repo(tmp_path, llm=llm, cost_cap=cap)
    assert reqs(d)["R7"]["met"] is met


# --- the public bar -----------------------------------------------------------------

def test_public_needs_real_accounts_and_a_store(tmp_path):
    d = repo(tmp_path, target="public", identity="invite-key", platforms='["ios", "android"]',
             distribution='ios = "testflight-internal"\nandroid = "play-internal"')
    r = reqs(d, mail_ready=True)
    assert r["R1"]["met"] is False
    assert r["R4"]["met"] is False and "ios=testflight-internal" in r["R4"]["detail"]

    ok = repo(tmp_path, "ok", target="public", identity="supabase-auth", platforms='["ios", "android"]',
              distribution='ios = "app-store"\nandroid = "play"')
    assert all(q["met"] for q in reqs(ok, mail_ready=True).values())


def test_public_requires_the_platform_mail_sender(tmp_path):
    d = repo(tmp_path, target="public", identity="supabase-auth", distribution='web = "vercel"')
    assert reqs(d, mail_ready=False)["R8"]["met"] is False
    assert reqs(d, mail_ready=True)["R8"]["met"] is True


def test_family_target_has_no_mail_requirement(tmp_path):
    d = repo(tmp_path)
    assert "R8" not in reqs(d, mail_ready=False)


# --- discovery, summary, exit code ---------------------------------------------------

def test_find_manifests_uses_code_root(tmp_path, monkeypatch):
    root = tmp_path / "code"
    root.mkdir()
    repo(root, "one")
    repo(root, "two")
    (root / "three").mkdir()          # no .git, no teyla.toml
    monkeypatch.setattr(config, "code_root", lambda cfg=None: root)
    found = productize.find_manifests()
    assert [p.parent.name for p in found] == ["one", "two"]


def test_find_manifests_accepts_paths(tmp_path):
    d = repo(tmp_path, "one", git=False)
    assert productize.find_manifests([str(d)]) == [d / "teyla.toml"]
    assert productize.find_manifests([str(d / "teyla.toml")]) == [d / "teyla.toml"]
    assert productize.find_manifests([str(tmp_path / "nope")]) == []


def test_summary_and_exit_code(tmp_path):
    good = repo(tmp_path, "good")
    bad = repo(tmp_path, "bad", identity="shared-key", tenancy="single", backend="local-mac")
    reports = productize.evaluate_all([str(good), str(bad)])
    n, m = productize.summarize(reports)
    assert n == 1 and m == 3
    assert productize.exit_code(reports) == 1
    assert productize.exit_code(productize.evaluate_all([str(good)])) == 0


def test_render_text_shows_users_arrow_target_and_the_unmet_ids(tmp_path):
    d = repo(tmp_path, "bad", identity="shared-key", backend="local-mac",
             platforms='["ios"]', distribution='ios = "none"')
    text = productize.render_text(productize.evaluate_all([str(d)]))
    assert "owner→family" in text
    assert "R1 identity=shared-key" in text
    assert "R3 backend=local-mac" in text
    assert "R4 ios=none" in text


def test_render_json_carries_both_step_lists(tmp_path):
    d = repo(tmp_path, "x", blockers=(
        '\n[[productize.blocker]]\nwhat = "a group"\nwho = "owner"\nhow = "invite two people"\n'
        '\n[[productize.blocker]]\nwhat = "per-user rows"\nwho = "agent"\nhow = "add user_id"\n'))
    data = json.loads(json.dumps(productize.render_json(productize.evaluate_all([str(d)])), default=str))
    assert data["owner_steps"] == ["a group — invite two people"]
    assert data["agent_steps"] == ["x: per-user rows — add user_id"]


# --- owner steps --------------------------------------------------------------------

def test_owner_steps_dedupe_across_products_and_put_the_platform_first(tmp_path):
    same = '\n[[productize.blocker]]\nwhat = "external TestFlight group"\nwho = "owner"\nhow = "add the two testers"\n'
    a = repo(tmp_path, "a", blockers=same)
    b = repo(tmp_path, "b", blockers=same + '\n[[productize.blocker]]\nwhat = "a domain"\nwho = "owner"\nhow = "register it"\n')
    reports = productize.evaluate_all([str(a), str(b)])
    steps = productize.owner_steps(reports, ["platform/mail: create the key"])
    assert steps[0] == "platform/mail: create the key"
    assert steps.count("external TestFlight group — add the two testers") == 1
    assert len(steps) == 3
    text = productize.render_owner_steps(reports, ["platform/mail: create the key"])
    assert text.startswith("Only you can do these.")
    assert "1. platform/mail" in text


def test_owner_steps_skip_agent_blockers(tmp_path):
    d = repo(tmp_path, "a", blockers='\n[[productize.blocker]]\nwhat = "rows"\nwho = "agent"\nhow = "add user_id"\n')
    assert productize.owner_steps(productize.evaluate_all([str(d)])) == []
    assert "Nothing is waiting on you" in productize.render_owner_steps(productize.evaluate_all([str(d)]))


# --- the command --------------------------------------------------------------------

def test_cmd_productize_exit_codes_and_flags(tmp_path, monkeypatch, capsys):
    from teyla import platform as platform_mod
    from teyla.cli import main
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(platform_mod, "PLATFORM_PATH", home / ".teyla" / "platform.toml")

    good = repo(tmp_path, "good")
    bad = repo(tmp_path, "bad", backend="local-mac")
    assert main(["productize", str(good)]) == 0
    assert "1/1" not in capsys.readouterr().out       # 7 requirements, not 1
    assert main(["productize", str(bad)]) == 1
    assert "R3 backend=local-mac" in capsys.readouterr().out
    main(["productize", str(bad), "--owner-steps"])
    assert "platform/" in capsys.readouterr().out     # the platform is unset in this tmp HOME
    main(["productize", str(good), "--json"])
    assert "unmet_requirements" in capsys.readouterr().out


# --- scaffold ------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["app", "service"])
def test_scaffold_app_writes_the_productize_files(tmp_path, kind):
    dest = tmp_path / kind
    scaffold.scaffold(str(dest), name="widget", kind=kind, license="none")
    toml = (dest / "teyla.toml").read_text()
    assert "[productize]" in toml and "[productize.distribution]" in toml
    assert "{{productize}}" not in toml
    assert (dest / "docs" / "GETTING-STARTED.md").exists()
    for f in ("docker-compose.fragment.yml", "Caddyfile.fragment", ".env.example"):
        assert (dest / "deploy" / "droplet" / f).exists(), f
    assert (dest / ".env.example").exists()
    # and it parses, with the declared onboarding doc actually present
    report = productize.evaluate(productize.parse(dest / "teyla.toml"))
    assert report["declared"] and report["target"] == "family"
    assert {q["id"] for q in report["requirements"]} == {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
    assert reqs(dest)["R5"]["met"] is True


@pytest.mark.parametrize("kind", ["cli", "ios"])
def test_scaffold_other_kinds_are_untouched(tmp_path, kind):
    dest = tmp_path / kind
    scaffold.scaffold(str(dest), name="widget", kind=kind, license="none")
    toml = (dest / "teyla.toml").read_text()
    assert "[productize]" not in toml
    assert "{{productize}}" not in toml
    assert not (dest / "deploy").exists()
    assert not (dest / "docs" / "GETTING-STARTED.md").exists()


def test_scaffolded_app_fragments_keep_the_server_placeholders(tmp_path):
    dest = tmp_path / "app"
    scaffold.scaffold(str(dest), name="widget", kind="app", license="none")
    compose = (dest / "deploy" / "droplet" / "docker-compose.fragment.yml").read_text()
    assert "{{port}}" in compose and "{{owner}}" in compose   # filled in by add-product.sh, not here
    assert "widget:" in compose                                # {{name}} is resolved at scaffold time
    caddy = (dest / "deploy" / "droplet" / "Caddyfile.fragment").read_text()
    assert "widget.{{domain}}" in caddy


def test_productize_template_block_matches_the_documented_vocabulary():
    block = scaffold.PRODUCTIZE_BLOCK
    for key in ("users", "target", "platforms", "identity", "tenancy", "backend", "llm",
                "onboarding_doc", "secrets", "cost_cap"):
        assert f"{key} =" in block
    assert "[productize.distribution]" in block


def test_docs_and_readme_mention_both_commands():
    root = pathlib.Path(teyla.__file__).resolve().parents[2]
    if not (root / "README.md").exists():
        pytest.skip("not a checkout")
    assert (root / "docs" / "PRODUCTIZE.md").exists()
    readme = (root / "README.md").read_text()
    assert "teyla platform" in readme and "teyla productize" in readme
    assert "## 6b. Productizing" in (root / "docs" / "MANUAL.md").read_text()
