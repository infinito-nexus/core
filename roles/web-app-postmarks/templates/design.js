(function () {
  function brandIcon() {
    const icons = document.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon']");
    for (let index = 0; index < icons.length; index += 1) {
      const wanted = icons[index].rel === "apple-touch-icon" ? INFINITO_DESIGN.urls['apple-touch-icon'].png : INFINITO_DESIGN.urls.favicon_ico;
      if (icons[index].getAttribute("href") !== wanted) {
        icons[index].setAttribute("href", wanted);
      }
    }
  }
  const title = INFINITO_DESIGN.title;
  function brandTitle() {
    const parts = document.title.split(" | ");
    if (parts.length > 1 && parts[parts.length - 1] !== title) {
      parts[parts.length - 1] = title;
      document.title = parts.join(" | ");
    }
    const name = document.querySelector(".header .logo a, .header .title h1 a");
    if (name) {
      for (let node = name.firstChild; node; node = node.nextSibling) {
        if (node.nodeType === 3 && node.nodeValue.trim() && node.nodeValue.trim() !== title) {
          node.nodeValue = ` ${  title  } `;
        }
      }
    }
  }
  function apply() {
  if (INFINITO_DESIGN.logo) {
      brandIcon();
  }
  if (INFINITO_DESIGN.title) {
      brandTitle();
  }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", apply);
  } else {
    apply();
  }
})();
