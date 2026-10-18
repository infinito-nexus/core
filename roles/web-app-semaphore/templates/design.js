(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  const choiceKey = "infinito.design.theme";
  const themeKey = "darkMode";
  function read(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function write(key, value) {
    try {
      if (value === null) {
        window.localStorage.removeItem(key);
      } else {
        window.localStorage.setItem(key, value);
      }
    } catch {
      return;
    }
  }
  function appDark() {
    return read(themeKey) === "1";
  }
  function chosen() {
    return read(choiceKey) === "explicit";
  }
  function follow() {
    if (!chosen()) {
      write(themeKey, prefersDark.matches ? "1" : null);
    }
  }
  function mirror() {
    if (chosen()) {
      root.setAttribute("data-design-theme", appDark() ? "dark" : "light");
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  follow();
  mirror();
  let last = appDark();
  function toggled() {
    const now = appDark();
    if (now !== last) {
      last = now;
      write(choiceKey, "explicit");
      mirror();
    }
  }
  ["change", "click", "touchend", "keyup"].forEach(function (type) {
    document.addEventListener(
      type,
      function (event) {
        if (event.target && event.target.closest && event.target.closest(".DarkModeSwitchWrap")) {
          window.setTimeout(toggled, 0);
        }
      },
      true
    );
  });
  prefersDark.addEventListener("change", function () {
    follow();
    last = appDark();
  });
  if (INFINITO_DESIGN.title || INFINITO_DESIGN.logo) {
    function brand() {
    if (INFINITO_DESIGN.title) {
        if (document.title !== INFINITO_DESIGN.title) {
          document.title = INFINITO_DESIGN.title;
        }
    }
    if (INFINITO_DESIGN.logo) {
        const icons = document.querySelectorAll("link[rel~='icon']");
        for (let index = 0; index < icons.length; index += 1) {
          if (icons[index].getAttribute("href") !== INFINITO_DESIGN.urls.favicon_ico) {
            icons[index].setAttribute("type", "image/x-icon");
            icons[index].setAttribute("href", INFINITO_DESIGN.urls.favicon_ico);
          }
        }
    }
    }
    new MutationObserver(brand).observe(document.head, { childList: true, subtree: true, characterData: true });
    brand();
    document.addEventListener("DOMContentLoaded", brand);
  }
})();
