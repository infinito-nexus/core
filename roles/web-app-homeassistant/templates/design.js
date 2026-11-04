(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  if (INFINITO_DESIGN.title) {
    const title = INFINITO_DESIGN.title;
    const product = "Home Assistant";
    function brandTitle() {
      if (document.title.indexOf(title) === -1 && document.title.indexOf(product) !== -1) {
        document.title = document.title.split(product).join(title);
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
    function brandIcons() {
      const icon = document.querySelector("link[rel='icon']") || document.head.appendChild(document.createElement("link"));
      icon.rel = "icon";
      icon.type = "image/x-icon";
      icon.href = INFINITO_DESIGN.urls.favicon_ico;
      const touch = document.querySelector("link[rel='apple-touch-icon']");
      if (touch) {
        touch.href = INFINITO_DESIGN.urls['apple-touch-icon'].png;
      }
    }
    brandIcons();
    document.addEventListener("DOMContentLoaded", brandIcons);
  }
  const visitor = /^\/(onboarding\.html|auth\/)/.test(window.location.pathname);
  function storedMode() {
    if (visitor) {
      return undefined;
    }
    try {
      const selected = JSON.parse(window.localStorage.getItem("selectedTheme"));
      return selected ? selected.dark : undefined;
    } catch {
      return undefined;
    }
  }
  function applyMode(dark) {
    if (typeof dark === "boolean" && dark !== prefersDark.matches) {
      root.setAttribute("data-design-theme", dark ? "dark" : "light");
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function mirrorMode() {
    const app = document.querySelector("home-assistant");
    const themes = app && app.hass && app.hass.themes;
    applyMode(themes && typeof themes.darkMode === "boolean" ? themes.darkMode : storedMode());
  }
  window.addEventListener(
    "settheme",
    function (event) {
      if (event.detail && "dark" in event.detail) {
        applyMode(event.detail.dark);
      }
    },
    true
  );
  prefersDark.addEventListener("change", function () {
    applyMode(storedMode());
  });
  new MutationObserver(mirrorMode).observe(root, { attributes: true, attributeFilter: ["style"] });
  mirrorMode();
})();
