(function () {
  const title = INFINITO_DESIGN.title;
  function brandTitle() {
    const current = document.title;
    if (current.indexOf(title) !== -1) {
      return;
    }
    document.title = /(^|\s-\s)Jenkins$/.test(current) ? current.replace(/Jenkins$/, title) : current;
    const name = document.querySelector(".app-jenkins-logo span");
    if (name && name.textContent.trim() === "Jenkins") {
      name.textContent = title;
    }
  }
  function brandIcon() {
    const icons = document.querySelectorAll("link[rel~='icon'], link[rel='apple-touch-icon'], link[rel='mask-icon']");
    for (let index = 0; index < icons.length; index += 1) {
      const icon = icons[index];
      const target = icon.rel === "apple-touch-icon" ? INFINITO_DESIGN.urls['apple-touch-icon'].png : INFINITO_DESIGN.urls.favicon_ico;
      if (icon.rel === "mask-icon") {
        icon.remove();
      } else if (icon.getAttribute("href") !== target) {
        icon.setAttribute("type", icon.rel === "apple-touch-icon" ? "image/png" : "image/x-icon");
        icon.setAttribute("href", target);
      }
    }
  }
  function brand() {
  if (INFINITO_DESIGN.title) {
      brandTitle();
  }
  if (INFINITO_DESIGN.logo) {
      brandIcon();
  }
  }
  brand();
  document.addEventListener("DOMContentLoaded", brand);
})();
