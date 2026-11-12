(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  function mirror() {
    const match = /(?:^|\s)theme--(light|dark|dim)(?:\s|$)/.exec(root.className);
    const mode = match ? (match[1] === "light" ? "light" : "dark") : null;
    if (mode === null || mode === (prefersDark.matches ? "dark" : "light")) {
      if (root.hasAttribute("data-design-theme")) {
        root.removeAttribute("data-design-theme");
      }
    } else if (root.getAttribute("data-design-theme") !== mode) {
      root.setAttribute("data-design-theme", mode);
    }
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  prefersDark.addEventListener("change", function () {
    root.removeAttribute("data-design-theme");
    window.setTimeout(mirror, 500);
  });
  if (INFINITO_DESIGN.logo) {
    function icons() {
      const links = document.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon']");
      for (let index = 0; index < links.length; index += 1) {
        const touch = links[index].getAttribute("rel") === "apple-touch-icon";
        const href = touch ? INFINITO_DESIGN.urls['apple-touch-icon'].png : INFINITO_DESIGN.urls.favicon_ico;
        if (links[index].getAttribute("href") !== href) {
          links[index].setAttribute("type", touch ? "image/png" : "image/x-icon");
          links[index].setAttribute("href", href);
        }
      }
    }
    icons();
    document.addEventListener("DOMContentLoaded", icons);
  }
})();
