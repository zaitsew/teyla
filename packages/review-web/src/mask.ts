/** Masking inside the cloned page that `modern-screenshot` draws. The picture painter also paints
 *  every private rectangle black on the finished pixels (pixels.ts); this is the second layer, so
 *  the text of a private element never reaches the picture at all. */
import { isPrivateElement } from "./anchors.ts";

export function isPrivateNode(node: Node): boolean {
  if (node.nodeType !== 1) return false;
  return isPrivateElement(node as Element);
}

/** Make a cloned private element a black box with nothing readable in it. */
export function maskClone(node: Node): void {
  if (!isPrivateNode(node)) return;
  const el = node as HTMLElement;
  el.style.setProperty("background-color", "#000", "important");
  el.style.setProperty("background-image", "none", "important");
  el.style.setProperty("color", "#000", "important");
  el.style.setProperty("border-color", "#000", "important");
  el.style.setProperty("box-shadow", "none", "important");
  el.style.setProperty("text-shadow", "none", "important");
  if ("value" in el) {
    try { (el as HTMLInputElement).value = ""; } catch { /* a read-only value is not shown anyway */ }
  }
  el.removeAttribute("value");
  el.removeAttribute("placeholder");
  for (const child of Array.from(el.querySelectorAll<HTMLElement>("*"))) {
    child.style.setProperty("visibility", "hidden", "important");
  }
  for (const t of Array.from(el.childNodes)) if (t.nodeType === 3) t.textContent = "";
}
