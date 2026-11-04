import { test } from "node:test";
import assert from "node:assert/strict";
import { isAlwaysPrivate, privateFrames } from "../src/anchors.ts";
import { maskClone } from "../src/mask.ts";
import { BLANK_LIMIT, blackOut, emptyFraction, isBlank, renderFailed, type Pixels } from "../src/pixels.ts";
import { page, place, rect } from "./helpers.ts";

function white(w: number, h: number): Pixels {
  const data = new Uint8ClampedArray(w * h * 4).fill(255);
  return { width: w, height: h, data };
}
const at = (p: Pixels, x: number, y: number) => Array.from(p.data.slice((y * p.width + x) * 4, (y * p.width + x) * 4 + 4));

test("a private rectangle is painted black, edges grown outward to whole pixels", () => {
  const p = white(20, 10);
  blackOut(p, [rect(2.2, 1.2, 3.1, 2.1)], 1); // covers x 2..5, y 1..3 after growing
  assert.deepEqual(at(p, 2, 1), [0, 0, 0, 255]);
  assert.deepEqual(at(p, 5, 3), [0, 0, 0, 255]);
  assert.deepEqual(at(p, 6, 1), [255, 255, 255, 255]);
  assert.deepEqual(at(p, 1, 1), [255, 255, 255, 255]);
  assert.deepEqual(at(p, 2, 4), [255, 255, 255, 255]);
});

test("the scale maps CSS pixels to picture pixels", () => {
  const p = white(40, 20);
  blackOut(p, [rect(5, 5, 5, 5)], 2); // x 10..20, y 10..20
  assert.deepEqual(at(p, 10, 10), [0, 0, 0, 255]);
  assert.deepEqual(at(p, 19, 19), [0, 0, 0, 255]);
  assert.deepEqual(at(p, 20, 10), [255, 255, 255, 255]);
});

test("a rectangle that cannot be placed hides the whole picture", () => {
  for (const bad of [rect(NaN, 0, 10, 10), rect(0, 0, Infinity, 10)]) {
    const p = white(8, 8);
    blackOut(p, [bad], 1);
    assert.deepEqual(at(p, 0, 0), [0, 0, 0, 255]);
    assert.deepEqual(at(p, 7, 7), [0, 0, 0, 255]);
  }
  const q = white(8, 8);
  blackOut(q, [rect(1, 1, 2, 2)], 0); // a scale that is not positive is also "cannot be placed"
  assert.deepEqual(at(q, 7, 7), [0, 0, 0, 255]);
});

test("a rectangle outside the picture paints nothing and does not throw", () => {
  const p = white(10, 10);
  blackOut(p, [rect(100, 100, 5, 5), rect(-50, -50, 10, 10)], 1);
  assert.deepEqual(at(p, 0, 0), [255, 255, 255, 255]);
});

test("a single-colour picture is blank, a busy one is not", () => {
  const view = rect(0, 0, 100, 100);
  const flat = white(100, 100);
  assert.equal(isBlank(flat, view, 1), true);
  assert.equal(emptyFraction(flat, view, 1), 1);
  const busy = white(100, 100);
  for (let i = 0; i < busy.data.length; i += 4) { busy.data[i] = (i / 4) % 256; busy.data[i + 1] = ((i / 4) * 5) % 256; }
  assert.equal(isBlank(busy, view, 1), false);
  assert.ok(BLANK_LIMIT > 0.99);
});

test("a fully transparent picture is blank whatever its colour channels hold", () => {
  const p = white(50, 50);
  for (let i = 3; i < p.data.length; i += 4) p.data[i] = 0;
  assert.equal(isBlank(p, rect(0, 0, 50, 50), 1), true);
});

test("a white picture of an empty page is not a failed render, of a page with content it is", () => {
  const v = rect(0, 0, 100, 100);
  assert.equal(renderFailed(white(100, 100), v, 1, false), false);
  assert.equal(renderFailed(white(100, 100), v, 1, true), true);
});

