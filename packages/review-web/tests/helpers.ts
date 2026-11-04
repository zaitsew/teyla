import { Window } from "happy-dom";
import type { Rect } from "../src/format.ts";

/** A page with a viewport, the way the tests need it. Layout does not exist in happy-dom, so a test
 *  states each element's box with `place`. */
export function page(html: string, url = "https://test.example.com/app") {
  const win = new Window({ url, width: 1000, height: 800 });
  win.document.body.innerHTML = html;
  return { win, doc: win.document as unknown as Document, w: win as unknown as globalThis.Window };
}

export function place(el: Element | null, r: Rect): void {
  if (!el) throw new Error("element not found");
  (el as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = () => ({
    x: r.x, y: r.y, width: r.width, height: r.height, left: r.x, top: r.y, right: r.x + r.width, bottom: r.y + r.height,
  });
}

export const rect = (x: number, y: number, width: number, height: number): Rect => ({ x, y, width, height });

/** A canvas of one colour that holds its pixels in memory. */
export function fakeCanvas(width: number, height: number, rgba: [number, number, number, number], pngBytes = 1000) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) { data[i] = rgba[0]; data[i + 1] = rgba[1]; data[i + 2] = rgba[2]; data[i + 3] = rgba[3]; }
  const px = { width, height, data };
  return {
    width, height, px,
    getContext: () => ({ getImageData: () => px, putImageData: (p: typeof px) => { px.data = p.data; } }),
    toBlob: (cb: (b: Blob | null) => void) => cb(new Blob([new Uint8Array(pngBytes)], { type: "image/png" })),
  };
}

/** Same, with a gradient so it is not one colour. */
export function busyCanvas(width: number, height: number, pngBytes = 1000) {
  const c = fakeCanvas(width, height, [0, 0, 0, 255], pngBytes);
  for (let i = 0; i < c.px.data.length; i += 4) { const p = i / 4; c.px.data[i] = p % 256; c.px.data[i + 1] = (p * 7) % 256; c.px.data[i + 2] = (p * 13) % 256; }
  return c;
}
