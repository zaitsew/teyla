// The iPhone app's own pieces, read from apps/ios/Teyla/UI (Components.swift, Cards.swift, DecisionsView.swift,
// HomeProducts.swift, PortfolioView.swift, ...) and apps/ios/TeylaWidget. Names start with `ios`. Colours are token names;
// the iOS neutrals (ios-card, ios-label, ios-label-2, ios-fill, ios-separator) are the system colours the app draws.
//   iosCard, iosHeader, iosFold, iosButton, iosChip, iosComposer, iosSegment   the shared parts (Components.swift, Grammar.swift)
//   iosGroup, iosRow, iosProductIcon, iosPill, iosHealth, iosEmpty, iosSync, iosSpark, iosTile   lists, rows and small marks
//   iosQuestionCard, iosOutcome, iosTaskRow, iosDoneCard, iosCloseFold, iosSentCard   Decisions
//   iosWidget (small, medium, lock, inline, empty), iosWidgetGrid   the activity widget
import { V, H, Z, T, I, U, SPACER } from "../dsl.mjs";

const hairline = "#747480@0.08"; // Palette.border: quaternarySystemFill
const tertiary = "#3C3C43@0.3"; // tertiaryLabel
const trackFill = "#767680@0.12"; // Palette.track: tertiarySystemFill

/** A grouped card (`.card()`: 16 pt padding, the panel radius). p: { kids, gap = 12, pad = 16, link } */
export function iosCard(p = {}) {
  return V({ name: "Card", w: "fill", gap: p.gap ?? 12, pad: p.pad ?? 16, fill: "ios-card", r: "ios-panel", link: p.link }, p.kids || []);
}

/** SectionHeader: a title (20 semibold), a count and a note. p: { title, count, note, trailing: text, link } */
export function iosHeader(p = {}) {
  return H({ name: "Section header", w: "fill", gap: 12, align: "baseline" },
    V({ w: "fill", gap: 2 },
      H({ gap: 8, align: "baseline" }, T(p.title || "", "ios-section", "ios-label"), p.count !== undefined ? T(String(p.count), "ios-body", "ios-label-2") : null),
      p.note ? T(p.note, "ios-caption", "ios-label-2", { w: "fill" }) : null),
    p.trailing ? T(p.trailing, "ios-body", "primary", { link: p.link }) : null);
}

/** Fold: a chevron, a title and what it holds when open. p: { title, detail, open, kids, link } */
export function iosFold(p = {}) {
  return V({ name: `Fold ${p.title || ""}`, w: "fill", gap: 12 },
    H({ name: "Fold header", w: "fill", h: 44, gap: 8, align: "center", link: p.link },
      T(p.title || "", "ios-body", "ios-label-2", { weight: 600 }),
      p.detail ? T(p.detail, "ios-caption", "ios-label-2") : null,
      SPACER,
      I(p.open ? "chevron.up" : "chevron.down", 13, "ios-label-2", { weight: "semibold" })),
    p.open ? p.kids || [] : null);
}

/**
 * A button. p: { label, kind: "prominent" | "bordered" | "text" = "bordered", size: "large" | "regular" | "small" = "regular",
 *   icon, tone: "primary" | "text" | "danger" (a bordered button's tint) = "primary", fill (true = full width), disabled, link }
 * `text` is a plain text button (Button with .font(body.weight(.medium)), 44 pt high).
 */
export function iosButton(p = {}) {
  const kind = p.kind || "bordered", size = p.size || "regular";
  if (kind === "text") {
    return H({ name: "Button", h: 44, w: p.fill ? "fill" : "hug", align: "center", justify: p.fill ? "center" : "start", link: p.link },
      T(p.label || "", "ios-body", p.tone || "primary", { weight: 500 }));
  }
  const h = size === "large" ? 50 : size === "small" ? 28 : 34;
  const tone = p.tone || "primary";
  const prominent = kind === "prominent";
  const content = [p.icon ? I(p.icon, size === "small" ? 13 : 17, prominent ? "#FFFFFF" : tone) : null,
    T(p.label || "", size === "small" ? "ios-caption" : "ios-text", prominent ? "#FFFFFF" : tone, { weight: prominent ? 600 : 400 })];
  const fill = prominent ? "primary" : tone === "text" ? "ios-fill" : `${tone}@0.15`;
  return H({ name: "Button", w: p.fill ? "fill" : "hug", h, pad: [0, size === "large" ? 20 : 14], gap: 6, align: "center", justify: "center", r: h / 2, fill, opacity: p.disabled ? 0.4 : 1, link: p.link }, content);
}

/** A chip of the option list (a bordered, regular button; the chosen one is tinted). p: { label, selected } */
export function iosChip(p = {}) {
  return U("iosButton", { label: p.label, kind: "bordered", size: "regular", tone: p.selected ? "primary" : "text", link: p.link });
}

