// The Mac app's own parts for the Figma generator, read from apps/mac/Teyla/UI (Grammar.swift, AskCard.swift,
// HomeProducts.swift, PortfolioViews.swift, MenuBar.swift, QuickNoteView.swift, CommandBarView.swift). Names carry the
// `mac` prefix: a name may be defined once across the folder. A spec calls one as { "t": "use", "c": "<name>", "p": {} }.
//   macBtn, macChip, macField, macSegment, macFold   controls (SwiftUI .borderedProminent, .bordered, .link; Chip; SegmentSwitch; Fold)
//   macPageHeader, macSection, macEmpty, macError      page grammar (PageHeader, SectionHeader, EmptyState, ErrorRow)
//   macAsk                                              the ask card, every state (AskCard)
//   macProductIcon, macSpark, macHero, macBuilt, macQuiet   Home's product cards (HomeProducts.swift, Scorecard)
//   macRowGroup, macRow                                 a grouped list and its rows (RowGroup, RowCard)
//   macPopover, macQuickNote, macCommandBar, macSheet   the menu bar popover, the quick note panel, the command bar, a sheet
import { V, H, T, I, SPACER } from "../dsl.mjs";

const shadow = (y, blur, a) => ({ x: 0, y, blur, color: `#000000@${a}` });

/** A button. p: { text, kind: "prominent" | "bordered" | "link" | "borderless" = "bordered", icon?, big?, off?, link? } */
export function macBtn(p = {}) {
  const kind = p.kind || "bordered";
  const prominent = kind === "prominent";
  const plain = kind === "link" || kind === "borderless";
  const tone = prominent ? "on-primary" : kind === "link" ? "primary" : kind === "borderless" ? "text-secondary" : "text";
  const pad = p.big ? [8, 18] : [5, 12];
  return H({ name: `Button ${p.text || ""}`.trim(), gap: 6, pad: plain ? [0, 0] : pad, r: "mac-control", align: "center",
    fill: prominent ? "primary" : plain ? null : "track", stroke: null, opacity: p.off ? 0.45 : undefined, link: p.link },
    p.icon ? I(p.icon, 13, tone) : null,
    T(p.text || "", "mac-body", tone, prominent ? { weight: 500 } : {}));
}

/** A chip (Chip in Tokens.swift): status colour at 16%. p: { text, tone: primary | needs-you | saving | danger | neutral = neutral, icon? } */
export function macChip(p = {}) {
  const tone = p.tone && p.tone !== "neutral" ? p.tone : "text-secondary";
  return H({ name: "Chip", gap: 4, pad: [2, 8], r: "chip", fill: `${tone}@0.16`, align: "center" },
    p.icon ? I(p.icon, 10, tone) : null, T(p.text || "", "mac-caption", tone, { weight: 500 }));
}

/** A rounded text field. p: { text?, placeholder?, w = "fill", lines = 1 } */
export function macField(p = {}) {
  return H({ name: "Field", w: p.w ?? "fill", pad: [5, 8], r: "mac-control", fill: "background", stroke: "border", align: "center", minH: (p.lines || 1) > 1 ? 22 * p.lines : undefined },
    p.text ? T(p.text, "mac-body", "text", { w: "fill" }) : T(p.placeholder || "", "mac-body", "text-tertiary", { w: "fill" }));
}

/** The Week / Month / Year switch (SegmentSwitch). p: { options: [text], selected: text } */
export function macSegment(p = {}) {
  return H({ name: "Switch", gap: 2, pad: 4, r: "card", fill: "track", align: "center" },
    (p.options || []).map((o) => H({ h: 36, pad: [0, 16], r: "mac-control", align: "center", fill: o === p.selected ? "surface" : null },
      T(o, "mac-body", o === p.selected ? "text" : "text-secondary", { weight: 600 }))));
}

