/** Captures that have not reached the channel wait here, in IndexedDB, with a cap, and go out again
 *  later. A capture is saved first and sent second; it is deleted only after the channel answered 200.
 *  If the save fails the sender still tries once from memory and the caller keeps the visible form. */
import type { ChannelResult } from "./channel.ts";

export interface QueueEntry {
  id: string;
  created: number;
  json: string;
  png: Blob;
  attempts: number;
  /** The channel will never take it (bad key, wrong product, too large). Kept so the words are not lost silently. */
  refused?: boolean;
}

export interface QueueStore {
  put(entry: QueueEntry): Promise<void>;
  all(): Promise<QueueEntry[]>;
  remove(id: string): Promise<void>;
}

export const CAP = { entries: 20, bytes: 40 * 1024 * 1024, ttlMs: 14 * 24 * 3600 * 1000 };

export class QueueFullError extends Error {
  constructor() { super("The review queue is full."); this.name = "QueueFullError"; }
}

export class MemoryStore implements QueueStore {
  readonly map = new Map<string, QueueEntry>();
  async put(e: QueueEntry) { this.map.set(e.id, e); }
  async all() { return [...this.map.values()]; }
  async remove(id: string) { this.map.delete(id); }
}

const sizeOf = (e: QueueEntry) => e.png.size + e.json.length;

export type Deliver = (e: QueueEntry) => Promise<ChannelResult>;
/** `delivered`: the channel has it. `queued`: it waits here. `unsaved`: it is nowhere but memory. */
export type SendOutcome = "delivered" | "queued" | "unsaved";

export class ReviewQueue {
  private flushing: Promise<FlushReport> | null = null;
  private readonly store: QueueStore;
  private readonly deliver: Deliver | null;
  private readonly now: () => number;
  private readonly cap: typeof CAP;
  constructor(store: QueueStore, deliver: Deliver | null, now: () => number = () => Date.now(), cap: typeof CAP = CAP) {
    this.store = store; this.deliver = deliver; this.now = now; this.cap = cap;
  }

  /** Save, then try once. Reuses the entry's slot when the same id is sent again (a retry). */
  async send(entry: QueueEntry): Promise<SendOutcome> {
    let saved = true;
    try { await this.save(entry); } catch { saved = false; }
    const result = this.deliver ? await this.deliver(entry) : "retry";
    if (result === "delivered") {
      if (saved) await this.store.remove(entry.id).catch(() => undefined);
      return "delivered";
    }
    if (!saved) return "unsaved";
    if (result === "refused") await this.store.put({ ...entry, refused: true, attempts: entry.attempts + 1 }).catch(() => undefined);
    else await this.store.put({ ...entry, attempts: entry.attempts + 1 }).catch(() => undefined);
    return "queued";
  }

  private async save(entry: QueueEntry): Promise<void> {
    const all = await this.store.all();
    const others = all.filter((e) => e.id !== entry.id);
    const bytes = others.reduce((n, e) => n + sizeOf(e), 0) + sizeOf(entry);
    if (others.length + 1 > this.cap.entries || bytes > this.cap.bytes) throw new QueueFullError();
    await this.store.put(entry);
  }

  /** Send everything that waits, oldest first. Two calls at once share one run. */
  flush(): Promise<FlushReport> {
    if (!this.flushing) this.flushing = this.run().finally(() => { this.flushing = null; });
    return this.flushing;
  }

  private async run(): Promise<FlushReport> {
    const report: FlushReport = { delivered: 0, retry: 0, refused: 0, expired: 0 };
    let all: QueueEntry[];
    try { all = (await this.store.all()).sort((a, b) => a.created - b.created); } catch { return report; }
    for (const e of all) {
      if (this.now() - e.created > this.cap.ttlMs) { await this.store.remove(e.id).catch(() => undefined); report.expired++; continue; }
      if (e.refused) continue;
      if (!this.deliver) { report.retry++; continue; }
      const r = await this.deliver(e);
      if (r === "delivered") { await this.store.remove(e.id).catch(() => undefined); report.delivered++; }
      else if (r === "refused") { await this.store.put({ ...e, refused: true }).catch(() => undefined); report.refused++; }
      else { report.retry++; await this.store.put({ ...e, attempts: e.attempts + 1 }).catch(() => undefined); }
    }
    return report;
  }

  async pending(): Promise<number> {
    try { return (await this.store.all()).filter((e) => !e.refused).length; } catch { return 0; }
  }
}

export interface FlushReport { delivered: number; retry: number; refused: number; expired: number }

/** IndexedDB, one object store keyed by id. Every call rejects when IndexedDB is missing or blocked
 *  (a private window, cleared site data): the queue treats that as "could not save". */
export class IdbStore implements QueueStore {
  private db: Promise<IDBDatabase> | null = null;
  private readonly name: string;
  private readonly factory: IDBFactory | undefined;
  constructor(name = "teyla-review", factory: IDBFactory | undefined = (globalThis as { indexedDB?: IDBFactory }).indexedDB) {
    this.name = name; this.factory = factory;
  }

  private open(): Promise<IDBDatabase> {
    if (!this.db) {
      const f = this.factory;
      this.db = new Promise((resolve, reject) => {
        if (!f) return reject(new Error("IndexedDB is not available"));
        let req: IDBOpenDBRequest;
        try { req = f.open(this.name, 1); } catch (e) { return reject(e); }
        req.onupgradeneeded = () => { req.result.createObjectStore("captures", { keyPath: "id" }); };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error ?? new Error("IndexedDB open failed"));
        req.onblocked = () => reject(new Error("IndexedDB is blocked"));
      });
      this.db.catch(() => { this.db = null; }); // try to open again next time
    }
    return this.db;
  }

  private async tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
    const db = await this.open();
    return new Promise<T>((resolve, reject) => {
      const t = db.transaction("captures", mode);
      const r = run(t.objectStore("captures"));
      let value: T;
      r.onsuccess = () => { value = r.result; };
      t.oncomplete = () => resolve(value);
      t.onerror = () => reject(t.error ?? new Error("IndexedDB write failed"));
      t.onabort = () => reject(t.error ?? new Error("IndexedDB write aborted"));
    });
  }

  async put(e: QueueEntry) { await this.tx("readwrite", (s) => s.put(e)); }
  async all() { return (await this.tx("readonly", (s) => s.getAll())) as QueueEntry[]; }
  async remove(id: string) { await this.tx("readwrite", (s) => s.delete(id)); }
}
