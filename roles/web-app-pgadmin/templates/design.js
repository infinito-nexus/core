(function () {
  const root = document.documentElement;
  function mirror(theme) {
    if (theme === "light" || theme === "dark") {
      root.setAttribute("data-design-theme", theme);
    } else {
      root.removeAttribute("data-design-theme");
    }
    if (theme === "high_contrast") {
      root.setAttribute("data-pgadmin-theme", theme);
    } else {
      root.removeAttribute("data-pgadmin-theme");
    }
  }
  function picked(message) {
    const data = message && message.data;
    if (!data || typeof data !== "object") {
      return;
    }
    const entries = Array.isArray(data) ? data : Object.keys(data).map(function (key) { return data[key]; });
    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index];
      if (entry && entry.module === "misc" && entry.name === "theme") {
        mirror(entry.value);
        return;
      }
    }
  }
  if (typeof window.theme === "string") {
    mirror(window.theme);
  }
  document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.theme === "string") {
      mirror(window.theme);
    }
  });
  if (typeof window.BroadcastChannel === "function") {
    const channel = new window.BroadcastChannel("preference-change");
    channel.onmessage = function (event) {
      picked(event.data);
    };
    channel.postMessage("sync");
  }
  if (INFINITO_DESIGN.logo) {
    const favicon = INFINITO_DESIGN.urls.favicon_ico;
    function brandIcon() {
      const icons = document.querySelectorAll("link[rel~='icon']");
      for (let index = 0; index < icons.length; index += 1) {
        if (icons[index].getAttribute("href") !== favicon) {
          icons[index].setAttribute("type", "image/x-icon");
          icons[index].setAttribute("href", favicon);
        }
      }
    }
    new MutationObserver(brandIcon).observe(document.head, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
    brandIcon();
  }
})();
