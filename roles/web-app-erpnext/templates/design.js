(function () {
  const root = document.documentElement;
  function mirror() {
    const mode = root.getAttribute("data-theme-mode");
    if (mode === "light" || mode === "dark") {
      root.setAttribute("data-design-theme", mode);
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-theme-mode"] });
})();
