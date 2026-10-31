# Security test templates for an MCP server or agent surface

Teyla Shield, SH7: cut one leg of the trifecta per product and prove it with effects, not labels. These
files are the proof. They are not a product; copy them and edit the marked block.

## What is here

| File | What it is |
|---|---|
| `injection_cases.json` | 43 invented attack inputs in 8 families, each `{id, family, input, expect}` |
| `tests/deno/security.test.ts` | the effect tests for a Deno product (Supabase edge functions, Deno Deploy) |
| `tests/vitest/security.test.ts` | the same tests for a Node product |

An `oversize` case holds a `repeat` count, not the 2 MB string: build it with `input.repeat(repeat)`.
An `encoded-canary` case holds the `canary` token (`CANARY-<id>`) and how it is encoded.

## Copy them into a product

1. Copy `injection_cases.json` and the test for your runtime into `tests/security/`.
2. Edit the block between `ADAPT` and `end of ADAPT`: the tool list, the documented hosts, and four
   functions (`callTool`, `seed`, `readRecord`, `permissions`) that call your own handlers with
   synthetic accounts. Call the handler, not the model: no model is in the loop.
3. Run it: `deno test --allow-read tests/security/` or `npx vitest run tests/security`.

## What the tests assert

- A call without a session fails (anonymous account).
- Account A cannot read what account B owns.
- A canary sent to one tool, in six forms, is in no captured outbound request (a `fetch` spy).
- A tool that takes a URL refuses the attacker URLs and sends no request.
- Forged instructions, permission changes and log-to-leak texts cause no request to an undocumented
  host and leave A's permissions as they were.
- An oversized argument is refused.

Synthetic data only: never a real account, token or record, and never a staging host you do not own.

## Wire the evidence into the release

Run the probe against staging with a synthetic account's token, then record the receipt in `teyla.toml`:

```toml
[security]
release = ["leak", "hosts", "deps", "mcp-probe<30d"]

[[security.evidence]]
what = "mcp-probe"
commit = "<short sha of the deployed commit>"
date = 2026-10-31
how = "teyla mcp probe https://staging.example.test/mcp --token $SYNTHETIC_TOKEN (exit 0)"
```

The probe refuses a host the repo does not name: put the staging URL in `[security] mcp = { url = "..." }`.
Keep the suite's result as the evidence for the mandatory review of a PR that touches an MCP tool.
See [docs/MCP-SECURITY.md](../../docs/MCP-SECURITY.md).
