const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, performKeycloakLogin, readEnv, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");

const ENDPOINT_FIELD = "#id_s_aiprovider_openai_action_generate_text_endpoint";
const USER_MENU = ".usermenu, [data-region='user-menu-toggle'], a[href*='profile.php']";
const GATEWAY_PROMPT = "Reply with the single word: pong";

/**
 * Open an authenticated site-administrator session.
 *
 * `tasks/04_oidc.yml` rewrites `mdl_user.auth` to `oidc` for every account but
 * `guest`, and `auth_oidc` grants a login only when the request carries an
 * authorization code, so with the sso service enabled no password reaches the
 * account through the native form. Without sso that task never runs, the
 * accounts stay on `auth_manual` and the password `install_database.php`
 * provisioned is the only way in.
 *
 * @param {import('@playwright/test').Page} page browser page to authenticate
 * @param {object} shared role-shared env and persona helpers
 */
async function loginAsSiteAdmin(page, shared) {
  if (shared.env.ssoEnabled) {
    await gotoOnion(page, `${shared.env.moodleBaseUrl}/auth/oidc/?source=loginpage`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await performKeycloakLogin(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      readEnv("CANONICAL_DOMAIN"),
    );
  } else {
    expect(
      adminNativePassword,
      "ADMIN_NATIVE_PASSWORD must be rendered from credentials.user_password; with the sso service off it is the only secret that authenticates the Moodle site administrator",
    ).toBeTruthy();

    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await page
      .locator("input[name='username'], input#username")
      .first()
      .fill(shared.env.adminUsername);

    const passwordInput = page
      .locator(
        ".toggle-sensitive-wrapper input[name='password'], .toggle-sensitive-wrapper input#password, input[name='password']",
      )
      .first();
    await expect(
      passwordInput,
      "the native Moodle login form must expose a password field; its absence means the login page no longer serves the manual auth form",
    ).toBeAttached({ timeout: resolveTimeout(30_000) });
    await expect(async () => {
      await passwordInput.fill(adminNativePassword);
      await expect(passwordInput).toHaveValue(adminNativePassword);
    }).toPass({ timeout: resolveTimeout(30_000) });

    await page.locator("#loginbtn, button[type='submit'], input[type='submit']").first().click();
    await page.waitForLoadState("load");
  }

  await expect(
    page.locator(USER_MENU).first(),
    "the site administrator must reach an authenticated session; a failure here means the auth chain the deploy configured does not admit the administrator account",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

exports.register = function (shared) {
  test("litellm: Moodle answers a prompt through the in-cluster gateway", async ({ page }) => {
    skipUnlessServiceEnabled("litellm");
    test.setTimeout(resolveTimeout(240_000));

    await loginAsSiteAdmin(page, shared);

    await gotoOnion(
      page,
      `${shared.env.moodleBaseUrl}/admin/settings.php?section=aiprovider_openai_generate_text`,
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) },
    );

    const endpointField = page.locator(ENDPOINT_FIELD);
    await expect(
      endpointField,
      "the aiprovider_openai generate_text settings page must render its API endpoint field; its absence means the provider was never configured or the session lacks moodle/site:config",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const configuredEndpoint = ((await endpointField.inputValue()) || "").trim();
    expect(
      configuredEndpoint,
      "aiprovider_openai/action_generate_text_endpoint must be an http(s) URL written by the deploy, not the upstream api.openai.com default",
    ).toMatch(/^https?:\/\/.+/i);

    const endpointHost = new URL(configuredEndpoint).hostname;
    expect(
      endpointHost,
      `the generate_text endpoint host must be a bare in-cluster service name; the dotted host "${endpointHost}" gets completed by the container dns-search suffix and resolves through the public ingress, so the prompt would leave the deployment`,
    ).not.toContain(".");
    expect(
      endpointHost,
      "the generate_text endpoint must address the svc-ai-litellm gateway, not point back at Moodle itself",
    ).not.toBe(new URL(shared.env.moodleBaseUrl).hostname);

    const bootstrap = await page.evaluate(() => ({
      sesskey: (window.M && window.M.cfg && window.M.cfg.sesskey) || "",
      contextid: (window.M && window.M.cfg && window.M.cfg.contextid) || 0,
    }));
    expect(
      bootstrap.sesskey,
      "M.cfg.sesskey must be exposed on the admin page; without it Moodle rejects every /lib/ajax/service.php call",
    ).toBeTruthy();
    expect(
      bootstrap.contextid,
      "M.cfg.contextid must be exposed so the AI placement runs in the context the admin page already validated",
    ).toBeGreaterThan(0);

    const ajaxUrl =
      `${shared.env.moodleBaseUrl}/lib/ajax/service.php` +
      `?sesskey=${encodeURIComponent(bootstrap.sesskey)}&info=aiplacement_editor_generate_text`;
    const response = await page.request.post(ajaxUrl, {
      headers: { "Content-Type": "application/json" },
      data: [
        {
          index: 0,
          methodname: "aiplacement_editor_generate_text",
          args: { contextid: bootstrap.contextid, prompttext: GATEWAY_PROMPT },
        },
      ],
      timeout: resolveTimeout(180_000),
    });

    expect(
      response.status(),
      `the aiplacement_editor web service must answer 200; a non-200 means the placement is disabled or unavailable, so no AI surface reaches the provider (got ${response.status()})`,
    ).toBe(200);

    const payload = await response.json();
    const entry = Array.isArray(payload) ? payload[0] : null;
    expect(
      entry,
      `aiplacement_editor_generate_text must return exactly one result entry, got ${JSON.stringify(payload).slice(0, 400)}`,
    ).toBeTruthy();
    expect(
      entry.error,
      `the placement call must not raise a Moodle exception, got ${JSON.stringify(entry.exception || entry).slice(0, 400)}`,
    ).toBe(false);

    const result = entry.data;
    expect(
      result.success,
      `the generate_text action must succeed; errorcode carries the gateway HTTP status, so 401 means the virtual key is wrong and 404 or 0 means the endpoint is unreachable (got ${JSON.stringify(result).slice(0, 400)})`,
    ).toBe(true);
    expect(
      String(result.generatedcontent || "").trim().length,
      "the gateway must return a non-empty completion, proving Moodle's AI placement had the prompt answered inside the deployment",
    ).toBeGreaterThan(0);
  });
};
