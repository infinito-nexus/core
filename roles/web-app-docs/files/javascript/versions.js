(function () {
  const LABELS = {
    ready: "ready",
    missing: "not built yet",
    queued: "queued",
    building: "building",
    failed: "failed",
  };
  const POLL_MS = 2000;

  function versionUrl(name, page) {
    return page ? `/${name}/${page}.html` : `/${name}/`;
  }

  function describe(version) {
    const label = LABELS[version.state];
    return version.phase && version.state !== "ready" ? `${label}: ${version.phase}` : label;
  }

  function optionLabel(version) {
    return version.built ? version.name : `${version.name} (${LABELS[version.state]})`;
  }

  function fillSwitcher(select, versions) {
    const { current, page } = select.dataset;
    select.replaceChildren(
      ...versions.map((version) => {
        const option = document.createElement("option");
        option.value = versionUrl(version.name, page);
        option.textContent = optionLabel(version);
        option.selected = version.name === current;
        return option;
      }),
    );
  }

  function fillOverview(tbody, versions) {
    tbody.replaceChildren(
      ...versions.map((version) => {
        const link = document.createElement("a");
        link.href = versionUrl(version.name);
        link.textContent = version.name;
        const bar = document.createElement("progress");
        bar.max = 100;
        bar.value = version.progress;
        const row = document.createElement("tr");
        [link, document.createTextNode(describe(version)), bar].forEach((child) => {
          const cell = document.createElement("td");
          cell.append(child);
          row.append(cell);
        });
        return row;
      }),
    );
  }

  function followBuild(section, versions) {
    const version = versions.find((candidate) => candidate.name === section.dataset.build);
    if (!version) {
      return;
    }
    if (version.built) {
      window.location.reload();
      return;
    }
    section.querySelector("progress").value = version.progress;
    section.querySelector("[data-phase]").textContent = describe(version);
    section.querySelector("pre").textContent = version.log.join("\n");
  }

  async function refresh() {
    const response = await fetch("/api/versions", { cache: "no-store" });
    const versions = await response.json();
    document.querySelectorAll("select.docs-version-switcher").forEach((select) => fillSwitcher(select, versions));
    document.querySelectorAll("tbody[data-versions]").forEach((tbody) => fillOverview(tbody, versions));
    document.querySelectorAll("section[data-build]").forEach((section) => followBuild(section, versions));
  }

  function start() {
    document.querySelectorAll("select.docs-version-switcher").forEach((select) => {
      select.addEventListener("change", () => {
        window.location.href = select.value;
      });
    });
    refresh();
    if (document.querySelector("tbody[data-versions], section[data-build]")) {
      window.setInterval(refresh, POLL_MS);
    }
  }

  window.docsVersions = { versionUrl, describe, optionLabel, fillSwitcher, fillOverview, followBuild, refresh };
  document.addEventListener("DOMContentLoaded", start);
})();
