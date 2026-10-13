class OpPrint extends HTMLElement {
  connectedCallback() {
    this.querySelector("button")?.addEventListener("click", () => window.print());
    this.hidden = false;
  }
}

if (!customElements.get("op-print")) customElements.define("op-print", OpPrint);
