/** The form: a launcher button and the review dialog, drawn in a shadow root so the page's styles
 *  cannot reach it and its styles cannot reach the page. Every word is set with `textContent`. */
import type { Rect } from "./format.ts";
import { canSend } from "./notice.ts";
import { noticeMessage, type ReviewStrings } from "./strings.ts";

export type SendResult = "sent" | "saved" | "unsaved";

export interface FormModel {
  strings: ReviewStrings;
  pictureUrl: string;
  viewport: { width: number; height: number };
  speech: boolean;
  requiresHealthConsent: boolean;
  sendsToServer: boolean;
  noticeNeeded(): boolean;
  acceptNotice(): void;
  onSend(draft: { tap?: { x: number; y: number }; region?: Rect; text: string; input: "text" | "speech" }): Promise<SendResult>;
  onClose(): void;
}

const CSS = `
:host { all: initial; }
* { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.launch { position: fixed; left: 12px; bottom: 12px; z-index: 2147483646; pointer-events: auto; min-height: 36px; padding: 0 14px;
  border-radius: 18px; border: 1px solid rgba(0,0,0,.25); background: #1f2937; color: #fff; font-size: 13px; cursor: pointer; opacity: .85; }
.launch:hover, .launch:focus-visible { opacity: 1; }
.backdrop { position: fixed; inset: 0; z-index: 2147483647; pointer-events: auto; display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,.6); padding: 16px; }
.card { width: min(720px, 100%); max-height: 100%; overflow: auto; border-radius: 14px; padding: 16px; background: #fff; color: #111827; }
.card h2 { margin: 0 0 4px; font-size: 17px; } .card h3 { margin: 0 0 4px; font-size: 16px; }
.card p { margin: 0 0 10px; font-size: 14px; line-height: 1.4; }
.pic { position: relative; width: 100%; max-height: 46vh; margin: 8px auto; border: 2px solid #4b5563; border-radius: 6px; overflow: hidden; cursor: crosshair; touch-action: none; user-select: none; }
.pic img { display: block; width: 100%; height: 100%; object-fit: fill; pointer-events: none; }
.mark { position: absolute; border: 2px solid #ef4444; background: rgba(239,68,68,.18); pointer-events: none; }
.mark.dot { width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%; }
textarea { width: 100%; min-height: 96px; padding: 8px; border: 1px solid #9ca3af; border-radius: 8px; font-size: 15px; resize: vertical; background: #fff; color: #111827; }
.row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
button.b { min-height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid #9ca3af; background: #f3f4f6; color: #111827; font-size: 15px; cursor: pointer; }
button.b.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
button.b:disabled { opacity: .45; cursor: not-allowed; }
.caption { color: #4b5563; font-size: 12px !important; }
.error { color: #b91c1c; }
label.health { display: flex; gap: 8px; align-items: flex-start; font-size: 14px; margin: 8px 0; }
.notice { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.6); padding: 16px; }
.notice .card { width: min(520px, 100%); } .notice .card p { white-space: pre-line; }
[hidden] { display: none !important; }
button:focus-visible, textarea:focus-visible, input:focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
@media (prefers-color-scheme: dark) {
  .card { background: #111827; color: #f9fafb; } textarea { background: #1f2937; color: #f9fafb; border-color: #4b5563; }
  button.b { background: #1f2937; color: #f9fafb; border-color: #4b5563; } .caption { color: #9ca3af; } .error { color: #fca5a5; }
}
`;

type Child = Node | string | null | undefined;
function h<K extends keyof HTMLElementTagNameMap>(doc: Document, tag: K, props: Record<string, string> = {}, ...kids: Child[]): HTMLElementTagNameMap[K] {
  const el = doc.createElement(tag);
  for (const [k, v] of Object.entries(props)) el.setAttribute(k, v);
  for (const c of kids) if (c != null) el.append(typeof c === "string" ? doc.createTextNode(c) : c);
  return el;
}

export function addStyle(root: ShadowRoot): void {
  const style = root.ownerDocument.createElement("style");
  style.textContent = CSS;
  root.append(style);
}

export function createLauncher(root: ShadowRoot, label: string, onClick: () => void): HTMLButtonElement {
  const b = h(root.ownerDocument, "button", { type: "button", class: "launch" }, label);
  b.addEventListener("click", onClick);
  root.append(b);
  return b;
}

/** A dialog with one message and one button, for "could not take a picture". */
export function showMessage(root: ShadowRoot, strings: ReviewStrings, message: string, onClose: () => void): () => void {
  const d = root.ownerDocument;
  const ok = h(d, "button", { type: "button", class: "b primary" }, strings.done);
  const wrap = h(d, "div", { class: "backdrop", role: "alertdialog", "aria-modal": "true" },
    h(d, "div", { class: "card" }, h(d, "h2", {}, strings.modeTitle), h(d, "p", { role: "alert" }, message), h(d, "div", { class: "row" }, ok)));
  const close = () => { wrap.remove(); onClose(); };
  ok.addEventListener("click", close);
  wrap.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Escape") close(); });
  root.append(wrap);
  ok.focus();
  return close;
}

