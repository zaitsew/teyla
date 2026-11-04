/** The picture: `modern-screenshot` first, `getDisplayMedia` when it fails or yields a blank image.
 *  Private areas are painted black on the finished pixels, whichever way the picture was taken. */
import { privateFrames } from "./anchors.ts";
import type { Rect } from "./format.ts";
import { maskClone } from "./mask.ts";
import { blackOut, renderFailed, type Pixels } from "./pixels.ts";

/** What this file needs from a canvas, so the control flow runs in Node with a fake. */
export interface CanvasLike {
  width: number;
  height: number;
  getContext(kind: "2d"): { getImageData(x: number, y: number, w: number, h: number): Pixels; putImageData(p: Pixels, x: number, y: number): void } | null;
  toBlob(cb: (b: Blob | null) => void, type?: string): void;
}

export interface Picture {
  blob: Blob;
  pixelWidth: number;
  pixelHeight: number;
  /** Pixels per CSS pixel, at least 1. */
  scale: number;
  via: "dom" | "display";
  /** The rectangles painted black, CSS pixels. */
  frames: Rect[];
}

export type PictureErrorCode = "failed" | "blank" | "mask-unplaceable" | "too-large";
export class PictureError extends Error {
  readonly code: PictureErrorCode;
  constructor(code: PictureErrorCode, message?: string) { super(message ?? code); this.name = "PictureError"; this.code = code; }
}

export interface Viewport { width: number; height: number; scrollX: number; scrollY: number; dpr: number }

export interface PictureDeps {
  viewport: Viewport;
  frames: Rect[];
  pageHasContent: boolean;
  /** modern-screenshot of the page at `scale`. */
  renderDom(scale: number): Promise<CanvasLike>;
  /** One frame of this tab from getDisplayMedia, and whether it is certain to show this page. */
  grabDisplay(): Promise<{ canvas: CanvasLike; sameViewport: boolean }>;
  /** Largest PNG the channel takes (10 MiB), minus a margin. */
  maxBytes?: number;
}

const MAX_PNG = 9.5 * 1024 * 1024;

function toBlob(c: CanvasLike): Promise<Blob> {
  return new Promise((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new PictureError("failed", "toBlob gave nothing"))), "image/png"));
}

function pixelsOf(c: CanvasLike): { px: Pixels; put: (p: Pixels) => void } {
  const ctx = c.getContext("2d");
  if (!ctx) throw new PictureError("failed", "no 2d context");
  return { px: ctx.getImageData(0, 0, c.width, c.height), put: (p) => ctx.putImageData(p, 0, 0) };
}

/** Finish a canvas: refuse a blank render, paint the private areas, encode. Used for both routes. */
async function finish(c: CanvasLike, d: PictureDeps, via: Picture["via"], sameViewport: boolean): Promise<Picture> {
  const { viewport: v, frames } = d;
  const scale = Math.max(1, c.width / v.width);
  const { px, put } = pixelsOf(c);
  if (renderFailed(px, { x: 0, y: 0, width: v.width, height: v.height }, c.width / v.width, d.pageHasContent)) throw new PictureError("blank");
  // A frame that may show some other page or another part of the screen cannot take a mask by position.
  if (!sameViewport && frames.length > 0) throw new PictureError("mask-unplaceable");
  blackOut(px, frames, c.width / v.width);
  put(px);
  const blob = await toBlob(c);
  if (blob.size > (d.maxBytes ?? MAX_PNG)) throw new PictureError("too-large");
  return { blob, pixelWidth: c.width, pixelHeight: c.height, scale, via, frames };
}

