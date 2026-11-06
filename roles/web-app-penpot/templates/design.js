(function () {
  const root = document.documentElement;
  function visitor() {
    return window.location.hash.indexOf("#/auth/") === 0;
  }
  function mirror() {
    const body = document.body;
    let theme = null;
    if (body && !visitor()) {
      if (body.classList.contains("light")) {
        theme = "light";
      } else if (body.classList.contains("default")) {
        theme = "dark";
      }
    }
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
  ["pushState", "replaceState"].forEach(function (name) {
    const original = window.history[name];
    window.history[name] = function () {
      const result = original.apply(this, arguments);
      mirror();
      return result;
    };
  });
  window.addEventListener("hashchange", mirror);
  window.addEventListener("popstate", mirror);
  if (document.body) {
    watchBody();
  } else {
    document.addEventListener("DOMContentLoaded", watchBody);
  }
  if (INFINITO_DESIGN.title) {
    const title = INFINITO_DESIGN.title;
    function brandTitle() {
      const current = document.title;
      let page = current.replace(/\s*\|\s*Full-stack design$/, "");
      if (page.slice(-title.length) !== title) {
        page = page.replace(/(^|\s-\s)Penpot$/, "");
        page = page ? `${page  } - ${  title}` : title;
      }
      if (page !== current) {
        document.title = page;
      }
    }
    function watchTitle() {
      const element = document.querySelector("title");
      if (!element) {
        return false;
      }
      new MutationObserver(brandTitle).observe(element, { childList: true, characterData: true, subtree: true });
      brandTitle();
      return true;
    }
    if (!watchTitle()) {
      document.addEventListener("DOMContentLoaded", watchTitle);
    }
  }
  if (INFINITO_DESIGN.logo) {
    function brandIcon() {
      const icons = document.querySelectorAll("link[rel~='icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
        }
      }
    }
    new MutationObserver(brandIcon).observe(document.head, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
    brandIcon();
    document.addEventListener("DOMContentLoaded", brandIcon);
  }
})();
