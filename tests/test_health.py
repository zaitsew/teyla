"""`teyla harness verify [--live]` and doctor's health:* lines (src/teyla/health.py): can each
harness do work now. Every fixture below is a fake HOME in tmp_path shaped like the real files
read on 2026-09-29; nothing reads or writes the real ~/.codex, ~/.grok, ~/.hermes or ~/.claude."""
from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
import time
import types

import pytest

from teyla import health

NOW = dt.datetime.now(dt.timezone.utc)
SECRET = "sk-THIS-MUST-NEVER-BE-PRINTED"


def _iso(d):
    return d.isoformat().replace("+00:00", "Z")


def _jwt(exp: dt.datetime) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"exp": int(exp.timestamp()), "sub": "u"}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{body}.{SECRET}"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in (".claude/projects/-Users-me-ops", ".codex/sessions", ".grok/logs", ".hermes/logs"):
        (h / d).mkdir(parents=True)
    monkeypatch.setattr(health, "HOME", h)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("GROK_HOME", raising=False)
    monkeypatch.setattr(health, "_keychain_has", lambda service: False)
    return h


# --- classify ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text,status,kind", [
    ("API error (status 402 Payment Required): Grok Build usage balance exhausted", 402, "quota"),
    ("Grok Build usage balance exhausted", None, "quota"),
    ("You've hit your session limit · resets 3am (Europe/Madrid)", None, "quota"),
    ("xAI OAuth state is missing access_token. Re-authenticate with `hermes model`.", None, "auth"),
    ('xAI token refresh failed. Response: {"error":"invalid_grant"}', None, "auth"),
    ("unexpected status 401 Unauthorized: Missing bearer", None, "auth"),
    ("Failed to authenticate: OAuth session expired and could not be refreshed", None, "auth"),
    ("API Error: 529 Overloaded.", None, "rate"),
    ("Too Many Requests", 429, "rate"),
    ("API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)", None, "network"),
    ("something odd", None, "other"),
])
def test_classify(text, status, kind):
    assert health.classify(text, status) == kind


# --- auth: shape and dates, never the secret ----------------------------------------------------

def test_codex_auth_reads_jwt_expiry_and_never_the_token(home):
    p = home / ".codex" / "auth.json"
    p.write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "last_refresh": _iso(NOW),
                             "tokens": {"id_token": SECRET, "access_token": _jwt(NOW + dt.timedelta(days=7)),
                                        "refresh_token": SECRET, "account_id": "a"}}))
    a = health.auth_codex(home / ".codex", env={})
    assert a["ok"] and a["detail"].startswith("chatgpt login, access token valid until ")
    p.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": _jwt(NOW - dt.timedelta(days=1)),
                                                                "refresh_token": SECRET}}))
    assert "Codex refreshes it" in health.auth_codex(home / ".codex", env={})["detail"]
    p.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": _jwt(NOW - dt.timedelta(days=1))}}))
    a = health.auth_codex(home / ".codex", env={})
    assert not a["ok"] and a["fix"] == "codex login"
    p.unlink()
    assert health.auth_codex(home / ".codex", env={})["fix"] == "codex login"
    assert health.auth_codex(home / ".codex", env={"OPENAI_API_KEY": SECRET})["ok"]
    assert all(SECRET not in str(v) for v in a.values())


def test_grok_auth(home):
    p = home / ".grok" / "auth.json"
    p.write_text(json.dumps({"https://auth.x.ai::b1a0": {"key": SECRET, "auth_mode": "oidc", "refresh_token": SECRET,
                                                        "expires_at": _iso(NOW - dt.timedelta(hours=1))}}))
    a = health.auth_grok(home / ".grok", env={})
    assert a["ok"] and a["detail"] == "oidc login, refreshed automatically" and SECRET not in str(a)
    p.write_text(json.dumps({"https://auth.x.ai::b1a0": {"key": SECRET, "auth_mode": "oidc",
                                                        "expires_at": _iso(NOW - dt.timedelta(hours=1))}}))
    assert health.auth_grok(home / ".grok", env={})["fix"] == "grok login"