export async function assemble(d: PictureDeps): Promise<Picture> {
  const { viewport: v } = d;
  if (!(v.width > 0 && v.height > 0)) throw new PictureError("failed", "empty viewport");
  const scales = [...new Set([Math.min(2, Math.max(1, v.dpr)), 1])];
  let lastTooLarge = false;
  let domError: unknown;
  for (const s of scales) {
    try {
      return await finish(await d.renderDom(s), d, "dom", true);
    } catch (e) {
      domError = e;
      if (e instanceof PictureError && e.code === "too-large") { lastTooLarge = true; continue; }
      break; // a failed or blank render: the same render at another scale will not do better
    }
  }
  if (lastTooLarge && domError instanceof PictureError) throw domError;
  try {
    const got = await d.grabDisplay();
    const c = got.canvas;
    const ratioOk = Math.abs(c.width / c.height - v.width / v.height) / (v.width / v.height) < 0.03;
    return await finish(c, d, "display", got.sameViewport && ratioOk);
  } catch (e) {
    if (e instanceof PictureError) throw e;
    throw new PictureError("failed", e instanceof Error ? e.message : "display capture failed");
  }
}

// ---- the real browser wiring --------------------------------------------------------------------

export function pageHasContent(doc: Document): boolean {
  const text = (doc.body?.innerText ?? "").trim();
  return text.length > 20 || doc.querySelector("img, canvas, video, svg") !== null;
}

function backgroundOf(doc: Document, win: Window): string {
  for (const el of [doc.body, doc.documentElement]) {
    if (!el) continue;
    const bg = win.getComputedStyle(el).backgroundColor;
    if (bg && bg !== "transparent" && !/rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)/.test(bg)) return bg;
  }
  return "#ffffff";
}

export async function takePicture(win: Window, hostToHide: HTMLElement | null): Promise<Picture> {
  const doc = win.document;
  const viewport: Viewport = { width: win.innerWidth, height: win.innerHeight, scrollX: win.scrollX, scrollY: win.scrollY, dpr: win.devicePixelRatio || 1 };
  const frames = privateFrames(doc, viewport.width, viewport.height);
    if (hostToHide) hostToHide.style.setProperty("visibility", "hidden", "important");
  try {
    return await assemble({
      viewport,
      frames,
      pageHasContent: pageHasContent(doc),
      renderDom: async (scale) => {
        const { domToCanvas } = await import("modern-screenshot");
        return (await domToCanvas(doc.documentElement, {
          width: viewport.width,
          height: viewport.height,
          scale,
          backgroundColor: backgroundOf(doc, win),
          style: { transform: `translate(${-viewport.scrollX}px, ${-viewport.scrollY}px)`, transformOrigin: "top left" },
          onCloneEachNode: (n) => maskClone(n),
          timeout: 15000,
        })) as unknown as CanvasLike;
      },
      grabDisplay: async () => {
        const md = win.navigator.mediaDevices;
        if (!md?.getDisplayMedia) throw new PictureError("failed", "getDisplayMedia is not available");
        const stream = await md.getDisplayMedia({
          video: { displaySurface: "browser" },
          audio: false,
          preferCurrentTab: true,
          selfBrowserSurface: "include",
          surfaceSwitching: "exclude",
        } as DisplayMediaStreamOptions);
        try {
          const track = stream.getVideoTracks()[0];
          const surface = (track?.getSettings() as { displaySurface?: string } | undefined)?.displaySurface;
          const video = doc.createElement("video");
          video.muted = true;
          video.srcObject = stream;
          await video.play();
          if (video.videoWidth === 0) await new Promise((r) => setTimeout(r, 120));
          const w = video.videoWidth, h = video.videoHeight;
          if (!w || !h) throw new PictureError("blank");
          // Natural size, but never smaller than the viewport: the capture states a scale of at least 1.
          const k = Math.max(1, viewport.width / w);
          const canvas = doc.createElement("canvas");
          canvas.width = Math.round(w * k);
          canvas.height = Math.round(h * k);
          canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
          return { canvas: canvas as unknown as CanvasLike, sameViewport: surface === "browser" };
        } finally {
          stream.getTracks().forEach((t) => t.stop());
        }
      },
    });
  } finally {
    if (hostToHide) hostToHide.style.removeProperty("visibility");
  }
}
