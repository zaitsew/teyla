"""teyla reviews — a fixture ledger, fake repos under a tmp code_root (a .git/config naming an origin),
and a fake gh runner. Nothing here reads the real ledger, the real ~/.teyla or calls gh."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import cli, config, digest, reviews, routine_install

A, B, C, D, E = ("a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40)
TODAY = dt.date(2026, 10, 8)


def _line(sha, mode="branch", p1=0, p2=0, repo="app", reviewer="codex:gpt-test", when="2026-10-07T10:00:00Z"):
    return "\t".join([when, repo, sha, mode, str(p1), str(p2), reviewer])


def _skip(reason, sha="", repo="app"):
    return "\t".join(["2026-10-07T11:00:00Z", repo, sha or "-", "skip", "0", "0", reason])


def _pr(number, commits, add=40, dele=10, files=("src/x.py",), title=None, head=None, merge=None, merged="2026-10-06T12:00:00Z"):
    return {"number": number, "title": title or f"change {number}", "mergedAt": merged,
            "additions": add, "deletions": dele, "files": [{"path": f} for f in files],
            "commits": [{"oid": c} for c in commits], "url": f"https://github.com/acme/app/pull/{number}",
            "headRefOid": head or "", "mergeCommit": {"oid": merge} if merge else None}


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    code = tmp_path / "code"
    code.mkdir()
    ledger = tmp_path / "ledger.tsv"
    (home / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\n[review]\nledger = "{ledger}"\n')

    class E_:
        pass
    e = E_()
    e.home, e.code, e.ledger = home, code, ledger

    def repo(name, slug="acme/app"):
        d = code / name
        (d / ".git").mkdir(parents=True)
        (d / ".git" / "config").write_text(f'[remote "origin"]\n\turl = https://github.com/{slug}.git\n')
        return d
    e.repo = repo

    def write(*lines):
        ledger.write_text("\n".join(lines) + "\n")
    e.write = write

    def runner_for(prs_by_slug):
        calls = []

        def run(argv):
            calls.append(argv)
            slug = argv[argv.index("--repo") + 1]
            if isinstance(prs_by_slug.get(slug), tuple):
                return prs_by_slug[slug]
            return 0, json.dumps(prs_by_slug.get(slug, [])), ""
        run.calls = calls
        return run
    e.runner = runner_for
    return e


def _scan(e, prs, **kw):
    return reviews.scan(None, days=7, today=TODAY, runner=e.runner({"acme/app": prs}), **kw)


# --- the ledger -------------------------------------------------------------------------------

def test_parse_ledger_counts_malformed_lines_and_never_raises():
    text = "\n".join([
        _line(A), _line(B, mode="commit", p1=2, p2=1), _line(C, mode="diff"),
        "", "short\tline", "2026-10-07T10:00:00Z\tapp\t" + D + "\tweird\t0\t0\tx",
        "2026-10-07T10:00:00Z\tapp\t" + D + "\tbranch\tmany\t0\tx",       # non-numeric count
        "2026-10-07T10:00:00Z\tapp\tnot-a-sha\tbranch\t0\t0\tx",          # not a sha
        "2026-10-07T10:00:00Z\tapp\t" + D + "\tbranch\t0",                # too few fields
        _skip("urgent hotfix #12", sha=E),
        "\xff\x00 binary-ish \t\t\t",
    ])
    led = reviews.parse_ledger(text)
    assert [r["sha"][0] for r in led["reviews"]] == ["a", "b", "c"]
    assert led["reviews"][1]["p1"] == 2 and led["reviews"][1]["mode"] == "commit"
    assert len(led["skips"]) == 1 and led["skips"][0]["reason"] == "urgent hotfix #12" and led["skips"][0]["sha"] == E
    assert led["unparsed"] == 6


def test_parse_ledger_tolerates_a_skip_without_a_sha_and_an_empty_file():
    led = reviews.parse_ledger("2026-10-07T11:00:00Z\tapp\t\tskip\t\t\tdocs fix for PR 7\n")
    assert led["skips"] == [{"time": "2026-10-07T11:00:00Z", "repo": "app", "sha": "", "reason": "docs fix for PR 7", "seq": 0}]
    assert reviews.parse_ledger("") == {"reviews": [], "skips": [], "unparsed": 0}


# --- classification ---------------------------------------------------------------------------

def test_reviewed_open_p1_skipped_unreviewed_exempt(env):
    env.repo("app")
    env.write(_line(A), _line(B, p1=1), _skip("blocked on the reviewer, #4", sha=""), _skip("hotfix", sha=E))
    prs = [
        _pr(1, [A]),                                   # reviewed
        _pr(2, ["f" * 40, B]),                         # reviewed, newest entry has a P1
        _pr(3, ["1" * 40]),                            # unreviewed
        _pr(4, ["2" * 40]),                            # skipped by number
        _pr(5, ["3" * 40, E]),                         # skipped by sha
        _pr(6, ["4" * 40], add=3, dele=3),             # 6 lines: exempt
        _pr(7, ["5" * 40], add=90, dele=0, files=("README.md", "docs/a.txt")),   # docs only: exempt
        _pr(8, ["6" * 40], add=3, dele=4),             # 7 lines: not exempt -> unreviewed
        _pr(9, ["7" * 40], add=90, dele=0, files=("README.md", "src/a.py")),     # a code file: unreviewed
    ]
    rep = _scan(env, prs)
    (row,) = rep["repos"]
    assert {k: row[k] for k in ("merged", "reviewed", "open_p1", "skipped", "unreviewed", "exempt")} == \
        {"merged": 9, "reviewed": 1, "open_p1": 1, "skipped": 2, "unreviewed": 3, "exempt": 2}
    assert [p["number"] for p in row["prs"] if p["state"] == "open_p1"] == [2]
    assert rep["totals"]["merged"] == 9
    assert reviews.totals_line(rep) == "review debt: 3 unreviewed, 1 merged with an open P1, 2 skipped of 9 merged PRs (7d)"


def test_p1_then_a_reviewed_fix_commit_is_reviewed(env):
    env.repo("app")
    env.write(_line(A, p1=2, when="2026-10-05T10:00:00Z"), _line(B, mode="commit", p1=0, when="2026-10-06T10:00:00Z"))
    (row,) = _scan(env, [_pr(1, [A, B])])["repos"]
    assert (row["reviewed"], row["open_p1"]) == (1, 0)


def test_fix_commit_not_reviewed_leaves_the_p1_open(env):
    env.repo("app")
    env.write(_line(A, p1=1))
    (row,) = _scan(env, [_pr(1, [A, B])])["repos"]
    assert (row["reviewed"], row["open_p1"]) == (0, 1)


def test_newest_entry_is_by_commit_position_then_line_order(env):
    env.repo("app")
    # The fix commit was reviewed first and the original later: the later commit still wins.
    env.write(_line(B, p1=0), _line(A, p1=3))
    (row,) = _scan(env, [_pr(1, [A, B])])["repos"]
    assert row["open_p1"] == 0 and row["reviewed"] == 1
    # The same commit reviewed twice: the later line wins.
    env.write(_line(A, p1=1), _line(A, p1=0))
    (row,) = _scan(env, [_pr(1, [A])])["repos"]
    assert row["reviewed"] == 1


def test_short_sha_head_and_merge_commit_match_and_other_repos_do_not(env):
    env.repo("app")
    env.write(_line(A[:9]), _line(C), _line(D, repo="other-repo"))
    prs = [_pr(1, ["9" * 40], head=A),            # ledger holds a prefix of the head
           _pr(2, ["8" * 40], merge=C),           # a review of the merge commit
           _pr(3, [D])]                           # reviewed, but under another repo's name
    (row,) = _scan(env, prs)["repos"]
    assert (row["reviewed"], row["unreviewed"]) == (2, 1)


def test_repo_matches_by_directory_name_or_github_name(env):
    env.repo("checkout-dir", slug="acme/app")
    env.write(_line(A, repo="app"))
    (row,) = _scan(env, [_pr(1, [A])])["repos"]
    assert row["reviewed"] == 1
    env.write(_line(A, repo="CHECKOUT-DIR"))
    (row,) = _scan(env, [_pr(1, [A])])["repos"]
    assert row["reviewed"] == 1


def test_min_lines_comes_from_config(env):
    env.repo("app")
    env.write(_line(A))
    (env.home / ".teyla" / "config.toml").write_text(
        f'code_root = "{env.code}"\n[review]\nledger = "{env.ledger}"\nmin_lines = 100\n')
    (row,) = _scan(env, [_pr(1, ["1" * 40], add=60, dele=30)])["repos"]
    assert row["exempt"] == 1


def test_prs_merged_before_the_window_are_dropped(env):
    env.repo("app")
    env.write(_line(A))
    (row,) = _scan(env, [_pr(1, [B], merged="2026-09-20T00:00:00Z"), _pr(2, [B])])["repos"]
    assert row["merged"] == 1 and row["prs"][0]["number"] == 2


# --- gh ---------------------------------------------------------------------------------------

def test_one_gh_call_per_repo_with_the_documented_arguments(env):
    env.repo("app")
    env.repo("lib", slug="acme/lib")
    (env.code / "scratch" / ".git").mkdir(parents=True)        # no remote: no call
    env.write(_line(A))
    run = env.runner({"acme/app": [], "acme/lib": []})
    reviews.scan(None, days=7, today=TODAY, runner=run)
    assert len(run.calls) == 2
    argv = next(c for c in run.calls if "acme/app" in c)
    assert argv[:3] == ["gh", "pr", "list"] and ["--state", "merged"] == argv[argv.index("--state"):argv.index("--state") + 2]
    assert argv[argv.index("--search") + 1] == "merged:>=2026-10-01"
    assert argv[argv.index("--json") + 1] == "number,title,mergedAt,additions,deletions,files,commits,url,mergeCommit,headRefOid"
    assert argv[argv.index("--limit") + 1] == "100"


def test_gh_failure_skips_the_repo_with_a_note(env):
    env.repo("app")
    env.write(_line(A))
    rep = reviews.scan(None, days=7, today=TODAY, runner=env.runner({"acme/app": (1, "", "gh: not logged in\nrun gh auth login")}))
    assert rep["repos"] == [] and any("acme/app" in n and "not logged in" in n for n in rep["notes"])
    rep = reviews.scan(None, days=7, today=TODAY, runner=env.runner({"acme/app": (0, "not json", "")}))
    assert rep["repos"] == [] and any("not JSON" in n for n in rep["notes"])
    out = reviews.render(rep)
    assert out.startswith("review debt: 0 unreviewed") or "not checked" in out


def test_a_failed_gh_query_keeps_the_last_summary(env):
    env.repo("app")
    env.repo("lib", slug="acme/lib")
    env.write(_line(A))
    reviews.write_summary(reviews.scan(None, days=7, today=TODAY,
                                       runner=env.runner({"acme/app": [_pr(1, [B])], "acme/lib": [_pr(2, [C])]})))
    assert json.loads(reviews.summary_path().read_text())["unreviewed"] == 2
    rep = reviews.scan(None, days=7, today=TODAY,
                       runner=env.runner({"acme/app": (1, "", "gh: not logged in"), "acme/lib": []}))
    reviews.write_summary(rep)
    assert json.loads(reviews.summary_path().read_text())["unreviewed"] == 2   # not replaced by a partial 0
    rep = reviews.scan(None, days=7, today=TODAY,
                       runner=env.runner({"acme/app": (1, "", "gh: not logged in"), "acme/lib": (1, "", "gh: not logged in")}))
    assert "not checked" in reviews.render(rep)


def test_gh_missing_is_a_note_not_a_crash(env, monkeypatch):
    env.repo("app")
    env.write(_line(A))
    monkeypatch.setattr(reviews.shutil, "which", lambda name: None)
    rep = reviews.scan(None, days=7, today=TODAY)
    assert rep["repos"] == [] and not rep["gh_called"] and any("gh is not installed" in n for n in rep["notes"])
    assert "not checked" in reviews.render(rep)
    reviews.write_summary(rep)
    assert not reviews.summary_path().exists()          # nothing was asked, nothing is remembered


def test_safe_mode_makes_no_gh_call(env, monkeypatch):
    env.repo("app")
    env.write(_line(A))
    monkeypatch.setenv("TEYLA_SAFE", "1")
    run = env.runner({"acme/app": [_pr(1, [B])]})
    rep = reviews.scan(None, days=7, today=TODAY, runner=run)
    assert run.calls == [] and rep["repos"] == [] and not rep["gh_called"]
    assert any("safe mode" in n for n in rep["notes"])
    # ... unless the command line said --allow-network
    rep = reviews.scan(None, days=7, today=TODAY, runner=run, network=True)
    assert len(run.calls) == 1 and rep["totals"]["unreviewed"] == 1


def test_missing_ledger_is_one_line_and_exit_zero(env, capsys):
    env.repo("app")
    assert cli.main(["reviews"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "no ledger" in out and str(env.ledger) in out


# --- output -----------------------------------------------------------------------------------

def test_full_and_quiet_output(env):
    env.repo("app")
    env.write(_line(A), _line(B, p1=1), _skip("hotfix #4"))
    prs = [_pr(1, [A]), _pr(2, [B], title="risky"), _pr(3, [C], title="forgotten"), _pr(4, [D], title="rushed")]
    rep = _scan(env, prs)
    full = reviews.render(rep)
    assert "unreviewed" in full.splitlines()[0] and "open-P1" in full.splitlines()[0]
    assert "app #2 merged with an open P1: risky  https://github.com/acme/app/pull/2" in full
    assert "app #3 unreviewed: forgotten  https://github.com/acme/app/pull/3" in full
    assert full.splitlines()[-1] == "review debt: 1 unreviewed, 1 merged with an open P1, 1 skipped of 4 merged PRs (7d)"
    quiet = reviews.render(rep, quiet=True)
    assert "open-P1" not in quiet and "reviewed" not in quiet.split("review debt")[0].replace("unreviewed", "")
    assert "app #2 merged with an open P1" in quiet and "app #3 unreviewed" in quiet and "app #4 skipped" in quiet
    assert quiet.splitlines()[-1] == reviews.totals_line(rep)


def test_unparsed_lines_and_truncation_are_reported(env):
    env.repo("app")
    env.write(_line(A), "garbage")
    prs = [_pr(n, [f"{n:040x}"]) for n in range(1, 101)]
    rep = _scan(env, prs)
    out = reviews.render(rep)
    assert "1 ledger line(s) unparsed" in out and "only the newest 100" in out


def test_cli_json_and_repo_argument(env, monkeypatch, capsys):
    env.repo("app")
    env.repo("lib", slug="acme/lib")
    env.write(_line(A))
    run = env.runner({"acme/app": [_pr(1, [B])], "acme/lib": [_pr(2, [C])]})
    monkeypatch.setattr(reviews, "_gh_runner", run)
    monkeypatch.setattr(reviews.shutil, "which", lambda name: "/bin/gh")
    assert cli.main(["reviews", "--json", "app"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["repo"] for r in data["repos"]] == ["app"] and data["totals"]["unreviewed"] == 1
    assert len(run.calls) == 1
    assert not reviews.summary_path().exists()          # a one-repo look is not the weekly summary
    assert cli.main(["reviews", "--quiet"]) == 0
    assert "2 unreviewed" in capsys.readouterr().out
    assert json.loads(reviews.summary_path().read_text())["unreviewed"] == 2


# --- the weekly wrapper and the digest -----------------------------------------------------------

def _wrapper():
    return routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=routine_install._watch_line())


def test_wrapper_files_the_reviews_report_and_an_old_wrapper_is_stale(env, monkeypatch):
    text = _wrapper()
    assert '"$TEYLA" reviews --quiet > "$OUT_DIR/reviews.md" 2>&1' in text
    assert text.index("models watch") < text.index("reviews --quiet") < text.index("digest --write")
    w = env.home / ".teyla" / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(text)
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(text.replace('"$TEYLA" reviews --quiet > "$OUT_DIR/reviews.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")        # written before `teyla reviews`


def _summary(env, unreviewed, open_p1, when):
    rep = {"days": 7, "gh_called": True,
           "totals": {"merged": 5, "unreviewed": unreviewed, "open_p1": open_p1, "skipped": 1}}
    reviews.write_summary(rep, now=when)


def test_digest_line_only_while_there_is_debt_and_the_summary_is_fresh(env):
    now = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)
    assert reviews.digest_line(now) is None                       # no summary yet
    _summary(env, 0, 0, now)
    assert reviews.digest_line(now) is None                       # no debt
    _summary(env, 2, 1, now)
    assert reviews.digest_line(now) == "review debt: 2 unreviewed, 1 merged with an open P1, 1 skipped of 5 merged PRs (7d)"
    assert reviews.digest_line(now + dt.timedelta(days=11)) is None   # a stale summary says nothing
    reviews.summary_path().write_text("{broken")
    assert reviews.digest_line(now) is None


def test_digest_build_and_write_carry_the_line(env, monkeypatch):
    lines, _ = digest.build([], [], [], {}, TODAY, review_line="review debt: 1 unreviewed, 0 merged with an open P1, 0 skipped of 3 merged PRs (7d)")
    assert lines[-1].startswith("review debt: 1 unreviewed") and len(lines) <= 6
    lines, _ = digest.build([], [], [], {}, TODAY)
    assert not any("review debt" in x for x in lines)
    from teyla import rules_lifecycle, models_watch, routines
    monkeypatch.setattr(rules_lifecycle, "digest_candidates", lambda *a, **k: [])
    monkeypatch.setattr(models_watch, "digest_candidates", lambda *a, **k: [])
    monkeypatch.setattr(routines, "_launchctl_list", lambda: "")
    monkeypatch.setattr(routines, "_crontab_l", lambda: "")
    _summary(env, 1, 0, dt.datetime.now(dt.timezone.utc))
    out = digest.write(findings=[], doctor_checks=[], reports=[], today=TODAY, notify_now=False)
    assert any(x.startswith("review debt: 1 unreviewed") for x in out)
    assert any("review debt" in x for x in digest.digest_path().read_text().splitlines())
