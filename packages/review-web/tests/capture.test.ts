import { test } from "node:test";
import assert from "node:assert/strict";
import { collectAnchors, hitTest, privateFrames, screenFor } from "../src/anchors.ts";
import { buildCapture, encodeCapture, isSlug, newId, type Anchor } from "../src/format.ts";
import { recordFor, type Frozen } from "../src/session.ts";
import { sha256Hex, sha256Plain } from "../src/sha256.ts";
import { page, place, rect } from "./helpers.ts";

const env = { os: "macOS 15.1", model: "Chrome 130", locale: "es-ES", language: "es", appearance: "dark" as const, dynamic_type: "unspecified" as const, screen: { width: 1000, height: 800, scale: 2 } };

function frozen(anchors: Anchor[], frames = [] as ReturnType<typeof rect>[], extra: Partial<Frozen> = {}): Frozen {
  return {
    id: "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64", hostname: "test.example.com", product: "fixture-app", version: "1.4.0", build: "212",
    environment: env, anchors, frames, sha256: "0b9e7c0e5f8a1d3c2f6a4b7d9e1c3a5f7b9d1e3c5a7f9b1d3e5c7a9f1b3d5e7c",
    pixelWidth: 2000, pixelHeight: 1600, scale: 2, ...extra,
  };
}

const NOW = new Date("2026-11-04T10:15:30.456Z");
const footer: Anchor = { id: "list.footer", screen: "list", role: "container", bounds: rect(0, 700, 1000, 100) };
const add: Anchor = { id: "list.add", screen: "list", parent: "list.footer", role: "button", bounds: rect(900, 720, 60, 60), strings: ["list.add"], source: { file: "src/List.tsx", line: 88 } };

test("the capture carries the iOS fields, test_host and the product tag", () => {
  const rec = recordFor(frozen([footer, add]), { tap: { x: 930.123, y: 750 }, text: "  Too small.  ", input: "text" }, NOW);
  assert.equal(rec.v, 1);
  assert.equal(rec.created, "2026-11-04T10:15:30Z");
  assert.equal(rec.device, "Web");
  assert.deepEqual(rec.app, { bundle_id: "test.example.com", version: "1.4.0", build: "212", product: "fixture-app", configuration: "test_host" });
  assert.deepEqual(rec.tap, { x: 930.12, y: 750 });
  assert.equal(rec.screen, "list");
  assert.equal(rec.element?.id, "list.add");
  assert.equal(rec.element?.matched_by, "anchor");
  assert.equal(rec.element?.parent, "list.footer");
  assert.deepEqual(rec.element?.source, { file: "src/List.tsx", line: 88 });
  assert.deepEqual(rec.element?.strings, ["list.add"]);
  assert.deepEqual(rec.comment, { text: "Too small.", input: "text", language: "es" });
  assert.deepEqual(rec.screenshot, { file: "capture.png", width: 2000, height: 1600, scale: 2, sha256: rec.screenshot.sha256 });
  assert.deepEqual(rec.microphone, { host_audio_in_use: false });
  assert.equal(rec.anchors.length, 2);
  assert.ok(!("region" in rec));
  assert.ok(!JSON.stringify(rec).includes("null"));
  assert.deepEqual(Object.keys(rec), ["v", "id", "created", "device", "app", "environment", "screen", "tap", "element", "anchors", "comment", "screenshot", "microphone"]);
});

test("the smallest anchor under the tap wins, and the later one on a tie", () => {
  const a: Anchor = { id: "a", role: "container", bounds: rect(0, 0, 100, 100) };
  const b: Anchor = { id: "b", role: "button", bounds: rect(10, 10, 20, 20) };
  const c: Anchor = { id: "c", role: "button", bounds: rect(10, 10, 20, 20) };
  assert.equal(hitTest([a, b], 15, 15)?.id, "b");
  assert.equal(hitTest([a, b, c], 15, 15)?.id, "c");
  assert.equal(hitTest([a, b], 50, 50)?.id, "a");
  assert.equal(hitTest([a], 100, 50), undefined, "the right edge is outside");
  assert.equal(hitTest([a], 0, 0)?.id, "a", "the left and top edges are inside");
});

test("a drag records the region, and the tap is its centre", () => {
  const rec = recordFor(frozen([footer, add]), { region: rect(890, 710, 80, 80), tap: { x: 930, y: 750 }, text: "x", input: "text" }, NOW);
  assert.deepEqual(rec.region, rect(890, 710, 80, 80));
  assert.equal(rec.element?.id, "list.add");
});

test("a capture about the whole screen has no tap, no region and no element, but a screen", () => {
  const rec = recordFor(frozen([footer, add]), { text: "The page is slow.", input: "text" }, NOW);
  assert.ok(!("tap" in rec) && !("region" in rec) && !("element" in rec));
  assert.equal(rec.screen, "list", "the screen most anchors share");
  const set = recordFor(frozen([footer, add], [], { currentScreen: "registered.screen" }), { text: "x", input: "text" }, NOW);
  assert.equal(set.screen, "registered.screen");
});

test("a tap on a private area records no element, and the picture has the box", () => {
  const secret = rect(880, 700, 100, 100);
  const rec = recordFor(frozen([footer, add], [secret]), { tap: { x: 930, y: 750 }, text: "x", input: "text" }, NOW);
  assert.ok(!("element" in rec), "a private area is not named");
  assert.deepEqual(rec.tap, { x: 930, y: 750 });
  const region = recordFor(frozen([footer, add], [secret]), { region: rect(100, 100, 790, 650), tap: { x: 495, y: 425 }, text: "x", input: "text" }, NOW);
  assert.ok(!("element" in region), "a circle that reaches the private area names nothing");
});

