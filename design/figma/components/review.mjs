// The review capture form's own parts for the Figma generator, read from packages/review-ios (ReviewOverlay.swift,
// ReviewStrings.swift), packages/review-web (ui.ts, strings.ts) and packages/review-android (ReviewFlow.kt).
// The form is unbranded: it takes the host app's accent, so it is drawn in each platform's defaults (system blue,
// the web's literal hex, Material 3). Names carry the `review` prefix: a name may be defined once across the folder.
//   reviewPicture   the frozen picture of the host screen, with the mark and a black privacy box
//   reviewIos       iPhone: banner, picture, bottom panel          (UI/ReviewOverlay.swift)
//   reviewMac       Mac: window "Report a problem", 320 pt column (ReviewOverlay.swift:74, ReviewPlatform.swift)
//   reviewWeb       web: dimmed page and card; reviewWebNotice    (ui.ts, notice.ts)
//   reviewAndroid   Android: picture over panel                   (ReviewFlow.kt)
// One `state` for all four: { step: "point" | "comment" | "done", mark: "none" | "spot" | "area", text, listening,
// sending, failed, outcome: "sent" | "saved", notice }.
import { V, H, Z, T, I, SPACER } from "../dsl.mjs";
import { iosStatusBar } from "./core.mjs";

const shadow = (y, blur, a) => ({ x: 0, y, blur, color: `#000000@${a}` });
const BLUE = "#007AFF", RED = "#FF3B30";

const STR = {
  modeTitle: "Review mode", commentTitle: "What is wrong here?", wholeScreen: "About the whole screen", next: "Next", exit: "Exit",
  back: "Back", placeholder: "Write what is wrong", dictate: "Dictate", send: "Send", retry: "Retry", saving: "Saving", done: "Done",
  sentTitle: "Sent. Thank you!", sentDetail: "Your comment and the screenshot are on their way.",
  previewCaption: "This picture is what is sent. Black boxes hide private areas.",
  noticeTitle: "Before you send",
  noticeCaptured: "What is sent: a picture of this screen exactly as it looks now, your comment, the name and build of this app, the kind of device and system, and the element you pointed at. The picture shows everything on the screen, including other people's names or data when they are visible.",
  noticeRecipient: "Who gets it: the developer of this app, through a review server. Nobody else.",
  noticeWhy: "Why: to find and fix what you pointed at.",
  noticeRetention: "How long: the copy on the server is deleted when the developer's Mac next collects it, usually within the hour. The developer's Mac keeps its copy for 30 days after the report is closed, or 90 days if it is never opened.",
  noticeOK: "OK, send", noticeCancel: "Cancel",
};
const PLATFORM = {
  ios: { hint: "The app is paused. Tap a spot or circle an area.", spot: "Spot chosen. Tap elsewhere to change it.", area: "Area chosen. Draw again to change it.",
    failed: "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry.",
    listening: "Listening. Tap the microphone to stop.", saved: "Saved on this phone", savedDetail: "It has not been sent: this phone is not connected to the review inbox yet." },
  mac: { hint: "The window is frozen. Click a spot or drag around an area.", spot: "Spot chosen. Tap elsewhere to change it.", area: "Area chosen. Draw again to change it.",
    failed: "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry.",
    listening: "Listening. Tap the microphone to stop.", saved: "Saved on this Mac", savedDetail: "It has not been sent: this Mac is not connected to the review inbox yet." },
  web: { hint: "The page is paused. Click a spot or drag over an area.", spot: "Spot chosen. Click elsewhere to change it.", area: "Area chosen. Drag again to change it.",
    failed: "Could not save the capture in this browser. Your comment and the screenshot are still here. Free some space, then press Retry.",
    listening: "Listening. Press the microphone to stop.", saved: "Saved in this browser", savedDetail: "It has not been sent yet. It will be sent again when the review server can be reached." },
  android: { hint: "The screen is paused. Tap a spot or drag over an area.", spot: "Spot chosen. Tap elsewhere to change it.", area: "Area chosen. Drag again to change it.",
    failed: "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry.",
    listening: "", saved: "Saved on this device", savedDetail: "It has not been sent yet. It will be sent again when the review server can be reached." },
};
const COMMENT = "The Quill export button does nothing when I tap it twice.";

// ---- the picture --------------------------------------------------------------------------------------------

