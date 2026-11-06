(function () {
  const root = document.documentElement;
  if (!root.hasAttribute("data-color-scheme-os") && !root.hasAttribute("data-color-scheme")) {
    return;
  }
  function mark(element) {
    const scheme = root.getAttribute("data-color-scheme");
    if (scheme === "dark" || scheme === "light") {
      element.setAttribute("data-design-theme", scheme);
    } else {
      element.removeAttribute("data-design-theme");
    }
  }
  function editor(frame) {
    const inner = frame.contentDocument;
    if (inner && inner.documentElement) {
      mark(inner.documentElement);
    }
  }
  function mirror() {
    mark(root);
    Array.prototype.forEach.call(document.querySelectorAll("iframe.tox-edit-area__iframe"), editor);
  }
  mirror();
  new MutationObserver(mirror).observe(root, { attributes: true, attributeFilter: ["data-color-scheme"] });
  document.addEventListener(
    "load",
    function (event) {
      if (event.target && event.target.matches && event.target.matches("iframe.tox-edit-area__iframe")) {
        editor(event.target);
      }
    },
    true
  );
})();
