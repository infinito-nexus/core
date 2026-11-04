(function () {
  const root = document.documentElement;
  const DARK = ["dark", "dark-highcontrast"];
  const LIGHT = ["light", "light-highcontrast"];
  function picked(ids, wanted) {
    return ids.some(function (id) {
      return wanted.indexOf(id) !== -1;
    });
  }
  function mirror() {
    const ids = (document.body.getAttribute("data-themes") || "").split(",");
    const mode = picked(ids, DARK) ? "dark" : picked(ids, LIGHT) ? "light" : null;
    if (mode === null) {
      if (root.hasAttribute("data-design-theme")) root.removeAttribute("data-design-theme");
    } else if (root.getAttribute("data-design-theme") !== mode) {
      root.setAttribute("data-design-theme", mode);
    }
  }
  function watch() {
    mirror();
    new MutationObserver(mirror).observe(document.body, { attributes: true, attributeFilter: ["data-themes"] });
  }
  if (document.body) watch();
  else document.addEventListener("DOMContentLoaded", watch);
})();
