(function () {
  // Auto-redirect Pi-hole's 403 page to /admin/
  if (document.querySelector('p') && document.body.innerText.includes("your Pi-hole")) {
    window.location.replace("/admin/");
    return;
  }

  // Inject logout button into Pi-hole admin navbar
  function injectLogoutButton() {
    if (document.getElementById("oauth2-logout-btn")) return;
    var navbar = document.querySelector(".navbar-custom-menu .navbar-nav");
    if (!navbar) return;
    var li = document.createElement("li");
    var a = document.createElement("a");
    a.id = "oauth2-logout-btn";
    a.href = "/oauth2/sign_out";
    a.title = "Logout";
    a.style.cursor = "pointer";
    a.innerHTML = '<i class="fa fa-sign-out"></i> Logout';
    li.appendChild(a);
    navbar.appendChild(li);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectLogoutButton, { once: true });
  } else {
    injectLogoutButton();
  }

  new MutationObserver(injectLogoutButton).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
