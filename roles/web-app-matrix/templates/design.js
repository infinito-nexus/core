(function () {
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  function mirror() {
    const classes = document.body.className || "";
    const app = /\bcpd-theme-dark(-hc)?\b/.test(classes) ? "dark" : /\bcpd-theme-light(-hc)?\b/.test(classes) ? "light" : "";
    if (app && app !== (system.matches ? "dark" : "light")) {
      root.setAttribute("data-design-theme", app);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function watch() {
    mirror();
    new MutationObserver(mirror).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }
  if (document.body) {
    watch();
  } else {
    document.addEventListener("DOMContentLoaded", watch);
  }
})();
