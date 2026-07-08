const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { runAdminFlow, gotoOnion } = require("../personas");

// pretix-oidc is Pretix's OIDC SSO plugin. It is pip-installed at image-build
// time and activated purely through environment: the role appends
// pretix_oidc.auth.OIDCAuthBackend to PRETIX_PRETIX_AUTH_BACKENDS and renders
// every PRETIX_OIDC_* endpoint/client variable, which the plugin reads from the
// [oidc] config section at runtime. The backend's authentication_url() builds a
// login link whose href is the partner Keycloak authorization endpoint itself,
// carrying the configured client_id and the pretix oidc/callback redirect_uri.
//
// We therefore verify FULL coupling (not a generic page load): the OIDC login
// affordance on /control/login must resolve to the Keycloak openid-connect
// authorization endpoint AND carry the configured OAuth client_id + the pretix
// oidc callback redirect. If the addon were not wired (backend not registered,
// or issuer/client_id not loaded), no such link exists and this fails.
test.use({ ignoreHTTPSErrors: true });

test("addon pretix-oidc: login affordance routes to the Keycloak authorization endpoint with the OAuth client", async ({ page }) => {
  skipUnlessAddonEnabled("pretix-oidc");
  skipUnlessServiceEnabled("sso");

  const appBaseUrl = (process.env.APP_BASE_URL || "").replace(/\/$/, "");
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/control/login`, { waitUntil: "domcontentloaded" }).catch(() => {});

  // The pretix-oidc backend renders a login link whose href is the full Keycloak
  // authorization URL (openid-connect/auth?client_id=...&redirect_uri=.../oidc/callback...).
  // Pretix's always-on NativeAuthBackend would satisfy a generic "log in" match,
  // so we assert ONLY this OIDC-specific, partner-coupled affordance.
  const oidcLink = page
    .locator("a[href*='openid-connect/auth' i], a[href*='oidc' i], a[href*='openid' i]")
    .or(page.getByRole("link", { name: /sso|openid|keycloak|single\s*sign/i }))
    .first();

  await expect(
    oidcLink,
    "Pretix /control/login must expose the pretix-oidc login affordance once the OIDC auth backend is active",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  // Resolve the actual destination. authentication_url() points the link straight
  // at the OIDC authorization endpoint, so the href itself is the coupling proof.
  let target = await oidcLink.getAttribute("href").catch(() => null);
  if (!target || !/openid-connect\/auth/i.test(target)) {
    // Some pretix themes route the affordance through an internal start URL that
    // 302s to the IdP. Follow the click and read the resulting Keycloak URL.
    await Promise.all([
      page.waitForURL(/openid-connect\/auth/i, { timeout: resolveTimeout(30_000) }).catch(() => {}),
      oidcLink.click().catch(() => {}),
    ]);
    target = page.url();
  }

  expect(
    target,
    "OIDC login affordance must resolve to the Keycloak openid-connect authorization endpoint",
  ).toMatch(/openid-connect\/auth/i);

  const authUrl = new URL(target);
  expect(
    (authUrl.searchParams.get("client_id") || "").length,
    "Keycloak authorization request from Pretix must carry the configured OAuth client_id",
  ).toBeGreaterThan(0);

  const redirectUri = authUrl.searchParams.get("redirect_uri") || "";
  expect(
    /oidc\/callback/i.test(redirectUri),
    `Authorization request redirect_uri must point back at the pretix OIDC callback (got: ${redirectUri || "<none>"})`,
  ).toBe(true);
});

test("addon pretix-oidc: administrator OIDC login round-trip succeeds", async ({ page }) => {
  skipUnlessAddonEnabled("pretix-oidc");
  skipUnlessServiceEnabled("sso");

  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage
        .getByRole("link", { name: /^(events|orders|control|admin)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage
          .waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) })
          .catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /event|order|ticket|control|pretix/i,
          { timeout: resolveTimeout(30_000) }
        );
      }
    },
  });
});
