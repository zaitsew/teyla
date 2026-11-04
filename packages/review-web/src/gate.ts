/** The three-part switch (docs/REVIEW.md, "Web"): a build flag, a hostname allow-list, and a lazy
 *  import. This file is the decision for the first two. Nothing here touches the page. */

export type GateReason = "flag-off" | "no-hosts" | "no-hostname" | "host-not-allowed";
export type GateDecision = { on: true } | { on: false; reason: GateReason };

/** `1`, `true`, the boolean true or the number 1 switch it on. Anything else is off. */
export function flagIsOn(value: unknown): boolean {
  if (value === true || value === 1) return true;
  if (typeof value !== "string") return false;
  const v = value.trim().toLowerCase();
  return v === "1" || v === "true";
}

const NAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$/;
const IPV6 = /^\[[0-9a-f:.]+\]$/;

function clean(host: string): string {
  return host.trim().toLowerCase().replace(/\.$/, "");
}

/** An exact hostname (`test.example.com`, `localhost`, `[::1]`) or a wildcard for subdomains
 *  (`*.test.example.com`, at least two labels after the star). A bare `*`, a scheme, a port or a
 *  path is not a pattern: it never matches. */
export function hostMatches(hostname: string, pattern: string): boolean {
  const host = clean(hostname);
  const p = clean(pattern);
  if (!host) return false;
  if (p.startsWith("*.")) {
    const base = p.slice(2);
    if (!NAME.test(base) || !base.includes(".")) return false;
    return host.endsWith("." + base) && NAME.test(host);
  }
  if (!(NAME.test(p) || IPV6.test(p))) return false;
  return host === p;
}

export function decide(input: { flag: unknown; hosts: readonly string[] | undefined; hostname: string | undefined }): GateDecision {
  if (!flagIsOn(input.flag)) return { on: false, reason: "flag-off" };
  if (!input.hosts || input.hosts.length === 0) return { on: false, reason: "no-hosts" };
  if (!input.hostname) return { on: false, reason: "no-hostname" };
  const host = input.hostname;
  return input.hosts.some((p) => typeof p === "string" && hostMatches(host, p))
    ? { on: true }
    : { on: false, reason: "host-not-allowed" };
}
