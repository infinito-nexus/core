(function () {
  const root = document.documentElement;
  function mirror() {
    const body = document.body;
    const admin = root.getAttribute("data-theme");
    if (body && body.classList.contains("theme-dark")) {
      root.setAttribute("data-design-theme", "dark");
    } else if (body && body.classList.contains("theme-light")) {
      root.setAttribute("data-design-theme", "light");
    } else if (admin === "dark" || admin === "light") {
      root.setAttribute("data-design-theme", admin);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function watchBody() {
    new MutationObserver(mirror).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    mirror();
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  mirror();
  if (document.body) {
    watchBody();
  } else {
    document.addEventListener("DOMContentLoaded", watchBody);
  }
  if (INFINITO_DESIGN.logo) {
    const icons = {
      icon: INFINITO_DESIGN.urls.favicon_ico,
      "apple-touch-icon": INFINITO_DESIGN.urls['apple-touch-icon'].png
    };
    function brandIcons() {
      const links = document.head.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon']");
      for (let index = 0; index < links.length; index += 1) {
        const link = links[index];
        const href = link.getAttribute("rel") === "apple-touch-icon" ? icons["apple-touch-icon"] : icons.icon;
        if (link.getAttribute("href") !== href) {
          link.removeAttribute("sizes");
          link.setAttribute("type", link.getAttribute("rel") === "apple-touch-icon" ? "image/png" : "image/x-icon");
          link.setAttribute("href", href);
        }
      }
    }
    new MutationObserver(brandIcons).observe(document.head, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
    brandIcons();
  }
})();
