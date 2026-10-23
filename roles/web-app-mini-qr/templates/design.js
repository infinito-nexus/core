(function () {
  const root = document.documentElement;
  if (INFINITO_DESIGN.title) {
    document.title = INFINITO_DESIGN.title;
  }
  if (INFINITO_DESIGN.logo) {
    const icon = document.querySelector("link[rel='icon']") || document.head.appendChild(document.createElement("link"));
    icon.rel = "icon";
    icon.type = "image/svg+xml";
    icon.href = INFINITO_DESIGN.urls.favicon.svg;
    const touch = document.querySelector("link[rel='apple-touch-icon']") || document.head.appendChild(document.createElement("link"));
    touch.rel = "apple-touch-icon";
    touch.href = INFINITO_DESIGN.urls['apple-touch-icon'].png;
  }
  function mirror() {
    let choice;
    try {
      choice = window.localStorage.getItem("dark-mode-preference");
    } catch {
      choice = null;
    }
    if (choice === "light" || choice === "dark") {
      root.setAttribute("data-design-theme", choice);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  document.addEventListener(
    "click",
    function () {
      window.setTimeout(mirror, 0);
    },
    true
  );
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", mirror);
  mirror();
})();
