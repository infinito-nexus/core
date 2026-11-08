(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  function mirror() {
    const theme = root.getAttribute("data-bs-theme");
    const explicit = theme === "light" || theme === "dark";
    if (explicit && (theme === "dark") !== prefersDark.matches) {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-bs-theme"] });
  prefersDark.addEventListener("change", mirror);
  mirror();
  if (INFINITO_DESIGN.logo) {
    const icons = {
      "image/png": INFINITO_DESIGN.urls.favicon.png,
      "image/svg+xml": INFINITO_DESIGN.urls.favicon.svg,
      "image/vnd.microsoft.icon": INFINITO_DESIGN.urls.favicon_ico
    };
    const links = document.querySelectorAll("link[rel~='icon']");
    for (let index = 0; index < links.length; index += 1) {
      const href = icons[links[index].getAttribute("type")] || icons["image/vnd.microsoft.icon"];
      if (links[index].getAttribute("href") !== href) {
        links[index].setAttribute("href", href);
      }
    }
  }
})();
