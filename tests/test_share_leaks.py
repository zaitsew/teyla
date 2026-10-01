"""The guarantee behind `teyla monitor --share` and `teyla feedback`: nothing that identifies the
machine or the work leaves in a shared output.

One synthetic machine — a fake HOME with a Claude Code transcript, a connector registry, a
config.toml [env] with a proxy carrying credentials and a CA bundle path, a reminder — where
every identifying string is a distinctive canary. The real CLI runs against it in a
subprocess (so every module-level `Path.home()` resolves to the fake HOME), and each shared
output is grepped for every canary. The unredacted `teyla monitor` over the same machine must
show them: that proves the canaries were reachable, so their absence from the shared outputs
is the redaction working and not the fixture failing to load.

Every canary contains "zq", a pair that appears nowhere in Teyla's own text, so the blanket
`"zq" not in output` check also catches a fragment of one (a truncated slug, an 8-char id).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

SLUG = "-Users-zqhomeuser-repos-zqprojslug"
SID = "zqsid001-aaaa-4bbb-8ccc-dddddddddddd"
SID_ROOT = "zqsid002-aaaa-4bbb-8ccc-dddddddddddd"
CWD = "/srv/zqcwdcanary/zqprojslug"
CWD_ROOT = "/srv/zqcwdcanary/repos"          # ends in /repos: advice A7
CONNECTOR_ID = "7eadbeef-1234-4abc-8def-0123456789ab"  # a claude.ai connector's uuid
CONNECTOR_NAME = "ZqConnectorName"
CONNECTOR_URL = "https://zqconnector.example/mcp"
STDIO_SERVER = "zqinternalserver"            # a non-uuid MCP server id: readable, so internal
# MCP verbs often carry the server's own name, and can carry a project's: both must go too
VERBS = ["zqverbserver_get_thing", "zqverbserver_whoami", "open_zqprojslug_board"]
SKILL = "zqsecretskill"
PROXY_USER, PROXY_PASS, PROXY_HOST = "zqproxyuser", "zqproxypass", "zqproxyhost.example"
PROXY = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:3128"
CA_BUNDLE = "/opt/zqcacerts/zqbundle.pem"
REMINDER = "renew zqreminder token"
REMINDER_HOW = "zqreminderhow rotate it"
CORRECTION = "no, that's wrong - zqcorrection use the other branch"
TITLE = "zqtitle of the session"
FIRST_PROMPT = "zqfirstprompt please build it"
CODE_ROOT = "~/zqcoderoot"
GROK_SID = "zqsid003-0000"
SID_ASK = "zqsid004-aaaa-4bbb-8ccc-dddddddddddd"
ASK = "All green. Want me to push zqaskcanary now?"   # a permission ask: advice A15 counts it
REPO = "zqrepocanary"                                  # a repo with a push-triggered workflow: A16
WORKFLOW = "zqworkflowcanary.yml"

CANARIES = [
    SLUG, "zqprojslug", SID, SID[:8], SID_ROOT, SID_ROOT[:8], CWD, CWD_ROOT, "zqcwdcanary",
    CONNECTOR_ID, CONNECTOR_ID[:8], CONNECTOR_NAME, CONNECTOR_URL, STDIO_SERVER, SKILL, "zqverbserver", *VERBS,
    PROXY, PROXY_USER, PROXY_PASS, PROXY_HOST, CA_BUNDLE, "zqcacerts", REMINDER, "zqreminder",
    REMINDER_HOW, CORRECTION, "zqcorrection", TITLE, FIRST_PROMPT, "zqhomeuser", "zqcoderoot",
    GROK_SID, GROK_SID[:8], "zqgrokproj", "zqgroktitle",
    SID_ASK, SID_ASK[:8], ASK, "zqaskcanary", REPO, WORKFLOW, "zqworkflowcanary",
]


def _ts(minutes: int) -> str:
    base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    return (base + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _assistant(minute, blocks, model="claude-sonnet-5"):
    return {"type": "assistant", "timestamp": _ts(minute), "message": {
        "role": "assistant", "model": model, "content": blocks,
        "usage": {"input_tokens": 1000, "output_tokens": 800, "cache_read_input_tokens": 5000,
                  "cache_creation_input_tokens": 100}}}


def _user(minute, content, cwd=CWD):
    return {"type": "user", "timestamp": _ts(minute), "cwd": cwd, "message": {"role": "user", "content": content}}


def _tool_use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _tool_result(tid, text="ok, 12 rows: " + "x" * 60, is_error=False):
    return {"type": "tool_result", "tool_use_id": tid, "is_error": is_error, "content": [{"type": "text", "text": text}]}


def _write_jsonl(path: pathlib.Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def build_machine(root: pathlib.Path) -> dict:
    """A fake HOME with one of everything a shared output must not carry. Returns the env."""
    home = root / "zqhomeuser"
    home.mkdir()

    # --- the main transcript: giant (13 active hours, 3 compactions), edits ~/.claude/CLAUDE.md, calls two
    # connectors, invokes a private, a Teyla and a built-in skill, has a correction.
    recs = [
        _user(0, FIRST_PROMPT),
        {"type": "custom-title", "customTitle": TITLE, "timestamp": _ts(0)},
        _assistant(1, [
            _tool_use("sk1", "Skill", {"skill": SKILL}),
            _tool_use("sk2", "Skill", {"skill": "teyla:harvest"}),
            _tool_use("sk3", "Skill", {"skill": "review"}),
            _tool_use("ed1", "Edit", {"file_path": str(home / ".claude" / "CLAUDE.md"),
                                      "old_string": "a", "new_string": "b"}),
            _tool_use("ag1", "Agent", {"subagent_type": "general-purpose", "description": "read zqagentdesc"}),
        ] + [_tool_use(f"u{i}", f"mcp__{CONNECTOR_ID}__search_issues", {"q": "zqquery"}) for i in range(3)]),
        # three failed calls to the uuid connector: advice C4 names it in its title
        _user(2, [_tool_result(f"u{i}", "boom", is_error=True) for i in range(3)]),
        _user(3, CORRECTION),
        _user(3, CORRECTION),  # said twice: advice A9 (a repeating correction) fires
        # thirty calls to the stdio server inside one human turn: advice C1 names it
        _assistant(4, [_tool_use(f"s{i}", f"mcp__{STDIO_SERVER}__{VERBS[i % 3]}", {"t": "zq"}) for i in range(30)]),
        _user(5, [_tool_result(f"s{i}") for i in range(30)]),
    ] + [{"type": "system", "subtype": "compact_boundary", "timestamp": _ts(6 + i)} for i in range(3)] + [
        _user(10, "and again, do it the other way"),
        _assistant(11, [{"type": "text", "text": "done"}]),
    ] + [_assistant(11 + 25 * k, [{"type": "text", "text": "still going"}]) for k in range(1, 32)]  # A3: >12 active h
    _write_jsonl(home / ".claude" / "projects" / SLUG / f"{SID}.jsonl", recs)

    # --- a session launched from the repos root: advice A7 quotes it
    _write_jsonl(home / ".claude" / "projects" / "-srv-zqcwdcanary-repos" / f"{SID_ROOT}.jsonl", [
        _user(20, "look around", cwd=CWD_ROOT),
        _assistant(21, [{"type": "text", "text": "ok"}]),
    ])

    # --- three turns that end by asking permission and get a bare "yes": advice A15 quotes one
    ask_recs = [_user(40, "fix the flaky test")]
    for i in range(3):
        ask_recs += [_assistant(41 + 2 * i, [{"type": "text", "text": ASK}]), _user(42 + 2 * i, "yes")]
    _write_jsonl(home / ".claude" / "projects" / SLUG / f"{SID_ASK}.jsonl", ask_recs)

    # --- the policy declares both detectors; a repo under code_root runs a workflow on push: A16
    (home / ".agents").mkdir()
    (home / ".agents" / "POLICY.md").write_text(
        "# Policy\n<!-- teyla:detect no-actions -->\n<!-- teyla:detect ask-permission -->\n")
    repo = home / "zqcoderoot" / REPO
    (repo / ".git").mkdir(parents=True)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / WORKFLOW).write_text("on: [push, workflow_dispatch]\njobs: {}\n")

    # --- one expensive Grok session: advice A13 (project share) and A14 (session cost) quote it
    import urllib.parse
    gcwd = "/srv/zqgrokproj/app"   # outside HOME: grok-cost names it by its full path
    gd = home / ".grok" / "sessions" / urllib.parse.quote(gcwd, safe="") / GROK_SID
    gd.mkdir(parents=True)
    (gd / "summary.json").write_text(json.dumps({
        "info": {"id": GROK_SID, "cwd": gcwd}, "created_at": _ts(30).replace(".000Z", ".000000Z"),
        "generated_title": "zqgroktitle", "current_model_id": "grok-4.7", "reasoning_effort": "high"}))
    (gd / "signals.json").write_text(json.dumps({"toolCallCount": 3, "contextTokensUsed": 1000}))
    usage = {"inputTokens": 1000, "outputTokens": 50, "totalTokens": 1050, "cachedReadTokens": 600,
             "modelCalls": 2, "costUsdTicks": int(12.0 * 1e10)}
    (gd / "updates.jsonl").write_text(json.dumps({"method": "_x.ai/session/update", "params": {
        "sessionId": GROK_SID, "update": {"sessionUpdate": "turn_completed", "stop_reason": "end_turn",
                                          "usage": usage}}}) + "\n")

    # --- the desktop app's connector registry: turns the uuid into a display name
    for base in (home / "Library" / "Application Support" / "Claude", home / ".config" / "Claude"):
        f = base / "local-agent-mode-sessions" / "acc" / "sess" / "local_1.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"remoteMcpServersConfig": [
            {"uuid": CONNECTOR_ID, "name": CONNECTOR_NAME, "url": CONNECTOR_URL}]}))

    # --- ~/.teyla: config with the [env] a managed laptop needs, a reminder, and a fresh
    # update-check cache so doctor answers from it instead of the network.
    teyla = home / ".teyla"
    teyla.mkdir()
    (teyla / "config.toml").write_text(
        f'code_root = "{CODE_ROOT}"\nops_root = "~/zqopsroot"\n\n[update]\nrepo = "zaitsew/teyla"\n\n'
        f'[env]\nHTTPS_PROXY = "{PROXY}"\nSSL_CERT_FILE = "{CA_BUNDLE}"\n')
    due = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    (teyla / "reminders.toml").write_text(
        f'[[reminder]]\nwhat = "{REMINDER}"\ndue = "{due}"\nhow = "{REMINDER_HOW}"\n')
    (teyla / "update-check.json").write_text(json.dumps({
        "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "repo": "zaitsew/teyla",
        "latest": "v0.0.1", "note": "releases/latest", "method": "checkout", "reachable": True}))

    # Any socket connect is refused and recorded: a shared output is built from local files only.
    guard = root / "netguard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import os, socket\n"
        "def _deny(self, *a, **k):\n"
        "    with open(os.environ['TEYLA_TEST_NETLOG'], 'a') as f: f.write(repr(a) + '\\n')\n"
        "    raise OSError('network disabled in test')\n"
        "socket.socket.connect = _deny\nsocket.socket.connect_ex = _deny\n")
    work = root / "cwd"
    work.mkdir()
    return {
        "HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": f"{guard}{os.pathsep}{SRC}", "TEYLA_TEST_NETLOG": str(root / "net.log"),
        "LANG": "C.UTF-8", "_cwd": str(work),
    }


def _teyla(env: dict, *argv) -> str:
    env = dict(env)
    cwd = env.pop("_cwd")
    r = subprocess.run([sys.executable, "-m", "teyla", *argv], env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _leaks(text: str) -> list[str]:
    low = text.lower()
    found = [c for c in CANARIES if c.lower() in low]
    if "zq" in low and not found:
        i = low.index("zq")
        found.append(f"fragment: …{text[max(0, i - 40):i + 40]}…")
    return found


@pytest.fixture(scope="module")
def machine(tmp_path_factory):
    root = tmp_path_factory.mktemp("share")
    env = build_machine(root)
    out = {
        "raw": _teyla(env, "monitor"),
        "raw_json": _teyla(env, "monitor", "--json"),
        "share": _teyla(env, "monitor", "--share"),
        "share_json": _teyla(env, "monitor", "--share", "--json"),
        "share_samples": _teyla(env, "monitor", "--share", "--samples"),
    }
    fb = root / "feedback.md"
    _teyla(env, "feedback", "--out", str(fb))
    out["feedback"] = fb.read_text()
    out["home"] = env["HOME"]
    out["netlog"] = root / "net.log"
    return out


def test_fixture_is_real_the_unredacted_report_shows_the_canaries(machine):
    raw = machine["raw"]
    for c in ("zqprojslug", SID[:8], CONNECTOR_NAME, STDIO_SERVER, SKILL):
        assert c in raw, f"fixture broken: {c!r} not even in the unredacted report"
    for c in VERBS:  # tool names are in the JSON only
        assert c in machine["raw_json"], f"fixture broken: {c!r} not even in the unredacted JSON"
    for fid in ("A3", "A7", "A9", "A10", "A13", "A14", "A15", "A16", "C1", "C4"):
        assert f"] {fid} " in raw, f"fixture does not trigger {fid}"
    assert "zqaskcanary" in raw and REPO in raw and WORKFLOW in raw
    assert "zqgrokproj" in raw


@pytest.mark.parametrize("which", ["share", "share_json", "share_samples", "feedback"])
def test_no_canary_in_shared_output(machine, which):
    text = machine[which]
    assert _leaks(text) == [], f"{which} leaks: {_leaks(text)}"
    assert machine["home"] not in text


@pytest.mark.parametrize("which", ["share", "share_json", "feedback"])
def test_shared_output_still_carries_the_findings_under_pseudonyms(machine, which):
    text = machine[which]
    # A13/A14 (the week's Grok cost) are `teyla monitor`'s, not the feedback file's;
    # A15/A16 reach both, via detect.enrich (review of #60, P2)
    for fid in ("A3", "A7", "A9", "A10", "C1", "C4", "A15", "A16") + (("A13", "A14") if which != "feedback" else ()):
        assert fid in text, f"{fid} missing from {which}: redaction must not drop the advice"
    for alias in ("p01", "c01", "c02", "s01"):
        assert alias in text, f"{alias} missing from {which}"
    # Teyla's own and built-in skill names are public vocabulary and stay readable
    assert "teyla:harvest" in text and "review" in text


def test_share_json_findings_evidence_carries_only_pseudonyms(machine):
    data = json.loads(machine["share_json"])
    assert data["metrics"]["redacted"] is True
    ev = {f["id"]: f["title"] + " " + f["evidence"] for f in data["findings"]}
    assert "p01" in ev["A3"] or "p02" in ev["A3"]
    assert "—" in ev["A7"] and "—" in ev["A10"]
    assert ev["C4"].startswith("c0") and ev["C1"].startswith("c0")
    assert data["metrics"]["connectors"]["names"] == {}
    # A15 says where (a project pseudonym and a day), never what the agent wrote; A16 names r01
    assert "Want me to" not in ev["A15"] and '"' not in ev["A15"] and "e.g. p0" in ev["A15"]
    assert "e.g. r01 on: push" in ev["A16"]
    assert all(e.keys() == {"project", "sid", "day"} for e in data["metrics"]["permission_asks"]["examples"])
    mcp = [k for k in data["metrics"]["tools"] if k.startswith("mcp__")]
    assert mcp and all(re.fullmatch(r"mcp__c\d\d__t\d\d", k) for k in mcp), mcp
    for c in data["metrics"]["connectors"]["connectors"].values():
        assert all(re.fullmatch(r"t\d\d", t) for t, _ in c["top_tools"] + c["rediscovery_top"])


def test_feedback_doctor_keeps_level_and_name_but_withholds_machine_detail(machine):
    fb = machine["feedback"]
    net = [l for l in fb.splitlines() if l.split()[1:2] == ["network"]]
    assert net and "(withheld)" in net[0]
    cfg = [l for l in fb.splitlines() if l.split()[1:2] == ["config"]]
    assert cfg and "(withheld)" in cfg[0]
    rem = [l for l in fb.splitlines() if l.split()[1:2] == ["remind"]]
    assert rem and rem[0].startswith("WARN")


def test_shared_outputs_opened_no_socket(machine):
    log = machine["netlog"]
    assert not log.exists() or log.read_text() == "", log.read_text()


# --- A17 (batch volume) must not name the project that drives it ---------------------------

A17_NOW = dt.datetime(2026, 9, 29, 18, 0, tzinfo=dt.timezone.utc)


def _batch_sessions(harness, cwd, n, days_ago):
    """`n` headless sessions of `harness` in `cwd`, `days_ago` days before A17_NOW."""
    from teyla.adapters import Session
    out = []
    for i in range(n):
        s = Session(harness=harness, project=cwd, sid=f"{harness}-{cwd}-{days_ago}-{i}", path="/x")
        s.cwd = cwd
        s.first = s.last = (A17_NOW - dt.timedelta(days=days_ago, hours=1)).isoformat()
        s.batch = True
        out.append(s)
    return out


def test_share_does_not_leak_a17_project_names_or_paths(monkeypatch, capsys):
    """`teyla monitor --share` advises from the redacted metrics: A17's title, evidence and action
    name the project driving the volume (review of #69, P1). A path outside $HOME is its own name."""
    import argparse
    from teyla import cli, policy
    from teyla.monitor import headless
    canary = "/srv/zqcwdcanary/zqprojslug"
    ss = _batch_sessions("grok", canary, 1500, 1) + _batch_sessions("grok", canary, 100, 10)
    monkeypatch.setattr(cli, "_sessions", lambda a: ss)
    monkeypatch.setattr(cli, "_extras", lambda m, s, d: m.update(headless=headless(s, d, now=A17_NOW), grok_week=None, harness_errors=[]))
    monkeypatch.setattr(cli, "_cloud_sessions", lambda days: [])  # no git walk of the real code_root, no gh
    monkeypatch.setattr(policy, "status", lambda: {})
    run = lambda **kw: (cli.cmd_monitor(argparse.Namespace(days=29, project=None, no_sidechain=True, samples=False,  # noqa: E731
                                                          out=None, **kw)), capsys.readouterr().out)[1]
    raw = run(share=False, json=True)
    assert "zqprojslug" in raw and '"A17"' in raw       # the canary is reachable without --share
    for as_json in (False, True):
        out = run(share=True, json=as_json)
        assert "zq" not in out and "h01" in out
    assert '"A17"' in run(share=True, json=True)         # the finding stays, only its names go
