// Teyla's shared chrome for the Figma generator, read from the apps' code. Every export is a composite:
// a spec calls it as { "t": "use", "c": "<name>", "p": { ... } }. Colours are token names (tokens.mjs).
//   macWindow   the Mac app's window: traffic lights, sidebar (apps/mac/Teyla/UI/MainView.swift SidebarView),
//               toolbar (LiveIndicator, Refresh, New task) and the page
//   iosScreen   an iPhone screen: status bar, large-title navigation bar, the page, the five-tab bar
//               (apps/ios/Teyla/App/TeylaApp.swift); iosStatusBar, iosNavBar, iosTabBar on their own
//   terminal    a terminal window with lines in the CLI's ANSI roles (src/teyla/brand.py, ui.py)
//   browser     a browser window around a web page (teyla web, the site)
//   brandMark, card, pill, tile, circles, activityGrid, dark   small parts; `dark` redraws its kids in the dark values
import { V, H, Z, T, I, SPACER } from "../dsl.mjs";
import tokens from "../tokens.mjs";

const TOK = tokens();
const shadow = (y, blur, a) => ({ x: 0, y, blur, color: `#000000@${a}` });

// ---- small parts ------------------------------------------------------------------------------------------

/** The mark (apps/mac/Teyla/UI/BrandMark.swift): a T and an amber block on a 64-unit grid. p: { size = 24 } */
export function brandMark(p = {}) {
  const size = p.size || 24, u = size / 64;
  const bar = (x, y, w, h, fill) => V({ abs: { top: y * u, left: x * u }, w: w * u, h: h * u, r: 2.5 * u, fill });
  return Z({ w: size, h: size, name: "Mark" }, bar(9, 12, 32, 10, "primary"), bar(27, 12, 10, 40, "primary"), bar(45, 12, 10, 17, "mark-accent"));
}

/** A card. p: { platform: "mac" | "ios" = "mac", kids, gap = 8, pad = 16, link } */
export function card(p = {}) {
  const ios = p.platform === "ios";
  return V({ name: "Card", w: "fill", gap: p.gap ?? 8, pad: p.pad ?? 16, fill: ios ? "ios-card" : "surface", r: ios ? "ios-card" : "card", stroke: ios ? null : "border", link: p.link }, p.kids || []);
}

/** A status pill. p: { text, tone: "needs-you" | "saving" | "danger" | "primary" | "neutral" = "neutral" } */
export function pill(p = {}) {
  const tone = p.tone && p.tone !== "neutral" ? p.tone : "text-secondary";
  return H({ name: "Pill", pad: [2, 8], r: "chip", fill: `${tone}@0.14`, align: "center" }, T(p.text || "", "caption", tone, { weight: 600 }));
}

/** A stat tile (StatTile). p: { label, value, detail?, tone?, platform: "mac" | "ios" = "mac", link } */
export function tile(p = {}) {
  const ios = p.platform === "ios";
  return V({ name: "Tile", w: "fill", gap: 4, pad: 12, fill: ios ? "ios-card" : "surface", r: ios ? "ios-card" : "card", stroke: ios ? null : "border", link: p.link },
    T(p.label || "", ios ? "ios-caption" : "mac-caption", "text-secondary"),
    T(p.value || "", ios ? "ios-number" : "mac-number", p.tone || "text"),
    p.detail ? T(p.detail, ios ? "ios-caption" : "mac-caption", "text-secondary") : null);
}

/** Weekly circles (Today's goals). p: { done, total, size = 12 } */
export function circles(p = {}) {
  const size = p.size || 12;
  return H({ name: "Circles", gap: 6, align: "center" }, Array.from({ length: p.total || 0 }, (_, i) =>
    V({ w: size, h: size, r: size / 2, fill: i < (p.done || 0) ? "primary" : null, stroke: i < (p.done || 0) ? null : "text-secondary@0.6", sw: 1 })));
}

/** The activity graph (ActivityView): weeks x 7 cells in five levels (Palette.activityLevels). p: { weeks = 17, cell = 11, seed = 1 } */
export function activityGrid(p = {}) {
  const weeks = p.weeks || 17, cell = p.cell || 11, seed = p.seed || 1;
  const LEVELS = ["border@0.45", "primary@0.3", "primary@0.5", "primary@0.75", "primary"];
  // made-up but steady: busier towards the right, quieter at the weekend
  const level = (w, d) => (d >= 5 ? 0 : Math.min(4, Math.floor(((w * 7 + d * 3 + seed * 5) % 11) / 4 + (w / weeks) * 2.2)));
  return H({ name: "Activity grid", gap: 3 }, Array.from({ length: weeks }, (_, w) =>
    V({ gap: 3 }, Array.from({ length: 7 }, (_, d) => V({ w: cell, h: cell, r: 2, fill: LEVELS[level(w, d)] })))));
}

