import { BLOCKED_TEXT, StoreError, wipeAll } from "./store.js";
import { applyPrefs } from "./prefs.js";

class OpWipe extends HTMLElement {
  connectedCallback() {
    const dialog = this.querySelector("dialog");
    const open = this.querySelector("[data-wipe-open]");
    const live = this.querySelector("[aria-live]");
    if (!dialog || !open || typeof dialog.showModal !== "function") return;
    const say = (state, text) => {
      if (!live) return;
      live.dataset.state = state;
      live.textContent = text;
    };
    open.addEventListener("click", () => dialog.showModal());
    dialog.addEventListener("close", async () => {
      if (dialog.returnValue !== "wipe") return;
      dialog.returnValue = "";
      open.setAttribute("aria-disabled", "true");
      say("busy", "Удаляем");
      try {
        await wipeAll();
        applyPrefs({});
        say("done", "Готово. Всё, что инструменты хранили в этом браузере, удалено");
      } catch (error) {
        say("error", `Ошибка: не всё удалено. ${error instanceof StoreError ? error.message : BLOCKED_TEXT}`);
      } finally {
        open.removeAttribute("aria-disabled");
      }
    });
    this.hidden = false;
  }
}

if (!customElements.get("op-wipe")) customElements.define("op-wipe", OpWipe);
