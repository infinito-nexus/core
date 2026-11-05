(function () {
  const root = document.documentElement;
  let watched = null;
  const observer = new MutationObserver(mirror);
  function mirror() {
    const body = document.body;
    if (!body) return;
    const mode = body.getAttribute("data-color-mode");
    if (body.getAttribute("data-auto-theme-switcher-theme-value") === "sync_with_os" || (mode !== "light" && mode !== "dark")) {
      root.removeAttribute("data-design-theme");
    } else if (root.getAttribute("data-design-theme") !== mode) {
      root.setAttribute("data-design-theme", mode);
    }
  }
  function bind() {
    if (!document.body || document.body === watched) return mirror();
    observer.disconnect();
    watched = document.body;
    observer.observe(watched, { attributes: true, attributeFilter: ["data-color-mode", "data-auto-theme-switcher-theme-value"] });
    mirror();
  }
  bind();
  document.addEventListener("DOMContentLoaded", bind);
  document.addEventListener("turbo:load", bind);
})();
