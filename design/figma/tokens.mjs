// Teyla's tokens for the Figma generator, read from brand/tokens.json (the one source).
// The file draws light values (one variable mode on the free plan); `dark` keeps every dark value for the cover's
// second column. Names are the brand roles. A few groups are not brand tokens but what the apps draw:
//   - tints: the opacities apps/mac/Teyla/UI/Tokens.swift (Palette) puts on the roles
//   - ios-*: the iOS system colours the iPhone app's surfaces use (apps/ios/Teyla/UI/Tokens.swift, Palette)
//   - mac-*: the macOS window chrome around the pages
//   - ansi-* / term-*: the CLI roles for a light terminal; ansi-dark-* / term-dark-* for a dark one (ansi256)
// Type: the four brand levels, then each platform's scale as its Typo enum draws it.
import { readFileSync } from "node:fs";

const SOURCE = new URL("../../brand/tokens.json", import.meta.url);
const c = (hex, alpha = 1) => ({ hex: hex.toUpperCase(), alpha });

export default function tokens() {
  const b = JSON.parse(readFileSync(SOURCE, "utf8"));
  const colors = {}, dark = {};
  for (const [name, hex] of Object.entries(b.color.light)) colors[name] = c(hex);
  for (const [name, hex] of Object.entries(b.color.dark)) dark[name] = c(hex);
  // Logo-only colours (color.mark): the amber block of the mark is brighter in light mode than needs-you.
  const m = b.color.mark;
  Object.assign(colors, { "mark-accent": c(m["accent-light"]), "icon-top": c(m["icon-top"]), "icon-bottom": c(m["icon-bottom"]), "on-icon": c(m["on-icon"]), "accent-on-icon": c(m["accent-on-icon"]) });
  Object.assign(dark, { "mark-accent": c(m["accent-on-icon"]), "icon-top": c(m["icon-top"]), "icon-bottom": c(m["icon-bottom"]), "on-icon": c(m["on-icon"]), "accent-on-icon": c(m["accent-on-icon"]) });
  // Tints (Palette in Tokens.swift): a letter tile, older chart bars, a switch track, fine print.
  const tint = (from, name, a) => { colors[name] = c(colors[from].hex, a); dark[name] = c(dark[from].hex, a); };
  tint("primary", "primary-tint", 0.14);
  tint("primary", "primary-muted", 0.35);
  tint("danger", "danger-tint", 0.14);
  tint("border", "track", 0.55);
  tint("text-secondary", "text-tertiary", 0.7);
  // iOS system colours (systemGroupedBackground, secondarySystemGroupedBackground, label, secondaryLabel, separator,
  // systemFill, the tab bar's material): Apple's published values, light and dark.
  const sys = {
    "ios-bg": [c("#F2F2F7"), c("#000000")],
    "ios-card": [c("#FFFFFF"), c("#1C1C1E")],
    "ios-label": [c("#000000"), c("#FFFFFF")],
    "ios-label-2": [c("#3C3C43", 0.6), c("#EBEBF5", 0.6)],
    "ios-separator": [c("#3C3C43", 0.29), c("#545458", 0.6)],
    "ios-fill": [c("#787880", 0.2), c("#787880", 0.36)],
    "ios-bar": [c("#F9F9F9", 0.94), c("#1D1D1D", 0.94)],
    // macOS window chrome: the sidebar's material, the window's edge, a selected sidebar row (the app's tint).
    "mac-sidebar": [c("#EEEEF0"), c("#26272B")],
    "mac-edge": [c("#000000", 0.18), c("#FFFFFF", 0.12)],
    "mac-selection": [c(b.color.light.primary, 0.16), c(b.color.dark.primary, 0.24)],
  };
  for (const [name, [l, d]] of Object.entries(sys)) { colors[name] = l; dark[name] = d; }
  // The CLI (ansi256): roles for a light terminal and a dark one. The backgrounds are the ones the contrast
  // ratios in tokens.json are measured against (#FFFFFF and #1E1E1E); the plain text is the brand text colour.
  const t = b.ansi256;
  colors["term-bg"] = c("#FFFFFF"); colors["term-fg"] = c(b.color.light.text);
  colors["term-dark-bg"] = c("#1E1E1E"); colors["term-dark-fg"] = c(b.color.dark.text);
  for (const [role, v] of Object.entries(t["light-terminal"])) colors[`ansi-${role}`] = c(v.hex);
  for (const [role, v] of Object.entries(t["dark-terminal"])) colors[`ansi-dark-${role}`] = c(v.hex);
  for (const k of ["term-bg", "term-fg", "term-dark-bg", "term-dark-fg"]) dark[k] = colors[k];
  for (const k of Object.keys(colors)) if (k.startsWith("ansi-")) dark[k] = colors[k];

  const s = b.type.scale;
  const type = {
    // brand levels (tokens.json type.scale)
    brief: { size: s.brief.size, weight: s.brief.weight, ls: 0 },
    lead: { size: s.lead.size, weight: s.lead.weight, ls: 0 },
    body: { size: s.body.size, weight: s.body.weight, ls: 0 },
    caption: { size: s.caption.size, weight: s.caption.weight, ls: 0 },
    // Mac (apps/mac/Teyla/UI/Tokens.swift, Typo)
    "mac-page-title": { size: 26, weight: 600, ls: 0 },
    "mac-section": { size: 17, weight: 600, ls: 0 },
    "mac-card-title": { size: 14, weight: 600, ls: 0 },
    "mac-body": { size: 13, weight: 400, ls: 0 },
    "mac-caption": { size: 12, weight: 400, ls: 0 },
    "mac-number": { size: 26, weight: 600, ls: 0, digits: true },
    "mac-code": { size: 12, weight: 400, ls: 0, family: "mono" },
    // iPhone (apps/ios/Teyla/UI/Tokens.swift, Typo: system text styles at the default size), and the system chrome
    "ios-large-title": { size: 34, weight: 700, ls: 0 },
    "ios-page-title": { size: 28, weight: 700, ls: 0 },
    "ios-section": { size: 20, weight: 600, ls: 0 },
    "ios-card-title": { size: 17, weight: 600, ls: 0 },
    "ios-text": { size: 17, weight: 400, ls: 0 },
    "ios-body": { size: 15, weight: 400, ls: 0 },
    "ios-caption": { size: 13, weight: 400, ls: 0 },
    "ios-number": { size: 28, weight: 600, ls: 0, digits: true },
    "ios-code": { size: 13, weight: 400, ls: 0, family: "mono" },
    "ios-tab": { size: 10, weight: 500, ls: 0 },
    // Terminal (the CLI) and the web (src/teyla/web/app.css, site/public/assets/tokens.css)
    term: { size: 13, weight: 400, ls: 0, family: "mono", digits: true },
    "web-title": { size: 28, weight: 600, ls: 0 },
    "web-head": { size: 16, weight: 600, ls: 0 },
    "web-body": { size: 15, weight: 400, ls: 0 },
    "web-small": { size: 13, weight: 400, ls: 0 },
  };
  const radius = { ...b.radius, "mac-control": 8, "mac-panel": 14, "ios-control": 8, "ios-card": 12, "ios-panel": 16 };
  const space = { ...b.space, "mac-gutter": 28, "ios-gutter": 16 };
  const families = { mono: { figma: "SF Mono", css: "ui-monospace, 'SF Mono', Menlo, monospace" } };
  return { set: `brand ${b.version}`, colors, dark, type, radius, space, families };
}
