(function () {
  const root = document.documentElement;
  function chosenScheme() {
    try {
      return JSON.parse(window.localStorage.getItem("hugoDocsUserSettings") || "{}").colorScheme;
    } catch {
      return 0;
    }
  }
  function mirror() {
    const chosen = chosenScheme();
    if (chosen === 2) {
      root.setAttribute("data-design-theme", "light");
    } else if (chosen === 3) {
      root.setAttribute("data-design-theme", "dark");
    } else {
      root.removeAttribute("data-design-theme");
    }
  }
  function mirrorLater() {
    window.setTimeout(mirror, 0);
  }
  new MutationObserver(mirrorLater).observe(root, { attributes: true, attributeFilter: ["class"] });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", mirrorLater);
  window.addEventListener("storage", mirrorLater);
  document.addEventListener(
    "click",
    function (event) {
      if (event.target && event.target.closest && event.target.closest("#theme-toggle")) {
        mirrorLater();
      }
    },
    true
  );
  mirror();
})();
