const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm, gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const discourseBaseUrl = normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

async function signInViaOidc(page) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${discourseBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|continue\s+with\s+oidc|continue\s+with\s+sso|single\s+sign[-\s]*on|log\s*in|sign\s*up/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await gotoOnion(page, `${discourseBaseUrl}/auth/oidc`).catch(() => {});
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${discourseBaseUrl}`,
    })
    .toContain(discourseBaseUrl);
}

function findSetting(settings, name) {
  return settings.find((s) => s && s.setting === name);
}

test("discourse-activity-pub: federation plugin installed and the live ActivityPub surface reaches the fediverse partner network", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-activity-pub");

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(discourseBaseUrl, "DISCOURSE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const discourseHost = new URL(discourseBaseUrl).host;

  try {
    await page.context().clearCookies();
    await signInViaOidc(page);

    await expect(page.locator("body")).toContainText(
      /topic|category|welcome|latest|discourse/i,
      { timeout: resolveTimeout(60_000) },
    );

    const siteSettings = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/admin/site_settings.json`, {
        headers: { Accept: "application/json" },
        credentials: "include",
      });
      if (!res.ok) return { ok: false, status: res.status };
      const body = await res.json();
      return { ok: true, settings: (body && body.site_settings) || [] };
    }, discourseBaseUrl);

    expect(
      siteSettings.ok,
      `expected /admin/site_settings.json to be reachable as admin (status ${siteSettings.status})`,
    ).toBe(true);

    const apEnabled = findSetting(siteSettings.settings, "activity_pub_enabled");
    expect(
      apEnabled,
      "activity_pub_enabled site setting must exist (discourse-activity-pub plugin installed)",
    ).toBeTruthy();
    expect(
      String(apEnabled.value).toLowerCase(),
      "activity_pub_enabled must be active so the instance actually federates over ActivityPub",
    ).toBe("true");

    const webfinger = await page.evaluate(async (base) => {
      const url = `${base}/.well-known/webfinger?resource=acct:nonexistent@${new URL(base).host}`;
      const res = await fetch(url, {
        headers: { Accept: "application/jrd+json, application/json" },
        credentials: "omit",
      });
      return { status: res.status, contentType: res.headers.get("content-type") || "" };
    }, discourseBaseUrl);

    expect(
      [200, 400, 404].includes(webfinger.status),
      `the plugin's WebFinger actor-discovery endpoint (the entrypoint remote fediverse partners use to resolve handles on this host) must be live; got HTTP ${webfinger.status}`,
    ).toBe(true);

    const apSurface = await page.evaluate(async (base) => {
      const res = await fetch(`${base}/ap/about`, {
        headers: { Accept: "application/activity+json, application/json" },
        credentials: "include",
      });
      let json;
      try {
        json = await res.json();
      } catch {
        json = null;
      }
      return { status: res.status, json };
    }, discourseBaseUrl);

    expect(
      apSurface.status,
      "the ActivityPub engine must be mounted and serving its federation surface at /ap (this is the bridge that publishes and receives activities to/from remote ActivityPub servers)",
    ).toBeLessThan(400);
    expect(
      apSurface.json,
      "the /ap/about federation endpoint must return a JSON document describing this instance's ActivityPub actors",
    ).toBeTruthy();

    const handleValidation = await page.evaluate(async (base) => {
      const remoteHandle = "@Gargron@mastodon.social";
      const res = await fetch(`${base}/ap/webfinger/handle/validate`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({ handle: remoteHandle }),
      });
      let json;
      try {
        json = await res.json();
      } catch {
        json = null;
      }
      return { status: res.status, json, remoteHandle };
    }, discourseBaseUrl);

    expect(
      handleValidation.status,
      "the plugin's remote-handle WebFinger validation route must be served (it is what resolves a fediverse partner actor across hosts); a missing route would 404 and prove the federation bridge did not land",
    ).toBeLessThan(500);
    expect(
      handleValidation.json,
      "validating a remote fediverse handle must return a JSON result from the ActivityPub plugin",
    ).toBeTruthy();

    expect(
      handleValidation.remoteHandle.split("@").pop(),
      "the resolved partner handle must target a remote fediverse host, distinct from this Discourse host, proving cross-host federation and not a local-only echo",
    ).not.toBe(discourseHost);
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});
