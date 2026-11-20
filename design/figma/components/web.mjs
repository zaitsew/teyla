// The web surfaces' own parts for the Figma generator, read from src/teyla/web (app.css, app.js: `teyla web`),
// site/public (assets/site.css, index.html: teyla.dev) and README.md. Names carry the `web` and `site` prefix.
//   webPage      the dashboard's shell: the top bar with the five tabs, then the page column (max 960)
//   webStat, webCard, webStrip, webEmpty, webBtn, webTag   the dashboard's parts (.stat, .card, .strip, .empty, .btn, .tag)
//   webStart, webSpend   the Start and Spend tabs, with their states
//   siteHome     the teyla.dev home, any width, light or dark (the one breakpoint is 44rem = 704 px)
//   readmeHero   the README as a repository page shows it
// The dashboard sets 13 px body text and 11 px captions on the brand colours (app.css), so the text styles carry a size.
import { V, H, Z, T, I, SPACER } from "../dsl.mjs";
import { brandMark } from "./core.mjs";

const body = (v, c = "text", p = {}) => T(v, "web-small", c, { w: "fill", ...p });
const cap = (v, c = "text-secondary", p = {}) => T(v, "web-small", c, { size: 11, ...p });
const mono = (v, c = "text", p = {}) => T(v, "term", c, { size: 12, ...p });

/** The lockup (brand/lockup.svg): the mark and the word, drawn from the mark so it follows the colours. */
const lockup = (h) => H({ name: "Lockup", gap: Math.round(h * 0.15), align: "center" }, brandMark({ size: h }), T("Teyla", "web-title", "text", { size: Math.round(h * 0.8), weight: 700 }));

// ---- the dashboard's parts ---------------------------------------------------------------------------------------

/** .btn: kind primary | plain | quiet. p: { text, kind, off, link } */
export function webBtn(p = {}) {
  const k = p.kind || "plain";
  return H({ name: `Button ${p.text}`, h: 30, pad: [0, 12], r: 6, align: "center", justify: "center", link: p.link, opacity: p.off ? 0.55 : undefined,
    fill: k === "primary" ? "primary" : k === "quiet" ? null : "surface", stroke: k === "plain" ? "border" : null },
    T(p.text, "web-small", k === "primary" ? "on-primary" : k === "quiet" ? "primary" : "text", { weight: 500 }));
}

/** .tag: tone needs-you | saving | primary | neutral */
export function webTag(p = {}) {
  const c = p.tone && p.tone !== "neutral" ? p.tone : "text-secondary";
  return H({ pad: [0, 8], r: "chip", stroke: p.tone && p.tone !== "neutral" ? c : "border", align: "center" }, cap(p.text, c, { weight: 500 }));
}

/** .strip: tone primary | error | warn | ok. p: { tone, text, kids } */
export function webStrip(p = {}) {
  const c = { primary: "primary", error: "danger", warn: "needs-you", ok: "saving" }[p.tone || "primary"];
  return H({ name: "Strip", w: "fill", pad: [8, 12], gap: 12, r: 6, align: "center", fill: `${c}@0.1`, stroke: c === "primary" ? "primary@0.3" : c },
    body(p.text, "text", { w: "hug" }), ...(p.kids || []));
}

/** .empty: a heading and one line. */
export function webEmpty(p = {}) {
  return V({ name: "Empty", w: "fill", pad: 16, gap: 4, r: 10, stroke: "border" },
    T(p.title, "web-head", "text", { weight: 500 }), body(p.text, "text-secondary"));
}

/** .stat tile. p: { num, label, tone } */
export function webStat(p = {}) {
  return V({ name: "Stat", w: "fill", pad: [12, 16], gap: 4, r: 10, fill: "surface", stroke: "border" },
    T(p.num, "web-title", p.tone || "text", { size: 28, weight: 600 }), body(p.label, "text-secondary", { size: 11 }));
}

/** .card */
export function webCard(p = {}) {
  return V({ name: "Card", w: "fill", pad: 16, gap: p.gap ?? 8, r: 10, fill: "surface", stroke: p.stroke || "border" }, p.kids || []);
}

const rule = () => V({ name: "Rule", w: "fill", h: 1, fill: "border" });
const nav = ["Start", "Today", "Products", "Notes", "Spend"];

