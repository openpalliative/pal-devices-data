const KEY = "op:region";

export function getRegion() {
  try {
    const value = localStorage.getItem(KEY);
    return /^RU-[A-Z]{2,3}$/.test(value || "") ? value : null;
  } catch {
    return null;
  }
}

export function setRegion(iso) {
  try {
    if (iso) localStorage.setItem(KEY, iso);
    else localStorage.removeItem(KEY);
  } catch {}
  document.dispatchEvent(new CustomEvent("op-region-change", { detail: { region: iso || null } }));
}
