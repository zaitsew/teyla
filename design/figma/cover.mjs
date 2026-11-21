// Page 1 of the Figma file: the cover and the foundations, and page 3's captures, in Teyla's tokens.
// The generator calls cover(ctx), foundations(ctx) and captures(pictures); each returns a tree of nodes.
// ctx = { name, version, commit, date, screens, areas, tokens, type }.
// The free plan has one variable mode, so the foundations draw every colour twice: the light column binds the
// variables, the dark column (the `dark` composite) paints the dark values from brand/tokens.json.
import { readFileSync } from "node:fs";
import { V, H, T, U } from "./dsl.mjs";

const BRAND = JSON.parse(readFileSync(new URL("../../brand/tokens.json", import.meta.url), "utf8"));
const W = 1600;

export function cover(ctx) {
  const count = (a) => ctx.screens.filter((s) => s.area === a.id).length;
  return V({ w: W, pad: 96, gap: 40, fill: "background", r: 32 },
    H({ gap: 28, align: "center" }, U("brandMark", { size: 112 }), T(ctx.name, "brief", "text", { size: 120 })),
    T(`${ctx.version} · Surfaces · brand tokens ${BRAND.version}`, "brief", "text-secondary"),
    V({ gap: 6, w: "fill" },
      T(`Drawn from commit ${ctx.commit} on ${ctx.date}.`, "lead", "text"),
      T("This file is generated from the code (design/figma in the repo). Change the spec and render again; edits made here are lost.", "lead", "text-secondary", { weight: 400, w: "fill" }),
      T("Page 2 holds every surface, one section per platform: Mac, iPhone, the review form, the web and the CLI. All content is made up.", "lead", "text-secondary", { weight: 400, w: "fill" })),
    H({ gap: 12, wrap: true, w: "fill" }, ctx.areas.filter(count).map((a) =>
      H({ gap: 8, pad: [10, 16], fill: "surface", r: "chip", stroke: "border", align: "center" }, T(a.title, "lead", "text", { weight: 400 }), T(String(count(a)), "mac-code", "text-secondary")))),
    T(`${ctx.screens.length} surfaces`, "mac-code", "text-secondary"));
}

const label = (s) => T(s, "caption", "text-secondary", { upper: true, weight: 600 });
const hexOf = (c) => (c.alpha < 1 ? `${c.hex} · ${Math.round(c.alpha * 100)}%` : c.hex);
const swatch = (name, c) => V({ gap: 6, w: 150 },
  V({ w: "fill", h: 56, fill: name, r: 10, stroke: "border" }),
  T(name, "mac-caption", "text", { weight: 600 }),
  T(hexOf(c), "mac-code", "text-secondary"));

// Colour groups by prefix, in the order a reader meets them.
const GROUPS = [
  ["Brand roles", (n) => n in BRAND.color.light],
  ["Mark", (n) => ["mark-accent", "icon-top", "icon-bottom", "on-icon", "accent-on-icon"].includes(n)],
  ["Tints", (n) => ["primary-tint", "primary-muted", "danger-tint", "track", "text-tertiary"].includes(n)],
  ["iOS system", (n) => n.startsWith("ios-")],
  ["Mac window", (n) => n.startsWith("mac-")],
];

function column(title, colors, dark) {
  const body = V({ gap: 32, w: 760, pad: 32, fill: "background", r: 20, stroke: "border" },
    T(title, "mac-section", "text"),
    GROUPS.map(([g, test]) => V({ gap: 14, w: "fill" }, label(g),
      H({ gap: 16, wrap: true, w: "fill" }, Object.entries(colors).filter(([n]) => test(n)).map(([n, c]) => swatch(n, c))))));
  return dark ? U("dark", { w: 760, kids: [body] }) : body;
}

