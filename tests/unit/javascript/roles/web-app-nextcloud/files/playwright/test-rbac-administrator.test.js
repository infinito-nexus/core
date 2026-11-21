const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-nextcloud/files/playwright/test-rbac-administrator.js");
const HREF_SELECTOR = /^a\[href\*="([^"]+)"\]$/;

const ACCOUNT_MENU_ADMIN_ENTRY = {
  id: "admin_settings",
  href: "/settings/admin/overview",
  containers: ["#header", "#user-menu"],
  visible: false,
};
const NAVIGATION_PERSONAL_LINK = {
  href: "/settings/user/personal-info",
  containers: ["#content", "#app-navigation-vue"],
  visible: true,
};
const NAVIGATION_ADMIN_LINK = {
  href: "/settings/admin/overview",
  containers: ["#content", "#app-navigation-vue"],
  visible: true,
};

/**
 * Args:
 *   elements: the elements in scope, each with its href, the ids of its containers and its visibility.
 *
 * Returns:
 *   An object whose `locator` narrows to the elements an `a[href*="..."]` selector matches or to
 *   those inside a `#id` container, and whose `first` returns the first element in scope.
 */
function scope(elements) {
  return {
    locator(selector) {
      const href = HREF_SELECTOR.exec(selector);
      return scope(
        href
          ? elements.filter((element) => element.href.includes(href[1]))
          : elements.filter((element) => element.containers.includes(selector)),
      );
    },
    first: () => elements[0],
  };
}

const { adminSettingsNavigationLink } = loadInternals(SPEC, ["adminSettingsNavigationLink"], {}, { URL });

test("the administration link is the settings navigation's, not the closed account menu's hidden entry before it", () => {
  const link = adminSettingsNavigationLink(
    scope([ACCOUNT_MENU_ADMIN_ENTRY, NAVIGATION_PERSONAL_LINK, NAVIGATION_ADMIN_LINK]),
  );

  assert.equal(link, NAVIGATION_ADMIN_LINK);
  assert.equal(link.visible, true);
});

test("a settings navigation without an administration section resolves no link, whatever the account menu holds", () => {
  assert.equal(
    adminSettingsNavigationLink(scope([ACCOUNT_MENU_ADMIN_ENTRY, NAVIGATION_PERSONAL_LINK])),
    undefined,
  );
});