const lights = () => H({ name: "Traffic lights", gap: 8, align: "center" },
  ["#FF5F57", "#FEBC2E", "#28C840"].map((hex) => V({ w: 12, h: 12, r: 6, fill: hex, stroke: "#000000@0.12" })));

// ---- Mac ---------------------------------------------------------------------------------------------------

// The sidebar, top to bottom (SidebarView). Today and the second section are the full build's (console) only.
const MAC_ROUTES = [
  ["today", "Today", "sun.max", true],
  ["home", "Home", "house", false],
  ["decisions", "Decisions", "tray", false],
  ["products", "Products", "square.grid.2x2", false],
  null,
  ["growth", "Growth", "megaphone", true],
  ["money", "Money", "creditcard", true],
  ["operations", "Operations", "gauge.with.dots.needle.67percent", true],
  ["playbook", "Playbook", "book", true],
];
const LIVE = { "up-to-date": ["text-secondary", "Up to date"], stale: ["needs-you", "Stale · 4 min"], offline: ["danger", "Offline"], updating: [null, "Updating…"] };

/**
 * The Mac window. The frame is the spec's device (default 1280 x 800).
 * p: { selected: route id, badges: { today: 3, decisions: 5, operations: "!" }, store: false (the Store build: no Today,
 *      no second section), live: "up-to-date" | "stale" | "offline" | "updating", linked: [route ids whose screen exists:
 *      the row links to "mac.<id>"], kids: the page, gap = 24 }
 */
export function macWindow(p = {}, ctx = {}) {
  const dev = ctx.screen?.device || { w: 1280, h: 800 };
  const linked = new Set(p.linked || []);
  const badges = p.badges || {};
  const row = ([id, label, symbol]) => {
    const on = p.selected === id;
    return H({ name: `Row ${label}`, w: "fill", gap: 8, pad: [5, 8], r: "mac-control", align: "center", fill: on ? "mac-selection" : null, link: linked.has(id) ? `mac.${id}` : null },
      I(symbol, 15, "primary"), T(label, "mac-body", "text"), SPACER,
      badges[id] !== undefined ? T(String(badges[id]), "mac-caption", "text-secondary") : null);
  };
  const rows = MAC_ROUTES.filter((r) => r === null || !(p.store && r[3]));
  const groups = [[]];
  for (const r of rows) r === null ? groups.push([]) : groups[groups.length - 1].push(r);
  const [dot, live] = LIVE[p.live || "up-to-date"];
  const sidebar = V({ name: "Sidebar", w: 220, h: "fill", fill: "mac-sidebar", gap: 0 },
    H({ pad: [18, 20, 10, 20] }, lights()),
    H({ name: "Header", w: "fill", gap: 8, pad: [8, 12], align: "center" }, brandMark({ size: 24 }), T("Teyla", "mac-card-title", "text")),
    groups.filter((g) => g.length).map((g, i) => V({ name: i ? "Section" : "Pages", w: "fill", gap: 2, pad: [i ? 14 : 4, 10, 0, 10] }, g.map(row))),
    SPACER,
    H({ name: "Settings", w: "fill", gap: 8, pad: 12, align: "center", link: linked.has("settings") ? "mac.settings" : null },
      I("gearshape", 15, "text-secondary"), T("Settings", "mac-body", "text-secondary")));
  const toolbar = H({ name: "Toolbar", w: "fill", h: 52, pad: [0, 16], gap: 10, align: "center" },
    SPACER,
    H({ name: "Live", gap: 4, pad: [0, 8], align: "center" },
      dot ? V({ w: 6, h: 6, r: 3, fill: dot }) : I("progress.indicator", 11, "text-secondary"),
      T(live, "mac-caption", "text-secondary")),
    H({ name: "Actions", gap: 14, pad: [7, 12], r: "chip", fill: "surface", stroke: "border", align: "center" },
      I("arrow.clockwise", 15, "text"), I("square.and.pencil", 15, "text")));
  return H({ name: "Mac window", w: dev.w, h: dev.h, fill: "background", r: 12, stroke: "mac-edge", clip: true, shadow: shadow(12, 40, 0.18) },
    sidebar,
    V({ w: 1, h: "fill", fill: "border" }),
    V({ name: "Detail", w: "fill", h: "fill", fill: "background" },
      toolbar,
      V({ name: "Page", w: "fill", h: "fill", gap: p.gap ?? 24, pad: [4, "mac-gutter", 28, "mac-gutter"].map((v) => TOK.space[v] ?? v), scroll: true }, p.kids || [])));
}

// ---- iPhone ------------------------------------------------------------------------------------------------