interface SpeechRec {
  lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: (() => void) | null; onend: (() => void) | null;
}

export function speechCtor(win: Window): (new () => SpeechRec) | null {
  const w = win as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function openForm(root: ShadowRoot, model: FormModel): () => void {
  const d = root.ownerDocument;
  const win = d.defaultView as Window;
  const s = model.strings;
  let step: "pick" | "comment" | "done" = "pick";
  let tap: { x: number; y: number } | undefined;
  let region: Rect | undefined;
  let input: "text" | "speech" = "text";
  let sending = false;
  let healthOk = false;
  let failure: string | null = null;
  let listening: SpeechRec | null = null;

  const title = h(d, "h2", { id: "teyla-review-title" }, s.modeTitle);
  const hint = h(d, "p", {}, s.modeHint);
  const img = h(d, "img", { alt: "", src: model.pictureUrl });
  const mark = h(d, "div", { class: "mark", hidden: "" });
  const pic = h(d, "div", { class: "pic" }, img, mark);
  pic.style.aspectRatio = `${model.viewport.width} / ${model.viewport.height}`;

  const whole = h(d, "button", { type: "button", class: "b" }, s.wholeScreen);
  const next = h(d, "button", { type: "button", class: "b primary", disabled: "" }, s.next);
  const exit = h(d, "button", { type: "button", class: "b" }, s.exit);
  const pickRow = h(d, "div", { class: "row" }, whole, next, exit);

  const text = h(d, "textarea", { id: "teyla-review-text", "aria-label": s.commentTitle, placeholder: s.placeholder, maxlength: "8000", rows: "4" });
  const listenNote = h(d, "p", { class: "caption", role: "status", hidden: "" }, s.listening);
  const dictate = h(d, "button", { type: "button", class: "b" }, s.dictate);
  const caption = h(d, "p", { class: "caption" }, s.previewCaption);
  const health = h(d, "input", { type: "checkbox", id: "teyla-review-health" });
  const healthRow = h(d, "label", { class: "health", for: "teyla-review-health" }, health, s.healthConsent);
  const error = h(d, "p", { class: "error", role: "alert", hidden: "" });
  const back = h(d, "button", { type: "button", class: "b" }, s.back);
  const send = h(d, "button", { type: "button", class: "b primary", disabled: "" }, s.send);
  const exit2 = h(d, "button", { type: "button", class: "b" }, s.exit);
  const commentBox = h(d, "div", {}, text, listenNote, caption, healthRow, error, h(d, "div", { class: "row" }, back, send, dictate, exit2));

  const doneTitle = h(d, "h3", {});
  const doneText = h(d, "p", {});
  const doneBtn = h(d, "button", { type: "button", class: "b primary" }, s.done);
  const doneBox = h(d, "div", { role: "status" }, doneTitle, doneText, h(d, "div", { class: "row" }, doneBtn));

  const noticeOK = h(d, "button", { type: "button", class: "b primary" }, s.noticeOK);
  const noticeCancel = h(d, "button", { type: "button", class: "b" }, s.noticeCancel);
  const notice = h(d, "div", { class: "notice", role: "dialog", "aria-modal": "true", hidden: "" },
    h(d, "div", { class: "card" }, h(d, "h2", {}, s.noticeTitle), h(d, "p", {}, noticeMessage(s)), h(d, "div", { class: "row" }, noticeOK, noticeCancel)));

  const card = h(d, "div", { class: "card" }, title, hint, pic, pickRow, commentBox, doneBox);
  const wrap = h(d, "div", { class: "backdrop", role: "dialog", "aria-modal": "true", "aria-labelledby": "teyla-review-title" }, card, notice);
  root.append(wrap);

  const Rec = model.speech ? speechCtor(win) : null;
  if (!Rec) dictate.hidden = true;
  if (!model.requiresHealthConsent) healthRow.hidden = true;

  const close = () => { stopListening(); wrap.remove(); model.onClose(); };

  function stopListening() { try { listening?.stop(); } catch { /* already stopped */ } listening = null; }

  function showError(msg: string | null) { failure = msg; error.hidden = msg === null; error.textContent = msg ?? ""; refresh(); }

  function refresh() {
    pickRow.hidden = step !== "pick";
    commentBox.hidden = step !== "comment";
    doneBox.hidden = step !== "done";
    next.disabled = !(tap || region);
    hint.textContent = step === "pick" ? (region ? s.areaChosen : tap ? s.spotChosen : s.modeHint) : "";
    hint.hidden = step !== "pick";
    title.textContent = step === "comment" ? s.commentTitle : s.modeTitle;
    listenNote.hidden = listening === null;
    send.textContent = sending ? s.saving : failure === null ? s.send : s.retry;
    send.disabled = !canSend(text.value, sending, model.requiresHealthConsent, healthOk);
    pic.style.cursor = step === "pick" ? "crosshair" : "default";
  }

  function drawMark() {
    const W = model.viewport.width, H = model.viewport.height;
    mark.hidden = !(tap || region);
    if (region) {
      mark.className = "mark";
      Object.assign(mark.style, { left: `${(region.x / W) * 100}%`, top: `${(region.y / H) * 100}%`, width: `${(region.width / W) * 100}%`, height: `${(region.height / H) * 100}%`, margin: "0" });
    } else if (tap) {
      mark.className = "mark dot";
      Object.assign(mark.style, { left: `${(tap.x / W) * 100}%`, top: `${(tap.y / H) * 100}%`, width: "", height: "", margin: "" });
    }
  }

  // Click picks a spot, drag picks an area. Coordinates are mapped from the shrunk picture back to the viewport.
  let down: { x: number; y: number } | null = null;
  const toViewport = (cx: number, cy: number) => {
    const r = pic.getBoundingClientRect();
    const x = Math.min(Math.max((cx - r.left) / r.width, 0), 1) * model.viewport.width;
    const y = Math.min(Math.max((cy - r.top) / r.height, 0), 1) * model.viewport.height;
    return { x, y };
  };
  pic.addEventListener("pointerdown", (e) => {
    if (step !== "pick") return;
    down = { x: e.clientX, y: e.clientY };
    try { pic.setPointerCapture(e.pointerId); } catch { /* not every pointer can be captured */ }
  });
  pic.addEventListener("pointermove", (e) => {
    if (!down || step !== "pick") return;
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) < 8) return;
    const a = toViewport(down.x, down.y), b = toViewport(e.clientX, e.clientY);
    region = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
    tap = { x: region.x + region.width / 2, y: region.y + region.height / 2 };
    drawMark(); refresh();
  });
  pic.addEventListener("pointerup", (e) => {
    if (!down || step !== "pick") { down = null; return; }
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) < 8) { tap = toViewport(e.clientX, e.clientY); region = undefined; }
    down = null; drawMark(); refresh();
  });
  pic.addEventListener("pointercancel", () => { down = null; });

  const goComment = () => { step = "comment"; refresh(); text.focus(); };
  whole.addEventListener("click", () => { tap = undefined; region = undefined; drawMark(); goComment(); });
  next.addEventListener("click", goComment);
  back.addEventListener("click", () => { stopListening(); step = "pick"; showError(null); });
  exit.addEventListener("click", close);
  exit2.addEventListener("click", close);
  doneBtn.addEventListener("click", close);
  text.addEventListener("input", () => { refresh(); });
  health.addEventListener("change", () => { healthOk = health.checked; refresh(); });
  wrap.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key !== "Escape") return;
    if (!notice.hidden) { notice.hidden = true; return; }
    close();
  });

  dictate.addEventListener("click", () => {
    if (!Rec) return;
    if (listening) { stopListening(); refresh(); return; }
    try {
      const r = new Rec();
      r.lang = win.navigator.language || "en";
      r.interimResults = false;
      r.continuous = true;
      r.onresult = (e) => {
        for (let i = 0; i < e.results.length; i++) {
          const res = e.results[i];
          if (res && res.isFinal && res[0]) { text.value = (text.value ? text.value + " " : "") + res[0].transcript.trim(); input = "speech"; }
        }
        refresh();
      };
      r.onerror = () => { listening = null; showError(s.microphoneUnavailable); };
      r.onend = () => { listening = null; refresh(); };
      listening = r;
      r.start();
      refresh();
    } catch { listening = null; showError(s.microphoneUnavailable); }
  });

  async function doSend() {
    if (!canSend(text.value, sending, model.requiresHealthConsent, healthOk)) return;
    sending = true; refresh();
    stopListening();
    let result: SendResult;
    try {
      result = await model.onSend({ ...(tap ? { tap } : {}), ...(region ? { region } : {}), text: text.value, input });
    } catch {
      result = "unsaved";
    }
    sending = false;
    if (result === "unsaved") { showError(s.saveFailed); return; }
    showError(null);
    step = "done";
    doneTitle.textContent = result === "sent" ? s.sentTitle : s.savedTitle;
    doneText.textContent = result === "sent" ? s.sentDetail : s.savedDetail;
    refresh();
    doneBtn.focus();
  }

  send.addEventListener("click", () => {
    if (!canSend(text.value, sending, model.requiresHealthConsent, healthOk)) return;
    if (model.sendsToServer && model.noticeNeeded()) { notice.hidden = false; noticeOK.focus(); return; }
    void doSend();
  });
  noticeOK.addEventListener("click", () => { model.acceptNotice(); notice.hidden = true; void doSend(); });
  noticeCancel.addEventListener("click", () => { notice.hidden = true; });

  refresh();
  whole.focus();
  return close;
}