/** A fold (Fold): chevron, title, quiet detail; kids below when open. p: { title, detail?, open?, kids } */
export function macFold(p = {}) {
  return V({ name: "Fold", w: "fill", gap: 12 },
    H({ gap: 4, align: "center" }, I(p.open ? "chevron.down" : "chevron.right", 11, "text-secondary"),
      T(p.title || "", "mac-body", "text-secondary", { weight: 600 }), p.detail ? T(p.detail, "mac-caption", "text-secondary") : null),
    p.open ? V({ w: "fill", gap: 12 }, p.kids || []) : null);
}

/** The title of a page and one line of context (PageHeader). p: { title, context?, trailing?: node } */
export function macPageHeader(p = {}) {
  return H({ name: "Page header", w: "fill", align: "center", gap: 12 },
    V({ gap: 2 }, T(p.title || "", "mac-page-title", "text"), p.context ? T(p.context, "mac-body", "text-secondary") : null),
    SPACER, p.trailing || null);
}

/** The title of a block, its rule and a count (SectionHeader). p: { title, note?, count?, trailing?: node } */
export function macSection(p = {}) {
  return H({ name: "Section header", w: "fill", align: "center", gap: 12 },
    V({ gap: 2 },
      H({ gap: 8, align: "baseline" }, T(p.title || "", "mac-section", "text"), p.count !== undefined ? T(String(p.count), "mac-body", "text-secondary") : null),
      p.note ? T(p.note, "mac-caption", "text-secondary") : null),
    SPACER, p.trailing || null);
}

/** EmptyState. p: { symbol, title, detail? } */
export function macEmpty(p = {}) {
  return V({ name: "Empty", w: "fill", gap: 8, pad: [24, 0], align: "center" },
    I(p.symbol || "checkmark.circle", 28, "text-secondary"),
    T(p.title || "", "mac-card-title", "text", { align: "center", w: "fill" }),
    p.detail ? T(p.detail, "mac-body", "text-secondary", { align: "center", w: "fill" }) : null);
}

/** ErrorRow. p: { section, message, retry = true } */
export function macError(p = {}) {
  return V({ name: "Error row", w: "fill", gap: 8 },
    H({ gap: 6, align: "center" }, I("exclamationmark.triangle", 14, "needs-you"), T(`Could not read ${p.section}`, "mac-card-title", "needs-you")),
    T(p.message || "", "mac-body", "text-secondary", { w: "fill" }),
    p.retry === false ? null : macBtn({ text: "Try again" }));
}

// ---- the ask card (AskCard.swift) ---------------------------------------------------------------------------

/**
 * One ask card. The order never changes: question, why, proposed default, action. At 860 pt and wider the last two sit
 * beside the first two (p.wide). p: { product, age, unblocks?, question, context?, proposal?, why?, options: [text],
 * canUseProposal = true, older?, highlighted?, wide?, note?, state: idle | composing | sending | done | failed,
 * text? (the sending / done / failed line), draft?, link? }
 */
