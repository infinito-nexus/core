(function () {
  const root = document.documentElement;
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  let picked = "";
  function stored() {
    try {
      const value = window.localStorage.getItem("theme");
      return value === "light" || value === "dark" ? value : "";
    } catch {
      return "";
    }
  }
  function apply() {
    if (picked) {
      root.setAttribute("data-design-theme", picked);
      return;
    }
    root.removeAttribute("data-design-theme");
    const browser = prefersDark.matches ? "dark" : "light";
    if (root.getAttribute("data-theme") !== browser) {
      root.setAttribute("data-theme", browser);
    }
  }
  if (/^\/examples\/(index\.html)?$/.test(window.location.pathname)) {
    picked = stored();
    prefersDark.addEventListener("change", apply);
    window.addEventListener("storage", function () {
      picked = stored();
      apply();
    });
    document.addEventListener(
      "click",
      function (event) {
        if (event.target && event.target.closest && event.target.closest("#buttonTheme")) {
          window.setTimeout(function () {
            const theme = root.getAttribute("data-theme");
            picked = theme === "light" || theme === "dark" ? theme : "";
            apply();
          }, 0);
        }
      },
      true
    );
    apply();
  }
  if (INFINITO_DESIGN.title || INFINITO_DESIGN.logo) {
    function brand() {
    if (INFINITO_DESIGN.title) {
        const title = INFINITO_DESIGN.title;
        if (document.title.indexOf(title) === -1) {
          document.title = document.title ? `${document.title  } | ${  title}` : title;
        }
    }
    if (INFINITO_DESIGN.logo) {
        const icon = INFINITO_DESIGN.urls.favicon.png;
        const links = document.querySelectorAll("link[rel~='icon']");
        for (let index = 0; index < links.length; index += 1) {
          if (links[index].getAttribute("href") !== icon) {
            links[index].setAttribute("type", "image/png");
            links[index].setAttribute("href", icon);
          }
        }
        if (links.length === 0 && document.head) {
          const link = document.createElement("link");
          link.setAttribute("rel", "icon");
          link.setAttribute("type", "image/png");
          link.setAttribute("href", icon);
          document.head.appendChild(link);
        }
        const symbol = document.querySelector("#topBar .brand img");
        if (symbol && symbol.getAttribute("src") !== icon) {
          symbol.setAttribute("src", icon);
        }
    }
    }
    document.addEventListener("DOMContentLoaded", brand);
    brand();
  }
})();