/**
 * The frozen picture: a made-up Atlas screen (title, three cards) with a black box over one private line and the
 * mark. p: { w, h, kind: "ios" | "mac" | "web" | "android" = "ios", mark: "none" | "spot" | "area" = "none", accent, markFill }
 */
export function reviewPicture(p = {}) {
  const w = p.w, h = p.h, kind = p.kind || "ios";
  const bg = kind === "ios" ? "ios-bg" : kind === "android" ? "#FFFBFE" : "background";
  const cardFill = kind === "ios" ? "ios-card" : kind === "android" ? "#F3EDF7" : "surface";
  const ink = kind === "android" ? "#1C1B1F" : "text";
  const bar = kind === "android" ? "#CAC4D0" : "border";
  const pad = Math.round(Math.min(w, h) * 0.07);
  const titleSize = Math.max(9, Math.round(Math.min(w, h) * 0.075));
  const top = pad + titleSize + pad * 0.6;
  const gap = Math.round(pad * 0.6);
  const ch = Math.round((h - top - pad - gap * 2) / 3);
  const cw = w - pad * 2;
  const card = (i) => {
    const y = top + i * (ch + gap);
    const bw = Math.round(ch * 0.12);
    return [
      V({ abs: { top: y, left: pad }, w: cw, h: ch, r: Math.min(12, Math.round(ch * 0.14)), fill: cardFill, stroke: kind === "ios" || kind === "android" ? null : "border" }),
      V({ abs: { top: y + ch * 0.22, left: pad + ch * 0.16 }, w: Math.round(cw * 0.42), h: bw * 1.4, r: 2, fill: bar }),
      V({ abs: { top: y + ch * 0.5, left: pad + ch * 0.16 }, w: Math.round(cw * 0.66), h: bw, r: 2, fill: bar + (bar.startsWith("#") ? "" : "@0.6") }),
    ];
  };
  const y3 = top + 2 * (ch + gap), y2 = top + (ch + gap);
  const accent = p.accent || BLUE;
  const mark = p.mark === "spot"
    ? V({ abs: { top: y2 + ch * 0.45, left: pad + cw * 0.58 }, w: 18, h: 18, r: 9, fill: accent, stroke: "#FFFFFF", sw: 2 })
    : p.mark === "area"
      ? V({ abs: { top: y2 - 4, left: pad - 4 }, w: cw + 8, h: ch + 8, r: 6, fill: `${accent}@${p.markFill ?? 0.15}`, stroke: accent, sw: 2.5 })
      : null;
  return Z({ name: "Picture", w, h, fill: bg, clip: true },
    V({ abs: { top: pad, left: pad } }, T("Atlas", "mac-body", ink, { size: titleSize, weight: 700 })),
    ...card(0), ...card(1), ...card(2),
    V({ abs: { top: y3 + ch * 0.2, left: pad + ch * 0.16 }, w: Math.round(cw * 0.5), h: Math.round(ch * 0.5), r: 2, fill: "#000000" }),
    mark);
}

// ---- iPhone and Mac -----------------------------------------------------------------------------------------

const iosButton = (text, kind, off, mac, link) => H({ name: `Button ${text}`, link, pad: mac ? [5, 12] : [9, 18], r: mac ? 6 : 20, align: "center", gap: 6, opacity: off ? 0.45 : undefined,
  fill: kind === "prominent" ? BLUE : "ios-fill" }, T(text, mac ? "mac-body" : "ios-text", kind === "prominent" ? "#FFFFFF" : "ios-label", kind === "prominent" ? { weight: 600 } : {}));