export function macAsk(p = {}) {
  const state = p.state || "idle";
  const header = H({ w: "fill", align: "baseline", gap: 12 },
    H({ gap: 0 },
      T(p.product || "", "mac-caption", "primary"),
      T(` · ${p.age || ""}`, "mac-caption", "text-secondary"),
      p.unblocks ? T(` · Unblocks ${p.unblocks}`, "mac-caption", "text-secondary") : null),
    SPACER,
    p.older && state === "idle" ? T("Close — no longer needed", "mac-caption", "text-secondary") : null);
  const question = V({ name: "Question", w: "fill", gap: 12 },
    header,
    T(p.question || "", "mac-card-title", "text", { w: "fill" }),
    p.context ? T(p.context, "mac-body", "text-secondary", { w: "fill" }) : null);
  const proposal = p.proposal ? V({ name: "Proposed default", w: "fill", gap: 4, pad: 12, r: "mac-control", fill: "background" },
    T("Proposed default", "mac-caption", "primary", { weight: 600 }),
    T(p.proposal, "mac-body", "text", { w: "fill" }),
    p.why ? T(p.why, "mac-caption", "text-secondary", { w: "fill" }) : null) : null;
  const note = p.note ? H({ w: "fill", gap: 6, align: "center" }, I("doc.on.clipboard", 13, "text-secondary"), T(p.note, "mac-body", "text-secondary", { w: "fill" })) : null;
  const options = p.options || [];
  const lead = p.proposal && p.canUseProposal !== false;
  let action;
  if (state === "sending") {
    action = H({ w: "fill", gap: 8, align: "center" }, I("progress.indicator", 12, "text-secondary"), T(p.text || "Sending the answer…", "mac-body", "text-secondary", { w: "fill" }));
  } else if (state === "done") {
    action = H({ w: "fill", gap: 6, align: "start" }, I("checkmark.circle.fill", 14, "saving"), T(p.text || "", "mac-body", "saving", { w: "fill" }));
  } else if (state === "failed") {
    action = V({ w: "fill", gap: 8 },
      H({ w: "fill", gap: 6, align: "start" }, I("exclamationmark.triangle.fill", 14, "danger"), T(p.text || "", "mac-body", "danger", { w: "fill" })),
      H({ gap: 8 }, macBtn({ text: "Open session", kind: "prominent" }), macBtn({ text: "Back" })));
  } else if (state === "composing") {
    action = V({ w: "fill", gap: 8 },
      H({ w: "fill", gap: 8, align: "center" }, macField({ text: p.draft, placeholder: "Write an answer" }), I("mic", 14, "text-secondary"),
        macBtn({ text: "Send", kind: "prominent", off: !p.draft }), macBtn({ text: "Cancel", kind: "borderless" })),
      T("Dictation stays on this Mac.", "mac-caption", "text-secondary"));
  } else {
    action = H({ w: "fill", gap: 8, wrap: true },
      lead ? macBtn({ text: "Use default", kind: "prominent" }) : null,
      options.map((o, i) => macBtn({ text: o, kind: i === 0 && !lead ? "prominent" : "bordered" })),
      macBtn({ text: "Answer…", kind: !options.length && !lead ? "prominent" : "bordered" }));
  }
  const response = V({ name: "Response", w: p.wide ? 360 : "fill", gap: 12 }, proposal, note, action);
  const body = p.wide
    ? H({ w: "fill", gap: 24, align: "start" }, V({ w: "fill" }, question), response)
    : V({ w: "fill", gap: 12 }, question, response);
  return V({ name: "Ask card", w: "fill", pad: 16, r: "card", fill: "surface", stroke: p.highlighted ? "primary" : "border", sw: p.highlighted ? 2 : 1, link: p.link }, body);
}

// ---- Home's product cards (HomeProducts.swift, Grammar.swift Scorecard) --------------------------------------

/** A product icon: the first letter on a tint of the primary colour. p: { letter, size = 44 } */
export function macProductIcon(p = {}) {
  const size = p.size || 44;
  const r = size >= 56 ? 13 : size >= 44 ? 10 : 7;
  return V({ name: "Product icon", w: size, h: size, r, fill: "primary-tint", align: "center", justify: "center" },
    T(p.letter || "A", "mac-card-title", "primary", { size: Math.round(size * 0.46), weight: 600 }));
}

/** The commits-per-week bars; the newest week stands out. p: { heights: [0..1], h = 18, bar = 3 } */
export function macSpark(p = {}) {
  const h = p.h || 18, bar = p.bar || 3, hs = p.heights || [];
  return H({ name: "Commits", gap: 2, align: "end", h }, hs.map((v, i) =>
    V({ w: bar, h: Math.max(2, Math.round(h * v)), r: 2, fill: i === hs.length - 1 ? "primary" : "primary@0.35" })));
}

