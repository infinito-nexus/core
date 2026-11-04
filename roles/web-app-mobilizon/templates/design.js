(function () {
  const root = document.documentElement;
  function stored() {
    try {
      return window.localStorage.getItem("theme");
    } catch {
      return null;
    }
  }
  function mirror() {
    const theme = stored();
    if (theme === "dark" || theme === "light") {
      const wanted = root.classList.contains("dark") ? "dark" : "light";
      if (root.getAttribute("data-design-theme") !== wanted) root.setAttribute("data-design-theme", wanted);
    } else if (root.hasAttribute("data-design-theme")) {
      root.removeAttribute("data-design-theme");
    }
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["class"] });
  window.addEventListener("storage", mirror);
  document.addEventListener(
    "change",
    function () {
      setTimeout(mirror, 0);
    },
    true,
  );
})();
