// nocheck: mirrored-unit-test - a DOMContentLoaded handler that toggles Bootstrap
// submenus; pure presentation with no exported function and no branch worth pinning
document.addEventListener('DOMContentLoaded', function () {
  // Toggle second-level menus on click
  const submenuTriggers = document.querySelectorAll('.dropdown-submenu > a.dropdown-toggle');

  submenuTriggers.forEach(function (trigger) {
    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();

      const submenu = this.nextElementSibling;
      if (!submenu) return;

      // Close other open submenus on the same level
      const parentMenu = this.closest('.dropdown-menu');
      if (parentMenu) {
        parentMenu.querySelectorAll('.dropdown-menu.show').forEach(function (menu) {
          if (menu !== submenu) {
            menu.classList.remove('show');
          }
        });
      }

      submenu.classList.toggle('show');
    });
  });

  // When the main Apps dropdown closes, close all submenus
  document.querySelectorAll('.navbar .dropdown').forEach(function (dropdown) {
    dropdown.addEventListener('hide.bs.dropdown', function () {
      this.querySelectorAll('.dropdown-menu.show').forEach(function (menu) {
        menu.classList.remove('show');
      });
    });
  });
});
