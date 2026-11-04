/** The channel address and key of a test build, from the build configuration (`.env.review`).
 *  This file is imported only by the lazily loaded overlay, so a build without the flag never reads
 *  these names and its output never holds their values. Outside Vite `import.meta.env` is missing:
 *  the product then passes `channel` to `init`. */
export function envChannel(): { url?: string; key?: string } {
  try {
    return { url: import.meta.env.VITE_TEYLA_REVIEW_URL, key: import.meta.env.VITE_TEYLA_REVIEW_KEY };
  } catch {
    return {};
  }
}
