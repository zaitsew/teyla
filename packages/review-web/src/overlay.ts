/** The review overlay. Loaded only by a dynamic import behind the build flag, so a build without the
 *  flag has no copy of this file, of the form, of `modern-screenshot` or of the channel key. */
import { collectAnchors, privateFrames } from "./anchors.ts";
import { parseChannel, sendCapture, type ChannelConfig, type FetchLike } from "./channel.ts";
import { envChannel } from "./env.ts";
import { probeEnvironment } from "./environment.ts";
import { encodeCapture, isSlug, newId } from "./format.ts";
import { decide } from "./gate.ts";
import { accept, isNeeded } from "./notice.ts";
import { takePicture } from "./picture.ts";
import { IdbStore, ReviewQueue, type FlushReport, type QueueEntry, type QueueStore } from "./queue.ts";
import { recordFor, type Frozen } from "./session.ts";
import { sha256Hex } from "./sha256.ts";
import { stringsFor, type ReviewStrings } from "./strings.ts";
import { addStyle, createLauncher, openForm, showMessage } from "./ui.ts";

/** In the built page only while the overlay is: `teyla review store-check` looks for it in a web dist. */
export const MARKER = "TEYLA_REVIEW_WEB_ACTIVE";

export interface StartOptions {
  /** The product's slug (`^[a-z][a-z0-9-]{0,39}$`). The channel key is bound to it. */
  product: string;
  /** Hostnames the overlay may run on: `test.example.com`, `*.test.example.com`, `localhost`. */
  hosts: readonly string[];
  /** The build flag. `init` passes the build's `VITE_TEYLA_REVIEW`; on the plain-page route pass your own. */
  flag?: unknown;
  /** Channel address and key. Default: `VITE_TEYLA_REVIEW_URL` and `VITE_TEYLA_REVIEW_KEY`. */
  channel?: { url?: string; key?: string };
  name?: string;
  version?: string;
  build?: string;
  /** 7 to 40 lowercase hex characters. */
  commit?: string;
  language?: string;
  strings?: Partial<ReviewStrings>;
  requiresHealthConsent?: boolean;
  /** Dictation through the browser's Web Speech API, when it exists. Off by default: see the README. */
  speech?: boolean;
  /** Draw the small Review button. Default true; false leaves `present()` for a settings row. */
  button?: boolean;
  /** For tests. */
  window?: Window;
  fetch?: FetchLike;
  store?: QueueStore;
}

export interface ReviewHandle {
  present(): Promise<void>;
  setScreen(id: string | undefined): void;
  flush(): Promise<FlushReport>;
  destroy(): void;
}

export async function start(opts: StartOptions): Promise<ReviewHandle | null> {
  const win = opts.window ?? window;
  const doc = win.document;
  const decision = decide({ flag: opts.flag, hosts: opts.hosts, hostname: win.location?.hostname });
  if (!decision.on) return null;
  if (!isSlug(opts.product)) {
    console.warn("[teyla-review] product must be a slug such as \"my-app\"; review mode stays off.");
    return null;
  }

  const channel: ChannelConfig | null = parseChannel(opts.channel ?? envChannel());
  const queue = new ReviewQueue(opts.store ?? new IdbStore(), channel ? (e) => sendCapture(channel, e, opts.fetch) : null);
  const strings = stringsFor(opts.language ?? win.navigator.language, opts.strings);

  const host = doc.createElement("div");
  host.setAttribute("data-teyla-review", MARKER);
  host.setAttribute("data-review-ignore", "");
  host.style.cssText = "all:initial;position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;";
  const root = host.attachShadow({ mode: "open" });
  addStyle(root);
  doc.documentElement.append(host);

  let open = false;
  let currentScreen: string | undefined;

  async function present(): Promise<void> {
    if (open) return;
    open = true;
    let url: string | null = null;
    const done = () => { open = false; if (url) { URL.revokeObjectURL(url); url = null; } };
    try {
      const vw = win.innerWidth, vh = win.innerHeight;
      const anchors = collectAnchors(doc, vw, vh, privateFrames(doc, vw, vh));
      const picture = await takePicture(win, host);
      const bytes = new Uint8Array(await picture.blob.arrayBuffer());
      const frozen: Frozen = {
        id: newId(), hostname: win.location.hostname, product: opts.product, version: opts.version ?? "0", build: opts.build ?? "web",
        environment: probeEnvironment(win), anchors, frames: picture.frames, sha256: await sha256Hex(bytes),
        pixelWidth: picture.pixelWidth, pixelHeight: picture.pixelHeight, scale: picture.scale,
      };
      if (opts.name) frozen.name = opts.name;
      if (opts.commit) frozen.commit = opts.commit;
      if (currentScreen) frozen.currentScreen = currentScreen;
      url = URL.createObjectURL(picture.blob);
      openForm(root, {
        strings, pictureUrl: url, viewport: { width: vw, height: vh },
        speech: opts.speech === true, requiresHealthConsent: opts.requiresHealthConsent === true,
        sendsToServer: channel !== null,
        noticeNeeded: () => isNeeded(channel !== null),
        acceptNotice: () => accept(),
        onClose: done,
        onSend: async (draft) => {
          const rec = recordFor(frozen, draft);
          const entry: QueueEntry = { id: frozen.id, created: Date.now(), json: encodeCapture(rec), png: picture.blob, attempts: 0 };
          const outcome = await queue.send(entry);
          if (outcome === "delivered") void queue.flush();
          return outcome === "delivered" ? "sent" : outcome === "queued" ? "saved" : "unsaved";
        },
      });
    } catch {
      done();
      showMessage(root, strings, strings.pictureFailed, () => undefined);
    }
  }

  if (opts.button !== false) createLauncher(root, strings.button, () => void present());

  const flush = () => void queue.flush();
  const onVisible = () => { if (doc.visibilityState === "visible") flush(); };
  win.addEventListener("online", flush);
  doc.addEventListener("visibilitychange", onVisible);
  flush();

  return {
    present,
    setScreen: (id) => { currentScreen = id; },
    flush: () => queue.flush(),
    destroy: () => {
      win.removeEventListener("online", flush);
      doc.removeEventListener("visibilitychange", onVisible);
      host.remove();
    },
  };
}
