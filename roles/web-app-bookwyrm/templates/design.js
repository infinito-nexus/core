(function () {
  const link = document.querySelector('link[rel="stylesheet"][href*="/css/themes/"]');
  const href = link ? link.getAttribute("href") : "";
  const root = document.documentElement;
  if (href.indexOf("/css/themes/bookwyrm-dark") !== -1) {
    root.setAttribute("data-design-theme", "dark");
  } else if (href.indexOf("/css/themes/bookwyrm-light") !== -1) {
    root.setAttribute("data-design-theme", "light");
  } else {
    root.removeAttribute("data-design-theme");
  }
})();
