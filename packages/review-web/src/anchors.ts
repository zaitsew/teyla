/** Anchors, private areas and the hit test. The web twins of `.reviewAnchor`, `.reviewScreen` and
 *  `.reviewPrivate()`: the attributes `data-review-anchor`, `data-review-screen` and
 *  `data-review-private`. Bounds are viewport CSS pixels, the coordinate space of the capture. */
import { MAX_ANCHORS, ROLES, roundRect, type Anchor, type Rect, type Role, type Source } from "./format.ts";

export const ATTR_ANCHOR = "data-review-anchor";
export const ATTR_SCREEN = "data-review-screen";
export const ATTR_PRIVATE = "data-review-private";
const ATTR_IGNORE = "data-review-ignore";
export const ATTR_ROLE = "data-review-role";
export const ATTR_STRINGS = "data-review-strings";
export const ATTR_SOURCE = "data-review-source";

/** Always masked, whatever the page did: passwords, card fields and one-time codes. */
export function isAlwaysPrivate(el: Element): boolean {
  if (el.tagName.toLowerCase() !== "input") return false;
  const type = (el.getAttribute("type") ?? "").trim().toLowerCase();
  const auto = (el.getAttribute("autocomplete") ?? "").trim().toLowerCase();
  return type === "password" || auto.startsWith("cc-") || auto === "one-time-code" || auto.split(/\s+/).some((t) => t.startsWith("cc-"));
}

export function isPrivateElement(el: Element): boolean {
  return el.hasAttribute(ATTR_PRIVATE) || isAlwaysPrivate(el);
}

/** Margin painted around a private area, in CSS pixels (iOS: 2 pt). */
export const PRIVATE_MARGIN = 2;

function rectOf(el: Element): Rect {
  const r = el.getBoundingClientRect();
  return { x: r.x ?? r.left, y: r.y ?? r.top, width: r.width, height: r.height };
}

function emptyRect(r: Rect): boolean {
  return r.width === 0 && r.height === 0;
}

/** The union of the children's rectangles, for an element with no box of its own (`display: contents`). */
function unionOfChildren(el: Element): Rect | null {
  let out: Rect | null = null;
  for (const child of Array.from(el.children)) {
    let r = rectOf(child);
    if (emptyRect(r)) { const u = unionOfChildren(child); if (!u) continue; r = u; }
    if (!out) { out = r; continue; }
    const x0 = Math.min(out.x, r.x), y0 = Math.min(out.y, r.y);
    const x1 = Math.max(out.x + out.width, r.x + r.width), y1 = Math.max(out.y + out.height, r.y + r.height);
    out = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  }
  return out;
}

export function intersectsViewport(r: Rect, vw: number, vh: number): boolean {
  return r.x < vw && r.y < vh && r.x + r.width > 0 && r.y + r.height > 0;
}

/** The elements that match, open shadow roots included. A closed root cannot be read. The package's
 *  own host is left out. */
function deepMatches(root: ParentNode, selector: string): Element[] {
  const out: Element[] = [];
  for (const el of Array.from(root.querySelectorAll("*"))) {
    if (el.hasAttribute(ATTR_IGNORE)) continue;
    if (el.matches(selector)) out.push(el);
    if (el.shadowRoot) out.push(...deepMatches(el.shadowRoot, selector));
  }
  return out;
}

/** Every private element's rectangle in the viewport, plus the margin. An element that has no box and
 *  no children with one draws nothing and hides nothing. A box that is not a finite number stays in
 *  the list, and the picture painter hides the whole picture for it. */
export function privateFrames(doc: Document, vw: number, vh: number): Rect[] {
  const out: Rect[] = [];
  const seen = new Set<Element>();
  for (const el of deepMatches(doc, `[${ATTR_PRIVATE}], input`)) {
    if (!isPrivateElement(el) || seen.has(el)) continue;
    seen.add(el);
    let r = rectOf(el);
    if (![r.x, r.y, r.width, r.height].every((n) => Number.isFinite(n))) { out.push(r); continue; }
    if (emptyRect(r)) { const u = unionOfChildren(el); if (!u) continue; r = u; }
    const grown = { x: r.x - PRIVATE_MARGIN, y: r.y - PRIVATE_MARGIN, width: r.width + 2 * PRIVATE_MARGIN, height: r.height + 2 * PRIVATE_MARGIN };
    if (intersectsViewport(grown, vw, vh)) out.push(grown);
  }
  return out;
}

