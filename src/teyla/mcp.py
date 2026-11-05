"""teyla mcp: a Model Context Protocol server over stdio, so any MCP client can ask Teyla.

    teyla mcp                run the server (newline-delimited JSON-RPC 2.0 on stdin/stdout; logs on stderr)
    teyla mcp --list-tools   print the tool names with one line each, then exit

Six tools, each one a call of Teyla's own CLI in a child process, so the server holds no logic of its own and
opens no socket. Five only read (asks, intent, load, routines, monitor); `teyla_answer` types the owner's answer
into the local session that asked, as `teyla answer` does. Words that change state (`asks done`, `intent clean`,
`--record`, `--issues`, `--share`) are not reachable from here. Standard library only: the protocol is
implemented by hand, in the 2024-11-05, 2025-03-26 and 2025-06-18 revisions of the spec.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys

from . import __version__

SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 100_000          # characters returned to the client; the rest is cut with a note
MAX_ARG = 20_000            # longest string argument accepted

# JSON-RPC error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _tool(name, title, description, props, required, argv, timeout, *, read_only, open_world=False,
          idempotent=None):
    return {
        "name": name, "title": title, "description": description, "argv": argv, "timeout": timeout,
        "inputSchema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
        "annotations": {"title": title, "readOnlyHint": read_only, "destructiveHint": False,
                        "idempotentHint": read_only if idempotent is None else idempotent,
                        "openWorldHint": open_world},
    }


def _days(what):
    return {"type": "integer", "minimum": 1, "maximum": 3650, "description": what}


# argv builders: (arguments) -> list of CLI words after `teyla`. Strings are separate argv items, never a shell line.

def _argv_asks(a):
    out = ["asks", "--json"]
    if "days" in a:
        out += ["--days", str(a["days"])]
    if a.get("product"):
        out.append("--product=" + a["product"])
    if a.get("all"):
        out.append("--all")
    return out


def _argv_answer(a):
    out = ["answer", "--json"]
    if a.get("dry"):
        out.append("--dry")
    return out + ["--", a["id"], a["text"]]       # after "--" a text that starts with "-" stays a word


def _argv_intent(a):
    out = ["intent", "--json"]
    if "days" in a:
        out += ["--days", str(a["days"])]
    if a.get("grep"):
        out.append("--grep=" + a["grep"])
    if a.get("product"):
        out.append(a["product"])
    return out


def _argv_routines(a):
    return ["routines", "--json"] + list(a.get("paths") or [])


def _argv_monitor(a):
    out = ["monitor", "--json", "--no-mark-seen"]   # an agent's call must not hide A10 from the owner
    if "days" in a:
        out += ["--days", str(a["days"])]
    if a.get("project"):
        out.append("--project=" + a["project"])
    return out


TOOLS = [
    _tool("teyla_asks", "Open questions waiting on you",
          "The questions the owner's AI agent sessions (Claude Code, Codex) have left waiting, newest first, each with "
          "an id, the product, the session and the question text. Read-only.",
          {"days": _days("Window in days (default 21)."),
           "product": {"type": "string", "description": "Only this product (its registry id)."},
           "all": {"type": "boolean", "description": "Also list closed and hidden questions, and those of parked products."}},
          [], _argv_asks, 60, read_only=True),
    _tool("teyla_answer", "Answer a waiting question",
          "Delivers the owner's answer to the local Claude Code or Codex session that asked (by resuming it). "
          "The text is typed into that session as the owner's own answer, exactly as given. "
          "With dry=true it prints the commands that would run and runs none.",
          {"id": {"type": "string", "minLength": 1, "description": "The id of a waiting question, or a prefix of it, as teyla_asks lists it."},
           "text": {"type": "string", "minLength": 1, "description": "The answer text, delivered as given."},
           "dry": {"type": "boolean", "description": "When true, prints the commands that would run and runs none."}},
          ["id", "text"], _argv_answer, 300, read_only=False, idempotent=False),
    _tool("teyla_intent", "The owner's own words for a product",
          "The long prompts the owner wrote for a product, stored verbatim, newest last. Without a product, one line "
          "per product. Read-only.",
          {"product": {"type": "string", "description": "The product name; without it the tool lists every product."},
           "days": _days("Only the last N days."),
           "grep": {"type": "string", "description": "Only entries containing this text (case-insensitive)."}},
          [], _argv_intent, 60, read_only=True),
    _tool("teyla_load", "Machine load verdict",
          "Whether this Mac has room for heavy work now (a build, a simulator boot, a headless agent): OK, BUSY or "
          "CRITICAL, with the numbers (memory, swap, load, simulators, builds). Read-only.",
          {}, [], lambda a: ["load", "--json"], 30, read_only=True),
    _tool("teyla_routines", "Routine health",
          "Whether each product's scheduled routines ran, and the manual checks in its teyla.toml: loaded, last run, "
          "stale or broken. May query GitHub for workflow status through the owner's `gh` login. Read-only; opens no issues.",
          {"paths": {"type": "array", "items": {"type": "string", "minLength": 1},
                     "description": "Repo directories or teyla.toml files; without it the tool covers every product on this machine."}},
          [], _argv_routines, 120, read_only=True, open_world=True),
    _tool("teyla_monitor", "AI session usage summary",
          "How the owner's AI coding sessions were used: tokens, models, cost at list price, corrections and the "
          "findings with their evidence. Local logs only. Read-only: it does not mark any finding as seen.",
          {"days": _days("Report window in days (default: all local history)."),
           "project": {"type": "string", "description": "Only sessions whose project or directory contains this text."}},
          [], _argv_monitor, 180, read_only=True),
]
BY_NAME = {t["name"]: t for t in TOOLS}
SUMMARY = {   # for --list-tools
    "teyla_asks": "questions your agent sessions are waiting on",
    "teyla_answer": "send your answer to the session that asked, as your own words",
    "teyla_intent": "your own words for a product, verbatim",
    "teyla_load": "can this Mac take heavy work now: OK, BUSY or CRITICAL",
    "teyla_routines": "whether each product's scheduled routines and checks ran",
    "teyla_monitor": "AI session usage: tokens, models, cost, corrections",
}
# Positional words must not look like options; flag values are glued with "=" so they can start with "-".
INTENT_WORDS = {"capture", "backfill", "path", "cover", "clean"}     # `teyla intent <word>` is not a product
POSITIONAL = {("teyla_answer", "id"), ("teyla_intent", "product")}


def log(msg: str) -> None:
    print(f"teyla mcp: {msg}", file=sys.stderr, flush=True)


def list_tools() -> list[dict]:
    """tools/list entries: the public fields only."""
    return [{k: t[k] for k in ("name", "title", "description", "inputSchema", "annotations")} for t in TOOLS]


# --- running Teyla ---------------------------------------------------------------------------

def run_teyla(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run `python -m teyla <argv>` and return (exit code, stdout, stderr). Raises subprocess.TimeoutExpired.
    The one place a child process starts; tests replace it. stdin is closed so the child never reads the protocol."""
    p = subprocess.Popen([sys.executable, "-m", "teyla", *argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)     # the command's own children (claude, gh) go with it
        except OSError:
            p.kill()
        p.communicate()
        raise
    return p.returncode, out, err


def _cut(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    return text[:MAX_TEXT] + f"\n\n[output cut: {len(text) - MAX_TEXT} more characters; the days and product arguments narrow the query]"


def _result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": _cut(text) or "(no output)"}], "isError": is_error}


# What the monitor report leaves out of the MCP answer: each finding's `action` is one imperative sentence written for
# the owner at a terminal. The answer keeps id, severity, title and evidence and says where the sentences are.
MONITOR_OMITTED = {"findings[].action": "one suggested change per finding id, printed by `teyla monitor` in a terminal"}


def _monitor_as_data(out: str) -> str:
    report = json.loads(out)
    for f in report.get("findings") or []:
        if isinstance(f, dict):
            f.pop("action", None)
    report["omitted"] = MONITOR_OMITTED
    return json.dumps(report, indent=1, ensure_ascii=False)


AS_DATA = {"teyla_monitor": _monitor_as_data}     # tool name -> answer filter; the other tools print facts only


def call_tool(name: str, arguments: dict) -> dict:
    tool = BY_NAME[name]
    argv = tool["argv"](arguments)
    try:
        rc, out, err = run_teyla(argv, tool["timeout"])
    except subprocess.TimeoutExpired:
        return _result(f"teyla {argv[0]} timed out after {tool['timeout']} seconds and was stopped.", True)
    except OSError as e:
        return _result(f"could not start teyla {argv[0]}: {e}", True)
    if rc != 0:
        body = "\n".join(s.strip() for s in (err, out) if s.strip())
        return _result(f"teyla {argv[0]} exited with status {rc}.\n{body}".rstrip(), True)
    if name in AS_DATA:
        try:
            out = AS_DATA[name](out)
        except (ValueError, AttributeError):
            return _result(f"teyla {argv[0]} printed output that is not the expected JSON report.", True)
    return _result(out, False)


# --- validation ------------------------------------------------------------------------------

class ParamError(Exception):
    pass


def _check(name: str, key: str, spec: dict, value) -> None:
    t = spec["type"]
    where = f"{name}.{key}"
    if t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParamError(f"{where} is not an integer")
        if not spec.get("minimum", value) <= value <= spec.get("maximum", value):
            raise ParamError(f"{where} takes values from {spec['minimum']} to {spec['maximum']}")
    elif t == "boolean":
        if not isinstance(value, bool):
            raise ParamError(f"{where} is not a boolean")
    elif t == "string":
        if not isinstance(value, str):
            raise ParamError(f"{where} is not a string")
        if spec.get("minLength") and not value.strip():
            raise ParamError(f"{where} is empty")
        if len(value) > MAX_ARG or "\0" in value:
            raise ParamError(f"{where} is too long or holds a NUL character")
        if (name, key) in POSITIONAL and value.startswith("-"):
            raise ParamError(f"{where} starts with '-', which is not accepted")
        if (name, key) == ("teyla_intent", "product") and value in INTENT_WORDS:
            raise ParamError(f"{where} is a reserved word of the intent command")
    elif t == "array":
        if not isinstance(value, list) or len(value) > 50:
            raise ParamError(f"{where} is not an array of at most 50 items")
        for i, v in enumerate(value):
            _check(name, f"{key}[{i}]", spec["items"], v)
            if v.startswith("-"):
                raise ParamError(f"{where}[{i}] starts with '-', which is not accepted")


def validate(name: str, arguments) -> dict:
    schema = BY_NAME[name]["inputSchema"]
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ParamError("arguments is not an object")
    for k in arguments:
        if k not in schema["properties"]:
            raise ParamError(f"unknown argument {k!r} for {name}")
    for k in schema["required"]:
        if k not in arguments:
            raise ParamError(f"{name} requires {k!r}")
    for k, v in arguments.items():
        _check(name, k, schema["properties"][k], v)
    return arguments


# --- the protocol ----------------------------------------------------------------------------

def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(msg) -> dict | None:
    """One JSON-RPC message in, the response out (None for a notification or a client's reply)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(msg.get("id") if isinstance(msg, dict) and isinstance(msg.get("id"), (str, int)) else None,
                      INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    if "method" not in msg:
        return None                       # a response to a request we never send
    method, params = msg["method"], msg.get("params")
    id_ = msg.get("id")
    if "id" not in msg:
        return None                       # a notification (notifications/initialized, /cancelled): no reply
    if not isinstance(method, str) or isinstance(id_, bool) or not isinstance(id_, (str, int)):
        return _error(None, INVALID_REQUEST, "method is not a string, or id is neither a string nor an integer")
    if params is not None and not isinstance(params, dict):
        return _error(id_, INVALID_PARAMS, "params is not an object")
    params = params or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": asked if asked in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "teyla", "version": __version__}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": list_tools()}}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in BY_NAME:
            return _error(id_, INVALID_PARAMS, f"unknown tool {name!r}" if isinstance(name, str) else "name is not a string")
        try:
            args = validate(name, params.get("arguments"))
        except ParamError as e:
            return _error(id_, INVALID_PARAMS, str(e))
        try:
            return {"jsonrpc": "2.0", "id": id_, "result": call_tool(name, args)}
        except Exception as e:  # noqa: BLE001 — a bug in one call must not end the session
            log(f"{name} failed: {type(e).__name__}: {e}")
            return {"jsonrpc": "2.0", "id": id_, "result": _result(f"{name} failed: {type(e).__name__}: {e}", True)}
    return _error(id_, METHOD_NOT_FOUND, f"method not found: {method}")


def handle_line(line: str) -> str | None:
    """One input line in, the output line out (None: nothing to send). Never raises."""
    try:
        msg = json.loads(line)
    except ValueError:
        return json.dumps(_error(None, PARSE_ERROR, "parse error"))
    try:
        if isinstance(msg, list):          # a batch (2025-03-26 allows it)
            if not msg:
                return json.dumps(_error(None, INVALID_REQUEST, "empty batch"))
            replies = [r for r in (handle(m) for m in msg) if r is not None]
            return json.dumps(replies) if replies else None
        reply = handle(msg)
    except Exception as e:  # noqa: BLE001
        log(f"internal error: {type(e).__name__}: {e}")
        return json.dumps(_error(None, -32603, "internal error"))
    return json.dumps(reply) if reply is not None else None


def serve(stdin, stdout) -> int:
    """The loop: read a line, answer it, until end of input."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        reply = handle_line(line)
        if reply is not None:
            stdout.write(reply + "\n")
            stdout.flush()
    return 0


def cmd_mcp(args) -> int:
    if args.list_tools:
        width = max(len(t["name"]) for t in TOOLS)
        for t in TOOLS:
            print(f"{t['name']:{width}}  {SUMMARY[t['name']]}")
        return 0
    for s in (sys.stdin, sys.stdout):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    log(f"{__version__} ready on stdio")
    try:
        return serve(sys.stdin, sys.stdout)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 0


def register(sp):
    q = sp.add_parser("mcp", help="run Teyla as an MCP server on stdio (asks, answer, intent, load, routines, monitor)")
    q.set_defaults(fn=cmd_mcp)
    q.add_argument("--list-tools", action="store_true", help="print the tool names with one line each, then exit")
    from . import mcp_probe
    mcp_probe.register(q)
    return q
