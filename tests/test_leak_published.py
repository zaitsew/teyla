"""`teyla leak --published`: the audit of what is already public. A fake `gh` on PATH answers every call from
fixtures and logs its argv; no test touches the network. Every address and name here is invented, and the
fixtures that look like leaks are built at run time so this file is clean under the guard."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from teyla import cli, digest, leak, leak_published, net

AT = "@"
PERSONAL = "pat" + AT + "mailbox-fixture.invalid"
AUTHOR = "dana" + AT + "devhost-fixture.invalid"
KEY = "ghp_" + "aB3dEf9hJk" * 4

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
from urllib.parse import parse_qs, urlsplit
d = os.environ["FAKE_GH"]
argv = sys.argv[1:]
with open(d + "/calls", "a") as f:
    f.write(json.dumps(argv) + "\\n")
def say(name):
    p = os.path.join(d, name + ".json")
    if os.path.exists(p):
        sys.stdout.write(open(p).read())
        sys.exit(0)
    sys.stdout.write('{{"message": "Not Found"}}')
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
if argv[:2] == ["repo", "list"]:
    say("repo_list_" + argv[2])
if argv[0] == "api":
    u = urlsplit(argv[1])
    q = parse_qs(u.query)
    name = u.path.strip("/").replace("/", "__")
    if name.endswith("__issues"):
        name += "_" + q["state"][0] + "_" + q.get("page", ["1"])[0]
    say(name)
sys.stderr.write("fake gh: unexpected call\\n")
sys.exit(3)
"""


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def commit(sha: str, name: str, email: str, message: str = "tidy up") -> dict:
    who = {"name": name, "email": email}
    return {"sha": sha * 40, "commit": {"author": who, "committer": who, "message": message}}


class Fake:
    def __init__(self, root: Path) -> None:
        self.dir = root

    def put(self, name: str, doc) -> None:
        (self.dir / f"{name}.json").write_text(json.dumps(doc))

    def repos(self, owner: str, *rows: dict) -> None:
        self.put(f"repo_list_{owner}", list(rows))

    def bare(self, owner: str, name: str) -> None:
        """A repo with nothing in it that could be read: no README, no commits, no issues, no releases."""
        base = f"repos__{owner}__{name}"
        self.put(f"{base}__commits", [])
        self.put(f"{base}__issues_open_1", [])
        self.put(f"{base}__issues_closed_1", [])
        self.put(f"{base}__releases", [])

    def calls(self) -> list[list[str]]:
        p = self.dir / "calls"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def api(self) -> list[str]:
        return [c[1] for c in self.calls() if c[0] == "api"]


