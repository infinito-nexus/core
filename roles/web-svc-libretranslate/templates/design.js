(function () {
  const root = document.documentElement;
  if (INFINITO_DESIGN.title) {
    if (window.location.pathname.indexOf("/docs") === 0) {
      document.title = INFINITO_DESIGN.title;
    }
  }
  if (INFINITO_DESIGN.logo) {
    const icons = document.querySelectorAll("link[rel~='icon']");
    for (let index = 1; index < icons.length; index += 1) {
      icons[index].parentNode.removeChild(icons[index]);
    }
    const icon = icons[0] || document.head.appendChild(document.createElement("link"));
    icon.rel = "icon";
    icon.type = "image/x-icon";
    icon.removeAttribute("sizes");
    icon.href = INFINITO_DESIGN.urls.favicon_ico;
  }
  const rules = Object.getOwnPropertyDescriptor(CSSStyleSheet.prototype, "cssRules");
  Object.defineProperty(CSSStyleSheet.prototype, "cssRules", {
    configurable: true,
    enumerable: rules.enumerable,
    get: function () {
      try {
        return rules.get.call(this);
      } catch {
        return [];
      }
    },
  });
  function chosen() {
    try {
      const scheme = window.localStorage.getItem("scheme");
      return scheme === "light" || scheme === "dark" ? scheme : null;
    } catch {
      return null;
    }
  }
  function mirror() {
    const scheme = chosen();
    if (scheme) {
      root.setAttribute("data-design-theme", scheme);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  mirror();
  document.addEventListener("DOMContentLoaded", function () {
    const save = window.savePreferredColorScheme;
    if (typeof save === "function") {
      window.savePreferredColorScheme = function (scheme) {
        save(scheme);
        mirror();
      };
    }
    mirror();
  });
  window.addEventListener("storage", mirror);
})();
