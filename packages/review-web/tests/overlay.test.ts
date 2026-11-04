import { test } from "node:test";
import assert from "node:assert/strict";
import { MARKER, start } from "../src/overlay.ts";
import { MemoryStore } from "../src/queue.ts";
import { STRINGS, noticeMessage, pickLanguage, stringsFor } from "../src/strings.ts";
import { accept, canSend, isNeeded, isAccepted, type KV } from "../src/notice.ts";
import { page } from "./helpers.ts";

const base = { product: "fixture-app", hosts: ["test.example.com", "localhost"], store: new MemoryStore(), channel: { url: "http://localhost:1", key: "k" } };
const launchers = (doc: Document) => doc.querySelectorAll("[data-teyla-review]").length;

test("start does nothing without the flag, on a production host, or with no allow-list", async () => {
  const prod = page("<p>hi</p>", "https://www.example.com/");
  assert.equal(await start({ ...base, flag: "1", window: prod.w }), null, "production host");
  const test_ = page("<p>hi</p>");
  assert.equal(await start({ ...base, flag: undefined, window: test_.w }), null, "no flag");
  assert.equal(await start({ ...base, flag: "0", window: test_.w }), null, "flag 0");
  assert.equal(await start({ ...base, flag: "1", hosts: [], window: test_.w }), null, "no allow-list");
  assert.equal(launchers(prod.doc) + launchers(test_.doc), 0, "nothing was added to either page");
});

test("start on an allowed host draws one launcher carrying the marker, and destroy removes it", async () => {
  const p = page("<p>hi</p>");
  const h = await start({ ...base, flag: "1", window: p.w });
  assert.ok(h);
  assert.equal(launchers(p.doc), 1);
  assert.equal(p.doc.querySelector("[data-teyla-review]")?.getAttribute("data-teyla-review"), MARKER);
  h.destroy();
  assert.equal(launchers(p.doc), 0);
});

test("button: false draws a host but no Review button", async () => {
  const p = page("<p>hi</p>");
  const h = await start({ ...base, flag: "1", button: false, window: p.w });
  assert.equal(p.doc.querySelector("[data-teyla-review]")?.shadowRoot?.querySelector(".launch") ?? null, null);
  h?.destroy();
  const q = page("<p>hi</p>");
  const g = await start({ ...base, flag: "1", window: q.w });
  assert.ok(q.doc.querySelector("[data-teyla-review]")?.shadowRoot?.querySelector(".launch"));
  g?.destroy();
});

test("a product that is not a slug keeps review mode off", async () => {
  const p = page("<p>hi</p>");
  const warn = console.warn; console.warn = () => {};
  try { assert.equal(await start({ ...base, product: "My App", flag: "1", window: p.w }), null); } finally { console.warn = warn; }
  assert.equal(launchers(p.doc), 0);
});

test("en, ru and es have every key, and none is empty", () => {
  const keys = Object.keys(STRINGS.en).sort();
  assert.ok(keys.length > 30);
  for (const lang of ["ru", "es"] as const) {
    assert.deepEqual(Object.keys(STRINGS[lang]).sort(), keys, lang);
    for (const k of keys) assert.ok((STRINGS[lang] as unknown as Record<string, string>)[k]!.trim().length > 0, `${lang}.${k}`);
  }
  assert.match(STRINGS.ru.send, /[\u0400-\u04FF]/);
  assert.notEqual(STRINGS.es.send, STRINGS.en.send);
});

test("the English wording is the iOS wording where the two share a sentence", () => {
  assert.equal(STRINGS.en.noticeRecipient, "Who gets it: the developer of this app, through a review server. Nobody else.");
  assert.equal(STRINGS.en.noticeWhy, "Why: to find and fix what you pointed at.");
  assert.equal(STRINGS.en.previewCaption, "This picture is what is sent. Black boxes hide private areas.");
  assert.equal(STRINGS.en.wholeScreen, "About the whole screen");
  assert.equal(STRINGS.en.sentTitle, "Sent. Thank you!");
});

test("the language follows the browser, falls back to English, and a product may override a key", () => {
  assert.equal(pickLanguage("ru-RU"), "ru");
  assert.equal(pickLanguage("es_ES"), "es");
  assert.equal(pickLanguage("fr-FR"), "en");
  assert.equal(pickLanguage(undefined), "en");
  assert.equal(stringsFor("es", { send: "Mandar" }).send, "Mandar");
  assert.equal(stringsFor("es", { send: "Mandar" }).next, STRINGS.es.next);
  assert.equal(noticeMessage(STRINGS.en).split("\n\n").length, 4);
});

test("the first-send notice shows until it is accepted, and only when the capture can leave the browser", () => {
  const mem = new Map<string, string>();
  const kv: KV = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => void mem.set(k, v) };
  assert.equal(isNeeded(true, kv), true);
  assert.equal(isNeeded(false, kv), false);
  accept(kv);
  assert.equal(isAccepted(kv), true);
  assert.equal(isNeeded(true, kv), false);
  const broken: KV = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(isNeeded(true, broken), true, "storage that throws shows the notice again, and does not break Send");
  assert.doesNotThrow(() => accept(broken));
});

test("Send needs a comment, no save under way, and the health box when the product asks", () => {
  assert.equal(canSend("", false, false, false), false);
  assert.equal(canSend("   ", false, false, false), false);
  assert.equal(canSend("x", false, false, false), true);
  assert.equal(canSend("x", true, false, false), false);
  assert.equal(canSend("x", false, true, false), false);
  assert.equal(canSend("x", false, true, true), true);
});