def row(owner: str, name: str, **kw) -> dict:
    return {"name": name, "nameWithOwner": f"{owner}/{name}", "description": "", "homepageUrl": "", "url": "",
            "visibility": "public", "isPrivate": False, "isFork": False, **kw}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    data = tmp_path / "ghdata"
    data.mkdir()
    monkeypatch.setenv("FAKE_GH", str(data))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / "no-terms.txt").write_text("# no terms\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(tmp_path / "no-terms.txt"))
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent")
    return Fake(data)


def audit(*extra: str) -> int:
    return cli.main(["leak", "--published", *extra])


def test_a_readme_with_an_email_is_one_masked_historical_finding(fake, capsys):
    fake.repos("acme", row("acme", "site"))
    fake.put("repos__acme__site__readme", {"encoding": "base64", "content": b64(f"# Site\nAsk {PERSONAL} for access\n")})
    fake.put("repos__acme__site__commits", [commit("a", "Dana", "dana" + AT + "users.noreply.github.com")])
    code = audit("acme")
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines()[0] == "already public: fix the source and, for a credential, rotate first"
    assert out.count("BLOCKER historical email") == 1
    assert "acme/site/README" in out and "pa…" in out
    assert PERSONAL not in out and "mailbox-fixture" not in out


def test_a_commit_author_email_is_a_finding_once_however_many_commits(fake, capsys):
    fake.repos("acme", row("acme", "tool"))
    fake.put("repos__acme__tool__commits", [commit(c, "Dana Fixture", AUTHOR) for c in "abc"])
    code = audit("acme", "--json")
    doc = json.loads(capsys.readouterr().out)
    assert code == 1 and doc["exit"] == 1
    [f] = [f for f in doc["findings"] if f["rule"] == "email"]
    assert f["class"] == "historical" and f["severity"] == "blocker" and f["path"] == "acme/tool/commits"
    assert len(f["places"]) == 3 and AUTHOR not in json.dumps(doc)


def test_a_private_term_in_a_commit_name_is_masked_as_its_index(fake, tmp_path, monkeypatch, capsys):
    terms = tmp_path / "terms.txt"
    terms.write_text("zebracorn\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))
    fake.repos("acme", row("acme", "tool", description="a zebracorn helper"))
    fake.put("repos__acme__tool__commits", [commit("a", "Zebracorn Dev", "dev" + AT + "users.noreply.github.com")])
    code = audit("acme")
    out = capsys.readouterr().out
    assert code == 1 and "term:0" in out and "ebracorn" not in out


def test_issues_pull_requests_and_releases_are_read_and_a_secret_is_a_blocker(fake, capsys):
    now = dt.datetime.now(dt.timezone.utc)
    fresh = (now - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - dt.timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.repos("acme", row("acme", "app", description="plain", homepageUrl="https://acme.example.com"))
    fake.put("repos__acme__app__issues_open_1", [{"number": 1, "title": "crash", "body": f"token {KEY}"}])
    fake.put("repos__acme__app__issues_closed_1", [
        {"number": 2, "title": "old pr", "body": "x " + PERSONAL, "pull_request": {}, "closed_at": old},
        {"number": 3, "title": "pr", "body": "mail " + AUTHOR, "pull_request": {}, "closed_at": fresh}])
    fake.put("repos__acme__app__releases", [{"tag_name": "v1", "name": "one", "body": "see " + "ops" + AT + "corp-fixture.invalid"}])
    code = audit("acme", "--json")
    doc = json.loads(capsys.readouterr().out)
    paths = {(f["rule"], f["path"]) for f in doc["findings"]}
    assert code == 1
    assert ("secret", "acme/app/issue#1") in paths
    assert ("email", "acme/app/pr#3") in paths
    assert ("email", "acme/app/release:v1") in paths
    assert not any(p.endswith("pr#2") for _, p in paths)                  # closed more than 90 days ago
    assert KEY not in json.dumps(doc) and AUTHOR not in json.dumps(doc)


def test_a_private_repo_in_the_list_is_skipped_and_never_fetched(fake, capsys):
    fake.repos("acme", row("acme", "open-one"),
               row("acme", "secret-one", visibility="private", isPrivate=True),
               row("acme", "forked-one", isFork=True))
    fake.bare("acme", "open-one")
    code = audit("acme")
    out = capsys.readouterr().out
    assert code == 0
    assert not any("secret-one" in a or "forked-one" in a for a in fake.api())
    assert any("open-one" in a for a in fake.api())
    assert "1 private repo(s) in the list were skipped" in out and "1 fork(s) skipped" in out


def test_the_request_cap_stops_the_audit_with_a_note(fake, capsys):
    fake.repos("acme", *[row("acme", f"r{i}") for i in range(5)])
    for i in range(5):
        fake.bare("acme", f"r{i}")
    code = audit("acme", "--max-requests", "9")
    out = capsys.readouterr().out
    assert len(fake.calls()) == 9
    assert code == 0 and "request cap hit (9)" in out and "1 repo(s) audited, 4 not" in out


def test_a_cap_spent_before_anything_was_scanned_is_exit_2(fake, capsys):
    fake.repos("acme", row("acme", "r"))
    code = audit("acme", "--max-requests", "1")
    out = capsys.readouterr().out
    assert code == 2 and "NOT READ published" in out and "request cap hit (1)" in out


def test_gh_missing_is_exit_2(fake, tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code = audit("acme")
    out = capsys.readouterr().out
    assert code == 2 and "NOT READ gh" in out


def test_gh_not_signed_in_is_exit_2_not_a_pass(fake, capsys):
    code = audit("nobody")                 # the fake answers "Not Found" with exit 1 for a list it has no file for
    out = capsys.readouterr().out
    assert code == 2 and "NOT READ nobody: repo list" in out


def test_a_blocker_outranks_an_unread_surface(fake, capsys):
    fake.repos("acme", row("acme", "a"))
    fake.put("repos__acme__a__readme", {"encoding": "base64", "content": b64("write " + PERSONAL)})
    code = audit("acme")                   # commits, issues, releases have no fixture: "Not Found"
    assert code == 1


def test_safe_mode_refuses_without_allow_network(fake, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    fake.repos("acme", row("acme", "a"))
    fake.bare("acme", "a")
    code = audit("acme")
    cap = capsys.readouterr()
    assert code == 2 and "safe mode is on" in cap.err and fake.calls() == []
    assert audit("acme", "--allow-network") == 0
    assert fake.calls()


def test_quiet_prints_only_the_blocker_count(fake, capsys):
    fake.repos("acme", row("acme", "a", description="mail " + PERSONAL))
    assert audit("acme", "--quiet") == 1
    assert capsys.readouterr().out.strip() == "1"


def test_a_bad_owner_name_or_another_surface_is_a_usage_error(fake, capsys):
    assert cli.main(["leak", "--published=-bad"]) == 2
    assert cli.main(["leak", "--published", "acme", "--staged"]) == 2
    assert fake.calls() == []


def test_the_default_owners_are_those_of_the_remotes_under_code_root(fake, tmp_path, monkeypatch):
    import subprocess
    root = tmp_path / "code"
    for name, url in (("a", "git@github.com:Acme/a.git"), ("b", "https://github.com/acme/b"),
                      ("c", "https://github.com/other-org/c.git"), ("d", "https://git.example.org/x/d.git")):
        r = root / name
        r.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "remote", "add", "origin", url], check=True)
    (root / "plain").mkdir()
    assert leak_published.owners_from_remotes(root) == ["Acme", "other-org"]
    monkeypatch.setattr("teyla.config.code_root", lambda cfg=None: root)
    fake.repos("Acme")
    fake.repos("other-org")
    assert audit() == 0
    assert [c[2] for c in fake.calls() if c[:2] == ["repo", "list"]] == ["Acme", "other-org"]


def test_no_owner_and_no_remote_is_a_usage_error(fake, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("teyla.config.code_root", lambda cfg=None: tmp_path / "nothing-here")
    assert audit() == 2
    assert "no owner given" in capsys.readouterr().err


def test_the_weekly_summary_feeds_one_digest_line(fake, capsys):
    fake.repos("acme", row("acme", "a", description="mail " + PERSONAL))
    audit("acme", "--quiet")
    [c] = leak_published.digest_candidates()
    assert c["text"].startswith("1 already-public finding(s)") and c["step"] == "teyla leak --published"
    leak_published.summary_path().write_text(json.dumps(
        {"at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=20)).isoformat(), "blockers": 3, "repos": 1}))
    assert leak_published.digest_candidates() == []


def test_the_text_surfaces_are_unchanged_by_the_new_flags(tmp_path, capsys):
    f = tmp_path / "body.md"
    f.write_text("hello " + PERSONAL + "\n")
    assert cli.main(["leak", "--text", str(f)]) == 1
    assert "already public" not in capsys.readouterr().out


# --- review round: dot repos, per-repo Teyla terms and .leak-allow, gitleaks ---------------------

def test_a_repo_name_may_begin_with_a_dot_but_dot_and_dotdot_are_refused(fake, capsys):
    for ok in (".github", ".dotfiles", "a.b", "_x"):
        assert leak_published._REPO.match(ok), ok
    for bad in (".", "..", "", "-x", "a/b"):
        assert not leak_published._REPO.match(bad), bad
    fake.repos("acme", row("acme", ".github", description="mail " + PERSONAL), row("acme", "..", description="x"))
    fake.bare("acme", ".github")
    code = audit("acme")
    out = capsys.readouterr().out
    assert code == 1 and "acme/.github/description" in out
    assert "a repo with an unusable name" in out
    assert not any("/../" in c or c.endswith("/..") for c in fake.api())


def _terms(tmp_path, monkeypatch) -> None:
    terms = tmp_path / "terms2.txt"
    terms.write_text("[everywhere]\nzebracorn\n[teyla]\nquokkaterm\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(terms))


def test_teyla_only_terms_apply_to_the_teyla_repo_and_to_no_other(fake, tmp_path, monkeypatch, capsys):
    _terms(tmp_path, monkeypatch)
    monkeypatch.chdir(Path(__file__).resolve().parents[1])         # the cwd IS Teyla's checkout: it must not matter
    fake.repos("acme", row("acme", "other", description="a quokkaterm helper"),
               row("acme", "svc", description="a quokkaterm helper"))
    fake.bare("acme", "other")
    fake.bare("acme", "svc")
    fake.put("repos__acme__svc__contents__pyproject.toml", {"encoding": "base64", "content": b64('[project]\nname = "teyla"\n')})
    code = audit("acme", "--json")
    doc = json.loads(capsys.readouterr().out)
    paths = {f["path"] for f in doc["findings"] if f["rule"] == "term"}
    assert code == 1 and paths == {"acme/svc/description"}          # the repo whose pyproject names it, not the other


def test_the_repo_zaitsew_teyla_gets_the_teyla_terms_and_other_cwd_does_not_change_it(fake, tmp_path, monkeypatch, capsys):
    _terms(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)                                    # not a Teyla checkout
    fake.repos("zaitsew", row("zaitsew", "teyla", description="a quokkaterm helper"),
               row("zaitsew", "teyla-notes", description="a quokkaterm helper"))
    fake.bare("zaitsew", "teyla")
    fake.bare("zaitsew", "teyla-notes")
    assert audit("zaitsew", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert {f["path"] for f in doc["findings"] if f["rule"] == "term"} == {"zaitsew/teyla/description"}
    assert not any("repos/zaitsew/teyla/contents/pyproject.toml" == c for c in fake.api())    # the name settles it: no request


def test_everywhere_terms_apply_to_every_audited_repo(fake, tmp_path, monkeypatch, capsys):
    _terms(tmp_path, monkeypatch)
    fake.repos("acme", row("acme", "other", description="a zebracorn helper"))
    fake.bare("acme", "other")
    assert audit("acme") == 1 and "term:0" in capsys.readouterr().out


def test_a_repos_own_leak_allow_applies_to_that_repo_only(fake, capsys):
    fake.repos("acme", row("acme", "a", description="mail " + PERSONAL), row("acme", "b", description="mail " + PERSONAL))
    fake.bare("acme", "a")
    fake.bare("acme", "b")
    fake.put("repos__acme__a__contents__.leak-allow", {"encoding": "base64", "content": b64(f"emails:\n{PERSONAL}\n")})
    code = audit("acme", "--json")
    doc = json.loads(capsys.readouterr().out)
    assert code == 1
    assert {f["path"] for f in doc["findings"] if f["rule"] == "email"} == {"acme/b/description"}
    assert any("acme/a: its .leak-allow was applied" in n for n in doc["coverage"]["notes"])


def test_a_malformed_leak_allow_in_a_published_repo_is_exit_2_naming_the_repo(fake, capsys):
    fake.repos("acme", row("acme", "a"))
    fake.bare("acme", "a")
    fake.put("repos__acme__a__contents__.leak-allow", {"encoding": "base64", "content": b64("[exceptions]\nemail * \n")})
    code = audit("acme", "--json")
    doc = json.loads(capsys.readouterr().out)
    assert code == 2 and doc["errors"] and doc["errors"][0].startswith("acme/a: .leak-allow")


@pytest.mark.skipif(__import__("shutil").which("gitleaks") is None, reason="gitleaks is not installed")
def test_published_text_goes_through_gitleaks_as_historical(fake, capsys):
    key = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
    fake.repos("acme", row("acme", "a"))
    fake.bare("acme", "a")
    fake.put("repos__acme__a__readme", {"encoding": "base64", "content": b64(f"# A\n\nkey = \"{key}\"\n")})
    code = audit("acme", "--json", "--require-gitleaks")
    doc = json.loads(capsys.readouterr().out)
    gl = [f for f in doc["findings"] if f["rule"].startswith("gitleaks:")]
    assert code == 1 and gl and gl[0]["class"] == "historical" and gl[0]["path"] == "acme/a/README"
    assert key not in json.dumps(doc) and "gitleaks (text)" in doc["coverage"]["read"]


def test_require_gitleaks_is_exit_2_when_gitleaks_did_not_run(fake, monkeypatch, capsys):
    bindir = Path(os.environ["PATH"].split(os.pathsep)[0])          # only the fake gh
    monkeypatch.setenv("PATH", str(bindir))
    fake.repos("acme", row("acme", "a"))
    fake.bare("acme", "a")
    assert audit("acme") == 0
    capsys.readouterr()
    assert audit("acme", "--require-gitleaks") == 2
    assert "gitleaks" in capsys.readouterr().out
    fake.repos("empty-owner")                                       # nothing scanned at all: still no pass
    assert audit("empty-owner", "--require-gitleaks") == 2