/** The answer field and Send (Composer). p: { placeholder, text, sendLabel = "Send", sending } */
export function iosComposer(p = {}) {
  const has = !!(p.text && p.text.trim());
  return H({ name: "Composer", w: "fill", gap: 8, align: "center" },
    H({ name: "Field", w: "fill", h: 44, r: 12, fill: trackFill, align: "center", pad: [8, 4, 8, 12], gap: 4 },
      T(has ? p.text : p.placeholder || "Write an answer", "ios-text", has ? "ios-label" : "ios-label-2", { w: "fill" }),
      H({ name: "Mic", w: 36, h: 36, justify: "center", align: "center" }, I("mic", 20, "primary"))),
    U("iosButton", { label: p.sendLabel || "Send", kind: "prominent", size: "large", disabled: !has || p.sending, link: has ? p.sendLink : null }));
}

/** A segmented switch that fills the width (SegmentSwitch): Week / Month / Year, All / Needs attention. p: { options, selected } */
export function iosSegment(p = {}) {
  return H({ name: "Segments", w: "fill", gap: 2, pad: 4, r: "ios-card", fill: trackFill }, (p.options || []).map((o) =>
    H({ w: "fill", h: 44, pad: [0, 16], r: "ios-control", justify: "center", align: "center", fill: o === p.selected ? "#FFFFFF" : null },
      T(o, "ios-body", o === p.selected ? "ios-label" : "ios-label-2", { weight: 600 }))));
}

/** A group of rows on one panel with hairlines between (RowGroup). p: { kids } */
export function iosGroup(p = {}) {
  const kids = (p.kids || []).filter(Boolean);
  const out = [];
  kids.forEach((k, i) => { out.push(k); if (i < kids.length - 1) out.push(V({ w: "fill", h: 1, fill: "ios-separator" })); });
  return V({ name: "Group", w: "fill", pad: [4, 16], r: "ios-panel", fill: "ios-card", gap: 0 }, out);
}

/**
 * One row (RowCard): p: { title, detail, value, icon, iconTone, chevron, tone: colour of the title, valueTone, link }
 */
export function iosRow(p = {}) {
  return H({ name: `Row ${p.title || ""}`, w: "fill", gap: 12, pad: [8, 0], minH: 44, align: "center", link: p.link },
    p.icon ? I(p.icon, 17, p.iconTone || "ios-label-2") : null,
    V({ w: "fill", gap: 2 },
      T(p.title || "", "ios-body", p.tone || "ios-label", { weight: 600, w: "fill" }),
      p.detail ? T(p.detail, "ios-caption", "ios-label-2", { w: "fill" }) : null),
    p.value ? T(p.value, "ios-body", p.valueTone || "ios-label-2", { align: "right" }) : null,
    p.chevron ? I("chevron.right", 13, tertiary, { weight: "semibold" }) : null);
}

/** A product's icon: the first letter on a tint (ProductIcon). p: { letter, size = 34, quiet } */
export function iosProductIcon(p = {}) {
  const size = p.size || 34, r = size >= 48 ? 11 : size >= 34 ? 8 : 6;
  return H({ name: "Icon", w: size, h: size, r, fill: p.quiet ? trackFill : "primary-tint", justify: "center", align: "center" },
    T(p.letter || "A", "ios-card-title", p.quiet ? "ios-label-2" : "primary", { size: Math.round(size * 0.45), weight: 600 }));
}

/** Pill (a capsule of the colour at 14%). p: { text, tone: needs-you | saving | danger | primary | neutral } */
export function iosPill(p = {}) {
  return U("pill", p);
}

/** HealthPill: a symbol and a word. p: { health: "off track" | "at risk" | "on track" | "parked" } */
export function iosHealth(p = {}) {
  const map = { "off track": ["exclamationmark.octagon", "danger"], "at risk": ["exclamationmark.triangle", "needs-you"], "on track": ["checkmark.circle", "primary"], parked: ["pause.circle", "ios-label-2"] };
  const [sym, tone] = map[p.health] || map["on track"];
  const fill = tone === "ios-label-2" ? trackFill : `${tone}@0.14`;
  return H({ name: "Health", pad: [2, 8], gap: 4, r: "chip", fill, align: "center" }, I(sym, 12, tone), T(p.health || "on track", "ios-caption", tone, { weight: 600 }));
}

/** An empty or waiting block: a symbol, a headline and a line. p: { icon, title, detail, big (40 pt symbol) } */
export function iosEmpty(p = {}) {
  return V({ name: "Empty", w: "fill", gap: 12, align: "center", pad: [32, 0, 0, 0] },
    p.icon ? I(p.icon, 40, "ios-label-2") : null,
    T(p.title || "", p.big === false ? "ios-body" : "ios-section", p.big === false ? "ios-label-2" : "ios-label", { w: "fill", align: "center" }),
    p.detail ? T(p.detail, "ios-body", "ios-label-2", { w: "fill", align: "center" }) : null);
}

