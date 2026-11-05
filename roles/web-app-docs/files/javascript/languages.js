(function () {
  function pageUrl(version, code, page) {
    const prefix = code === "en" ? `/${version}` : `/${version}/${code}`;
    return page ? `${prefix}/${page}.html` : `${prefix}/`;
  }

  async function fill(select) {
    const { version, language, page } = select.dataset;
    const response = await fetch(`/api/languages/${encodeURIComponent(version)}`);
    if (!response.ok) {
      return;
    }
    const { languages } = await response.json();
    select.replaceChildren(
      ...languages.map((entry) => {
        const option = document.createElement("option");
        option.value = pageUrl(version, entry.code, page);
        option.textContent = entry.native;
        option.lang = entry.code;
        option.selected = entry.code === language;
        return option;
      }),
    );
    select.addEventListener("change", () => {
      window.location.href = select.value;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".docs-language-switcher").forEach(fill);
  });
})();
