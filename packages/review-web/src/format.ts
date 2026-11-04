/** capture.json, format v1 (docs/REVIEW.md, templates/review/capture.schema.json). The fields are the
 *  iOS package's, in the same order. A key that is unknown is absent; `null` is never written. */

export const FORMAT_VERSION = 1;
export const PNG_NAME = "capture.png";
export const JSON_NAME = "capture.json";
export const MAX_ANCHORS = 200;
export const MAX_COMMENT = 8000;

export type Role = "button" | "text" | "field" | "image" | "list" | "cell" | "toggle" | "container" | "other";
export const ROLES: readonly Role[] = ["button", "text", "field", "image", "list", "cell", "toggle", "container", "other"];

export interface Rect { x: number; y: number; width: number; height: number }
export interface Source { file: string; line: number }

export interface Anchor {
  id: string;
  role: Role;
  bounds: Rect;
  screen?: string;
  parent?: string;
  strings?: string[];
  source?: Source;
}

export interface CaptureRecord {
  v: 1;
  id: string;
  created: string;
  device: string;
  app: {
    bundle_id: string; name?: string; version: string; build: string; commit?: string; product: string;
    configuration: "test_host";
  };
  environment: {
    os: string; model: string; locale: string; language?: string; appearance: "light" | "dark";
    dynamic_type: "unspecified"; screen: { width: number; height: number; scale: number };
  };
  screen?: string;
  tap?: { x: number; y: number };
  region?: Rect;
  element?: {
    id: string; matched_by: "anchor" | "accessibility_identifier"; screen?: string; parent?: string; role?: Role;
    bounds?: Rect; strings?: string[]; source?: Source;
  };
  anchors: Anchor[];
  comment: { text: string; input: "text" | "speech"; language?: string };
  screenshot: { file: "capture.png"; width: number; height: number; scale: number; sha256: string };
  microphone: { host_audio_in_use: false };
}

export const round2 = (n: number): number => Math.round(n * 100) / 100;

export function roundRect(r: Rect): Rect {
  return { x: round2(r.x), y: round2(r.y), width: round2(r.width), height: round2(r.height) };
}

/** `^[a-z][a-z0-9-]{0,39}$`, the slug the channel's key is bound to. */
export function isSlug(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9-]{0,39}$/.test(value);
}

/** A random lowercase UUID v4. The channel accepts only lowercase. */
export function newId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) return c.randomUUID().toLowerCase();
  const b = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40;
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** `YYYY-MM-DDTHH:MM:SSZ`, UTC, no milliseconds. */
export function isoSeconds(d: Date): string {
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export interface BuildInput {
  id: string;
  now: Date;
  product: string;
  hostname: string;
  name?: string;
  version: string;
  build: string;
  commit?: string;
  environment: CaptureRecord["environment"];
  screen?: string;
  tap?: { x: number; y: number };
  region?: Rect;
  element?: Anchor | { id: string };
  anchors: Anchor[];
  text: string;
  input: "text" | "speech";
  language?: string;
  sha256: string;
  pixelWidth: number;
  pixelHeight: number;
  scale: number;
}

function cleanAnchor(a: Anchor): Anchor {
  const out: Anchor = { id: a.id.slice(0, 200), role: a.role, bounds: roundRect(a.bounds) };
  if (a.screen) out.screen = a.screen.slice(0, 200);
  if (a.parent) out.parent = a.parent.slice(0, 200);
  if (a.strings && a.strings.length > 0) out.strings = a.strings.slice(0, 20).map((s) => s.slice(0, 200));
  if (a.source) out.source = a.source;
  return out;
}

/** The record. `screenshot.scale` is at least 1 and the picture is `pixelWidth` x `pixelHeight` pixels. */
export function buildCapture(i: BuildInput): CaptureRecord {
  const rec: CaptureRecord = {
    v: FORMAT_VERSION,
    id: i.id,
    created: isoSeconds(i.now),
    device: "Web",
    app: {
      bundle_id: i.hostname.slice(0, 200),
      ...(i.name ? { name: i.name.slice(0, 200) } : {}),
      version: i.version,
      build: i.build,
      ...(i.commit && /^[0-9a-f]{7,40}$/.test(i.commit) ? { commit: i.commit } : {}),
      product: i.product,
      configuration: "test_host",
    },
    environment: i.environment,
    anchors: i.anchors.slice(0, MAX_ANCHORS).map(cleanAnchor),
    comment: { text: i.text.slice(0, MAX_COMMENT), input: i.input },
    screenshot: { file: PNG_NAME, width: i.pixelWidth, height: i.pixelHeight, scale: round2(Math.max(1, i.scale)), sha256: i.sha256 },
    microphone: { host_audio_in_use: false },
  };
  if (i.language) {
    rec.comment.language = i.language;
  }
  if (i.screen) rec.screen = i.screen;
  if (i.tap) rec.tap = { x: round2(i.tap.x), y: round2(i.tap.y) };
  if (i.region) rec.region = roundRect(i.region);
  if (i.element) {
    const e = i.element;
    if ("bounds" in e) {
      rec.element = { id: e.id.slice(0, 200), matched_by: "anchor", role: e.role, bounds: roundRect(e.bounds) };
      if (e.screen) rec.element.screen = e.screen;
      if (e.parent) rec.element.parent = e.parent;
      if (e.strings && e.strings.length > 0) rec.element.strings = e.strings.slice(0, 20);
      if (e.source) rec.element.source = e.source;
    } else {
      rec.element = { id: e.id.slice(0, 200), matched_by: "accessibility_identifier" };
    }
  }
  // Re-order the keys the way the iOS package writes them, so a diff of two captures reads the same.
  const order = ["v", "id", "created", "device", "app", "environment", "screen", "tap", "region", "element", "anchors", "comment", "screenshot", "microphone"];
  const ordered: Record<string, unknown> = {};
  for (const k of order) if ((rec as unknown as Record<string, unknown>)[k] !== undefined) ordered[k] = (rec as unknown as Record<string, unknown>)[k];
  return ordered as unknown as CaptureRecord;
}

export function encodeCapture(rec: CaptureRecord): string {
  return JSON.stringify(rec);
}