/** The page: top bar (brand link, five tabs) and the column. p: { active, kids, width = 960 } */
export function webPage(p = {}) {
  const top = H({ name: "Top bar", w: "fill", pad: [12, 24], gap: 24, align: "center", fill: "surface", stroke: "border" },
    H({ name: "Brand", gap: 6, align: "center" }, brandMark({ size: 28 }), T("Teyla", "web-title", "text", { size: 22, weight: 700 })),
    H({ name: "Tabs", gap: 4, align: "center" }, nav.map((t) => H({ pad: [4, 12], r: 6, align: "center", fill: t === p.active ? "primary@0.14" : null },
      T(t, "web-small", t === p.active ? "primary" : "text-secondary", { weight: 500 })))));
  return V({ name: "Dashboard", w: "fill", fill: "background" }, top,
    H({ w: "fill", justify: "center", pad: [0, 0, 32, 0] }, V({ name: "Main", w: p.width || 960, pad: [24, 24, 0, 24], gap: 0 }, p.kids || [])));
}

const h1 = (v) => T(v, "web-title", "text", { size: 28, weight: 600 });
const sub = (v) => V({ w: "fill", pad: [4, 0, 16, 0] }, body(v, "text-secondary"));
const h2 = (v) => V({ w: "fill", pad: [24, 0, 8, 0] }, T(v, "web-head", "text", { weight: 500 }));
const counted = (t) => H({ gap: 4, align: "center", pad: [12, 0] }, cap(t), webBtn({ text: "Refresh", kind: "quiet" }));

// ---- Start --------------------------------------------------------------------------------------------------------

const OFFERS = [
  { id: "O1", title: "Compact long sessions earlier", change: "set autoCompactWindow to 320000 in the agent's settings file",
    brings: ["Saving", "About $11-$22 a month", " at list price. 94 turns in 4 sessions went past 300k tokens of context. Each would have re-read 250k fewer cached tokens per compaction."],
    trade: "A session compacts at about 300k tokens instead of running on, so very long tasks meet a summary sooner and can lose detail the summary leaves out.",
    undo: "teyla undo O1 removes autoCompactWindow again; nothing else in the file is touched.", tag: "about $11-$22 a month" },
  { id: "O2", title: "Run subagents on Sonnet unless they say otherwise", change: "set a subagent model in the agent's settings file",
    brings: ["Saving", "About $14-$27 a month", " at list price. 62% of $46 of subagent spend ran on Opus by default."],
    trade: "Subagents that name no model run on Sonnet instead of your session's model. A task that needs Opus must ask for it with the Agent call's model parameter.",
    undo: "teyla undo O2 removes the setting again; the other keys stay.", tag: "about $14-$27 a month" },
];

function offerCard(o, state = {}) {
  const brings = o.brings;
  return V({ name: `Offer ${o.id}`, w: "fill", pad: 16, gap: 12, r: 10, fill: "surface", stroke: "border" },
    H({ w: "fill", gap: 12, align: "baseline" }, mono(o.id, "text-secondary", { size: 11, weight: 500 }), T(o.title, "web-head", "text", { weight: 500, w: "fill" }),
      state.applied ? { t: "use", c: "webTag", p: { text: "Applied 2 min ago", tone: "saving" } } : { t: "use", c: "webTag", p: { text: o.tag, tone: "saving" } }),
    V({ w: "fill", gap: 4 },
      H({ w: "fill", gap: 12, align: "start" }, V({ w: 84 }, body("Change", "text-secondary", { w: "hug" })), body(o.change)),
      H({ w: "fill", gap: 12, align: "start" }, V({ w: 84 }, body(brings[0], "text-secondary", { w: "hug" })), body(brings[1] + brings[2])),
      H({ w: "fill", gap: 12, align: "start" }, V({ w: 84 }, body("Trade-off", "text-secondary", { w: "hug" })), body(o.trade)),
      H({ w: "fill", gap: 12, align: "start" }, V({ w: 84 }, body("Undo", "text-secondary", { w: "hug" })), body(o.undo))),
    H({ gap: 4, align: "center" }, I("chevron.right", 10, "text-secondary"), body("Explain", "text-secondary", { w: "hug" })),
    state.confirming
      ? V({ name: "Confirm", w: "fill", pad: 12, gap: 8, r: 6, stroke: "needs-you" },
        body("Make this change?", "text", { weight: 600 }),
        body("This edits the agent's settings file and keeps a backup. teyla undo " + o.id + " puts it back."),
        H({ gap: 8 }, webBtn({ text: "Make this change", kind: "primary", link: "web.start-applied" }), webBtn({ text: "Cancel", link: "web.start" })))
      : H({ gap: 8, align: "center" }, state.applied ? webBtn({ text: "Undo" }) : webBtn({ text: "Apply", kind: "primary", link: state.link })),
    state.applied ? webStrip({ tone: "ok", text: "Set autoCompactWindow to 320000. Backup kept; teyla undo O1 puts it back." }) : null);
}