export function rectsIntersect(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

export function inRect(r: Rect, x: number, y: number): boolean {
  return x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height;
}

export function inferRole(el: Element): Role {
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute("type") ?? "").toLowerCase();
  const aria = (el.getAttribute("role") ?? "").toLowerCase();
  if (tag === "button" || tag === "a" || aria === "button" || aria === "link" || (tag === "input" && ["button", "submit", "reset"].includes(type))) return "button";
  if (aria === "switch" || aria === "checkbox" || aria === "radio" || (tag === "input" && ["checkbox", "radio"].includes(type))) return "toggle";
  if (tag === "input" || tag === "textarea" || tag === "select" || aria === "textbox") return "field";
  if (tag === "img" || tag === "svg" || tag === "canvas" || tag === "video" || tag === "picture") return "image";
  if (tag === "ul" || tag === "ol" || tag === "table" || aria === "list") return "list";
  if (tag === "li" || tag === "tr" || aria === "listitem") return "cell";
  if (/^h[1-6]$/.test(tag) || tag === "p" || tag === "span" || tag === "label") return "text";
  return el.children.length > 0 ? "container" : "other";
}

function parseSource(raw: string | null): Source | undefined {
  const m = /^(.{1,300}):(\d{1,7})$/.exec((raw ?? "").trim());
  if (!m) return undefined;
  const line = Number(m[2]);
  return line >= 1 ? { file: m[1] as string, line } : undefined;
}

/** The screen id an element sits in: its own `data-review-screen` or the nearest ancestor's. */
export function screenOf(el: Element): string | undefined {
  const holder = el.closest(`[${ATTR_SCREEN}]`);
  const id = holder?.getAttribute(ATTR_SCREEN)?.trim();
  return id && /^[A-Za-z0-9_.:#/-]{1,200}$/.test(id) ? id : undefined;
}

/** Every anchor on screen when the tester pressed Review, in document order. Anchors with no box,
 *  or outside the viewport, are left out. At most 200. An anchor that overlaps a private area loses
 *  its `strings`: the keys of the text it shows (ReviewRedaction.anchors). */
export function collectAnchors(doc: Document, vw: number, vh: number, frames: readonly Rect[]): Anchor[] {
  const out: Anchor[] = [];
  for (const el of Array.from(doc.querySelectorAll(`[${ATTR_ANCHOR}]`))) {
    if (out.length >= MAX_ANCHORS) break;
    const id = el.getAttribute(ATTR_ANCHOR)?.trim();
    if (!id) continue;
    const bounds = rectOf(el);
    if (![bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite) || emptyRect(bounds) || !intersectsViewport(bounds, vw, vh)) continue;
    const roleAttr = el.getAttribute(ATTR_ROLE)?.trim() as Role | undefined;
    const a: Anchor = { id, role: roleAttr && ROLES.includes(roleAttr) ? roleAttr : inferRole(el), bounds: roundRect(bounds) };
    const screen = screenOf(el);
    if (screen) a.screen = screen;
    const parent = el.parentElement?.closest(`[${ATTR_ANCHOR}]`)?.getAttribute(ATTR_ANCHOR)?.trim();
    if (parent) a.parent = parent;
    const strings = (el.getAttribute(ATTR_STRINGS) ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    if (strings.length > 0 && !frames.some((f) => rectsIntersect(f, bounds))) a.strings = strings.slice(0, 20);
    const source = parseSource(el.getAttribute(ATTR_SOURCE));
    if (source) a.source = source;
    out.push(a);
  }
  return out;
}

/** The smallest anchor that contains the point wins; on a tie the later one wins. The left and top
 *  edges are inside, the right and bottom edges are outside. */
export function hitTest(anchors: readonly Anchor[], x: number, y: number): Anchor | undefined {
  let best: Anchor | undefined;
  let bestArea = Infinity;
  for (const a of anchors) {
    if (!inRect(a.bounds, x, y)) continue;
    const area = a.bounds.width * a.bounds.height;
    if (area <= bestArea) { best = a; bestArea = area; }
  }
  return best;
}

/** The screen the capture is about: the one the product set, else the hit anchor's, else the one most
 *  anchors share. */
export function screenFor(current: string | undefined, hit: Anchor | undefined, anchors: readonly Anchor[]): string | undefined {
  if (current) return current;
  if (hit?.screen) return hit.screen;
  const counts = new Map<string, number>();
  for (const a of anchors) if (a.screen) counts.set(a.screen, (counts.get(a.screen) ?? 0) + 1);
  let best: string | undefined, n = 0;
  for (const [s, c] of counts) if (c > n) { best = s; n = c; }
  return best;
}

/** What a tap or circle may say about the element under it. A tap in a private area keeps no element
 *  (ReviewRedaction.pointed): the picture hides it, and the JSON must not name it. */
export function touchesPrivate(point: { x: number; y: number } | undefined, region: Rect | undefined, frames: readonly Rect[]): boolean {
  return frames.some((f) => (point ? inRect(f, point.x, point.y) : false) || (region ? rectsIntersect(f, region) : false));
}
