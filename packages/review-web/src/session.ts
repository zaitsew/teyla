/** What one opening of review mode froze, and how the tester's draft becomes the capture record.
 *  Both the privacy rules and the field choices live here, so they are written once and tested. */
import { hitTest, screenFor, touchesPrivate } from "./anchors.ts";
import { buildCapture, type Anchor, type CaptureRecord, type Rect } from "./format.ts";

export interface Frozen {
  id: string;
  hostname: string;
  product: string;
  name?: string;
  version: string;
  build: string;
  commit?: string;
  environment: CaptureRecord["environment"];
  /** The screen the product registered with `setScreen`, if any. */
  currentScreen?: string;
  /** Already free of the `strings` that overlap a private frame. */
  anchors: Anchor[];
  /** The rectangles painted black in the picture, viewport CSS pixels. */
  frames: Rect[];
  sha256: string;
  pixelWidth: number;
  pixelHeight: number;
  scale: number;
}

export interface Draft {
  tap?: { x: number; y: number };
  region?: Rect;
  text: string;
  input: "text" | "speech";
}

export function recordFor(f: Frozen, d: Draft, now: Date = new Date()): CaptureRecord {
  // A click or drag that touches a private area records no element: the picture hides it, so the JSON must not name it.
  const priv = touchesPrivate(d.tap, d.region, f.frames);
  const point = d.tap ?? (d.region ? { x: d.region.x + d.region.width / 2, y: d.region.y + d.region.height / 2 } : undefined);
  const hit = !priv && point ? hitTest(f.anchors, point.x, point.y) : undefined;
  const input: Parameters<typeof buildCapture>[0] = {
    id: f.id, now, product: f.product, hostname: f.hostname, version: f.version, build: f.build,
    environment: f.environment, anchors: f.anchors, text: d.text.trim(), input: d.input,
    sha256: f.sha256, pixelWidth: f.pixelWidth, pixelHeight: f.pixelHeight, scale: f.scale,
  };
  if (f.name) input.name = f.name;
  if (f.commit) input.commit = f.commit;
  const screen = screenFor(f.currentScreen, hit, f.anchors);
  if (screen) input.screen = screen;
  if (point) input.tap = point;
  if (d.region) input.region = d.region;
  if (hit) input.element = hit;
  if (f.environment.language) input.language = f.environment.language;
  return buildCapture(input);
}