/** A hero card ("People use these"). p: { letter, name, stage, summary, numbers: [[value, label]], commits, spend, spark: [], money = "Off", link } */
export function macHero(p = {}) {
  const [n1, n2, n3] = p.numbers || [];
  const num = (n) => V({ w: "fill", gap: 2 }, T(n[0], "mac-number", n[0] === "–" ? "text-tertiary" : "text"), T(n[1], "mac-caption", "text-secondary"));
  return V({ name: "Hero card", w: "fill", gap: 16, pad: 16, r: "mac-panel", fill: "surface", stroke: "border", link: p.link },
    H({ w: "fill", gap: 12, align: "start" }, macProductIcon({ letter: p.letter, size: 56 }),
      V({ w: "fill", gap: 2 },
        H({ gap: 8, align: "baseline" }, T(p.name, "mac-section", "text"), T(p.stage || "", "mac-caption", "text-secondary")),
        T(p.summary || "", "mac-body", "text-secondary", { w: "fill", lines: 2 }))),
    H({ w: "fill", gap: 12, align: "start" }, num(n1), num(n2), num(n3)),
    V({ w: "fill", h: 1, fill: "border" }),
    H({ w: "fill", gap: 12, align: "end" },
      V({ w: "fill", gap: 2 }, T(p.commits || "", "mac-card-title", "text"), T(p.spend || "", "mac-caption", "text-secondary", { w: "fill" })),
      macSpark({ heights: p.spark, h: 34, bar: 7 })),
    H({ w: "fill", pad: [8, 12], r: "card", fill: "background", align: "center" },
      T("Monetization", "mac-body", "text-secondary"), SPACER, T(p.money || "Off", "mac-body", "text-secondary", { weight: 600 })));
}

/** A "Being built" card. p: { letter, name, summary, commits, spark: [], link } */
export function macBuilt(p = {}) {
  return H({ name: "Built card", w: "fill", gap: 12, pad: 12, r: "card", fill: "surface", stroke: "border", align: "center", link: p.link },
    macProductIcon({ letter: p.letter, size: 44 }),
    V({ w: "fill", gap: 2 }, T(p.name, "mac-card-title", "text"), T(p.summary || "", "mac-caption", "text-secondary", { w: "fill", lines: 2 })),
    V({ gap: 2, align: "end" },
      T(p.commits || "0", "mac-card-title", "text"), T(p.commits === "1" ? "commit" : "commits", "mac-caption", "text-secondary"),
      macSpark({ heights: p.spark, h: 18, bar: 3 })));
}

/** The "Quiet" list: a plain row per product. p: { rows: [{ letter, name, summary, commits, link }] } */
export function macQuiet(p = {}) {
  const rows = p.rows || [];
  return V({ name: "Quiet list", w: "fill", pad: [4, 16], r: "card", fill: "surface", stroke: "border" },
    rows.flatMap((r, i) => [
      H({ w: "fill", h: 44, gap: 12, align: "center", link: r.link },
        macProductIcon({ letter: r.letter, size: 30 }), T(r.name, "mac-body", "text", { weight: 600, w: 160 }),
        T(r.summary || "", "mac-body", "text-secondary", { w: "fill" }), T(r.commits || "", "mac-body", "text-secondary")),
      i < rows.length - 1 ? V({ w: "fill", h: 1, fill: "border" }) : null]));
}

// ---- lists --------------------------------------------------------------------------------------------------

/** A grouped list: a surface with hairlines between its rows. p: { kids } */
export function macRowGroup(p = {}) {
  const kids = (p.kids || []).filter(Boolean);
  return V({ name: "Row group", w: "fill", pad: [0, 16], r: "card", fill: "surface", stroke: "border" },
    kids.flatMap((k, i) => [k, i < kids.length - 1 ? V({ w: "fill", h: 1, fill: "border" }) : null]));
}

/** A row (RowCard): title, detail, a trailing node or text. p: { title, detail?, value?, dim?, trailing?: node, leading?: node, link? } */
export function macRow(p = {}) {
  return H({ name: `Row ${p.title || ""}`.trim(), w: "fill", minH: 44, pad: [6, 0], gap: 12, align: "center", link: p.link },
    p.leading || null,
    V({ w: "fill", gap: 2 }, T(p.title || "", "mac-body", "text", { weight: 600 }), p.detail ? T(p.detail, "mac-caption", "text-secondary", { w: "fill" }) : null),
    p.trailing || (p.value !== undefined ? T(p.value, "mac-body", p.dim ? "text-secondary" : "text", { weight: p.dim ? 400 : 600 }) : null));
}

