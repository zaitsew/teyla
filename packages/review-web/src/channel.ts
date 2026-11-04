/** The built-in client for the shared review channel (packages/review-channel): PUT the picture, then
 *  the JSON, each with the write-only bearer key. The only network call the package makes. */
import { JSON_NAME, PNG_NAME } from "./format.ts";

export type ChannelResult = "delivered" | "retry" | "refused";

export interface ChannelConfig { baseUrl: string; key: string }

/** Statuses that will not change by asking again. 429, 503, 507, 5xx and a network error read as "later". */
export const PERMANENT = new Set([400, 401, 403, 413, 422]);

export function resultForStatus(status: number): ChannelResult {
  if (status === 200) return "delivered";
  return PERMANENT.has(status) ? "refused" : "retry";
}

function text(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t === "" || t.startsWith("$(") || t === "undefined" ? null : t;
}

/** Null unless both values are present and non-empty and the URL is HTTPS (plain HTTP only for a
 *  loopback host, for local development). */
export function parseChannel(input: { url?: unknown; key?: unknown } | null | undefined): ChannelConfig | null {
  const url = text(input?.url), key = text(input?.key);
  if (!url || !key) return null;
  let u: URL;
  try { u = new URL(url); } catch { return null; }
  const loopback = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(u.hostname);
  if (!(u.protocol === "https:" || (u.protocol === "http:" && loopback))) return null;
  return { baseUrl: u.origin + u.pathname.replace(/\/+$/, ""), key };
}

export const isUuid = (id: string): boolean => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id);

export type FetchLike = (url: string, init: RequestInit) => Promise<Pick<Response, "status">>;

export async function putOne(
  cfg: ChannelConfig, id: string, file: string, body: Blob | string, contentType: string,
  fetchImpl: FetchLike = (u, i) => fetch(u, i), timeoutMs = 30000,
): Promise<ChannelResult> {
  const ctl = typeof AbortController !== "undefined" ? new AbortController() : undefined;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : undefined;
  try {
    const res = await fetchImpl(`${cfg.baseUrl}/v1/captures/${id}/${file}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${cfg.key}`, "Content-Type": contentType },
      body,
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      mode: "cors",
      ...(ctl ? { signal: ctl.signal } : {}),
    });
    return resultForStatus(res.status);
  } catch {
    return "retry"; // no network, a timeout, a CORS refusal or a cancelled request: try again later
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** The picture first, then the JSON. Stops at the first answer that is not 200. */
export async function sendCapture(
  cfg: ChannelConfig, cap: { id: string; json: string; png: Blob }, fetchImpl?: FetchLike,
): Promise<ChannelResult> {
  if (!isUuid(cap.id)) return "refused";
  const png = await putOne(cfg, cap.id, PNG_NAME, cap.png, "image/png", fetchImpl);
  if (png !== "delivered") return png;
  return putOne(cfg, cap.id, JSON_NAME, cap.json, "application/json", fetchImpl);
}
