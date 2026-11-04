(function () {
  const root = document.documentElement;
  function mirror() {
    const scheme = root.getAttribute("data-color-scheme");
    if (root.getAttribute("data-system-theme") === "true" || (scheme !== "dark" && scheme !== "light")) {
      root.removeAttribute("data-design-theme");
    } else if (root.getAttribute("data-design-theme") !== scheme) {
      root.setAttribute("data-design-theme", scheme);
    }
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-color-scheme", "data-system-theme"] });
})();