/** One quiet line with a symbol (a Label in secondary): "Nothing waits on you." p: { icon, text, tone } */
export function iosNote(p = {}) {
  return H({ name: "Note", w: "fill", gap: 6, align: "center" }, p.icon ? I(p.icon, 15, p.tone || "ios-label-2") : null, T(p.text || "", p.caption ? "ios-caption" : "ios-body", p.tone || "ios-label-2", { w: "fill" }));
}

/** SyncLine: "Mac synced 4 min ago", amber with the warning once older than 10 minutes. p: { state: "fresh" | "stale" | "syncing" | "preview", text } */
export function iosSync(p = {}) {
  const s = p.state || "fresh";
  if (s === "syncing") return H({ name: "Sync", gap: 4, align: "center" }, I("progress.indicator", 11, "ios-label-2"), T("Syncing", "ios-caption", "ios-label-2"));
  if (s === "preview") return H({ name: "Sync", gap: 4, align: "center" }, I("eye", 12, "ios-label-2"), T("Preview data", "ios-caption", "ios-label-2"));
  const stale = s === "stale";
  return H({ name: "Sync", gap: 4, align: "center" }, I(stale ? "exclamationmark.triangle.fill" : "checkmark.icloud", 12, stale ? "needs-you" : "ios-label-2"),
    T(p.text || (stale ? "Mac synced 14 min ago. The Mac may be asleep." : "Mac synced 2 min ago"), "ios-caption", stale ? "needs-you" : "ios-label-2"));
}

/** The commits-per-week bars (SparklineView). p: { bars: [0..1], h = 28, bar = 5 } */
export function iosSpark(p = {}) {
  const bars = p.bars || [0.3, 0.5, 0.4, 0.8, 0.6, 0.9, 1], h = p.h || 28, w = p.bar || 5;
  return H({ name: "Commits", gap: 2, align: "end", h }, bars.map((b, i) => V({ w, h: Math.max(2, Math.round(h * b)), r: 2, fill: i < bars.length - 3 ? "primary-muted" : "primary" })));
}

/** A stat tile of the pulse strip (StatTile): label, number, detail; the number is coloured by tone. p: { label, value, detail, tone, link } */
export function iosTile(p = {}) {
  return V({ name: "Tile", w: "fill", gap: 4, pad: 12, fill: "ios-card", r: "ios-card", stroke: hairline, minH: 92, link: p.link },
    T(p.label || "", "ios-caption", "ios-label-2"),
    T(p.value ?? "–", "ios-number", p.value == null ? tertiary : p.tone || "ios-label"),
    T(p.detail || " ", "ios-caption", "ios-label-2", { w: "fill", lines: 2 }));
}

// ---- Decisions ---------------------------------------------------------------------------------------------

/**
 * OutcomeView, under a card: what happened to a send. p: { state: "waiting" | "ok" | "failed" | "sample", text (what was sent), line (the result) }
 */
export function iosOutcome(p = {}) {
  const s = p.state || "waiting";
  const sent = p.text ? T(p.text, "ios-caption", "ios-label-2", { w: "fill", lines: 3 }) : null;
  if (s === "waiting") {
    return V({ name: "Outcome", w: "fill", gap: 8 },
      H({ gap: 8, align: "center" }, I("progress.indicator", 13, "ios-label-2"), T("Waiting for the Mac", "ios-body", "ios-label-2")), sent);
  }
  const [icon, tone, line, button] = s === "ok" ? ["checkmark.circle.fill", "saving", p.line || "Sent to the session", "Dismiss"]
    : s === "sample" ? ["info.circle.fill", "ios-label-2", "Sample: nothing was sent", "Dismiss"]
    : ["exclamationmark.triangle.fill", "danger", p.line || "The Mac could not deliver this", "Dismiss and try again"];
  return V({ name: "Outcome", w: "fill", gap: 8 },
    H({ w: "fill", gap: 6, align: "start" }, I(icon, 15, tone), T(line, "ios-body", tone, { w: "fill" })), sent,
    U("iosButton", { label: button, kind: "text", tone: "primary", link: p.dismissLink }));
}

/**
 * One question (QuestionCard): meta line, the question, three lines of context, then the proposal, "Use default",
 * the options and the answer field, or the outcome of a send.
 * p: { product, age, unblocks, question, context, proposed, why, options: [..], selected, draft,
 *      pay (no "Use default"), state: "answering" | "waiting" | "ok" | "failed" | "sample", sentText, line,
 *      links: { use, chip, send, dismiss } (screen ids a tap opens), link }
 */
