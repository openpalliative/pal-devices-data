export async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.className = "op-visually-hidden";
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  return ok;
}

class OpCopy extends HTMLElement {
  connectedCallback() {
    const button = this.querySelector("button");
    const live = this.querySelector("[aria-live]");
    if (!button) return;
    button.addEventListener("click", async () => {
      const source = this.getAttribute("for") ? document.getElementById(this.getAttribute("for")) : null;
      const text = this.getAttribute("text") ?? source?.value ?? source?.textContent ?? "";
      const ok = await copyText(text.trim()).catch(() => false);
      if (live) live.textContent = ok ? "Скопировано" : "Не получилось скопировать. Выделите текст и скопируйте вручную";
    });
    this.hidden = false;
  }
}

if (!customElements.get("op-copy")) customElements.define("op-copy", OpCopy);