def test_hermes_auth_names_the_missing_access_token(home):
    # The real state on 2026-09-29: a failed refresh left only an id_token.
    (home / ".hermes" / "auth.json").write_text(json.dumps({
        "version": 1, "active_provider": "xai-oauth",
        "providers": {"xai-oauth": {"tokens": {"id_token": SECRET, "expires_in": 3600, "token_type": "Bearer"},
                                    "auth_mode": "oauth_device_code", "last_refresh": "2026-09-06T17:37:08Z",
                                    "last_auth_error": {"provider": "xai-oauth", "code": "xai_refresh_failed",
                                                        "message": "xAI token refresh failed. Response: {\"error\":\"invalid_grant\"}",
                                                        "reason": "credential_pool_refresh_failure", "relogin_required": True,
                                                        "at": _iso(NOW - dt.timedelta(hours=1))}}},
        "credential_pool": {"xai-oauth": []}}))
    a = health.auth_hermes(home / ".hermes")
    assert not a["ok"] and "missing access_token" in a["detail"] and "invalid_grant" in a["detail"]
    assert a["fix"] == "hermes model   (re-authenticate xAI)" and SECRET not in str(a)


def test_claude_auth_is_presence_only(home, monkeypatch):
    assert not health.auth_claude(home / ".claude", env={})["ok"]
    assert health.auth_claude(home / ".claude", env={"CLAUDE_CODE_OAUTH_TOKEN": SECRET})["detail"] == \
        "CLAUDE_CODE_OAUTH_TOKEN set in the environment"
    monkeypatch.setattr(health, "_keychain_has", lambda service: service == "Claude Code-credentials")
    assert "keychain" in health.auth_claude(home / ".claude", env={})["detail"]
    # `claude auth status` is the truth when it runs: on 2026-09-29 the keychain item existed and
    # `claude -p` failed "OAuth session expired and could not be refreshed".
    a = health.auth_claude(home / ".claude", env={}, status={"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"})
    assert not a["ok"] and a["fix"] == "claude auth login" and "OAuth session expired" in a["detail"]
    assert health.auth_claude(home / ".claude", env={}, status={"loggedIn": True, "authMethod": "claude.ai",
                                                                "apiProvider": "firstParty"})["ok"]


def test_child_env_drops_the_host_claude_session():
    env = {"PATH": "/bin", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "CLAUDE_CODE_SESSION_ID": "x",
           "CLAUDE_CODE_DESKTOP_APP_VERSION": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:1", "CLAUDE_CODE_OAUTH_TOKEN": "t",
           "HOME": "/h"}
    assert health.child_env(env) == {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "t", "HOME": "/h"}
    plain = {"PATH": "/bin", "ANTHROPIC_BASE_URL": "https://proxy.corp"}
    assert health.child_env(plain) == plain


# --- errors vs the last success ------------------------------------------------------------------

def _grok_log(home, events):
    with open(home / ".grok" / "logs" / "unified.jsonl", "w") as fh:
        for ts, msg, ctx in events:
            fh.write(json.dumps({"ts": _iso(ts), "src": "shell", "lvl": "error" if "failed" in msg else "info",
                                 "msg": msg, "ctx": ctx}) + "\n")


def _fake_sessions(n_batch, project="/private/tmp/frank-grok-empty"):  # Frank starts its grok children here
    last = NOW.isoformat()
    return [types.SimpleNamespace(batch=True, cwd=project, project=project, last=last, first=last) for _ in range(n_batch)] + \
        [types.SimpleNamespace(batch=False, cwd="/Users/me/ops", project="/Users/me/ops", last=last, first=last)]


