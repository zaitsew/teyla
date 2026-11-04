import { test } from "node:test";
import assert from "node:assert/strict";
import { assemble, PictureError, type CanvasLike, type PictureDeps } from "../src/picture.ts";
import { busyCanvas, fakeCanvas, rect } from "./helpers.ts";

const viewport = { width: 100, height: 50, scrollX: 0, scrollY: 0, dpr: 2 };
const pix = (c: { px: { width: number; data: Uint8ClampedArray } }, x: number, y: number) => Array.from(c.px.data.slice((y * c.px.width + x) * 4, (y * c.px.width + x) * 4 + 3));

function deps(over: Partial<PictureDeps>): PictureDeps {
  return {
    viewport, frames: [], pageHasContent: true,
    renderDom: async (s) => busyCanvas(100 * s, 50 * s) as unknown as CanvasLike,
    grabDisplay: async () => { throw new Error("no display capture in this test"); },
    liveFrames: () => [],
    ...over,
  };
}

test("the DOM render is used first, at the device scale up to 2", async () => {
  const p = await assemble(deps({}));
  assert.equal(p.via, "dom");
  assert.equal(p.scale, 2);
  assert.equal(p.pixelWidth, 200);
  assert.equal(p.pixelHeight, 100);
});

test("private frames are painted black on the DOM render", async () => {
  const canvas = busyCanvas(200, 100);
  const p = await assemble(deps({ frames: [rect(10, 10, 20, 10)], renderDom: async () => canvas as unknown as CanvasLike }));
  assert.equal(p.via, "dom");
  assert.deepEqual(pix(canvas, 20, 20), [0, 0, 0]);
  assert.deepEqual(pix(canvas, 59, 39), [0, 0, 0]);
  assert.notDeepEqual(pix(canvas, 100, 80), [0, 0, 0]);
});

test("a render that throws falls back to the display capture on a page with nothing private", async () => {
  const shown = busyCanvas(200, 100);
  const p = await assemble(deps({
    renderDom: async () => { throw new Error("foreignObject failed"); },
    grabDisplay: async () => ({ canvas: shown as unknown as CanvasLike }),
  }));
  assert.equal(p.via, "display");
  assert.deepEqual(p.frames, []);
});

test("a blank render of a page with content falls back; of an empty page it is accepted", async () => {
  const blank = () => fakeCanvas(200, 100, [255, 255, 255, 255]) as unknown as CanvasLike;
  const fell = await assemble(deps({ renderDom: async () => blank(), grabDisplay: async () => ({ canvas: busyCanvas(200, 100) as unknown as CanvasLike }) }));
  assert.equal(fell.via, "display");
  const empty = await assemble(deps({ pageHasContent: false, renderDom: async () => blank() }));
  assert.equal(empty.via, "dom");
});

test("when both ways fail the picture fails, and nothing is made up", async () => {
  await assert.rejects(
    assemble(deps({ renderDom: async () => { throw new Error("x"); }, grabDisplay: async () => { throw new Error("the tester declined"); } })),
    (e: unknown) => e instanceof PictureError && e.code === "failed",
  );
  await assert.rejects(
    assemble(deps({ renderDom: async () => fakeCanvas(200, 100, [255, 255, 255, 255]) as unknown as CanvasLike, grabDisplay: async () => ({ canvas: fakeCanvas(200, 100, [255, 255, 255, 255]) as unknown as CanvasLike }) })),
    (e: unknown) => e instanceof PictureError && e.code === "blank",
  );
});

test("a page with private areas never opens the sharing prompt", async () => {
  let asked = false;
  await assert.rejects(
    assemble(deps({
      frames: [rect(0, 0, 10, 10)],
      renderDom: async () => { throw new Error("x"); },
      grabDisplay: async () => { asked = true; return { canvas: busyCanvas(200, 100) as unknown as CanvasLike }; },
    })),
    (e: unknown) => e instanceof PictureError && e.code === "mask-unplaceable",
  );
  assert.equal(asked, false);
});

test("a private area that appears while the sharing prompt is open refuses the frame", async () => {
  await assert.rejects(
    assemble(deps({
      renderDom: async () => { throw new Error("x"); },
      grabDisplay: async () => ({ canvas: busyCanvas(200, 100) as unknown as CanvasLike }),
      liveFrames: () => [rect(0, 0, 10, 10)],
    })),
    (e: unknown) => e instanceof PictureError && e.code === "mask-unplaceable",
  );
});

test("a PNG over the limit is retried at scale 1, then refused", async () => {
  const sizes: number[] = [];
  const p = await assemble(deps({ maxBytes: 5000, renderDom: async (s) => { sizes.push(s); return busyCanvas(100 * s, 50 * s, s === 2 ? 9000 : 100) as unknown as CanvasLike; } }));
  assert.deepEqual(sizes, [2, 1]);
  assert.equal(p.scale, 1);
  await assert.rejects(
    assemble(deps({ maxBytes: 5000, renderDom: async (s) => busyCanvas(100 * s, 50 * s, 9000) as unknown as CanvasLike })),
    (e: unknown) => e instanceof PictureError && e.code === "too-large",
  );
});

test("an empty viewport fails at once", async () => {
  await assert.rejects(assemble(deps({ viewport: { ...viewport, width: 0 } })), (e: unknown) => e instanceof PictureError);
});
