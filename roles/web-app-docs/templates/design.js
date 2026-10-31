(function () {
  const root = document.documentElement;
  function mirror() {
    const theme = root.classList.contains("dark") ? "dark" : "light";
    if (root.getAttribute("data-design-theme") !== theme) root.setAttribute("data-design-theme", theme);
  }
  if (/darkMode/.test(root.getAttribute("x-data") || "")) {
    mirror();
    new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  }
  if (INFINITO_DESIGN.logo) {
    function favicon() {
      const link = document.querySelector("link[rel~='icon']");
      if (link) link.setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", favicon);
    } else {
      favicon();
    }
  }
})();
