(function () {
  const root = document.documentElement;
  const key = "pf_m2s.color-scheme";
  function stored() {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function chosen() {
    const body = document.body;
    if (body && body.classList.contains("force-dark-mode")) {
      return "dark";
    }
    if (body && body.classList.contains("force-light-mode")) {
      return "light";
    }
    const value = stored();
    return value === "dark" || value === "light" ? value : null;
  }
  function mirror() {
    const theme = chosen();
    if (theme) {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function watchBody() {
    new MutationObserver(mirror).observe(document.body, { attributes: true, attributeFilter: ["class"] });
    mirror();
  }
  mirror();
  window.addEventListener("storage", function (event) {
    if (event.key === key) {
      mirror();
    }
  });
  if (document.body) {
    watchBody();
  } else {
    document.addEventListener("DOMContentLoaded", watchBody);
  }
  if (INFINITO_DESIGN.logo) {
    function brandIcon() {
      const icons = document.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
        }
      }
    }
    new MutationObserver(brandIcon).observe(document.head, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
    brandIcon();
  }
})();