export function iosQuestionCard(p = {}) {
  const meta = `${p.product} · ${p.age}${p.unblocks ? ` · Unblocks ${p.unblocks}` : ""}`;
  const state = p.state || "answering";
  const proposal = p.proposed ? V({ name: "Proposal", w: "fill", gap: 4, pad: 12, r: "ios-control", fill: "ios-bg" },
    T("Proposed default", "ios-caption", "primary", { weight: 600 }),
    T(p.proposed, "ios-body", "ios-label", { w: "fill" }),
    p.why ? T(p.why, "ios-caption", "ios-label-2", { w: "fill", lines: 2 }) : null) : null;
  const answering = V({ name: "Answering", w: "fill", gap: 12 },
    proposal,
    p.proposed && !p.pay ? U("iosButton", { label: "Use default", kind: "prominent", size: "large", fill: true, link: p.links?.use }) : null,
    p.options && p.options.length ? H({ name: "Options", w: "fill", gap: 8, wrap: true }, p.options.map((o) => U("iosChip", { label: o, selected: o === p.selected, link: p.links?.chip }))) : null,
    U("iosComposer", { placeholder: "Write an answer", text: p.draft, sendLink: p.links?.send }));
  return V({ name: "Question card", w: "fill", gap: 12, pad: 16, fill: "ios-card", r: "ios-panel", link: p.link },
    T(meta, "ios-caption", "ios-label-2", { w: "fill", lines: 2 }),
    T(p.question, "ios-card-title", "ios-label", { w: "fill" }),
    p.context ? T(p.context, "ios-body", "ios-label-2", { w: "fill", lines: 3 }) : null,
    state === "answering" ? answering : U("iosOutcome", { state, text: p.sentText, line: p.line, dismissLink: p.links?.dismiss }));
}

/** TaskRow (Only you): a merge or checklist symbol, the meta line, the title, the detail and an arrow. p: { kind: "merge" | "checklist", meta, title, detail } */
export function iosTaskRow(p = {}) {
  return H({ name: "Task", w: "fill", gap: 12, pad: 16, fill: "ios-card", r: "ios-panel", align: "start" },
    V({ w: 20, align: "center" }, I(p.kind === "merge" ? "arrow.triangle.merge" : "checklist", 20, "primary")),
    V({ w: "fill", gap: 2 },
      T(p.meta, "ios-caption", "ios-label-2", { w: "fill" }),
      T(p.title, "ios-body", "ios-label", { weight: 500, w: "fill" }),
      p.detail ? T(p.detail, "ios-body", "ios-label-2", { w: "fill" }) : null),
    I("arrow.up.right", 13, tertiary, { weight: "semibold" }));
}

/** DoneCard: product and age, a status pill, the title, up to three result lines, what it needs, links. p: { headline, status, title, result: [..], needs, links: [..] } */
export function iosDoneCard(p = {}) {
  const tones = { Done: "saving", "Needs you": "needs-you", Blocked: "danger", Failed: "danger", "Review ready": "primary" };
  return V({ name: "Done card", w: "fill", gap: 8, pad: 16, fill: "ios-card", r: "ios-panel" },
    H({ w: "fill", align: "baseline", gap: 8 }, T(p.headline, "ios-caption", "ios-label-2", { w: "fill" }), U("pill", { text: p.status, tone: tones[p.status] || "neutral" })),
    T(p.title, "ios-card-title", "ios-label", { w: "fill" }),
    (p.result || []).slice(0, 3).map((l) => T(l, "ios-body", "ios-label", { w: "fill" })),
    p.needs ? H({ w: "fill", gap: 6, align: "start" }, I("hand.raised.fill", 15, "needs-you"), T(p.needs, "ios-body", "needs-you", { weight: 500, w: "fill" })) : null,
    p.links && p.links.length ? H({ gap: 8, wrap: true }, p.links.map((l) => U("iosButton", { label: l, kind: "bordered", size: "small", icon: "link", tone: "text" }))) : null);
}

/** "Sent from this iPhone": what this phone sent that no card shows any more. p: { heading, state, text, line } */
export function iosSentCard(p = {}) {
  return V({ name: "Sent card", w: "fill", gap: 4, pad: 16, fill: "ios-card", r: "ios-panel" },
    T(p.heading, "ios-body", "ios-label", { weight: 600, w: "fill" }),
    U("iosOutcome", { state: p.state, text: p.text, line: p.line }));
}

/**
 * "Teyla suggests closing N": the fold, its questions, then Accept and what the Mac did with the request.
 * p: { count, open, items: [{ question, detail }], state: "idle" | "waiting" | "done" | "failed" | "sample", line, failure, link }
 */
