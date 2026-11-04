/** The product-facing entry. This file is all a build without the flag keeps of the package: when
 *  `VITE_TEYLA_REVIEW` is not `1` the bundler drops the dynamic import below, and with it the form,
 *  the picture code and the channel key. See README.md. */
import type { ReviewHandle, StartOptions } from "./overlay.ts";

export type InitOptions = Omit<StartOptions, "flag" | "window" | "fetch" | "store">;
export type { ReviewHandle };

let handle: ReviewHandle | null = null;

/** Start review mode when the build flag is on and this page's hostname is in `hosts`. Otherwise it
 *  does nothing and returns null. Never throws. */
export async function init(options: InitOptions): Promise<ReviewHandle | null> {
  if (import.meta.env.VITE_TEYLA_REVIEW === "1") {
    try {
      const { start } = await import("./overlay.ts");
      handle = await start({ ...options, flag: "1" });
    } catch (e) {
      console.warn("[teyla-review] could not start", e);
      handle = null;
    }
  }
  return handle;
}

/** Open review mode from a settings row. Does nothing unless `init` started it. */
export function present(): Promise<void> {
  return handle ? handle.present() : Promise.resolve();
}

/** Tell the review which screen the page is on (the twin of `.reviewScreen`), when markup is not enough. */
export function setScreen(id: string | undefined): void {
  handle?.setScreen(id);
}
