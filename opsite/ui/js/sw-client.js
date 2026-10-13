export function registerServiceWorker(swUrl) {
  if (!("serviceWorker" in navigator)) return;
  let accepted = false;
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!accepted || reloaded) return;
    reloaded = true;
    location.reload();
  });
  navigator.serviceWorker.register(swUrl).then((reg) => {
    const offer = (worker) => {
      if (!navigator.serviceWorker.controller || document.querySelector(".op-update")) return;
      const bar = document.createElement("div");
      bar.className = "op-update";
      bar.setAttribute("role", "status");
      const text = document.createElement("p");
      text.textContent = "Вышла новая версия. Обновите страницу, когда закончите ввод";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "op-btn op-btn--primary";
      button.textContent = "Обновить";
      button.addEventListener("click", () => {
        accepted = true;
        button.disabled = true;
        worker.postMessage("skip-waiting");
      });
      bar.append(text, button);
      document.body.append(bar);
    };
    if (reg.waiting) offer(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const worker = reg.installing;
      worker?.addEventListener("statechange", () => {
        if (worker.state === "installed") offer(worker);
      });
    });
  }).catch(() => {});
}
