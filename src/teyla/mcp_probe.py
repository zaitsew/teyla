"""`teyla mcp probe` — the deterministic checks any Streamable HTTP MCP server must pass.

    teyla mcp probe <url> [--token T] [--write TOOL] [--budget N] [--seconds S] [--json]
                    [--repo PATH] [--i-own-this] [--allow-network]

Docs: docs/MCP-SECURITY.md (SHIELD SH7, SH13, SH14). The probe speaks JSON-RPC 2.0 over POST
(initialize, notifications/initialized, tools/list, tools/call) with `urllib` and nothing else.
It reads `application/json` answers and the first `data:` line of a `text/event-stream` answer,
and carries `Mcp-Session-Id` when the server sets it. It never follows a redirect.

One line per check, `OK|FIX|SKIP  <name>  <evidence>`; a FIX line ends with the fix:

    url-key        the URL path or query holds something that looks like a key
    auth-required  initialize and tools/list without Authorization answer 401 or 403
    tool-pinning   tools/list in two sessions gives the same sha256 of names, descriptions, schemas
    schema-error   a wrong-type argument is a JSON-RPC -32602 or a 4xx, never a 500 or a success
    oversize       a 1 MB string argument is refused (413, 4xx or an error), never a success or a 500
    ssrf-inputs    a tool with a url/uri/href string property refuses every attacker-url case
    canary         an encoded canary sent to one tool appears in no other tool's answer or in tools/list
    rate-limit     rapid tools/list calls meet a 429 or a Retry-After within the budget

Safety: it runs only against a host that the current repo names (`[security]` `mcp.url` or the `[privacy]`
table in teyla.toml, or the Host column of docs/PRIVACY.md), or with `--i-own-this`: never probe a
third party. It has a request budget (default 60) and a time budget (default 120 s), both above zero.
It makes no `tools/call` on a tool whose name or description reads like a write
(create, delete, send, post, update, write, pay, and a few more) unless `--write TOOL` names that tool.
Safe mode refuses it unless `--allow-network` is given. The token goes in an Authorization header, over
https or to a loopback host only, and is never printed.

Exit 0: every check OK or SKIP. 1: at least one FIX. 2: refused (ownership, budget, safe mode, a token
over plain http) or the server could not be initialized.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import pathlib
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__, net

DEFAULT_BUDGET = 60
DEFAULT_SECONDS = 120.0
REQUEST_TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 1024 * 1024
OVERSIZE_BYTES = 1024 * 1024
MIN_RATE_LIMIT_BUDGET = 20
PROTOCOL_VERSION = "2025-06-18"
LIST_PAGES = 20
TOKEN_RE = re.compile(r"[\x21-\x7e]+")
USER_AGENT = f"teyla-mcp-probe/{__version__}"

OK, FIX, SKIP = "OK", "FIX", "SKIP"

# A tool is a write-like when a word of its name (split on camelCase, underscore and hyphen) or of its description is
# one of these verbs, in any common form. Deliberately wide; a tool with no description and no read verb in its name
# is write-like too: when in doubt the probe does not call it.
_WRITE_VERBS = (
    "add create write send post delete remove update publish grant share pay save upload modify set insert put patch "
    "drop destroy execute exec run transfer invite approve revoke submit commit reply forward store keep remember "
    "enable disable install uninstall rename move merge push edit change import assign charge buy cancel reset clear "
    "erase purge wipe deploy kill sign withdraw deposit mint email notify overwrite append attach").split()
_READ_VERBS = set("get list search read find lookup fetch query show describe count check view browse inspect "
                  "status info".split())


def _forms(v: str) -> set[str]:
    out = {v, v + "s", v + "es", v + "ed", v + "d", v + "ing", v + v[-1] + "ing", v + v[-1] + "ed"}
    if v.endswith("e"):
        out.add(v[:-1] + "ing")
    if v.endswith("y"):
        out |= {v[:-1] + "ies", v[:-1] + "ied"}
    return out


WRITE_WORDS = set().union(*(_forms(v) for v in _WRITE_VERBS))


def words_of(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", text.lower()) if w]


URL_PROP_RE = re.compile(r"(?i)(url|uri|href)")
TEXT_PROP_RE = re.compile(r"(?i)^(text|query|q|note|content|message|body|input|title|description|prompt|comment|summary)$")
REFUSAL_RE = re.compile(r"(?i)(refus|block|denied|not allowed|forbidden|disallow|invalid|private address|unsupported|"
                        r"outside the allowed|not permitted)")
KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
KEY_QUERY_RE = re.compile(r"(?i)(?:^|[?&;_-])(?:api[_-]?)?(?:key|token|secret)=")

AUTH_MSG_RE = re.compile(r"(?i)(unauthori|authenti|forbidden|credential|token|permission|denied|not allowed|login|sign in)")

FIXES = {
    "url-key": "move the key into an Authorization header and rotate the one in the URL; the URL is the secret, "
               "so it lands in access logs and referrers",
    "auth-required": "require a bearer token or OAuth on every MCP request, initialize included, and answer 401 "
                     "with WWW-Authenticate",
    "tool-pinning": "freeze tool names, descriptions and schemas per release; a changed description needs a new "
                    "version and a client re-approval (rug-pull)",
    "schema-error": "validate arguments against the input schema and answer JSON-RPC -32602; never a 500 or a "
                    "stack trace",
    "oversize": "cap the request body (413) and the length of each argument",
    "ssrf-inputs": "resolve the host and refuse loopback, private, link-local, metadata addresses and non-http(s) "
                   "schemes before fetching; pin the resolved address",
    "canary": "keep one tool's input out of other tools' answers and the tool list; treat stored text as data, "
              "scoped per user",
    "rate-limit": "add per-credential and per-address limits and answer 429 with Retry-After",
}


class Refused(Exception):
    """The probe will not run (exit 2)."""


class BudgetSpent(Exception):
    """The request budget or the time budget is used up."""

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


@dataclass
class Check:
    name: str
    status: str
    evidence: str
    fix: str = ""
    inconclusive: bool = False      # a SKIP that leaves the answer open: the run exits 2, never 0

    def line(self) -> str:
        tail = f"; fix: {self.fix}" if self.status == FIX and self.fix else ""
        return f"{self.status:<4}  {self.name:<13}  {self.evidence}{tail}"

    def as_dict(self) -> dict:
        d = {"name": self.name, "status": self.status, "evidence": self.evidence}
        if self.status == FIX:
            d["fix"] = self.fix
        if self.inconclusive:
            d["inconclusive"] = True
        return d


@dataclass
class Resp:
    status: int                   # 0: no HTTP answer (connection error, timeout)
    headers: dict = field(default_factory=dict)
    body: object = None           # the parsed JSON-RPC message, when there is one
    text: str = ""
    error: str = ""

    @property
    def rpc_error(self) -> dict | None:
        return self.body.get("error") if isinstance(self.body, dict) and isinstance(self.body.get("error"), dict) else None

    @property
    def result(self):
        return self.body.get("result") if isinstance(self.body, dict) else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # a 3xx comes back as an HTTPError; nothing is followed
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


# --- corpus ---------------------------------------------------------------------------------------

def corpus_path() -> pathlib.Path:
    import teyla
    return teyla.templates_dir() / "security" / "injection_cases.json"


def load_corpus(path: pathlib.Path | None = None) -> dict:
    return json.loads((path or corpus_path()).read_text(encoding="utf-8"))


def cases_of(corpus: dict, family: str) -> list[dict]:
    return [c for c in corpus.get("cases", []) if c.get("family") == family]


def canary_variants(token: str) -> list[str]:
    """The token as it may come back: plain, base64, percent-encoded, hex, reversed, and with the zero-width spaces gone."""
    import base64
    pct = "".join("%%%02X" % b for b in token.encode())
    return [token, base64.b64encode(token.encode()).decode().rstrip("="), pct, pct.lower(), token.encode().hex(),
            token[::-1]]


def strip_invisible(text: str) -> str:
    return re.sub("[​‌‍⁠﻿]", "", text)


# --- the repo's own hosts (SHIELD §8) -------------------------------------------------------------

_HOST_TOKEN = re.compile(r"(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}|localhost|\d{1,3}(?:\.\d{1,3}){3}")
# A file name is not a host: `privacy.md`, `teyla.toml`. Applies to the Host column only.
_FILE_TLDS = set("md toml json py ts js swift txt yml yaml sh html css kt plist lock cfg ini png jpg svg pdf rs go rb "
                 "mjs cjs tsx jsx csv log".split())


def _host_of(token: str) -> str:
    token = token.strip()
    if "://" in token:
        return (urllib.parse.urlparse(token).hostname or "").lower()
    return token.split("/")[0].split(":")[0].lower()


def host_tokens(cell: str) -> set[str]:
    """Hosts in one cell of the Host column: whole tokens only, so prose and file names never count."""
    out = set()
    for tok in re.split(r"[\s,;]+", cell.replace("`", " ")):
        tok = tok.strip("()[]<>\"'.,;:")
        if not tok or ("://" not in tok and "/" in tok):
            continue
        h = _host_of(tok)
        if _HOST_TOKEN.fullmatch(h) and h.rsplit(".", 1)[-1] not in _FILE_TLDS:
            out.add(h)
    return out


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def find_repo(start: pathlib.Path) -> pathlib.Path:
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / "teyla.toml").exists() or (d / ".git").exists():
            return d
    return start


def read_manifest(repo: pathlib.Path) -> dict:
    p = repo / "teyla.toml"
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def owned_hosts(repo: pathlib.Path) -> set[str]:
    """Hosts the repo names, from two places only: `[security] mcp.url` and `[privacy] hosts` in teyla.toml, and the
    Host column of a markdown table row in docs/PRIVACY.md. Never from prose."""
    hosts: set[str] = set()
    data = read_manifest(repo)
    mcp = (data.get("security") or {}).get("mcp")
    if isinstance(mcp, dict):
        for key in ("url", "urls"):
            hosts |= {_host_of(x) for x in _strings(mcp.get(key))}
    privacy = data.get("privacy")
    if isinstance(privacy, dict):
        hosts |= {_host_of(x) for x in _strings(privacy.get("hosts"))}
    try:
        lines = (repo / "docs" / "PRIVACY.md").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    col = None
    for ln in lines:
        if not ln.lstrip().startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if any(c.lower() == "host" for c in cells):
            col = [c.lower() for c in cells].index("host")
        elif col is not None and col < len(cells) and not set(cells[col]) <= set("-: "):
            hosts |= host_tokens(cells[col])
    hosts.discard("")
    return hosts


def host_is_owned(host: str, hosts: set[str]) -> bool:
    host = host.lower()
    return any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in hosts)


# --- the wire -------------------------------------------------------------------------------------

class Client:
    """Every request goes through `post`, which counts it against both budgets."""

    def __init__(self, url: str, token: str | None, budget: int, seconds: float):
        self.url, self.token, self.budget = url, token, budget
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.used = 0
        self._id = 0

    def remaining(self) -> int:
        return self.budget - self.used

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def next_id(self) -> int:
        self._id += 1
        return self._id

    def scrub(self, text: str) -> str:
        return scrub(text, self.token)

    def post(self, payload, headers: dict, *, authed: bool = True) -> Resp:
        if self.used >= self.budget:
            raise BudgetSpent(f"the request budget of {self.budget} is spent")
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise BudgetSpent("the time budget is spent")
        self.used += 1
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "User-Agent": USER_AGENT, **headers}
        if authed and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=raw, headers=h, method="POST")
        timeout = max(0.2, min(REQUEST_TIMEOUT_S, left))
        try:
            with _OPENER.open(req, timeout=timeout) as r:          # noqa: S310 (scheme checked in run())
                return _read(r.status, r, self.deadline)
        except urllib.error.HTTPError as e:
            return _read(e.code, e, self.deadline)
        except BudgetSpent:
            raise
        except Exception as e:                                      # noqa: BLE001 — never let an exception carry the token out
            return Resp(0, error=self.scrub(str(getattr(e, "reason", e)))[:120] or type(e).__name__)


def scrub(text: str, token: str | None) -> str:
    """Every printed string passes through here: the token, whole or in a line of it, becomes `<token>`."""
    if not token:
        return text
    for part in {token, *[p for p in re.split(r"[\s]+", token) if len(p) >= 4]}:
        text = text.replace(part, "<token>")
    return text


def _sock_of(r):
    for obj in (r, getattr(r, "fp", None)):
        try:
            return obj.fp.raw._sock
        except AttributeError:
            continue
    return None


def _read(status: int, r, deadline: float) -> Resp:
    """Read the answer in chunks against the total deadline, so a server that drips bytes cannot stall the probe."""
    headers = {k.lower(): v for k, v in r.headers.items()}
    sse = "text/event-stream" in headers.get("content-type", "").lower()
    sock, buf, text = _sock_of(r), b"", ""
    while len(buf) < MAX_RESPONSE_BYTES:
        left = deadline - time.monotonic()
        if left <= 0:
            raise BudgetSpent("the time budget is spent")
        if sock is not None:
            try:
                sock.settimeout(max(0.05, min(left, REQUEST_TIMEOUT_S)))
            except OSError:
                pass
        try:
            chunk = r.read1(65536)
        except TimeoutError:
            if time.monotonic() >= deadline:
                raise BudgetSpent("the time budget is spent")
            break
        except Exception:                                           # noqa: BLE001 — a cut connection ends the read
            break
        if not chunk:
            break
        buf += chunk
        if sse:
            for ln in buf.split(b"\n")[:-1]:
                if ln.strip().startswith(b"data:"):
                    text = ln.strip()[5:].decode("utf-8", "replace").strip()
                    break
            if text:
                break
    if not sse:
        text = buf.decode("utf-8", "replace")
    body = None
    if text.strip()[:1] in ("{", "["):
        try:
            body = json.loads(text)
        except ValueError:
            body = None
    if isinstance(body, list):
        body = next((m for m in body if isinstance(m, dict)), None)
    return Resp(status, headers, body, text)


class Session:
    def __init__(self, client: Client, authed: bool = True):
        self.c, self.authed = client, authed
        self.sid: str | None = None
        self.version = PROTOCOL_VERSION
        self.first: Resp | None = None
        self.truncated = False

    def _headers(self) -> dict:
        h = {"MCP-Protocol-Version": self.version}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        return h

    def rpc(self, method: str, params: dict | None = None) -> Resp:
        msg = {"jsonrpc": "2.0", "id": self.c.next_id(), "method": method}
        if params is not None:
            msg["params"] = params
        return self.c.post(msg, self._headers(), authed=self.authed)

    def open(self) -> Resp:
        """initialize, then notifications/initialized. Returns the initialize answer; ok() says whether it worked."""
        r = self.c.post({"jsonrpc": "2.0", "id": self.c.next_id(), "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "teyla-mcp-probe", "version": __version__}}}, {}, authed=self.authed)
        self.first = r
        if not self.ok(r):
            return r
        self.sid = r.headers.get("mcp-session-id")
        got = (r.result or {}).get("protocolVersion")
        if isinstance(got, str):
            self.version = got
        self.c.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, self._headers(), authed=self.authed)
        return r

    @staticmethod
    def ok(r: Resp) -> bool:
        return 200 <= r.status < 300 and isinstance(r.result, dict)

    def list_tools(self) -> tuple[list[dict] | None, Resp]:
        """All pages of tools/list (bounded by LIST_PAGES). `self.truncated` is True when a cursor was left over."""
        tools: list[dict] = []
        cursor = None
        r = Resp(0)
        self.truncated = False
        for page in range(LIST_PAGES):
            r = self.rpc("tools/list", {"cursor": cursor} if cursor else None)
            res = r.result
            if not (200 <= r.status < 300 and isinstance(res, dict) and isinstance(res.get("tools"), list)):
                self.truncated = bool(tools)
                return (tools or None), r
            tools += [t for t in res["tools"] if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = res.get("nextCursor")
            if not cursor:
                return tools, r
        self.truncated = True
        return tools, r

    def call(self, name: str, arguments) -> Resp:
        return self.rpc("tools/call", {"name": name, "arguments": arguments})


# --- schemas and tools ----------------------------------------------------------------------------

def tools_hash(tools: list[dict]) -> str:
    keep = sorted(({"name": t.get("name"), "description": t.get("description"), "inputSchema": t.get("inputSchema")}
                   for t in tools), key=lambda t: str(t["name"]))
    return hashlib.sha256(json.dumps(keep, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def is_write(tool: dict) -> bool:
    ann = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    if ann.get("destructiveHint"):
        return True
    name_words, desc = words_of(str(tool.get("name", ""))), str(tool.get("description") or "")
    if any(w in WRITE_WORDS for w in name_words + words_of(desc)):
        return True
    return not desc.strip() and not _READ_VERBS.intersection(name_words)       # no description, no read verb: doubt


def props_of(tool: dict) -> dict:
    s = tool.get("inputSchema")
    p = s.get("properties") if isinstance(s, dict) else None
    return p if isinstance(p, dict) else {}


def required_of(tool: dict) -> list[str]:
    s = tool.get("inputSchema")
    r = s.get("required") if isinstance(s, dict) else None
    return [x for x in r if isinstance(x, str)] if isinstance(r, list) else []


def valid_value(schema):
    schema = schema if isinstance(schema, dict) else {}
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    t = schema.get("type")
    t = t[0] if isinstance(t, list) and t else t
    if t == "string":
        return "https://example.test/" if schema.get("format") in ("uri", "url") else "x"
    return {"integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}.get(t, "x")


def wrong_value(schema):
    schema = schema if isinstance(schema, dict) else {}
    t = schema.get("type")
    t = t[0] if isinstance(t, list) and t else t
    return {"string": {"unexpected": True}, "integer": "not-a-number", "number": "not-a-number",
            "boolean": "not-a-boolean", "array": "not-an-array", "object": "not-an-object"}.get(t, {"unexpected": [1]})


def base_args(tool: dict) -> dict:
    props = props_of(tool)
    return {k: valid_value(props.get(k)) for k in required_of(tool)}


def string_props(tool: dict) -> list[str]:
    return [k for k, v in props_of(tool).items() if isinstance(v, dict) and v.get("type") == "string" and "enum" not in v]


def url_prop(tool: dict) -> str | None:
    for k in string_props(tool):
        v = props_of(tool)[k]
        if URL_PROP_RE.search(k) or v.get("format") in ("uri", "url"):
            return k
    return None


def text_prop(tool: dict) -> str | None:
    ps = [k for k in string_props(tool) if k != url_prop(tool)]
    return next((k for k in ps if TEXT_PROP_RE.match(k)), ps[0] if ps else None)


def judge(r: Resp) -> str:
    """error | server-error | success | none, for one tools/call answer."""
    if r.status == 0:
        return "none"
    if r.status >= 500:
        return "server-error"
    if r.status >= 400:
        return "error"
    err = r.rpc_error
    if err:
        return "server-error" if err.get("code") == -32603 else "error"
    res = r.result
    if isinstance(res, dict):
        return "error" if res.get("isError") else "success"
    return "none"


def _text_of(r: Resp) -> str:
    res = r.result if isinstance(r.result, dict) else {}
    parts = [c.get("text", "") for c in res.get("content", []) if isinstance(c, dict)] if isinstance(res.get("content"), list) else []
    return " ".join(parts) or r.text


# --- the checks -----------------------------------------------------------------------------------

class Probe:
    def __init__(self, client: Client, corpus: dict, *, write_tool: str | None, tier: str | None, own: bool):
        self.c, self.corpus, self.write_tool, self.tier, self.own = client, corpus, write_tool, tier, own
        self.checks: list[Check] = []
        self.session: Session | None = None
        self.tools: list[dict] | None = None
        self.hash1: str | None = None
        self.truncated = False
        self.cannot_initialize = ""

    def add(self, name: str, status: str, evidence: str, *, inconclusive: bool = False) -> Check:
        c = Check(name, status, evidence, FIXES.get(name, ""), inconclusive)
        self.checks.append(c)
        return c

    def callable_tools(self, named_first: bool = False) -> list[dict]:
        """Tools the probe may call: the read-only ones, plus the one `--write` names. That one goes first for the
        checks that exercise a single tool (schema-error, oversize) and last for the rest."""
        out = [t for t in (self.tools or []) if not is_write(t) or t["name"] == self.write_tool]
        out.sort(key=lambda t: (t["name"] != self.write_tool) if named_first else (t["name"] == self.write_tool))
        return out

    def guarded(self, name: str, fn) -> None:
        try:
            fn()
        except BudgetSpent as e:
            # Pinning and the canary need every answer: a budget that ends them early leaves the question open.
            self.add(name, SKIP, e.what, inconclusive=name in ("tool-pinning", "canary"))

    # url-key: no request
    def url_key(self) -> None:
        u = urllib.parse.urlparse(self.c.url)
        segs = [s for s in u.path.split("/") if KEY_SEGMENT_RE.match(s)]
        keyq = bool(KEY_QUERY_RE.search("?" + u.query)) if u.query else False
        if segs or keyq:
            what = (f"a path segment of {len(segs[0])} key-like characters" if segs else "a query parameter named like a key")
            self.add("url-key", FIX, f"the URL carries {what}")
        else:
            self.add("url-key", OK, "no key-like path segment or query parameter")

    @staticmethod
    def _refuses(r: Resp) -> bool:
        err = r.rpc_error or {}
        return r.status in (401, 403) or (err.get("code") in (-32001, -32000) and bool(AUTH_MSG_RE.search(str(err.get("message", "")))))

    @staticmethod
    def _reached_handler(r: Resp) -> str:
        """Why an anonymous answer shows the request got past authentication, or ''."""
        if r.status >= 500:
            return f"HTTP {r.status}"
        err = r.rpc_error
        return f"JSON-RPC error {err.get('code')}" if err else ""

    def auth_required(self) -> None:
        s = Session(self.c, authed=False)
        r = s.open()
        if self._refuses(r):
            self.add("auth-required", OK, f"initialize without Authorization answered {r.status}"
                     + ("" if r.status in (401, 403) else f" (JSON-RPC error {r.rpc_error.get('code')})"))
            return
        if r.status == 0:
            self.add("auth-required", SKIP, f"no answer to initialize ({r.error})")
            return
        why = self._reached_handler(r)
        if why:
            self.add("auth-required", FIX, f"anonymous request reached the handler: initialize gave {why}")
            return
        if not s.ok(r):
            self.add("auth-required", SKIP, f"initialize without Authorization answered {r.status} with no result")
            return
        tools, lr = s.list_tools()
        if self._refuses(lr):
            self.add("auth-required", OK, f"tools/list without Authorization answered {lr.status}"
                     + ("" if lr.status in (401, 403) else f" (JSON-RPC error {lr.rpc_error.get('code')})"))
        elif tools is not None:
            if self.tier == "owner" and self.own:
                self.add("auth-required", SKIP, f"tools/list without Authorization answered {lr.status} with {len(tools)} tool(s); "
                                                 "allowed: tier owner and --i-own-this")
            else:
                self.add("auth-required", FIX, f"tools/list without Authorization answered {lr.status} with {len(tools)} tool(s)")
        elif self._reached_handler(lr):
            self.add("auth-required", FIX, f"anonymous request reached the handler: tools/list gave {self._reached_handler(lr)}")
        else:
            self.add("auth-required", SKIP, f"tools/list without Authorization answered {lr.status} with no tool list")

    def open_main(self) -> bool:
        s = Session(self.c)
        r = s.open()
        if not s.ok(r):
            why = f"HTTP {r.status}" if r.status else f"no answer ({r.error})"
            hint = "; pass --token" if r.status in (401, 403) and not self.c.token else ""
            self.cannot_initialize = f"initialize failed: {why}{hint}"
            return False
        tools, lr = s.list_tools()
        self.session = s
        if tools is None:
            self.tools = None
            self.cannot_initialize = f"tools/list failed: HTTP {lr.status}"
            return False
        self.tools = tools
        self.truncated = s.truncated
        self.hash1 = tools_hash(tools)
        return True

    def tool_pinning(self) -> None:
        s2 = Session(self.c)
        r = s2.open()
        if not s2.ok(r):
            self.add("tool-pinning", SKIP, "the second session could not be opened")
            return
        tools2, _ = s2.list_tools()
        if tools2 is None:
            self.add("tool-pinning", SKIP, "tools/list failed in the second session")
            return
        if self.truncated or s2.truncated:
            self.add("tool-pinning", SKIP, f"the tool list is longer than {LIST_PAGES} pages, so it cannot be hashed whole",
                     inconclusive=True)
            return
        h2 = tools_hash(tools2)
        if h2 == self.hash1:
            self.add("tool-pinning", OK, f"sha256 {h2[:12]} in both sessions ({len(tools2)} tool(s))")
            return
        a = {t["name"]: t for t in self.tools or []}
        changed = sorted(n for n, t in {t["name"]: t for t in tools2}.items() if n not in a or tools_hash([t]) != tools_hash([a[n]]))
        gone = sorted(set(a) - {t["name"] for t in tools2})
        bits = []
        if changed:
            bits.append("changed or new: " + ", ".join(changed[:3]))
        if gone:
            bits.append("gone: " + ", ".join(gone[:3]))
        self.add("tool-pinning", FIX, f"rug-pull: sha256 {self.hash1[:12]} then {h2[:12]} ({'; '.join(bits)})")

    def schema_error(self) -> None:
        cand = self.callable_tools(named_first=True)
        if not cand:
            self.add("schema-error", SKIP, "no tool the probe may call (write-like tools need --write TOOL)")
            return
        tool = cand[0]
        props = props_of(tool)
        if props or required_of(tool):
            key = next((k for k in required_of(tool) if k in props), None) or next(iter(props), None) or required_of(tool)[0]
            args = {**base_args(tool), key: wrong_value(props.get(key))}
            how = f"{key} sent as the wrong type"
        else:
            args, how = "not-an-object", "arguments sent as a string"
        r = self.session.call(tool["name"], args)
        v = judge(r)
        code = (r.rpc_error or {}).get("code")
        if v == "server-error":
            self.add("schema-error", FIX, f"{tool['name']}: {how} gave {'HTTP ' + str(r.status) if r.status >= 500 else 'JSON-RPC error ' + str(code)}")
        elif v == "success":
            self.add("schema-error", FIX, f"{tool['name']}: {how} was accepted and returned a result")
        elif v == "none":
            self.add("schema-error", SKIP, f"{tool['name']}: no usable answer ({r.error or 'HTTP ' + str(r.status)})")
        else:
            got = f"JSON-RPC {code}" if code is not None else (f"HTTP {r.status}" if r.status >= 400 else "an isError result")
            self.add("schema-error", OK, f"{tool['name']}: {how} gave {got}")

    def oversize(self) -> None:
        cand = [t for t in self.callable_tools(named_first=True) if string_props(t)]
        if not cand:
            self.add("oversize", SKIP, "no callable tool has a string argument")
            return
        tool = cand[0]
        key = text_prop(tool) or string_props(tool)[0]
        r = self.session.call(tool["name"], {**base_args(tool), key: "A" * OVERSIZE_BYTES})
        v = judge(r)
        if r.status == 413:
            self.add("oversize", OK, f"{tool['name']}.{key}: 1 MB answered 413")
        elif v == "error":
            self.add("oversize", OK, f"{tool['name']}.{key}: 1 MB refused ({'HTTP ' + str(r.status) if r.status >= 400 else 'error result'})")
        elif r.status == 0:
            self.add("oversize", FIX, f"{tool['name']}.{key}: server crashed on oversized input (no answer: {r.error or 'connection ended'})")
        elif v == "server-error":
            self.add("oversize", FIX, f"{tool['name']}.{key}: 1 MB gave {'HTTP ' + str(r.status) if r.status >= 500 else 'an internal error'}")
        else:
            self.add("oversize", FIX, f"{tool['name']}.{key}: 1 MB was accepted and returned a result")

    def ssrf(self, cap: int) -> None:
        tools = [t for t in self.callable_tools() if url_prop(t)]
        if not tools:
            self.add("ssrf-inputs", SKIP, "no tool has a url, uri or href string property")
            return
        cases = cases_of(self.corpus, "attacker-url")
        per = max(1, cap // len(tools))
        sent, fetched = 0, []
        try:
            for t in tools:
                key = url_prop(t)
                for case in cases[:per]:
                    r = self.session.call(t["name"], {**base_args(t), key: case["input"]})
                    sent += 1
                    v = judge(r)
                    if v in ("server-error", "none") or (v == "success" and not REFUSAL_RE.search(_text_of(r))):
                        note = {"server-error": " (HTTP 5xx)", "none": f" (no explicit refusal: {r.error or 'no answer'})"}.get(v, "")
                        fetched.append(f"{t['name']} <- {case['id']}{note}")
        except BudgetSpent as e:
            if not sent:
                raise
            fetched_note = f" (stopped: {e.what})"
        else:
            fetched_note = ""
        if fetched:
            self.add("ssrf-inputs", FIX, f"{len(fetched)} of {sent} attacker URL(s) not refused: {', '.join(fetched[:3])}")
        else:
            self.add("ssrf-inputs", OK, f"{sent} attacker URL(s) refused across {len(tools)} tool(s){fetched_note}")

    def canary(self, cap: int) -> None:
        cases = cases_of(self.corpus, "encoded-canary")
        usable = [t for t in self.callable_tools() if text_prop(t)]
        sources = [t for t in usable if TEXT_PROP_RE.match(text_prop(t))][:3] or usable[:1]
        if not sources or not cases:
            self.add("canary", SKIP, "no callable tool has a free-text property" if not sources else "the corpus has no canary case")
            return
        per = max(1, (cap - 4) // len(sources))
        sent: dict[str, list[str]] = {}
        replies, stopped = [], ""
        try:
            for src in sources:
                for case in cases[:per]:
                    sent.setdefault(src["name"], []).append(case.get("canary") or f"CANARY-{case['id']}")
                    self.session.call(src["name"], {**base_args(src), text_prop(src): case["input"]})
            # Other tools first (a source tool echoing its own input is not a leak), the ones that need no argument before the rest.
            others = sorted((t for t in self.callable_tools() if t["name"] != self.write_tool),
                            key=lambda t: (t["name"] in sent, len(required_of(t))))
            for t in others[:3]:
                replies.append((t["name"], self.session.call(t["name"], base_args(t))))
            _, lr = self.session.list_tools()
            replies.append(("tools/list", lr))
        except BudgetSpent as e:
            stopped = e.what
        seen = []
        for where, r in replies:
            body = (r.text or "") + " " + _text_of(r)
            body += " " + strip_invisible(body)
            for origin, toks in sent.items():
                if origin != where:
                    seen += [f"{tok} (sent to {origin}) in {where}" for tok in toks if any(v in body for v in canary_variants(tok))]
        n = sum(len(v) for v in sent.values())
        if seen:
            self.add("canary", FIX, f"canary returned by another call: {', '.join(seen[:2])}")
        elif stopped:
            self.add("canary", SKIP, f"budget exhausted before canary check ({stopped}; {len(replies)} answer(s) inspected)",
                     inconclusive=True)
        else:
            self.add("canary", OK, f"{n} canary input(s) to {', '.join(sent)}; none in {len(replies)} other answer(s)")

    def rate_limit(self, n: int) -> None:
        if self.c.budget < MIN_RATE_LIMIT_BUDGET:
            self.add("rate-limit", SKIP, f"budget {self.c.budget} is under {MIN_RATE_LIMIT_BUDGET}")
            return
        n = min(n, self.c.remaining())
        if n < 5:
            self.add("rate-limit", SKIP, f"only {max(n, 0)} request(s) left in the budget")
            return
        made = 0
        try:
            for _ in range(n):
                r = self.session.rpc("tools/list")
                made += 1
                if r.status == 429 or "retry-after" in r.headers:
                    extra = f", Retry-After {r.headers['retry-after']}" if "retry-after" in r.headers else ""
                    self.add("rate-limit", OK, f"HTTP {r.status}{extra} after {made} call(s)")
                    return
        except BudgetSpent as e:
            if not made:
                raise
            self.add("rate-limit", FIX if made >= 5 else SKIP,
                     f"no rate limit observed within {made} requests ({e.what})")
            return
        self.add("rate-limit", FIX, f"no rate limit observed within {made} requests")

    def run(self) -> None:
        self.url_key()
        self.guarded("auth-required", self.auth_required)
        try:
            ok = self.open_main()
        except BudgetSpent as e:
            ok, self.cannot_initialize = False, e.what
        if not ok:
            for n in ("tool-pinning", "schema-error", "oversize", "ssrf-inputs", "canary", "rate-limit"):
                self.add(n, SKIP, self.cannot_initialize)
            return
        if self.write_tool and self.write_tool not in {t["name"] for t in self.tools}:
            self.cannot_initialize = f"--write {self.write_tool}: the server lists no such tool"
            raise Refused(self.cannot_initialize)
        budget = self.c.budget
        self.guarded("tool-pinning", self.tool_pinning)
        self.guarded("schema-error", self.schema_error)
        self.guarded("oversize", self.oversize)
        self.guarded("ssrf-inputs", lambda: self.ssrf(max(2, budget // 5)))
        self.guarded("canary", lambda: self.canary(max(4, budget // 6)))
        self.guarded("rate-limit", lambda: self.rate_limit(budget // 2))


# --- command --------------------------------------------------------------------------------------

def is_loopback_host(host: str) -> bool:
    """`localhost`, or an address that parses as loopback. A name that merely starts with 127. is not."""
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def exit_code(checks: list[Check]) -> int:
    if any(c.status == FIX for c in checks):
        return 1
    return 2 if any(c.inconclusive for c in checks) else 0


def redact(url: str) -> str:
    u = urllib.parse.urlparse(url)
    return f"{u.scheme}://{u.netloc.rsplit('@', 1)[-1]}/..."


def run(url: str, *, token: str | None = None, write_tool: str | None = None, budget: int = DEFAULT_BUDGET,
        seconds: float = DEFAULT_SECONDS, own: bool = False, repo: pathlib.Path | None = None,
        corpus: dict | None = None) -> tuple[int, dict]:
    """Returns (exit code, report). Raises Refused for exit 2 before any request is sent."""
    if budget <= 0 or seconds <= 0:
        raise Refused("a probe needs a budget: --budget and --seconds must both be above zero")
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Refused("the URL must be http:// or https:// with a host")
    host = u.hostname.lower()
    if token is not None and not TOKEN_RE.fullmatch(token):
        raise Refused("the token has invalid characters (it must be printable ASCII with no spaces)")      # never echoed
    if token and u.scheme == "http" and not is_loopback_host(host):
        raise Refused("refusing to send a token over plain http to a non-loopback host; use https")
    repo = repo or find_repo(pathlib.Path.cwd())
    manifest = read_manifest(repo)
    if not own and not host_is_owned(host, owned_hosts(repo)):
        raise Refused(f"{host} is not in {repo.name}'s teyla.toml ([security] mcp.url, [privacy]) or the Host column of "
                      "docs/PRIVACY.md; the probe never touches a third party. If you own this server, pass --i-own-this")
    client = Client(url, token, budget, seconds)
    probe = Probe(client, corpus or load_corpus(), write_tool=write_tool,
                  tier=(manifest.get("security") or {}).get("tier"), own=own)
    probe.run()
    code = exit_code(probe.checks)
    order = ["url-key", "auth-required", "tool-pinning", "schema-error", "oversize", "ssrf-inputs", "canary", "rate-limit"]
    checks = sorted(probe.checks, key=lambda c: order.index(c.name) if c.name in order else 99)
    return code, {"target": redact(url), "budget": budget, "requests": client.used,
                  "seconds": round(client.elapsed(), 1), "exit": code,
                  "checks": [c.as_dict() for c in checks], "_lines": [c.line() for c in checks],
                  "_initialize_error": probe.cannot_initialize}


def cmd_probe(args) -> int:
    token = args.token
    say = lambda text: scrub(str(text), token)          # every printed string passes through here
    try:
        if not net.gate("mcp probe (it sends JSON-RPC calls, and the injection corpus, to the URL you named)"):
            return 2
        code, report = run(args.url, token=token, write_tool=args.write, budget=args.budget, seconds=args.seconds,
                           own=args.i_own_this, repo=pathlib.Path(args.repo) if args.repo else None)
    except Refused as e:
        print(f"teyla mcp probe: refused: {say(e)}", file=sys.stderr)
        return 2
    except Exception as e:                              # noqa: BLE001 — one scrubbed line, never a traceback with the token
        print(f"teyla mcp probe: {say(e) or type(e).__name__}", file=sys.stderr)
        return 2
    init_failed = report["_initialize_error"]
    lines = report.pop("_lines")
    report.pop("_initialize_error")
    if init_failed:
        code = 2
        report["exit"] = 2
        report["error"] = init_failed
    if args.json:
        print(say(json.dumps(report, indent=2)))
    else:
        print(say(f"teyla mcp probe {report['target']}: {report['requests']} of {report['budget']} requests, {report['seconds']} s"))
        for ln in lines:
            print(say(ln))
        if init_failed:
            print(say(f"teyla mcp probe: {init_failed}"), file=sys.stderr)
    return code


def register(q):
    """Adds `probe` under `teyla mcp` (q is the `mcp` parser)."""
    sub = q.add_subparsers(dest="mcp_cmd", metavar="[probe]")
    p = sub.add_parser("probe", help="check a Streamable HTTP MCP server you own: auth, pinning, schemas, limits, SSRF, canary")
    p.set_defaults(fn=cmd_probe)
    p.add_argument("url", help="the MCP endpoint, http(s)://host/path")
    p.add_argument("--token", help="bearer token for the authenticated session (sent in an Authorization header, never printed)")
    p.add_argument("--write", metavar="TOOL", help="allow tools/call on this one write-like tool (default: none)")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help=f"most requests to send (default {DEFAULT_BUDGET}, above 0)")
    p.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help=f"most seconds to run (default {DEFAULT_SECONDS:g}, above 0)")
    p.add_argument("--json", action="store_true", help="print the checks as JSON")
    p.add_argument("--repo", help="the repo whose teyla.toml and docs/PRIVACY.md name your hosts (default: the current one)")
    p.add_argument("--i-own-this", action="store_true", help="the host is not in the repo's tables, and you own the server")
    p.add_argument("--allow-network", action="store_true", help="safe mode: allow this one probe")
    return p