/** The Start tab. p: { state: loaded | confirm | applied | reading | refreshing | error | empty } */
export function webStart(p = {}) {
  const s = p.state || "loaded";
  const intro = [h1("Start"), sub("Teyla reads your Claude Code and Codex sessions on this Mac, shows what they cost, and fixes the waste. Nothing leaves your machine.")];
  let kids;
  if (s === "reading") kids = [...intro, webStrip({ text: "Reading your sessions... The first count takes up to a minute on a large machine. Nothing leaves this Mac." })];
  else if (s === "error") kids = [...intro, webStrip({ tone: "error", text: "Could not read the sessions folder. Check that this Mac has not moved it.", kids: [SPACER, webBtn({ text: "Try again", link: "web.start" })] })];
  else if (s === "empty") kids = [h1("Start"), V({ w: "fill", pad: [0, 0, 12, 0] }, { t: "use", c: "webEmpty", p: { title: "No sessions yet", text: "Use Claude Code or Codex for a day, then refresh. Teyla looks in ~/.claude and ~/.codex." } }), counted("Counted just now.")];
  else {
    const stats = H({ w: "fill", gap: 12, pad: [16, 0] },
      { t: "use", c: "webStat", p: { num: "71%", label: "of spend was re-reading or storing context ($293)" } },
      { t: "use", c: "webStat", p: { num: "5", label: "sessions ran past 250k tokens ($118)" } },
      { t: "use", c: "webStat", p: { num: "$46", label: "went to subagents; Opus ran 62% of it" } },
      { t: "use", c: "webStat", p: { num: "3", label: "questions are waiting on you", tone: "needs-you" } });
    const strip = s === "refreshing" ? webStrip({ text: "Refreshing... Showing the count from 4 min ago." }) : counted("Counted 4 min ago.");
    const applied = s === "applied";
    kids = [h1("$412 in the last 30 days"), sub("At API list price, over 38 sessions on 17 days (claude-code $331, codex $81). List price is what these tokens would cost through the API; a subscription bills differently."),
      stats, strip,
      h2(applied ? "1 change to consider" : "2 changes to consider"),
      V({ w: "fill", gap: 12 }, applied ? [] : offerCard(OFFERS[0], { confirming: s === "confirm", link: "web.start-confirm" }), offerCard(OFFERS[1], { link: "web.start-confirm" })),
      ...(applied ? [h2("Applied"), offerCard(OFFERS[0], { applied: true })] : []),
      V({ w: "fill", pad: [16, 0, 0, 0] }, H({ gap: 4, align: "center" }, I("chevron.right", 10, "text-secondary"), body("Already in place or not available (3)", "text-secondary", { w: "hug" }))),
      V({ w: "fill", pad: [12, 0, 0, 0] }, cap("Every change keeps a backup, and teyla changes lists them. Apply and Undo here call the same code as teyla apply and teyla undo."))];
  }
  return webPage({ active: "start", kids });
}

// ---- Spend --------------------------------------------------------------------------------------------------------

const LAST = [38, 52, 41, 47, 28, 15, 10], THIS = [35, 41, 22, 38, 29, 12, 7];
const LETTERS = ["S", "S", "M", "T", "W", "T", "F", "S", "S", "M", "T", "W", "T", "F"];

function dayChart() {
  const W = 878, k = W / 640, Hh = 150 * k, base = 120 * k, bw = 34 * k;
  const days = [...LAST, ...THIS], max = Math.max(...days), gap = (W - 20 * k - 14 * bw) / 13;
  const kids = [];
  days.forEach((d, i) => {
    const x = 10 * k + i * (bw + gap), hgt = Math.max(1, (d / max) * (base - 14 * k));
    kids.push(V({ abs: { top: base - hgt, left: x }, w: bw, h: hgt, r: 2, fill: i < 7 ? "text-secondary@0.55" : "primary" }));
    kids.push(V({ abs: { top: base - hgt - 18, left: x }, w: bw, align: "center" }, cap("$" + d, "text-secondary", { w: bw, align: "center" })));
    kids.push(V({ abs: { top: base + 6, left: x }, w: bw, align: "center" }, cap(LETTERS[i], "text-secondary", { w: bw, align: "center" })));
  });
  return webCard({ kids: [Z({ name: "By day", w: W, h: Math.round(Hh), fill: null }, ...kids),
    H({ gap: 16 }, H({ gap: 4, align: "center" }, V({ w: 10, h: 10, r: 2, fill: "text-secondary@0.55" }), cap("last week")), H({ gap: 4, align: "center" }, V({ w: 10, h: 10, r: 2, fill: "primary" }), cap("this week")))] });
}