function ansi(ctx) {
  const roles = Object.keys(BRAND.ansi256["light-terminal"]);
  const sample = (bg, fg, prefix) => V({ gap: 6, pad: [14, 16], w: 380, fill: bg, r: 10, stroke: "border" },
    H({}, T("T", "term", `${prefix}primary`, { weight: 700 }), T("█", "term", `${prefix}needs-you`), T(" Teyla 0.58", "term", fg)),
    roles.map((r) => H({ gap: 0 }, T(`${r.padEnd(15)}`, "term", fg), T("Atlas · 2 waiting", "term", `${prefix}${r}`))));
  return V({ gap: 20, w: "fill" }, label("CLI · ANSI roles (ansi256)"),
    H({ gap: 32, w: "fill" },
      V({ gap: 8 }, T("Light terminal", "mac-caption", "text-secondary"), sample("term-bg", "term-fg", "ansi-")),
      V({ gap: 8 }, T("Dark terminal", "mac-caption", "text-secondary"), sample("term-dark-bg", "term-dark-fg", "ansi-dark-")),
      V({ gap: 6, w: "fill" }, T("16-colour fallback", "mac-caption", "text-secondary"),
        Object.entries(BRAND.ansi256["ansi16-fallback"]).map(([r, v]) => H({ gap: 12 }, T(r, "mac-code", "text", { w: 140 }), T(v, "mac-code", "text-secondary"))))));
}

export function foundations(ctx) {
  const t = ctx.tokens;
  const specimen = (name) => H({ gap: 32, align: "center", w: "fill" },
    V({ w: 220 }, T(`${name} · ${ctx.type[name].size}`, "mac-code", "text-secondary")), T("Atlas has two questions waiting", name, "text"));
  return V({ w: W, pad: 96, gap: 56, fill: "background", r: 32 },
    T("Foundations", "brief", "text", { size: 48 }),
    T(`brand/tokens.json ${BRAND.version}, the one source. Light on the left (bound to the variables), dark on the right (painted). System fonts only: SF Pro and SF Mono, drawn in Inter and Roboto Mono where Figma lacks them.`, "lead", "text-secondary", { weight: 400, w: "fill" }),
    H({ gap: 32, w: "fill" }, column("Light", t.colors, false), column("Dark", t.colors, true)),
    ansi(ctx),
    V({ gap: 16, w: "fill" }, label("Type"), Object.keys(ctx.type).map(specimen)),
    H({ gap: 64, w: "fill" },
      V({ gap: 16 }, label("Space"), Object.entries(t.space).map(([n, v]) =>
        H({ gap: 16, align: "center" }, T(n, "mac-code", "text-secondary", { w: 110 }), V({ w: v, h: 12, fill: "primary", r: 2 }), T(String(v), "mac-code", "text-secondary")))),
      V({ gap: 16 }, label("Radius"), H({ gap: 20, wrap: true, w: 640 }, Object.entries(t.radius).filter(([n]) => n !== "icon-body").map(([n, v]) =>
        V({ gap: 6, align: "center" }, V({ w: 72, h: 72, r: Math.min(v, 36), fill: "primary-tint", stroke: "primary" }), T(`${n} · ${v}`, "mac-code", "text-secondary"))))),
      V({ gap: 16 }, label("Mark"), H({ gap: 24, align: "end" }, [16, 24, 64, 128].map((s) => U("brandMark", { size: s }))),
        H({ gap: 0, pad: [10, 14], fill: "term-bg", r: 8, stroke: "border" }, T("T", "term", "ansi-primary", { weight: 700 }), T("█", "term", "ansi-needs-you"), T(" banner glyph", "term", "term-fg")))));
}

export function captures(pictures) {
  return V({ pad: 96, gap: 72, fill: "background", r: 32 },
    T("Captures", "brief", "text", { size: 48 }),
    T("Pictures the repo keeps (docs/img), to set beside the surfaces.", "lead", "text-secondary", { weight: 400 }),
    pictures.map(({ title, shots }) => V({ gap: 24 }, label(title),
      H({ gap: 48 }, shots.map((p) => V({ gap: 12 }, { t: "img", src: p.src, w: p.w, h: p.h, r: 12, stroke: "border" }, T(p.name, "mac-code", "text-secondary")))))));
}
