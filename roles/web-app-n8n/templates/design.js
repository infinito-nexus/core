(function () {
  const root = document.documentElement;
  function stored() {
    try {
      return new URLSearchParams(window.location.search).get("theme") || window.localStorage.getItem("N8N_THEME");
    } catch {
      return null;
    }
  }
  function chosen() {
    const body = document.body;
    if (body && body.hasAttribute("data-theme")) {
      return body.getAttribute("data-theme");
    }
    return document.getElementById("n8n-app") ? null : stored();
  }
  function mirror() {
    const theme = chosen();
    if (theme === "light" || theme === "dark") {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function watchBody() {
    new MutationObserver(mirror).observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
    mirror();
  }
  mirror();
  if (document.body) {
    watchBody();
  } else {
    document.addEventListener("DOMContentLoaded", watchBody);
  }
  if (INFINITO_DESIGN.title) {
    const title = INFINITO_DESIGN.title;
    function brandTitle() {
      const current = document.title;
      if (current.indexOf(title) !== -1) {
        return;
      }
      const page = current.replace(/\s*-\s*n8n(\[[A-Z]+\])?$/, "").replace(/^n8n\.io\s*-\s*/, "");
      document.title = page && page !== "Workflow Automation" ? `${page  } - ${  title}` : title;
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