function barsCard(label, rows) {
  const max = Math.max(...rows.flatMap((r) => [r[1], r[2]]));
  const head = H({ w: "fill", gap: 8, pad: [4, 0] }, V({ w: "fill" }, cap(label)), V({ w: 80, align: "end" }, cap("This week")), V({ w: 80, align: "end" }, cap("Last week")), V({ w: 300, h: 1 }));
  const line = (r) => V({ w: "fill", gap: 0 }, rule(), H({ w: "fill", gap: 8, pad: [8, 0], align: "center" },
    V({ w: "fill" }, body(r[0])), V({ w: 80, align: "end" }, body("$" + r[1], "text", { w: "hug" })), V({ w: 80, align: "end" }, body("$" + r[2], "text", { w: "hug" })),
    Z({ w: 300, h: 12 }, V({ abs: { top: 0, left: 0 }, w: 300, h: 12, fill: "text@0.08" }), V({ abs: { top: 0, left: 0 }, w: Math.round(300 * r[1] / max), h: 5, fill: "primary" }),
      V({ abs: { top: 7, left: 0 }, w: Math.round(300 * r[2] / max), h: 5, fill: "text-secondary@0.55" }))));
  return webCard({ gap: 4, kids: [cap("Bars: this week above, last week below."), head, ...rows.map(line)] });
}

/** The Spend tab. p: { state: loaded | refreshing | counting | empty | error } */
export function webSpend(p = {}) {
  const s = p.state || "loaded";
  const head = [h1("Spend"), sub("This week against last, at API list price, every harness. A subscription bills differently.")];
  let kids;
  if (s === "counting") kids = [...head, webStrip({ text: "Counting two weeks of sessions... The first count takes up to a minute." })];
  else if (s === "error") kids = [...head, webStrip({ tone: "error", text: "Could not count the sessions. Nothing was changed.", kids: [SPACER, webBtn({ text: "Try again", link: "web.spend" })] })];
  else if (s === "empty") kids = [...head, V({ w: "fill", pad: [0, 0, 12, 0] }, { t: "use", c: "webEmpty", p: { title: "No sessions yet", text: "Use Claude Code or Codex for a day. Their cost shows up here." } }), counted("Counted just now.")];
  else {
    kids = [...head,
      H({ w: "fill", gap: 12, pad: [16, 0] },
        { t: "use", c: "webStat", p: { num: "$184", label: "last 7 days" } }, { t: "use", c: "webStat", p: { num: "$231", label: "the 7 days before" } }, { t: "use", c: "webStat", p: { num: "-20%", label: "change" } }),
      s === "refreshing" ? webStrip({ text: "Refreshing... Showing the count from 4 min ago." }) : counted("Counted 4 min ago."),
      h2("By day"), dayChart(),
      h2("By model"), barsCard("Model", [["Opus 5.5", 96, 140], ["Sonnet 5.5", 62, 58], ["Haiku 5.5", 14, 12], ["GPT-6.1 Sol", 12, 21]]),
      h2("By product"), barsCard("Product", [["Atlas", 88, 102], ["Pebble", 52, 71], ["Quill", 31, 29], ["Fern", 13, 29]])];
  }
  return webPage({ active: "spend", kids });
}

// ---- teyla.dev ----------------------------------------------------------------------------------------------------