def test_grok_402_after_the_last_success_is_a_fix_naming_the_batch_project(home, monkeypatch):
    monkeypatch.setattr(health, "find_binary", lambda n: None)
    fail = {"kind": "api", "status_code": 402, "message": "API error (status 402 Payment Required): Grok Build usage balance exhausted"}
    _grok_log(home, [(NOW - dt.timedelta(hours=5), "shell.turn.inference_done", {}),
                     (NOW - dt.timedelta(hours=2), "shell.turn.inference_failed", fail),
                     (NOW - dt.timedelta(hours=1), "shell.turn.inference_failed", fail)])
    (home / ".grok" / "auth.json").write_text(json.dumps({"x::1": {"key": SECRET, "refresh_token": SECRET, "auth_mode": "oidc"}}))
    row = health.offline("grok", sessions=_fake_sessions(250))
    assert row["level"] == "FIX" and "quota ×2" in row["detail"] and "7d: 1 interactive, 250 batch" in row["detail"]
    assert row["fix"].startswith("Grok Build balance exhausted") and "`frank` (250 `grok -p` calls in 7 days)" in row["fix"]
    # a success after the error: history, not a fix
    _grok_log(home, [(NOW - dt.timedelta(hours=2), "shell.turn.inference_failed", fail),
                     (NOW - dt.timedelta(hours=1), "shell.turn.inference_done", {})])
    row = health.offline("grok", sessions=[])
    assert row["level"] == "OK" and "later calls succeeded" in row["detail"]
    # …but not a parallel call that finished a minute after the first 402
    _grok_log(home, [(NOW - dt.timedelta(minutes=10), "shell.turn.inference_failed", fail),
                     (NOW - dt.timedelta(minutes=9), "shell.turn.inference_done", {})])
    assert health.offline("grok", sessions=[])["level"] == "FIX"


