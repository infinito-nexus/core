(function () {
  const root = document.documentElement;
  function mirror() {
    const classes = root.classList;
    if (classes.contains("skin-theme-clientpref-night")) {
      root.setAttribute("data-design-theme", "dark");
    } else if (classes.contains("skin-theme-clientpref-day") || classes.contains("skin-theme-clientpref--excluded")) {
      root.setAttribute("data-design-theme", "light");
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  mirror();
})();