// ---- panels and sheets --------------------------------------------------------------------------------------

/** A sheet over the main window (the frame is the spec's device). p: { kids, pad = 24, gap = 16 } */
export function macSheet(p = {}) {
  return V({ name: "Sheet", w: "fill", gap: p.gap ?? 16, pad: p.pad ?? 24, fill: "background" }, p.kids || []);
}

/** The menu bar popover (MenuBar.swift), 320 pt wide. p: { brief, questions: [[product, question]], sample?, quickNote = "Quick note ⌥Space" } */
export function macPopover(p = {}) {
  const qs = p.questions || [];
  return V({ name: "Popover", w: "fill", gap: 12, pad: 16, r: "mac-panel", fill: "surface", stroke: "mac-edge", shadow: shadow(8, 28, 0.18) },
    p.sample ? T("Sample data — connect to see yours", "mac-caption", "text-secondary", { w: "fill" }) : null,
    T(p.brief || "", "mac-card-title", "text", { w: "fill" }),
    qs.length ? V({ w: "fill", gap: 12 }, V({ w: "fill", h: 1, fill: "border" }), qs.map(([product, q]) =>
      V({ w: "fill", gap: 2 }, T(product, "mac-caption", "text-secondary"), T(q, "mac-body", "text", { w: "fill", lines: 2 })))) : null,
    V({ w: "fill", h: 1, fill: "border" }),
    p.quickNote === false ? null : T(p.quickNote || "Quick note ⌥Space", "mac-body", "text", { w: "fill" }),
    H({ w: "fill", gap: 12, align: "center" },
      macBtn({ text: "Open Teyla" }), macBtn({ text: "New task" }), SPACER, macBtn({ text: "Quit" })));
}

const hint = (key, text) => H({ gap: 4, align: "center" },
  H({ pad: [2, 4], r: 4, fill: "surface" }, T(key, "mac-caption", "text", { weight: 500 })), T(text, "mac-caption", "text-secondary"));

/**
 * The quick note panel (QuickNoteView.swift), 580 x 244. p: { draft?, chips: [{ label, key, on }], how, state: idle | sending | done | failed, text? }
 */
export function macQuickNote(p = {}) {
  const chip = (c) => H({ gap: 4, pad: [4, 12], r: "chip", align: "center", fill: c.on ? "primary-tint" : "surface", stroke: c.on ? "primary" : "border" },
    T(c.label, "mac-body", "text", { weight: c.on ? 600 : 400 }), c.key ? T(`⌘${c.key}`, "mac-caption", "text-secondary") : null);
  const state = p.state || "idle";
  const outcome = state === "sending" ? H({ gap: 8, align: "center" }, I("progress.indicator", 12, "text-secondary"), T(p.text || "Saving…", "mac-body", "text-secondary"))
    : state === "done" ? H({ gap: 6, align: "center" }, I("checkmark.circle.fill", 14, "saving"), T(p.text || "", "mac-body", "saving"))
    : state === "failed" ? H({ w: "fill", gap: 6, align: "start" }, I("exclamationmark.triangle.fill", 14, "danger"), T(p.text || "", "mac-body", "danger", { w: "fill", lines: 3 }))
    : null;
  return V({ name: "Quick note", w: "fill", gap: 12, pad: 16, r: "mac-panel", fill: "mac-sidebar", stroke: "border", shadow: shadow(10, 30, 0.2) },
    V({ w: "fill", h: 72, pad: 8, r: "mac-control", fill: "background", stroke: "border" },
      p.draft ? T(p.draft, "mac-body", "text", { w: "fill" }) : T("An idea, in your own words", "mac-body", "text-tertiary")),
    H({ w: "fill", gap: 8, wrap: true }, (p.chips || []).map(chip)),
    T(p.how || "", "mac-caption", "text-secondary"),
    outcome,
    SPACER,
    V({ w: "fill", h: 1, fill: "border" }),
    H({ w: "fill", gap: 16, align: "center" }, hint("⏎", "save"), hint("⇧⏎", "new line"), hint("⌘1–9", "product"), hint("Esc", "close"), SPACER,
      T("Kept on this Mac", "mac-caption", "text-secondary")));
}

