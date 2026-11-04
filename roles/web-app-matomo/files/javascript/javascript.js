(function () {
  function hideNativeLogin() {
    if (new URLSearchParams(window.location.search).get("fallback") === "local") {
      return;
    }
    const field = document.getElementById("login_form_login");
    const form = field ? field.closest("form") : null;
    if (form) {
      form.style.setProperty("display", "none", "important");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hideNativeLogin, { once: true });
  } else {
    hideNativeLogin();
  }
})();
