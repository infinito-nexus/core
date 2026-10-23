(function () {
  const root = document.documentElement;
  function mirror() {
    const mode = root.getAttribute("data-theme-mode");
    if (mode === "light" || mode === "dark") {
      if (root.getAttribute("data-design-theme") !== mode) root.setAttribute("data-design-theme", mode);
    } else if (root.hasAttribute("data-design-theme")) {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-theme-mode"] });
  mirror();
})();
