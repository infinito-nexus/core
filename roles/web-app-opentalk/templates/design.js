(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  let recheck = 0;
  function appMode() {
    if (!document.body) {
      return null;
    }
    const channels = (getComputedStyle(document.body).color.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    if (channels.length < 3) {
      return null;
    }
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2] > 127 ? "dark" : "light";
  }
  function mirror() {
    const mode = appMode();
    if (mode === null || mode === (prefersDark.matches ? "dark" : "light")) {
      root.removeAttribute("data-design-theme");
    } else if (root.getAttribute("data-design-theme") !== mode) {
      root.setAttribute("data-design-theme", mode);
    }
  }
  function brand() {
  if (INFINITO_DESIGN.title) {
      const wanted = document.title.replace(/OpenTalk/g, INFINITO_DESIGN.title);
      if (document.title !== wanted) {
        document.title = wanted;
      }
  }
  if (INFINITO_DESIGN.logo) {
      const icons = document.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
        }
      }
  }
  }
  function refresh() {
    mirror();
    brand();
  }
  new MutationObserver(refresh).observe(document.head, { childList: true, subtree: true, characterData: true });
  prefersDark.addEventListener("change", function () {
    root.removeAttribute("data-design-theme");
    window.clearTimeout(recheck);
    recheck = window.setTimeout(mirror, 400);
  });
  document.addEventListener("DOMContentLoaded", refresh);
  refresh();
})();
