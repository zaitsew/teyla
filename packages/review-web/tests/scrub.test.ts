import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildCapture } from "../src/format.ts";
import { LABEL_CAP, scrub, scrubLabel } from "../src/scrub.ts";

// The one list of cases every platform's tests read: packages/review-channel/test-vectors/scrub.json.
interface Case { name: string; input: string; expected: string }
const vectors = JSON.parse(
  readFileSync(new URL("../../review-channel/test-vectors/scrub.json", import.meta.url), "utf8"),
) as { text: Case[]; label: Case[] };

test("the shared vectors are not empty", () => {
  assert.ok(vectors.text.length >= 30);
  assert.ok(vectors.label.length >= 3);
});

for (const c of vectors.text) {
  test(`scrub: ${c.name}`, () => {
    assert.equal(scrub(c.input), c.expected);
    assert.equal(scrub(c.expected), c.expected, "scrubbing twice changes nothing");
  });
}

for (const c of vectors.label) {
  test(`scrubLabel: ${c.name}`, () => assert.equal(scrubLabel(c.input), c.expected));
}

test("the label cap is 200", () => assert.equal(LABEL_CAP, 200));

test("a capture carries no raw e-mail, phone or token in any text field", () => {
  const rec = buildCapture({
    id: "11111111-1111-4111-8111-111111111111", now: new Date("2026-11-20T10:00:00Z"), product: "sample", hostname: "app.example.com",
    version: "1", build: "1", environment: { os: "Web", model: "x", locale: "en", appearance: "light", dynamic_type: "unspecified", screen: { width: 1, height: 1, scale: 1 } },
    screen: "page jane@example.com",
    anchors: [{ id: "a.b", role: "text", bounds: { x: 0, y: 0, width: 5, height: 5 }, strings: ["jane@example.com", "ok"], screen: "s" }],
    element: { id: "id.jane@example.com", role: "text", bounds: { x: 0, y: 0, width: 5, height: 5 }, strings: ["+34 600 123 456"] },
    text: "mail jane@example.com, key sk_live_abcdefghijklmnop1234, https://example.com/x?token=abc",
    input: "text", sha256: "0".repeat(64), pixelWidth: 1, pixelHeight: 1, scale: 1,
  } as unknown as Parameters<typeof buildCapture>[0]);
  const json = JSON.stringify(rec);
  for (const raw of ["jane@example.com", "sk_live_abcdefghijklmnop1234", "token=abc", "600 123 456"]) {
    assert.ok(!json.includes(raw), raw);
  }
  assert.equal(rec.comment.text, "mail [email], key [token], https://example.com/x?token=[token]");
});
