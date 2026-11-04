/** Pixel work that needs no canvas, so the tests run in Node: painting private areas black and
 *  finding a picture that came out empty. Rectangles are in CSS pixels with the origin at the top
 *  left of the viewport, the way a capture states them. Port of ReviewBitmap.swift. */
import type { Rect } from "./format.ts";

/** RGBA, 8 bits per channel, rows from the top. The shape of a canvas `ImageData`. */
export interface Pixels { width: number; height: number; data: Uint8ClampedArray | Uint8Array }

/** A rectangle that is not a finite number is a view that lost its place. */
export function isFiniteRect(r: Rect): boolean {
  return [r.x, r.y, r.width, r.height].every((n) => Number.isFinite(n));
}

/** Paint every rectangle solid black (alpha 255), grown outward to whole pixels. A rectangle that
 *  cannot be placed hides the whole picture: a mask that cannot be placed fails towards hiding. */
export function blackOut(px: Pixels, rects: readonly Rect[], scale: number): void {
  const fill = (x0: number, y0: number, x1: number, y1: number) => {
    const xa = Math.max(0, x0), xb = Math.min(px.width, x1), ya = Math.max(0, y0), yb = Math.min(px.height, y1);
    for (let y = ya; y < yb; y++) {
      for (let x = xa; x < xb; x++) {
        const i = (y * px.width + x) * 4;
        px.data[i] = 0; px.data[i + 1] = 0; px.data[i + 2] = 0; px.data[i + 3] = 255;
      }
    }
  };
  for (const r of rects) {
    if (!isFiniteRect(r) || !(scale > 0)) { fill(0, 0, px.width, px.height); continue; }
    fill(Math.floor(r.x * scale), Math.floor(r.y * scale), Math.ceil((r.x + r.width) * scale), Math.ceil((r.y + r.height) * scale));
  }
}

/** The share of sampled pixels in `rect` that are one colour: the most common colour, each channel
 *  rounded to steps of 8, over a grid of at most 48 by 48 samples. A transparent pixel is one colour
 *  whatever its other channels say. 1 means nothing was drawn there. */
export function emptyFraction(px: Pixels, rect: Rect, scale: number): number {
  const x0 = Math.max(0, Math.floor(rect.x * scale)), x1 = Math.min(px.width, Math.ceil((rect.x + rect.width) * scale));
  const y0 = Math.max(0, Math.floor(rect.y * scale)), y1 = Math.min(px.height, Math.ceil((rect.y + rect.height) * scale));
  if (x1 <= x0 || y1 <= y0) return 0;
  const cols = Math.min(48, x1 - x0), rows = Math.min(48, y1 - y0);
  const counts = new Map<number, number>();
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = x0 + Math.floor(((x1 - x0 - 1) * c) / Math.max(cols - 1, 1));
      const y = y0 + Math.floor(((y1 - y0 - 1) * r) / Math.max(rows - 1, 1));
      const i = (y * px.width + x) * 4;
      const key = (px.data[i + 3] ?? 0) === 0 ? -1 : (((px.data[i] ?? 0) >> 3) << 16) | (((px.data[i + 1] ?? 0) >> 3) << 8) | ((px.data[i + 2] ?? 0) >> 3);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  let best = 0;
  for (const n of counts.values()) best = Math.max(best, n);
  return best / (cols * rows);
}

/** At or above this share of one colour a region counts as blank. */
export const BLANK_LIMIT = 0.995;

export function isBlank(px: Pixels, rect: Rect, scale: number): boolean {
  return emptyFraction(px, rect, scale) >= BLANK_LIMIT;
}

/** A single-colour picture is a failed render only when the page has something to draw. An empty
 *  white page is a white picture, and that is correct. */
export function renderFailed(px: Pixels, viewport: Rect, scale: number, pageHasContent: boolean): boolean {
  return pageHasContent && isBlank(px, viewport, scale);
}
