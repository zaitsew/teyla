"""The orchestrator gate: a top-tier model orchestrates, a worker builds.

Owner policy (2026-11-27, POLICY.md section 1): Claude Fable and OpenAI Astra brief workers, decide, check
evidence and report. Builds, tests, commits, pushes, merges and store uploads go to a named worker. This is
the PreToolUse hook (`plugin/hooks/orchestrator-gate.sh`, matcher `Bash`, Claude Code and Codex) that makes a
top-tier main session unable to run them itself.

What the hook payload carries (checked against the installed binaries):
  Codex 0.172 `pre-tool-use.command.input` schema: `model` (required), `session_id`, `transcript_path`
    (the rollout file, nullable), `turn_id`, `cwd`, `tool_name`, `tool_input`, optional `agent_id`/`agent_type`.
    The model comes from the payload. Without it: the latest `turn_context` record of the rollout.
    A sub-agent is a rollout whose first record, `session_meta`, says `thread_source: "subagent"`.
  Claude Code: `session_id`, `transcript_path`, `cwd`, `tool_name`, `tool_input` and, inside a sub-agent,
    `agent_id`. No model field is relied on (one is used if present): the model is the `message.model` of the
    last assistant record at the tail of the transcript. A sub-agent's transcript lives under `subagents/` and
    its records carry `isSidechain: true`.
Reading a bounded tail of one file costs about a millisecond, so nothing is cached between calls: a cache keyed
on the transcript would miss on every call (the file grows with each tool use) and a time-based one would let
a `/model` switch go unseen.

Config, `~/.teyla/config.toml`:
  [orchestrator]
  gate = "refuse"          # refuse | warn | off
  top_models = ["claude-fable-", "gpt-[0-9.]+-astra"]    # regexes, searched in the model id

Exit 2 and a short stderr message refuse. Every error allows (fail open) and is logged. The override is
`TEYLA_ORCH_OK="<reason>"` in the hook's environment or as a leading assignment word of the command; it allows
and appends a row. Rows go to `~/.teyla/orchestrator-gate.tsv` (`$TEYLA_HOME` overrides the directory):
`date, event (refuse|warn|override|error), harness, model, command head, reason`. The head is the first two
words of the worker command (`git commit`), never its arguments.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys

LOG_NAME = "orchestrator-gate.tsv"
TAIL_BYTES = 262144
DEFAULT_TOP = ("claude-fable-", r"gpt-[0-9.]+-astra")
MODES = ("refuse", "warn", "off")
DELEGATE = ("Delegate this to a worker: Claude -> Agent(subagent_type: builder, model: sonnet); "
            "Codex -> spawn_agent(agent_type: volume).")
NPM_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
NPM_VALUE_OPTS = {"--prefix", "-C", "--dir", "--cwd", "--workspace", "-w", "--filter", "-F", "--project"}
XCODE_READONLY = {"-list", "-showsdks", "-version", "-showbuildsettings", "-showdestinations", "-help", "-usage"}
SIMCTL_WORK = {"boot", "install", "launch", "create", "clone", "bootstatus"}
GIT_WORK = {"commit", "push", "merge", "rebase", "cherry-pick"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GH_VALUE_OPTS = {"-R", "--repo", "--hostname"}


def home_dir(environ=os.environ) -> pathlib.Path:
    return pathlib.Path(environ.get("TEYLA_HOME") or os.path.join(os.path.expanduser("~"), ".teyla"))


def log_row(event: str, harness: str, model: str, head: str, reason: str = "", environ=os.environ) -> None:
    try:
        d = home_dir(environ)
        d.mkdir(parents=True, exist_ok=True)
        clean = lambda s: re.sub(r"[\t\r\n]+", " ", str(s))[:200]
        row = "\t".join([dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), event, clean(harness), clean(model),
                         clean(head), clean(reason)])
        with open(d / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except OSError:
        pass


def load_config(environ=os.environ) -> tuple[str, list[str]]:
    """(mode, top-model regexes). An unreadable config gives the defaults; an unknown mode is refuse."""
    import tomllib
    mode, tops = "refuse", list(DEFAULT_TOP)
    try:
        data = tomllib.loads((home_dir(environ) / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return mode, tops
    sec = data.get("orchestrator")
    if isinstance(sec, dict):
        g = sec.get("gate")
        if isinstance(g, str) and g.lower() in MODES:
            mode = g.lower()
        t = sec.get("top_models")
        if isinstance(t, list) and t and all(isinstance(x, str) for x in t):
            tops = list(t)
    return mode, tops


def is_top(model: str, patterns: list[str]) -> bool:
    for p in patterns:
        try:
            if re.search(p, model):
                return True
        except re.error:
            continue
    return False


# --- which harness, which model, which session ----------------------------------------------------------

def harness_of(payload: dict) -> str:
    tp = str(payload.get("transcript_path") or "")
    if "turn_id" in payload or "/.codex/" in tp or os.path.basename(tp).startswith("rollout-"):
        return "codex"
    return "claude"


def _tail_lines(path: str, nbytes: int = TAIL_BYTES) -> list[str]:
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - nbytes))
        raw = f.read()
        cut = size > nbytes
    lines = raw.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if cut and lines else lines


def _records(lines: list[str]):
    for line in reversed(lines):
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            yield rec


def claude_model(path: str) -> tuple[str, bool]:
    """(model of the last assistant record, whether that record is a sub-agent's)."""
    for rec in _records(_tail_lines(path)):
        msg = rec.get("message")
        if rec.get("type") == "assistant" and isinstance(msg, dict):
            m = msg.get("model")
            if isinstance(m, str) and m and not m.startswith("<"):
                return m, bool(rec.get("isSidechain"))
    return "", False


def find_rollout(session_id: str, environ=os.environ) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]{8,}", session_id or ""):
        return ""
    root = pathlib.Path(environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")) / "sessions"
    hits = sorted(root.glob(f"*/*/*/rollout-*{session_id}.jsonl"))
    return str(hits[-1]) if hits else ""


def codex_rollout_info(path: str) -> tuple[str, bool]:
    """(latest turn_context model, whether the first record says this thread is a sub-agent)."""
    sub = False
    with open(path, "rb") as f:
        first = f.readline(1 << 20).decode("utf-8", errors="replace")
    try:
        meta = json.loads(first)
        p = meta.get("payload") if isinstance(meta, dict) else None
        if isinstance(p, dict):
            src = p.get("source")
            sub = p.get("thread_source") == "subagent" or (isinstance(src, dict) and "subagent" in src)
    except ValueError:
        pass
    model = ""
    for rec in _records(_tail_lines(path)):
        p = rec.get("payload")
        if rec.get("type") == "turn_context" and isinstance(p, dict) and isinstance(p.get("model"), str):
            model = p["model"]
            break
    return model, sub


def session_model(payload: dict, harness: str, environ=os.environ) -> tuple[str, bool]:
    """(model id or "", is_subagent). An unknown model is "" and is never gated."""
    model = payload.get("model") if isinstance(payload.get("model"), str) else ""
    tp = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else ""
    if harness == "claude":
        sub = bool(payload.get("agent_id")) or "/subagents/" in tp
        if tp and (not model or not sub):
            m, side = claude_model(tp)
            model, sub = model or m, sub or side
        return model, sub
    if not tp:
        tp = find_rollout(str(payload.get("session_id") or ""), environ)
    sub = False
    if tp:
        m, sub = codex_rollout_info(tp)
        model = model or m
    return model, sub


# --- which commands are worker commands --------------------------------------------------------------------

def _first_arg(args: list[str], value_opts: set[str]) -> tuple[str, list[str]]:
    """The first non-option word, skipping options and the values of those that take one."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in value_opts:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return "", []


def _name(w: str) -> str:
    return os.path.basename(w)


_NESTED_REASON: list[str] = []


def _nested(result: tuple[str, str]) -> str:
    """The head of a script run by `bash -c` / `eval`; its TEYLA_ORCH_OK reason is kept for classify()."""
    if result[0] and result[1]:
        _NESTED_REASON.append(result[1])
    return result[0]


def worker_head(words: list[str], depth: int = 0) -> str:
    """"git commit" style head when `words` (already past wrappers) starts a worker command, else ""."""
    if not words or depth > 4:
        return ""
    exe, args = _name(words[0]), words[1:]
    low = [a.lower() for a in args]
    if exe == "xcrun" and args:
        return worker_head(args, depth + 1)
    if exe == "xcodebuild":
        return "xcodebuild" if not (set(low) & XCODE_READONLY) else ""
    if exe in ("swift", "cargo"):
        before = args[:args.index("--")] if "--" in args else args
        for a in before:
            if a in ("build", "test"):
                return f"{exe} {a}"
        return ""
    if exe == "simctl":
        sub, _ = _first_arg(args, set())
        return f"simctl {sub}" if sub in SIMCTL_WORK else ""
    if exe == "gradlew" or exe == "gradle":
        return exe if any(not a.startswith("-") for a in args) else ""
    if exe in NPM_RUNNERS:
        sub, rest = _first_arg(args, NPM_VALUE_OPTS)
        if sub in ("run", "run-script") and rest:
            sub = _first_arg(rest, NPM_VALUE_OPTS)[0]
        return f"{exe} {sub}" if re.match(r"(build|test)\b", sub) else ""
    if exe in ("pytest", "py.test"):
        return "pytest"
    if exe in ("python", "python3") and args[:2] == ["-m", "pytest"]:
        return "pytest"
    if exe == "uv":
        sub, rest = _first_arg(args, {"--project", "--directory", "--with", "-p", "--python"})
        if sub == "run":
            inner, _ = _first_arg(rest, {"--project", "--directory", "--with", "-p", "--python"})
            if _name(inner) == "pytest" or (rest and "pytest" in rest[:3]):
                return "uv run pytest"
        return ""
    if exe == "check.sh":
        return "check.sh"
    if exe == "git":
        sub, _ = _first_arg(args, GIT_VALUE_OPTS)
        return f"git {sub}" if sub in GIT_WORK else ""
    if exe == "gh":
        sub, rest = _first_arg(args, GH_VALUE_OPTS)
        act, _ = _first_arg(rest, GH_VALUE_OPTS)
        return f"gh {sub} {act}" if sub == "pr" and act in ("create", "merge") else ""
    if exe == "testflight":
        return "testflight"
    if exe in ("codex-review", "claude-review"):
        return exe
    if exe in ("sh", "bash", "zsh", "dash", "ksh"):
        for i, a in enumerate(args):
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and i + 1 < len(args):
                return _nested(classify(args[i + 1], depth + 1))
        return ""
    if exe == "eval":
        return _nested(classify(" ".join(args), depth + 1))
    return ""


def classify(command: str, depth: int = 0) -> tuple[str, str]:
    """(worker head or "", the TEYLA_ORCH_OK reason found as a leading assignment word, else "")."""
    from . import leak_guard as lg
    reason = ""
    for cmd in lg.lex(command):
        words = list(cmd.words)
        if not words:
            continue
        i, assigns, _cd, split = lg._normalize_ex(words)
        if split is not None:  # `env -S "..."` splits into more words; treat the rest as a script
            head = classify(split[3], depth + 1)[0]
        else:
            head = worker_head(words[i:], depth)
        if head:
            if _NESTED_REASON:
                reason = _NESTED_REASON.pop()
                _NESTED_REASON.clear()
            for a in assigns:
                if a.startswith("TEYLA_ORCH_OK="):
                    reason = a.split("=", 1)[1].strip("'\"") or "override"
            return head, reason
    return "", reason


# --- the decision --------------------------------------------------------------------------------------------

def command_of(tool_input: dict) -> str:
    cmd = tool_input.get("command")
    if isinstance(cmd, list):  # Codex's shell tool may send ["bash", "-lc", "..."]
        parts = [str(x) for x in cmd]
        if len(parts) >= 3 and _name(parts[0]) in ("sh", "bash", "zsh", "dash", "ksh") and parts[1].lstrip("-").endswith("c"):
            return parts[2]
        return " ".join(parts)
    return cmd if isinstance(cmd, str) else ""


def decide(payload: dict, environ=os.environ) -> str | None:
    """The refusal text, or None to allow. Rows are logged here."""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return None
    command = command_of(ti)
    if not command:
        return None
    mode, tops = load_config(environ)
    if mode == "off":
        return None
    head, lead_reason = classify(command)
    if not head:
        return None
    harness = harness_of(payload)
    model, sub = session_model(payload, harness, environ)
    if sub or not model or not is_top(model, tops):
        return None
    reason = (environ.get("TEYLA_ORCH_OK") or "").strip() or lead_reason
    if reason:
        log_row("override", harness, model, head, reason, environ)
        return None
    if mode == "warn":
        log_row("warn", harness, model, head, "", environ)
        print(f"teyla orchestrator gate (warn): {model} is an orchestrator; `{head}` belongs to a worker. {DELEGATE}",
              file=sys.stderr)
        return None
    log_row("refuse", harness, model, head, "", environ)
    return (f"teyla orchestrator gate: {model} only orchestrates; `{head}` is worker work. {DELEGATE} "
            f"Once, on the record: TEYLA_ORCH_OK=\"<reason>\" <command>.")


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return 0
        text = decide(payload, os.environ)
    except Exception as e:  # fail open, on the record
        log_row("error", "", "", type(e).__name__, str(e)[:100])
        return 0
    if text:
        print(text, file=sys.stderr)
        return 2
    return 0


def monitor_line(days: int = 7, environ=os.environ, now: dt.datetime | None = None) -> str:
    """One line for `teyla monitor`: gate rows of the last `days` days, or "" when there are none."""
    p = home_dir(environ) / LOG_NAME
    try:
        rows = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    cutoff = ((now or dt.datetime.now()) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    counts: dict[str, int] = {}
    for r in rows:
        f = r.split("\t")
        if len(f) >= 2 and f[0] >= cutoff:
            counts[f[1]] = counts.get(f[1], 0) + 1
    if not counts:
        return ""
    parts = ", ".join(f"{counts[k]} {k}" for k in ("refuse", "warn", "override", "error") if k in counts)
    return f"Orchestrator gate, last {days} days: {parts}.\n"


if __name__ == "__main__":
    sys.exit(main())
