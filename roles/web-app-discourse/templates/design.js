(function () {
  const root = document.documentElement;

  function mirror() {
    const light = document.querySelector("link.light-scheme");
    const dark = document.querySelector("link.dark-scheme");
    let mode = null;
    if (dark) {
      if (dark.media === "all") mode = "dark";
      else if (dark.media === "none") mode = "light";
    } else if (light) {
      const meta = document.querySelector('meta[name="color-scheme"]');
      mode = meta && meta.content.trim() === "dark" ? "dark" : "light";
    }
    if (mode) root.setAttribute("data-design-theme", mode);
    else root.removeAttribute("data-design-theme");
  }

  function watch() {
    mirror();
    const links = document.querySelectorAll("link.light-scheme, link.dark-scheme");
    const observer = new MutationObserver(mirror);
    for (let i = 0; i < links.length; i += 1) {
      observer.observe(links[i], { attributes: true, attributeFilter: ["media"] });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch);
  else watch();
})();
