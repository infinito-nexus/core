(function () {
  const root = document.documentElement;
  function persisted() {
    try {
      const saved = JSON.parse(window.localStorage.getItem("stalwart-ui") || "null");
      return (saved && saved.state && saved.state.theme) || null;
    } catch {
      return null;
    }
  }
  function stored() {
    const cookie = /(?:^|;\s*)colorMode=(dark|light)/.exec(document.cookie);
    const theme = cookie ? cookie[1] : persisted();
    return theme === "dark" || theme === "light" ? theme : null;
  }
  function mirror() {
    const theme = root.classList.contains("dark") || root.classList.contains("dark-mode") ? "dark" : stored();
    if (theme) {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  mirror();
  if (INFINITO_DESIGN.title) {
    function brandTitle() {
      const title = INFINITO_DESIGN.title;
      const next = document.title === "Portal" ? title : document.title.replace(/(^|\s·\s)Stalwart WebUI$/, function (match, prefix) {
        return prefix + title;
      });
      if (next !== document.title) {
        document.title = next;
      }
    }
    new MutationObserver(brandTitle).observe(document.head, { childList: true, subtree: true, characterData: true });
    brandTitle();
    document.addEventListener("DOMContentLoaded", brandTitle);
  }
  if (INFINITO_DESIGN.logo) {
    function brandIcon() {
      const href = INFINITO_DESIGN.urls.favicon_ico;
      const icons = document.querySelectorAll("link[rel~='icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== href) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", href);
        }
      }
    }
    new MutationObserver(brandIcon).observe(document.head, { childList: true, subtree: true });
    brandIcon();
    document.addEventListener("DOMContentLoaded", brandIcon);
  }
})();