/** The bottom panel's content, the same on the iPhone and in the Mac's column. */
function applePanel(s, mac) {
  const k = s.links || {};
  const pl = PLATFORM[mac ? "mac" : "ios"], cap = mac ? "mac-caption" : "ios-caption", body = mac ? "mac-body" : "ios-body";
  const sel = s.mark === "area" ? pl.area : s.mark === "spot" ? pl.spot : null;
  if (s.step === "point") {
    return V({ w: "fill", gap: 10 },
      sel ? T(sel, cap, "ios-label-2", { w: "fill" }) : { t: "spacer", h: 16 },
      H({ w: "fill", align: "center" }, iosButton(STR.exit, "bordered", false, mac, k.exit), SPACER,
        iosButton(sel ? STR.next : STR.wholeScreen, "prominent", false, mac, k.next)));
  }
  if (s.step === "done") {
    const sent = s.outcome !== "saved";
    return V({ w: "fill", gap: 10 },
      H({ gap: 6, align: "center" }, I(sent ? "checkmark.circle.fill" : mac ? "laptopcomputer" : "iphone", 17, sent ? BLUE : "ios-label"),
        T(sent ? STR.sentTitle : pl.saved, body, "ios-label", { weight: 600 })),
      T(sent ? STR.sentDetail : pl.savedDetail, cap, "ios-label-2", { w: "fill" }),
      H({ w: "fill" }, SPACER, iosButton(STR.done, "prominent", false, mac, k.done)));
  }
  const field = H({ name: "Field", w: "fill", pad: [10, 12], r: 10, fill: "ios-fill", align: "start", minH: mac ? 66 : 40, opacity: s.sending ? 0.6 : undefined },
    s.text ? T(s.text, body, "ios-label", { w: "fill" }) : T(STR.placeholder, body, "ios-label-2", { w: "fill" }));
  const dictate = H({ name: "Dictate", w: 40, h: 40, r: 10, fill: s.listening ? `${RED}@0.2` : `${BLUE}@0.2`, align: "center", justify: "center" },
    I(s.listening ? "stop.fill" : "mic.fill", 16, s.listening ? RED : BLUE));
  return V({ w: "fill", gap: 10 },
    T(STR.commentTitle, body, "ios-label", { weight: 600 }),
    H({ w: "fill", gap: 8, align: "end" }, field, dictate),
    s.listening ? T(pl.listening, cap, "ios-label-2", { w: "fill" }) : null,
    T(STR.previewCaption, cap, "ios-label-2", { w: "fill" }),
    s.failed ? T(pl.failed, cap, RED, { w: "fill" }) : null,
    H({ w: "fill", align: "center", gap: 10 }, iosButton(STR.back, "bordered", s.sending, mac, k.back), SPACER,
      s.sending ? I("progress.indicator", 16, "ios-label-2") : null,
      iosButton(s.sending ? STR.saving : s.failed ? STR.retry : STR.send, "prominent", s.sending || !s.text, mac, k.send)));
}

function appleNotice(mac) {
  return V({ name: "Alert", w: 270, r: 14, fill: "ios-card", clip: true, shadow: shadow(8, 28, 0.25), abs: { center: "xy" } },
    V({ w: "fill", gap: 8, pad: 16 },
      T(STR.noticeTitle, "ios-card-title", "ios-label", { w: "fill", align: "center" }),
      T([STR.noticeCaptured, STR.noticeRecipient, STR.noticeWhy, STR.noticeRetention].join("\n\n"), "ios-caption", "ios-label", { w: "fill" })),
    H({ w: "fill", h: 44, align: "center", justify: "center", stroke: "ios-separator" }, T(STR.noticeOK, "ios-text", BLUE, { weight: 600 })),
    H({ w: "fill", h: 44, align: "center", justify: "center", stroke: "ios-separator" }, T(STR.noticeCancel, "ios-text", BLUE)));
}

/** The iPhone form. p: state, see the file header. */
export function reviewIos(p = {}) {
  const entered = p.step !== "point";
  const ph = p.step === "point" ? 600 : p.step === "done" ? 480 : p.failed ? 400 : 440;
  const pw = Math.round(ph * 402 / 874);
  const banner = H({ name: "Banner", w: "fill", pad: [8, 16], gap: 10, align: "baseline" },
    H({ pad: [4, 10], r: 20, fill: BLUE }, T(STR.modeTitle, "ios-body", "#FFFFFF", { weight: 600 })),
    p.step === "point" ? T(PLATFORM.ios.hint, "ios-caption", "ios-label-2", { w: "fill" }) : null);
  const pic = V({ name: "Stage", w: "fill", h: "fill", align: "center", justify: "center" },
    V({ r: entered ? 16 : 0, stroke: entered ? BLUE : null, sw: 3, clip: true },
      reviewPicture({ w: pw, h: ph, kind: "ios", mark: p.mark, accent: BLUE })));
  const z = Z({ name: "Review iOS", w: 402, h: 874, fill: "ios-bg" },
    V({ abs: { top: 0, left: 0 }, w: 402, h: 874 }, iosStatusBar(), banner, pic,
      V({ name: "Panel", w: "fill", pad: [12, 16, 34, 16], fill: "ios-bar" }, applePanel(p, false))),
    p.notice ? V({ abs: { top: 0, left: 0 }, w: 402, h: 874, fill: "#000000@0.4" }) : null,
    p.notice ? appleNotice(false) : null);
  return z;
}

