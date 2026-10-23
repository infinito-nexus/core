(function () {
  const root = document.documentElement;
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  function stored() {
    try {
      return localStorage.getItem("theme");
    } catch {
      return null;
    }
  }
  function sync() {
    const choice = stored();
    if (choice === "light" || choice === "dark") {
      if (root.getAttribute("data-design-theme") !== choice) root.setAttribute("data-design-theme", choice);
      return;
    }
    if (root.hasAttribute("data-design-theme")) root.removeAttribute("data-design-theme");
    const system = query.matches ? "dark" : "light";
    if (root.getAttribute("data-theme") !== system) root.setAttribute("data-theme", system);
  }
  sync();
  query.addEventListener("change", sync);
  new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
})();
