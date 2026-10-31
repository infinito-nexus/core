(function () {
  const root = document.documentElement;
  const modes = {
    "default-light": "light",
    "high-contrast": "light",
    "default-dark": "dark",
    "default-darker": "dark",
    "high-contrast-dark": "dark",
    "lcars": "dark"
  };
  function mirror() {
    const links = document.querySelectorAll("link[rel='stylesheet'][href*='style/themes/']");
    let theme = null;
    if (links.length === 1) {
      const name = (links[0].getAttribute("href") || "").split("style/themes/")[1].split(".css")[0];
      theme = Object.prototype.hasOwnProperty.call(modes, name) ? modes[name] : null;
    }
    if (theme) {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function brand() {
  if (INFINITO_DESIGN.title) {
      if (document.title !== INFINITO_DESIGN.title) {
        document.title = INFINITO_DESIGN.title;
      }
      const marks = document.querySelectorAll(".main-header .logo .logo-lg, .login-logo .logo-lg");
      for (let mark = 0; mark < marks.length; mark += 1) {
        if (marks[mark].textContent !== INFINITO_DESIGN.title) {
          marks[mark].textContent = INFINITO_DESIGN.title;
        }
      }
  }
  if (INFINITO_DESIGN.logo) {
      const icons = document.querySelectorAll("link[rel~='icon']");
      for (let icon = 0; icon < icons.length; icon += 1) {
        if (icons[icon].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
          icons[icon].removeAttribute("sizes");
          icons[icon].setAttribute("type", "image/x-icon");
          icons[icon].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
        }
      }
      const touch = document.querySelector("link[rel='apple-touch-icon']");
      if (touch && touch.getAttribute("href") !== INFINITO_DESIGN.urls['apple-touch-icon'].png) {
        touch.setAttribute("href", INFINITO_DESIGN.urls['apple-touch-icon'].png);
      }
  }
  }
  function apply() {
    mirror();
  if (INFINITO_DESIGN.title || INFINITO_DESIGN.logo) {
      brand();
  }
  }
  apply();
  document.addEventListener("DOMContentLoaded", apply);
})();
