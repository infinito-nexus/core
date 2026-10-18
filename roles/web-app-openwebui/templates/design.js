(function () {
  const root = document.documentElement;

  function chosen() {
    try {
      return window.localStorage.getItem("theme") || "system";
    } catch {
      return "system";
    }
  }

  function assign(name, value) {
    if (value === null) {
      if (root.hasAttribute(name)) root.removeAttribute(name);
    } else if (root.getAttribute(name) !== value) {
      root.setAttribute(name, value);
    }
  }

  function mirror() {
    const theme = chosen();
    assign("data-design-app-theme", theme);
    assign("data-design-theme", theme === "system" ? null : root.classList.contains("dark") ? "dark" : "light");
  }

  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class", "style"] });
  window.addEventListener("storage", mirror);
})();
