"""The sweeps over every repo (`teyla products`, `teyla reviews`) run their per-repo calls concurrently, keep the
order, and bound every call with a timeout. Fake probes and a fake gh: no network, no real HOME."""
import json
import subprocess
import threading

import pytest

from teyla import cli, fanout, products, reviews


def test_pmap_keeps_the_item_order_whatever_finishes_first():
    gates = {1: threading.Event(), 2: threading.Event(), 3: threading.Event()}

    def fn(x):
        gates[x].wait(5)
        if x == 1:                      # the first item finishes last: it waits for the others
            assert gates[2].is_set() and gates[3].is_set()
        return x * 10

    def release():
        gates[3].set()
        gates[2].set()
        gates[1].set()
    timer = threading.Timer(0.2, release)
    timer.start()
    assert fanout.pmap(fn, [1, 2, 3], progress=False) == [10, 20, 30]
    timer.cancel()


def test_pmap_runs_calls_at_the_same_time():
    both = threading.Barrier(2, timeout=5)      # a sequential run would break the barrier

    def fn(x):
        both.wait()
        return x
    assert fanout.pmap(fn, ["a", "b"], workers=2, progress=False) == ["a", "b"]


def test_pmap_progress_goes_to_stderr_only_when_asked(capsys):
    fanout.pmap(lambda x: x, [1, 2, 3], label="probing", progress=True)
    cap = capsys.readouterr()
    assert "probing 3/3" in cap.err and cap.out == ""
    fanout.pmap(lambda x: x, [1, 2, 3], label="probing")          # stderr is not a terminal under pytest
    assert capsys.readouterr().err == ""


def test_pmap_of_nothing_and_of_one_item():
    assert fanout.pmap(lambda x: x, [], progress=False) == []
    assert fanout.pmap(lambda x: x + 1, [1], progress=True) == [2]


def _repos(tmp_path, *names):
    out = []
    for n in names:
        d = tmp_path / n
        d.mkdir()
        out.append(d)
    return out


def test_products_table_lists_a_timed_out_probe_and_still_prints_the_others(tmp_path, monkeypatch):
    a, b, c = _repos(tmp_path, "aaa", "bbb", "ccc")
    monkeypatch.setattr(products, "write_cache", lambda results: None)
    monkeypatch.setattr("teyla.config.safe_mode", lambda cfg=None: False)
    monkeypatch.setattr("teyla.config.products_allowlist", lambda cfg=None: set())
    seen_b = threading.Event()

    def fake_probe(repo, timeout=60, *, committed=False):
        if repo.name == "aaa":
            assert seen_b.wait(5)       # the slow repo is still running while the next one has answered
            return {"_status": "timeout"}
        if repo.name == "bbb":
            seen_b.set()
        return {"_status": "ok", "rows": "3"}
    monkeypatch.setattr(products, "probe", fake_probe)
    text = products.table([str(a), str(b), str(c)], cfg={})
    rows = [ln.split() for ln in text.splitlines()[2:5]]
    assert rows == [["aaa", "timeout", "-"], ["bbb", "ok", "rows=3"], ["ccc", "ok", "rows=3"]]


def test_products_probe_reports_a_subprocess_timeout(tmp_path, monkeypatch):
    repo = _repos(tmp_path, "slow")[0]
    (repo / "check.sh").write_text('case "$1" in usage) sleep 30;; esac\n')

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("bash", k.get("timeout", 0))
    monkeypatch.setattr(products.subprocess, "run", boom)
    assert products.probe(repo, timeout=1) == {"_status": "timeout"}


def test_products_table_survives_an_oserror_in_one_probe(tmp_path, monkeypatch):
    a, b = _repos(tmp_path, "aaa", "bbb")
    monkeypatch.setattr(products, "write_cache", lambda results: None)
    monkeypatch.setattr("teyla.config.safe_mode", lambda cfg=None: False)
    monkeypatch.setattr("teyla.config.products_allowlist", lambda cfg=None: set())

    def fake_probe(repo, timeout=60, *, committed=False):
        if repo.name == "aaa":
            raise OSError("boom")
        return {"_status": "ok", "rows": "1"}
    monkeypatch.setattr(products, "probe", fake_probe)
    text = products.table([str(a), str(b)], cfg={})
    assert "error OSError" in text and "rows=1" in text


def test_the_gh_runner_turns_a_timeout_into_a_failed_call(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("gh", k["timeout"])
    monkeypatch.setattr(reviews.subprocess, "run", boom)
    rc, out, err = reviews._gh_runner(["gh", "api"])
    assert rc != 0 and "timed out" in err
    assert reviews.GH_TIMEOUT <= 30


@pytest.fixture
def review_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    from teyla import config
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    code = tmp_path / "code"
    code.mkdir()
    ledger = tmp_path / "ledger.tsv"
    ledger.write_text("2026-10-07T10:00:00Z\tbranch\tabc1234\t0\t0\tapp\tcodex:gpt-test\n")
    (home / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\n[review]\nledger = "{ledger}"\n')
    for name in ("one", "two", "three"):
        d = code / name
        (d / ".git").mkdir(parents=True)
        (d / ".git" / "config").write_text(f'[remote "origin"]\n\turl = https://github.com/acme/{name}.git\n')
    return code


def test_reviews_scan_lists_repos_in_order_and_reports_the_one_that_timed_out(review_env):
    import datetime as dt
    gate = threading.Event()

    def run(argv):
        q = next(a for a in argv if a.startswith("q="))
        slug = q.split("repo:", 1)[1].split()[0]
        if slug == "acme/one":
            assert gate.wait(5)          # slow repo: the others have been listed by now
            return 124, "", "timed out after 30s"
        if slug == "acme/three":
            gate.set()
        return 0, json.dumps({"data": {"search": {"nodes": []}}}), ""
    rep = reviews.scan(None, days=7, today=dt.date(2026, 10, 8), runner=run)
    assert [r["repo"] for r in rep["repos"]] == ["three", "two"]          # directory order, whatever finished first
    assert rep["gh_failed"] == 1 and any("acme/one" in n and "timed out" in n for n in rep["notes"])


def test_product_show_help_documents_quick(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["product", "show", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--quick" in out and "sessions" in out


def test_product_show_says_on_stderr_that_the_session_read_takes_a_while(capsys, monkeypatch):
    from teyla import product_page
    reg = {"product": {"app": {"stage": "live"}}}
    monkeypatch.setattr(product_page, "load_rows", lambda days=30: ([], {}))
    monkeypatch.setattr(product_page, "waiting_asks", lambda *a, **k: [])
    monkeypatch.setattr(product_page, "product_notes", lambda *a, **k: [])
    product_page.snapshot("app", 0.0, reg=reg, note=True)
    cap = capsys.readouterr()
    assert "--quick" in cap.err and cap.out == ""
    product_page.snapshot("app", 0.0, reg=reg)                      # the apps' --json read stays silent
    product_page.snapshot("app", 0.0, reg=reg, quick=True, note=True)   # nothing is read with --quick
    assert capsys.readouterr().err == ""
