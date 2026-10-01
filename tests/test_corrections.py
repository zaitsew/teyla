"""The correction store (`teyla.corrections`): outside the repo, 0600, scrubbed, keyed by the
main checkout, still reading the pre-0.12 in-repo file. HOME and TEYLA_HOME point into
tmp_path for every test, so the real ~/.teyla and real repos are never touched."""
from __future__ import annotations

import json
import pathlib
import stat
import subprocess

import pytest

from teyla import config, corrections, rules


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TEYLA_HOME", raising=False)
    return home


def _git(*args):
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


def _repo(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(parents=True)
    _git("init", "-q", "-b", "main", path)
    _git("-C", path, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "init")
    return path


def _rec(text, ts="2026-09-29T10:00:00+00:00", cwd="x"):
    return {"ts": ts, "cwd": cwd, "text": text}


# --- scrub ----------------------------------------------------------------------------------

SECRETS = [
    "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "gho_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
    "sk-ant-" + "api03-AbCdEfGhIjKlMnOpQrStUv-wxyz0123",
    "sk-proj-" + "AbCdEfGhIjKlMnOpQrStUvWx0123",
    "xai-" + "AbCdEfGhIjKlMnOpQrStUvWx0123",
    "AKIA" + "IOSFODNN7EXAMPLE",
    "xoxb-" + "123456789012-abcdefABCDEF",
    "AIza" + "SyA1234567890abcdefghijklmnopqrstuv",
    "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0In0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    "0123456789abcdef0123456789abcdef01234567",              # 40 hex
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",              # AWS secret access key shape
]


@pytest.mark.parametrize("secret", SECRETS)
def test_scrub_removes_each_secret_shape(secret):
    out = corrections.scrub(f"no, use {secret} here, again")
    assert secret not in out and "[redacted]" in out
    assert out.startswith("no, use ") and out.endswith(" here, again")


def test_scrub_removes_a_pem_block_even_cut_off_by_truncation():
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    assert corrections.scrub(f"wrong key:\n{pem}\nthanks") == "wrong key:\n[redacted]\nthanks"
    assert corrections.scrub("key: -----BEGIN RSA PRIVATE KEY-----\nMIIEow") == "key: [redacted]"


@pytest.mark.parametrize("text,want", [
    ("password=hunter2 and retry", "password=[redacted] and retry"),
    ('API_KEY: "abc def" is wrong', 'API_KEY: [redacted] is wrong'),
    ("GITHUB_TOKEN=abc123", "GITHUB_TOKEN=[redacted]"),
    ("client_secret = s3cr3t;", "client_secret = [redacted];"),
    ("Authorization: Bearer abcdefghijklmnop1234", "Authorization: Bearer [redacted]"),
    ("Authorization: Basic dXNlcjpodW50ZXIy", "Authorization: Basic [redacted]"),
    ('{"password": "hunter2", "user": "me"}', '{"password": [redacted], "user": "me"}'),
    ("gh auth login --token abc123def", "gh auth login --token [redacted]"),
    ("machine api.example.com login me password hunter2", "machine api.example.com login me password [redacted]"),
    ("clone https://me:hunter2@git.example.com/x.git", "clone https://[redacted]@git.example.com/x.git"),
    ("use glpat-" + "abcdefghij0123456789", "use [redacted]"),
    # review of #63, P1: `}` inside an unquoted value is part of it; only a closing brace stays.
    ("PASSWORD=abC}123 again", "PASSWORD=[redacted] again"),
    ("password hunt}er2 again", "password [redacted] again"),
    ("{token=abc123}", "{token=[redacted]}"),
    # review of #63, P1: a quoted .netrc password, escaped quotes included.
    ('machine h login me password "hunter2"', "machine h login me password [redacted]"),
    ('machine h login me password "hun\\"ter 2" x', "machine h login me password [redacted] x"),
    ('API_KEY="ab\\"cd" again', "API_KEY=[redacted] again"),
])
def test_scrub_keeps_the_name_of_an_assignment_and_drops_the_value(text, want):
    assert corrections.scrub(text) == want


@pytest.mark.parametrize("text", [
    "no, don't rewrite the whole file, just fix the one line",
    "не так, я же говорил — сделай сам",
    "revert 9109aba, it broke the tokens: count",             # short sha; "tokens:" is not "token:"
    "/private/tmp/claude-501/-Users-ceozaitsev-repos-njord/def1dd1e-d751-4770-aeb7-77a3f1e9b6df/tasks/a257944d6c38e1807.output",
    "session 46bca301-b4cf-4e94-8a5f-57b6f50b09ab again",
    "pwd: /Users/me/repos/teyla",
    "the model is claude-opus-5-5-20260601, wrong one",
    "the token expired again, and the secret santa list is wrong",
    "reset my password then retry",
    "see https://github.com/zaitsew/teyla/pull/56 again",
])
def test_scrub_leaves_ordinary_text_alone(text):
    assert corrections.scrub(text) == text


def test_scrub_record_scrubs_before_truncating():
    """Truncating first would cut a key below its pattern's minimum and leave the prefix."""
    key = "sk-ant-" + "Zq" * 20
    rec = corrections.scrub_record(_rec("x" * 479 + " " + key))
    assert "sk-ant" not in rec["text"] and len(rec["text"]) <= corrections.MAX_TEXT


# --- where ----------------------------------------------------------------------------------

def test_a_worktree_resolves_to_its_main_checkout(tmp_path):
    main = _repo(tmp_path / "code" / "teyla")
    wt = tmp_path / "wt" / "feat"
    _git("-C", main, "worktree", "add", "-q", "-b", "feat", wt)
    (wt / "sub").mkdir()
    assert corrections.find_repo(wt / "sub")[0] == main.resolve()
    assert corrections.path_for(wt / "sub") == corrections.path_for(main)
    assert corrections.path_for(main).name.startswith("teyla-") and corrections.path_for(main).parent.name == "corrections"
    assert corrections.find_repo(tmp_path)[0] is None and corrections.path_for(tmp_path).name == "misc.jsonl"


def test_two_repos_with_the_same_name_do_not_share_a_file(tmp_path):
    a, b = _repo(tmp_path / "a" / "app"), _repo(tmp_path / "b" / "app")
    assert corrections.path_for(a) != corrections.path_for(b)


# --- write + read ---------------------------------------------------------------------------

def test_append_writes_private_scrubbed_and_outside_the_repo(tmp_path, _home):
    repo = _repo(tmp_path / "r")
    f = corrections.append(repo, _rec("no, token=abc123 is wrong"))
    assert f.parent == _home / ".teyla" / "corrections"
    assert json.loads(f.read_text())["text"] == "no, token=[redacted] is wrong"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert not (repo / ".teyla").exists()


def test_an_existing_world_readable_teyla_dir_and_file_are_tightened(tmp_path, _home):
    repo = _repo(tmp_path / "r")
    f = corrections.path_for(repo)
    f.parent.mkdir(parents=True); (_home / ".teyla").chmod(0o755); f.parent.chmod(0o755)
    f.write_text(""); f.chmod(0o644)
    corrections.append(repo, _rec("wrong"))
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE((_home / ".teyla").stat().st_mode) == 0o700


def test_records_read_the_store_and_the_legacy_file_and_exclude_it(tmp_path):
    repo = _repo(tmp_path / "r")
    (repo / ".teyla").mkdir()
    legacy = repo / ".teyla" / "corrections.jsonl"
    old = json.dumps(_rec("old one", ts="2026-09-01T00:00:00+00:00"))
    legacy.write_text(old + "\n")
    corrections.append(repo, _rec("new one"))
    corrections.append(repo, json.loads(old))            # the same record in both counts once
    assert [r["text"] for r in corrections.records(repo)] == ["old one", "new one"]
    assert legacy.read_text() == old + "\n", "never moved, never rewritten"
    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert exclude.splitlines().count(".teyla/") == 1
    corrections.records(repo)
    assert (repo / ".git" / "info" / "exclude").read_text() == exclude, "added once"


def test_a_repo_without_a_teyla_dir_is_left_alone(tmp_path):
    repo = _repo(tmp_path / "r")
    before = (repo / ".git" / "info" / "exclude").read_text() if (repo / ".git" / "info" / "exclude").exists() else None
    corrections.append(repo, _rec("wrong"))
    after = (repo / ".git" / "info" / "exclude").read_text() if (repo / ".git" / "info" / "exclude").exists() else None
    assert before == after


def test_repo_mode_keeps_the_old_place_and_still_excludes(tmp_path, _home, monkeypatch):
    repo = _repo(tmp_path / "r")
    (_home / ".teyla").mkdir()
    (_home / ".teyla" / "config.toml").write_text('[corrections]\nstore = "repo"\n')
    f = corrections.append(repo / "", _rec("wrong: password=x1"))
    assert f == repo.resolve() / ".teyla" / "corrections.jsonl"
    assert "x1" not in f.read_text() and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert ".teyla/" in (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert not (_home / ".teyla" / "corrections").exists()


def test_config_set_accepts_the_store_option(tmp_path):
    p = tmp_path / "config.toml"
    assert config.set_value("corrections.store", "repo", path=p).startswith("set corrections.store")
    assert corrections.store_mode(config.load(p)) == "repo"
    assert corrections.store_mode({"corrections": {"store": "nonsense"}}) == "home"


def test_import_lines_scrubs_and_deduplicates(tmp_path):
    repo = _repo(tmp_path / "r")
    lines = [json.dumps(_rec("use sk-ant-" + "B" * 30)).encode(), b'{"torn', b"", json.dumps(_rec("second")).encode()]
    assert corrections.import_lines(repo, lines) == 2
    assert corrections.import_lines(repo, lines) == 0
    texts = [r["text"] for r in corrections.records(repo)]
    assert texts == ["use [redacted]", "second"]


def test_misc_records_are_per_directory(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    corrections.append(a, _rec("in a", cwd=str(a.resolve())))
    corrections.append(b, _rec("in b", cwd=str(b.resolve())))
    assert [r["text"] for r in corrections.records(a)] == ["in a"]


def test_misc_records_are_found_again_when_the_path_itself_was_scrubbed(tmp_path):
    """review of #63, P2: the stored cwd is scrubbed, so lookup goes by a key of the raw one."""
    d = tmp_path / "token=abc123"; d.mkdir()
    other = tmp_path / "token=xyz789"; other.mkdir()
    assert corrections.capture({"prompt": "no, use pnpm", "cwd": str(d)}) is not None
    assert corrections.capture({"prompt": "wrong dir", "cwd": str(other)}) is not None
    recs = corrections.records(d)
    assert [r["text"] for r in recs] == ["no, use pnpm"]
    assert "abc123" not in json.dumps(recs) and "abc123" not in corrections.path_for(d).read_text()


def test_old_misc_records_without_a_key_do_not_leak_between_directories_that_scrub_alike(tmp_path):
    """review of #63, P2: a record from before `cwd_key` has only its scrubbed path, which two
    directories can share. It is not attributed to either; a plain directory still gets its own."""
    d = tmp_path / "token=abc123"; d.mkdir()
    other = tmp_path / "token=xyz789"; other.mkdir()
    plain = tmp_path / "plain"; plain.mkdir()
    scrubbed = corrections.scrub(str(d.resolve()))
    assert scrubbed == corrections.scrub(str(other.resolve())) and scrubbed != str(d.resolve())
    misc = corrections.path_for(d)
    corrections.append(plain, _rec("in plain", cwd=str(plain.resolve())))
    with misc.open("a") as f:
        f.write(json.dumps(_rec("old record", cwd=scrubbed)) + "\n")
        f.write(json.dumps(_rec("old plain", cwd=str(plain.resolve()))) + "\n")
    assert [r["text"] for r in corrections.records(d)] == []
    assert [r["text"] for r in corrections.records(other)] == []
    assert sorted(r["text"] for r in corrections.records(plain)) == ["in plain", "old plain"]


def test_append_survives_a_short_write(tmp_path, monkeypatch):
    """review of #63, P1: os.write may write fewer bytes than asked; all of them must land."""
    import os as _os
    real = _os.write
    monkeypatch.setattr(_os, "write", lambda fd, b: real(fd, bytes(b[:3])))
    f = corrections.append(tmp_path, _rec("the whole record, not three bytes of it"))
    config.write_private(tmp_path / "t" / "doctor.json", '{"ok": true}\n')
    monkeypatch.undo()
    assert json.loads(f.read_text())["text"] == "the whole record, not three bytes of it"
    assert (tmp_path / "t" / "doctor.json").read_text() == '{"ok": true}\n'


def test_capture_deduplicates_a_double_delivery(tmp_path):
    import datetime as dt
    now = dt.datetime(2026, 9, 29, 10, 0, 0, tzinfo=dt.timezone.utc)
    payload = {"prompt": "no, use pnpm here, not npm", "cwd": str(tmp_path)}
    assert corrections.capture(payload, now=now) is not None
    assert corrections.capture(payload, now=now + dt.timedelta(seconds=3)) is None
    assert corrections.capture(payload, now=now + dt.timedelta(seconds=30)) is not None


# --- the commands -----------------------------------------------------------------------------

def test_teyla_correct_says_where_and_that_it_redacted(tmp_path, _home):
    repo = _repo(tmp_path / "r")
    out = rules.record_correction(repo, "wrong key, it is ghp_" + "c" * 36)
    assert out[0].startswith("recorded in ~/.teyla/corrections/r-") and out[0].endswith("(1 so far)")
    assert any("[redacted]" in l for l in out)
    assert not (repo / ".teyla").exists()


def test_corrections_recorded_lists_the_store_and_legacy_files(tmp_path, _home, capsys, monkeypatch):
    from teyla import cli
    code = tmp_path / "code"; repo = _repo(code / "old")
    (repo / ".teyla").mkdir()
    (repo / ".teyla" / "corrections.jsonl").write_text(json.dumps(_rec("legacy text")) + "\n")
    corrections.append(_repo(code / "new"), _rec("stored text", ts="2026-09-29T11:00:00+00:00"))
    (_home / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\n')
    cli.main(["corrections", "--recorded"])
    out = capsys.readouterr().out
    assert "legacy text" in out and "stored text" in out
    assert ".teyla/" in (repo / ".git" / "info" / "exclude").read_text().splitlines()


def test_harvest_lists_the_recorded_corrections_of_the_repo(tmp_path, monkeypatch):
    from teyla import harvest
    from teyla.adapters import claude_code
    repo = _repo(tmp_path / "r")
    corrections.append(repo, _rec("the gate opens at 14:30"))
    proj = tmp_path / "projects" / "p"; proj.mkdir(parents=True)
    for i in range(2):
        (proj / f"s{i}.jsonl").write_text(json.dumps({"type": "user", "sessionId": f"s{i}", "cwd": str(repo),
                                                       "timestamp": "2026-09-29T10:00:00Z",
                                                       "message": {"role": "user", "content": f"edit {repo}"}}) + "\n")
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(tmp_path / "projects"))
    out = harvest.harvest(str(repo))
    assert "## recorded corrections for this repo" in out and "the gate opens at 14:30" in out


def test_write_private_makes_doctor_and_update_state_0600(tmp_path):
    p = tmp_path / "t" / "doctor.json"
    config.write_private(p, "{}\n")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    p.chmod(0o644)
    config.write_private(p, "{}\n")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


# --- review findings (Codex, 2026-09-29) ------------------------------------------------------

def test_legacy_records_are_scrubbed_when_read(tmp_path):
    repo = _repo(tmp_path / "r")
    (repo / ".teyla").mkdir()
    (repo / ".teyla" / "corrections.jsonl").write_text(json.dumps(_rec("old: password=hunter2")) + "\n")
    assert [r["text"] for r in corrections.records(repo)] == ["old: password=[redacted]"]


def test_repo_mode_refuses_a_symlinked_correction_file(tmp_path, _home):
    """A repo could commit `.teyla/corrections.jsonl -> ~/.ssh/authorized_keys`; in repo mode the
    write must not follow it (nor chmod the target)."""
    repo = _repo(tmp_path / "r")
    (_home / ".teyla").mkdir()
    (_home / ".teyla" / "config.toml").write_text('[corrections]\nstore = "repo"\n')
    target = tmp_path / "victim"; target.write_text("keep\n"); target.chmod(0o644)
    (repo / ".teyla").mkdir(); (repo / ".teyla" / "corrections.jsonl").symlink_to(target)
    with pytest.raises(OSError):
        corrections.append(repo, _rec("wrong"))
    assert target.read_text() == "keep\n" and stat.S_IMODE(target.stat().st_mode) == 0o644


def test_repo_mode_rescue_goes_through_the_scrubber(tmp_path, _home):
    from teyla import storage
    (_home / ".teyla").mkdir()
    (_home / ".teyla" / "config.toml").write_text('[corrections]\nstore = "repo"\n')
    wt, main = tmp_path / "wt", tmp_path / "main"
    main.mkdir(); (wt / ".teyla").mkdir(parents=True)
    (wt / ".teyla" / "corrections.jsonl").write_text(json.dumps(_rec("token=abc123")) + "\n")
    storage.rescue(str(wt), str(main))
    assert "abc123" not in (main / ".teyla" / "corrections.jsonl").read_text()


def test_a_torn_last_line_does_not_swallow_the_next_record(tmp_path):
    repo = _repo(tmp_path / "r")
    f = corrections.path_for(repo)
    f.parent.mkdir(parents=True); f.write_text('{"ts": "2026-09-01T00:00:00+00:00", "text": "to')
    corrections.append(repo, _rec("next"))
    assert [r["text"] for r in corrections.records(repo)] == ["next"]


def test_write_private_does_not_follow_a_symlink(tmp_path):
    target = tmp_path / "victim"; target.write_text("keep\n")
    (tmp_path / "t").mkdir(); (tmp_path / "t" / "doctor.json").symlink_to(target)
    with pytest.raises(OSError):
        config.write_private(tmp_path / "t" / "doctor.json", "{}\n")
    assert target.read_text() == "keep\n"


def test_a_worktree_of_a_separate_git_dir_repo_keys_to_its_main_checkout(tmp_path):
    main = tmp_path / "code" / "app"; gitdir = tmp_path / "gitdirs" / "app.git"
    main.parent.mkdir(parents=True); gitdir.parent.mkdir(parents=True)
    _git("init", "-q", "-b", "main", "--separate-git-dir", gitdir, main)
    _git("-C", main, "config", "core.worktree", main)
    _git("-C", main, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "i")
    wt = tmp_path / "wt"
    _git("-C", main, "worktree", "add", "-q", "-b", "feat", wt)
    assert corrections.path_for(wt) == corrections.path_for(main)
