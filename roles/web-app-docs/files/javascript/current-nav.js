document.addEventListener("DOMContentLoaded", function () {
  function markAsCurrent(link) {
    let li = link.closest("li");
    while (li) {
      li.classList.add("current");
      if (li.__x && li.__x.$data) {
        li.__x.$data.expanded = true;
      }
      li = li.parentElement.closest("li");
    }
  }

  function openCurrentSubmenus() {
    document.querySelectorAll(".current-index li.current").forEach(function (li) {
      li.querySelectorAll(":scope > [x-show]").forEach(function (elem) {
        if (elem.style.display === "none" || elem.style.display === "") {
          elem.style.display = "block";
        }
      });
    });
  }

  function processNav() {
    const currentHash = window.location.hash.trim();
    if (!currentHash) {
      return;
    }

    document.querySelectorAll(".current-index a.reference.internal").forEach(function (link) {
      const href = (link.getAttribute("href") || "").trim();
      if (href.startsWith("#")) {
        if (href === currentHash) {
          document
            .querySelectorAll(".current-index a.reference.internal.current")
            .forEach(function (active) {
              active.classList.remove("current");
            });
          link.classList.add("current");
          markAsCurrent(link);
        }
      } else if (href.includes("#") && `#${href.split("#")[1].trim()}` === currentHash) {
        markAsCurrent(link);
      }
    });

    openCurrentSubmenus();
  }

  function initCurrentNav() {
    if (window.Alpine && typeof window.Alpine.nextTick === "function") {
      window.Alpine.nextTick(processNav);
    } else {
      processNav();
    }
  }

  window.addEventListener("load", initCurrentNav);
  window.addEventListener("hashchange", initCurrentNav);
  window.initCurrentNav = initCurrentNav;
});
