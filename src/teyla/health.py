"""Can each harness do work right now? — `teyla harness verify [--live]` and doctor's `health:*` lines.

`teyla harness status` answers "is Teyla wired into it". That is not the question a person has
when a routine stopped producing anything: on 2026-09-29 doctor said grok and hermes were OK
("wired") while every Grok model answered HTTP 402 "Grok Build usage balance exhausted" and
Hermes answered "xAI OAuth state is missing access_token". This module reads, per harness and
without a network call:

  version   `<binary> --version` (a broken install fails here: Hermes mid-update printed
            "no dependency environment is committed for this install; run `hermes pm repair`")
  auth      present and not obviously expired — shape and dates only, never a secret:
              claude  ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN in the environment, else the
                      macOS keychain item "Claude Code-credentials" (presence: `security
                      find-generic-password -s …` exit 0, no -w), else ~/.claude/.credentials.json
              codex   ~/.codex/auth.json: auth_mode, tokens.{access,refresh}_token present,
                      the access token's JWT `exp` (Codex refreshes it; 0.153.4)
              grok    ~/.grok/auth.json: `{"<issuer>::<id>": {key, refresh_token, expires_at, …}}`
                      (Grok CLI 1.0.0)
              hermes  ~/.hermes/auth.json: `active_provider`, `providers[p].tokens` — the
                      xai-oauth state held only id_token after a failed refresh — and
                      `providers[p].last_auth_error` {code, message, relogin_required, at}
                      (Hermes 0.20.4)
  errors    the newest quota / rate / auth / network error in the harness's own recent
            records, and the newest success, so an error that later calls got past is history:
              claude  ~/.claude/projects/**/*.jsonl tails: `isApiErrorMessage: true` records
              codex   ~/.codex/logs_2.sqlite ERROR rows; rollout `event_msg` type `error`;
                      the last `token_count.rate_limits` (plan, 5-hour and weekly used_percent)
              grok    ~/.grok/logs/unified.jsonl: `shell.turn.inference_failed` {status_code,
                      message} vs `shell.turn.inference_done`
              hermes  auth.json `last_auth_error`; logs/errors.log; state.db last assistant row

`verify --live` additionally sends one line through each installed harness headless (`claude
-p`, `codex exec`, `grok -p`, `hermes -z`) from an empty temporary directory and checks the
answer names the title of POLICY.md §7 — the policy reaches that harness from its global file,
not from a repo. --live spends a few tokens per harness and is never run by a routine or a hook.
"""
from __future__ import annotations

import base64
import concurrent.futures
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HOME = pathlib.Path.home()
NAMES = ("claude-code", "codex", "grok", "hermes")
BINARY = {"claude-code": "claude", "codex": "codex", "grok": "grok", "hermes": "hermes"}
# GUI apps put their CLI where no shell PATH looks (ChatGPT 26.9xx bundles Codex here).
APP_BINARY = {"codex": "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"}
TAIL = 512 * 1024


def child_env(env=None) -> dict:
    """The environment a harness CLI is started with here. Inside a Claude Code session the host
    exports its own session variables (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CLAUDE_CODE_SESSION_ID,
    CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH, the desktop app's ANTHROPIC_BASE_URL, …); a child
    `claude` that inherits them is not the `claude` a terminal or a routine runs. They are
    dropped; the user's own settings (CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_USE_BEDROCK/VERTEX)
    are kept."""
    env = dict(os.environ if env is None else env)
    if "CLAUDE_CODE_ENTRYPOINT" in env or "CLAUDECODE" in env:
        keep = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}
        desktop = "CLAUDE_CODE_DESKTOP_APP_VERSION" in env
        for k in list(env):
            if (k.startswith("CLAUDE_CODE_") and k not in keep) or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT",
                                                                         "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR"):
                env.pop(k)
            elif k == "ANTHROPIC_BASE_URL" and desktop:
                env.pop(k)
    return env


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _home(name: str, home: pathlib.Path | None = None) -> pathlib.Path:
    h = home or HOME
    if name == "codex" and not home and os.environ.get("CODEX_HOME"):
        return pathlib.Path(os.environ["CODEX_HOME"])
    if name == "grok" and not home and os.environ.get("GROK_HOME"):
        return pathlib.Path(os.environ["GROK_HOME"])
    return h / {"claude-code": ".claude", "codex": ".codex", "grok": ".grok", "hermes": ".hermes"}[name]


