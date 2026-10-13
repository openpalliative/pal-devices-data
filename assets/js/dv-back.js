import { readParams } from "../../ui/js/xparams.js";

export function showBack(id) {
  const box = document.querySelector("dv-back");
  const item = id && box?.querySelector(`[data-back="${CSS.escape(id)}"]`);
  if (!item) return false;
  item.hidden = false;
  box.hidden = false;
  return true;
}

class DvBack extends HTMLElement {
  connectedCallback() {
    if (this.hasAttribute("data-manual")) return;
    const known = (id) => Boolean(this.querySelector(`[data-back="${CSS.escape(id)}"]`));
    const { back } = readParams(["back"], { back: known });
    showBack(back);
  }
}

if (!customElements.get("dv-back")) customElements.define("dv-back", DvBack);
