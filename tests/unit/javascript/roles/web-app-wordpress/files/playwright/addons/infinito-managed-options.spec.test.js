const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-wordpress/files/playwright/addons/infinito-managed-options.spec.js");
const BASE_URL = `https://blog.${DOMAIN}`;
const MANAGED = `administrator@${DOMAIN}`;
const MAIN_SITE_ID = "1";
const SITE_SETTINGS = `${BASE_URL}/wp-admin/network/site-settings.php?id=${MAIN_SITE_ID}`;
const EDIT_SITE_NONCE = "edit-site-nonce";
const NETWORK_SETTINGS = [
  "date_format",
  "default_category",
  "default_comment_status",
  "default_ping_status",
  "default_post_format",
  "description",
  "language",
  "page_for_posts",
  "page_on_front",
  "posts_per_page",
  "show_on_front",
  "site_icon",
  "site_logo",
  "start_of_week",
  "time_format",
  "timezone",
  "title",
  "use_smilies",
];

function expect(value, message) {
  return {
    toBeTruthy: () => assert.ok(value, message),
    toBe: (wanted) => assert.equal(value, wanted, message),
    not: { toContain: (needle) => assert.ok(!String(value).includes(needle), message) },
  };
}

function reply(body, { status = 200, url = "" } = {}) {
  return {
    ok: () => status < 400,
    url: () => url,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

/**
 * Args:
 *   multisite: true for a network, whose register_initial_settings() puts no admin_email into the REST settings
 *     and whose network/site-settings.php writes option[admin_email] of a site with update_option().
 *   guarded: false when a write of the admin email reaches the stored admin_email.
 *   leaking: true when the values file serves its PHP source.
 *   stored: the admin_email WordPress stores before the probe.
 *   refusing: true when network/site-settings.php rejects the edit-site nonce.
 */
function wordpress({ multisite, guarded = true, leaking = false, stored = MANAGED, refusing = false }) {
  const options = { admin_email: stored };
  const keep = (wanted) => {
    if (!guarded) options.admin_email = wanted;
  };
  const settings = () => ({
    ...Object.fromEntries(NETWORK_SETTINGS.map((key) => [key, null])),
    ...(multisite ? {} : { email: options.admin_email, url: BASE_URL }),
  });
  const screens = {
    [`${BASE_URL}/wp-admin/options-general.php #new_admin_email`]: () => options.admin_email,
  };
  if (multisite) {
    Object.assign(screens, {
      [`${BASE_URL}/wp-admin/network/sites.php #the-list tr:not(:has(input[name="allblogs[]"])) a.edit`]: () => [
        `${BASE_URL}/wp-admin/network/site-info.php?id=${MAIN_SITE_ID}`,
        `${BASE_URL}/wp-admin/`,
      ],
      [`${SITE_SETTINGS} #admin_email`]: () => options.admin_email,
      [`${SITE_SETTINGS} form[action*="action=update-site"] input[name="_wpnonce"]`]: () => EDIT_SITE_NONCE,
    });
  }
  let shown = "";
  const rendered = (selector) => {
    const field = screens[`${shown} ${selector}`];
    if (!field) throw new Error(`${shown} renders no ${selector}`);
    return [].concat(field());
  };
  const strict = (selector) => {
    const matches = rendered(selector);
    if (matches.length !== 1) {
      throw new Error(`strict mode violation: ${selector} resolved to ${matches.length} elements`);
    }
    return matches[0];
  };
  const element = (selector, pick) => ({
    inputValue: async () => pick(selector),
    getAttribute: async (name) => {
      assert.equal(name, "href");
      return pick(selector);
    },
  });
  return {
    goto: async (url) => {
      shown = url;
    },
    url: () => shown,
    locator: (selector) => ({
      ...element(selector, strict),
      first: () => element(selector, (picked) => rendered(picked)[0]),
    }),
    request: {
      get: async (url) => {
        if (url === `${BASE_URL}/wp-admin/admin-ajax.php?action=rest-nonce`) return reply("nonce\n");
        if (url === `${BASE_URL}/wp-json/wp/v2/settings`) return reply(settings());
        if (url === `${BASE_URL}/wp-content/infinito-managed-options.php`) {
          return reply(leaking ? `<?php return ['option' => ['admin_email' => '${options.admin_email}']];` : "");
        }
        throw new Error(`unexpected GET ${url}`);
      },
      post: async (url, { data, form }) => {
        if (url === `${BASE_URL}/wp-json/wp/v2/settings`) {
          if (!multisite && "email" in data) keep(data.email);
          return reply(settings());
        }
        if (multisite && url === `${SITE_SETTINGS}&action=update-site`) {
          if (refusing || form._wpnonce !== EDIT_SITE_NONCE) return reply("The link you followed has expired.", { status: 403, url });
          keep(form["option[admin_email]"]);
          return reply("", { url: `${BASE_URL}/wp-admin/network/site-settings.php?update=updated&id=${MAIN_SITE_ID}` });
        }
        throw new Error(`unexpected POST ${url}`);
      },
    },
  };
}

/**
 * Args:
 *   page: the page the body drives.
 *   multisiteEnabled: the WORDPRESS_MULTISITE_ENABLED the spec reads.
 */
async function probe(page, multisiteEnabled) {
  const bodies = [];
  const playwrightTest = Object.assign((title, body) => bodies.push(body), {
    use: () => undefined,
    setTimeout: () => undefined,
  });
  loadInternals(
    SPEC,
    [],
    {
      "@playwright/test": { test: playwrightTest, expect },
      "../addon-gating": { skipUnlessAddonEnabled: () => undefined },
      "../timeouts": { resolveTimeout: (ms) => ms },
      "../personas": { gotoOnion: (target, url, options) => target.goto(url, options) },
      "../_shared": {
        env: { wpBaseUrl: BASE_URL, multisiteEnabled, adminEmail: MANAGED },
        wpAdminLogin: async () => undefined,
      },
    },
    { URL },
  );
  assert.equal(bodies.length, 1);
  await bodies[0]({ page });
}

test("the probe passes on a single site whose guard keeps the admin email", async () => {
  await probe(wordpress({ multisite: false }), false);
});

test("the probe passes on a network whose guard keeps the admin email", async () => {
  await probe(wordpress({ multisite: true }), true);
});

test("the probe fails on a single site without the guard", async () => {
  await assert.rejects(
    probe(wordpress({ multisite: false, guarded: false }), false),
    /the guard MUST keep the managed admin email against a REST write/,
  );
});

test("the probe fails on a network without the guard", async () => {
  await assert.rejects(
    probe(wordpress({ multisite: true, guarded: false }), true),
    /the stored admin email MUST stay the managed one/,
  );
});

test("the probe fails on a network that never applies the write", async () => {
  await assert.rejects(
    probe(wordpress({ multisite: true, refusing: true }), true),
    /the network MUST accept the write of the main site's options/,
  );
});

test("the probe fails on either install when the stored admin email is not the deployed one", async () => {
  for (const multisite of [false, true]) {
    await assert.rejects(
      probe(wordpress({ multisite, stored: `someone-else@${DOMAIN}` }), multisite),
      /the platform administrator's email as its managed admin email/,
    );
  }
});

test("the probe fails on either install when the values file serves the admin email", async () => {
  for (const multisite of [false, true]) {
    await assert.rejects(
      probe(wordpress({ multisite, leaking: true }), multisite),
      /MUST serve none of its values over HTTP/,
    );
  }
});
