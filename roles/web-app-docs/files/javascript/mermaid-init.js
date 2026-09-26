(function () {
  if (typeof window.mermaid === "undefined") {
    return;
  }
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  window.mermaid.initialize({
    startOnLoad: true,
    securityLevel: "strict",
    theme: dark ? "dark" : "default",
  });
})();
