import { test } from "node:test";
import assert from "node:assert/strict";
import type { ChannelResult } from "../src/channel.ts";
import { MemoryStore, QueueFullError, ReviewQueue, type QueueEntry, type QueueStore } from "../src/queue.ts";

const entry = (id: string, created = 1000, bytes = 10): QueueEntry => ({ id, created, json: "{}", png: new Blob([new Uint8Array(bytes)]), attempts: 0 });
const cap = { entries: 3, bytes: 100, ttlMs: 10_000 };

/** A store whose writes fail, the way a private window or a full disk does. */
class BrokenStore implements QueueStore {
  async put(): Promise<void> { throw new Error("QuotaExceededError"); }
  async all(): Promise<QueueEntry[]> { return []; }
  async remove(): Promise<void> {}
}

test("a capture is saved first, sent second, and deleted only after the channel said 200", async () => {
  const store = new MemoryStore();
  const seen: string[] = [];
  const q = new ReviewQueue(store, async (e) => { seen.push(`${e.id}:${store.map.has(e.id)}`); return "delivered"; }, () => 2000, cap);
  assert.equal(await q.send(entry("a")), "delivered");
  assert.deepEqual(seen, ["a:true"], "it was in the store while it was sent");
  assert.equal(store.map.size, 0);
});

test("a failed send keeps the capture for later and counts the attempt", async () => {
  const store = new MemoryStore();
  const q = new ReviewQueue(store, async () => "retry", () => 2000, cap);
  assert.equal(await q.send(entry("a")), "queued");
  assert.equal(store.map.get("a")?.attempts, 1);
  assert.equal(await q.pending(), 1);
});

test("flush sends the oldest first and deletes each one the channel took", async () => {
  const store = new MemoryStore();
  for (const [id, t] of [["c", 3], ["a", 1], ["b", 2]] as const) await store.put(entry(id, t * 100));
  const order: string[] = [];
  const answers: Record<string, ChannelResult> = { a: "delivered", b: "retry", c: "delivered" };
  const q = new ReviewQueue(store, async (e) => { order.push(e.id); return answers[e.id] as ChannelResult; }, () => 1000, cap);
  const report = await q.flush();
  assert.deepEqual(order, ["a", "b", "c"]);
  assert.deepEqual(report, { delivered: 2, retry: 1, refused: 0, expired: 0 });
  assert.deepEqual([...store.map.keys()], ["b"]);
});

test("a refused capture is kept, flagged, and never sent again", async () => {
  const store = new MemoryStore();
  await store.put(entry("a"));
  let calls = 0;
  const q = new ReviewQueue(store, async () => { calls++; return "refused"; }, () => 2000, cap);
  assert.equal((await q.flush()).refused, 1);
  assert.equal(store.map.get("a")?.refused, true);
  await q.flush();
  assert.equal(calls, 1);
  assert.equal(await q.pending(), 0, "it no longer waits");
});

test("a capture older than the limit is dropped", async () => {
  const store = new MemoryStore();
  await store.put(entry("old", 0));
  await store.put(entry("new", 9_000));
  const q = new ReviewQueue(store, async () => "retry", () => 10_500, cap);
  const r = await q.flush();
  assert.equal(r.expired, 1);
  assert.deepEqual([...store.map.keys()], ["new"]);
});

test("the queue holds at most `entries` captures and `bytes` bytes", async () => {
  const store = new MemoryStore();
  const q = new ReviewQueue(store, async () => "retry", () => 2000, cap);
  for (const id of ["a", "b", "c"]) assert.equal(await q.send(entry(id)), "queued");
  assert.equal(await q.send(entry("d")), "unsaved", "a fourth does not fit");
  assert.equal(store.map.size, 3);
  const big = new ReviewQueue(new MemoryStore(), async () => "retry", () => 2000, cap);
  assert.equal(await big.send(entry("x", 1000, 500)), "unsaved");
  assert.ok(new QueueFullError() instanceof Error);
});

test("a send for the same id again reuses its slot, so a retry does not fill the queue", async () => {
  const store = new MemoryStore();
  const q = new ReviewQueue(store, async () => "retry", () => 2000, cap);
  for (let i = 0; i < 10; i++) assert.equal(await q.send(entry("same")), "queued");
  assert.equal(store.map.size, 1);
});

test("a failed IndexedDB write still tries the channel once; a miss reports unsaved so the form stays", async () => {
  let sent = 0;
  const ok = new ReviewQueue(new BrokenStore(), async () => { sent++; return "delivered"; }, () => 2000, cap);
  assert.equal(await ok.send(entry("a")), "delivered", "sent from memory, nothing to delete");
  const miss = new ReviewQueue(new BrokenStore(), async () => { sent++; return "retry"; }, () => 2000, cap);
  assert.equal(await miss.send(entry("a")), "unsaved");
  assert.equal(sent, 2);
});

test("with no channel the capture waits in the store", async () => {
  const store = new MemoryStore();
  const q = new ReviewQueue(store, null, () => 2000, cap);
  assert.equal(await q.send(entry("a")), "queued");
  assert.equal((await q.flush()).retry, 1);
  assert.equal(store.map.size, 1);
});

test("two flushes at once share one run", async () => {
  const store = new MemoryStore();
  await store.put(entry("a"));
  let calls = 0;
  const q = new ReviewQueue(store, async () => { calls++; await new Promise((r) => setTimeout(r, 10)); return "delivered"; }, () => 2000, cap);
  await Promise.all([q.flush(), q.flush(), q.flush()]);
  assert.equal(calls, 1);
});

test("an unreadable store does not throw out of flush or pending", async () => {
  const broken: QueueStore = { put: async () => {}, all: async () => { throw new Error("blocked"); }, remove: async () => {} };
  const q = new ReviewQueue(broken, async () => "delivered", () => 2000, cap);
  assert.deepEqual(await q.flush(), { delivered: 0, retry: 0, refused: 0, expired: 0 });
  assert.equal(await q.pending(), 0);
});