export function iosCloseFold(p = {}) {
  const state = p.state || "idle";
  const rows = (p.items || []).map((it) => V({ name: "Suggestion", w: "fill", gap: 2, pad: [0, 0, 0, 16] },
    T(it.question, "ios-body", "ios-label", { w: "fill" }), T(it.detail, "ios-caption", "ios-label-2", { w: "fill" })));
  const status = [];
  if (state === "waiting") status.push(H({ gap: 8, align: "center" }, I("progress.indicator", 13, "ios-label-2"), T(`${p.line || "Closing 3\u2026"} Waiting for the Mac`, "ios-body", "ios-label-2")));
  if (state === "done") status.push(H({ w: "fill", gap: 8, align: "center" }, T(p.line || "Closed 3", "ios-body", "ios-label-2"), U("iosButton", { label: "Undo", kind: "bordered", size: "large" })));
  if (state === "failed") status.push(H({ w: "fill", gap: 6, align: "start" }, I("exclamationmark.triangle.fill", 15, "danger"), T(p.failure || "The Mac could not close 1 of 3.", "ios-body", "danger", { w: "fill" })));
  if (state === "done" || state === "failed") status.push(U("iosButton", { label: "Dismiss", kind: "text", tone: "ios-label" }));
  return V({ name: "Close suggestions", w: "fill", gap: 12 },
    U("iosFold", { title: `Teyla suggests closing ${p.count}`, open: p.open, kids: rows }),
    state === "idle" ? U("iosButton", { label: `Accept these ${p.count}`, kind: "bordered", size: "large", tone: "primary" }) : null,
    status);
}

// ---- The activity widget -----------------------------------------------------------------------------------

/**
 * The activity grid (ActivityWidgetView.grid): 7 rows, Monday on top, the newest week at the right, squares that fill the height.
 * p: { weeks, cell, gap = 1.5, seed = 1, accented }
 */
export function iosWidgetGrid(p = {}) {
  const weeks = p.weeks || 10, cell = p.cell || 6, gap = p.gap ?? 1.5, seed = p.seed || 1;
  const level = (w, d) => ((w * 7 + d) * seed + Math.floor((w * 7 + d) / 5)) % 5;
  const fill = (l) => (l === 0 ? (p.accented ? "ios-label@0.15" : trackFill) : p.accented ? `ios-label@${(0.25 + 0.75 * [0, 0.3, 0.5, 0.75, 1][l]).toFixed(2)}` : `primary@${[0, 0.3, 0.5, 0.75, 1][l]}`);
  return H({ name: "Grid", gap }, Array.from({ length: weeks }, (_, w) => V({ gap }, Array.from({ length: 7 }, (_, d) => V({ w: cell, h: cell, r: cell * 0.22, fill: fill(level(w, d)) })))));
}

/**
 * The activity widget at the size of the spec's frame (small 170 x 170, medium 364 x 170, lock screen rectangular 172 x 76,
 * inline 240 x 22). Its colours are hardcoded in ActivityWidget.swift (Look.accent) and drawn as the code draws them.
 * p: { family: small | medium | lock | inline | empty-small | not-connected, github, growth, ghStreak, grStreak, updated }
 */
export function iosWidget(p = {}, ctx = {}) {
  const dev = ctx.screen?.device || { w: 170, h: 170 };
  const f = p.family || "small";
  const gh = p.github ?? "128", gr = p.growth ?? "4";
  const row = (name, n, streak, seed, weeks, big) => ({ name, n, streak, seed, weeks, big });
  if (f === "inline") {
    return H({ name: "Widget inline", w: dev.w, h: dev.h, align: "center", justify: "center", fill: "#1C1C1E", r: 6 }, T(`GitHub ${gh} · Growth ${gr}`, "ios-body", "#FFFFFF"));
  }
  if (f === "lock") {
    return V({ name: "Widget lock rectangular", w: dev.w, h: dev.h, pad: [8, 12], gap: 1, r: 14, fill: "#FFFFFF@0.15", justify: "center" },
      T("Today", "ios-card-title", "#FFFFFF", { weight: 600 }),
      [["GitHub", gh], ["Growth", gr]].map(([n, v]) => H({ w: "fill", align: "center" }, T(n, "ios-body", "#FFFFFF"), SPACER, T(v, "ios-body", "#FFFFFF", { weight: 600 }))));
  }
  if (f === "empty") {
    return V({ name: "Widget empty", w: dev.w, h: dev.h, pad: 16, gap: 4, r: 22, fill: "ios-card", stroke: hairline },
      T("Activity", "ios-caption", "ios-label", { weight: 600 }),
      T("Open Teyla once to fill this widget.", "ios-caption", "ios-label-2", { w: "fill", size: 11 }));
  }
  const rows = [row("GitHub", gh, p.ghStreak ?? 90, 7), row("Growth", gr, p.grStreak ?? 6, 3)];
  const connected = f !== "not-connected";
  if (f === "medium") {
    return V({ name: "Widget medium", w: dev.w, h: dev.h, pad: 16, gap: 6, r: 22, fill: "ios-card", stroke: hairline },
      rows.map((r) => H({ w: "fill", gap: 10, align: "center" },
        V({ w: "fill" }, U("iosWidgetGrid", { weeks: 17, cell: 6.9, seed: r.seed })),
        V({ w: 70, align: "end" },
          T(r.n, "ios-number", "ios-label", { size: 26, font: "rounded", align: "right" }),
          T(`${r.name} today`, "ios-caption", "ios-label-2", { size: 11, align: "right" }),
          T(`streak ${r.streak}`, "ios-caption", tertiary, { size: 11, align: "right" })))),
      T(p.updated || "Updated 09:41", "ios-caption", tertiary, { size: 9 }));
  }
  return V({ name: "Widget small", w: dev.w, h: dev.h, pad: 16, gap: 8, r: 22, fill: "ios-card", stroke: hairline },
    rows.map((r) => V({ w: "fill", gap: 3 },
      H({ w: "fill", align: "baseline", gap: 4 }, T(r.name, "ios-caption", "ios-label-2", { size: 11, weight: 600 }), SPACER,
        T(connected ? r.n : "–", "ios-card-title", "ios-label", { size: 20, weight: 600, font: "rounded" })),
      connected ? U("iosWidgetGrid", { weeks: 10, cell: 4.1, seed: r.seed }) : T("Not connected", "ios-caption", tertiary, { size: 11 }))));
}