/** The Mac window "Report a problem". p: state. */
export function reviewMac(p = {}) {
  const lights = H({ gap: 8, align: "center" }, ["#FF5F57", "#FEBC2E", "#28C840"].map((hex) => V({ w: 12, h: 12, r: 6, fill: hex, stroke: "#000000@0.12" })));
  const pic = V({ name: "Stage", w: "fill", h: "fill", align: "center", justify: "center", fill: "mac-sidebar" },
    V({ r: 8, stroke: p.step === "point" ? null : BLUE, sw: 3, clip: true }, reviewPicture({ w: 520, h: p.step === "point" ? 440 : 380, kind: "mac", mark: p.mark, accent: BLUE })));
  const col = V({ name: "Form column", w: 320, h: "fill", pad: 16, gap: 10, fill: "background", stroke: "mac-edge" },
    H({ pad: [4, 10], r: 20, fill: BLUE }, T(STR.modeTitle, "mac-body", "#FFFFFF", { weight: 600 })),
    p.step === "point" ? T(PLATFORM.mac.hint, "mac-caption", "text-secondary", { w: "fill" }) : null,
    applePanel(p, true));
  return Z({ name: "Review Mac", w: 1000, h: 660, fill: "mac-sidebar", r: 12, clip: true, stroke: "mac-edge", shadow: shadow(12, 40, 0.18) },
    V({ abs: { top: 0, left: 0 }, w: 1000, h: 660 },
      H({ name: "Title bar", w: "fill", h: 30, pad: [0, 12], align: "center", fill: "mac-sidebar" }, lights, SPACER, T("Report a problem", "mac-body", "text", { weight: 600 }), SPACER, V({ w: 52, h: 1 })),
      H({ w: "fill", h: "fill" }, pic, col)),
    p.notice ? V({ abs: { top: 0, left: 0 }, w: 1000, h: 660, fill: "#000000@0.4" }) : null,
    p.notice ? appleNotice(true) : null);
}

// ---- web ----------------------------------------------------------------------------------------------------

function webPalette(dark) {
  return dark
    ? { card: "#111827", text: "#F9FAFB", field: "#1F2937", border: "#4B5563", btn: "#1F2937", caption: "#9CA3AF", error: "#FCA5A5" }
    : { card: "#FFFFFF", text: "#111827", field: "#FFFFFF", border: "#9CA3AF", btn: "#F3F4F6", caption: "#4B5563", error: "#B91C1C" };
}
const webBtn = (c, text, kind, off, link) => H({ name: `Button ${text}`, link, h: 44, pad: [0, 16], r: 10, align: "center", justify: "center", opacity: off ? 0.45 : undefined,
  fill: kind === "primary" ? "#2563EB" : c.btn, stroke: kind === "primary" ? "#2563EB" : c.border },
  T(text, "web-body", kind === "primary" ? "#FFFFFF" : c.text));

/** The web launcher: a fixed pill at the bottom left of the host page. */
export function reviewLauncher() {
  return H({ name: "Launcher", h: 36, pad: [0, 14], r: 18, fill: "#1F2937", stroke: "#000000@0.25", align: "center", opacity: 0.85 }, T("Review", "web-small", "#FFFFFF"));
}

/** The first-send notice over the card. */
export function reviewWebNotice(p = {}) {
  const c = webPalette(p.dark);
  return V({ name: "Notice", w: 520, pad: 16, gap: 8, r: 14, fill: c.card, abs: { center: "xy" } },
    T(STR.noticeTitle, "web-head", c.text, { size: 17 }),
    T([STR.noticeCaptured, STR.noticeRecipient, STR.noticeWhy, STR.noticeRetention].join("\n\n"), "web-small", c.text, { w: "fill", size: 14 }),
    H({ gap: 8, pad: [8, 0, 0, 0] }, webBtn(c, STR.noticeOK, "primary"), webBtn(c, STR.noticeCancel, "plain")));
}

