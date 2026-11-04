(function () {
  const root = document.documentElement;
  const scheme = document.querySelector("style[data-color-scheme]");
  if (scheme && scheme.getAttribute("data-color-scheme") === "dark") {
    root.setAttribute("data-design-theme", "dark");
  } else {
    root.removeAttribute("data-design-theme");
  }
})();
