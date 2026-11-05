(function () {
  const root = document.documentElement;
  const path = window.location.pathname;
  let surface = "legacy";
  if (/^\/mobile(\/|$)/.test(path)) {
    surface = "mobile";
  } else if (/^\/desktop(\/|$)/.test(path)) {
    surface = "desktop";
  } else if (/^\/help(\/|$)/.test(path)) {
    surface = "help";
  }
  root.setAttribute("data-design-surface", surface);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  function mirror() {
    const theme = root.getAttribute("data-theme");
    if ((theme === "light" || theme === "dark") && theme !== (media.matches ? "dark" : "light")) {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  if (surface === "legacy") {
    new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    mirror();
  }
  if (INFINITO_DESIGN.logo) {
  const favicon = INFINITO_DESIGN.urls.favicon_ico;
  const touchIcon = INFINITO_DESIGN.urls['apple-touch-icon'].png;
  let icons = document.querySelectorAll("link[rel~='icon']");
  if (icons.length === 0) {
    const icon = document.createElement("link");
    icon.rel = "icon";
    document.head.appendChild(icon);
    icons = [icon];
  }
  for (let index = 0; index < icons.length; index += 1) {
    icons[index].setAttribute("type", "image/x-icon");
    icons[index].setAttribute("href", favicon);
  }
  const touch = document.querySelectorAll("link[rel='apple-touch-icon']");
  for (let position = 0; position < touch.length; position += 1) {
    touch[position].setAttribute("href", touchIcon);
  }
  }
})();
