/** The scrub rules: what a report may not carry out of the page. The Swift, Kotlin and Python implementations
 *  (`ReviewScrub.swift`, `Scrub.kt`, `packages/review-channel/server.py`) run the same rules and the same test
 *  vectors (`packages/review-channel/test-vectors/scrub.json`). Placeholders are never matched by a rule, so
 *  scrubbing twice gives the same text. */

export const LABEL_CAP = 200;

const URL_PARAM = /([?&;][A-Za-z0-9_.\-]*(?:token|key|secret|password|passwd|pwd|auth|code|sig)[A-Za-z0-9_.\-]*=)[^&#\s]+/gi;
const JWT = /(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]*/g;
const BEARER = /(?<![A-Za-z0-9])Bearer[ \t]+[A-Za-z0-9._~+/=\-]{12,}/gi;
const API_KEY =
  /(?<![A-Za-z0-9_\-])(?:(?:sk|pk|rk)[_\-][A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_\-]{30,})/g;
const EMAIL = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+/g;
const IBAN = /(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])/g;
const CARD = /(?<![0-9])[0-9](?:[ \-]?[0-9]){12,18}(?![0-9])/g;
const PHONE = /(?<![A-Za-z0-9+])(?![0-9]{4}-[0-9]{2}-[0-9]{2})\+?[0-9(][0-9 .()\-]{6,}[0-9](?![A-Za-z0-9])/g;

function digitsOf(text: string): string {
  return text.replace(/[^0-9]/g, "");
}

function luhn(digits: string): boolean {
  let total = 0;
  for (let i = 0; i < digits.length; i++) {
    let n = digits.charCodeAt(digits.length - 1 - i) - 48;
    if (i % 2 === 1) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    total += n;
  }
  return total % 10 === 0;
}

/** E-mail addresses, phone numbers, card numbers, IBANs, bearer tokens, API keys, JWTs and the values of
 *  secret URL parameters, each replaced by a placeholder. */
export function scrub(text: string): string {
  let out = text.replace(URL_PARAM, (_m, head: string) => `${head}[token]`);
  out = out.replace(JWT, "[token]");
  out = out.replace(BEARER, "Bearer [token]");
  out = out.replace(API_KEY, "[token]");
  out = out.replace(EMAIL, "[email]");
  out = out.replace(IBAN, "[iban]");
  out = out.replace(CARD, (m) => {
    const d = digitsOf(m);
    return d.length >= 13 && d.length <= 19 && luhn(d) ? "[card]" : m;
  });
  return out.replace(PHONE, (m) => {
    const n = digitsOf(m).length;
    const low = m.startsWith("+") ? 8 : 9;
    return n >= low && n <= 15 ? "[phone]" : m;
  });
}

/** An accessibility label: scrubbed first, then at most 200 characters. */
export function scrubLabel(text: string): string {
  return scrub(text).slice(0, LABEL_CAP);
}