/** The home page. p: { w = 1440, dark, h } */
export function siteHome(p = {}) {
  const W = p.w || 1440, narrow = W < 704, wrap = Math.min(W - 32, 1088), dark = !!p.dark;
  const title = Math.max(32, Math.min(56, Math.round(W * 0.064)));
  const t = (v, size, c = "text", extra = {}) => T(v, "body", c, { size, w: "fill", ...extra });
  const bold = { weight: 700 };
  const section = (...kids) => V({ name: "Section", w: "fill", gap: 0 }, rule(), V({ w: "fill", align: "center", pad: [48, 0] }, V({ w: wrap, gap: 8 }, ...kids)));
  const box = (v, link) => H({ name: "Command", w: "fill", pad: [12, 12, 12, 16], gap: 12, r: 10, fill: "surface", stroke: "border", align: "center" },
    T(v, "term", "text", { size: 16, w: "fill" }), narrow ? null : H({ h: 44, pad: [0, 16], r: 10, stroke: link ? "border" : null, fill: link ? null : "primary", align: "center", justify: "center" },
      T(link ? "Copy" : "Copy line", "body", link ? "primary" : "on-primary", { size: 16, weight: link ? 500 : 700 })));
  const fact = (a, b) => V({ w: "fill", gap: 0 }, rule(), V({ w: "fill", pad: [12, 0] }, H({ w: "fill", wrap: true }, T(a, "body", "text", { size: 16, weight: 700 }), b ? T(" " + b, "body", "text-secondary", { size: 16 }) : null)));
  const plain = (v) => V({ w: "fill", gap: 0 }, rule(), V({ w: "fill", pad: [12, 0] }, t(v, 16)));
  const pack = (head, tone, text, cmd) => V({ w: narrow ? "fill" : (wrap - 32) / 2, gap: 4 }, t(head, 16, tone, bold), t(text, 16, "text-secondary"), T(cmd, "term", "text", { size: 16 }));
  const grid = V({ w: "fill", gap: 32, pad: [24, 0, 0, 0] },
    narrow
      ? [pack("Spend you cannot see", "saving", "Long sessions re-read their whole context every turn. Teyla finds them, compacts earlier and runs subagents on cheaper models.", "teyla apply O1"),
        pack("Questions nobody reads", "needs-you", "A session ends on a question and the work stops. Every open question sits on one screen, oldest first, with a link back to the session.", "teyla asks"),
        pack("Agents that forget", "text", "A correction made in Claude Code is unknown to Codex. One POLICY.md is linked into Claude Code, Codex, Grok, Cursor and Hermes.", "teyla policy sync"),
        pack("A Mac that falls over", "text", "Parallel agents swap the Mac until it hangs or panics. Teyla admits one heavy build or simulator at a time and holds new ones under memory pressure.", "teyla load")]
      : [H({ w: "fill", gap: 32 }, pack("Spend you cannot see", "saving", "Long sessions re-read their whole context every turn. Teyla finds them, compacts earlier and runs subagents on cheaper models.", "teyla apply O1"),
          pack("Questions nobody reads", "needs-you", "A session ends on a question and the work stops. Every open question sits on one screen, oldest first, with a link back to the session.", "teyla asks")),
        H({ w: "fill", gap: 32 }, pack("Agents that forget", "text", "A correction made in Claude Code is unknown to Codex. One POLICY.md is linked into Claude Code, Codex, Grok, Cursor and Hermes.", "teyla policy sync"),
          pack("A Mac that falls over", "text", "Parallel agents swap the Mac until it hangs or panics. Teyla admits one heavy build or simulator at a time and holds new ones under memory pressure.", "teyla load"))]);
  const shotW = wrap, shotH = Math.round(wrap * 860 / 1280);
  const header = V({ w: "fill", align: "center" }, H({ w: wrap, h: 68, align: "center" },
    lockup(32), SPACER, T("GitHub", "body", "text-secondary", { size: 16 })));
  const hero = V({ w: "fill", align: "center", pad: [48, 0] }, V({ w: wrap, gap: 16 },
    H({ w: "fill", gap: 6, align: "end", wrap: true }, T("The control room for your AI agents", "body", "text", { size: title, weight: 700, w: narrow ? "fill" : "hug" }),
      V({ w: Math.round(title * 0.42), h: Math.round(title * 0.72), r: 4, fill: "mark-accent" })),
    t("Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting on you, and fixes the waste.", 22, "text-secondary", { w: narrow ? "fill" : 640 }),
    V({ w: narrow ? "fill" : 640, gap: 8, pad: [16, 0, 0, 0] }, t("Paste this into Claude Code or Codex", 16, "text", { weight: 500 }), box("Set up https://github.com/<owner>/teyla"),
      t("Your agent installs Teyla, shows the diagnosis and asks before each change. Install by hand", 16, "text-secondary"))));
  const first = section(t("The first run shows what 30 days cost", 22, "text", bold),
    t("Teyla prices the sessions already on your disk, then lists the changes that save money, each with its saving, trade-off and undo.", 16, "text-secondary", { w: narrow ? "fill" : 640 }),
    V({ w: "fill", pad: [16, 0, 0, 0] }, V({ w: shotW, h: shotH, r: 10, stroke: "border", clip: true }, { t: "img", src: "docs/img/web-start.png", w: shotW, h: shotH, fit: "cover" })),
    t("Sample data. List price is what the tokens would cost through the API; a subscription bills differently.", 16, "text-secondary"));
  const four = section(t("Four problems it takes off your hands", 22, "text", bold), grid,
    V({ w: "fill", pad: [24, 0, 0, 0] }, T("See all 10 packs", "body", "primary", { size: 16, weight: 500 })));
  const privacy = section(t("Nothing about your sessions leaves your Mac unless you turn it on", 22, "text", bold),
    V({ w: narrow ? "fill" : 640, gap: 0 }, plain("No server, no account, no telemetry. Every network call is listed."), plain("Each change asks first and names the file, the saving and the way back. teyla undo O1 puts back the setting."),
      plain("Open source under Apache-2.0. This site sets no cookies and loads nothing from another host.")));
  const where = section(t("Where it runs", 22, "text", bold),
    V({ w: narrow ? "fill" : 640 }, fact("Command line and teyla web.", "Available now. The web page runs on 127.0.0.1, on your Mac."),
      fact("Mac app.", "Build it from source today, with macOS 15 and Xcode. See how."),
      fact("iPhone app and Mac App Store.", "Not on sale yet. The iPhone app reads a signed folder in your own iCloud Drive; there is no Teyla server.")));
  const install = section(t("Install by hand", 22, "text", bold),
    t("You need a Mac and uv. The first command installs Teyla. The second shows the diagnosis, the checklist of packs, then each change: yes, no or explain.", 16, "text-secondary", { w: narrow ? "fill" : 640 }),
    V({ w: narrow ? "fill" : 640, gap: 12, pad: [8, 0, 0, 0] }, box("uv tool install --python 3.12 git+https://github.com/<owner>/teyla", true), box("teyla start", true)),
    t("To look without installing, run this. It changes no setting of your tools and keeps its counts in ~/.teyla.", 16, "text-secondary", { w: narrow ? "fill" : 640 }),
    V({ w: narrow ? "fill" : 640, pad: [4, 0, 0, 0] }, box("uvx --python 3.12 --from git+https://github.com/<owner>/teyla teyla start", true)));
  const footer = V({ w: "fill", gap: 0 }, rule(), V({ w: "fill", align: "center", pad: [32, 0] }, H({ w: wrap, gap: 24, wrap: true },
    ["GitHub", "Guide", "Privacy", "Support", "Apache-2.0"].map((x) => T(x, "body", "text-secondary", { size: 16 })))));
  return V({ name: "teyla.dev", w: W, fill: "background" }, header, hero, first, four, privacy, where, install, footer);
}