const IOS_TABS = [["home", "Home", "house"], ["decisions", "Decisions", "checkmark.bubble"], ["products", "Products", "square.stack.3d.up"], ["growth", "Growth", "megaphone"], ["more", "More", "ellipsis.circle"]];

/** The status bar at 9:41. */
export function iosStatusBar() {
  return H({ name: "Status bar", w: "fill", h: 54, pad: [0, 36, 0, 48], align: "center" },
    T("9:41", "ios-card-title", "ios-label"), SPACER,
    H({ gap: 6, align: "center" }, I("cellularbars", 15, "ios-label"), I("wifi", 15, "ios-label"), I("battery.100", 22, "ios-label")));
}

/** A navigation bar. p: { title, large = true, back?: label of the back button, trailing?: text of a trailing button } */
export function iosNavBar(p = {}) {
  const top = H({ name: "Bar", w: "fill", h: 44, pad: [0, 16], align: "center", gap: 6 },
    p.back ? H({ gap: 4, align: "center", link: "back" }, I("chevron.left", 19, "primary", { weight: "semibold" }), T(p.back, "ios-text", "primary")) : null,
    p.large === false ? SPACER : null,
    p.large === false && p.title ? T(p.title, "ios-card-title", "ios-label") : null,
    SPACER,
    p.trailing ? T(p.trailing, "ios-card-title", "primary") : null);
  return V({ name: "Navigation bar", w: "fill" }, top,
    p.large !== false && p.title ? H({ w: "fill", pad: [2, 16, 8, 16] }, T(p.title, "ios-large-title", "ios-label")) : null);
}

/** The tab bar (Liquid Glass, floating). p: { selected: tab id, badges: { decisions: 3 }, linked: [tab ids: links to "iphone.<id>"] } */
export function iosTabBar(p = {}) {
  const linked = new Set(p.linked || []);
  const badges = p.badges || {};
  return H({ name: "Tab bar", abs: { bottom: 24, left: 16 }, fixed: true, w: 370, h: 62, r: 31, pad: [4, 6], fill: "ios-bar", stroke: "#000000@0.06", shadow: shadow(8, 24, 0.12), align: "center" },
    IOS_TABS.map(([id, label, symbol]) => {
      const on = p.selected === id, tone = on ? "primary" : "ios-label";
      return V({ name: `Tab ${label}`, w: "fill", h: "fill", gap: 1, r: 27, align: "center", justify: "center", fill: on ? "ios-fill" : null, link: linked.has(id) && !on ? { to: `iphone.${id}`, as: "tab" } : null },
        Z({ w: 30, h: 26 },
          V({ abs: { center: "xy" } }, I(symbol, 20, tone)),
          badges[id] ? H({ abs: { top: -3, right: -4 }, pad: [1, 5], r: 9, fill: "#FF3B30" }, T(String(badges[id]), "ios-tab", "#FFFFFF", { weight: 600 })) : null),
        T(label, "ios-tab", tone));
    }));
}

/** An iPhone screen (402 x 874 unless the spec sets a device). p: { title, large, back, trailing, tab, badges, linked, kids, gap = 24 } */
export function iosScreen(p = {}) {
  return V({ name: "Screen", w: "fill", fill: "ios-bg" },
    iosStatusBar(),
    iosNavBar(p),
    V({ name: "Page", w: "fill", gap: p.gap ?? 24, pad: [8, "ios-gutter", 120, "ios-gutter"].map((v) => TOK.space[v] ?? v) }, p.kids || []),
    p.tab === null ? null : iosTabBar({ selected: p.tab, badges: p.badges, linked: p.linked }));
}

// ---- terminal ----------------------------------------------------------------------------------------------

/**
 * A terminal window. The frame takes the spec's device width.
 * p: { title = "teyla — zsh", theme: "light" | "dark" = "light", prompt = "~ %", lines: [line, ...] }
 * A line is a string, a list of segments, { "cmd": "teyla today" } (prompt and command) or "" (an empty line).
 * A segment is a string or { "v", "role", "bold" }; role is primary, needs-you, saving, danger or text-secondary
 * (src/teyla/brand.py); { "mark": true } is the banner glyph: a bold T in primary and a block in needs-you.
 */
