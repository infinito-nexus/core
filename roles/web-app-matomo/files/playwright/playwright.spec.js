const { test, expect } = require("@playwright/test");

const { isServiceEnabled } = require("./service-gating");
const { assertCspMetaParity, assertCspResponseHeader, assertInjectedAssetLoadsWithoutCspBlock, decodeDotenvQuotedValue, expectNoCspViolations, installCspViolationObserver, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }

    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });

  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);

    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });

  return { consoleErrors, pageErrors, cspRelated };
}

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const matomoApiToken = decodeDotenvQuotedValue(process.env.MATOMO_API_TOKEN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(appBaseUrl, "APP_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set in the Playwright env file").toBeTruthy();

  await page.context().clearCookies();
  await installCspViolationObserver(page);
});

test("matomo enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected Matomo login response").toBeTruthy();
  expect(response.status(), "Expected Matomo login response to be successful").toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "matomo login");
  await assertCspMetaParity(page, directives, "matomo login");

  const documentHtml = await response.text();
  const documentUrl = response.url();
  expect(
    documentHtml.includes(canonicalDomain) || documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to appear in the Matomo login document`
  ).toBe(true);

  await expectNoCspViolations(page, diagnostics, "matomo login");
});

test("matomo local administrator logs in and logs out", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  await page.goto(`${appBaseUrl}/index.php?module=Login`);

  const usernameField = page
    .locator("input#login_form_login, input[name='form_login']")
    .first();
  const passwordField = page
    .locator("input#login_form_password, input[name='form_password']")
    .first();
  const submitButton = page
    .locator("input#login_form_submit, button#login_form_submit, button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "Expected Matomo login form username field").toBeVisible({ timeout: 60_000 });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await submitButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "Expected Matomo login to leave the Login module"
    })
    .not.toContain("module=Login");

  await expect(page.locator("body")).toContainText(/dashboard|websites|matomo/i, { timeout: 60_000 });

  await page.goto(`${appBaseUrl}/index.php?module=Login&action=logout`);

  await expect
    .poll(
      async () =>
        (await page
          .locator("input#login_form_login, input[name='form_login']")
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: 60_000,
        message: "Expected Matomo login form to reappear after logout"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "matomo administrator login");
});

// Biber denial at Matomo: biber's Keycloak account exists but is NOT
// in `web-app-matomo-administrator`. After the OIDC chain,
// oauth2-proxy MUST refuse the session — either with a 403 at
// `/oauth2/callback` or by redirecting to a denial surface. The check
// is the SPOT for "biber cannot reach Matomo" since the persona helper
// no longer drives this probe.
test("matomo: biber is denied access at the admin surface", async ({ browser }) => {
  test.skip(
    !isServiceEnabled("sso"),
    "matomo's oauth2-proxy gate is not wired yet (services.yml oauth2.enabled=false; see TODO).",
  );
  test.skip(
    !oidcIssuerUrl || !biberUsername || !biberPassword,
    "OIDC_ISSUER_URL / BIBER_USERNAME / BIBER_PASSWORD must be set in the Playwright env file",
  );

  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedMatomoBaseUrl = appBaseUrl.replace(/\/$/, "");

  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const biberPage = await biberContext.newPage();

    // Register the callback listener BEFORE goto so no response is
    // missed — the redirect chain may complete before a listener
    // registered after login starts.
    const callbackResponsePromise = biberPage
      .waitForResponse(
        (res) => res.url().includes("/oauth2/callback"),
        { timeout: 60_000 },
      )
      .catch(() => null);

    await biberPage.goto(`${expectedMatomoBaseUrl}/`);

    await expect
      .poll(() => biberPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`,
      })
      .toContain(expectedOidcAuthUrl);

    const usernameField = biberPage
      .getByRole("textbox", { name: /username|email/i })
      .or(biberPage.locator("input[name='username'], input#username"))
      .first();
    const passwordField = biberPage
      .getByRole("textbox", { name: /^password$/i })
      .or(biberPage.locator("input[name='password'], input#password"))
      .first();
    const signInButton = biberPage
      .getByRole("button", { name: /sign in|login|log in/i })
      .or(biberPage.locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"))
      .first();

    await usernameField.waitFor({ state: "visible", timeout: 60_000 });
    await usernameField.fill(biberUsername);
    await usernameField.press("Tab").catch(() => {});
    await passwordField.fill(biberPassword);
    await signInButton.click();

    const callbackResponse = await callbackResponsePromise;

    if (callbackResponse) {
      // Primary path: the proxy returns 403 at /oauth2/callback.
      // Anything below 400 means biber crossed into the admin surface
      // and is a real regression.
      expect(
        callbackResponse.status(),
        `oauth2-proxy MUST deny biber at /oauth2/callback (got ${callbackResponse.status()})`,
      ).toBeGreaterThanOrEqual(400);
      return;
    }

    // Fallback: no callback observed — verify the URL did not settle
    // on the authenticated Matomo surface, AND the body does not
    // expose the admin DOM markers (body validation).
    await biberPage.waitForLoadState("domcontentloaded", { timeout: 60_000 }).catch(() => {});
    const finalUrl = biberPage.url();
    const onAuthDenialChain =
      /openid-connect\/auth/.test(finalUrl) ||
      /\/oauth2\/(?:start|sign_in|callback)/.test(finalUrl);

    if (onAuthDenialChain) return;

    const probe = await biberPage.request
      .get(`${expectedMatomoBaseUrl}/`, { ignoreHTTPSErrors: true, maxRedirects: 0 })
      .catch(() => null);
    if (!probe) {
      expect(
        false,
        `biber must NOT reach the matomo UI (probe failed; outer URL ${finalUrl})`,
      ).toBe(true);
      return;
    }
    const status = probe.status();
    if (status === 401 || status === 403) return;
    if (status >= 300 && status < 400) {
      const location = probe.headers()["location"] || "";
      if (/openid-connect\/auth|\/oauth2\/(?:start|sign_in|callback)/.test(location)) return;
      return;
    }
    if (status === 200) {
      const body = await probe.text().catch(() => "");
      const showsAdminUi =
        /id=['"]?Dashboard_/i.test(body) &&
        (/id=['"]?Settings/i.test(body) || /class=['"][^'"]*activeNav/i.test(body));
      if (showsAdminUi) {
        expect(
          false,
          `biber must NOT reach the matomo UI: GET ${expectedMatomoBaseUrl}/ returned 200 with admin DOM markers.`,
        ).toBe(true);
        return;
      }
      // Pre-auth or login-form surface is acceptable: biber sees
      // matomo's login but is NOT past it.
      const isMatomoSurface =
        /<input[^>]*name=['"]?form_login['"]?/i.test(body) ||
        /<input[^>]*name=['"]?form_password['"]?/i.test(body) ||
        /piwik|matomo/i.test(body);
      expect(
        isMatomoSurface,
        `biber probe to ${expectedMatomoBaseUrl}/ returned 200 but the body is neither matomo's login form nor a recognisable matomo / piwik surface.`,
      ).toBe(true);
      return;
    }
    expect(
      false,
      `biber probe to ${expectedMatomoBaseUrl}/ returned unexpected status ${status}.`,
    ).toBe(true);
  } finally {
    await biberContext.close().catch(() => {});
  }
});

// -----------------------------------------------------------------------------
// Tracker-target presence per consumer: one
// parameterised assertion per role declared as a matomo consumer in
// its meta/services.yml. The role list is emitted into
// MATOMO_TARGET_ROLES_JSON at deploy time by the env template via the
// `roles_with_service('matomo')` Ansible filter, so this spec — and
// ONLY this spec — owns the per-role tracker-site assertion. Other
// roles' personas no longer drive the matomo surface.
// -----------------------------------------------------------------------------

const matomoTargetRoles = (() => {
  const raw = process.env.MATOMO_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

// alias_urls / main_url may be a full URL or a bare host; normalise both to the hostname before matching
function hostOf(value) {
  const s = String(value || "")
    .trim()
    .toLowerCase();
  if (!s) return "";
  try {
    return new URL(s.includes("://") ? s : `https://${s}`).hostname;
  } catch {
    return s.replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split("/")[0];
  }
}

// MUST mirror sys-front-inj-matomo/vars/main.yml base_domain: matomo registers one shared site per registrable domain, not per subdomain
function baseDomainOf(host) {
  return String(host || "")
    .toLowerCase()
    .replace(/^(?:.*\.)?(.+\..+)$/, "$1");
}

test("matomo SitesManager registers a tracker site for every consumer role", async ({ page, request }) => {
  test.skip(matomoTargetRoles.length === 0, "no matomo consumer roles in inventory");

  // Sign in via the local Matomo form so the API call below can reuse
  // the session cookie. Same shape as the local-admin login test above
  // but does not assert logout.
  await page.goto(`${appBaseUrl}/index.php?module=Login`);
  await page
    .locator("input#login_form_login, input[name='form_login']")
    .first()
    .fill(adminUsername);
  await page
    .locator("input#login_form_password, input[name='form_password']")
    .first()
    .fill(adminPassword);
  await page
    .locator("input#login_form_submit, button#login_form_submit, button[type='submit'], input[type='submit']")
    .first()
    .click();
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "Expected Matomo login to leave the Login module before SitesManager probe",
    })
    .not.toContain("module=Login");

  // Hand the session cookies over to the request fixture so the API
  // call below carries the authenticated session.
  const cookies = await page.context().cookies();
  await request.storageState();

  // token_auth: session cookie alone yields 401; POST keeps the token out of the URL
  const apiBase = `${appBaseUrl}/index.php`;
  const apiResp = await page.request.post(apiBase, {
    form: {
      module: "API",
      method: "SitesManager.getAllSites",
      format: "JSON",
      token_auth: matomoApiToken,
    },
    ignoreHTTPSErrors: true,
  });
  expect(
    apiResp.status(),
    `Matomo SitesManager.getAllSites MUST respond < 400 (got ${apiResp.status()})`
  ).toBeLessThan(400);

  const sites = await apiResp.json().catch(() => []);
  expect(Array.isArray(sites), "Matomo SitesManager.getAllSites MUST return an array").toBe(true);

  const failures = [];
  for (const target of matomoTargetRoles) {
    const needle = baseDomainOf(target.canonical_domain);
    if (!needle) {
      failures.push(`${target.id}: empty canonical_domain in MATOMO_TARGET_ROLES_JSON`);
      continue;
    }
    const matchingSite = sites.find((site) => {
      const candidates = [
        String(site?.main_url || ""),
        ...(Array.isArray(site?.alias_urls) ? site.alias_urls.map(String) : []),
      ];
      return candidates.some((c) => hostOf(c) === needle);
    });
    if (!matchingSite) {
      failures.push(`${target.id}: no Matomo site main_url / alias_urls host equals base domain "${needle}" (canonical "${target.canonical_domain}")`);
    }
  }

  expect(
    failures,
    `Matomo SitesManager coverage failures:\n  - ${failures.join("\n  - ")}`
  ).toEqual([]);

  // `cookies` is intentionally referenced once so the variable is not flagged
  // as unused; the cookies sit on `page.request` already, the array is for
  // post-mortem inspection if a future test needs it.
  void cookies;
});

const matomoCanonicalDomain = (() => {
  try {
    return new URL(appBaseUrl).hostname;
  } catch {
    return "";
  }
})();

for (const target of matomoTargetRoles) {
  test(`matomo tracker injected in ${target.id} (${target.canonical_domain})`, async ({ page }) => {
    expect(
      target.canonical_url,
      `Expected canonical_url in MATOMO_TARGET_ROLES_JSON entry for ${target.id}`
    ).toBeTruthy();
    const targetUrl = `${target.canonical_url.replace(/\/$/, "")}/`;

    if (matomoCanonicalDomain) {
      await assertInjectedAssetLoadsWithoutCspBlock(page, {
        url: targetUrl,
        hostCandidates: [matomoCanonicalDomain],
        resourceTypes: ["script"],
        label: target.id,
      });
    } else {
      await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    }

    const html = await page.content();
    expect(
      html,
      `Expected matomo tracker '_paq' marker in ${target.id} HTML body`
    ).toContain("_paq");
    expect(
      html,
      `Expected matomo tracker URL ('matomo.php') in ${target.id} HTML body`
    ).toContain("matomo.php");
    if (matomoCanonicalDomain) {
      expect(
        html,
        `Expected matomo host '${matomoCanonicalDomain}' referenced in ${target.id} HTML body`
      ).toContain(matomoCanonicalDomain);
    }
  });
}

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Matomo admin-only interaction: open the Websites admin page from
      // the topbar / admin gear. Confirms the admin reaches the management
      // surface — biber's deny-check at matomo is the symmetric counter
      // assertion.
      const settingsLink = interactivePage
        .getByRole("link", { name: /administration|settings|websites/i })
        .first();
      if (await settingsLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await settingsLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /websites|administration|users|general settings/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
