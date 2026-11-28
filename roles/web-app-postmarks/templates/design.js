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
  function apply() {
  if (INFINITO_DESIGN.logo) {
      brandIcon();
  }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", apply);
  } else {
    apply();
  }
})();
