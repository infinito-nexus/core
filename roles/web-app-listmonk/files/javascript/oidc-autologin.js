// nocheck: mirrored-unit-test - a self-executing IIFE that submits the first /auth/oidc
// form it finds; it exports nothing, so there is no unit to call
(function () {
  function go() {
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
