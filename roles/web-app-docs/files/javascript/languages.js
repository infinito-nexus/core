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
    const urls = languages.map((entry) => pageUrl(version, entry.code, page));
    select.replaceChildren(
      ...languages.map((entry, index) => {
        const option = document.createElement("option");
        option.value = urls[index];
        option.textContent = entry.native;
        option.lang = entry.code;
        option.selected = entry.code === language;
        return option;
      }),
    );
    select.addEventListener("change", () => {
      window.location.href = urls[select.selectedIndex];
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".docs-language-switcher").forEach(fill);
  });
})();
