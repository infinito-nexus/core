const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  expectHstsWhenTls,
  ownResponseHeaders,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Mobilizon front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Mobilizon response").toBeTruthy();
  expect(response.status(), "Expected Mobilizon front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Mobilizon URL`
  ).toBe(true);
  expectHstsWhenTls(await ownResponseHeaders(response), appBaseUrl, "Mobilizon");
});

test("Mobilizon returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Mobilizon front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

async function loggedUserRole(page) {
  await expect
    .poll(() => page.evaluate(() => Boolean(window.localStorage.getItem("auth-access-token"))), {
      timeout: resolveTimeout(30_000),
      message: "Mobilizon MUST store the access token of the signed-in account",
    })
    .toBe(true);
  return page.evaluate(async () => {
    const response = await fetch("/api", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${window.localStorage.getItem("auth-access-token")}`,
      },
      body: JSON.stringify({ query: "{ loggedUser { role } }" }),
    });
    const body = await response.json();
    return body?.data?.loggedUser?.role ?? null;
  });
}

test("biber: app → user role → universal logout", async ({ page }) => {
  await runBiberFlow(page, {
    biberInteraction: async (interactivePage) => {
      expect(
        await loggedUserRole(interactivePage),
        "biber holds no role group, so the deploy MUST keep the Mobilizon user role",
      ).toBe("USER");
    },
  });
});

test("administrator: app → administrator role → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      expect(
        await loggedUserRole(interactivePage),
        "the administrator persona MUST hold the Mobilizon administrator role",
      ).toBe("ADMINISTRATOR");
    },
  });
});

require("./test-design");