// ---- Home --------------------------------------------------------------------------------------------------

/** The five pulse tiles in rows of two (StatStrip: a tile is at least 150 pt wide, so two fit a phone). p: { tiles: [{label, value, detail, tone, link}] } */
export function iosPulse(p = {}) {
  const tiles = p.tiles || [], rows = [];
  for (let i = 0; i < tiles.length; i += 2) rows.push(tiles.slice(i, i + 2));
  return V({ name: "Pulse strip", w: "fill", gap: 12 }, rows.map((r) => H({ w: "fill", gap: 12 }, r.map((t) => U("iosTile", t)), r.length === 1 ? V({ w: "fill" }) : null)));
}

/** The Next line: one line that names the top decision; it opens Decisions. p: { text, link } or { done: text } for "nothing waits" */
export function iosNext(p = {}) {
  if (p.done) return U("iosNote", { icon: "checkmark.circle", text: p.done });
  return H({ name: "Next", w: "fill", gap: 8, minH: 44, align: "center", link: p.link },
    T("Next", "ios-body", "primary", { weight: 600 }), T(p.text, "ios-body", "ios-label", { w: "fill", lines: 2 }), I("chevron.right", 13, tertiary));
}

/** "People use these": a hero card. p: { name, stage, summary, active, new, total, commits, spend, money, bars, letter, link } */
export function iosHeroCard(p = {}) {
  const fig = (v, l) => V({ w: "fill", gap: 4 }, T(v, "ios-number", "ios-label"), T(l, "ios-caption", "ios-label-2"));
  return V({ name: `Hero ${p.name}`, w: "fill", gap: 12, pad: 16, fill: "ios-card", r: "ios-panel", link: p.link },
    H({ w: "fill", gap: 12, align: "start" }, U("iosProductIcon", { letter: p.name[0], size: 48 }),
      V({ w: "fill", gap: 2 },
        H({ gap: 8, align: "baseline" }, T(p.name, "ios-section", "ios-label"), T(p.stage, "ios-caption", "ios-label-2")),
        T(p.summary, "ios-caption", "ios-label-2", { w: "fill", lines: 3 }))),
    H({ w: "fill", gap: 8, align: "start" }, fig(p.active, "active"), fig(p.new, "new"), fig(p.total, "total")),
    V({ w: "fill", h: 1, fill: "ios-separator" }),
    H({ w: "fill", gap: 8, align: "end" }, V({ w: "fill", gap: 2 }, T(p.commits, "ios-body", "ios-label", { weight: 600 }), T(p.spend, "ios-caption", "ios-label-2", { w: "fill" })), U("iosSpark", { bars: p.bars, h: 28, bar: 5 })),
    H({ w: "fill", pad: [8, 12], r: "ios-card", fill: "ios-bg", align: "center" }, T("Monetization", "ios-body", "ios-label-2"), SPACER, T(p.money, "ios-body", "ios-label-2", { weight: 600 })));
}

/** The white panel of a list with a fold button at its foot ("Show all 9" / "Show fewer"). p: { kids, fold } */
export function iosPanel(p = {}) {
  const kids = (p.kids || []).filter(Boolean), out = [];
  kids.forEach((k, i) => { out.push(k); if (i < kids.length - 1 || p.fold) out.push(V({ w: "fill", h: 1, fill: "ios-separator" })); });
  if (p.fold) out.push(H({ w: "fill", h: 44, justify: "center", align: "center", link: p.link }, T(p.fold, "ios-body", "primary", { weight: 600 })));
  return V({ name: "List panel", w: "fill", pad: [0, 12], r: "ios-panel", fill: "ios-card", gap: 0 }, out);
}

