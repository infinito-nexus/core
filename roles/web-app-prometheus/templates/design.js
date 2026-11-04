(function () {
  const root = document.documentElement;
  function stored() {
    try {
      return window.localStorage.getItem("mantine-color-scheme-value");
    } catch {
      return null;
    }
  }
  function mirror() {
    const theme = stored();
    if (theme === "light" || theme === "dark") {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-mantine-color-scheme"] });
  window.addEventListener("storage", mirror);
  mirror();
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
