(function () {
  var root = document.documentElement;
  root.classList.add("op-js");
  try {
    var prefs = JSON.parse(localStorage.getItem("op:prefs") || "{}");
    if (prefs.theme === "light" || prefs.theme === "dark") root.setAttribute("data-theme", prefs.theme);
    if (prefs.size === "l" || prefs.size === "xl") root.setAttribute("data-size", prefs.size);
  } catch (e) {}
})();
