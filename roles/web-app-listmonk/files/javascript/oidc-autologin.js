// nocheck: mirrored-unit-test - a self-executing IIFE that hides the password form and submits
// the first /auth/oidc form it finds; it exports nothing, so there is no unit to call
(function () {
  function go() {
    document.querySelectorAll('form[action$="/admin/login"], a[href$="/admin/forgot"]').forEach(function (entry) {
      entry.style.setProperty("display", "none", "important");
    });
    if (document.querySelector(".error")) return;
    const forms = document.forms;
    for (let i = 0; i < forms.length; i++) {
      if (forms[i].action.indexOf("/auth/oidc") > -1) {
        forms[i].submit();
        return;
      }
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", go);
  } else {
    go();
  }
})();