test("data-review-private elements and password inputs have frames; others do not", () => {
  const { doc } = page(`
    <p id="plain">name</p>
    <div id="p1" data-review-private>secret</div>
    <input id="pw" type="password" value="x">
    <input id="pw2" type="PASSWORD">
    <input id="cc" autocomplete="cc-number">
    <input id="otp" autocomplete="one-time-code">
    <input id="txt" type="text">
    <div id="gone" data-review-private></div>`);
  place(doc.getElementById("plain"), rect(0, 0, 50, 10));
  place(doc.getElementById("p1"), rect(10, 20, 100, 30));
  place(doc.getElementById("pw"), rect(10, 60, 100, 20));
  place(doc.getElementById("pw2"), rect(10, 90, 100, 20));
  place(doc.getElementById("cc"), rect(10, 120, 100, 20));
  place(doc.getElementById("otp"), rect(10, 150, 100, 20));
  place(doc.getElementById("txt"), rect(10, 180, 100, 20));
  const frames = privateFrames(doc, 1000, 800);
  assert.equal(frames.length, 5, "the plain text and the text input are not private; the box-less one draws nothing");
  assert.deepEqual(frames[0], rect(8, 18, 104, 34), "a 2 px margin on each side");
  assert.equal(isAlwaysPrivate(doc.getElementById("pw")!), true);
  assert.equal(isAlwaysPrivate(doc.getElementById("txt")!), false);
});

test("a private element with no box of its own is covered through its children", () => {
  const { doc } = page(`<div id="wrap" data-review-private style="display:contents"><span id="a">1</span><span id="b">2</span></div>`);
  place(doc.getElementById("wrap"), rect(0, 0, 0, 0));
  place(doc.getElementById("a"), rect(10, 10, 20, 10));
  place(doc.getElementById("b"), rect(40, 30, 20, 10));
  assert.deepEqual(privateFrames(doc, 1000, 800), [rect(8, 8, 54, 34)]);
});

test("a private element off screen has no frame; one whose box is not a number keeps one", () => {
  const { doc } = page(`<div id="off" data-review-private>x</div><div id="nan" data-review-private>y</div>`);
  place(doc.getElementById("off"), rect(0, 5000, 10, 10));
  place(doc.getElementById("nan"), rect(NaN, 0, 10, 10));
  const frames = privateFrames(doc, 1000, 800);
  assert.equal(frames.length, 1);
  assert.ok(Number.isNaN(frames[0]?.x));
  const p = white(10, 10);
  blackOut(p, frames, 1);
  assert.deepEqual(at(p, 5, 5), [0, 0, 0, 255], "and the painter hides everything for it");
});

test("a cloned private element is a black box with nothing readable in it", () => {
  const { doc } = page(`<div id="s" data-review-private>Account 1234<b>more</b></div><input id="pw" type="password" value="hunter2" placeholder="Password"><p id="ok">visible</p>`);
  const priv = doc.getElementById("s")!.cloneNode(true) as HTMLElement;
  maskClone(priv);
  assert.match(priv.getAttribute("style") ?? "", /background-color:\s*#000/);
  assert.equal(priv.firstChild?.textContent, "", "the text node is emptied");
  assert.match(priv.querySelector("b")!.getAttribute("style") ?? "", /visibility:\s*hidden/);
  const pw = doc.getElementById("pw")!.cloneNode(true) as HTMLInputElement;
  maskClone(pw);
  assert.equal(pw.getAttribute("value"), null);
  assert.equal(pw.getAttribute("placeholder"), null);
  assert.match(pw.getAttribute("style") ?? "", /background-color:\s*#000/);
  const plain = doc.getElementById("ok")!.cloneNode(true) as HTMLElement;
  maskClone(plain);
  assert.equal(plain.getAttribute("style"), null);
  assert.equal(plain.textContent, "visible");
});
