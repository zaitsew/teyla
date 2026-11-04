import { test } from "node:test";
import assert from "node:assert/strict";
import { isUuid, parseChannel, putOne, resultForStatus, sendCapture, type FetchLike } from "../src/channel.ts";

const cfg = { baseUrl: "https://review.example.com", key: "secret-key" };
const ID = "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64";

test("statuses map to delivered, retry and refused the way the iOS client reads them", () => {
  assert.equal(resultForStatus(200), "delivered");
  for (const s of [400, 401, 403, 413, 422]) assert.equal(resultForStatus(s), "refused", String(s));
  for (const s of [404, 405, 408, 429, 500, 502, 503, 507]) assert.equal(resultForStatus(s), "retry", String(s));
});

test("the channel needs an https address and a key; plain http only for loopback", () => {
  assert.deepEqual(parseChannel({ url: "https://review.example.com/", key: " k " }), { baseUrl: "https://review.example.com", key: "k" });
  assert.deepEqual(parseChannel({ url: "http://localhost:8099", key: "k" }), { baseUrl: "http://localhost:8099", key: "k" });
  assert.notEqual(parseChannel({ url: "http://127.0.0.1:8099", key: "k" }), null);
  assert.equal(parseChannel({ url: "http://review.example.com", key: "k" }), null);
  assert.equal(parseChannel({ url: "https://review.example.com" }), null);
  assert.equal(parseChannel({ key: "k" }), null);
  assert.equal(parseChannel({ url: "https://review.example.com", key: "$(KEY)" }), null);
  assert.equal(parseChannel({ url: "https://review.example.com", key: "undefined" }), null);
  assert.equal(parseChannel({ url: "not a url", key: "k" }), null);
  assert.equal(parseChannel(undefined), null);
});

test("the key goes in one header and nowhere else; no cookies, no referrer", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const f: FetchLike = async (url, init) => { calls.push({ url, init }); return { status: 200 }; };
  assert.equal(await putOne(cfg, ID, "capture.json", "{}", "application/json", f), "delivered");
  const c = calls[0]!;
  assert.equal(c.url, `https://review.example.com/v1/captures/${ID}/capture.json`);
  assert.equal(c.init.method, "PUT");
  assert.equal((c.init.headers as Record<string, string>)["Authorization"], "Bearer secret-key");
  assert.equal(c.init.credentials, "omit");
  assert.equal(c.init.referrerPolicy, "no-referrer");
  assert.ok(!c.url.includes("secret-key"));
});

test("the picture goes first, then the JSON, and a miss on the picture stops it", async () => {
  const order: string[] = [];
  const f: FetchLike = async (url) => { order.push(url.split("/").pop()!); return { status: 200 }; };
  const cap = { id: ID, json: "{}", png: new Blob([new Uint8Array(3)]) };
  assert.equal(await sendCapture(cfg, cap, f), "delivered");
  assert.deepEqual(order, ["capture.png", "capture.json"]);
  order.length = 0;
  const busy: FetchLike = async (url) => { order.push(url.split("/").pop()!); return { status: 503 }; };
  assert.equal(await sendCapture(cfg, cap, busy), "retry");
  assert.deepEqual(order, ["capture.png"]);
});

test("a network or CORS failure reads as retry, never as a throw", async () => {
  const f: FetchLike = async () => { throw new TypeError("Failed to fetch"); };
  assert.equal(await putOne(cfg, ID, "capture.png", new Blob([]), "image/png", f), "retry");
});

test("an id that is not a lowercase UUID is refused before anything is sent", async () => {
  let called = false;
  const f: FetchLike = async () => { called = true; return { status: 200 }; };
  assert.equal(await sendCapture(cfg, { id: ID.toUpperCase(), json: "{}", png: new Blob([]) }, f), "refused");
  assert.equal(called, false);
  assert.equal(isUuid(ID), true);
});
