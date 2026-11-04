import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS } from "../src/strings.ts";
import { addStyle, openForm, type FormModel, type SendResult } from "../src/ui.ts";
import { page } from "./helpers.ts";

function mount(over: Partial<FormModel> = {}) {
  const p = page("<p>hi</p>");
  const host = p.doc.createElement("div");
  p.doc.body.append(host);
  const root = host.attachShadow({ mode: "open" });
  addStyle(root);
  const sent: unknown[] = [];
  let accepted = false;
  let closed = 0;
  const model: FormModel = {
    strings: STRINGS.en, pictureUrl: "blob:x", viewport: { width: 100, height: 50 }, speech: false,
    requiresHealthConsent: false, sendsToServer: true, noticeNeeded: () => !accepted, acceptNotice: () => { accepted = true; },
    onSend: async (d) => { sent.push(d); return "sent"; }, onClose: () => { closed++; }, ...over,
  };
  openForm(root, model);
  const $ = (sel: string) => root.querySelector(sel) as HTMLElement;
  const button = (label: string) => Array.from(root.querySelectorAll("button")).find((b) => b.textContent === label) as HTMLButtonElement;
  const type = (v: string) => { const t = $("textarea") as HTMLTextAreaElement; t.value = v; t.dispatchEvent(new p.win.Event("input") as unknown as Event); };
  return { root, $, button, type, sent, closed: () => closed, accepted: () => accepted };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the whole-screen button opens the comment step; Send waits for a comment", async () => {
  const f = mount();
  f.button("About the whole screen").click();
  assert.equal(f.button("Send").disabled, true);
  f.type("The header overlaps the menu.");
  assert.equal(f.button("Send").disabled, false);
});

test("the first Send shows the notice; Cancel sends nothing; OK sends once", async () => {
  const f = mount();
  f.button("About the whole screen").click();
  f.type("x");
  f.button("Send").click();
  assert.equal((f.$(".notice") as HTMLElement).hidden, false);
  assert.equal(f.sent.length, 0);
  f.button("Cancel").click();
  assert.equal(f.sent.length, 0);
  f.button("Send").click();
  f.button("OK, send").click();
  await tick();
  assert.equal(f.sent.length, 1);
  assert.equal(f.accepted(), true);
  assert.match(f.root.textContent ?? "", /Sent\. Thank you!/);
});

test("with the notice accepted, Send goes straight out and a queued capture says it was saved", async () => {
  const f = mount({ noticeNeeded: () => false, onSend: async (): Promise<SendResult> => "saved" });
  f.button("About the whole screen").click();
  f.type("x");
  f.button("Send").click();
  await tick();
  assert.match(f.root.textContent ?? "", /Saved in this browser/);
});

test("a failed save keeps the form, the words and the error, and turns Send into Retry", async () => {
  let calls = 0;
  const f = mount({ noticeNeeded: () => false, onSend: async (): Promise<SendResult> => (++calls === 1 ? "unsaved" : "sent") });
  f.button("About the whole screen").click();
  f.type("My words must survive.");
  f.button("Send").click();
  await tick();
  assert.equal((f.$("textarea") as HTMLTextAreaElement).value, "My words must survive.");
  assert.equal((f.$(".error") as HTMLElement).hidden, false);
  assert.match(f.$(".error").textContent ?? "", /Could not save the capture in this browser/);
  const retry = f.button("Retry");
  assert.ok(retry);
  retry.click();
  await tick();
  assert.equal(calls, 2);
  assert.match(f.root.textContent ?? "", /Sent\. Thank you!/);
});

test("a send that throws is treated as a failed save, not as a lost form", async () => {
  const f = mount({ noticeNeeded: () => false, onSend: async () => { throw new Error("boom"); } });
  f.button("About the whole screen").click();
  f.type("keep me");
  f.button("Send").click();
  await tick();
  assert.equal((f.$("textarea") as HTMLTextAreaElement).value, "keep me");
  assert.ok(f.button("Retry"));
});

test("the health box must be ticked before Send, when the product asks", async () => {
  const f = mount({ requiresHealthConsent: true, noticeNeeded: () => false });
  f.button("About the whole screen").click();
  f.type("x");
  assert.equal(f.button("Send").disabled, true);
  const box = f.$("#teyla-review-health") as HTMLInputElement;
  box.checked = true;
  box.dispatchEvent(new (box.ownerDocument.defaultView as unknown as { Event: typeof Event }).Event("change"));
  assert.equal(f.button("Send").disabled, false);
  const plain = mount();
  assert.equal((plain.$(".health") as HTMLElement).hidden, true, "no health box unless asked");
});

test("no dictate button without Web Speech, and Exit closes", () => {
  const f = mount({ speech: true });
  f.button("About the whole screen").click();
  assert.equal(f.button("Dictate").hidden, true, "happy-dom has no SpeechRecognition");
  f.button("Exit").click();
  assert.equal(f.closed(), 1);
});