/** "Being built": icon, name, summary, commit count. p: { name, summary, count, link } */
export function iosBuiltRow(p = {}) {
  return H({ name: `Built ${p.name}`, w: "fill", gap: 12, pad: [4, 0], minH: 44, align: "center", link: p.link },
    U("iosProductIcon", { letter: p.name[0], size: 34 }),
    V({ w: "fill", gap: 2 }, T(p.name, "ios-body", "ios-label", { weight: 600 }), T(p.summary, "ios-caption", "ios-label-2", { w: "fill", lines: 1 })),
    V({ align: "end" }, T(p.count, "ios-body", "ios-label", { weight: 600 }), T(p.count === "1" ? "commit" : "commits", "ios-caption", "ios-label-2")));
}

/** "Quiet": a smaller icon on grey, the 7-day commits over "this week". p: { name, summary, count, link } */
export function iosQuietRow(p = {}) {
  return H({ name: `Quiet ${p.name}`, w: "fill", gap: 12, pad: [4, 0], minH: 44, align: "center", link: p.link },
    U("iosProductIcon", { letter: p.name[0], size: 26, quiet: true }),
    V({ w: "fill", gap: 2 }, T(p.name, "ios-body", "ios-label", { weight: 500 }), T(p.summary, "ios-caption", "ios-label-2", { w: "fill", lines: 1 })),
    V({ align: "end" }, T(`${p.count} commits`, "ios-caption", "ios-label-2", { align: "right" }), T("this week", "ios-caption", "ios-label-2", { align: "right" })));
}

/** A running session (RunningCard). p: { title, detail, correct } */
export function iosRunningCard(p = {}) {
  return V({ name: "Running card", w: "fill", gap: 8, pad: 16, fill: "ios-card", r: "ios-panel" },
    H({ w: "fill", gap: 8, align: "baseline" }, V({ w: 6, h: 6, r: 3, fill: "saving" }),
      V({ w: "fill", gap: 2 }, T(p.title, "ios-body", "ios-label", { weight: 500, w: "fill" }), T(p.detail, "ios-caption", "ios-label-2", { w: "fill" })),
      p.correct ? U("iosButton", { label: "Correct", kind: "bordered", size: "small" }) : null));
}

/** A row of the Today screen (Lab): meta, question, chevron. p: { meta, title, link } */
export function iosDecisionRow(p = {}) {
  return H({ name: "Decision row", w: "fill", gap: 8, pad: [8, 0], minH: 44, align: "center", link: p.link },
    V({ w: "fill", gap: 2 }, T(p.meta, "ios-caption", "ios-label-2", { w: "fill" }), T(p.title, "ios-body", "ios-label", { weight: 600, w: "fill", lines: 3 })),
    I("chevron.right", 13, tertiary));
}

/** EmptyState inside a RowGroup: a symbol, a title and a line. p: { icon, title, detail } */
export function iosEmptyRow(p = {}) {
  return H({ name: "Empty row", w: "fill", gap: 8, pad: [8, 0], align: "start" }, I(p.icon || "checkmark.circle", 15, "ios-label-2"),
    V({ w: "fill", gap: 2 }, T(p.title, "ios-body", "ios-label", { w: "fill" }), p.detail ? T(p.detail, "ios-caption", "ios-label-2", { w: "fill" }) : null));
}

// ---- Products ----------------------------------------------------------------------------------------------

/**
 * One product on the list (PortfolioRow): icon, name, stage and reason, the earned stage and selling line, the health pill and a
 * chevron; then the platform symbols, the commits bars and three figures.
 * p: { name, subtitle, stageLine, selling, health, platforms: [{ icon, tone }], bars, prs, waiting, spend, link }
 */
export function iosProductRow(p = {}) {
  const fig = (v, l, tone) => V({ w: 56, align: "end", gap: 2 }, T(v, "ios-body", tone || "ios-label", { weight: 600, align: "right" }), T(l, "ios-caption", "ios-label-2", { align: "right" }));
  return V({ name: `Product ${p.name}`, w: "fill", gap: 8, pad: [12, 0], link: p.link },
    H({ w: "fill", gap: 12, align: "center" },
      U("iosProductIcon", { letter: p.name[0], size: 26 }),
      V({ w: "fill", gap: 2 },
        T(p.name, "ios-card-title", "ios-label"),
        T(p.subtitle, "ios-caption", "ios-label-2", { w: "fill", lines: 2 }),
        p.stageLine ? H({ gap: 4, align: "center" }, I(p.selling ? "megaphone" : "flag", 12, p.selling ? "primary" : "ios-label-2"), T(p.stageLine, "ios-caption", p.selling ? "primary" : "ios-label-2", { weight: 500 })) : null),
      p.health && p.health !== "on track" ? U("iosHealth", { health: p.health }) : null,
      I("chevron.right", 13, tertiary, { weight: "semibold" })),
    H({ w: "fill", gap: 8, align: "end" },
      H({ gap: 4, align: "center" }, (p.platforms || []).map((x) => I(x.icon, 13, x.tone || "ios-label-2"))),
      SPACER, V({ w: 56, align: "end" }, U("iosSpark", { bars: p.bars, h: 18, bar: 3 })),
      fig(String(p.prs ?? 0), "PRs"), fig(String(p.waiting ?? 0), "Waiting", p.waiting > 0 ? "needs-you" : null), fig(p.spend || "$0", "7 days")));
}

