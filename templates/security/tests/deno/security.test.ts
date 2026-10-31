// Security effects for an MCP server or agent surface (Teyla Shield, SH7). Copy to tests/security/, next to
// injection_cases.json, then edit only the ADAPT block. Run: deno test --allow-read tests/security/
//
// The tests call the product's own handlers directly, with synthetic accounts (anon, A, B) and no model in
// the loop. They assert effects, not labels: an unauthorised call fails, A cannot read B, and a canary
// string never reaches a captured outbound request.
import { assert, assertEquals, assertFalse } from "jsr:@std/assert@1";

type Who = "anon" | "a" | "b";
type Result = { ok: boolean; status?: number; text: string };
type Case = { id: string; family: string; input: string; expect: string; repeat?: number; canary?: string };

// ---- ADAPT: wire these to the product's handlers. Synthetic data only. --------------------------------
/** Every tool the server exposes, with the argument that takes free text and the one that takes a URL. */
const TOOLS: { name: string; text?: string; url?: string; args?: Record<string, unknown> }[] = [
  { name: "note_add", text: "text" },
  { name: "note_get", args: { id: "x" } },
  { name: "page_fetch", url: "url" },
];
/** Hosts the product documents in docs/PRIVACY.md. A request to any other host is a failure. */
const DOCUMENTED_HOSTS = ["api.example.test"];

/** Call a tool handler as `who`. No HTTP, no model: import the handler and pass a synthetic session. */
async function callTool(_who: Who, _tool: string, _args: Record<string, unknown>): Promise<Result> {
  throw new Error("ADAPT: call the product's handler and map its answer to { ok, status, text }");
}
/** Create a record owned by `who`; return its id. */
async function seed(_who: Who, _text: string): Promise<string> {
  throw new Error("ADAPT: insert through the product's own write path");
}
/** Read one record as `who`. */
async function readRecord(_who: Who, _id: string): Promise<Result> {
  throw new Error("ADAPT: call the product's read handler");
}
/** A comparable snapshot of what `who` may do (roles, grants, shares). */
async function permissions(_who: Who): Promise<string> {
  throw new Error("ADAPT: return the account's roles, grants and shares as a string");
}
// ---- end of ADAPT ---------------------------------------------------------------------------------------

/** Valid arguments for a tool, so a refusal means "not authorised", not "missing field". */
const validArgs = (t: (typeof TOOLS)[number]): Record<string, unknown> => ({
  ...t.args,
  ...(t.text ? { [t.text]: "hello" } : {}),
  ...(t.url ? { [t.url]: "https://example.test/" } : {}),
});

const corpus: { cases: Case[] } = JSON.parse(
  Deno.readTextFileSync(new URL("./injection_cases.json", import.meta.url)),
);
const family = (f: string) => corpus.cases.filter((c) => c.family === f);
const valueOf = (c: Case) => (c.repeat ? c.input.repeat(c.repeat) : c.input);

function variants(token: string): string[] {
  const hex = [...new TextEncoder().encode(token)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const pct = [...new TextEncoder().encode(token)].map((b) => "%" + b.toString(16).toUpperCase().padStart(2, "0")).join("");
  return [token, btoa(token).replace(/=+$/, ""), pct, pct.toLowerCase(), hex, [...token].reverse().join("")];
}
const stripInvisible = (s: string) => s.replace(/[​‌‍⁠﻿]/g, "");

/** Replace fetch with a recorder for one test; every outbound request lands in `seen`. */
async function withFetchSpy(run: (seen: { url: string; text: string }[]) => Promise<void>) {
  const seen: { url: string; text: string }[] = [];
  const real = globalThis.fetch;
  globalThis.fetch = (async (input: Request | URL | string, init?: RequestInit) => {
    const req = new Request(input, init);
    seen.push({ url: req.url, text: req.url + " " + [...req.headers].join(" ") + " " + (await req.clone().text()) });
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  try {
    await run(seen);
  } finally {
    globalThis.fetch = real;
  }
}

Deno.test("the corpus has every family and a valid expectation", () => {
  assert(corpus.cases.length >= 40);
  for (const f of ["forged-instruction", "delimiter-escape", "encoded-canary", "attacker-url", "oversize",
    "permission-change", "log-to-leak", "rug-pull"]) assert(family(f).length > 0, f);
});

Deno.test("a direct call without a session fails, with no model in the loop", async () => {
  for (const t of TOOLS) {
    const r = await callTool("anon", t.name, validArgs(t));
    assertFalse(r.ok, `${t.name} answered an anonymous call`);
  }
});

Deno.test("A cannot read what B owns", async () => {
  const marker = "MARKER-owned-by-b";
  const id = await seed("b", marker);
  assert((await readRecord("b", id)).text.includes(marker));
  const r = await readRecord("a", id);
  assertFalse(r.ok);
  assertFalse(r.text.includes(marker));
});

Deno.test("a canary sent to one tool is in no outbound request", async () => {
  await withFetchSpy(async (seen) => {
    for (const c of family("encoded-canary")) {
      for (const t of TOOLS.filter((t) => t.text)) await callTool("a", t.name, { ...t.args, [t.text!]: c.input });
    }
    for (const t of TOOLS) await callTool("a", t.name, validArgs(t));
    for (const c of family("encoded-canary")) {
      for (const s of seen) for (const v of variants(c.canary!)) {
        assertFalse(stripInvisible(s.text).includes(v), `${c.id} reached ${s.url}`);
      }
    }
  });
});

Deno.test("a tool that takes a URL refuses the attacker URLs and makes no request", async () => {
  for (const t of TOOLS.filter((t) => t.url)) {
    for (const c of family("attacker-url")) {
      await withFetchSpy(async (seen) => {
        const r = await callTool("a", t.name, { ...t.args, [t.url!]: c.input });
        assertFalse(r.ok, `${t.name} accepted ${c.id}`);
        assertEquals(seen.length, 0, `${t.name} fetched for ${c.id}`);
      });
    }
  }
});

Deno.test("forged instructions and log-to-leak texts cause no undocumented request and no new permission", async () => {
  const before = await permissions("a");
  await withFetchSpy(async (seen) => {
    for (const c of [...family("forged-instruction"), ...family("permission-change"), ...family("log-to-leak"),
      ...family("delimiter-escape")]) {
      for (const t of TOOLS.filter((t) => t.text)) await callTool("a", t.name, { ...t.args, [t.text!]: c.input });
    }
    for (const s of seen) {
      assert(DOCUMENTED_HOSTS.includes(new URL(s.url).hostname), `undocumented host ${s.url}`);
    }
  });
  assertEquals(await permissions("a"), before);
});

Deno.test("an oversized argument is refused", async () => {
  for (const t of TOOLS.filter((t) => t.text)) {
    for (const c of family("oversize")) {
      const r = await callTool("a", t.name, { ...t.args, [t.text!]: valueOf(c) });
      assertFalse(r.ok, `${t.name} accepted ${c.id}`);
    }
  }
});