test("dictated text is marked as speech", () => {
  assert.equal(recordFor(frozen([]), { text: "x", input: "speech" }, NOW).comment.input, "speech");
});

test("the comment is capped at 8000 characters and anchors at 200", () => {
  const many = Array.from({ length: 250 }, (_, i): Anchor => ({ id: `a${i}`, role: "other", bounds: rect(i, 0, 1, 1) }));
  const rec = recordFor(frozen(many), { text: "y".repeat(9000), input: "text" }, NOW);
  assert.equal(rec.comment.text.length, 8000);
  assert.equal(rec.anchors.length, 200);
});

test("a commit is kept only when it is 7 to 40 lowercase hex characters", () => {
  const ok = recordFor(frozen([], [], { commit: "3f9c2ab" }), { text: "x", input: "text" }, NOW);
  assert.equal(ok.app.commit, "3f9c2ab");
  const bad = recordFor(frozen([], [], { commit: "not-a-sha" }), { text: "x", input: "text" }, NOW);
  assert.ok(!("commit" in bad.app));
});

test("buildCapture with a bare id element uses the accessibility_identifier fallback", () => {
  const rec = buildCapture({ id: newId(), now: NOW, product: "p", hostname: "h.example.com", version: "1", build: "1", environment: env, anchors: [], text: "t", input: "text", sha256: "0".repeat(64), pixelWidth: 1, pixelHeight: 1, scale: 1, element: { id: "save-btn" } });
  assert.deepEqual(rec.element, { id: "save-btn", matched_by: "accessibility_identifier" });
  assert.match(encodeCapture(rec), /"v":1/);
});

test("ids are lowercase UUIDs and slugs are checked", () => {
  assert.match(newId(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(isSlug("my-app"), true);
  assert.equal(isSlug("My-app"), false);
  assert.equal(isSlug("1abc"), false);
  assert.equal(isSlug("a".repeat(41)), false);
});

test("sha256 matches the known vectors, with and without Web Crypto", async () => {
  const abc = new TextEncoder().encode("abc");
  const want = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
  assert.equal(sha256Plain(abc), want);
  assert.equal(await sha256Hex(abc), want);
  assert.equal(sha256Plain(new Uint8Array()), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  const big = new Uint8Array(100_000).map((_, i) => (i * 31) % 251);
  assert.equal(sha256Plain(big), await sha256Hex(big));
  const subtle = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  Object.defineProperty(globalThis, "crypto", { value: { randomUUID: () => "x" }, configurable: true });
  try { assert.equal(await sha256Hex(abc), want, "an http page with no crypto.subtle still hashes"); }
  finally { if (subtle) Object.defineProperty(globalThis, "crypto", subtle); }
});

test("anchors come from data-review attributes: role, screen, parent, strings, source", () => {
  const { doc } = page(`
    <div data-review-screen="trip.timeline">
      <section id="foot" data-review-anchor="trip.timeline.footer">
        <button id="add" data-review-anchor="trip.timeline.addButton" data-review-strings="timeline.add, timeline.hint" data-review-source="src/Timeline.tsx:41">Add</button>
        <input id="note" data-review-anchor="trip.timeline.note" data-review-role="text">
        <span id="gone" data-review-anchor="gone"></span>
        <span id="off" data-review-anchor="off">x</span>
      </section>
    </div>`);
  place(doc.getElementById("foot"), rect(0, 700, 1000, 100));
  place(doc.getElementById("add"), rect(900, 720, 60, 60));
  place(doc.getElementById("note"), rect(10, 720, 200, 30));
  place(doc.getElementById("gone"), rect(0, 0, 0, 0));
  place(doc.getElementById("off"), rect(0, 9000, 10, 10));
  const anchors = collectAnchors(doc, 1000, 800, []);
  assert.deepEqual(anchors.map((a) => a.id), ["trip.timeline.footer", "trip.timeline.addButton", "trip.timeline.note"]);
  const [, addA, note] = anchors;
  assert.equal(addA?.role, "button");
  assert.equal(addA?.parent, "trip.timeline.footer");
  assert.equal(addA?.screen, "trip.timeline");
  assert.deepEqual(addA?.strings, ["timeline.add", "timeline.hint"]);
  assert.deepEqual(addA?.source, { file: "src/Timeline.tsx", line: 41 });
  assert.equal(note?.role, "text", "data-review-role wins over the tag");
  assert.equal(screenFor(undefined, undefined, anchors), "trip.timeline");
});

test("an anchor that overlaps a private area loses its strings, and keeps its id and bounds", () => {
  const { doc } = page(`<button id="b" data-review-anchor="x.b" data-review-strings="k.name">Name</button><div id="p" data-review-private>Ana</div>`);
  place(doc.getElementById("b"), rect(10, 10, 100, 30));
  place(doc.getElementById("p"), rect(20, 15, 50, 20));
  const frames = privateFrames(doc, 1000, 800);
  const [a] = collectAnchors(doc, 1000, 800, frames);
  assert.equal(a?.id, "x.b");
  assert.ok(!a || !("strings" in a));
  assert.deepEqual(a?.bounds, rect(10, 10, 100, 30));
});