/** A platform card of the product page (PlatformCard). p: { icon, name, primary, line, lineTone, detail, checked, link } */
export function iosPlatformCard(p = {}) {
  return V({ name: `Platform ${p.name}`, w: "fill", gap: 4, pad: 16, fill: "ios-card", r: "ios-panel" },
    H({ gap: 8, align: "baseline" }, I(p.icon, 15, "ios-label-2"), T(p.name, "ios-card-title", "ios-label"), p.primary ? T("primary", "ios-caption", "ios-label-2") : null),
    T(p.line, "ios-body", p.lineTone || "ios-label", { weight: 500, w: "fill" }),
    p.detail ? T(p.detail, "ios-body", "ios-label-2", { w: "fill" }) : null,
    p.checked ? T(p.checked, "ios-caption", "ios-label-2") : null,
    p.link ? U("iosButton", { label: p.link, kind: "bordered", size: "small", icon: "link", tone: "text" }) : null);
}

/** One rung of the stage ladder. p: { title, status: met | missing | stale | not_applicable, word, detail } */
export function iosRung(p = {}) {
  const sym = { met: "checkmark.circle.fill", missing: "circle", stale: "clock.badge.exclamationmark", not_applicable: "minus.circle" }[p.status] || "questionmark.circle";
  const tone = { met: "saving", stale: "needs-you", not_applicable: tertiary }[p.status] || "ios-label-2";
  return H({ name: `Rung ${p.title}`, w: "fill", gap: 12, pad: [8, 0], minH: 44, align: "baseline" }, V({ w: 20 }, I(sym, 15, tone)),
    V({ w: "fill", gap: 2 }, T(p.title, "ios-body", "ios-label", { weight: 600, w: "fill" }), T(p.word, "ios-caption", tone, { weight: 600 }), p.detail ? T(p.detail, "ios-caption", "ios-label-2", { w: "fill" }) : null));
}

/** A big number and what it counts (the product page's Number). p: { value, label, highlight } */
export function iosNumber(p = {}) {
  return V({ w: "fill", gap: 2 }, T(String(p.value), "ios-section", p.highlight ? "needs-you" : "ios-label"), T(p.label, "ios-caption", "ios-label-2", { w: "fill" }));
}

/** The sample banner above the tabs (SampleBanner). */
export function iosSampleBanner() {
  return H({ name: "Sample banner", w: "fill", pad: [8, 16], gap: 8, align: "center", fill: "ios-bar" }, I("eye", 13, "ios-label-2"),
    T("Sample data \u2014 pair with your Mac to see yours", "ios-caption", "ios-label-2", { w: "fill" }), U("iosButton", { label: "Pair", kind: "prominent", size: "small" }));
}

/** A system alert. p: { title, message, buttons: [{ label, tone }] } */
export function iosAlert(p = {}) {
  const btns = p.buttons || [{ label: "OK" }];
  return V({ name: "Alert", w: 270, r: 14, fill: "ios-bar", stroke: "#000000@0.06", shadow: { x: 0, y: 8, blur: 30, color: "#000000@0.2" }, gap: 0 },
    V({ w: "fill", pad: [20, 16, 16, 16], gap: 4, align: "center" }, T(p.title, "ios-card-title", "ios-label", { align: "center", w: "fill" }), T(p.message, "ios-caption", "ios-label", { align: "center", w: "fill" })),
    btns.map((b) => V({ w: "fill", gap: 0 }, V({ w: "fill", h: 1, fill: "ios-separator" }), H({ w: "fill", h: 44, justify: "center", align: "center" }, T(b.label, "ios-text", b.tone || "primary", { weight: b.bold ? 600 : 400 })))));
}

/** A tab screen in sample mode: the banner sits above the tab bar (RootView). p: as iosScreen. */
export function iosSampleScreen(p = {}, ctx = {}) {
  return V({ name: "Screen", w: "fill", fill: "ios-bg" },
    U("iosStatusBar"), U("iosNavBar", p),
    V({ name: "Page", w: "fill", gap: p.gap ?? 24, pad: [8, 16, 120, 16] }, p.kids || []),
    iosSampleBanner(),
    U("iosTabBar", { selected: p.tab, badges: p.badges, linked: p.linked }));
}