/** The command bar (CommandBarView.swift), 560 wide. p: { query?, rows: [{ icon, title, detail, code?, on? }], empty? } */
export function macCommandBar(p = {}) {
  const row = (r) => H({ w: "fill", gap: 12, pad: [8, 12], r: "card", fill: r.on ? "primary-tint" : null, align: "center" },
    V({ w: 20, align: "center" }, I(r.icon, 15, "text-secondary")),
    V({ w: "fill", gap: 2 }, T(r.title, "mac-body", "text"), T(r.detail, r.code ? "mac-code" : "mac-caption", "text-secondary")));
  return V({ name: "Command bar", w: "fill", fill: "surface", r: "mac-panel", stroke: "mac-edge", clip: true, shadow: shadow(12, 36, 0.22) },
    H({ w: "fill", pad: 16, align: "center" }, p.query ? T(p.query, "mac-card-title", "text") : T("Go to a page, a product or an action", "mac-card-title", "text-tertiary")),
    V({ w: "fill", h: 1, fill: "border" }),
    p.empty ? V({ w: "fill", pad: 16 }, T("Nothing matches. This list is fixed: pages, products, New task, Refresh and the actions on Operations.", "mac-caption", "text-secondary", { w: "fill" }))
      : V({ w: "fill", h: 320, gap: 2, pad: 8, clip: true }, (p.rows || []).map(row)));
}

// ---- windows without a sidebar, and the pairing code ---------------------------------------------------------

const lights = () => H({ name: "Traffic lights", gap: 8, align: "center" },
  ["#FF5F57", "#FEBC2E", "#28C840"].map((hex) => V({ w: 12, h: 12, r: 6, fill: hex, stroke: "#000000@0.12" })));

/** The Mac window with no sidebar (Welcome, the missing command, Store setup): traffic lights, then the page centred. p: { kids, gap = 24, pad = 32 } */
export function macBare(p = {}, ctx = {}) {
  const dev = ctx.screen?.device || { w: 1280, h: 800 };
  return V({ name: "Mac window", w: dev.w, h: dev.h, fill: "background", r: 12, stroke: "mac-edge", clip: true, shadow: shadow(12, 40, 0.18) },
    H({ w: "fill", pad: [18, 20, 0, 20] }, lights()),
    V({ name: "Page", w: "fill", h: "fill", gap: p.gap ?? 24, pad: p.pad ?? 32, align: "center", justify: "center" }, p.kids || []));
}

/** The pairing QR code, drawn as modules (a made-up pattern, not a real code). p: { size = 280, n = 25, seed = 3 } */
export function macQr(p = {}) {
  const size = p.size || 280, n = p.n || 25, cell = size / n;
  let s = (p.seed || 3) * 9301 + 49297;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  const finder = (x, y) => (x < 7 && y < 7) || (x >= n - 7 && y < 7) || (x < 7 && y >= n - 7);
  const ring = (x, y) => { const a = Math.min(x % (n - 7), 6), dx = x < 7 ? x : x - (n - 7), dy = y < 7 ? y : y - (n - 7); return Math.max(Math.abs(dx - 3), Math.abs(dy - 3)) !== 2; };
  const dark = (x, y) => (finder(x, y) ? ring(x, y) : rnd() > 0.52);
  const rows = [];
  for (let y = 0; y < n; y++) {
    const runs = []; let start = -1;
    for (let x = 0; x <= n; x++) {
      const on = x < n && dark(x, y);
      if (on && start < 0) start = x;
      if (!on && start >= 0) { runs.push([start, x - start]); start = -1; }
    }
    rows.push(...runs.map(([x0, len]) => V({ abs: { top: y * cell, left: x0 * cell }, w: len * cell, h: cell, fill: "#000000" })));
  }
  return { t: "z", name: "QR code", w: size, h: size, r: 10, fill: "#FFFFFF", clip: true, kids: rows };
}
