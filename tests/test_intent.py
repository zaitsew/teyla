"""`teyla intent`: the owner's long prompts, verbatim, per product.

Synthetic prompts only. conftest points TEYLA_HOME and every adapter root at tmp dirs, so
nothing here touches the real ~/.teyla or this Mac's transcripts."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

import pytest

from teyla import cli, config, corrections, intent

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "capture-intent.sh"
START = ROOT / "plugin" / "hooks" / "session-start.sh"
NOW = dt.datetime(2026, 10, 16, 15, 40, tzinfo=dt.timezone.utc)


def prose(n: int, tag: str = "x") -> str:
    """A prompt of exactly n characters, ordinary words, no secrets."""
    base = f"I want the {tag} screen to show the plan for the week and nothing else. "
    return (base * (n // len(base) + 1))[:n]


def repo(tmp_path, name="demo") -> pathlib.Path:
    r = tmp_path / "repos" / name
    (r / ".git").mkdir(parents=True)
    return r


def entries_of(product: str) -> list[dict]:
    return intent.entries(product)


# --- which product ------------------------------------------------------------------------

def test_product_is_the_repo_name_from_any_subdirectory(tmp_path):
    r = repo(tmp_path, "alpha")
    (r / "src" / "deep").mkdir(parents=True)
    assert intent.product_for(r) == "alpha"
    assert intent.product_for(r / "src" / "deep") == "alpha"


def test_worktree_paths_map_to_their_repo_even_when_gone(tmp_path):
    # <repo>/.claude/worktrees/<x>, and ~/.worktrees/<repo>/<branch>: neither needs to exist
    assert intent.product_for(tmp_path / "repos" / "alpha" / ".claude" / "worktrees" / "agent-1" / "src") == "alpha"
    assert intent.product_for(tmp_path / ".worktrees" / "beta" / "feat-x") == "beta"
    assert intent.product_for(tmp_path / ".worktrees" / "beta" / "feat-x" / "sub") == "beta"


def test_a_linked_worktree_elsewhere_maps_to_the_main_checkout(tmp_path):
    main = repo(tmp_path, "gamma")
    wt_git = main / ".git" / "worktrees" / "w1"
    wt_git.mkdir(parents=True)
    (wt_git / "commondir").write_text("../..\n")
    wt = tmp_path / "elsewhere" / "w1"
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {wt_git}\n")
    assert intent.product_for(wt) == "gamma"


def test_outside_a_repo_prompts_share_one_general_file(tmp_path):
    d = tmp_path / "notes folder"
    d.mkdir()
    assert intent.product_for(d) == "general"
    assert intent.product_for(tmp_path / "gone" / "x") == "general"
    assert intent.product_for("") != ""


def test_a_brief_one_session_wrote_for_another_is_not_the_owners_words():
    brief = "Background (from the session that started this one): the owner decided X. " + "y " * 300
    assert intent.automated(brief)
    assert intent.typed("<task-notification><task-id>x</task-id></task-notification>") is None
    assert intent.automated("You are reviewing a pull request diff for owner/repo. " + "z " * 300)


# --- what is kept -------------------------------------------------------------------------

def hook_payload(text: str, cwd, **extra) -> dict:
    return {"prompt": text, "cwd": str(cwd), "session_id": "1a2b3c4d-0000", "hook_event_name": "UserPromptSubmit", **extra}


def test_threshold_is_400_characters_by_default(tmp_path):
    r = repo(tmp_path)
    assert intent.capture(hook_payload(prose(399), r), now=NOW) is False
    assert intent.capture(hook_payload(prose(400), r), now=NOW) is True
    assert not (intent.intent_dir() / "demo.md").exists() or len(entries_of("demo")) == 1


def test_threshold_and_switch_come_from_config(tmp_path):
    r = repo(tmp_path)
    assert intent.capture(hook_payload(prose(120), r), now=NOW, cfg={"intent": {"min_chars": 100}}) is True
    assert intent.capture(hook_payload(prose(500, "off"), r), now=NOW, cfg={"intent": {"enabled": False}}) is False
    assert config.DEFAULTS["intent"] == {"enabled": True, "min_chars": 400}


def test_the_entry_is_the_prompt_word_for_word(tmp_path):
    r = repo(tmp_path)
    text = "Goal:\n\n  - first point, with   odd  spacing\n  - second point\n\n```\ncode  stays\n```\n" + prose(400)
    assert intent.capture(hook_payload(text, r), now=NOW, harness="claude")
    raw = (intent.intent_dir() / "demo.md").read_text()
    local = NOW.astimezone().strftime("%Y-%m-%d %H:%M")
    assert raw.startswith(f"## {local} · claude · session 1a2b3c4d\nGoal:\n\n  - first point, with   odd  spacing")
    (e,) = entries_of("demo")
    assert e["text"] == text.strip() and e["harness"] == "claude" and e["session"] == "1a2b3c4d"


def test_secrets_are_scrubbed_before_anything_is_written(tmp_path):
    r = repo(tmp_path)
    key = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2
    text = prose(300) + f"\nUse token {key} and password=hunter2 for the run.\n" + prose(100)
    assert intent.capture(hook_payload(text, r), now=NOW)
    for f in intent.intent_dir().iterdir():
        body = f.read_text()
        assert key not in body and "hunter2" not in body
    assert "[redacted]" in (intent.intent_dir() / "demo.md").read_text()


def test_the_same_text_is_kept_once_per_product(tmp_path):
    a, b = repo(tmp_path, "a"), repo(tmp_path, "b")
    t = prose(450)
    assert intent.capture(hook_payload(t, a), now=NOW) is True
    assert intent.capture(hook_payload("  " + t.replace(" ", "  ") + "\n", a), now=NOW) is False  # whitespace only
    assert intent.capture(hook_payload(t, b), now=NOW) is True
    assert len(entries_of("a")) == 1 and len(entries_of("b")) == 1
    idx = json.loads((intent.intent_dir() / ".index.json").read_text())["seen"]
    assert len(idx) == 2 and all(set(v) >= {"product", "date", "session", "chars"} for v in idx.values())


def test_prompts_that_differ_only_in_line_breaks_are_both_kept(tmp_path):
    r = repo(tmp_path)
    one = "Goals for the week:\n\n- ship the window\n- fix the sync\n\n" + prose(400)
    two = "Goals for the week: - ship the window - fix the sync " + prose(400)
    assert intent.capture(hook_payload(one, r), now=NOW) is True
    assert intent.capture(hook_payload(two, r), now=NOW) is True        # other layout: kept as typed
    assert intent.capture(hook_payload(one.replace("\n", "\r\n") + "  \n", r), now=NOW) is False  # CRLF, trailing blanks
    a, b = entries_of("demo")
    assert a["text"] == one.strip() and b["text"] == two.strip()


def test_an_index_from_the_old_key_scheme_is_rebuilt_not_trusted(tmp_path):
    r = repo(tmp_path)
    t = prose(450)
    assert intent.capture(hook_payload(t, r), now=NOW)
    path = intent.intent_dir() / ".index.json"
    old = json.loads(path.read_text())
    old["version"] = 1
    old["seen"] = {"demo:0000000000000000": next(iter(old["seen"].values()))}   # a hash the new scheme never makes
    path.write_text(json.dumps(old))
    assert intent.capture(hook_payload(t, r), now=NOW) is False
    assert json.loads(path.read_text())["version"] == intent.INDEX_VERSION
    assert len(entries_of("demo")) == 1


def test_a_lost_index_is_rebuilt_from_the_files(tmp_path):
    r = repo(tmp_path)
    t = prose(450)
    assert intent.capture(hook_payload(t, r), now=NOW)
    (intent.intent_dir() / ".index.json").write_text("{not json")
    assert intent.capture(hook_payload(t, r), now=NOW) is False
    assert len(entries_of("demo")) == 1


def test_a_line_that_looks_like_a_header_does_not_split_the_entry(tmp_path):
    r = repo(tmp_path)
    t = prose(300) + "\n## 2026-01-01 10:00 · claude · session abc\nmore\n" + prose(120)
    assert intent.capture(hook_payload(t, r), now=NOW)
    (e,) = entries_of("demo")
    assert e["text"] == t


def test_a_very_long_prompt_is_cut_and_says_so(tmp_path):
    r = repo(tmp_path)
    assert intent.capture(hook_payload(prose(intent.MAX_CHARS + 500), r), now=NOW)
    (e,) = entries_of("demo")
    assert e["text"].endswith("[500 more characters not kept]")


def test_the_size_cap_is_exact(tmp_path):
    r = repo(tmp_path)
    assert intent.MAX_CHARS == 50_000
    at_cap = prose(intent.MAX_CHARS - 1) + "x"
    assert len(at_cap) == intent.MAX_CHARS
    assert intent.capture(hook_payload(at_cap, r), now=NOW)                          # exactly at the cap: whole
    assert intent.capture(hook_payload(at_cap + "y", r), now=NOW) is False           # same kept part: the same entry
    over = prose(intent.MAX_CHARS, "z") + "y"
    assert intent.capture(hook_payload(over, r), now=NOW)                            # one over: cut, and says so
    whole, cut = entries_of("demo")
    assert whole["text"] == at_cap
    assert cut["text"] == over[:-1] + "\n[1 more characters not kept]"


def test_a_cut_prompt_is_still_deduped_after_the_index_is_lost(tmp_path):
    r = repo(tmp_path)
    t = prose(intent.MAX_CHARS + 700)
    assert intent.capture(hook_payload(t, r), now=NOW) is True
    assert intent.capture(hook_payload(t, r), now=NOW) is False
    (intent.intent_dir() / ".index.json").write_text("{broken")
    assert intent.capture(hook_payload(t, r), now=NOW) is False          # rebuilt from the cut entry
    assert len(entries_of("demo")) == 1
    seen = json.loads((intent.intent_dir() / ".index.json").read_text())["seen"]
    (row,) = seen.values()
    assert row["chars"] == len(t.strip())                                # the full length, not the kept part


@pytest.mark.parametrize("text", [
    "# AGENTS.md instructions for /x/y\n\n<INSTRUCTIONS>\n" + prose(500),
    "One-pass code review of this diff. Report P1 and P2 only. " + prose(500),
    "<task-notification><summary>done</summary>" + prose(500) + "</task-notification>",
    "<system-reminder>" + prose(500) + "</system-reminder>",
    "<command-name>/foo</command-name>" + prose(500),
    "<user_query>" + prose(500) + "</user_query>",
    "Base directory for this skill: /x\n" + prose(500),
    "<scheduled-task name=\"weekly\">" + prose(500),
])
def test_prompts_nobody_typed_are_not_kept(tmp_path, text):
    assert intent.capture(hook_payload(text, repo(tmp_path)), now=NOW) is False
    assert not intent.intent_dir().exists() or not list(intent.intent_dir().glob("*.md"))


def test_headless_runs_are_not_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert intent.capture(hook_payload(prose(500), repo(tmp_path)), now=NOW) is False


def test_other_harness_payload_shapes_are_read(tmp_path):
    r = repo(tmp_path)
    payload = {"hook_event_name": "pre_llm_call", "session_id": "hermes-1", "cwd": str(r),
               "extra": {"user_message": prose(450, "h"), "is_first_turn": True}}
    assert intent.capture(payload, now=NOW)
    assert entries_of("demo")[0]["harness"] == "hermes"


# --- the hook script ----------------------------------------------------------------------

def run_hook(tmp_path, stdin: str, *args, **env) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k not in ("TEYLA_HOME", "CLAUDE_CODE_ENTRYPOINT")}
    e.update({"HOME": str(tmp_path / "home"), "TEYLA_HOME": str(tmp_path / "th"), "TEYLA_PYTHON": sys.executable, **env})
    return subprocess.run(["sh", str(HOOK), *args], input=stdin, capture_output=True, text=True, timeout=20, env=e)


def test_the_hook_writes_silently(tmp_path):
    r = repo(tmp_path)
    proc = run_hook(tmp_path, json.dumps(hook_payload(prose(450), r)), "codex")
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    text = (tmp_path / "th" / "intent" / "demo.md").read_text()
    assert " · codex · session 1a2b3c4d" in text
    assert (tmp_path / "th" / "intent" / "demo.md").stat().st_mode & 0o077 == 0
    assert (tmp_path / "th" / "intent").stat().st_mode & 0o077 == 0


def test_the_hook_never_fails_and_never_prints(tmp_path):
    r = repo(tmp_path)
    good = json.dumps(hook_payload(prose(450), r))
    cases = [
        ("", {}),
        ("not json", {}),
        ("[]", {}),
        (json.dumps({"prompt": 5, "cwd": 7}), {}),
        (good, {"TEYLA_PYTHON": "/nonexistent/python"}),
        (good, {"TEYLA_PYTHON": "/bin/false"}),
    ]
    for stdin, env in cases:
        proc = run_hook(tmp_path, stdin, **env)
        assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == "", (stdin[:20], env)


def test_the_hook_survives_an_unwritable_store(tmp_path):
    r = repo(tmp_path)
    th = tmp_path / "th"
    th.mkdir()
    (th / "intent").write_text("a file where the directory should be")
    proc = run_hook(tmp_path, json.dumps(hook_payload(prose(450), r)))
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


def test_concurrent_hooks_lose_nothing_and_keep_the_index_whole(tmp_path):
    r = repo(tmp_path)
    e = {k: v for k, v in os.environ.items() if k not in ("TEYLA_HOME", "CLAUDE_CODE_ENTRYPOINT")}
    e.update(HOME=str(tmp_path / "home"), TEYLA_HOME=str(tmp_path / "th"), TEYLA_PYTHON=sys.executable)
    procs = []
    for i in range(10):
        p = subprocess.Popen(["sh", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=e)
        p.stdin.write(json.dumps(hook_payload(prose(450, f"t{i}"), r, session_id=f"s{i}")))
        p.stdin.close()
        procs.append(p)
    assert [p.wait(timeout=60) for p in procs] == [0] * 10
    d = tmp_path / "th" / "intent"
    es = intent.parse((d / "demo.md").read_text())
    assert len(es) == 10 and len({x["text"] for x in es}) == 10
    assert len(json.loads((d / ".index.json").read_text())["seen"]) == 10


# --- backfill -----------------------------------------------------------------------------

def jl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def claude_user(ts, cwd, content, **extra) -> dict:
    return {"type": "user", "timestamp": ts, "cwd": cwd, "message": {"role": "user", "content": content}, **extra}


def recent(minutes_ago: int = 60) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fixture_roots(tmp_path):
    a = repo(tmp_path, "alpha")
    cc = tmp_path / "cc"
    long_a = prose(2200, "alpha")  # longer than the adapters' 1500-character cut
    jl(cc / "-p-alpha" / "s1.jsonl", [
        claude_user(recent(90), str(a), long_a),
        claude_user(recent(80), str(a), prose(100, "short")),                               # too short
        claude_user(recent(70), str(a), [{"type": "tool_result", "content": prose(900, "tool")}]),
        claude_user(recent(60), str(a), prose(900, "meta"), isMeta=True),
        claude_user(recent(40), str(a), "<task-notification><summary>x</summary>" + prose(900) + "</task-notification>"),
        claude_user(recent(30), str(a), prose(900, "remind") + "<system-reminder>" + prose(900) + "</system-reminder>"),
        claude_user(recent(20), str(a / ".claude" / "worktrees" / "w9"), prose(500, "wt")),   # a worktree of alpha
        claude_user(recent(10), str(a), "<command-name>/x</command-name>" + prose(900)),
    ])
    jl(cc / "-p-alpha" / "s2.jsonl", [  # `claude -p`: a script wrote it
        {**claude_user(recent(30), str(a), prose(900, "sdk")), "entrypoint": "sdk-cli"},
    ])
    jl(cc / "-p-alpha" / "s5.jsonl", [claude_user(recent(50), str(a), prose(900, "side"), isSidechain=True)])
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    jl(cc / "-p-alpha" / "s3.jsonl", [claude_user(old, str(a), prose(900, "old"))])

    b = repo(tmp_path, "beta")
    cx = tmp_path / "cx"
    day = dt.datetime.now(dt.timezone.utc)
    rollout = cx / f"{day:%Y/%m/%d}" / "rollout-2026-10-16T10-00-00-aaaa1111.jsonl"

    def msg(ts, text, role="user"):
        return {"timestamp": ts, "type": "response_item",
                "payload": {"type": "message", "role": role,
                            "content": [{"type": "input_text", "text": text}]}}
    jl(rollout, [
        {"timestamp": recent(100), "type": "session_meta", "payload": {"session_id": "aaaa1111", "cwd": str(b), "originator": "Codex Desktop"}},
        msg(recent(99), "# AGENTS.md instructions for " + str(b) + "\n\n<INSTRUCTIONS>\n" + prose(3000) + "\n</INSTRUCTIONS>"),
        msg(recent(98), "<environment_context>\n<cwd>x</cwd>\n</environment_context>"),
        msg(recent(97), "One-pass code review of this diff. " + prose(900)),
        msg(recent(96), prose(700, "beta")),
        msg(recent(95), prose(900, "reply"), role="assistant"),
    ])
    jl(cx / f"{day:%Y/%m/%d}" / "rollout-2026-10-16T11-00-00-bbbb2222.jsonl", [
        {"timestamp": recent(50), "type": "session_meta", "payload": {"session_id": "bbbb2222", "cwd": str(b), "originator": "codex_exec", "source": "exec"}},
        msg(recent(49), prose(900, "brief")),
    ])
    roots = {"claude-code": {"root": str(cc)}, "codex": {"root": str(cx), "archive_root": "", "index_path": str(tmp_path / "none.jsonl")}}
    return roots, long_a


def test_backfill_keeps_human_prompts_in_full_and_skips_everything_automated(tmp_path):
    roots, long_a = fixture_roots(tmp_path)
    res = intent.backfill(days=30, roots=roots)
    assert res == {"alpha": {"found": 3, "new": 3}, "beta": {"found": 1, "new": 1}}
    texts = [e["text"] for e in entries_of("alpha")]
    assert long_a in texts, "the adapters cut a turn at 1500 characters; the store must not"
    assert any("wt screen" in t for t in texts), "a worktree prompt lands in its repo's file"
    assert any("remind screen" in t and "system-reminder" not in t for t in texts)
    assert not any(s in t for t in texts for s in ("tool screen", "meta screen", "side screen", "sdk screen", "old screen"))
    (b,) = entries_of("beta")
    assert "beta screen" in b["text"] and b["harness"] == "codex" and b["session"] == "aaaa1111"
    assert {e["harness"] for e in entries_of("alpha")} == {"claude"}


def test_backfill_twice_adds_nothing_and_the_hook_agrees_with_it(tmp_path):
    roots, long_a = fixture_roots(tmp_path)
    intent.backfill(days=30, roots=roots)
    again = intent.backfill(days=30, roots=roots)
    assert all(r["new"] == 0 for r in again.values()) and again["alpha"]["found"] == 3
    # the same prompt arriving live, afterwards, is the same entry
    assert intent.capture(hook_payload(long_a, tmp_path / "repos" / "alpha"), now=NOW) is False
    assert len(entries_of("alpha")) == 3


def test_backfill_dry_counts_and_writes_nothing(tmp_path):
    roots, _ = fixture_roots(tmp_path)
    res = intent.backfill(days=30, dry=True, roots=roots)
    assert res["alpha"]["new"] == 3 and res["beta"]["new"] == 1
    assert not intent.intent_dir().exists()


def test_backfill_window_and_scrub(tmp_path):
    roots, _ = fixture_roots(tmp_path)
    assert intent.backfill(days=1, dry=True, roots=roots)["alpha"]["found"] == 3
    assert intent.backfill(days=365, dry=True, roots=roots)["alpha"]["found"] == 4  # the 90-day-old prompt
    secret = "sk-" + "Zy9Xw8Vu7Ts6Rq5Po4Nm3" * 2
    a = tmp_path / "repos" / "alpha"
    jl(pathlib.Path(roots["claude-code"]["root"]) / "-p-alpha" / "s4.jsonl",
       [claude_user(recent(5), str(a), prose(450, "sec") + f" key {secret}")])
    intent.backfill(days=30, roots=roots)
    assert secret not in (intent.intent_dir() / "alpha.md").read_text()


# --- commands -----------------------------------------------------------------------------

def run_cli(capsys, *argv) -> tuple[int, str, str]:
    rc = cli.main(["intent", *argv])
    out = capsys.readouterr()
    return rc or 0, out.out, out.err


def test_list_commands(tmp_path, capsys):
    a, b = repo(tmp_path, "alpha"), repo(tmp_path, "beta")
    old = NOW - dt.timedelta(days=40)
    intent.capture(hook_payload(prose(450, "recent") + " needle", a), now=NOW, harness="claude")
    intent.capture(hook_payload(prose(500, "ancient"), a), now=old, harness="codex")
    intent.capture(hook_payload(prose(420, "other"), b), now=NOW, harness="claude")
    rc, out, _ = run_cli(capsys)
    assert rc == 0 and out.splitlines()[0].split()[:2] == ["alpha", "2"] and "beta" in out and "latest" in out
    rc, out, _ = run_cli(capsys, "alpha")
    lines = out.splitlines()
    assert len(lines) == 2 and lines[0].split()[2] == "codex" and lines[1].split()[2] == "claude"
    full = json.loads(run_cli(capsys, "alpha", "--json")[1])
    for line, e in zip(lines, full):
        first = " ".join(e["text"].split())[:100]
        assert line.endswith("  " + first) and len(first) == 100 and f"{e['chars']:6}" in line
    rc, out, _ = run_cli(capsys, "alpha", "--grep", "NEEDLE")
    assert len(out.splitlines()) == 1 and "claude" in out
    rc, out, _ = run_cli(capsys, "alpha", "--days", "7")
    assert len(out.splitlines()) == 1
    rc, out, _ = run_cli(capsys, "alpha", "--json")
    data = json.loads(out)
    assert [d["harness"] for d in data] == ["codex", "claude"] and data[1]["text"].endswith("needle")
    rc, out, _ = run_cli(capsys, "--json")
    assert {p["product"] for p in json.loads(out)} == {"alpha", "beta"}
    rc, out, err = run_cli(capsys, "nope")
    assert rc == 1 and "no intent" in err


def test_path_prints_the_file(tmp_path, capsys):
    intent.capture(hook_payload(prose(450), repo(tmp_path, "alpha")), now=NOW)
    rc, out, _ = run_cli(capsys, "path", "alpha")
    assert rc == 0 and out.strip() == str(intent.intent_dir() / "alpha.md")
    assert pathlib.Path(out.strip()).read_text().startswith("## ")
    rc, out, err = run_cli(capsys, "path", "missing")
    assert rc == 1 and out.strip().endswith("missing.md") and "no intent" in err


def test_backfill_command_reports_counts_per_product(tmp_path, capsys, monkeypatch):
    roots, _ = fixture_roots(tmp_path)
    real = intent.backfill
    monkeypatch.setattr(intent, "backfill", lambda **k: real(roots=roots, **k))
    rc, out, _ = run_cli(capsys, "backfill", "--dry")
    assert rc == 0 and "alpha" in out and "would add" in out and "total" in out
    assert not intent.intent_dir().exists()
    rc, out, _ = run_cli(capsys, "backfill", "--days", "30")
    assert "added" in out and (intent.intent_dir() / "alpha.md").exists()


def test_capture_command_reads_stdin(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_payload(prose(450), repo(tmp_path)))))
    rc, out, err = run_cli(capsys, "capture")
    assert rc == 0 and out == "" and len(entries_of("demo")) == 1


# --- session start ------------------------------------------------------------------------

def start(tmp_path, cwd, *args, payload=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["sh", str(START), *args], input=json.dumps(payload) if payload is not None else "",
                          capture_output=True, text=True, timeout=10, cwd=cwd, env=env)


def seed_intent(tmp_path, product, n=2):
    d = tmp_path / "home" / ".teyla" / "intent"
    d.mkdir(parents=True)
    body = "".join(f"## 2026-10-1{i} 09:00 · claude · session abcd1234\ntext {i}\n\n" for i in range(n))
    (d / f"{product}.md").write_text(body)
    return d / f"{product}.md"


def test_session_start_points_at_the_owners_words(tmp_path):
    r = repo(tmp_path, "alpha")
    f = seed_intent(tmp_path, "alpha", 2)
    want = (f"Owner's own words for alpha: {f} (2 entries, latest 2026-10-11). "
            "Read them before planning; quote the sentences a plan serves.\n")
    assert start(tmp_path, r).stdout == want
    sub = r / "src"
    sub.mkdir()
    assert start(tmp_path, sub).stdout == want
    wt = r / ".claude" / "worktrees" / "agent-7"
    wt.mkdir(parents=True)
    assert start(tmp_path, wt).stdout == want
    other = tmp_path / ".worktrees" / "alpha" / "feat-1"
    other.mkdir(parents=True)
    assert start(tmp_path, other).stdout == want
    assert start(tmp_path, tmp_path, "--codex", payload={"cwd": str(r)}).stdout == want
    assert start(tmp_path, repo(tmp_path, "unrelated")).stdout == ""


def test_session_start_names_the_same_product_as_python(tmp_path):
    seed_intent(tmp_path, "general", 1)
    d = tmp_path / "notes folder"
    d.mkdir()
    assert intent.product_for(d) == "general"
    assert "Owner's own words for general:" in start(tmp_path, d).stdout


# --- wiring -------------------------------------------------------------------------------

def test_the_plugin_and_every_harness_run_the_hook():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]
    cmds = [h["command"] for g in hooks["UserPromptSubmit"] for h in g["hooks"]]
    assert any("capture-intent.sh" in c for c in cmds) and any("capture-correction.sh" in c for c in cmds)
    from teyla import harness
    assert "capture-intent.sh" in harness.HOOK_SCRIPTS
    assert any("capture-intent.sh codex" in h["command"] for g in harness._codex_hooks(None)["hooks"]["UserPromptSubmit"] for h in g["hooks"])
    assert any("capture-intent.sh grok" in h["command"] for g in harness._grok_hooks()["hooks"]["UserPromptSubmit"] for h in g["hooks"])
    assert any("capture-intent.sh" in e["command"] for e in harness._cursor_hooks(None)["hooks"]["beforeSubmitPrompt"])
    assert "capture-intent.sh hermes" in harness.hermes_block()
