/** The browser and system, in the shape `environment` has on iOS. Nothing here names the person. */
import type { CaptureRecord } from "./format.ts";

const cut = (s: string) => s.slice(0, 64) || "unknown";

export function parseBrowser(ua: string): string {
  const pick = (re: RegExp, name: string) => { const m = re.exec(ua); return m ? `${name} ${m[1]}` : null; };
  return (
    pick(/Edg\/(\d+)/, "Edge") ?? pick(/OPR\/(\d+)/, "Opera") ?? pick(/Firefox\/(\d+)/, "Firefox") ??
    pick(/(?:Chrome|CriOS)\/(\d+)/, "Chrome") ?? pick(/Version\/(\d+)[^ ]* .*Safari/, "Safari") ?? "Browser"
  );
}

export function parseOS(ua: string): string {
  let m: RegExpExecArray | null;
  if ((m = /(?:iPhone|CPU) OS (\d+)[_.](\d+)/.exec(ua))) return `iOS ${m[1]}.${m[2]}`;
  if ((m = /Android (\d+(?:\.\d+)?)/.exec(ua))) return `Android ${m[1]}`;
  if ((m = /Mac OS X (\d+)[_.](\d+)/.exec(ua))) return `macOS ${m[1]}.${m[2]}`;
  if (/Mac OS X/.test(ua)) return "macOS";
  if ((m = /Windows NT (\d+(?:\.\d+)?)/.exec(ua))) return `Windows NT ${m[1]}`;
  if (/CrOS/.test(ua)) return "ChromeOS";
  if (/Linux/.test(ua)) return "Linux";
  return "unknown";
}

export function probeEnvironment(win: Window): CaptureRecord["environment"] {
  const nav = win.navigator;
  const locale = nav.language || "en";
  const dark = typeof win.matchMedia === "function" && win.matchMedia("(prefers-color-scheme: dark)").matches;
  const language = locale.split(/[-_]/)[0];
  const env: CaptureRecord["environment"] = {
    os: cut(parseOS(nav.userAgent || "")),
    model: cut(parseBrowser(nav.userAgent || "")),
    locale: cut(locale),
    ...(language && language.length >= 2 ? { language: language.slice(0, 16) } : {}),
    appearance: dark ? "dark" : "light",
    dynamic_type: "unspecified",
    screen: { width: win.innerWidth, height: win.innerHeight, scale: Math.max(1, Math.round((win.devicePixelRatio || 1) * 100) / 100) },
  };
  return env;
}
