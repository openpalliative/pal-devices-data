import { copyText } from "./copy.js";

class OpShare extends HTMLElement {
  connectedCallback() {
    const text = this.dataset.text || "";
    const title = this.dataset.title || "";
    const live = this.querySelector("[aria-live]");
    const native = this.querySelector('[data-share="native"]');
    const copy = this.querySelector('[data-share="copy"]');
    const sms = this.querySelector('[data-share="sms"]');
    if (sms && /android/i.test(navigator.userAgent)) sms.href = `sms:?body=${encodeURIComponent(text)}`;
    if (native && navigator.share) {
      native.hidden = false;
      native.addEventListener("click", () => navigator.share({ title, text }).catch(() => {}));
    }
    if (copy) {
      copy.hidden = false;
      copy.addEventListener("click", async () => {
        const ok = await copyText(text).catch(() => false);
        if (live) live.textContent = ok ? "Текст скопирован" : "Не получилось скопировать";
      });
    }
  }
}

if (!customElements.get("op-share")) customElements.define("op-share", OpShare);
