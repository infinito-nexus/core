(function () {
  const root = document.documentElement;
  const theme = root.getAttribute("data-theme") || "";
  if (/dark/.test(theme)) {
    root.setAttribute("data-design-theme", "dark");
  } else if (/light/.test(theme)) {
    root.setAttribute("data-design-theme", "light");
  }
})();