def test_codex_limits_and_errors(home, monkeypatch):
    monkeypatch.setattr(health, "find_binary", lambda n: None)
    day = home / ".codex" / "sessions" / f"{NOW:%Y}" / f"{NOW:%m}" / f"{NOW:%d}"
    day.mkdir(parents=True)
    limits = {"limit_id": "codex", "primary": {"used_percent": 32.0, "window_minutes": 300, "resets_at": int(time.time()) + 3600},
              "secondary": {"used_percent": 93.0, "window_minutes": 10080, "resets_at": int(time.time()) + 86400},
              "plan_type": "plus", "rate_limit_reached_type": None}
    (day / "rollout-a.jsonl").write_text(json.dumps({"timestamp": _iso(NOW), "type": "event_msg",
                                                     "payload": {"type": "token_count", "info": None, "rate_limits": limits}}) + "\n")
    (home / ".codex" / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": _jwt(NOW + dt.timedelta(days=3)), "refresh_token": SECRET}}))
    # a newer "premium" record without windows does not hide the "codex" one
    with open(day / "rollout-a.jsonl", "a") as fh:
        fh.write(json.dumps({"timestamp": _iso(NOW + dt.timedelta(seconds=1)), "type": "event_msg", "payload": {
            "type": "token_count", "rate_limits": {"limit_id": "premium", "primary": None, "secondary": None,
                                                   "plan_type": None, "rate_limit_reached_type": None}}}) + "\n")
    row = health.offline("codex")
    assert row["level"] == "WARN" and "plus: 5h 32%, week 93%" in row["detail"]
    limits["rate_limit_reached_type"] = "secondary"
    (day / "rollout-a.jsonl").write_text(json.dumps({"timestamp": _iso(NOW), "type": "event_msg",
                                                     "payload": {"type": "token_count", "rate_limits": limits}}) + "\n")
    assert health.offline("codex")["level"] == "FIX"
    # a later turn that ended on the usage limit: the error Codex writes into task_complete
    later = _iso(NOW + dt.timedelta(seconds=5))
    (day / "rollout-b.jsonl").write_text(json.dumps({"timestamp": later, "type": "event_msg", "payload": {
        "type": "task_complete", "turn_id": "t", "last_agent_message": None,
        "error": {"message": "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
                             "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 11:20 PM.",
                  "codex_error_info": "usage_limit_exceeded"}}}, separators=(",", ":")) + "\n")
    row = health.offline("codex")
    assert row["level"] == "FIX" and "quota: You've hit your usage limit" in row["detail"]
    (day / "rollout-b.jsonl").unlink()
    # logs_2.sqlite ERROR rows; a model-list refresh timeout is noise
    con = sqlite3.connect(home / ".codex" / "logs_2.sqlite")
    con.execute("create table logs (id integer primary key, ts integer, ts_nanos integer, level text, target text, feedback_log_body text)")
    con.execute("insert into logs (ts, ts_nanos, level, target, feedback_log_body) values (?,0,'ERROR','m',?)",
                (int(time.time()) + 60, "list_models: failed to refresh available models: request timed out"))
    con.commit(); con.close()
    assert health.errors_codex(home / ".codex", time.time() - 86400)["error"] is None


def test_hermes_errors_skip_the_auxiliary_lane_and_read_the_last_assistant_row(home):
    stamp = (NOW - dt.timedelta(minutes=5)).astimezone().strftime("%Y-%m-%d %H:%M:%S,000")
    (home / ".hermes" / "logs" / "errors.log").write_text(
        f"{stamp} WARNING agent.auxiliary_client: Auxiliary: marking openrouter unhealthy for 60s (payment / credit error).\n"
        f"{stamp} ERROR agent.run: provider error: 429 Too Many Requests\n")
    con = sqlite3.connect(home / ".hermes" / "state.db")
    con.execute("create table messages (id integer primary key, session_id text, role text, timestamp real)")
    con.execute("insert into messages (session_id, role, timestamp) values ('s', 'assistant', ?)", (time.time() - 30 * 86400,))
    con.commit(); con.close()
    e = health.errors_hermes(home / ".hermes", time.time() - 7 * 86400)
    assert e["error"]["kind"] == "rate" and "429" in e["error"]["message"]
    assert e["last_ok"] < NOW - dt.timedelta(days=29)


def test_claude_error_is_weighed_against_its_own_entrypoint(home):
    # A `claude -p` routine (sdk-cli) failing to authenticate is not undone by the desktop app
    # working an hour later: they sign in separately.
    p = home / ".claude" / "projects" / "-Users-me-ops" / "e.jsonl"
    rows = [{"type": "assistant", "entrypoint": "sdk-cli", "timestamp": _iso(NOW - dt.timedelta(hours=2)), "isApiErrorMessage": True,
             "message": {"content": [{"type": "text", "text": "Failed to authenticate: OAuth session expired and could not be refreshed"}]}},
            {"type": "assistant", "entrypoint": "claude-desktop", "timestamp": _iso(NOW - dt.timedelta(hours=1)),
             "message": {"content": [{"type": "text", "text": "done"}]}}]
    p.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")
    e = health.errors_claude(home / ".claude", time.time() - 86400)
    assert e["error"]["kind"] == "auth" and e["last_ok"] is None


def test_claude_api_error_records(home):
    p = home / ".claude" / "projects" / "-Users-me-ops" / "s.jsonl"
    rows = [{"type": "assistant", "timestamp": _iso(NOW - dt.timedelta(hours=3)), "message": {"content": [{"type": "text", "text": "done"}]}},
            {"type": "assistant", "timestamp": _iso(NOW - dt.timedelta(hours=1)), "isApiErrorMessage": True, "error": "rate_limit",
             "message": {"content": [{"type": "text", "text": "You've hit your session limit · resets 3am (Europe/Madrid)"}]}}]
    p.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")
    e = health.errors_claude(home / ".claude", time.time() - 86400)
    assert e["error"]["kind"] == "quota" and e["last_ok"] < e["error"]["ts"]


def test_a_broken_install_is_a_fix(home, tmp_path, monkeypatch):
    fake = tmp_path / "hermes"
    fake.write_text("#!/bin/sh\necho 'hermes: no dependency environment is committed for this install; run `hermes pm repair`' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(health, "find_binary", lambda n: str(fake))
    row = health.offline("hermes")
    assert row["level"] == "FIX" and "hermes pm repair" in row["fix"]


@pytest.mark.parametrize("out,want", [
    ("codex-cli 0.153.4", "0.153.4"), ("2.1.234 (Claude Code)", "2.1.234"), ("grok 1.0.0 (3cd0d0cbcebe) [stable]", "1.0.0"),
    ("Hermes Agent v0.20.4 (2026.8.18) · upstream 1ad89ac0", "0.20.4"),
    ("Hermes Agent vgit.7368801 (2026.9.24) · upstream 73688014", "git.7368801"),
])
def test_version_parsing(tmp_path, out, want):
    fake = tmp_path / "bin"
    fake.write_text(f"#!/bin/sh\necho '{out}'\n")
    fake.chmod(0o755)
    assert health.version(str(fake)) == (want, None)


# --- live ---------------------------------------------------------------------------------------

def test_policy_marker_is_the_section_7_title(tmp_path):
    p = tmp_path / "POLICY.md"
    p.write_text("# How to run a session\n\n## 6. Deliver plug-and-play\n\nx\n\n## 7. Merging\n\ny\n")
    assert health.policy_marker(p) == "Merging"


def _fake_cli(tmp_path, name, script):
    f = tmp_path / name
    f.write_text("#!/bin/sh\n" + script)
    f.chmod(0o755)
    return str(f)


def test_live_ok_error_and_policy(tmp_path, monkeypatch):
    bins = {"claude-code": _fake_cli(tmp_path, "claude", "echo Merging\n"),
            "codex": _fake_cli(tmp_path, "codex", "echo 'I have no such policy'\n"),
            "grok": _fake_cli(tmp_path, "grok", "printf 'Internal error: {\\n  \"message\": \"API error (status 402 Payment Required): Grok Build usage balance exhausted\",\\n  \"http_status\": 402\\n}\\n' >&2\nexit 1\n"),
            "hermes": _fake_cli(tmp_path, "hermes", "echo 'xAI OAuth state is missing access_token. Re-authenticate with `hermes model`.'\nexit 0\n")}
    monkeypatch.setattr(health, "find_binary", lambda n: bins[n])
    r = {n: health.live(n, timeout=10, marker="Merging") for n in bins}
    assert r["claude-code"]["result"] == "ok" and r["claude-code"]["policy"] == "yes"
    assert r["codex"]["result"] == "ok" and r["codex"]["policy"] == "NO"
    assert r["grok"]["result"] == "error" and r["grok"]["kind"] == "quota"
    assert r["grok"]["detail"] == "API error (status 402 Payment Required): Grok Build usage balance exhausted"
    assert r["hermes"]["result"] == "error" and r["hermes"]["kind"] == "auth"


def test_live_commands_are_headless_and_cheap():
    assert health.live_command("claude-code", "claude")[:2] == ["claude", "-p"]
    assert "--model" in health.live_command("claude-code", "claude")
    assert health.live_command("codex", "codex")[:2] == ["codex", "exec"] and "--ephemeral" in health.live_command("codex", "codex")
    assert health.live_command("grok", "grok")[:2] == ["grok", "-p"]
    assert health.live_command("hermes", "hermes")[:2] == ["hermes", "-z"]


def test_render_never_prints_a_secret(home, monkeypatch):
    monkeypatch.setattr(health, "find_binary", lambda n: None)
    (home / ".codex" / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": _jwt(NOW), "refresh_token": SECRET}}))
    (home / ".grok" / "auth.json").write_text(json.dumps({"x::1": {"key": SECRET, "refresh_token": SECRET}}))
    rows = [health.offline(n) for n in ("codex", "grok")]
    assert SECRET not in health.render(rows) and SECRET not in json.dumps(rows, default=str)


def test_doctor_checks_one_line_per_installed_harness(home, monkeypatch):
    monkeypatch.setattr(health, "find_binary", lambda n: None)
    import shutil
    shutil.rmtree(home / ".hermes")
    rows = health.doctor_checks({"grok": _fake_sessions(3)}, home=home)
    assert [r["name"] for r in rows] == ["health:claude", "health:codex", "health:grok"]
    assert all(set(r) == {"level", "name", "detail", "fix"} for r in rows)
    assert "7d:" not in rows[2]["detail"]  # doctor's harness:grok line already counts sessions
