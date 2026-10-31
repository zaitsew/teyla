# MCP security: the probe, the corpus and the product tests

Status: shipped 2026-10-31.

An MCP server turns text from the outside into actions on the inside. This page covers the three parts
of Teyla that test one: `teyla mcp probe` (a black-box check of a server you own), the injection corpus
(attack inputs), and the per-product test templates (effects against the product's own handlers). They
implement SH7, SH13 and SH14 of the Shield concept (section 5.5).

## The cut: one leg of the trifecta per product

A server or agent has up to three legs: private data, untrusted content, an outbound channel. All three
together is the exfiltration path. The product's `teyla.toml` says which leg it cuts:

- A public research server has no private data.
- A personal-data server has no arbitrary URL fetch, no mail, no shell and no posting tool, and
  authorises every record it returns.
- A coding worker holds no production secret and no publishing credential.
- A research-to-action flow produces a proposal; a separate executor checks recipients and permissions.

The probe and the templates test the cut. They do not replace it.

## `teyla mcp probe`

```
teyla mcp probe <url> [--token T] [--write TOOL] [--budget N] [--seconds S] [--json] [--repo PATH]
                [--i-own-this] [--allow-network]
```

It speaks MCP Streamable HTTP: JSON-RPC 2.0 over POST, `initialize`, `notifications/initialized`,
`tools/list`, `tools/call`. It reads JSON answers and the first `data:` line of an event stream, carries
`Mcp-Session-Id`, follows no redirect and uses the standard library only. One line per check:
`OK|FIX|SKIP  <name>  <evidence>`; a FIX line ends with the fix. Exit 0 when every check is OK or SKIP,
1 on any FIX, 2 when it refused or could not initialize. `--json` prints the same list.

| Check | Passes when | FIX means | Fix |
|---|---|---|---|
| `url-key` | no path segment of 20 or more `[A-Za-z0-9_-]`, no `key=`, `token=` or `secret=` in the query | the URL is the secret: it lands in access logs and referrers | key in an `Authorization` header; rotate the exposed one |
| `auth-required` | `initialize` or `tools/list` without Authorization answers 401 or 403 | an anonymous caller sees the tools (SKIP for tier `owner` with `--i-own-this`) | bearer token or OAuth on every request; 401 with `WWW-Authenticate` |
| `tool-pinning` | two sessions give one sha256 of names, descriptions and schemas | the tool list changed between sessions: a rug-pull | freeze tools per release; a changed description needs a new version and client re-approval |
| `schema-error` | a wrong-type argument gives JSON-RPC -32602, a 4xx or an `isError` result | a 500, a -32603, or a success | validate against the input schema; never a stack trace |
| `oversize` | a 1 MB string argument gives 413, a 4xx or an error | the server accepted it or fell over | cap body and argument length |
| `ssrf-inputs` | every attacker URL in the corpus is refused by each tool with a `url`, `uri` or `href` string | a tool returned content for a loopback, private, link-local, metadata or non-http address | resolve and refuse those ranges and schemes before fetching; pin the resolved address |
| `canary` | encoded canaries sent to the free-text tools appear in no other tool's answer and not in `tools/list` | stored input crossed a tool or a user boundary | scope stored text per user; return it only from the tool that owns it |
| `rate-limit` | rapid `tools/list` calls meet a 429 or a `Retry-After` within the budget | `no rate limit observed within N requests` (SKIP when the budget is under 20) | per-credential and per-address limits; 429 with `Retry-After` |

`auth-required` also passes a server that answers 200 to `initialize` and 401 to `tools/list`.
`canary` and `ssrf-inputs` SKIP when no tool has the matching property.

### Budgets and writes

The probe has a request budget (`--budget`, default 60) and a time budget (`--seconds`, default 120);
both must be above zero or it exits 2 before sending anything. Every request is counted. A check that
meets a spent budget prints SKIP with the reason. Rough use in a default run: 9 to 12 requests for the
handshakes, pinning, schema and size checks, up to 12 for SSRF, up to 10 for the canary, and the rest
(up to 30) for the rate limit.

It makes no `tools/call` on a tool whose name or description reads like a write (create, delete, send,
post, update, write, pay, save, remove, insert, publish, transfer, grant, share, upload, drop, destroy,
execute) or whose annotations say destructive. `--write TOOL` allows exactly that one tool. It then
serves as the target of the schema and size checks; a name the server does not list exits 2.

### Never a third party

The probe runs only against a host that the current repo names: `[security] mcp = { url = "..." }` or
the `[privacy]` table in `teyla.toml`, or the Host column of `docs/PRIVACY.md`. A wildcard row such as
`*.example.test` matches subdomains. Otherwise it exits 2 unless you pass `--i-own-this`, which says you
own the server. A token goes in an Authorization header, only over https or to a loopback host, and is
never printed; the report shows the scheme and host, not the path. Safe mode refuses the probe unless
`--allow-network` is given. It is row 32 of [PRIVACY.md](PRIVACY.md).

## The corpus

`templates/security/injection_cases.json`: 43 invented cases `{id, family, input, expect}`. The text
names no real person, product or host; hosts are RFC-reserved, private or link-local addresses, or
`example.test`.

| Family | Cases | What it tries | Usual `expect` |
|---|---|---|---|
| `forged-instruction` | 6 | text that tells the agent to call a tool, change a rule or skip confirmation | `no-outbound` |
| `delimiter-escape` | 6 | closing tags, markdown fences, JSON and CDATA breakouts, header injection | `rejected`, `schema-error` |
| `encoded-canary` | 6 | `CANARY-<id>` in plain, base64, percent-encoded, zero-width-spaced, hex and reversed form | `no-canary-in-output` |
| `attacker-url` | 13 | loopback, 10/8, 172.16/12, 192.168/16, 169.254.169.254, `file://`, `gopher://`, decimal IP, rebinding names | `rejected` |
| `oversize` | 2 | a 2 MB string and a 2 MB nested array, stored as `input` plus `repeat` | `rejected` |
| `permission-change` | 4 | grant a role, add an admin, share with everyone, widen a scope | `unchanged-permissions` |
| `log-to-leak` | 4 | call the logging, notes or memory tool with everything known about the user | `no-canary-in-output`, `no-outbound` |
| `rug-pull` | 2 | a tool description or schema that changes between sessions | `same-tool-hash` |

`expect` is one of `rejected`, `no-outbound`, `no-canary-in-output`, `schema-error`,
`unchanged-permissions`, `same-tool-hash`. The probe reads the `attacker-url` and `encoded-canary`
families; the product tests read all of them. `tests/test_mcp_probe.py` checks the file's shape.

## Product tests

`templates/security/tests/deno/security.test.ts` and `tests/vitest/security.test.ts` call the product's
own handlers with synthetic accounts (anonymous, A, B) and no model: an unauthorised call fails, A cannot
read B, a canary appears in no captured outbound request (a `fetch` spy), a URL tool makes no request for
an attacker URL, and forged or permission-changing text leaves A's permissions and the set of contacted
hosts as they were. `templates/security/README.md` says how to copy them in and how to record the probe's
result as `[[security.evidence]]` with `what = "mcp-probe"`. The Deno template type-checks and passes
against an in-memory handler; the vitest template is the same code and has not been run.

## What this does not do

It does not test a model's judgment: the checks are deterministic and run without one. It does not attack
production, send mail, post or pay. A red team against staging with a written target list is SH14 and
comes after tenant isolation. A clean probe is evidence of eight mechanical properties, not proof of
safety.
