// Short constructors for composite authors (components/*.mjs, cover.mjs), the same as the generator's render/dsl.mjs.
export const V = (p = {}, ...kids) => ({ t: "v", ...p, kids: kids.flat().filter(Boolean) });
export const H = (p = {}, ...kids) => ({ t: "h", ...p, kids: kids.flat().filter(Boolean) });
export const Z = (p = {}, ...kids) => ({ t: "z", ...p, kids: kids.flat().filter(Boolean) });
export const T = (v, s = "body", c = "tx", p = {}) => ({ t: "text", v, s, c, ...p });
export const I = (n, size = 17, c = "tx", p = {}) => ({ t: "icon", n, size, c, ...p });
export const U = (c, p = {}, extra = {}) => ({ t: "use", c, p, ...extra });
export const SPACER = { t: "spacer" };
