(function () {
  const KEY = "isDarkMode";
  const SEED = "infinito-design-seeded-dark-mode";
  const root = document.documentElement;
  function read(name) {
    try {
      return window.localStorage.getItem(name);
    } catch {
      return null;
    }
  }
  function write(name, value) {
    try {
      if (value === null) {
        window.localStorage.removeItem(name);
      } else {
        window.localStorage.setItem(name, value);
      }
    } catch {
      return;
    }
  }
  function boot() {
    const stored = read(KEY);
    const seeded = read(SEED);
    if (stored === null || stored === seeded) {
      const value = window.matchMedia("(prefers-color-scheme: dark)").matches ? "true" : "false";
      write(KEY, value);
      write(SEED, value);
      root.removeAttribute("data-design-theme");
      return;
    }
    write(SEED, null);
    root.setAttribute("data-design-theme", stored === "true" ? "dark" : "light");
  }
  function picked(event) {
    if (!event.target.closest || !event.target.closest(".MuiAppBar-root .MuiSwitch-root")) {
      return;
    }
    window.setTimeout(function () {
      write(SEED, null);
      root.setAttribute("data-design-theme", read(KEY) === "true" ? "dark" : "light");
    }, 0);
  }
  boot();
  document.addEventListener("change", picked, true);
  if (INFINITO_DESIGN.title) {
    const title = INFINITO_DESIGN.title;
    function brandTitle() {
      if (document.title !== title) {
        document.title = title;
      }
    }
    function watchTitle() {
      const element = document.querySelector("title");
      if (!element) {
        return false;
      }
      new MutationObserver(brandTitle).observe(element, { childList: true, characterData: true, subtree: true });
      brandTitle();
      return true;
    }
    if (!watchTitle()) {
      document.addEventListener("DOMContentLoaded", watchTitle);
    }
  }
  if (INFINITO_DESIGN.logo) {
    function brandIcon() {
      const icons = document.querySelectorAll("link[rel~='icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
        }
      }
    }
    new MutationObserver(brandIcon).observe(document.head, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
    brandIcon();
    document.addEventListener("DOMContentLoaded", brandIcon);
  }
})();