def _parse_ts(v) -> _dt.datetime | None:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            return _dt.datetime.fromtimestamp(float(v), _dt.timezone.utc)
        s = str(v).strip().replace("Z", "+00:00")
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+$", s):  # Python logging, local time
            return _dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S,%f").astimezone(_dt.timezone.utc)
        d = _dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _tail(path: pathlib.Path, n: int = TAIL) -> bytes:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - n))
            data = fh.read()
        return data if size <= n else data.split(b"\n", 1)[-1]
    except OSError:
        return b""


# --- classify an error text -------------------------------------------------------------------

_KINDS = (
    ("quota", re.compile(r"\b402\b|payment required|balance exhausted|insufficient_quota|usage limit|session limit|"
                         r"weekly limit|out of credits|credit balance|billing|quota", re.I)),
    ("auth", re.compile(r"\b401\b|unauthori[sz]ed|missing access_token|invalid_grant|refresh token|re-?authenticate|"
                        r"relogin|not logged in|authenticat|invalid api key|expired token|session expired", re.I)),
    ("rate", re.compile(r"\b429\b|rate.?limit|too many requests|\b529\b|overloaded", re.I)),
    ("network", re.compile(r"ENOTFOUND|ECONNREFUSED|ECONNRESET|timed out|timeout|can't reach|could not resolve|"
                           r"network|connection (refused|reset|closed)|dns", re.I)),
)


def classify(text: str, status: int | None = None) -> str:
    if status == 402:
        return "quota"
    if status in (401, 403):
        return "auth"
    if status in (429, 529):
        return "rate"
    for kind, rx in _KINDS:
        if rx.search(text or ""):
            return kind
    return "other"


def _err(ts, kind, message, source) -> dict:
    return {"ts": ts, "kind": kind, "message": " ".join(str(message).split())[:200], "source": source}


# --- auth -------------------------------------------------------------------------------------