export function terminal(p = {}) {
  const dark = p.theme === "dark";
  const fg = dark ? "term-dark-fg" : "term-fg";
  const role = (r) => (r ? `${dark ? "ansi-dark-" : "ansi-"}${r}` : fg);
  const seg = (s) => {
    if (typeof s === "string") return T(s, "term", fg);
    if (s.mark) return [T("T", "term", role("primary"), { weight: 700 }), T("█", "term", role("needs-you"))];
    return T(s.v, "term", role(s.role), s.bold ? { weight: 700 } : {});
  };
  const line = (l) => {
    if (l === "" || l == null) return { t: "spacer", h: 18 };
    if (l.cmd) return H({ name: "Command" }, T(`${p.prompt || "~ %"} `, "term", role("text-secondary")), T(l.cmd, "term", fg, { weight: 700 }));
    // A run of spaces carries no colour: it joins the next segment, so no text node is blank (the lint refuses one).
    const segs = [];
    let lead = "";
    for (const s of Array.isArray(l) ? l : [l]) {
      const v = typeof s === "string" ? s : s.v;
      if (s.mark) { segs.push(s); continue; }
      if (v.trim() === "") { lead += v; continue; }
      segs.push(typeof s === "string" ? lead + s : { ...s, v: lead + s.v });
      lead = "";
    }
    return H({ name: "Line" }, segs.flatMap((s) => seg(s)));
  };
  return V({ name: "Terminal", w: "fill", fill: dark ? "term-dark-bg" : "term-bg", r: 10, stroke: "mac-edge", clip: true, shadow: shadow(10, 32, 0.16) },
    H({ name: "Title bar", w: "fill", h: 30, pad: [0, 12], align: "center", fill: dark ? "#323232" : "mac-sidebar" },
      lights(), SPACER, T(p.title || "teyla — zsh", "mac-caption", dark ? "term-dark-fg" : "text-secondary"), SPACER, V({ w: 52, h: 1 })),
    V({ name: "Lines", w: "fill", pad: [10, 14, 16, 14] }, (p.lines || []).map(line)));
}

// ---- browser -----------------------------------------------------------------------------------------------

/** A browser window. The frame is the spec's device (default 1440 x 900). p: { url, kids, fill = "background" } */
export function browser(p = {}, ctx = {}) {
  const dev = ctx.screen?.device || { w: 1440, h: 900 };
  return V({ name: "Browser", w: dev.w, h: dev.h, fill: p.fill || "background", r: 12, stroke: "mac-edge", clip: true, shadow: shadow(12, 40, 0.18) },
    H({ name: "Toolbar", w: "fill", h: 52, pad: [0, 16], gap: 16, align: "center", fill: "mac-sidebar" },
      lights(),
      H({ gap: 14, align: "center" }, I("sidebar.left", 15, "text-secondary"), I("chevron.left", 15, "text-secondary"), I("chevron.right", 15, "text-tertiary")),
      SPACER,
      H({ name: "Address", w: 520, h: 32, r: "mac-control", fill: "ios-fill", gap: 6, align: "center", justify: "center" },
        I("lock.fill", 11, "text-secondary"), T(p.url || "localhost", "web-small", "text")),
      SPACER,
      H({ gap: 14, align: "center" }, I("square.and.arrow.up", 15, "text-secondary"), I("plus", 15, "text-secondary"), I("square.on.square", 15, "text-secondary"))),
    V({ name: "Page", w: "fill", h: "fill", fill: p.fill || "background", scroll: true }, p.kids || []));
}

// ---- dark --------------------------------------------------------------------------------------------------

// The file has one variable mode (light). `dark` expands its kids, composites included, and swaps every colour
// token for its dark value (tokens.mjs `dark`), so a dark column can stand beside the light one.
const darkOf = (v) => {
  if (typeof v !== "string" || v.startsWith("#") || v === "none") return v;
  const [name, a] = v.split("@");
  const d = TOK.dark[name];
  if (!d) return v;
  const alpha = d.alpha * (a === undefined ? 1 : Number(a));
  return alpha === 1 ? d.hex : `${d.hex}@${+alpha.toFixed(3)}`;
};
function recolour(n, ctx, depth = 0) {
  if (!n || typeof n !== "object" || depth > 40) return n;
  while (n.t === "use") {
    const fn = ctx.composites?.[n.c];
    if (!fn) return n;
    const outer = n;
    n = fn(n.p || {}, ctx);
    for (const k of ["abs", "fixed", "link", "w", "h", "name"]) if (outer[k] !== undefined && n[k] === undefined) n = { ...n, [k]: outer[k] };
  }
  const out = { ...n };
  for (const k of ["c", "fill", "stroke"]) if (out[k]) out[k] = darkOf(out[k]);
  if (out.shadow && typeof out.shadow === "object") out.shadow = { ...out.shadow, color: darkOf(out.shadow.color) };
  if (out.kids) out.kids = out.kids.filter(Boolean).map((k) => recolour(k, ctx, depth + 1));
  return out;
}
/** Draws its kids in the dark values. p: { kids, gap, w, pad } */
export function dark(p = {}, ctx = {}) {
  return recolour(V({ name: "Dark", w: p.w ?? "fill", gap: p.gap ?? 0, pad: p.pad ?? 0 }, p.kids || []), ctx);
}
