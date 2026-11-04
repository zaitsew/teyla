/** The first-send notice and the checks that sit before Send. */
export const NOTICE_KEY = "teyla.review.noticeAccepted";

export interface KV { getItem(k: string): string | null; setItem(k: string, v: string): void }

function store(kv?: KV): KV | null {
  if (kv) return kv;
  try { return (globalThis as { localStorage?: Storage }).localStorage ?? null; } catch { return null; }
}

/** True once the tester pressed OK on the notice, in this browser. */
export function isAccepted(kv?: KV): boolean {
  try { return store(kv)?.getItem(NOTICE_KEY) === "1"; } catch { return false; }
}

export function accept(kv?: KV): void {
  try { store(kv)?.setItem(NOTICE_KEY, "1"); } catch { /* the notice shows again next time */ }
}

/** The notice appears before a send that can leave the browser, until the tester has accepted it once. */
export function isNeeded(sendsToServer: boolean, kv?: KV): boolean {
  return sendsToServer && !isAccepted(kv);
}

/** Whether Send is enabled: a comment, no save under way, and the health box ticked when the product requires it. */
export function canSend(comment: string, sending: boolean, requiresHealthConsent: boolean, healthConsentGiven: boolean): boolean {
  return !sending && comment.trim() !== "" && (!requiresHealthConsent || healthConsentGiven);
}