/** The web page behind the form, with the overlay card. p: state plus { dark, h = page height, launcher } */
export function reviewWeb(p = {}) {
  const c = webPalette(p.dark), pl = PLATFORM.web, h = p.h || 848, k = p.links || {};
  const sel = p.mark === "area" ? pl.area : p.mark === "spot" ? pl.spot : pl.hint;
  const pic = V({ name: "Picture", w: "fill", r: 6, stroke: "#4B5563", sw: 2, clip: true },
    reviewPicture({ w: 684, h: 330, kind: "web", mark: p.mark === "spot" ? "spot" : p.mark === "area" ? "area" : "none", accent: "#EF4444", markFill: 0.18 }));
  const rows = {
    point: H({ gap: 8, w: "fill" }, webBtn(c, STR.wholeScreen, "plain", false, k.next), webBtn(c, STR.next, "primary", p.mark === "none" || !p.mark, k.next), webBtn(c, STR.exit, "plain", false, k.exit)),
    comment: V({ w: "fill", gap: 8 },
      H({ w: "fill", gap: 8 }, webBtn(c, STR.back, "plain", p.sending, k.back), webBtn(c, p.sending ? STR.saving : p.failed ? STR.retry : STR.send, "primary", p.sending || !p.text, k.send), webBtn(c, STR.dictate, "plain", p.sending), webBtn(c, STR.exit, "plain", false, k.exit))),
    done: H({ gap: 8 }, webBtn(c, STR.done, "primary", false, k.done)),
  };
  const body = p.step === "done"
    ? V({ w: "fill", gap: 4 }, T(p.outcome === "saved" ? pl.saved : STR.sentTitle, "web-head", c.text, { size: 16 }),
        T(p.outcome === "saved" ? pl.savedDetail : STR.sentDetail, "web-body", c.text, { w: "fill", size: 14 }))
    : null;
  const comment = p.step === "comment" ? V({ w: "fill", gap: 8 },
    H({ w: "fill", h: 96, pad: 8, r: 8, fill: c.field, stroke: c.border, align: "start", opacity: p.sending ? 0.6 : undefined },
      p.text ? T(p.text, "web-body", c.text, { w: "fill" }) : T(STR.placeholder, "web-body", c.caption, { w: "fill" })),
    p.listening ? T(pl.listening, "web-small", c.caption, { w: "fill", size: 12 }) : null,
    T(STR.previewCaption, "web-small", c.caption, { w: "fill", size: 12 }),
    p.failed ? T(pl.failed, "web-body", c.error, { w: "fill", size: 14 }) : null) : null;
  const card = V({ name: "Card", w: 720, pad: 16, gap: 8, r: 14, fill: c.card, abs: { center: "xy" } },
    T(p.step === "comment" ? STR.commentTitle : STR.modeTitle, "web-head", c.text, { size: 17 }),
    p.step === "point" ? T(sel, "web-body", c.text, { w: "fill", size: 14 }) : null,
    pic, comment, body, rows[p.step || "point"]);
  const page = reviewPicture({ w: 1440, h, kind: "web", mark: "none" });
  return Z({ name: "Page", w: 1440, h, fill: "background" },
    V({ abs: { top: 0, left: 0 } }, page),
    p.launcher ? V({ abs: { bottom: 12, left: 12 } }, reviewLauncher()) : null,
    p.step ? V({ abs: { top: 0, left: 0 }, w: 1440, h, fill: "#000000@0.6" }) : null,
    p.step ? card : null,
    p.notice ? V({ abs: { top: 0, left: 0 }, w: 1440, h, fill: "#000000@0.6" }) : null,
    p.notice ? reviewWebNotice({ dark: p.dark }) : null);
}

// ---- Android ------------------------------------------------------------------------------------------------

const M3 = { surface: "#FFFBFE", on: "#1C1B1F", primary: "#6750A4", onPrimary: "#FFFFFF", outline: "#79747E", error: "#B3261E", variant: "#49454F", container: "#ECE6F0" };
const mBtn = (text, kind, off, link) => H({ name: `Button ${text}`, link, h: 40, pad: [0, 24], r: 20, align: "center", justify: "center", opacity: off ? 0.38 : undefined,
  fill: kind === "filled" ? M3.primary : null, stroke: kind === "outlined" ? M3.outline : null },
  T(text, "ios-text", kind === "filled" ? M3.onPrimary : M3.primary, { weight: 500, size: 14 }));