// ---- README -------------------------------------------------------------------------------------------------------

/** The README as a repository page shows it, 1440 wide: the lockup, the tagline, the two paragraphs, the hero image. */
export function readmeHero() {
  const col = 880, p = (v, extra = {}) => T(v, "body", "text", { size: 16, w: "fill", ...extra });
  return V({ name: "README", w: "fill", fill: "surface", align: "center", pad: [40, 0, 60, 0] }, V({ w: col, gap: 16, align: "center" },
    lockup(53),
    p("The control room for working with AI agents on one Mac.", { align: "center", weight: 700 }),
    p("What your agent sessions cost, what waits on you, and where each product stands.", { align: "center" }),
    p("Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting on you, and fixes the waste. Nothing about your sessions leaves your Mac unless you turn it on."),
    p("It is a command-line tool with a Mac and an iPhone app, for a person who builds products with AI agents. It also reads Grok, Cursor and Hermes sessions, keeps every question an agent left for you on one screen, and keeps one line per product on where it stands."),
    V({ w: 820, h: 695, r: 6, stroke: "border", clip: true }, { t: "img", src: "docs/img/mac/today-light.png", w: 820, h: 695, fit: "cover" }),
    p("teyla.dev · Set up · Packs · Guide · Commands · Privacy · Changelog · Contributing · Apache-2.0", { align: "center", c: "primary" })));
}
