// Security effects for an MCP server or agent surface (Teyla Shield, SH7). Copy to tests/security/, next to
// injection_cases.json, then edit only the ADAPT block. Run: npx vitest run tests/security
//
// The tests call the product's own handlers directly, with synthetic accounts (anon, A, B) and no model in
// the loop. They assert effects, not labels: an unauthorised call fails, A cannot read B, and a canary
// string never reaches a captured outbound request.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const corpus: { cases: Case[] } = JSON.parse(
  readFileSync(new URL("./injection_cases.json", import.meta.url), "utf8"),
);
const family = (f: string) => corpus.cases.filter((c) => c.family === f);
const valueOf = (c: Case) => (c.repeat ? c.input.repeat(c.repeat) : c.input);

function variants(token: string): string[] {
  const bytes = [...new TextEncoder().encode(token)];
  const hex = bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
  const pct = bytes.map((b) => "%" + b.toString(16).toUpperCase().padStart(2, "0")).join("");
  return [token, btoa(token).replace(/=+$/, ""), pct, pct.toLowerCase(), hex, [...token].reverse().join("")];
}
const stripInvisible = (s: string) => s.replace(/[​‌‍⁠﻿]/g, "");

let seen: { url: string; text: string }[] = [];
beforeEach(() => {
  seen = [];
  vi.stubGlobal("fetch", async (input: Request | URL | string, init?: RequestInit) => {
    const req = new Request(input, init);
    seen.push({ url: req.url, text: req.url + " " + [...req.headers].join(" ") + " " + (await req.clone().text()) });
    return new Response("{}", { status: 200 });
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("security effects", () => {
  it("the corpus has every family", () => {
    expect(corpus.cases.length).toBeGreaterThanOrEqual(40);
    for (const f of ["forged-instruction", "delimiter-escape", "encoded-canary", "attacker-url", "oversize",
      "permission-change", "log-to-leak", "rug-pull"]) expect(family(f).length, f).toBeGreaterThan(0);
  });

  it("a direct call without a session fails, with no model in the loop", async () => {
    for (const t of TOOLS) expect((await callTool("anon", t.name, t.args ?? {})).ok, t.name).toBe(false);
  });

  it("A cannot read what B owns", async () => {
    const marker = "MARKER-owned-by-b";
    const id = await seed("b", marker);
    expect((await readRecord("b", id)).text).toContain(marker);
    const r = await readRecord("a", id);
    expect(r.ok).toBe(false);
    expect(r.text).not.toContain(marker);
  });

  it("a canary sent to one tool is in no outbound request", async () => {
    for (const c of family("encoded-canary")) {
      for (const t of TOOLS.filter((t) => t.text)) await callTool("a", t.name, { ...t.args, [t.text!]: c.input });
    }
    for (const t of TOOLS) await callTool("a", t.name, t.args ?? {});
    for (const c of family("encoded-canary")) {
      for (const s of seen) for (const v of variants(c.canary!)) {
        expect(stripInvisible(s.text).includes(v), `${c.id} reached ${s.url}`).toBe(false);
      }
    }
  });

  it("a tool that takes a URL refuses the attacker URLs and makes no request", async () => {
    for (const t of TOOLS.filter((t) => t.url)) {
      for (const c of family("attacker-url")) {
        seen = [];
        const r = await callTool("a", t.name, { ...t.args, [t.url!]: c.input });
        expect(r.ok, `${t.name} accepted ${c.id}`).toBe(false);
        expect(seen.length, `${t.name} fetched for ${c.id}`).toBe(0);
      }
    }
  });

  it("forged instructions and log-to-leak texts cause no undocumented request and no new permission", async () => {
    const before = await permissions("a");
    for (const c of [...family("forged-instruction"), ...family("permission-change"), ...family("log-to-leak"),
      ...family("delimiter-escape")]) {
      for (const t of TOOLS.filter((t) => t.text)) await callTool("a", t.name, { ...t.args, [t.text!]: c.input });
    }
    for (const s of seen) expect(DOCUMENTED_HOSTS, `undocumented host ${s.url}`).toContain(new URL(s.url).hostname);
    expect(await permissions("a")).toBe(before);
  });

  it("an oversized argument is refused", async () => {
    for (const t of TOOLS.filter((t) => t.text)) {
      for (const c of family("oversize")) {
        expect((await callTool("a", t.name, { ...t.args, [t.text!]: valueOf(c) })).ok, `${t.name} accepted ${c.id}`).toBe(false);
      }
    }
  });
});