/** The Android form. p: state. The status bar and the picture sit above the panel (ReviewFlow.kt, portrait). */
export function reviewAndroid(p = {}) {
  const pl = PLATFORM.android, k = p.links || {};
  const point = p.step === "point";
  const ph = point ? 440 : p.step === "done" ? 330 : 300, pw = Math.round(ph * 412 / 892);
  const status = H({ name: "Status bar", w: "fill", h: 32, pad: [0, 20], align: "center" },
    T("9:41", "ios-caption", M3.on, { weight: 500, size: 13 }), SPACER, I("wifi", 13, M3.on), I("battery.100", 16, M3.on));
  const pic = V({ name: "Stage", w: "fill", pad: 16, align: "center", justify: "center" },
    V({ clip: true }, reviewPicture({ w: pw, h: ph, kind: "android", mark: p.mark, accent: M3.primary })));
  const title = (v) => T(v, "ios-section", M3.on, { size: 22, weight: 400 });
  const sel = p.mark === "area" ? pl.area : p.mark === "spot" ? pl.spot : null;
  let panel;
  if (point) {
    panel = V({ w: "fill", gap: 12, pad: 16 }, title(STR.modeTitle), T(pl.hint, "ios-body", M3.on, { w: "fill", size: 14 }),
      sel ? T(sel, "ios-body", M3.primary, { w: "fill", size: 14 }) : null,
      H({ gap: 8 }, mBtn(STR.exit, "outlined", false, k.exit), mBtn(STR.next, "filled", p.mark === "none" || !p.mark, k.next)),
      H({ h: 40, pad: [0, 12], align: "center" }, T(STR.wholeScreen, "ios-text", M3.primary, { weight: 500, size: 14 })));
  } else if (p.step === "done") {
    const sent = p.outcome !== "saved";
    panel = V({ w: "fill", gap: 12, pad: 16 }, title(sent ? STR.sentTitle : pl.saved), T(sent ? STR.sentDetail : pl.savedDetail, "ios-body", M3.on, { w: "fill", size: 14 }),
      H({ gap: 8 }, mBtn(STR.done, "filled", false, k.done)));
  } else {
    panel = V({ w: "fill", gap: 12, pad: 16 }, title(STR.commentTitle),
      H({ w: "fill", minH: 96, pad: 16, r: 4, stroke: M3.outline, align: "start", opacity: p.sending ? 0.6 : undefined },
        p.text ? T(p.text, "ios-text", M3.on, { w: "fill", size: 16 }) : T(STR.placeholder, "ios-text", M3.variant, { w: "fill", size: 16 })),
      T(STR.previewCaption, "ios-caption", M3.variant, { w: "fill", size: 12 }),
      p.failed ? T(pl.failed, "ios-body", M3.error, { w: "fill", size: 14 }) : null,
      H({ gap: 8 }, mBtn(STR.back, "outlined", p.sending, k.back), mBtn(p.sending ? STR.saving : p.failed ? STR.retry : STR.send, "filled", p.sending || !p.text, k.send)));
  }
  const notice = p.notice ? V({ name: "Dialog", w: 320, pad: 24, gap: 16, r: 28, fill: M3.container, abs: { center: "xy" } },
    T(STR.noticeTitle, "ios-section", M3.on, { size: 24, weight: 400 }),
    T([STR.noticeCaptured, STR.noticeRecipient, STR.noticeWhy, STR.noticeRetention].join("\n\n"), "ios-body", M3.variant, { w: "fill", size: 13 }),
    H({ w: "fill", gap: 8 }, SPACER, T(STR.noticeCancel, "ios-text", M3.primary, { weight: 500, size: 14 }), T(STR.noticeOK, "ios-text", M3.primary, { weight: 500, size: 14 }))) : null;
  return Z({ name: "Review Android", w: 412, h: 892, fill: M3.surface },
    V({ abs: { top: 0, left: 0 }, w: 412, h: 892 }, status, pic, panel),
    p.notice ? V({ abs: { top: 0, left: 0 }, w: 412, h: 892, fill: "#000000@0.32" }) : null, notice);
}