def _jwt_exp(token: str) -> _dt.datetime | None:
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return _dt.datetime.fromtimestamp(int(claims["exp"]), _dt.timezone.utc)
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def _keychain_has(service: str) -> bool:
    if sys.platform != "darwin" or not shutil.which("security"):
        return False
    try:
        # No -w/-g: exit status only, the secret is never read.
        return subprocess.run(["security", "find-generic-password", "-s", service],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def claude_auth_status(binary: str | None) -> dict | None:
    """`claude auth status` (Claude Code 2.1.234): `{"loggedIn": bool, "authMethod", "apiProvider"}`
    — no secret in it. None when it cannot be run."""
    if not binary:
        return None
    try:
        r = subprocess.run([binary, "auth", "status"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL, env=child_env())
        d = json.loads(r.stdout)
        return d if isinstance(d, dict) and "loggedIn" in d else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def auth_claude(home: pathlib.Path, env=None, status: dict | None = None) -> dict:
    env = os.environ if env is None else env
    if status is not None and not status.get("loggedIn") and not env.get("ANTHROPIC_API_KEY") \
            and not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        where = " (the keychain item \"Claude Code-credentials\" exists: its OAuth session expired)" \
            if _keychain_has("Claude Code-credentials") else ""
        return {"ok": False, "detail": f"`claude auth status`: loggedIn false{where} — `claude -p` and routines cannot run; "
                                       "the desktop app signs in on its own", "fix": "claude auth login"}
    if status and status.get("loggedIn"):
        return {"ok": True, "detail": f"logged in ({status.get('authMethod', '?')}, {status.get('apiProvider', '?')})"}
    for var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        if env.get(var):
            return {"ok": True, "detail": f"{var} set in the environment"}
    if (home / ".credentials.json").is_file():
        return {"ok": True, "detail": "~/.claude/.credentials.json present"}
    if _keychain_has("Claude Code-credentials"):
        return {"ok": True, "detail": "keychain item \"Claude Code-credentials\" present"}
    return {"ok": False, "detail": "no credentials (env, keychain or ~/.claude/.credentials.json)",
            "fix": "claude auth login"}


def auth_codex(home: pathlib.Path, env=None) -> dict:
    env = os.environ if env is None else env
    p = home / "auth.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        if env.get("OPENAI_API_KEY"):
            return {"ok": True, "detail": "OPENAI_API_KEY set in the environment"}
        return {"ok": False, "detail": f"no {p}", "fix": "codex login"}
    if d.get("OPENAI_API_KEY"):
        return {"ok": True, "detail": "API key in auth.json"}
    tok = d.get("tokens") or {}
    if not tok.get("access_token") and not tok.get("refresh_token"):
        return {"ok": False, "detail": f"{p} holds no tokens", "fix": "codex login"}
    exp = _jwt_exp(tok.get("access_token") or "")
    mode = d.get("auth_mode") or "?"
    if exp and exp < _now():
        if tok.get("refresh_token"):
            return {"ok": True, "detail": f"{mode} login; access token expired {exp:%Y-%m-%d}, Codex refreshes it on the next run"}
        return {"ok": False, "detail": f"{mode} login expired {exp:%Y-%m-%d} and no refresh token", "fix": "codex login"}
    return {"ok": True, "detail": f"{mode} login" + (f", access token valid until {exp:%Y-%m-%d}" if exp else "")}


def auth_grok(home: pathlib.Path, env=None) -> dict:
    env = os.environ if env is None else env
    if env.get("XAI_API_KEY") or env.get("GROK_API_KEY"):
        return {"ok": True, "detail": "XAI_API_KEY set in the environment"}
    p = home / "auth.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"ok": False, "detail": f"no {p}", "fix": "grok login"}
    entries = [v for v in d.values() if isinstance(v, dict)] if isinstance(d, dict) else []
    if not any(e.get("key") or e.get("refresh_token") for e in entries):
        return {"ok": False, "detail": f"{p} holds no credentials", "fix": "grok login"}
    e = next(e for e in entries if e.get("key") or e.get("refresh_token"))
    exp = _parse_ts(e.get("expires_at"))
    mode = e.get("auth_mode") or "?"
    if exp and exp < _now() and not e.get("refresh_token"):
        return {"ok": False, "detail": f"{mode} session expired {exp:%Y-%m-%d %H:%M}Z and no refresh token", "fix": "grok login"}
    return {"ok": True, "detail": f"{mode} login" + (", refreshed automatically" if e.get("refresh_token") else "")}


def auth_hermes(home: pathlib.Path, env=None) -> dict:
    p = home / "auth.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"ok": False, "detail": f"no {p}", "fix": "hermes model   (pick a provider and sign in)"}
    prov = d.get("active_provider")
    if not prov:
        return {"ok": False, "detail": "no active provider", "fix": "hermes model"}
    st = (d.get("providers") or {}).get(prov)
    pool = (d.get("credential_pool") or {}).get(prov) or []
    if st is None:
        if pool:
            return {"ok": True, "detail": f"{prov}: {len(pool)} pooled credential(s)"}
        return {"ok": False, "detail": f"{prov}: no credentials", "fix": f"hermes model   (re-authenticate {prov})"}
    tok = st.get("tokens") or {}
    err = st.get("last_auth_error") or {}
    if not tok.get("access_token"):
        why = f" — last error {str(err.get('at', ''))[:10]}: {err.get('message', '')[:120]}" if err else ""
        return {"ok": False, "detail": f"{prov} state is missing access_token{why}",
                "fix": f"hermes model   (re-authenticate {_provider_label(prov)})"}
    if err.get("relogin_required"):
        return {"ok": False, "detail": f"{prov}: relogin required since {str(err.get('at', ''))[:10]}: {err.get('message', '')[:120]}",
                "fix": f"hermes model   (re-authenticate {_provider_label(prov)})"}
    return {"ok": True, "detail": f"{prov} signed in"}


def _provider_label(prov: str) -> str:
    return {"xai-oauth": "xAI", "openai-api": "OpenAI", "anthropic": "Anthropic", "nous": "Nous"}.get(prov, prov)


AUTH = {"claude-code": auth_claude, "codex": auth_codex, "grok": auth_grok, "hermes": auth_hermes}


# --- errors and the last success --------------------------------------------------------------

def errors_claude(home: pathlib.Path, since: float) -> dict:
    """{error, last_ok}: `isApiErrorMessage` records vs ordinary assistant records, from the
    tail of every transcript written in the window."""
    root = home / "projects"
    newest_err, last_ok = None, {}
    if not root.is_dir():
        return {"error": None, "last_ok": None}
    for p in root.glob("*/*.jsonl"):
        try:
            if p.stat().st_mtime < since:
                continue
        except OSError:
            continue
        for raw in _tail(p).splitlines():
            if b'"type":"assistant"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            ts = _parse_ts(d.get("timestamp"))
            if ts is None or ts.timestamp() < since:
                continue
            # `claude -p` (entrypoint sdk-cli) and the desktop app sign in separately: a desktop
            # session that worked says nothing about a `-p` routine that failed, so an error is
            # weighed against later successes of its own entrypoint.
            ep = d.get("entrypoint") or "?"
            if d.get("isApiErrorMessage"):
                content = (d.get("message") or {}).get("content") or []
                text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                if newest_err is None or ts > newest_err["ts"]:
                    newest_err = dict(_err(ts, classify(text + " " + str(d.get("error") or "")), text, p.name), entrypoint=ep)
            elif ep not in last_ok or ts > last_ok[ep]:
                last_ok[ep] = ts
    ok = last_ok.get(newest_err["entrypoint"]) if newest_err else max(last_ok.values(), default=None)
    return {"error": newest_err, "last_ok": ok}


def errors_codex(home: pathlib.Path, since: float) -> dict:
    newest_err, last_ok, limits = None, None, None
    db = home / "logs_2.sqlite"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            rows = con.execute("select ts, feedback_log_body from logs where level='ERROR' and ts >= ? "
                               "order by ts desc limit 200", (int(since),)).fetchall()
            con.close()
        except sqlite3.Error:
            rows = []
        for ts, body in rows:
            kind = classify(body or "")
            # A model-list refresh timing out is noise; a failed turn is not.
            if kind == "network" and "list_models" in (body or ""):
                continue
            newest_err = _err(_parse_ts(ts), kind, body or "", "logs_2.sqlite")
            break
    sessions = home / "sessions"
    files = []
    if sessions.is_dir():
        for p in sessions.glob("*/*/*/rollout-*.jsonl"):
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m >= since:
                files.append((m, p))
    files.sort(reverse=True)
    for i, (_, p) in enumerate(files):
        for raw in _tail(p).splitlines():
            if b'"token_count"' in raw or b'"type":"error"' in raw or (b'"task_complete"' in raw and b'"error"' in raw):
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                pl = d.get("payload") or {}
                ts = _parse_ts(d.get("timestamp"))
                if ts is None:
                    continue
                if pl.get("type") == "token_count":
                    if last_ok is None or ts > last_ok:
                        last_ok = ts
                    # Codex reports several limit ids ("codex", and "premium" with null windows);
                    # the newest one that carries a window is the one that says how close it is.
                    rl = pl.get("rate_limits") or {}
                    if (rl.get("primary") or rl.get("secondary")) and (limits is None or ts > limits["at"]):
                        limits = dict(rl, at=ts)
                elif pl.get("type") == "error":
                    msg = pl.get("message") or json.dumps(pl)[:200]
                    if newest_err is None or ts > newest_err["ts"]:
                        newest_err = _err(ts, classify(msg), msg, p.name)
                elif pl.get("type") == "task_complete" and isinstance(pl.get("error"), dict):
                    # A turn Codex ended on an error (0.153.4, 2026-09-29): {"message": "You've hit
                    # your usage limit. … try again at 11:20 PM.", "codex_error_info": "usage_limit_exceeded"}
                    er = pl["error"]
                    msg = er.get("message") or str(er.get("codex_error_info") or "error")
                    kind = "quota" if "usage_limit" in str(er.get("codex_error_info") or "") else classify(msg)
                    if newest_err is None or ts > newest_err["ts"]:
                        newest_err = _err(ts, kind, msg, p.name)
        if i >= 40 and last_ok is not None:
            break  # the newest forty rollouts settle "last success" and the current limits
    return {"error": newest_err, "last_ok": last_ok, "limits": limits}


def errors_grok(home: pathlib.Path, since: float) -> dict:
    newest_err, last_ok, n_err = None, None, 0
    for raw in _tail(home / "logs" / "unified.jsonl", 8 * 1024 * 1024).splitlines():
        if b"shell.turn.inference_" not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        ts = _parse_ts(d.get("ts"))
        if ts is None or ts.timestamp() < since:
            continue
        if d.get("msg") == "shell.turn.inference_done":
            last_ok = ts if last_ok is None or ts > last_ok else last_ok
        elif d.get("msg") == "shell.turn.inference_failed":
            ctx = d.get("ctx") or {}
            n_err += 1
            if newest_err is None or ts >= newest_err["ts"]:
                newest_err = _err(ts, classify(ctx.get("message", ""), ctx.get("status_code")),
                                  ctx.get("message") or f"status {ctx.get('status_code')}", "logs/unified.jsonl")
    if newest_err:
        newest_err["count"] = n_err
    return {"error": newest_err, "last_ok": last_ok}


_LOG_LINE = re.compile(rb"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) (ERROR|WARNING|CRITICAL) (\S+): (.*)$")


def errors_hermes(home: pathlib.Path, since: float) -> dict:
    newest_err, last_ok = None, None
    try:
        d = json.loads((home / "auth.json").read_text())
        for prov, st in (d.get("providers") or {}).items():
            e = (st or {}).get("last_auth_error") or {}
            ts = _parse_ts(e.get("at"))
            if ts and ts.timestamp() >= since:
                newest_err = _err(ts, "auth", f"{prov}: {e.get('message', e.get('code', ''))}", "auth.json")
    except (OSError, ValueError, AttributeError):
        pass
    for raw in _tail(home / "logs" / "errors.log").splitlines():
        m = _LOG_LINE.match(raw)
        if not m:
            continue
        text = m.group(4).decode("utf-8", "replace")
        kind = classify(text)
        if kind in ("other", "network") or "Auxiliary" in text or "auxiliary" in m.group(3).decode():
            continue  # the auxiliary lane's fallbacks are not the chat model failing
        ts = _parse_ts(m.group(1).decode())
        if ts and ts.timestamp() >= since and (newest_err is None or ts > newest_err["ts"]):
            newest_err = _err(ts, kind, text, "logs/errors.log")
    db = home / "state.db"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            (t,) = con.execute("select max(timestamp) from messages where role='assistant'").fetchone()
            con.close()
            last_ok = _parse_ts(t)
        except sqlite3.Error:
            pass
    return {"error": newest_err, "last_ok": last_ok}


ERRORS = {"claude-code": errors_claude, "codex": errors_codex, "grok": errors_grok, "hermes": errors_hermes}


# --- one harness, offline ---------------------------------------------------------------------

def find_binary(name: str) -> str | None:
    b = shutil.which(BINARY[name])
    if b:
        return b
    for cand in (APP_BINARY.get(name), str(HOME / ".local" / "bin" / BINARY[name])):
        if cand and os.access(cand, os.X_OK):
            return cand
    return None


def version(binary: str) -> tuple[str | None, str | None]:
    """(version, error). A non-zero exit or no version-looking text is the error, first line."""
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL,
                           env=child_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)[:160]
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    # "codex-cli 0.153.4", "2.1.234 (Claude Code)", "grok 1.0.0 (3cd0d0c)", "Hermes Agent v0.20.4 (…)";
    # a Hermes git install says "Hermes Agent vgit.7368801 (2026.9.24)".
    m = re.search(r"(?<![\w.])v?(git\.[0-9a-f]{6,}|\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?)", r.stdout or "")
    if r.returncode != 0 or not m:
        first = next((l.strip() for l in out.splitlines() if l.strip()), f"exit {r.returncode}")
        return None, first[:200]
    return m.group(1), None


def _fix_for(name: str, err: dict, batch_top: tuple[str, int] | None) -> str:
    kind = err["kind"]
    if name == "grok" and kind == "quota":
        s = "Grok Build balance exhausted — top up (console.x.ai → Grok Build usage)"
        if batch_top:
            s += f", or move `{batch_top[0]}` ({batch_top[1]} `grok -p` calls in 7 days) to another provider"
        return s
    if name == "hermes" and kind == "auth":
        return "hermes model   (re-authenticate xAI)" if "xai" in err["message"].lower() else "hermes model   (re-authenticate)"
    if kind == "auth":
        return {"claude-code": "claude auth login", "codex": "codex login", "grok": "grok login"}.get(name, "sign in again")
    if kind == "quota":
        return {"claude-code": "Claude usage limit — wait for the reset the message names, or move batch work to a cheaper model",
                "codex": "Codex usage limit — wait for the reset, or move `codex exec` batch work elsewhere"}.get(
                    name, "top up, or move the batch work to another provider")
    if kind == "rate":
        return "rate-limited — spread the batch calls out, or lower their concurrency"
    return "look at the message; retry"


def _short(name: str) -> str:
    return "claude" if name == "claude-code" else name


def offline(name: str, home: pathlib.Path | None = None, days: int = 7, sessions: list | None = None,
            run_version: bool = True, show_sessions: bool = True) -> dict:
    """Everything knowable about one harness without calling a model."""
    hdir = _home(name, home)
    binary = find_binary(name) if run_version else None
    row = {"harness": _short(name), "installed": bool(binary) or hdir.is_dir(), "binary": binary,
           "show_sessions": show_sessions}
    if not row["installed"]:
        return row
    # No binary but a home directory: a desktop app without its CLI on PATH, not a broken install.
    row["version"], row["version_error"] = version(binary) if binary else (None, None)
    row["auth"] = auth_claude(hdir, status=claude_auth_status(binary)) if name == "claude-code" else AUTH[name](hdir)
    since = time.time() - days * 86400
    try:
        e = ERRORS[name](hdir, since)
    except Exception as exc:  # noqa: BLE001 — a health check must never take doctor down
        e = {"error": None, "last_ok": None, "scan_error": str(exc)[:120]}
    row.update(error=e.get("error"), last_ok=e.get("last_ok"), limits=e.get("limits"))
    if sessions is not None:
        cutoff = _dt.datetime.fromtimestamp(since, _dt.timezone.utc).isoformat()[:19]
        recent = [s for s in sessions if (s.last or s.first or "") >= cutoff]
        row["sessions"] = {"interactive": sum(1 for s in recent if not s.batch), "batch": sum(1 for s in recent if s.batch)}
        from .grokcost import project_of  # worktrees, ~/repos/<repo> and <repo>-grok-empty are <repo>
        by_proj: dict = {}
        for s in recent:
            if s.batch:
                key = project_of(s.cwd or s.project or "?")
                by_proj[key] = by_proj.get(key, 0) + 1
        row["batch_top"] = max(by_proj.items(), key=lambda kv: kv[1]) if by_proj else None
    return verdict(name, row)


# Parallel batch calls finish out of order: a review that started before the limit can complete
# seconds after another one hit it. A success counts as recovery only this long after the error.
RECOVERY_MARGIN = _dt.timedelta(minutes=5)


def recovered(err: dict | None, last_ok: _dt.datetime | None) -> bool:
    return bool(err and err.get("ts") and last_ok and last_ok > err["ts"] + RECOVERY_MARGIN)


def verdict(name: str, row: dict) -> dict:
    """level (OK/WARN/FIX), a one-line detail, and the fix."""
    parts, level, fix = [], "OK", None
    parts.append(row.get("version") or (f"no `{BINARY[name]}` on PATH" if not row.get("binary") else "version ?"))
    if row.get("version_error"):
        level, fix = "FIX", f"the `{BINARY[name]}` install does not start: {row['version_error']}"
        parts[-1] = "broken install"
    a = row.get("auth") or {}
    parts.append(("auth ok: " if a.get("ok") else "AUTH: ") + a.get("detail", "?"))
    if a and not a.get("ok"):
        level, fix = "FIX", fix or a.get("fix")
    lim = row.get("limits")
    if lim:
        p, s = (lim.get("primary") or {}), (lim.get("secondary") or {})
        pct = [x for x in (p.get("used_percent"), s.get("used_percent")) if isinstance(x, (int, float))]
        fmt = lambda v: f"{v:g}%" if isinstance(v, (int, float)) else "?"  # noqa: E731
        text = f"{lim.get('plan_type') or 'plan ?'}: 5h {fmt(p.get('used_percent'))}, week {fmt(s.get('used_percent'))}"
        if s.get("resets_at"):
            text += f" (resets {_dt.datetime.fromtimestamp(s['resets_at']):%a %d %b %H:%M})"
        parts.append(text)
        if lim.get("rate_limit_reached_type") or (pct and max(pct) >= 100):
            level, fix = "FIX", fix or "Codex usage limit reached — wait for the reset above"
        elif pct and max(pct) >= 90 and level == "OK":
            level = "WARN"
    err, ok = row.get("error"), row.get("last_ok")
    if err and a and not a.get("ok") and err.get("source") == "auth.json":
        err = None  # the auth line above already says it
    if err and err.get("ts"):
        stale = recovered(err, ok)
        n = f" ×{err['count']}" if err.get("count", 1) > 1 else ""
        parts.append(f"last error {err['ts']:%Y-%m-%d %H:%M}Z {err['kind']}{n}: {err['message'][:110]}"
                     + (f" (later calls succeeded, last {ok:%Y-%m-%d %H:%M}Z)" if stale else ""))
        if not stale and err["kind"] in ("quota", "auth"):
            level, fix = "FIX", fix or _fix_for(name, err, row.get("batch_top"))
        elif not stale and err["kind"] == "rate" and level == "OK":
            level, fix = "WARN", _fix_for(name, err, row.get("batch_top"))
    elif ok:
        parts.append(f"last success {ok:%Y-%m-%d %H:%M}Z")
    ss = row.get("sessions")
    if ss is not None and row.get("show_sessions", True):
        parts.append(f"7d: {ss['interactive']} interactive, {ss['batch']} batch")
    row.update(level=level, detail="; ".join(parts), fix=fix)
    return row


def doctor_checks(sessions_by_harness: dict | None = None, home: pathlib.Path | None = None) -> list[dict]:
    """One `health:<harness>` line per installed harness, for doctor."""
    names = [n for n in NAMES if find_binary(n) or _home(n, home).is_dir()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        # doctor's harness:<name> line already counts the sessions; the batch volume still names
        # the project to move off a harness whose balance ran out.
        rows = list(ex.map(lambda n: offline(n, home=home, sessions=(sessions_by_harness or {}).get(n),
                                             show_sessions=False), names))
    return [{"level": r["level"], "name": f"health:{r['harness']}", "detail": r["detail"], "fix": r["fix"]} for r in rows]


def window_errors(days: int, home: pathlib.Path | None = None) -> list[dict]:
    """For advice A18: each installed harness whose own records hold a quota/balance or auth
    error in the last `days` days (or whose Codex rate limit is reached), and whether it is still
    failing — no call succeeded after it."""
    since = time.time() - days * 86400
    out = []
    for name in NAMES:
        hdir = _home(name, home)
        if not hdir.is_dir():
            continue
        try:
            e = ERRORS[name](hdir, since)
        except Exception:  # noqa: BLE001 — advice must never take the report down
            continue
        err, ok = e.get("error"), e.get("last_ok")
        lim = e.get("limits") or {}
        if lim.get("rate_limit_reached_type") and (err is None or err["kind"] not in ("quota", "auth")):
            err = _err(lim.get("at"), "quota", f"usage limit reached ({lim['rate_limit_reached_type']})", "rate_limits")
            ok = None
        if not err or err["kind"] not in ("quota", "auth") or err.get("ts") is None:
            continue
        out.append(dict(harness=_short(name), kind=err["kind"], day=f"{err['ts']:%Y-%m-%d}", message=err["message"],
                        count=err.get("count", 1), still_failing=not recovered(err, ok),
                        fix=_fix_for(name, err, None)))
    return out


# --- live ---------------------------------------------------------------------------------------

def policy_marker(policy_path: pathlib.Path | None = None) -> str | None:
    """The title of §7 of POLICY.md ("Merging" in Ivan's), which a model can only name if the
    policy is in its instructions."""
    from . import policy
    p = policy_path or policy.POLICY
    try:
        m = re.search(r"^##\s*7\.\s*(.+?)\s*$", p.read_text(), re.M)
    except OSError:
        return None
    return m.group(1).split("—")[0].strip() if m else None


LIVE_PROMPT = ("Reply with one line and nothing else: the title of section 7 of the operating policy in your "
               "instructions (the heading text after \"7.\"). Do not use any tool and do not read any file. "
               "If your instructions contain no such policy, reply NO-POLICY.")


def live_command(name: str, binary: str, prompt: str = LIVE_PROMPT) -> list[str]:
    if name == "claude-code":
        return [binary, "-p", prompt, "--model", "haiku", "--max-turns", "2"]
    if name == "codex":
        return [binary, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                "-c", 'model_reasoning_effort="low"', prompt]
    if name == "grok":
        return [binary, "-p", prompt, "--max-turns", "2"]
    if name == "hermes":
        return [binary, "-z", prompt]
    raise ValueError(name)


def live(name: str, timeout: int = 120, marker: str | None = None) -> dict:
    binary = find_binary(name)
    row = {"harness": _short(name)}
    if not binary:
        return dict(row, result="absent")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="teyla-verify-") as cwd:
        try:
            r = subprocess.run(live_command(name, binary), capture_output=True, text=True, timeout=timeout,
                               cwd=cwd, stdin=subprocess.DEVNULL, env=child_env())
            out, code = (r.stdout or "").strip(), r.returncode
            errtext = (r.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return dict(row, result="error", secs=round(time.time() - t0), detail=f"no answer in {timeout}s", policy="?")
        except OSError as e:
            return dict(row, result="error", secs=0, detail=str(e)[:160], policy="?")
    secs = round(time.time() - t0)
    answer = next((l.strip() for l in reversed(out.splitlines()) if l.strip()), "")
    failed_text = _failure_line(out + "\n" + errtext)
    if code != 0 or not answer or failed_text and not (marker and marker.lower() in out.lower()):
        detail = failed_text or (errtext.splitlines() or [f"exit {code}"])[-1]
        return dict(row, result="error", secs=secs, detail=detail[:160], kind=classify(detail), policy="?")
    pol = "?" if not marker else ("yes" if marker.lower() in out.lower() else "NO")
    return dict(row, result="ok", secs=secs, detail=answer[:80], policy=pol)


_FAIL = re.compile(r"(error|failed|exhausted|payment required|unauthori[sz]ed|missing access_token|re-?authenticate|"
                   r"\b40[1-3]\b|\b429\b)", re.I)


def _failure_line(text: str) -> str | None:
    # Grok prints `Internal error: {\n  "message": "API error (status 402 …)", "http_status": 402 }`.
    m = re.search(r'"message"\s*:\s*"([^"]+)"', text)
    if m and _FAIL.search(m.group(1)):
        return m.group(1)
    for line in text.splitlines():
        if _FAIL.search(line) and not line.lstrip().startswith(("warning:", "WARN")):
            return " ".join(line.split())
    return None


def verify(live_run: bool = False, timeout: int = 120, home: pathlib.Path | None = None) -> list[dict]:
    from .adapters import claude_code, codex, grok, hermes
    mods = {"claude-code": claude_code, "codex": codex, "grok": grok, "hermes": hermes}
    since = time.time() - 7 * 86400
    names = [n for n in NAMES if find_binary(n) or _home(n, home).is_dir()]

    def one(n):
        try:
            sess = mods[n].load(since=since) if home is None else None
        except Exception:  # noqa: BLE001
            sess = None
        return offline(n, home=home, sessions=sess)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, names))
    if live_run:
        marker = policy_marker()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            lives = list(ex.map(lambda n: live(n, timeout=timeout, marker=marker), names))
        for r, lv in zip(rows, lives):
            r["live"] = lv
    return rows


def render(rows: list[dict], live_run: bool = False) -> str:
    lines = []
    for r in rows:
        lines.append(f"{r['level']:4} {r['harness']:7} {r['detail']}")
        if r.get("fix") and r["level"] != "OK":
            lines.append(f"{'':4} {'':7} → {r['fix']}")
    if live_run:
        lines += ["", f"{'harness':8} {'live':6} {'secs':>4}  {'policy':6} answer / error",
                  f"{'-' * 8} {'-' * 6} {'-' * 4}  {'-' * 6} {'-' * 40}"]
        for r in rows:
            lv = r.get("live") or {}
            lines.append(f"{r['harness']:8} {lv.get('result', '-'):6} {lv.get('secs', ''):>4}  {lv.get('policy', '-'):6} {lv.get('detail', '')}")
    return "\n".join(lines)


def cmd_verify(args) -> int:
    rows = verify(live_run=getattr(args, "live", False), timeout=getattr(args, "timeout", 120))
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
    else:
        print(render(rows, live_run=getattr(args, "live", False)))
    bad = any(r["level"] == "FIX" for r in rows) or any((r.get("live") or {}).get("result") == "error" for r in rows)
    return 1 if bad else 0
