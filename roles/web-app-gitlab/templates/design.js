(function () {
  const root = document.documentElement;
  function chosen() {
    const classes = root.classList;
    if (classes.contains("gl-system")) {
      return null;
    }
    if (classes.contains("gl-dark")) {
      return "dark";
    }
    return classes.contains("gl-light") ? "light" : null;
  }
  function mirror() {
    const theme = chosen();
    if (theme) {
      if (root.getAttribute("data-design-theme") !== theme) {
        root.setAttribute("data-design-theme", theme);
      }
    } else if (root.hasAttribute("data-design-theme")) {
      root.removeAttribute("data-design-theme");
    }
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
})();
