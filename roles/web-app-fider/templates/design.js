(function () {
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const THEME = "theme";
  const CHOSEN = "infinito-design-theme-chosen";
  function read(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function write(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      return;
    }
  }
  function preferred() {
    return media.matches ? "dark" : "light";
  }
  function sync() {
    const body = document.body;
    if (read(CHOSEN) === "1") {
      const mode = (body && body.getAttribute("data-theme")) || read(THEME);
      if (mode === "light" || mode === "dark") root.setAttribute("data-design-theme", mode);
      return;
    }
    root.removeAttribute("data-design-theme");
    write(THEME, preferred());
    if (body && body.getAttribute("data-theme") !== preferred()) body.setAttribute("data-theme", preferred());
  }
  function watch() {
    sync();
    new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
  }
  const requested = new URLSearchParams(window.location.search).get("theme");
  if (requested === "light" || requested === "dark") write(CHOSEN, "1");
  sync();
  document.addEventListener(
    "click",
    function (event) {
      if (event.target.closest && event.target.closest('.c-themeswitcher[aria-label="Toggle theme"]')) write(CHOSEN, "1");
    },
    true
  );
  if (document.body) watch();
  else document.addEventListener("DOMContentLoaded", watch);
  media.addEventListener("change", sync);
})();
